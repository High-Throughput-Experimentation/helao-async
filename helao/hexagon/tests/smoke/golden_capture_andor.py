"""Runtime golden-diff capture for the andor_server hexagon canary (P3a
special-split).

*** DRIVES THE REAL ANDOR ZYLA CAMERA + ATSPECTROGRAPH. NOT A SIMULATION. ***

Like gamry/spec/co2 (and unlike sample), andor_server has NO sim/dummy data
path: ``AndorDriver.__init__``/``connect`` (helao/deploy/hte/drivers/spec/andor/
driver.py) lazily loads the vendor ``pyAndorSDK3`` / ``pyAndorSpectrograph``
runtimes and opens the physical camera + spectrograph, and ``andor_server.py``
instantiates ``driver_classes=[AndorDriver]`` unconditionally -- the config's
``dummy``/``simulation`` YAML keys are cosmetic (banner color) for this canary
only. So this capture rig is an AT-STATION, REAL-HARDWARE gate: the Andor
camera + spectrograph must be attached (Windows, vendor SDKs present) for
``acquire`` to produce any data.

``acquire`` (``POST /ANDOR/acquire``) streams spectra: ``AndorAcquire`` (a
POLL-PACED, non-oneoff executor) arms the camera in ``_exec`` and pulls a batch
of frames per ``_poll`` via ``AndorDriver.get_data`` until ``duration`` seconds
of hardware tick-time elapse, enqueuing each frame as a row to the default data
sink as a ``.hlo``. It is single-read, NON-PERTURBING -- it only reads the
detector; it drives nothing. IMPORTANT: this capture dispatches with
``external_trigger=False`` (SOFTWARE trigger) so frames flow WITHOUT an external
5V TTL source -- with the endpoint default ``external_trigger=True`` the camera
would block on a trigger that never arrives in a bench/station canary and the
run would time out with no data.

That .hlo's body columns are ``tick_time`` (camera clock tick / clock_hz, per
``AndorDriver.get_data``) and ``ch_0000``..``ch_<N_PIXELS-1>`` (per-pixel
detector intensities) -- ALL live/hardware-derived, none deterministic
run-to-run -- so their VALUES are masked via the manifest's
``masked_hlo_columns`` (``elapsed_time_s`` is also masked defensively: the
endpoint declares it in ``json_data_keys``/``column_headings`` even though the
driver streams ``tick_time`` as the time column, and masking an absent column
is a harmless no-op). Column presence is still asserted. Because the executor is
POLL-PACED over a wall-clock/tick ``duration``, the ROW COUNT jitters run-to-run
(hardware framerate timing at the duration boundary, NOT anything the hexagon
graft controls), so a ``hlo_row_count_tolerance`` is allowed (mirrors
gamry ``run_OCV`` / co2 ``acquire_co2``, not spec's exact single-shot count).

The .hlo HEADER carries ``wl`` (the pixel->wavelength table,
``list(app.driver.wl_arr)`` from the spectrograph ``GetCalibration``) and
``column_headings`` -- both config/calibration-deterministic and compared
UNMASKED (a diff there is a genuine regression).

Unlike spec's ``acquire_spec`` (and like co2's ``acquire_co2``, which writes
``mean_co2_ppm`` back into ``action_params``), ``AndorAcquire.__init__`` writes
one run-specific value back into ``action_params``: ``action_path`` = the
action's ``action_output_dir`` (a per-run absolute path carrying wall-clock
week/date/timestamp components and uuids). ``normalize_meta`` only §5.1-grammar-
normalizes string values whose KEY ends in ``_output_dir`` -- ``action_path``
does not, so only its embedded uuids are mapped and its timestamp components
would otherwise surface as a spurious -act.yml diff between two independent
captures. It is therefore value-masked via ``masked_meta_keys`` (the meta-side
analogue of masked_hlo_columns); the key stays present so a one-sided presence
difference still surfaces.

Standalone counterpart to ``harness.capture.snapshot_capture`` for the
orch-less, db-less andor/andorhex 2-server topology (ANDOR@8011 + ACTVIS@5001
only -- no ORCH, no DB), mirroring spec/co2/gamry's ``golden_capture[_*].py``
(see those modules' docstrings for the full topology-gap rationale). The
hardware-agnostic settle / anti-vacuous-guard logic (``settle``,
``_run_artifacts``, ``_act_status_map``) and the production dispatch path
(``dispatch_action``) are IMPORTED from ``golden_capture.py`` rather than
re-implemented here; only the scenario-specific pieces (endpoint, masking,
manifest notes) are new. ``golden_capture.py`` itself is NOT modified.

Usage (AT-STATION, Windows, conda env ``helao``) -- ATTACH THE CAMERA +
SPECTROGRAPH FIRST:

    rmdir /s /q C:\\INST_hlo_golden               (or pick a fresh --root)
    conda run -n helao python launch.py andorgold --no-hot-reload
    conda run -n helao python -m helao.hexagon.tests.smoke.golden_capture_andor ^
        --config-prefix andorgold --root C:\\INST_hlo_golden ^
        --out C:\\golden\\andor

then terminate the launch, point ``--root``/``--config-prefix`` at a FRESH
throwaway root and ``andorgoldhex``, capture again, and diff the two capture
directories with ``harness.parity``. ``andor_diff.bat`` automates exactly this
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

ANDOR_HOST, ANDOR_PORT = "127.0.0.1", 8011

SCENARIO = "GM-ANDOR"

# helao/hexagon/tests/smoke/golden_capture_andor.py -> repo root is 4 parents up
# (matches safe_root.py's own _repo_root()).
REPO_ROOT = Path(__file__).resolve().parents[4]
CONFIG_DIR = REPO_ROOT / "helao" / "deploy" / "hte" / "configs"

# N_PIXELS: AndorDriver.setup_spectroscope reads the calibrated wavelength array
# via GetCalibration(0, 2560) (NumHorizPixels=2560), so wl_arr has 2560 elements;
# both the acquire endpoint (range(app.driver.wl_arr.shape[0])) and the driver
# get_data ({f"ch_{i:04}": [] for i in range(self.wl_arr.size)}) build one ch
# column per pixel -> ch_0000..ch_2559.
N_PIXELS = 2560

# ALL acquire .hlo body columns are live/hardware-derived (raw detector
# intensities + camera clock ticks), none seeded or deterministic -- so their
# VALUES are masked for parity. tick_time is the driver's time column;
# elapsed_time_s is the endpoint-declared column_headings name (masked
# defensively -- a no-op if absent from the body). Column presence + the row
# count (within tolerance) are still compared. The .hlo HEADER's `wl`
# (pixel->wavelength table) and `column_headings` are config/calibration-
# deterministic and are NOT masked (a diff there is a real regression). Pattern
# "*.hlo" is safe: the only .hlo any acquire capture emits is this spectrum
# stream file (the driver writes NO image/sidecar files).
ANDOR_HLO_COLUMNS = ["tick_time", "elapsed_time_s"] + [
    f"ch_{i:04}" for i in range(N_PIXELS)
]
ANDOR_MASKED_HLO_COLUMNS = {
    "*.hlo": ANDOR_HLO_COLUMNS,
    "*.hlo.json*": ANDOR_HLO_COLUMNS,
}
# The executor is POLL-PACED over a wall-clock/tick `duration`, so the frame/row
# count jitters run-to-run at the duration boundary (hardware framerate timing,
# NOT graft-controlled). Masked columns are compared within this tolerance
# (mirrors gamry run_OCV / co2 acquire_co2; NOT spec/cam's exact single-shot
# count). The value is a station-tunable ceiling on that timing jitter: it must
# stay well below the expected row count so a real graft regression (e.g. a
# broken streaming loop that writes ~1 row) still trips the len check, while
# absorbing the handful-of-frames boundary jitter. Tune at-station if the two
# captures' frame counts prove tighter or looser than this.
ANDOR_HLO_ROW_COUNT_TOLERANCE = {"*.hlo": 20, "*.hlo.json*": 20}
# AndorAcquire.__init__ writes action_path (= action_output_dir, a per-run
# absolute path with wall-clock + uuid components) back into the run's -act.yml
# action_params. normalize_meta only §5.1-normalizes *_output_dir-suffixed
# string values, so action_path's timestamp components would otherwise diff
# between two independent captures. Masked via masked_meta_keys (the meta-side
# analogue of masked_hlo_columns): parity neutralizes its VALUE on both sides
# while keeping the key present, so the runtime diff is a CLEAN PASS when only it
# differs and a real regression in any other key/file still surfaces. The key is
# a no-op on any yml lacking it.
ANDOR_ACT_YML_MASKED_META_KEYS = {
    "*-act.yml": [
        "action_params.action_path",
    ],
}


def acquire_action(
    config_prefix: str,
    duration: float = 1.0,
    external_trigger: bool = False,
    frames_per_poll: int = 100,
    buffer_count: int = 10,
    exp_time: float = 0.0098,
    framerate: float = 98,
    timeout: float = 5000,
) -> dict:
    """Run /ANDOR/acquire via ``async_action_dispatcher`` (production
    action-dispatch path -- RPC then HTTP, full action envelope).

    A SHORT finite ``duration`` (> 0) streams frames for that many
    (tick-)seconds then the executor finishes on its own. ``external_trigger``
    is forced ``False`` (SOFTWARE trigger) so frames flow without an external 5V
    TTL source; the endpoint default (``True``) would block on a trigger that
    never arrives in a canary. Non-perturbing: reads the detector only, drives
    nothing. The endpoint requires no ``fast_samples_in``.
    """
    return dispatch_action(
        config_prefix,
        "ANDOR",
        "acquire",
        {
            "external_trigger": external_trigger,
            "duration": duration,
            "frames_per_poll": frames_per_poll,
            "buffer_count": buffer_count,
            "exp_time": exp_time,
            "framerate": framerate,
            "timeout": timeout,
        },
        # duration-bounded stream plus headroom for the endpoint's trailing
        # dangling-data drain + finish().
        timeout=120,
    )


def snapshot(
    root: Path,
    out_dir: Path,
    config_prefix: str,
    duration: float,
    external_trigger: bool,
    notes: str = "",
) -> Path:
    """Copy PARITY_TOPS from ``root`` and write a provenance manifest.

    Refuses to overwrite an existing ``out_dir``, matching
    ``harness.capture.snapshot_capture`` / spec/co2's ``snapshot``.
    """
    root, out_dir = Path(root), Path(out_dir)
    if out_dir.exists():
        raise FileExistsError(
            f"{out_dir} already exists; refusing to overwrite a capture"
        )
    # Anti-vacuous-pass guard (shared convention with spec/co2/gamry/galil/
    # sample): an empty capture (no action output) compares to nothing and
    # passes parity trivially. Require at least one -act.yml before writing.
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
            f"[golden_capture_andor] WARNING: {len(errored)} action(s) ERRORED "
            f"and were still captured: {errored}. An errored run is NOT a valid "
            "parity baseline. Check the -act.yml error fields and the ANDOR log "
            "before trusting a PASS."
        )
    if not hlos:
        print(
            f"[golden_capture_andor] WARNING: no .hlo captured under {root} -- "
            "acquire streamed no spectrum data file. Parity will compare "
            "-act.yml metadata only, NOT the hlo data-write path. Verify the "
            "Andor camera + spectrograph are attached and that the SOFTWARE "
            "trigger (external_trigger=False) delivered frames."
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
        "REAL-HARDWARE acquire capture (Andor Zyla camera + ATSpectrograph "
        "attached); NOT a simulation -- AndorDriver has no sim/dummy data path. "
        "Dispatched with external_trigger=False (software trigger) so frames flow "
        "without an external TTL. The .hlo body columns tick_time/ch_NNNN are "
        "live detector data and are masked via masked_hlo_columns; the row count "
        "is compared within hlo_row_count_tolerance (poll-paced stream). The .hlo "
        "header `wl` (pixel->wavelength table) + column_headings are "
        "config-deterministic and compared unmasked. The per-run action_params "
        "key action_path is masked via masked_meta_keys, so parity is a clean "
        "PASS when only these differ."
    )
    if notes:
        combined_notes = f"{combined_notes} {notes}"
    ProvenanceManifest(
        scenario=SCENARIO,
        config_prefix=config_prefix,
        config_path=str(config_path),
        legacy_git_sha=sha,
        launch_cmd=f"conda run -n helao python launch.py {config_prefix} --no-hot-reload",
        sequence_name="manual_acquire",
        sequence_params={
            "manual": True,
            "endpoint": "POST /ANDOR/acquire",
            "duration": duration,
            "external_trigger": external_trigger,
            "fast_samples_in": [],
        },
        capture_timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
        harness_version=HARNESS_VERSION,
        masked_hlo_columns=ANDOR_MASKED_HLO_COLUMNS,
        hlo_row_count_tolerance=ANDOR_HLO_ROW_COUNT_TOLERANCE,
        masked_meta_keys=ANDOR_ACT_YML_MASKED_META_KEYS,
        notes=combined_notes,
    ).save(out_dir)
    return out_dir


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m helao.hexagon.tests.smoke.golden_capture_andor",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--config-prefix", required=True)
    parser.add_argument(
        "--duration",
        type=float,
        default=1.0,
        help="acquire duration in (tick-)seconds; must be > 0 so the stream "
        "terminates on its own (default 1.0)",
    )
    parser.add_argument(
        "--external-trigger",
        action="store_true",
        help="use the camera's External Start trigger instead of the default "
        "software trigger (requires a 5V TTL source; the capture will hang "
        "without one -- leave unset for a bench/station canary)",
    )
    parser.add_argument("--settle-polls", type=int, default=3)
    parser.add_argument("--notes", default="")
    args = parser.parse_args(argv)

    if args.duration <= 0:
        parser.error(
            "--duration must be > 0 so acquire terminates on its own "
            "(duration <= 0 runs until cancelled and would hang the capture)"
        )

    assert_fresh(args.root)
    wait_for_server(ANDOR_HOST, ANDOR_PORT)
    acquire_action(
        args.config_prefix,
        duration=args.duration,
        external_trigger=args.external_trigger,
    )
    settle(args.root, settle_polls=args.settle_polls)
    out = snapshot(
        root=args.root,
        out_dir=args.out,
        config_prefix=args.config_prefix,
        duration=args.duration,
        external_trigger=args.external_trigger,
        notes=args.notes,
    )
    print(f"captured {SCENARIO} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
