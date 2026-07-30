"""PalTriggerPort (P3a-PAL plan §Ports/domain bullet D, slice 5): the
NI-DAQmx start/continue/done DIO handshake. Lifted out of
``helao/deploy/hte/drivers/robot/pal_driver.py``'s ``_poll_trigger_task``/
``_sendcommand_triggerwait``/``_clear_trigger_qs`` and the three trigger
queues.

``wait_for_triggers`` is side-effect-free: it returns the resolved
``(ErrorCodes, start_ns, continue_ns, done_ns)`` tuple (preserving the
three distinct timeout codes -- ``start_timeout``/``continue_timeout``/
``done_timeout``) instead of stamping a ``PalAction`` or mutating
``self.IO_error``/``self.IO_continue`` itself; the engine reads the tuple
and does both (this port never reaches a domain model or ``DataSinkPort``
handle). Likewise the poller never reaches ``DataSinkPort`` directly: it
is handed a ``realtime_nowait`` callable (thread-safe per that port's
contract) at ``start_polling``, captured once for the duration of the
poll -- mirroring the legacy poller's own `job = self._job` capture-once-
at-task-start pattern. A `NullPalTrigger` (construct-time choice when
``dev_trigger != "NImax"``) preserves the exact legacy no-op behavior
(``_poll_trigger_task`` returns immediately when `self.triggers` is
False; `_sendcommand_triggerwait` returns `ErrorCodes.none` immediately
without waiting).
"""

from collections.abc import Callable
from typing import Optional, Protocol, runtime_checkable

from helao.hexagon.domain.models import ErrorCodes

__all__ = ["PalTriggerPort"]


@runtime_checkable
class PalTriggerPort(Protocol):
    def start_polling(
        self, realtime_nowait: Callable[[], int], is_measuring: Callable[[], bool]
    ) -> None:
        """Start (or restart) the trigger DIO poll task, capturing
        ``realtime_nowait`` for the duration of the poll. ``is_measuring``
        is polled once per DIO read (mirrors the legacy poller's own
        ``while self.IO_measuring:`` loop condition) so the poll task can
        exit on its own the moment a stop signal is drained -- even though
        the engine still explicitly cancels it too at the existing 3 call
        sites, there is a window (the mandatory 20s "wait for PAL to
        close" tail) where ``IO_measuring`` has already flipped False but
        the engine hasn't cancelled yet; without this the poller would
        keep the NI-DAQmx task open needlessly for that window. No-op for
        the null adapter."""
        ...

    def stop_polling(self) -> None:
        """Cancel the poll task if one is running (idempotent)."""
        ...

    async def clear_queues(self) -> None:
        """Drain any stale entries from the start/continue/done queues,
        logging each one (mirrors legacy `_clear_trigger_qs`)."""
        ...

    async def wait_for_triggers(
        self,
    ) -> tuple[ErrorCodes, Optional[int], Optional[int], Optional[int]]:
        """Wait for the start, then continue, then done trigger, each
        bounded by the adapter's configured timeout.

        Returns:
            ``(error, start_ns, continue_ns, done_ns)``. ``error`` is
            ``ErrorCodes.none`` on success, or one of ``start_timeout``/
            ``continue_timeout``/``done_timeout`` if a wait expires --
            already-resolved timestamps before the failing wait are still
            returned (``None`` for the ones not yet reached).
        """
        ...
