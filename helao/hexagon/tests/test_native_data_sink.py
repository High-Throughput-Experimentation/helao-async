"""NativeDataSinkAdapter (P2b-1): DataSinkPort over the native write bodies.
Q2 (binding): append_sample / set_estop stay LEGACY-delegated (pure model
mutations + status_q puts — P2a owns the status plane); split routes to the
native finalizer; lbuf members route via active.base (sanctioned)."""

import pytest

from helao.core.models.data import DataModel
from helao.core.models.hlostatus import HloStatus
from helao.core.models.sample import LiquidSample, SampleInheritance
from helao.hexagon.adapters.errors import UnwiredPortError
from helao.hexagon.adapters.native.data_sink import NativeDataSinkAdapter
from helao.hexagon.adapters.native.data_stream import NativeDataStreamer
from helao.hexagon.adapters.native.data_file import NativeDataFileWriter
from helao.hexagon.adapters.native.finalizer import NativeActionFinalizer
from helao.hexagon.ports.data_sink import DataSinkPort
from helao.hexagon.tests.native_fixtures import make_base, mk_active


def _bound(tmp_path):
    base = make_base(str(tmp_path / "RUNS_ACTIVE"))
    active, dflt = mk_active(base)
    active.data_stream = NativeDataStreamer(active)  # type: ignore[reportAttributeAccessIssue]
    active.data_file_writer = NativeDataFileWriter(active)  # type: ignore[reportAttributeAccessIssue]
    active.action_finalizer = NativeActionFinalizer(active)  # type: ignore[reportAttributeAccessIssue]
    return base, active, dflt, NativeDataSinkAdapter().for_action(active)


def test_port_conformance_and_no_base_inheritance():
    from helao.core.servers.base import Base

    sink = NativeDataSinkAdapter()
    assert isinstance(sink, DataSinkPort)
    assert not isinstance(sink, Base)


def test_unbound_raises():
    with pytest.raises(UnwiredPortError):
        NativeDataSinkAdapter().enqueue_data_nowait(DataModel(data={}, errors=[]))


@pytest.mark.asyncio
async def test_enqueue_members_bump_active_counter(tmp_path):
    base, active, dflt, sink = _bound(tmp_path)
    await sink.enqueue_data(DataModel(data={dflt: {"t_s": 1}}, errors=[]))
    sink.enqueue_data_nowait(DataModel(data={dflt: {"t_s": 2}}, errors=[]))
    await sink.enqueue_data_dflt({"t_s": 3})
    assert active.num_data_queued == 3  # counter lives on Active (Q3)


@pytest.mark.asyncio
async def test_write_file_and_realtime_and_header(tmp_path):
    base, active, dflt, sink = _bound(tmp_path)
    assert isinstance(sink.get_realtime_nowait(), int)
    path = await sink.write_file(output_str="r", file_type="t", filename="s.csv")
    assert path is not None
    assert sink.write_file_nowait(output_str="r", file_type="t", filename="s2.csv")
    await sink.finish_hlo_header(realtime=17)
    assert active.file_conn_dict[dflt].params.hloheader.epoch_ns == 17


@pytest.mark.asyncio
async def test_q2_members_delegate_to_legacy_active(tmp_path):
    base, active, dflt, sink = _bound(tmp_path)
    sample = LiquidSample(
        sample_no=1,
        machine_name="test-machine",
        inheritance=SampleInheritance.allow_both,
    )
    await sink.append_sample([sample], IO="in")
    # legacy Active.append_sample ran: sample recorded with defaults filled
    # (MultisubscriberQueue has no qsize; its put with no subscribers is a
    # drop, so the status broadcast is asserted via the sample side effects)
    assert active.action.samples_in
    assert active.action.samples_in[0].action_uuid == [active.action.action_uuid]
    sink.set_estop()
    assert HloStatus.estopped in active.action.action_status
