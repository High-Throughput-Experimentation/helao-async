import pytest

from helao.framework.ports.eventsink import EventSink
from helao.framework.adapters.fakes.eventsink import FakeEventSink


def test_fake_satisfies_protocol():
    sink: EventSink = FakeEventSink()
    assert isinstance(sink, EventSink)


@pytest.mark.asyncio
async def test_emit_records_channel_and_payload():
    sink = FakeEventSink()
    await sink.emit("status", {"uuid": "abc", "state": "active"})
    await sink.emit("data", {"x": 1})
    assert sink.emitted == [
        ("status", {"uuid": "abc", "state": "active"}),
        ("data", {"x": 1}),
    ]


@pytest.mark.asyncio
async def test_emit_snapshots_payload():
    sink = FakeEventSink()
    payload = {"n": 1}
    await sink.emit("data", payload)
    payload["n"] = 999
    assert sink.emitted[0][1] == {"n": 1}
