import pytest

from helao.framework.ports.transport import (
    Transport,
    Message,
    DeliveryResult,
)
from helao.framework.adapters.fakes.transport import FakeTransport


def test_message_is_frozen():
    msg = Message(name="dispatch_action", payload={"uuid": "abc"})
    with pytest.raises(Exception):
        msg.name = "other"  # type: ignore[misc]


def test_message_defaults_to_empty_payload():
    assert Message(name="ping").payload == {}


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
