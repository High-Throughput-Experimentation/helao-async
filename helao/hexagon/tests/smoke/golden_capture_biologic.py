"""Runtime golden-diff capture for the biologic_server hexagon canary (P3a
special-split).

*** DRIVES THE REAL BIOLOGIC POTENTIOSTAT (OPEN-CIRCUIT READ, NON-PERTURBING). ***

Step 0 of the parent task investigated whether ``run_OCV`` can produce data
under ``simulation: true``/``dummy: true`` with no real instrument attached,
and found: no. ``BiologicDriver.__init__`` (helao/deploy/hte/drivers/pstat/
biologic/driver.py) unconditionally calls ``connect()``, which opens a real
``easy_biologic.BiologicDevice`` TCP connection to the instrument, and
``biologic_server.py`` instantiates ``driver_classes=[BiologicDriver]``
unconditionally -- there is no dummy/sim driver swap anywhere in this code
path, and ``easy_biologic`` itself imports only on Windows (raises OSError on
Linux). The config's ``dummy``/``simulation`` YAML keys are therefore cosmetic
(banner color) for this canary, exactly as already documented for gamry in
``golden_capture.py`` and galil in ``golden_capture_galil.py``.

``run_OCV`` (``POST /BIOLOGIC/run_OCV``) is NON-PERTURBING: the OCV technique
(easy_biologic ``blp.OCV``) monitors the open-circuit potential and NEVER
actively drives the cell (no applied potential/current -- unlike run_CA/run_CP/
run_CV/run_PEIS/run_GEIS/run_CAOCV, which impose a potential or current on the
cell). It is therefore safe to run at-station against a dummy cell /
calibration resistor, but it still requires a live Biologic device to produce
any data at all.

Standalone counterpart to ``harness.capture.snapshot_capture`` for the
orch-less, db-less biologic/biologichex 2-server topology (BIOLOGIC@8016 +
ACTVIS@5001 only -- no ORCH, no DB), mirroring gamry's
``helao.hexagon.tests.smoke.golden_capture`` (see that module's docstring for
the full topology-gap rationale already recorded there and in
``gamryhex_canary.bat``, which hit the same gap for the openapi-diff canary).
The hardware-agnostic settle/anti-vacuous-guard logic (``settle``,
``_run_artifacts``, ``_act_status_map``) and the production action-dispatch
path (``dispatch_action``) are IMPORTED from ``golden_capture.py`` rather than
re-implemented here -- they are pure -act.yml/RUNS_ACTIVE polling +
async_action_dispatcher logic with no gamry-specific assumptions (they do not
reference gamry's OCV scenario name or masking). Only the scenario-specific
pieces (endpoint params, masking, verify_device_open probe, manifest notes)
are new in this module. ``golden_capture.py`` itself is NOT modified.

Usage (AT-STATION, Windows, conda env ``helao``) -- ATTACH THE DUMMY CELL /
CAL RESISTOR FIRST (run_OCV drives nothing, but connect() needs the live
instrument, and a dummy cell gives a stable open-circuit reading):

    rmdir /s /q C:\\INST_hlo_golden               (or pick a fresh --root)
    conda run -n helao python launch.py biologicgold --no-hot-reload
    conda run -n helao python -m helao.hexagon.tests.smoke.golden_capture_biologic ^
        --config-prefix biologicgold --root C:\\INST_hlo_golden ^
        --out C:\\golden\\biologic

then terminate the launch, point ``--root``/``--config-prefix`` at a FRESH
throwaway root and ``biologicgoldhex``, capture again, and diff the two capture
directories with ``harness.parity``. ``biologic_diff.bat`` automates exactly
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

BIO_HOST, BIO_PORT = "127.0.0.1", 8016

SCENARIO = "GM-BIOOCV"

# helao/hexagon/tests/smoke/golden_capture_biologic.py -> repo root is 4 parents
# up (matches safe_root.py's own _repo_root()).
REPO_ROOT = Path(__file__).resolve().parents[4]
CONFIG_DIR = REPO_ROOT / "helao" / "deploy" / "hte" / "configs"

# The run_OCV .hlo columns. BiologicExec._poll enqueues BiologicDriver.get_data's
# data dict verbatim (base.py writes datadict keys straight through as hlo
# columns). For the OCV technique (TECH_OCV, technique.py) get_data emits:
#   - "t_s"  = field_remap of easy_biologic "time"    (live sample times)
#   - "Ewe_V"= field_remap of easy_biologic "voltage" (live open-circuit potential)
#   - the "_<Field>" columns = getdict(segment.values), i.e. the per-segment
#     ctypes CurrentValues struct (ec_lib.py) prefixed with "_": live device
#     state / instantaneous readings (State, MemFilled, TimeBase, Ewe, I,
#     IRange, ElapsedTime, Freq, saturation/overflow flags, ...).
# ALL of these are raw live measurements / device state pulled straight off the
# instrument -- no seeded/deterministic sim values exist anywhere in this driver
# -- so their VALUES are MASKED for parity. Row counts are compared within a
# small tolerance (the OCV poll loop / dtaq segment retrieval jitters a row or
# two run-to-run). The "channel" column is NOT masked: BiologicExec adds it as a
# constant equal to the requested channel index (config/param-deterministic,
# identical on every capture -- the biologic analogue of galil's unmasked "ax").
OCV_HLO_COLUMNS = [
    "t_s",
    "Ewe_V",
    "_State",
    "_MemFilled",
    "_TimeBase",
    "_Ewe",
    "_EweRangeMin",
    "_EweRangeMax",
    "_Ece",
    "_EceRangeMin",
    "_EceRangeMax",
    "_Eoverflow",
    "_I",
    "_IRange",
    "_Ioverflow",
    "_ElapsedTime",
    "_Freq",
    "_Rcomp",
    "_Saturation",
    "_OptErr",
    "_OptPos",
]
OCV_MASKED_HLO_COLUMNS = {
    "*OCV*.hlo": OCV_HLO_COLUMNS,
    "*OCV*.hlo.json*": OCV_HLO_COLUMNS,
}
OCV_HLO_ROW_COUNT_TOLERANCE = {"*OCV*.hlo": 2, "*OCV*.hlo.json*": 2}

# BiologicExec._post_exec (biologic_server.py ~269-303) writes data-derived
# summary values into the run's -act.yml action_params: for each of t_s / Ewe_V
# that is present in the OCV data buffer it stores "<k>__mean_final" (the mean of
# the trailing 5 samples), and for run_OCV it stores "has_bubble" (the
# bubble_detection verdict over the whole OCV trace). All three derive from the
# exact same live/unmasked measurement and are NOT covered by masked_hlo_columns
# (which masks .hlo files only) nor by harness.yaml_pass.normalize_meta's §5.5
# volatile lists (they are plain float/bool leaves under action_params, not
# uuids/timestamps/host-identity). Without masking, harness.parity's diff_meta
# would report a diff on these keys between any two independent captures, even
# against the identical dummy cell. (I_A__mean_final is NOT emitted for OCV: the
# OCV technique field_map produces no "I_A" column, so that branch never fires.)
#
# They are masked via the manifest's masked_meta_keys (the meta-side analogue of
# masked_hlo_columns): parity neutralizes their VALUES on both sides before
# diffing while keeping the keys present, so the runtime diff is a CLEAN PASS
# when only these values differ, and a real regression in ANY other key/file
# still surfaces normally. Pattern is "*-act.yml" (any action yml in this
# GM-BIOOCV capture set); the keys are no-ops on any yml lacking them. This
# mirrors gamry's run_OCV masking (golden_capture.py) exactly.
OCV_ACT_YML_MASKED_META_KEYS = {
    "*-act.yml": [
        "action_params.t_s__mean_final",
        "action_params.Ewe_V__mean_final",
        "action_params.has_bubble",
    ],
}


def verify_device_open(host: str, port: int) -> None:
    """Fail fast if the Biologic instrument did not connect at startup.

    ``BiologicDriver.connect()`` opens an ``easy_biologic.BiologicDevice`` TCP
    connection at construction; on failure ``ready`` stays False (and a
    second process holding the connection yields ``status=busy`` via the "In
    use by another script" guard). If the instrument is unreachable the server
    still comes up, but ``get_status`` then reports ``uninitialized``/``error``
    and running run_OCV just errors with no data (an errored -act.yml, no
    .hlo). Checking the driver status up front surfaces the real cause instead
    of a silently-empty capture.

    NOTE: ``get_status`` is a PRIVATE endpoint -- bare ``/get_status``, NOT
    ``/BIOLOGIC/get_status``. On this server only ACTION endpoints carry the
    ``/{server_key}/`` prefix (e.g. ``/BIOLOGIC/run_OCV``); private/system
    routes (get_status, stop_private, shutdown, endpoints) are unprefixed.
    ``_driver_status`` is ``BiologicDriver.get_status()``'s ``DriverStatus``
    value, appended by base_api.py's bare ``/get_status`` handler as
    ``status_dict["_driver_status"]``: "uninitialized"/"error" when the device
    is not connected, "ok"/"busy" once the TCP connection is open.
    """
    try:
        r = requests.post(f"http://{host}:{port}/get_status", timeout=10)
        driver_status = r.json().get("_driver_status") if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        driver_status = None
    if driver_status not in ("ok", "busy"):
        raise RuntimeError(
            f"BIOLOGIC device is NOT open (_driver_status={driver_status!r}) -- "
            "connect() failed at server startup (commonly the instrument "
            "unreachable/powered off, or 'In use by another script' when "
            "another biologic process holds the connection). Verify the "
            "Biologic instrument is powered on and reachable and that no other "
            "biologic group / leftover python holds it, then re-run. See the "
            "BIOLOGIC launch log for the connect traceback."
        )


def run_ocv_action(
    config_prefix: str, tval_s: float, acq_s: float, channel: int
) -> dict:
    """Run /BIOLOGIC/run_OCV via ``dispatch_action`` (the production action-dispatch
    path -- RPC then HTTP, full action envelope).

    ``run_OCV`` monitors open-circuit potential for ``tval_s`` seconds sampling
    every ``acq_s`` on ``channel``. NON-PERTURBING -- the OCV technique imposes
    no potential/current on the cell.
    """
    return dispatch_action(
        config_prefix,
        "BIOLOGIC",
        "run_OCV",
        {"Tval__s": tval_s, "AcqInterval__s": acq_s, "channel": channel},
    )


def snapshot(
    root: Path,
    out_dir: Path,
    config_prefix: str,
    tval_s: float,
    acq_s: float,
    channel: int,
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
    # Anti-vacuous-pass guard (shared with gamry's golden_capture.snapshot): an
    # empty capture (no action output) compares to nothing and passes parity
    # trivially. Require at least one -act.yml before writing anything, so a
    # false PASS is impossible even if settle() were bypassed. .hlo is NOT
    # required (a manual run_OCV may emit none if it errors), but its absence is
    # warned loudly: parity then compares -act.yml metadata only, not the hlo
    # data-write path.
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
            f"[golden_capture_biologic] WARNING: {len(errored)} action(s) ERRORED "
            f"and were still captured: {errored}. An errored run is NOT a valid "
            "parity baseline (it likely produced no data / partial output). Check "
            "the -act.yml error fields and the BIOLOGIC log before trusting a PASS."
        )
    if not hlos:
        print(
            f"[golden_capture_biologic] WARNING: no .hlo captured under {root} -- "
            "run_OCV produced no streamed data file. Parity will compare -act.yml "
            "metadata only, NOT the hlo data-write path. Verify verify_device_open "
            "passed, the dummy cell is connected, and driver.get_data returns "
            "samples."
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
        "REAL-HARDWARE run_OCV capture (dummy cell / cal resistor at-station); "
        "NOT a simulation -- BiologicDriver has no sim/dummy data path and "
        "easy_biologic imports only on Windows. NON-PERTURBING (open-circuit "
        "monitor, imposes no potential/current). The .hlo data columns (t_s, "
        "Ewe_V, and the _<Field> CurrentValues segment columns) are live "
        "measurements masked via masked_hlo_columns; 'channel' is deterministic "
        "and unmasked. -act.yml action_params t_s__mean_final, Ewe_V__mean_final, "
        "has_bubble are data-derived from the live measurement and are masked via "
        "masked_meta_keys so parity is a clean PASS when only they differ."
    )
    if notes:
        combined_notes = f"{combined_notes} {notes}"
    ProvenanceManifest(
        scenario=SCENARIO,
        config_prefix=config_prefix,
        config_path=str(config_path),
        legacy_git_sha=sha,
        launch_cmd=f"conda run -n helao python launch.py {config_prefix} --no-hot-reload",
        sequence_name="manual_run_OCV",
        sequence_params={
            "manual": True,
            "endpoint": "POST /BIOLOGIC/run_OCV",
            "Tval__s": tval_s,
            "AcqInterval__s": acq_s,
            "channel": channel,
        },
        capture_timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
        harness_version=HARNESS_VERSION,
        masked_hlo_columns=OCV_MASKED_HLO_COLUMNS,
        hlo_row_count_tolerance=OCV_HLO_ROW_COUNT_TOLERANCE,
        masked_meta_keys=OCV_ACT_YML_MASKED_META_KEYS,
        notes=combined_notes,
    ).save(out_dir)
    return out_dir


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m helao.hexagon.tests.smoke.golden_capture_biologic",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--config-prefix", required=True)
    parser.add_argument(
        "--tval", type=float, default=3.0, help="Tval__s (default 3.0s)"
    )
    parser.add_argument("--acq", type=float, default=0.1, help="AcqInterval__s")
    parser.add_argument("--channel", type=int, default=0, help="channel index")
    parser.add_argument("--settle-polls", type=int, default=3)
    parser.add_argument("--notes", default="")
    args = parser.parse_args(argv)

    assert_fresh(args.root)
    wait_for_server(BIO_HOST, BIO_PORT)
    verify_device_open(BIO_HOST, BIO_PORT)
    run_ocv_action(args.config_prefix, args.tval, args.acq, args.channel)
    settle(args.root, settle_polls=args.settle_polls)
    out = snapshot(
        root=args.root,
        out_dir=args.out,
        config_prefix=args.config_prefix,
        tval_s=args.tval,
        acq_s=args.acq,
        channel=args.channel,
        notes=args.notes,
    )
    print(f"captured {SCENARIO} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
