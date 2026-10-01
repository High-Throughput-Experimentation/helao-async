"""NativeDataFileWriter (P2b-1): verbatim re-body of legacy DataFileWriter
(helao/core/servers/active_data_file.py, deleted by B7b). Real-tmp-tree
behavior checks for the §5.4 quirks: w+ truncate-on-create, filename autogen
format, one-shot a+ header+%%+payload, save_data gate, posix
PureWindowsPath+.strip("\\\\") path quirk, FileInfo recording."""

import os

import pytest

from helao.core.models.file import HloFileGroup
from helao.helpers.premodels import Action
from helao.hexagon.adapters.native.data_file import NativeDataFileWriter
from helao.hexagon.tests.native_fixtures import make_base, mk_action, mk_active


def _native_active(tmp_path, **action_over):
    base = make_base(str(tmp_path / "RUNS_ACTIVE"))
    active, dflt = mk_active(
        base, action=mk_action(**action_over) if action_over else None
    )
    assert isinstance(active.data_file_writer, NativeDataFileWriter)
    return base, active, dflt


def test_init_datafile_autogen_filename(tmp_path):
    _, active, dflt = _native_active(tmp_path)
    header, file_info = active.init_datafile(
        header={"a": 1},
        file_type="nu__test_file",
        json_data_keys=["t_s"],
        file_sample_label=None,
        filename=None,
        file_group=HloFileGroup.helao_files,
        file_conn_key=dflt,  # type: ignore[reportArgumentType]
    )
    a = active.action
    assert (
        file_info.file_name
        == f"{a.action_abbr}-{a.orch_submit_order}.{a.action_order}.{a.action_retry}.{a.action_split}__0.hlo"
    )
    assert header.endswith("\n")
    assert "a: 1" in header
    assert file_info.data_keys == ["t_s"]
    assert file_info.file_type == "nu__test_file"
    assert file_info.action_uuid == a.action_uuid


def test_init_datafile_empty_header_variants(tmp_path):
    _, active, _ = _native_active(tmp_path)
    for hdr in ({}, [], None):
        header, _ = active.init_datafile(
            header=hdr,
            file_type="t",
            json_data_keys=None,
            file_sample_label=None,
            filename="x.csv",
            file_group=HloFileGroup.aux_files,
        )
        assert header == ""  # {} must NOT become "{}\n"


@pytest.mark.asyncio
async def test_log_data_set_output_file_truncates_stale_bytes(tmp_path):
    """w+ open: stale crash bytes must not survive ahead of the header
    (active_data_file.py:264-272 rationale comment)."""
    base, active, dflt = _native_active(tmp_path)
    out_dir = os.path.join(
        str(base.helaodirs.save_root), str(active.action.action_output_dir)
    )
    os.makedirs(out_dir, exist_ok=True)
    a = active.action
    fname = f"{a.action_abbr}-{a.orch_submit_order}.{a.action_order}.{a.action_retry}.{a.action_split}__0.hlo"
    stale = os.path.join(out_dir, fname)
    open(stale, "w").write("STALE-CRASH-BYTES\n")
    active.file_conn_dict[dflt].params.hloheader.epoch_ns = 1234567890
    await active.log_data_set_output_file(file_conn_key=dflt)
    await active.file_conn_dict[dflt].file.close()
    text = open(stale).read()
    assert "STALE-CRASH-BYTES" not in text
    assert "epoch_ns: 1234567890" in text
    assert active.action.files and active.action.files[-1].file_name == fname


@pytest.mark.asyncio
async def test_write_file_one_shot_layout_and_gate(tmp_path):
    base, active, _ = _native_active(tmp_path)
    path = await active.write_file(
        output_str="r1,r2",
        file_type="aux__csv",
        filename="one.csv",
        header="colA,colB",
    )
    assert path is not None and path.endswith("one.csv")
    assert open(path).read() == "colA,colB\n%%\nr1,r2"
    assert any(fi.file_name == "one.csv" for fi in active.action.files)
    # append mode a+ (not w+): a second write appends
    await active.write_file(output_str="r3", file_type="aux__csv", filename="one.csv")
    assert open(path).read() == "colA,colB\n%%\nr1,r2%%\nr3"
    # save_data gate
    active.action.save_data = False
    assert (
        await active.write_file(output_str="x", file_type="t", filename="no.csv")
        is None
    )
    assert not os.path.exists(os.path.join(os.path.dirname(path), "no.csv"))


def test_write_file_nowait_matches_async_layout(tmp_path):
    base, active, _ = _native_active(tmp_path)
    path = active.write_file_nowait(
        output_str="r1", file_type="aux__csv", filename="two.csv", header="h"
    )
    assert path is not None
    assert open(path).read() == "h\n%%\nr1"


def test_resolve_output_path_posix_strip_quirk(tmp_path):
    """posix branch: PureWindowsPath normalization + .strip("\\\\")
    (active_data_file.py:313-316) — byte-copied, not 'fixed'."""
    base, active, _ = _native_active(tmp_path)
    result = active._resolve_output_path(
        file_type="t",
        filename="f.csv",
        file_group=HloFileGroup.aux_files,
        header=None,
        file_sample_label=None,
        json_data_keys=None,
        action=active.action,
    )
    assert result is not None
    _, _, _, output_file = result
    assert "\\" not in output_file  # windows seps collapsed on posix


@pytest.mark.asyncio
async def test_finish_hlo_header_stamps_only_unset(tmp_path):
    base, active, dflt = _native_active(tmp_path)
    active.file_conn_dict[dflt].params.hloheader.epoch_ns = None
    active.finish_hlo_header(realtime=42)
    assert active.file_conn_dict[dflt].params.hloheader.epoch_ns == 42
    active.finish_hlo_header(realtime=99)
    assert active.file_conn_dict[dflt].params.hloheader.epoch_ns == 42  # not re-stamped


@pytest.mark.asyncio
async def test_write_file_creates_a_subdirectory_named_by_the_filename(tmp_path):
    """Amendment A14.4: makedirs covered the record root, not the file's dir.

    ``file_name`` is record-relative since the upload set is built from it, so
    a one-shot write under a subdirectory name is legitimate. It used to fail
    with FileNotFoundError because only the record root was created.
    """
    _, active, _ = _native_active(tmp_path)
    path = await active.write_file(
        output_str="payload",
        file_type="aux__csv",
        filename="subdir/nested.csv",
    )
    assert path is not None and os.path.isfile(path)
    assert os.path.basename(os.path.dirname(path)) == "subdir"


def test_init_datafile_explicit_filename_aux(tmp_path):
    """Moved from unit_test_active_data_file: an explicit filename is used as
    given, an empty header stays empty, and the sample label is recorded."""
    _, active, _ = _native_active(tmp_path)
    header, file_info = active.init_datafile(
        header=None,
        file_type="df__aux",
        json_data_keys=None,
        file_sample_label="label-1",
        filename="explicit.csv",
        file_group=HloFileGroup.aux_files,
    )
    assert file_info.file_name == "explicit.csv"
    assert header == ""
    assert list(file_info.sample) == ["label-1"]


def test_resolve_output_path_save_data_false(tmp_path):
    """Moved from unit_test_active_data_file: save_data=False resolves to None."""
    _, active, _ = _native_active(tmp_path)
    result = active._resolve_output_path(
        file_type="df__blob",
        filename="whatever.txt",
        file_group=HloFileGroup.aux_files,
        header=None,
        file_sample_label=None,
        json_data_keys=None,
        action=Action(action_name="x", save_data=False),
    )
    assert result is None


@pytest.mark.asyncio
async def test_track_file_outside_the_output_dir_records_its_basename(tmp_path):
    """Moved from unit_test_active_data_file: a file outside the action's
    output dir is recorded under its basename."""
    _, active, _ = _native_active(tmp_path)
    outside = tmp_path / "elsewhere" / "aux_data.dat"
    outside.parent.mkdir()
    outside.write_text("payload")
    await active.track_file("df__aux", str(outside), [])
    assert any(fi.file_name == "aux_data.dat" for fi in active.action.files)
