"""HELAO orchestrator runtime.

Implements the :class:`Orch` service that extends :class:`Base` with the
sequence/experiment/action deques, the dispatch loop that drives them, the
global status model used by the Bokeh operator UI, and the heartbeat /
status-monitor tasks that keep the orchestrator aware of every action server
in the world configuration.
"""

__all__ = ["Orch"]

import os
from helao.helpers import helao_logging as logging

import asyncio
import sys
from copy import deepcopy
from typing import List
from uuid import UUID
import re
import traceback
import inspect
from typing import Optional

import time
from collections import defaultdict

import colorama
from fastapi import WebSocket

from helao.core.models.action_start_condition import ActionStartCondition
from helao.core.models.experiment import ExperimentModel, ShortExperimentModel
from helao.core.models.hlostatus import HloStatus
from helao.core.models.status_transitions import guarded_append, guarded_replace
from helao.core.models.server import ActionServerModel, GlobalStatusModel
from helao.core.models.orchstatus import OrchStatus, LoopStatus, LoopIntent
from helao.core.models.run_dir import RunDir
from helao.core.error import ErrorCodes

from helao.helpers.server_api import HelaoFastAPI
from helao.helpers.time_utils import set_time
from helao.helpers.import_autolibs import import_autolibs
from helao.helpers.dispatcher import (
    async_private_dispatcher,
    async_action_dispatcher,
)
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.yml_tools import move_dir
from helao.helpers.premodels import Sequence, Experiment, Action
from helao.core.servers.base import Base, Active
from helao.core.servers.orch_global_params import (
    apply_from_globals,
    collect_to_globals,
)
from helao.core.servers.orch_persist import QueuePersister
from helao.core.servers.orch_monitor import ServerMonitor
from helao.core.servers.orch_status_sync import StatusIngester
from helao.core.servers.orch_queues import RunQueues
from helao.core.servers import orch_unpack
from helao.core.servers.orch_unpack import PLATE_API
from helao.core.servers.orch_lifecycle import RunLifecycle
from helao.helpers.time_utils import gen_uuid
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
        """
        self.queue_persister = QueuePersister(self)
        self.server_monitor = ServerMonitor(self)
        self.status_ingester = StatusIngester(self)
        self.run_queues = RunQueues(self)
        self.run_lifecycle = RunLifecycle(self)

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

    # def endpoint_queues_init(self):
    #     """
    #     Initializes endpoint queues for the server.

    #     This method iterates over the list of fast URLs and checks if the path
    #     starts with the server's name. For each matching URL, it creates a new
    #     queue and assigns it to the endpoint_queues dictionary with the URL's
    #     name as the key.
    #     """
    #     for urld in self.fast_urls:
    #         if urld.get("path", "").startswith(f"/{self.server.server_name}/"):
    #             self.endpoint_queues[urld["name"]] = zdeque([])

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
        return orch_unpack.unpack_sequence(sequence_name, sequence_params, self.sequence_lib)

    def get_sequence_codehash(self, sequence_name: str) -> UUID:
        """Return the cached code hash for the named sequence library entry."""
        return orch_unpack.get_sequence_codehash(sequence_name, self.sequence_codehash_lib)

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

        Returns:
            ``ErrorCodes.none`` on success, or a non-zero code if the sequence
            could not be started (for example because plate verification failed).
        """
        if self.sequence_dq:
            LOGGER.info("getting new sequence from sequence_dq")
            self.active_sequence = self.sequence_dq.popleft()

            LOGGER.info(f"new active sequence is {self.active_sequence.sequence_name}")
            await self.put_lbuf(
                {
                    self.active_sequence.sequence_uuid: {
                        "sequence_name": self.active_sequence.sequence_name,
                        "status": HloStatus.active.value,
                    }
                }
            )
            self.active_sequence.dummy = self.world_cfg.get("dummy", False)
            self.active_sequence.simulation = self.world_cfg.get("simulation", False)
            if self.active_sequence.run_type is None:
                self.active_sequence.run_type = self.run_type
            self.active_sequence.orchestrator = self.server
            self.active_sequence.init_seq(time_offset=self.ntp_offset)
            self.register_obj_uuid(
                self.active_sequence.sequence_uuid,
                {
                    "sequence_name": self.active_sequence.sequence_name,
                    "sequence_params": self.active_sequence.sequence_params,
                    "sequence_timestamp": f"{self.active_sequence.sequence_timestamp: %m-%d %H:%M:%S}",
                    "sequence_status": HloStatus.active.value,
                    "sequence_label": self.active_sequence.sequence_label,
                    "campaign_name": (
                        self.active_sequence.campaign_name
                        if self.active_sequence.campaign_name
                        else None
                    ),
                },
                "sequence",
            )
            LOGGER.debug(
                "registered sequence uuid: " + str(self.active_sequence.sequence_uuid)
            )

            # from global params
            apply_from_globals(
                self.active_sequence.sequence_params,
                self.active_sequence.from_global_seq_params,
                self.global_params,
                logger_ctx="sequence",
            )

            # attach run_id (derive active_run_id from the dequeued sequence)
            self._resolve_active_run_id(self.active_sequence)

            # if planned_experiments is empty, unpack sequence,
            # otherwise operator already populated planned_experiments
            if self.active_sequence.sequence_name in self.sequence_lib:
                planned_experiments = self.unpack_sequence(
                    self.active_sequence.sequence_name,
                    self.active_sequence.sequence_params,
                )
                if not self.active_sequence.planned_experiments:
                    self.active_sequence.planned_experiments = planned_experiments
                elif len(self.active_sequence.planned_experiments) >= len(
                    planned_experiments
                ):
                    new_planned_experiments = []
                    for exp_model in self.active_sequence.planned_experiments:
                        if not planned_experiments:
                            new_planned_experiments.append(exp_model)
                        else:
                            exp = planned_experiments.pop(0)
                            if exp.experiment_name == exp_model.experiment_name:
                                for k, v in vars(exp_model).items():
                                    setattr(exp, k, v)
                                new_planned_experiments.append(exp)
                            else:
                                break
                    if len(self.active_sequence.planned_experiments) == len(
                        new_planned_experiments
                    ):
                        self.active_sequence.planned_experiments = (
                            new_planned_experiments
                        )

            self.seq_model = self.active_sequence.get_seq()
            await self.write_seq(self.active_sequence)

            if self.use_db:
                try:
                    meta_s3_key = f"sequence/{self.seq_model.sequence_uuid}.json"
                    LOGGER.info(
                        f"uploading initial active sequence json to s3 ({meta_s3_key})"
                    )
                    await self.syncer.to_s3(
                        self.seq_model.clean_dict(strip_private=True), meta_s3_key
                    )
                except Exception as e:
                    LOGGER.error(
                        f"Error uploading initial active sequence json to s3: {e}"
                    )

            if self.verify_plates and PLATE_API.has_access:
                plate_found = self.verify_plate_in_params(
                    self.active_sequence.sequence_params
                )
                if not plate_found:
                    stop_message = "sequence contains a plate_id parameter but plate_id could not be found"
                    self.current_stop_message = stop_message
                    LOGGER.warning(stop_message)
                    await self.stop()
                    self.globalstatusmodel.loop_state = LoopStatus.stopped
                    await self.intend_none()
                    return ErrorCodes.not_available

            self.aloop.create_task(self.seq_unpacker())
            LOGGER.info("waiting for experiment queue to populate")
            while len(self.experiment_dq) == 0:
                await asyncio.sleep(0.1)

        else:
            LOGGER.info("sequence queue is empty, cannot start orch loop")

            self.globalstatusmodel.loop_state = LoopStatus.stopped
            await self.intend_none()

        return ErrorCodes.none

    async def loop_task_dispatch_experiment(self) -> ErrorCodes:
        """Pop the next experiment, expand its planned actions, and push them onto ``action_dq``.

        Coordinator over the extracted staging/expansion/upload/plate-gate
        helpers. Returns ``ErrorCodes.none`` on success, or a non-zero code if
        the experiment could not be processed (for example because plate
        verification failed).
        """

        # check again if experiment_dq is empty
        if not self.experiment_dq:
            LOGGER.info("experiment_dq is empty, cannot dispatch experiments")
            await self.intend_none()
            return ErrorCodes.none

        await self._stage_experiment()

        rc, staged_acts = await self._expand_experiment_actions()
        if rc is not None:
            return rc

        await self._upload_exp_meta_s3()

        rc = await self._verify_experiment_plate()
        if rc is not None:
            return rc

        LOGGER.info("adding unpacked actions to action_dq")
        for act in staged_acts:
            self.action_dq.append(act)

        return ErrorCodes.none

    async def _stage_experiment(self) -> None:
        """Pop the next experiment, make it active, and register it."""
        LOGGER.info("action_dq is empty, getting new actions")
        # wait for all actions in last/active experiment to finish
        # LOGGER.info("finishing last active experiment first")
        # await self.finish_active_experiment()

        # LOGGER.info("getting new experiment to fill action_dq")
        # generate uids when populating,
        # generate timestamp when acquring
        self.active_experiment = self.experiment_dq.popleft()

        self.active_experiment.orch_key = self.orch_key
        self.active_experiment.orch_host = self.orch_host
        self.active_experiment.orch_port = self.orch_port
        self.active_experiment.sequence_uuid = self.active_sequence.sequence_uuid
        if self.active_sequence.campaign_name:
            self.active_experiment.campaign_name = self.active_sequence.campaign_name
            self.active_experiment.campaign_uuid = self.active_sequence.campaign_uuid
        self.active_seq_exp_counter += 1

        # LOGGER.info("copying global vars to experiment")
        # copy requested global param to experiment params
        apply_from_globals(
            self.active_experiment.experiment_params,
            self.active_experiment.from_global_exp_params,
            self.global_params,
            logger_ctx="experiment --",
        )

        LOGGER.info(
            f"new active experiment is {self.active_experiment.experiment_name}"
        )
        await self.put_lbuf(
            {
                self.active_experiment.experiment_uuid: {
                    "experiment_name": self.active_experiment.experiment_name,
                    "status": HloStatus.active.value,
                }
            }
        )
        self.active_experiment.dummy = self.world_cfg.get("dummy", False)
        self.active_experiment.simulation = self.world_cfg.get("simulation", False)
        if self.active_experiment.run_type is None:
            self.active_experiment.run_type = self.run_type
        self.active_experiment.orchestrator = self.server
        self.active_experiment.init_exp(time_offset=self.ntp_offset)
        self.register_obj_uuid(
            self.active_experiment.experiment_uuid,
            {
                "experiment_name": self.active_experiment.experiment_name,
                "experiment_params": self.active_experiment.experiment_params,
                "experiment_timestamp": f"{self.active_experiment.experiment_timestamp: %m-%d %H:%M:%S}",
                "experiment_status": HloStatus.active.value,
                "sequence_label": self.active_sequence.sequence_label,
                "campaign_name": (
                    self.active_sequence.campaign_name
                    if self.active_sequence.campaign_name
                    else None
                ),
            },
            "experiment",
        )
        LOGGER.debug(
            "registered experiment uuid: " + str(self.active_experiment.experiment_uuid)
        )

        # attach run_id
        if self.active_run_id is not None:
            self.active_experiment.run_id = self.active_run_id

        self.globalstatusmodel.new_experiment(
            exp_uuid=self.active_experiment.experiment_uuid
        )

    async def _expand_experiment_actions(
        self,
    ) -> tuple[Optional[ErrorCodes], Optional[list]]:
        """Expand the active experiment into staged actions with process bookkeeping.

        Returns ``(ErrorCodes.none, None)`` when the experiment produced no
        actions (early exit) and ``(None, staged_acts)`` otherwise.
        """
        # additional experiment params should be stored
        # in experiment.experiment_params
        # self.print_message(
        #     f"unpacking actions for {self.active_experiment.experiment_name}"
        # )
        exp_func = self.experiment_lib[self.active_experiment.experiment_name]
        exp_func_args = inspect.getfullargspec(exp_func).args
        supplied_params = {
            k: v
            for k, v in self.active_experiment.experiment_params.items()
            if k in exp_func_args
        }
        exp_return = exp_func(self.active_experiment, **supplied_params)

        unpacked_acts = None
        if isinstance(exp_return, list):
            unpacked_acts = exp_return
        elif isinstance(exp_return, Experiment):
            self.active_experiment = exp_return
            unpacked_acts = self.active_experiment.planned_actions

        self.active_experiment.experiment_codehash = self.experiment_codehash_lib[
            self.active_experiment.experiment_name
        ]
        self.active_experiment.experiment_codepath = self.experiment_codepath_lib[
            self.active_experiment.experiment_name
        ]
        self.active_experiment.experiment_funcname = self.experiment_lib[
            self.active_experiment.experiment_name
        ].__name__
        if unpacked_acts is None:
            LOGGER.error("no actions in experiment")
            self.action_dq = zdeque([])
            return ErrorCodes.none, None

        process_order_groups = defaultdict(list)
        process_count = 0
        init_process_uuids = [gen_uuid()]
        # LOGGER.info("setting action order")

        ## actions are not instantiated until experiment is unpacked
        staged_acts = []
        for i, act in enumerate(unpacked_acts):
            # init uuid now for tracking later
            act.action_uuid = gen_uuid()
            act.action_order = int(i)
            act.orch_key = self.orch_key
            act.orch_host = self.orch_host
            act.orch_port = self.orch_port
            # actual order should be the same at the beginning
            # will be incremented as necessary
            act.orch_submit_order = int(i)
            if act.process_contrib:
                process_order_groups[process_count].append(i)
                act.process_uuid = init_process_uuids[process_count]
            if act.process_finish:
                process_count += 1
                init_process_uuids.append(gen_uuid())
            if self.active_experiment.data_request_id is not None:
                act.data_request_id = self.active_experiment.data_request_id
            actserv_cfg = self.world_cfg["servers"][act.action_server.server_name]
            act.action_server.hostname = actserv_cfg["host"]
            act.action_server.port = actserv_cfg["port"]
            act.action_server.machine_name = self.server.machine_name
            act.campaign_name = self.active_experiment.campaign_name
            act.campaign_uuid = self.active_experiment.campaign_uuid
            staged_acts.append(act)
        if process_order_groups:
            self.active_experiment.process_order_groups = process_order_groups
            process_list = init_process_uuids[: len(process_order_groups)]
            self.active_experiment.process_list = process_list

        LOGGER.info(f"got: {staged_acts}")
        LOGGER.info(f"optional params: {self.active_experiment.experiment_params}")

        return None, staged_acts

    async def _upload_exp_meta_s3(self) -> None:
        """Write the temporary experiment and upload its meta json to S3."""
        # write a temporary exp
        self.exp_model = self.active_experiment.get_exp()
        await self.write_active_experiment_exp()
        if self.use_db:
            try:
                meta_s3_key = f"experiment/{self.exp_model.experiment_uuid}.json"
                LOGGER.info(
                    f"uploading initial active experiment json to s3 ({meta_s3_key})"
                )
                await self.syncer.to_s3(
                    self.exp_model.clean_dict(strip_private=True), meta_s3_key
                )
            except Exception as e:
                LOGGER.error(
                    f"Error uploading initial active experiment json to s3: {e}"
                )

    async def _verify_experiment_plate(self) -> Optional[ErrorCodes]:
        """Gate on plate verification; returns ``ErrorCodes.not_available`` on failure."""
        if self.verify_plates and PLATE_API.has_access:
            plate_found = self.verify_plate_in_params(
                self.active_experiment.experiment_params
            )
            if not plate_found:
                stop_message = "experiment contains a plate_id parameter but plate_id could not be found"
                self.current_stop_message = stop_message
                LOGGER.warning(stop_message)
                await self.stop()
                self.globalstatusmodel.loop_state = LoopStatus.stopped
                await self.intend_none()
                return ErrorCodes.not_available

        return None

    async def loop_task_dispatch_action(self) -> ErrorCodes:
        """Dispatch the next action from ``action_dq`` honouring start conditions and loop intent.

        Coordinator over the extracted intent/start-condition/staging/dispatch
        helpers. Respects ``LoopIntent.stop``/``skip``/``estop``, waits according
        to the action's ``ActionStartCondition``, copies requested values into
        and out of ``global_params``, registers the dispatched action in the
        global status model, and pauses the orchestrator if dispatch fails.

        Returns:
            ``ErrorCodes`` summarising the dispatch outcome.
        """
        # check again if action_dq is empty
        if not self.action_dq:
            LOGGER.info("action_dq is empty, cannot dispatch actions")
            await self.intend_none()
            return ErrorCodes.none

        # LOGGER.info("actions in action_dq, processing them")
        if await self._apply_loop_intent_before_dispatch():
            return ErrorCodes.none

        # all action blocking is handled like preempt,
        # check Action requirements
        A = self.action_dq.popleft()

        rc = await self._wait_for_start_condition(A)
        if rc is not None:
            return rc

        self._stage_action_for_dispatch(A)

        rc, result_actiondict = await self._dispatch_action_locked(A)
        if rc is not None:
            return rc

        rc = await self._record_dispatch_result(A, result_actiondict)
        if rc is not None:
            return rc

        return ErrorCodes.none

    async def _apply_loop_intent_before_dispatch(self) -> bool:
        """Handle stop/skip/estop loop intent before any dispatch.

        Returns ``True`` when one of the intent branches was taken (the caller
        should short-circuit with ``ErrorCodes.none``), ``False`` otherwise.
        """
        if self.globalstatusmodel.loop_intent == LoopIntent.stop:
            LOGGER.info("stopping orchestrator")
            # monitor status of running action_dq, then end loop
            while self.globalstatusmodel.loop_state != LoopStatus.stopped:
                # wait for all orch actions to finish first
                await self.orch_wait_for_all_actions()
                if self.globalstatusmodel.orch_state == OrchStatus.idle:
                    await self.intend_none()
                    LOGGER.info("got stop")
                    self.globalstatusmodel.loop_state = LoopStatus.stopped
                    break
            return True

        elif self.globalstatusmodel.loop_intent == LoopIntent.skip:
            # clear action queue, forcing next experiment
            self.action_dq.clear()
            await self.intend_none()
            LOGGER.info("skipping to next experiment")
            return True
        elif self.globalstatusmodel.loop_intent == LoopIntent.estop:
            self.action_dq.clear()
            await self.intend_none()
            LOGGER.info("estopping")
            self.globalstatusmodel.loop_state = LoopStatus.estopped
            return True
        else:
            return False

    async def _wait_for_start_condition(self, A) -> Optional[ErrorCodes]:
        """Wait according to the action's ``ActionStartCondition``.

        Returns ``ErrorCodes.none`` if a wait loop is interrupted (early exit),
        ``None`` otherwise.
        """
        # see async_action_dispatcher for unpacking
        if A.start_condition == ActionStartCondition.no_wait:
            LOGGER.info("orch is dispatching an unconditional action")
        else:
            if A.start_condition == ActionStartCondition.wait_for_endpoint:
                LOGGER.info("orch is waiting for endpoint to become available")
                endpoint_free = self.globalstatusmodel.endpoint_free(
                    action_server=A.action_server, endpoint_name=A.action_name
                )
                while not endpoint_free:
                    if not await self.wait_for_interrupt():
                        return ErrorCodes.none
                    endpoint_free = self.globalstatusmodel.endpoint_free(
                        action_server=A.action_server, endpoint_name=A.action_name
                    )
            elif A.start_condition == ActionStartCondition.wait_for_server:
                LOGGER.info("orch is waiting for server to become available")
                server_free = self.globalstatusmodel.server_free(
                    action_server=A.action_server
                )
                while not server_free:
                    if not await self.wait_for_interrupt():
                        return ErrorCodes.none
                    server_free = self.globalstatusmodel.server_free(
                        action_server=A.action_server
                    )
            elif A.start_condition == ActionStartCondition.wait_for_orch:
                LOGGER.info("orch is waiting for wait action to end")
                wait_free = self.globalstatusmodel.endpoint_free(
                    action_server=A.orchestrator, endpoint_name="wait"
                )
                while not wait_free:
                    if not await self.wait_for_interrupt():
                        return ErrorCodes.none
                    wait_free = self.globalstatusmodel.endpoint_free(
                        action_server=A.orchestrator, endpoint_name="wait"
                    )
            elif A.start_condition == ActionStartCondition.wait_for_previous:
                LOGGER.info("orch is waiting for previous action to finish")
                previous_action_active = (
                    self.last_action_uuid
                    in self.globalstatusmodel.active_dict.keys()
                )
                while previous_action_active:
                    if not await self.wait_for_interrupt():
                        return ErrorCodes.none
                    previous_action_active = (
                        self.last_action_uuid
                        in self.globalstatusmodel.active_dict.keys()
                    )
            elif A.start_condition == ActionStartCondition.wait_for_all:
                await self.orch_wait_for_all_actions()

            else:  # unsupported value
                await self.orch_wait_for_all_actions()

        return None

    def _stage_action_for_dispatch(self, A) -> None:
        """Fold in globals, stamp run-id/submit-order, and init the action."""
        # LOGGER.info("copying global vars to action")
        # copy requested global param to action params
        apply_from_globals(
            A.action_params,
            A.from_global_act_params,
            self.global_params,
            logger_ctx="action",
        )

        # attach run_id
        if self.active_run_id is not None:
            A.run_id = self.active_run_id

        # actserv_exists, _ = await endpoints_available([A.url])
        # if not actserv_exists:
        #     stop_message = f"{A.url} is not available, orchestrator will stop. Rectify action server then resume orchestrator run."
        #     self.current_stop_message = stop_message
        #     LOGGER.warning(stop_message)
        #     await self.stop()
        #     LOGGER.alert(f"ORCH STOPPED ~ {stop_message}")
        #     self.action_dq.insert(0, A)
        #     await self.update_operator(True)
        #     return ErrorCodes.none

        LOGGER.info(
            f"dispatching action {A.action_name} on server {A.action_server.server_name}"
        )
        # keep running counter of dispatched actions
        A.orch_submit_order = self.globalstatusmodel.counter_dispatched_actions[
            self.active_experiment.experiment_uuid
        ]
        self.globalstatusmodel.counter_dispatched_actions[
            self.active_experiment.experiment_uuid
        ] += 1

        A.init_act(time_offset=self.ntp_offset)

    async def _dispatch_action_locked(
        self, A
    ) -> tuple[Optional[ErrorCodes], Optional[dict]]:
        """Run the ``aiolock`` dispatch critical section intact.

        Returns ``(ErrorCodes.none, None)`` on the failure→pause→requeue early
        exit and ``(None, result_actiondict)`` after a successful dispatch and
        self-registration.
        """
        result_actiondict = None
        async with self.aiolock:
            try:
                if (
                    self.globalstatusmodel.loop_intent == LoopIntent.estop
                    or self.globalstatusmodel.loop_state == LoopStatus.estopped
                ):
                    LOGGER.info("orchestrator estopped, not dispatching action")
                    error_code = ErrorCodes.estop
                else:
                    result_actiondict, error_code = await async_action_dispatcher(
                        self.world_cfg, A
                    )
            except Exception as e:
                LOGGER.info(f"Error while dispatching action {A.action_name}: {e}")
                error_code = ErrorCodes.http

            for cond, stop_message in [
                (
                    error_code != ErrorCodes.none,
                    f"Dispatching {A.action_name} did not return status 200. Pausing orch.",
                ),
                (
                    result_actiondict is None,
                    f"Dispatching {A.action_name} returned None object. Pausing orch.",
                ),
            ]:
                if cond:
                    self.current_stop_message = stop_message
                    LOGGER.warning(stop_message)
                    await self.stop()
                    LOGGER.info(f"Re-queuing {A.action_name}")
                    self.action_dq.insert(0, A)
                    return ErrorCodes.none, None

            # except asyncio.exceptions.TimeoutError:
            #     result_actiondict, error_code = await async_private_dispatcher(
            #         self.world_cfg,
            #         A.action_server.server_name,
            #         "resend_active",
            #         params_dict={},
            #         json_dict={"action_uuid": A.action_uuid},
            #     )

            result_uuid = result_actiondict["action_uuid"]
            self.last_action_uuid = result_uuid
            self.track_action_uuid(UUID(result_uuid))
            LOGGER.info(
                f"Action {A.action_name} dispatched with uuid: {result_uuid}"
            )
            self.put_lbuf_nowait(
                {result_uuid: {"action_name": A.action_name, "status": HloStatus.active.value}}
            )

            if not A.nonblocking:
                # orch gets back an active action dict, we can self-register the dispatched action in global status
                resmod = Action(**result_actiondict)
                srvname = resmod.action_server.server_name
                actname = resmod.action_name
                resuuid = resmod.action_uuid
                actstats = resmod.action_status
                srvkeys = self.globalstatusmodel.server_dict.keys()
                srvkey = [k for k in srvkeys if k[0] == srvname][0]
                if HloStatus.active in actstats:
                    self.globalstatusmodel.active_dict[resuuid] = resmod
                    self.globalstatusmodel.server_dict[srvkey].endpoints[
                        actname
                    ].active_dict[resuuid] = resmod
                else:  # orch got back a nonactive result
                    for actstat in actstats:
                        try:
                            if (
                                resuuid
                                in self.globalstatusmodel.nonactive_dict.get(
                                    actstat, {}
                                )
                            ):
                                break  # already in nonactive_dict

                            # need to populate nonactive and endpoint statuses
                            current_nonactive_status = (
                                self.globalstatusmodel.nonactive_dict.get(
                                    actstat, {}
                                )
                            )
                            current_nonactive_status.update({resuuid: resmod})
                            self.globalstatusmodel.nonactive_dict[actstat] = (
                                current_nonactive_status
                            )

                            current_endpoint_status = (
                                self.globalstatusmodel.server_dict[srvkey]
                                .endpoints[actname]
                                .nonactive_dict.get(actstat, {})
                            )
                            current_endpoint_status.update({resuuid: resmod})
                            self.globalstatusmodel.server_dict[srvkey].endpoints[
                                actname
                            ].nonactive_dict[actstat] = current_endpoint_status
                        except Exception:
                            LOGGER.info(
                                f"{actstat} not found in globalstatus.nonactive_dict",
                                exc_info=True,
                            )

        return None, result_actiondict

    async def _record_dispatch_result(self, A, result_actiondict) -> Optional[ErrorCodes]:
        """Register the dispatch result and fold returned globals back out.

        Returns ``ErrorCodes.critical_error`` if the returned model is invalid,
        the action's error code (after ``estop_loop``) if it errored, or ``None``
        on success.
        """
        try:
            result_action = Action(**result_actiondict)
            self.active_experiment.dispatched_actions.append(result_action)
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            LOGGER.error(
                f"returned result is not a valid Action BaseModel: {repr(e), tb,}"
            )
            return ErrorCodes.critical_error

        if result_action.error_code is not ErrorCodes.none:
            LOGGER.error(
                f"Action result for '{result_action.action_name}' on '{result_action.action_server.disp_name()}' has error code: {result_action.error_code}"
            )
            stop_reason = f"{result_action.action_name} on {result_action.action_server.disp_name()} returned an error"
            await self.estop_loop(stop_reason)
            return result_action.error_code

        # self.print_message(
        #     f"copying global vars {', '.join(result_action.to_global_params)} back to experiment"
        # )
        collect_to_globals(
            result_action,
            self.global_params,
            orch_key=self.orch_key,
            orch_host=self.orch_host,
            orch_port=self.orch_port,
        )

        # # this will recursively call the next no_wait action in queue, and return its error
        # if self.action_dq and not self.step_thru_actions:
        #     nextA = self.action_dq[0]
        #     if nextA.start_condition == ActionStartCondition.no_wait:
        #         error_code = await self.loop_task_dispatch_action()

        # if error_code is not ErrorCodes.none:
        #     return error_code

        return None

    async def dispatch_loop_task(self) -> bool:
        """Drive the main orchestrator loop until the queues are exhausted or it is stopped.

        Polls the action, experiment and sequence deques in priority order,
        dispatches the next available item, observes step-through flags and
        driver health, and finishes any still-active experiment/sequence at
        the end. Returns ``True`` on a clean exit and ``False`` on a raised
        exception (after triggering an E-STOP).
        """
        LOGGER.info("--- started operator orch ---")
        LOGGER.info(f"current orch status: {self.globalstatusmodel.orch_state}")
        # clause for resuming paused action list
        # LOGGER.info(f"current orch sequences: {list(self.sequence_dq)[:5]}... ({len(self.sequence_dq)})")
        # LOGGER.info(f"current orch descisions: {list(self.experiment_dq)[:5]}... ({len(self.experiment_dq)})")
        # LOGGER.info(f"current orch actions: {list(self.action_dq)[:5]}... ({len(self.action_dq)})")
        # LOGGER.info("--- resuming orch loop now ---")

        self.globalstatusmodel.loop_state = LoopStatus.started

        try:
            while self.globalstatusmodel.loop_state == LoopStatus.started and (
                self.action_dq or self.experiment_dq or self.sequence_dq
            ):
                error_code = ErrorCodes.unspecified
                LOGGER.info(
                    f"current content of action_dq: {[self.action_dq[i] for i in range(min(len(self.action_dq), 5))]}... ({len(self.action_dq)})"
                )
                LOGGER.info(
                    f"current content of experiment_dq: {[self.experiment_dq[i] for i in range(min(len(self.experiment_dq), 5))]}... ({len(self.experiment_dq)})"
                )
                LOGGER.info(
                    f"current content of sequence_dq: {[self.sequence_dq[i] for i in range(min(len(self.sequence_dq), 5))]}... ({len(self.sequence_dq)})"
                )
                # check driver states
                na_drivers = [
                    k for k, (_, v) in self.status_summary.items() if v == "unknown"
                ]
                if na_drivers:
                    na_driver_retries = 0
                    while na_driver_retries < 5 and na_drivers:
                        LOGGER.info(
                            f"unknown driver states: {', '.join(na_drivers)}, retrying in 5 seconds"
                        )
                        await asyncio.sleep(5)
                        na_drivers = [
                            k
                            for k, (_, v) in self.status_summary.items()
                            if v == "unknown"
                        ]
                        na_driver_retries += 1
                    if na_drivers:
                        self.current_stop_message = (
                            f"unknown driver states: {', '.join(na_drivers)}"
                        )
                        LOGGER.warning(
                            (f"unknown driver states: {', '.join(na_drivers)}")
                        )
                        await self.stop()

                if (
                    self.globalstatusmodel.loop_state == LoopStatus.estopped
                    or self.globalstatusmodel.loop_intent == LoopIntent.estop
                ):
                    await self.stop_loop()
                elif self.action_dq:
                    LOGGER.info("!!!checking conditions for next action")
                    error_code = await self.loop_task_dispatch_action()
                    while (
                        self.last_dispatched_action_uuid
                        not in self.action_history.keys()
                    ):
                        await asyncio.sleep(0.2)
                    if self.action_dq and self.step_thru_actions:
                        self.current_stop_message = "Step-thru actions is enabled, use 'Start Orch' to dispatch next action."
                        LOGGER.warning(
                            "Step-thru actions is enabled, use 'Start Orch' to dispatch next action."
                        )
                        await self.stop()
                    elif (
                        not self.action_dq
                        and self.experiment_dq
                        and self.step_thru_experiments
                    ):
                        self.current_stop_message = "Step-thru experiments is enabled, use 'Start Orch' to dispatch next experiment."
                        LOGGER.warning(
                            "Step-thru experiments is enabled, use 'Start Orch' to dispatch next experiment."
                        )
                        await self.stop()
                    elif (
                        not self.action_dq
                        and not self.experiment_dq
                        and self.sequence_dq
                        and self.step_thru_sequences
                    ):
                        self.current_stop_message = "Step-thru sequences is enabled, use 'Start Orch' to dispatch next sequence."
                        LOGGER.warning(
                            "Step-thru sequences is enabled, use 'Start Orch' to dispatch next sequence."
                        )
                        await self.stop()
                elif self.experiment_dq:
                    LOGGER.info(
                        "!!!waiting for all actions to finish before dispatching next experiment"
                    )
                    LOGGER.info("finishing last experiment")
                    await self.finish_active_experiment()
                    LOGGER.info("!!!dispatching next experiment")
                    error_code = await self.loop_task_dispatch_experiment()
                # if no acts and no exps, disptach next sequence
                elif self.sequence_dq:
                    LOGGER.info(
                        "!!!waiting for all actions to finish before dispatching next sequence"
                    )
                    LOGGER.info("finishing last sequence")
                    await self.finish_active_sequence()
                    LOGGER.info("!!!dispatching next sequence")
                    error_code = await self.loop_task_dispatch_sequence()
                else:
                    LOGGER.info("all queues are empty")
                    LOGGER.info("--- stopping operator orch ---")
                # check error responses from dispatching this loop iter
                if error_code is not ErrorCodes.none:
                    LOGGER.error(f"stopping orch with error code: {error_code}")
                    await self.intend_stop()

            # finish the last exp
            # this wait for all actions in active experiment
            # to finish and then updates the exp with the acts
            if (
                not self.action_dq and self.active_experiment is not None
            ):  # in case of interrupt, don't finish exp
                LOGGER.info("finishing final experiment")
                await self.finish_active_experiment()
            if (
                not self.experiment_dq
                and not self.action_dq
                and self.active_sequence is not None
            ):  # in case of interrupt, don't finish seq
                LOGGER.info("finishing final sequence")
                await self.finish_active_sequence()

            if self.globalstatusmodel.loop_state != OrchStatus.estopped:
                self.globalstatusmodel.loop_state = LoopStatus.stopped
            await self.intend_none()

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
                self.export_queues(timestamp_pck=True)

            return True

        # except asyncio.CancelledError:
        #     LOGGER.info("serious orch exception occurred")
        #     return False

        except Exception:
            LOGGER.error("serious orch exception occurred")
            LOGGER.error("ERROR: ", exc_info=True)
            await self.estop_loop()
            return False

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

        Args:
            reason: Free-form text appended to the stop message and alert.
        """
        reason_suffix = f"{' ' + reason if reason else ''}"
        LOGGER.info("estopping orch")

        # set globalstatusmodel.loop_state to estop
        self.globalstatusmodel.loop_state = LoopStatus.estopped
        self.active_run_id = None

        # force stop all running actions in the status dict (for this orch)
        await self.estop_actions(switch=False)  # don't latch actionserver model

        # reset loop intend
        await self.intend_none()

        # finalize + move the active experiment/sequence with estopped status so
        # the partial run is not stranded in RUNS_ACTIVE and can be synced
        try:
            await self.estop_finish_active()
        except Exception:
            LOGGER.error(
                "error finalizing estopped experiment/sequence", exc_info=True
            )

        self.current_stop_message = "E-STOP" + reason_suffix
        LOGGER.warning("E-STOP" + reason_suffix)
        LOGGER.alert("ORCH E-STOP")

    async def stop_loop(self):
        """Signal the dispatch loop to stop after the current iteration via :meth:`intend_stop`."""
        await self.intend_stop()

    async def estop_actions(self, switch: bool):
        """Signal every registered action server to emergency-stop (or release).

        Each server's ``/estop`` endpoint stops its executors and finalizes any
        in-flight actions with ``estopped`` status (moving them to
        ``RUNS_FINISHED`` via their normal lifecycle). No placeholder ``estop``
        action artifact is generated -- an idle server writes nothing, and estop
        is recorded purely through the ``*_status`` fields of the actions (and,
        orch-side, the experiment/sequence) that were actually running.

        Args:
            switch: ``True`` to latch the per-server estop flag, ``False`` to
                release it. Finalization of in-flight actions happens regardless;
                on release there are simply none left to finalize.
        """
        LOGGER.info("estopping all servers")

        for (
            action_server_key,
            actionservermodel,
        ) in self.globalstatusmodel.server_dict.items():
            # A minimal estop action -- the endpoint ignores the action payload
            # entirely now (it operates on whatever actions were already running),
            # so no experiment/sequence identity needs to be attached.
            A = Action(
                action_name="estop",
                action_server=actionservermodel.action_server.as_dict(),
                action_params={"switch": switch},
                start_condition=ActionStartCondition.no_wait,
            )
            LOGGER.info(
                f"Sending estop={switch} request to {actionservermodel.action_server.disp_name()}"
            )
            try:
                # pass switch as an explicit query/RPC param so it reliably
                # reaches the endpoint's `switch` parameter
                _ = await async_action_dispatcher(
                    self.world_cfg, A, params={"switch": switch}
                )
            except Exception as e:
                tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
                # no estop endpoint for this action server?
                LOGGER.error(
                    f"estop for {actionservermodel.action_server.disp_name()} failed with: {repr(e), tb,}"
                )

    async def estop_finish_active(self):
        """Finalize the active experiment and sequence with estopped status on e-stop.

        The clean finish path (:meth:`finish_active_experiment` /
        :meth:`finish_active_sequence`) waits for all actions and is never reached
        on e-stop, so the active experiment and sequence would otherwise stay
        stranded in ``RUNS_ACTIVE`` and never be enqueued for sync. This marks
        them ``estopped`` (leaving ``active`` swapped to ``finished`` so they read
        as terminal), persists the yml, and schedules a background promotion to
        ``RUNS_FINISHED`` so the syncer can ship the partial run.

        It does NOT wait for actions inline: the e-stop already halted them and
        each action server finalizes its own in-flight actions independently
        (they may live on other machines). The background promotion, however,
        does wait for co-located child directories to clear before moving -- see
        :meth:`_estop_promote`.
        """

        def _mark_estopped(status_list: list, owner: str):
            guarded_replace(
                status_list,
                HloStatus.active,
                HloStatus.finished,
                owner=owner,
            )
            if HloStatus.estopped not in status_list:
                guarded_append(status_list, HloStatus.estopped, owner=owner)

        exp_to_move = None
        seq_to_move = None

        if self.active_experiment is not None:
            _mark_estopped(self.active_experiment.experiment_status, owner="experiment_status")
            self.active_experiment.experiment_finished_timestamp = set_time(
                offset=self.ntp_offset
            )
            self.active_experiment.finished_global_params = {
                k: v for k, v in self.global_params.items() if k != "_fast_samples_in"
            }
            try:
                if self.active_sequence is not None:
                    self.active_sequence.dispatched_experiments.append(
                        deepcopy(self.active_experiment.get_exp())
                    )
                    await self.write_active_sequence_seq()
                await self.write_exp(self.active_experiment)
            except Exception:
                LOGGER.error("error writing estopped experiment", exc_info=True)
            self.last_experiment = deepcopy(self.active_experiment)
            exp_to_move = self.last_experiment
            self.active_experiment = None

        if self.active_sequence is not None:
            _mark_estopped(self.active_sequence.sequence_status, owner="sequence_status")
            self.active_sequence.sequence_finished_timestamp = set_time(
                offset=self.ntp_offset
            )
            try:
                await self.write_seq(self.active_sequence)
            except Exception:
                LOGGER.error("error writing estopped sequence", exc_info=True)
            self.last_sequence = deepcopy(self.active_sequence)
            seq_to_move = self.last_sequence
            self.active_sequence = None
            self.active_seq_exp_counter = 0
            self.globalstatusmodel.counter_dispatched_actions = {}

        # Promote in a background task, experiment before sequence, so the
        # sequence dir's child experiment dir is gone before the sequence moves.
        if exp_to_move is not None or seq_to_move is not None:
            self.aloop.create_task(
                self._estop_promote_all(exp_to_move, seq_to_move)
            )

    async def _estop_promote_all(self, exp_to_move, seq_to_move):
        """Promote an estopped experiment then sequence to RUNS_FINISHED, in order."""
        if exp_to_move is not None:
            await self._estop_promote(exp_to_move, "experiment")
        if seq_to_move is not None:
            await self._estop_promote(seq_to_move, "sequence")

    async def _estop_promote(self, hobj, kind: str, max_wait: int = 30) -> bool:
        """Move an estopped exp/seq to RUNS_FINISHED once its child dirs have cleared.

        :func:`move_dir` promotes only an exp/seq's *top-level* files and then
        ``rmtree``s the whole directory, so moving while a co-located child
        action is still finalizing in ``RUNS_ACTIVE`` would delete that action's
        data. We wait (bounded) for child subdirectories to be vacated by the
        (possibly co-located) action servers; if they don't clear, we leave the
        record in ``RUNS_ACTIVE`` (data preserved) rather than destroy in-flight
        children -- ``finish_pending`` can promote it later. For remote action
        servers there are no local child dirs, so this returns immediately.

        Returns:
            True if the record was moved, False if left in place.
        """
        save_dir = str(self.helaodirs.save_root)
        subdir = (
            hobj.get_experiment_dir()
            if kind == "experiment"
            else hobj.get_sequence_dir()
        )
        ydir = os.path.normpath(os.path.join(save_dir, subdir))

        def _child_dirs():
            if not os.path.isdir(ydir):
                return []
            return [e.path for e in os.scandir(ydir) if e.is_dir()]

        waited = 0
        while _child_dirs() and waited < max_wait:
            await asyncio.sleep(1)
            waited += 1
        remaining = _child_dirs()
        if remaining:
            LOGGER.warning(
                f"estop: {kind} {ydir} still has {len(remaining)} child dir(s) in "
                f"RUNS_ACTIVE after {max_wait}s; leaving it in place (data "
                f"preserved) to avoid deleting in-flight child actions. Run "
                f"finish_pending once children clear to sync it."
            )
            return False
        try:
            await move_dir(hobj, base=self)
            return True
        except Exception:
            LOGGER.error(f"error moving estopped {kind} to RUNS_FINISHED", exc_info=True)
            return False

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
        """Clear estopped UUIDs, release the estop on every action server, and resume to ``stopped``."""
        # which were estopped first
        LOGGER.info("clearing estopped uuids")
        self.globalstatusmodel.clear_in_finished(hlostatus=HloStatus.estopped)
        # release estop for all action servers
        await self.estop_actions(switch=False)
        # set orch status from estop back to stopped
        self.globalstatusmodel.loop_state = LoopStatus.stopped
        await self.interrupt_q.put("cleared_estop")

    async def clear_error(self):
        """Clear errored UUIDs from the finished dict and signal the interrupt queue."""
        # currently only resets the error dict
        LOGGER.info("clearing errored uuids")
        self.globalstatusmodel.clear_in_finished(hlostatus=HloStatus.errored)
        await self.interrupt_q.put("cleared_errored")

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
            LOGGER.info(
                f"Orch queues are not empty, exported queues to {export_path}"
            )

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
