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


@pytest.mark.asyncio
async def test_emit_status_uses_status_channel():
    sink = FakeEventSink()
    await sink.emit_status({"uuid": "abc", "state": "active"})
    assert sink.emitted == [("status", {"uuid": "abc", "state": "active"})]
    assert sink.statuses == [{"uuid": "abc", "state": "active"}]


@pytest.mark.asyncio
async def test_emit_data_uses_data_channel():
    sink = FakeEventSink()
    await sink.emit_data({"x": 1})
    assert sink.emitted == [("data", {"x": 1})]
    assert sink.data == [{"x": 1}]


@pytest.mark.asyncio
async def test_status_and_data_props_filter_by_channel():
    sink = FakeEventSink()
    await sink.emit_status({"s": 1})
    await sink.emit_data({"d": 1})
    await sink.emit_status({"s": 2})
    assert sink.statuses == [{"s": 1}, {"s": 2}]
    assert sink.data == [{"d": 1}]
