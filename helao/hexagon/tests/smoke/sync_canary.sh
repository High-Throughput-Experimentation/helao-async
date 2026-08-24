#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Linux canary for the synchex hexagon cut-over: runtime /openapi.json diff.
# Bash port of sample_canary.sh's conventions for a SOFTWARE openapi-surface
# canary -- sync_server wraps driver_classes=[HelaoSyncer]
# (helao/core/drivers/data/sync_driver.py:2059) and exposes ONLY private/bare
# endpoints (/finish_yml, /list_pending, /n_queue, /current_progress, ...);
# there is no `/{server_key}/{action}` action endpoint and no data-producing
# action, so a runtime RUNS-tree golden diff is N/A for this server -- the
# openapi surface diff (this script) is the topology-appropriate parity
# check. See sync.yml's header comment for the aws_bucket/AWS_CONFIG_PATH
# gate investigation that makes the syncer launchable on Linux without real AWS.
#
# Launches the LEGACY dbpack group and the HEXAGON synchex group in turn,
# dumps each syncer server's live /openapi.json, and diffs them. An identical
# route/schema surface proves the hexagon makeActionApp factory produces a
# byte-parity action server for this cut-over target.
#
# Both configs share root /tmp/INST_hlo_sync and port 8010, so they MUST
# run sequentially (this script does that) -- never launch both at once.
#
# Usage: sync_canary.sh [root] [outdir]
#   root   default /tmp/INST_hlo_sync    (must match the configs' root: key)
#   outdir default /tmp/synchex_canary
# ---------------------------------------------------------------------------
set -u

ROOT="${1:-/tmp/INST_hlo_sync}"
OUTDIR="${2:-/tmp/synchex_canary}"

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
LEGACY_JSON="$OUTDIR/sync_openapi.json"
HEX_JSON="$OUTDIR/synchex_openapi.json"

# ---------------------------------------------------------------------------
kill_one() {
  # $1 = config prefix
  local prefix="$1"
  # 0) graceful shutdown first so the driver's shutdown() lifecycle runs
  # cleanly (HelaoSyncer holds no hardware handle, but this matches every
  # other canary's kill sequence).
  conda run -n helao python "$SCRIPT_DIR/graceful_shutdown.py" 8010
  sleep 2
  # 1) kill the action/vis servers via their pid pickle (any that didn't exit).
  conda run -n helao python "$SCRIPT_DIR/kill_group.py" "$ROOT" "$prefix"
  # 2) kill the launch.py monitor for THIS prefix by matching its command
  # line -- precise, so it can never hit this shell. The trailing
  # ".yml" ensures prefix "dbpack" cannot match "synchex" ("sync.yml" is a distinct filename, so no collision).
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
  # serve requests until the startup event -- HelaoSyncer init + dyn
  # endpoints -- completes, so a socket-only wait races startup (connection
  # refused). Retrying the fetch both waits for readiness and captures.
  echo "[canary] waiting for SYNC /openapi.json to serve, then fetching -> $outjson"
  local up=0
  for i in $(seq 1 90); do
    if conda run -n helao python -c "
import urllib.request, sys
open(sys.argv[1], 'wb').write(
    urllib.request.urlopen('http://127.0.0.1:8010/openapi.json', timeout=10).read()
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
run_one sync "$LEGACY_JSON" || { echo "[canary] ABORTED -- see logs in $OUTDIR"; exit 2; }
run_one synchex "$HEX_JSON" || { echo "[canary] ABORTED -- see logs in $OUTDIR"; exit 2; }

echo
echo "[canary] diffing openapi surfaces"
conda run -n helao python "$SCRIPT_DIR/openapi_diff.py" "$LEGACY_JSON" "$HEX_JSON" \
  > "$OUTDIR/openapi_diff.txt" 2>&1
DIFF_RC=$?
cat "$OUTDIR/openapi_diff.txt"

echo
if [ "$DIFF_RC" -eq 0 ]; then
  echo "[canary] PASS -- synchex openapi surface matches legacy dbpack" > "$OUTDIR/canary_result.txt"
else
  echo "[canary] DIFFS FOUND rc=$DIFF_RC -- see openapi_diff.txt" > "$OUTDIR/canary_result.txt"
fi
cat "$OUTDIR/canary_result.txt"
echo "[canary] artifacts + result saved in: $OUTDIR"
exit "$DIFF_RC"
