"""HELAO orchestrator runtime.

Implements the :class:`Orch` service that extends :class:`Base` with the
sequence/experiment/action deques, the dispatch loop that drives them, the
global status model used by the Bokeh operator UI, and the heartbeat /
status-monitor tasks that keep the orchestrator aware of every action server
in the world configuration.
"""

__all__ = ["Orch"]

from helao.helpers import helao_logging as logging

import asyncio
import sys
from typing import List
from uuid import UUID
import re
import traceback
from typing import Optional

import time

import colorama
from fastapi import WebSocket

from helao.core.models.experiment import ExperimentModel, ShortExperimentModel
from helao.core.models.server import ActionServerModel, GlobalStatusModel
from helao.core.models.orchstatus import LoopStatus, LoopIntent
from helao.core.error import ErrorCodes

from helao.helpers.server_api import HelaoFastAPI
from helao.helpers.import_autolibs import import_autolibs
from helao.helpers.dispatcher import (
    async_action_dispatcher,  # noqa: F401  re-export: EstopController + orch_dispatch import it from here so orch stays the single golden-master patch point
)
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.yml_tools import (
    move_dir,  # noqa: F401  re-export: EstopController + orch_lifecycle import it from here so orch stays the single golden-master patch point
)
from helao.helpers.premodels import Sequence, Experiment, Action
from helao.core.servers.base import Base, Active
from helao.core.servers.orch_persist import QueuePersister
from helao.core.servers.orch_monitor import ServerMonitor
from helao.core.servers.orch_status_sync import StatusIngester
from helao.core.servers.orch_queues import RunQueues
from helao.core.servers import orch_unpack
from helao.core.servers.orch_unpack import (
    PLATE_API,
)  # noqa: F401  re-export: preserves monkeypatch point helao.core.servers.orch.PLATE_API
from helao.core.servers.orch_lifecycle import RunLifecycle
from helao.core.servers.orch_dispatch import DispatchRunner
from helao.core.servers.orch_estop import EstopController
from helao.helpers.zdeque import zdeque
from helao.core.drivers.data.sync_driver import HelaoSyncer
from helao.helpers.processors import MetaProcessor
from helao.helpers.dequedict import DequeDict

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def sanitize_sequence_label(label):
    """Collapse whitespace/underscore runs to single underscores (None-safe)."""
    if not label:
        return label
    return re.sub(r"[\s_]+", "_", label)


# ANSI color codes converted to the Windows versions
# strip colors if stdout is redirected
colorama.init(strip=not sys.stdout.isatty())


class Orch(Base):
    """Long-lived orchestrator service that schedules sequences, experiments and actions.

    Builds on :class:`Base` by importing the deployment's experiment and
    sequence libraries, running the dispatch loop, maintaining a
    ``GlobalStatusModel`` of every action server, optionally hosting the Bokeh
    operator UI, and emitting heartbeat/status pings so the queues react to
    remote events. Database integration is enabled when a ``DB`` server is
    present in the world config.
    """

    loop_task: asyncio.Task
    status_subscriber: asyncio.Task
    globstat_broadcaster: asyncio.Task
    heartbeat_monitor: asyncio.Task
    driver_monitor: asyncio.Task

    def __init__(self, fastapp: HelaoFastAPI):
        """Wire the orchestrator into a FastAPI app and load its experiment/sequence libraries.

        Args:
            fastapp: The ``HelaoFastAPI`` instance hosting the orchestrator.
        """
        super().__init__(fastapp)
        (
            self.experiment_lib,
            self.experiment_codehash_lib,
            self.experiment_codepath_lib,
        ) = import_autolibs(
            world_config_dict=self.world_cfg,
            lib_dir=None,
            user_lib_dir=self.helaodirs.user_exp,
            lib_type="experiment",
        )
        self.sequence_lib, self.sequence_codehash_lib, self.sequence_codepath_lib = (
            import_autolibs(
                world_config_dict=self.world_cfg,
                lib_dir=None,
                user_lib_dir=self.helaodirs.user_seq,
                lib_type="sequence",
            )
        )

        self.use_db = "DB" in self.world_cfg["servers"].keys()
        if self.use_db:
            self.syncer = HelaoSyncer(action_serv=self, db_server_name="DB")

        # instantiate experiment/experiment queue, action queue
        self.sequence_dq = zdeque([])
        self.experiment_dq = zdeque([])
        self.action_dq = zdeque([])
        self.dispatch_buffer = []
        self.nonblocking = []

        # holder for tracking dispatched action in status
        self.last_dispatched_action_uuid = None
        self.action_history = DequeDict(maxlen=1000)
        self.experiment_history = DequeDict(maxlen=1000)
        self.sequence_history = DequeDict(maxlen=1000)
        self.last_action_uuid = ""
        self.last_interrupt = time.time()
        # hold schema objects
        self.active_experiment: Experiment = None
        self.last_experiment: Experiment = None
        self.active_sequence: Sequence = None
        self.active_seq_exp_counter = 0
        self.last_sequence: Sequence = None
        self.active_run_id: Optional[UUID] = None
        self.heartbeat_interval = self.server_params.get("heartbeat_interval", 10)
        self.ignore_heartbeats = self.server_params.get("ignore_heartbeats", [])
        self.verify_plates = self.server_params.get("verify_plates", True)
        # basemodel which holds all information for orch
        self.globalstatusmodel = GlobalStatusModel(orchestrator=self.server)
        self.globalstatusmodel._sort_status()
        # this queue is simply used for waiting for any interrupt
        # but it does not do anything with its content
        self.interrupt_q = asyncio.Queue()
        self.incoming_status = asyncio.Queue()
        self.incoming = None

        self.init_success = False  # need to subscribe to all fastapi servers in config

        # pointer to dispatch_loop_task
        self.loop_task = None
        self.status_subscriber = None
        self.globstat_broadcaster = None
        self.heartbeat_monitor = None
        self.driver_monitor = None

        # pointer to wait_task
        self.wait_task = None
        self.current_wait_ts = 0
        self.last_wait_ts = 0

        self.globstat_q = MultisubscriberQueue()
        self.globstat_clients = set()
        self.current_stop_message = ""

        self.step_thru_actions = False
        self.step_thru_experiments = False
        self.step_thru_sequences = False
        self.status_summary = {}
        self.global_params = {}

        self.exp_postprocessors: List[MetaProcessor] = []
        self.exp_postprocess_libs = self.server_cfg.get("exp_postprocess_libs", [])
        self.import_postprocessors(
            self.exp_postprocess_libs, self.exp_postprocessors, MetaProcessor
        )

        self.seq_postprocessors: List[MetaProcessor] = []
        self.seq_postprocess_libs = self.server_cfg.get("seq_postprocess_libs", [])
        self.import_postprocessors(
            self.seq_postprocess_libs, self.seq_postprocessors, MetaProcessor
        )

        self._init_collaborators()

    def _init_collaborators(self):
        """Construct the collaborators extracted from ``Orch`` by CARDS P5.

        Called from ``__init__`` at the point each collaborator's state was
        previously constructed inline; test fixtures that bypass ``__init__``
        (e.g. the dispatch golden-master harness's ``Orch.__new__``
        construction) call this directly so collaborators exist without
        per-collaborator lazy guards.

        Calls ``super()`` first so the ``Base`` collaborators (``live_buffer_mgr``,
        ``status_broadcaster``, CARDS P6) are also built on ``Orch`` instances --
        the orchestrator inherits and delegates those status/live-buffer methods.
        """
        super()._init_collaborators()
        self.queue_persister = QueuePersister(self)
        self.server_monitor = ServerMonitor(self)
        self.status_ingester = StatusIngester(self)
        self.run_queues = RunQueues(self)
        self.run_lifecycle = RunLifecycle(self)
        self.dispatch_runner = DispatchRunner(self)
        self.estop_controller = EstopController(self)

    def exception_handler(self, loop, context):
        """Log uncaught coroutine exceptions caught by the orchestrator's event loop."""
        LOGGER.error(f"Got exception from coroutine: {context}")
        exc = context.get("exception")
        LOGGER.error(f"{traceback.format_exception(type(exc), exc, exc.__traceback__)}")
        # LOGGER.info("setting E-STOP flag on active actions")
        # for _, active in self.actives.items():
        #     active.stop_action_task()

    def myinit(self):
        """Start the orchestrator's background tasks (status, broadcasts, heartbeats) and Bokeh UI."""
        self.aloop = asyncio.get_running_loop()
        self.aloop.set_exception_handler(self.exception_handler)

        self.bufferer = self.aloop.create_task(self.live_buffer_task())
        asyncio.gather(self.init_endpoint_status())

        self.fast_urls = self.get_endpoint_urls()
        self.status_logger = self.aloop.create_task(self.log_status_task())
        if self.server_cfg.get("regular_update", False):
            regular_delay = self.server_cfg.get("regular_update_delay", 10)
            self.regular_updater = self.aloop.create_task(
                self.regular_status_task(regular_delay)
            )

        self.status_subscriber = asyncio.create_task(self.subscribe_all())
        self.globstat_broadcaster = asyncio.create_task(self.globstat_broadcast_task())
        self.heartbeat_monitor = asyncio.create_task(self.active_action_monitor())
        self.driver_monitor = asyncio.create_task(self.action_server_monitor())

        # Restore previously exported queues only when opted in, either via the
        # per-server config key `restore_queues_on_startup: true` or the launcher
        # CLI switch `--restore` (which sets that key for orchestrators). Left off
        # by default so a stale STATES/queues.pck is never silently replayed.
        if self.server_cfg.get("restore_queues_on_startup", False):
            LOGGER.info(
                "restore_queues_on_startup is set; importing saved queues from "
                "STATES/queues.pck."
            )
            self.import_queues()

    def register_obj_uuid(self, obj_uuid_key, obj_uuid_dict, obj_type: str):
        """Insert or merge a UUID's metadata into the action/experiment/sequence history map.

        Args:
            obj_uuid_key: UUID of the action, experiment, or sequence.
            obj_uuid_dict: Metadata associated with the UUID.
            obj_type: One of ``"action"``, ``"experiment"``, or ``"sequence"``.
        """
        return self.run_queues.register_obj_uuid(obj_uuid_key, obj_uuid_dict, obj_type)

    def register_action_uuid(self, action_uuid, action_dict):
        """Record an action UUID and its metadata in the action history map."""
        return self.run_queues.register_action_uuid(action_uuid, action_dict)

    def track_action_uuid(self, action_uuid):
        """Remember ``action_uuid`` as the most recently dispatched action."""
        return self.run_queues.track_action_uuid(action_uuid)

    async def wait_for_interrupt(self, pending_action: Optional[Action] = None) -> bool:
        """Block until an interrupt message arrives and forward queued ``GlobalStatusModel``s.

        Args:
            pending_action: Optional action to push back onto ``action_dq`` if a
                stop intent arrives while waiting.

        Returns:
            ``True`` if processing should continue, ``False`` if the pending
            action was re-queued and the caller should bail out.
        """

        interrupt = await self.interrupt_q.get()
        if isinstance(interrupt, GlobalStatusModel):
            self.incoming = interrupt

        self.last_interrupt = time.time()
        # if not empty clear it
        while not self.interrupt_q.empty():
            interrupt = await self.interrupt_q.get()
            if isinstance(interrupt, GlobalStatusModel):
                self.incoming = interrupt
                await self.globstat_q.put(interrupt.as_json())

        if (
            pending_action is not None
            and self.globalstatusmodel.loop_intent == LoopIntent.stop
        ):

            pending_action.action_server.machine_name = self.server.machine_name
            self.action_dq.insert(0, pending_action)
            return False
        return True

    async def subscribe_all(self, retry_limit: int = 15):
        """Subscribe this orchestrator to every non-Bokeh action server in the world config.

        Args:
            retry_limit: Maximum subscription attempts per server.
        """
        return await self.server_monitor.subscribe_all(retry_limit=retry_limit)

    async def update_nonblocking(
        self, actionmodel: Action, server_host: str, server_port: int
    ) -> dict:
        """Record a non-blocking action transition and nudge the dispatch loop.

        Args:
            actionmodel: ``Action`` describing the non-blocking event.
            server_host: Host of the action server reporting the event.
            server_port: Port of the action server reporting the event.

        Returns:
            ``{"success": True}`` once the action's executor id has been
            added or removed from ``self.nonblocking``.
        """
        return await self.status_ingester.update_nonblocking(
            actionmodel, server_host, server_port
        )

    async def clear_nonblocking(self) -> list:
        """Send ``stop_executor`` to every tracked non-blocking action and return their responses."""
        return await self.status_ingester.clear_nonblocking()

    async def update_status(
        self, actionservermodel: Optional[ActionServerModel] = None
    ) -> bool:
        """Merge an action-server status into the global status model and react to errors/estops.

        Updates the action history, tracks completed non-active actions in the
        live buffer, transitions the orchestrator to ``estopped``, ``error``,
        ``idle`` or ``busy`` as appropriate, and pushes the new status to the
        interrupt queue and Bokeh operator.

        Args:
            actionservermodel: Reported status from a remote action server.

        Returns:
            ``True`` if the model was applied, ``False`` if ``actionservermodel`` was ``None``.
        """
        return await self.status_ingester.update_status(actionservermodel)

    async def ws_globstat(self, websocket: WebSocket):
        """Stream global status updates over ``websocket`` until the client disconnects."""
        return await self.status_ingester.ws_globstat(websocket)

    async def globstat_broadcast_task(self):
        """Drain ``globstat_q`` indefinitely so subscribers can read messages eagerly."""
        return await self.status_ingester.globstat_broadcast_task()

    def unpack_sequence(self, sequence_name: str, sequence_params) -> List[Experiment]:
        """Invoke the named sequence factory and return the list of planned experiments.

        Args:
            sequence_name: Sequence library entry to expand.
            sequence_params: Keyword arguments forwarded to the sequence factory.
        """
        return orch_unpack.unpack_sequence(
            sequence_name, sequence_params, self.sequence_lib
        )

    def get_sequence_codehash(self, sequence_name: str) -> UUID:
        """Return the cached code hash for the named sequence library entry."""
        return orch_unpack.get_sequence_codehash(
            sequence_name, self.sequence_codehash_lib
        )

    async def seq_unpacker(self):
        """Push every planned experiment from the active sequence onto the experiment deque."""
        return await orch_unpack.seq_unpacker(self)

    def verify_plate_in_params(self, paramd: dict) -> bool:
        """Confirm that any ``plate_id``/``solid_plate_id`` parameter resolves to a valid platemap.

        Args:
            paramd: Parameter dictionary to inspect.

        Returns:
            ``True`` if no plate parameter is present or a platemap was found.
        """
        return orch_unpack.verify_plate_in_params(paramd)

    async def loop_task_dispatch_sequence(self) -> ErrorCodes:
        """Pop the next sequence, make it active, validate it, and spawn its experiment unpacker.

        Delegates to :class:`DispatchRunner` (CARDS P5 S8). Kept as an ``Orch``
        delegator because it is the public surface the golden master + orch_api
        call.

        Returns:
            ``ErrorCodes.none`` on success, or a non-zero code if the sequence
            could not be started (for example because plate verification failed).
        """
        return await self.dispatch_runner.dispatch_sequence()

    async def loop_task_dispatch_experiment(self) -> ErrorCodes:
        """Pop the next experiment, expand its planned actions, and push them onto ``action_dq``.

        Delegates to :class:`DispatchRunner` (CARDS P5 S8). Returns
        ``ErrorCodes.none`` on success, or a non-zero code if the experiment
        could not be processed (for example because plate verification failed).
        """
        return await self.dispatch_runner.dispatch_experiment()

    async def loop_task_dispatch_action(self) -> ErrorCodes:
        """Dispatch the next action from ``action_dq`` honouring start conditions and loop intent.

        Delegates to :class:`DispatchRunner` (CARDS P5 S8). Respects
        ``LoopIntent.stop``/``skip``/``estop``, waits according to the action's
        ``ActionStartCondition``, copies requested values into and out of
        ``global_params``, registers the dispatched action in the global status
        model, and pauses the orchestrator if dispatch fails.

        Returns:
            ``ErrorCodes`` summarising the dispatch outcome.
        """
        return await self.dispatch_runner._launch_action()

    async def dispatch_loop_task(self) -> bool:
        """Drive the main orchestrator loop until the queues are exhausted or it is stopped.

        Delegates to :class:`DispatchRunner` (CARDS P5 S8), which inverts the
        former imperative loop into a pure ``DispatchPolicy`` + async effect
        runner. Kept as an ``Orch`` delegator so ``start_loop``'s
        ``asyncio.create_task(self.dispatch_loop_task())`` keeps a stable
        bound-method identity. Returns ``True`` on a clean exit and ``False`` on
        a raised exception (after triggering an E-STOP).
        """
        return await self.dispatch_runner.run()

    async def orch_wait_for_all_actions(self):
        """Block until ``globalstatusmodel.actions_idle()`` reports no active actions."""

        # LOGGER.info("orch is waiting for all action_dq to finish")

        # some actions are active
        # we need to wait for them to finish
        while not self.globalstatusmodel.actions_idle():
            if time.time() - self.last_interrupt > 10.0:
                LOGGER.info("some actions are still active, waiting for status update")
            # we check again once the active action
            # updates its status again
            await self.wait_for_interrupt()
            # LOGGER.info("got status update")
            # we got a status update
        # LOGGER.info("all actions are idle")

    async def start(self):
        """Resume or start the dispatch loop when queues are non-empty and the loop is stopped."""
        if self.globalstatusmodel.loop_state == LoopStatus.stopped:
            if (
                self.action_dq
                or self.experiment_dq
                or self.sequence_dq
                or self.active_sequence is not None
            ):  # resume actions from a paused run
                await self.start_loop()
            else:
                LOGGER.info("experiment list is empty")
        else:
            LOGGER.info("already running")
        self.current_stop_message = ""

    async def start_loop(self) -> LoopStatus:
        """Start :meth:`dispatch_loop_task` if the loop is stopped, refusing to start under E-STOP.

        Returns:
            The current ``LoopStatus`` after the attempt.
        """
        if self.globalstatusmodel.loop_state == LoopStatus.stopped:
            LOGGER.info("starting orch loop")
            self.loop_task = asyncio.create_task(self.dispatch_loop_task())
        elif self.globalstatusmodel.loop_state == LoopStatus.estopped:
            LOGGER.error("E-STOP flag was raised, clear E-STOP before starting.")
        else:
            LOGGER.info("loop already started.")
        return self.globalstatusmodel.loop_state

    async def estop_loop(self, reason: str = ""):
        """Emergency-stop the orchestrator and fan out an ``estop`` to every action server.

        Delegates to :class:`EstopController` (CARDS P5b). Kept as an ``Orch``
        delegator because it is the public surface orch_api, the status ingester,
        and the dispatch loop (and the golden-master spy) call.

        Args:
            reason: Free-form text appended to the stop message and alert.
        """
        return await self.estop_controller.estop_loop(reason=reason)

    async def stop_loop(self):
        """Signal the dispatch loop to stop after the current iteration via :meth:`intend_stop`."""
        await self.intend_stop()

    async def estop_actions(self, switch: bool):
        """Signal every registered action server to emergency-stop (or release).

        Delegates to :class:`EstopController` (CARDS P5b).

        Args:
            switch: ``True`` to latch the per-server estop flag, ``False`` to
                release it.
        """
        return await self.estop_controller.estop_actions(switch)

    async def estop_finish_active(self):
        """Finalize the active experiment and sequence with estopped status on e-stop.

        Delegates to :class:`EstopController` (CARDS P5b). Marks the active
        experiment/sequence ``estopped``, persists the yml, and schedules a
        background promotion to ``RUNS_FINISHED`` so the syncer can ship the
        partial run.
        """
        return await self.estop_controller.estop_finish_active()

    async def skip(self):
        """Request a skip while running, or clear ``action_dq`` if the loop is idle."""
        if self.globalstatusmodel.loop_state == LoopStatus.started:
            await self.intend_skip()
        else:
            LOGGER.info("orchestrator not running, clearing action queue")
            self.action_dq.clear()

    async def intend_skip(self):
        """Set ``LoopIntent.skip`` and post it to the interrupt queue."""
        self.globalstatusmodel.loop_intent = LoopIntent.skip
        await self.interrupt_q.put(self.globalstatusmodel.loop_intent)

    async def stop(self, reset_run_id: bool = False):
        """Request a graceful stop respecting the current loop state.

        When ``reset_run_id`` is True, also drop ``active_run_id`` so the next
        dequeued sequence starts a fresh run rather than re-joining the current
        one.
        """
        if self.globalstatusmodel.loop_state == LoopStatus.started:
            await self.intend_stop()
        elif self.globalstatusmodel.loop_state == LoopStatus.estopped:
            LOGGER.info("orchestrator E-STOP flag was raised; nothing to stop")
        else:
            LOGGER.info("orchestrator is not running")
        if reset_run_id:
            LOGGER.info("resetting active_run_id on stop")
            self.active_run_id = None

    async def intend_stop(self):
        """Set ``LoopIntent.stop`` and post it to the interrupt queue."""
        self.globalstatusmodel.loop_intent = LoopIntent.stop
        await self.interrupt_q.put(self.globalstatusmodel.loop_intent)

    async def intend_estop(self):
        """Set ``LoopIntent.estop`` and post it to the interrupt queue."""
        self.globalstatusmodel.loop_intent = LoopIntent.estop
        await self.interrupt_q.put(self.globalstatusmodel.loop_intent)

    async def intend_none(self):
        """Reset ``loop_intent`` to ``LoopIntent.none`` and post it to the interrupt queue."""
        self.globalstatusmodel.loop_intent = LoopIntent.none
        await self.interrupt_q.put(self.globalstatusmodel.loop_intent)

    async def clear_estop(self):
        """Clear estopped UUIDs, release the estop on every action server, and resume to ``stopped``.

        Delegates to :class:`EstopController` (CARDS P5b); called by orch_api.
        """
        return await self.estop_controller.clear_estop()

    async def clear_error(self):
        """Clear errored UUIDs from the finished dict and signal the interrupt queue.

        Delegates to :class:`EstopController` (CARDS P5b); called by orch_api.
        """
        return await self.estop_controller.clear_error()

    async def clear_sequences(self):
        """Empty the sequence deque."""
        return await self.run_queues.clear_sequences()

    async def clear_experiments(self):
        """Empty the experiment deque."""
        return await self.run_queues.clear_experiments()

    async def clear_actions(self):
        """Empty the action deque."""
        return await self.run_queues.clear_actions()

    def _prep_sequence_meta(self, sequence: Sequence) -> None:
        """Populate uuid/codehash/codepath/funcname metadata on ``sequence`` in place."""
        return self.run_queues._prep_sequence_meta(sequence)

    def _ensure_run_id(self) -> UUID:
        """Return the run_id to stamp on a sequence entering the queue.

        Empty/just-cleared queue -> fresh run_id; non-empty -> reuse the
        in-flight ``active_run_id`` (back-to-back sharing).
        """
        return self.run_queues._ensure_run_id()

    def _resolve_active_run_id(self, sequence: Sequence) -> None:
        """At dequeue, sync ``active_run_id`` with the active sequence's run_id."""
        return self.run_queues._resolve_active_run_id(sequence)

    async def add_sequence(self, sequence: Sequence) -> UUID:
        """Append ``sequence`` to the sequence deque, populating its metadata and run_id.

        Returns:
            The UUID of the added sequence.
        """
        return await self.run_queues.add_sequence(sequence)

    async def add_split_sequences(self, sequence: Sequence):
        """Split ``sequence`` along the configured params and enqueue each sub-sequence.

        Args:
            sequence: Source sequence whose parameters trigger splitting.

        Returns:
            List of sub-sequence UUIDs, or the result of :meth:`add_sequence`
            if no split parameter applied.
        """
        return await self.run_queues.add_split_sequences(sequence)

    async def prepend_sequences(self, sequences: List[Sequence]) -> List[UUID]:
        """Insert ``sequences`` at the front of the queue, preserving their order.

        Stamps uuid/codehash/run_id like :meth:`add_sequence`. Reuses the
        in-flight run_id when the queue is non-empty, else mints a fresh one.
        An empty list is a no-op (returns ``[]`` without touching run_id).

        Returns:
            The UUIDs of the prepended sequences, in buffer order.
        """
        return await self.run_queues.prepend_sequences(sequences)

    def _rebuild_sequence_dq(self, seqs) -> None:
        """Replace the sequence deque contents with ``seqs`` (re-compresses each)."""
        return self.run_queues._rebuild_sequence_dq(seqs)

    async def move_sequence(self, from_idx: int, to_idx: int) -> None:
        """Move the queued sequence at ``from_idx`` to ``to_idx`` (no-op if out of range)."""
        return await self.run_queues.move_sequence(from_idx, to_idx)

    async def remove_sequence(self, idx: int) -> None:
        """Remove the queued sequence at ``idx`` (no-op if out of range)."""
        return await self.run_queues.remove_sequence(idx)

    def _rebuild_experiment_dq(self, exps) -> None:
        """Replace the experiment deque contents with ``exps`` (re-compresses each)."""
        return self.run_queues._rebuild_experiment_dq(exps)

    async def move_experiment(self, from_idx: int, to_idx: int) -> None:
        """Move the queued experiment at ``from_idx`` to ``to_idx`` (no-op if out of range)."""
        return await self.run_queues.move_experiment(from_idx, to_idx)

    async def remove_experiment(
        self, idx: Optional[int] = None, by_uuid: Optional[UUID] = None
    ) -> None:
        """Remove the queued experiment at ``idx`` (or matching ``by_uuid``); no-op if out of range."""
        return await self.run_queues.remove_experiment(idx=idx, by_uuid=by_uuid)

    def _rebuild_action_dq(self, acts) -> None:
        """Replace the action deque contents with ``acts`` (re-compresses each)."""
        return self.run_queues._rebuild_action_dq(acts)

    async def move_action(self, from_idx: int, to_idx: int) -> None:
        """Move the queued action at ``from_idx`` to ``to_idx`` (no-op if out of range)."""
        return await self.run_queues.move_action(from_idx, to_idx)

    async def remove_action(self, idx: int) -> None:
        """Remove the queued action at ``idx`` (no-op if out of range)."""
        return await self.run_queues.remove_action(idx)

    async def add_experiment(
        self,
        seq: Sequence,
        experimentmodel: Experiment | ExperimentModel | ShortExperimentModel,
        prepend: bool = False,
        at_index: Optional[int] = None,
    ) -> UUID:
        """Enqueue an experiment derived from ``experimentmodel`` and attached to ``seq``.

        Args:
            seq: Sequence whose fields are folded into the new experiment.
            experimentmodel: Experiment definition to enqueue.
            prepend: If True, push to the front of the deque.
            at_index: Optional index to insert at; takes precedence over ``prepend``.

        Returns:
            The UUID of the enqueued experiment.
        """
        return await self.run_queues.add_experiment(
            seq, experimentmodel, prepend=prepend, at_index=at_index
        )

    def list_sequences(self, limit=10) -> list:
        """Return at most ``limit`` sequence summaries from the sequence deque."""
        return self.run_queues.list_sequences(limit=limit)

    def list_experiments(self, limit=10) -> list:
        """Return at most ``limit`` experiment summaries from the experiment deque."""
        return self.run_queues.list_experiments(limit=limit)

    def list_all_experiments(self) -> list:
        """Return ``(index, experiment_name)`` tuples for every queued experiment."""
        return self.run_queues.list_all_experiments()

    def drop_experiment_inds(self, inds: List[int]) -> list:
        """Remove the queued experiments at ``inds`` and return :meth:`list_all_experiments`."""
        return self.run_queues.drop_experiment_inds(inds)

    def get_experiment(self, last=False) -> Experiment:
        """Return the active (or, if ``last`` is True, most recent) experiment summary.

        Returns an empty dict when no experiment is available.
        """
        return self.run_queues.get_experiment(last=last)

    def get_sequence(self, last=False) -> Sequence:
        """Return the active (or, if ``last`` is True, most recent) sequence summary.

        Returns an empty dict when no sequence is available.
        """
        return self.run_queues.get_sequence(last=last)

    def list_active_actions(self) -> list:
        """Return the status model entries for every currently active action."""
        return self.run_queues.list_active_actions()

    def list_actions(self, limit=10) -> list:
        """Return at most ``limit`` action summaries from the action deque."""
        return self.run_queues.list_actions(limit=limit)

    def supplement_error_action(self, check_uuid: UUID, sup_action: Action):
        """Retry an errored action by appending ``sup_action`` to the front of ``action_dq``.

        Args:
            check_uuid: UUID of the previously errored action.
            sup_action: Replacement action whose order/retry counters get adjusted.
        """
        return self.run_queues.supplement_error_action(check_uuid, sup_action)

    def replace_action(
        self,
        sup_action: Action,
        by_index: Optional[int] = None,
        by_uuid: Optional[UUID] = None,
        by_action_order: Optional[int] = None,
    ):
        """Replace a queued action selected by index, UUID, or action order with ``sup_action``."""
        return self.run_queues.replace_action(
            sup_action,
            by_index=by_index,
            by_uuid=by_uuid,
            by_action_order=by_action_order,
        )

    def append_action(self, sup_action: Action):
        """Append ``sup_action`` to ``action_dq`` and assign it the next action order."""
        return self.run_queues.append_action(sup_action)

    async def finish_active_sequence(self):
        """Finalize the active sequence: mark finished, run postprocessors, persist, and roll over."""
        return await self.run_lifecycle.finish_active_sequence()

    async def finish_active_experiment(self):
        """Finalize the active experiment after waiting for actions and stopping non-blockers."""
        return await self.run_lifecycle.finish_active_experiment()

    async def write_active_experiment_exp(self):
        """Persist the active experiment to disk after snapshotting initial global params."""
        return await self.run_lifecycle.write_active_experiment_exp()

    async def write_active_sequence_seq(self):
        """Persist the active sequence to disk after snapshotting initial global params."""
        return await self.run_lifecycle.write_active_sequence_seq()

    async def shutdown(self):
        """Detach subscribers, cancel orchestrator tasks, and export queues if non-empty."""
        await self.detach_subscribers()
        self.status_logger.cancel()
        self.status_subscriber.cancel()
        if any(
            [
                len(x) > 0
                for x in (
                    self.sequence_dq,
                    self.experiment_dq,
                    self.action_dq,
                )
            ]
        ):
            export_path = self.export_queues(timestamp_pck=False)
            LOGGER.info(f"Orch queues are not empty, exported queues to {export_path}")

    def start_wait(self, active: Active):
        """Schedule :meth:`dispatch_wait_task` for ``active`` as a background task."""
        return self.run_lifecycle.start_wait(active)

    async def dispatch_wait_task(self, active: Active, print_every_secs: int = 5):
        """Run a long wait action off the HTTP handler so the client doesn't time out.

        Args:
            active: ``Active`` carrying the ``waittime`` parameter.
            print_every_secs: Interval between progress log messages.

        Returns:
            The finished action returned by ``active.finish()``.
        """
        return await self.run_lifecycle.dispatch_wait_task(
            active, print_every_secs=print_every_secs
        )

    async def active_action_monitor(self):
        """Heartbeat loop that stops the orchestrator if any active action endpoint goes offline."""
        return await self.server_monitor.active_action_monitor()

    async def ping_action_servers(self) -> dict:
        """Query every action server for its endpoint and driver status.

        Returns:
            Mapping of ``server_key`` to ``(status_str, driver_status)`` where
            ``status_str`` is ``"idle"``, ``"busy [<endpoints>]"`` or
            ``"unreachable"``.
        """
        return await self.server_monitor.ping_action_servers()

    async def action_server_monitor(self):
        """Heartbeat loop that refreshes ``status_summary`` via :meth:`ping_action_servers`."""
        return await self.server_monitor.action_server_monitor()

    def export_queues(self, timestamp_pck: bool = False) -> str:
        """Pickle the deques, active/last sequence and experiment, and histories under ``STATES/``.

        Args:
            timestamp_pck: When True, embed a timestamp in the pickle filename.

        Returns:
            Filesystem path of the written pickle file.
        """
        return self.queue_persister.export_queues(timestamp_pck=timestamp_pck)

    def import_queues(self, pck_path: Optional[str] = None) -> str:
        """Restore deques/active/last state from a previously exported pickle.

        Args:
            pck_path: Optional explicit path to the pickle; defaults to
                ``<root>/STATES/queues.pck``.

        Returns:
            The path that was loaded (or attempted).
        """
        return self.queue_persister.import_queues(pck_path)
