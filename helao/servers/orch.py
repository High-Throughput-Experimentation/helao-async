"""Orchestrator class and FastAPI server templating function

TODO:
1. track loaded samples, so we don't have to query; orch can either query PAL server or hold state
2. replace globalexp_params with global state dict and persist state on disk
3. investigate multi-driver servers; orch can request from itself, or try to bypass fastapi endpoint and execute function directly

"""

__all__ = ["Orch"]

import asyncio
import sys
from copy import deepcopy
from typing import List
from uuid import UUID
import json
import traceback
import inspect

import time
from functools import partial
from collections import defaultdict
from queue import Queue

import aiohttp
import colorama
from fastapi import WebSocket
from bokeh.server.server import Server

from helaocore.models.action_start_condition import ActionStartCondition
from helaocore.models.hlostatus import HloStatus
from helaocore.models.server import ActionServerModel, GlobalStatusModel
from helaocore.models.orchstatus import OrchStatus, LoopStatus, LoopIntent
from helaocore.error import ErrorCodes

from helao.servers.operator.bokeh_operator import BokehOperator
from helao.servers.vis import HelaoVis
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
from helao.drivers.data.sync_driver import HelaoSyncer

# ANSI color codes converted to the Windows versions
# strip colors if stdout is redirected
colorama.init(strip=not sys.stdout.isatty())


class Orch(Base):
    """Base class for async orchestrator with trigger support and pushed status update.

    Websockets are not used for critical communications. Orch will attach to all action
    servers listed in a config and maintain a dict of {serverName: status}, which is
    updated by POST requests from action servers. Orch will simultaneously dispatch as
    many action_dq as possible in action queue until it encounters any of the following
    conditions:
      (1) last executed action is final action in queue
      (2) last executed action is blocking
      (3) next action to execute is preempted
      (4) next action is on a busy action server
    which triggers a temporary async task to monitor the action server status dict until
    all conditions are cleared.

    POST requests from action servers are added to a multisubscriber queue and consumed
    by a self-subscriber task to update the action server status dict and log changes.
    """

    def __init__(self, fastapp):
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
        self.print_message(f"Got exception from coroutine: {context}", error=True)
        exc = context.get("exception")
        self.print_message(
            f"{traceback.format_exception(type(exc), exc, exc.__traceback__)}",
            error=True,
        )
        self.print_message("setting E-STOP flag on active actions")
        for _, active in self.actives.items():
            active.set_estop()

    def myinit(self):
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

        if self.op_enabled:
            self.start_operator()
        self.status_subscriber = asyncio.create_task(self.subscribe_all())
        self.globstat_broadcaster = asyncio.create_task(self.globstat_broadcast_task())
        self.heartbeat_monitor = asyncio.create_task(self.active_action_monitor())
        self.driver_monitor = asyncio.create_task(self.action_server_monitor())

    def endpoint_queues_init(self):
        for urld in self.fast_urls:
            if urld.get("path", "").startswith(f"/{self.server.server_name}/"):
                self.endpoint_queues[urld["name"]] = Queue()

    def register_action_uuid(self, action_uuid):
        while len(self.last_50_action_uuids) >= 50:
            self.last_50_action_uuids.pop(0)
        self.last_50_action_uuids.append(action_uuid)

    def track_action_uuid(self, action_uuid):
        self.last_dispatched_action_uuid = action_uuid

    def start_operator(self):
        servHost = self.server_cfg["host"]
        servPort = self.server_params.get("bokeh_port", self.server_cfg["port"] + 1000)
        servPy = "BokehOperator"

        self.bokehapp = Server(
            {f"/{servPy}": partial(self.makeBokehApp, orch=self)},
            port=servPort,
            address=servHost,
            allow_websocket_origin=[f"{servHost}:{servPort}"],
        )
        self.print_message(f"started bokeh server {self.bokehapp}", info=True)
        self.bokehapp.start()
        if self.server_params.get("launch_browser", False):
            self.bokehapp.io_loop.add_callback(self.bokehapp.show, f"/{servPy}")
        # bokehapp.io_loop.start()

    def makeBokehApp(self, doc, orch):
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

    async def wait_for_interrupt(self):
        """interrupt function which waits for any interrupt
        currently only for status changes
        but this can be extended in the future"""

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
        #         self.print_message("This message will print again after 10 seconds.")
        #         self.last_interrupt = time.time()
        #     return None

        self.last_interrupt = time.time()
        # if not empty clear it
        while not self.interrupt_q.empty():
            interrupt = await self.interrupt_q.get()
            if isinstance(interrupt, GlobalStatusModel):
                self.incoming = interrupt
                await self.globstat_q.put(interrupt.as_json())
        return None

    async def subscribe_all(self, retry_limit: int = 15):
        """Subscribe to all fastapi servers in config."""
        fails = []
        for serv_key, serv_dict in self.world_cfg["servers"].items():
            if "bokeh" not in serv_dict and "demovis" not in serv_dict:
                self.print_message(f"trying to subscribe to {serv_key} status")

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
                    except aiohttp.client_exceptions.ClientConnectorError as err:
                        self.print_message(
                            f"failed to subscribe to "
                            f"{serv_key} at "
                            f"{serv_addr}:{serv_port}, {err}"
                            "trying again in 2 seconds",
                            info=True,
                        )
                        await asyncio.sleep(2)

                if success:
                    self.print_message(
                        f"Subscribed to {serv_key} at {serv_addr}:{serv_port}"
                    )
                else:
                    fails.append(serv_key)
                    self.print_message(
                        f"Failed to subscribe to {serv_key} at {serv_addr}:{serv_port}. Check connection."
                    )

        if len(fails) == 0:
            self.init_success = True
        else:
            self.print_message(
                "Orchestrator cannot action experiment_dq unless "
                "all FastAPI servers in config file are accessible."
            )

    async def update_nonblocking(
        self, actionmodel: Action, server_host: str, server_port: int
    ):
        """Update method for action server to push non-blocking action ids."""
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
        """Clear method for orch to purge non-blocking action ids."""
        resp_tups = []
        for server_key, exec_id, server_host, server_port in self.nonblocking:
            self.print_message(
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

    async def update_status(self, actionservermodel: ActionServerModel = None):
        """Dict update method for action server to push status messages."""

        self.print_message(
            "received status from server:", actionservermodel.action_server.server_name
        )

        if actionservermodel is None:
            return False

        async with self.aiolock:
            # update GlobalStatusModel with new ActionServerModel
            # and sort the new status dict
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
                self.print_message(
                    f"running_states: {self.globalstatusmodel.active_dict}"
                )

            # now push it to the interrupt_q
            await self.interrupt_q.put(self.globalstatusmodel)
            await self.update_operator(True)
            # await self.globstat_q.put(self.globalstatusmodel.as_json())

            return True

    async def ws_globstat(self, websocket: WebSocket):
        """Subscribe to global status queue and send messages to websocket client."""
        self.print_message("got new global status subscriber")
        await websocket.accept()
        gs_sub = self.globstat_q.subscribe()
        try:
            async for globstat_msg in gs_sub:
                await websocket.send_text(json.dumps(globstat_msg.as_dict()))
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            self.print_message(
                f"Data websocket client {websocket.client[0]}:{websocket.client[1]} disconnected. {repr(e), tb,}",
                warning=True,
            )
            if gs_sub in self.globstat_q.subscribers:
                self.globstat_q.remove(gs_sub)

    async def globstat_broadcast_task(self):
        """Consume globstat_q. Does nothing for now."""
        async for _ in self.globstat_q.subscribe():
            await asyncio.sleep(0.01)

    def unpack_sequence(
        self, sequence_name: str, sequence_params
    ) -> List[Experiment]:
        if sequence_name in self.sequence_lib:
            return self.sequence_lib[sequence_name](**sequence_params)
        else:
            return []

    def get_sequence_codehash(self, sequence_name: str) -> UUID:
        return self.sequence_codehash_lib[sequence_name]

    async def seq_unpacker(self):
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

    async def loop_task_dispatch_sequence(self) -> ErrorCodes:
        if self.sequence_dq:
            self.print_message("getting new sequence from sequence_dq")
            self.active_sequence = self.sequence_dq.popleft()
            self.print_message(
                f"new active sequence is {self.active_sequence.sequence_name}"
            )
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
            for k, v in self.active_sequence.from_globalexp_params.items():
                self.print_message(f"{k}:{v}")
                if k in self.global_params:
                    self.active_sequence.sequence_params[v] = self.global_params[k]

            # if experiment_plan_list is empty, unpack sequence,
            # otherwise operator already populated experiment_plan_list
            if True:
                self.active_sequence.experiment_plan_list = self.unpack_sequence(
                    self.active_sequence.sequence_name,
                    self.active_sequence.sequence_params,
                )

            self.seq_model = self.active_sequence.get_seq()
            await self.write_seq(self.active_sequence)
            if self.use_db:
                try:
                    meta_s3_key = f"sequence/{self.seq_model.sequence_uuid}.json"
                    self.print_message(
                        f"uploading initial active sequence json to s3 ({meta_s3_key})"
                    )
                    await self.syncer.to_s3(
                        self.seq_model.clean_dict(strip_private=True), meta_s3_key
                    )
                except Exception as e:
                    self.print_message(
                        f"Error uploading initial active sequence json to s3: {e}",
                        error=True,
                    )

            self.aloop.create_task(self.seq_unpacker())
            await asyncio.sleep(1)

        else:
            self.print_message("sequence queue is empty, cannot start orch loop")

            self.globalstatusmodel.loop_state = LoopStatus.stopped
            await self.intend_none()

        return ErrorCodes.none

    async def loop_task_dispatch_experiment(self) -> ErrorCodes:
        self.print_message("action_dq is empty, getting new actions")
        # wait for all actions in last/active experiment to finish
        # self.print_message("finishing last active experiment first")
        # await self.finish_active_experiment()

        # self.print_message("getting new experiment to fill action_dq")
        # generate uids when populating,
        # generate timestamp when acquring
        self.active_experiment = self.experiment_dq.popleft()
        self.active_experiment.orch_key = self.orch_key
        self.active_experiment.orch_host = self.orch_host
        self.active_experiment.orch_port = self.orch_port
        self.active_experiment.sequence_uuid = self.active_sequence.sequence_uuid
        self.active_seq_exp_counter += 1

        # self.print_message("copying global vars to experiment")
        # copy requested global param to experiment params
        for k, v in self.active_experiment.from_globalexp_params.items():
            self.print_message(f"{k}:{v}")
            if k in self.global_params:
                self.active_experiment.experiment_params[v] = self.global_params[k]

        self.print_message(
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

        if isinstance(exp_return, list):
            unpacked_acts = exp_return
        elif isinstance(exp_return, Experiment):
            self.active_experiment = exp_return
            unpacked_acts = self.active_experiment.action_plan

        self.active_experiment.experiment_codehash = self.experiment_codehash_lib[
            self.active_experiment.experiment_name
        ]
        if unpacked_acts is None:
            self.print_message("no actions in experiment", error=True)
            self.action_dq = zdeque([])
            return ErrorCodes.none

        process_order_groups = defaultdict(list)
        process_count = 0
        init_process_uuids = [gen_uuid()]
        # self.print_message("setting action order")

        ## actions are not instantiated until experiment is unpacked
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
            self.action_dq.append(act)
        if process_order_groups:
            self.active_experiment.process_order_groups = process_order_groups
            process_list = init_process_uuids[: len(process_order_groups)]
            self.active_experiment.process_list = process_list
        # loop through actions again

        # self.print_message("adding unpacked actions to action_dq")
        self.print_message(f"got: {self.action_dq}")
        self.print_message(
            f"optional params: {self.active_experiment.experiment_params}"
        )

        # write a temporary exp
        self.exp_model = self.active_experiment.get_exp()
        await self.write_active_experiment_exp()
        if self.use_db:
            try:
                meta_s3_key = f"experiment/{self.exp_model.experiment_uuid}.json"
                self.print_message(
                    f"uploading initial active experiment json to s3 ({meta_s3_key})"
                )
                await self.syncer.to_s3(
                    self.exp_model.clean_dict(strip_private=True), meta_s3_key
                )
            except Exception as e:
                self.print_message(
                    f"Error uploading initial active experiment json to s3: {e}",
                    error=True,
                )
        return ErrorCodes.none

    async def loop_task_dispatch_action(self) -> ErrorCodes:
        # self.print_message("actions in action_dq, processing them")
        if self.globalstatusmodel.loop_intent == LoopIntent.stop:
            self.print_message("stopping orchestrator")
            # monitor status of running action_dq, then end loop
            while self.globalstatusmodel.loop_state != LoopStatus.stopped:
                # wait for all orch actions to finish first
                await self.orch_wait_for_all_actions()
                if self.globalstatusmodel.orch_state == OrchStatus.idle:
                    await self.intend_none()
                    self.print_message("got stop")
                    self.globalstatusmodel.loop_state = LoopStatus.stopped
                    break

        elif self.globalstatusmodel.loop_intent == LoopIntent.skip:
            # clear action queue, forcing next experiment
            self.action_dq.clear()
            await self.intend_none()
            self.print_message("skipping to next experiment")
        elif self.globalstatusmodel.loop_intent == LoopIntent.estop:
            self.action_dq.clear()
            await self.intend_none()
            self.print_message("estopping")
            self.globalstatusmodel.loop_state = LoopStatus.estopped
        else:
            # all action blocking is handled like preempt,
            # check Action requirements
            A = self.action_dq.popleft()

            # see async_action_dispatcher for unpacking
            if A.start_condition == ActionStartCondition.no_wait:
                self.print_message("orch is dispatching an unconditional action")
            else:
                if A.start_condition == ActionStartCondition.wait_for_endpoint:
                    self.print_message(
                        "orch is waiting for endpoint to become available"
                    )
                    endpoint_free = self.globalstatusmodel.endpoint_free(
                        action_server=A.action_server, endpoint_name=A.action_name
                    )
                    while not endpoint_free:
                        await self.wait_for_interrupt()
                        endpoint_free = self.globalstatusmodel.endpoint_free(
                            action_server=A.action_server, endpoint_name=A.action_name
                        )
                elif A.start_condition == ActionStartCondition.wait_for_server:
                    self.print_message("orch is waiting for server to become available")
                    server_free = self.globalstatusmodel.server_free(
                        action_server=A.action_server
                    )
                    while not server_free:
                        await self.wait_for_interrupt()
                        server_free = self.globalstatusmodel.server_free(
                            action_server=A.action_server
                        )
                elif A.start_condition == ActionStartCondition.wait_for_orch:
                    self.print_message("orch is waiting for wait action to end")
                    wait_free = self.globalstatusmodel.endpoint_free(
                        action_server=A.orchestrator, endpoint_name="wait"
                    )
                    while not wait_free:
                        await self.wait_for_interrupt()
                        wait_free = self.globalstatusmodel.endpoint_free(
                            action_server=A.orchestrator, endpoint_name="wait"
                        )
                elif A.start_condition == ActionStartCondition.wait_for_previous:
                    self.print_message("orch is waiting for previous action to finish")
                    previous_action_active = (
                        self.last_action_uuid
                        in self.globalstatusmodel.active_dict.keys()
                    )
                    while previous_action_active:
                        await self.wait_for_interrupt()
                        previous_action_active = (
                            self.last_action_uuid
                            in self.globalstatusmodel.active_dict.keys()
                        )
                elif A.start_condition == ActionStartCondition.wait_for_all:
                    await self.orch_wait_for_all_actions()

                else:  # unsupported value
                    await self.orch_wait_for_all_actions()

            # self.print_message("copying global vars to action")
            # copy requested global param to action params
            for k, v in A.from_globalexp_params.items():
                self.print_message(f"{k}:{v}")
                if k in self.global_params:
                    A.action_params[v] = self.global_params[k]

            actserv_exists, _ = await endpoints_available([A.url])
            if not actserv_exists:
                stop_message = f"{A.url} is not available, orchestrator will stop. Rectify action server then resume orchestrator run."
                self.stop_message = stop_message
                await self.stop()
                self.action_dq.insert(0, A)
                await self.update_operator(True)
                return ErrorCodes.none

            self.print_message(
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
                    self.print_message(
                        f"Error while dispatching action {A.action_name}: {e}"
                    )
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
                        self.stop_message = stop_message
                        await self.stop()
                        self.print_message(f"Re-queuing {A.action_name}")
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
                self.print_message(
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
                    if (
                        HloStatus.active in actstats
                        and resuuid not in self.globalstatusmodel.active_dict
                    ):
                        self.globalstatusmodel.active_dict[resuuid] = resmod
                        self.globalstatusmodel.server_dict[srvkey].endpoints[
                            actname
                        ].active_dict[resuuid] = resmod
                    else:
                        for actstat in actstats:
                            try:
                                if (
                                    resuuid
                                    in self.globalstatusmodel.nonactive_dict[actstat]
                                ):
                                    break
                                self.globalstatusmodel.nonactive_dict[actstat][
                                    resuuid
                                ] = resmod
                                self.globalstatusmodel.server_dict[srvkey].endpoints[
                                    actname
                                ].nonactive_dict[actstat][resuuid] = resmod
                            except:
                                self.print_message(
                                    f"{actstat} not found in globalstatus.nonactive_dict"
                                )

            try:
                result_action = Action(**result_actiondict)
            except Exception as e:
                tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
                self.print_message(
                    f"returned result is not a valid Action BaseModel: {repr(e), tb,}",
                    error=True,
                )
                return ErrorCodes.critical

            if result_action.error_code is not ErrorCodes.none:
                self.print_message(
                    f"Action result for "
                    f"'{result_action.action_name}' on "
                    f"'{result_action.action_server.disp_name()}' "
                    f"has error code: "
                    f"{result_action.error_code}",
                    error=True,
                )
                stop_reason = f"{result_action.action_name} on {result_action.action_server.disp_name()} returned an error"
                await self.estop_loop(stop_reason)
                return result_action.error_code

            if (
                result_action.to_globalexp_params
                and result_action.orch_key == self.orch_key
                and result_action.orch_host == self.orch_host
                and int(result_action.orch_port) == int(self.orch_port)
            ):
                if isinstance(result_action.to_globalexp_params, list):
                    # self.print_message(
                    #     f"copying global vars {', '.join(result_action.to_globalexp_params)} back to experiment"
                    # )
                    for k in result_action.to_globalexp_params:
                        if k in result_action.action_params:
                            self.print_message(f"updating {k} in global vars")
                            self.global_params[k] = result_action.action_params[k]
                        elif k in result_action.action_output:
                            self.print_message(f"updating {k} in global vars")
                            self.global_params[k] = result_action.action_output[k]
                        else:
                            self.print_message(
                                f"key {k} not found in action output or params"
                            )
                elif isinstance(result_action.to_globalexp_params, dict):
                    # self.print_message(
                    #     f"copying global vars {', '.join(result_action.to_globalexp_params.keys())} back to experiment"
                    # )
                    for k1, k2 in result_action.to_globalexp_params.items():
                        if k1 in result_action.action_params:
                            self.print_message(f"updating {k2} in global vars")
                            self.global_params[k2] = result_action.action_params[k1]
                        elif k1 in result_action.action_output:
                            self.print_message(f"updating {k2} in global vars")
                            self.global_params[k2] = result_action.action_output[k1]
                        else:
                            self.print_message(
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
        """Parse experiment and action queues,
        and dispatch action_dq while tracking run state flags."""
        self.print_message("--- started operator orch ---")
        self.print_message(f"current orch status: {self.globalstatusmodel.orch_state}")
        # clause for resuming paused action list
        # self.print_message(f"current orch sequences: {list(self.sequence_dq)[:5]}... ({len(self.sequence_dq)})")
        # self.print_message(f"current orch descisions: {list(self.experiment_dq)[:5]}... ({len(self.experiment_dq)})")
        # self.print_message(f"current orch actions: {list(self.action_dq)[:5]}... ({len(self.action_dq)})")
        # self.print_message("--- resuming orch loop now ---")

        self.globalstatusmodel.loop_state = LoopStatus.started

        try:
            while self.globalstatusmodel.loop_state == LoopStatus.started and (
                self.action_dq or self.experiment_dq or self.sequence_dq
            ):
                self.print_message(
                    f"current content of action_dq: {[self.action_dq[i] for i in range(min(len(self.action_dq), 5))]}... ({len(self.action_dq)})"
                )
                self.print_message(
                    f"current content of experiment_dq: {[self.experiment_dq[i] for i in range(min(len(self.experiment_dq), 5))]}... ({len(self.experiment_dq)})"
                )
                self.print_message(
                    f"current content of sequence_dq: {[self.sequence_dq[i] for i in range(min(len(self.sequence_dq), 5))]}... ({len(self.sequence_dq)})"
                )
                # check driver states
                na_drivers = [
                    k for k, (_, v) in self.status_summary.items() if v == "unknown"
                ]
                if na_drivers:
                    na_driver_retries = 0
                    while na_driver_retries < 5 and na_drivers:
                        self.print_message(
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
                        await self.stop()

                if (
                    self.globalstatusmodel.loop_state == LoopStatus.estopped
                    or self.globalstatusmodel.loop_intent == LoopIntent.estop
                ):
                    await self.estop_loop()
                elif self.action_dq:
                    self.print_message("!!!dispatching next action", info=True)
                    error_code = await self.loop_task_dispatch_action()
                    while (
                        self.last_dispatched_action_uuid
                        not in self.last_50_action_uuids
                    ):
                        await asyncio.sleep(0.2)
                    if self.action_dq and self.step_thru_actions:
                        self.current_stop_message = "Step-thru actions is enabled, use 'Start Orch' to dispatch next action."
                        await self.stop()
                    elif (
                        not self.action_dq
                        and self.experiment_dq
                        and self.step_thru_experiments
                    ):
                        self.current_stop_message = "Step-thru experiments is enabled, use 'Start Orch' to dispatch next experiment."
                        await self.stop()
                    elif (
                        not self.action_dq
                        and not self.experiment_dq
                        and self.sequence_dq
                        and self.step_thru_sequences
                    ):
                        self.current_stop_message = "Step-thru sequences is enabled, use 'Start Orch' to dispatch next sequence."
                        await self.stop()
                elif self.experiment_dq:
                    self.print_message(
                        "!!!waiting for all actions to finish before dispatching next experiment",
                        info=True,
                    )
                    self.print_message("finishing last experiment")
                    await self.finish_active_experiment()
                    self.print_message("!!!dispatching next experiment", info=True)
                    error_code = await self.loop_task_dispatch_experiment()
                # if no acts and no exps, disptach next sequence
                elif self.sequence_dq:
                    self.print_message(
                        "!!!waiting for all actions to finish before dispatching next sequence",
                        info=True,
                    )
                    self.print_message("finishing last sequence")
                    await self.finish_active_sequence()
                    self.print_message("!!!dispatching next sequence", info=True)
                    error_code = await self.loop_task_dispatch_sequence()
                else:
                    self.print_message("all queues are empty")
                    self.print_message("--- stopping operator orch ---", info=True)
                # check error responses from dispatching this loop iter
                if error_code is not ErrorCodes.none:
                    self.print_message(
                        f"stopping orch with error code: {error_code}", error=True
                    )
                    await self.intend_estop()
                await self.update_operator(True)

            # finish the last exp
            # this wait for all actions in active experiment
            # to finish and then updates the exp with the acts
            if (
                not self.action_dq and self.active_experiment is not None
            ):  # in case of interrupt, don't finish exp
                self.print_message("finishing final experiment")
                await self.finish_active_experiment()
            if (
                not self.experiment_dq
                and not self.action_dq
                and self.active_sequence is not None
            ):  # in case of interrupt, don't finish seq
                self.print_message("finishing final sequence")
                await self.finish_active_sequence()

            if self.globalstatusmodel.loop_state != OrchStatus.estopped:
                self.globalstatusmodel.loop_state = LoopStatus.stopped
            await self.intend_none()
            await self.update_operator(True)
            return True

        # except asyncio.CancelledError:
        #     self.print_message("serious orch exception occurred",error = True)
        #     return False

        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            self.print_message("serious orch exception occurred", error=True)
            self.print_message(f"ERROR: {repr(e), tb,}", error=True)
            await self.estop_loop()
            return False

    async def orch_wait_for_all_actions(self):
        """waits for all action assigned to this orch to finish"""

        # self.print_message("orch is waiting for all action_dq to finish")

        # some actions are active
        # we need to wait for them to finish
        while not self.globalstatusmodel.actions_idle():
            if time.time() - self.last_interrupt > 10.0:
                self.print_message(
                    "some actions are still active, waiting for status update"
                )
            # we check again once the active action
            # updates its status again
            await self.wait_for_interrupt()
            # self.print_message("got status update")
            # we got a status update
        # self.print_message("all actions are idle")

    async def start(self):
        """Begin experimenting experiment and action queues."""
        if self.globalstatusmodel.loop_state == LoopStatus.stopped:
            if (
                self.action_dq
                or self.experiment_dq
                or self.sequence_dq
                or self.active_sequence is not None
            ):  # resume actions from a paused run
                await self.start_loop()
            else:
                self.print_message("experiment list is empty")
        else:
            self.print_message("already running")
        self.current_stop_message = ""
        await self.update_operator(True)

    async def start_loop(self):
        if self.globalstatusmodel.loop_state == LoopStatus.stopped:
            self.print_message("starting orch loop")
            self.loop_task = asyncio.create_task(self.dispatch_loop_task())
        elif self.globalstatusmodel.loop_state == LoopStatus.estopped:
            self.print_message(
                "E-STOP flag was raised, clear E-STOP before starting.", error=True
            )
        else:
            self.print_message("loop already started.")
        return self.globalstatusmodel.loop_state

    async def estop_loop(self, reason: str = ""):
        reason_suffix = f"{' ' + reason if reason else ''}"
        self.print_message("estopping orch" + reason_suffix, error=True)

        # set globalstatusmodel.loop_state to estop
        self.globalstatusmodel.loop_state = LoopStatus.estopped

        # force stop all running actions in the status dict (for this orch)
        await self.estop_actions(switch=True)

        # reset loop intend
        await self.intend_none()

        self.current_stop_message = "E-STOP" + reason_suffix
        await self.update_operator(True)

    async def stop_loop(self):
        await self.intend_stop()

    async def estop_actions(self, switch: bool):
        self.print_message("estopping all servers", info=True)

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
            self.print_message(
                f"Sending estop={switch} request to {actionservermodel.action_server.disp_name()}",
                info=True,
            )
            try:
                _ = await async_action_dispatcher(self.world_cfg, A)
            except Exception as e:
                tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
                # no estop endpoint for this action server?
                self.print_message(
                    f"estop for {actionservermodel.action_server.disp_name()} failed with: {repr(e), tb,}",
                    error=True,
                )

    async def skip(self):
        """Clear the present action queue while running."""
        if self.globalstatusmodel.loop_state == LoopStatus.started:
            await self.intend_skip()
        else:
            self.print_message("orchestrator not running, clearing action queue")
            self.action_dq.clear()

    async def intend_skip(self):
        self.globalstatusmodel.loop_intent = LoopIntent.skip
        await self.interrupt_q.put(self.globalstatusmodel.loop_intent)

    async def stop(self):
        """Stop experimenting experiment and
        action queues after current actions finish."""
        if self.globalstatusmodel.loop_state == LoopStatus.started:
            await self.intend_stop()
        elif self.globalstatusmodel.loop_state == LoopStatus.estopped:
            self.print_message("orchestrator E-STOP flag was raised; nothing to stop")
        else:
            self.print_message("orchestrator is not running")

    async def intend_stop(self):
        self.globalstatusmodel.loop_intent = LoopIntent.stop
        await self.interrupt_q.put(self.globalstatusmodel.loop_intent)

    async def intend_estop(self):
        self.globalstatusmodel.loop_intent = LoopIntent.estop
        await self.interrupt_q.put(self.globalstatusmodel.loop_intent)

    async def intend_none(self):
        self.globalstatusmodel.loop_intent = LoopIntent.none
        await self.interrupt_q.put(self.globalstatusmodel.loop_intent)

    async def clear_estop(self):
        # which were estopped first
        self.print_message("clearing estopped uuids")
        self.globalstatusmodel.clear_in_finished(hlostatus=HloStatus.estopped)
        # release estop for all action servers
        await self.estop_actions(switch=False)
        # set orch status from estop back to stopped
        self.globalstatusmodel.loop_state = LoopStatus.stopped
        await self.interrupt_q.put("cleared_estop")

    async def clear_error(self):
        # currently only resets the error dict
        self.print_message("clearing errored uuids")
        self.globalstatusmodel.clear_in_finished(hlostatus=HloStatus.errored)
        await self.interrupt_q.put("cleared_errored")

    async def clear_sequences(self):
        self.print_message("clearing sequence queue")
        self.sequence_dq.clear()

    async def clear_experiments(self):
        self.print_message("clearing experiment queue")
        self.experiment_dq.clear()

    async def clear_actions(self):
        self.print_message("clearing action queue")
        self.action_dq.clear()

    async def add_sequence(
        self,
        sequence: Sequence,
    ):
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
        at_index: int = None,
    ):
        seq_dict = seq.model_dump()
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
            # self.print_message(f"experiment {D.experiment_name} prepended to queue")
        else:
            self.experiment_dq.append(D)
            # self.print_message(f"experiment {D.experiment_name} appended to queue")
        return D.experiment_uuid

    def list_sequences(self, limit=10):
        """Return the current queue of sequence_dq."""
        return [
            self.sequence_dq[i].get_seq()
            for i in range(min(len(self.sequence_dq), limit))
        ]

    def list_experiments(self, limit=10):
        """Return the current queue of experiment_dq."""
        return [
            self.experiment_dq[i].get_exp()
            for i in range(min(len(self.experiment_dq), limit))
        ]

    def list_all_experiments(self):
        """Return all experiments in queue."""
        return [
            (i, D.get_exp().experiment_name) for i, D in enumerate(self.experiment_dq)
        ]

    def drop_experiment_inds(self, inds: List[int]):
        """Drop experiments by index."""
        for i in sorted(inds, reverse=True):
            del self.experiment_dq[i]
        return self.list_all_experiments()

    def get_experiment(self, last=False) -> Experiment:
        """Return the active or last experiment."""
        experiment = self.last_experiment if last else self.active_experiment
        if experiment is not None:
            return experiment.get_exp()
        return {}

    def get_sequence(self, last=False) -> Sequence:
        """Return the active or last experiment."""
        sequence = self.last_sequence if last else self.active_sequence
        if sequence is not None:
            return sequence.get_seq()
        return {}

    def list_active_actions(self):
        """Return the current queue running actions."""
        return [
            statusmodel
            for uuid, statusmodel in self.globalstatusmodel.active_dict.items()
        ]

    def list_actions(self, limit=10):
        """Return the current queue of action_dq."""
        return [
            self.action_dq[i].get_actmodel()
            for i in range(min(len(self.action_dq), limit))
        ]

    def supplement_error_action(self, check_uuid: UUID, sup_action: Action):
        """Insert action at front of action queue with
        subversion of errored action,
        inherit parameters if desired."""

        error_uuids = self.globalstatusmodel.find_hlostatus_in_finished(
            hlostatus=HloStatus.errored,
        )
        if not error_uuids:
            self.print_message("There are no error statuses to replace")
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
                self.print_message(
                    f"uuid {check_uuid} not found in list of error statuses:"
                )
                self.print_message(", ".join(self.error_uuids))

    def remove_experiment(self, by_index: int = None, by_uuid: UUID = None):
        """Remove experiment in list by enumeration index or uuid."""
        if by_index is not None:
            i = by_index
        elif by_uuid is not None:
            i = [
                i
                for i, D in enumerate(list(self.experiment_dq))
                if D.experiment_uuid == by_uuid
            ][0]
        else:
            self.print_message(
                "No arguments given for locating existing experiment to remove."
            )
            return None
        del self.experiment_dq[i]

    def replace_action(
        self,
        sup_action: Action,
        by_index: int = None,
        by_uuid: UUID = None,
        by_action_order: int = None,
    ):
        """Substitute a queued action."""
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
            self.print_message(
                "No arguments given for locating existing action to replace."
            )
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
        # we need to wait for all actions to finish first
        await self.orch_wait_for_all_actions()
        while len(self.nonblocking) > 0:
            self.print_message(
                f"Stopping non-blocking action executors ({len(self.nonblocking)})"
            )
            await self.clear_nonblocking()
            await asyncio.sleep(1)
        if self.active_experiment is not None:
            self.print_message(
                f"finished exp uuid is: "
                f"{self.active_experiment.experiment_uuid}, "
                f"adding matching acts to it"
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
        await self.write_exp(self.active_experiment)

    async def write_active_sequence_seq(self):
        if self.active_seq_exp_counter > 1:
            active_exp = self.active_experiment.get_exp()
            await self.append_exp_to_seq(active_exp, self.active_sequence)
        else:
            await self.write_seq(self.active_sequence)

    async def shutdown(self):
        await self.detach_subscribers()
        self.status_logger.cancel()
        self.ntp_syncer.cancel()
        self.status_subscriber.cancel()

    async def update_operator(self, msg):
        if self.op_enabled and self.orch_op:
            await self.orch_op.update_q.put(msg)

    def start_wait(self, active: Active):
        self.wait_task = asyncio.create_task(self.dispatch_wait_task(active))

    async def dispatch_wait_task(self, active: Active, print_every_secs: int = 5):
        # handle long waits as a separate task so HTTP timeout doesn't occur
        waittime = active.action.action_params["waittime"]
        self.print_message(" ... wait action:", waittime)
        self.current_wait_ts = time.time()
        last_print_time = self.current_wait_ts
        check_time = self.current_wait_ts
        while check_time - self.current_wait_ts < waittime:
            if check_time - last_print_time > print_every_secs - 0.01:
                self.print_message(
                    f" ... orch waited {(check_time-self.current_wait_ts):.1f} sec / {waittime:.1f} sec"
                )
                last_print_time = check_time
            await asyncio.sleep(0.01)  # 10 msec sleep
            check_time = time.time()
        self.print_message(" ... wait action done")
        finished_action = await active.finish()
        self.last_wait_ts = check_time
        return finished_action

    async def active_action_monitor(self):
        while True:
            if self.globalstatusmodel.loop_state == LoopStatus.started:
                still_alive = True
                active_endpoints = [
                    actmod.url for actmod in self.globalstatusmodel.active_dict.values()
                ]
                if active_endpoints:
                    unique_endpoints = list(set(active_endpoints))
                    still_alive, unavail = await endpoints_available(unique_endpoints)
                if not still_alive:
                    bad_serves = [x.strip("/".split("/")[-2]) for x, _ in unavail]
                    self.current_stop_message = (
                        f"{', '.join(bad_serves)} servers are unavailable"
                    )
                    await self.stop()
                    await self.update_operator(True)
            await asyncio.sleep(self.heartbeat_interval)

    async def ping_action_servers(self):
        """Periodically monitor all action servers."""
        status_summary = {}
        for serv_key, serv_dict in self.world_cfg["servers"].items():
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
        while True:
            self.status_summary = await self.ping_action_servers()
            await self.update_operator(True)
            await asyncio.sleep(self.heartbeat_interval)
