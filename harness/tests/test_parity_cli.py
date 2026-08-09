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


def test_empty_golden_set_fails_not_vacuous_pass(tmp_path):
    """A golden with no comparable files must FAIL, not pass with 0 diffs."""
    a = tmp_path / "runA"
    (a / "root").mkdir(parents=True)  # empty root, no run output
    attach_manifest(a)
    b = make_golden(tmp_path, "runB", seed=100)
    report = run_parity(a, b)
    assert report["status"] == "fail"
    assert any(c.get("check") == "empty_golden" for c in report["consistency_diffs"])


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


# --- accepted legacy divergences ---------------------------------------------
def test_accepted_divergence_is_pinned_to_its_measured_value():
    """Acceptance is not masking: the value is pinned, so a change to the
    divergence resurfaces as an unaccepted finding."""
    from harness.parity import partition_accepted

    found = [{"key": "x.json:files[a].file_type", "candidate": "legacy_form"}]
    spec = [{"key_suffix": "files[a].file_type", "candidate": "legacy_form"}]
    unaccepted, accepted, stale = partition_accepted(found, spec)
    assert (unaccepted, len(accepted), stale) == ([], 1, [])

    drifted = [{"key": "x.json:files[a].file_type", "candidate": "something_else"}]
    unaccepted, accepted, stale = partition_accepted(drifted, spec)
    assert len(unaccepted) == 1 and not accepted and len(stale) == 1


def test_an_acceptance_that_matches_nothing_is_stale_and_fails():
    """Otherwise the list rots into a mute button once the divergence is
    fixed, and the next regression of it would be silently accepted."""
    from harness.parity import partition_accepted

    spec = [{"key_suffix": "files[gone].file_type", "candidate": "legacy_form"}]
    unaccepted, accepted, stale = partition_accepted([], spec)
    assert not unaccepted and not accepted and len(stale) == 1
    assert "matched nothing" in stale[0]["candidate"]


def test_no_acceptances_leaves_every_finding_unaccepted():
    from harness.parity import partition_accepted

    found = [{"key": "k", "candidate": "v"}]
    assert partition_accepted(found, []) == (found, [], [])
