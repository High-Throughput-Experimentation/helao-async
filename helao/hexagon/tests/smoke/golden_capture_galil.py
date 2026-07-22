"""Runtime golden-diff capture for the galil_motion hexagon canary (P3a
special-split).

*** DRIVES THE REAL GALIL MOTION CONTROLLER (READ-ONLY QUERY, NO MOTION). ***

Step 0 of the parent task investigated whether ``query_positions`` needs a
live controller to produce data and found: yes. ``Galil.connect()``
(helao/deploy/hte/drivers/motion/galil_motion_driver.py) unconditionally
opens a real ``gclib`` TCP connection to ``galil_ip_str`` and swallows any
connection failure into ``galil_enabled = False`` (no exception propagates,
no dummy/sim data path anywhere in this code path) -- if the controller is
unreachable the server still comes up, but ``query_axis_position``
short-circuits to ``{"ax": [], "position": []}`` with no real position data.
The config's ``dummy``/``simulation`` YAML keys are therefore cosmetic
(banner color) for this canary, exactly as already documented for gamry in
``golden_capture.py``.

``query_positions`` (``POST /MOTOR/query_positions``) is NON-PERTURBING: it
reads encoder positions via ``TP``/``PA ?`` gclib commands and never issues a
motion command (no ``move``/``easymove``/``home``/``run_aligner``). It is
therefore safe to run at-station without moving the stage, but the galil
controller must still be powered on and reachable at ``galil_ip_str`` to
produce any position data at all.

Standalone counterpart to ``harness.capture.snapshot_capture`` for the
orch-less, db-less galil/galilhex 2-server topology (MOTOR@8003 +
ACTVIS@5001 only -- no ORCH, no DB), mirroring gamry's
``helao.hexagon.tests.smoke.golden_capture`` (see that module's docstring for
the full topology-gap rationale already recorded there and in
``gamryhex_canary.bat``, which hit the same gap for the openapi-diff
canary). The hardware-agnostic settle/anti-vacuous-guard logic (``settle``,
``_run_artifacts``, ``_act_status_map``) is IMPORTED from
``golden_capture.py`` rather than re-implemented here -- it is pure
-act.yml/RUNS_ACTIVE polling logic with no gamry-specific assumptions (does
not reference gamry's OCV scenario name or masking). Only the
scenario-specific pieces (endpoint, masking, manifest notes) are new in this
module. ``golden_capture.py`` itself is NOT modified.

Usage (AT-STATION, Windows, conda env ``helao``) -- the galil controller must
be powered on and reachable at ``galil_ip_str`` (192.168.200.234 by default).
NO dummy cell / calibration resistor is needed (this is a motion controller,
not a potentiostat), and THE STAGE DOES NOT MOVE for this scenario:

    rmdir /s /q C:\\INST_hlo_golden               (or pick a fresh --root)
    conda run -n helao python launch.py galilgold --no-hot-reload
    conda run -n helao python -m helao.hexagon.tests.smoke.golden_capture_galil ^
        --config-prefix galilgold --root C:\\INST_hlo_golden ^
        --out C:\\golden\\galil

then terminate the launch, point ``--root``/``--config-prefix`` at a FRESH
throwaway root and ``galilgoldhex``, capture again, and diff the two capture
directories with ``harness.parity``. ``galil_diff.bat`` automates exactly
this sequence.
"""

from __future__ import annotations

import argparse
import datetime
import shutil
import subprocess
import sys
from pathlib import Path

import requests

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

MOTOR_HOST, MOTOR_PORT = "127.0.0.1", 8003

SCENARIO = "GM-QPOS"

# hte canary configs (P3a/P3e relocation) live alongside this module, in
# its own configs/ sibling directory -- no longer under helao/deploy/hte/.
CONFIG_DIR = Path(__file__).resolve().parent / "configs"

# galil_motion.py's query_positions endpoint calls
# `Galil.query_axis_position(axis=Galil.get_all_axis())` and enqueues its
# return dict verbatim via `enqueue_data_dflt` (base.py writes datadict keys
# straight through as hlo columns -- see active_data_stream.py
# enqueue_data_dflt). query_axis_position (galil_motion_driver.py) returns
# {"ax": [...], "position": [...]}:
#   - "ax": the configured axis-name list (deterministic given axis_id,
#     identical on every capture that shares config -- NOT masked).
#   - "position": the live encoder reading in motor mm (raw gclib "PA ?"
#     query result) -- MASKED. Tolerance 0: a single `enqueue_data_dflt`
#     call writes exactly one row (no poll loop / no jitter to tolerate).
QPOS_HLO_COLUMNS = ["position"]
QPOS_MASKED_HLO_COLUMNS = {
    "*query_position*.hlo": QPOS_HLO_COLUMNS,
    "*query_position*.hlo.json*": QPOS_HLO_COLUMNS,
}
QPOS_HLO_ROW_COUNT_TOLERANCE = {
    "*query_position*.hlo": 0,
    "*query_position*.hlo.json*": 0,
}


def verify_device_open(host: str, port: int) -> None:
    """Fail fast if the Galil controller did not connect at startup.

    ``Galil.connect()`` opens a gclib TCP connection to ``galil_ip_str``; if
    the controller is unreachable or the open raises, ``connect()`` catches
    the exception and sets ``galil_enabled = False`` (see
    galil_motion_driver.py), so the server otherwise comes up cleanly with a
    closed motor connection. Running ``query_positions`` then just returns
    ``{"ax": [], "position": []}`` with no real data (a "finished" -act.yml,
    but a vacuous one). Checking ``_driver_status`` up front surfaces the
    real cause instead of a silently-empty capture.

    NOTE: ``get_status`` is a PRIVATE endpoint -- bare ``/get_status``, NOT
    ``/MOTOR/get_status``. On this server only ACTION endpoints carry the
    ``/{server_key}/`` prefix (e.g. ``/MOTOR/query_positions``);
    private/system routes (get_status, shutdown, endpoints) are unprefixed.
    ``_driver_status`` is ``Galil.get_status()``'s ``DriverStatus`` value:
    "uninitialized" when ``galil_enabled`` is falsy, "ok"/"busy" once the
    gclib connection is open (base_api.py's bare ``/get_status`` handler
    appends it as ``status_dict["_driver_status"]``).
    """
    try:
        r = requests.post(f"http://{host}:{port}/get_status", timeout=10)
        driver_status = r.json().get("_driver_status") if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        driver_status = None
    if driver_status not in ("ok", "busy"):
        raise RuntimeError(
            f"MOTOR galil device is NOT open (_driver_status={driver_status!r}) "
            "-- connect() failed at server startup (commonly the "
            "galil_ip_str controller unreachable/powered off). Verify the "
            "Galil controller is powered on and reachable at the configured "
            "galil_ip_str, then re-run. See the MOTOR launch log for the "
            "connect traceback."
        )


def query_positions_action(config_prefix: str) -> dict:
    """Run /MOTOR/query_positions via ``async_action_dispatcher`` (the production
    action-dispatch path -- RPC then HTTP, full action envelope).

    No params: ``query_positions`` always queries every configured axis
    (``Galil.get_all_axis()``). Non-perturbing -- reads encoder counts only,
    issues no motion command.
    """
    return dispatch_action(config_prefix, "MOTOR", "query_positions")


def snapshot(
    root: Path,
    out_dir: Path,
    config_prefix: str,
    notes: str = "",
) -> Path:
    """Copy PARITY_TOPS from ``root`` and write a provenance manifest.

    Refuses to overwrite an existing ``out_dir``, matching
    ``harness.capture.snapshot_capture`` / gamry's ``golden_capture.snapshot``.
    """
    root, out_dir = Path(root), Path(out_dir)
    if out_dir.exists():
        raise FileExistsError(
            f"{out_dir} already exists; refusing to overwrite a capture"
        )
    # Anti-vacuous-pass guard (shared with gamry's golden_capture.snapshot):
    # an empty capture (no action output) compares to nothing and passes
    # parity trivially. Require at least one -act.yml before writing
    # anything. .hlo is NOT required in principle, but query_positions
    # always enqueues data on success, so its absence here is a strong signal
    # of a failed/disconnected query and is warned loudly below.
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
            f"[golden_capture_galil] WARNING: {len(errored)} action(s) ERRORED "
            f"and were still captured: {errored}. An errored run is NOT a "
            "valid parity baseline (it likely produced no data / partial "
            "output). Check the -act.yml error fields and the MOTOR log "
            "before trusting a PASS."
        )
    if not hlos:
        print(
            f"[golden_capture_galil] WARNING: no .hlo captured under {root} -- "
            "query_positions produced no data file. Parity will compare "
            "-act.yml metadata only, NOT the hlo data-write path. Verify "
            "verify_device_open passed and the galil controller is reachable."
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
        "REAL-HARDWARE query_positions capture (galil controller reachable "
        "at-station); NON-PERTURBING (no motion command issued). 'position' "
        "hlo values are masked via masked_hlo_columns since they are live "
        "encoder readings, not deterministic sim data."
    )
    if notes:
        combined_notes = f"{combined_notes} {notes}"
    ProvenanceManifest(
        scenario=SCENARIO,
        config_prefix=config_prefix,
        config_path=str(config_path),
        legacy_git_sha=sha,
        launch_cmd=f'conda run -n helao python launch.py "{config_path}" --no-hot-reload',
        sequence_name="manual_query_positions",
        sequence_params={
            "manual": True,
            "endpoint": "POST /MOTOR/query_positions",
        },
        capture_timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
        harness_version=HARNESS_VERSION,
        masked_hlo_columns=QPOS_MASKED_HLO_COLUMNS,
        hlo_row_count_tolerance=QPOS_HLO_ROW_COUNT_TOLERANCE,
        notes=combined_notes,
    ).save(out_dir)
    return out_dir


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m helao.hexagon.tests.smoke.golden_capture_galil",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--config-prefix", required=True)
    parser.add_argument("--settle-polls", type=int, default=3)
    parser.add_argument("--notes", default="")
    args = parser.parse_args(argv)

    assert_fresh(args.root)
    wait_for_server(MOTOR_HOST, MOTOR_PORT)
    verify_device_open(MOTOR_HOST, MOTOR_PORT)
    query_positions_action(args.config_prefix)
    settle(args.root, settle_polls=args.settle_polls)
    out = snapshot(
        root=args.root,
        out_dir=args.out,
        config_prefix=args.config_prefix,
        notes=args.notes,
    )
    print(f"captured {SCENARIO} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
