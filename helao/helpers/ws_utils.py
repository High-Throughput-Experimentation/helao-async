"""WebSocket publisher/subscriber helpers used by HELAO server fan-out.

Messages are pickled and zstd-compressed on the wire. :class:`WsPublisher`
fans an in-process queue out to many WebSocket clients, :class:`WsSubscriber`
asynchronously buffers received messages, and :class:`WsSyncClient` is a
blocking one-shot reader.
"""

__all__ = [
    "WsPublisher",
    "WsSubscriber",
    "WsSyncClient",
    "wire_loads",
    "WireDecodeError",
]

import asyncio
import collections
import enum
import io
import os
import pathlib
import pickle
import sys
import time

import numpy
import pyzstd
import websockets
from fastapi import WebSocket
from pydantic import BaseModel
from websockets.sync.client import connect

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

MAX_DECOMPRESSED_BYTES = 16 * 1024 * 1024
"""Cap on a decompressed frame. Measured: recorded producer frames are <= 1.6 KB
and a 100k-point float64 spectrum is ~0.8 MB, so 16 MiB is >10x the largest real
payload. Opcode amplification (memo refs) costs ~11x the cap in RAM, hence not
larger. Larger frames are rejected."""

MAX_RATIO = 1000
"""Frames over 1 MiB decompressed must compress by less than this ratio (real
pickled floats compress ~2-10x); a higher ratio is a bomb."""

_WIRE_LOG_INTERVAL_S = 30.0
_wire_last_log = 0.0

# Real C types / builtin functions: a BUILD opcode cannot setattr on them.
# set/frozenset/bytearray/range are deliberately absent: protocol 5 producers
# emit opcodes for them, and as callables they amplify a tiny frame into GBs.
_SAFE_GLOBALS = (
    {("builtins", n) for n in ("complex", "slice")}
    | {("datetime", n) for n in ("datetime", "date", "time", "timedelta", "timezone")}
    | {("uuid", "UUID"), ("collections", "OrderedDict"), ("numpy", "dtype")}
    | {(f"numpy.{c}.multiarray", "scalar") for c in ("core", "_core")}
)


# Pure Python classes/functions below are handed out as factories, never as the
# object itself: a BUILD opcode on a returned class would setattr on it and
# poison it process-wide. A factory is reached by REDUCE only.
def _posix(*a):
    return pathlib.PosixPath(*a) if os.name != "nt" else pathlib.PurePosixPath(*a)


def _windows(*a):  # a peer on the other OS: decode as the pure equivalent
    return pathlib.PureWindowsPath(*a)


def _pure_posix(*a):
    return pathlib.PurePosixPath(*a)


def _pure_windows(*a):
    return pathlib.PureWindowsPath(*a)


_NP_CORE = getattr(numpy, "_core", None) or numpy.core  # numpy 2.x / 1.x


class _NdarrayToken:
    """Stands in for ``numpy.ndarray``; only :func:`_np_reconstruct` accepts it."""


def _np_reconstruct(cls, shape, dtype):
    # numpy only ever emits shape (0,) here (data arrives via BUILD), so a hostile
    # shape cannot allocate.
    if cls is not _NdarrayToken or tuple(shape) != (0,):
        raise pickle.UnpicklingError("numpy _reconstruct restricted to shape (0,)")
    return _NP_CORE.multiarray._reconstruct(numpy.ndarray, (0,), dtype)


def _np_frombuffer(*a):
    return _NP_CORE.numeric._frombuffer(*a)  # type: ignore[attr-defined]


_FACTORIES = {
    ("pathlib", "PosixPath"): _posix,
    ("pathlib", "WindowsPath"): _windows,
    ("pathlib", "PurePosixPath"): _pure_posix,
    ("pathlib", "PureWindowsPath"): _pure_windows,
    ("numpy", "ndarray"): _NdarrayToken,
}
for _c in ("core", "_core"):  # numpy 1.x / 2.x module paths
    _FACTORIES[(f"numpy.{_c}.multiarray", "_reconstruct")] = _np_reconstruct
    _FACTORIES[(f"numpy.{_c}.numeric", "_frombuffer")] = _np_frombuffer


def _core_ok(module: str) -> bool:
    """Modules that may be imported on a frame's say-so (no import-time effects)."""
    return module == "helao.core.error" or (
        module.startswith("helao.core.models.")
        and module != "helao.core.models.credentials"
    )


def _enum_value(v):
    """Stand-in for an enum from a module this process has not loaded."""
    if type(v) not in (str, int, float):
        raise pickle.UnpicklingError("enum value must be str/int/float")
    return v


class WireDecodeError(Exception):
    """A frame was rejected (disallowed class, bad data or oversize)."""


class _WireUnpickler(pickle.Unpickler):
    """Unpickler that resolves only the classes real HELAO frames reference.

    Never imports a module because a frame names it, except the core model
    modules. Enum members are guarded against BUILD poisoning.
    """

    def __init__(self, file):
        super().__init__(file)
        self._members: list = []  # (member, __dict__ snapshot)
        self._enum_factories: dict = {}

    def _enum_factory(self, cls):
        if cls not in self._enum_factories:

            def make(v):
                m = cls(v)
                self._members.append((m, dict(m.__dict__)))
                return m

            self._enum_factories[cls] = make
        return self._enum_factories[cls]

    def restore_members(self) -> bool:
        """Undo any BUILD that wrote into an enum member; True if one did.

        Compared by identity (``is``) so an ndarray value cannot raise or
        compare equal to the original.
        """
        bad = False
        for m, snap in self._members:
            cur = m.__dict__
            if cur.keys() != snap.keys() or any(cur[k] is not snap[k] for k in snap):
                cur.clear()
                cur.update(snap)
                bad = True
        return bad

    def find_class(self, module, name):
        key = (module, name)
        if key in _FACTORIES:
            return _FACTORIES[key]
        if key in _SAFE_GLOBALS:
            return super().find_class(module, name)
        # Dotted names are rejected (protocol 4 walks attributes, which would
        # reach e.g. ``os`` through a module global).
        if "." in name or not module.startswith("helao."):
            raise pickle.UnpicklingError(f"wire class not allowed: {module}.{name}")
        if _core_ok(module):
            obj = super().find_class(module, name)
        elif module in sys.modules:  # never import on a peer's say-so
            obj = vars(sys.modules[module]).get(name)  # no module __getattr__
        else:
            return _enum_value  # unloaded module: decode to the raw value
        if isinstance(obj, type) and obj.__module__ == module:
            if issubclass(obj, enum.Enum):
                return self._enum_factory(obj)
            if issubclass(obj, BaseModel) and _core_ok(module):
                return obj
        raise pickle.UnpicklingError(f"wire class not allowed: {module}.{name}")


def wire_loads(recv_bytes: bytes | str):
    """Decode one zstd+pickle frame with the restricted unpickler.

    Raises:
        WireDecodeError: frame oversize, corrupt, or referencing a class
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
        up = _WireUnpickler(io.BytesIO(raw))
        try:
            out = up.load()
        finally:  # runs on a failed load too: a poisoned member is always undone
            poisoned = up.restore_members()
        if poisoned:
            raise WireDecodeError("frame modified an enum member")
        return out
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

    Each message is run through ``xform_func``, pickled, and zstd-compressed
    before being written to a connected WebSocket.

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
                await websocket.send_bytes(
                    pyzstd.compress(pickle.dumps(self.xform_func(source_msg)))
                )
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
