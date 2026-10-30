"""Base class for action-server execution lifecycles.

The :class:`Executor` defines the four-phase contract used by
:class:`Base.contain_action` and its action handlers: ``_pre_exec``
(setup), ``_exec`` (one-shot work), ``_poll`` (repeated work returning
status), and ``_post_exec`` (cleanup), plus a ``_manual_stop`` hook for
abort. Drivers and action implementations subclass this to supply the phases.
"""

import time
from typing import Optional

from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class Executor:
    """Lifecycle host that wraps a driver call against the active action.

    Subclasses supply the actual
    setup/execute/poll/cleanup behaviour; the default implementations are
    no-ops that simply return ``ErrorCodes.none``. The ``oneoff`` flag
    selects single-shot ``_exec`` execution; otherwise ``_poll`` is
    called repeatedly until it reports a terminal :class:`HloStatus`.

    Attributes:
        active: The :class:`Active` (or equivalent) action wrapper this
            executor runs against.
        oneoff: When true, run ``_exec`` once; otherwise loop ``_poll``.
        poll_rate: Seconds between successive ``_poll`` invocations.
        exec_id: Unique identifier for this executor; defaults to
            ``"<action_name> <action_uuid>"``.
        start_time: Wall-clock time (``time.time()``) at construction.
        duration: Requested duration in seconds taken from
            ``action.action_params['duration']``; ``-1`` means indefinite.
        concurrent: Whether this executor tolerates other executors
            running simultaneously on the same server.
    """

    def __init__(
        self,
        active,
        poll_rate: float = 0.2,
        oneoff: bool = True,
        exec_id: Optional[str] = None,
        concurrent: bool = True,
        **kwargs,
    ):
        """Initialize the executor and stamp the action with ``exec_id``.

        Args:
            active: Active action wrapper this executor will drive.
            poll_rate: Seconds between successive ``_poll`` invocations.
            oneoff: When true, only ``_exec`` runs; otherwise ``_poll`` is
                looped until it returns a terminal status.
            exec_id: Optional override for the executor identifier;
                defaults to ``"<action_name> <action_uuid>"``.
            concurrent: Whether multiple executors can coexist on the
                same server.
            **kwargs: Subclass-specific keyword arguments (ignored here).
        """
        self.active = active
        self.oneoff = oneoff
        self.poll_rate = poll_rate
        if exec_id is None:
            self.exec_id = f"{active.action.action_name} {active.action.action_uuid}"
        else:
            self.exec_id = exec_id
        self.active.action.exec_id = self.exec_id
        self.start_time = time.time()
        self.duration = self.active.action.action_params.get("duration", -1)
        # whether or not we can run multiple executors concurrently, regardless of executor type
        self.concurrent = concurrent

    async def _pre_exec(self) -> dict:
        """Setup phase hook invoked once before ``_exec`` / ``_poll``.

        Returns:
            ``{"error": ErrorCodes.none}`` for the no-op default.
        """
        LOGGER.info("generic Executor running setup methods.")
        return {"error": ErrorCodes.none}

    async def _exec(self) -> dict:
        """One-shot execution phase; runs when ``oneoff`` is true.

        Returns:
            ``{"data": {}, "error": ErrorCodes.none}`` for the no-op default.
        """
        return {"data": {}, "error": ErrorCodes.none}

    async def _poll(self) -> dict:
        """Single polling iteration; called repeatedly when ``oneoff`` is false.

        Returns:
            ``{"data": {}, "error": ErrorCodes.none, "status": HloStatus.finished}``
            for the no-op default; the loop terminates on a terminal
            :class:`HloStatus`.
        """
        return {"data": {}, "error": ErrorCodes.none, "status": HloStatus.finished}

    async def _post_exec(self) -> dict:
        """Cleanup phase hook invoked once after ``_exec`` / ``_poll`` finishes.

        Returns:
            ``{"data": {}, "error": ErrorCodes.none}`` for the no-op default.
        """
        return {"data": {}, "error": ErrorCodes.none}

    async def _manual_stop(self) -> dict:
        """Hook invoked when the action is aborted by the orchestrator.

        Returns:
            ``{"error": ErrorCodes.none}`` for the no-op default.
        """
        return {"error": ErrorCodes.none}
