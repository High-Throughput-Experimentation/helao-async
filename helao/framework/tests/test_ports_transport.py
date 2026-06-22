import pytest

from helao.framework.models.errors import ErrorCodes
from helao.framework.ports.transport import (
    Transport,
    Message,
    DeliveryResult,
    DispatchTarget,
    DispatchResult,
    ProbeResult,
)
from helao.framework.adapters.fakes.transport import FakeTransport


def test_message_is_frozen():
    msg = Message(name="dispatch_action", payload={"uuid": "abc"})
    with pytest.raises(Exception):
        msg.name = "other"  # type: ignore[misc]


def test_message_defaults_to_empty_payload():
    assert Message(name="ping").payload == {}


def test_dispatch_target_is_frozen():
    target = DispatchTarget(server_key="orch", host="h", port=8001, endpoint="run")
    with pytest.raises(Exception):
        target.port = 9000  # type: ignore[misc]


def test_dispatch_result_carries_response_and_error():
    ok = DispatchResult(response={"x": 1}, error=ErrorCodes.none)
    assert ok.response == {"x": 1}
    assert ok.error is ErrorCodes.none
    fail = DispatchResult(response=None, error=ErrorCodes.timeout)
    assert fail.response is None
    assert fail.error is ErrorCodes.timeout


def test_probe_result_defaults_to_empty_unavailable():
    assert ProbeResult(available=True).unavailable == []


def test_fake_satisfies_protocol():
    transport: Transport = FakeTransport()
    assert isinstance(transport, Transport)


@pytest.mark.asyncio
async def test_publish_records_message_and_reports_delivered():
    transport = FakeTransport()
    result = await transport.publish(Message(name="dispatch", payload={"x": 1}))
    assert result == DeliveryResult(delivered=True, error=None)
    assert transport.published == [Message(name="dispatch", payload={"x": 1})]


@pytest.mark.asyncio
async def test_publish_can_be_configured_to_fail():
    transport = FakeTransport(fail_with="connection refused")
    result = await transport.publish(Message(name="dispatch"))
    assert result.delivered is False
    assert result.error == "connection refused"


@pytest.mark.asyncio
async def test_subscribed_handlers_receive_delivered_messages():
    transport = FakeTransport()
    seen: list[Message] = []

    async def handler(message: Message) -> None:
        seen.append(message)

    transport.subscribe(handler)
    await transport.deliver(Message(name="status", payload={"state": "active"}))
    assert seen == [Message(name="status", payload={"state": "active"})]


# --- fake dispatch / probe scripting ---


@pytest.mark.asyncio
async def test_dispatch_returns_default_success_and_records_call():
    transport = FakeTransport()
    target = DispatchTarget(server_key="orch", host="h", port=8001, endpoint="run")
    result = await transport.dispatch(target, {"a": 1})
    assert result == DispatchResult(response={}, error=ErrorCodes.none)
    assert transport.dispatched == [(target, {"a": 1})]


@pytest.mark.asyncio
async def test_dispatch_script_by_endpoint_takes_precedence():
    transport = FakeTransport()
    canned = DispatchResult(response={"r": 2}, error=ErrorCodes.none)
    transport.script_by_endpoint["run"] = canned
    target = DispatchTarget(server_key="orch", host="h", port=8001, endpoint="run")
    assert await transport.dispatch(target, {}) is canned
    # different endpoint falls through to default
    other = DispatchTarget(server_key="orch", host="h", port=8001, endpoint="stop")
    assert (await transport.dispatch(other, {})).error is ErrorCodes.none


@pytest.mark.asyncio
async def test_dispatch_queue_consumed_fifo():
    transport = FakeTransport()
    transport.queue_dispatch(DispatchResult(response=None, error=ErrorCodes.timeout))
    transport.queue_dispatch(DispatchResult(response={"ok": 1}, error=ErrorCodes.none))
    target = DispatchTarget(server_key="orch", host="h", port=8001, endpoint="run")
    first = await transport.dispatch(target, {})
    second = await transport.dispatch(target, {})
    assert first.error is ErrorCodes.timeout
    assert second.error is ErrorCodes.none
    assert len(transport.dispatched) == 2


@pytest.mark.asyncio
async def test_probe_returns_scripted_result_and_records_targets():
    transport = FakeTransport()
    transport.probe_result = ProbeResult(
        available=False, unavailable=[("orch/run", "could not connect")]
    )
    targets = [DispatchTarget(server_key="orch", host="h", port=8001, endpoint="run")]
    result = await transport.probe(targets)
    assert result.available is False
    assert result.unavailable == [("orch/run", "could not connect")]
    assert transport.probed == [targets]
