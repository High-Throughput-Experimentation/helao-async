__all__ = ["Orch"]

import pickle
import os
from datetime import datetime
from helao.helpers import helao_logging as logging

if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER

import asyncio
import sys
from copy import deepcopy
from typing import List
from uuid import UUID
import json
import traceback
import inspect
from typing import Optional

import time
from functools import partial
from collections import defaultdict

import aiohttp
import colorama
from fastapi import WebSocket
from bokeh.server.server import Server

from helao.core.models.action_start_condition import ActionStartCondition
from helao.core.models.hlostatus import HloStatus
from helao.core.models.server import ActionServerModel, GlobalStatusModel
from helao.core.models.orchstatus import OrchStatus, LoopStatus, LoopIntent
from helao.core.error import ErrorCodes

from helao.servers.operator.bokeh_operator import BokehOperator
from helao.servers.vis import HelaoVis
from helao.helpers.server_api import HelaoFastAPI
from helao.helpers.import_experiments import import_experiments
from helao.helpers.import_sequences import import_sequences
from helao.helpers.dispatcher import (
    async_private_dispatcher,
    async_action_dispatcher,
    endpoints_available,
)
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.yml_finisher import move_dir
from helao.helpers.premodels import Sequence, Experiment, Action
from helao.servers.base import Base, Active
from helao.helpers.gen_uuid import gen_uuid
from helao.helpers.zdeque import zdeque
from helao.helpers.legacy_api import HTELegacyAPI
from helao.drivers.data.sync_driver import HelaoSyncer

# ANSI color codes converted to the Windows versions
# strip colors if stdout is redirected
colorama.init(strip=not sys.stdout.isatty())


LEGACY_API = HTELegacyAPI()


class Orch(Base):
    """
    Orch class is responsible for orchestrating sequences, experiments, and actions in a distributed system. It manages the lifecycle of these entities, handles exceptions, and communicates with various servers to dispatch and monitor actions.

    Attributes:
        experiment_lib (dict): Library of available experiments.
        experiment_codehash_lib (dict): Library of experiment code hashes.
        sequence_lib (dict): Library of available sequences.
        sequence_codehash_lib (dict): Library of sequence code hashes.
        use_db (bool): Flag indicating if a database is used.
        syncer (HelaoSyncer): Syncer object for database synchronization.
        sequence_dq (zdeque): Deque for sequences.
        experiment_dq (zdeque): Deque for experiments.
        action_dq (zdeque): Deque for actions.
        dispatch_buffer (list): Buffer for dispatching actions.
        nonblocking (list): List of non-blocking actions.
        last_dispatched_action_uuid (UUID): UUID of the last dispatched action.
        last_50_action_uuids (list): List of the last 50 action UUIDs.
        last_action_uuid (str): UUID of the last action.
        last_interrupt (float): Timestamp of the last interrupt.
        active_experiment (Experiment): Currently active experiment.
        last_experiment (Experiment): Last executed experiment.
        active_sequence (Sequence): Currently active sequence.
        active_seq_exp_counter (int): Counter for active sequence experiments.
        last_sequence (Sequence): Last executed sequence.
        bokehapp (Server): Bokeh server instance.
        orch_op (BokehOperator): Bokeh operator instance.
        op_enabled (bool): Flag indicating if the operator is enabled.
        heartbeat_interval (int): Interval for heartbeat monitoring.
        globalstatusmodel (GlobalStatusModel): Global status model.
        interrupt_q (asyncio.Queue): Queue for interrupts.
        incoming_status (asyncio.Queue): Queue for incoming statuses.
        incoming (GlobalStatusModel): Incoming status model.
        init_success (bool): Flag indicating if initialization was successful.
        loop_task (asyncio.Task): Task for the dispatch loop.
        wait_task (asyncio.Task): Task for waiting.
        current_wait_ts (float): Timestamp of the current wait.
        last_wait_ts (float): Timestamp of the last wait.
        globstat_q (MultisubscriberQueue): Queue for global status.
        globstat_clients (set): Set of global status clients.
        current_stop_message (str): Current stop message.
        step_thru_actions (bool): Flag for stepping through actions.
        step_thru_experiments (bool): Flag for stepping through experiments.
        step_thru_sequences (bool): Flag for stepping through sequences.
        status_summary (dict): Summary of statuses.
        global_params (dict): Global parameters.

    Methods:
        exception_handler(loop, context): Handles exceptions in the event loop.
        myinit(): Initializes the orchestrator.
        endpoint_queues_init(): Initializes endpoint queues.
        register_action_uuid(action_uuid): Registers an action UUID.
        track_action_uuid(action_uuid): Tracks an action UUID.
        start_operator(): Starts the Bokeh operator.
        makeBokehApp(doc, orch): Creates a Bokeh application.
        wait_for_interrupt(): Waits for an interrupt.
        subscribe_all(retry_limit): Subscribes to all FastAPI servers.
        update_nonblocking(actionmodel, server_host, server_port): Updates non-blocking actions.
        clear_nonblocking(): Clears non-blocking actions.
        update_status(actionservermodel): Updates the status.
        ws_globstat(websocket): Subscribes to global status queue and sends messages to websocket client.
        globstat_broadcast_task(): Consumes the global status queue.
        unpack_sequence(sequence_name, sequence_params): Unpacks a sequence.
        get_sequence_codehash(sequence_name): Gets the code hash of a sequence.
        seq_unpacker(): Unpacks the sequence.
        loop_task_dispatch_sequence(): Dispatches the sequence.
        loop_task_dispatch_experiment(): Dispatches the experiment.
        loop_task_dispatch_action(): Dispatches the action.
        dispatch_loop_task(): Parses experiment and action queues and dispatches actions.
        orch_wait_for_all_actions(): Waits for all actions to finish.
        start(): Begins experimenting with experiment and action queues.
        start_loop(): Starts the orchestrator loop.
        estop_loop(reason): Emergency stops the orchestrator loop.
        stop_loop(): Stops the orchestrator loop.
        estop_actions(switch): Emergency stops all actions.
        skip(): Clears the current action queue while running.
        intend_skip(): Intends to skip the current action.
        stop(): Stops experimenting with experiment and action queues.
        intend_stop(): Intends to stop the orchestrator.
        intend_estop(): Intends to emergency stop the orchestrator.
        intend_none(): Resets the loop intent.
        clear_estop(): Clears the emergency stop.
        clear_error(): Clears the error statuses.
        clear_sequences(): Clears the sequence queue.
        clear_experiments(): Clears the experiment queue.
        clear_actions(): Clears the action queue.
        add_sequence(sequence): Adds a sequence to the queue.
        add_experiment(seq, experimentmodel, prepend, at_index): Adds an experiment to the queue.
        list_sequences(limit): Lists the sequences in the queue.
        list_experiments(limit): Lists the experiments in the queue.
        list_all_experiments(): Lists all experiments in the queue.
        drop_experiment_inds(inds): Drops experiments by index.
        get_experiment(last): Gets the active or last experiment.
        get_sequence(last): Gets the active or last sequence.
        list_active_actions(): Lists the active actions.
        list_actions(limit): Lists the actions in the queue.
        supplement_error_action(check_uuid, sup_action): Supplements an error action.
        remove_experiment(by_index, by_uuid): Removes an experiment by index or UUID.
        replace_action(sup_action, by_index, by_uuid, by_action_order): Replaces an action in the queue.
        append_action(sup_action): Appends an action to the queue.
        finish_active_sequence(): Finishes the active sequence.
        finish_active_experiment(): Finishes the active experiment.
        write_active_experiment_exp(): Writes the active experiment.
        write_active_sequence_seq(): Writes the active sequence.
        shutdown(): Shuts down the orchestrator.
        update_operator(msg): Updates the operator.
        start_wait(active): Starts a wait action.
        dispatch_wait_task(active, print_every_secs): Dispatches a wait task.
        active_action_monitor(): Monitors active actions.
        ping_action_servers(): Pings action servers.
        action_server_monitor(): Monitors action servers.
    """

    bokehapp: Server

    def __init__(self, fastapp: HelaoFastAPI):
        """
        Initializes the orchestrator server.

        Args:
            fastapp: The FastAPI application instance.
        """
        super().__init__(fastapp)
        self.experiment_lib, self.experiment_codehash_lib = import_experiments(
            world_config_dict=self.world_cfg,
            experiment_path=None,
            server_name=self.server.server_name,
            user_experiment_path=self.helaodirs.user_exp,
        )
        self.sequence_lib, self.sequence_codehash_lib = import_sequences(
            world_config_dict=self.world_cfg,
            sequence_path=None,
            server_name=self.server.server_name,
            user_sequence_path=self.helaodirs.user_seq,
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
        self.last_50_action_uuids = []
        self.last_50_experiment_uuids = []
        self.last_50_sequence_uuids = []
        self.last_action_uuid = ""
        self.last_interrupt = time.time()
        # hold schema objects
        self.active_experiment = None
        self.last_experiment = None
        self.active_sequence = None
        self.active_seq_exp_counter = 0
        self.last_sequence = None
        self.bokehapp = None
        self.orch_op = None
        self.op_enabled = self.server_params.get("enable_op", False)
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

    def exception_handler(self, loop, context):
        """
        Handles exceptions raised by coroutines in the event loop.

        This method is called when an exception is raised in a coroutine
        that is being executed by the event loop. It logs the exception
        details and sets the E-STOP flag on all active actions.

        Args:
            loop (asyncio.AbstractEventLoop): The event loop where the exception occurred.
            context (dict): A dictionary containing information about the exception,
                            including the exception object itself under the key "exception".

        Logs:
            - The exception message and traceback.
            - A message indicating that the E-STOP flag is being set on active actions.
        """
        LOGGER.error(f"Got exception from coroutine: {context}")
        exc = context.get("exception")
        LOGGER.error(f"{traceback.format_exception(type(exc), exc, exc.__traceback__)}")
        LOGGER.info("setting E-STOP flag on active actions")
        for _, active in self.actives.items():
            active.stop_action_task()

    def myinit(self):
        """
        Initializes the asynchronous event loop and sets up various tasks and handlers.

        This method performs the following actions:
        - Retrieves the current running event loop.
        - Sets a custom exception handler for the event loop.
        - Initiates an NTP time synchronization if it hasn't been done yet.
        - Creates and schedules tasks for NTP synchronization, live buffering, endpoint status initialization,
          status logging, global status broadcasting, heartbeat monitoring, and action server monitoring.
        - Retrieves and stores endpoint URLs.
        - Starts the operator if the operation is enabled.
        - Subscribes to all necessary status updates.

        Attributes:
            aloop (asyncio.AbstractEventLoop): The current running event loop.
            sync_ntp_task_run (bool): Flag indicating if the NTP sync task is running.
            ntp_syncer (asyncio.Task): Task for synchronizing NTP time.
            bufferer (asyncio.Task): Task for live buffering.
            fast_urls (list): List of endpoint URLs.
            status_logger (asyncio.Task): Task for logging status.
            status_subscriber (asyncio.Task): Task for subscribing to all status updates.
            globstat_broadcaster (asyncio.Task): Task for broadcasting global status.
            heartbeat_monitor (asyncio.Task): Task for monitoring active actions.
            driver_monitor (asyncio.Task): Task for monitoring the action server.
        """
        self.aloop = asyncio.get_running_loop()
        self.aloop.set_exception_handler(self.exception_handler)
        if self.ntp_last_sync is None:
            asyncio.gather(self.get_ntp_time())

        self.sync_ntp_task_run = False
        self.ntp_syncer = self.aloop.create_task(self.sync_ntp_task())
        self.bufferer = self.aloop.create_task(self.live_buffer_task())
        asyncio.gather(self.init_endpoint_status())

        self.fast_urls = self.get_endpoint_urls()
        self.status_logger = self.aloop.create_task(self.log_status_task())
        if self.server_cfg.get("regular_update", False):
            regular_delay = self.server_cfg.get("regular_update_delay", 10)
            self.regular_updater = self.aloop.create_task(
                self.regular_status_task(regular_delay)
            )

        if self.op_enabled:
            self.start_operator()
        self.status_subscriber = asyncio.create_task(self.subscribe_all())
        self.globstat_broadcaster = asyncio.create_task(self.globstat_broadcast_task())
        self.heartbeat_monitor = asyncio.create_task(self.active_action_monitor())
        self.driver_monitor = asyncio.create_task(self.action_server_monitor())

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

    def register_obj_uuid(self, obj_uuid, obj_type: str):
        """
        Registers a new object UUID in the list of the last 50 object UUIDs.

        This method ensures that the list of object UUIDs does not exceed 50 entries.
        If the list is full, the oldest UUID is removed before adding the new one.

        Args:
            obj_uuid (str): The UUID of the object to be registered.
        """
        OBJ_MAP = {
            "action": self.last_50_action_uuids,
            "experiment": self.last_50_experiment_uuids,
            "sequence": self.last_50_sequence_uuids,
        }

        if obj_uuid not in OBJ_MAP[obj_type]:
            while len(OBJ_MAP[obj_type]) >= 50:
                OBJ_MAP[obj_type].pop(0)
            OBJ_MAP[obj_type].append(obj_uuid)

    def register_action_uuid(self, action_uuid):
        """
        Registers a new action UUID in the list of the last 50 action UUIDs.

        This method ensures that the list of action UUIDs does not exceed 50 entries.
        If the list is full, the oldest UUID is removed before adding the new one.

        Args:
            action_uuid (str): The UUID of the action to be registered.
        """
        self.register_obj_uuid(action_uuid, "action")

    def track_action_uuid(self, action_uuid):
        """
        Tracks the last dispatched action UUID.

        Args:
            action_uuid (str): The UUID of the action to be tracked.
        """
        self.last_dispatched_action_uuid = action_uuid

    def start_operator(self):
        """
        Starts the Bokeh server for the operator.

        This method initializes and starts a Bokeh server instance using the
        configuration specified in `self.server_cfg` and `self.server_params`.
        It sets up the server to serve a Bokeh application at a specified port
        and address, and optionally launches a web browser to display the
        application.

        Parameters:
        None

        Returns:
        None
        """
        servHost = self.server_cfg["host"]
        servPort = self.server_params.get("bokeh_port", self.server_cfg["port"] + 1000)
        servPy = "BokehOperator"

        self.bokehapp = Server(
            {f"/{servPy}": partial(self.makeBokehApp, orch=self)},
            port=servPort,
            address=servHost,
            allow_websocket_origin=[f"{servHost}:{servPort}"],
        )
        LOGGER.info(f"started bokeh server {self.bokehapp}")
        self.bokehapp.start()
        if self.server_params.get("launch_browser", False):
            self.bokehapp.io_loop.add_callback(self.bokehapp.show, f"/{servPy}")
        # bokehapp.io_loop.start()

    def makeBokehApp(self, doc, orch):
        """
        Initializes a Bokeh application for visualization and sets up a BokehOperator.

        Args:
            doc (bokeh.document.Document): The Bokeh document to be used for the application.
            orch (Orchestrator): The orchestrator instance to be used by the BokehOperator.

        Returns:
            bokeh.document.Document: The modified Bokeh document with the BokehOperator attached.
        """
        app = HelaoVis(
            config=self.world_cfg,
            server_key=self.server.server_name,
            doc=doc,
        )

        # _ = HelaoOperator(app.vis)
        doc.operator = BokehOperator(app.vis, orch)
        # get the event loop
        # operatorloop = asyncio.get_event_loop()

        # this periodically updates the GUI (action and experiment tables)
        # operator.vis.doc.add_periodic_callback(operator.IOloop,2000) # time in ms

        return doc

    async def wait_for_interrupt(self, pending_action: Optional[Action] = None):
        """
        Asynchronously waits for an interrupt message from the interrupt queue.

        This method retrieves at least one status message from the `interrupt_q` queue.
        If the message is an instance of `GlobalStatusModel`, it updates the `incoming` attribute.
        It then continues to clear the `interrupt_q` queue, processing any remaining messages
        and putting their JSON representation into the `globstat_q` queue.

        Returns:
            None
        """

        # we wait for at least one status message
        # and then (if it contains more)
        # empty it and then return

        # get at least one status
        # try:
        if 1:
            # interrupt = await asyncio.wait_for(self.interrupt_q.get(), 0.5)
            interrupt = await self.interrupt_q.get()
            if isinstance(interrupt, GlobalStatusModel):
                self.incoming = interrupt
        # except asyncio.TimeoutError:
        #     if time.time() - self.last_interrupt > 10.0:
        #         self.print_message(
        #             "No interrupt, returning to while loop to check condition."
        #         )
        #         LOGGER.info("This message will print again after 10 seconds.")
        #         self.last_interrupt = time.time()
        #     return None

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
            self.action_dq.insert(0, pending_action)
            return False
        return True

    async def subscribe_all(self, retry_limit: int = 15):
        """
        Attempts to subscribe to all servers listed in the configuration, excluding
        those with "bokeh" or "demovis" in their configuration.

        This method tries to attach the client to each server by sending an
        "attach_client" request. If the connection fails, it retries up to
        `retry_limit` times with a 2-second delay between attempts.

        Args:
            retry_limit (int): The number of retry attempts for each server.
                               Default is 15.

        Side Effects:
            Updates `self.init_success` to True if all subscriptions are successful.
            Logs messages indicating the success or failure of each subscription attempt.

        Raises:
            aiohttp.client_exceptions.ClientConnectorError: If the connection to a server fails.

        Notes:
            - If any server fails to subscribe after the specified retries,
              `self.init_success` is set to False.
            - The method logs detailed messages about the subscription process.
        """
        fails = []
        for serv_key, serv_dict in self.world_cfg["servers"].items():
            if "bokeh" not in serv_dict and "demovis" not in serv_dict:
                LOGGER.info(f"trying to subscribe to {serv_key} status")

                success = False
                serv_addr = serv_dict["host"]
                serv_port = serv_dict["port"]
                for _ in range(retry_limit):
                    try:
                        response, error_code = await async_private_dispatcher(
                            server_key=serv_key,
                            host=serv_addr,
                            port=serv_port,
                            private_action="attach_client",
                            params_dict={
                                "client_servkey": self.server.server_name,
                                "client_host": self.server_cfg["host"],
                                "client_port": self.server_cfg["port"],
                            },
                            json_dict={},
                        )
                        # print(response)
                        # print(error_code)
                        if response is not None and error_code == ErrorCodes.none:
                            success = True
                            break
                    except aiohttp.client_exceptions.ClientConnectorError:
                        LOGGER.error(
                            f"failed to subscribe to {serv_key} at {serv_addr}:{serv_port}, trying again in 2 seconds",
                            exc_info=True,
                        )
                        await asyncio.sleep(2)

                if success:
                    LOGGER.info(f"Subscribed to {serv_key} at {serv_addr}:{serv_port}")
                else:
                    fails.append(serv_key)
                    LOGGER.info(
                        f"Failed to subscribe to {serv_key} at {serv_addr}:{serv_port}. Check connection."
                    )

        if len(fails) == 0:
            self.init_success = True
        else:
            LOGGER.info(
                "Orchestrator cannot action experiment_dq unless all FastAPI servers in config file are accessible."
            )

    async def update_nonblocking(
        self, actionmodel: Action, server_host: str, server_port: int
    ):
        """
        Asynchronously updates the non-blocking action list based on the action status.

        This method registers the action UUID, constructs a server execution ID, and
        updates the non-blocking list depending on the action status. It also triggers
        the orchestrator dispatch loop by putting an empty object in the interrupt queue.

        Args:
            actionmodel (Action): The action model containing details of the action.
            server_host (str): The host address of the server.
            server_port (int): The port number of the server.

        Returns:
            dict: A dictionary indicating the success of the operation.
        """
        # print(actionmodel.clean_dict())
        self.register_action_uuid(actionmodel.action_uuid)
        server_key = actionmodel.action_server.server_name
        server_exec_id = (server_key, actionmodel.exec_id, server_host, server_port)
        if "active" in actionmodel.action_status:
            self.nonblocking.append(server_exec_id)
        else:
            self.nonblocking.remove(server_exec_id)
        # put an empty object in interrupt_q to trigger orch dispatch loop
        await self.interrupt_q.put({})
        return {"success": True}

    async def clear_nonblocking(self):
        """
        Asynchronously clears non-blocking action IDs by sending stop requests to the respective servers.

        This method iterates over the non-blocking actions and sends a `stop_executor` request to each server
        to stop the corresponding executor. It collects the responses and error codes from each request.

        Returns:
            list of tuples: A list of tuples where each tuple contains the response and error code from a server.
        """
        resp_tups = []
        for server_key, exec_id, server_host, server_port in self.nonblocking:
            LOGGER.info(
                f"Sending stop_executor request to {server_key} on {server_host}:{server_port} for executor {exec_id}"
            )
            # print(server_key, exec_id, server_host, server_port)
            response, error_code = await async_private_dispatcher(
                server_key=server_key,
                host=server_host,
                port=server_port,
                private_action="stop_executor",
                params_dict={"executor_id": exec_id},
                json_dict={},
            )
            resp_tups.append((response, error_code))
        return resp_tups

    async def update_status(
        self, actionservermodel: Optional[ActionServerModel] = None
    ):
        """
        Asynchronously updates the status of the action server and the global status model.

        Args:
            actionservermodel (ActionServerModel, optional): The model containing the status of the action server. Defaults to None.

        Returns:
            bool: True if the status was successfully updated, False otherwise.

        This method performs the following steps:
        1. Prints a message indicating the receipt of the status from the server.
        2. If the actionservermodel is None, returns False.
        3. Acquires an asynchronous lock to ensure thread safety.
        4. Updates the global status model with the new action server model and sorts the new status dictionary.
        5. Registers the action UUID from the action server model.
        6. Updates the local buffer with the recent non-active actions.
        7. Checks if any action is in an emergency stop (estop) state or has errored.
        8. Updates the orchestration state based on the current status of actions.
        9. Pushes the updated global status model to the interrupt queue.
        10. Updates the operator with the new status.

        Note:
            The method assumes that `self.aiolock`, `self.globalstatusmodel`, `self.interrupt_q`, and `self.update_operator` are defined elsewhere in the class.
        """

        # LOGGER.debug(
        #     f"received status from server: {actionservermodel.action_server.server_name}"
        # )

        if actionservermodel is None:
            return False

        async with self.aiolock:
            # update GlobalStatusModel with new ActionServerModel
            # and sort the new status dict
            if actionservermodel.last_action_uuid is not None:
                self.register_action_uuid(actionservermodel.last_action_uuid)

            recent_nonactive = self.globalstatusmodel.update_global_with_acts(
                actionservermodel=actionservermodel
            )
            for act_uuid, act_status in recent_nonactive:
                await self.put_lbuf({act_uuid: {"status": act_status}})

            # check if one action is in estop in the error list:
            estop_uuids = self.globalstatusmodel.find_hlostatus_in_finished(
                hlostatus=HloStatus.estopped,
            )

            error_uuids = self.globalstatusmodel.find_hlostatus_in_finished(
                hlostatus=HloStatus.errored,
            )

            if estop_uuids and self.globalstatusmodel.loop_state == LoopStatus.started:
                await self.estop_loop(reason=f"due to action uuid(s): {estop_uuids}")
            elif (
                error_uuids and self.globalstatusmodel.loop_state == LoopStatus.started
            ):
                self.globalstatusmodel.orch_state = OrchStatus.error
            elif not self.globalstatusmodel.active_dict:
                # no uuids in active action dict
                self.globalstatusmodel.orch_state = OrchStatus.idle
            else:
                self.globalstatusmodel.orch_state = OrchStatus.busy
                LOGGER.info(f"running_states: {self.globalstatusmodel.active_dict}")

            # now push it to the interrupt_q
            await self.interrupt_q.put(self.globalstatusmodel)
            await self.update_operator(True)
            # await self.globstat_q.put(self.globalstatusmodel.as_json())

            return True

    async def ws_globstat(self, websocket: WebSocket):
        """
        Handle WebSocket connections for global status updates.

        This asynchronous method accepts a WebSocket connection, subscribes to global status updates,
        and sends these updates to the connected WebSocket client in real-time. If an exception occurs,
        it logs the error and removes the subscription.

        Args:
            websocket (WebSocket): The WebSocket connection instance.

        Raises:
            Exception: If an error occurs during the WebSocket communication or subscription handling.
        """
        LOGGER.info("got new global status subscriber")
        await websocket.accept()
        gs_sub = self.globstat_q.subscribe()
        try:
            async for globstat_msg in gs_sub:
                await websocket.send_text(json.dumps(globstat_msg.as_dict()))
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            LOGGER.warning(
                f"Data websocket client {websocket.client[0]}:{websocket.client[1]} disconnected. {repr(e), tb,}"
            )
            if gs_sub in self.globstat_q.subscribers:
                self.globstat_q.remove(gs_sub)

    async def globstat_broadcast_task(self):
        """
        Asynchronous task that subscribes to the `globstat_q` queue and
        periodically sleeps for a short duration.

        This method continuously listens to the `globstat_q` queue and
        performs a non-blocking sleep for 0.01 seconds on each iteration.

        Returns:
            None
        """
        async for _ in self.globstat_q.subscribe():
            await asyncio.sleep(0.01)

    def unpack_sequence(self, sequence_name: str, sequence_params) -> List[Experiment]:
        """
        Unpacks and returns a sequence of experiments based on the given sequence name and parameters.

        Args:
            sequence_name (str): The name of the sequence to unpack.
            sequence_params (dict): A dictionary of parameters to pass to the sequence function.

        Returns:
            List[Experiment]: A list of Experiment objects corresponding to the unpacked sequence.
                              Returns an empty list if the sequence name is not found in the sequence library.
        """
        if sequence_name in self.sequence_lib:
            return self.sequence_lib[sequence_name](**sequence_params)
        else:
            return []

    def get_sequence_codehash(self, sequence_name: str) -> UUID:
        """
        Retrieve the UUID code hash for a given sequence name.

        Args:
            sequence_name (str): The name of the sequence.

        Returns:
            UUID: The UUID code hash associated with the sequence name.
        """
        return self.sequence_codehash_lib[sequence_name]

    async def seq_unpacker(self):
        """
        Asynchronously unpacks and processes experiments from the active sequence.

        Iterates through the list of experiments in the active sequence's experiment plan.
        For each experiment, it assigns a data request ID if available and adds the experiment
        to the sequence. Updates the global status model to indicate the loop state has started
        after processing the first experiment.

        Args:
            None

        Returns:
            None
        """
        for i, experimentmodel in enumerate(self.active_sequence.experiment_plan_list):
            # self.print_message(
            #     f"unpack experiment {experimentmodel.experiment_name}"
            # )
            if self.seq_model.data_request_id is not None:
                experimentmodel.data_request_id = self.seq_model.data_request_id
            await self.add_experiment(
                seq=self.seq_model, experimentmodel=experimentmodel
            )
            if i == 0:
                self.globalstatusmodel.loop_state = LoopStatus.started

    def verify_plate_in_params(self, paramd: dict) -> bool:
        """
        Checks parameter dict if plate_id parameter has a valid screening print.

        Args:
            paramd (dict): parameter dictionary

        Returns:
            bool: True when parameter dict contains plate_id with a valid screening print
        """
        plate_found = False
        if "solid_plate_id" in paramd or "plate_id" in paramd:
            # check for valid plate if solid_plate_id or plate_id is a sequence parameter
            if LEGACY_API.has_access:
                for pid_key in ["solid_plate_id", "plate_id"]:
                    pid_val = paramd.get(pid_key, None)
                    if pid_val is not None:
                        platemap = LEGACY_API.get_platemap_plateid(pid_val)
                        if platemap:
                            plate_found = True
                            LOGGER.info(
                                f"plate_id {pid_val} was found with a valid platemap"
                            )
                            break
            else:
                LOGGER.warning(
                    "plate_id is a sequence parameter but there is no access to info and map file locations."
                )
        else:
            # no plate parameter, so act like it's fine
            plate_found = True
        return plate_found

    async def loop_task_dispatch_sequence(self) -> ErrorCodes:
        """
        Asynchronously dispatches a sequence from the sequence queue and initializes it.

        This method performs the following steps:
        1. Retrieves a new sequence from the sequence queue (`sequence_dq`).
        2. Sets the new sequence as the active sequence and updates its status to "active".
        3. Configures the sequence based on the world configuration (`world_cfg`).
        4. Initializes the sequence with a time offset and sets the orchestrator.
        5. Populates the sequence parameters from global experiment parameters.
        6. Unpacks the sequence into an experiment plan list if not already populated.
        7. Writes the sequence to a local buffer and optionally uploads it to S3.
        8. Creates a task to unpack the sequence and waits for a short duration.

        Returns:
            ErrorCodes: The error code indicating the result of the operation.
        """
        if self.sequence_dq:
            LOGGER.info("getting new sequence from sequence_dq")
            self.active_sequence = self.sequence_dq.popleft()

            self.last_50_sequence_uuids.append(self.active_sequence.sequence_uuid)
            LOGGER.info(f"new active sequence is {self.active_sequence.sequence_name}")
            await self.put_lbuf(
                {
                    self.active_sequence.sequence_uuid: {
                        "sequence_name": self.active_sequence.sequence_name,
                        "status": "active",
                    }
                }
            )
            if self.world_cfg.get("dummy", "False"):
                self.active_sequence.dummy = True
            if self.world_cfg.get("simulation", "False"):
                self.active_sequence.simulation = True
            self.active_sequence.init_seq(time_offset=self.ntp_offset)
            self.active_sequence.orchestrator = self.server

            # from global params
            for k, v in self.active_sequence.from_global_params.items():
                LOGGER.info(f"mapping from global params to sequence {k}:{v}")
                if k in self.global_params:
                    if isinstance(v, list):
                        for vv in v:
                            self.active_sequence.sequence_params[vv] = (
                                self.global_params[k]
                            )
                    else:
                        self.active_sequence.sequence_params[v] = self.global_params[k]

            # if experiment_plan_list is empty, unpack sequence,
            # otherwise operator already populated experiment_plan_list
            if self.active_sequence.sequence_name in self.sequence_lib:
                experiment_plan_list = self.unpack_sequence(
                    self.active_sequence.sequence_name,
                    self.active_sequence.sequence_params,
                )
                if not self.active_sequence.experiment_plan_list:
                    self.active_sequence.experiment_plan_list = experiment_plan_list
                elif len(self.active_sequence.experiment_plan_list) >= len(
                    experiment_plan_list
                ):
                    new_experiment_plan_list = []
                    for exp_model in self.active_sequence.experiment_plan_list:
                        if not experiment_plan_list:
                            new_experiment_plan_list.append(exp_model)
                        else:
                            exp = experiment_plan_list.pop(0)
                            if exp.experiment_name == exp_model.experiment_name:
                                for k, v in vars(exp_model).items():
                                    setattr(exp, k, v)
                                new_experiment_plan_list.append(exp)
                            else:
                                break
                    if len(self.active_sequence.experiment_plan_list) == len(
                        new_experiment_plan_list
                    ):
                        self.active_sequence.experiment_plan_list = (
                            new_experiment_plan_list
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

            if self.verify_plates and LEGACY_API.has_access:
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
        """
        Asynchronously dispatches a new experiment from the experiment queue and processes its actions.

        This method performs the following steps:
        1. Retrieves a new experiment from the experiment queue.
        2. Copies global parameters to the experiment parameters.
        3. Initializes the experiment and updates the global status model.
        4. Unpacks the actions for the experiment and assigns necessary attributes.
        5. Adds the unpacked actions to the action queue.
        6. Writes the active experiment to a temporary storage.
        7. Optionally uploads the initial active experiment JSON to S3.

        Returns:
            ErrorCodes: The error code indicating the result of the operation.
        """
        LOGGER.info("action_dq is empty, getting new actions")
        # wait for all actions in last/active experiment to finish
        # LOGGER.info("finishing last active experiment first")
        # await self.finish_active_experiment()

        # LOGGER.info("getting new experiment to fill action_dq")
        # generate uids when populating,
        # generate timestamp when acquring
        self.active_experiment = self.experiment_dq.popleft()

        self.last_50_experiment_uuids.append(self.active_experiment.experiment_uuid)
        self.active_experiment.orch_key = self.orch_key
        self.active_experiment.orch_host = self.orch_host
        self.active_experiment.orch_port = self.orch_port
        self.active_experiment.sequence_uuid = self.active_sequence.sequence_uuid
        self.active_seq_exp_counter += 1

        # LOGGER.info("copying global vars to experiment")
        # copy requested global param to experiment params
        for k, v in self.active_experiment.from_global_params.items():
            LOGGER.info(f"mapping from global params to experiment -- {k}:{v}")
            if k in self.global_params:
                if isinstance(v, list):
                    for vv in v:
                        self.active_experiment.experiment_params[vv] = (
                            self.global_params[k]
                        )
                else:
                    self.active_experiment.experiment_params[v] = self.global_params[k]

        LOGGER.info(
            f"new active experiment is {self.active_experiment.experiment_name}"
        )
        await self.put_lbuf(
            {
                self.active_experiment.experiment_uuid: {
                    "experiment_name": self.active_experiment.experiment_name,
                    "status": "active",
                }
            }
        )
        if self.world_cfg.get("dummy", "False"):
            self.active_experiment.dummy = True
        if self.world_cfg.get("simulation", "False"):
            self.active_experiment.simulation = True
        self.active_experiment.run_type = self.run_type
        self.active_experiment.orchestrator = self.server
        self.active_experiment.init_exp(time_offset=self.ntp_offset)

        self.globalstatusmodel.new_experiment(
            exp_uuid=self.active_experiment.experiment_uuid
        )

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
            unpacked_acts = self.active_experiment.action_plan

        self.active_experiment.experiment_codehash = self.experiment_codehash_lib[
            self.active_experiment.experiment_name
        ]
        if unpacked_acts is None:
            LOGGER.error("no actions in experiment")
            self.action_dq = zdeque([])
            return ErrorCodes.none

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
            staged_acts.append(act)
        if process_order_groups:
            self.active_experiment.process_order_groups = process_order_groups
            process_list = init_process_uuids[: len(process_order_groups)]
            self.active_experiment.process_list = process_list

        LOGGER.info(f"got: {staged_acts}")
        LOGGER.info(f"optional params: {self.active_experiment.experiment_params}")

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

        if self.verify_plates and LEGACY_API.has_access:
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

        LOGGER.info("adding unpacked actions to action_dq")
        for act in staged_acts:
            self.action_dq.append(act)

        return ErrorCodes.none

    async def loop_task_dispatch_action(self) -> ErrorCodes:
        """
        Asynchronously dispatches actions based on the current loop intent and action queue.

        This method processes actions in the action queue (`action_dq`) according to the
        current loop intent (`loop_intent`) and loop state (`loop_state`). It handles
        different loop intents such as stop, skip, and estop, and dispatches actions
        accordingly. The method also manages action start conditions and updates global
        parameters based on action results.

        Returns:
            ErrorCodes: The error code indicating the result of the action dispatch process.

        Loop Intents:
            - LoopIntent.stop: Stops the orchestrator after all actions are finished.
            - LoopIntent.skip: Clears the action queue and skips to the next experiment.
            - LoopIntent.estop: Clears the action queue and sets the loop state to estopped.
            - Default: Dispatches actions based on their start conditions.

        Action Start Conditions:
            - ActionStartCondition.no_wait: Dispatches the action unconditionally.
            - ActionStartCondition.wait_for_endpoint: Waits for the endpoint to become available.
            - ActionStartCondition.wait_for_server: Waits for the server to become available.
            - ActionStartCondition.wait_for_orch: Waits for the orchestrator to become available.
            - ActionStartCondition.wait_for_previous: Waits for the previous action to finish.
            - ActionStartCondition.wait_for_all: Waits for all actions to finish.

        Raises:
            Exception: If an error occurs during action dispatching.
            asyncio.exceptions.TimeoutError: If a timeout occurs during action dispatching.

        Notes:
            - This method uses an asyncio lock (`aiolock`) to ensure thread safety during
              action dispatching.
            - The method updates global parameters based on the results of dispatched actions.
            - If an action dispatch fails, the method stops the orchestrator and re-queues
              the action.
        """
        # LOGGER.info("actions in action_dq, processing them")
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

        elif self.globalstatusmodel.loop_intent == LoopIntent.skip:
            # clear action queue, forcing next experiment
            self.action_dq.clear()
            await self.intend_none()
            LOGGER.info("skipping to next experiment")
        elif self.globalstatusmodel.loop_intent == LoopIntent.estop:
            self.action_dq.clear()
            await self.intend_none()
            LOGGER.info("estopping")
            self.globalstatusmodel.loop_state = LoopStatus.estopped
        else:
            # all action blocking is handled like preempt,
            # check Action requirements
            A = self.action_dq.popleft()

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

            # LOGGER.info("copying global vars to action")
            # copy requested global param to action params
            for k, v in A.from_global_params.items():
                LOGGER.info(f"mapping from global params to action {k}:{v}")
                if k in self.global_params:
                    if isinstance(v, list):
                        for vv in v:
                            A.action_params[vv] = self.global_params[k]
                    else:
                        A.action_params[v] = self.global_params[k]

            actserv_exists, _ = await endpoints_available([A.url])
            if not actserv_exists:
                stop_message = f"{A.url} is not available, orchestrator will stop. Rectify action server then resume orchestrator run."
                self.current_stop_message = stop_message
                LOGGER.warning(stop_message)
                await self.stop()
                LOGGER.alert(f"ORCH STOPPED ~ {stop_message}")
                self.action_dq.insert(0, A)
                await self.update_operator(True)
                return ErrorCodes.none

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
            result_actiondict = None
            async with self.aiolock:
                try:
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
                        await self.update_operator(True)
                        return ErrorCodes.none

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
                    {result_uuid: {"action_name": A.action_name, "status": "active"}}
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

            try:
                result_action = Action(**result_actiondict)
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

            if (
                result_action.to_global_params
                and result_action.orch_key == self.orch_key
                and result_action.orch_host == self.orch_host
                and int(result_action.orch_port) == int(self.orch_port)
            ):
                if isinstance(result_action.to_global_params, list):
                    # self.print_message(
                    #     f"copying global vars {', '.join(result_action.to_global_params)} back to experiment"
                    # )
                    for k in result_action.to_global_params:
                        if k in result_action.action_params:
                            LOGGER.info(f"updating {k} in global vars")
                            self.global_params[k] = result_action.action_params[k]
                        elif k in result_action.action_output:
                            LOGGER.info(f"updating {k} in global vars")
                            self.global_params[k] = result_action.action_output[k]
                        else:
                            LOGGER.info(f"key {k} not found in action output or params")
                elif isinstance(result_action.to_global_params, dict):
                    # self.print_message(
                    #     f"copying global vars {', '.join(result_action.to_global_params.keys())} back to experiment"
                    # )
                    for k1, k2 in result_action.to_global_params.items():
                        if k1 in result_action.action_params:
                            LOGGER.info(f"updating {k2} in global vars")
                            self.global_params[k2] = result_action.action_params[k1]
                        elif k1 in result_action.action_output:
                            LOGGER.info(f"updating {k2} in global vars")
                            self.global_params[k2] = result_action.action_output[k1]
                        else:
                            LOGGER.info(
                                f"key {k1} not found in action output or params"
                            )

            # # this will recursively call the next no_wait action in queue, and return its error
            # if self.action_dq and not self.step_thru_actions:
            #     nextA = self.action_dq[0]
            #     if nextA.start_condition == ActionStartCondition.no_wait:
            #         error_code = await self.loop_task_dispatch_action()

            # if error_code is not ErrorCodes.none:
            #     return error_code

        return ErrorCodes.none

    async def dispatch_loop_task(self):
        """
        The main dispatch loop task for the operator orchestrator. This asynchronous
        method manages the dispatching of actions, experiments, and sequences based
        on the current state of the orchestrator and the contents of the respective
        queues.

        The loop continues running as long as the orchestrator's loop state is
        `LoopStatus.started` and there are items in the action, experiment, or
        sequence queues. It handles the following tasks:

        - Resuming paused action lists.
        - Checking driver states and retrying if necessary.
        - Dispatching actions, experiments, and sequences based on the current state.
        - Handling emergency stops and step-through modes.
        - Updating the operator with the current state and progress.

        The loop will stop if:
        - An emergency stop is triggered.
        - All queues are empty.
        - An error occurs during dispatching.

        Upon stopping, it ensures that any active experiment or sequence is finished
        properly.

        Returns:
            bool: True if the loop completes successfully, False if an exception occurs.

        Raises:
            Exception: If an unexpected error occurs during the loop execution.
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
                    LOGGER.info("!!!dispatching next action")
                    error_code = await self.loop_task_dispatch_action()
                    while (
                        self.last_dispatched_action_uuid
                        not in self.last_50_action_uuids
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
                await self.update_operator(True)

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
            await self.update_operator(True)

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
        """
        Waits for all actions to complete.

        This asynchronous method continuously checks the status of actions and waits
        until all actions are idle. If any actions are still active, it waits for a
        status update and prints a message if the wait time exceeds 10 seconds.

        Returns:
            None
        """

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
        """
        Starts the orchestration loop if it is currently stopped. If there are any
        actions, experiments, or sequences in the queue, it resumes from a paused
        state. Otherwise, it notifies that the experiment list is empty. If the loop
        is already running, it notifies that it is already running. Finally, it clears
        the current stop message and updates the operator status.

        Returns:
            None
        """
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
        await self.update_operator(True)

    async def start_loop(self):
        if self.globalstatusmodel.loop_state == LoopStatus.stopped:
            """
            Starts the orchestration loop if it is currently stopped.

            This method checks the current state of the orchestration loop and starts it if it is in the 'stopped' state.
            If the loop is in the 'estopped' state, it logs an error message indicating that the E-STOP flag must be cleared
            before starting. If the loop is already running, it logs a message indicating that the loop is already started.

            Returns:
                LoopStatus: The current state of the orchestration loop after attempting to start it.
            """
            LOGGER.info("starting orch loop")
            self.loop_task = asyncio.create_task(self.dispatch_loop_task())
        elif self.globalstatusmodel.loop_state == LoopStatus.estopped:
            LOGGER.error("E-STOP flag was raised, clear E-STOP before starting.")
        else:
            LOGGER.info("loop already started.")
        return self.globalstatusmodel.loop_state

    async def estop_loop(self, reason: str = ""):
        """
        Asynchronously handles the emergency stop (E-STOP) procedure for the orchestrator.

        This method performs the following actions:
        1. Logs an emergency stop message with an optional reason.
        2. Sets the global status model's loop state to 'estopped'.
        3. Forces the stop of all running actions associated with this orchestrator.
        4. Resets the loop intention to none.
        5. Updates the current stop message with "E-STOP" and the optional reason.
        6. Notifies the operator of the emergency stop status.

        Args:
            reason (str, optional): An optional reason for the emergency stop. Defaults to an empty string.
        """
        reason_suffix = f"{' ' + reason if reason else ''}"
        LOGGER.info("estopping orch")

        # set globalstatusmodel.loop_state to estop
        self.globalstatusmodel.loop_state = LoopStatus.estopped

        # force stop all running actions in the status dict (for this orch)
        await self.estop_actions(switch=False)  # don't latch actionserver model

        # reset loop intend
        await self.intend_none()

        self.current_stop_message = "E-STOP" + reason_suffix
        LOGGER.warning("E-STOP" + reason_suffix)
        LOGGER.alert("ORCH E-STOP")
        await self.update_operator(True)

    async def stop_loop(self):
        """
        Asynchronously stops the loop by intending to stop.

        This method calls the `intend_stop` coroutine to signal that the loop should stop.
        """
        await self.intend_stop()

    async def estop_actions(self, switch: bool):
        """
        Asynchronously sends an emergency stop (estop) command to all servers.

        This method sends an estop command to all action servers registered in the global status model.
        The estop command can be triggered during an active experiment or based on the last experiment.
        If no experiment is active or available, a new experiment with estop status is created.

        Args:
            switch (bool): The state of the estop switch. True to activate estop, False to deactivate.

        Raises:
            Exception: If the estop command fails for any action server, an exception is caught and logged.

        """
        LOGGER.info("estopping all servers")

        # create a dict for current active_experiment
        # (estop happens during the active_experiment)

        if self.active_experiment is not None:
            active_exp_dict = self.active_experiment.as_dict()
        elif self.last_experiment is not None:
            active_exp_dict = self.last_experiment.as_dict()
        else:
            exp = Experiment()
            exp.sequence_name = "orch_estop"
            # need to set status, else init will set in to active
            exp.sequence_status = [HloStatus.estopped, HloStatus.finished]
            exp.init_seq(time_offset=self.ntp_offset)

            exp.run_type = self.run_type
            exp.orchestrator = self.server
            exp.experiment_status = [HloStatus.estopped, HloStatus.finished]
            exp.init_exp(time_offset=self.ntp_offset)
            active_exp_dict = exp.as_dict()

        for (
            action_server_key,
            actionservermodel,
        ) in self.globalstatusmodel.server_dict.items():
            # if actionservermodel.action_server == self.server:
            #     continue

            action_dict = deepcopy(active_exp_dict)
            action_dict.update(
                {
                    "action_name": "estop",
                    "action_server": actionservermodel.action_server.as_dict(),
                    "action_params": {"switch": switch},
                    "start_condition": ActionStartCondition.no_wait,
                }
            )

            A = Action(**action_dict)
            LOGGER.info(
                f"Sending estop={switch} request to {actionservermodel.action_server.disp_name()}"
            )
            try:
                _ = await async_action_dispatcher(self.world_cfg, A)
            except Exception as e:
                tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
                # no estop endpoint for this action server?
                LOGGER.error(
                    f"estop for {actionservermodel.action_server.disp_name()} failed with: {repr(e), tb,}"
                )

    async def skip(self):
        """
        Asynchronously skips the current action in the orchestrator.

        If the orchestrator's loop state is `LoopStatus.started`, it will attempt to skip the current action by calling `intend_skip()`.
        Otherwise, it will print a message indicating that the orchestrator is not running and clear the action queue.

        Returns:
            None
        """
        if self.globalstatusmodel.loop_state == LoopStatus.started:
            await self.intend_skip()
        else:
            LOGGER.info("orchestrator not running, clearing action queue")
            self.action_dq.clear()

    async def intend_skip(self):
        """
        Asynchronously sets the loop intent to 'skip' and puts this intent into the interrupt queue.

        This method updates the global status model's loop intent to 'skip' and then places this intent
        into the interrupt queue to signal that the current loop should be skipped.

        Returns:
            None
        """
        self.globalstatusmodel.loop_intent = LoopIntent.skip
        await self.interrupt_q.put(self.globalstatusmodel.loop_intent)

    async def stop(self):
        """
        Stops the orchestrator based on its current loop state.

        If the loop state is `LoopStatus.started`, it will attempt to stop the orchestrator
        by calling `intend_stop()`. If the loop state is `LoopStatus.estopped`, it will
        print a message indicating that the E-STOP flag was raised and there is nothing to stop.
        Otherwise, it will print a message indicating that the orchestrator is not running.
        """
        if self.globalstatusmodel.loop_state == LoopStatus.started:
            await self.intend_stop()
        elif self.globalstatusmodel.loop_state == LoopStatus.estopped:
            LOGGER.info("orchestrator E-STOP flag was raised; nothing to stop")
        else:
            LOGGER.info("orchestrator is not running")

    async def intend_stop(self):
        """
        Asynchronously sets the loop intent to stop and puts this intent into the interrupt queue.

        This method updates the `loop_intent` attribute of the `globalstatusmodel` to `LoopIntent.stop`
        and then places this intent into the `interrupt_q` queue to signal that the loop should stop.

        Returns:
            None
        """
        self.globalstatusmodel.loop_intent = LoopIntent.stop
        await self.interrupt_q.put(self.globalstatusmodel.loop_intent)

    async def intend_estop(self):
        """
        Asynchronously sets the loop intent to emergency stop (estop) and puts the
        updated loop intent into the interrupt queue.

        This method updates the `loop_intent` attribute of the `globalstatusmodel`
        to `LoopIntent.estop` and then places this intent into the `interrupt_q`
        queue to signal an emergency stop.

        Returns:
            None
        """
        self.globalstatusmodel.loop_intent = LoopIntent.estop
        await self.interrupt_q.put(self.globalstatusmodel.loop_intent)

    async def intend_none(self):
        """
        Sets the loop intent to 'none' and puts this intent into the interrupt queue.

        This method updates the global status model's loop intent to indicate that no
        specific loop action is intended. It then places this updated intent into the
        interrupt queue to signal other parts of the system.

        Returns:
            None
        """
        self.globalstatusmodel.loop_intent = LoopIntent.none
        await self.interrupt_q.put(self.globalstatusmodel.loop_intent)

    async def clear_estop(self):
        """
        Asynchronously clears the emergency stop (estop) state.

        This method performs the following actions:
        1. Logs a message indicating that estopped UUIDs are being cleared.
        2. Clears the estopped status from the global status model.
        3. Releases the estop state for all action servers.
        4. Sets the orchestration status from estopped back to stopped.
        5. Puts a "cleared_estop" message into the interrupt queue.

        Returns:
            None
        """
        # which were estopped first
        LOGGER.info("clearing estopped uuids")
        self.globalstatusmodel.clear_in_finished(hlostatus=HloStatus.estopped)
        # release estop for all action servers
        await self.estop_actions(switch=False)
        # set orch status from estop back to stopped
        self.globalstatusmodel.loop_state = LoopStatus.stopped
        await self.interrupt_q.put("cleared_estop")

    async def clear_error(self):
        """
        Asynchronously clears the error state.

        This method resets the error dictionary by clearing errored UUIDs
        and updates the global status model to reflect that the errors
        have been cleared. It also sends a message to the interrupt queue
        indicating that the errors have been cleared.

        Returns:
            None
        """
        # currently only resets the error dict
        LOGGER.info("clearing errored uuids")
        self.globalstatusmodel.clear_in_finished(hlostatus=HloStatus.errored)
        await self.interrupt_q.put("cleared_errored")

    async def clear_sequences(self):
        """
        Asynchronously clears the sequence queue.

        This method logs a message indicating that the sequence queue is being cleared
        and then clears the sequence deque.

        Returns:
            None
        """
        LOGGER.info("clearing sequence queue")
        self.sequence_dq.clear()

    async def clear_experiments(self):
        """
        Asynchronously clears the experiment queue.

        This method prints a message indicating that the experiment queue is being cleared
        and then clears the deque containing the experiments.

        Returns:
            None
        """
        LOGGER.info("clearing experiment queue")
        self.experiment_dq.clear()

    async def clear_actions(self):
        """
        Asynchronously clears the action queue.

        This method prints a message indicating that the action queue is being cleared
        and then clears the action deque.

        Returns:
            None
        """
        LOGGER.info("clearing action queue")
        self.action_dq.clear()

    async def add_sequence(self, sequence: Sequence):
        """
        Adds a sequence to the sequence deque and initializes its UUID and codehash if not already set.

        Args:
            sequence (Sequence): The sequence object to be added.

        Returns:
            str: The UUID of the added sequence.
        """
        # init uuid now for tracking later
        if sequence.sequence_uuid is None:
            sequence.sequence_uuid = gen_uuid()
        if (
            sequence.sequence_codehash is None
            and sequence.sequence_name in self.sequence_codehash_lib
        ):
            sequence.sequence_codehash = self.sequence_codehash_lib[
                sequence.sequence_name
            ]
        self.sequence_dq.append(sequence)
        return sequence.sequence_uuid

    async def add_experiment(
        self,
        seq: Sequence,
        experimentmodel: Experiment,
        prepend: bool = False,
        at_index: Optional[int] = None,
    ):
        """
        Adds an experiment to the sequence.

        Args:
            seq (Sequence): The sequence to which the experiment will be added.
            experimentmodel (Experiment): The experiment model to be added.
            prepend (bool, optional): If True, the experiment will be added to the front of the queue. Defaults to False.
            at_index (int, optional): If provided, the experiment will be inserted at the specified index. Defaults to None.

        Returns:
            str: The UUID of the added experiment.

        Raises:
            TypeError: If the experimentmodel is not an instance of Experiment.
        """
        seq_dict = seq.model_dump()
        if not isinstance(experimentmodel, Experiment):
            experimentmodel_dict = experimentmodel.model_dump()
            D = Experiment(**experimentmodel_dict)
        else:
            D = experimentmodel
        for k in seq_dict.keys():
            setattr(D, k, getattr(seq, k))

        # init uuid now for tracking later
        D.experiment_uuid = gen_uuid()

        # reminder: experiment_dict values take precedence over keyword args
        if D.orchestrator.server_name is None or D.orchestrator.machine_name is None:
            D.orchestrator = self.server

        await asyncio.sleep(0.01)
        if at_index is not None:
            self.experiment_dq.insert(i=at_index, x=D)
        elif prepend:
            self.experiment_dq.appendleft(D)
            # LOGGER.info(f"experiment {D.experiment_name} prepended to queue")
        else:
            self.experiment_dq.append(D)
            # LOGGER.info(f"experiment {D.experiment_name} appended to queue")
        return D.experiment_uuid

    def list_sequences(self, limit=10):
        """
        List sequences from the sequence deque up to a specified limit.

        Args:
            limit (int, optional): The maximum number of sequences to list. Defaults to 10.

        Returns:
            list: A list of sequences, each obtained by calling the `get_seq` method on the elements of the sequence deque.
        """
        return [
            self.sequence_dq[i].get_seq()
            for i in range(min(len(self.sequence_dq), limit))
        ]

    def list_experiments(self, limit=10):
        """
        List a limited number of experiments.

        Args:
            limit (int, optional): The maximum number of experiments to list. Defaults to 10.

        Returns:
            list: A list of experiments, each obtained by calling `get_exp()` on elements of `self.experiment_dq`.
        """
        return [
            self.experiment_dq[i].get_exp()
            for i in range(min(len(self.experiment_dq), limit))
        ]

    def list_all_experiments(self):
        """
        List all experiments with their indices.

        Returns:
            list of tuple: A list of tuples where each tuple contains the index of the
            experiment and the experiment name.
        """
        return [
            (i, D.get_exp().experiment_name) for i, D in enumerate(self.experiment_dq)
        ]

    def drop_experiment_inds(self, inds: List[int]):
        """
        Remove experiments from the experiment queue at the specified indices.

        Args:
            inds (List[int]): A list of indices of the experiments to be removed.

        Returns:
            List: A list of all remaining experiments after the specified experiments have been removed.
        """
        for i in sorted(inds, reverse=True):
            del self.experiment_dq[i]
        return self.list_all_experiments()

    def get_experiment(self, last=False) -> Experiment:
        """
        Retrieve the current or last experiment.

        Args:
            last (bool): If True, retrieve the last experiment. If False, retrieve the active experiment.

        Returns:
            Experiment: The experiment object if it exists, otherwise an empty dictionary.
        """
        experiment = self.last_experiment if last else self.active_experiment
        if experiment is not None:
            return experiment.get_exp()
        return {}

    def get_sequence(self, last=False) -> Sequence:
        """
        Retrieve the current or last sequence.

        Args:
            last (bool): If True, retrieve the last sequence. If False, retrieve the active sequence.

        Returns:
            Sequence: The sequence object if available, otherwise an empty dictionary.
        """
        sequence = self.last_sequence if last else self.active_sequence
        if sequence is not None:
            return sequence.get_seq()
        return {}

    def list_active_actions(self):
        """
        List all active actions.

        Returns:
            list: A list of status models representing the active actions.
        """
        return [
            statusmodel
            for uuid, statusmodel in self.globalstatusmodel.active_dict.items()
        ]

    def list_actions(self, limit=10):
        """
        List a limited number of actions from the action queue.

        Args:
            limit (int, optional): The maximum number of actions to list. Defaults to 10.

        Returns:
            list: A list of action models from the action queue, up to the specified limit.
        """
        return [
            self.action_dq[i].get_act() for i in range(min(len(self.action_dq), limit))
        ]

    def supplement_error_action(self, check_uuid: UUID, sup_action: Action):
        """
        Supplements an errored action with a new action.

        This method checks if the provided UUID is in the list of errored actions.
        If it is, it creates a new action based on the supplied action, updates its
        order and retry count, and appends it to the action deque for reprocessing.
        If the UUID is not found in the list of errored actions, it prints an error message.

        Args:
            check_uuid (UUID): The UUID of the action to check.
            sup_action (Action): The new action to supplement the errored action.

        Returns:
            None
        """

        error_uuids = self.globalstatusmodel.find_hlostatus_in_finished(
            hlostatus=HloStatus.errored,
        )
        if not error_uuids:
            LOGGER.info("There are no error statuses to replace")
        else:
            if check_uuid in error_uuids:
                EA_act = error_uuids[check_uuid]
                # sup_action can be a differnt one,
                # but for now we treat it thats a retry of the errored one
                new_action = sup_action
                new_action.action_order = EA_act.action_order
                # will be updated again once its dispatched again
                new_action.actual_order = EA_act.actual_order
                new_action.action_retry = EA_act.action_retry + 1
                self.action_dq.appendleft(new_action)
            else:
                LOGGER.info(f"uuid {check_uuid} not found in list of error statuses:")
                LOGGER.info(", ")

    def remove_experiment(
        self, by_index: Optional[int] = None, by_uuid: Optional[UUID] = None
    ):
        """
        Removes an experiment from the experiment queue.

        Parameters:
        by_index (int, optional): The index of the experiment to remove.
        by_uuid (UUID, optional): The UUID of the experiment to remove.

        If both parameters are provided, `by_index` will take precedence.
        If neither parameter is provided, a message will be printed and the method will return None.

        Raises:
        IndexError: If the index is out of range.
        KeyError: If the UUID is not found in the experiment queue.
        """
        if by_index is not None:
            i = by_index
        elif by_uuid is not None:
            i = [
                i
                for i, D in enumerate(list(self.experiment_dq))
                if D.experiment_uuid == by_uuid
            ][0]
        else:
            LOGGER.info(
                "No arguments given for locating existing experiment to remove."
            )
            return None
        del self.experiment_dq[i]

    def replace_action(
        self,
        sup_action: Action,
        by_index: Optional[int] = None,
        by_uuid: Optional[UUID] = None,
        by_action_order: Optional[int] = None,
    ):
        """
        Substitute a queued action with a new action.

        Parameters:
        sup_action (Action): The new action to replace the existing one.
        by_index (int, optional): The index of the action to be replaced.
        by_uuid (UUID, optional): The UUID of the action to be replaced.
        by_action_order (int, optional): The action order of the action to be replaced.

        Returns:
        None
        """
        if by_index:
            i = by_index
        elif by_uuid:
            i = [
                i
                for i, A in enumerate(list(self.action_dq))
                if A.action_uuid == by_uuid
            ][0]
        elif by_action_order:
            i = [
                i
                for i, A in enumerate(list(self.action_dq))
                if A.action_order == by_action_order
            ][0]
        else:
            LOGGER.info("No arguments given for locating existing action to replace.")
            return None
        # get action_order of selected action which gets replaced
        current_action_order = self.action_dq[i].action_order
        new_action = sup_action
        new_action.action_order = current_action_order
        self.action_dq.insert(i, new_action)
        del self.action_dq[i + 1]

    def append_action(self, sup_action: Action):
        """Add action to end of current action queue."""
        if len(self.action_dq) == 0:
            last_action_order = (
                self.globalstatusmodel.counter_dispatched_actions[
                    self.active_experiment.experiment_uuid
                ]
                - 1
            )
            if last_action_order < 0:
                # no action was dispatched yet
                last_action_order = 0
        else:
            last_action_order = self.action_dq[-1].action_order

        new_action_order = last_action_order + 1
        new_action = sup_action
        new_action.action_uuid = gen_uuid()
        new_action.action_order = new_action_order
        self.action_dq.append(new_action)

    async def finish_active_sequence(self):
        """
        Completes the currently active sequence by performing the following steps:

        1. Waits for all actions to complete using `orch_wait_for_all_actions`.
        2. Updates the status of the active sequence from `HloStatus.active` to `HloStatus.finished`.
        3. Writes the active sequence to a persistent storage using `write_seq`.
        4. Deep copies the active sequence to `last_sequence`.
        5. Updates the local buffer with the sequence UUID, name, and status.
        6. Resets the active sequence and related counters.
        7. Clears the dispatched actions counter in the global status model.
        8. Initiates a task to move the sequence directory if a database server exists.

        This method ensures that the sequence is properly finalized and all related
        resources are cleaned up.
        """
        await self.orch_wait_for_all_actions()
        if self.active_sequence is not None:
            self.replace_status(
                status_list=self.active_sequence.sequence_status,
                old_status=HloStatus.active,
                new_status=HloStatus.finished,
            )
            await self.write_seq(self.active_sequence)
            self.last_sequence = deepcopy(self.active_sequence)
            await self.put_lbuf(
                {
                    self.active_sequence.sequence_uuid: {
                        "sequence_name": self.active_sequence.sequence_name,
                        "status": "finished",
                    }
                }
            )
            self.active_sequence = None
            self.active_seq_exp_counter = 0
            self.globalstatusmodel.counter_dispatched_actions = {}
            # DB server call to finish_yml if DB exists
            self.aloop.create_task(move_dir(self.last_sequence, base=self))

    async def finish_active_experiment(self):
        """
        Finalizes the currently active experiment by performing the following steps:

        1. Waits for all actions to complete.
        2. Stops any non-blocking action executors.
        3. Updates the status of the active experiment to 'finished'.
        4. Adds the finished experiment to the active sequence.
        5. Writes the updated sequence and experiment data to storage.
        6. Initiates a task to move the experiment directory if a database server exists.

        This method ensures that all necessary cleanup and state updates are performed
        before marking the experiment as finished and moving on to the next one.
        """
        # we need to wait for all actions to finish first
        await self.orch_wait_for_all_actions()
        while len(self.nonblocking) > 0:
            LOGGER.info(
                f"Stopping non-blocking action executors ({len(self.nonblocking)})"
            )
            await self.clear_nonblocking()
            await asyncio.sleep(1)
        if self.active_experiment is not None:
            LOGGER.info(
                f"finished exp uuid is: {self.active_experiment.experiment_uuid}, adding matching acts to it"
            )
            await self.put_lbuf(
                {
                    self.active_experiment.experiment_uuid: {
                        "experiment_name": self.active_experiment.experiment_name,
                        "status": "finished",
                    }
                }
            )

            self.active_experiment.actionmodel_list = []

            # TODO use exp uuid to filter actions?
            self.active_experiment.actionmodel_list = (
                self.globalstatusmodel.finish_experiment(
                    exp_uuid=self.active_experiment.experiment_uuid
                )
            )
            # set exp status to finished
            self.replace_status(
                status_list=self.active_experiment.experiment_status,
                old_status=HloStatus.active,
                new_status=HloStatus.finished,
            )

            # add finished exp to seq
            # !!! add to experimentmodel_list
            # not to experiment_list !!!!
            self.active_sequence.experimentmodel_list.append(
                deepcopy(self.active_experiment.get_exp())
            )

            # write new updated seq
            await self.write_active_sequence_seq()

            # write final exp
            await self.write_exp(self.active_experiment)

            self.last_experiment = deepcopy(self.active_experiment)
            self.active_experiment = None

            # DB server call to finish_yml if DB exists
            self.aloop.create_task(move_dir(self.last_experiment, base=self))

    async def write_active_experiment_exp(self):
        """
        Asynchronously writes the active experiment data to the experiment log.

        This method calls the `write_exp` method with the current active experiment
        data to log it.

        Returns:
            None
        """
        await self.write_exp(self.active_experiment)

    async def write_active_sequence_seq(self):
        """
        Asynchronously writes the active sequence to storage.

        If the active sequence experiment counter is greater than 1, it appends
        the current active experiment to the active sequence. Otherwise, it writes
        the active sequence directly.

        Returns:
            None
        """
        if self.active_seq_exp_counter > 1:
            active_exp = self.active_experiment.get_exp()
            await self.append_exp_to_seq(active_exp, self.active_sequence)
        else:
            await self.write_seq(self.active_sequence)

    async def shutdown(self):
        """
        Asynchronously shuts down the server by performing the following actions:

        1. Detaches all subscribers.
        2. Cancels the status logger.
        3. Cancels the NTP syncer.
        4. Cancels the status subscriber.

        This method ensures that all ongoing tasks are properly terminated and resources are released.
        """
        await self.detach_subscribers()
        self.status_logger.cancel()
        self.ntp_syncer.cancel()
        self.status_subscriber.cancel()

    async def update_operator(self, msg):
        """
        Asynchronously updates the operator with a given message.

        Args:
            msg: The message to be sent to the operator.

        Returns:
            None

        Raises:
            None
        """
        if self.op_enabled and self.orch_op:
            await self.orch_op.update_q.put(msg)

    def start_wait(self, active: Active):
        """
        Initiates and starts an asynchronous wait task for the given active object.

        Args:
            active (Active): The active object for which the wait task is to be started.

        Returns:
            None
        """
        self.wait_task = asyncio.create_task(self.dispatch_wait_task(active))

    async def dispatch_wait_task(self, active: Active, print_every_secs: int = 5):
        """
        Handles long wait actions as a separate task to prevent HTTP timeout.

        Args:
            active (Active): The active action instance containing action parameters.
            print_every_secs (int, optional): Interval in seconds to print wait status. Defaults to 5.

        Returns:
            finished_action: The result of the finished action.

        """
        # handle long waits as a separate task so HTTP timeout doesn't occur
        waittime = active.action.action_params["waittime"]
        LOGGER.info(" ... wait action:")
        self.current_wait_ts = time.time()
        last_print_time = self.current_wait_ts
        check_time = self.current_wait_ts
        while check_time - self.current_wait_ts < waittime:
            if check_time - last_print_time > print_every_secs - 0.01:
                LOGGER.info(
                    f" ... orch waited {(check_time-self.current_wait_ts):.1f} sec / {waittime:.1f} sec"
                )
                last_print_time = check_time
            await asyncio.sleep(0.01)  # 10 msec sleep
            check_time = time.time()
        LOGGER.info(" ... wait action done")
        finished_action = await active.finish()
        self.last_wait_ts = check_time
        return finished_action

    async def active_action_monitor(self):
        """
        Monitors the status of active actions in a loop and stops the process if any
        required endpoints become unavailable.

        This asynchronous method continuously checks the status of active actions
        and verifies the availability of required endpoints. If any endpoints are
        found to be unavailable, it stops the process and updates the operator.

        The method performs the following steps in a loop:
        1. Checks if the loop state is started.
        2. Retrieves the list of active endpoints.
        3. Verifies the availability of unique active endpoints.
        4. If any endpoints are unavailable, stops the process and updates the operator.
        5. Sleeps for a specified heartbeat interval before repeating the loop.

        Attributes:
            globalstatusmodel (GlobalStatusModel): The global status model containing
                the loop state and active actions.
            heartbeat_interval (int): The interval (in seconds) to wait between each
                iteration of the monitoring loop.
            current_stop_message (str): The message to display when stopping the process.

        Returns:
            None
        """
        while True:
            if self.globalstatusmodel.loop_state == LoopStatus.started:
                active_endpoints = [
                    actmod.url for actmod in self.globalstatusmodel.active_dict.values()
                ]
                if active_endpoints:
                    unique_endpoints = list(set(active_endpoints))
                    _, unavail = await endpoints_available(unique_endpoints)
                    bad_ends = [
                        "/".join(x.strip("/").split("/")[-2:]) for x, _ in unavail
                    ]
                    bad_ends = [x for x in bad_ends if x not in self.ignore_heartbeats]
                    if bad_ends:
                        self.current_stop_message = (
                            f"{', '.join(bad_ends)} endpoints are unavailable"
                        )
                        LOGGER.warning(
                            (f"{', '.join(bad_ends)} endpoints are unavailable")
                        )
                        await self.stop()
                        LOGGER.alert(f"ORCH STOPPED ~ {self.current_stop_message}")
                        await self.update_operator(True)
            await asyncio.sleep(self.heartbeat_interval)

    async def ping_action_servers(self):
        """
        Periodically monitor all action servers and return their status.

        This asynchronous method iterates through the configured action servers,
        excluding those with "bokeh" or "demovis" in their configuration, and
        attempts to retrieve their status using the `async_private_dispatcher`.
        The status of each server is summarized and returned in a dictionary.

        Returns:
            dict: A dictionary where the keys are server keys and the values are
                  tuples containing the status string ("busy", "idle", or "unreachable")
                  and the driver status.

        Raises:
            aiohttp.client_exceptions.ClientConnectorError: If there is an issue
                                                            connecting to a server.
        """
        status_summary = {}
        for serv_key, serv_dict in self.world_cfg["servers"].items():
            if "ignore_heartbeats" in serv_dict.get("params", {}):
                continue
            if "bokeh" not in serv_dict and "demovis" not in serv_dict:
                serv_addr = serv_dict["host"]
                serv_port = serv_dict["port"]
                try:
                    response, error_code = await async_private_dispatcher(
                        server_key=serv_key,
                        host=serv_addr,
                        port=serv_port,
                        private_action="get_status",
                        params_dict={
                            "client_servkey": self.server.server_name,
                            "client_host": self.server_cfg["host"],
                            "client_port": self.server_cfg["port"],
                        },
                        json_dict={},
                    )
                    if response is not None and error_code == ErrorCodes.none:
                        busy_endpoints = []
                        driver_status = response.get("_driver_status", "unknown")
                        for endpoint_name, endpoint_dict in response.get(
                            "endpoints", {}
                        ).items():
                            if endpoint_dict["active_dict"]:
                                busy_endpoints.append(endpoint_name)
                        if busy_endpoints:
                            busy_str = ", ".join(busy_endpoints)
                            status_str = f"busy [{busy_str}]"
                        else:
                            status_str = "idle"
                        status_summary[serv_key] = (status_str, driver_status)
                    else:
                        status_summary[serv_key] = ("unreachable", "unknown")
                except aiohttp.client_exceptions.ClientConnectorError:
                    status_summary[serv_key] = ("unreachable", "unknown")
        return status_summary

    async def action_server_monitor(self):
        """
        Monitors the status of action servers in a continuous loop.

        This asynchronous method continuously pings action servers to update their status
        and notifies the operator with the updated status summary at regular intervals
        defined by `heartbeat_interval`.

        The loop runs indefinitely, sleeping for `heartbeat_interval` seconds between
        each iteration.

        Returns:
            None
        """
        while True:
            self.status_summary = await self.ping_action_servers()
            await self.update_operator(True)
            await asyncio.sleep(self.heartbeat_interval)

    def export_queues(self, timestamp_pck: bool = False):
        """
        Exports the current state of various queues and active elements in the orchestrator to a pickle file.

        The function collects the following data from the orchestrator:
        - Sequence queue
        - Experiment queue
        - Action queue
        - Active experiment
        - Last experiment
        - Active sequence
        - Last sequence
        - Active sequence-experiment counter
        - Last action UUID
        - Last dispatched action UUID
        - Last 50 action UUIDs

        The collected data is saved as a dictionary in a pickle file located in the "STATES" directory under the root path specified in the orchestrator's world configuration.

        Returns:
            str: The file path where the pickle file is saved.
        """
        save_dir = self.world_cfg["root"]
        queue_dict = {
            "seq": list(self.sequence_dq),
            "exp": list(self.experiment_dq),
            "act": list(self.action_dq),
            "active_exp": self.active_experiment,
            "last_exp": self.last_experiment,
            "active_seq": self.active_sequence,
            "last_seq": self.last_sequence,
            "active_counter": self.active_seq_exp_counter,
            "last_act": self.last_action_uuid,
            "last_dispatched_act": self.last_dispatched_action_uuid,
            "last_50_act_uuids": self.last_50_action_uuids,
            "last_50_exp_uuids": self.last_50_experiment_uuids,
            "last_50_seq_uuids": self.last_50_sequence_uuids,
            "global_status_model": self.globalstatusmodel,
        }
        if timestamp_pck:
            pck_name = f"queues_{datetime.now().strftime('%Y%m%d.%H%M%S')}.pck"
        else:
            pck_name = "queues.pck"
        save_path = os.path.join(save_dir, "STATES", pck_name)
        pickle.dump(queue_dict, open(save_path, "wb"))
        return save_path

    def import_queues(self, pck_path: Optional[str] = None):
        """
        Imports and restores the state of various queues from a saved pickle file.

        This function attempts to load a previously saved state of action, experiment,
        and sequence queues from a pickle file located at "STATES/queues.pck" within
        the directory specified by `self.orch.world_cfg["root"]`. If the file does not
        exist, or if any of the current queues are not empty, the function will print
        an appropriate message and will not restore the queues.

        Upon successful restoration, the function updates the following attributes of
        `self.orch`:
        - action_dq
        - experiment_dq
        - sequence_dq
        - active_experiment
        - last_experiment
        - active_sequence
        - last_sequence
        - active_seq_exp_counter
        - last_action_uuid
        - last_dispatched_action_uuid
        - last_50_action_uuids

        Returns:
            str: The path to the pickle file used for restoring the queues.
        """
        save_dir = self.world_cfg["root"]
        if pck_path is None:
            save_path = os.path.join(save_dir, "STATES", "queues.pck")
        else:
            save_path = pck_path.strip('"').strip("'")
        if os.path.exists(save_path):
            queue_dict = pickle.load(open(save_path, "rb"))
        else:
            LOGGER.info("Exported queues.pck does not exist. Cannot restore.")
            return save_path
        if self.sequence_dq or self.experiment_dq or self.action_dq:
            LOGGER.info("Existing queues are not empty. Cannot restore.")
        else:
            LOGGER.info("Restoring queues from saved pck.")
            for x in queue_dict["act"]:
                self.action_dq.append(x)
            for x in queue_dict["exp"]:
                self.experiment_dq.append(x)
            for x in queue_dict["seq"]:
                self.sequence_dq.append(x)
            self.active_experiment = queue_dict["active_exp"]
            self.last_experiment = queue_dict["last_exp"]
            self.active_sequence = queue_dict["active_seq"]
            self.last_sequence = queue_dict["last_seq"]
            self.active_seq_exp_counter = queue_dict["active_counter"]
            self.last_action_uuid = queue_dict["last_act"]
            self.last_dispatched_action_uuid = queue_dict["last_dispatched_act"]
            self.last_50_action_uuids = queue_dict["last_50_act_uuids"]
            self.last_50_experiment_uuids = queue_dict["last_50_exp_uuids"]
            self.last_50_sequence_uuids = queue_dict["last_50_seq_uuids"]
            self.globalstatusmodel = queue_dict["globalstatusmodel"]
        return save_path
