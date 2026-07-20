"""Linux unit tests for golden_capture_sample.py's PURE logic (no server, no
HTTP, no hardware).

Exercises only:
  - the PARITY_TOPS snapshot copy + provenance.yml round-trip (``snapshot``)
  - the shared (gamry-authored, imported here) ``settle`` helper, applied to
    a sample_server-shaped RUNS_DIAG tree

The real POST to ``/SAMPLE/get_loaded_positions`` is NOT exercised here --
that requires a running sample_server (see golden_capture_sample.py /
sample_diff.sh docstrings). Unlike the galil/gamry canaries, this one needs
NO hardware to run end-to-end (Archive is pure software), but this module
still deliberately stays server-free so it runs anywhere, including CI.

Written as plain assert-based ``test_*`` functions with no ``import pytest``
(mirrors ``test_golden_capture.py``/``test_golden_capture_galil.py`` -- this
repo's conda ``helao`` env does not currently have the pytest package
installed), so this module is runnable two ways:

    conda run -n helao python -m pytest helao/hexagon/tests/smoke/test_golden_capture_sample.py -q
    conda run -n helao python -m helao.hexagon.tests.smoke.test_golden_capture_sample
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from harness.manifest import ProvenanceManifest

from helao.hexagon.tests.smoke.golden_capture import settle
from helao.hexagon.tests.smoke.golden_capture_sample import (
    POS_ACT_YML_MASKED_META_KEYS,
    POS_HLO_ROW_COUNT_TOLERANCE,
    POS_MASKED_HLO_COLUMNS,
    SCENARIO,
    snapshot,
)


def _write_action(root: Path, status: str = "finished", with_hlo: bool = False) -> Path:
    """A RUNS_DIAG tree with one manual get_loaded_positions -act.yml at
    ``status``. ``with_hlo=False`` by default -- this scenario never enqueues
    a .hlo (metadata-only), unlike galil/gamry's data-producing scenarios."""
    d = root / "RUNS_DIAG" / "25.28" / "0716" / "0__0__SAMPLE__get_loaded_positions"
    d.mkdir(parents=True)
    (d / "250716.131421-act.yml").write_text(
        f"file_type: action\naction_status:\n  - {status}\n"
    )
    if with_hlo:
        (d / "get_loaded_positions-0.hlo").write_text("hlo_version: x\n%%\n")
    return d


def test_snapshot_copies_parity_tops_and_writes_roundtrippable_provenance():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        _write_action(root, status="finished", with_hlo=False)
        (root / "LOGS").mkdir(parents=True)
        (root / "LOGS" / "SAMPLE.log").write_text("not captured")

        out = Path(td) / "golden" / "run1"
        snapshot(root=root, out_dir=out, config_prefix="samplegold")

        assert (
            out
            / "root"
            / "RUNS_DIAG"
            / "25.28"
            / "0716"
            / "0__0__SAMPLE__get_loaded_positions"
            / "250716.131421-act.yml"
        ).exists()
        assert not (out / "root" / "LOGS").exists()  # non-parity top excluded
        assert (out / "provenance.yml").exists()

        manifest = ProvenanceManifest.load(out)
        assert manifest.scenario == SCENARIO
        assert manifest.config_prefix == "samplegold"
        assert manifest.config_path.replace("\\", "/").endswith(
            "helao/deploy/hte/configs/samplegold.yml"
        )
        # No volatile action_params fields for this scenario (Step 0):
        # _positions/_tray_pos/_custom_pos are fully config-derived on a
        # fresh root -- no masking anywhere.
        assert manifest.masked_hlo_columns == POS_MASKED_HLO_COLUMNS == {}
        assert manifest.hlo_row_count_tolerance == POS_HLO_ROW_COUNT_TOLERANCE == {}
        assert manifest.masked_meta_keys == POS_ACT_YML_MASKED_META_KEYS == {}


def test_snapshot_refuses_to_overwrite_existing_out_dir():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        _write_action(root, status="finished")
        out = Path(td) / "golden" / "run1"
        snapshot(root=root, out_dir=out, config_prefix="samplegold")
        try:
            snapshot(root=root, out_dir=out, config_prefix="samplegold")
        except FileExistsError:
            pass
        else:
            raise AssertionError(
                "snapshot() should refuse to overwrite an existing out_dir"
            )


def test_snapshot_refuses_empty_capture():
    """The false-PASS guard: a root with no -act.yml must NOT be captured
    (an empty golden set compares to nothing and passes parity vacuously)."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        (root / "RUNS_DIAG").mkdir(parents=True)  # present but empty (no data)
        out = Path(td) / "golden" / "run1"
        try:
            snapshot(root=root, out_dir=out, config_prefix="samplegold")
        except RuntimeError:
            pass
        else:
            raise AssertionError("snapshot() must refuse an empty (no-output) capture")
        assert not out.exists()  # nothing written on refusal


def test_snapshot_succeeds_with_no_hlo_at_all():
    """The EXPECTED happy path for this metadata-only scenario: a terminal
    -act.yml with NO .hlo anywhere is a normal, complete capture (not a
    warning-worthy gap, unlike gamry/galil's data-producing scenarios)."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        _write_action(root, status="finished", with_hlo=False)
        out = Path(td) / "golden" / "run1"
        snapshot(root=root, out_dir=out, config_prefix="samplegold")
        assert (out / "provenance.yml").exists()
        assert not any((out / "root").rglob("*.hlo"))


def test_settle_returns_once_action_artifacts_are_complete_and_stable():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        _write_action(root, status="finished")
        settle(root, settle_polls=2, poll_s=0.01, timeout_s=5.0)


def test_settle_times_out_when_no_artifacts_are_written():
    """The action never wrote output (errored / never dispatched): settle
    must raise, not silently return -- this is what prevents the
    empty-capture false PASS."""
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
    server mid-query."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        _write_action(root, status="active")  # still running
        try:
            settle(root, settle_polls=2, poll_s=0.01, timeout_s=0.05)
        except TimeoutError:
            pass
        else:
            raise AssertionError("settle() must not return while status is 'active'")


ALL_TESTS = [
    test_snapshot_copies_parity_tops_and_writes_roundtrippable_provenance,
    test_snapshot_refuses_to_overwrite_existing_out_dir,
    test_snapshot_refuses_empty_capture,
    test_snapshot_succeeds_with_no_hlo_at_all,
    test_settle_returns_once_action_artifacts_are_complete_and_stable,
    test_settle_times_out_when_no_artifacts_are_written,
    test_settle_does_not_return_while_action_active,
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
