"""Transport port: message-shaped publish/subscribe between servers.

Deliberately message-shaped (not RPC-call-shaped) so a future event-bus
adapter can implement the same interface (spec A->C runway).
"""
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Protocol, runtime_checkable


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


Handler = Callable[[Message], Awaitable[None]]


@runtime_checkable
class Transport(Protocol):
    """Publishes Messages and registers async handlers for incoming Messages."""

    async def publish(self, message: Message) -> DeliveryResult:
        """Send message; return a DeliveryResult (never raise for expected failures)."""
        ...

    def subscribe(self, handler: Handler) -> None:
        """Register handler to be invoked for each incoming message."""
        ...
