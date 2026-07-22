#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Linux canary for the samplehex hexagon cut-over: runtime /openapi.json diff.
# Bash port of gamryhex_canary.bat's conventions for the FOURTH hardware
# canary but the FIRST fully-Linux-runnable one -- sample_server wraps
# driver_classes=[Archive], a pure SOFTWARE sample-DB / tray-position manager
# with NO hardware dependency, so (unlike gamryhex_canary.bat) this canary
# needs no attached device of any kind to even start the servers.
#
# Launches the LEGACY sample group and the HEXAGON samplehex group in turn,
# dumps each SAMPLE server's live /openapi.json, and diffs them. An identical
# route/schema surface proves the hexagon makeActionApp factory produces a
# byte-parity action server for this cut-over target.
#
# Why NOT parity_run.sh / harness.capture: that harness is hardcoded to the
# golden SIM group topology (orch@8001, sim@8002, db@8010) and dispatches
# sequences to an orchestrator. sample/samplehex is a 1-server group
# (SAMPLE@8008) with NO orchestrator, so the GM-* scenarios cannot drive it
# via that harness -- the openapi diff is the topology-appropriate parity
# check (see sample_diff.sh for the runtime get_loaded_positions golden diff,
# the topology-appropriate DATA check).
#
# Both configs share root /tmp/INST_hlo_sample and port 8008, so they MUST
# run sequentially (this script does that) -- never launch both at once.
#
# Usage: sample_canary.sh [root] [outdir]
#   root   default /tmp/INST_hlo_sample   (must match the configs' root: key)
#   outdir default /tmp/samplehex_canary
# ---------------------------------------------------------------------------
set -u

ROOT="${1:-/tmp/INST_hlo_sample}"
OUTDIR="${2:-/tmp/samplehex_canary}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
cd "$REPO" || exit 2

# Guard: refuse an unsafe root (drive/fs anchor, or a root that contains the
# code repo) BEFORE anything touches it. safe_root.py is the single choke
# point; $ROOT is only ever used read-only in this script (to locate the pid
# pickle for kill_group.py), but the check is defense in depth against a
# mis-set root: key.
conda run -n helao python "$SCRIPT_DIR/safe_root.py" check "$ROOT"
if [ $? -ne 0 ]; then
  echo "[canary] ABORT -- root $ROOT failed the safety guard; see message above"
  exit 2
fi

mkdir -p "$OUTDIR"
LEGACY_JSON="$OUTDIR/sample_openapi.json"
HEX_JSON="$OUTDIR/samplehex_openapi.json"

# ---------------------------------------------------------------------------
kill_one() {
  # $1 = config prefix
  local prefix="$1"
  # 0) graceful shutdown first so the driver's shutdown() lifecycle runs
  # cleanly (Archive holds no hardware handle, but this matches every other
  # canary's kill sequence).
  conda run -n helao python "$SCRIPT_DIR/graceful_shutdown.py" 8008
  sleep 2
  # 1) kill the action/vis servers via their pid pickle (any that didn't exit).
  conda run -n helao python "$SCRIPT_DIR/kill_group.py" "$ROOT" "$prefix"
  # 2) kill the launch.py monitor for THIS prefix by matching its command
  # line -- precise, so it can never hit this shell. The trailing
  # ".yml" ensures prefix "sample" cannot match "samplehex" ("sample.yml" is a distinct filename, so no collision).
  pkill -f "launch\\.py .*${prefix}\\.yml --no-hot-reload" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
run_one() {
  # $1 = config prefix, $2 = output json path
  local prefix="$1"
  local outjson="$2"
  local launchlog="$OUTDIR/${prefix}.launch.log"

  echo
  echo "[canary] === $prefix ==="
  # NEVER wipe $ROOT. An openapi diff reads the live server's /openapi.json
  # and produces no output tree, so no "fresh root" is needed. $ROOT is used
  # read-only here, only to locate the pid pickle for kill_group.py.
  echo "[canary] launching $prefix (log: $launchlog)"
  nohup conda run -n helao python launch.py "$SCRIPT_DIR/configs/${prefix}.yml" --no-hot-reload > "$launchlog" 2>&1 &
  local launch_pid=$!

  # Poll the actual /openapi.json fetch until it SERVES (not just until the
  # port is bound): helao servers bind the port early but uvicorn does not
  # serve requests until the startup event -- Archive/SQLite init + dyn
  # endpoints -- completes, so a socket-only wait races startup (connection
  # refused). Retrying the fetch both waits for readiness and captures.
  echo "[canary] waiting for SAMPLE /openapi.json to serve, then fetching -> $outjson"
  local up=0
  for i in $(seq 1 90); do
    if conda run -n helao python -c "
import urllib.request, sys
open(sys.argv[1], 'wb').write(
    urllib.request.urlopen('http://127.0.0.1:8008/openapi.json', timeout=10).read()
)
" "$outjson" 2>/dev/null
    then
      up=1
      break
    fi
    sleep 2
  done
  local fetch_rc=0
  if [ "$up" -ne 1 ]; then
    fetch_rc=1
    echo "[canary] FAIL $prefix /openapi.json never served; launch tail:"
    tail -40 "$launchlog"
  fi

  echo "[canary] killing $prefix"
  kill_one "$prefix"
  kill "$launch_pid" 2>/dev/null || true
  sleep 2

  if [ "$fetch_rc" -ne 0 ]; then
    echo "[canary] FAIL $prefix openapi fetch rc=$fetch_rc"
    return 2
  fi
  return 0
}

# ---------------------------------------------------------------------------
run_one sample "$LEGACY_JSON" || { echo "[canary] ABORTED -- see logs in $OUTDIR"; exit 2; }
run_one samplehex "$HEX_JSON" || { echo "[canary] ABORTED -- see logs in $OUTDIR"; exit 2; }

echo
echo "[canary] diffing openapi surfaces"
conda run -n helao python "$SCRIPT_DIR/openapi_diff.py" "$LEGACY_JSON" "$HEX_JSON" \
  > "$OUTDIR/openapi_diff.txt" 2>&1
DIFF_RC=$?
cat "$OUTDIR/openapi_diff.txt"

echo
if [ "$DIFF_RC" -eq 0 ]; then
  echo "[canary] PASS -- samplehex openapi surface matches legacy sample" > "$OUTDIR/canary_result.txt"
else
  echo "[canary] DIFFS FOUND rc=$DIFF_RC -- see openapi_diff.txt" > "$OUTDIR/canary_result.txt"
fi
cat "$OUTDIR/canary_result.txt"
echo "[canary] artifacts + result saved in: $OUTDIR"
exit "$DIFF_RC"
