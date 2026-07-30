"""Runtime golden-diff capture for the cam_server hexagon canary (P3a
special-split).

*** DRIVES THE REAL AXIS WEBCAM (fetches one live JPEG frame). ***

cam_server wraps ``AxisCam`` (helao/deploy/hte/drivers/sensor/axiscam_driver.py),
which pulls a JPEG over HTTP from the camera's ``/jpg/1/image.jpg`` endpoint.
``AxisCam.connect()`` opens no persistent connection, but ``acquire_image``
actually fetches a frame, so the camera must be REACHABLE at ``axis_ip`` for the
capture to produce data (the openapi canary needs no camera; this runtime diff
does).

``acquire_image`` (``POST /CAM/acquire_image``) with ``duration == 0`` runs a
ONE-SHOT executor (``AxisCamExec`` oneoff): it acquires exactly one frame,
writes it to disk as ``cam_000000_<%y%m%d.%H%M%S>.jpg``, ``track_file``-registers
it into ``-act.yml``'s ``files`` list, and streams a one-row ``.hlo`` whose body
columns are ``epoch_s`` (wall clock) and ``filename`` (the timestamped JPEG name).

This scenario has THREE run-to-run-volatile surfaces, ALL neutralized without
changing what the hexagon graft controls:
  1. the ``.jpg`` TREE PATH -- ``cam_NNNNNN_<ts>.jpg`` -- is normalized to
     ``cam_NNNNNN_TS.jpg`` by ``harness.classify.normalize_name``'s cam-frame
     grammar rule (RE_CAM_IMG), so both captures land the frame at the same
     normalized member (the counter is kept; only the wall clock collapses);
  2. the ``.jpg`` BYTES (a live frame) are content-masked ``"skip"`` (presence
     only) via the manifest's ``content_masked_files``;
  3. the ``.hlo`` body columns ``epoch_s``/``filename`` are value-masked via
     ``masked_hlo_columns`` (structure + the single-row count still asserted).
The ``-act.yml`` ``files[].file_name`` (the same ``cam_NNNNNN_<ts>.jpg``) is
handled structurally: ``harness.yaml_pass.normalize_meta`` routes ``file_name``
values through the same ``normalize_name`` grammar, so it matches on both sides
with NO masking (a real difference in any other -act.yml field still surfaces).

Standalone counterpart to ``harness.capture.snapshot_capture`` for the
orch-less, db-less cam/camhex 2-server topology (CAM@8013 + ACTVIS@5001 only),
mirroring spec/galil/gamry's golden_capture modules. The hardware-agnostic
settle / anti-vacuous-guard logic (``settle``, ``_run_artifacts``,
``_act_status_map``) and the production dispatch path (``dispatch_action``) are
IMPORTED from ``golden_capture.py``; only the scenario-specific pieces are new.

Usage (AT-STATION, Windows, conda env ``helao``) -- CAMERA REACHABLE AT axis_ip:

    rmdir /s /q C:\\INST_hlo_golden               (or pick a fresh --root)
    conda run -n helao python launch.py camgold --no-hot-reload
    conda run -n helao python -m helao.hexagon.tests.smoke.golden_capture_cam ^
        --config-prefix camgold --root C:\\INST_hlo_golden ^
        --out C:\\golden\\cam

then terminate the launch, point ``--root``/``--config-prefix`` at a FRESH
throwaway root and ``camgoldhex``, capture again, and diff the two capture
directories with ``harness.parity``. ``cam_diff.bat`` automates exactly this
sequence.
"""

from __future__ import annotations

import argparse
import datetime
import shutil
import subprocess
import sys
from pathlib import Path

from harness import HARNESS_VERSION
from harness.capture import assert_fresh, wait_for_server
from harness.manifest import ProvenanceManifest
from harness.treepass import PARITY_TOPS
from helao.hexagon.tests.smoke.golden_capture import (
    _act_status_map,
    _run_artifacts,
    dispatch_action,
    settle,
)

CAM_HOST, CAM_PORT = "127.0.0.1", 8013

SCENARIO = "GM-CAM"

# hte canary configs (P3a/P3e relocation) live alongside this module, in
# its own configs/ sibling directory -- no longer under helao/deploy/hte/.
CONFIG_DIR = Path(__file__).resolve().parent / "configs"

# AxisCamExec.write_image streams live_dict {"epoch_s": ..., "filename": ...} as
# the .hlo body: epoch_s is wall-clock, filename is the timestamped JPEG name --
# both volatile, so their VALUES are masked (column presence + the single-row
# count are still asserted). The .jpg TREE PATH + the -act.yml files[].file_name
# are handled structurally by normalize_name/normalize_meta (see module
# docstring), not here.
CAM_HLO_COLUMNS = ["epoch_s", "filename"]
CAM_MASKED_HLO_COLUMNS = {
    "*.hlo": CAM_HLO_COLUMNS,
    "*.hlo.json*": CAM_HLO_COLUMNS,
}
# One-shot (duration == 0) writes exactly ONE frame/row on both sides -- exact
# row-count match required (empty tolerance dict == 0).
CAM_HLO_ROW_COUNT_TOLERANCE: dict = {}
# The live JPEG frame differs every capture; compare PRESENCE only (its
# normalized path already matches via the RE_CAM_IMG grammar rule).
CAM_CONTENT_MASKED_FILES = {"*.jpg": "skip"}
# acquire_image writes no data-derived value into action_params; the only
# volatile -act.yml field (files[].file_name) is normalized structurally, not
# masked -> nothing to mask here.
CAM_ACT_YML_MASKED_META_KEYS: dict = {}


def acquire_image_action(
    config_prefix: str, duration: float = 0, acquisition_rate: float = 1
) -> dict:
    """Run /CAM/acquire_image via ``async_action_dispatcher`` (production
    action-dispatch path -- RPC then HTTP, full action envelope).

    ``duration == 0`` runs a ONE-SHOT executor: exactly one frame is fetched and
    written, then the action finishes. ``dispatch_action`` returns as soon as the
    executor is started (fire-and-forget); ``settle`` then waits for the -act.yml
    to reach a terminal status.
    """
    return dispatch_action(
        config_prefix,
        "CAM",
        "acquire_image",
        {"duration": duration, "acquisition_rate": acquisition_rate},
        timeout=60,
    )


def snapshot(
    root: Path,
    out_dir: Path,
    config_prefix: str,
    duration: float,
    acquisition_rate: float,
    notes: str = "",
) -> Path:
    """Copy PARITY_TOPS from ``root`` and write a provenance manifest.

    Refuses to overwrite an existing ``out_dir``, matching
    ``harness.capture.snapshot_capture`` / the other golden_capture modules.
    """
    root, out_dir = Path(root), Path(out_dir)
    if out_dir.exists():
        raise FileExistsError(
            f"{out_dir} already exists; refusing to overwrite a capture"
        )
    # Anti-vacuous-pass guard (shared convention with gamry/galil/spec/sample):
    # an empty capture (no action output) compares to nothing and passes parity
    # trivially. Require at least one -act.yml before writing anything.
    acts, hlos = _run_artifacts(root)
    if not acts:
        raise RuntimeError(
            f"{root} has no -act.yml to capture; refusing a vacuous capture "
            "that would pass parity with 0 diffs. Check the launch/capture "
            "logs -- the action may have errored or produced no output."
        )
    errored = [p for p, st in _act_status_map(root).items() if "errored" in st]
    if errored:
        print(
            f"[golden_capture_cam] WARNING: {len(errored)} action(s) ERRORED "
            f"and were still captured: {errored}. An errored run is NOT a valid "
            "parity baseline. Check the -act.yml error fields and the CAM log "
            "before trusting a PASS."
        )
    if not hlos:
        print(
            f"[golden_capture_cam] WARNING: no .hlo captured under {root} -- "
            "acquire_image streamed no frame data. Parity will compare -act.yml "
            "metadata only, NOT the hlo/jpg write path. Verify the camera is "
            "reachable at axis_ip and returned a frame."
        )
    out_root = out_dir / "root"
    out_root.mkdir(parents=True)
    for top in PARITY_TOPS:
        src = root / top
        if src.is_dir():
            shutil.copytree(src, out_root / top)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    config_path = CONFIG_DIR / f"{config_prefix}.yml"
    combined_notes = (
        "REAL-HARDWARE acquire_image capture (Axis webcam reachable at axis_ip). "
        "Three volatile surfaces neutralized: the .jpg tree path is normalized by "
        "the RE_CAM_IMG grammar rule (cam_NNNNNN_TS.jpg); the .jpg bytes are "
        "content-masked 'skip'; the .hlo epoch_s/filename columns are "
        "value-masked. The -act.yml files[].file_name normalizes structurally via "
        "normalize_meta's file_name grammar (unmasked, so any other diff shows)."
    )
    if notes:
        combined_notes = f"{combined_notes} {notes}"
    ProvenanceManifest(
        scenario=SCENARIO,
        config_prefix=config_prefix,
        config_path=str(config_path),
        legacy_git_sha=sha,
        launch_cmd=f'conda run -n helao python launch.py "{config_path}" --no-hot-reload',
        sequence_name="manual_acquire_image",
        sequence_params={
            "manual": True,
            "endpoint": "POST /CAM/acquire_image",
            "duration": duration,
            "acquisition_rate": acquisition_rate,
            "fast_samples_in": [],
        },
        capture_timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
        harness_version=HARNESS_VERSION,
        masked_hlo_columns=CAM_MASKED_HLO_COLUMNS,
        hlo_row_count_tolerance=CAM_HLO_ROW_COUNT_TOLERANCE,
        content_masked_files=CAM_CONTENT_MASKED_FILES,
        masked_meta_keys=CAM_ACT_YML_MASKED_META_KEYS,
        notes=combined_notes,
    ).save(out_dir)
    return out_dir


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m helao.hexagon.tests.smoke.golden_capture_cam",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--config-prefix", required=True)
    parser.add_argument(
        "--duration",
        type=float,
        default=0,
        help="duration; 0 acquires a single frame (default 0)",
    )
    parser.add_argument("--acquisition-rate", type=float, default=1)
    parser.add_argument("--settle-polls", type=int, default=3)
    parser.add_argument("--notes", default="")
    args = parser.parse_args(argv)

    assert_fresh(args.root)
    wait_for_server(CAM_HOST, CAM_PORT)
    acquire_image_action(args.config_prefix, args.duration, args.acquisition_rate)
    settle(args.root, settle_polls=args.settle_polls)
    out = snapshot(
        root=args.root,
        out_dir=args.out,
        config_prefix=args.config_prefix,
        duration=args.duration,
        acquisition_rate=args.acquisition_rate,
        notes=args.notes,
    )
    print(f"captured {SCENARIO} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
