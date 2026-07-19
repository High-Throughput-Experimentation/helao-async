"""End-to-end gate plumbing on synthetic manifested trees."""

import uuid

import pytest

from harness.manifest import ManifestMissingError
from harness.parity import run_parity
from harness.tests.synthtree import attach_manifest, build_tree


def make_golden(base, name, seed):
    gdir = base / name
    build_tree(gdir / "root", seed=seed)
    attach_manifest(gdir)
    return gdir


def test_identical_runs_pass(tmp_path):
    a = make_golden(tmp_path, "runA", seed=0)
    b = make_golden(tmp_path, "runB", seed=100)
    report = run_parity(a, b)
    assert report["status"] == "pass"
    assert report["n_diffs"] == 0
    assert len(report["run_id"]) == 12


def test_candidate_may_be_a_raw_root(tmp_path):
    a = make_golden(tmp_path, "runA", seed=0)
    raw = tmp_path / "rawroot"
    build_tree(raw, seed=100)
    assert run_parity(a, raw)["status"] == "pass"


def test_manifestless_golden_hard_fails(tmp_path):
    gdir = tmp_path / "nomanifest"
    build_tree(gdir / "root", seed=0)
    b = make_golden(tmp_path, "runB", seed=100)
    with pytest.raises(ManifestMissingError):
        run_parity(gdir, b)


def test_content_diff_fails_gate(tmp_path):
    a = make_golden(tmp_path, "runA", seed=0)
    b = make_golden(tmp_path, "runB", seed=100)
    act = next((b / "root").rglob("*-act.yml"))
    act.write_text(act.read_text().replace("duration: 2.0", "duration: 9.0"))
    report = run_parity(a, b)
    assert report["status"] == "fail"
    assert report["n_diffs"] >= 1


def test_masked_meta_key_neutralizes_act_yml_value(tmp_path):
    """masked_meta_keys masks a data-derived -act.yml value (the meta-side
    analogue of masked_hlo_columns): the same diff that fails the gate above
    passes once the manifest masks that dotted key."""
    a = make_golden(tmp_path, "runA", seed=0)
    b = make_golden(tmp_path, "runB", seed=100)
    act = next((b / "root").rglob("*-act.yml"))
    act.write_text(act.read_text().replace("duration: 2.0", "duration: 9.0"))
    # control: unmasked, the differing action_params value fails the gate
    assert run_parity(a, b)["status"] == "fail"
    # re-attach the golden manifest WITH the meta mask -> value neutralized on
    # both sides, gate passes; a real diff in any OTHER key would still fail.
    attach_manifest(a, meta_masked={"*-act.yml": ["action_params.duration"]})
    report = run_parity(a, b)
    assert report["status"] == "pass", report["file_diffs"]


def test_masked_meta_key_still_catches_other_diffs(tmp_path):
    """Masking one action_params key must NOT hide a diff in a different key."""
    a = make_golden(tmp_path, "runA", seed=0)
    b = make_golden(tmp_path, "runB", seed=100)
    act = next((b / "root").rglob("*-act.yml"))
    # change action_name (not masked) in addition to the masked duration
    txt = (
        act.read_text()
        .replace("duration: 2.0", "duration: 9.0")
        .replace("action_name: acquire_data", "action_name: something_else")
    )
    act.write_text(txt)
    attach_manifest(a, meta_masked={"*-act.yml": ["action_params.duration"]})
    report = run_parity(a, b)
    assert report["status"] == "fail"  # the unmasked action_name diff surfaces


def test_report_file_is_written(tmp_path):
    a = make_golden(tmp_path, "runA", seed=0)
    b = make_golden(tmp_path, "runB", seed=100)
    out = tmp_path / "report.json"
    run_parity(a, b, report_path=out)
    assert out.exists()
    import json

    loaded = json.loads(out.read_text())
    assert loaded["status"] == "pass"


def _add_derived_process(gdir, exp_uuid, pidx=0):
    """Add a PROCESSES/*-prc.yml whose process_uuid is the uuid5 derivation.

    Exercises the PRC_YML / register_derived path end-to-end through the
    full gate (seed_mapper registration -> yaml-pass diff), per Task 8's
    correctness notes; the raw synthtree fixtures don't emit process
    records so this augments the golden tree built by build_tree().
    """
    process_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{exp_uuid}__{pidx}"))
    proc_dir = gdir / "root" / "PROCESSES" / "25.28" / "0716" / "someproc"
    proc_dir.mkdir(parents=True)
    (proc_dir / "0__0__t-prc.yml").write_text(
        "file_type: process\n"
        f"process_uuid: {process_uuid}\n"
        f"experiment_uuid: {exp_uuid}\n"
        "process_group_index: 0\n"
        "process_name: acquire_data\n"
        "process_timestamp: 2025-07-16 13:14:21.123456\n"
    )


def make_golden_with_process(base, name, seed):
    gdir = base / name
    ids = build_tree(gdir / "root", seed=seed)
    _add_derived_process(gdir, ids["exp_uuid"])
    attach_manifest(gdir)
    return gdir


def test_prc_yml_derived_uuid_end_to_end(tmp_path):
    a = make_golden_with_process(tmp_path, "runA", seed=0)
    b = make_golden_with_process(tmp_path, "runB", seed=100)
    report = run_parity(a, b)
    assert report["status"] == "pass"
    assert report["n_diffs"] == 0
