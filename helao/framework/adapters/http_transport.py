"""Real Transport adapter: ZMQ-RPC fast-path with HTTP fallback.

Realizes the :class:`~helao.framework.ports.transport.Transport` Protocol by
porting ``helao.helpers.dispatcher`` onto the framework's value-object
contract:

- :meth:`HttpTransport.dispatch` -- tries a ZMQ DEALER RPC call to the peer's
  derived RPC port (~3 s probe timeout) and, on any RPC/timeout/socket error,
  falls back to an ``httpx`` POST with bounded retry/backoff. Every expected
  failure is mapped to an :class:`ErrorCodes` and returned inside a
  :class:`DispatchResult` -- the adapter NEVER raises for an expected failure.
- :meth:`HttpTransport.probe` -- HEAD-probes each target and classifies
  reachability into a :class:`ProbeResult`, mirroring legacy
  ``endpoints_available``.

The RPC client cache (one persistent :class:`RPCClient` per ``(host, port)``)
is reused from the legacy dispatcher's design; :meth:`HttpTransport.aclose`
tears the cache down.

This is an ADAPTER: it MAY import ``httpx`` / ``zmq`` / ``asyncio`` and the
existing :mod:`helao.core.rpc` client. It must NOT be imported by anything in
``domain/`` (enforced by the AST boundary test). ``publish``/``subscribe`` are
documented stubs here -- the WebSocket status mechanism is wired in ``app/``.
"""
from __future__ import annotations

import asyncio
from typing import Any, Mapping

import httpx

from helao.core.rpc import RPCClient, RPCError, derive_rpc_port
from helao.framework.models.errors import ErrorCodes
from helao.framework.ports.transport import (
    DeliveryResult,
    DispatchResult,
    DispatchTarget,
    Handler,
    Message,
    ProbeResult,
    Transport,
)

# zmq is only needed for the exception types we catch off the RPC fast-path.
try:  # pragma: no cover - zmq is always present in the helao env
    import zmq

    _ZMQ_ERROR: tuple[type[BaseException], ...] = (zmq.ZMQError,)
except Exception:  # pragma: no cover
    _ZMQ_ERROR = ()

# Short timeout for the RPC probe (matches legacy dispatcher). If the peer's
# dispatcher is up, replies arrive in <10 ms on localhost; if down, the DEALER
# socket queues silently, so a low timeout is the only fall-back signal.
_RPC_PROBE_TIMEOUT = 3.0

# Exceptions off the RPC fast-path that mean "fall back to HTTP".
_RPC_FALLBACK_ERRORS: tuple[type[BaseException], ...] = (
    RPCError,
    asyncio.TimeoutError,
    OSError,
) + _ZMQ_ERROR


def classify_http_status(status: int) -> ErrorCodes:
    """Map an HTTP status code to an :class:`ErrorCodes` value.

    2xx -> ``none``; everything else -> ``http``. Exposed for unit testing
    the error-mapping contract directly.
    """
    return ErrorCodes.none if status // 100 == 2 else ErrorCodes.http


def classify_probe_status(status: int) -> str | None:
    """Classify a HEAD-probe status into a reason string, or ``None`` if 2xx.

    Mirrors legacy ``endpoints_available``: 2xx is available (``None``); 4xx
    -> ``"client error"``; 5xx -> ``"server error"``; otherwise
    ``"no success"``.
    """
    cent = status // 100
    if cent == 2:
        return None
    if cent == 4:
        return "client error"
    if cent == 5:
        return "server error"
    return "no success"


def classify_transport_error(exc: BaseException) -> ErrorCodes:
    """Map a transport-level exception to an :class:`ErrorCodes` value.

    - timeouts (``asyncio.TimeoutError`` / ``httpx.TimeoutException``)
      -> ``timeout``;
    - connection / network failures (``httpx.TransportError``, ``OSError``,
      ``zmq.ZMQError``) -> ``not_available``;
    - RPC application errors (``RPCError``) -> ``cmd_error``;
    - anything else -> ``unspecified``.
    """
    if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException)):
        return ErrorCodes.timeout
    if isinstance(exc, RPCError):
        return ErrorCodes.cmd_error
    if isinstance(exc, httpx.TransportError):
        return ErrorCodes.not_available
    if _ZMQ_ERROR and isinstance(exc, _ZMQ_ERROR):
        return ErrorCodes.not_available
    if isinstance(exc, OSError):
        return ErrorCodes.not_available
    return ErrorCodes.unspecified


class HttpTransport(Transport):
    """Transport over ZMQ-RPC (fast-path) + httpx HTTP (fallback).

    Args:
        timeout: Per-request timeout in seconds for both the HTTP fallback
            and (capped by the probe timeout) the RPC fast-path.
        retries: Maximum HTTP retry attempts before giving up.
        use_rpc: When ``False``, skip the RPC fast-path entirely and dispatch
            straight over HTTP (useful for tests / RPC-less peers).
        probe_timeout: Per-target HEAD-probe timeout in seconds.
    """

    def __init__(
        self,
        timeout: float = 60.0,
        retries: int = 5,
        use_rpc: bool = True,
        probe_timeout: float = 5.0,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.use_rpc = use_rpc
        self.probe_timeout = probe_timeout
        self._rpc_clients: dict[tuple[str, int], RPCClient] = {}
        self._rpc_lock = asyncio.Lock()
        self._handlers: list[Handler] = []

    # --- RPC client cache (mirrors dispatcher._get_rpc_client) ---

    async def _get_rpc_client(self, host: str, port: int) -> RPCClient:
        key = (host, port)
        client = self._rpc_clients.get(key)
        if client is not None:
            return client
        async with self._rpc_lock:
            client = self._rpc_clients.get(key)
            if client is None:
                client = RPCClient(
                    endpoint=f"tcp://{host}:{derive_rpc_port(port)}",
                    default_timeout=_RPC_PROBE_TIMEOUT,
                )
                self._rpc_clients[key] = client
        return client

    async def aclose(self) -> None:
        """Close and discard every cached RPC client. Idempotent."""
        clients = list(self._rpc_clients.values())
        self._rpc_clients.clear()
        for client in clients:
            try:
                await client.close()
            except Exception:
                pass

    # --- dispatch ---

    async def dispatch(
        self, target: DispatchTarget, payload: Mapping[str, Any]
    ) -> DispatchResult:
        payload = dict(payload)

        # --- ZMQ RPC fast-path ---
        if self.use_rpc:
            rpc_method = f"{target.server_key}/{target.endpoint}"
            try:
                client = await self._get_rpc_client(target.host, target.port)
                result = await client.call(
                    rpc_method,
                    timeout=min(self.timeout, _RPC_PROBE_TIMEOUT),
                    **payload,
                )
                return DispatchResult(response=result, error=ErrorCodes.none)
            except _RPC_FALLBACK_ERRORS:
                # RPC dispatcher unreachable or errored; fall back to HTTP.
                pass

        # --- HTTP fallback (bounded retry with linear backoff) ---
        url = (
            f"http://{target.host}:{target.port}/"
            f"{target.server_key}/{target.endpoint}"
        )
        response: Mapping[str, Any] | None = None
        error_code = ErrorCodes.unspecified
        retry_count = 0
        timeout_cfg = httpx.Timeout(self.timeout)

        while retry_count < self.retries:
            try:
                async with httpx.AsyncClient(timeout=timeout_cfg) as session:
                    resp = await session.post(url, json=payload)
                    try:
                        response = resp.json()
                    except Exception:
                        response = None
                    error_code = classify_http_status(resp.status_code)
                    if error_code is ErrorCodes.none:
                        return DispatchResult(response=response, error=error_code)
                    # non-2xx: classified failure, no further retry
                    return DispatchResult(response=response, error=error_code)
            except Exception as exc:  # transient transport failure -> retry
                error_code = classify_transport_error(exc)
                response = None
                retry_count += 1
                if retry_count >= self.retries:
                    break
                retry_wait = retry_count * self.timeout / 2
                await self._backoff(retry_wait)

        return DispatchResult(response=response, error=error_code)

    async def _backoff(self, seconds: float) -> None:
        """Sleep between HTTP retries. Separated so tests can patch it."""
        await asyncio.sleep(seconds)

    # --- probe ---

    async def probe(self, targets: list[DispatchTarget]) -> ProbeResult:
        unavailable: list[tuple[str, str]] = []
        timeout_cfg = httpx.Timeout(self.probe_timeout)
        async with httpx.AsyncClient(timeout=timeout_cfg) as session:
            for target in targets:
                label = f"{target.server_key}/{target.endpoint}"
                url = (
                    f"http://{target.host}:{target.port}/"
                    f"{target.server_key}/{target.endpoint}"
                )
                try:
                    resp = await session.head(url)
                    reason = classify_probe_status(resp.status_code)
                    if reason is not None:
                        unavailable.append((label, reason))
                except httpx.TimeoutException:
                    unavailable.append((label, "timeout"))
                except httpx.ConnectError:
                    unavailable.append((label, "could not connect"))
                except httpx.TransportError:
                    unavailable.append((label, "could not connect"))
                except Exception:
                    unavailable.append((label, "could not connect"))
        return ProbeResult(available=not unavailable, unavailable=unavailable)

    # --- pub/sub (WS status mechanism, wired in app/) ---

    async def publish(self, message: Message) -> DeliveryResult:
        """Publish over the WS status mechanism.

        Stub: the WebSocket broadcast wiring lives in ``app/`` composition;
        this adapter focuses on the dispatch path. Records nothing and reports
        failure so callers detect the unwired transport explicitly.
        """
        return DeliveryResult(delivered=False, error="publish not wired in adapter")

    def subscribe(self, handler: Handler) -> None:
        """Register a handler. WS subscription is wired in ``app/`` composition."""
        self._handlers.append(handler)
