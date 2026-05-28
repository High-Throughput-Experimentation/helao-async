"""ZeroMQ + msgspec RPC layer that runs alongside FastAPI on each HELAO server.

Each ``BaseAPI`` / ``OrchAPI`` instance binds a ``zmq.ROUTER`` socket on
``http_port + RPC_PORT_OFFSET`` at startup. Every FastAPI POST route on the
app is auto-mirrored into the dispatcher under the route's path (sans leading
slash) so callers can reach the same handler over either HTTP or a ``DEALER``
socket.

The wire format is msgspec.msgpack with fixed ``RPCRequest`` / ``RPCResponse``
envelopes. Dict args are coerced to the handler's declared pydantic model
type via :func:`_coerce_args` so FastAPI-style signatures
(``model: SomeModel = Body(...)``) work unchanged.
"""

from __future__ import annotations

import asyncio
import inspect
import itertools
import pathlib
from typing import Any, Awaitable, Callable, Dict, Optional

import msgspec
import zmq
import zmq.asyncio
from pydantic import BaseModel

try:
    import numpy as _np_mod
    _np: Any = _np_mod
except ImportError:  # numpy is optional in some deployments
    _np = None

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: Added to a server's HTTP port to obtain its RPC port.
RPC_PORT_OFFSET = 10000


def derive_rpc_port(http_port: int) -> int:
    """Return the RPC port paired with ``http_port`` (offset by ``RPC_PORT_OFFSET``)."""
    return http_port + RPC_PORT_OFFSET


# ---------------------------------------------------------------------------
# Wire envelope
# ---------------------------------------------------------------------------


class RPCRequest(msgspec.Struct, omit_defaults=True):
    """Wire envelope for one RPC call: ``id``, ``method`` path, and kwargs dict."""

    id: int
    method: str
    args: Dict[str, Any] = {}


class RPCResponse(msgspec.Struct, omit_defaults=True):
    """Wire envelope for an RPC reply, correlated to a request by ``id``."""

    id: int
    ok: bool
    result: Any = None
    error: str = ""


class RPCError(RuntimeError):
    """Raised on the client side when the server replied with ``ok=False``."""


def _msgpack_enc_hook(obj: Any) -> Any:
    """Unwrap subclasses of native types and NumPy scalars to plain Python.

    msgspec matches types exactly, so subclasses of float/int/str/dict/list
    (notably ruamel.yaml's ``ScalarFloat`` / ``ScalarInt`` / ``CommentedMap``
    etc.) and NumPy scalar/array values trip the encoder. This hook unwraps
    them to the closest native primitive (or a list for arrays).

    Raises:
        NotImplementedError: For any other unsupported type.
    """
    if isinstance(obj, pathlib.PurePath):
        return str(obj)
    if _np is not None:
        # ndarray.tolist() also recursively unwraps nested numpy scalars.
        if isinstance(obj, _np.ndarray):
            return obj.tolist()
        if isinstance(obj, _np.generic):
            return obj.item()
    # ruamel.yaml scalar wrappers (and any other builtin subclass).
    # Order matters: bool before int (bool is an int subclass); numpy
    # checks above already ran, so these only catch pure-Python subclasses.
    if isinstance(obj, bool):
        return bool(obj)
    if isinstance(obj, int):
        return int(obj)
    if isinstance(obj, float):
        return float(obj)
    if isinstance(obj, str):
        return str(obj)
    if isinstance(obj, dict):
        return dict(obj)
    if isinstance(obj, (list, tuple, set, frozenset)):
        return list(obj)
    if isinstance(obj, bytes):
        return bytes(obj)
    raise NotImplementedError(
        f"Objects of type {type(obj).__name__} are not msgpack-serializable"
    )


_REQ_DECODER = msgspec.msgpack.Decoder(RPCRequest)
_REQ_ENCODER = msgspec.msgpack.Encoder(enc_hook=_msgpack_enc_hook)
_RESP_DECODER = msgspec.msgpack.Decoder(RPCResponse)
_RESP_ENCODER = msgspec.msgpack.Encoder(enc_hook=_msgpack_enc_hook)


# ---------------------------------------------------------------------------
# Argument coercion
# ---------------------------------------------------------------------------


def _coerce_args(fn: Callable, args: Dict[str, Any]) -> Dict[str, Any]:
    """Bind a flat caller-supplied args dict to ``fn``'s declared parameters.

    Handles three FastAPI-style patterns:

    1. ``Body(embed=True)`` / query params -- keys line up with parameter
       names and pydantic models are rehydrated from dicts.
    2. ``Body()`` with a single ``dict`` or ``BaseModel`` parameter -- the
       caller's full ``args`` is wrapped as that parameter's value.
    3. ``Body({})`` / ``Body([])`` sentinel defaults on still-unfilled
       parameters are replaced with their wrapped empty container so the
       handler sees ``{}`` / ``[]`` instead of a FastAPI ``Body`` instance.

    Args:
        fn: Target handler.
        args: Flat dict of args supplied by the RPC caller.

    Returns:
        kwargs dict suitable for ``fn(**kwargs)``.
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

    # Pass 3: Replace any Body({}) / Body([]) sentinel defaults for
    # still-unfilled params with the empty container they wrap.
    # Without this, fn(**out) falls through to Python's default-arg
    # mechanism and the handler receives a fastapi.params.Body instance
    # in place of an empty dict/list (which the FastAPI request layer
    # would have supplied for an empty HTTP body).
    for name, param in params.items():
        if name in out:
            continue
        default = param.default
        if type(default).__name__ != "Body":
            continue
        wrapped = getattr(default, "default", None)
        if isinstance(wrapped, dict) and not wrapped:
            out[name] = {}
        elif isinstance(wrapped, list) and not wrapped:
            out[name] = []

    return out


# ---------------------------------------------------------------------------
# Server side: RPCDispatcher
# ---------------------------------------------------------------------------


class RPCDispatcher:
    """Method registry plus a ROUTER-socket receive loop.

    Created eagerly so routes can register during FastAPI startup, then bound
    lazily through :meth:`serve` once an event loop is running.
    """

    def __init__(self, server_key: str) -> None:
        """Create an unbound dispatcher tagged with ``server_key`` for logging."""
        self.server_key = server_key
        self._methods: Dict[str, Callable[..., Awaitable[Any]]] = {}
        self._socket: Optional[zmq.asyncio.Socket] = None
        self._task: Optional[asyncio.Task] = None
        self._endpoint: Optional[str] = None

    def register(self, name: str, fn: Callable[..., Any]) -> None:
        """Add ``fn`` to the dispatch table under ``name`` (last writer wins).

        Args:
            name: Route name (a leading slash is stripped).
            fn: Sync or async callable to invoke for the method.
        """
        # Strip a leading slash if the caller passed the raw route path.
        name = name.lstrip("/")
        self._methods[name] = fn

    @property
    def methods(self) -> Dict[str, Callable[..., Any]]:
        """Read-only view of the registered method table."""
        return self._methods

    async def serve(self, host: str, port: int) -> None:
        """Bind ``tcp://host:port`` and start the receive loop (idempotent)."""
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
        """Cancel the receive loop and close the ROUTER socket."""
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
        """Receive multipart frames and spawn a ``_handle`` task per request."""
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
        """Decode one request, invoke the registered method, and send the reply."""
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
    """Convert a handler return value to msgpack-friendly primitives.

    Pydantic models are dumped via ``model_dump(mode="json")``; objects with
    an ``as_dict`` method are converted through it; anything else passes
    through unchanged for the encoder hook to handle.
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
    """Persistent DEALER-socket RPC client with id-correlated concurrent calls.

    Construction is cheap and synchronous; the background reader task starts
    on the first call so it binds to the caller's running event loop.
    """

    def __init__(self, endpoint: str, default_timeout: float = 5.0) -> None:
        """Configure the endpoint and per-call default timeout.

        Args:
            endpoint: ``tcp://host:port`` of the target RPC dispatcher.
            default_timeout: Seconds to wait for a reply when ``call`` is
                invoked without an explicit timeout.
        """
        self.endpoint = endpoint
        self.default_timeout = default_timeout
        self._socket: Optional[zmq.asyncio.Socket] = None
        self._ids = itertools.count(1)
        self._pending: Dict[int, asyncio.Future] = {}
        self._reader: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    async def _ensure_started(self) -> None:
        """Lazily connect the DEALER socket and spawn the reader task."""
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
        """Decode incoming replies and resolve the matching pending future."""
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
        """Invoke ``method`` on the remote dispatcher and return its result.

        Args:
            method: Remote method name.
            timeout: Override for the per-call wait, in seconds.
            **kwargs: Forwarded to the remote method.

        Returns:
            The server's ``result`` payload.

        Raises:
            RPCError: If the server returned ``ok=False``.
            asyncio.TimeoutError: If no response arrives within ``timeout``.
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
        """Cancel the reader task and close the DEALER socket."""
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
    """Blocking RPC client over a ``zmq.REQ`` socket (one call in flight).

    Used by operator scripts and Bokeh visualizers that have no asyncio loop.
    A REQ socket enters an invalid state after a poll timeout, so the client
    recreates the socket lazily before the next call. The socket is only
    created on the first :meth:`call`.
    """

    def __init__(self, endpoint: str, default_timeout: float = 5.0) -> None:
        """Configure the endpoint and default per-call timeout.

        Args:
            endpoint: ``tcp://host:port`` of the target RPC dispatcher.
            default_timeout: Seconds to wait for a reply when ``call`` is
                invoked without an explicit timeout.
        """
        self.endpoint = endpoint
        self.default_timeout = default_timeout
        self._socket: Optional["zmq.Socket"] = None
        self._ids = itertools.count(1)

    def _ensure_socket(self) -> "zmq.Socket":
        """Return the cached REQ socket, creating and connecting it if needed."""
        if self._socket is not None:
            return self._socket
        ctx = zmq.Context.instance()
        sock = ctx.socket(zmq.REQ)
        sock.setsockopt(zmq.LINGER, 0)
        sock.connect(self.endpoint)
        self._socket = sock
        return sock

    def _reset_socket(self) -> None:
        """Close and discard the cached REQ socket so the next call recreates it."""
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
        """Send a single request and block for the reply.

        Args:
            method: Remote method name.
            timeout: Override for the per-call wait, in seconds.
            **kwargs: Forwarded to the remote method.

        Returns:
            The server's ``result`` payload.

        Raises:
            RPCError: If the server returned ``ok=False``.
            TimeoutError: If no reply arrives within ``timeout``.
        """
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
        """Close the cached REQ socket if any."""
        self._reset_socket()
