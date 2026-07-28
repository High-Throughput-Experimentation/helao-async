"""Sync / StatePersistence / Status / Hardware / SampleState adapters."""

import pickle
from pathlib import Path

import pytest

from helao.core.drivers.helao_driver import DriverResponse, HelaoDriver
from helao.hexagon.adapters.errors import UnwiredPortError
from helao.hexagon.adapters.legacy.hardware import LegacyDriverHardwareAdapter
from helao.hexagon.adapters.legacy.sample_state import SampleShimAdapter
from helao.hexagon.adapters.legacy.state_persistence import QueuePckStore
from helao.hexagon.adapters.legacy.status import DispatcherStatusAdapter
from helao.hexagon.adapters.legacy.sync import LegacySyncAdapter
from helao.hexagon.ports.auxiliary import StatePersistencePort
from helao.hexagon.ports.hardware import HardwarePort
from helao.hexagon.ports.sample_state import SampleStatePort
from helao.hexagon.ports.status import StatusPort
from helao.hexagon.ports.sync import SyncPort


# --- Sync -------------------------------------------------------------------
class _StubSyncer:
    def __init__(self):
        self.calls = []

        class _Q:
            @staticmethod
            def qsize():
                return 3

        self.task_queue = _Q()

    async def enqueue_yml(self, upath, rank=0, rank_limit=-5):
        self.calls.append(("enqueue_yml", upath, rank, rank_limit))

    async def sync_yml(
        self,
        yml_path,
        retries=3,
        rank=5,
        force_s3=False,
        force_api=False,
        compress=False,
    ):
        self.calls.append(("sync_yml", yml_path))
        return {"ok": True}

    async def finish_pending(self):
        self.calls.append(("finish_pending",))
        return []

    def reset_sync(self, sync_path):  # SYNC in legacy
        self.calls.append(("reset_sync", sync_path))
        return True

    async def to_s3(self, msg, target, retries=5, compress=False):
        self.calls.append(("to_s3", target))
        return True

    def list_pending(self, omit_manual_exps=True):
        return ["p"]


@pytest.mark.asyncio
async def test_sync_adapter_delegates():
    stub = _StubSyncer()
    a = LegacySyncAdapter(stub)
    assert isinstance(a, SyncPort)
    await a.enqueue_yml("x.yml", rank=1)
    assert (await a.sync_yml(Path("y.yml"))) == {"ok": True}
    assert await a.reset_sync("z") is True
    assert a.list_pending() == ["p"]
    assert a.n_queue() == 3
    assert [c[0] for c in stub.calls] == ["enqueue_yml", "sync_yml", "reset_sync"]


# --- StatePersistence: the queues.pck file contract --------------------------
def test_queue_pck_roundtrip_and_consume_archive(tmp_path):
    (tmp_path / "STATES").mkdir()
    store = QueuePckStore(str(tmp_path))
    assert isinstance(store, StatePersistencePort)
    payload = {"seq": [1], "exp": [], "act": [], "globalstatusmodel": None}
    p = store.export_queues(payload)
    assert p == tmp_path / "STATES" / "queues.pck"
    assert pickle.load(open(p, "rb")) == payload
    out = store.import_queues()
    assert out == payload
    # consumed pck archived, not replayable (core-01 §2 rule)
    assert not p.exists()
    assert list((tmp_path / "STATES").glob("queues_imported_*.pck"))
    assert store.import_queues() is None


def test_queue_pck_timestamped_export(tmp_path):
    (tmp_path / "STATES").mkdir()
    p = QueuePckStore(str(tmp_path)).export_queues({"a": 1}, timestamp_pck=True)
    assert p.name.startswith("queues_") and p.name.endswith(".pck")
    assert p.name != "queues.pck"


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

    import helao.hexagon.adapters.legacy.status as status_mod

    monkeypatch.setattr(status_mod, "async_private_dispatcher", _fake_dispatch)
    a = DispatcherStatusAdapter(server_key="SIM")
    assert await a.attach_client("ORCH", "127.0.0.1", 8001) is True
    await a.send_nonblocking_status(
        "ORCH", "127.0.0.1", 8001, "SIM", "exec1", None, "finished"
    )
    assert sent[0][3] == "update_nonblocking"
    await a.detach_client("ORCH", "127.0.0.1", 8001)
    assert a.clients == []


# --- Hardware: HelaoDriver passthrough + disconnected construct ---------------
class _SimDriver(HelaoDriver):
    def __init__(self, config: dict = {}):
        super().__init__(config=config)
        self.calls = []

    def connect(self) -> DriverResponse:
        self.calls.append("connect")
        return DriverResponse()

    def get_status(self) -> DriverResponse:
        self.calls.append("get_status")
        return DriverResponse()

    def stop(self) -> DriverResponse:
        self.calls.append("stop")
        return DriverResponse()

    def reset(self) -> DriverResponse:
        self.calls.append("reset")
        return DriverResponse()

    def disconnect(self) -> DriverResponse:
        self.calls.append("disconnect")
        return DriverResponse()


@pytest.mark.asyncio
async def test_hardware_passthrough_and_mapping():
    drv = _SimDriver(config={})  # disconnected construct: no I/O in __init__
    a = LegacyDriverHardwareAdapter(drv)
    assert isinstance(a, HardwarePort)
    await a.connect()
    await a.get_status()
    await a.abort()  # -> legacy ABC stop()
    await a.reset()
    await a.disconnect()
    assert drv.calls == ["connect", "get_status", "stop", "reset", "disconnect"]
    with pytest.raises(AttributeError):
        await a.arm()  # _SimDriver has no setup(); fail loud, no silent no-op


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
