"""Retagging a synced sequence record's ``run_use``.

Every record here is synthetic and built under ``tmp_path`` -- a real station
zip is large, and the interesting cases (a file entry with no ``run_use``, a
process yml belonging to another sequence) do not all occur in any one record.
"""

import json
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
from helao.helpers.meta_io import meta_glob, write_meta
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
    z = day / "120155__XRDS_generic_scan__CoO-987655.zip"
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
        / "120155__XRDS_generic_scan__CoO-987655"
        / EXP_DIR
    )
    d.mkdir(parents=True, exist_ok=True)
    (d / "0__0690e558-0b51-7466-8000-ccac06b55692__xrds_frame-prc.yml").write_text(
        _prc_yml(sequence_uuid), encoding="utf-8"
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
    zip_before, prc_before = z.read_bytes(), prc.read_text(encoding="utf-8")

    edits, sequence_uuid = rewrite_zip(z, "data", dry_run=True)
    prc_edits = rewrite_processes(prc_dir, sequence_uuid, "data", dry_run=True)

    assert [e.changed for e in edits if e.changed]
    assert [e.changed for e in prc_edits if e.changed]
    assert z.read_bytes() == zip_before
    assert prc.read_text(encoding="utf-8") == prc_before


def test_process_dir_mirrors_the_run_tree(tmp_path):
    z = _build_zip(tmp_path)
    assert process_dir_for(z) == (
        tmp_path.resolve()
        / "PROCESSES"
        / "25.39"
        / "1003"
        / "120155__XRDS_generic_scan__CoO-987655"
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
    before = prc.read_text(encoding="utf-8")

    edits = rewrite_processes(prc_dir, SEQ_UUID, "data")

    assert edits[0].changed == []
    assert "not this record's" in edits[0].note
    assert prc.read_text(encoding="utf-8") == before


def test_an_unidentifiable_sequence_leaves_every_process_yml_alone(tmp_path):
    """No readable sequence uuid means the mirrored directory cannot be proved
    to belong to this record, and a path convention alone is not proof."""
    prc_dir = _build_processes(tmp_path)
    before = next(prc_dir.glob("*-prc.yml")).read_text(encoding="utf-8")
    edits = rewrite_processes(prc_dir, None, "data")
    assert edits[0].changed == []
    assert next(prc_dir.glob("*-prc.yml")).read_text(encoding="utf-8") == before


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
        / "120155__XRDS_generic_scan__CoO-987655"
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
    z = day / "120155__XRDS_generic_scan__CoO-987655.zip"
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
    z = day / "120155__XRDS_generic_scan__CoO-987655.zip"
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


def test_reset_refuses_a_non_empty_runs_finished_twin(tmp_path):
    """``extractall`` would merge into whatever already sits in the twin -- an
    earlier record synced in place, or a crashed extraction -- so a non-empty
    twin is refused, nothing is extracted and the zip stays where it is."""
    z = _build_zip(tmp_path)
    twin = _finished_dir(tmp_path)
    twin.mkdir(parents=True)
    (twin / "earlier-record.txt").write_text("synced in place", encoding="utf-8")
    before = z.read_bytes()

    ok, dest, note = reset_to_finished(z)

    assert not ok
    assert dest == twin
    assert "not empty" in note and str(twin) in note
    assert sorted(p.name for p in twin.iterdir()) == ["earlier-record.txt"]
    assert z.read_bytes() == before
    assert not z.with_suffix(".orig").exists()
    # An empty twin is not a collision.
    (twin / "earlier-record.txt").unlink()
    assert reset_to_finished(z)[0]


# ------------------------------------------------------- RUNS-layout sequence

RUNS_SEQ = "120155__XRDS_generic_scan__CoO-987655"
ACT_DIR = f"{EXP_DIR}/0__0__XRDS__acquire_frame"
PRC_NAME = "0__0690e558-0b51-7466-8000-ccac06b55692__xrds_frame"
SYNCED_PRG = "yml: x\nsynced: true\n"


def _build_runs_dir(tmp_path: Path, fmt: str = "json") -> Path:
    """A synced sequence in the single ``RUNS`` tree, every record with its ``.prg``.

    ``fmt="json"``: every record ``.json``. ``fmt="mixed"``: a ``-seq.yml``
    carrying a comment above ``.json`` experiment/action/process records -- a
    sequence that straddled the storage upgrade.
    """
    seq_dir = tmp_path / "RUNS" / "2025" / "1003" / RUNS_SEQ
    (seq_dir / ACT_DIR).mkdir(parents=True)
    seq = seq_dir / "251003.120155695637-seq.json"
    if fmt == "mixed":
        seq.with_suffix(".yml").write_text(
            "# written by an old build\n" + _seq_yml(), encoding="utf-8"
        )
    else:
        write_meta(seq, yml_load(_seq_yml(), fast=True))
    seq.with_suffix(".prg").write_text(SYNCED_PRG, encoding="utf-8")
    for rel, text in (
        (f"{EXP_DIR}/251003.120155695637-exp", _exp_yml()),
        (f"{ACT_DIR}/251003.120155695637-act", _act_yml("ref")),
    ):
        write_meta(seq_dir / f"{rel}.json", yml_load(text, fast=True))
        (seq_dir / f"{rel}.prg").write_text(SYNCED_PRG, encoding="utf-8")
    write_meta(
        seq_dir / EXP_DIR / f"{PRC_NAME}-prc.json", yml_load(_prc_yml(), fast=True)
    )
    (seq_dir / ACT_DIR / "X0-000-0000.jsonl").write_text('{"v": 1}\n', "utf-8")
    return seq_dir


def _pending(tmp_path: Path) -> list:
    """What the syncer's startup sweep would enqueue from ``<tmp_path>/RUNS``."""
    from types import SimpleNamespace

    from helao.hexagon.adapters.native.sync_driver import SyncDriver

    me = SimpleNamespace(helaodirs=SimpleNamespace(save_root=tmp_path / "RUNS"))
    return (
        SyncDriver.list_pending(me)  # type: ignore[arg-type]
        + SyncDriver.list_pending_exps(me)  # type: ignore[arg-type]
        + SyncDriver.list_pending_acts(me)  # type: ignore[arg-type]
    )


@pytest.mark.parametrize("fmt", ["json", "mixed"])
def test_a_runs_sequence_is_retagged_in_place_in_each_files_own_format(
    tmp_path, capsys, fmt
):
    seq_dir = _build_runs_dir(tmp_path, fmt)
    assert _pending(tmp_path) == []  # synced: nothing for the syncer to do

    assert main([str(seq_dir), "--run-use", "data"]) == 0
    out = capsys.readouterr().out

    act = seq_dir / ACT_DIR / "251003.120155695637-act.json"
    exp = seq_dir / EXP_DIR / "251003.120155695637-exp.json"
    prc = seq_dir / EXP_DIR / f"{PRC_NAME}-prc.json"
    for path in (act, exp, prc):
        text = path.read_text(encoding="utf-8")
        assert text.startswith("{\n  "), path  # still pretty JSON
        assert json.loads(text)["run_use"] == "data"
    assert json.loads(act.read_text(encoding="utf-8"))["files"][0]["run_use"] == (
        "data"
    )
    if fmt == "mixed":
        seq = seq_dir / "251003.120155695637-seq.yml"
        assert seq.read_text(encoding="utf-8").startswith("# written by an old build")
        assert not seq.with_suffix(".json").exists()
    assert not list(seq_dir.rglob("*.prg"))
    assert "retagged 3 yml(s) to run_use=data" in out
    (seq_record,) = meta_glob(seq_dir, "seq")
    assert f"/finish_yml?yml_path={seq_record}" in out
    # Every record is pending again, so the next sweep re-pushes the sequence.
    assert len(_pending(tmp_path)) == 3


@pytest.mark.parametrize("prg", ["missing", "unsynced"])
def test_a_runs_sequence_not_fully_synced_is_refused_with_nothing_written(
    tmp_path, capsys, prg
):
    seq_dir = _build_runs_dir(tmp_path)
    act_prg = seq_dir / ACT_DIR / "251003.120155695637-act.prg"
    if prg == "missing":
        act_prg.unlink()
    else:
        act_prg.write_text("yml: x\nsynced: false\n", encoding="utf-8")
    before = {p: p.read_bytes() for p in seq_dir.rglob("*") if p.is_file()}

    for extra in ([], ["--no-reset"], ["--dry-run"]):
        assert main([str(seq_dir), *extra]) != 0
        err = capsys.readouterr().err
        assert "251003.120155695637-act.json" in err
        assert {p: p.read_bytes() for p in seq_dir.rglob("*") if p.is_file()} == before


def test_dry_run_on_a_runs_sequence_reports_and_writes_nothing(tmp_path, capsys):
    seq_dir = _build_runs_dir(tmp_path)
    before = {p: p.read_bytes() for p in seq_dir.rglob("*") if p.is_file()}
    assert main([str(seq_dir), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "would retag 3 yml(s)" in out
    assert "would delete 3 .prg" in out
    assert {p: p.read_bytes() for p in seq_dir.rglob("*") if p.is_file()} == before


def test_no_reset_on_a_runs_sequence_keeps_the_prg_files(tmp_path):
    seq_dir = _build_runs_dir(tmp_path)
    assert main([str(seq_dir), "--no-reset"]) == 0
    assert len(list(seq_dir.rglob("*.prg"))) == 3


@pytest.mark.parametrize(
    "source, no_reset",
    [("zip", ["--no-reset"]), ("runs", []), ("runs", ["--no-reset"])],
)
def test_an_already_retagged_record_is_nothing_to_change_and_exits_zero(
    tmp_path, capsys, source, no_reset
):
    """An idempotent re-run succeeds; a RUNS sequence then keeps its ``.prg``s."""
    if source == "zip":
        path = _build_zip(tmp_path, run_use="data")
        rewrite_zip(path, "data")  # adds the experiment's missing key too
    else:
        path = _build_runs_dir(tmp_path)
        assert main([str(path), "--no-reset"]) == 0
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    capsys.readouterr()

    assert main([str(path), *no_reset]) == 0

    assert "nothing to change" in capsys.readouterr().out
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


def test_a_zip_with_no_record_in_it_exits_non_zero(tmp_path, capsys):
    """Nothing recognised is not "nothing to change": it is the vacuous case."""
    day = tmp_path / "RUNS_SYNCED" / "25.39" / "1003"
    day.mkdir(parents=True)
    z = day / "120155__XRDS_generic_scan__CoO-987655.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr(HLO_MEMBER, b"payload")
    assert main([str(z), "--no-reset"]) != 0
    assert "no record" in capsys.readouterr().err


def test_a_json_member_of_a_zip_is_left_byte_for_byte(tmp_path):
    """Legacy archives hold yml only; a .json record member is never re-emitted."""
    z = _build_zip(tmp_path)
    member = f"{EXP_DIR}/0__0__XRDS__acquire_frame/251003.120155695638-act.json"
    payload = b'{"run_use": "ref"}'
    with zipfile.ZipFile(z, "a") as zf:
        zf.writestr(member, payload)
    edits, _ = rewrite_zip(z, "data")
    assert member not in [e.path for e in edits]
    with zipfile.ZipFile(z) as zf:
        assert zf.read(member) == payload


WRITE_OFF_PRG = (
    "yml: x\nsynced: true\nwrite_off:\n  at: 2026-10-01\n  operator: op\n"
    "  reason: lost\n  groups:\n    0:\n    - 0\n"
)


@pytest.mark.parametrize(
    "extra", [[], ["--no-reset"], ["--dry-run"], ["--reset-only"]], ids=str
)
def test_a_written_off_runs_sequence_is_refused_with_nothing_written(
    tmp_path, capsys, extra
):
    """A reset would drop the operator's write_off and re-park the experiment."""
    seq_dir = _build_runs_dir(tmp_path)
    (seq_dir / EXP_DIR / "251003.120155695637-exp.prg").write_text(
        WRITE_OFF_PRG, encoding="utf-8"
    )
    before = {p: p.read_bytes() for p in seq_dir.rglob("*") if p.is_file()}
    assert main([str(seq_dir), *extra]) != 0
    assert "write_off" in capsys.readouterr().err
    assert {p: p.read_bytes() for p in seq_dir.rglob("*") if p.is_file()} == before


def test_no_reset_then_reset_only_hands_the_sequence_back(tmp_path, capsys):
    """Probes P1 + P3: the edits are already on disk, the .prg files still synced."""
    seq_dir = _build_runs_dir(tmp_path)
    assert main([str(seq_dir), "--no-reset"]) == 0
    capsys.readouterr()

    assert main([str(seq_dir)]) == 0  # P1: nothing to change, and says how to go on
    out = capsys.readouterr().out
    assert "nothing to change" in out and "--reset-only" in out
    assert len(list(seq_dir.rglob("*.prg"))) == 3

    assert main([str(seq_dir), "--reset-only", "--dry-run"]) == 0
    assert "would delete 3 .prg" in capsys.readouterr().out
    assert len(list(seq_dir.rglob("*.prg"))) == 3

    assert main([str(seq_dir), "--reset-only"]) == 0
    out = capsys.readouterr().out
    assert not list(seq_dir.rglob("*.prg"))
    assert "/finish_yml?yml_path=" in out
    assert len(_pending(tmp_path)) == 3  # P3: re-queued


def test_an_interrupted_reset_is_refused_then_finished_by_reset_only(tmp_path, capsys):
    """Probe P2: some .prg already deleted by a reset that did not finish."""
    seq_dir = _build_runs_dir(tmp_path)
    assert main([str(seq_dir), "--no-reset"]) == 0
    (seq_dir / "251003.120155695637-seq.prg").unlink()
    capsys.readouterr()

    assert main([str(seq_dir)]) != 0
    assert "--reset-only" in capsys.readouterr().err

    assert main([str(seq_dir), "--reset-only"]) == 0
    assert not list(seq_dir.rglob("*.prg"))
    assert len(_pending(tmp_path)) == 3


def test_reset_only_refuses_a_sync_in_flight(tmp_path, capsys):
    seq_dir = _build_runs_dir(tmp_path)
    act_prg = seq_dir / ACT_DIR / "251003.120155695637-act.prg"
    act_prg.write_text("yml: x\nsynced: false\n", encoding="utf-8")
    assert main([str(seq_dir), "--reset-only"]) != 0
    assert str(act_prg) in capsys.readouterr().err
    assert len(list(seq_dir.rglob("*.prg"))) == 3


def test_reset_only_refuses_a_zip(tmp_path, capsys):
    z = _build_zip(tmp_path)
    before = z.read_bytes()
    assert main([str(z), "--reset-only"]) != 0
    assert "RUNS" in capsys.readouterr().err
    assert z.read_bytes() == before


def test_the_finish_yml_hint_is_absolute_for_a_relative_input(
    tmp_path, capsys, monkeypatch
):
    seq_dir = _build_runs_dir(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main([str(seq_dir.relative_to(tmp_path))]) == 0
    hint = next(
        ln for ln in capsys.readouterr().out.splitlines() if "/finish_yml" in ln
    )
    target = hint.split("yml_path=", 1)[1].split(" ", 1)[0]
    assert Path(target).is_absolute() and Path(target).is_file()
