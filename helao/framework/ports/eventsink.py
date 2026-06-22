"""EventSink port: async egress for status/data messages to subscribers."""
from typing import Any, Mapping, Protocol, runtime_checkable


@runtime_checkable
class EventSink(Protocol):
    """Sink that broadcasts a payload on a named channel."""

    async def emit(self, channel: str, payload: Mapping[str, Any]) -> None:
        """Publish payload to all subscribers of channel."""
        ...
