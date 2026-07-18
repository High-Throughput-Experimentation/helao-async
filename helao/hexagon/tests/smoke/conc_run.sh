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

# Wait for the orch to actually SERVE over HTTP. Probe ONLY with curl (one
# tiny process per poll) — do NOT spawn `conda run python` per iteration: each
# is a full interpreter + conda activation, and hammering it every 2s during
# the CPU-sensitive multi-server startup starves the group so badly that
# launch.py tears it down (observed: SIM shut down ~3s in and the orch never
# finished its SIM status-subscribe, so the driver's HTTP call was refused).
# We probe only the orch on 8001: action/DB servers launch before the
# orchestrator (LAUNCH_ORDER), so a serving orch implies they are up. The
# drivers reach the orch over HTTP (e.g. /append_sequence is not RPC-mirrored),
# and its uvicorn HTTP does not accept until the startup lifespan finishes
# (~30s SIM-subscribe backoff), so HTTP-200 is the right readiness signal.
echo "[conc_run] waiting for $ORCH_KEY HTTP to serve (/get_orch_state)"
READY=0
for i in $(seq 1 120); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
    -H 'Content-Type: application/json' --data '{}' \
    --max-time 3 "http://127.0.0.1:8001/get_orch_state" 2>/dev/null || echo 000)
  if [ "$code" = "200" ]; then READY=1; break; fi
  sleep 2
done
if [ "$READY" -ne 1 ]; then
  echo "[conc_run] FAIL $ORCH_KEY never became ready; launch tail:"; tail -40 "$LAUNCHLOG"
  conda run -n helao python helao/hexagon/tests/smoke/kill_group.py "$ROOT" "$PREFIX"
  kill "$LAUNCH_PID" 2>/dev/null; exit 2
fi
sleep 3  # small settle after readiness

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
