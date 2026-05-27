"""ZeroMQ + msgspec RPC layer that runs alongside FastAPI on each HELAO server.

Each ``BaseAPI`` / ``OrchAPI`` instance binds a ``zmq.ROUTER`` socket on
``http_port + RPC_PORT_OFFSET`` at startup.  Every FastAPI POST route registered
on the app is auto-mirrored into the dispatcher under the route's path
(without leading slash) as its method name.  Callers reach the same handler
via either HTTP (existing behavior) or a ``DEALER`` socket (new fast path).

The wire format is msgspec.msgpack with a fixed envelope (``RPCRequest`` and
``RPCResponse``).  Dict args are coerced to the handler's declared pydantic
model type via :func:`_coerce_args` so existing FastAPI-style signatures
(e.g. ``actionservermodel: ActionServerModel = Body(...)``) work unchanged.
"""

from __future__ import annotations

import asyncio
import inspect
import itertools
from typing import Any, Awaitable, Callable, Dict, Optional

import msgspec
import zmq
import zmq.asyncio
from pydantic import BaseModel

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: Added to a server's HTTP port to obtain its RPC port.
RPC_PORT_OFFSET = 10000


def derive_rpc_port(http_port: int) -> int:
    """Return the RPC port co-located with *http_port*."""
    return http_port + RPC_PORT_OFFSET


# ---------------------------------------------------------------------------
# Wire envelope
# ---------------------------------------------------------------------------


class RPCRequest(msgspec.Struct, omit_defaults=True):
    id: int
    method: str
    args: Dict[str, Any] = {}


class RPCResponse(msgspec.Struct, omit_defaults=True):
    id: int
    ok: bool
    result: Any = None
    error: str = ""


class RPCError(RuntimeError):
    """Raised on the client side when the server returned ``ok=False``."""


_REQ_DECODER = msgspec.msgpack.Decoder(RPCRequest)
_REQ_ENCODER = msgspec.msgpack.Encoder()
_RESP_DECODER = msgspec.msgpack.Decoder(RPCResponse)
_RESP_ENCODER = msgspec.msgpack.Encoder()


# ---------------------------------------------------------------------------
# Argument coercion
# ---------------------------------------------------------------------------


def _coerce_args(fn: Callable, args: Dict[str, Any]) -> Dict[str, Any]:
    """Map a flat args dict onto the handler's parameters.

    FastAPI normally splits HTTP query params from the body and matches each
    to its declared handler param at request time; the RPC dispatcher just
    sees a single ``args`` dict from the caller and must figure out the
    binding itself.  Two patterns appear in HELAO:

    1. ``Body(embed=True)`` (or query params): keys in ``args`` line up with
       parameter names, so a simple name-by-name pickup works.  Pydantic
       model annotations are rehydrated from dicts here.
    2. ``Body()`` with a single ``dict`` or ``BaseModel`` parameter: the
       whole body IS that parameter's value, so the caller's ``args`` dict
       contains the body's keys -- none of which match the param name.  In
       this case we wrap the leftover args as the single unfilled
       dict/model parameter's value.
    """
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return args

    params = sig.parameters
    remaining = dict(args)
    out: Dict[str, Any] = {}

    # Pass 1: name-by-name pickup (covers Body(embed=True) and query params).
    for name, param in params.items():
        if name not in remaining:
            continue
        val = remaining.pop(name)
        ann = param.annotation
        if (
            isinstance(ann, type)
            and issubclass(ann, BaseModel)
            and isinstance(val, dict)
        ):
            val = ann(**val)
        out[name] = val

    # Pass 2: leftover args + an unfilled dict/BaseModel param -> wrap.
    # Handles the "body IS the dict" pattern (e.g. update_global_params).
    if remaining:
        for name, param in params.items():
            if name in out:
                continue
            ann = param.annotation
            is_dict = ann is dict
            is_model = (
                isinstance(ann, type)
                and not is_dict
                and issubclass(ann, BaseModel)
            )
            if is_dict:
                out[name] = remaining
                remaining = {}
                break
            if is_model:
                out[name] = ann(**remaining)
                remaining = {}
                break
        # Anything still left over is dropped (mirrors FastAPI ignoring
        # unknown body keys).

    return out


# ---------------------------------------------------------------------------
# Server side: RPCDispatcher
# ---------------------------------------------------------------------------


class RPCDispatcher:
    """Holds a method registry and serves RPC requests over a ROUTER socket.

    The dispatcher is created eagerly (so routes can be registered during
    FastAPI startup) and bound lazily via :meth:`serve` once the event loop
    is running.
    """

    def __init__(self, server_key: str) -> None:
        self.server_key = server_key
        self._methods: Dict[str, Callable[..., Awaitable[Any]]] = {}
        self._socket: Optional[zmq.asyncio.Socket] = None
        self._task: Optional[asyncio.Task] = None
        self._endpoint: Optional[str] = None

    def register(self, name: str, fn: Callable[..., Any]) -> None:
        """Register *fn* under *name*.  Last writer wins (mirrors FastAPI)."""
        # Strip a leading slash if the caller passed the raw route path.
        name = name.lstrip("/")
        self._methods[name] = fn

    @property
    def methods(self) -> Dict[str, Callable[..., Any]]:
        return self._methods

    async def serve(self, host: str, port: int) -> None:
        """Bind a ROUTER socket and start the receive loop as a background task."""
        if self._task is not None:
            return  # idempotent
        ctx = zmq.asyncio.Context.instance()
        self._socket = ctx.socket(zmq.ROUTER)
        # Allow reusing the address quickly across restarts.
        self._socket.setsockopt(zmq.LINGER, 0)
        endpoint = f"tcp://{host}:{port}"
        self._socket.bind(endpoint)
        self._endpoint = endpoint
        self._task = asyncio.create_task(self._recv_loop(), name=f"rpc-{self.server_key}")
        LOGGER.info(f"RPC dispatcher for {self.server_key!r} listening on {endpoint}")

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        if self._socket is not None:
            self._socket.close(linger=0)
            self._socket = None

    async def _recv_loop(self) -> None:
        assert self._socket is not None
        while True:
            try:
                frames = await self._socket.recv_multipart()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("RPC dispatcher recv error; continuing")
                continue
            # ROUTER+DEALER:  [identity, payload]      (2 frames)
            # ROUTER+REQ:     [identity, b'', payload] (3 frames -- REQ
            #                 auto-prepends an empty delimiter that must
            #                 be echoed back so REQ accepts the reply).
            if len(frames) < 2:
                LOGGER.warning(f"RPC dispatcher dropped malformed frames (n={len(frames)})")
                continue
            identity = frames[0]
            payload = frames[-1]
            envelope = frames[:-1]  # identity + any delimiters
            asyncio.create_task(self._handle(envelope, payload))

    async def _handle(self, envelope: list, payload: bytes) -> None:
        req_id = 0
        try:
            req = _REQ_DECODER.decode(payload)
            req_id = req.id
            fn = self._methods.get(req.method.lstrip("/"))
            if fn is None:
                resp = RPCResponse(
                    id=req_id, ok=False, error=f"unknown method {req.method!r}"
                )
            else:
                coerced = _coerce_args(fn, req.args)
                if asyncio.iscoroutinefunction(fn):
                    result = await fn(**coerced)
                else:
                    result = fn(**coerced)
                resp = RPCResponse(id=req_id, ok=True, result=_to_jsonable(result))
        except Exception as e:  # noqa: BLE001
            LOGGER.exception(f"RPC dispatch error for method (id={req_id})")
            resp = RPCResponse(
                id=req_id, ok=False, error=f"{type(e).__name__}: {e}"
            )
        try:
            assert self._socket is not None
            await self._socket.send_multipart(envelope + [_RESP_ENCODER.encode(resp)])
        except Exception:
            LOGGER.exception("RPC dispatcher failed to send response")


def _to_jsonable(value: Any) -> Any:
    """Best-effort conversion of return values to msgpack-friendly primitives.

    Most HELAO endpoints already return dict / list / primitives, but a few
    return pydantic models or objects with ``as_dict()`` / ``model_dump()``.
    """
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if hasattr(value, "as_dict") and callable(value.as_dict):
        try:
            return value.as_dict()
        except Exception:
            pass
    return value


# ---------------------------------------------------------------------------
# Client side: RPCClient
# ---------------------------------------------------------------------------


class RPCClient:
    """Persistent DEALER-socket client with id-correlated, concurrent requests.

    Construction is cheap and synchronous; the background reader task is
    started on the first call so it binds to the caller's running event loop.
    """

    def __init__(self, endpoint: str, default_timeout: float = 5.0) -> None:
        self.endpoint = endpoint
        self.default_timeout = default_timeout
        self._socket: Optional[zmq.asyncio.Socket] = None
        self._ids = itertools.count(1)
        self._pending: Dict[int, asyncio.Future] = {}
        self._reader: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    async def _ensure_started(self) -> None:
        if self._socket is not None:
            return
        async with self._lock:
            if self._socket is not None:
                return
            ctx = zmq.asyncio.Context.instance()
            self._socket = ctx.socket(zmq.DEALER)
            self._socket.setsockopt(zmq.LINGER, 0)
            self._socket.connect(self.endpoint)
            self._reader = asyncio.create_task(
                self._read_loop(), name=f"rpc-client-{self.endpoint}"
            )

    async def _read_loop(self) -> None:
        assert self._socket is not None
        while True:
            try:
                frames = await self._socket.recv_multipart()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception(f"RPC client recv error on {self.endpoint}")
                continue
            payload = frames[-1]
            try:
                resp = _RESP_DECODER.decode(payload)
            except Exception:
                LOGGER.exception("RPC client failed to decode response")
                continue
            fut = self._pending.pop(resp.id, None)
            if fut is not None and not fut.done():
                fut.set_result(resp)

    async def call(
        self,
        method: str,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> Any:
        """Invoke *method* on the remote dispatcher and return its result.

        Raises ``RPCError`` if the server returned ``ok=False``, or
        ``asyncio.TimeoutError`` if no response within *timeout* seconds.
        """
        await self._ensure_started()
        assert self._socket is not None

        req_id = next(self._ids)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut
        try:
            req = RPCRequest(id=req_id, method=method, args=kwargs)
            await self._socket.send(_REQ_ENCODER.encode(req))
            wait = timeout if timeout is not None else self.default_timeout
            resp: RPCResponse = await asyncio.wait_for(fut, timeout=wait)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise
        except BaseException:
            self._pending.pop(req_id, None)
            raise
        if not resp.ok:
            raise RPCError(resp.error)
        return resp.result

    async def close(self) -> None:
        if self._reader is not None:
            self._reader.cancel()
            try:
                await self._reader
            except (asyncio.CancelledError, Exception):
                pass
            self._reader = None
        if self._socket is not None:
            self._socket.close(linger=0)
            self._socket = None


# ---------------------------------------------------------------------------
# Synchronous client (used by operator scripts and Bokeh visualizers that
# don't have an asyncio loop available).
# ---------------------------------------------------------------------------


class RPCSyncClient:
    """Blocking RPC client built on ``zmq.REQ``.

    REQ is strictly request/reply -- one call in flight at a time -- which
    matches how callers of the legacy ``private_dispatcher`` already behave.
    On a poll timeout the socket enters an invalid state, so we close and
    recreate it for the next call.  Construction is lazy: the socket is only
    created on the first :meth:`call`.
    """

    def __init__(self, endpoint: str, default_timeout: float = 5.0) -> None:
        self.endpoint = endpoint
        self.default_timeout = default_timeout
        self._socket: Optional["zmq.Socket"] = None
        self._ids = itertools.count(1)

    def _ensure_socket(self) -> "zmq.Socket":
        if self._socket is not None:
            return self._socket
        ctx = zmq.Context.instance()
        sock = ctx.socket(zmq.REQ)
        sock.setsockopt(zmq.LINGER, 0)
        sock.connect(self.endpoint)
        self._socket = sock
        return sock

    def _reset_socket(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close(linger=0)
            except Exception:
                pass
            self._socket = None

    def call(
        self,
        method: str,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> Any:
        sock = self._ensure_socket()
        req = RPCRequest(id=next(self._ids), method=method, args=kwargs)
        try:
            sock.send(_REQ_ENCODER.encode(req))
        except zmq.ZMQError:
            self._reset_socket()
            raise
        wait_ms = int((timeout if timeout is not None else self.default_timeout) * 1000)
        if not (sock.poll(wait_ms) & zmq.POLLIN):
            # REQ socket is now in an inconsistent state; recreate next time.
            self._reset_socket()
            raise TimeoutError(f"sync RPC call {method!r} timed out")
        payload = sock.recv()
        resp = _RESP_DECODER.decode(payload)
        if not resp.ok:
            raise RPCError(resp.error)
        return resp.result

    def close(self) -> None:
        self._reset_socket()
