"""In-memory Transport for tests: records publishes, drives subscribers manually."""
from helao.framework.ports.transport import (
    DeliveryResult,
    Handler,
    Message,
    Transport,
)


class FakeTransport(Transport):
    """Records published messages; `deliver` invokes subscribed handlers.

    Pass fail_with=<str> to make every publish return a failed DeliveryResult.
    """

    def __init__(self, fail_with: str | None = None) -> None:
        self.published: list[Message] = []
        self._handlers: list[Handler] = []
        self._fail_with = fail_with

    async def publish(self, message: Message) -> DeliveryResult:
        self.published.append(message)
        if self._fail_with is not None:
            return DeliveryResult(delivered=False, error=self._fail_with)
        return DeliveryResult(delivered=True, error=None)

    def subscribe(self, handler: Handler) -> None:
        self._handlers.append(handler)

    async def deliver(self, message: Message) -> None:
        """Test helper: dispatch message to every subscribed handler in order."""
        for handler in self._handlers:
            await handler(message)
