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
