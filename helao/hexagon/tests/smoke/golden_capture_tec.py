"""Runtime golden-diff capture for the tec_server hexagon canary (P3a
special-split).

*** DRIVES THE REAL MEERSTETTER TEC CONTROLLER (READ-ONLY TELEMETRY, NO
SETPOINT/ENABLE CHANGE). ***

``record_tec`` (``POST /TEC/record_tec``, ``tec_server.py``) starts a
``TECMonExec`` that streams TEC telemetry (``tec_vals`` off the poller's live
buffer) for a fixed ``duration`` and never calls ``set_temp``/``enable``/
``disable`` -- it is NON-PERTURBING. It still requires a live MeCom serial
session to produce any real data: ``MeerstetterTEC`` has no sim/dummy data
path (``get_data`` raises/returns empty on a closed session; see
``mecom_driver.py``), and unlike ``galil_motion``/``gamry`` the MeCom session
is opened LAZILY -- ``MeerstetterTECPoller``'s background poll loop calls
``driver.get_data()`` which calls ``driver.session()``, which opens the
connection on its first call if not already open. There is no explicit
``connect()`` call anywhere in ``tec_server.py``, so the connection is only
open once the poller has run at least once after server startup. The
config's ``dummy``/``simulation`` YAML keys are therefore cosmetic (banner
color) for this canary, exactly as already documented for galil/gamry.

Standalone counterpart to ``harness.capture.snapshot_capture`` for the
orch-less, db-less tec/techex 2-server topology (TEC@8008 + ACTVIS@5001 only
-- no ORCH, no DB), mirroring gamry's
``helao.hexagon.tests.smoke.golden_capture`` / galil's
``golden_capture_galil`` (see those modules' docstrings for the full
topology-gap rationale already recorded there and in ``gamryhex_canary.bat``,
which hit the same gap for the openapi-diff canary). The hardware-agnostic
settle/anti-vacuous-guard logic (``settle``, ``_run_artifacts``,
``_act_status_map``, ``dispatch_action``) is IMPORTED from
``golden_capture.py`` rather than re-implemented here. Only the
scenario-specific pieces (endpoint, masking, manifest notes) are new in this
module. ``golden_capture.py`` itself is NOT modified.

Usage (AT-STATION, Windows, conda env ``helao``) -- the Meerstetter
controller must be powered on and reachable at the configured serial ``port``
(COM5 by default). NO setpoint/enable change is issued for this scenario:

    rmdir /s /q C:\\INST_hlo_golden               (or pick a fresh --root)
    conda run -n helao python launch.py tecgold --no-hot-reload
    conda run -n helao python -m helao.hexagon.tests.smoke.golden_capture_tec ^
        --config-prefix tecgold --root C:\\INST_hlo_golden ^
        --out C:\\golden\\tec

then terminate the launch, point ``--root``/``--config-prefix`` at a FRESH
throwaway root and ``tecgoldhex``, capture again, and diff the two capture
directories with ``harness.parity``. ``tec_diff.bat`` automates exactly this
sequence.
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

TEC_HOST, TEC_PORT = "127.0.0.1", 8008

SCENARIO = "GM-TEC"

# hte canary configs (P3a/P3e relocation) live alongside this module, in
# its own configs/ sibling directory -- no longer under helao/deploy/hte/.
CONFIG_DIR = Path(__file__).resolve().parent / "configs"

# TECMonExec._poll (mecom_driver.py) reads the poller's live buffer
# (`tec_vals` + `epoch_s`) and returns it verbatim as the polled `data` dict,
# which the Executor plumbing enqueues straight through as hlo columns.
# `tec_vals` keys mirror MeerstetterTEC.queries (default: DEFAULT_QUERIES) --
# every one is a raw live reading off the MeCom serial session, no
# seeded/deterministic sim value exists anywhere in this driver, so all
# columns (including `epoch_s`, a live timestamp) must be masked for parity.
# Row counts are compared within a small tolerance: the executor's poll
# cadence is wall-clock/asyncio-scheduling driven (like gamry's OCV), not a
# fixed sample count.
TEC_HLO_COLUMNS = [
    "epoch_s",
    "enabled_status",
    "object_temperature",
    "target_object_temperature",
    "output_current",
    "temperature_is_stable",
]
TEC_MASKED_HLO_COLUMNS = {
    "*record_tec*.hlo": TEC_HLO_COLUMNS,
    "*record_tec*.hlo.json*": TEC_HLO_COLUMNS,
}
TEC_HLO_ROW_COUNT_TOLERANCE = {"*record_tec*.hlo": 2, "*record_tec*.hlo.json*": 2}


def verify_device_open(host: str, port: int) -> None:
    """Fail fast if the Meerstetter MeCom session did not open.

    ``MeerstetterTEC``'s MeCom session is opened LAZILY by the poller's first
    ``get_data()`` call (there is no explicit ``connect()`` call in
    ``tec_server.py``), so give the poller a moment to run before checking.
    ``get_status()`` returns ``status=ok`` once ``self._session`` is set,
    else ``status=uninitialized`` (see ``mecom_driver.py``).

    NOTE: ``get_status`` is a PRIVATE endpoint -- bare ``/get_status``, NOT
    ``/TEC/get_status``. On this server only ACTION endpoints carry the
    ``/{server_key}/`` prefix (e.g. ``/TEC/record_tec``); private/system
    routes (get_status, shutdown, endpoints) are unprefixed.
    """
    try:
        r = requests.post(f"http://{host}:{port}/get_status", timeout=10)
        driver_status = r.json().get("_driver_status") if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        driver_status = None
    if driver_status != "ok":
        raise RuntimeError(
            f"TEC MeCom session is NOT open (_driver_status={driver_status!r}) "
            "-- the poller's lazy connect failed (commonly the Meerstetter "
            "controller unreachable/powered off at the configured serial "
            "`port`). Verify the controller is powered on and reachable, "
            "then re-run. See the TEC launch log for the connect traceback."
        )


def record_tec_action(
    config_prefix: str, duration_s: float, acquisition_rate: float
) -> dict:
    """Dispatch /TEC/record_tec via ``async_action_dispatcher`` (the production
    action-dispatch path -- RPC then HTTP, full action envelope).

    ``duration_s`` bounds the executor's ``TECMonExec._poll`` loop -- it
    self-terminates (``HloStatus.finished``) once elapsed time exceeds
    ``duration``, so no separate ``cancel_record_tec`` call is needed.
    Non-perturbing: does not change the setpoint or enable/disable state.
    """
    return dispatch_action(
        config_prefix,
        "TEC",
        "record_tec",
        {"duration": duration_s, "acquisition_rate": acquisition_rate},
    )


def snapshot(
    root: Path,
    out_dir: Path,
    config_prefix: str,
    duration_s: float,
    acquisition_rate: float,
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
    # Anti-vacuous-pass guard (shared with gamry's/galil's golden_capture.snapshot):
    # an empty capture (no action output) compares to nothing and passes
    # parity trivially. Require at least one -act.yml before writing anything.
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
            f"[golden_capture_tec] WARNING: {len(errored)} action(s) ERRORED "
            f"and were still captured: {errored}. An errored run is NOT a "
            "valid parity baseline (it likely produced no data / partial "
            "output). Check the -act.yml error fields and the TEC log "
            "before trusting a PASS."
        )
    if not hlos:
        print(
            f"[golden_capture_tec] WARNING: no .hlo captured under {root} -- "
            "record_tec produced no streamed data file. Parity will compare "
            "-act.yml metadata only, NOT the hlo data-write path. Verify "
            "verify_device_open passed and the Meerstetter controller is "
            "reachable."
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
        "REAL-HARDWARE record_tec capture (Meerstetter TEC controller "
        "reachable at-station); NON-PERTURBING (no setpoint/enable change "
        "issued). All tec_vals + epoch_s hlo values are masked via "
        "masked_hlo_columns since they are live device readings, not "
        "deterministic sim data."
    )
    if notes:
        combined_notes = f"{combined_notes} {notes}"
    ProvenanceManifest(
        scenario=SCENARIO,
        config_prefix=config_prefix,
        config_path=str(config_path),
        legacy_git_sha=sha,
        launch_cmd=f'conda run -n helao python launch.py "{config_path}" --no-hot-reload',
        sequence_name="manual_record_tec",
        sequence_params={
            "manual": True,
            "endpoint": "POST /TEC/record_tec",
            "duration": duration_s,
            "acquisition_rate": acquisition_rate,
        },
        capture_timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
        harness_version=HARNESS_VERSION,
        masked_hlo_columns=TEC_MASKED_HLO_COLUMNS,
        hlo_row_count_tolerance=TEC_HLO_ROW_COUNT_TOLERANCE,
        notes=combined_notes,
    ).save(out_dir)
    return out_dir


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m helao.hexagon.tests.smoke.golden_capture_tec",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--config-prefix", required=True)
    parser.add_argument(
        "--duration", type=float, default=3.0, help="record_tec duration (default 3.0s)"
    )
    parser.add_argument(
        "--acquisition-rate",
        type=float,
        default=0.2,
        help="poll cadence (default 0.2s)",
    )
    parser.add_argument("--settle-polls", type=int, default=3)
    parser.add_argument("--notes", default="")
    args = parser.parse_args(argv)

    assert_fresh(args.root)
    wait_for_server(TEC_HOST, TEC_PORT)
    verify_device_open(TEC_HOST, TEC_PORT)
    record_tec_action(args.config_prefix, args.duration, args.acquisition_rate)
    settle(args.root, settle_polls=args.settle_polls)
    out = snapshot(
        root=args.root,
        out_dir=args.out,
        config_prefix=args.config_prefix,
        duration_s=args.duration,
        acquisition_rate=args.acquisition_rate,
        notes=args.notes,
    )
    print(f"captured {SCENARIO} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
