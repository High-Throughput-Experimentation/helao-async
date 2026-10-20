"""StatePersistence / Status / SampleState adapters."""

import os
import pickle

import pytest

from helao.hexagon.adapters.errors import UnwiredPortError
from helao.hexagon.adapters.shared.sample_state import SampleShimAdapter
from helao.hexagon.adapters.shared.state_persistence import QueuePckStore
from helao.hexagon.adapters.shared.status import DispatcherStatusAdapter
from helao.hexagon.ports.auxiliary import StatePersistencePort
from helao.hexagon.ports.sample_state import SampleStatePort
from helao.hexagon.ports.status import StatusPort


# --- StatePersistence: the queues.pck file contract --------------------------
def test_queue_pck_roundtrip_and_consume_archive(tmp_path):
    (tmp_path / "STATES").mkdir()
    store = QueuePckStore(str(tmp_path))
    assert isinstance(store, StatePersistencePort)
    payload = {"seq": [1], "exp": [], "act": [], "globalstatusmodel": None}
    p = store.export_queues(payload)
    assert p == os.path.join(str(tmp_path), "STATES", "queues.pck")
    assert pickle.load(open(p, "rb")) == payload
    path, out = store.load_queues()
    assert (path, out) == (p, payload)
    # loading does not consume; archiving does (core-01 §2 rule)
    assert os.path.exists(p)
    archived = store.archive_consumed(path)
    assert archived is not None and not os.path.exists(p)
    assert list((tmp_path / "STATES").glob("queues_imported_*.pck"))
    assert store.load_queues() == (p, None)


def test_queue_pck_timestamped_export(tmp_path):
    (tmp_path / "STATES").mkdir()
    p = QueuePckStore(str(tmp_path)).export_queues({"a": 1}, timestamp_pck=True)
    name = os.path.basename(p)
    assert name.startswith("queues_") and name.endswith(".pck")
    assert name != "queues.pck"


# --- Status: wire-level push (publish_* fail loud until the bridge binds) -----
@pytest.mark.asyncio
async def test_status_conformance_and_unbound_publish():
    a = DispatcherStatusAdapter(server_key="ORCH")
    assert isinstance(a, StatusPort)
    with pytest.raises(UnwiredPortError):
        await a.publish_status({})
    with pytest.raises(UnwiredPortError):
        await a.publish_data({})
    with pytest.raises(UnwiredPortError):
        await a.publish_live({})


@pytest.mark.asyncio
async def test_status_bound_publish_puts_wire_types():
    """D1 through the adapter: a bound publish_status restores the
    channel's wire type (ActionModel) onto the fan-out queue."""
    from helao.core.models.action import ActionModel
    from helao.helpers.multisubscriber_queue import MultisubscriberQueue
    from helao.hexagon.adapters.native.ws_publish import WsPublishBridge

    status_q = MultisubscriberQueue()
    data_q = MultisubscriberQueue()
    live_q = MultisubscriberQueue()
    sub = status_q.queue()  # direct subscriber queue
    a = DispatcherStatusAdapter(server_key="SIM")
    a.bind_publish_bridge(WsPublishBridge(status_q, data_q, live_q))
    await a.publish_status(ActionModel(action_name="acquire_data").model_dump())
    item = sub.get_nowait()
    assert isinstance(item, ActionModel)
    assert item.action_name == "acquire_data"


@pytest.mark.asyncio
async def test_status_attach_and_send_record_clients(monkeypatch):
    from helao.core.error import ErrorCodes

    sent = []

    async def _fake_dispatch(
        server_key,
        host,
        port,
        private_action,
        params_dict,
        json_dict,
        timeout=60,
        retries=5,
    ):
        sent.append((server_key, host, port, private_action, params_dict, json_dict))
        return {}, ErrorCodes.none

    import helao.hexagon.adapters.shared.status as status_mod

    monkeypatch.setattr(status_mod, "async_private_dispatcher", _fake_dispatch)
    a = DispatcherStatusAdapter(server_key="SIM")
    assert await a.attach_client("ORCH", "127.0.0.1", 8001) is True
    await a.send_nonblocking_status(
        "ORCH", "127.0.0.1", 8001, "SIM", "exec1", None, "finished"
    )
    assert sent[0][3] == "update_nonblocking"
    await a.detach_client("ORCH", "127.0.0.1", 8001)
    assert a.clients == []


# --- SampleState: flattening facade over the shim ------------------------------
class _StubUnifiedDB:
    def __init__(self, log):
        self._log = log

    async def get_samples(self, samples=None):
        self._log.append(("get_samples", samples))
        return ["g"]

    async def new_samples(self, samples=None):
        self._log.append(("new_samples", samples))
        return ["n"]

    async def update_samples(self, samples=None):
        self._log.append(("update_samples", samples))


class _StubShim:
    def __init__(self):
        self.log = []
        self.unified_db = _StubUnifiedDB(self.log)

    async def tray_query_sample(self, tray=None, slot=None, vial=None):
        self.log.append(("tray_query_sample", tray, slot, vial))
        return ("none", None)


@pytest.mark.asyncio
async def test_sample_state_flattens_unified_db():
    shim = _StubShim()
    a = SampleShimAdapter(shim)
    assert isinstance(a, SampleStatePort)
    assert await a.get_samples(["s"]) == ["g"]  # flat -> shim.unified_db
    assert await a.new_samples(["s"]) == ["n"]
    await a.update_samples(["s"])
    await a.tray_query_sample(tray=1)  # 1:1 pass-through
    assert [e[0] for e in shim.log] == [
        "get_samples",
        "new_samples",
        "update_samples",
        "tray_query_sample",
    ]
