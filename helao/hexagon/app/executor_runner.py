"""Native executor loop driver — B1 Task 6, the replacement for ``ExecutorRunner``.

``Executor`` itself is **not** in scope and does not move: it lives in
``helao/helpers/executor.py`` and is only re-exported through ``base.py``. The 44
``Executor`` subclasses across the deployments keep their ``_pre_exec`` /
``_exec`` / ``_poll`` / ``_post_exec`` / ``_manual_stop`` hooks verbatim. What is
reimplemented here is the thing that *drives* them.

Two behaviours in the loop are load-bearing and easy to lose in a rewrite:

* **Non-concurrent executors serialize through a host-level queue.** The loop
  parks on ``base.local_action_task_queue`` until this action's uuid is at the
  head. Drop it and two non-concurrent actions on one server interleave, which
  is a hardware-safety property on a station, not a tidiness one.
* **``base.executors[exec_id]`` holds the SESSION, not the executor.** That is
  what makes ``ActionHost.stop_executor_by_id`` work, since the session is what
  carries ``stop_action_task``. Storing the executor there would break stop.

A failure inside ``_exec`` or ``_poll`` is caught and turned into an empty
result rather than propagating — legacy does this so one bad poll does not abort
an action mid-flight, and the error surfaces through the action's own error code
instead.
"""

import asyncio
import traceback

from helao.core.error import ErrorCodes
from helao.core.models.data import DataModel
from helao.core.models.hlostatus import HloStatus
from helao.helpers import helao_logging as logging
from helao.helpers.executor import Executor

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

__all__ = ["ExecutorRunner"]


class ExecutorRunner:
    """Starts, polls and stops one session's executors."""

    def __init__(self, active):
        """Bind to the session whose action the executors run under."""
        self.active = active

    def executor_done_callback(self, futr):
        """Log an exception raised by the action task, so it is not swallowed."""
        try:
            _ = futr.result()
        except Exception as exc:
            LOGGER.info(
                f"{traceback.format_exception(type(exc), exc, exc.__traceback__)}"
            )

    def start_executor(self, executor: Executor) -> dict:
        """Schedule *executor*'s loop as a task and return the action dict."""
        if not executor.concurrent:
            self.active.base.local_action_task_queue.append(
                executor.active.action.action_uuid
            )
        self.active.action_task = self.active.base.aloop.create_task(
            self.active.action_loop_task(executor)
        )
        self.active.action_task.add_done_callback(self.active.executor_done_callback)
        LOGGER.info("Executor task started.")
        return self.active.action.as_dict()

    async def oneoff_executor(self, executor: Executor):
        """Run *executor* to completion inline rather than as a task."""
        return await self.active.action_loop_task(executor)

    async def action_loop_task(self, executor: Executor):
        """Drive one executor through setup, work, polling and cleanup."""
        while (
            self.active.base.local_action_task_queue
            and self.active.base.local_action_task_queue[0]
            != self.active.action.action_uuid
            and (not executor.concurrent)
        ):
            await asyncio.sleep(0.1)

        if self.active.action.nonblocking:
            await self.active.send_nonblocking_status()

        LOGGER.info("action_loop_task started")
        setup_state = await executor._pre_exec()
        setup_error = setup_state.get("error", ErrorCodes.none)
        if setup_error == ErrorCodes.none:
            self.active.action_loop_running = True
        else:
            LOGGER.info("Error encountered during executor setup.")
            self.active.action.error_code = setup_error
            return await self.active.finish()

        LOGGER.info(f"Registering exec_id: '{executor.exec_id}' with server")
        # The SESSION, not the executor -- stop_executor_by_id calls
        # stop_action_task on whatever is stored here.
        self.active.base.executors[executor.exec_id] = self.active

        LOGGER.info("Running executor._exec() method")
        try:
            result = await executor._exec()
        except Exception:
            LOGGER.error("Executor._exec() failed", exc_info=True)
            result = {}
        error = result.get("error", ErrorCodes.none)
        data = result.get("data", {})
        if data:
            datamodel = DataModel(
                data={self.active.action.file_conn_keys[0]: data},
                errors=[],
                status=HloStatus.active,
            )
            self.active.enqueue_data_nowait(datamodel)

        if not executor.oneoff:
            LOGGER.info("entering executor polling loop")
            while self.active.action_loop_running:
                try:
                    result = await executor._poll()
                except Exception:
                    LOGGER.error("Executor._poll() failed", exc_info=True)
                    result = {}
                error = result.get("error", ErrorCodes.none)
                status = result.get("status", HloStatus.finished)
                data = result.get("data", {})
                if data:
                    datamodel = DataModel(
                        data={self.active.action.file_conn_keys[0]: data},
                        errors=[],
                        status=HloStatus.active,
                    )
                    self.active.enqueue_data_nowait(datamodel)
                if status == HloStatus.active:
                    await asyncio.sleep(executor.poll_rate)
                else:
                    LOGGER.info("exiting executor polling loop")
                    self.active.action_loop_running = False

        if error != ErrorCodes.none:
            self.active.action.error_code = error
        self.active.action_loop_running = False

        if self.active.manual_stop:
            result = await executor._manual_stop()
            error = result.get("error", {})
            if error != ErrorCodes.none:
                LOGGER.info("Error encountered during manual stop.")

        cleanup_state = await executor._post_exec()
        cleanup_error = cleanup_state.get("error", {})
        data = cleanup_state.get("data", {})
        if data:
            datamodel = DataModel(
                data={self.active.action.file_conn_keys[0]: data},
                errors=[],
                status=HloStatus.active,
            )
            self.active.enqueue_data_nowait(datamodel)
        if cleanup_error != ErrorCodes.none:
            LOGGER.info("Error encountered during executor cleanup.")

        _ = self.active.base.executors.pop(executor.exec_id)
        retval = await self.active.finish()
        if self.active.action.nonblocking:
            await self.active.send_nonblocking_status()
        return retval

    def stop_action_task(self) -> None:
        """Request the poll loop stop at its next iteration."""
        LOGGER.info("Stop action request received. Stopping poll.")
        self.active.manual_stop = True
        self.active.action_loop_running = False
