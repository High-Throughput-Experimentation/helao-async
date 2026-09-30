"""The orchestrator's ``wait`` executor and the conditional-endpoint enum.

Moved verbatim from ``helao/core/servers/orch_api.py`` by B7a. ``OrchHost``
runs its ``wait`` action on :class:`WaitExec` and types its conditional
endpoints with :class:`checkcond`; ``orch_api`` re-exports both names for the
legacy ``OrchAPI`` until B7b deletes it.
"""

import asyncio
import time
from enum import Enum

from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.helpers import helao_logging as logging
from helao.helpers.executor import Executor

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class WaitExec(Executor):
    """Executor implementing the orchestrator's ``wait`` action via polled timing."""

    def __init__(self, *args, **kwargs):
        """Initialize the wait executor from the active action's ``waittime`` parameter.

        Args:
            *args: Positional arguments forwarded to :class:`Executor`.
            **kwargs: Keyword arguments forwarded to :class:`Executor`; recognises
                ``print_every_secs`` to control the progress log cadence.
        """
        super().__init__(*args, **kwargs)
        LOGGER.info("WaitExec initialized.")
        self.poll_rate = 0.01
        self.duration = self.active.action.action_params.get("waittime", -1)
        self.print_every_secs = kwargs.get("print_every_secs", 5)
        self.start_time = time.time()
        self.last_print_time = self.start_time

    async def _exec(self):
        """Log the wait duration and return an empty success result."""
        LOGGER.info(f" ... wait action: {self.duration}")
        return {"data": {}, "error": ErrorCodes.none}

    async def _poll(self):
        """Track elapsed time, log progress, and finish once the configured duration elapses."""
        check_time = time.time()
        elapsed_time = check_time - self.start_time
        if check_time - self.last_print_time > self.print_every_secs - 0.01:
            LOGGER.info(
                f" ... orch waited {elapsed_time:.1f} sec / {self.duration:.1f} sec"
            )
            self.last_print_time = check_time
        if (self.duration < 0) or (elapsed_time < self.duration):
            status = HloStatus.active
        else:
            status = HloStatus.finished
        await asyncio.sleep(0.001)
        return {"error": ErrorCodes.none, "status": status}

    async def _post_exec(self):
        """Log completion and return a success result."""
        LOGGER.info(" ... wait action done")
        return {"error": ErrorCodes.none}


class checkcond(str, Enum):
    """Comparison conditions supported by the orchestrator's conditional action endpoints."""

    equals = "equals"
    below = "below"
    above = "above"
    isnot = "isnot"
    uncond = "uncond"
