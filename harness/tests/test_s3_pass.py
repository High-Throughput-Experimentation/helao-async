"""S3 payload compare + the intentional on-disk-vs-S3 difference assertions (§5.5)."""

import json

from harness.s3_pass import (
    assert_s3_meta_rules,
    diff_s3_manifest,
    diff_s3_record,
)
from harness.manifest import ProvenanceManifest
from harness import HARNESS_VERSION
from harness.uuidmap import UuidMapper

U1 = "00000000-0000-0000-0000-000000000001"
U2 = "00000000-0000-0000-0000-000000000002"


def manifest():
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
    )


def test_meta_json_payloads_are_normalized_and_diffed(tmp_path):
    g, c = tmp_path / "g.json", tmp_path / "c.json"
    g.write_text(json.dumps({"action_uuid": U1, "action_params": {"duration": 2.0}}))
    c.write_text(json.dumps({"action_uuid": U2, "action_params": {"duration": 2.0}}))
    mg, mc = UuidMapper(), UuidMapper()
    norm = "S3_SIM/helao-sim/action/UUID-0.json"
    assert diff_s3_record(norm, g, c, mg, mc, manifest()) == []
    c.write_text(json.dumps({"action_uuid": U2, "action_params": {"duration": 9.0}}))
    diffs = diff_s3_record(norm, g, c, mg, mc, manifest())
    assert any("duration" in d["key"] for d in diffs)


def test_hlo_json_payload_uses_body_masking(tmp_path):
    payload_g = {
        "meta": {"action_name": "WsSim", "epoch_ns": 1},
        "data": {"series_0": [0.5]},
    }
    payload_c = {
        "meta": {"action_name": "WsSim", "epoch_ns": 2},
        "data": {"series_0": [0.9]},
    }
    g, c = tmp_path / "g.hlo.json", tmp_path / "c.hlo.json"
    g.write_text(json.dumps(payload_g))
    c.write_text(json.dumps(payload_c))
    m = manifest()
    m.masked_hlo_columns = {"*WsSim*.hlo.json": ["series_0"]}
    norm = "S3_SIM/helao-sim/raw_data/UUID-0/WsSim-0.0.0.0__0.hlo.json"
    assert diff_s3_record(norm, g, c, UuidMapper(), UuidMapper(), m) == []


def test_s3_manifest_jsonl_compares_mapped_key_sets(tmp_path):
    g, c = tmp_path / "g.jsonl", tmp_path / "c.jsonl"
    g.write_text(
        json.dumps(
            {
                "bucket": "b",
                "key": f"action/{U1}.json",
                "mode": "fileobj",
                "gzip": False,
            }
        )
        + "\n"
    )
    c.write_text(
        json.dumps(
            {
                "bucket": "b",
                "key": f"action/{U2}.json",
                "mode": "fileobj",
                "gzip": False,
            }
        )
        + "\n"
    )
    mg, mc = UuidMapper(), UuidMapper()
    mg.map(U1)
    mc.map(U2)
    assert diff_s3_manifest(g, c, mg, mc) == []
    c.write_text(
        json.dumps(
            {"bucket": "b", "key": f"action/{U2}.json", "mode": "fileobj", "gzip": True}
        )
        + "\n"
    )
    assert diff_s3_manifest(g, c, mg, mc) != []


def test_fileinfo_rename_rule_is_asserted():
    # Realistic values per sync_driver.py (~1213-1239) and base.py's default
    # file_type (f"{server_name.lower()}_helao__file"): the on-disk FileInfo
    # carries a server-name prefix, and the S3-side rename replaces
    # "helao__file" with "helao__<last-S3-key-extension>_file" (never "hlo").
    disk_act = {
        "files": [
            {"file_name": "WsSim-0.0.0.0__0.hlo", "file_type": "wssim_helao__file"}
        ],
        "technique_name": ["t1", "t2"],
    }
    good_s3 = {
        "files": [
            {
                "file_name": "WsSim-0.0.0.0__0.hlo.json",
                "file_type": "wssim_helao__json_file",
            }
        ],
        "technique_name": "t1",
    }
    assert assert_s3_meta_rules(disk_act, good_s3) == []

    # Rename MISSING: S3 side still carries the pre-rename generic file_type.
    bad_type = {
        "files": [
            {
                "file_name": "WsSim-0.0.0.0__0.hlo.json",
                "file_type": "wssim_helao__file",
            }
        ],
        "technique_name": "t1",
    }
    assert assert_s3_meta_rules(disk_act, bad_type) != []

    # Compressed upload: S3 key gets ".hlo.json.gz", file_type extension is
    # "gz" (the LAST S3-key extension), not "json".
    gzip_s3 = {
        "files": [
            {
                "file_name": "WsSim-0.0.0.0__0.hlo.json.gz",
                "file_type": "wssim_helao__gz_file",
            }
        ],
        "technique_name": "t1",
    }
    assert assert_s3_meta_rules(disk_act, gzip_s3) == []

    bad_technique = dict(good_s3, technique_name=["t1", "t2"])
    assert assert_s3_meta_rules(disk_act, bad_technique) != []
