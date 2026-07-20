"""Linux unit tests for golden_capture_cam.py's PURE logic (no server, no HTTP).

Exercises only:
  - the PARITY_TOPS snapshot copy + provenance.yml round-trip (``snapshot``)
  - the masking config (epoch_s / filename .hlo columns masked; .jpg content
    "skip"; no meta-key masking -- the frame filename normalizes structurally)
  - the shared (gamry-authored, imported here) ``settle`` helper on a
    cam-shaped RUNS_DIAG tree
  - the end-to-end tree normalization of a cam frame: two captures whose JPEGs
    differ ONLY by wall clock collapse to the SAME normalized member (this is
    what makes the cam runtime golden diff possible)

The real-hardware POST to ``/CAM/acquire_image`` is NOT exercised here -- that
only runs at-station with the camera reachable (see golden_capture_cam.py /
cam_diff.bat docstrings).

Runnable two ways (no ``import pytest`` -- mirrors the other capture tests):

    conda run -n helao python -m pytest helao/hexagon/tests/smoke/test_golden_capture_cam.py -q
    conda run -n helao python -m helao.hexagon.tests.smoke.test_golden_capture_cam
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from harness.manifest import ProvenanceManifest
from harness.treepass import snapshot as tree_snapshot
from harness.uuidmap import UuidMapper

from helao.hexagon.tests.smoke.golden_capture import settle
from helao.hexagon.tests.smoke.golden_capture_cam import (
    CAM_CONTENT_MASKED_FILES,
    CAM_MASKED_HLO_COLUMNS,
    SCENARIO,
    snapshot,
)


def test_masking_config_covers_the_volatile_surfaces():
    cols = set(CAM_MASKED_HLO_COLUMNS["*.hlo"])
    assert cols == {"epoch_s", "filename"}  # both live: wall clock + frame name
    assert CAM_CONTENT_MASKED_FILES == {"*.jpg": "skip"}  # bytes: presence only


def test_two_cam_captures_normalize_the_frame_to_one_member():
    """The crux: JPEG frames that differ ONLY by wall clock must land at the
    SAME normalized tree member (else diff_member_sets fails). Proves the
    RE_CAM_IMG grammar rule is wired end-to-end through treepass.snapshot."""
    with tempfile.TemporaryDirectory() as td:
        a = Path(td) / "a"
        b = Path(td) / "b"
        rel = "RUNS_DIAG/25.28/0716/0__0__CAM__acquire_image"
        for root, ts in ((a, "260719.220107"), (b, "991231.010203")):
            d = root / rel
            d.mkdir(parents=True)
            (d / f"cam_000000_{ts}.jpg").write_bytes(b"\xff\xd8\xff")  # differ
        sa = tree_snapshot(a, UuidMapper())
        sb = tree_snapshot(b, UuidMapper())
        assert set(sa.files) == set(sb.files)
        assert any(k.endswith("cam_000000_TS.jpg") for k in sa.files)


def _write_action(root: Path, status: str = "finished", with_hlo: bool = True) -> Path:
    """A RUNS_DIAG tree with one manual acquire_image -act.yml (+ .hlo + .jpg)."""
    d = root / "RUNS_DIAG" / "25.28" / "0716" / "0__0__CAM__acquire_image"
    d.mkdir(parents=True)
    (d / "250716.131421-act.yml").write_text(
        f"file_type: action\naction_status:\n  - {status}\n"
    )
    if with_hlo:
        (d / "acquire_image-0.hlo").write_text("hlo_version: x\n%%\n")
        (d / "cam_000000_250716.131421.jpg").write_bytes(b"\xff\xd8\xff")
    return d


def test_snapshot_writes_roundtrippable_provenance_with_cam_masking():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        _write_action(root, status="finished", with_hlo=True)
        (root / "LOGS").mkdir(parents=True)
        (root / "LOGS" / "CAM.log").write_text("not captured")

        out = Path(td) / "golden" / "run1"
        snapshot(
            root=root,
            out_dir=out,
            config_prefix="camgold",
            duration=0,
            acquisition_rate=1,
        )
        assert not (out / "root" / "LOGS").exists()  # non-parity top excluded
        assert (
            out
            / "root"
            / "RUNS_DIAG"
            / "25.28"
            / "0716"
            / "0__0__CAM__acquire_image"
            / "cam_000000_250716.131421.jpg"
        ).exists()

        manifest = ProvenanceManifest.load(out)
        assert manifest.scenario == SCENARIO
        assert manifest.config_prefix == "camgold"
        assert manifest.masked_hlo_columns == CAM_MASKED_HLO_COLUMNS
        assert manifest.content_masked_files == CAM_CONTENT_MASKED_FILES
        assert manifest.masked_meta_keys == {}


def test_snapshot_refuses_empty_capture():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        (root / "RUNS_DIAG").mkdir(parents=True)  # present but empty
        out = Path(td) / "golden" / "run1"
        try:
            snapshot(
                root=root,
                out_dir=out,
                config_prefix="camgold",
                duration=0,
                acquisition_rate=1,
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("snapshot() must refuse an empty (no-output) capture")
        assert not out.exists()


def test_settle_returns_once_action_complete_and_stable():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        _write_action(root, status="finished", with_hlo=True)
        settle(root, settle_polls=2, poll_s=0.01, timeout_s=5.0)


def test_settle_does_not_return_while_action_active():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "captroot"
        _write_action(root, status="active", with_hlo=False)
        try:
            settle(root, settle_polls=2, poll_s=0.01, timeout_s=0.05)
        except TimeoutError:
            pass
        else:
            raise AssertionError("settle() must not return while status is 'active'")


ALL_TESTS = [
    test_masking_config_covers_the_volatile_surfaces,
    test_two_cam_captures_normalize_the_frame_to_one_member,
    test_snapshot_writes_roundtrippable_provenance_with_cam_masking,
    test_snapshot_refuses_empty_capture,
    test_settle_returns_once_action_complete_and_stable,
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
