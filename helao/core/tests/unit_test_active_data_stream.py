"""Unit tests for the ``DataStreamer`` collaborator extracted from ``Active``
(CARDS P6, Stage S6): the async data-streaming cluster
(``get_realtime``/``get_realtime_nowait``/``write_live_data``/
``enqueue_data_dflt``/``_build_data_package``/``enqueue_data``/
``enqueue_data_nowait``/``assemble_data_msg``/``add_new_listen_uuid``/
``log_data_task``).

``test_active_golden_master.py --check`` is the byte+whole-record gate for the
streamed ``.hlo`` output across the full ``Active`` lifecycle; this module is
the S6-specific behavior-preservation gate that drives the enqueue -> ``data_q``
-> ``log_data_task`` drain -> file-write path directly and asserts the pieces in
isolation: that the queued/written counters advance, that streamed data reaches
the ``.hlo`` file, that ``add_new_listen_uuid`` mutates the ``Active``'s
``listen_uuids``, and that ``assemble_data_msg`` / ``_build_data_package`` build
the expected package shape. Also confirms every ``Active`` delegator forwards to
``active.data_stream`` and that all mutable data-stream state stays on
``Active``.

Mirrors the ``Base.__new__`` bypass fixture used by
``unit_test_active_data_file.py`` / ``test_active_golden_master.py``'s
``_make_base`` + ``_mk_action``, additionally wiring the real ``data_q``
(``MultisubscriberQueue``) and the ``aloop`` the drain loop subscribes to.

Hermetic: no network; real (temp-dir) disk I/O so the streamed ``%%`` +
JSON-row byte layout is checked against genuine filesystem behavior.
"""

__all__ = ["active_data_stream_unit_test"]

import asyncio
import json
import os
import tempfile
import traceback
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from helao.core.tests._test_utils import TestReporter
from helao.core.servers.base import Base, Active
from helao.core.servers.active_data_stream import DataStreamer
from helao.core.models.data import DataModel, DataPackageModel
from helao.core.models.file import FileConnParams, HloFileGroup
from helao.core.models.hlostatus import HloStatus
from helao.core.models.machine import MachineModel
from helao.helpers.active_params import ActiveParams
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.premodels import Action

_FIXED_DT = datetime(2026, 1, 2, 3, 4, 5, 678901)


def _make_base(save_root: str) -> Base:
    """Build a bare ``Base`` with every attribute the data-stream path touches."""
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
    base.aloop = asyncio.get_running_loop()
    base.data_q = MultisubscriberQueue()
    base._init_collaborators()
    return base


def _mk_action(save_data: bool = True) -> Action:
    """Non-manual ``Action`` (parent seq/exp set) with data saving enabled."""
    return Action(
        action_name="dstest",
        action_abbr="dste",
        orch_key="ACTSRV",
        orch_host="127.0.0.1",
        orch_port=8000,
        action_uuid=UUID("00000000-0000-0000-0000-0000000000a2"),
        action_timestamp=_FIXED_DT,
        sequence_uuid=UUID("00000000-0000-0000-0000-0000000000b2"),
        sequence_name="seq_ds",
        sequence_label="ut",
        sequence_timestamp=_FIXED_DT,
        experiment_uuid=UUID("00000000-0000-0000-0000-0000000000c2"),
        experiment_name="exp_ds",
        experiment_timestamp=_FIXED_DT,
        save_data=save_data,
    )


def _mk_active(base: Base, save_data: bool = True) -> "tuple[Active, UUID]":
    action = _mk_action(save_data=save_data)
    dflt = base.dflt_file_conn_key()
    ap = ActiveParams(
        action=action,
        file_conn_params_dict={
            dflt: FileConnParams(
                file_conn_key=dflt,
                json_data_keys=["t", "v"],
                file_type="ds__test_file",
                file_group=HloFileGroup.helao_files,
            )
        },
        aux_listen_uuids=[],
    )
    return Active(base, ap), dflt


async def _drain(active: Active, timeout_s: float = 5.0):
    """Block until the drain loop has consumed every data-bearing packet."""
    waited = 0.0
    while active.num_data_queued > active.num_data_written and waited < timeout_s:
        await asyncio.sleep(0.01)
        waited += 0.01
    # settle the threadpool aiofiles open/write future
    await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------


async def _check_collaborator_wired() -> bool:
    base = _make_base(tempfile.mkdtemp())
    active, _ = _mk_active(base)
    return (
        isinstance(active.data_stream, DataStreamer)
        and active.data_stream.active is active
    )


async def _check_realtime_forwarding() -> bool:
    base = _make_base(tempfile.mkdtemp())
    active, _ = _mk_active(base)
    # offset 0 (ntp_offset=0.0) + explicit epoch_ns -> deterministic passthrough
    nowait = active.get_realtime_nowait(epoch_ns=123456789)
    awaited = await active.get_realtime(epoch_ns=123456789)
    return nowait == 123456789 and awaited == 123456789


async def _check_add_new_listen_uuid_mutates_active() -> bool:
    base = _make_base(tempfile.mkdtemp())
    active, _ = _mk_active(base)
    # action_uuid is added during __init__; listen_uuids lives on Active
    before = list(active.listen_uuids)
    new = UUID("00000000-0000-0000-0000-0000000000ff")
    active.add_new_listen_uuid(new)
    return (
        active.action.action_uuid in before
        and new in active.listen_uuids
        and active.data_stream.active.listen_uuids is active.listen_uuids
    )


async def _check_assemble_and_build_package() -> bool:
    base = _make_base(tempfile.mkdtemp())
    active, dflt = _mk_active(base)
    dm = DataModel(data={dflt: {"t": 1, "v": 2}}, errors=[], status=HloStatus.active)
    pkg = active.assemble_data_msg(datamodel=dm)
    if not isinstance(pkg, DataPackageModel):
        return False
    if pkg.action_uuid != active.action.action_uuid:
        return False
    if pkg.action_name != active.action.action_name:
        return False
    built_pkg, has_data = active._build_data_package(dm)
    empty_pkg, empty_has = active._build_data_package(
        DataModel(data={}, errors=[], status=HloStatus.active)
    )
    return (
        isinstance(built_pkg, DataPackageModel)
        and has_data is True
        and empty_has is False
    )


async def _check_enqueue_drains_and_writes() -> bool:
    """enqueue_data_dflt + enqueue_data -> counters advance and rows land in the .hlo."""
    save_root = tempfile.mkdtemp()
    base = _make_base(save_root)
    active, dflt = _mk_active(base)
    logger = base.aloop.create_task(active.log_data_task())
    # let the drain loop subscribe to data_q before publishing (MultisubscriberQueue
    # only delivers to subscribers present at put time) -- mirrors myinit ordering
    await asyncio.sleep(0.05)
    try:
        for i in range(3):
            await active.enqueue_data_dflt({"t": i, "v": i * 10})
        # explicit enqueue_data on the same conn key
        await active.enqueue_data(
            DataModel(
                data={dflt: {"t": 99, "v": 990}}, errors=[], status=HloStatus.active
            )
        )
        await _drain(active)
    finally:
        logger.cancel()
        try:
            await logger
        except asyncio.CancelledError:
            pass

    if active.num_data_queued != 4 or active.num_data_written != 4:
        return False

    # locate the streamed .hlo file and confirm every enqueued point is present
    fc = active.file_conn_dict.get(dflt)
    if fc is None or fc.file is None:
        return False
    await fc.file.close()
    output_dir = os.path.join(save_root, active.action.action_output_dir)
    hlo_files = [f for f in os.listdir(output_dir) if f.endswith(".hlo")]
    if len(hlo_files) != 1:
        return False
    with open(os.path.join(output_dir, hlo_files[0]), "r") as f:
        body = f.read()
    if "%%" not in body:
        return False
    data_lines = [
        json.loads(ln) for ln in body.split("%%", 1)[1].splitlines() if ln.strip()
    ]
    expected = [
        {"t": 0, "v": 0},
        {"t": 1, "v": 10},
        {"t": 2, "v": 20},
        {"t": 99, "v": 990},
    ]
    return data_lines == expected


async def _check_enqueue_nowait_counts() -> bool:
    """enqueue_data_nowait bumps num_data_queued; empty-data packet does not."""
    base = _make_base(tempfile.mkdtemp())
    active, dflt = _mk_active(base)
    active.enqueue_data_nowait(
        DataModel(data={dflt: {"t": 0, "v": 0}}, errors=[], status=HloStatus.active)
    )
    after_data = active.num_data_queued
    active.enqueue_data_nowait(DataModel(data={}, errors=[], status=HloStatus.active))
    after_empty = active.num_data_queued
    return after_data == 1 and after_empty == 1


async def _check_save_data_false_no_write() -> bool:
    """log_data_task returns immediately when save_data is False; nothing is written."""
    save_root = tempfile.mkdtemp()
    base = _make_base(save_root)
    active, dflt = _mk_active(base, save_data=False)
    logger = base.aloop.create_task(active.log_data_task())
    try:
        await active.enqueue_data_dflt({"t": 0, "v": 0})
        await asyncio.sleep(0.1)
    finally:
        logger.cancel()
        try:
            await logger
        except asyncio.CancelledError:
            pass
    # queued counter still advances (enqueue path), but no file connection opened
    return (
        active.num_data_queued == 1
        and active.num_data_written == 0
        and active.file_conn_dict[dflt].file is None
    )


async def _run_checks() -> dict:
    return {
        "collaborator_wired": await _check_collaborator_wired(),
        "realtime_forwarding": await _check_realtime_forwarding(),
        "add_new_listen_uuid_mutates_active": await _check_add_new_listen_uuid_mutates_active(),
        "assemble_and_build_package": await _check_assemble_and_build_package(),
        "enqueue_drains_and_writes": await _check_enqueue_drains_and_writes(),
        "enqueue_nowait_counts": await _check_enqueue_nowait_counts(),
        "save_data_false_no_write": await _check_save_data_false_no_write(),
    }


def active_data_stream_unit_test() -> bool:
    reporter = TestReporter("active_data_stream")
    try:
        res = asyncio.run(_run_checks())
    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False

    reporter.section("collaborator construction")
    reporter.check(
        "Active.__init__ builds a DataStreamer back-referencing the Active",
        lambda: res["collaborator_wired"],
    )

    reporter.section("realtime forwarders")
    reporter.check(
        "get_realtime / get_realtime_nowait forward to Base (deterministic epoch_ns)",
        lambda: res["realtime_forwarding"],
    )

    reporter.section("listen-uuid state stays on Active")
    reporter.check(
        "add_new_listen_uuid appends to the Active's own listen_uuids list",
        lambda: res["add_new_listen_uuid_mutates_active"],
    )

    reporter.section("package assembly")
    reporter.check(
        "assemble_data_msg / _build_data_package build a DataPackageModel with has_data flag",
        lambda: res["assemble_and_build_package"],
    )

    reporter.section("enqueue -> drain -> write")
    reporter.check(
        "enqueue_data(_dflt) advances both counters and every row lands in the .hlo",
        lambda: res["enqueue_drains_and_writes"],
    )
    reporter.check(
        "enqueue_data_nowait bumps num_data_queued for data, not for an empty packet",
        lambda: res["enqueue_nowait_counts"],
    )
    reporter.check(
        "log_data_task writes nothing when save_data is False",
        lambda: res["save_data_false_no_write"],
    )

    return reporter.success()


if __name__ == "__main__":
    import sys

    sys.exit(0 if active_data_stream_unit_test() else 1)
