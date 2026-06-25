"""Transport port: message-shaped pub/sub plus RPC-shaped dispatch.

Two complementary shapes share one Protocol so a single adapter (or a
future event-bus adapter) can satisfy both:

- **message-shaped** ``publish``/``subscribe`` -- fire-and-forget named
  messages with JSON payloads (spec A->C runway for an event bus);
- **RPC-shaped** ``dispatch``/``probe`` -- request/response calls to a peer
  server's endpoint, plus reachability probing.

Deliberately transport-tech-agnostic: a :class:`DispatchTarget` carries
``host``/``port``/``endpoint`` rather than a URL, so the adapter owns the
choice of ZMQ-RPC, HTTP, or anything else. Expected failures are returned as
values (:class:`DispatchResult` / :class:`ProbeResult`), never raised
(parent spec section 6).

Pure port: only stdlib/typing/dataclasses and ``models.ErrorCodes`` -- no
httpx/zmq/aiohttp here. The real adapter lives in
``adapters/http_transport.py``; the fake in ``adapters/fakes/transport.py``.
"""
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Protocol, runtime_checkable

from helao.framework.models.errors import ErrorCodes


@dataclass(frozen=True)
class Message:
    """A named message with a JSON-serializable payload."""

    name: str
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DeliveryResult:
    """Outcome of a publish attempt. Expected failures are values, not exceptions."""

    delivered: bool
    error: str | None = None


@dataclass(frozen=True)
class DispatchTarget:
    """Addresses one peer endpoint, independent of transport technology.

    The adapter turns this into whatever wire form it uses (e.g. a ZMQ-RPC
    method ``server_key/endpoint`` and/or an HTTP URL
    ``http://host:port/server_key/endpoint``).

    Attributes:
        server_key: Logical server name (the first URL path segment / the
            RPC method prefix and the logging identifier).
        host: Hostname or IP of the peer.
        port: HTTP port of the peer (the adapter derives any RPC port from it).
        endpoint: Endpoint/action path, without a leading slash and without
            the ``server_key`` prefix (e.g. ``"run_action"``).
        private: When ``True``, the endpoint is a framework private/admin
            endpoint registered at ROOT (e.g. ``/get_status``) rather than
            under the server-key prefix (e.g. ``/SIM/get_status``).  The
            adapter uses RPC method ``{endpoint}`` and HTTP URL
            ``http://host:port/{endpoint}`` instead of the prefixed form.
            Default ``False`` preserves existing action-dispatch behaviour.
    """

    server_key: str
    host: str
    port: int
    endpoint: str
    private: bool = False


@dataclass(frozen=True)
class DispatchResult:
    """Outcome of a :meth:`Transport.dispatch` call.

    A value object: the adapter NEVER raises for an expected failure
    (timeout, connection refused, non-2xx, RPC error). It returns
    ``response=None`` with a classifying :class:`ErrorCodes`.

    Attributes:
        response: Decoded JSON response body on success, else ``None``.
        error: :class:`ErrorCodes.none` on success, otherwise the
            classified failure code.
    """

    response: Mapping[str, Any] | None
    error: ErrorCodes


@dataclass(frozen=True)
class ProbeResult:
    """Reachability classification for a batch of :class:`DispatchTarget`s.

    Mirrors the legacy ``endpoints_available`` return shape.

    Attributes:
        available: ``True`` only when every probed target was reachable
            (2xx). When ``False``, ``unavailable`` lists the failures.
        unavailable: ``(server_key/endpoint, reason)`` pairs for each
            unreachable target; empty when ``available`` is ``True``. The
            ``reason`` is a short classification string such as
            ``"could not connect"``, ``"timeout"``, ``"client error"``,
            ``"server error"``, ``"cert failure"`` or ``"no success"``.
    """

    available: bool
    unavailable: list[tuple[str, str]] = field(default_factory=list)


Handler = Callable[[Message], Awaitable[None]]


@runtime_checkable
class Transport(Protocol):
    """Publishes/subscribes Messages and dispatches RPC-shaped calls to peers."""

    async def publish(self, message: Message) -> DeliveryResult:
        """Send message; return a DeliveryResult (never raise for expected failures)."""
        ...

    def subscribe(self, handler: Handler) -> None:
        """Register handler to be invoked for each incoming message."""
        ...

    async def dispatch(
        self, target: DispatchTarget, payload: Mapping[str, Any]
    ) -> DispatchResult:
        """Call ``target``'s endpoint with ``payload``; return a DispatchResult.

        Never raises for expected transport failures -- those are classified
        into the returned :class:`DispatchResult.error`.
        """
        ...

    async def probe(self, targets: list[DispatchTarget]) -> ProbeResult:
        """Probe reachability of every ``target``; return a ProbeResult."""
        ...
