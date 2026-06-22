"""Tests for :class:`helao.framework.adapters.queue_eventsink.QueueEventSink`.

A concrete in-process ``EventSink`` that fans every emission out to an
``asyncio.Queue`` per subscriber (the framework analogue of the legacy status/
data WebSocket broadcast). Realizes the same Protocol the fake does, but is a
real adapter usable from ``app/`` composition.
"""
import asyncio

from helao.framework.ports.eventsink import (
    DATA_CHANNEL,
    STATUS_CHANNEL,
    EventSink,
)
from helao.framework.adapters.queue_eventsink import QueueEventSink


def test_realizes_eventsink_port():
    assert isinstance(QueueEventSink(), EventSink)


def test_emit_status_and_data_reach_a_subscriber():
    async def _run():
        sink = QueueEventSink()
        q = sink.subscribe()
        await sink.emit_status({"k": "s"})
        await sink.emit_data({"k": "d"})
        first = await asyncio.wait_for(q.get(), timeout=1)
        second = await asyncio.wait_for(q.get(), timeout=1)
        return first, second

    (c1, p1), (c2, p2) = asyncio.run(_run())
    assert c1 == STATUS_CHANNEL and p1 == {"k": "s"}
    assert c2 == DATA_CHANNEL and p2 == {"k": "d"}


def test_multiple_subscribers_each_receive():
    async def _run():
        sink = QueueEventSink()
        q1 = sink.subscribe()
        q2 = sink.subscribe()
        await sink.emit(STATUS_CHANNEL, {"n": 1})
        return await q1.get(), await q2.get()

    a, b = asyncio.run(_run())
    assert a == b == (STATUS_CHANNEL, {"n": 1})


def test_history_records_every_emission():
    async def _run():
        sink = QueueEventSink()
        await sink.emit_status({"a": 1})
        await sink.emit_data({"b": 2})
        return sink

    sink = asyncio.run(_run())
    assert sink.statuses == [{"a": 1}]
    assert sink.data == [{"b": 2}]
