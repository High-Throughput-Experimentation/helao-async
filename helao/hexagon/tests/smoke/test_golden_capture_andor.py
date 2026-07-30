"""Linux unit tests for golden_capture_andor.py's PURE logic (no server, no HTTP).

Exercises only:
  - the PARITY_TOPS snapshot copy + provenance.yml round-trip (``snapshot``)
  - the masked-column set (tick_time / elapsed_time_s / ch_NNNN are masked; the
    deterministic header `wl` is NOT)
  - the data-derived meta-key mask (action_params.action_path)
  - the shared (gamry-authored, imported here) ``settle`` helper, applied to an
    andor-shaped RUNS_DIAG tree

The real-hardware POST to ``/ANDOR/acquire`` is NOT exercised here -- that only
runs at-station with the Andor camera + spectrograph attached (see
golden_capture_andor.py / andor_diff.bat docstrings).

Written as plain assert-based ``test_*`` functions with no ``import pytest``
(mirrors test_golden_capture_spec.py -- this repo's conda ``helao`` env does not
currently have the pytest package installed), so this module is runnable two
ways:

    conda run -n helao python -m pytest helao/hexagon/tests/smoke/test_golden_capture_andor.py -q
    conda run -n helao python -m helao.hexagon.tests.smoke.test_golden_capture_andor
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from harness.manifest import ProvenanceManifest
from helao.hexagon.tests.smoke.golden_capture import settle
from helao.hexagon.tests.smoke.golden_capture_andor import (
    ANDOR_ACT_YML_MASKED_META_KEYS,
    ANDOR_HLO_COLUMNS,
    ANDOR_MASKED_HLO_COLUMNS,
    N_PIXELS,
    SCENARIO,
    snapshot,
)


def test_masked_columns_cover_all_live_channels_but_not_header_wl():
    cols = set(ANDOR_MASKED_HLO_COLUMNS["*.hlo"])
    # every live/hardware-derived column is masked: the time column (driver's
    # tick_time + the endpoint-declared elapsed_time_s alias) and every pixel...
    assert "tick_time" in cols
    assert "elapsed_time_s" in cols
    assert "ch_0000" in cols
    assert f"ch_{N_PIXELS - 1:04}" in cols
    # ...one per pixel, plus the two time-column names
    assert len(ANDOR_HLO_COLUMNS) == N_PIXELS + 2
    # the deterministic pixel->wavelength header key is NOT a masked body column
    # (it lives in the .hlo HEADER and is compared unmasked -- a diff there is a
    # real regression).
    assert "wl" not in cols


def test_action_path_is_masked_via_meta_keys():
    # AndorAcquire writes the per-run action_output_dir into action_params as
    # action_path; normalize_meta does not §5.1-normalize a non-_output_dir key,
    # so it must be value-masked to keep parity clean.
    assert ANDOR_ACT_YML_MASKED_META_KEYS != {}
    keys = ANDOR_ACT_YML_MASKED_META_KEYS["*-act.yml"]
    assert "action_params.action_path" in keys


def test_snapshot_copies_parity_tops_and_writes_roundtrippable_provenance():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        (root / "RUNS_FINISHED" / "x").mkdir(parents=True)
        (root / "RUNS_FINISHED" / "x" / "a-act.yml").write_text("file_type: action\n")
        # include a .hlo too (the full happy path: metadata + spectrum stream)
        (root / "RUNS_FINISHED" / "x" / "acquire-0.hlo").write_text(
            "hlo_version: x\n%%\n"
        )
        (root / "LOGS").mkdir(parents=True)
        (root / "LOGS" / "ANDOR.log").write_text("not captured")

        out = Path(td) / "golden" / "run1"
        snapshot(
            root=root,
            out_dir=out,
            config_prefix="andorgold",
            duration=1.0,
            external_trigger=False,
        )

        assert (out / "root" / "RUNS_FINISHED" / "x" / "a-act.yml").exists()
        assert not (out / "root" / "LOGS").exists()  # non-parity top excluded
        assert (out / "provenance.yml").exists()

        manifest = ProvenanceManifest.load(out)
        assert manifest.scenario == SCENARIO
        assert manifest.config_prefix == "andorgold"
        assert manifest.config_path.replace("\\", "/").endswith(
            "helao/hexagon/tests/smoke/configs/andorgold.yml"
        )
        assert manifest.masked_hlo_columns == ANDOR_MASKED_HLO_COLUMNS
        # the per-run action_params.action_path is masked via masked_meta_keys
        assert manifest.masked_meta_keys == ANDOR_ACT_YML_MASKED_META_KEYS
        # poll-paced stream -> a non-zero row-count tolerance is recorded
        assert manifest.hlo_row_count_tolerance.get("*.hlo", 0) > 0


def _write_action(root: Path, status: str = "finished", with_hlo: bool = True) -> Path:
    """A RUNS_DIAG tree with one manual action -act.yml at ``status`` (+ .hlo)."""
    d = root / "RUNS_DIAG" / "25.28" / "0716" / "0__0__ANDOR__acquire"
    d.mkdir(parents=True)
    (d / "250716.131421-act.yml").write_text(
        f"file_type: action\naction_status:\n  - {status}\n"
    )
    if with_hlo:
        (d / "acquire-0.hlo").write_text("hlo_version: x\n%%\n")
    return d


def test_snapshot_refuses_to_overwrite_existing_out_dir():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        _write_action(root, status="finished", with_hlo=True)
        out = Path(td) / "golden" / "run1"
        snapshot(
            root=root,
            out_dir=out,
            config_prefix="andorgold",
            duration=1.0,
            external_trigger=False,
        )
        try:
            snapshot(
                root=root,
                out_dir=out,
                config_prefix="andorgold",
                duration=1.0,
                external_trigger=False,
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
                config_prefix="andorgold",
                duration=1.0,
                external_trigger=False,
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
    test_masked_columns_cover_all_live_channels_but_not_header_wl,
    test_action_path_is_masked_via_meta_keys,
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
