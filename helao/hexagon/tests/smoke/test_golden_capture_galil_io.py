"""Linux unit tests for golden_capture_galil_io.py's PURE logic (no server,
no HTTP).

Exercises only:
  - the PARITY_TOPS snapshot copy + provenance.yml round-trip (``snapshot``)
  - the shared (gamry-authored, imported here) ``settle`` helper, applied to
    a galil_io-shaped RUNS_DIAG tree

The real-hardware POST to ``/IO/get_digital_in`` (and ``verify_device_open``'s
``/get_status`` probe) is NOT exercised here -- that only runs at-station
(see golden_capture_galil_io.py / galilio_diff.bat docstrings).

Written as plain assert-based ``test_*`` functions with no ``import pytest``
(mirrors ``test_golden_capture_galil.py`` -- this repo's conda ``helao`` env
does not currently have the pytest package installed), so this module is
runnable two ways:

    conda run -n helao python -m pytest helao/hexagon/tests/smoke/test_golden_capture_galil_io.py -q
    conda run -n helao python -m helao.hexagon.tests.smoke.test_golden_capture_galil_io
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from harness.manifest import ProvenanceManifest

from helao.hexagon.tests.smoke.golden_capture import settle
from helao.hexagon.tests.smoke.golden_capture_galil_io import (
    DIN_HLO_COLUMNS,
    DIN_HLO_ROW_COUNT_TOLERANCE,
    DIN_MASKED_HLO_COLUMNS,
    DI_ITEM,
    SCENARIO,
    snapshot,
)


def test_snapshot_copies_parity_tops_and_writes_roundtrippable_provenance():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        (root / "RUNS_FINISHED" / "x").mkdir(parents=True)
        (root / "RUNS_FINISHED" / "x" / "a-act.yml").write_text("file_type: action\n")
        # include a .hlo too (the full happy path: metadata + data file)
        (root / "RUNS_FINISHED" / "x" / "get_di-0.hlo").write_text(
            "hlo_version: x\n%%\n"
        )
        (root / "LOGS").mkdir(parents=True)
        (root / "LOGS" / "IO.log").write_text("not captured")

        out = Path(td) / "golden" / "run1"
        snapshot(root=root, out_dir=out, config_prefix="galiliogold")

        assert (out / "root" / "RUNS_FINISHED" / "x" / "a-act.yml").exists()
        assert not (out / "root" / "LOGS").exists()  # non-parity top excluded
        assert (out / "provenance.yml").exists()

        manifest = ProvenanceManifest.load(out)
        assert manifest.scenario == SCENARIO
        assert manifest.config_prefix == "galiliogold"
        assert manifest.config_path.replace("\\", "/").endswith(
            "helao/hexagon/tests/smoke/configs/galiliogold.yml"
        )
        assert manifest.masked_hlo_columns == DIN_MASKED_HLO_COLUMNS
        assert manifest.hlo_row_count_tolerance == DIN_HLO_ROW_COUNT_TOLERANCE
        assert set(DIN_HLO_COLUMNS) == set(manifest.masked_hlo_columns["*get_di*.hlo"])
        # "name"/"port"/"type"/"error_code" are config-deterministic and must
        # NOT be masked; only "value" (the live digital-input reading) is.
        assert "name" not in manifest.masked_hlo_columns["*get_di*.hlo"]
        assert "port" not in manifest.masked_hlo_columns["*get_di*.hlo"]
        assert manifest.sequence_params["di_item"] == DI_ITEM


def _write_action(root: Path, status: str = "finished", with_hlo: bool = True) -> Path:
    """A RUNS_DIAG tree with one manual action -act.yml at ``status`` (+ .hlo)."""
    d = root / "RUNS_DIAG" / "25.28" / "0716" / "0__0__IO__get_di"
    d.mkdir(parents=True)
    (d / "250716.131421-act.yml").write_text(
        f"file_type: action\naction_status:\n  - {status}\n"
    )
    if with_hlo:
        (d / "get_di-0.hlo").write_text("hlo_version: x\n%%\n")
    return d


def test_snapshot_refuses_to_overwrite_existing_out_dir():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        _write_action(root, status="finished", with_hlo=True)
        out = Path(td) / "golden" / "run1"
        snapshot(root=root, out_dir=out, config_prefix="galiliogold")
        try:
            snapshot(root=root, out_dir=out, config_prefix="galiliogold")
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
            snapshot(root=root, out_dir=out, config_prefix="galiliogold")
        except RuntimeError:
            pass
        else:
            raise AssertionError("snapshot() must refuse an empty (no-output) capture")
        assert not out.exists()  # nothing written on refusal


def test_settle_returns_once_action_artifacts_are_complete_and_stable():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        _write_action(root, status="finished", with_hlo=True)
        settle(root, settle_polls=2, poll_s=0.01, timeout_s=5.0)


def test_settle_times_out_when_no_artifacts_are_written():
    """The action never wrote output (errored / no data): settle must raise,
    not silently return -- this is what prevents the empty-capture false PASS."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        root.mkdir()  # empty root, nothing ever written
        try:
            settle(root, settle_polls=2, poll_s=0.01, timeout_s=0.05)
        except TimeoutError:
            pass
        else:
            raise AssertionError("settle() should time out when no artifacts appear")


def test_settle_does_not_return_while_action_active():
    """-act.yml exists at init with status 'active' (base.py:1029). settle
    must NOT return on file existence -- else it snapshots + kills the
    server mid-read."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        _write_action(root, status="active", with_hlo=False)  # still running
        try:
            settle(root, settle_polls=2, poll_s=0.01, timeout_s=0.05)
        except TimeoutError:
            pass
        else:
            raise AssertionError("settle() must not return while status is 'active'")


def test_snapshot_succeeds_with_terminal_act_yml_only():
    """snapshot captures a finished -act.yml-only tree (warns about the
    missing .hlo but does not refuse -- the -act.yml is still a real parity
    comparison)."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        _write_action(root, status="finished", with_hlo=False)
        out = Path(td) / "golden" / "run1"
        snapshot(root=root, out_dir=out, config_prefix="galiliogold")
        assert (out / "provenance.yml").exists()


ALL_TESTS = [
    test_snapshot_copies_parity_tops_and_writes_roundtrippable_provenance,
    test_snapshot_refuses_to_overwrite_existing_out_dir,
    test_snapshot_refuses_empty_capture,
    test_settle_returns_once_action_artifacts_are_complete_and_stable,
    test_settle_times_out_when_no_artifacts_are_written,
    test_settle_does_not_return_while_action_active,
    test_snapshot_succeeds_with_terminal_act_yml_only,
]


def main() -> int:
    failures = 0
    for fn in ALL_TESTS:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 -- report every failure, keep going
            failures += 1
            print(f"FAIL {fn.__name__}: {exc}")
        else:
            print(f"PASS {fn.__name__}")
    print(f"{len(ALL_TESTS) - failures}/{len(ALL_TESTS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
