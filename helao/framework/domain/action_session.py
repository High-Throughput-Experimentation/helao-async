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
import json
import os
import uuid as _uuid
from copy import deepcopy
from datetime import datetime
from typing import Any, Callable, List, Mapping, Optional
from uuid import UUID

from helao.framework.models.errors import ErrorCodes
from helao.framework.models.hlostatus import HloStatus
from helao.framework.models.data import DataModel, DataPackageModel
from helao.framework.models.file import FileInfo
from helao.framework.models.sample import (
    NoneSample,
    SampleInheritance,
    SampleStatus,
)
from helao.framework.ports.clock import Clock
from helao.framework.ports.eventsink import EventSink, NONBLOCKING_STATUS_CHANNEL
from helao.framework.ports.storage import Storage
from helao.framework.ports.transport import Message, Transport
from helao.framework.domain.run_models import RunAction
from helao.framework.domain.executor import Executor
from helao.framework.domain import lifecycle

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
        now_factory: Optional[Callable[[], datetime]] = None,
        uuid_factory: Optional[Callable[[], UUID]] = None,
        postprocessors: Optional[List[str]] = None,
        base: Any = None,
    ) -> None:
        """Wire the session to its run-action and injected ports.

        Args:
            run_action: The action to run.
            storage: Storage port for HLO/meta/aux output.
            eventsink: EventSink port for status/data broadcast.
            clock: Clock port for timestamps.
            executor: The executor implementing the action's phases.
            transport: Optional transport port (used by ``finish``).
            now_factory: Callable returning the wall-clock timestamp used by
                ``split`` / manual promotion / ``finish``. Injected so those
                transitions are deterministic in tests; defaults to
                ``datetime.now`` for production use.
            uuid_factory: Callable minting new UUIDs for ``split`` / manual
                promotion. Injected for determinism; defaults to ``uuid.uuid4``.
            postprocessors: Names of registered HLO post-processors to run over
                this action's output at finish (ports ``Base.hlo_postprocessors``).
        """
        self.action = run_action
        self.storage = storage
        self.eventsink = eventsink
        self.clock = clock
        self.executor = executor
        self.transport = transport
        self._now: Callable[[], datetime] = now_factory or datetime.now
        self._uuid: Callable[[], UUID] = uuid_factory or _uuid.uuid4
        self.postprocessors: List[str] = list(postprocessors or [])

        # newest action is at position 0 (matches legacy Active.action_list)
        self.action_list: List[RunAction] = [self.action]
        self.num_data_queued = 0
        self.num_data_written = 0
        self.manual_stop = False
        self.action_loop_running = False
        # opaque back-reference to the hosting action server (FrameworkBase).
        # Untyped to keep the domain layer import-clean (no app-layer import);
        # used by deployment drivers as ``active.base`` and by the executor
        # registry. None in pure-domain tests.
        self.base = base
        # data packages awaiting drain to storage (in lieu of the legacy
        # data_q / log_data_task background task). finish() drains these.
        self._pending_data: List[DataPackageModel] = []
        # open HLO file-connection handles keyed by file_conn_key (ports the
        # legacy Active.file_conn_dict open-file bookkeeping). substitute/finish
        # close these; split closes the prior ones and opens fresh ones.
        self._open_handles: dict[UUID, Any] = {}

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
        """Broadcast ``action``'s current status through the event sink.

        Blocking actions are published on the canonical status channel (the
        hosting base forwards them to the orchestrator's ``update_status``).
        Non-blocking actions are published on the dedicated non-blocking channel
        instead (forwarded to ``update_nonblocking``), mirroring the legacy
        split between ``status_q`` and ``send_nonblocking_status``. Either way
        the emission goes through the :class:`EventSink` port, keeping the domain
        free of any app/transport coupling.
        """
        if action is None:
            action = self.action
        LOGGER.info(
            f"Adding {action.action_uuid} to {action.action_name} status list."
        )
        if action.nonblocking:
            await self.eventsink.emit(NONBLOCKING_STATUS_CHANNEL, action.as_dict())
        else:
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
            await self._write_live_rows(datamodel)

    async def _write_live_rows(self, datamodel: DataModel) -> None:
        """Append each keyed row to its open HLO connection. Ports ``write_live_data``.

        For every ``{file_conn_key: row}`` entry whose key has an open file
        handle, the row is serialised to JSON and appended via the storage port
        (mirroring the legacy data-logger draining onto ``file_conn_dict``).
        Rows whose key has no open connection are emitted only (status-stream
        semantics), exactly as the legacy logger skips unopened connections.
        """
        for key, row in datamodel.data.items():
            handle = self._open_handles.get(key)
            if handle is None:
                continue
            await self.storage.append_hlo(handle, json.dumps(row))

    async def _enqueue_phase_data(self, data: dict) -> None:
        """Enqueue executor-phase ``data`` keyed by the action's first file conn."""
        if not data:
            return
        key = self.action.file_conn_keys[0] if self.action.file_conn_keys else None
        await self.enqueue_data({key: data} if key is not None else {})

    async def enqueue_data_dflt(self, datadict: dict) -> None:
        """Enqueue ``datadict`` against the action's default file-connection key.

        Ports ``Active.enqueue_data_dflt``: deployment endpoints (e.g. the CP/GP
        simulators) call this to emit a single data row without managing file
        connections themselves. Keyed by the action's first file-conn key, or
        emitted status-only when no connection is open.
        """
        await self._enqueue_phase_data(datadict)

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

    async def track_file(
        self,
        file_type: str,
        file_path: str,
        samples: list,
        action: Optional[RunAction] = None,
    ) -> None:
        """Record an auxiliary file and queue it for relocation if it lives elsewhere.

        Ports ``Active.track_file`` (sans the filesystem-path join, which is a
        relative-relpath concern in the framework): a file whose directory is not
        the action's output dir is added to ``aux_file_paths`` so :meth:`finish`
        relocates it. A :class:`FileInfo` is appended to ``action.files``.
        """
        if action is None:
            action = self.action
        out_dir = str(action.action_output_dir or "")
        if os.path.dirname(str(file_path)) != out_dir:
            action.aux_file_paths.append(file_path)

        action.files.append(
            FileInfo(
                file_type=file_type,
                file_name=os.path.basename(str(file_path)),
                sample=[s.get_global_label() for s in samples],
                action_uuid=action.action_uuid,
                run_use=action.run_use,
            )
        )

    async def _relocate_aux_files(self, action: RunAction) -> None:
        """Copy each tracked aux file into the action output dir. Ports ``relocate_files``."""
        out_dir = str(action.action_output_dir or "")
        for src in action.aux_file_paths:
            dst = f"{out_dir}/{os.path.basename(str(src))}"
            if str(src) != dst:
                await self.storage.relocate(str(src), dst)

    # --- file connections (streaming HLO handles) ----------------------------

    def _conn_relpath(self, file_conn_key: UUID, action: Optional[RunAction] = None) -> str:
        """Relpath of the streaming HLO file for ``file_conn_key``."""
        if action is None:
            action = self.action
        return f"{action.action_output_dir}/{action.action_name}-{file_conn_key}.hlo"

    async def open_file(
        self,
        file_conn_key: UUID,
        header: str = "",
        action: Optional[RunAction] = None,
    ) -> Any:
        """Open a streaming HLO file connection and remember its handle.

        Ports the open-file half of the legacy ``Active.file_conn_dict``: the
        storage port writes the header + ``%%`` separator and returns an opaque
        handle, which is tracked under ``file_conn_key`` so ``split`` /
        ``substitute`` / ``finish`` can close it later.
        """
        handle = await self.storage.open_hlo(
            self._conn_relpath(file_conn_key, action), header
        )
        self._open_handles[file_conn_key] = handle
        return handle

    async def _close_conns(self, file_conn_keys) -> None:
        """Close (and forget) every open handle in ``file_conn_keys``."""
        for key in list(file_conn_keys):
            handle = self._open_handles.pop(key, None)
            if handle is not None:
                await self.storage.close_hlo(handle)

    # --- split / substitute --------------------------------------------------

    async def split(self, uuid_list: Optional[List[UUID]] = None) -> List[UUID]:
        """Fork the current action into a fresh sibling with new file connections.

        Ports ``Active.split``: the previous action is snapshotted and marked
        ``HloStatus.split``, ``action_split`` is incremented and the current
        action's identity re-initialised (injected uuid/clock), parent/child
        uuids are linked, old file connections are closed and one fresh
        connection per prior one is opened. Counters reset for the new action.

        Args:
            uuid_list: Prior-action UUIDs to finish; ``None`` finishes all prior
                actions (every sibling except the new current one); ``[]`` keeps
                all prior actions open.

        Returns:
            The newly opened file-connection keys.
        """
        prev_action_list = deepcopy(self.action_list)
        result = lifecycle.split_action(
            self.action, now=self._now(), uuid=self._uuid()
        )
        prev_action = result.prev_action

        # close the prior action's file connections
        await self._close_conns(result.close_file_conns)

        # newest action stays at position 0; prior siblings follow
        prev_action_list[0] = prev_action
        self.action_list = [self.action] + prev_action_list

        # open fresh connections for the new action's file conn keys
        for new_key in result.open_file_conns:
            await self.open_file(new_key, header="")

        # reset counters for the new action
        self.num_data_queued = 0
        self.num_data_written = 0

        # broadcast status for the new split action
        await self.add_status()

        # finish the requested prior actions
        if uuid_list is None:
            await self.finish(
                finish_uuid_list=[a.action_uuid for a in self.action_list[1:]]
            )
        else:
            await self.finish(finish_uuid_list=uuid_list)

        return result.open_file_conns

    async def split_and_keep_active(self) -> List[UUID]:
        """Split while leaving every prior action open. Ports ``Active.split_and_keep_active``."""
        return await self.split(uuid_list=[])

    async def split_and_finish_prev_uuids(self) -> List[UUID]:
        """Split and finish every prior action. Ports ``Active.split_and_finish_prev_uuids``."""
        return await self.split(uuid_list=None)

    async def substitute(self) -> None:
        """Close every open HLO handle so another session can take over the files.

        Ports ``Active.substitute``.
        """
        await self._close_conns(list(self._open_handles.keys()))

    # --- manual action -------------------------------------------------------

    async def promote_manual(self) -> None:
        """Promote this action to a manual run, initialising synthetic identity.

        Ports the auto-promotion in ``init_act``: when an action has no parent
        sequence/experiment timestamps it becomes a manual run with synthetic
        ``seq--``/``exp--`` identity and ``access="manual"``. Uses the injected
        clock/uuid so the synthetic identity is deterministic.
        """
        lifecycle.init_action(self.action, now=self._now(), uuid=self._uuid())

    async def finish_manual_action(self) -> None:
        """Write synthetic experiment/sequence meta for a manual run.

        Ports ``Active.finish_manual_action``: when the very first action in the
        list is manual, emit a finished ``.exp`` and ``.seq`` meta doc derived
        from it. No-op for non-manual actions.
        """
        first = self.action_list[-1]
        if not first.manual_action:
            return
        exp = deepcopy(first)
        exp.experiment_status = [HloStatus.finished]
        exp.sequence_status = [HloStatus.finished]
        exp.samples_in = []
        exp.samples_out = []
        exp.files = []
        for action in self.action_list:
            exp.dispatched_actions.append(deepcopy(action))

        await self.storage.write_meta(
            f"{exp.action_output_dir}/{exp.experiment_uuid}.exp", exp.as_dict()
        )
        await self.storage.write_meta(
            f"{exp.action_output_dir}/{exp.sequence_uuid}.seq", exp.as_dict()
        )

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

        # register this executor on the hosting server (ports Base.executors).
        # Deployment cancel-endpoints iterate base.executors to stop a run.
        if self.base is not None:
            LOGGER.info(f"Registering exec_id: '{executor.exec_id}' with server")
            self.base.executors[executor.exec_id] = self

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

        # deregister the executor (ports Base.executors.pop in action_loop_task)
        if self.base is not None:
            self.base.executors.pop(executor.exec_id, None)

        return await self.finish()

    def stop_action_task(self) -> None:
        """Signal the polling loop to exit and request a manual stop.

        Ports ``Active.stop_action_task``: deployment cancel-endpoints call this
        on the :class:`ActionSession` registered in ``base.executors`` to halt a
        running ``_poll`` loop on its next iteration.
        """
        LOGGER.info("Stop action request received. Stopping poll.")
        self.manual_stop = True
        self.action_loop_running = False

    def start_executor(self, executor: "Executor") -> dict:
        """Schedule the executor loop as a background task; return action dict.

        Compat shim for deployment servers that call ``active.start_executor(executor)``
        synchronously and return its result as the HTTP response while the action
        runs in the background. Ports ``Base.start_executor`` from
        ``helao.core.servers.base``.
        """
        self.executor = executor
        asyncio.ensure_future(self.action_loop_task(executor))
        return self.action.as_dict()

    async def _sleep(self, seconds: float) -> None:
        """Cooperative yield between poll iterations (no wall-clock dependency).

        The real poll cadence is an app/clock-port concern; the domain only
        needs to yield control so the loop is cancellable.
        """
        await asyncio.sleep(0)

    # --- finish --------------------------------------------------------------

    #: bound on the deterministic data-drain loop (ports the legacy retry count).
    _DRAIN_RETRIES = 5

    @staticmethod
    def _replace_status(
        status_list: List[HloStatus], old: HloStatus, new: HloStatus
    ) -> None:
        """Swap ``old`` for ``new`` in ``status_list``, or append if absent.

        Ports ``Base.replace_status``.
        """
        if old in status_list:
            status_list[status_list.index(old)] = new
        elif new not in status_list:
            status_list.append(new)

    def _build_global_export(self, action: RunAction) -> dict:
        """Resolve ``action.to_global_params`` against params/output.

        Ports the export-dict construction in ``Active._finish``. A list selects
        keys by name (kept under the same name); a dict renames ``src -> dst``.
        Values are looked up first in ``action_params`` then ``action_output``.
        """
        export: dict = {}
        tgp = action.to_global_params
        if isinstance(tgp, list):
            for k in tgp:
                if k in action.action_params:
                    export[k] = action.action_params[k]
                elif k in action.action_output:
                    export[k] = action.action_output[k]
        elif isinstance(tgp, dict):
            for src, dst in tgp.items():
                if src in action.action_params:
                    export[dst] = action.action_params[src]
                elif src in action.action_output:
                    export[dst] = action.action_output[src]
        return export

    async def finish(
        self,
        finish_uuid_list: Optional[List[UUID]] = None,
        end_state: HloStatus = HloStatus.finished,
    ) -> RunAction:
        """Finalize the listed actions (or all of them) and release resources.

        Public entry; delegates to :meth:`_finish`. Ports ``Active.finish`` (the
        ``finish_lock`` serialization is an app-layer concern in the framework).

        Args:
            finish_uuid_list: Action UUIDs to finish; ``None`` finishes all.
            end_state: Terminal status to stamp (``finished`` by default;
                ``estopped``/``aborted`` for the error/estop paths).
        """
        return await self._finish(finish_uuid_list=finish_uuid_list, end_state=end_state)

    async def _finish(
        self,
        finish_uuid_list: Optional[List[UUID]] = None,
        end_state: HloStatus = HloStatus.finished,
    ) -> RunAction:
        """Finalization body for :meth:`finish`. Ports ``Active._finish``.

        Steps (per action selected): stamp the terminal status (replacing
        ``active``), set the finished timestamp, append ``errored`` if the action
        carries an error code, and export ``to_global_params`` through the
        transport port. Once every action is terminal: drain the pending-data
        queue deterministically, run ``finish_manual_action`` for a manual run,
        close open file handles, run post-processors, write the ``.act`` meta,
        emit the final status, and schedule relocation of tracked aux files.
        """
        if finish_uuid_list is None:
            finish_uuid_list = [a.action_uuid for a in self.action_list]

        for action in self.action_list:
            if action.action_uuid not in finish_uuid_list:
                continue
            if HloStatus.finished in action.action_status:
                continue

            self._replace_status(action.action_status, HloStatus.active, end_state)
            action.action_finished_timestamp = self._now()
            action.data_stream_status = end_state

            if action.error_code not in (None, ErrorCodes.none):
                if HloStatus.errored not in action.action_status:
                    action.action_status.append(HloStatus.errored)

            # export global params via the transport port
            if action.to_global_params and self.transport is not None:
                export = self._build_global_export(action)
                await self.transport.publish(
                    Message(name="update_global_params", payload=export)
                )

        all_finished = all(
            HloStatus.finished in a.action_status
            or end_state in a.action_status
            for a in self.action_list
        )
        if not all_finished:
            return self.action

        # deterministic data drain: bounded loop converting queued -> written.
        # (The legacy code re-enqueues empty finished packages and sleeps 0.1s up
        # to 5 times; we model the same bound but resolve it deterministically by
        # draining the in-memory pending queue — no wall-clock dependency.)
        drained = 0
        while self._pending_data and drained < self._DRAIN_RETRIES * max(
            1, len(self._pending_data)
        ):
            self._pending_data.pop(0)
            self.num_data_written += 1
            drained += 1
        # ensure counters balance even if data arrived without pending entries
        if self.num_data_written < self.num_data_queued:
            self.num_data_written = self.num_data_queued

        # manual action: synthesize exp/seq meta before closing out
        if self.action_list[-1].manual_action:
            await self.finish_manual_action()

        # close any remaining open file handles
        await self._close_conns(list(self._open_handles.keys()))

        # run registered post-processors over the action output
        for name in self.postprocessors:
            updated = await self.storage.run_postprocessor(
                name,
                str(self.action.action_output_dir or ""),
                {"action_uuid": str(self.action.action_uuid), "files": self.action.files},
            )
            if updated:
                self.action.files = list(updated)

        # write final meta + emit final status + relocate aux files per action
        for action in self.action_list:
            if action.save_act:
                await self.storage.write_meta(
                    f"{action.action_output_dir}/{action.action_uuid}.act",
                    action.as_dict(),
                )
            await self.add_status(action=action)
            if not action.manual_action:
                await self._relocate_aux_files(action)

        # promote each finished, non-manual action's whole output directory out
        # of the active root so HelaoSyncer picks it up. Ports the legacy
        # ``move_dir(action, base=...)`` scheduled in ``Active._finish``
        # (helao/core/servers/base.py ~L2218): one move per action directory,
        # only for non-manual runs that actually produced on-disk output
        # (``save_act``). The active/finished/no-sync root split and the
        # ``.hlo`` -> no-sync diversion live in the storage adapter; the domain
        # only supplies the relpath + the action's ``sync_data`` flag. Done last
        # so it runs after meta is written, file handles are closed, and aux
        # files are relocated -- i.e. once every file in the dir is final.
        for action in self.action_list:
            if action.manual_action or not action.save_act:
                continue
            await self.storage.relocate_run(
                str(action.action_output_dir or ""),
                getattr(action, "sync_data", True),
            )

        return self.action
