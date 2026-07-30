"""Runtime golden-diff capture for the spec_server hexagon canary (P3a
special-split).

*** DRIVES THE REAL SM303 SPECTROMETER. THIS IS NOT A SIMULATION. ***

Like gamry/galil (and unlike sample), spec_server has NO sim/dummy data path:
``SM303.__init__``/``connect`` (helao/deploy/hte/drivers/spec/
spectral_products_driver.py) unconditionally loads the vendor ``SPdbUSBm.dll``
via ctypes and configures the physical device, and ``spec_server.py``
instantiates ``driver_classes=[SM303]`` unconditionally -- the config's
``dummy``/``simulation`` YAML keys are cosmetic (banner color) for this canary
only. So this capture rig is an AT-STATION, REAL-HARDWARE gate: the SM303
spectrometer must be attached (Windows, vendor DLL present) for ``acquire_spec``
to produce any data.

``acquire_spec`` (``POST /SPEC/acquire_spec``) with ``duration_sec <= 0``
acquires ONE spectrum (single-shot, non-perturbing -- it only reads the
detector; it drives nothing) and enqueues it to the default data sink as a
``.hlo``. That .hlo's body columns are ``epoch_s`` (wall clock), ``ch_0000``..
``ch_<n_pixels-1>`` (per-pixel detector intensities), ``error_code`` and
``peak_intensity`` -- ALL live/hardware-derived, none deterministic run-to-run.
Their VALUES are therefore masked via the manifest's ``masked_hlo_columns``
(structure, column presence, and the single-row count are still asserted). The
``.hlo`` HEADER carries ``wl`` (the pixel->wavelength table, ``app.driver.pxwl``)
which IS config/calibration-deterministic and is compared unmasked -- a real
diff there is a genuine regression.

Unlike gamry's ``run_OCV``, the ``acquire_spec`` endpoint writes NO data-derived
summary value back into ``action_params`` (only ``acquire_spec_adv`` stashes
``peak_intensity`` into params; ``acquire_spec`` does not), so ``-act.yml`` is
fully deterministic (params = ``int_time_ms``/``duration_sec``) and NO
``masked_meta_keys`` are needed. The only masking is the .hlo body columns.

Standalone counterpart to ``harness.capture.snapshot_capture`` for the
orch-less, db-less spec/spechex 2-server topology (SPEC@8011 + ACTVIS@5001 only
-- no ORCH, no DB), mirroring galil/gamry's ``golden_capture[_galil].py`` (see
those modules' docstrings for the full topology-gap rationale). The
hardware-agnostic settle / anti-vacuous-guard logic (``settle``,
``_run_artifacts``, ``_act_status_map``) and the production dispatch path
(``dispatch_action``) are IMPORTED from ``golden_capture.py`` rather than
re-implemented here; only the scenario-specific pieces (endpoint, masking,
manifest notes) are new. ``golden_capture.py`` itself is NOT modified.

Usage (AT-STATION, Windows, conda env ``helao``) -- ATTACH THE SPECTROMETER
FIRST:

    rmdir /s /q C:\\INST_hlo_golden               (or pick a fresh --root)
    conda run -n helao python launch.py specgold --no-hot-reload
    conda run -n helao python -m helao.hexagon.tests.smoke.golden_capture_spec ^
        --config-prefix specgold --root C:\\INST_hlo_golden ^
        --out C:\\golden\\spec

then terminate the launch, point ``--root``/``--config-prefix`` at a FRESH
throwaway root and ``specgoldhex``, capture again, and diff the two capture
directories with ``harness.parity``. ``spec_diff.bat`` automates exactly this
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

SPEC_HOST, SPEC_PORT = "127.0.0.1", 8011

SCENARIO = "GM-SPEC"

# hte canary configs (P3a/P3e relocation) live alongside this module, in
# its own configs/ sibling directory -- no longer under helao/deploy/hte/.
CONFIG_DIR = Path(__file__).resolve().parent / "configs"

# n_pixels from the SPEC config block (eche10.yml / spec*.yml). SM303.
# acquire_spec_adv builds the data dict as {"epoch_s": ..., "ch_0000": ...,
# ..., "ch_<N-1>": ..., "error_code": ..., "peak_intensity": ...}
# (spectral_products_driver.py ~L307: retdict.update({f"ch_{i:04}": x ...})).
N_PIXELS = 1024

# ALL acquire_spec .hlo body columns are live/hardware-derived (raw detector
# intensities + wall-clock epoch + data-derived peak/error), none seeded or
# deterministic -- so their VALUES are masked for parity. Column presence and
# the single-shot row count are still compared. The .hlo HEADER's `wl`
# (pixel->wavelength table) is config/calibration-deterministic and is NOT
# masked (a diff there is a real regression). Pattern "*.hlo" is safe: the only
# .hlo any acquire_spec capture emits is this spectrum file.
SPEC_HLO_COLUMNS = ["epoch_s", "error_code", "peak_intensity"] + [
    f"ch_{i:04}" for i in range(N_PIXELS)
]
SPEC_MASKED_HLO_COLUMNS = {
    "*.hlo": SPEC_HLO_COLUMNS,
    "*.hlo.json*": SPEC_HLO_COLUMNS,
}
# Single-shot acquire (duration_sec <= 0) writes exactly ONE row on both sides
# -- exact row-count match required (empty tolerance dict == 0).
SPEC_HLO_ROW_COUNT_TOLERANCE: dict = {}
# acquire_spec writes no data-derived value back into action_params (only
# acquire_spec_adv does); -act.yml is fully deterministic -> nothing to mask.
SPEC_ACT_YML_MASKED_META_KEYS: dict = {}


def acquire_spec_action(
    config_prefix: str, int_time_ms: int = 35, duration_sec: float = -1
) -> dict:
    """Run /SPEC/acquire_spec via ``async_action_dispatcher`` (production
    action-dispatch path -- RPC then HTTP, full action envelope).

    ``duration_sec <= 0`` acquires a single spectrum (non-perturbing: reads the
    detector only, drives nothing). ``allow_no_sample: true`` in the SPEC config
    means no ``fast_samples_in`` is required (the endpoint's ``Body([])``
    default applies).
    """
    return dispatch_action(
        config_prefix,
        "SPEC",
        "acquire_spec",
        {"int_time_ms": int_time_ms, "duration_sec": duration_sec},
        # single acquisition is quick, but leave headroom for the endpoint's
        # trailing 1s dangling-data drain + finish().
        timeout=60,
    )


def snapshot(
    root: Path,
    out_dir: Path,
    config_prefix: str,
    int_time_ms: int,
    duration_sec: float,
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
    # Anti-vacuous-pass guard (shared convention with gamry/galil/sample): an
    # empty capture (no action output) compares to nothing and passes parity
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
            f"[golden_capture_spec] WARNING: {len(errored)} action(s) ERRORED "
            f"and were still captured: {errored}. An errored run is NOT a valid "
            "parity baseline. Check the -act.yml error fields and the SPEC log "
            "before trusting a PASS."
        )
    if not hlos:
        print(
            f"[golden_capture_spec] WARNING: no .hlo captured under {root} -- "
            "acquire_spec produced no spectrum data file. Parity will compare "
            "-act.yml metadata only, NOT the hlo data-write path. Verify the "
            "SM303 is attached and read_data returned a spectrum."
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
        "REAL-HARDWARE acquire_spec capture (SM303 spectrometer attached); NOT "
        "a simulation -- SM303 has no sim/dummy data path. The .hlo body columns "
        "epoch_s/ch_NNNN/error_code/peak_intensity are live detector data and "
        "are masked via masked_hlo_columns so parity is a clean PASS when only "
        "they differ; the .hlo header `wl` (pixel->wavelength table) is "
        "config-deterministic and compared unmasked."
    )
    if notes:
        combined_notes = f"{combined_notes} {notes}"
    ProvenanceManifest(
        scenario=SCENARIO,
        config_prefix=config_prefix,
        config_path=str(config_path),
        legacy_git_sha=sha,
        launch_cmd=f'conda run -n helao python launch.py "{config_path}" --no-hot-reload',
        sequence_name="manual_acquire_spec",
        sequence_params={
            "manual": True,
            "endpoint": "POST /SPEC/acquire_spec",
            "int_time_ms": int_time_ms,
            "duration_sec": duration_sec,
            "fast_samples_in": [],
        },
        capture_timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
        harness_version=HARNESS_VERSION,
        masked_hlo_columns=SPEC_MASKED_HLO_COLUMNS,
        hlo_row_count_tolerance=SPEC_HLO_ROW_COUNT_TOLERANCE,
        masked_meta_keys=SPEC_ACT_YML_MASKED_META_KEYS,
        notes=combined_notes,
    ).save(out_dir)
    return out_dir


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m helao.hexagon.tests.smoke.golden_capture_spec",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--config-prefix", required=True)
    parser.add_argument(
        "--int-time-ms", type=int, default=35, help="int_time_ms (default 35)"
    )
    parser.add_argument(
        "--duration-sec",
        type=float,
        default=-1,
        help="duration_sec; <=0 acquires a single spectrum (default -1)",
    )
    parser.add_argument("--settle-polls", type=int, default=3)
    parser.add_argument("--notes", default="")
    args = parser.parse_args(argv)

    assert_fresh(args.root)
    wait_for_server(SPEC_HOST, SPEC_PORT)
    acquire_spec_action(args.config_prefix, args.int_time_ms, args.duration_sec)
    settle(args.root, settle_polls=args.settle_polls)
    out = snapshot(
        root=args.root,
        out_dir=args.out,
        config_prefix=args.config_prefix,
        int_time_ms=args.int_time_ms,
        duration_sec=args.duration_sec,
        notes=args.notes,
    )
    print(f"captured {SCENARIO} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
