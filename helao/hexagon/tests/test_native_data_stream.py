"""NativeDataStreamer (P2b-1): verbatim re-body of legacy DataStreamer
(helao/core/servers/active_data_stream.py). Source-parity pin + drain-loop
behavior on a real MultisubscriberQueue + tmp tree: lazy open on first
matching packet, json_data_keys inference, %% exactly once, non-serializable
-> error line, string payload raw, listen_uuids filter, queued/written
counters live on Active, cancel removes the data_q subscription."""

import asyncio
import os
from uuid import uuid4

import pytest

from helao.core.models.data import DataModel
from helao.core.models.hlostatus import HloStatus
from helao.core.servers.active_data_stream import DataStreamer
from helao.hexagon.adapters.native.data_file import NativeDataFileWriter
from helao.hexagon.adapters.native.data_stream import NativeDataStreamer
from helao.hexagon.tests.native_fixtures import make_base, mk_active

METHODS = [
    "__init__",
    "get_realtime",
    "get_realtime_nowait",
    "write_live_data",
    "enqueue_data_dflt",
    "_build_data_package",
    "enqueue_data",
    "enqueue_data_nowait",
    "assemble_data_msg",
    "add_new_listen_uuid",
    "log_data_task",
]


def test_source_parity_with_legacy():
    from helao.hexagon.tests.native_fixtures import assert_source_parity

    assert_source_parity(NativeDataStreamer, DataStreamer, METHODS)


def _native_active(tmp_path):
    base = make_base(str(tmp_path / "RUNS_ACTIVE"))
    active, dflt = mk_active(base)
    # mini-graft: both write collaborators native (the drain loop hops
    # active.log_data_set_output_file -> data_file_writer)
    active.data_stream = NativeDataStreamer(active)  # type: ignore[reportAttributeAccessIssue]  # the swap under test
    active.data_file_writer = NativeDataFileWriter(active)  # type: ignore[reportAttributeAccessIssue]  # the swap under test
    return base, active, dflt


@pytest.mark.asyncio
async def test_enqueue_counts_only_data_bearing(tmp_path):
    base, active, dflt = _native_active(tmp_path)
    await active.enqueue_data(DataModel(data={dflt: {"t_s": 1}}, errors=[]))
    await active.enqueue_data(DataModel(data={}, errors=[], status=HloStatus.finished))
    active.enqueue_data_nowait(DataModel(data={dflt: {"t_s": 2}}, errors=[]))
    assert active.num_data_queued == 2  # empty-data packet doesn't count


@pytest.mark.asyncio
async def test_drain_loop_lazy_open_separator_and_rows(tmp_path):
    base, active, dflt = _native_active(tmp_path)
    task = asyncio.get_running_loop().create_task(active.log_data_task())
    await asyncio.sleep(0.05)
    out_dir = os.path.join(
        str(base.helaodirs.save_root), str(active.action.action_output_dir)
    )
    # NO DATA => NO FILE (lazy-open contract, F2a)
    assert not os.path.isdir(out_dir) or not os.listdir(out_dir)

    await active.enqueue_data(
        DataModel(data={dflt: {"t_s": 1, "value": 2.5}}, errors=[])
    )
    await active.enqueue_data(
        DataModel(data={dflt: {"t_s": 2, "value": set()}}, errors=[])
    )  # not serializable
    # DataModel.data is typed dict[UUID, dict], so the normal constructor
    # rejects a str payload outright; model_construct bypasses validation to
    # exercise the legacy string-payload branch (byte-copied but
    # public-path-unreachable via the real constructor).
    await active.enqueue_data(
        DataModel.model_construct(data={dflt: "raw-string-row"}, errors=[])
    )
    await asyncio.sleep(0.2)

    assert active.num_data_written == 3
    task.cancel()
    await asyncio.sleep(0.05)
    # log_data_task's CancelledError handler only removes the subscription
    # (matches legacy) -- it never closes the streamed file, so an explicit
    # close is needed before reading it back (same pattern as
    # test_native_data_file.py's stale-file-conn check).
    await active.file_conn_dict[dflt].file.close()
    hlo = [f for f in os.listdir(out_dir) if f.endswith(".hlo")]
    assert len(hlo) == 1
    text = open(os.path.join(out_dir, hlo[0])).read()
    assert text.count("%%\n") == 1  # separator exactly once
    body = text.split("%%\n", 1)[1]
    lines = body.splitlines()
    # hlo_json_dumps uses compact separators (verified: no spaces)
    assert lines[0] == '{"t_s":1,"value":2.5}'
    assert lines[1] == '{"error":"data was not serializable"}'
    assert lines[2] == "raw-string-row"
    # subscription removed on cancel
    assert len(base.data_q.subscribers) == 0


@pytest.mark.asyncio
async def test_drain_loop_filters_foreign_uuids_and_nonactive_status(tmp_path):
    base, active, dflt = _native_active(tmp_path)
    task = asyncio.get_running_loop().create_task(active.log_data_task())
    await asyncio.sleep(0.05)
    foreign = DataModel(data={dflt: {"t_s": 9}}, errors=[])
    # a packet whose action_uuid is not in listen_uuids must be skipped
    msg = active.assemble_data_msg(datamodel=foreign)
    msg.action_uuid = uuid4()
    await base.data_q.put(msg)
    # finished-status packet must be skipped for writing
    await active.enqueue_data(DataModel(data={}, errors=[], status=HloStatus.finished))
    await asyncio.sleep(0.2)
    assert active.num_data_written == 0
    task.cancel()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_save_data_false_no_logger(tmp_path):
    base = make_base(str(tmp_path / "RUNS_ACTIVE"))
    active, _ = mk_active(base)
    active.action.save_data = False
    active.data_stream = NativeDataStreamer(active)  # type: ignore[reportAttributeAccessIssue]  # the swap under test
    await active.log_data_task()  # returns immediately, no subscription
    assert len(base.data_q.subscribers) == 0
