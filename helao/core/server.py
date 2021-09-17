""" servers.py
Standard HelaoFastAPI action server and orchestrator classes.

"""
from importlib import import_module
import os
import sys
import json
import uuid
import shutil
import pyaml
from copy import copy
from collections import defaultdict, deque
from socket import gethostname
from time import ctime, time, strftime, strptime, time_ns
from typing import Optional, Union, List
from math import floor
from enum import Enum
import colorama

import numpy as np
import ntplib
import asyncio
import aiohttp
import aiofiles
from aiofiles.os import wrap
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.openapi.utils import get_flat_params


from bokeh.io import curdoc

from helao.core.helper import MultisubscriberQueue, dict_to_rcp, eval_val
from helao.core.helper import print_message
from helao.core.schema import Action, Decision
from helao.core.model import return_dec, return_declist, return_act, return_actlist
from helao.core.model import liquid_sample_no, gas_sample_no, solid_sample_no, samples_inout


async_copy = wrap(shutil.copy)

# ANSI color codes converted to the Windows versions
colorama.init(strip=not sys.stdout.isatty())  # strip colors if stdout is redirected
# colorama.init()

# version number, gets written into every rcp and hlo file
hlo_version = 0.2

class action_start_condition(int, Enum):
    no_wait = 0  # orch is dispatching an unconditional action
    wait_for_endpoint = 1  # orch is waiting for endpoint to become available
    wait_for_server = 2  # orch is waiting for server to become available
    wait_for_all = 3  #  (or other): orch is waiting for all action_dq to finish


class HelaoFastAPI(FastAPI):
    """Standard FastAPI class with HELAO config attached for simpler import."""

    def __init__(self, helao_cfg: dict, helao_srv: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helao_cfg = helao_cfg
        self.helao_srv = helao_srv


class HelaoBokehAPI:  # (curdoc):
    """Standard Bokeh class with HELAO config attached for simpler import."""

    def __init__(self, helao_cfg: dict, helao_srv: str, doc, *args, **kwargs):
        # super().__init__(*args, **kwargs)
        # self.helao_cfg = helao_cfg
        self.helao_srv = helao_srv
        self.world_cfg = helao_cfg

        self.srv_config = self.world_cfg["servers"][self.helao_srv]["params"]
        self.doc_name = self.srv_config.get("doc_name", "Bokeh App")
        self.doc = doc
        self.doc.title = self.doc_name


async def setupAct(request: Request):
    servKey, _, action_name = request.url.path.strip("/").partition("/")
    body_bytes = await request.body()
    if body_bytes == b"":
        body_params = {}
    else:
        body_params = await request.json()

    action_dict = dict()
    # action_dict.update(request.query_params)
    if len(request.query_params) == 0:  # cannot check against {}
        # empty: orch
        action_dict.update(body_params)
    else:
        # not empty: swagger
        if "action_params" not in action_dict:
            action_dict.update({"action_params": {}})
        action_dict["action_params"].update(body_params)
        # action_dict["action_params"].update(request.query_params)
        for k, v in request.query_params.items():
            try:
                val = json.loads(v)
            except ValueError:
                val = v
            action_dict["action_params"][k] = val

    action_dict["action_server"] = servKey
    action_dict["action_name"] = action_name
    A = Action(action_dict)
    # setting some default values of action was notsubmitted via orch
    if A.machine_name is None:
        A.machine_name = gethostname()
    if A.technique_name is None:
        A.technique_name = "MANUAL"
        A.orch_name = "MANUAL"
        A.decision_label = "MANUAL"

    return A


def makeActServ(
    config, server_key, server_title, description, version, driver_class=None
):
    app = HelaoFastAPI(
        config, server_key, title=server_title, description=description, version=version
    )

    @app.on_event("startup")
    def startup_event():
        app.base = Base(app)
        if driver_class:
            app.driver = driver_class(app.base)

    @app.websocket("/ws_status")
    async def websocket_status(websocket: WebSocket):
        """Broadcast status messages.

        Args:
        websocket: a fastapi.WebSocket object
        """
        await app.base.ws_status(websocket)

    @app.websocket("/ws_data")
    async def websocket_data(websocket: WebSocket):
        """Broadcast status dicts.

        Args:
        websocket: a fastapi.WebSocket object
        """
        await app.base.ws_data(websocket)

    @app.post("/get_status")
    def status_wrapper():
        return app.base.status

    @app.post("/attach_client")
    async def attach_client(client_servkey: str):
        return await app.base.attach_client(client_servkey)

    @app.post("/endpoints")
    def get_all_urls():
        """Return a list of all endpoints on this server."""
        return app.base.get_endpoint_urls(app)

    return app


def makeOrchServ(
    config, server_key, server_title, description, version, driver_class=None
):
    app = HelaoFastAPI(
        config, server_key, title=server_title, description=description, version=version
    )

    @app.on_event("startup")
    async def startup_event():
        """Run startup actions.

        When FastAPI server starts, create a global OrchHandler object, initiate the
        monitor_states coroutine which runs forever, and append dummy decisions to the
        decision queue for testing.
        """
        app.orch = Orch(app)
        if driver_class:
            app.driver = driver_class(app.orch)

    @app.post("/update_status")
    async def update_status(server: str, status: str):
        return await app.orch.update_status(
            act_serv=server, status_dict=json.loads(status)
        )

    @app.post("/attach_client")
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

    @app.post("/start")
    async def start_process():
        """Begin processing decision and action queues."""
        if app.orch.loop_state == "stopped":
            if (
                app.orch.action_dq or app.orch.decision_dq
            ):  # resume actions from a paused run
                await app.orch.start_loop()
            else:
                app.orch.print_message("decision list is empty")
        else:
            app.orch.print_message("already running")
        return {}

    @app.post("/estop")
    async def estop_process():
        """Emergency stop decision and action queues, interrupt running actions."""
        if app.orch.loop_state == "started":
            await app.orch.estop_loop()
        elif app.orch.loop_state == "E-STOP":
            app.orch.print_message("orchestrator E-STOP flag already raised")
        else:
            app.orch.print_message("orchestrator is not running")
        return {}

    @app.post("/stop")
    async def stop_process():
        """Stop processing decision and action queues after current actions finish."""
        if app.orch.loop_state == "started":
            await app.orch.intend_stop()
        elif app.orch.loop_state == "E-STOP":
            app.orch.print_message(
                "orchestrator E-STOP flag was raised; nothing to stop"
            )
        else:
            app.orch.print_message("orchestrator is not running")
        return {}

    @app.post("/clear_estop")
    async def clear_estop():
        """Remove emergency stop condition."""
        if app.orch.loop_state != "E-STOP":
            app.orch.print_message("orchestrator is not currently in E-STOP")
        else:
            await app.orch.clear_estate(clear_estop=True, clear_error=False)

    @app.post("/clear_error")
    async def clear_error():
        """Remove error condition."""
        if app.orch.loop_state != "ERROR":
            app.orch.print_message("orchestrator is not currently in ERROR")
        else:
            await app.orch.clear_estate(clear_estop=False, clear_error=True)

    @app.post("/skip")
    async def skip_decision():
        """Clear the present action queue while running."""
        if app.orch.loop_state == "started":
            await app.orch.intend_skip()
        else:
            app.orch.print_message("orchestrator not running, clearing action queue")
            await asyncio.sleep(0.001)
            app.orch.action_dq.clear()
        return {}

    @app.post("/clear_actions")
    async def clear_actions():
        """Clear the present action queue while stopped."""
        app.orch.print_message("clearing action queue")
        await asyncio.sleep(0.001)
        app.orch.action_dq.clear()
        return {}

    @app.post("/clear_decisions")
    async def clear_decisions():
        """Clear the present decision queue while stopped."""
        app.orch.print_message("clearing decision queue")
        await asyncio.sleep(0.001)
        app.orch.decision_dq.clear()
        return {}

    @app.post("/append_decision")
    async def append_decision(
        orch_name: str = None,
        decision_label: str = None,
        actualizer: str = None,
        actualizer_pars: dict = {},
        result_dict: dict = {},
        access: str = "hte",
    ):
        """Add a decision object to the end of the decision queue.

        Args:
        decision_dict: Decision parameters (optional), as dict.
        orch_name: Orchestrator server key (optional), as str.
        plate_id: The sample's plate id (no checksum), as int.
        sample_no: A sample number, as int.
        actualizer: The name of the actualizer for building the action list, as str.
        actualizer_pars: Actualizer parameters, as dict.
        result_dict: Action responses dict keyed by action_enum.
        access: Access control group, as str.

        Returns:
        Nothing.
        """
        await app.orch.add_decision(
            orch_name,
            decision_label,
            actualizer,
            actualizer_pars,
            result_dict,
            access,
            prepend=False,
        )
        return {}

    @app.post("/prepend_decision")
    async def prepend_decision(
        orch_name: str = None,
        decision_label: str = None,
        actualizer: str = None,
        actualizer_pars: dict = {},
        result_dict: dict = {},
        access: str = "hte",
    ):
        """Add a decision object to the start of the decision queue.

        Args:
        decision_dict: Decision parameters (optional), as dict.
        orch_name: Orchestrator server key (optional), as str.
        plate_id: The sample's plate id (no checksum), as int.
        sample_no: A sample number, as int.
        actualizer: The name of the actualizer for building the action list, as str.
        actualizer_pars: Actualizer parameters, as dict.
        result_dict: Action responses dict keyed by action_enum.
        access: Access control group, as str.

        Returns:
        Nothing.
        """
        await app.orch.add_decision(
            orch_name,
            decision_label,
            actualizer,
            actualizer_pars,
            result_dict,
            access,
            prepend=True,
        )
        return {}

    @app.post("/insert_decision")
    async def insert_decision(
        idx: int,
        decision_dict: dict = None,
        orch_name: str = None,
        decision_label: str = None,
        actualizer: str = None,
        actualizer_pars: dict = {},
        result_dict: dict = {},
        access: str = "hte",
    ):
        """Insert a decision object at decision queue index.

        Args:
        idx: index in decision queue for insertion, as int
        decision_dict: Decision parameters (optional), as dict.
        orch_name: Orchestrator server key (optional), as str.
        plate_id: The sample's plate id (no checksum), as int.
        sample_no: A sample number, as int.
        actualizer: The name of the actualizer for building the action list, as str.
        actualizer_pars: Actualizer parameters, as dict.
        result_dict: Action responses dict keyed by action_enum.
        access: Access control group, as str.

        Returns:
        Nothing.
        """
        await app.orch.add_decision(
            decision_dict,
            orch_name,
            decision_label,
            actualizer,
            actualizer_pars,
            result_dict,
            access,
            at_index=idx,
        )
        return {}

    @app.post("/list_decisions")
    def list_decisions():
        """Return the current list of decisions."""
        return app.orch.list_decisions()

    @app.post("/active_decision")
    def active_decision():
        """Return the active decision."""
        return app.orch.get_decision(last=False)

    @app.post("/last_decision")
    def last_decision():
        """Return the last decision."""
        return app.orch.get_decision(last=True)

    @app.post("/list_actions")
    def list_actions():
        """Return the current list of actions."""
        return app.orch.list_actions()

    @app.post("/list_active_actions")
    def list_active_actions():
        """Return the current list of actions."""
        return app.orch.list_active_actions()

    @app.post("/endpoints")
    def get_all_urls():
        """Return a list of all endpoints on this server."""
        return app.orch.get_endpoint_urls(app)

    @app.on_event("shutdown")
    def disconnect():
        """Run shutdown actions."""
        # emergencyStop = True
        time.sleep(0.75)

    return app


def makeVisServ(
    config,
    server_key,
    doc,
    server_title,
    description,
    version,
    driver_class=None,
):
    app = HelaoBokehAPI(
        config,
        server_key,
        doc=doc,
        title=server_title,
        description=description,
        ersion=version,
    )
    app.vis = Vis(app)
    return app


class Base(object):
    """Base class for all HELAO servers.

    Base is a general class which implements message passing, status update, data
    writing, and data streaming via async tasks. Every instrument and action server
    should import this class for efficient integration into an orchestrated environment.

    A Base initialized within a FastAPI startup event will launch three async tasks
    to the server's event loop for handling:
    (1) broadcasting status updates via websocket and http POST requests to an attached
        orchestrator's status updater if available,
    (2) data streaming via websocket,
    (3) data writing to local disk.

    Websocket connections are broadcast from a multisubscriber queue in order to handle
    consumption from multiple clients awaiting a single queue. Self-subscriber tasks are
    also created as initial subscribers to log all events and prevent queue overflow.

    The data writing method will update a class attribute with the currently open file.
    For a given root directory, files and folders will be written as follows:
    {%y.%j}/  # decision_date year.weeknum
        {%Y%m%d}/  # decision_date
            {%H%M%S}__{decision_label}/  # decision_time
                {%Y%m%d.%H%M%S}__{action_server_name}__{action_name}__{action_uuid}/
                    {filename}.{ext}
                    {%Y%m%d.%H%M%S%f}.rcp  # action_datetime
                    (aux_files)
    """

    def __init__(
        self,
        fastapp: HelaoFastAPI,
        calibration: dict = {},
    ):
        self.server_name = fastapp.helao_srv
        self.server_cfg = fastapp.helao_cfg["servers"][self.server_name]
        self.world_cfg = fastapp.helao_cfg
        self.hostname = gethostname()
        self.save_root = None
        self.technique_name = None
        self.aloop = asyncio.get_running_loop()

        if "technique_name" in self.world_cfg.keys():
            self.print_message(
                f" ... Found technique_name in config: {self.world_cfg['technique_name']}",
                info=True,
            )
            self.technique_name = self.world_cfg["technique_name"]
        else:
            raise ValueError(
                "Missing 'technique_name' in config, cannot create server object.",
                error=True,
            )

        self.calibration = calibration
        if "save_root" in self.world_cfg.keys():
            self.save_root = self.world_cfg["save_root"]
            self.print_message(
                f" ... Found root save directory in config: {self.world_cfg['save_root']}",
                info=True,
            )
            if not os.path.isdir(self.save_root):
                self.print_message(
                    " ... Warning: root save directory does not exist. Creatig it.",
                    warning=True,
                )
                os.makedirs(self.save_root)
        else:
            raise ValueError(
                " ... Warning: root save directory was not defined. Logs, RCPs, and data will not be written.",
                error=True,
            )
        self.actives = {}
        self.status = {}
        self.endpoints = []
        self.status_q = MultisubscriberQueue()
        self.data_q = MultisubscriberQueue()
        self.status_clients = set()
        self.ntp_server = "time.nist.gov"
        self.ntp_response = None
        self.ntp_offset = None  # add to system time for correction
        self.ntp_last_sync = None
        if os.path.exists("ntpLastSync.txt"):
            time_inst = open("ntpLastSync.txt", "r")
            tmps = time_inst.readlines()
            time_inst.close()
            if len(tmps) > 0:
                self.ntp_last_sync, self.ntp_offset = tmps[0].strip().split(",")
                self.ntp_offset = float(self.ntp_offset)
        elif self.ntp_last_sync is None:
            asyncio.gather(self.get_ntp_time())
        self.init_endpoint_status(fastapp)
        self.fast_urls = self.get_endpoint_urls(fastapp)
        self.status_logger = self.aloop.create_task(self.log_status_task())
        self.ntp_syncer = self.aloop.create_task(self.sync_ntp_task())

    def print_message(self, *args, **kwargs):
        print_message(self.server_cfg, self.server_name, *args, **kwargs)

        # style = self.server_cfg.get("msg_color","")
        # for arg in args:
        #     # print(f"{Style.BRIGHT}{Fore.GREEN}{arg}{Style.RESET_ALL}")
        #     print(f"[{strftime('%H:%M:%S')}_{self.server_name}]: {style}{arg}{Style.RESET_ALL}")

    def init_endpoint_status(self, app: FastAPI):
        "Populate status dict with FastAPI server endpoints for monitoring."
        for route in app.routes:
            if route.path.startswith(f"/{self.server_name}"):
                self.status[route.name] = []
                self.endpoints.append(route.name)
        self.print_message(
            f" ... Found {len(self.status)} endpoints for status monitoring on {self.server_name}."
        )

    def get_endpoint_urls(self, app: HelaoFastAPI):
        """Return a list of all endpoints on this server."""
        url_list = []
        for route in app.routes:
            routeD = {"path": route.path, "name": route.name}
            if "dependant" in dir(route):
                flatParams = get_flat_params(route.dependant)
                paramD = {
                    par.name: {
                        "outer_type": str(par.outer_type_).split("'")[1],
                        "type": str(par.type_).split("'")[1],
                        "required": par.required,
                        "shape": par.shape,
                        "default": par.default,
                    }
                    for par in flatParams
                }
                routeD["params"] = paramD
            else:
                routeD["params"] = []
            url_list.append(routeD)
        return url_list

    async def contain_action(
        self,
        action: Action,
        file_type: str = "helao__file",
        file_group: str = "helao_files",
        file_data_keys: Optional[str] = None, # this is also keyd by file_sample_keys
        file_sample_label: Optional[str] = None, # this is also keyd by file_sample_keys
        file_sample_keys: Optional[list] = None, # I need one key per datafile, but each datafile can still be based on multiple samples
        header: Optional[str] = None, # this is also keyd by file_sample_keys
    ):
        self.actives[action.action_uuid] = Base.Active(
            self,
            action=action,
            file_type=file_type,
            file_group=file_group,
            file_data_keys=file_data_keys,
            file_sample_label=file_sample_label,
            file_sample_keys=file_sample_keys,
            header=header,
        )
        await self.actives[action.action_uuid].myinit()
        return self.actives[action.action_uuid]


    def create_file_sample_label(self, samples):
        if samples is None:
            return None

        if type(samples) is not list:
            samples = [samples]

        file_sample_label={}
        for sample in samples:
            label = None
            if sample.sample_type == "liquid":
                if sample.liquid is not None:
                    label = f"{sample.machine}__{sample.liquid.id}"
                
            elif sample.sample_type == "gas":
                if sample.gas is not None:
                    label = f"{sample.machine}__{sample.gas.id}"
            elif sample.sample_type == "solid":
                if sample.solid is not None:
                    label = f"{sample.solid.plate_id}__{sample.solid.sample_no}"

            elif sample.sample_type == "sample_assembly":
                label = sample.label
            
            if label is not None:
                if sample.sample_type in file_sample_label:
                    file_sample_label[sample.sample_type].append(label)
                else:
                    file_sample_label[sample.sample_type]=[label]

        if len(file_sample_label) == 0:
            file_sample_label = None 
        return file_sample_label


    async def get_active_info(self, action_uuid: str):
        if action_uuid in self.actives.keys():
            action_dict = await self.actives[action_uuid].active.as_dict()
            return action_dict
        else:
            self.print_message(
                f" ... Specified action uuid {action_uuid} was not found.", error=True
            )
            return None

    async def get_ntp_time(self):
        "Check system clock against NIST clock for trigger operations."
        c = ntplib.NTPClient()
        response = c.request(self.ntp_server, version=3)
        self.ntp_response = response
        self.ntp_last_sync = response.orig_time
        self.ntp_offset = response.offset
        self.print_message(f" ... ntp_offset: {self.ntp_offset}")

        time_inst = await aiofiles.open("ntpLastSync.txt", "w")
        await time_inst.write(f"{self.ntp_last_sync},{self.ntp_offset}")
        await time_inst.close()
        self.print_message(
            f" ... retrieved time at {ctime(self.ntp_response.tx_timestamp)} from {self.ntp_server}"
        )

    async def attach_client(self, client_servkey: str, retry_limit=5):
        "Add client for pushing status updates via HTTP POST."
        success = False

        if client_servkey in self.world_cfg["servers"]:

            if client_servkey in self.status_clients:
                self.print_message(
                    f" ... Client {client_servkey} is already subscribed to {self.server_name} status updates."
                )
            else:
                self.status_clients.add(client_servkey)

                current_status = self.status
                for _ in range(retry_limit):
                    response = await async_private_dispatcher(
                        world_config_dict=self.world_cfg,
                        server=client_servkey,
                        private_action="update_status",
                        params_dict={
                            "server": self.server_name,
                            "status": json.dumps(current_status),
                        },
                        json_dict={},
                    )
                    if response == True:
                        self.print_message(
                            f" ... Added {client_servkey} to {self.server_name} status subscriber list."
                        )
                        success = True
                        break
                    else:
                        self.print_message(
                            f" ... Failed to add {client_servkey} to {self.server_name} status subscriber list.",
                            error=True,
                        )

            if success:
                self.print_message(
                    f" ... Updated {self.server_name} status to {current_status} on {client_servkey}."
                )
            else:
                self.print_message(
                    f" ... Failed to push status message to {client_servkey} after {retry_limit} attempts.",
                    error=True,
                )

        return success

    def detach_client(self, client_servkey: str):
        "Remove client from receiving status updates via HTTP POST"
        if client_servkey in self.status_clients:
            self.status_clients.remove(client_servkey)
            self.print_message(
                f"Client {client_servkey} will no longer receive status updates."
            )
        else:
            self.print_message(f" ... Client {client_servkey} is not subscribed.")

    async def ws_status(self, websocket: WebSocket):
        "Subscribe to status queue and send message to websocket client."
        self.print_message(" ... got new status subscriber")
        await websocket.accept()
        try:
            async for status_msg in self.status_q.subscribe():
                await websocket.send_text(json.dumps(status_msg))
        except WebSocketDisconnect:
            self.print_message(
                f" ... Status websocket client {websocket.client[0]}:{websocket.client[1]} disconnected.",
                error=True,
            )

    async def ws_data(self, websocket: WebSocket):
        "Subscribe to data queue and send messages to websocket client."
        self.print_message(" ... got new data subscriber")
        await websocket.accept()
        try:
            async for data_msg in self.data_q.subscribe():
                await websocket.send_text(json.dumps(data_msg))
        except WebSocketDisconnect:
            self.print_message(
                f" ... Data websocket client {websocket.client[0]}:{websocket.client[1]} disconnected.",
                error=True,
            )

    async def log_status_task(self, retry_limit: int = 5):
        "Self-subscribe to status queue, log status changes, POST to clients."
        self.print_message(f" ... {self.server_name} status log task created.")

        try:
            async for status_msg in self.status_q.subscribe():
                self.status.update(status_msg)
                for client_servkey in self.status_clients:
                    success = False

                    for _ in range(retry_limit):

                        response = await async_private_dispatcher(
                            world_config_dict=self.world_cfg,
                            server=client_servkey,
                            private_action="update_status",
                            params_dict={
                                "server": self.server_name,
                                "status": json.dumps(status_msg),
                            },
                            json_dict={},
                        )
                        if response == True:
                            self.print_message(
                                f" ... send status msg to {client_servkey}."
                            )
                            success = True
                            break
                        else:
                            self.print_message(
                                f" ... Failed to send status msg {client_servkey}."
                            )

                    if success:
                        self.print_message(
                            f" ... Updated {self.server_name} status to {status_msg} on {client_servkey}."
                        )
                    else:
                        self.print_message(
                            f" ... Failed to push status message to {client_servkey} after {retry_limit} attempts."
                        )

                # TODO:write to log if save_root exists
        except asyncio.CancelledError:
            self.print_message(" ... status logger task was cancelled", error=True)

    async def detach_subscribers(self):
        await self.status_q.put(StopAsyncIteration)
        await self.data_q.put(StopAsyncIteration)
        await asyncio.sleep(5)

    async def sync_ntp_task(self, resync_time: int = 600):
        "Regularly sync with NTP server."
        try:
            while True:
                time_inst = await aiofiles.open("ntpLastSync.txt", "r")
                ntp_last_sync = await time_inst.readline()
                await time_inst.close()
                self.ntp_last_sync = float(ntp_last_sync.strip())
                if time() - self.ntp_last_sync > resync_time:
                    await self.get_ntp_time()
                else:
                    wait_time = time() - self.ntp_last_sync
                    await asyncio.sleep(wait_time)
        except asyncio.CancelledError:
            self.print_message(" ... ntp sync task was cancelled", error=True)

    async def shutdown(self):
        await self.detach_subscribers()
        self.status_logger.cancel()
        self.ntp_syncer.cancel()

    class Active(object):
        """Active action holder which wraps data queing and rcp writing."""

        def __init__(
            self,
            base,  # outer instance
            action: Action,
            file_type: str = "helao__file",
            file_group: str = "helao_files",
            file_data_keys: Optional[str] = None,
            file_sample_label: Optional[str] = None,
            file_sample_keys: Optional[list] = None,
            header: Optional[str] = None,
        ):
            self.base = base
            self.action = action
            self.action.file_type = file_type
            self.action.file_group = file_group
            self.action.file_data_keys = file_data_keys
            self.action.file_sample_label = file_sample_label
            self.action.header = header
            
            # this can be filled in via copy_globals
            # or in the actualizer
            # but should not be written to rcp
            # as its filled in to  self.action.samples_in later by the server
            # this way samples can be action input params, without writing the
            # complete samples_inout object into the rcp
            if "samples_in" in self.action.action_params:
                del self.action.action_params["samples_in"]
            
            if file_sample_keys is None:
                self.action.file_sample_keys = ["None"]
                self.action.file_sample_label = {"None":self.action.file_sample_label}
                self.action.file_data_keys = {"None":self.action.file_data_keys}
                self.action.header = {"None":self.action.header}
            else:
                self.action.file_sample_keys = file_sample_keys
                if type(self.action.file_sample_keys) is not list:
                    self.action.file_sample_keys = [self.action.file_sample_keys]
                if self.action.file_sample_label is None:
                    self.action.file_sample_label = {f"{file_sample_key}":None for file_sample_key in self.action.file_sample_keys}
                if self.action.file_data_keys is None:
                    self.action.file_data_keys = {f"{file_sample_key}":None for file_sample_key in self.action.file_sample_keys}
                if self.action.header is None:
                    self.action.header = {f"{file_sample_key}":None for file_sample_key in self.action.file_sample_keys}
                    


            self.action.set_atime(offset=self.base.ntp_offset)
            self.action.gen_uuid_action(self.base.hostname)
            # signals the data logger that it got data and hlo header was written or not
            # active.finish_hlo_header should be called within the driver before
            # any data is pushed to avoid a forced header end write
            self.finished_hlo_header = dict()
            self.file_conn = dict()
            # if Action is not created from Decision+Actualizer, Action is independent
            if self.action.decision_timestamp is None:
                self.action.set_dtime(offset=self.base.ntp_offset)
                self.action.gen_uuid_decision(self.base.hostname)
            decision_date = self.action.decision_timestamp.split(".")[0]
            decision_time = self.action.decision_timestamp.split(".")[-1]
            year_week = strftime("%y.%U", strptime(decision_date, "%Y%m%d"))
            if not self.base.save_root:
                self.base.print_message(
                    " ... Root save directory not specified, cannot save action results."
                )
                self.action.save_data = False
                self.action.save_rcp = False
                self.action.output_dir = None
            else:
                if self.action.save_data is None:
                    self.action.save_data = False
                if self.action.save_rcp is None:
                    self.action.save_rcp = False
                # cannot save data without rcp
                if self.action.save_data is True:
                    self.action.save_rcp = True
                # self.action.save_data = True
                # self.action.save_rcp = True
                self.action.output_dir = os.path.join(
                    year_week,
                    decision_date,
                    f"{decision_time}_{self.action.decision_label}",
                    f"{self.action.action_queue_time}__{self.action.action_server}__{self.action.action_name}__{self.action.action_uuid}",
                )
            self.data_logger = self.base.aloop.create_task(self.log_data_task())


        async def myinit(self):
            if self.action.save_rcp:
                os.makedirs(os.path.join(self.base.save_root,self.action.output_dir), exist_ok=True)
                self.action.actionnum = (
                    f"{self.action.action_abbr}-{self.action.action_enum}"
                )
                # self.action.filetech_key = f"files_technique__{self.action.actionnum}"
                self.action.filetech_key = (
                    f"{self.base.server_name}_files__{self.action.actionnum}"
                )
                initial_dict = {
                    "hlo_version":hlo_version,
                    "technique_name": self.action.technique_name,  # self.base.technique_name,
                    "server_name": self.base.server_name,
                    "orchestrator": self.action.orch_name,
                    "machine_name": self.action.machine_name,  # self.base.hostname,
                    "access": self.action.access,
                    # "samples_in": self.action.samples_in,
                    "output_dir": self.action.output_dir,
                }
                initial_dict.update(self.base.calibration)
                # need to remove swagger workaround value if present
                if "scratch" in self.action.action_params:
                    del self.action.action_params["scratch"]
                initial_dict.update(
                    {
                        "decision_uuid": self.action.decision_uuid,
                        "action_uuid": self.action.action_uuid,
                        "action_enum": self.action.action_enum,
                        "action_name": self.action.action_name,
                        f"{self.base.server_name}_params__{self.action.actionnum}": self.action.action_params,
                    }
                )
                await self.write_to_rcp(initial_dict)

                if self.action.save_data:
                    for i, file_sample_key in enumerate(self.action.file_sample_keys):
                        filename, header, file_info = self.init_datafile(
                            header = self.action.header.get(file_sample_key,None),
                            file_type = self.action.file_type,
                            file_data_keys = self.action.file_data_keys.get(file_sample_key,None),
                            file_sample_label = self.action.file_sample_label.get(file_sample_key,None),
                            filename = None, # always autogen a filename
                            file_group = self.action.file_group,
                            action_enum = self.action.action_enum,
                            action_abbr = self.action.action_abbr,
                            filenum=i
                        )
                        
                        self.action.file_dict[self.action.filetech_key][
                            self.action.file_group
                        ].update({filename: file_info})
                        await self.set_output_file(
                            filename=filename, 
                            header=header, 
                            file_sample_key=file_sample_key,
                        )

            await self.add_status()


        def init_datafile(
                self, 
                header, 
                file_type, 
                file_data_keys, 
                file_sample_label,
                filename,
                file_group,
                action_enum,
                action_abbr,
                filenum: Optional[int] = 0
            ):

            if header:
                if isinstance(header, dict):
                    header_dict = copy(header)
                    header = pyaml.dump(
                        header, sort_dicts=False
                    )
                    header_lines = len(header_dict.keys())
                else:
                    if isinstance(header, list):
                        header_lines = len(header)
                        header = "\n".join(header)
                    else:
                        header_lines = len(header.split("\n"))
    
            file_info = {"type": file_type}
            if file_data_keys is not None:
                file_info.update({"keys": file_data_keys})
            if file_sample_label is not None:
                file_info.update({"sample": file_sample_label})
            if filename is None:  # generate filename
                file_ext = "csv"
                if file_group == "helao_files":
                    file_ext = "hlo"
                    if header is None:
                        header = pyaml.dump({"hlo_version":hlo_version}, sort_dicts=False)
                    else:
                        header = pyaml.dump({"hlo_version":hlo_version}, sort_dicts=False)+header
    
                if action_enum is not None:
                    filename = f"{action_abbr}-{action_enum:.1f}__{filenum}.{file_ext}"
                else:
                    filename = (
                        f"{action_abbr}-0.0__{filenum}.{file_ext}"
                    )

            if header:
                if not header.endswith("\n"):
                    header += "\n"

            return filename, header, file_info


        def finish_hlo_header(self, realtime: Optional[int] = None):
            # needs to be a sync function
            if realtime == None:
                 realtime = self.set_realtime_nowait()

            data_dict1 = dict()
            data_dict2 = dict()
            file_keys = []
            for file_key in self.file_conn.keys():
                data_dict1[file_key] = pyaml.dump({"epoch_ns":realtime})
                data_dict2[file_key] = "%%"
                file_keys.append(file_key)
                # before we push the header end onto the dataq, need to set the flag
                self.finished_hlo_header[file_key] = True

            self.enqueue_data_nowait(
                            data_dict1,
                            file_sample_keys = file_keys
                        )
            self.enqueue_data_nowait(
                            data_dict2,
                            file_sample_keys = file_keys
                        )
            

        async def add_status(self):
            self.base.status[self.action.action_name].append(self.action.action_uuid)
            self.base.print_message(
                f" ... Added {self.action.action_uuid} to {self.action.action_name} status list."
            )
            await self.base.status_q.put(
                {self.action.action_name: self.base.status[self.action.action_name]}
            )

        async def clear_status(self):
            if self.action.action_uuid in self.base.status[self.action.action_name]:
                self.base.status[self.action.action_name].remove(
                    self.action.action_uuid
                )
                self.base.print_message(
                    f" ... Removed {self.action.action_uuid} from {self.action.action_name} status list.",
                    info = True
                )
            else:
                self.base.print_message(
                    f" ... {self.action.action_uuid} did not excist in {self.action.action_name} status list.",
                    error = True
                )
            await self.base.status_q.put(
                {self.action.action_name: self.base.status[self.action.action_name]}
            )

        async def set_estop(self):
            self.base.status[self.action.action_name].remove(self.action.action_uuid)
            self.base.status[self.action.action_name].append(
                f"{self.action.action_uuid}__estop"
            )
            self.base.print_message(
                f" ... E-STOP {self.action.action_uuid} on {self.action.action_name} status.",
                error = True
            )
            await self.base.status_q.put(
                {self.action.action_name: self.base.status[self.action.action_name]}
            )

        async def set_error(self, err_msg: Optional[str] = None):
            self.base.status[self.action.action_name].remove(self.action.action_uuid)
            self.base.status[self.action.action_name].append(
                f"{self.action.action_uuid}__error"
            )
            self.base.print_message(
                f" ... ERROR {self.action.action_uuid} on {self.action.action_name} status.",
                error = True
            )
            if err_msg:
                self.action.error_code = err_msg
            else:
                self.action.error_code = "-1 unspecified error"
            await self.base.status_q.put(
                {self.action.action_name: self.base.status[self.action.action_name]}
            )


        async def set_realtime(
            self, epoch_ns: Optional[float] = None, offset: Optional[float] = None
        ):
            return self.set_realtime_nowait(epoch_ns=epoch_ns, offset=offset)


        def set_realtime_nowait(
            self, epoch_ns: Optional[float] = None, offset: Optional[float] = None
        ):
            if offset is None:
                if self.base.ntp_offset is not None:
                    offset_ns = int(np.floor(self.base.ntp_offset * 1e9))
                else:
                    offset_ns = 0.0
            else:
                offset_ns = int(np.floor(offset * 1e9))
            if epoch_ns is None:
                action_real_time = time_ns() + offset_ns
            else:
                action_real_time = epoch_ns + offset_ns
            return action_real_time


        async def set_output_file(self, filename: str, file_sample_key: str, header: Optional[str] = None):
            "Set active save_path, write header if supplied."
            output_path = os.path.join(self.base.save_root,self.action.output_dir, filename)
            self.base.print_message(f" ... writing data to: {output_path}")
            # create output file and set connection
            self.file_conn[file_sample_key] = await aiofiles.open(output_path, mode="a+")
            self.finished_hlo_header[file_sample_key] = False
            if header:
                if not header.endswith("\n"):
                    header += "\n"
                await self.file_conn[file_sample_key].write(header)


        async def write_live_data(self, output_str: str, file_conn_key):
            """Appends lines to file_conn."""
            if file_conn_key in self.file_conn:
                if self.file_conn[file_conn_key]:
                    if not output_str.endswith("\n"):
                        output_str += "\n"
                    await self.file_conn[file_conn_key].write(output_str)


        async def enqueue_data(self, data, errors: list = [], file_sample_keys: Optional[list] = None):
            await self.base.data_q.put(
                self.assemble_data_msg(
                    data=data,
                    errors=errors,
                    file_sample_keys=file_sample_keys
                )
            )


        def enqueue_data_nowait(self, data, errors: list = [], file_sample_keys: Optional[list] = None):
            self.base.data_q.put_nowait(
                self.assemble_data_msg(
                    data=data,
                    errors=errors,
                    file_sample_keys=file_sample_keys
                )
            )


        def assemble_data_msg(self, data, errors: list = [], file_sample_keys: list = None):
            data_dict = dict()
            if file_sample_keys is None:
               data_dict["None"] = data
            else:
                if type(file_sample_keys) is not list:
                    file_sample_keys = [file_sample_keys]
                for file_sample_key in file_sample_keys:
                    data_dict[file_sample_key] = data.get(file_sample_key,dict())

            data_msg = {
                self.action.action_uuid: {
                    "data": data_dict,
                    "action_name": self.action.action_name,
                    "errors": errors,
                }
            }
            return data_msg


        async def log_data_task(self):
            """Self-subscribe to data queue, write to present file path."""
            self.base.print_message(" ... starting data logger")
            # data_msg should be a dict {uuid: list of values or a list of list of values}
            try:
                async for data_msg in self.base.data_q.subscribe():
                    if (
                        self.action.action_uuid in data_msg.keys()
                    ):  # only write data for this action
                        data_dict = data_msg[self.action.action_uuid]
                        data_val = data_dict["data"]
                        self.action.data.append(data_val)
                        for sample, sample_data in data_val.items():
                            if sample in self.file_conn:
                                if self.file_conn[sample]:
                                    # check if end of hlo header was writen
                                    # else force it here
                                    # e.g. just write the separator
                                    if not self.finished_hlo_header[sample]:
                                        self.base.print_message(
                                            f" ... {self.action.action_abbr} data file {sample} is missing hlo separator. Writing it.",
                                            error = True
                                        )
                                        self.finished_hlo_header[sample] = True
                                        await self.write_live_data(
                                             output_str="%%",
                                             file_conn_key=sample
                                        )
                                        
                                    if type(sample_data) is dict:
                                        await self.write_live_data(
                                             output_str=json.dumps(sample_data),
                                             file_conn_key=sample
                                             )
                                    else:
                                        await self.write_live_data(
                                             output_str=sample_data,
                                             file_conn_key=sample
                                             )
                            else:
                                self.base.print_message(
                                    " ... {sample} doesn not exist in file_conn.", error=True
                                )

            except asyncio.CancelledError:
                self.base.print_message(
                    " ... data logger task was cancelled", error=True
                )


        async def write_file(
            self,
            output_str: str,
            file_type: str,
            filename: Optional[str] = None,
            file_group: Optional[str] = "aux_files",
            header: Optional[str] = None,
            sample_str: Optional[str] = None,
            file_sample_label: Optional[str] = None,
            file_data_keys: Optional[str] = None,
        ):
            "Write complete file, not used with queue streaming."
            if self.action.save_data:
                filename, header, file_info = self.init_datafile(
                    header = header,
                    file_type = file_type,
                    file_data_keys = file_data_keys, 
                    file_sample_label = file_sample_label,
                    filename = filename,
                    file_group = file_group,
                    action_enum = self.action.action_enum,
                    action_abbr = self.action.action_abbr,
                )
                output_path = os.path.join(self.base.save_root,self.action.output_dir, filename)
                self.base.print_message(f" ... writing non stream data to: {output_path}")

                file_instance = await aiofiles.open(output_path, mode="w")
                await file_instance.write(header + output_str)
                await file_instance.close()
                self.action.file_dict[self.action.filetech_key][file_group].update(
                    {filename: file_info}
                )


        def write_file_nowait(
            self,
            output_str: str,
            file_type: str,
            filename: Optional[str] = None,
            file_group: Optional[str] = "aux_files",
            header: Optional[str] = None,
            sample_str: Optional[str] = None,
            file_sample_label: Optional[str] = None,
            file_data_keys: Optional[str] = None,
        ):
            "Write complete file, not used with queue streaming."
            if self.action.save_data:
                filename, header, file_info = self.init_datafile(
                    header = header,
                    file_type = file_type,
                    file_data_keys = file_data_keys, 
                    file_sample_label = file_sample_label,
                    filename = filename,
                    file_group = file_group,
                    action_enum = self.action.action_enum,
                    action_abbr = self.action.action_abbr,
                )
                output_path = os.path.join(self.base.save_root,self.action.output_dir, filename)
                self.base.print_message(f" ... writing non stream data to: {output_path}")

                file_instance = open(output_path, mode="w")
                file_instance.write(header + output_str)
                file_instance.close()
                self.action.file_dict[self.action.filetech_key][file_group].update(
                    {filename: file_info}
                )


        async def write_to_rcp(self, rcp_dict: dict):
            "Create new rcp if it doesn't exist, otherwise append rcp_dict to file."
            output_path = os.path.join(
                self.base.save_root,
                self.action.output_dir,
                f"{self.action.action_queue_time}.rcp"
            )
            self.base.print_message(f" ... writing to rcp: {output_path}")
            # self.base.print_message(" ... writing:",rcp_dict)
            output_str = pyaml.dump(rcp_dict, sort_dicts=False)
            file_instance = await aiofiles.open(output_path, mode="a+")

            if not output_str.endswith("\n"):
                output_str += "\n"

            await file_instance.write(output_str)
            await file_instance.close()
           

        async def append_sample(
            self,
            samples: Union[List[samples_inout],samples_inout]
        ):
            "Add sample to samples_out and samples_in dict"

            # - inheritance
            # give_only:
            # receive_only:
            # allow_both:
            # block_both:

            # - status:
            # created: pretty self-explanatory; the sample was created during the process.
            # destroyed: also self-explanatory
            # preserved: the sample exists before and after the process. e.g. an echem experiment
            # incorporated: the sample was combined with others in the process. E.g. the creation of an electrode assembly from electrodes and electrolytes
            # recovered: the opposite of incorporated. E.g. an electrode assembly is taken apart, and the original electrodes are recovered, and further experiments may be done on those electrodes

            def add_subkeys(status, inheritance):
                subdict = dict()
                if inheritance is not None:
                    subdict.update({"inheritance": inheritance})
                if status is not None:
                    if type(status) is not list:
                        status = [status]
                    subdict.update({"status": status})
                return subdict

            def solid_to_dict(solid):
                solid_dict = dict()
                if solid is not None:
                    solid_dict.update({"plate_id": solid.plate_id})
                    solid_dict.update({"sample_no": solid.sample_no})
                return solid_dict

            def gas_to_dict(gas):
                gas_dict = dict()
                if gas is not None:
                    gas_dict.update({"sample_no": gas.id})
                return gas_dict

            def liquid_to_dict(liquid):
                liquid_dict = dict()
                if liquid is not None:
                    liquid_dict.update({"sample_no": liquid.id})
                return liquid_dict

            def update_dict(self, in_out, sample_type, append_dict):
                if in_out == "in":
                    if sample_type in self.action.samples_in:
                        self.action.samples_in[sample_type].append(append_dict)
                    else:
                        self.action.samples_in[sample_type] = [append_dict]
                if in_out == "out":
                    if sample_type in self.action.samples_in:
                        self.action.samples_out[sample_type].append(append_dict)
                    else:
                        self.action.samples_out[sample_type] = [append_dict]

            def append_liquid(liquid, machine, status, inheritance):
                append_dict = {
                    "label": f"{machine}__{liquid.id}",
                    "machine": machine,
                }
                append_dict.update(liquid_to_dict(liquid))
                append_dict.update(add_subkeys(status, inheritance))
                return append_dict

            def append_gas(gas, machine, status, inheritance):
                append_dict = {
                    "label": f"{machine}__{gas.id}",
                    "machine": machine,
                }
                append_dict.update(gas_to_dict(gas))
                append_dict.update(add_subkeys(status, inheritance))
                return append_dict

            def append_solid(solid, machine, status, inheritance):
                append_dict = {
                    "label": f"{solid.plate_id}__{solid.sample_no}",
                }
                append_dict.update(solid_to_dict(solid))
                append_dict.update(add_subkeys(status, inheritance))
                return append_dict


            if samples is None:
                return

            if type(samples) is not list:
                    samples = [samples]
                    
            for sample in samples:
                if sample.inheritance is None:
                    sample.inheritance = "allow_both"
                if sample.status is None:
                    sample.status = "preserved"
                if sample.machine is None:
                    sample.machine = self.action.machine_name
    
                if sample.sample_type == "solid":
                    append_dict = append_solid(sample.solid, sample.machine, sample.status, sample.inheritance)
                    update_dict(self, sample.in_out, sample.sample_type, append_dict)
    
                elif sample.sample_type == "liquid":
                    append_dict = append_liquid(sample.liquid, sample.machine, sample.status, sample.inheritance)
                    update_dict(self, sample.in_out, sample.sample_type, append_dict)
    
                elif sample.sample_type == "gas":
                    append_dict = append_gas(sample.liquid, sample.machine, sample.status, sample.inheritance)
                    update_dict(self, sample.in_out, sample.sample_type, append_dict)
    
                elif sample.sample_type == "liquid_reservoir":
                    append_dict = append_liquid(sample.liquid, sample.machine, sample.status, sample.inheritance)
                    update_dict(self, sample.in_out, sample.sample_type, append_dict)
    
                elif sample.sample_type == "sample_assembly":
                    append_dict = {
                        "label": f"{sample.label}",
                        "machine": sample.machine,
                    }
                    if sample.liquid is not None:
                        append_dict["liquid"] = [
                            append_liquid(sample.liquid, sample.machine, None, None)
                        ]
                    if sample.solid is not None:
                        append_dict["solid"] = [
                            append_solid(sample.solid, sample.machine, None, None)
                        ]
                    if sample.gas is not None:
                        append_dict["gas"] = [append_gas(sample.gas, sample.machine, None, None)]
                    append_dict.update(add_subkeys(sample.status, sample.inheritance))
                    update_dict(self, sample.in_out, sample.sample_type, append_dict)
    
                else:
                    self.base.print_message(f"Type '{sample.sample_type}' is not supported.", error = True)


        async def finish(self):
            "Close file_conn, finish rcp, copy aux, set endpoint status, and move active dict to past."
            await asyncio.sleep(1)
            self.base.print_message(" ... finishing data logging.")
            for filekey in self.file_conn.keys():
                if self.file_conn[filekey]:
                    await self.file_conn[filekey].close()
            self.file_conn = dict()

            if self.action.samples_in:
                await self.write_to_rcp({"samples_in": self.action.samples_in})
            if self.action.samples_out:
                await self.write_to_rcp({"samples_out": self.action.samples_out})
            if self.action.file_dict:
                await self.write_to_rcp(self.action.file_dict)
            await self.clear_status()
            self.data_logger.cancel()
            _ = self.base.actives.pop(self.action.action_uuid, None)
            return self.action

        async def track_file(self, file_type: str, file_path: str, sample_no: str):
            "Add auxiliary files to file dictionary."
            if os.path.dirname(file_path) != os.path.join(self.base.save_root,self.action.output_dir):
                self.action.file_paths.append(file_path)
            file_info = f"{file_type};{sample_no}"
            filename = os.path.basename(file_path)
            self.action.file_dict[self.action.filetech_key]["aux_files"].update(
                {filename: file_info}
            )
            self.base.print_message(
                f" ... {filename} added to files_technique__{self.action.actionnum} / aux_files list."
            )

        async def relocate_files(self):
            "Copy auxiliary files from folder path to rcp directory."
            for x in self.action.file_paths:
                new_path = os.path.join(
                    self.base.save_root,
                    self.action.output_dir,
                    os.path.basename(x)
                )
                await async_copy(x, new_path)


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
        # self.import_actualizers()
        self.action_lib = import_actualizers(
            world_config_dict=self.world_cfg,
            library_path=None,
            server_name=self.server_name,
        )
        # instantiate decision/experiment queue, action queue
        self.decision_dq = deque([])
        self.action_dq = deque([])
        self.dispatched_actions = {}
        self.active_decision = None
        self.last_decision = None

        # compilation of action server status dicts
        self.global_state_dict = defaultdict(lambda: defaultdict(list))
        self.global_state_dict["_internal"]["async_action_dispatcher"] = []
        self.global_q = MultisubscriberQueue()  # passes global_state_dict dicts
        self.dispatch_q = self.global_q.queue()

        # global state of all instruments as string [idle|busy] independent of dispatch loop
        self.global_state_str = None

        # uuid lists for estop and error tracking used by update_global_state_task
        self.error_uuids = []
        self.estop_uuids = []
        self.running_uuids = []

        self.init_success = False  # need to subscribe to all fastapi servers in config
        # present dispatch loop state [started|stopped]
        self.loop_state = "stopped"

        # separate from global state, signals dispatch loop control [skip|stop|None]
        self.loop_intent = None

        # pointer to dispatch_loop_task
        self.loop_task = None
        self.status_subscriber = asyncio.create_task(self.subscribe_all())
        self.status_subscriber = asyncio.create_task(self.update_global_state_task())

    async def check_dispatch_queue(self):
        val = await self.dispatch_q.get()
        while not self.dispatch_q.empty():
            val = await self.dispatch_q.get()
        return val

    async def check_wait_for_all_actions(self):
        running_states, _ = await self.check_global_state()
        global_free = len(running_states) == 0
        self.print_message(f" ... check len(running_states): {len(running_states)}")
        return global_free

    async def subscribe_all(self, retry_limit: int = 5):
        """Subscribe to all fastapi servers in config."""
        fails = []
        for serv_key, serv_dict in self.world_cfg["servers"].items():
            if "fast" in serv_dict.keys():
                self.print_message(f" ... trying to subscribe to {serv_key} status")

                success = False
                for _ in range(retry_limit):
                    response = await async_private_dispatcher(
                        world_config_dict=self.world_cfg,
                        server=serv_key,
                        private_action="attach_client",
                        params_dict={"client_servkey": self.server_name},
                        json_dict={},
                    )
                    if response == True:
                        success = True
                        break

                serv_addr = serv_dict["host"]
                serv_port = serv_dict["port"]
                if success:
                    self.print_message(
                        f"Subscribed to {serv_key} at {serv_addr}:{serv_port}"
                    )
                else:
                    fails.append(serv_key)
                    self.print_message(
                        f" ... Failed to subscribe to {serv_key} at {serv_addr}:{serv_port}. Check connection."
                    )

        if len(fails) == 0:
            self.init_success = True
        else:
            self.print_message(
                " ... Orchestrator cannot process decision_dq unless all FastAPI servers in config file are accessible."
            )

    async def update_status(self, act_serv: str, status_dict: dict):
        """Dict update method for action server to push status messages.

        Async task for updating orch status dict {act_serv_key: {act_name: [act_uuid]}}
        """
        last_dict = self.global_state_dict[act_serv]
        for act_name, acts in status_dict.items():
            if set(acts) != set(last_dict[act_name]):
                started = set(acts).difference(last_dict[act_name])
                removed = set(last_dict[act_name]).difference(acts)
                ongoing = set(acts).intersection(last_dict[act_name])
                if removed:
                    self.print_message(
                        f" ... '{act_serv}:{act_name}' finished {','.join(removed)}"
                    )
                if started:
                    self.print_message(
                        f" ... '{act_serv}:{act_name}' started {','.join(started)}"
                    )
                if ongoing:
                    self.print_message(
                        f" ... '{act_serv}:{act_name}' ongoing {','.join(ongoing)}"
                    )
        self.global_state_dict[act_serv].update(status_dict)
        await self.global_q.put(self.global_state_dict)
        return True

    async def update_global_state(self, status_dict: dict):
        _running_uuids = []
        for act_serv, act_named in status_dict.items():
            for act_name, uuids in act_named.items():
                for myuuid in uuids:
                    uuid_tup = (act_serv, act_name, myuuid)
                    if myuuid.endswith("__estop"):
                        self.estop_uuids.append(uuid_tup)
                    elif myuuid.endswith("__error"):
                        self.error_uuids.append(uuid_tup)
                    else:
                        _running_uuids.append(uuid_tup)
        self.running_uuids = _running_uuids

    async def update_global_state_task(self):
        """Self-subscribe to global_q and update status dict."""
        async for status_dict in self.global_q.subscribe():
            await self.update_global_state(status_dict)
            running_states, _ = await self.check_global_state()
            if self.estop_uuids and self.loop_state == "started":
                await self.estop_loop()
            elif self.error_uuids and self.loop_state == "started":
                self.global_state_str = "error"
            elif len(running_states) == 0:
                self.global_state_str = "idle"
            else:
                self.global_state_str = "busy"
                self.print_message(f" ... running_states: {running_states}")

    async def check_global_state(self):
        """Return global state of action servers."""
        running_states = []
        idle_states = []
        # self.print_message(" ... checking global state:")
        # self.print_message(self.global_state_dict.items())
        for act_serv, act_dict in self.global_state_dict.items():
            self.print_message(f" ... checking {act_serv} state")
            for act_name, act_uuids in act_dict.items():
                if len(act_uuids) == 0:
                    idle_states.append(f"{act_serv}:{act_name}")
                else:
                    running_states.append(f"{act_serv}:{act_name}:{len(act_uuids)}")
            await asyncio.sleep(
                0.001
            )  # allows status changes to affect between action_dq, also enforce unique timestamp
        return running_states, idle_states

    async def dispatch_loop_task(self):
        """Parse decision and action queues, and dispatch action_dq while tracking run state flags."""
        self.print_message(" ... running operator orch")
        self.print_message(f" ... orch status: {self.global_state_str}")
        # clause for resuming paused action list
        self.print_message(f" ... orch descisions: {self.decision_dq}")
        try:
            self.loop_state = "started"
            while self.loop_state == "started" and (self.action_dq or self.decision_dq):
                self.print_message(
                    f" ... current content of action_dq: {self.action_dq}"
                )
                self.print_message(
                    f" ... current content of decision_dq: {self.decision_dq}"
                )
                await asyncio.sleep(
                    0.001
                )  # allows status changes to affect between action_dq, also enforce unique timestamp
                if not self.action_dq:
                    self.print_message(" ... getting action_dq from new decision")
                    # generate uids when populating, generate timestamp when acquring
                    self.last_decision = copy(self.active_decision)
                    self.active_decision = self.decision_dq.popleft()
                    self.active_decision.technique_name = self.technique_name
                    self.active_decision.machine_name = self.hostname
                    self.active_decision.set_dtime(offset=self.ntp_offset)
                    self.active_decision.gen_uuid_decision(self.hostname)
                    actualizer = self.active_decision.actualizer
                    # additional actualizer params should be stored in decision.actualizer_pars
                    unpacked_acts = self.action_lib[actualizer](self.active_decision)
                    for i, act in enumerate(unpacked_acts):
                        act.action_enum = float(i)  # f"{i}"
                        # act.gen_uuid()
                    # TODO:update actualizer code
                    self.action_dq = deque(unpacked_acts)
                    self.dispatched_actions = {}
                    self.print_message(f" ... got: {self.action_dq}")
                    self.print_message(
                        f" ... optional params: {self.active_decision.actualizer_pars}"
                    )
                else:
                    if self.loop_intent == "stop":
                        self.print_message(" ... stopping orchestrator")
                        # monitor status of running action_dq, then end loop
                        # async for _ in self.global_q.subscribe():
                        while True:
                            _ = await self.check_dispatch_queue()
                            if self.global_state_str == "idle":
                                self.loop_state = "stopped"
                                await self.intend_none()
                                break
                    elif self.loop_intent == "skip":
                        # clear action queue, forcing next decision
                        self.action_dq.clear()
                        await self.intend_none()
                        self.print_message(" ... skipping to next decision")
                    else:
                        # all action blocking is handled like preempt, check Action requirements
                        A = self.action_dq.popleft()
                        # append previous results to current action
                        A.result_dict = self.active_decision.result_dict

                        # see async_action_dispatcher for unpacking
                        if isinstance(A.start_condition, int):
                            if A.start_condition == action_start_condition.no_wait:
                                self.print_message(
                                    " ... orch is dispatching an unconditional action"
                                )
                            else:
                                if (
                                    A.start_condition
                                    == action_start_condition.wait_for_endpoint
                                ):
                                    self.print_message(
                                        " ... orch is waiting for endpoint to become available"
                                    )
                                    # async for _ in self.global_q.subscribe():
                                    while True:
                                        _ = await self.check_dispatch_queue()
                                        endpoint_free = (
                                            len(
                                                self.global_state_dict[A.action_server][
                                                    A.action_name
                                                ]
                                            )
                                            == 0
                                        )
                                        if endpoint_free:
                                            break
                                elif (
                                    A.start_condition
                                    == action_start_condition.wait_for_server
                                ):
                                    self.print_message(
                                        " ... orch is waiting for server to become available"
                                    )
                                    # async for _ in self.global_q.subscribe():
                                    while True:
                                        _ = await self.check_dispatch_queue()
                                        server_free = all(
                                            [
                                                len(uuid_list) == 0
                                                for _, uuid_list in self.global_state_dict[
                                                    A.action_server
                                                ].items()
                                            ]
                                        )
                                        if server_free:
                                            break
                                else:  # start_condition is 3 or unsupported value
                                    self.print_message(
                                        " ... orch is waiting for all action_dq to finish"
                                    )
                                    if not await self.check_wait_for_all_actions():
                                        while True:
                                            _ = await self.check_dispatch_queue()
                                            if await self.check_wait_for_all_actions():
                                                break
                                    else:
                                        self.print_message(" ... global_free is true")
                        elif isinstance(A.start_condition, dict):
                            self.print_message(
                                " ... waiting for multiple conditions on external servers"
                            )
                            condition_dict = A.start_condition
                            # async for _ in self.global_q.subscribe():
                            while True:
                                _ = await self.check_dispatch_queue()
                                conditions_free = all(
                                    [
                                        len(self.global_state_dict[k][v] == 0)
                                        for k, vlist in condition_dict.items()
                                        if vlist and isinstance(vlist, list)
                                        for v in vlist
                                    ]
                                    + [
                                        len(uuid_list) == 0
                                        for k, v in condition_dict.items()
                                        if v == [] or v is None
                                        for _, uuid_list in self.global_state_dict[
                                            k
                                        ].items()
                                    ]
                                )
                                if conditions_free:
                                    break
                        else:
                            self.print_message(
                                " ... invalid start condition, waiting for all action_dq to finish"
                            )
                            # async for _ in self.global_q.subscribe():
                            while True:
                                _ = await self.check_dispatch_queue()
                                if await self.check_wait_for_all_actions():
                                    break

                        self.print_message(" ... copying global vars to action")

                        # copy requested global param to action params
                        for k, v in A.from_global_params.items():
                            self.print_message(f"{k}:{v}")
                            if k in self.active_decision.global_params.keys():
                                A.action_params.update(
                                    {v: self.active_decision.global_params[k]}
                                )

                        self.print_message(" ... dispatching action", A.as_dict())
                        self.print_message(
                            f" ... dispatching action {A.action_name} on server {A.action_server}"
                        )
                        # keep running list of dispatched actions
                        self.dispatched_actions[A.action_enum] = copy(A)
                        result = await async_action_dispatcher(self.world_cfg, A)
                        self.active_decision.result_dict[A.action_enum] = result

                        self.print_message(" ... copying global vars back to decision")
                        # self.print_message(result)
                        if "to_global_params" in result:
                            for k in result["to_global_params"]:
                                if k in result["action_params"].keys():
                                    if (
                                        result["action_params"][k] is None
                                        and k
                                        in self.active_decision.global_params.keys()
                                    ):
                                        self.active_decision.global_params.pop(k)
                                    else:
                                        self.active_decision.global_params.update(
                                            {k: result["action_params"][k]}
                                        )
                        self.print_message(
                            " ... done copying global vars back to decision"
                        )

            self.print_message(" ... decision queue is empty")
            self.print_message(" ... stopping operator orch")
            self.loop_state = "stopped"
            await self.intend_none()
            return True
        # except asyncio.CancelledError:
        #     self.print_message(" ... serious orch exception occurred",error = True)
        #     return False
        except Exception as e:
            self.print_message(" ... serious orch exception occurred", error=True)
            self.print_message(f"ERROR: {e}", error=True)
            return False

    async def start_loop(self):
        if self.loop_state == "stopped":
            self.loop_task = asyncio.create_task(self.dispatch_loop_task())
        elif self.loop_state == "E-STOP":
            self.print_message(
                " ... E-STOP flag was raised, clear E-STOP before starting."
            )
        else:
            self.print_message(" ... loop already started.")
        return self.loop_state

    async def estop_loop(self):
        self.loop_state = "E-STOP"
        self.loop_task.cancel()
        await self.force_stop_running_action_q()
        await self.intend_none()

    async def force_stop_running_action_q(self):
        running_uuids = []
        estop_uuids = []
        for act_serv, act_named in self.global_state_dict.items():
            for act_name, uuids in act_named.items():
                for myuuid in uuids:
                    uuid_tup = (act_serv, act_name, myuuid)
                    if myuuid.endswith("__estop"):
                        estop_uuids.append(uuid_tup)
                    else:
                        running_uuids.append(uuid_tup)
        running_servers = list(set([serv for serv, _, _ in running_uuids]))
        for serv in running_servers:
            serv_conf = self.world_cfg["servers"][serv]
            async with aiohttp.ClientSession() as session:
                self.print_message(f" ... Sending force-stop request to {serv}")
                async with session.post(
                    f"http://{serv_conf['host']}:{serv_conf['port']}/force_stop"
                ) as resp:
                    response = await resp.text()
                    self.print_message(response)

    async def intend_skip(self):
        await asyncio.sleep(0.001)
        self.loop_intent = "skip"

    async def intend_stop(self):
        await asyncio.sleep(0.001)
        self.loop_intent = "stop"

    async def intend_none(self):
        await asyncio.sleep(0.001)
        self.loop_intent = None

    async def clear_estate(self, clear_estop=True, clear_error=True):
        if not clear_estop and not clear_error:
            self.print_message(
                " ... both clear_estop and clear_error parameters are False, nothing to clear"
            )
        cleared_status = copy(self.global_state_dict)
        if clear_estop:
            for serv, act, myuuid in self.estop_uuids:
                self.print_message(f" ... clearing E-STOP {act} on {serv}")
                cleared_status[serv][act] = cleared_status[serv][act].remove(myuuid)
        if clear_error:
            for serv, act, myuuid in self.error_uuids:
                self.print_message(f" ... clearing error {act} on {serv}")
                cleared_status[serv][act] = cleared_status[serv][act].remove(myuuid)
        await self.global_q.put(cleared_status)
        self.print_message(" ... resetting dispatch loop state")
        self.loop_state = "stopped"
        self.print_message(
            f" ... {len(self.running_uuids)} running action_dq did not fully stop after E-STOP/error was raised"
        )

    async def add_decision(
        self,
        orch_name: str = None,
        decision_label: str = None,
        actualizer: str = None,
        actualizer_pars: dict = {},
        result_dict: dict = {},
        access: str = "hte",
        prepend: Optional[bool] = False,
        at_index: Optional[int] = None,
    ):

        D = Decision(
            {
                "orch_name": orch_name,
                "decision_label": decision_label,
                "actualizer": actualizer,
                "actualizer_pars": actualizer_pars,
                "result_dict": result_dict,
                "access": access,
            }
        )

        # reminder: decision_dict values take precedence over keyword args but we grab
        # active or last decision label if decision_label is not specified
        if D.orch_name is None:
            D.orch_name = self.server_name
        if decision_label is None:
            if self.active_decision is not None:
                active_label = self.active_decision.decision_label
                self.print_message(
                    f" ... decision_label not specified, inheriting {active_label} from active decision"
                )
                D.decision_label = active_label
            elif self.last_decision is not None:
                last_label = self.last_decision.decision_label
                self.print_message(
                    f" ... decision_label not specified, inheriting {last_label} from previous decision"
                )
                D.decision_label = last_label
            else:
                self.print_message(
                    " ... decision_label not specified, no past decision_dq to inherit so using default 'nolabel"
                )
        await asyncio.sleep(0.001)
        if at_index:
            self.decision_dq.insert(i=at_index, x=D)
        elif prepend:
            self.decision_dq.appendleft(D)
            self.print_message(f" ... decision {D.decision_uuid} prepended to queue")
        else:
            self.decision_dq.append(D)
            self.print_message(f" ... decision {D.decision_uuid} appended to queue")

    def list_decisions(self):
        """Return the current queue of decision_dq."""

        declist = [
            return_dec(
                index=i,
                uid=dec.decision_uuid,
                label=dec.decision_label,
                actualizer=dec.actualizer,
                pars=dec.actualizer_pars,
                access=dec.access,
            )
            for i, dec in enumerate(self.decision_dq)
        ]
        retval = return_declist(decisions=declist)
        return retval

    def get_decision(self, last=False):
        """Return the active or last decision."""
        if last:
            dec = self.last_decision
        else:
            dec = self.active_decision
        if dec is not None:
            declist = [
                return_dec(
                    index=-1,
                    uid=dec.decision_uuid,
                    label=dec.decision_label,
                    actualizer=dec.actualizer,
                    pars=dec.actualizer_pars,
                    access=dec.access,
                )
            ]
        else:
            declist = [
                return_dec(
                    index=-1,
                    uid=None,
                    label=None,
                    actualizer=None,
                    pars=None,
                    access=None,
                )
            ]
        retval = return_declist(decisions=declist)
        return retval

    def list_active_actions(self):
        """Return the current queue running actions."""
        actlist = []
        index = 0
        for act_serv, act_dict in self.global_state_dict.items():
            for act_name, act_uuids in act_dict.items():
                for act_uuid in act_uuids:
                    actlist.append(
                        return_act(
                            index=index,
                            uid=act_uuid,
                            server=act_serv,
                            action=act_name,
                            pars=dict(),
                            preempt=-1,
                        )
                    )
                    index = index + 1
        retval = return_actlist(actions=actlist)
        return retval

    def list_actions(self):
        """Return the current queue of action_dq."""
        actlist = [
            return_act(
                index=i,
                uid=act.action_uuid,
                server=act.action_server,
                action=act.action_name,
                pars=act.action_params,
                preempt=act.start_condition,
            )
            for i, act in enumerate(self.action_dq)
        ]
        retval = return_actlist(actions=actlist)
        return retval

    def supplement_error_action(self, check_uuid: str, sup_action: Action):
        """Insert action at front of action queue with subversion of errored action, inherit parameters if desired."""
        if self.error_uuids == []:
            self.print_message("There are no error statuses to replace")
        else:
            matching_error = [tup for tup in self.error_uuids if tup[2] == check_uuid]
            if matching_error:
                _, _, error_uuid = matching_error[0]
                EA = [
                    A
                    for _, A in self.dispatched_actions.items()
                    if A.action_uuid == error_uuid
                ][0]
                # up to 99 supplements
                new_enum = round(EA.action_enum + 0.01, 2)
                new_action = sup_action
                new_action.action_enum = new_enum
                self.action_dq.appendleft(new_action)
            else:
                self.print_message(
                    f"uuid {check_uuid} not found in list of error statuses:"
                )
                self.print_message(", ".join(self.error_uuids))

    def remove_decision(
        self, by_index: Optional[int] = None, by_uuid: Optional[str] = None
    ):
        """Remove decision in list by enumeration index or uuid."""
        if by_index:
            i = by_index
        elif by_uuid:
            i = [
                i
                for i, D in enumerate(list(self.decision_dq))
                if D.decision_uuid == by_uuid
            ][0]
        else:
            self.print_message(
                "No arguments given for locating existing decision to remove."
            )
            return None
        del self.decision_dq[i]

    def replace_action(
        self,
        sup_action: Action,
        by_index: Optional[int] = None,
        by_uuid: Optional[str] = None,
        by_enum: Optional[Union[int, float]] = None,
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
        elif by_enum:
            i = [
                i
                for i, A in enumerate(list(self.action_dq))
                if A.action_enum == by_enum
            ][0]
        else:
            self.print_message(
                "No arguments given for locating existing action to replace."
            )
            return None
        current_enum = self.action_dq[i].action_enum
        new_action = sup_action
        new_action.action_enum = current_enum
        self.action_dq.insert(i, new_action)
        del self.action_dq[i + 1]

    def append_action(self, sup_action: Action):
        """Add action to end of current action queue."""
        if len(self.action_dq) == 0:
            last_enum = floor(max(list(self.dispatched_actions.keys())))
        else:
            last_enum = floor(self.action_dq[-1].action_enum)
        new_enum = int(last_enum + 1)
        new_action = sup_action
        new_action.action_enum = new_enum
        self.action_dq.append(new_action)

    async def shutdown(self):
        await self.detach_subscribers()
        self.status_logger.cancel()
        self.ntp_syncer.cancel()
        self.status_subscriber.cancel()


class Vis(object):
    """Base class for all HELAO bokeh servers."""

    def __init__(self, bokehapp: HelaoBokehAPI):
        self.server_name = bokehapp.helao_srv
        self.server_cfg = bokehapp.world_cfg["servers"][self.server_name]
        self.world_cfg = bokehapp.world_cfg
        self.hostname = gethostname()
        self.doc = bokehapp.doc
        # self.save_root = None
        # self.technique_name = None
        # self.aloop = asyncio.get_running_loop()

    def print_message(self, *args, **kwargs):
        print_message(self.server_cfg, self.server_name, *args, **kwargs)


def import_actualizers(
    world_config_dict: dict, library_path: str = None, server_name: str = ""
):
    """Import actualizer functions into environment."""
    action_lib = {}
    if library_path is None:
        library_path = world_config_dict.get(
            "action_library_path", os.path.join("helao", "library", "actualizer")
        )
    if not os.path.isdir(library_path):
        print_message(
            world_config_dict,
            server_name,
            f" ... library path {library_path} was specified but is not a valid directory",
        )
        return action_lib  # False
    sys.path.append(library_path)
    for actlib in world_config_dict["action_libraries"]:
        tempd = import_module(actlib).__dict__
        action_lib.update({func: tempd[func] for func in tempd["ACTUALIZERS"]})
    print_message(
        world_config_dict,
        server_name,
        f" ... imported {len(world_config_dict['action_libraries'])} actualizers specified by config.",
    )
    return action_lib  # True


async def async_action_dispatcher(world_config_dict: dict, A: Action):
    """Request non-blocking action_dq which may run concurrently.

    Send action object to action server for processing.

    Args:
        A: an action type object contain action server name, endpoint, parameters

    Returns:
        Response string from http POST request to action server
    """
    actd = world_config_dict["servers"][A.action_server]
    act_addr = actd["host"]
    act_port = actd["port"]
    url = f"http://{act_addr}:{act_port}/{A.action_server}/{A.action_name}"
    # splits action dict into suitable params and json parts
    # params_dict, json_dict = A.fastdict()
    params_dict = {}
    json_dict = A.as_dict()

    # print("... params_dict", params_dict)
    # print("... json_dict", json_dict)
    # print(url)

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            params=params_dict,
            # data = data_dict,
            json=json_dict,
        ) as resp:
            response = await resp.json()
            return response


async def async_private_dispatcher(
    world_config_dict: dict,
    server: str,
    private_action: str,
    params_dict: dict,
    json_dict: dict,
):
    """Request non-blocking private action which may run concurrently.

    Returns:
        Response string from http POST request to action server
    """

    actd = world_config_dict["servers"][server]
    act_addr = actd["host"]
    act_port = actd["port"]

    url = f"http://{act_addr}:{act_port}/{private_action}"

    # print(" ... params_dict", params_dict)
    # print(" ... json_dict", json_dict)

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            params=params_dict,
            # data = data_dict,
            json=json_dict,
        ) as resp:
            response = await resp.json()
            return response
