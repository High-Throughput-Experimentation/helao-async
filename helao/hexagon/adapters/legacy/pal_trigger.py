"""NidaqmxPalTrigger / NullPalTrigger adapters (P3a-PAL slice 5): reproduce
``pal_driver.py``'s ``_poll_trigger_task``/``_sendcommand_triggerwait``/
``_clear_trigger_qs`` verbatim (same log wording, same three timeout
codes).

``nidaqmx`` is imported LAZILY inside ``_run_poll_loop`` (not at module
top) -- it already was in the legacy driver; preserved here so this
module imports cleanly on Linux without the NI-DAQmx runtime installed.
Construction never opens the DAQ device; only the poll task (once
started) does.

``NullPalTrigger`` is the construct-time choice when the driver's
``dev_trigger`` config key is not ``"NImax"`` -- it reproduces the exact
legacy no-op behavior: the old ``_poll_trigger_task`` returned immediately
when ``self.triggers`` was False, and ``_sendcommand_triggerwait``
returned ``ErrorCodes.none`` immediately without waiting on any queue.
"""

import asyncio
import logging
import traceback
from copy import deepcopy
from typing import Callable, Optional, Tuple

from helao.core.error import ErrorCodes

LOGGER = logging.getLogger(__name__)

__all__ = ["NidaqmxPalTrigger", "NullPalTrigger"]


class NidaqmxPalTrigger:
    def __init__(
        self,
        trigger_start,
        trigger_continue,
        trigger_done,
        timeout: float,
    ):
        self._triggerport_start = trigger_start
        self._triggerport_continue = trigger_continue
        self._triggerport_done = trigger_done
        self._timeout = timeout

        self._startq: asyncio.Queue = asyncio.Queue()
        self._continueq: asyncio.Queue = asyncio.Queue()
        self._doneq: asyncio.Queue = asyncio.Queue()

        self._poll_task: Optional[asyncio.Task] = None
        # non-Optional placeholders (never actually invoked before
        # start_polling replaces them -- the poll loop only runs inside
        # the task start_polling creates): avoids a reportOptionalCall
        # pyright finding for zero behavior cost.
        self._realtime_nowait: Callable[[], int] = lambda: 0
        self._is_measuring: Callable[[], bool] = lambda: False

    def start_polling(
        self, realtime_nowait: Callable[[], int], is_measuring: Callable[[], bool]
    ) -> None:
        self._realtime_nowait = realtime_nowait
        self._is_measuring = is_measuring
        self._poll_task = asyncio.create_task(self._run_poll_loop())

    def stop_polling(self) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
            self._poll_task = None

    async def clear_queues(self) -> None:
        """Drain the start/continue/done trigger queues, logging any stale entries."""
        while not self._startq.empty():
            timecode = await self._startq.get()
            LOGGER.error(f"startq was not empty: '{timecode}'")
        while not self._continueq.empty():
            timecode = await self._continueq.get()
            LOGGER.error(f"continyeq was not empty: '{timecode}'")
        while not self._doneq.empty():
            timecode = await self._doneq.get()
            LOGGER.error(f"doneq was not empty: '{timecode}'")

    async def _run_poll_loop(self) -> None:
        """Poll NI-DAQ trigger lines while measuring and post rising edges to the queues."""
        prev_start = False
        prev_continue = False
        prev_done = False
        try:
            import nidaqmx
            from nidaqmx.constants import LineGrouping

            with nidaqmx.Task() as task:
                LOGGER.info(
                    f"using trigger port '{self._triggerport_start}' for 'start' trigger"
                )
                task.di_channels.add_di_chan(
                    self._triggerport_start, line_grouping=LineGrouping.CHAN_PER_LINE
                )
                LOGGER.info(
                    f"using trigger port '{self._triggerport_continue}' for 'continue' trigger"
                )
                task.di_channels.add_di_chan(
                    self._triggerport_continue,
                    line_grouping=LineGrouping.CHAN_PER_LINE,
                )
                LOGGER.info(
                    f"using trigger port '{self._triggerport_done}' for 'done' trigger"
                )
                task.di_channels.add_di_chan(
                    self._triggerport_done, line_grouping=LineGrouping.CHAN_PER_LINE
                )
                while self._is_measuring():
                    data = task.read(number_of_samples_per_channel=1)
                    new_start = data[0][0]
                    new_continue = data[1][0]
                    new_done = data[2][0]
                    if (new_start ^ prev_start) and new_start:
                        self._startq.put_nowait(self._realtime_nowait())
                        prev_start = deepcopy(new_start)
                        LOGGER.info("IOq: got PAL 'start' trigger poll")
                    if (new_start ^ prev_start) and not new_start:
                        prev_start = deepcopy(new_start)

                    if (new_continue ^ prev_continue) and new_continue:
                        self._continueq.put_nowait(self._realtime_nowait())
                        prev_continue = deepcopy(new_continue)
                        LOGGER.info("IOq: got PAL 'continue' trigger poll")

                    if (new_continue ^ prev_continue) and not new_continue:
                        prev_continue = deepcopy(new_continue)

                    if (new_done ^ prev_done) and new_done:
                        self._doneq.put_nowait(self._realtime_nowait())
                        prev_done = deepcopy(new_done)
                        LOGGER.info("IOq: got PAL 'done' trigger poll")

                    if (new_done ^ prev_done) and not new_done:
                        prev_done = deepcopy(new_done)

                    await asyncio.sleep(0.01)

        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            LOGGER.error(f"_poll_trigger_task excited with error: {repr(e), tb,}")

    async def wait_for_triggers(
        self,
    ) -> Tuple[ErrorCodes, Optional[int], Optional[int], Optional[int]]:
        LOGGER.info("waiting for PAL start trigger")
        try:
            start = await asyncio.wait_for(self._startq.get(), self._timeout)
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            LOGGER.error(f"PAL start trigger timeout with error: {repr(e), tb,}")
            return ErrorCodes.start_timeout, None, None, None

        LOGGER.info("got PAL start trigger, waiting for PAL continue trigger")
        try:
            cont = await asyncio.wait_for(self._continueq.get(), self._timeout)
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            LOGGER.error(f"PAL continue trigger timeout with error: {repr(e), tb,}")
            return ErrorCodes.continue_timeout, start, None, None

        LOGGER.info("got PAL continue trigger, waiting for PAL done trigger")
        try:
            done = await asyncio.wait_for(self._doneq.get(), self._timeout)
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            LOGGER.error(f"PAL done trigger timeout with error: {repr(e), tb,}")
            return ErrorCodes.done_timeout, start, cont, None

        LOGGER.info("got PAL done trigger")
        return ErrorCodes.none, start, cont, done


class NullPalTrigger:
    """No-op adapter for ``dev_trigger != "NImax"`` -- reproduces the legacy
    no-triggers-configured behavior exactly: the poller never runs, and
    ``wait_for_triggers`` returns immediately with ``ErrorCodes.none`` and
    no timestamps (the legacy `_sendcommand_triggerwait` returned early
    with `error = ErrorCodes.none` and never populated `palaction.start_
    time`/`continue_time`/`done_time` in this case)."""

    def start_polling(
        self, realtime_nowait: Callable[[], int], is_measuring: Callable[[], bool]
    ) -> None:
        return None

    def stop_polling(self) -> None:
        return None

    async def clear_queues(self) -> None:
        return None

    async def wait_for_triggers(
        self,
    ) -> Tuple[ErrorCodes, Optional[int], Optional[int], Optional[int]]:
        LOGGER.error("No triggers configured")
        return ErrorCodes.none, None, None, None
