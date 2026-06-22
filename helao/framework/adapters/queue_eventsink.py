"""In-process queue EventSink adapter.

``QueueEventSink`` is a concrete :class:`EventSink` that fans every emission out
to one :class:`asyncio.Queue` per subscriber, and retains a full history of
every ``(channel, payload)`` tuple. It is the framework analogue of the legacy
status/data WebSocket broadcast (``Base.ws_status`` / ``ws_data``), minus the
network: an ``app/`` WebSocket handler subscribes to a queue and forwards items
to its socket.

Lives under ``adapters/``; it depends only on stdlib ``asyncio`` and the port.
"""
from __future__ import annotations

import asyncio
import copy
from typing import Any, List, Mapping, Tuple

from helao.framework.ports.eventsink import (
    DATA_CHANNEL,
    STATUS_CHANNEL,
    EventSink,
)

Item = Tuple[str, Mapping[str, Any]]


class QueueEventSink(EventSink):
    """EventSink that broadcasts to per-subscriber asyncio queues.

    Attributes:
        history: Every ``(channel, payload)`` emitted, in order (deep-copied).
    """

    def __init__(self, maxsize: int = 0) -> None:
        """Initialize the sink.

        Args:
            maxsize: Per-subscriber queue bound (``0`` = unbounded).
        """
        self._maxsize = maxsize
        self._queues: List[asyncio.Queue] = []
        self.history: List[Item] = []

    def subscribe(self) -> asyncio.Queue:
        """Register and return a fresh queue that will receive every emission."""
        q: asyncio.Queue = asyncio.Queue(self._maxsize)
        self._queues.append(q)
        return q

    async def emit(self, channel: str, payload: Mapping[str, Any]) -> None:
        """Record and broadcast ``payload`` on ``channel`` to all subscribers."""
        item: Item = (channel, copy.deepcopy(dict(payload)))
        self.history.append(item)
        for q in self._queues:
            await q.put(item)

    async def emit_status(self, payload: Mapping[str, Any]) -> None:
        """Publish ``payload`` on the canonical status channel."""
        await self.emit(STATUS_CHANNEL, payload)

    async def emit_data(self, payload: Mapping[str, Any]) -> None:
        """Publish ``payload`` on the canonical data channel."""
        await self.emit(DATA_CHANNEL, payload)

    @property
    def statuses(self) -> List[Mapping[str, Any]]:
        """Payloads emitted on the status channel, in order."""
        return [p for c, p in self.history if c == STATUS_CHANNEL]

    @property
    def data(self) -> List[Mapping[str, Any]]:
        """Payloads emitted on the data channel, in order."""
        return [p for c, p in self.history if c == DATA_CHANNEL]
