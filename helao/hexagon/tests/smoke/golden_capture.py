"""Runtime golden-diff capture for the gamry hexagon canary (P3a special-split).

*** DRIVES THE REAL POTENTIOSTAT. THIS IS NOT A SIMULATION. ***

Step 0 of the parent task investigated whether ``run_OCV`` can produce data
under ``simulation: true``/``dummy: true`` with no real potentiostat attached,
and found: no. ``GamryDriver.__init__`` (helao/deploy/hte/drivers/pstat/gamry/
driver.py) unconditionally opens a real GamryCOM connection, and
``gamry_server2.py`` instantiates ``driver_classes=[GamryDriver]``
unconditionally -- there is no dummy/sim driver swap anywhere in this code
path. The config's ``dummy``/``simulation`` YAML keys are cosmetic (banner
color) for this canary only.

This capture rig is therefore an AT-STATION, REAL-HARDWARE gate. Before
running it, the operator MUST attach a dummy cell / calibration resistor to
the potentiostat -- ``run_OCV`` (open-circuit voltage monitoring, ``CellMon``,
non-perturbing) is safe against a dummy cell and never actively drives it,
but it still requires a live GamryCOM device to produce any data at all.

Standalone counterpart to ``harness.capture.snapshot_capture`` for the
orch-less, db-less gamry/gamryhex 2-server topology (PSTAT@8001 + ACTVIS@5001
only -- no ORCH, no DB). ``harness.capture``'s ``quiesce``/``orch_stopped``/
``db_drained`` assume an orchestrator + DB server and do not apply here (see
the rationale already recorded in ``gamryhex_canary.bat``, which hit the same
topology gap for the openapi-diff canary). Settling is done by polling
``harness.capture.runs_active_empty`` alone, the same primitive
``harness.capture.run_gm3`` uses for its own orch-less manual action.

Usage (AT-STATION, Windows, conda env ``helao``) -- ATTACH THE DUMMY CELL /
CAL RESISTOR FIRST:

    rmdir /s /q C:\\INST_hlo_golden               (or pick a fresh --root)
    conda run -n helao python launch.py gamrygold --no-hot-reload
    conda run -n helao python -m helao.hexagon.tests.smoke.golden_capture ^
        --config-prefix gamrygold --root C:\\INST_hlo_golden ^
        --out C:\\golden\\gamry

then terminate the launch, point ``--root``/``--config-prefix`` at a FRESH
throwaway root and ``gamrygoldhex``, capture again, and diff the two capture
directories with ``harness.parity``. ``golden_diff.bat`` automates exactly
this sequence.
"""

from __future__ import annotations

import argparse
import datetime
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests

from harness import HARNESS_VERSION
from harness.capture import assert_fresh, runs_active_empty, wait_for_server
from harness.manifest import ProvenanceManifest
from harness.treepass import PARITY_TOPS

PSTAT_HOST, PSTAT_PORT = "127.0.0.1", 8001

SCENARIO = "GM-OCV"

# helao/hexagon/tests/smoke/golden_capture.py -> repo root is 4 parents up
# (matches safe_root.py's own _repo_root()).
REPO_ROOT = Path(__file__).resolve().parents[4]
CONFIG_DIR = REPO_ROOT / "helao" / "deploy" / "hte" / "configs"

# helao/deploy/hte/drivers/pstat/gamry/dtaq.py: DTAQ_OCV.output_keys. These
# are raw ADC/COM samples pulled straight off the live potentiostat -- no
# seeded/deterministic sim values exist anywhere in this driver -- so their
# VALUES must be masked for parity; row counts are compared within a small
# tolerance (PumpEvents/dtaq-sink timing jitters run to run).
OCV_HLO_COLUMNS = [
    "t_s",
    "Ewe_V",
    "Vm",
    "Vsig",
    "Ach_V",
    "Overload_HEX",
    "StopTest",
    "unknown1",
    "unknown2",
    "unknown3",
]
OCV_MASKED_HLO_COLUMNS = {
    "*OCV*.hlo": OCV_HLO_COLUMNS,
    "*OCV*.hlo.json*": OCV_HLO_COLUMNS,
}
OCV_HLO_ROW_COUNT_TOLERANCE = {"*OCV*.hlo": 2, "*OCV*.hlo.json*": 2}
# Any csv postprocess derived from the masked columns above: line-count only.
OCV_CONTENT_MASKED_FILES = {"*.csv": "line-count"}

# KNOWN GAP -- NOT covered by masked_hlo_columns (.hlo files only).
# GamryExec._post_exec (gamry_server2.py ~283-330) writes data-derived
# summary values into the run's -act.yml action_params: t_s__mean_final,
# Ewe_V__mean_final, and (run_OCV only) has_bubble. These derive from the
# exact same live/unmasked measurement and are NOT normalized away by
# harness.yaml_pass.normalize_meta -- they are plain float/bool leaves under
# action_params, not uuids/timestamps/host-identity/dropped-env-keys (the
# §5.5 volatile lists there). harness.parity's diff_meta will therefore
# ALWAYS report a diff on these three keys between two independent captures,
# even against the identical dummy cell. This is intentionally left as a
# documented, eyeballed-by-the-operator expected diff (chosen over inventing
# a harness masking change): golden_diff.bat persists and prints the full
# parity report so the operator can confirm the ONLY diffs present are these
# three action_params keys (plus the already-masked hlo columns above). A
# bare "FAIL" from harness.parity must NOT be read as a regression without
# checking the report contents for anything beyond this list.
ACT_YML_KNOWN_EXPECTED_DIFF_KEYS = (
    "action_params.t_s__mean_final",
    "action_params.Ewe_V__mean_final",
    "action_params.has_bubble",
)


def run_ocv_action(host: str, port: int, tval_s: float, acq_s: float) -> dict:
    """POST /PSTAT/run_OCV and return the dispatch response (does not block)."""
    r = requests.post(
        f"http://{host}:{port}/PSTAT/run_OCV",
        params={"Tval__s": tval_s, "AcqInterval__s": acq_s},
        json={"fast_samples_in": []},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def settle(
    root: Path,
    settle_polls: int = 3,
    poll_s: float = 2.0,
    timeout_s: float = 300.0,
) -> None:
    """Settle with NO orch/DB in this topology: RUNS_ACTIVE emptying only.

    Mirrors ``harness.capture.run_gm3``'s manual-action settle (that scenario
    is also orch-less), generalized into consecutive-clean-poll form like
    ``harness.capture.quiesce``.
    """
    root = Path(root)
    t0 = time.time()
    settled = 0
    while time.time() - t0 < timeout_s:
        settled = settled + 1 if runs_active_empty(root) else 0
        if settled >= settle_polls:
            return
        time.sleep(poll_s)
    raise TimeoutError(f"{root} RUNS_ACTIVE did not settle after {timeout_s}s")


def snapshot(
    root: Path,
    out_dir: Path,
    config_prefix: str,
    tval_s: float,
    acq_s: float,
    notes: str = "",
) -> Path:
    """Copy PARITY_TOPS from ``root`` and write a provenance manifest.

    Refuses to overwrite an existing ``out_dir``, matching
    ``harness.capture.snapshot_capture``.
    """
    root, out_dir = Path(root), Path(out_dir)
    if out_dir.exists():
        raise FileExistsError(
            f"{out_dir} already exists; refusing to overwrite a capture"
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
        "NOT a simulation -- GamryDriver has no sim/dummy data path. "
        "KNOWN EXPECTED DIFF (not covered by masked_hlo_columns): -act.yml "
        f"{', '.join(ACT_YML_KNOWN_EXPECTED_DIFF_KEYS)} are data-derived from "
        "the live measurement and always differ between captures; eyeball "
        "the parity report to confirm no OTHER diffs are present."
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
            "endpoint": "POST /PSTAT/run_OCV",
            "Tval__s": tval_s,
            "AcqInterval__s": acq_s,
            "fast_samples_in": [],
        },
        capture_timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
        harness_version=HARNESS_VERSION,
        masked_hlo_columns=OCV_MASKED_HLO_COLUMNS,
        hlo_row_count_tolerance=OCV_HLO_ROW_COUNT_TOLERANCE,
        content_masked_files=OCV_CONTENT_MASKED_FILES,
        notes=combined_notes,
    ).save(out_dir)
    return out_dir


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m helao.hexagon.tests.smoke.golden_capture",
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
    parser.add_argument("--settle-polls", type=int, default=3)
    parser.add_argument("--notes", default="")
    args = parser.parse_args(argv)

    assert_fresh(args.root)
    wait_for_server(PSTAT_HOST, PSTAT_PORT)
    run_ocv_action(PSTAT_HOST, PSTAT_PORT, args.tval, args.acq)
    settle(args.root, settle_polls=args.settle_polls)
    out = snapshot(
        root=args.root,
        out_dir=args.out,
        config_prefix=args.config_prefix,
        tval_s=args.tval,
        acq_s=args.acq,
        notes=args.notes,
    )
    print(f"captured {SCENARIO} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
