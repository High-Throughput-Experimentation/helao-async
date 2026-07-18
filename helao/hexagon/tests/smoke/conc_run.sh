#!/usr/bin/env bash
# Launch a HELAO group, run one §10.3 concurrency item driver, kill the
# group. Exit code = driver exit (0 PASS, 1 assert fail, 2 error).
# MAIN SESSION ONLY (subagent background launches get reaped on idle).
#
# Usage: conc_run.sh <item> <config_prefix> <root> [orch_key]
set -u
ITEM="$1"; PREFIX="$2"; ROOT="$3"; ORCH_KEY="${4:-ORCH}"
REPO="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$REPO" || exit 2
LAUNCHLOG="/tmp/p1b2b_${PREFIX}_${ITEM}.launch.log"

echo "[conc_run] wiping fresh root $ROOT"
rm -rf "$ROOT"

echo "[conc_run] launching $PREFIX (log: $LAUNCHLOG)"
# --no-capture-output: stream launch.py's stdout straight to the file. With
# conda's default output capture, a slow+verbose orch startup (e.g. the ~30s
# SIM status-subscribe backoff) can fill conda's capture buffer and stall
# launch.py before it writes STATES/pids_<prefix>_.pck, leaving a half-up
# group the driver can't reach.
nohup conda run --no-capture-output -n helao python launch.py "$PREFIX" --no-hot-reload > "$LAUNCHLOG" 2>&1 &
LAUNCH_PID=$!

echo "[conc_run] waiting for ports 8001/8002/8010"
UP=0
for i in $(seq 1 90); do
  if conda run -n helao python - <<'PY' 2>/dev/null
import socket, sys
ok = all(socket.socket().connect_ex(("127.0.0.1", p)) == 0 for p in (8001, 8002, 8010))
sys.exit(0 if ok else 1)
PY
  then UP=1; break; fi
  sleep 2
done
if [ "$UP" -ne 1 ]; then
  echo "[conc_run] FAIL ports never came up; launch tail:"; tail -40 "$LAUNCHLOG"
  conda run -n helao python helao/hexagon/tests/smoke/kill_group.py "$ROOT" "$PREFIX"
  kill "$LAUNCH_PID" 2>/dev/null; exit 2
fi
# Ports being open (socket bound by the launcher) is NOT the same as the orch
# app being ready to serve. The co-located ZMQ RPC mirror (18001) comes up
# early, but the uvicorn HTTP server (8001) does not accept until the orch's
# startup lifespan finishes — which can spend ~30s in a SIM status-subscribe
# backoff. The item drivers reach the orch over HTTP (e.g. /append_sequence,
# which is not RPC-mirrored), so poll the orch's real HTTP endpoint until it
# answers 200 (or give up after ~120s). RPC readiness alone races the driver.
echo "[conc_run] waiting for $ORCH_KEY HTTP to be serving (/get_orch_state)"
READY=0
for i in $(seq 1 60); do
  if conda run -n helao python - <<'PY' 2>/dev/null
import sys, requests
try:
    r = requests.post("http://127.0.0.1:8001/get_orch_state", json={}, timeout=3)
    sys.exit(0 if r.status_code == 200 else 1)
except Exception:
    sys.exit(1)
PY
  then READY=1; break; fi
  sleep 2
done
if [ "$READY" -ne 1 ]; then
  echo "[conc_run] FAIL $ORCH_KEY never became ready; launch tail:"; tail -40 "$LAUNCHLOG"
  conda run -n helao python helao/hexagon/tests/smoke/kill_group.py "$ROOT" "$PREFIX"
  kill "$LAUNCH_PID" 2>/dev/null; exit 2
fi
sleep 2  # small settle after readiness

echo "[conc_run] driving $ITEM"
conda run -n helao python -m helao.hexagon.tests.smoke.conc_items \
  --item "$ITEM" --root "$ROOT" --prefix "$PREFIX" --orch-key "$ORCH_KEY"
RC=$?

echo "[conc_run] killing group"
conda run -n helao python helao/hexagon/tests/smoke/kill_group.py "$ROOT" "$PREFIX"
kill "$LAUNCH_PID" 2>/dev/null
if [ "$RC" -ne 0 ]; then
  echo "[conc_run] FAIL rc=$RC; launch tail:"; tail -60 "$LAUNCHLOG"
fi
exit $RC
