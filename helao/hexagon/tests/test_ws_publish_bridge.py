"""P2b-2 WS publish bridge: REAL-encoder/REAL-decoder round-trip (§10.1(3)).

The bridge's puts must serialize through the real legacy wire path — the
WsPublisher ``pyzstd.compress(pickle.dumps(...))`` encode and the
WsSubscriber ``pickle.loads(pyzstd.decompress(...))`` decode
(helao/helpers/ws_utils.py) — never a test-local copy of either (the
dd31c36f trap). A minimal uvicorn app hosts the three WS routes with the
exact handler shape the legacy BaseAPI uses (base_api.py:677-708), and a
real WsSubscriber connects and decodes. Certifies D1: status frames decode
to ActionModel, data frames to DataPackageModel, live frames to the dict.
"""

import asyncio
import contextlib
import socket
from uuid import uuid4

import pydantic
import pytest
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from helao.core.models.action import ActionModel
from helao.core.models.data import DataModel, DataPackageModel
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.ws_utils import WsPublisher, WsSubscriber
from helao.hexagon.adapters.native.ws_publish import WsPublishBridge
from helao.hexagon.adapters.shared.status import DispatcherStatusAdapter

HOST = "127.0.0.1"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def _ws_app(publishers: dict) -> FastAPI:
    """Host each REAL WsPublisher under its route, with the exact handler
    shape the legacy BaseAPI registers (base_api.py:677-708)."""
    app = FastAPI()
    for path, pub in publishers.items():

        def _make_route(pub: WsPublisher):
            async def _route(websocket: WebSocket):
                await pub.connect(websocket)
                try:
                    await pub.broadcast(websocket)
                except WebSocketDisconnect:
                    pub.disconnect(websocket)

            return _route

        app.websocket(path)(_make_route(pub))
    return app


@pytest.mark.asyncio
async def test_bridge_roundtrip_real_publisher_real_subscriber():
    status_q = MultisubscriberQueue()
    data_q = MultisubscriberQueue()
    live_q = MultisubscriberQueue()
    pubs = {
        "/ws_status": WsPublisher(status_q),
        "/ws_data": WsPublisher(data_q),
        "/ws_live": WsPublisher(live_q),
    }
    queues = {"/ws_status": status_q, "/ws_data": data_q, "/ws_live": live_q}
    port = _free_port()
    cfg = uvicorn.Config(_ws_app(pubs), host=HOST, port=port, log_level="warning")
    server = uvicorn.Server(cfg)
    serve_task = asyncio.create_task(server.serve())
    subs: dict = {}
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.1)
        assert server.started

        # real WsSubscriber per channel; its __init__ starts the task
        subs = {p: WsSubscriber(HOST, port, p.strip("/")) for p in pubs}
        # broadcast() registers its subscriber queue on first iteration —
        # wait until every fan-out queue has a live WS subscription before
        # putting, or the frames are lost.
        for _ in range(200):
            if all(len(q.subscribers) >= 1 for q in queues.values()):
                break
            await asyncio.sleep(0.05)
        assert all(len(q.subscribers) >= 1 for q in queues.values())

        bridge = WsPublishBridge(status_q, data_q, live_q)
        act_uuid = uuid4()
        status_payload = ActionModel(
            action_uuid=act_uuid, action_name="acquire_data"
        ).model_dump()
        data_payload = DataPackageModel(
            action_uuid=act_uuid,
            action_name="acquire_data",
            datamodel=DataModel(data={uuid4(): {"epoch_s": [1.0]}}),
        ).model_dump()
        live_payload = {"sim_temp": (25.0, 1234.5)}
        await bridge.publish_status(status_payload)
        await bridge.publish_data(data_payload)
        await bridge.publish_live(live_payload)

        decoded: dict = {}
        for path, sub in subs.items():
            for _ in range(200):
                msgs = await sub.read_messages()
                if msgs:
                    decoded[path] = msgs[0]
                    break
                await asyncio.sleep(0.05)
        assert set(decoded) == set(pubs), f"missing frames: {set(pubs) - set(decoded)}"

        # D1 wire types restored through the REAL pickle+pyzstd path
        assert isinstance(decoded["/ws_status"], ActionModel)
        assert decoded["/ws_status"].action_uuid == act_uuid
        assert isinstance(decoded["/ws_data"], DataPackageModel)
        assert decoded["/ws_data"].action_uuid == act_uuid
        assert decoded["/ws_data"].datamodel.data  # payload survived
        assert decoded["/ws_live"] == live_payload  # dict-native channel
    finally:
        for sub in subs.values():
            sub.subscriber_task.cancel()
        # The WS handlers are blocked inside WsPublisher.broadcast() awaiting
        # the fan-out queue and never observe the client close, so uvicorn's
        # graceful shutdown would wait out its close_timeout. force_exit skips
        # the connection-drain; cancel+suppress guarantees teardown returns.
        server.should_exit = True
        server.force_exit = True
        try:
            await asyncio.wait_for(serve_task, timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            serve_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await serve_task


@pytest.mark.asyncio
async def test_bridge_rejects_malformed_payload_loud():
    """D1 fail-loud: a payload that is not the channel's model in dict form
    raises pydantic.ValidationError and puts NOTHING on the queue."""
    q = MultisubscriberQueue()
    sub = q.queue()  # direct subscriber queue, no WS needed
    bridge = WsPublishBridge(q, q, q)
    with pytest.raises(pydantic.ValidationError):
        # DataPackageModel requires action_uuid/action_name/datamodel
        await bridge.publish_data({"nonsense": True})
    assert sub.empty()


def _bridge_cfg(tmp_path):
    return {
        "root": str(tmp_path),
        "dummy": True,
        "simulation": True,
        "run_type": "simulation",
        "servers": {
            "ORCH": {
                "host": "127.0.0.1",
                "port": 8901,
                "group": "orchestrator",
                "params": {},
            },
            "SIM": {"host": "127.0.0.1", "port": 8902, "group": "action", "params": {}},
        },
    }


@pytest.fixture()
def installed_bridge_cfg(tmp_path, monkeypatch):
    from helao.helpers import config_loader

    cfg = _bridge_cfg(tmp_path)
    (tmp_path / "LOGS").mkdir()
    monkeypatch.setattr(config_loader, "CONFIG", cfg)
    return cfg


def test_an_action_host_binds_the_bridge_to_its_own_queues(installed_bridge_cfg):
    """D-B7c.1: every ActionHost binds the WS publish bridge in __init__, over its own
    fan-out queues, into the status adapter build_wiring gave it."""
    from helao.hexagon.app.action_host import ActionHost

    host = ActionHost("SIM", "SIM", "bridge", 1.0, helao_cfg=installed_bridge_cfg)
    bridge = host.hexagon_ws_bridge
    assert isinstance(bridge, WsPublishBridge)
    assert host.hexagon_wiring is not None
    status = host.hexagon_wiring.status
    assert isinstance(status, DispatcherStatusAdapter)
    assert status._publish_bridge is bridge
    assert bridge._status_q is host.status_q
    assert bridge._data_q is host.data_q
    assert bridge._live_q is host.live_q


def test_an_orch_host_has_no_bridge(installed_bridge_cfg):
    """Q5 / P2b-2 D3: an OrchHost serves its own /ws_* relays and is never bound."""
    from helao.hexagon.app.orch_host import OrchHost

    host = OrchHost(
        "ORCH", "ORCH", "bridge", version=3.0, helao_cfg=installed_bridge_cfg
    )
    assert host.hexagon_ws_bridge is None
    assert host.hexagon_wiring is not None
    status = host.hexagon_wiring.status
    assert isinstance(status, DispatcherStatusAdapter)
    assert status._publish_bridge is None


def test_an_injected_status_without_bind_publish_bridge_yields_no_bridge(
    installed_bridge_cfg,
):
    """The isinstance guard: a status port that is not a DispatcherStatusAdapter (here the
    FakeStatusPush, which has no bind_publish_bridge) gets no bridge, and nothing raises.
    """
    import dataclasses

    from helao.hexagon.adapters.fakes import FakeStatusPush
    from helao.hexagon.app.action_host import ActionHost
    from helao.hexagon.app.factory import build_wiring

    wiring = dataclasses.replace(build_wiring("SIM"), status=FakeStatusPush())
    host = ActionHost(
        "SIM", "SIM", "bridge", 1.0, wiring=wiring, helao_cfg=installed_bridge_cfg
    )
    assert host.hexagon_ws_bridge is None
