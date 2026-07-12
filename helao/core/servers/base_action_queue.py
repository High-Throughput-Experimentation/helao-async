"""Queued-action dispatcher collaborator extracted from ``Base`` (CARDS P6, Stage S4).

``Base``'s per-endpoint and unified queued-action dispatch -- the shared
pop-and-redispatch helper plus the two thin wrappers that drive it from the
local unified queue and from a per-endpoint queue -- is moved here into an
``ActionQueueDispatcher`` collaborator that ``Base`` delegates to. This
follows the ``LiveBuffer`` (S1) / ``StatusBroadcaster`` (S2) /
``MetaFileWriter`` (S3) pattern exactly.

Methods relocated (bodies byte-identical to the original inline ``Base``
methods, with ``self.`` rewritten to ``self.base.``):

- ``_dispatch_queued_action`` -- pop one queued action, redispatch it with
  ``no_wait``, and requeue on failure.
- ``process_unified_queue`` -- dispatch the next queued action from the
  server's local unified queue when concurrency is disallowed.
- ``process_endpoint_queue`` -- dispatch the next queued action for the
  endpoint that just transitioned status.

State stays on ``Base`` (rule 3, same as the earlier collaborators):
``local_action_queue`` and ``endpoint_queues`` remain attributes of ``Base``,
constructed exactly where they are today in ``Base.__init__``.
``ActionQueueDispatcher`` caches none of it -- it holds only the ``base``
back-reference and reads those attributes through it at call time.
"""

from helao.helpers import helao_logging as logging
from helao.helpers.dispatcher import async_action_dispatcher
from helao.core.models.action_start_condition import ActionStartCondition as ASC
from helao.core.models.action import ActionModel

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class ActionQueueDispatcher:
    """Queued-action dispatch methods for a ``Base``.

    Holds only the ``base`` back-reference (never cached queue state), per the
    call-time state resolution rule -- see module docstring.
    """

    def __init__(self, base):
        self.base = base

    async def _dispatch_queued_action(self, action_queue, queue_label: str) -> None:
        """Pop one queued action, redispatch it with ``no_wait``, and requeue on failure.

        Args:
            action_queue: Deque of ``(action, extra_params)`` tuples.
            queue_label: Human-readable label used in log messages.
        """
        qact, qpars = None, {}
        try:
            qact, qpars = action_queue.popleft()
            LOGGER.info(f"{qact.action_name} was previously queued")
            LOGGER.info(f"running queued {qact.action_name}")
            qact.start_condition = ASC.no_wait
            qact.action_params["queued_launch"] = True
            await async_action_dispatcher(self.base.world_cfg, qact, qpars)
        except Exception:
            LOGGER.error(f"Failed to process {queue_label} queue", exc_info=True)
            if qact is not None:
                LOGGER.info(f"re-queueing {qact.action_name}")
                action_queue.appendleft((qact, qpars))

    async def process_unified_queue(self) -> None:
        """Dispatch the next queued action when the server disallows concurrency."""
        await self.base._dispatch_queued_action(
            self.base.local_action_queue, "local unified"
        )

    async def process_endpoint_queue(self, status_msg: ActionModel) -> None:
        """Dispatch the next queued action for the endpoint that just transitioned status."""
        await self.base._dispatch_queued_action(
            self.base.endpoint_queues[status_msg.action_name],
            f"endpoint '{status_msg.action_name}'",
        )
