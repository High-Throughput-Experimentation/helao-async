"""HLO compare: header normalized, %% split honored, masked columns by manifest."""

from pathlib import Path

from harness.hlo_pass import diff_hlo, diff_hlo_body, masked_columns_for
from harness.manifest import ProvenanceManifest
from harness import HARNESS_VERSION
from harness.uuidmap import UuidMapper


def write_hlo(path: Path, epoch_ns: int, rows: list[str]) -> None:
    path.write_text(
        "hlo_version: '2025.07.07'\n"
        "action_name: WsSim\n"
        "column_headings:\n"
        "  - epoch_s\n"
        "  - series_0\n"
        f"epoch_ns: {epoch_ns}\n"
        "%%\n" + "".join(r + "\n" for r in rows)
    )


def make_manifest(masked: dict, tolerance: dict) -> ProvenanceManifest:
    return ProvenanceManifest(
        scenario="SYNTH",
        config_prefix="x",
        config_path="x",
        legacy_git_sha="0" * 40,
        launch_cmd="x",
        sequence_name="x",
        sequence_params={},
        capture_timestamp="2026-07-16T00:00:00",
        harness_version=HARNESS_VERSION,
        masked_hlo_columns=masked,
        hlo_row_count_tolerance=tolerance,
    )


def test_epoch_ns_and_hlo_version_never_diff(tmp_path):
    a, b = tmp_path / "a.hlo", tmp_path / "b.hlo"
    write_hlo(a, 111, ['{"epoch_s": 1.0, "series_0": 0.5}'])
    write_hlo(b, 999, ['{"epoch_s": 1.0, "series_0": 0.5}'])
    diffs = diff_hlo(a, b, "x/a.hlo", UuidMapper(), UuidMapper(), make_manifest({}, {}))
    assert diffs == []


def test_unmasked_value_change_is_caught(tmp_path):
    a, b = tmp_path / "a.hlo", tmp_path / "b.hlo"
    write_hlo(a, 1, ['{"epoch_s": 1.0, "series_0": 0.5}'])
    write_hlo(b, 1, ['{"epoch_s": 1.0, "series_0": 0.7}'])
    diffs = diff_hlo(a, b, "x/a.hlo", UuidMapper(), UuidMapper(), make_manifest({}, {}))
    assert any(d["key"] == "body.series_0" for d in diffs)


def test_masked_column_values_are_ignored(tmp_path):
    a, b = tmp_path / "a.hlo", tmp_path / "b.hlo"
    write_hlo(a, 1, ['{"epoch_s": 1.0, "series_0": 0.5}'])
    write_hlo(b, 1, ['{"epoch_s": 2.0, "series_0": 0.7}'])
    manifest = make_manifest({"x/*.hlo": ["epoch_s", "series_0"]}, {})
    assert diff_hlo(a, b, "x/a.hlo", UuidMapper(), UuidMapper(), manifest) == []


def test_masked_column_row_count_respects_tolerance(tmp_path):
    a, b = tmp_path / "a.hlo", tmp_path / "b.hlo"
    write_hlo(a, 1, ['{"series_0": 0.5}'] * 10)
    write_hlo(b, 1, ['{"series_0": 0.7}'] * 12)
    strict = make_manifest({"x/*.hlo": ["series_0"]}, {})
    assert diff_hlo(a, b, "x/a.hlo", UuidMapper(), UuidMapper(), strict) != []
    tolerant = make_manifest({"x/*.hlo": ["series_0"]}, {"x/*.hlo": 3})
    assert diff_hlo(a, b, "x/a.hlo", UuidMapper(), UuidMapper(), tolerant) == []


def test_missing_column_is_structural_even_when_masked():
    diffs = diff_hlo_body({"a": [1]}, {}, masked={"a"}, tolerance=0)
    assert diffs == [{"key": "body.a", "golden": "present", "candidate": "<absent>"}]


def test_masked_columns_for_matches_fnmatch():
    cols = masked_columns_for(
        "RUNS_FINISHED/x/WsSim-0.0.0.0__0.hlo", {"*WsSim*.hlo": ["epoch_s"]}
    )
    assert cols == {"epoch_s"}


def test_matching_position_nan_is_not_a_diff():
    diffs = diff_hlo_body(
        {"series_0": [float("nan"), 1.0]},
        {"series_0": [float("nan"), 1.0]},
        masked=set(),
        tolerance=0,
    )
    assert diffs == []


def test_nan_vs_real_value_is_a_diff():
    diffs = diff_hlo_body(
        {"series_0": [float("nan")]},
        {"series_0": [1.0]},
        masked=set(),
        tolerance=0,
    )
    assert any(d["key"] == "body.series_0" for d in diffs)
