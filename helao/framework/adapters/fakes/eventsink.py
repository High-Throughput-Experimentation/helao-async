"""In-memory EventSink that records every emission for assertions."""
import copy
from typing import Any, Mapping

from helao.framework.ports.eventsink import EventSink


class FakeEventSink(EventSink):
    """Records (channel, payload) tuples; payloads are deep-copied on emit."""

    def __init__(self) -> None:
        self.emitted: list[tuple[str, Mapping[str, Any]]] = []

    async def emit(self, channel: str, payload: Mapping[str, Any]) -> None:
        self.emitted.append((channel, copy.deepcopy(dict(payload))))
