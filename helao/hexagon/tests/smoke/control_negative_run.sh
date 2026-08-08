#!/usr/bin/env bash
# P7g gate: launch the controlneg sim group, drive all five private /control
# routes, assert the run tree is unchanged, kill the group.
# Exit code = driver exit (0 PASS, 1 assert fail, 2 error).
# MAIN SESSION ONLY (subagent background launches get reaped on idle).
#
# Usage: control_negative_run.sh [config_prefix] [root]
set -u
PREFIX="${1:-controlneg}"
REPO="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$REPO" || exit 2
# One interpreter spelling for every call. `conda run --no-capture-output` is
# the default for the same reason conc_run.sh needs it: conda's capture buffer
# can fill during a verbose startup and stall launch.py before it writes the
# pid pickle, leaving a half-up group. HELAO_PY overrides it with a direct
# env python where one is on hand (faster, and no capture layer at all).
PY="${HELAO_PY:-conda run --no-capture-output -n helao python}"
ROOT="${2:-$($PY -c "
from helao.helpers.config_loader import read_config
print(read_config('$PREFIX')['root'])" | tail -1)}"
LAUNCHLOG="/tmp/p7g_${PREFIX}.launch.log"

echo "[control_negative] wiping fresh root $ROOT"
rm -rf "$ROOT"

echo "[control_negative] launching $PREFIX (log: $LAUNCHLOG)"
nohup $PY launch.py "$PREFIX" --no-hot-reload > "$LAUNCHLOG" 2>&1 &
LAUNCH_PID=$!

# Probe with curl only -- one tiny process per poll. Spawning `conda run
# python` every 2 s during startup starves the group badly enough that
# launch.py tears it down. The IO sim is what this check actually drives, and
# action servers launch before the orchestrator (LAUNCH_ORDER), so probing it
# is both sufficient and the earliest honest signal.
echo "[control_negative] waiting for IOSIM HTTP to serve (/get_digital_outs)"
READY=0
for i in $(seq 1 90); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
    --max-time 3 "http://127.0.0.1:8072/get_digital_outs" 2>/dev/null || echo 000)
  if [ "$code" = "200" ]; then READY=1; break; fi
  sleep 2
done
if [ "$READY" -ne 1 ]; then
  echo "[control_negative] FAIL IOSIM never became ready; launch tail:"; tail -40 "$LAUNCHLOG"
  $PY helao/hexagon/tests/smoke/kill_group.py "$ROOT" "$PREFIX"
  kill "$LAUNCH_PID" 2>/dev/null; exit 2
fi
sleep 3  # small settle after readiness

echo "[control_negative] driving all five control routes"
$PY -m helao.hexagon.tests.smoke.control_negative_check \
  --prefix "$PREFIX" --seed-tree
RC=$?

echo "[control_negative] killing group"
$PY helao/hexagon/tests/smoke/kill_group.py "$ROOT" "$PREFIX"
kill "$LAUNCH_PID" 2>/dev/null
if [ "$RC" -ne 0 ]; then
  echo "[control_negative] FAIL rc=$RC; launch tail:"; tail -60 "$LAUNCHLOG"
fi
exit $RC
