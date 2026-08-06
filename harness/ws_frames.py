"""Canonical wire frames for HELAO's two WS producer families (P7-UI, P7b).

Six WS routes, two producer families, different payload types under the same
route names (measured, see docs/superpowers/plans/2026-08-05-P7-UI-both-stacks.md
§P7b):

- ``base_api`` family: ``BaseAPI`` registers ``/ws_status`` / ``/ws_data`` /
  ``/ws_live`` directly over ``WsPublisher.broadcast``
  (``helao/core/servers/base_api.py:679-708``), which pickles the message
  object as-is (identity ``xform_func``) -- status carries an ``ActionModel``,
  data an ``DataPackageModel``, live a plain dict.
- ``orch_api`` family: ``OrchAPI`` (a *sibling* of ``BaseAPI``, not a subclass)
  registers the same three routes over ``Base.ws_status``/``ws_data``/``ws_live``
  -> ``StatusBroadcaster._ws_relay`` (``helao/core/servers/base_status.py``),
  which calls ``msg.as_dict()`` before pickling for status/data (live stays a
  dict either way).

Frames here are produced by driving the REAL production coroutines --
``WsPublisher.broadcast`` and ``StatusBroadcaster.ws_status``/``ws_data``/
``ws_live`` -- against a :class:`FakeWebSocket` that only fakes the transport
(``accept``/``send_bytes``); the ``pyzstd.compress(pickle.dumps(...))`` (or
``msg.as_dict()`` then the same) encode step is the actual production code
path, not a hand-rolled copy (the dd31c36f trap this repo has hit before,
see ``helao/hexagon/tests/test_ws_publish_bridge.py``). Decoding is likewise
driven through the real :class:`~helao.helpers.ws_utils.WsSubscriber` /
:class:`~helao.helpers.ws_utils.WsSyncClient`, via a tiny replay server
(:func:`replay_server`) that serves pre-computed frame bytes over an actual
WebSocket connection -- the only way to exercise those classes' real
``pickle.loads(pyzstd.decompress(...))`` decode step without copying it.
"""

from __future__ import annotations

__all__ = [
    "CHANNELS",
    "FAMILIES",
    "ACTION_UUID",
    "NUMERIC_COLUMN",
    "NUMERIC_VALUES",
    "STRING_COLUMN",
    "STRING_VALUES",
    "LIVE_FLOAT_LABEL",
    "LIVE_FLOAT_VALUE",
    "LIVE_STRING_LABEL",
    "LIVE_STRING_VALUE",
    "LIVE_EPOCH",
    "build_status_payload",
    "build_data_payload",
    "build_live_payload",
    "FakeWebSocket",
    "encode_base_api",
    "encode_orch_api",
    "frame",
    "replay_server",
    "decode_via_wssubscriber",
    "decode_via_wssyncclient",
    "roundtrip",
]

import asyncio
import contextlib
import socket
import time
from typing import Any, Optional
from uuid import UUID, uuid4

import uvicorn
from fastapi import FastAPI, WebSocket

from helao.core.models.action import ActionModel
from helao.core.models.data import DataModel, DataPackageModel
from helao.core.servers.base_status import StatusBroadcaster
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.ws_utils import WsPublisher, WsSubscriber, WsSyncClient

HOST = "127.0.0.1"

#: The three WS routes both producer families register under.
CHANNELS = ("ws_status", "ws_data", "ws_live")
#: The two independent encoders (siblings, not subclasses -- see module docstring).
FAMILIES = ("base_api", "orch_api")

#: Fixed synthetic content shared by every canonical fixture, so the
#: "identical inputs" byte-comparisons (base_api vs a hand-checked expectation)
#: and the sentinel-value assertions have one source of truth.
ACTION_UUID: UUID = uuid4()
NUMERIC_COLUMN = "current_a"
NUMERIC_VALUES = [0.1, 0.2]
#: Deliberately outside every panel's declared numeric columns -- the
#: non-numeric trap `normalize_data_package` (ingest.py:204-209) is documented
#: to drop and `normalize` (ingest.py:104-109) is documented to divert to rows.
STRING_COLUMN = "composition"
STRING_VALUES = ["Ni0.5Fe0.5", "Ni0.5Fe0.5"]
LIVE_FLOAT_LABEL = "sim_temp"
LIVE_FLOAT_VALUE = 25.0
LIVE_STRING_LABEL = "orch_host"
LIVE_STRING_VALUE = "station1"
LIVE_EPOCH = 1234.5


def build_status_payload(
    action_uuid: UUID = ACTION_UUID, action_name: str = "acquire_data"
) -> ActionModel:
    """The canonical ``/ws_status`` payload: a real ``ActionModel``."""
    return ActionModel(action_uuid=action_uuid, action_name=action_name)


def build_data_payload(
    numeric: Optional[dict] = None,
    strings: Optional[dict] = None,
    action_uuid: UUID = ACTION_UUID,
    action_name: str = "acquire_data",
) -> DataPackageModel:
    """The canonical ``/ws_data`` payload: a real ``DataPackageModel``.

    Carries one numeric column and one string column in the same file
    connection's data, by default -- the trap ``normalize_data_package``
    must survive and ``normalize`` must reject outright (they are keyed by
    ``ws_path``, not by payload shape).
    """
    numeric = {NUMERIC_COLUMN: list(NUMERIC_VALUES)} if numeric is None else numeric
    strings = {STRING_COLUMN: list(STRING_VALUES)} if strings is None else strings
    row: dict = {"epoch_s": [1.0, 2.0]}
    row.update(numeric)
    row.update(strings)
    return DataPackageModel(
        action_uuid=action_uuid,
        action_name=action_name,
        datamodel=DataModel(data={uuid4(): row}),
    )


def build_live_payload(
    numeric: Optional[dict] = None, strings: Optional[dict] = None
) -> dict:
    """The canonical ``/ws_live`` payload: ``{datalab: (value, epoch)}``.

    Carries one float datalab and one string datalab by default, per the
    design in the P7b plan section.
    """
    numeric = {LIVE_FLOAT_LABEL: LIVE_FLOAT_VALUE} if numeric is None else numeric
    strings = {LIVE_STRING_LABEL: LIVE_STRING_VALUE} if strings is None else strings
    out: dict = {}
    for k, v in numeric.items():
        out[k] = (v, LIVE_EPOCH)
    for k, v in strings.items():
        out[k] = (v, LIVE_EPOCH)
    return out


_PAYLOAD_BUILDERS = {
    "ws_status": build_status_payload,
    "ws_data": build_data_payload,
    "ws_live": build_live_payload,
}


class FakeWebSocket:
    """Records ``send_bytes`` calls; ``accept`` is a no-op.

    Not a network socket -- it exists so :class:`WsPublisher.broadcast` and
    :class:`StatusBroadcaster`'s relay methods can run to completion and
    perform their real ``pyzstd.compress(pickle.dumps(...))`` encode step
    against something matching the tiny subset of the FastAPI ``WebSocket``
    surface they actually call, without opening a socket per frame.
    """

    def __init__(self):
        self.frames: list[bytes] = []

    async def accept(self):
        return None

    async def send_bytes(self, data: bytes):
        self.frames.append(data)


class _FakeBase:
    """Stand-in for ``Base``/``Orch`` exposing only the three fan-out queues
    ``StatusBroadcaster`` reads via ``self.base.<queue>`` at call time."""

    def __init__(self):
        self.status_q = MultisubscriberQueue()
        self.data_q = MultisubscriberQueue()
        self.live_q = MultisubscriberQueue()


async def _drain_one(queue: MultisubscriberQueue, relay_coro, payload: Any) -> bytes:
    """Run one real-encoder coroutine against a :class:`FakeWebSocket`.

    Waits for the coroutine to register a subscriber, puts ``payload`` once,
    waits for exactly one frame, then closes the queue so the coroutine's
    ``async for`` ends normally (no exception, no hung task).
    """
    ws = FakeWebSocket()
    task = asyncio.ensure_future(relay_coro(ws))
    for _ in range(200):
        if queue.subscribers:
            break
        await asyncio.sleep(0.01)
    assert queue.subscribers, "producer coroutine never subscribed to the queue"
    await queue.put(payload)
    for _ in range(200):
        if ws.frames:
            break
        await asyncio.sleep(0.01)
    await queue.close()
    await asyncio.wait_for(task, timeout=5)
    assert ws.frames, "producer coroutine never sent a frame"
    return ws.frames[0]


async def encode_base_api(channel: str, payload: Any = None) -> bytes:
    """Encode one frame through the real ``BaseAPI``/``WsPublisher.broadcast`` path.

    Args:
        channel: One of :data:`CHANNELS`.
        payload: Override payload; defaults to the canonical fixture for
            ``channel``.

    Returns:
        The exact bytes ``WsPublisher.broadcast`` would send over the wire.
    """
    if channel not in CHANNELS:
        raise ValueError(f"unknown channel {channel!r}")
    if payload is None:
        payload = _PAYLOAD_BUILDERS[channel]()
    queue = MultisubscriberQueue()
    pub = WsPublisher(queue)
    return await _drain_one(queue, pub.broadcast, payload)


async def encode_orch_api(channel: str, payload: Any = None) -> bytes:
    """Encode one frame through the real ``OrchAPI``/``StatusBroadcaster`` path.

    Args:
        channel: One of :data:`CHANNELS`.
        payload: Override payload; defaults to the canonical fixture for
            ``channel``.

    Returns:
        The exact bytes ``StatusBroadcaster._ws_relay`` would send over the
        wire (``msg.as_dict()`` for status/data, the dict as-is for live).
    """
    if channel not in CHANNELS:
        raise ValueError(f"unknown channel {channel!r}")
    if payload is None:
        payload = _PAYLOAD_BUILDERS[channel]()
    base = _FakeBase()
    broadcaster = StatusBroadcaster(base)
    queue = {
        "ws_status": base.status_q,
        "ws_data": base.data_q,
        "ws_live": base.live_q,
    }[channel]
    # StatusBroadcaster.ws_status/ws_data/ws_live are thin wrappers that call
    # ``self.base._ws_relay(...)`` -- Base's own delegator back to
    # ``self.status_broadcaster._ws_relay`` (base.py:562). _FakeBase doesn't
    # carry that indirection layer (it is pass-through, not encoding logic),
    # so call the real relay implementation directly with the same
    # per-channel label/use_as_dict the wrappers pass it
    # (base_status.py:262-273).
    use_as_dict = channel != "ws_live"
    label = {"ws_status": "status", "ws_data": "data", "ws_live": "live_buffer"}[
        channel
    ]

    async def relay_coro(ws):
        await broadcaster._ws_relay(ws, queue, label, use_as_dict=use_as_dict)

    return await _drain_one(queue, relay_coro, payload)


_ENCODERS = {"base_api": encode_base_api, "orch_api": encode_orch_api}


async def frame(channel: str, family: str, payload: Any = None) -> bytes:
    """Canonical fixture frame bytes for ``(channel, family)``.

    Args:
        channel: One of :data:`CHANNELS`.
        family: One of :data:`FAMILIES`.
        payload: Override payload; defaults to the canonical fixture.

    Returns:
        Wire bytes produced by the real encoder for that family.
    """
    if family not in FAMILIES:
        raise ValueError(f"unknown family {family!r}")
    return await _ENCODERS[family](channel, payload)


@contextlib.asynccontextmanager
async def replay_server(frames_by_path: dict[str, Any]):
    """Serve pre-computed frame bytes over real WebSocket routes.

    Each path in ``frames_by_path`` gets one route that, on connect, sends
    every frame in order (a single ``bytes`` is wrapped as a one-element
    list) and then idles until the server is torn down. This is what lets
    :func:`decode_via_wssubscriber` / :func:`decode_via_wssyncclient` drive
    the *real* decode path (``pickle.loads(pyzstd.decompress(...))`` inside
    ``WsSubscriber``/``WsSyncClient``) without copying that line.

    Args:
        frames_by_path: Map of route name (no leading ``/``) to one frame or
            a list of frames to replay on that route.

    Yields:
        ``(host, port)`` of the running server.
    """
    normalized = {
        path: (frames if isinstance(frames, list) else [frames])
        for path, frames in frames_by_path.items()
    }
    app = FastAPI()

    def _make_route(frames: list[bytes]):
        async def _route(websocket: WebSocket):
            await websocket.accept()
            for fr in frames:
                await websocket.send_bytes(fr)
            # Idle rather than close -- the client decides when it has read
            # enough and disconnects on its own timeline; closing here would
            # race a slow reader.
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                raise

        return _route

    for path, frames in normalized.items():
        app.websocket(f"/{path}")(_make_route(frames))

    with socket.socket() as s:
        s.bind((HOST, 0))
        port = s.getsockname()[1]
    config = uvicorn.Config(app, host=HOST, port=port, log_level="warning")
    server = uvicorn.Server(config)
    serve_task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.1)
        assert server.started
        yield HOST, port
    finally:
        server.should_exit = True
        server.force_exit = True
        try:
            await asyncio.wait_for(serve_task, timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            serve_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await serve_task


async def decode_via_wssubscriber(
    host: str, port: int, path: str, count: int = 1, timeout: float = 5.0
) -> list:
    """Drain ``count`` decoded messages through a real :class:`WsSubscriber`.

    Args:
        host: Replay server host.
        port: Replay server port.
        path: Route name (no leading ``/``).
        count: Number of messages to collect before returning.
        timeout: Overall deadline in seconds.

    Returns:
        Decoded messages in receipt order.
    """
    sub = WsSubscriber(host, port, path)
    try:
        deadline = time.monotonic() + timeout
        out: list = []
        while len(out) < count and time.monotonic() < deadline:
            out.extend(await sub.read_messages())
            if len(out) < count:
                await asyncio.sleep(0.05)
        return out
    finally:
        sub.subscriber_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await sub.subscriber_task


async def decode_via_wssyncclient(host: str, port: int, path: str) -> dict:
    """Decode one message through the real (blocking) :class:`WsSyncClient`.

    Runs the blocking client in a worker thread so it does not stall the
    caller's event loop (the replay server is itself running on that loop).
    """
    client = WsSyncClient(host, port, path)
    return await asyncio.to_thread(client.read_messages)


async def roundtrip(
    channel: str, family: str, payload: Any = None, *, via: str = "wssubscriber"
) -> tuple[bytes, Any]:
    """Encode one frame, then decode it back through a real transport decoder.

    Args:
        channel: One of :data:`CHANNELS`.
        family: One of :data:`FAMILIES`.
        payload: Override payload; defaults to the canonical fixture.
        via: ``"wssubscriber"`` or ``"wssyncclient"``.

    Returns:
        ``(raw_bytes, decoded_message)``.
    """
    raw = await frame(channel, family, payload)
    async with replay_server({channel: raw}) as (host, port):
        if via == "wssubscriber":
            msgs = await decode_via_wssubscriber(host, port, channel, count=1)
            decoded = msgs[0]
        elif via == "wssyncclient":
            decoded = await decode_via_wssyncclient(host, port, channel)
        else:
            raise ValueError(f"unknown transport {via!r}")
    return raw, decoded
