"""Linux unit tests for golden_capture_tec.py's PURE logic (no server, no HTTP).

Exercises only:
  - the PARITY_TOPS snapshot copy + provenance.yml round-trip (``snapshot``)

The real-hardware POST to ``/TEC/record_tec`` (and ``verify_device_open``'s
``/get_status`` probe) is NOT exercised here -- that only runs at-station
(see golden_capture_tec.py docstrings).

Run:

    conda run -n helao python -m pytest helao/hexagon/tests/smoke/test_golden_capture_tec.py -q
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from harness.manifest import ProvenanceManifest
from helao.hexagon.tests.smoke.golden_capture_tec import (
    SCENARIO,
    TEC_HLO_COLUMNS,
    TEC_HLO_ROW_COUNT_TOLERANCE,
    TEC_MASKED_HLO_COLUMNS,
    snapshot,
)


def test_snapshot_copies_parity_tops_and_writes_roundtrippable_provenance():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        (root / "RUNS_FINISHED" / "x").mkdir(parents=True)
        (root / "RUNS_FINISHED" / "x" / "a-act.yml").write_text(
            "file_type: action\n", encoding="utf-8"
        )
        # include a .hlo too (the full happy path: metadata + data file)
        (root / "RUNS_FINISHED" / "x" / "record_tec-0.hlo").write_text(
            "hlo_version: x\n%%\n", encoding="utf-8"
        )
        (root / "LOGS").mkdir(parents=True)
        (root / "LOGS" / "TEC.log").write_text("not captured", encoding="utf-8")

        out = Path(td) / "golden" / "run1"
        snapshot(
            root=root,
            out_dir=out,
            config_prefix="tecgold",
            duration_s=3.0,
            acquisition_rate=0.2,
        )

        assert (out / "root" / "RUNS_FINISHED" / "x" / "a-act.yml").exists()
        assert not (out / "root" / "LOGS").exists()  # non-parity top excluded
        assert (out / "provenance.yml").exists()

        manifest = ProvenanceManifest.load(out)
        assert manifest.scenario == SCENARIO
        assert manifest.config_prefix == "tecgold"
        assert manifest.config_path.replace("\\", "/").endswith(
            "helao/hexagon/tests/smoke/configs/tecgold.yml"
        )
        assert manifest.masked_hlo_columns == TEC_MASKED_HLO_COLUMNS
        assert manifest.hlo_row_count_tolerance == TEC_HLO_ROW_COUNT_TOLERANCE
        assert set(TEC_HLO_COLUMNS) == set(
            manifest.masked_hlo_columns["*record_tec*.hlo"]
        )


def _write_action(root: Path, status: str = "finished", with_hlo: bool = True) -> Path:
    """A RUNS_DIAG tree with one manual action -act.yml at ``status`` (+ .hlo)."""
    d = root / "RUNS_DIAG" / "25.28" / "0716" / "0__0__TEC__record_tec"
    d.mkdir(parents=True)
    (d / "250716.131421-act.yml").write_text(
        f"file_type: action\naction_status:\n  - {status}\n", encoding="utf-8"
    )
    if with_hlo:
        (d / "record_tec-0.hlo").write_text("hlo_version: x\n%%\n", encoding="utf-8")
    return d


def test_snapshot_refuses_to_overwrite_existing_out_dir():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        _write_action(root, status="finished", with_hlo=True)
        out = Path(td) / "golden" / "run1"
        snapshot(
            root=root,
            out_dir=out,
            config_prefix="tecgold",
            duration_s=3.0,
            acquisition_rate=0.2,
        )
        try:
            snapshot(
                root=root,
                out_dir=out,
                config_prefix="tecgold",
                duration_s=3.0,
                acquisition_rate=0.2,
            )
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
            snapshot(
                root=root,
                out_dir=out,
                config_prefix="tecgold",
                duration_s=3.0,
                acquisition_rate=0.2,
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("snapshot() must refuse an empty (no-output) capture")
        assert not out.exists()  # nothing written on refusal


def test_snapshot_succeeds_with_terminal_act_yml_only():
    """snapshot captures a finished -act.yml-only tree (warns about the
    missing .hlo but does not refuse -- the -act.yml is still a real parity
    comparison)."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        _write_action(root, status="finished", with_hlo=False)
        out = Path(td) / "golden" / "run1"
        snapshot(
            root=root,
            out_dir=out,
            config_prefix="tecgold",
            duration_s=3.0,
            acquisition_rate=0.2,
        )
        assert (out / "provenance.yml").exists()
