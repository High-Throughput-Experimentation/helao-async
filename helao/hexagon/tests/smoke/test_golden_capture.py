"""Linux unit tests for golden_capture.py's PURE logic (no server, no HTTP).

Exercises only:
  - the PARITY_TOPS snapshot copy + provenance.yml round-trip (``snapshot``)
  - the RUNS_ACTIVE-based settle helper (``settle``), with no orch/DB

The real-hardware POST to ``/PSTAT/run_OCV`` is NOT exercised here -- that
only runs at-station (see golden_capture.py / golden_diff.bat docstrings).

Written as plain assert-based ``test_*`` functions with no ``import pytest``
(this repo's conda ``helao`` env does not currently have the pytest package
installed -- see CLAUDE.md: "There is no pytest harness and no project-wide
build step"), so this module is runnable two ways:

    conda run -n helao python -m pytest helao/hexagon/tests/smoke/test_golden_capture.py -q
    conda run -n helao python -m helao.hexagon.tests.smoke.test_golden_capture

Both simply call the ``test_*`` functions below; the ``__main__`` block
reports PASS/FAIL per function without requiring pytest to be installed.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from harness.manifest import ProvenanceManifest

from helao.hexagon.tests.smoke.golden_capture import (
    OCV_ACT_YML_MASKED_META_KEYS,
    OCV_HLO_COLUMNS,
    OCV_HLO_ROW_COUNT_TOLERANCE,
    OCV_MASKED_HLO_COLUMNS,
    SCENARIO,
    settle,
    snapshot,
)


def test_snapshot_copies_parity_tops_and_writes_roundtrippable_provenance():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        (root / "RUNS_FINISHED" / "x").mkdir(parents=True)
        (root / "RUNS_FINISHED" / "x" / "a-act.yml").write_text("file_type: action\n")
        # a .hlo is required for the anti-vacuous-pass guard to accept the tree
        (root / "RUNS_FINISHED" / "x" / "OCV-0.hlo").write_text("hlo_version: x\n%%\n")
        (root / "LOGS").mkdir(parents=True)
        (root / "LOGS" / "PSTAT.log").write_text("not captured")

        out = Path(td) / "golden" / "run1"
        snapshot(
            root=root,
            out_dir=out,
            config_prefix="gamrygold",
            tval_s=3.0,
            acq_s=0.1,
        )

        assert (out / "root" / "RUNS_FINISHED" / "x" / "a-act.yml").exists()
        assert not (out / "root" / "LOGS").exists()  # non-parity top excluded
        assert (out / "provenance.yml").exists()

        manifest = ProvenanceManifest.load(out)
        assert manifest.scenario == SCENARIO
        assert manifest.config_prefix == "gamrygold"
        assert manifest.config_path.replace("\\", "/").endswith(
            "helao/deploy/hte/configs/gamrygold.yml"
        )
        assert manifest.masked_hlo_columns == OCV_MASKED_HLO_COLUMNS
        assert manifest.hlo_row_count_tolerance == OCV_HLO_ROW_COUNT_TOLERANCE
        assert set(OCV_HLO_COLUMNS) == set(manifest.masked_hlo_columns["*OCV*.hlo"])
        # The data-derived -act.yml action_params are masked via masked_meta_keys
        # (manifest-driven meta-value mask) so parity is a clean PASS when only
        # those values differ; assert the manifest carries the mask + round-trips.
        assert manifest.masked_meta_keys == OCV_ACT_YML_MASKED_META_KEYS
        assert manifest.masked_meta_keys_for("run_OCV__0-act.yml") == [
            "action_params.t_s__mean_final",
            "action_params.Ewe_V__mean_final",
            "action_params.has_bubble",
        ]


def _write_completed_run(root: Path) -> None:
    """A RUNS_DIAG tree with one completed manual action: -act.yml + .hlo."""
    d = root / "RUNS_DIAG" / "25.28" / "0716" / "0__0__PSTAT__run_OCV"
    d.mkdir(parents=True)
    (d / "250716.131421-act.yml").write_text("file_type: action\n")
    (d / "PSTAT-OCV-0.hlo").write_text("hlo_version: x\n%%\n")


def test_snapshot_refuses_to_overwrite_existing_out_dir():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        _write_completed_run(root)
        out = Path(td) / "golden" / "run1"
        snapshot(
            root=root, out_dir=out, config_prefix="gamrygold", tval_s=3.0, acq_s=0.1
        )
        try:
            snapshot(
                root=root,
                out_dir=out,
                config_prefix="gamrygold",
                tval_s=3.0,
                acq_s=0.1,
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
                root=root, out_dir=out, config_prefix="gamrygold", tval_s=3.0, acq_s=0.1
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("snapshot() must refuse an empty (no-output) capture")
        assert not out.exists()  # nothing written on refusal


def test_settle_returns_once_action_artifacts_are_complete_and_stable():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        _write_completed_run(root)  # -act.yml + .hlo present, RUNS_ACTIVE absent
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


ALL_TESTS = [
    test_snapshot_copies_parity_tops_and_writes_roundtrippable_provenance,
    test_snapshot_refuses_to_overwrite_existing_out_dir,
    test_snapshot_refuses_empty_capture,
    test_settle_returns_once_action_artifacts_are_complete_and_stable,
    test_settle_times_out_when_no_artifacts_are_written,
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
