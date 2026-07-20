#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Runtime golden-diff driver for the sample_server hexagon canary (P3a
# special-split). LINUX bash port of galil_diff.bat/golden_diff.bat's
# conventions for the FOURTH hardware canary but the FIRST fully-Linux-
# runnable one: sample_server wraps driver_classes=[Archive], a pure SOFTWARE
# sample-DB / tray-position manager -- NO hardware, NO COM/gclib, NO
# orchestrator. See golden_capture_sample.py's docstring for the full Step-0
# investigation.
#
# Launches samplegold (legacy) then samplegoldhex (hexagon), each against a
# FRESH throwaway root, drives one POST /SAMPLE/get_loaded_positions per
# launch via golden_capture_sample.py, snapshots the resulting RUNS tree, and
# diffs the two captures with harness.parity.
#
# Usage: sample_diff.sh [caproot] [outdir]
#   caproot default /tmp/INST_hlo_sample_golden -- a DEDICATED THROWAWAY
#            capture root, fully wiped before EACH capture (see
#            wipe_caproot). NEVER point this at /tmp/INST_hlo_sample (the
#            standalone canary root used by sample.yml/samplehex.yml) or any
#            root holding real data.
#   outdir  default /tmp/sample_golden -- capture sets + parity report land
#            here (outdir/sample, outdir/samplehex,
#            outdir/parity-report.json, outdir/golden_result.txt).
# ---------------------------------------------------------------------------
set -u

CAPROOT="${1:-/tmp/INST_hlo_sample_golden}"
OUTDIR="${2:-/tmp/sample_golden}"
NONGOLD_ROOT="/tmp/INST_hlo_sample"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
cd "$REPO" || exit 2

# Guard: refuse an unsafe caproot (drive/fs anchor, or a root that contains
# the code repo) BEFORE anything touches it. safe_root.py is the single
# choke point.
conda run -n helao python "$SCRIPT_DIR/safe_root.py" check "$CAPROOT"
if [ $? -ne 0 ]; then
  echo "[golden] ABORT -- caproot $CAPROOT failed the safety guard; see message above"
  exit 2
fi
if [ "$CAPROOT" = "$NONGOLD_ROOT" ]; then
  echo "[golden] ABORT -- caproot equals the non-throwaway sample root $NONGOLD_ROOT; refusing to run"
  exit 2
fi

mkdir -p "$OUTDIR"

# ---------------------------------------------------------------------------
wipe_caproot() {
  # Full-wipe the throwaway capture root before each capture -- required
  # because golden_capture_sample.py's assert_fresh() refuses a root that
  # already contains run artifacts. This rm -rf is safe ONLY because
  # $CAPROOT just passed safe_root.py's check (repo not underneath it, not a
  # drive/fs anchor) AND the equality guard below proves it is not the
  # non-throwaway sample root -- it must NEVER run against a root that could
  # hold real data.
  if [ "$CAPROOT" = "$NONGOLD_ROOT" ]; then
    echo "[golden] ABORT -- refusing to wipe non-throwaway root $NONGOLD_ROOT"
    return 2
  fi
  conda run -n helao python "$SCRIPT_DIR/safe_root.py" check "$CAPROOT"
  if [ $? -ne 0 ]; then
    echo "[golden] ABORT -- caproot $CAPROOT failed the safety guard before wipe"
    return 2
  fi
  if [ -e "$CAPROOT" ]; then
    echo "[golden] wiping throwaway caproot $CAPROOT"
    rm -rf "$CAPROOT"
  fi
  return 0
}

# ---------------------------------------------------------------------------
kill_one() {
  # $1 = config prefix
  local prefix="$1"
  # 0) graceful shutdown first so the driver's shutdown() lifecycle runs
  # cleanly (Archive holds no hardware handle, but this still matches every
  # other canary's kill sequence and lets any pending SQLite writes finish).
  conda run -n helao python "$SCRIPT_DIR/graceful_shutdown.py" 8008
  sleep 2
  # 1) kill the action/vis servers via their pid pickle (any that didn't exit).
  conda run -n helao python "$SCRIPT_DIR/kill_group.py" "$CAPROOT" "$prefix"
  # 2) kill the launch.py monitor for THIS prefix by matching its command
  # line -- precise, so it can never hit this shell. The trailing
  # " --no-hot-reload" ensures "samplegold" cannot match "samplegoldhex" (no
  # space follows "samplegold" in that cmdline).
  pkill -f "launch\\.py ${prefix} --no-hot-reload" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
run_one() {
  # $1 = config prefix, $2 = capture out dir
  local prefix="$1"
  local capout="$2"
  local launchlog="$OUTDIR/${prefix}.launch.log"

  echo
  echo "[golden] === $prefix ==="
  echo "[golden] launching $prefix (log: $launchlog)"
  nohup conda run -n helao python launch.py "$prefix" --no-hot-reload > "$launchlog" 2>&1 &
  local launch_pid=$!

  echo "[golden] waiting for SAMPLE port 8008"
  local up=0
  for i in $(seq 1 90); do
    if conda run -n helao python - <<'PY' 2>/dev/null
import socket, sys
sys.exit(0 if socket.socket().connect_ex(("127.0.0.1", 8008)) == 0 else 1)
PY
    then
      up=1
      break
    fi
    sleep 2
  done
  if [ "$up" -ne 1 ]; then
    echo "[golden] FAIL $prefix port 8008 never came up; launch tail:"
    tail -40 "$launchlog"
    kill_one "$prefix"
    kill "$launch_pid" 2>/dev/null || true
    return 2
  fi
  sleep 3  # settle: action server registered

  echo "[golden] capturing get_loaded_positions -> $capout"
  conda run -n helao python -m helao.hexagon.tests.smoke.golden_capture_sample \
    --config-prefix "$prefix" --root "$CAPROOT" --out "$capout" \
    > "$OUTDIR/${prefix}.capture.log" 2>&1
  local capture_rc=$?
  cat "$OUTDIR/${prefix}.capture.log"

  echo "[golden] killing $prefix"
  kill_one "$prefix"
  kill "$launch_pid" 2>/dev/null || true
  sleep 2

  if [ "$capture_rc" -ne 0 ]; then
    echo "[golden] FAIL $prefix capture rc=$capture_rc"
    return 2
  fi
  return 0
}

# ---------------------------------------------------------------------------
wipe_caproot || { echo "[golden] ABORTED -- see logs in $OUTDIR"; exit 2; }
run_one samplegold "$OUTDIR/sample" || { echo "[golden] ABORTED -- see logs in $OUTDIR"; exit 2; }
wipe_caproot || { echo "[golden] ABORTED -- see logs in $OUTDIR"; exit 2; }
run_one samplegoldhex "$OUTDIR/samplehex" || { echo "[golden] ABORTED -- see logs in $OUTDIR"; exit 2; }

echo
echo "[golden] running parity diff"
conda run -n helao python -m harness.parity \
  --golden "$OUTDIR/sample" --candidate "$OUTDIR/samplehex" \
  --report "$OUTDIR/parity-report.json" > "$OUTDIR/parity_stdout.txt" 2>&1
PARITY_RC=$?
cat "$OUTDIR/parity_stdout.txt"

echo
echo "[golden] full parity report (also saved to $OUTDIR/parity-report.json):"
cat "$OUTDIR/parity-report.json"

echo
# No masking is used for this scenario (fully deterministic, see
# golden_capture_sample.py) -- so parity rc=0 is a genuine PASS and rc!=0
# means a REAL hexagon-vs-legacy diff.
if [ "$PARITY_RC" -eq 0 ]; then
  {
    echo "[golden] PASS -- samplegoldhex RUNS-tree matches legacy samplegold (get_loaded_positions)"
    echo "[golden] artifacts: $OUTDIR/sample, $OUTDIR/samplehex, $OUTDIR/parity-report.json"
  } > "$OUTDIR/golden_result.txt"
else
  {
    echo "[golden] DIFFS FOUND rc=$PARITY_RC -- REAL regression, inspect the report"
    echo "[golden] open $OUTDIR/parity-report.json: tree_diffs / file_diffs list"
    echo "[golden]   every differing member and key -- nothing is masked for"
    echo "[golden]   this scenario, so anything shown here is a genuine"
    echo "[golden]   hexagon-vs-legacy difference."
    echo "[golden] artifacts: $OUTDIR/sample, $OUTDIR/samplehex, $OUTDIR/parity-report.json"
  } > "$OUTDIR/golden_result.txt"
fi
cat "$OUTDIR/golden_result.txt"
exit "$PARITY_RC"
