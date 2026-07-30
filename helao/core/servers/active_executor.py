"""Executor-orchestration collaborator extracted from ``Active`` (CARDS P6, Stage S7).

``Active``'s executor-orchestration cluster -- the task launcher, the done
callback, the one-off runner, the ``_pre_exec`` -> ``_exec`` -> ``_poll``-loop
-> ``_post_exec`` state machine that produces action data, and the manual-stop
signal -- is moved here into an ``ExecutorRunner`` collaborator that ``Active``
delegates to. ``action_loop_task`` is every driver's action-execution engine,
so this path is gated by the executor scenarios added to the whole-record
golden master (``test_active_golden_master.py``) in Part A of the same stage.

Follows the per-Active collaborator pattern established by S5's
``DataFileWriter`` (see ``active_data_file.py``) and S6's ``DataStreamer`` (see
``active_data_stream.py``): the collaborator holds only the ``active``
back-reference and reads ``self.active.<attr>`` / ``self.active.base.<attr>`` at
call time -- it caches nothing.

Methods relocated (bodies byte-identical to the original inline ``Active``
methods, with ``self.`` rewritten to ``self.active.``):

- ``executor_done_callback`` -- log any exception raised by the executor task.
- ``start_executor`` -- launch the action loop task and return the action dict
  (71 driver reach-ins call this via the ``Active`` delegator).
- ``oneoff_executor`` -- run an executor inline with no polling loop.
- ``action_loop_task`` -- the async executor state machine.
- ``stop_action_task`` -- signal the polling loop to exit / request manual stop.

State stays on ``Active`` (rule 3, same as S5/S6): ``manual_stop``,
``action_loop_running``, and ``action_task`` remain ``Active`` attributes,
constructed exactly where they are today. ``ExecutorRunner`` never caches them
-- it reads/mutates them through ``self.active`` at call time (e.g.
``self.active.action_loop_running = True``).

Task-creation + done-callback wiring is preserved verbatim:
``start_executor`` still sets ``self.active.action_task =
self.active.base.aloop.create_task(self.active.action_loop_task(executor))`` and
registers ``self.active.executor_done_callback`` -- i.e. the task and callback
keep calling the ``Active`` delegators, so bound-method identity and callback
wiring are unchanged.

Cross-collaborator hop: ``action_loop_task`` enqueues produced data via
``self.active.enqueue_data_nowait`` (S6's ``DataStreamer``, through the
``Active`` delegator) -- one extra hop, behaviour-identical, keeping every call
routed through the ``Active`` public surface rather than reaching into a sibling
collaborator directly.
"""

import asyncio
import traceback

from helao.core.error import ErrorCodes
from helao.core.models.data import DataModel
from helao.core.models.hlostatus import HloStatus
from helao.helpers import helao_logging as logging
from helao.helpers.executor import Executor

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class ExecutorRunner:
    """Executor-orchestration methods for an ``Active``.

    Holds only the ``active`` back-reference (never cached
    ``manual_stop``/``action_loop_running``/``action_task`` state), per the
    call-time state resolution rule -- see module docstring.
    """

    def __init__(self, active):
        self.active = active

    def executor_done_callback(self, futr):
        """Log any exception raised by the executor task on completion."""
        try:
            _ = futr.result()
        except Exception as exc:
            LOGGER.info(
                f"{traceback.format_exception(type(exc), exc, exc.__traceback__)}"
            )

    def start_executor(self, executor: Executor) -> dict:
        """Launch the action loop task for ``executor`` and return the action dict.

        Non-concurrent executors register on the unified local queue so the
        loop task stalls until previous actions finish.
        """
        # append action_uuid to local queue before running task if concurrency not allowed
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
        """Run ``executor`` inline (no polling loop) and return its action result."""
        return await self.active.action_loop_task(executor)

    async def action_loop_task(self, executor: Executor):
        """Drive the full executor lifecycle: pre-exec, exec, polling, manual stop, post-exec.

        Stalls until earlier non-concurrent actions finish, then runs
        ``executor._pre_exec``, ``_exec``, optionally ``_poll`` (unless
        ``oneoff``), ``_manual_stop`` (if signalled), and ``_post_exec``.
        Data returned at any stage is broadcast on the data queue.

        Args:
            executor: The executor implementing the action.

        Returns:
            The action returned by :meth:`finish`.
        """
        # stall action_loop task if concurrency is not allowed
        while (
            self.active.base.local_action_task_queue
            and self.active.base.local_action_task_queue[0]
            != self.active.action.action_uuid
            and not executor.concurrent
        ):
            await asyncio.sleep(0.1)

        if self.active.action.nonblocking:
            await self.active.send_nonblocking_status()
        LOGGER.info("action_loop_task started")
        # pre-action operations
        setup_state = await executor._pre_exec()
        setup_error = setup_state.get("error", ErrorCodes.none)
        if setup_error == ErrorCodes.none:
            self.active.action_loop_running = True
        else:
            LOGGER.info("Error encountered during executor setup.")
            self.active.action.error_code = setup_error
            return await self.active.finish()

        # shortcut to active exectuors
        LOGGER.info(f"Registering exec_id: '{executor.exec_id}' with server")
        self.active.base.executors[executor.exec_id] = self.active

        # action operations
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
            self.active.enqueue_data_nowait(datamodel)  # write and broadcast

        # polling loop for ongoing action
        if not executor.oneoff:
            LOGGER.info("entering executor polling loop")
            while self.active.action_loop_running:
                try:
                    result = await executor._poll()
                except Exception:
                    LOGGER.error("Executor._poll() failed", exc_info=True)
                    result = {}
                # LOGGER.info(f"got result: {result}")
                error = result.get("error", ErrorCodes.none)
                status = result.get("status", HloStatus.finished)
                data = result.get("data", {})
                if data:
                    # LOGGER.info(f"got data from poll iter: {data}")
                    datamodel = DataModel(
                        data={self.active.action.file_conn_keys[0]: data},
                        errors=[],
                        status=HloStatus.active,
                    )
                    self.active.enqueue_data_nowait(datamodel)  # write and broadcast

                if status == HloStatus.active:
                    await asyncio.sleep(executor.poll_rate)
                else:
                    LOGGER.info("exiting executor polling loop")
                    self.active.action_loop_running = False

        if error != ErrorCodes.none:
            self.active.action.error_code = error
        self.active.action_loop_running = False

        # in case of manual stop, perform driver operations
        if self.active.manual_stop:
            result = await executor._manual_stop()
            error = result.get("error", {})
            if error != ErrorCodes.none:
                LOGGER.info("Error encountered during manual stop.")

        # post-action operations
        cleanup_state = await executor._post_exec()
        cleanup_error = cleanup_state.get("error", {})
        data = cleanup_state.get("data", {})
        if data:
            datamodel = DataModel(
                data={self.active.action.file_conn_keys[0]: data},
                errors=[],
                status=HloStatus.active,  # must be active for data writer to write
            )
            self.active.enqueue_data_nowait(datamodel)  # write and broadcast
        if cleanup_error != ErrorCodes.none:
            LOGGER.info("Error encountered during executor cleanup.")

        _ = self.active.base.executors.pop(executor.exec_id)
        retval = await self.active.finish()
        if self.active.action.nonblocking:
            await self.active.send_nonblocking_status()
        return retval

    def stop_action_task(self):
        """Signal the polling loop to exit on the next iteration and request a manual stop."""
        LOGGER.info("Stop action request received. Stopping poll.")
        self.active.manual_stop = True
        self.active.action_loop_running = False
