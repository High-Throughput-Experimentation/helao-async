"""In-memory Transport for tests: records pub/dispatch/probe, drives subscribers.

Used by domain and app tests. ``publish``/``subscribe`` record and replay
messages; ``dispatch``/``probe`` are scriptable -- preload canned
:class:`DispatchResult` / :class:`ProbeResult` values keyed by endpoint and
assert on the recorded calls.
"""
from collections import deque
from typing import Any, Mapping

from helao.framework.models.errors import ErrorCodes
from helao.framework.ports.transport import (
    DeliveryResult,
    DispatchResult,
    DispatchTarget,
    Handler,
    Message,
    ProbeResult,
    Transport,
)


class FakeTransport(Transport):
    """Records published messages and dispatch/probe calls for assertions.

    Pass ``fail_with=<str>`` to make every ``publish`` return a failed
    :class:`DeliveryResult`.

    Script ``dispatch`` results two ways (checked in this order per call):

    - ``script_by_endpoint[endpoint]`` -- a :class:`DispatchResult` returned
      whenever a target with that ``endpoint`` is dispatched (reusable);
    - ``script_queue`` -- a FIFO of :class:`DispatchResult` consumed one per
      ``dispatch`` call (use :meth:`queue_dispatch`).

    With no script, ``dispatch`` returns ``default_result`` (a success with an
    empty response by default). ``probe`` returns ``probe_result`` (all
    available by default); set it to script a classification.
    """

    def __init__(self, fail_with: str | None = None) -> None:
        self.published: list[Message] = []
        self._handlers: list[Handler] = []
        self._fail_with = fail_with

        # dispatch scripting + recording
        self.script_by_endpoint: dict[str, DispatchResult] = {}
        self._script_queue: deque[DispatchResult] = deque()
        self.default_result: DispatchResult = DispatchResult(
            response={}, error=ErrorCodes.none
        )
        self.dispatched: list[tuple[DispatchTarget, Mapping[str, Any]]] = []

        # probe scripting + recording
        self.probe_result: ProbeResult = ProbeResult(available=True, unavailable=[])
        self.probed: list[list[DispatchTarget]] = []

    # --- pub/sub ---

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

    # --- scriptable dispatch ---

    def queue_dispatch(self, result: DispatchResult) -> None:
        """Append a canned :class:`DispatchResult` to the FIFO dispatch queue."""
        self._script_queue.append(result)

    async def dispatch(
        self, target: DispatchTarget, payload: Mapping[str, Any]
    ) -> DispatchResult:
        self.dispatched.append((target, payload))
        if target.endpoint in self.script_by_endpoint:
            return self.script_by_endpoint[target.endpoint]
        if self._script_queue:
            return self._script_queue.popleft()
        return self.default_result

    async def probe(self, targets: list[DispatchTarget]) -> ProbeResult:
        self.probed.append(list(targets))
        return self.probe_result
