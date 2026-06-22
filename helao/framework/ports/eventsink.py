"""EventSink port: async egress for status/data messages to subscribers."""
from typing import Any, Mapping, Protocol, runtime_checkable

#: Canonical channel names used by the action path.
STATUS_CHANNEL = "status"
DATA_CHANNEL = "data"


@runtime_checkable
class EventSink(Protocol):
    """Sink that broadcasts a payload on a named channel.

    ``emit`` is the generic primitive; ``emit_status``/``emit_data`` are typed
    conveniences that publish on the canonical ``status``/``data`` channels.
    """

    async def emit(self, channel: str, payload: Mapping[str, Any]) -> None:
        """Publish payload to all subscribers of channel."""
        ...

    async def emit_status(self, payload: Mapping[str, Any]) -> None:
        """Publish ``payload`` on the canonical status channel."""
        ...

    async def emit_data(self, payload: Mapping[str, Any]) -> None:
        """Publish ``payload`` on the canonical data channel."""
        ...
