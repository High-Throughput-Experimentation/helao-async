__all__ = ["Orch", "makeOrchServ"]

import asyncio
import sys
from copy import deepcopy
from typing import Optional, List
from uuid import UUID
from socket import gethostname
import inspect
from pydantic import BaseModel
import numpy as np
import json
import io
from pybase64 import b64decode
import traceback

import aiohttp
import colorama
import time
from fastapi import WebSocket, Body
from functools import partial

from bokeh.server.server import Server
from bokeh.layouts import column
from bokeh.layouts import layout, Spacer
from bokeh.models import ColumnDataSource
from bokeh.models import DataTable, TableColumn
from bokeh.models.widgets import Paragraph
from bokeh.models import Select
from bokeh.models import Button
from bokeh.models.widgets import Div
from bokeh.models.widgets.inputs import TextInput
from bokeh.plotting import figure, Figure
from bokeh.events import ButtonClick, DoubleTap
from bokeh.models.widgets import FileInput, Toggle

from helaocore.models.action_start_condition import ActionStartCondition
from helaocore.models.sequence import SequenceModel
from helaocore.models.experiment import ExperimentModel
from helaocore.models.hlostatus import HloStatus
from helaocore.models.server import ActionServerModel, GlobalStatusModel
from helaocore.models.orchstatus import OrchStatus
from helaocore.error import ErrorCodes

from helao.helpers.server_api import HelaoFastAPI
from helao.helpers.make_vis_serv import makeVisServ
from helao.helpers.import_experiments import import_experiments
from helao.helpers.import_sequences import import_sequences
from helao.helpers.dispatcher import async_private_dispatcher, async_action_dispatcher
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.to_json import to_json
from helao.helpers.unpack_samples import unpack_samples_helper
from helao.helpers.yml_finisher import move_dir
from helao.helpers.premodels import Sequence, Experiment, Action
from helao.servers.base import Base, Active
from helao.servers.vis import Vis
from helao.helpers.legacy_api import HTELegacyAPI
from helao.helpers.gen_uuid import gen_uuid
from helao.helpers.zdeque import zdeque


# ANSI color codes converted to the Windows versions
# strip colors if stdout is redirected
colorama.init(strip=not sys.stdout.isatty())
# colorama.init()

hlotags_metadata = [
    {"name": "public", "description": "prublic orchestrator endpoints"},
    {"name": "private", "description": "private orchestrator endpoints"},
]


def makeOrchServ(
    config, server_key, server_title, description, version, driver_class=None
):

    app = HelaoFastAPI(
        helao_cfg=config,
        helao_srv=server_key,
        title=server_title,
        description=description,
        version=version,
    )

    @app.on_event("startup")
    async def startup_event():
        """Run startup actions.

        When FastAPI server starts, create a global OrchHandler object,
        initiate the monitor_states coroutine which runs forever,
        and append dummy experiments to the
        experiment queue for testing.
        """
        app.orch = Orch(app)
        if driver_class:
            app.driver = driver_class(app.orch)

    @app.post("/get_status", tags=["private"])
    def get_status():
        # print(app.orch.orchstatusmodel.as_json())
        return app.orch.orchstatusmodel.as_json()

    @app.post("/update_status", tags=["private"])
    async def update_status(
        actionservermodel: Optional[ActionServerModel] = Body({}, embed=True)
    ):
        if actionservermodel is None:
            return False
        app.orch.print_message(
            f"orch '{app.orch.server.server_name}' "
            f"got status from "
            f"'{actionservermodel.action_server.server_name}': "
            f"{actionservermodel.endpoints}"
        )
        return await app.orch.update_status(actionservermodel=actionservermodel)

    @app.post("/attach_client", tags=["private"])
    async def attach_client(client_servkey: str):
        return await app.orch.attach_client(client_servkey)

    @app.websocket("/ws_status")
    async def websocket_status(websocket: WebSocket):
        """Subscribe to orchestrator status messages.

        Args:
        websocket: a fastapi.WebSocket object
        """
        await app.orch.ws_status(websocket)

    @app.websocket("/ws_data")
    async def websocket_data(websocket: WebSocket):
        """Subscribe to action server status dicts.

        Args:
        websocket: a fastapi.WebSocket object
        """
        await app.orch.ws_data(websocket)

    @app.post("/start", tags=["private"])
    async def start():
        """Begin experimenting experiment and action queues."""
        await app.orch.start()
        return {}

    @app.post("/estop", tags=["private"])
    async def estop():
        """Emergency stop experiment and action queues, interrupt running actions."""
        if app.orch.orchstatusmodel.loop_state == OrchStatus.started:
            await app.orch.estop_loop()
        elif app.orch.orchstatusmodel.loop_state == OrchStatus.estop:
            app.orch.print_message("orchestrator E-STOP flag already raised")
        else:
            app.orch.print_message("orchestrator is not running")
        return {}

    @app.post("/stop", tags=["private"])
    async def stop():
        """Stop experimenting experiment and action queues after current actions finish."""
        await app.orch.stop()
        return {}

    @app.post("/clear_estop", tags=["private"])
    async def clear_estop():
        """Remove emergency stop condition."""
        if app.orch.orchstatusmodel.loop_state != OrchStatus.estop:
            app.orch.print_message("orchestrator is not currently in E-STOP")
        else:
            await app.orch.clear_estop()

    @app.post("/clear_error", tags=["private"])
    async def clear_error():
        """Remove error condition."""
        if app.orch.orchstatusmodel.loop_state != OrchStatus.error:
            app.orch.print_message("orchestrator is not currently in ERROR")
        else:
            await app.orch.clear_error()

    @app.post("/skip_experiment", tags=["private"])
    async def skip_experiment():
        """Clear the present action queue while running."""
        await app.orch.skip()
        return {}

    @app.post("/clear_actions", tags=["private"])
    async def clear_actions():
        """Clear the present action queue while stopped."""
        await app.orch.clear_actions()
        return {}

    @app.post("/clear_experiments", tags=["private"])
    async def clear_experiments():
        """Clear the present experiment queue while stopped."""
        await app.orch.clear_experiments()
        return {}

    @app.post("/append_sequence", tags=["private"])
    async def append_sequence(
        sequence: Optional[Sequence] = Body({}, embed=True),
    ):
        seq_uuid = await app.orch.add_sequence(sequence=sequence)
        return {"sequence_uuid": seq_uuid}

    @app.post(f"/{server_key}/wait")
    async def wait(
        action: Optional[Action] = Body({}, embed=True),
        waittime: Optional[float] = 10.0,
    ):
        """Sleep action"""
        active = await app.orch.setup_and_contain_action()
        partial_action = active.action.as_dict()
        app.orch.start_wait(active)
        while app.orch.last_wait_ts == app.orch.current_wait_ts:
            await asyncio.sleep(0.01)
        return partial_action

    @app.post(f"/{server_key}/interrupt")
    async def interrupt(
        action: Optional[Action] = Body({}, embed=True), reason: Optional[str] = "wait"
    ):
        """Stop dispatch loop for planned manual intervention."""
        active = await app.orch.setup_and_contain_action()
        app.orch.current_stop_message = active.action.action_params["reason"]
        await app.orch.stop()
        await app.orch.update_operator(True)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post("/append_experiment", tags=["private"])
    async def append_experiment(
        experiment: Optional[Experiment] = Body({}, embed=True)
    ):
        """Add a experiment object to the end of the experiment queue."""
        exp_uuid = await app.orch.add_experiment(
            seq=app.orch.seq_file, experimenttemplate=experiment
        )
        return {"experiment_uuid": exp_uuid}

    @app.post("/prepend_experiment")
    async def prepend_experiment(
        experiment: Optional[Experiment] = Body({}, embed=True)
    ):
        """Add a experiment object to the start of the experiment queue."""
        exp_uuid = await app.orch.add_experiment(
            seq=app.orch.seq_file, experimenttemplate=experiment, prepend=True
        )
        return {"experiment_uuid": exp_uuid}

    @app.post("/insert_experiment")
    async def insert_experiment(
        experiment: Optional[Experiment] = Body({}, embed=True),
        index: Optional[int] = 0,
    ):
        """Insert a experiment object at experiment queue index."""
        exp_uuid = await app.orch.add_experiment(
            seq=app.orch.seq_file, experimenttemplate=experiment, at_index=index
        )
        return {"experiment_uuid": exp_uuid}

    @app.post("/list_sequences", tags=["private"])
    def list_sequences():
        """Return the current list of sequences."""
        return app.orch.list_sequences()

    @app.post("/list_experiments", tags=["private"])
    def list_experiments():
        """Return the current list of experiments."""
        return app.orch.list_experiments()

    @app.post("/active_experiment", tags=["private"])
    def active_experiment():
        """Return the active experiment."""
        return app.orch.get_experiment(last=False)

    @app.post("/last_experiment", tags=["private"])
    def last_experiment():
        """Return the last experiment."""
        return app.orch.get_experiment(last=True)

    @app.post("/list_actions", tags=["private"])
    def list_actions():
        """Return the current list of actions."""
        return app.orch.list_actions()

    @app.post("/list_active_actions", tags=["private"])
    def list_active_actions():
        """Return the current list of actions."""
        return app.orch.list_active_actions()

    @app.post("/endpoints", tags=["private"])
    def get_all_urls():
        """Return a list of all endpoints on this server."""
        return app.orch.get_endpoint_urls()

    @app.post("/shutdown", tags=["private"])
    def post_shutdown():
        shutdown_event()

    @app.on_event("shutdown")
    def shutdown_event():
        """Run shutdown actions."""
        app.orch.print_message("Stopping operator", info=True)
        app.orch.bokehapp.stop()
        app.orch.print_message("orch shutdown", info=True)
        # emergencyStop = True
        time.sleep(0.75)

    return app


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

    def __init__(self, fastapp: HelaoFastAPI):
        super().__init__(fastapp)
        self.experiment_lib = import_experiments(
            world_config_dict=self.world_cfg,
            experiment_path=None,
            server_name=self.server.server_name,
            user_experiment_path=self.helaodirs.user_exp,
        )
        self.sequence_lib = import_sequences(
            world_config_dict=self.world_cfg,
            sequence_path=None,
            server_name=self.server.server_name,
            user_sequence_path=self.helaodirs.user_seq,
        )

        # instantiate experiment/experiment queue, action queue
        self.sequence_dq = zdeque([])
        self.experiment_dq = zdeque([])
        self.action_dq = zdeque([])

        # holder for tracking dispatched action in status
        self.last_dispatched_action_uuid = None
        self.last_10_action_uuids = []
        # hold schema objects
        self.active_experiment = None
        self.last_experiment = None
        self.active_sequence = None
        self.active_seq_exp_counter = 0
        self.last_sequence = None
        self.bokehapp = None
        self.orch_op = None
        self.op_enabled = self.server_params.get("enable_op", False)
        if self.op_enabled:
            # asyncio.gather(self.init_Gamry(self.Gamry_devid))
            self.start_operator()
        # basemodel which holds all information for orch
        self.orchstatusmodel = GlobalStatusModel(orchestrator=self.server)
        self.orchstatusmodel._sort_status()
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

        self.status_subscriber = asyncio.create_task(self.subscribe_all())

        self.globstat_q = MultisubscriberQueue()
        self.globstat_clients = set()
        self.globstat_broadcaster = asyncio.create_task(self.globstat_broadcast_task())
        self.current_stop_message = ""

    def register_action_uuid(self, action_uuid):
        if len(self.last_10_action_uuids) == 10:
            self.last_10_action_uuids.pop(0)
        self.last_10_action_uuids.append(action_uuid)

    def track_action_uuid(self, action_uuid):
        self.last_dispatched_action_uuid = action_uuid

    def start_operator(self):
        servHost = self.server_cfg["host"]
        servPort = self.server_params.get("bokeh_port", self.server_cfg["port"] + 1000)
        servPy = "Operator"

        self.bokehapp = Server(
            {f"/{servPy}": partial(self.makeBokehApp, orch=self)},
            port=servPort,
            address=servHost,
            allow_websocket_origin=[f"{servHost}:{servPort}"],
        )
        self.print_message(f"started bokeh server {self.bokehapp}", info=True)
        self.bokehapp.start()
        # self.bokehapp.io_loop.add_callback(self.bokehapp.show, f"/{servPy}")
        # bokehapp.io_loop.start()

    def makeBokehApp(self, doc, orch):
        app = makeVisServ(
            config=self.world_cfg,
            server_key=self.server.server_name,
            doc=doc,
            server_title=self.server.server_name,
            description=f"{self.run_type} Operator",
            version=2.0,
            driver_class=None,
        )

        # _ = Operator(app.vis)
        doc.operator = Operator(app.vis, orch)
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
        interrupt = await self.interrupt_q.get()
        if isinstance(interrupt, GlobalStatusModel):
            self.incoming = interrupt

        # if not empty clear it
        while not self.interrupt_q.empty():
            interrupt = await self.interrupt_q.get()
            if isinstance(interrupt, GlobalStatusModel):
                self.incoming = interrupt
                await self.globstat_q.put(interrupt)

    async def subscribe_all(self, retry_limit: int = 5):
        """Subscribe to all fastapi servers in config."""
        fails = []
        for serv_key, serv_dict in self.world_cfg["servers"].items():
            if "fast" in serv_dict:
                self.print_message(f"trying to subscribe to {serv_key} status")

                success = False
                serv_addr = serv_dict["host"]
                serv_port = serv_dict["port"]
                for _ in range(retry_limit):
                    try:
                        response, error_code = await async_private_dispatcher(
                            world_config_dict=self.world_cfg,
                            server=serv_key,
                            private_action="attach_client",
                            params_dict={"client_servkey": self.server.server_name},
                            json_dict={},
                        )
                        if response and error_code == ErrorCodes.none:
                            success = True
                            break
                    except aiohttp.client_exceptions.ClientConnectorError:
                        self.print_message(
                            f"failed to subscribe to "
                            f"{serv_key} at "
                            f"{serv_addr}:{serv_port}, "
                            "trying again in 1sec",
                            info=True,
                        )
                        await asyncio.sleep(1)

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

    async def update_status(
        self, actionservermodel: Optional[ActionServerModel] = None
    ):
        """Dict update method for action server to push status messages."""
        if actionservermodel is None:
            return False
        # update GlobalStatusModel with new ActionServerModel
        # and sort the new status dict
        self.register_action_uuid(actionservermodel.last_action_uuid)
        self.orchstatusmodel.update_global_with_acts(
            actionservermodel=actionservermodel
        )

        # check if one action is in estop in the error list:
        estop_uuids = self.orchstatusmodel.find_hlostatus_in_finished(
            hlostatus=HloStatus.estopped,
        )

        error_uuids = self.orchstatusmodel.find_hlostatus_in_finished(
            hlostatus=HloStatus.errored,
        )

        if estop_uuids and self.orchstatusmodel.loop_state == OrchStatus.started:
            await self.estop_loop()
        elif error_uuids and self.orchstatusmodel.loop_state == OrchStatus.started:
            self.orchstatusmodel.orch_state = OrchStatus.error
        elif not self.orchstatusmodel.active_dict:
            # no uuids in active action dict
            self.orchstatusmodel.orch_state = OrchStatus.idle
        else:
            self.orchstatusmodel.orch_state = OrchStatus.busy
            self.print_message(f"running_states: {self.orchstatusmodel.active_dict}")

        await self.update_operator(True)

        # now push it to the interrupt_q
        await self.interrupt_q.put(self.orchstatusmodel)
        await self.globstat_q.put(self.orchstatusmodel.as_json())

        return True

    async def ws_globstat(self, websocket: WebSocket):
        """Subscribe to global status queue and send messages to websocket client."""
        self.print_message("got new global status subscriber")
        await websocket.accept()
        try:
            async for globstat_msg in self.globstat_q.subscribe():
                await websocket.send_text(json.dumps(globstat_msg.json_dict()))
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            self.print_message(
                f"Data websocket client {websocket.client[0]}:{websocket.client[1]} disconnected. {repr(e), tb,}",
                warning=True,
            )

    async def globstat_broadcast_task(self):
        """Consume globstat_q. Does nothing for now."""
        async for _ in self.globstat_q.subscribe():
            await asyncio.sleep(0.01)

    def unpack_sequence(
        self, sequence_name, sequence_params
    ) -> List[ExperimentModel]:
        if sequence_name in self.sequence_lib:
            return self.sequence_lib[sequence_name](**sequence_params)
        else:
            return []

    async def seq_unpacker(self):
        for i, experimentmodel in enumerate(
            self.active_sequence.experiment_plan_list
        ):
            # self.print_message(
            #     f"unpack experiment {experimenttemplate.experiment_name}"
            # )
            await self.add_experiment(
                seq=self.seq_file, experimentmodel=experimentmodel
            )
            if i == 0:
                self.orchstatusmodel.loop_state = OrchStatus.started

    async def loop_task_dispatch_sequence(self) -> ErrorCodes:
        if self.sequence_dq:
            self.print_message("finishing last sequence")
            await self.finish_active_sequence()
            self.print_message("getting new sequence from sequence_dq")
            self.active_sequence = self.sequence_dq.popleft()
            self.print_message(
                f"new active sequence is {self.active_sequence.sequence_name}"
            )
            if self.world_cfg.get("dummy", "False"):
                self.active_sequence.dummy = True
            if self.world_cfg.get("simulation", "False"):
                self.active_sequence.simulation = True
            self.active_sequence.init_seq(time_offset=self.ntp_offset)

            # todo: this is for later, for now the operator needs to unpack the sequence
            # in order to also use a semi manual op mode

            # self.print_message(f"unpacking experiments for {self.active_sequence.sequence_name}")
            # if self.active_sequence.sequence_name in self.sequence_lib:
            #     unpacked_exps = self.sequence_lib[self.active_sequence.sequence_name](**self.active_sequence.sequence_params)
            # else:
            #     unpacked_exps = []

            # for exp in unpacked_exps:
            #     D = Experiment(**exp.as_dict())
            #     self.active_sequence.experiment_plan_list.append(D)

            self.seq_file = self.active_sequence.get_seq()
            await self.write_seq(self.active_sequence)

            # add all experiments from sequence to experiment queue
            # todo: use seq model instead to initialize some parameters
            # of the experiment

            self.aloop.create_task(self.seq_unpacker())
            await asyncio.sleep(1)

        else:
            self.print_message("sequence queue is empty, cannot start orch loop")

            self.orchstatusmodel.loop_state = OrchStatus.stopped
            await self.intend_none()

        return ErrorCodes.none

    async def loop_task_dispatch_experiment(self) -> ErrorCodes:
        self.print_message("action_dq is empty, getting new actions")
        # wait for all actions in last/active experiment to finish
        self.print_message("finishing last active experiment first")
        await self.finish_active_experiment()

        # self.print_message("getting new experiment to fill action_dq")
        # generate uids when populating,
        # generate timestamp when acquring
        self.active_experiment = self.experiment_dq.popleft()
        self.active_seq_exp_counter += 1

        # self.print_message("copying global vars to experiment")
        # copy requested global param to experiment params
        for k, v in self.active_experiment.from_globalseq_params.items():
            self.print_message(f"{k}:{v}")
            if k in self.active_sequence.globalseq_params:
                self.active_experiment.experiment_params.update(
                    {v: self.active_sequence.globalseq_params[k]}
                )

        self.print_message(
            f"new active experiment is {self.active_experiment.experiment_name}"
        )
        if self.world_cfg.get("dummy", "False"):
            self.active_experiment.dummy = True
        if self.world_cfg.get("simulation", "False"):
            self.active_experiment.simulation = True
        self.active_experiment.run_type = self.run_type
        self.active_experiment.orchestrator = self.server
        self.active_experiment.init_exp(time_offset=self.ntp_offset)

        self.orchstatusmodel.new_experiment(
            exp_uuid=self.active_experiment.experiment_uuid
        )

        # additional experiment params should be stored
        # in experiment.experiment_params
        # self.print_message(
        #     f"unpacking actions for {self.active_experiment.experiment_name}"
        # )
        unpacked_acts = self.experiment_lib[self.active_experiment.experiment_name](
            self.active_experiment
        )
        if unpacked_acts is None:
            self.print_message("no actions in experiment", error=True)
            self.action_dq = zdeque([])
            return ErrorCodes.none

        # self.print_message("setting action order")
        for i, act in enumerate(unpacked_acts):
            # init uuid now for tracking later
            act.action_uuid = gen_uuid()
            act.action_order = int(i)
            # actual order should be the same at the beginning
            # will be incremented as necessary
            act.orch_submit_order = int(i)
            self.action_dq.append(act)

        # TODO:update experiment code
        # self.print_message("adding unpacked actions to action_dq")
        self.print_message(f"got: {self.action_dq}")
        self.print_message(
            f"optional params: {self.active_experiment.experiment_params}"
        )

        # write a temporary exp
        await self.write_active_experiment_exp()
        return ErrorCodes.none

    async def loop_task_dispatch_action(self) -> ErrorCodes:
        # self.print_message("actions in action_dq, processing them")
        if self.orchstatusmodel.loop_intent == OrchStatus.stop:
            self.print_message("stopping orchestrator")
            # monitor status of running action_dq, then end loop
            while self.orchstatusmodel.loop_state != OrchStatus.stopped:
                # wait for all orch actions to finish first
                await self.orch_wait_for_all_actions()
                if self.orchstatusmodel.orch_state == OrchStatus.idle:
                    await self.intend_none()
                    self.print_message("got stop")
                    self.orchstatusmodel.loop_state = OrchStatus.stopped
                    break

        elif self.orchstatusmodel.loop_intent == OrchStatus.skip:
            # clear action queue, forcing next experiment
            self.action_dq.clear()
            await self.intend_none()
            self.print_message("skipping to next experiment")
        elif self.orchstatusmodel.loop_intent == OrchStatus.estop:
            self.action_dq.clear()
            await self.intend_none()
            self.print_message("estopping")
            self.orchstatusmodel.loop_state = OrchStatus.estop
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
                    while True:
                        await self.wait_for_interrupt()
                        endpoint_free = self.orchstatusmodel.endpoint_free(
                            action_server=A.action_server, endpoint_name=A.action_name
                        )
                        if endpoint_free:
                            break
                elif A.start_condition == ActionStartCondition.wait_for_server:
                    self.print_message("orch is waiting for server to become available")
                    while True:
                        await self.wait_for_interrupt()
                        server_free = self.orchstatusmodel.server_free(
                            action_server=A.action_server
                        )
                        if server_free:
                            break
                elif A.start_condition == ActionStartCondition.wait_for_orch:
                    self.print_message(
                        "orch is waiting for endpoint to become available"
                    )
                    while True:
                        await self.wait_for_interrupt()
                        endpoint_free = self.orchstatusmodel.endpoint_free(
                            action_server=A.orchestrator, endpoint_name="wait"
                        )
                        if endpoint_free:
                            break
                elif A.start_condition == ActionStartCondition.wait_for_all:
                    await self.orch_wait_for_all_actions()

                else:  # unsupported value
                    await self.orch_wait_for_all_actions()

            # self.print_message("copying global vars to action")
            # copy requested global param to action params
            for k, v in A.from_globalexp_params.items():
                self.print_message(f"{k}:{v}")
                if k in self.active_experiment.globalexp_params:
                    A.action_params.update(
                        {v: self.active_experiment.globalexp_params[k]}
                    )

            self.print_message(
                f"dispatching action {A.action_name} on server {A.action_server.server_name}"
            )
            # keep running counter of dispatched actions
            A.orch_submit_order = self.orchstatusmodel.counter_dispatched_actions[
                self.active_experiment.experiment_uuid
            ]
            self.orchstatusmodel.counter_dispatched_actions[
                self.active_experiment.experiment_uuid
            ] += 1

            A.init_act(time_offset=self.ntp_offset)
            result_actiondict, error_code = await async_action_dispatcher(
                self.world_cfg, A
            )
            # endpoint_status = deepcopy(
            #     self.orchstatusmodel.server_dict[A.action_server.as_key()].endpoints[
            #         A.action_name
            #     ]
            # )
            # endpoint_uuids = [str(k) for k in endpoint_status.active_dict.keys()] + [
            #     str(k) for k in endpoint_status.nonactive_dict["finished"].keys()
            # ]
            endpoint_uuids = [
                str(k) for k in self.orchstatusmodel.active_dict.keys()
            ] + [
                str(k)
                for k in self.orchstatusmodel.nonactive_dict.get("finished", {}).keys()
            ]
            self.print_message(
                f"Current {A.action_name} received uuids: {endpoint_uuids}"
            )
            result_uuid = result_actiondict["action_uuid"]
            self.track_action_uuid(UUID(result_uuid))
            self.print_message(
                f"Action {A.action_name} dispatched with uuid: {result_uuid}"
            )
            while result_uuid not in endpoint_uuids:
                self.print_message(
                    f"Waiting for dispatched {A.action_name}, {A.action_uuid} request to register in global status."
                )
                try:
                    await asyncio.wait_for(self.wait_for_interrupt(), timeout=5.0)
                except asyncio.TimeoutError:
                    print("!!! Did not receive interrupt after 5 sec, retrying. !!!")
                # endpoint_status = deepcopy(
                #     self.orchstatusmodel.server_dict[
                #         A.action_server.as_key()
                #     ].endpoints[A.action_name]
                # )
                # endpoint_uuids = [
                #     str(k) for k in endpoint_status.active_dict.keys()
                # ] + [str(k) for k in endpoint_status.nonactive_dict["finished"].keys()]
                endpoint_uuids = [
                    str(k) for k in self.orchstatusmodel.active_dict.keys()
                ] + [
                    str(k)
                    for k in self.orchstatusmodel.nonactive_dict.get(
                        "finished", {}
                    ).keys()
                ]
            self.print_message(f"New status registered on {A.action_name}.")
            if error_code is not ErrorCodes.none:
                return error_code

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
                return result_action.error_code

            if result_action.to_globalexp_params:
                if isinstance(result_action.to_globalexp_params, list):
                    # self.print_message(
                    #     f"copying global vars {', '.join(result_action.to_globalexp_params)} back to experiment"
                    # )
                    for k in result_action.to_globalexp_params:
                        if k in result_action.action_params:
                            if (
                                result_action.action_params[k] is None
                                and k in self.active_experiment.globalexp_params
                            ):
                                self.print_message(f"clearing {k} in global vars")
                                self.active_experiment.globalexp_params.pop(k)
                            else:
                                self.print_message(f"updating {k} in global vars")
                                self.active_experiment.globalexp_params.update(
                                    {k: result_action.action_params[k]}
                                )
                elif isinstance(result_action.to_globalexp_params, dict):
                    # self.print_message(
                    #     f"copying global vars {', '.join(result_action.to_globalexp_params.keys())} back to experiment"
                    # )
                    for k1, k2 in result_action.to_globalexp_params.items():
                        if k1 in result_action.action_params:
                            if (
                                result_action.action_params[k1] is None
                                and k2 in self.active_experiment.globalexp_params
                            ):
                                self.print_message(f"clearing {k2} in global vars")
                                self.active_experiment.globalexp_params.pop(k2)
                            else:
                                self.print_message(f"updating {k2} in global vars")
                                self.active_experiment.globalexp_params.update(
                                    {k2: result_action.action_params[k1]}
                                )

                # self.print_message("done copying global vars back to experiment")

        return ErrorCodes.none

    async def dispatch_loop_task(self):
        """Parse experiment and action queues,
        and dispatch action_dq while tracking run state flags."""
        self.print_message("--- started operator orch ---")
        self.print_message(f"current orch status: {self.orchstatusmodel.orch_state}")
        # clause for resuming paused action list
        # self.print_message(f"current orch sequences: {list(self.sequence_dq)[:5]}... ({len(self.sequence_dq)})")
        # self.print_message(f"current orch descisions: {list(self.experiment_dq)[:5]}... ({len(self.experiment_dq)})")
        # self.print_message(f"current orch actions: {list(self.action_dq)[:5]}... ({len(self.action_dq)})")
        # self.print_message("--- resuming orch loop now ---")

        self.orchstatusmodel.loop_state = OrchStatus.started

        try:
            while self.orchstatusmodel.loop_state == OrchStatus.started and (
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
                # await asyncio.sleep(0.001)

                if self.action_dq:
                    self.print_message("!!!dispatching next action", info=True)
                    # num_exp_actions = deepcopy(
                    #     self.orchstatusmodel.counter_dispatched_actions[
                    #         self.active_experiment.experiment_uuid
                    #     ]
                    # )
                    error_code = await self.loop_task_dispatch_action()
                    if (
                        self.last_dispatched_action_uuid
                        not in self.last_10_action_uuids
                    ):
                        await asyncio.sleep(0.001)
                elif self.experiment_dq:
                    self.print_message(
                        "!!!waiting for all actions to finish before dispatching next experiment",
                        info=True,
                    )
                    await self.orch_wait_for_all_actions()
                    self.print_message("!!!dispatching next experiment", info=True)
                    error_code = await self.loop_task_dispatch_experiment()
                # if no acts and no exps, disptach next sequence
                elif self.sequence_dq:
                    self.print_message(
                        "!!!waiting for all actions to finish before dispatching next sequence",
                        info=True,
                    )
                    await self.orch_wait_for_all_actions()
                    self.print_message("!!!dispatching next sequence", info=True)
                    error_code = await self.loop_task_dispatch_sequence()

                if error_code is not ErrorCodes.none:
                    self.print_message(
                        f"stopping orch with error code: {error_code}", error=True
                    )
                    # await self.intend_stop()
                    await self.intend_estop()

                await self.update_operator(True)

            if (
                self.orchstatusmodel.loop_state == OrchStatus.estop
                or self.orchstatusmodel.loop_intent == OrchStatus.estop
            ):
                await self.estop_loop()

            self.print_message("all queues are empty")
            self.print_message("--- stopping operator orch ---", info=True)

            # finish the last exp
            # this wait for all actions in active experiment
            # to finish and then updates the exp with the acts
            if not self.action_dq:  # in case of interrupt, don't finish exp
                self.print_message("finishing final experiment")
                await self.finish_active_experiment()
            if not self.experiment_dq:  # in case of interrupt, don't finish seq
                self.print_message("finishing final sequence")
                await self.finish_active_sequence()

            if self.orchstatusmodel.loop_state != OrchStatus.estop:
                self.orchstatusmodel.loop_state = OrchStatus.stopped
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
            return False

    async def orch_wait_for_all_actions(self):
        """waits for all action assigned to this orch to finish"""

        # self.print_message("orch is waiting for all action_dq to finish")

        # some actions are active
        # we need to wait for them to finish
        while not self.orchstatusmodel.actions_idle():
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
        if self.orchstatusmodel.loop_state == OrchStatus.stopped:
            if (
                self.action_dq or self.experiment_dq or self.sequence_dq
            ):  # resume actions from a paused run
                await self.start_loop()
            else:
                self.print_message("experiment list is empty")
        else:
            self.print_message("already running")
        self.current_stop_message = ""
        await self.update_operator(True)

    async def start_loop(self):
        if self.orchstatusmodel.loop_state == OrchStatus.stopped:
            self.print_message("starting orch loop")
            self.loop_task = asyncio.create_task(self.dispatch_loop_task())
        elif self.orchstatusmodel.loop_state == OrchStatus.estop:
            self.print_message(
                "E-STOP flag was raised, clear E-STOP before starting.", error=True
            )
        else:
            self.print_message("loop already started.")
        return self.orchstatusmodel.loop_state

    async def estop_loop(self):
        self.print_message("estopping orch", info=True)

        # set orchstatusmodel.loop_state to estop
        self.orchstatusmodel.loop_state = OrchStatus.estop

        # force stop all running actions in the status dict (for this orch)
        await self.estop_actions(switch=True)

        # reset loop intend
        await self.intend_none()

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
        ) in self.orchstatusmodel.server_dict.items():
            # if actionservermodel.action_server == self.server:
            #     continue

            action_dict = deepcopy(active_exp_dict)
            action_dict.update(
                {
                    "action_name": "estop",
                    "action_server": actionservermodel.action_server.json_dict(),
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
        if self.orchstatusmodel.loop_state == OrchStatus.started:
            await self.intend_skip()
        else:
            self.print_message("orchestrator not running, clearing action queue")
            await asyncio.sleep(0.001)
            self.action_dq.clear()

    async def intend_skip(self):
        await asyncio.sleep(0.001)
        self.orchstatusmodel.loop_intent = OrchStatus.skip
        await self.interrupt_q.put(self.orchstatusmodel.loop_intent)

    async def stop(self):
        """Stop experimenting experiment and
        action queues after current actions finish."""
        if self.orchstatusmodel.loop_state == OrchStatus.started:
            await self.intend_stop()
        elif self.orchstatusmodel.loop_state == OrchStatus.estop:
            self.print_message("orchestrator E-STOP flag was raised; nothing to stop")
        else:
            self.print_message("orchestrator is not running")

    async def intend_stop(self):
        await asyncio.sleep(0.001)
        self.orchstatusmodel.loop_intent = OrchStatus.stop
        await self.interrupt_q.put(self.orchstatusmodel.loop_intent)

    async def intend_estop(self):
        await asyncio.sleep(0.001)
        self.orchstatusmodel.loop_intent = OrchStatus.estop
        await self.interrupt_q.put(self.orchstatusmodel.loop_intent)

    async def intend_none(self):
        await asyncio.sleep(0.001)
        self.orchstatusmodel.loop_intent = OrchStatus.none
        await self.interrupt_q.put(self.orchstatusmodel.loop_intent)

    async def clear_estop(self):
        # which were estopped first
        await asyncio.sleep(0.001)
        self.print_message("clearing estopped uuids")
        self.orchstatusmodel.clear_in_finished(hlostatus=HloStatus.estopped)
        # release estop for all action servers
        await self.estop_actions(switch=False)
        # set orch status from estop back to stopped
        self.orchstatusmodel.loop_state = OrchStatus.stopped
        await self.interrupt_q.put("cleared_estop")

    async def clear_error(self):
        # currently only resets the error dict
        self.print_message("clearing errored uuids")
        await asyncio.sleep(0.001)
        self.orchstatusmodel.clear_in_finished(hlostatus=HloStatus.errored)
        await self.interrupt_q.put("cleared_errored")

    async def clear_sequences(self):
        self.print_message("clearing sequence queue")
        await asyncio.sleep(0.001)
        self.sequence_dq.clear()

    async def clear_experiments(self):
        self.print_message("clearing experiment queue")
        await asyncio.sleep(0.001)
        self.experiment_dq.clear()

    async def clear_actions(self):
        self.print_message("clearing action queue")
        await asyncio.sleep(0.001)
        self.action_dq.clear()

    async def add_sequence(
        self,
        sequence: Sequence,
    ):
        # init uuid now for tracking later
        sequence.sequence_uuid = gen_uuid()
        self.sequence_dq.append(sequence)
        return sequence.sequence_uuid

    async def add_experiment(
        self,
        seq: SequenceModel,
        experimentmodel: ExperimentModel,
        prepend: Optional[bool] = False,
        at_index: Optional[int] = None,
    ):
        Ddict = experimentmodel.dict()
        Ddict.update(seq.dict())
        D = Experiment(**Ddict)

        # init uuid now for tracking later
        D.experiment_uuid = gen_uuid()

        # reminder: experiment_dict values take precedence over keyword args
        if D.orchestrator.server_name is None or D.orchestrator.machine_name is None:
            D.orchestrator = self.server

        await asyncio.sleep(0.0001)
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

    def get_experiment(self, last=False):
        """Return the active or last experiment."""
        active_experiment_list = []
        if last:
            experiment = self.last_experiment
        else:
            experiment = self.active_experiment
        if experiment is not None:
            active_experiment_list.append(experiment.get_exp())
        return active_experiment_list

    def list_active_actions(self):
        """Return the current queue running actions."""
        return [
            statusmodel.act
            for uuid, statusmodel in self.orchstatusmodel.active_dict.items()
        ]

    def list_actions(self, limit=10):
        """Return the current queue of action_dq."""
        return [
            self.action_dq[i].get_act() for i in range(min(len(self.action_dq), limit))
        ]

    def supplement_error_action(self, check_uuid: UUID, sup_action: Action):
        """Insert action at front of action queue with
        subversion of errored action,
        inherit parameters if desired."""

        error_uuids = self.orchstatusmodel.find_hlostatus_in_finished(
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

    def remove_experiment(
        self, by_index: Optional[int] = None, by_uuid: Optional[UUID] = None
    ):
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
        by_index: Optional[int] = None,
        by_uuid: Optional[UUID] = None,
        by_action_order: Optional[int] = None,
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
                self.orchstatusmodel.counter_dispatched_actions[
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
        if self.active_sequence is not None:
            self.replace_status(
                status_list=self.active_sequence.sequence_status,
                old_status=HloStatus.active,
                new_status=HloStatus.finished,
            )
            await self.write_seq(self.active_sequence)
            self.last_sequence = deepcopy(self.active_sequence)
            self.active_sequence = None
            self.active_seq_exp_counter = 0

            self.orchstatusmodel.counter_dispatched_actions = {}

            # DB server call to finish_yml if DB exists
            self.aloop.create_task(move_dir(self.last_sequence, base=self))

    async def finish_active_experiment(self):
        # we need to wait for all actions to finish first
        await self.orch_wait_for_all_actions()
        if self.active_experiment is not None:
            self.print_message(
                f"finished exp uuid is: "
                f"{self.active_experiment.experiment_uuid}, "
                f"adding matching acts to it"
            )

            self.active_experiment.actionmodel_list = []

            # TODO use exp uuid to filter actions?
            self.active_experiment.actionmodel_list = (
                self.orchstatusmodel.finish_experiment(
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

            if self.active_experiment.to_globalseq_params:
                if isinstance(self.active_experiment.to_globalseq_params, list):
                    # self.print_message(
                    #     f"copying global vars {', '.join(self.active_experiment.to_globalseq_params)} back to sequence"
                    # )
                    for k in self.active_experiment.to_globalseq_params:
                        if k in self.active_experiment.experiment_params:
                            if (
                                self.active_experiment.experiment_params[k] is None
                                and k in self.active_sequence.globalseq_params
                            ):
                                self.print_message(f"clearing {k} in global vars")
                                self.active_sequence.globalseq_params.pop(k)
                            else:
                                self.print_message(f"updating {k} in global vars")
                                self.active_sequence.globalseq_params.update(
                                    {k: self.active_experiment.experiment_params[k]}
                                )
                elif isinstance(self.active_experiment.to_globalseq_params, dict):
                    # self.print_message(
                    #     f"copying global vars {', '.join(self.active_experiment.to_globalseq_params.keys())} back to sequence"
                    # )
                    for k1, k2 in self.active_experiment.to_globalseq_params.items():
                        if k1 in self.active_experiment.experiment_params:
                            if (
                                self.active_experiment.experiment_params[k1] is None
                                and k2 in self.active_sequence.globalseq_params
                            ):
                                self.print_message(f"clearing {k2} in global vars")
                                self.active_sequence.globalseq_params.pop(k2)
                            else:
                                self.print_message(f"updating {k2} in global vars")
                                self.active_sequence.globalseq_params.update(
                                    {k2: self.active_experiment.experiment_params[k1]}
                                )
                # self.print_message("done copying global vars back to sequence")

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


class return_sequence_lib(BaseModel):
    """Return class for queried sequence objects."""

    index: int
    sequence_name: str
    doc: str
    args: list
    defaults: list


class return_experiment_lib(BaseModel):
    """Return class for queried experiment objects."""

    index: int
    experiment_name: str
    doc: str
    args: list
    defaults: list


class Operator:
    def __init__(self, visServ: Vis, orch):
        self.vis = visServ
        self.orch = orch
        self.dataAPI = HTELegacyAPI(self.vis)

        self.config_dict = self.vis.server_cfg.get("params", {})
        self.pal_name = None
        self.update_q = asyncio.Queue()
        # find pal server if configured in world config
        for server_name, server_config in self.vis.world_cfg["servers"].items():
            if server_config.get("fast", "") == "pal_server":
                self.pal_name = server_name
                self.vis.print_message(
                    f"found PAL server: '{self.pal_name}'", info=True
                )
                break

        self.dev_customitems = []
        if self.pal_name is not None:
            pal_server_params = self.vis.world_cfg["servers"][self.pal_name]["params"]
            if "positions" in pal_server_params:
                dev_custom = pal_server_params["positions"].get("custom", {})
            else:
                dev_custom = {}
            self.dev_customitems = [key for key in dev_custom.keys()]

        self.color_sq_param_inputs = "#BDB76B"
        self.max_width = 1024
        # holds the page layout
        self.layout = []
        self.seq_param_layout = []
        self.seq_param_input = []
        self.seq_private_input = []
        self.exp_param_layout = []
        self.exp_param_input = []
        self.exp_private_input = []

        self.sequence = None
        self.experiment_plan_list = {}
        self.experiment_plan_list["sequence_name"] = []
        self.experiment_plan_list["sequence_label"] = []
        self.experiment_plan_list["experiment_name"] = []

        self.sequence_list = {}
        self.sequence_list["sequence_name"] = []
        self.sequence_list["sequence_uuid"] = []

        self.experiment_list = {}
        self.experiment_list["experiment_name"] = []
        self.experiment_list["experiment_uuid"] = []

        self.action_list = {}
        self.action_list["action_name"] = []
        self.action_list["action_server"] = []
        self.action_list["action_uuid"] = []

        self.active_action_list = {}
        self.active_action_list["action_name"] = []
        self.active_action_list["action_server"] = []
        self.active_action_list["action_uuid"] = []
        self.active_action_list["samples_in"] = []
        self.active_action_list["solids_in"] = []

        self.sequence_select_list = []
        self.sequences = []
        self.sequence_lib = self.orch.sequence_lib

        self.experiment_select_list = []
        self.experiments = []
        self.experiment_lib = self.orch.experiment_lib

        # FastAPI calls
        self.get_sequence_lib()
        self.get_experiment_lib()

        self.vis.doc.add_next_tick_callback(partial(self.get_sequences))
        self.vis.doc.add_next_tick_callback(partial(self.get_experiments))
        self.vis.doc.add_next_tick_callback(partial(self.get_actions))
        self.vis.doc.add_next_tick_callback(partial(self.get_active_actions))

        self.experimentplan_source = ColumnDataSource(data=self.experiment_plan_list)
        self.columns_expplan = [
            TableColumn(field=key, title=key) for key in self.experiment_plan_list
        ]
        self.experimentplan_table = DataTable(
            source=self.experimentplan_source,
            columns=self.columns_expplan,
            width=self.max_width - 20,
            height=200,
            autosize_mode="fit_columns",
        )

        self.sequence_source = ColumnDataSource(data=self.sequence_list)
        self.columns_seq = [
            TableColumn(field=key, title=key) for key in self.sequence_list
        ]
        self.sequence_table = DataTable(
            source=self.sequence_source,
            columns=self.columns_seq,
            width=self.max_width - 20,
            height=200,
            autosize_mode="fit_columns",
        )

        self.experiment_source = ColumnDataSource(data=self.experiment_list)
        self.columns_exp = [
            TableColumn(field=key, title=key) for key in self.experiment_list
        ]
        self.experiment_table = DataTable(
            source=self.experiment_source,
            columns=self.columns_exp,
            width=self.max_width - 20,
            height=200,
            autosize_mode="fit_columns",
        )

        self.action_source = ColumnDataSource(data=self.action_list)
        self.columns_act = [
            TableColumn(field=key, title=key) for key in self.action_list
        ]
        self.action_table = DataTable(
            source=self.action_source,
            columns=self.columns_act,
            width=self.max_width - 20,
            height=200,
            autosize_mode="fit_columns",
        )

        self.active_action_source = ColumnDataSource(data=self.active_action_list)
        self.columns_active_action = [
            TableColumn(field=key, title=key) for key in self.active_action_list
        ]
        self.active_action_table = DataTable(
            source=self.active_action_source,
            columns=self.columns_active_action,
            width=self.max_width - 20,
            height=200,
            autosize_mode="fit_columns",
            fit_columns=False,
        )

        self.sequence_dropdown = Select(
            title="Select sequence:",
            value=None,
            options=self.sequence_select_list,
        )
        self.sequence_dropdown.on_change("value", self.callback_sequence_select)

        self.experiment_dropdown = Select(
            title="Select experiment:", value=None, options=self.experiment_select_list
        )
        self.experiment_dropdown.on_change("value", self.callback_experiment_select)

        # buttons to control orch
        self.button_start_orch = Button(
            label="Start Orch", button_type="default", width=70
        )
        self.button_start_orch.on_event(ButtonClick, self.callback_start_orch)
        self.button_estop_orch = Button(
            label="ESTOP", button_type="danger", width=400, height=100
        )
        self.button_estop_orch.on_event(ButtonClick, self.callback_estop_orch)
        self.button_add_expplan = Button(
            label="add exp plan", button_type="default", width=100
        )
        self.button_add_expplan.on_event(ButtonClick, self.callback_add_expplan)
        self.button_stop_orch = Button(
            label="Stop Orch", button_type="default", width=70
        )
        self.button_stop_orch.on_event(ButtonClick, self.callback_stop_orch)
        self.button_skip_exp = Button(label="Skip exp", button_type="danger", width=70)
        self.button_skip_exp.on_event(ButtonClick, self.callback_skip_exp)
        self.button_update = Button(
            label="update tables", button_type="default", width=120
        )
        self.button_update.on_event(ButtonClick, self.callback_update_tables)
        self.button_clear_expplan = Button(
            label="clear expplan", button_type="default", width=100
        )
        self.button_clear_expplan.on_event(ButtonClick, self.callback_clear_expplan)
        self.orch_status_button = Toggle(
            label="Disabled", disabled=True, button_type="danger", width=400
        )  # success: green, danger: red

        self.button_clear_seqs = Button(
            label="clear seqs", button_type="danger", width=100
        )
        self.button_clear_seqs.on_event(ButtonClick, self.callback_clear_sequences)
        self.button_clear_exps = Button(
            label="clear exp", button_type="danger", width=100
        )
        self.button_clear_exps.on_event(ButtonClick, self.callback_clear_experiments)
        self.button_clear_action = Button(
            label="clear act", button_type="danger", width=100
        )
        self.button_clear_action.on_event(ButtonClick, self.callback_clear_actions)

        self.button_prepend_exp = Button(
            label="prepend exp to exp plan", button_type="default", width=150
        )
        self.button_prepend_exp.on_event(ButtonClick, self.callback_prepend_exp)
        self.button_append_exp = Button(
            label="append exp to exp plan", button_type="default", width=150
        )
        self.button_append_exp.on_event(ButtonClick, self.callback_append_exp)

        self.button_prepend_seq = Button(
            label="prepend seq to experiment plan list",
            button_type="default",
            width=250,
        )
        self.button_prepend_seq.on_event(ButtonClick, self.callback_prepend_seq)
        self.button_append_seq = Button(
            label="append seq to experiment plan list", button_type="default", width=250
        )
        self.button_append_seq.on_event(ButtonClick, self.callback_append_seq)

        self.sequence_descr_txt = Div(text="""select a sequence item""", width=600)
        self.experiment_descr_txt = Div(text="""select a experiment item""", width=600)
        self.error_txt = Paragraph(
            text="""no error""",
            width=600,
            height=30,
            style={"font-size": "100%", "color": "black"},
        )

        self.input_sequence_label = TextInput(
            value="nolabel",
            title="sequence label",
            disabled=False,
            width=120,
            height=40,
        )

        self.orch_section = Div(
            text="<b>Orch:</b>",
            width=self.max_width - 20,
            height=32,
            style={"font-size": "150%", "color": "red"},
        )

        self.layout0 = layout(
            [
                layout(
                    [
                        Spacer(width=20),
                        Div(
                            text=f"<b>{self.config_dict.get('doc_name', 'Operator')} on {gethostname()}</b>",
                            width=self.max_width - 20,
                            height=32,
                            style={"font-size": "200%", "color": "red"},
                        ),
                    ],
                    background="#C0C0C0",
                    width=self.max_width,
                ),
                Spacer(height=10),
                layout(
                    [
                        Spacer(width=20),
                        Div(
                            text="<b>Sequences:</b>",
                            width=self.max_width - 20,
                            height=32,
                            style={"font-size": "150%", "color": "red"},
                        ),
                    ],
                    background="#C0C0C0",
                    width=self.max_width,
                ),
                layout(
                    [
                        [self.sequence_dropdown],
                        [
                            Spacer(width=10),
                            Div(
                                text="<b>sequence description:</b>",
                                width=200 + 50,
                                height=15,
                            ),
                        ],
                        [self.sequence_descr_txt],
                        Spacer(height=10),
                    ],
                    background="#808080",
                    width=self.max_width,
                ),
                layout(
                    [
                        self.button_append_seq,
                        self.button_prepend_seq,
                    ],
                    background="#808080",
                    width=self.max_width,
                ),
            ]
        )

        self.layout2 = layout(
            [
                Spacer(height=10),
                layout(
                    [
                        Spacer(width=20),
                        Div(
                            text="<b>Experiments:</b>",
                            width=self.max_width - 20,
                            height=32,
                            style={"font-size": "150%", "color": "red"},
                        ),
                    ],
                    background="#C0C0C0",
                    width=self.max_width,
                ),
                Spacer(height=10),
                layout(
                    [
                        [self.experiment_dropdown],
                        [
                            Spacer(width=10),
                            Div(
                                text="<b>experiment description:</b>",
                                width=200 + 50,
                                height=15,
                            ),
                        ],
                        [self.experiment_descr_txt],
                        Spacer(height=20),
                    ],
                    background="#808080",
                    width=self.max_width,
                ),
                layout(
                    [
                        [self.button_append_exp, self.button_prepend_exp],
                    ],
                    background="#808080",
                    width=self.max_width,
                ),
            ]
        )

        self.layout4 = layout(
            [
                Spacer(height=10),
                layout(
                    [
                        Spacer(width=20),
                        self.orch_section,
                    ],
                    background="#C0C0C0",
                    width=self.max_width,
                ),
                layout(
                    [
                        [
                            self.input_sequence_label,
                            self.button_add_expplan,
                            Spacer(width=10),
                            self.button_start_orch,
                            Spacer(width=10),
                            self.button_stop_orch,
                            Spacer(width=10),
                            self.button_clear_expplan,
                            Spacer(width=10),
                            self.orch_status_button,
                        ],
                        Spacer(height=10),
                        [
                            Spacer(width=10),
                            Div(
                                text="<b>Error message:</b>",
                                width=200 + 50,
                                height=15,
                                style={"font-size": "100%", "color": "black"},
                            ),
                        ],
                        [Spacer(width=10), self.error_txt],
                        Spacer(height=10),
                    ],
                    background="#808080",
                    width=self.max_width,
                ),
                layout(
                    [
                        [
                            Spacer(width=20),
                            Div(
                                text="<b>Experiment Plan:</b>",
                                width=200 + 50,
                                height=15,
                            ),
                        ],
                        [self.experimentplan_table],
                        [
                            Spacer(width=20),
                            Div(
                                text="<b>queued sequences:</b>",
                                width=200 + 50,
                                height=15,
                            ),
                        ],
                        [self.sequence_table],
                        [
                            Spacer(width=20),
                            Div(
                                text="<b>queued experiments:</b>",
                                width=200 + 50,
                                height=15,
                            ),
                        ],
                        [self.experiment_table],
                        [
                            Spacer(width=20),
                            Div(
                                text="<b>queued actions:</b>", width=200 + 50, height=15
                            ),
                        ],
                        [self.action_table],
                        [
                            Spacer(width=20),
                            Div(
                                text="<b>Active actions:</b>", width=200 + 50, height=15
                            ),
                        ],
                        [self.active_action_table],
                        Spacer(height=10),
                        [
                            self.button_skip_exp,
                            Spacer(width=5),
                            self.button_clear_seqs,
                            Spacer(width=5),
                            self.button_clear_exps,
                            Spacer(width=5),
                            self.button_clear_action,
                            self.button_update,
                        ],
                        Spacer(height=10),
                        self.button_estop_orch,
                        Spacer(height=10),
                    ],
                    background="#7fdbff",
                    width=self.max_width,
                ),
            ]
        )

        self.dynamic_col = column(
            self.layout0,
            layout(),
            self.layout2,
            layout(),
            self.layout4,  # placeholder  # placeholder
        )
        self.vis.doc.add_root(self.dynamic_col)

        # select the first item to force an update of the layout
        if self.experiment_select_list:
            self.experiment_dropdown.value = self.experiment_select_list[0]

        if self.sequence_select_list:
            self.sequence_dropdown.value = self.sequence_select_list[0]

        self.IOloop_run = False
        self.IOtask = asyncio.create_task(self.IOloop())
        self.vis.doc.on_session_destroyed(self.cleanup_session)
        self.orch.orch_op = self

    def cleanup_session(self, session_context):
        self.vis.print_message("Operator Bokeh session closed", info=True)
        self.IOloop_run = False
        self.IOtask.cancel()

    def get_sequence_lib(self):
        """Return the current list of sequences."""
        self.sequences = []
        self.vis.print_message(
            f"found sequences: {[sequence for sequence in self.sequence_lib]}"
        )
        for i, sequence in enumerate(self.sequence_lib):
            tmpdoc = self.sequence_lib[sequence].__doc__
            if tmpdoc is None:
                tmpdoc = ""

            argspec = inspect.getfullargspec(self.sequence_lib[sequence])
            tmpargs = argspec.args
            tmpdefs = argspec.defaults

            if tmpdefs is None:
                tmpdefs = []

            # filter the Sequence BaseModel
            idxlist = []
            # for idx, tmparg in enumerate(argspec.args):
            #     if tmparg=="sequence_version":
            #         idxlist.append(idx)

            tmpargs = list(tmpargs)
            tmpdefs = list(tmpdefs)
            for j, idx in enumerate(idxlist):
                if len(tmpargs) == len(tmpdefs):
                    tmpargs.pop(idx - j)
                    tmpdefs.pop(idx - j)
                else:
                    tmpargs.pop(idx - j)
            # use defaults specified in config
            seq_defs = self.orch.world_cfg.get("sequence_params", {})
            tmpdefs = [seq_defs.get(ta, td) for ta, td in zip(tmpargs, tmpdefs)]
            tmpargs = tuple(tmpargs)
            tmpdefs = tuple(tmpdefs)

            for t in tmpdefs:
                t = json.dumps(t)

            self.sequences.append(
                return_sequence_lib(
                    index=i,
                    sequence_name=sequence,
                    doc=tmpdoc,
                    args=tmpargs,
                    defaults=tmpdefs,
                ).dict()
            )
        for item in self.sequences:
            self.sequence_select_list.append(item["sequence_name"])

    def get_experiment_lib(self):
        """Return the current list of experiments."""
        self.experiments = []
        self.vis.print_message(
            f"found experiment: {[experiment for experiment in self.experiment_lib]}"
        )
        for i, experiment in enumerate(self.experiment_lib):
            tmpdoc = self.experiment_lib[experiment].__doc__
            if tmpdoc is None:
                tmpdoc = ""

            argspec = inspect.getfullargspec(self.experiment_lib[experiment])
            tmpargs = argspec.args
            tmpdefs = argspec.defaults
            if tmpdefs is None:
                tmpdefs = []

            # filter the Experiment BaseModel
            idxlist = []
            for idx, tmparg in enumerate(argspec.args):
                # if argspec.annotations.get(tmparg, None) == Experiment or tmparg=="experiment_version":
                if argspec.annotations.get(tmparg, None) == Experiment:
                    idxlist.append(idx)

            tmpargs = list(tmpargs)
            tmpdefs = list(tmpdefs)
            for j, idx in enumerate(idxlist):
                if len(tmpargs) == len(tmpdefs):
                    tmpargs.pop(idx - j)
                    tmpdefs.pop(idx - j)
                else:
                    tmpargs.pop(idx - j)
            # use defaults specified in config
            exp_defs = self.orch.world_cfg.get("experiment_params", {})
            tmpdefs = [exp_defs.get(ta, td) for ta, td in zip(tmpargs, tmpdefs)]
            tmpargs = tuple(tmpargs)
            tmpdefs = tuple(tmpdefs)

            for t in tmpdefs:
                t = json.dumps(t)

            self.experiments.append(
                return_experiment_lib(
                    index=i,
                    experiment_name=experiment,
                    doc=tmpdoc,
                    args=tmpargs,
                    defaults=tmpdefs,
                ).dict()
            )
        for item in self.experiments:
            self.experiment_select_list.append(item["experiment_name"])

    async def get_sequences(self):
        """get experiment list from orch"""
        sequences = self.orch.list_sequences()
        for key in self.sequence_list:
            self.sequence_list[key] = []

        for seq in sequences:
            seqdict = seq.json_dict()
            self.sequence_list["sequence_name"].append(
                seqdict.get("sequence_name", None)
            )
            self.sequence_list["sequence_uuid"].append(
                seqdict.get("sequence_uuid", None)
            )

        self.sequence_source.data = self.sequence_list
        self.vis.print_message(
            f"current queued sequences: ({len(self.orch.sequence_dq)})"
        )

    async def get_experiments(self):
        """get experiment list from orch"""
        experiments = self.orch.list_experiments()
        for key in self.experiment_list:
            self.experiment_list[key] = []

        for exp in experiments:
            expdict = exp.json_dict()
            self.experiment_list["experiment_name"].append(
                expdict.get("experiment_name", None)
            )
            self.experiment_list["experiment_uuid"].append(
                expdict.get("experiment_uuid", None)
            )

        self.experiment_source.data = self.experiment_list
        self.vis.print_message(
            f"current queued experiments: ({len(self.orch.experiment_dq)})"
        )

    async def get_actions(self):
        """get action list from orch"""
        actions = self.orch.list_actions()
        for key in self.action_list:
            self.action_list[key] = []

        for act in actions:
            actdict = act.json_dict()
            self.action_list["action_name"].append(actdict.get("action_name", None))
            self.action_list["action_server"].append(act.action_server.disp_name())
            self.action_list["action_uuid"].append(actdict.get("action_uuid", None))

        self.action_source.data = self.action_list
        self.vis.print_message(f"current queued actions: ({len(self.orch.action_dq)})")

    async def get_active_actions(self):
        """get action list from orch"""
        actions = self.orch.list_active_actions()
        for key in self.active_action_list:
            self.active_action_list[key] = []
        for act in actions:
            actdict = act.json_dict()
            liquid_list, solid_list, gas_list = unpack_samples_helper(
                samples=act.samples_in
            )
            self.vis.print_message(
                f"solids_in: {[s.get_global_label() for s in solid_list]}", sample=True
            )
            self.active_action_list["action_name"].append(
                actdict.get("action_name", None)
            )
            self.active_action_list["action_server"].append(
                act.action_server.disp_name()
            )
            self.active_action_list["action_uuid"].append(
                actdict.get("action_uuid", None)
            )
            self.active_action_list["samples_in"].append(
                [s.get_global_label() for s in act.samples_in]
            )
            self.active_action_list["solids_in"].append(
                [s.get_global_label() for s in solid_list]
            )

        self.active_action_source.data = self.active_action_list
        self.vis.print_message(f"current active actions: {self.active_action_list}")

    def callback_sequence_select(self, attr, old, new):
        idx = self.sequence_select_list.index(new)
        self.update_seq_param_layout(idx)
        self.vis.doc.add_next_tick_callback(
            partial(self.update_seq_doc, self.sequences[idx]["doc"])
        )

    def callback_experiment_select(self, attr, old, new):
        idx = self.experiment_select_list.index(new)
        self.update_exp_param_layout(idx)
        self.vis.doc.add_next_tick_callback(
            partial(self.update_exp_doc, self.experiments[idx]["doc"])
        )

    def callback_clicked_pmplot(self, event, sender):
        """double click/tap on PM plot to add/move marker"""
        self.vis.print_message(f"DOUBLE TAP PMplot: {event.x}, {event.y}")
        # get coordinates of doubleclick
        platex = event.x
        platey = event.y
        # transform to nearest sample point
        PMnum = self.get_samples([platex], [platey], sender)
        self.get_sample_infos(PMnum, sender)

    def callback_changed_plateid(self, attr, old, new, sender):
        """callback for plateid text input"""

        def to_int(val):
            try:
                return int(val)
            except ValueError:
                return None

        plateid = to_int(new)
        if plateid is not None:
            self.get_pm(new, sender)
            self.get_elements_plateid(new, sender)

            private_input, param_input = self.find_param_private_input(sender)
            if private_input is None or param_input is None:
                return

            # after selecting a new plate, we reset the sample_no
            input_sample_no = self.find_input(param_input, "solid_sample_no")
            if input_sample_no is not None:
                self.vis.doc.add_next_tick_callback(
                    partial(
                        self.callback_changed_sampleno,
                        attr="value",
                        old=input_sample_no.value,
                        new="1",
                        sender=input_sample_no,
                    )
                )

        else:
            self.vis.doc.add_next_tick_callback(
                partial(self.update_input_value, sender, "")
            )

    def callback_plate_sample_no_list_file(self, attr, old, new, sender, inputfield):
        f = io.BytesIO(b64decode(sender.value))
        sample_nos = json.dumps(np.loadtxt(f).astype(int).tolist())
        self.vis.doc.add_next_tick_callback(
            partial(self.update_input_value, inputfield, sample_nos)
        )

    def callback_changed_sampleno(self, attr, old, new, sender):
        """callback for sampleno text input"""

        def to_int(val):
            try:
                return int(val)
            except ValueError:
                return None

        sample_no = to_int(new)
        if sample_no is not None:
            self.get_sample_infos([sample_no - 1], sender)
        else:
            self.vis.doc.add_next_tick_callback(
                partial(self.update_input_value, sender, "")
            )

    def callback_estop_orch(self, event):
        self.vis.print_message("estop orch")
        self.vis.doc.add_next_tick_callback(partial(self.orch.estop_loop))

    def callback_start_orch(self, event):
        if self.orch.orchstatusmodel.loop_state == OrchStatus.stopped:
            self.vis.print_message("starting orch")
            self.vis.doc.add_next_tick_callback(partial(self.orch.start))
            self.vis.doc.add_next_tick_callback(partial(self.update_tables))
        elif self.orch.orchstatusmodel.loop_state == OrchStatus.estop:
            self.vis.print_message("orch is in estop", error=True)
        else:
            self.vis.print_message("Cannot start orch when not in a stopped state.")

    def callback_add_expplan(self, event):
        """add experiment plan as new sequene to orch sequence_dq"""
        if self.sequence is not None:
            sellabel = self.input_sequence_label.value
            self.sequence.sequence_label = sellabel
            self.vis.doc.add_next_tick_callback(
                partial(self.orch.add_sequence, self.sequence)
            )
            # clear current experiment_plan (sequence in operator)
            self.sequence = None
            self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_stop_orch(self, event):
        self.vis.print_message("stopping operator orch")
        self.vis.doc.add_next_tick_callback(partial(self.orch.stop))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_skip_exp(self, event):
        self.vis.print_message("skipping experiment")
        self.vis.doc.add_next_tick_callback(partial(self.orch.skip))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_clear_expplan(self, event):
        self.vis.print_message("clearing exp plan table")
        self.sequence = None
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_clear_sequences(self, event):
        self.vis.print_message("clearing experiments")
        self.vis.doc.add_next_tick_callback(partial(self.orch.clear_sequences))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_clear_experiments(self, event):
        self.vis.print_message("clearing experiments")
        self.vis.doc.add_next_tick_callback(partial(self.orch.clear_experiments))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_clear_actions(self, event):
        self.vis.print_message("clearing actions")
        self.vis.doc.add_next_tick_callback(partial(self.orch.clear_actions))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_prepend_seq(self, event):
        sequence = self.populate_sequence()
        for i, D in enumerate(sequence.experiment_plan_list):
            self.sequence.experiment_plan_list.insert(i, D)
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_append_seq(self, event):
        sequence = self.populate_sequence()
        for D in sequence.experiment_plan_list:
            self.sequence.experiment_plan_list.append(D)
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_prepend_exp(self, event):
        self.prepend_experiment()
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_append_exp(self, event):
        self.append_experiment()
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_update_tables(self, event):
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def append_experiment(self):
        experimenttemplate = self.populate_experimentmodel()
        self.sequence.experiment_plan_list.append(experimenttemplate)

    def prepend_experiment(self):
        experimenttemplate = self.populate_experimentmodel()
        self.sequence.experiment_plan_list.insert(0, experimenttemplate)

    def populate_sequence(self):
        selected_sequence = self.sequence_dropdown.value
        self.vis.print_message(f"selected sequence from list: {selected_sequence}")

        sequence_params = {
            paraminput.title: to_json(paraminput.value)
            for paraminput in self.seq_param_input
        }
        expplan_list = self.orch.unpack_sequence(
            sequence_name=selected_sequence, sequence_params=sequence_params
        )

        sequence = Sequence()
        sequence.sequence_name = selected_sequence
        sequence.sequence_label = self.input_sequence_label.value
        sequence.sequence_params = sequence_params
        for expplan in expplan_list:
            sequence.experiment_plan_list.append(expplan)

        if self.sequence is None:
            self.sequence = Sequence()
        self.sequence.sequence_name = sequence.sequence_name
        self.sequence.sequence_label = sequence.sequence_label
        self.sequence.sequence_params = sequence.sequence_params

        return sequence

    def populate_experimentmodel(self) -> ExperimentModel:
        selected_experiment = self.experiment_dropdown.value
        self.vis.print_message(f"selected experiment from list: {selected_experiment}")
        experiment_params = {
            paraminput.title: to_json(paraminput.value)
            for paraminput in self.exp_param_input
        }
        experimentmodel = ExperimentModel(
            experiment_name=selected_experiment, experiment_params=experiment_params
        )
        if self.sequence is None:
            self.sequence = Sequence()
        self.sequence.sequence_name = "manual_orch_seq"
        self.sequence.sequence_label = self.input_sequence_label.value
        return experimentmodel

    def refresh_inputs(self, param_input, private_input):
        input_plate_id = self.find_input(param_input, "solid_plate_id")
        input_sample_no = self.find_input(param_input, "solid_sample_no")
        if input_plate_id is not None:
            self.vis.doc.add_next_tick_callback(
                partial(
                    self.callback_changed_plateid,
                    attr="value",
                    old=input_plate_id.value,
                    new=input_plate_id.value,
                    sender=input_plate_id,
                )
            )
        if input_sample_no is not None:
            self.vis.doc.add_next_tick_callback(
                partial(
                    self.callback_changed_sampleno,
                    attr="value",
                    old=input_sample_no.value,
                    new=input_sample_no.value,
                    sender=input_sample_no,
                )
            )

    def update_input_value(self, sender, value):
        sender.value = value

    def update_seq_param_layout(self, idx):
        args = self.sequences[idx]["args"]
        defaults = self.sequences[idx]["defaults"]
        self.dynamic_col.children.pop(1)

        for _ in range(len(args) - len(defaults)):
            defaults.insert(0, "")

        self.seq_param_input = []
        self.seq_private_input = []
        self.seq_param_layout = [
            layout(
                [
                    [
                        Spacer(width=10),
                        Div(
                            text="<b>Optional sequence parameters:</b>",
                            width=200 + 50,
                            height=15,
                            style={"font-size": "100%", "color": "black"},
                        ),
                    ],
                ],
                background=self.color_sq_param_inputs,
                width=self.max_width,
            ),
        ]

        self.add_dynamic_inputs(
            self.seq_param_input,
            self.seq_private_input,
            self.seq_param_layout,
            args,
            defaults,
        )

        if not self.seq_param_input:
            self.seq_param_layout.append(
                layout(
                    [
                        [
                            Spacer(width=10),
                            Div(
                                text="-- none --",
                                width=200 + 50,
                                height=15,
                                style={"font-size": "100%", "color": "black"},
                            ),
                        ],
                    ],
                    background=self.color_sq_param_inputs,
                    width=self.max_width,
                ),
            )

        self.dynamic_col.children.insert(1, layout(self.seq_param_layout))

        self.refresh_inputs(self.seq_param_input, self.seq_private_input)

    def update_exp_param_layout(self, idx):
        args = self.experiments[idx]["args"]
        defaults = self.experiments[idx]["defaults"]
        self.dynamic_col.children.pop(3)

        for _ in range(len(args) - len(defaults)):
            defaults.insert(0, "")

        self.exp_param_input = []
        self.exp_private_input = []
        self.exp_param_layout = [
            layout(
                [
                    [
                        Spacer(width=10),
                        Div(
                            text="<b>Optional experiment parameters:</b>",
                            width=200 + 50,
                            height=15,
                            style={"font-size": "100%", "color": "black"},
                        ),
                    ],
                ],
                background=self.color_sq_param_inputs,
                width=self.max_width,
            ),
        ]
        self.add_dynamic_inputs(
            self.exp_param_input,
            self.exp_private_input,
            self.exp_param_layout,
            args,
            defaults,
        )

        if not self.exp_param_input:
            self.exp_param_layout.append(
                layout(
                    [
                        [
                            Spacer(width=10),
                            Div(
                                text="-- none --",
                                width=200 + 50,
                                height=15,
                                style={"font-size": "100%", "color": "black"},
                            ),
                        ],
                    ],
                    background=self.color_sq_param_inputs,
                    width=self.max_width,
                ),
            )

        self.dynamic_col.children.insert(3, layout(self.exp_param_layout))

        self.refresh_inputs(self.exp_param_input, self.exp_private_input)

    def add_dynamic_inputs(
        self, param_input, private_input, param_layout, args, defaults
    ):
        item = 0
        for idx in range(len(args)):
            def_val = f"{defaults[idx]}"
            # if args[idx] == "experiment":
            #     continue
            # disabled = False

            param_input.append(
                TextInput(
                    value=def_val,
                    title=args[idx],
                    disabled=True if args[idx].endswith("_version") else False,
                    width=400,
                    height=40,
                )
            )
            param_layout.append(
                layout(
                    [
                        [param_input[item]],
                        Spacer(height=10),
                    ],
                    background=self.color_sq_param_inputs,
                    width=self.max_width,
                )
            )
            item = item + 1

            # special key params
            if args[idx] == "solid_plate_id":
                param_input[-1].on_change(
                    "value",
                    partial(self.callback_changed_plateid, sender=param_input[-1]),
                )
                private_input.append(
                    figure(
                        title="PlateMap",
                        # height=300,
                        x_axis_label="X (mm)",
                        y_axis_label="Y (mm)",
                        width=self.max_width,
                        aspect_ratio=6 / 4,
                        aspect_scale=1,
                    )
                )
                private_input[-1].border_fill_color = self.color_sq_param_inputs
                private_input[-1].border_fill_alpha = 0.5
                private_input[-1].background_fill_color = self.color_sq_param_inputs
                private_input[-1].background_fill_alpha = 0.5
                private_input[-1].on_event(
                    DoubleTap,
                    partial(self.callback_clicked_pmplot, sender=param_input[-1]),
                )
                self.update_pm_plot(private_input[-1], [])
                param_layout.append(
                    layout(
                        [
                            [private_input[-1]],
                            Spacer(height=10),
                        ],
                        background=self.color_sq_param_inputs,
                        width=self.max_width,
                    )
                )

                private_input.append(
                    TextInput(
                        value="", title="elements", disabled=True, width=120, height=40
                    )
                )
                private_input.append(
                    TextInput(
                        value="", title="code", disabled=True, width=60, height=40
                    )
                )
                private_input.append(
                    TextInput(
                        value="",
                        title="composition",
                        disabled=True,
                        width=220,
                        height=40,
                    )
                )
                param_layout.append(
                    layout(
                        [
                            [private_input[-3], private_input[-2], private_input[-1]],
                            Spacer(height=10),
                        ],
                        background=self.color_sq_param_inputs,
                        width=self.max_width,
                    )
                )

            elif args[idx] == "solid_sample_no":
                param_input[-1].on_change(
                    "value",
                    partial(self.callback_changed_sampleno, sender=param_input[-1]),
                )

            elif args[idx] == "x_mm":
                param_input[-1].disabled = True

            elif args[idx] == "y_mm":
                param_input[-1].disabled = True

            elif args[idx] == "solid_custom_position":
                param_input[-1] = Select(
                    title=args[idx], value=None, options=self.dev_customitems
                )
                if self.dev_customitems:
                    if def_val in self.dev_customitems:
                        param_input[-1].value = def_val
                    else:
                        param_input[-1].value = self.dev_customitems[0]
                param_layout[-1] = layout(
                    [
                        [param_input[-1]],
                        Spacer(height=10),
                    ],
                    background=self.color_sq_param_inputs,
                    width=self.max_width,
                )

            elif args[idx] == "liquid_custom_position":
                param_input[-1] = Select(
                    title=args[idx], value=None, options=self.dev_customitems
                )
                if self.dev_customitems:
                    if def_val in self.dev_customitems:
                        param_input[-1].value = def_val
                    else:
                        param_input[-1].value = self.dev_customitems[0]
                param_layout[-1] = layout(
                    [
                        [param_input[-1]],
                        Spacer(height=10),
                    ],
                    background=self.color_sq_param_inputs,
                    width=self.max_width,
                )

            elif args[idx] == "plate_sample_no_list":
                private_input.append(FileInput(width=200, accept=".txt"))
                param_layout.append(
                    layout(
                        [
                            [private_input[-1]],
                            Spacer(height=10),
                        ],
                        background=self.color_sq_param_inputs,
                        width=self.max_width,
                    )
                )
                private_input[-1].on_change(
                    "value",
                    partial(
                        self.callback_plate_sample_no_list_file,
                        sender=private_input[-1],
                        inputfield=param_input[-1],
                    ),
                )

    def update_seq_doc(self, value):
        self.sequence_descr_txt.text = value.replace("\n", "<br>")

    def update_exp_doc(self, value):
        self.experiment_descr_txt.text = value.replace("\n", "<br>")

    def update_error(self, value):
        self.error_txt.text = value

    def update_xysamples(self, xval, yval, sender):

        private_input, param_input = self.find_param_private_input(sender)
        if private_input is None or param_input is None:
            return False

        for paraminput in param_input:
            if paraminput.title == "x_mm":
                paraminput.value = xval
            if paraminput.title == "y_mm":
                paraminput.value = yval

    def update_pm_plot(self, plot_mpmap, pmdata):
        """plots the plate map"""
        x = [col["x"] for col in pmdata]
        y = [col["y"] for col in pmdata]
        # remove old Pmplot
        old_point = plot_mpmap.select(name="PMplot")
        if len(old_point) > 0:
            plot_mpmap.renderers.remove(old_point[0])
        plot_mpmap.square(
            x, y, size=5, color=None, alpha=0.5, line_color="black", name="PMplot"
        )

    def get_pm(self, plateid, sender):
        """gets plate map"""
        private_input, param_input = self.find_param_private_input(sender)
        if private_input is None or param_input is None:
            return False

        # pmdata = json.loads(self.dataAPI.get_platemap_plateid(plateid))
        pmdata = self.dataAPI.get_platemap_plateid(plateid)
        if len(pmdata) == 0:
            self.vis.doc.add_next_tick_callback(
                partial(self.update_error, "no pm found")
            )

        plot_mpmap = self.find_plot(private_input, "PlateMap")
        if plot_mpmap is not None:
            self.vis.doc.add_next_tick_callback(
                partial(self.update_pm_plot, plot_mpmap, pmdata)
            )

    def xy_to_sample(self, xy, pmapxy):
        """get point from pmap closest to xy"""
        if len(pmapxy):
            diff = pmapxy - xy
            sumdiff = (diff**2).sum(axis=1)
            return np.int(np.argmin(sumdiff))
        else:
            return None

    def get_samples(self, X, Y, sender):
        """get list of samples row number closest to xy"""
        # X and Y are vectors

        private_input, param_input = self.find_param_private_input(sender)
        if private_input is None or param_input is None:
            return False

        input_plate_id = self.find_input(param_input, "solid_plate_id")

        if input_plate_id is not None:
            # pmdata = json.loads(self.dataAPI.get_platemap_plateid(input_plate_id.value))
            pmdata = self.dataAPI.get_platemap_plateid(input_plate_id.value)

            xyarr = np.array((X, Y)).T
            pmxy = np.array([[col["x"], col["y"]] for col in pmdata])
            samples = list(np.apply_along_axis(self.xy_to_sample, 1, xyarr, pmxy))
            return samples
        else:
            return [None]

    def get_elements_plateid(self, plateid: int, sender):
        """gets plate elements from aligner server"""

        private_input, param_input = self.find_param_private_input(sender)
        if private_input is None or param_input is None:
            return False

        input_elements = self.find_input(private_input, "elements")

        if input_elements is not None:

            elements = self.dataAPI.get_elements_plateid(
                plateid,
                multielementink_concentrationinfo_bool=False,
                print_key_or_keyword="screening_print_id",
                exclude_elements_list=[""],
                return_defaults_if_none=False,
            )
            if elements is not None:
                self.vis.doc.add_next_tick_callback(
                    partial(self.update_input_value, input_elements, ",".join(elements))
                )

    def find_plot(self, inputs, name):
        for inp in inputs:
            if isinstance(inp, Figure):
                if inp.title.text == name:
                    return inp
        return None

    def find_input(self, inputs, name):
        for inp in inputs:
            if isinstance(inp, TextInput):
                if inp.title == name:
                    return inp
        return None

    def find_param_private_input(self, sender):
        private_input = None
        param_input = None

        if sender in self.exp_param_input or sender in self.exp_private_input:
            private_input = self.exp_private_input
            param_input = self.exp_param_input

        elif sender in self.seq_param_input or sender in self.seq_private_input:
            private_input = self.seq_private_input
            param_input = self.seq_param_input

        return private_input, param_input

    def get_sample_infos(self, PMnum: List = None, sender=None):
        self.vis.print_message("updating samples")

        private_input, param_input = self.find_param_private_input(sender)
        if private_input is None or param_input is None:
            return False

        plot_mpmap = self.find_plot(private_input, "PlateMap")
        input_plate_id = self.find_input(param_input, "solid_plate_id")
        input_sample_no = self.find_input(param_input, "solid_sample_no")
        input_code = self.find_input(private_input, "code")
        input_composition = self.find_input(private_input, "composition")
        if (
            plot_mpmap is not None
            and input_plate_id is not None
            and input_sample_no is not None
        ):
            # pmdata = json.loads(self.dataAPI.get_platemap_plateid(input_plate_id.value))
            pmdata = self.dataAPI.get_platemap_plateid(input_plate_id.value)
            buf = ""
            if PMnum is not None and pmdata:
                if PMnum[0] is not None:  # need to check as this can also happen
                    self.vis.print_message(f"selected sample_no: {PMnum[0]+1}")
                    if PMnum[0] > len(pmdata) or PMnum[0] < 0:
                        self.vis.print_message("invalid sample no")
                        self.vis.doc.add_next_tick_callback(
                            partial(self.update_input_value, input_sample_no, "")
                        )
                        return False

                    platex = pmdata[PMnum[0]]["x"]
                    platey = pmdata[PMnum[0]]["y"]
                    code = pmdata[PMnum[0]]["code"]

                    buf = ""
                    for fraclet in ("A", "B", "C", "D", "E", "F", "G", "H"):
                        buf = "%s%s_%s " % (buf, fraclet, pmdata[PMnum[0]][fraclet])
                    if len(buf) == 0:
                        buf = "-"
                    if input_sample_no != str(PMnum[0] + 1):
                        self.vis.doc.add_next_tick_callback(
                            partial(
                                self.update_input_value,
                                input_sample_no,
                                str(PMnum[0] + 1),
                            )
                        )
                    self.vis.doc.add_next_tick_callback(
                        partial(self.update_xysamples, str(platex), str(platey), sender)
                    )
                    if input_composition is not None:
                        self.vis.doc.add_next_tick_callback(
                            partial(self.update_input_value, input_composition, buf)
                        )
                    if input_code is not None:
                        self.vis.doc.add_next_tick_callback(
                            partial(self.update_input_value, input_code, str(code))
                        )

                    # remove old Marker point
                    old_point = plot_mpmap.select(name="selsample")
                    if len(old_point) > 0:
                        plot_mpmap.renderers.remove(old_point[0])
                    # plot new Marker point
                    plot_mpmap.square(
                        platex,
                        platey,
                        size=7,
                        line_width=2,
                        color=None,
                        alpha=1.0,
                        line_color=(255, 0, 0),
                        name="selsample",
                    )

                    return True
            else:
                return False

        return False

    async def add_experiment_to_sequence(self):
        pass

    async def update_tables(self):
        await self.get_sequences()
        await self.get_experiments()
        await self.get_actions()
        await self.get_active_actions()
        for key in self.experiment_plan_list:
            self.experiment_plan_list[key] = []
        if self.sequence is not None:
            for D in self.sequence.experiment_plan_list:
                self.experiment_plan_list["sequence_name"].append(
                    self.sequence.sequence_name
                )
                self.experiment_plan_list["sequence_label"].append(
                    self.sequence.sequence_label
                )
                self.experiment_plan_list["experiment_name"].append(D.experiment_name)

        self.experimentplan_source.data = self.experiment_plan_list

        if self.orch.orchstatusmodel.loop_state == OrchStatus.started:
            self.orch_status_button.label = "started"
            self.orch_status_button.button_type = "success"
        elif self.orch.orchstatusmodel.loop_state == OrchStatus.stopped:
            stop_msg = (
                ": " + self.orch.current_stop_message
                if self.orch.current_stop_message != ""
                else ""
            )
            self.orch_status_button.label = f"stopped{stop_msg}"
            self.orch_status_button.button_type = "success"
            # self.orch_status_button.button_type = "danger"
        else:
            self.orch_status_button.label = (
                f"{self.orch.orchstatusmodel.loop_state.value}"
            )
            self.orch_status_button.button_type = "danger"

    async def IOloop(self):
        self.IOloop_run = True
        while self.IOloop_run:
            try:
                await asyncio.sleep(0.1)
                self.vis.doc.add_next_tick_callback(partial(self.update_tables))
                _ = await self.update_q.get()
            except Exception as e:
                tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
                self.vis.print_message(
                    f"Operator IOloop error: {repr(e), tb,}", error=True
                )
