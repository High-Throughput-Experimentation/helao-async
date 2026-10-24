"""Linux unit tests for golden_capture_syringe.py's PURE logic (no server, no HTTP).

Exercises only:
  - the PARITY_TOPS snapshot copy + provenance.yml round-trip (``snapshot``),
    including the explicit MASKING=NONE decision (both masked_hlo_columns and
    masked_meta_keys are empty because get_present_volume writes a
    config-deterministic value -- 0.0 on a fresh idle pump -- not a live device
    reading; masking it would only weaken the parity check)

The (hardware-independent) POST to ``/WORKSYRINGE/get_present_volume`` (and
``check_device_open``'s ``/get_status`` probe) is NOT exercised here -- that
only runs against a launched server (see golden_capture_syringe.py docstrings).

Run:

    conda run -n helao python -m pytest helao/hexagon/tests/smoke/test_golden_capture_syringe.py -q
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from harness.manifest import ProvenanceManifest
from helao.hexagon.tests.smoke.golden_capture_syringe import (
    SCENARIO,
    SYRVOL_MASKED_HLO_COLUMNS,
    SYRVOL_MASKED_META_KEYS,
    snapshot,
)


def test_snapshot_copies_parity_tops_and_writes_roundtrippable_provenance():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        (root / "RUNS_FINISHED" / "x").mkdir(parents=True)
        (root / "RUNS_FINISHED" / "x" / "a-act.yml").write_text(
            "file_type: action\n", encoding="utf-8"
        )
        # include a .hlo too (the full happy path: metadata + data file --
        # get_present_volume ALWAYS enqueues one data row)
        (root / "RUNS_FINISHED" / "x" / "get_present_volume-0.hlo").write_text(
            "hlo_version: x\n%%\n", encoding="utf-8"
        )
        (root / "LOGS").mkdir(parents=True)
        (root / "LOGS" / "WORKSYRINGE.log").write_text("not captured", encoding="utf-8")

        out = Path(td) / "golden" / "run1"
        snapshot(root=root, out_dir=out, config_prefix="syringegold")

        assert (out / "root" / "RUNS_FINISHED" / "x" / "a-act.yml").exists()
        assert not (out / "root" / "LOGS").exists()  # non-parity top excluded
        assert (out / "provenance.yml").exists()

        manifest = ProvenanceManifest.load(out)
        assert manifest.scenario == SCENARIO
        assert manifest.config_prefix == "syringegold"
        assert manifest.config_path.replace("\\", "/").endswith(
            "helao/hexagon/tests/smoke/configs/syringegold.yml"
        )
        # MASKING = NONE is the load-bearing decision for this scenario: the
        # present_volume_ul value is config-deterministic on a fresh idle pump
        # (0.0), NOT a live/nondeterministic device reading, so nothing is
        # masked. A future edit that adds masking must consciously flip this.
        assert manifest.masked_hlo_columns == {}
        assert manifest.masked_meta_keys == {}
        assert SYRVOL_MASKED_HLO_COLUMNS == {}
        assert SYRVOL_MASKED_META_KEYS == {}


def _write_action(root: Path, status: str = "finished", with_hlo: bool = True) -> Path:
    """A RUNS_DIAG tree with one manual action -act.yml at ``status`` (+ .hlo)."""
    d = root / "RUNS_DIAG" / "25.28" / "0716" / "0__0__WORKSYRINGE__get_present_volume"
    d.mkdir(parents=True)
    (d / "250716.131421-act.yml").write_text(
        f"file_type: action\naction_status:\n  - {status}\n", encoding="utf-8"
    )
    if with_hlo:
        (d / "get_present_volume-0.hlo").write_text(
            "hlo_version: x\n%%\n", encoding="utf-8"
        )
    return d


def test_snapshot_refuses_to_overwrite_existing_out_dir():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        _write_action(root, status="finished", with_hlo=True)
        out = Path(td) / "golden" / "run1"
        snapshot(root=root, out_dir=out, config_prefix="syringegold")
        try:
            snapshot(root=root, out_dir=out, config_prefix="syringegold")
        except FileExistsError:
            pass
        else:
            raise AssertionError(
                "snapshot() should refuse to overwrite an existing out_dir"
            )


def test_snapshot_refuses_empty_capture():
    """The false-PASS guard: a root with no -act.yml/.hlo must NOT be captured
    (an empty golden set compares to nothing and passes parity vacuously)."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        (root / "RUNS_DIAG").mkdir(parents=True)  # present but empty (no data)
        out = Path(td) / "golden" / "run1"
        try:
            snapshot(root=root, out_dir=out, config_prefix="syringegold")
        except RuntimeError:
            pass
        else:
            raise AssertionError("snapshot() must refuse an empty (no-output) capture")
        assert not out.exists()  # nothing written on refusal


def test_snapshot_succeeds_with_terminal_act_yml_only():
    """snapshot captures a finished -act.yml-only tree (warns about the missing
    .hlo but does not refuse -- the -act.yml is still a real parity comparison).
    For get_present_volume a .hlo IS normally expected, so the warning matters,
    but its absence is not a hard failure."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        _write_action(root, status="finished", with_hlo=False)
        out = Path(td) / "golden" / "run1"
        snapshot(root=root, out_dir=out, config_prefix="syringegold")
        assert (out / "provenance.yml").exists()
