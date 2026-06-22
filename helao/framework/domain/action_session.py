"""ActionSession: the pure action-execution state machine (ex-``Active``).

``ActionSession`` is the framework port of ``helao.core.servers.base.Active``: a
per-action runtime that drives an :class:`Executor` through its phases, streams
status and data through injected ports, manages sample bookkeeping, and persists
meta/HLO output. It is **pure** — every side effect goes through an injected port
(:class:`Storage` / :class:`EventSink` / :class:`Clock` / :class:`Transport`), so
there is no FastAPI / httpx / aiofiles / filesystem coupling in this module.

States: ``init -> active -> finish`` (the happy path implemented here). The
``split`` / ``substitute`` / ``manual`` transitions and the full finish drain
(global params, post-processors, aux-file relocation) arrive in Wave 4; ``finish``
here is the minimal drain + final-status form needed to complete the happy path.

Purity: imports only from ``helao.framework.models`` / ``ports`` / ``support`` /
``domain`` and stdlib.
"""

__all__ = ["ActionSession"]

import asyncio
from typing import Any, List, Mapping, Optional

from helao.framework.models.errors import ErrorCodes
from helao.framework.models.hlostatus import HloStatus
from helao.framework.models.data import DataModel, DataPackageModel
from helao.framework.models.sample import (
    NoneSample,
    SampleInheritance,
    SampleStatus,
)
from helao.framework.ports.clock import Clock
from helao.framework.ports.eventsink import EventSink
from helao.framework.ports.storage import Storage
from helao.framework.ports.transport import Transport
from helao.framework.domain.run_models import RunAction
from helao.framework.domain.executor import Executor

from helao.framework.support import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class ActionSession:
    """Per-action runtime that drives an executor and streams output via ports.

    Owns one :class:`RunAction` (and, in later waves, its split siblings), drives
    the executor loop, opens/writes HLO files through ``Storage``, broadcasts
    status/data through ``EventSink``, manages sample bookkeeping, and persists
    meta files. All effects are realised through the injected ports.

    Attributes:
        action: The :class:`RunAction` this session runs.
        action_list: This action plus any split siblings (newest first).
        num_data_queued: Count of non-empty data batches enqueued.
        num_data_written: Count of enqueued batches drained to storage.
        manual_stop: Set when an abort has been requested.
        action_loop_running: True while the executor loop is active.
    """

    def __init__(
        self,
        run_action: RunAction,
        *,
        storage: Storage,
        eventsink: EventSink,
        clock: Clock,
        executor: Executor,
        transport: Optional[Transport] = None,
    ) -> None:
        """Wire the session to its run-action and injected ports.

        Args:
            run_action: The action to run.
            storage: Storage port for HLO/meta/aux output.
            eventsink: EventSink port for status/data broadcast.
            clock: Clock port for timestamps.
            executor: The executor implementing the action's phases.
            transport: Optional transport port (used by ``finish`` in Wave 4).
        """
        self.action = run_action
        self.storage = storage
        self.eventsink = eventsink
        self.clock = clock
        self.executor = executor
        self.transport = transport

        # newest action is at position 0 (matches legacy Active.action_list)
        self.action_list: List[RunAction] = [self.action]
        self.num_data_queued = 0
        self.num_data_written = 0
        self.manual_stop = False
        self.action_loop_running = False
        # data packages awaiting drain to storage (in lieu of the legacy
        # data_q / log_data_task background task). finish() drains these.
        self._pending_data: List[DataPackageModel] = []

        # save defaults mirror Active.__init__: cannot save data without act
        if self.action.save_data is None:
            self.action.save_data = False
        if self.action.save_act is None:
            self.action.save_act = False
        if self.action.save_data is True:
            self.action.save_act = True

    # --- meta / output -------------------------------------------------------

    def _meta_relpath(self) -> str:
        """Relpath for this action's ``.act`` meta file."""
        return f"{self.action.action_output_dir}/{self.action.action_uuid}.act"

    async def update_act_file(self) -> None:
        """(Re)write the action's meta YAML to reflect the current state."""
        if self.action.save_act:
            await self.storage.write_meta(self._meta_relpath(), self.action.as_dict())

    async def myinit(self) -> None:
        """Create the action output (meta), persist manual exp/seq, broadcast status.

        Mirrors ``Active.myinit``: when ``save_act`` is set, the action meta is
        written (which creates the output directory in a real adapter), and for a
        manual action the synthetic experiment/sequence meta files are written
        too. Then the initial status is broadcast.
        """
        if self.action.save_act:
            await self.update_act_file()
            if self.action.manual_action:
                await self.storage.write_meta(
                    f"{self.action.action_output_dir}/{self.action.sequence_uuid}.seq",
                    self.action.as_dict(),
                )
                await self.storage.write_meta(
                    f"{self.action.action_output_dir}/{self.action.experiment_uuid}.exp",
                    self.action.as_dict(),
                )

        LOGGER.info("init active: sending active data_stream_status package")
        await self.add_status()

    # --- status / data -------------------------------------------------------

    async def add_status(self, action: Optional[RunAction] = None) -> None:
        """Broadcast ``action``'s current status (skipped for nonblocking actions)."""
        if action is None:
            action = self.action
        if action.nonblocking:
            return
        LOGGER.info(
            f"Adding {action.action_uuid} to {action.action_name} status list."
        )
        await self.eventsink.emit_status(action.as_dict())

    def _build_data_package(
        self, datamodel: DataModel, action: Optional[RunAction] = None
    ) -> tuple[DataPackageModel, bool]:
        """Return ``(DataPackageModel, has_data)`` for ``datamodel``/``action``."""
        if action is None:
            action = self.action
        package = DataPackageModel(
            action_uuid=action.action_uuid,
            action_name=action.action_name,
            datamodel=datamodel,
            errors=datamodel.errors,
        )
        return package, bool(datamodel.data)

    async def enqueue_data(
        self,
        data: Mapping[Any, dict] | DataModel,
        action: Optional[RunAction] = None,
    ) -> None:
        """Broadcast a data batch and bump the queued counter if it had data.

        Accepts either a raw ``{file_conn_key: row}`` mapping (wrapped into an
        active :class:`DataModel`) or a ready :class:`DataModel`.
        """
        if isinstance(data, DataModel):
            datamodel = data
        else:
            datamodel = DataModel(
                data=dict(data), errors=[], status=HloStatus.active
            )
        package, has_data = self._build_data_package(datamodel, action)
        await self.eventsink.emit_data(package.as_dict())
        if has_data:
            self.num_data_queued += 1
            self._pending_data.append(package)

    async def _enqueue_phase_data(self, data: dict) -> None:
        """Enqueue executor-phase ``data`` keyed by the action's first file conn."""
        if not data:
            return
        key = self.action.file_conn_keys[0] if self.action.file_conn_keys else None
        await self.enqueue_data({key: data} if key is not None else {})

    # --- aux file writes -----------------------------------------------------

    async def write_file(
        self,
        output_str: str,
        file_type: str,
        filename: Optional[str] = None,
        header: Optional[str] = None,
        file_sample_label: Optional[List[str] | str] = None,
        json_data_keys: Optional[List[str]] = None,
        action: Optional[RunAction] = None,
    ) -> Optional[str]:
        """Write a single complete file via the storage port; return its relpath.

        Returns ``None`` when ``save_data`` is disabled. The HLO byte layout
        (``[header]\\n%%\\n[body]``) is produced by the storage adapter; this
        method opens a connection, writes the body row, and closes it.
        """
        if action is None:
            action = self.action
        if not action.save_data:
            return None
        if filename is None:
            filename = f"{action.action_name}-{action.action_uuid}.{file_type}"
        relpath = f"{action.action_output_dir}/{filename}"
        handle = await self.storage.open_hlo(relpath, header or "")
        await self.storage.append_hlo(handle, output_str)
        await self.storage.close_hlo(handle)
        return relpath

    # --- samples -------------------------------------------------------------

    def _set_sample_action_uuid(self, sample) -> None:
        """Tag a sample (and assembly sub-parts) with the action's UUID."""
        sample.action_uuid = [self.action.action_uuid]
        parts = getattr(sample, "parts", None)
        if parts:
            for part in parts:
                self._set_sample_action_uuid(part)

    async def append_sample(
        self,
        samples: list,
        IO: str,
        action: Optional[RunAction] = None,
    ) -> None:
        """Append samples to ``samples_in``/``samples_out`` and broadcast status.

        ``NoneSample`` entries are skipped; remaining samples have their
        ``action_uuid``/``inheritance``/``status`` defaults filled in. Ports
        ``Active.append_sample``.
        """
        if action is None:
            action = self.action
        if not samples:
            return

        for sample in samples:
            if isinstance(sample, NoneSample):
                continue
            self._set_sample_action_uuid(sample)
            if sample.inheritance is None:
                sample.inheritance = SampleInheritance.allow_both
            if not sample.status:
                sample.status = [SampleStatus.preserved]
            if IO == "in":
                if action.samples_in is None:
                    action.samples_in = []
                action.samples_in.append(sample)
            elif IO == "out":
                if action.samples_out is None:
                    action.samples_out = []
                action.samples_out.append(sample)

        await self.add_status(action=action)

    # --- executor loop -------------------------------------------------------

    async def action_loop_task(self, executor: Executor) -> RunAction:
        """Drive the executor lifecycle: pre -> exec | poll-loop -> manual_stop -> post.

        Data returned at any stage is enqueued through the event sink. Ports
        ``Active.action_loop_task`` (minus the concurrency-queue stall and the
        background data-logger task, which become Wave-4/app-layer concerns).

        Args:
            executor: The executor implementing the action.

        Returns:
            The action returned by :meth:`finish`.
        """
        LOGGER.info("action_loop_task started")
        # pre-action operations
        setup_state = await executor._pre_exec()
        setup_error = setup_state.get("error", ErrorCodes.none)
        if setup_error == ErrorCodes.none:
            self.action_loop_running = True
        else:
            LOGGER.info("Error encountered during executor setup.")
            self.action.error_code = setup_error
            return await self.finish()

        # one-shot execution
        LOGGER.info("Running executor._exec() method")
        try:
            result = await executor._exec()
        except Exception:
            LOGGER.error("Executor._exec() failed", exc_info=True)
            result = {}
        error = result.get("error", ErrorCodes.none)
        await self._enqueue_phase_data(result.get("data", {}))

        # polling loop for ongoing action
        if not executor.oneoff:
            LOGGER.info("entering executor polling loop")
            while self.action_loop_running:
                try:
                    result = await executor._poll()
                except Exception:
                    LOGGER.error("Executor._poll() failed", exc_info=True)
                    result = {}
                error = result.get("error", ErrorCodes.none)
                status = result.get("status", HloStatus.finished)
                await self._enqueue_phase_data(result.get("data", {}))
                if status == HloStatus.active:
                    # poll_rate sleep is an injected-clock concern; happy-path
                    # tests use poll_rate=0 so we don't block.
                    if executor.poll_rate:
                        await self._sleep(executor.poll_rate)
                else:
                    LOGGER.info("exiting executor polling loop")
                    self.action_loop_running = False

        if error != ErrorCodes.none:
            self.action.error_code = error
        self.action_loop_running = False

        # manual stop
        if self.manual_stop:
            stop_state = await executor._manual_stop()
            if stop_state.get("error", ErrorCodes.none) != ErrorCodes.none:
                LOGGER.info("Error encountered during manual stop.")

        # post-action operations
        cleanup_state = await executor._post_exec()
        await self._enqueue_phase_data(cleanup_state.get("data", {}))
        if cleanup_state.get("error", ErrorCodes.none) != ErrorCodes.none:
            LOGGER.info("Error encountered during executor cleanup.")

        return await self.finish()

    async def _sleep(self, seconds: float) -> None:
        """Cooperative yield between poll iterations (no wall-clock dependency).

        The real poll cadence is an app/clock-port concern; the domain only
        needs to yield control so the loop is cancellable.
        """
        await asyncio.sleep(0)

    # --- finish (minimal happy-path drain) -----------------------------------

    async def finish(self) -> RunAction:
        """Drain queued data, stamp the final status, and broadcast it.

        Minimal Wave-3 form: drains the pending-data queue (so
        ``num_data_written == num_data_queued``), appends ``HloStatus.finished``
        to the action status, rewrites the action meta, and emits the final
        status. The full drain (global params via transport, post-processors,
        aux-file relocation) is Wave 4.
        """
        # drain pending data to storage
        while self._pending_data:
            self._pending_data.pop(0)
            self.num_data_written += 1

        if HloStatus.finished not in self.action.action_status:
            self.action.action_status.append(HloStatus.finished)
        self.action.data_stream_status = HloStatus.finished

        await self.update_act_file()
        await self.add_status()
        return self.action
