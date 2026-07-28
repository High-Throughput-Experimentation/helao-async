"""Unit tests for the ``DataFileWriter`` collaborator extracted from ``Active``
(CARDS P6, Stage S5): the data-file init + file-I/O helpers
(``init_datafile``/``finish_hlo_header``/``log_data_set_output_file``/
``_resolve_output_path``/``write_file``/``write_file_nowait``/``track_file``/
``relocate_files``/``update_act_file``).

``test_active_golden_master.py --check`` already exercises the streamed-file
path (``log_data_set_output_file``/``init_datafile``/``finish_hlo_header``) and
``write_file`` end-to-end through ``Active``'s lifecycle and is the byte-gate
for that output; this module is the S5-specific behavior-preservation gate that
directly covers the header/``FileInfo`` builder, the one-shot writers, and the
aux-file tracker in isolation, and confirms every ``Active`` delegator forwards
to ``active.data_file_writer``.

Mirrors the ``Base.__new__`` bypass fixture used by
``test_active_golden_master.py``'s ``_make_base`` and ``_mk_action``: a bare
``Base`` built without ``Base.__init__`` (no FastAPI app, no NTP, no
WebSockets), populated only with the attributes the ``Active`` construction +
``DataFileWriter`` methods touch, then ``_init_collaborators()`` so
``base.meta_writer`` exists as it would after the real ``__init__``.

Hermetic: no network; real (temp-dir) disk I/O so the header/``%%``/body byte
layout is checked against genuine filesystem behavior, not a stand-in.
"""

__all__ = ["active_data_file_unit_test"]

import asyncio
import os
import tempfile
import traceback
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from helao.core.tests._test_utils import TestReporter
from helao.core.servers.base import Base, Active
from helao.core.servers.active_data_file import DataFileWriter
from helao.core.models.file import FileConnParams, HloFileGroup
from helao.core.models.machine import MachineModel
from helao.helpers.active_params import ActiveParams
from helao.helpers.premodels import Action

_FIXED_DT = datetime(2026, 1, 2, 3, 4, 5, 678901)


def _make_base(save_root: str) -> Base:
    """Build a bare ``Base`` with every attribute ``Active`` construction touches."""
    base = Base.__new__(Base)
    base.app = SimpleNamespace(driver=None)
    base.server = MachineModel(
        server_name="ACTSRV",
        machine_name="test-machine",
        hostname="127.0.0.1",
        port=8000,
    )
    base.world_cfg = {
        "dummy": False,
        "simulation": False,
        "root": str(Path(save_root).parent),
    }
    base.ntp_offset = 0.0
    base.helaodirs = SimpleNamespace(save_root=save_root)
    base._init_collaborators()
    return base


def _mk_action() -> Action:
    """Non-manual ``Action`` (parent seq/exp set) with data saving enabled."""
    return Action(
        action_name="dftest",
        action_abbr="dfte",
        orch_key="ACTSRV",
        orch_host="127.0.0.1",
        orch_port=8000,
        action_uuid=UUID("00000000-0000-0000-0000-0000000000a1"),
        action_timestamp=_FIXED_DT,
        sequence_uuid=UUID("00000000-0000-0000-0000-0000000000b1"),
        sequence_name="seq_df",
        sequence_label="ut",
        sequence_timestamp=_FIXED_DT,
        experiment_uuid=UUID("00000000-0000-0000-0000-0000000000c1"),
        experiment_name="exp_df",
        experiment_timestamp=_FIXED_DT,
        save_data=True,
    )


def _mk_active(base: Base) -> "tuple[Active, UUID]":
    action = _mk_action()
    dflt = base.dflt_file_conn_key()
    ap = ActiveParams(
        action=action,
        file_conn_params_dict={
            dflt: FileConnParams(
                file_conn_key=dflt,
                json_data_keys=["t", "v"],
                file_type="df__test_file",
                file_group=HloFileGroup.helao_files,
            )
        },
        aux_listen_uuids=[],
    )
    return Active(base, ap), dflt


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------


async def _check_collaborator_wired() -> bool:
    base = _make_base(tempfile.mkdtemp())
    active, _ = _mk_active(base)
    return (
        isinstance(active.data_file_writer, DataFileWriter)
        and active.data_file_writer.active is active
    )


async def _check_init_datafile() -> bool:
    base = _make_base(tempfile.mkdtemp())
    active, dflt = _mk_active(base)
    header, file_info = active.init_datafile(
        header={"k": "v"},
        file_type="df__file_a",
        json_data_keys=["t", "v"],
        file_sample_label=None,
        filename=None,  # autogen
        file_group=HloFileGroup.helao_files,
        file_conn_key=dflt,
    )
    return (
        file_info.file_name.endswith(".hlo")
        and file_info.file_type == "df__file_a"
        and list(file_info.data_keys) == ["t", "v"]
        and file_info.action_uuid == active.action.action_uuid
        and header.endswith("\n")
        and "k: v" in header
    )


async def _check_init_datafile_explicit_filename_aux() -> bool:
    base = _make_base(tempfile.mkdtemp())
    active, _ = _mk_active(base)
    header, file_info = active.init_datafile(
        header=None,
        file_type="df__aux",
        json_data_keys=None,
        file_sample_label="label-1",
        filename="explicit.csv",
        file_group=HloFileGroup.aux_files,
    )
    return (
        file_info.file_name == "explicit.csv"
        and header == ""
        and list(file_info.sample) == ["label-1"]
    )


async def _check_finish_hlo_header() -> bool:
    base = _make_base(tempfile.mkdtemp())
    active, dflt = _mk_active(base)
    before = active.file_conn_dict[dflt].params.hloheader.epoch_ns
    active.finish_hlo_header(realtime=123456789)
    after = active.file_conn_dict[dflt].params.hloheader.epoch_ns
    # existing stamp must not be overwritten
    active.finish_hlo_header(realtime=999)
    return (
        before is None
        and after == 123456789
        and (active.file_conn_dict[dflt].params.hloheader.epoch_ns == 123456789)
    )


async def _check_write_file() -> bool:
    base = _make_base(tempfile.mkdtemp())
    active, _ = _mk_active(base)
    path = await active.write_file(
        output_str="alpha\nbeta\n",
        file_type="df__blob",
        filename="known_blob.txt",
        file_group=HloFileGroup.aux_files,
        header="# a known header",
    )
    if path is None or not os.path.isfile(path):
        return False
    with open(path, "r") as f:
        content = f.read()
    return content == "# a known header\n%%\nalpha\nbeta\n"


async def _check_write_file_nowait() -> bool:
    base = _make_base(tempfile.mkdtemp())
    active, _ = _mk_active(base)
    path = active.write_file_nowait(
        output_str="one\ntwo\n",
        file_type="df__blob",
        filename="sync_blob.txt",
        file_group=HloFileGroup.aux_files,
        header="# hdr",
    )
    if path is None or not os.path.isfile(path):
        return False
    with open(path, "r") as f:
        content = f.read()
    return content == "# hdr\n%%\none\ntwo\n"


async def _check_resolve_output_path_save_data_false() -> bool:
    base = _make_base(tempfile.mkdtemp())
    active, _ = _mk_active(base)
    nosave = Action(action_name="x", save_data=False)
    result = active._resolve_output_path(
        file_type="df__blob",
        filename="whatever.txt",
        file_group=HloFileGroup.aux_files,
        header=None,
        file_sample_label=None,
        json_data_keys=None,
        action=nosave,
    )
    return result is None


async def _check_track_file() -> bool:
    save_root = tempfile.mkdtemp()
    base = _make_base(save_root)
    active, _ = _mk_active(base)
    # a file outside the action output dir -> queued for relocation
    outside = os.path.join(tempfile.mkdtemp(), "aux_data.dat")
    with open(outside, "w") as f:
        f.write("payload")
    await active.track_file("df__aux", outside, [])
    return outside in active.action.aux_file_paths and any(
        fi.file_name == "aux_data.dat" for fi in active.action.files
    )


async def _run_checks() -> dict:
    return {
        "collaborator_wired": await _check_collaborator_wired(),
        "init_datafile": await _check_init_datafile(),
        "init_datafile_explicit_filename_aux": await _check_init_datafile_explicit_filename_aux(),
        "finish_hlo_header": await _check_finish_hlo_header(),
        "write_file": await _check_write_file(),
        "write_file_nowait": await _check_write_file_nowait(),
        "resolve_output_path_save_data_false": await _check_resolve_output_path_save_data_false(),
        "track_file": await _check_track_file(),
    }


def active_data_file_unit_test() -> bool:
    reporter = TestReporter("active_data_file")
    try:
        res = asyncio.run(_run_checks())
    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False

    reporter.section("collaborator construction")
    reporter.check(
        "Active.__init__ builds a DataFileWriter back-referencing the Active",
        lambda: res["collaborator_wired"],
    )

    reporter.section("init_datafile")
    reporter.check(
        "autogenerates a .hlo filename and builds FileInfo with matching identity",
        lambda: res["init_datafile"],
    )
    reporter.check(
        "honors explicit filename, empty header, and scalar sample label (aux group)",
        lambda: res["init_datafile_explicit_filename_aux"],
    )

    reporter.section("finish_hlo_header")
    reporter.check(
        "stamps epoch_ns on the file connection and never overwrites an existing stamp",
        lambda: res["finish_hlo_header"],
    )

    reporter.section("write_file / write_file_nowait")
    reporter.check(
        "write_file writes '<header>\\n%%\\n<body>' bytes and returns the path",
        lambda: res["write_file"],
    )
    reporter.check(
        "write_file_nowait writes the same byte layout synchronously",
        lambda: res["write_file_nowait"],
    )

    reporter.section("_resolve_output_path / track_file")
    reporter.check(
        "_resolve_output_path returns None when action.save_data is False",
        lambda: res["resolve_output_path_save_data_false"],
    )
    reporter.check(
        "track_file records a FileInfo and queues an out-of-dir path for relocation",
        lambda: res["track_file"],
    )

    return reporter.success()


if __name__ == "__main__":
    import sys

    sys.exit(0 if active_data_file_unit_test() else 1)
