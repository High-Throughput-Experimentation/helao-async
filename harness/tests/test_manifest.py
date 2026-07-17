"""ProvenanceManifest round-trip + the manifest-less hard-fail (spec §6.5 / F1)."""

import pytest

from harness import HARNESS_VERSION
from harness.manifest import ManifestMissingError, ProvenanceManifest, MANIFEST_NAME


def make_manifest() -> ProvenanceManifest:
    return ProvenanceManifest(
        scenario="GM-1",
        config_prefix="golden",
        config_path="/abs/path/golden.yml",
        legacy_git_sha="c3b80003" + "0" * 32,
        launch_cmd="conda run -n helao python launch.py golden --no-hot-reload",
        sequence_name="SIM_websocket_data_seq",
        sequence_params={"wait_time": 2.0},
        capture_timestamp="2026-07-16T12:00:00",
        harness_version=HARNESS_VERSION,
        masked_hlo_columns={"*WsSim*.hlo": ["epoch_s", "series_0"]},
        hlo_row_count_tolerance={"*WsSim*.hlo": 3},
        content_masked_files={"*.csv": "line-count"},
        notes="unit test",
    )


def test_save_and_load_roundtrip(tmp_path):
    m = make_manifest()
    saved = m.save(tmp_path)
    assert saved == tmp_path / MANIFEST_NAME
    loaded = ProvenanceManifest.load(tmp_path)
    assert loaded == m


def test_load_without_manifest_hard_fails(tmp_path):
    with pytest.raises(ManifestMissingError):
        ProvenanceManifest.load(tmp_path)


def test_optional_masking_fields_default_empty(tmp_path):
    m = make_manifest()
    m.masked_hlo_columns = {}
    m.hlo_row_count_tolerance = {}
    m.content_masked_files = {}
    m.save(tmp_path)
    loaded = ProvenanceManifest.load(tmp_path)
    assert loaded.masked_hlo_columns == {}
    assert loaded.hlo_row_count_tolerance == {}
    assert loaded.content_masked_files == {}
