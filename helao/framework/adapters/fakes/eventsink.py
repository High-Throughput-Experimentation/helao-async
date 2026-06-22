"""In-memory EventSink that records every emission for assertions."""
import copy
from typing import Any, Mapping

from helao.framework.ports.eventsink import (
    DATA_CHANNEL,
    STATUS_CHANNEL,
    EventSink,
)


class FakeEventSink(EventSink):
    """Records (channel, payload) tuples; payloads are deep-copied on emit."""

    def __init__(self) -> None:
        self.emitted: list[tuple[str, Mapping[str, Any]]] = []

    async def emit(self, channel: str, payload: Mapping[str, Any]) -> None:
        self.emitted.append((channel, copy.deepcopy(dict(payload))))

    async def emit_status(self, payload: Mapping[str, Any]) -> None:
        await self.emit(STATUS_CHANNEL, payload)

    async def emit_data(self, payload: Mapping[str, Any]) -> None:
        await self.emit(DATA_CHANNEL, payload)

    @property
    def statuses(self) -> list[Mapping[str, Any]]:
        """Payloads emitted on the status channel, in order."""
        return [p for c, p in self.emitted if c == STATUS_CHANNEL]

    @property
    def data(self) -> list[Mapping[str, Any]]:
        """Payloads emitted on the data channel, in order."""
        return [p for c, p in self.emitted if c == DATA_CHANNEL]
