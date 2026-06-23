"""EventSink port: async egress for status/data messages to subscribers."""
import asyncio
from typing import Any, Mapping, Protocol, runtime_checkable

#: Canonical channel names used by the action path.
STATUS_CHANNEL = "status"
DATA_CHANNEL = "data"
#: Channel for non-blocking action transitions (routed to the orchestrator's
#: ``update_nonblocking`` rather than ``update_status``). Non-blocking actions
#: are excluded from the blocking ``STATUS_CHANNEL`` stream.
NONBLOCKING_STATUS_CHANNEL = "nonblocking_status"
#: Channel the orchestrator broadcasts its ``GlobalStatusModel`` snapshots on.
GLOBAL_STATUS_CHANNEL = "global_status"


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

    def subscribe(self) -> asyncio.Queue:
        """Register and return a fresh queue receiving every ``(channel, payload)``.

        Consumers (the action server's status-drain task, WebSocket relays) read
        ``(channel, payload)`` tuples; multiple concurrent subscribers each get an
        independent queue.
        """
        ...
