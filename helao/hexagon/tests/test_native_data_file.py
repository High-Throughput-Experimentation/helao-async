"""NativeDataFileWriter (P2b-1): verbatim re-body of legacy DataFileWriter
(helao/core/servers/active_data_file.py). Source-parity pin + real-tmp-tree
behavior checks for the §5.4 quirks: w+ truncate-on-create, filename autogen
format, one-shot a+ header+%%+payload, save_data gate, posix
PureWindowsPath+.strip("\\\\") path quirk, FileInfo recording."""

import os

import pytest

from helao.core.models.file import HloFileGroup
from helao.core.servers.active_data_file import DataFileWriter
from helao.hexagon.adapters.native.data_file import NativeDataFileWriter
from helao.hexagon.tests.native_fixtures import (
    assert_source_parity,
    make_base,
    mk_action,
    mk_active,
)

METHODS = [
    "__init__",
    "update_act_file",
    "init_datafile",
    "finish_hlo_header",
    "log_data_set_output_file",
    "_resolve_output_path",
    "write_file",
    "write_file_nowait",
    "track_file",
    "relocate_files",
]


def test_source_parity_with_legacy():
    assert_source_parity(NativeDataFileWriter, DataFileWriter, METHODS)


def _native_active(tmp_path, **action_over):
    base = make_base(str(tmp_path / "RUNS_ACTIVE"))
    active, dflt = mk_active(
        base, action=mk_action(**action_over) if action_over else None
    )
    active.data_file_writer = NativeDataFileWriter(active)  # type: ignore[reportAttributeAccessIssue]  # the swap under test
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
    assert file_info.data_keys == ["t_s"]


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
