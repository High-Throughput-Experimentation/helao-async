"""FileInfo.file_name addresses a file relative to its record directory."""

from pathlib import Path

from helao.core.drivers.data.sync_driver import HelaoYml
from helao.helpers.file_utils import _relative_file_name


def test_file_in_record_root_is_a_bare_name(tmp_path: Path):
    (tmp_path / "data.hlo").write_text("x")
    assert _relative_file_name(tmp_path / "data.hlo", tmp_path) == "data.hlo"


def test_file_in_subdirectory_keeps_its_subdirectory(tmp_path: Path):
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "instrument.spc").write_text("x")
    assert (
        _relative_file_name(sub / "instrument.spc", tmp_path) == "subdir/instrument.spc"
    )


def test_separator_is_always_forward_slash(tmp_path: Path):
    """Spec §9: stored paths are forward-slash on every platform."""
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    (sub / "c.spc").write_text("x")
    assert "\\" not in _relative_file_name(sub / "c.spc", tmp_path)


def test_file_outside_the_record_falls_back_to_its_basename(tmp_path: Path):
    """A writer handed an unrelated absolute path must not emit '../..' paths."""
    outside = tmp_path.parent / "elsewhere.spc"
    outside.write_text("x")
    assert _relative_file_name(outside, tmp_path) == "elsewhere.spc"


# --------------------------------------------------------------------------
# HelaoYml.upload_files / warn_unregistered_files (spec §3.5, §3.5.1)
# --------------------------------------------------------------------------


def _action_tree(tmp_path: Path, files_block: str) -> Path:
    """An action directory with an -act.yml whose files list is ``files_block``."""
    act_dir = tmp_path / "RUNS_FINISHED" / "26.35" / "0925" / "seqdir" / "expdir"
    act_dir = act_dir / "0__0__SIM__do_thing"
    act_dir.mkdir(parents=True)
    act_yml = act_dir / "260925.120000000000-act.yml"
    # Not a dedented triple-quote: ``files_block`` is itself multi-line and
    # indented, so interpolating it into one would defeat textwrap.dedent's
    # common-prefix calculation and emit an unparseable yml.
    act_yml.write_text(
        "action_name: do_thing\n"
        "action_uuid: 11111111-1111-1111-1111-111111111111\n"
        "action_status: [finished]\n"
        "files:\n" + files_block + "\n"
    )
    return act_yml


def test_nosync_files_are_not_in_the_upload_set(tmp_path: Path):
    """Spec §3.5: RUNS_NOSYNC is gone, so the flag itself must exclude."""
    act_yml = _action_tree(
        tmp_path,
        "  - {file_name: keep.hlo, nosync: false}\n"
        "  - {file_name: withhold.hlo, nosync: true}",
    )
    (act_yml.parent / "keep.hlo").write_text("x")
    (act_yml.parent / "withhold.hlo").write_text("x")

    names = {p.name for p in HelaoYml(act_yml).upload_files}
    assert "keep.hlo" in names
    assert "withhold.hlo" not in names


def test_registered_subdirectory_file_is_in_the_upload_set(tmp_path: Path):
    act_yml = _action_tree(
        tmp_path, "  - {file_name: subdir/instrument.spc, nosync: false}"
    )
    sub = act_yml.parent / "subdir"
    sub.mkdir()
    (sub / "instrument.spc").write_text("x")

    rels = {
        p.relative_to(act_yml.parent).as_posix() for p in HelaoYml(act_yml).upload_files
    }
    assert rels == {"subdir/instrument.spc"}


def test_staging_file_is_not_in_the_upload_set(tmp_path: Path):
    """The sync-uploads-glob-not-action-files defect, prevented structurally."""
    act_yml = _action_tree(tmp_path, "  - {file_name: real.hlo, nosync: false}")
    (act_yml.parent / "real.hlo").write_text("x")
    (act_yml.parent / ".a1b2c3.tmp").write_text("x")

    names = {p.name for p in HelaoYml(act_yml).upload_files}
    assert names == {"real.hlo"}


def test_unregistered_file_is_reported_but_not_uploaded(tmp_path: Path, caplog):
    """Spec §3.5.1: the gap is made visible, not silently closed or uploaded."""
    act_yml = _action_tree(tmp_path, "  - {file_name: real.hlo, nosync: false}")
    (act_yml.parent / "real.hlo").write_text("x")
    (act_yml.parent / "orphan.spc").write_text("x")

    yml = HelaoYml(act_yml)
    names = {p.name for p in yml.upload_files}
    assert "orphan.spc" not in names

    with caplog.at_level("WARNING"):
        yml.warn_unregistered_files()
    assert "orphan.spc" in caplog.text


def test_named_file_that_is_not_on_disk_is_reported(tmp_path: Path, caplog):
    """Amendment A14.2: silent in, silent out -- the other direction of the gap.

    ``track_file`` on a source outside the record directory records a bare
    basename and never copies the file in, so the entry resolves to nothing.
    A glob of the record directory cannot see it either, so the reconciliation
    warning has to check the ``files`` list against disk as well as disk
    against the ``files`` list.
    """
    act_yml = _action_tree(
        tmp_path,
        "  - {file_name: real.hlo, nosync: false}\n"
        "  - {file_name: elsewhere.spc, nosync: false}",
    )
    (act_yml.parent / "real.hlo").write_text("x")

    yml = HelaoYml(act_yml)
    assert {p.name for p in yml.upload_files} == {"real.hlo"}

    with caplog.at_level("WARNING"):
        reported = yml.warn_unregistered_files()
    assert [p.name for p in reported] == ["elsewhere.spc"]
    assert "elsewhere.spc" in caplog.text


def test_sidecars_are_not_reported_as_unregistered(tmp_path: Path):
    """Spec §4.5 puts .prg beside the yml; it must not look like a gap.

    _is_syncable_misc_file excludes .yml, .hlo, .lock and .tmp -- but NOT
    .prg. The sidecar escapes it today purely because it is written into
    RUNS_SYNCED while the record being globbed is still in RUNS_FINISHED.
    Once the two are colocated, an unguarded reconciliation warning fires on
    every record ever synced.
    """
    act_yml = _action_tree(tmp_path, "  - {file_name: real.hlo, nosync: false}")
    (act_yml.parent / "real.hlo").write_text("x")
    (act_yml.parent / "260925.120000000000-act.prg").write_text("s3: true\napi: true\n")
    (act_yml.parent / "260925.120000000000-act.lock").write_text("")

    assert HelaoYml(act_yml).warn_unregistered_files() == []


def test_a_withheld_file_is_not_reported_as_unregistered(tmp_path: Path):
    """A nosync file is on disk and deliberately absent from the upload set.

    It is named by ``files``, so reporting it as unregistered would tell the
    station to register a file it already registered.
    """
    act_yml = _action_tree(tmp_path, "  - {file_name: withhold.hlo, nosync: true}")
    (act_yml.parent / "withhold.hlo").write_text("x")

    yml = HelaoYml(act_yml)
    assert yml.upload_files == []
    assert yml.warn_unregistered_files() == []
