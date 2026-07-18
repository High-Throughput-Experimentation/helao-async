#!/usr/bin/env bash
# Launch a HELAO group, capture one golden scenario, kill it, and diff the
# captured tree against a legacy golden. Exit code = harness.parity exit code
# (0 PASS, 1 diffs, 2 harness error). Used by the P1b2a parity gate.
#
# Usage: parity_run.sh <scenario> <config_prefix> <root> <golden_dir> <candidate_dir>
set -u
SCEN="$1"; PREFIX="$2"; ROOT="$3"; GOLDEN="$4"; CAND="$5"
REPO="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$REPO" || exit 2
LAUNCHLOG="/tmp/p1b2a_${PREFIX}_${SCEN}.launch.log"

echo "[parity_run] wiping fresh root $ROOT"
rm -rf "$ROOT"
rm -rf "$CAND"

echo "[parity_run] launching $PREFIX (log: $LAUNCHLOG)"
nohup conda run -n helao python launch.py "$PREFIX" --no-hot-reload > "$LAUNCHLOG" 2>&1 &
LAUNCH_PID=$!

echo "[parity_run] waiting for ports 8001/8002/8010"
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
  echo "[parity_run] FAIL ports never came up; launch tail:"; tail -40 "$LAUNCHLOG"
  conda run -n helao python helao/hexagon/tests/smoke/kill_group.py "$ROOT" "$PREFIX"
  kill "$LAUNCH_PID" 2>/dev/null; exit 2
fi
sleep 5  # settle: orch loop parked, action servers registered

echo "[parity_run] capturing $SCEN -> $CAND"
conda run -n helao python -m harness.capture \
  --scenario "$SCEN" --root "$ROOT" --out "$CAND" --config-prefix "$PREFIX"
CAP_RC=$?

echo "[parity_run] killing group"
conda run -n helao python helao/hexagon/tests/smoke/kill_group.py "$ROOT" "$PREFIX"
kill "$LAUNCH_PID" 2>/dev/null
if [ "$CAP_RC" -ne 0 ]; then
  echo "[parity_run] FAIL capture rc=$CAP_RC; launch tail:"; tail -40 "$LAUNCHLOG"; exit 2
fi

echo "[parity_run] parity: golden=$GOLDEN candidate=$CAND"
conda run -n helao python -m harness.parity \
  --golden "$GOLDEN" --candidate "$CAND" --report "${CAND}/parity-report.json"
exit $?
