"""Linux unit tests for golden_capture_mfc.py's PURE logic (no server, no HTTP).

Exercises only:
  - the PARITY_TOPS snapshot copy + provenance.yml round-trip (``snapshot``)
  - the masked-column set (the live sensor/clock columns are masked; the
    config-deterministic categorical columns gas/control_point are NOT)
  - the masked_meta_keys lever (action_params.total_scc is masked)
  - the shared (gamry-authored, imported here) ``settle`` helper, applied to an
    mfc-shaped RUNS_DIAG tree

The real-hardware POST to ``/MFC/acquire_flowrate`` is NOT exercised here --
that only runs at-station with the Alicat MFC attached on COM9 (see
golden_capture_mfc.py / mfc_diff.bat docstrings).

Written as plain assert-based ``test_*`` functions with no ``import pytest``
(mirrors test_golden_capture_spec.py -- this repo's conda ``helao`` env does not
currently have the pytest package installed), so this module is runnable two
ways:

    conda run -n helao python -m pytest helao/hexagon/tests/smoke/test_golden_capture_mfc.py -q
    conda run -n helao python -m helao.hexagon.tests.smoke.test_golden_capture_mfc
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from harness.manifest import ProvenanceManifest

from helao.hexagon.tests.smoke.golden_capture import settle
from helao.hexagon.tests.smoke.golden_capture_mfc import (
    DEVICE_NAME,
    MFC_ACT_YML_MASKED_META_KEYS,
    MFC_HLO_COLUMNS,
    MFC_MASKED_HLO_COLUMNS,
    SCENARIO,
    snapshot,
)


def test_masked_columns_cover_live_telemetry_but_not_deterministic_categoricals():
    cols = set(MFC_MASKED_HLO_COLUMNS["*.hlo"])
    # every live/hardware-derived sensor + clock column is masked...
    assert "epoch_s" in cols
    assert "acquire_time" in cols
    assert "pressure" in cols
    assert "temperature" in cols
    assert "volumetric_flow" in cols
    assert "mass_flow" in cols
    assert "setpoint" in cols
    # ...including the totalizer-only column (harmless no-op mask elsewhere)
    assert "total flow" in cols
    # the config-deterministic categorical columns are NOT masked -- they are the
    # deterministic anchors (the .hlo analogue of spec's `wl`); a diff there is a
    # real regression.
    assert "gas" not in cols
    assert "control_point" not in cols
    # both fnmatch patterns carry the identical column set
    assert MFC_MASKED_HLO_COLUMNS["*.hlo.json*"] == MFC_HLO_COLUMNS


def test_masked_meta_keys_mask_total_scc():
    # MfcExec._post_exec writes the data-derived action_params.total_scc back
    # into -act.yml; it must be masked (the meta-side analogue of a live column).
    keys = MFC_ACT_YML_MASKED_META_KEYS["*-act.yml"]
    assert "action_params.total_scc" in keys


def test_snapshot_copies_parity_tops_and_writes_roundtrippable_provenance():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        (root / "RUNS_FINISHED" / "x").mkdir(parents=True)
        (root / "RUNS_FINISHED" / "x" / "a-act.yml").write_text("file_type: action\n")
        # include a .hlo too (the full happy path: metadata + telemetry file)
        (root / "RUNS_FINISHED" / "x" / "acquire_flowrate-0.hlo").write_text(
            "hlo_version: x\n%%\n"
        )
        (root / "LOGS").mkdir(parents=True)
        (root / "LOGS" / "MFC.log").write_text("not captured")

        out = Path(td) / "golden" / "run1"
        snapshot(
            root=root,
            out_dir=out,
            config_prefix="mfcgold",
            device_name=DEVICE_NAME,
            duration=2.0,
            acquisition_rate=0.2,
        )

        assert (out / "root" / "RUNS_FINISHED" / "x" / "a-act.yml").exists()
        assert not (out / "root" / "LOGS").exists()  # non-parity top excluded
        assert (out / "provenance.yml").exists()

        manifest = ProvenanceManifest.load(out)
        assert manifest.scenario == SCENARIO
        assert manifest.config_prefix == "mfcgold"
        assert manifest.config_path.replace("\\", "/").endswith(
            "helao/deploy/hte/configs/mfcgold.yml"
        )
        assert manifest.masked_hlo_columns == MFC_MASKED_HLO_COLUMNS
        # the one data-derived summary that acquire_flowrate lands in -act.yml
        assert manifest.masked_meta_keys == MFC_ACT_YML_MASKED_META_KEYS
        # poll-paced stream -> a non-empty row-count tolerance was recorded
        assert manifest.hlo_row_count_tolerance


def _write_action(root: Path, status: str = "finished", with_hlo: bool = True) -> Path:
    """A RUNS_DIAG tree with one manual action -act.yml at ``status`` (+ .hlo)."""
    d = root / "RUNS_DIAG" / "25.28" / "0716" / "0__0__MFC__acquire_flowrate"
    d.mkdir(parents=True)
    (d / "250716.131421-act.yml").write_text(
        f"file_type: action\naction_status:\n  - {status}\n"
    )
    if with_hlo:
        (d / "acquire_flowrate-0.hlo").write_text("hlo_version: x\n%%\n")
    return d


def test_snapshot_refuses_to_overwrite_existing_out_dir():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        _write_action(root, status="finished", with_hlo=True)
        out = Path(td) / "golden" / "run1"
        snapshot(
            root=root,
            out_dir=out,
            config_prefix="mfcgold",
            device_name=DEVICE_NAME,
            duration=2.0,
            acquisition_rate=0.2,
        )
        try:
            snapshot(
                root=root,
                out_dir=out,
                config_prefix="mfcgold",
                device_name=DEVICE_NAME,
                duration=2.0,
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
                config_prefix="mfcgold",
                device_name=DEVICE_NAME,
                duration=2.0,
                acquisition_rate=0.2,
            )
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
    """-act.yml exists at init with status 'active' (base.py:1029). settle must
    NOT return on file existence -- else it snapshots + kills the server
    mid-acquisition."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        _write_action(root, status="active", with_hlo=False)  # still running
        try:
            settle(root, settle_polls=2, poll_s=0.01, timeout_s=0.05)
        except TimeoutError:
            pass
        else:
            raise AssertionError("settle() must not return while status is 'active'")


ALL_TESTS = [
    test_masked_columns_cover_live_telemetry_but_not_deterministic_categoricals,
    test_masked_meta_keys_mask_total_scc,
    test_snapshot_copies_parity_tops_and_writes_roundtrippable_provenance,
    test_snapshot_refuses_to_overwrite_existing_out_dir,
    test_snapshot_refuses_empty_capture,
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
