"""Runtime golden-diff capture for the co2sensor_server hexagon canary (P3a
special-split).

*** DRIVES THE REAL SprintIR-6S CO2 SENSOR. THIS IS NOT A SIMULATION. ***

Like gamry/spec (and unlike sample), co2sensor_server has NO sim/dummy data
path: ``SprintIR.connect`` (helao/deploy/hte/drivers/sensor/sprintir_driver.py)
unconditionally opens the serial port (``serial.Serial(port=...)``) and
configures the physical sensor, and ``co2sensor_server.py`` instantiates
``driver_classes=[SprintIR]`` / ``poller_class=SprintIRPoller`` unconditionally
-- the config's ``dummy``/``simulation`` YAML keys are cosmetic (banner color)
for this canary only. So this capture rig is an AT-STATION, REAL-HARDWARE gate:
the SprintIR sensor must be attached (Windows station, serial ``COM12``) for
``acquire_co2`` to produce any data.

``acquire_co2`` (``POST /CO2SENSOR/acquire_co2``) with a SHORT finite
``duration`` streams live CO2 ppm off the sensor's live buffer at
``acquisition_rate`` Hz and terminates on its own once ``duration`` elapses
(``CO2MonExec._poll`` returns ``HloStatus.finished`` when
``elapsed >= duration``; ``duration <= 0`` would run until cancelled, so a
positive finite duration is used here so the capture terminates without a
cancel). It is single-read, NON-PERTURBING -- it only mirrors the sensor's
live-buffer reading; it drives nothing. Each poll enqueues one row to the
default data sink as a ``.hlo``.

That .hlo's body columns are ``co2_ppm`` (live sensor ppm) and ``epoch_s``
(wall clock) -- BOTH live/hardware-derived, none deterministic run-to-run. Their
VALUES are therefore masked via the manifest's ``masked_hlo_columns`` (column
presence is still asserted). Because the executor is POLL-PACED (one row per
``acquisition_rate``-second poll over a wall-clock ``duration``), the ROW COUNT
jitters by a row or two run-to-run, so a small ``hlo_row_count_tolerance`` is
allowed (mirrors gamry ``run_OCV``, not spec's exact single-shot count).

Unlike spec's ``acquire_spec`` (and like gamry's ``run_OCV``), the
``acquire_co2`` executor writes ONE data-derived summary value back into
``action_params``: ``CO2MonExec._post_exec`` stashes ``mean_co2_ppm`` (mean of
the masked live samples) into ``action_params`` at the end of the run. That
value derives from the same live measurement and is NOT covered by
``masked_hlo_columns`` (which masks .hlo files only) nor by
``normalize_meta``'s §5.5 volatile lists (it is a plain float leaf under
``action_params``), so it is masked via ``masked_meta_keys`` -- otherwise
parity would report a diff on it between any two independent captures.

Standalone counterpart to ``harness.capture.snapshot_capture`` for the
orch-less, db-less co2/co2hex 2-server topology (CO2SENSOR@8012 + ACTVIS@5001
only -- no ORCH, no DB), mirroring spec/gamry's ``golden_capture[_spec].py``
(see those modules' docstrings for the full topology-gap rationale). The
hardware-agnostic settle / anti-vacuous-guard logic (``settle``,
``_run_artifacts``, ``_act_status_map``) and the production dispatch path
(``dispatch_action``) are IMPORTED from ``golden_capture.py`` rather than
re-implemented here; only the scenario-specific pieces (endpoint, masking,
manifest notes) are new. ``golden_capture.py`` itself is NOT modified.

Usage (AT-STATION, Windows, conda env ``helao``) -- ATTACH THE SENSOR FIRST:

    rmdir /s /q C:\\INST_hlo_golden               (or pick a fresh --root)
    conda run -n helao python launch.py co2gold --no-hot-reload
    conda run -n helao python -m helao.hexagon.tests.smoke.golden_capture_co2 ^
        --config-prefix co2gold --root C:\\INST_hlo_golden ^
        --out C:\\golden\\co2

then terminate the launch, point ``--root``/``--config-prefix`` at a FRESH
throwaway root and ``co2goldhex``, capture again, and diff the two capture
directories with ``harness.parity``. ``co2_diff.bat`` automates exactly this
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

CO2_HOST, CO2_PORT = "127.0.0.1", 8012

SCENARIO = "GM-CO2"

# helao/hexagon/tests/smoke/golden_capture_co2.py -> repo root is 4 parents up
# (matches safe_root.py's own _repo_root()).
REPO_ROOT = Path(__file__).resolve().parents[4]
CONFIG_DIR = REPO_ROOT / "helao" / "deploy" / "hte" / "configs"

# CO2MonExec._poll (sprintir_driver.py) builds each data row as
# {"co2_ppm": <live sensor ppm>, "epoch_s": <wall clock>}. Both are
# live/hardware-derived -- no seeded/deterministic sim values exist anywhere in
# this driver -- so their VALUES must be masked for parity; column presence is
# still compared. Pattern "*.hlo" is safe: the only .hlo an acquire_co2 capture
# emits is this CO2 stream file.
CO2_HLO_COLUMNS = ["co2_ppm", "epoch_s"]
CO2_MASKED_HLO_COLUMNS = {
    "*.hlo": CO2_HLO_COLUMNS,
    "*.hlo.json*": CO2_HLO_COLUMNS,
}
# The executor is POLL-PACED (one row per acquisition_rate-second poll over a
# wall-clock `duration`), so the row count jitters by a row or two run-to-run --
# masked columns compared within a small tolerance (mirrors gamry run_OCV; NOT
# spec's exact single-shot count).
CO2_HLO_ROW_COUNT_TOLERANCE = {"*.hlo": 2, "*.hlo.json*": 2}
# CO2MonExec._post_exec writes the data-derived summary value mean_co2_ppm back
# into the run's -act.yml action_params. It derives from the same live/unmasked
# measurement and is NOT covered by masked_hlo_columns (hlo files only) nor by
# normalize_meta's §5.5 volatile lists (a plain float leaf under action_params).
# Masked via masked_meta_keys (the meta-side analogue of masked_hlo_columns):
# parity neutralizes its VALUE on both sides while keeping the key present, so
# the runtime diff is a CLEAN PASS when only it differs and a real regression in
# any other key/file still surfaces. The key is a no-op on any yml lacking it.
CO2_ACT_YML_MASKED_META_KEYS = {
    "*-act.yml": [
        "action_params.mean_co2_ppm",
    ],
}


def acquire_co2_action(
    config_prefix: str, duration: float = 3.0, acquisition_rate: float = 0.2
) -> dict:
    """Run /CO2SENSOR/acquire_co2 via ``async_action_dispatcher`` (production
    action-dispatch path -- RPC then HTTP, full action envelope).

    A SHORT finite ``duration`` (> 0) streams live CO2 ppm for that many seconds
    then terminates on its own (``CO2MonExec._poll`` finishes when the elapsed
    wall clock reaches ``duration``); ``duration <= 0`` would run until
    cancelled. Non-perturbing: mirrors the sensor's live-buffer reading, drives
    nothing. The endpoint's ``fast_samples_in`` defaults to ``Body([])`` so no
    sample is required.
    """
    return dispatch_action(
        config_prefix,
        "CO2SENSOR",
        "acquire_co2",
        {"duration": duration, "acquisition_rate": acquisition_rate},
        # duration-bounded stream plus headroom for the endpoint's trailing
        # dangling-data drain + finish().
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
    ``harness.capture.snapshot_capture`` / spec/gamry's ``snapshot``.
    """
    root, out_dir = Path(root), Path(out_dir)
    if out_dir.exists():
        raise FileExistsError(
            f"{out_dir} already exists; refusing to overwrite a capture"
        )
    # Anti-vacuous-pass guard (shared convention with spec/gamry/galil/sample):
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
            f"[golden_capture_co2] WARNING: {len(errored)} action(s) ERRORED "
            f"and were still captured: {errored}. An errored run is NOT a valid "
            "parity baseline. Check the -act.yml error fields and the CO2SENSOR "
            "log before trusting a PASS."
        )
    if not hlos:
        print(
            f"[golden_capture_co2] WARNING: no .hlo captured under {root} -- "
            "acquire_co2 produced no CO2 stream data file. Parity will compare "
            "-act.yml metadata only, NOT the hlo data-write path. Verify the "
            "SprintIR is attached on COM12 and the poller returned ppm samples."
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
        "REAL-HARDWARE acquire_co2 capture (SprintIR-6S CO2 sensor attached on "
        "COM12); NOT a simulation -- SprintIR has no sim/dummy data path. The "
        ".hlo body columns co2_ppm/epoch_s are live sensor data and are masked "
        "via masked_hlo_columns; the row count is compared within "
        "hlo_row_count_tolerance (the executor is poll-paced). The data-derived "
        "action_params key mean_co2_ppm is masked via masked_meta_keys, so "
        "parity is a clean PASS when only these differ."
    )
    if notes:
        combined_notes = f"{combined_notes} {notes}"
    ProvenanceManifest(
        scenario=SCENARIO,
        config_prefix=config_prefix,
        config_path=str(config_path),
        legacy_git_sha=sha,
        launch_cmd=f"conda run -n helao python launch.py {config_prefix} --no-hot-reload",
        sequence_name="manual_acquire_co2",
        sequence_params={
            "manual": True,
            "endpoint": "POST /CO2SENSOR/acquire_co2",
            "duration": duration,
            "acquisition_rate": acquisition_rate,
            "fast_samples_in": [],
        },
        capture_timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
        harness_version=HARNESS_VERSION,
        masked_hlo_columns=CO2_MASKED_HLO_COLUMNS,
        hlo_row_count_tolerance=CO2_HLO_ROW_COUNT_TOLERANCE,
        masked_meta_keys=CO2_ACT_YML_MASKED_META_KEYS,
        notes=combined_notes,
    ).save(out_dir)
    return out_dir


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m helao.hexagon.tests.smoke.golden_capture_co2",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--config-prefix", required=True)
    parser.add_argument(
        "--duration",
        type=float,
        default=3.0,
        help="acquire_co2 duration in seconds; must be > 0 so the stream "
        "terminates on its own (default 3.0)",
    )
    parser.add_argument(
        "--acquisition-rate",
        type=float,
        default=0.2,
        help="acquisition_rate (poll pacing, seconds/sample) (default 0.2)",
    )
    parser.add_argument("--settle-polls", type=int, default=3)
    parser.add_argument("--notes", default="")
    args = parser.parse_args(argv)

    if args.duration <= 0:
        parser.error(
            "--duration must be > 0 so acquire_co2 terminates on its own "
            "(duration <= 0 runs until cancelled and would hang the capture)"
        )

    assert_fresh(args.root)
    wait_for_server(CO2_HOST, CO2_PORT)
    acquire_co2_action(args.config_prefix, args.duration, args.acquisition_rate)
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
