"""Retagging a synced sequence record's ``run_use``.

Every record here is synthetic and built under ``tmp_path`` -- a real station
zip is large, and the interesting cases (a file entry with no ``run_use``, a
process yml belonging to another sequence) do not all occur in any one record.
"""

import zipfile
from pathlib import Path

import pytest

from helao.core.tests.set_run_use import (
    apply_run_use,
    kind_for,
    main,
    process_dir_for,
    reset_to_finished,
    rewrite_processes,
    rewrite_zip,
)
from helao.helpers.yml_tools import yml_dumps, yml_load

SEQ_UUID = "068dfbb3-3b21-7544-8000-ca3f3342fd63"
EXP_UUID = "068dfbb3-3b21-7544-8001-516001cafc02"
OTHER_SEQ_UUID = "068dfbb3-3b21-7544-8000-000000000999"


def _seq_yml() -> str:
    return yml_dumps(
        {
            "hlo_version": "f8cc4de3",
            "sequence_uuid": SEQ_UUID,
            "sequence_name": "XRDS_generic_scan",
        }
    )


def _exp_yml() -> str:
    # No run_use at all: the experiment writer strips it, so this is the shape
    # a real -exp.yml has on disk.
    return yml_dumps(
        {
            "hlo_version": "f8cc4de3",
            "experiment_uuid": EXP_UUID,
            "sequence_uuid": SEQ_UUID,
            "run_type": "xrds",
            "process_order_groups": {0: [1]},
        }
    )


def _act_yml(run_use: str = "ref") -> str:
    return yml_dumps(
        {
            "hlo_version": "f8cc4de3",
            "action_uuid": "068dfbb3-3b21-7544-8002-5f220b3807eb",
            "run_type": "xrds",
            "run_use": run_use,
            "experiment_uuid": EXP_UUID,
            "files": [
                {"file_name": "X0-000-0000.npz", "run_use": run_use},
                {"file_name": "X0-000-0001.npz"},  # never recorded one
            ],
            "process_contrib": ["samples_in", "files", "action_params", "run_use"],
        }
    )


def _prc_yml(sequence_uuid: str = SEQ_UUID, run_use: str = "ref") -> str:
    return yml_dumps(
        {
            "hlo_version": "6d33e58d",
            "process_uuid": "0690e558-0b51-7466-8000-ccac06b55692",
            "sequence_uuid": sequence_uuid,
            "experiment_uuid": EXP_UUID,
            "technique_name": "xrds_frame",
            "run_use": run_use,
        }
    )


EXP_DIR = "251003.120155__XRDS_sub_sample_acquire"
ACT_MEMBER = f"{EXP_DIR}/0__0__XRDS__acquire_frame/251003.120155695637-act.yml"
EXP_MEMBER = f"{EXP_DIR}/251003.120155695637-exp.yml"
SEQ_MEMBER = "251003.120155695637-seq.yml"
HLO_MEMBER = f"{EXP_DIR}/0__0__XRDS__acquire_frame/X0-000-0000.hlo"
PRG_MEMBER = "251003.120155695637-seq.prg"


def _build_zip(tmp_path: Path, *, run_use: str = "ref") -> Path:
    day = tmp_path / "RUNS_SYNCED" / "25.39" / "1003"
    day.mkdir(parents=True, exist_ok=True)
    z = day / "120155__XRDS_generic_scan__CoO-100034.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(SEQ_MEMBER, _seq_yml())
        zf.writestr(EXP_MEMBER, _exp_yml())
        zf.writestr(ACT_MEMBER, _act_yml(run_use))
        zf.writestr(PRG_MEMBER, "yml: /x/y-seq.yml\napi: true\ns3: true\n")
        zf.writestr(zipfile.ZipInfo(HLO_MEMBER), b"\x00\x01binary payload\x02")
    return z


def _build_processes(tmp_path: Path, *, sequence_uuid: str = SEQ_UUID) -> Path:
    d = (
        tmp_path
        / "PROCESSES"
        / "25.39"
        / "1003"
        / "120155__XRDS_generic_scan__CoO-100034"
        / EXP_DIR
    )
    d.mkdir(parents=True, exist_ok=True)
    (d / "0__0690e558-0b51-7466-8000-ccac06b55692__xrds_frame-prc.yml").write_text(
        _prc_yml(sequence_uuid)
    )
    return d


def _member(z: Path, name: str) -> str:
    with zipfile.ZipFile(z) as zf:
        return zf.read(name).decode()


def test_kind_for_reads_the_suffix():
    assert kind_for("a/b/251003-act.yml") == "action"
    assert kind_for("251003-exp.yml") == "experiment"
    assert kind_for("251003-seq.yml") == "sequence"
    assert kind_for("0__uuid__xrds_frame-prc.yml") == "process"
    assert kind_for("X0-000-0000.hlo") is None


def test_the_process_contrib_list_item_is_not_a_value_to_retag():
    """``process_contrib`` says which fields the action contributes to its
    process. An entry reading "run_use" is that tag's name, not its value."""
    doc = yml_load(_act_yml("ref"))
    apply_run_use(doc, "action", "data")
    assert doc["process_contrib"] == [
        "samples_in",
        "files",
        "action_params",
        "run_use",
    ]


def test_a_recorded_file_entry_is_retagged_and_an_unrecorded_one_is_left_alone():
    doc = yml_load(_act_yml("ref"))
    changed = apply_run_use(doc, "action", "data")
    assert changed == ["run_use", "files[0].run_use"]
    assert doc["files"][0]["run_use"] == "data"
    assert "run_use" not in doc["files"][1]


def test_an_experiment_gains_the_key_and_a_sequence_never_does():
    exp = yml_load(_exp_yml())
    assert apply_run_use(exp, "experiment", "data") == ["run_use"]
    assert exp["run_use"] == "data"

    seq = yml_load(_seq_yml())
    assert apply_run_use(seq, "sequence", "data") == []
    assert "run_use" not in seq


def test_rewriting_a_zip_retags_its_ymls_and_leaves_every_other_member_intact(
    tmp_path,
):
    z = _build_zip(tmp_path)
    with zipfile.ZipFile(z) as zf:
        before = {i.filename: (zf.read(i), i.compress_type) for i in zf.infolist()}

    edits, sequence_uuid = rewrite_zip(z, "data")

    assert sequence_uuid == SEQ_UUID
    assert yml_load(_member(z, ACT_MEMBER))["run_use"] == "data"
    assert yml_load(_member(z, ACT_MEMBER))["files"][0]["run_use"] == "data"
    assert yml_load(_member(z, EXP_MEMBER))["run_use"] == "data"
    assert "run_use" not in yml_load(_member(z, SEQ_MEMBER))

    with zipfile.ZipFile(z) as zf:
        after = {i.filename: (zf.read(i), i.compress_type) for i in zf.infolist()}
    assert set(after) == set(before)
    for name in (HLO_MEMBER, PRG_MEMBER, SEQ_MEMBER):
        assert after[name] == before[name], name

    kinds = {e.kind: e for e in edits}
    assert kinds["action"].changed == ["run_use", "files[0].run_use"]
    assert kinds["sequence"].changed == []
    assert "no run_use field" in kinds["sequence"].note
    # No staging litter beside the record.
    assert sorted(p.name for p in z.parent.iterdir()) == [z.name]


def test_a_zip_already_carrying_the_requested_tag_is_not_rewritten(tmp_path):
    z = _build_zip(tmp_path, run_use="data")
    # The experiment yml still lacks the key, so this record does change; use
    # one that does not, by retagging twice and comparing the second pass.
    rewrite_zip(z, "data")
    before = z.read_bytes()
    edits, _ = rewrite_zip(z, "data")
    assert [e for e in edits if e.changed] == []
    assert z.read_bytes() == before


def test_dry_run_reports_and_writes_nothing(tmp_path):
    z = _build_zip(tmp_path)
    prc_dir = _build_processes(tmp_path)
    prc = next(prc_dir.glob("*-prc.yml"))
    zip_before, prc_before = z.read_bytes(), prc.read_text()

    edits, sequence_uuid = rewrite_zip(z, "data", dry_run=True)
    prc_edits = rewrite_processes(prc_dir, sequence_uuid, "data", dry_run=True)

    assert [e.changed for e in edits if e.changed]
    assert [e.changed for e in prc_edits if e.changed]
    assert z.read_bytes() == zip_before
    assert prc.read_text() == prc_before


def test_process_dir_mirrors_the_run_tree(tmp_path):
    z = _build_zip(tmp_path)
    assert process_dir_for(z) == (
        tmp_path.resolve()
        / "PROCESSES"
        / "25.39"
        / "1003"
        / "120155__XRDS_generic_scan__CoO-100034"
    )
    assert process_dir_for(tmp_path / "loose.zip") is None


def test_an_external_process_yml_is_retagged(tmp_path):
    _build_zip(tmp_path)
    prc_dir = _build_processes(tmp_path)
    edits = rewrite_processes(prc_dir, SEQ_UUID, "data")
    assert [e.changed for e in edits] == [["run_use"]]
    assert yml_load(next(prc_dir.glob("*-prc.yml")))["run_use"] == "data"


def test_a_process_yml_from_another_sequence_is_reported_not_retagged(tmp_path):
    prc_dir = _build_processes(tmp_path, sequence_uuid=OTHER_SEQ_UUID)
    prc = next(prc_dir.glob("*-prc.yml"))
    before = prc.read_text()

    edits = rewrite_processes(prc_dir, SEQ_UUID, "data")

    assert edits[0].changed == []
    assert "not this record's" in edits[0].note
    assert prc.read_text() == before


def test_an_unidentifiable_sequence_leaves_every_process_yml_alone(tmp_path):
    """No readable sequence uuid means the mirrored directory cannot be proved
    to belong to this record, and a path convention alone is not proof."""
    prc_dir = _build_processes(tmp_path)
    before = next(prc_dir.glob("*-prc.yml")).read_text()
    edits = rewrite_processes(prc_dir, None, "data")
    assert edits[0].changed == []
    assert next(prc_dir.glob("*-prc.yml")).read_text() == before


def test_main_retags_zip_and_processes_together(tmp_path, capsys):
    z = _build_zip(tmp_path)
    prc_dir = _build_processes(tmp_path)

    assert main([str(z), "--run-use", "data"]) == 0

    # The zip is gone by now: a default run hands the record back, so the
    # retagged copy to read is the one in RUNS_FINISHED.
    assert yml_load(_finished_dir(tmp_path) / ACT_MEMBER)["run_use"] == "data"
    assert yml_load(next(prc_dir.glob("*-prc.yml")))["run_use"] == "data"
    out = capsys.readouterr().out
    assert "retagged 3 yml(s) to run_use=data" in out


def test_main_defaults_to_data(tmp_path):
    z = _build_zip(tmp_path, run_use="ref")
    assert main([str(z), "--no-reset"]) == 0
    assert yml_load(_member(z, ACT_MEMBER))["run_use"] == "data"


def test_main_refuses_a_run_use_the_enum_does_not_define(tmp_path):
    z = _build_zip(tmp_path)
    before = z.read_bytes()
    with pytest.raises(SystemExit) as exc:
        main([str(z), "--run-use", "not_a_run_use"])
    assert exc.value.code == 2
    assert z.read_bytes() == before


def test_main_refuses_a_path_that_is_not_a_file(tmp_path):
    assert main([str(tmp_path / "nope.zip")]) == 1


def _finished_dir(tmp_path: Path) -> Path:
    return (
        tmp_path
        / "RUNS_FINISHED"
        / "25.39"
        / "1003"
        / "120155__XRDS_generic_scan__CoO-100034"
    )


def test_the_record_is_extracted_to_runs_finished_without_its_prg(tmp_path):
    """Dropping the .prg is what makes the record re-syncable: it records
    which files already reached S3, so one restored with it reads as done."""
    z = _build_zip(tmp_path)
    with zipfile.ZipFile(z) as zf:
        hlo_before = zf.read(HLO_MEMBER)

    assert main([str(z), "--run-use", "data"]) == 0

    dest = _finished_dir(tmp_path)
    assert dest.is_dir()
    assert not list(dest.rglob("*.prg"))
    assert not list(dest.rglob("*.lock"))
    assert (dest / SEQ_MEMBER).is_file()
    assert (dest / HLO_MEMBER).read_bytes() == hlo_before
    # The retag is in the extracted copy, not only in the archive.
    assert yml_load(dest / ACT_MEMBER)["run_use"] == "data"
    assert yml_load(dest / EXP_MEMBER)["run_use"] == "data"

    assert not z.exists()
    assert z.with_suffix(".orig").is_file()


def test_no_reset_leaves_the_record_in_runs_synced(tmp_path):
    z = _build_zip(tmp_path)
    assert main([str(z), "--no-reset"]) == 0
    assert z.is_file()
    assert not z.with_suffix(".orig").exists()
    assert not _finished_dir(tmp_path).exists()
    assert yml_load(_member(z, ACT_MEMBER))["run_use"] == "data"


def test_dry_run_extracts_nothing(tmp_path):
    z = _build_zip(tmp_path)
    before = z.read_bytes()
    assert main([str(z), "--dry-run"]) == 0
    assert z.read_bytes() == before
    assert not _finished_dir(tmp_path).exists()
    assert not z.with_suffix(".orig").exists()


def test_reset_reports_where_it_would_go_without_touching_disk(tmp_path):
    z = _build_zip(tmp_path)
    ok, dest, note = reset_to_finished(z, dry_run=True)
    assert ok
    assert dest == _finished_dir(tmp_path)
    assert "dropping 1 sync-state file(s)" in note
    assert not dest.exists()


def test_a_record_carrying_no_prg_at_all_is_still_handed_back(tmp_path):
    """A batch-converted record has no .prg anywhere -- 0 of 506 members on
    the one measured -- and those are exactly the records a retag aims at.
    SyncDriver.reset_sync refuses them; this must not."""
    day = tmp_path / "RUNS_SYNCED" / "25.39" / "1003"
    day.mkdir(parents=True)
    z = day / "120155__XRDS_generic_scan__CoO-100034.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr(SEQ_MEMBER, _seq_yml())
        zf.writestr(ACT_MEMBER, _act_yml("ref"))

    assert main([str(z)]) == 0

    dest = _finished_dir(tmp_path)
    assert yml_load(dest / ACT_MEMBER)["run_use"] == "data"
    assert not z.exists()
    assert z.with_suffix(".orig").is_file()


def test_a_zip_with_no_seq_yml_is_reported_as_not_reset(tmp_path):
    """The validity check is a sequence yml: without one there is no record
    here to hand back, and the retag has nothing to identify either."""
    day = tmp_path / "RUNS_SYNCED" / "25.39" / "1003"
    day.mkdir(parents=True)
    z = day / "120155__XRDS_generic_scan__CoO-100034.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr(ACT_MEMBER, _act_yml("ref"))

    assert main([str(z)]) == 1

    assert z.is_file()
    assert not _finished_dir(tmp_path).exists()
    # The retag itself still happened.
    assert yml_load(_member(z, ACT_MEMBER))["run_use"] == "data"


def test_an_existing_orig_is_never_overwritten(tmp_path):
    """An .orig beside the zip is an earlier reset's copy of the record as it
    was; replacing it would destroy the only pre-retag copy."""
    z = _build_zip(tmp_path)
    orig = z.with_suffix(".orig")
    orig.write_bytes(b"an earlier reset's archive")

    assert main([str(z)]) == 0

    assert orig.read_bytes() == b"an earlier reset's archive"
    assert z.is_file()
    assert _finished_dir(tmp_path).is_dir()


def test_a_zip_outside_runs_synced_is_not_reset(tmp_path):
    loose = tmp_path / "loose.zip"
    with zipfile.ZipFile(loose, "w") as zf:
        zf.writestr(SEQ_MEMBER, _seq_yml())
        zf.writestr(PRG_MEMBER, "yml: /x/y-seq.yml\n")
        zf.writestr(ACT_MEMBER, _act_yml("ref"))

    ok, dest, note = reset_to_finished(loose)
    assert not ok
    assert dest is None
    assert "RUNS_SYNCED" in note
