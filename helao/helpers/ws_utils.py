"""WebSocket publisher/subscriber helpers used by HELAO server fan-out.

Messages travel as a zstd-compressed msgspec msgpack ``[tag, payload]`` envelope
(a pydantic model carries its ``module:Class`` tag; see :func:`wire_dumps`). :class:`WsPublisher`
fans an in-process queue out to many WebSocket clients, :class:`WsSubscriber`
asynchronously buffers received messages, and :class:`WsSyncClient` is a
blocking one-shot reader.
"""

__all__ = [
    "WsPublisher",
    "WsSubscriber",
    "WsSyncClient",
    "wire_loads",
    "wire_dumps",
    "WireDecodeError",
]

import asyncio
import collections
import importlib
import pathlib
import time
from typing import Any

import msgspec
import numpy
import pyzstd
import websockets
from fastapi import WebSocket
from pydantic import BaseModel
from websockets.sync.client import connect

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

MAX_DECOMPRESSED_BYTES = 4 * 1024 * 1024
"""Cap on a decompressed frame. Measured: recorded producer frames are <= 1.6 KB
and a 100k-point float64 spectrum is ~0.8 MB, so 4 MiB is ~5x the largest real
payload. Not larger: msgpack decoding of a hostile frame of empty containers
allocates ~70x its size (16 MiB peaked at 1.2 GB), so the cap bounds that
memory to ~300 MB. Larger frames are rejected."""

MAX_RATIO = 1000
"""Frames over 1 MiB decompressed must compress by less than this ratio (real
float payloads compress ~2-10x); a higher ratio is a bomb."""

_FRAME_CACHE_MAX = 8
"""Encoded frames a publisher keeps for clients a few messages behind. Small,
because the cache holds each message and its frame: 8 large spectra is ~32 MB."""
_WIRE_LOG_INTERVAL_S = 30.0
_wire_last_log = 0.0


def _core_ok(module: str) -> bool:
    """Modules that may be imported on a frame's say-so (no import-time effects)."""
    return module == "helao.core.error" or (
        module.startswith("helao.core.models.")
        and module != "helao.core.models.credentials"
    )


class WireDecodeError(Exception):
    """A frame was rejected (disallowed class, bad data or oversize)."""


def _enc_hook(obj):
    """Types msgspec has no native encoding for (UUID, Enum, datetime are native)."""
    if isinstance(obj, numpy.ndarray):
        return obj.tolist()
    if isinstance(obj, numpy.generic):
        return obj.item()
    if isinstance(obj, pathlib.PurePath):
        return str(obj)
    raise NotImplementedError(f"cannot encode {type(obj).__name__} on the wire")


_ENCODER = msgspec.msgpack.Encoder(enc_hook=_enc_hook)


def wire_dumps(obj) -> bytes:
    """Encode one message as a zstd-compressed msgpack ``[tag, payload]`` frame.

    A pydantic model travels as ``("module:Class", model_dump())`` so the
    decoder can rebuild the same type; anything else travels with tag ``None``.
    """
    if isinstance(obj, BaseModel):
        cls = type(obj)
        envelope = [f"{cls.__module__}:{cls.__qualname__}", obj.model_dump()]
    else:
        envelope = [None, obj]
    return pyzstd.compress(_ENCODER.encode(envelope))


def _resolve_model(tag: str):
    """Resolve a ``module:Class`` tag to an allowed pydantic model class."""
    module, sep, name = tag.partition(":")
    if not sep or not name.isidentifier() or not _core_ok(module):
        raise WireDecodeError(f"wire class not allowed: {tag!r}")
    obj = vars(importlib.import_module(module)).get(name)  # no module __getattr__
    if not (
        isinstance(obj, type)
        and issubclass(obj, BaseModel)
        and obj.__module__ == module
    ):
        raise WireDecodeError(f"wire class not allowed: {tag!r}")
    return obj


def wire_loads(recv_bytes: bytes | str) -> Any:
    """Decode one zstd+msgpack frame produced by :func:`wire_dumps`.

    Raises:
        WireDecodeError: frame oversize, corrupt, malformed, or naming a class
            outside the allowlist.
    """
    try:
        if isinstance(recv_bytes, str):
            raise WireDecodeError("text frame")
        dec = pyzstd.ZstdDecompressor()
        raw = dec.decompress(recv_bytes, MAX_DECOMPRESSED_BYTES + 1)
        if len(raw) > MAX_DECOMPRESSED_BYTES or (
            len(raw) > 1024 * 1024 and len(raw) > MAX_RATIO * len(recv_bytes)
        ):
            raise WireDecodeError(
                f"frame too large or over-compressed ({len(raw)} decompressed bytes)"
            )
        env = msgspec.msgpack.decode(raw)
        if not (isinstance(env, list) and len(env) == 2):
            raise WireDecodeError("malformed envelope")
        tag, payload = env
        if tag is None:
            return payload
        if not isinstance(tag, str):
            raise WireDecodeError("malformed envelope tag")
        return _resolve_model(tag).model_validate(payload)
    except WireDecodeError:
        raise
    except Exception as exc:
        raise WireDecodeError(f"{type(exc).__name__}: {exc}") from exc


def _log_rejected(url, exc):
    """Warn about a skipped frame, at most once per interval."""
    global _wire_last_log
    now = time.monotonic()
    if now - _wire_last_log >= _WIRE_LOG_INTERVAL_S:
        _wire_last_log = now
        LOGGER.warning(f"skipping rejected frame from {url}: {exc}")


class WsPublisher:
    """Broadcast messages from a multi-subscriber queue to WebSocket clients.

    Each message is run through ``xform_func``, encoded with :func:`wire_dumps`
    and written to a connected WebSocket. The frame is encoded once per message
    (identity-keyed cache) and shared by every client's broadcast loop.

    Producers must put a new object for each publish: re-putting the same
    object after mutating it would send the frame encoded the first time.

    Attributes:
        active_connections: WebSocket connections that have completed handshake.
        source_queue: Multi-subscriber queue producing source messages.
        xform_func: Callable applied to each message before serialization.
    """

    active_connections: list[WebSocket]

    def __init__(self, source_queue, xform_func=lambda x: x):
        """Capture the source queue and optional message transform."""
        self.active_connections = []
        self.source_queue = source_queue
        self.xform_func = xform_func
        self._frames: collections.OrderedDict = collections.OrderedDict()

    def _frame(self, msg) -> bytes | None:
        """Return the wire frame for ``msg``, encoding it once per message object.

        Holding ``msg`` in the cache keeps its ``id`` from being reused, so an
        identity hit is exact. A client lagging past the bound just re-encodes.
        A message that cannot be encoded yields ``None`` and is skipped: one bad
        value from a driver must not end every client's stream.
        """
        hit = self._frames.get(id(msg))
        if hit is not None and hit[0] is msg:
            return hit[1]
        try:
            frame = wire_dumps(self.xform_func(msg))
        except Exception as exc:
            _log_rejected("this publisher (encode)", exc)
            frame = None
        self._frames[id(msg)] = (msg, frame)
        if len(self._frames) > _FRAME_CACHE_MAX:
            self._frames.popitem(last=False)
        return frame

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket handshake and track the connection."""
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        """Remove ``websocket`` from the active set, if it is still in it.

        Idempotent because ``broadcast`` also clears the connection on its way
        out, and every caller then calls this from its own ``except`` arm: a
        bare ``list.remove`` would raise ValueError out of the disconnect
        handler, which is the same ASGI-traceback noise this whole path is
        meant to stop producing.
        """
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, websocket: WebSocket):
        """Subscribe to the source queue and forward messages to ``websocket``.

        Returns when the client closes the connection, when the source queue is
        closed (``MultisubscriberQueue.close`` sends the sentinel every
        ``subscribe`` iterator breaks on), or when the task is cancelled.

        The cancel case is a shutdown, and it is handled here rather than left
        to propagate: this coroutine is the last frame of a WebSocket endpoint,
        so an escaping ``CancelledError`` is what uvicorn reports as "Exception
        in ASGI application" with a full traceback on every server at CTRL-x.
        Nothing above this frame needs the cancellation to continue.
        """
        try:
            async for source_msg in self.source_queue.subscribe():
                frame = self._frame(source_msg)
                if frame is not None:
                    await websocket.send_bytes(frame)
        except websockets.ConnectionClosedError:
            LOGGER.info("client closed the connection without a close frame")
        except asyncio.CancelledError:
            LOGGER.info("websocket broadcast cancelled, server is shutting down")
        finally:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)


class WsSyncClient:
    """Blocking single-shot WebSocket reader for HELAO publisher streams."""

    def __init__(self, host, port, path):
        """Build the ``ws://`` URL for the target endpoint."""
        self.data_url = f"ws://{host}:{port}/{path}"

    def read_messages(self) -> dict:
        """Connect, receive one message, and return the decoded payload.

        Retries up to five times on connection failure, sleeping two seconds
        between attempts. Returns ``{}`` at once if no message arrives within
        5 s of connecting.

        Returns:
            Decoded message dict, or ``{}`` if all retries fail.
        """
        retry_limit = 5
        for retry_idx in range(retry_limit):
            try:
                with connect(self.data_url) as conn:
                    recv_bytes = conn.recv(timeout=5)
                if recv_bytes:
                    try:
                        return wire_loads(recv_bytes)
                    except WireDecodeError as exc:
                        _log_rejected(self.data_url, exc)
                        return {}
            except TimeoutError:
                # connected but the publisher is silent: no packet, not a retry
                return {}
            except Exception:
                print(f"Could not connect, retrying {retry_idx+1}/{retry_limit}")
                time.sleep(2)
        return {}


class WsSubscriber:
    """Async WebSocket subscriber that buffers decoded messages in a deque.

    A background task connects to the target URL and pushes every decoded
    message into ``recv_queue`` (bounded by ``max_qlen``).
    """

    def __init__(self, host, port, path, max_qlen=500):
        """Start the background subscriber task targeting ``ws://host:port/path``."""
        self.data_url = f"ws://{host}:{port}/{path}"
        self.recv_queue = collections.deque(maxlen=max_qlen)
        self.subscriber_task = asyncio.create_task(self.subscriber_loop())

    async def subscriber_loop(self):
        """Connect to the publisher and feed decoded messages into ``recv_queue``.

        Reconnects indefinitely so the subscriber survives a restart of the
        target server (hot-reload, CTRL-r, crash, transient network drop). Uses
        a capped exponential backoff, reset after each successful connect, and a
        non-blocking ``await asyncio.sleep`` so it never stalls the event loop.
        The task ends only when cancelled (``CancelledError`` derives from
        ``BaseException`` and is intentionally not caught here).
        """
        backoff = 1.0
        max_backoff = 30.0
        while True:
            try:
                async with websockets.connect(self.data_url) as ws:
                    if backoff != 1.0:
                        LOGGER.info(f"WsSubscriber (re)connected to {self.data_url}")
                    backoff = 1.0  # reset after a successful connect
                    while True:
                        recv_bytes = await ws.recv()
                        try:
                            recv_data_dict = wire_loads(recv_bytes)
                        except WireDecodeError as exc:
                            _log_rejected(self.data_url, exc)
                            continue  # skip the frame, keep the connection
                        self.recv_queue.append(recv_data_dict)
            except Exception:
                LOGGER.warning(
                    f"WsSubscriber lost/failed connection to {self.data_url}; "
                    f"reconnecting in {backoff:.0f}s."
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    async def read_messages(self) -> list:
        """Drain and return every buffered message in FIFO order."""
        messages = []
        while self.recv_queue:
            messages.append(self.recv_queue.popleft())
            await asyncio.sleep(1e-4)
        return messages
