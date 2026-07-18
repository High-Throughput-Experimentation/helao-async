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
nohup conda run -n helao python launch.py "$PREFIX" --no-hot-reload > "$LAUNCHLOG" 2>&1 &
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
sleep 5  # settle: orch loop parked, action servers registered

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
