""" servers.py
Standard HelaoFastAPI process server and orchestrator classes.

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
from pathlib import Path

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
from helao.core.helper import print_message, cleanupdict
from helao.core.schema import cProcess, cProcess_group
from helao.core.model import return_process_group, return_process_group_list, return_process, return_process_list
from helao.core.model import liquid_sample, gas_sample, solid_sample, assembly_sample, sample_list
from helao.core.model import rcp_header


async_copy = wrap(shutil.copy)

# ANSI color codes converted to the Windows versions
colorama.init(strip=not sys.stdout.isatty())  # strip colors if stdout is redirected
# colorama.init()

# version number, gets written into every rcp and hlo file
hlo_version = "2021.09.20"

class process_start_condition(int, Enum):
    no_wait = 0  # orch is dispatching an unconditional process
    wait_for_endpoint = 1  # orch is waiting for endpoint to become available
    wait_for_server = 2  # orch is waiting for server to become available
    wait_for_all = 3  #  (or other): orch is waiting for all process_dq to finish


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


async def setup_process(request: Request):
    servKey, _, process_name = request.url.path.strip("/").partition("/")
    body_bytes = await request.body()
    if body_bytes == b"":
        body_params = {}
    else:
        body_params = await request.json()

    process_dict = dict()
    # process_dict.update(request.query_params)
    if len(request.query_params) == 0:  # cannot check against {}
        # empty: orch
        process_dict.update(body_params)
    else:
        # not empty: swagger
        if "process_params" not in process_dict:
            process_dict.update({"process_params": {}})
        process_dict["process_params"].update(body_params)
        # process_dict["process_params"].update(request.query_params)
        for k, v in request.query_params.items():
            try:
                val = json.loads(v)
            except ValueError:
                val = v
            process_dict["process_params"][k] = val

    process_dict["process_server"] = servKey
    process_dict["process_name"] = process_name
    A = cProcess(process_dict)
    
    if "fast_samples_in" in A.process_params:
        tmp_fast_samples_in = A.process_params.get("fast_samples_in",[])
        del A.process_params["fast_samples_in"]
        if type(tmp_fast_samples_in) is dict:
            A.samples_in = sample_list(**tmp_fast_samples_in)
        elif type(tmp_fast_samples_in) is list:
            A.samples_in = sample_list(samples=tmp_fast_samples_in)
    
    # setting some default values of process was notsubmitted via orch
    if A.machine_name is None:
        A.machine_name = gethostname()
    if A.technique_name is None:
        A.technique_name = "MANUAL"
        A.orch_name = "MANUAL"
        A.process_group_label = "MANUAL"

    return A


def make_process_serv(
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
        """Run startup processes.

        When FastAPI server starts, create a global OrchHandler object, initiate the
        monitor_states coroutine which runs forever, and append dummy process_groups to the
        process_group queue for testing.
        """
        app.orch = Orch(app)
        if driver_class:
            app.driver = driver_class(app.orch)

    @app.post("/update_status")
    async def update_status(server: str, status: str):
        return await app.orch.update_status(
            process_serv=server, status_dict=json.loads(status)
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
        """Subscribe to process server status dicts.

        Args:
        websocket: a fastapi.WebSocket object
        """
        await app.orch.ws_data(websocket)

    @app.post("/start")
    async def start_process():
        """Begin processing process_group and process queues."""
        if app.orch.loop_state == "stopped":
            if (
                app.orch.process_dq or app.orch.process_group_dq
            ):  # resume processes from a paused run
                await app.orch.start_loop()
            else:
                app.orch.print_message("process_group list is empty")
        else:
            app.orch.print_message("already running")
        return {}

    @app.post("/estop")
    async def estop_process():
        """Emergency stop process_group and process queues, interrupt running processes."""
        if app.orch.loop_state == "started":
            await app.orch.estop_loop()
        elif app.orch.loop_state == "E-STOP":
            app.orch.print_message("orchestrator E-STOP flag already raised")
        else:
            app.orch.print_message("orchestrator is not running")
        return {}

    @app.post("/stop")
    async def stop_process():
        """Stop processing process_group and process queues after current processes finish."""
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
    async def skip_process_group():
        """Clear the present process queue while running."""
        if app.orch.loop_state == "started":
            await app.orch.intend_skip()
        else:
            app.orch.print_message("orchestrator not running, clearing process queue")
            await asyncio.sleep(0.001)
            app.orch.process_dq.clear()
        return {}

    @app.post("/clear_processes")
    async def clear_processes():
        """Clear the present process queue while stopped."""
        app.orch.print_message("clearing process queue")
        await asyncio.sleep(0.001)
        app.orch.process_dq.clear()
        return {}

    @app.post("/clear_process_groups")
    async def clear_process_groups():
        """Clear the present process_group queue while stopped."""
        app.orch.print_message("clearing process_group queue")
        await asyncio.sleep(0.001)
        app.orch.process_group_dq.clear()
        return {}

    @app.post("/append_process_group")
    async def append_process_group(
        orch_name: str = None,
        process_group_label: str = None,
        actualizer: str = None,
        actualizer_pars: dict = {},
        result_dict: dict = {},
        access: str = "hte",
    ):
        """Add a process_group object to the end of the process_group queue.

        Args:
        process_group_dict: process_group parameters (optional), as dict.
        orch_name: Orchestrator server key (optional), as str.
        plate_id: The sample's plate id (no checksum), as int.
        sample_no: A sample number, as int.
        actualizer: The name of the actualizer for building the process list, as str.
        actualizer_pars: Actualizer parameters, as dict.
        result_dict: process responses dict keyed by process_enum.
        access: Access control group, as str.

        Returns:
        Nothing.
        """
        await app.orch.add_process_group(
            orch_name,
            process_group_label,
            actualizer,
            actualizer_pars,
            result_dict,
            access,
            prepend=False,
        )
        return {}

    @app.post("/prepend_process_group")
    async def prepend_process_group(
        orch_name: str = None,
        process_group_label: str = None,
        actualizer: str = None,
        actualizer_pars: dict = {},
        result_dict: dict = {},
        access: str = "hte",
    ):
        """Add a process_group object to the start of the process_group queue.

        Args:
        process_group_dict: process_group parameters (optional), as dict.
        orch_name: Orchestrator server key (optional), as str.
        plate_id: The sample's plate id (no checksum), as int.
        sample_no: A sample number, as int.
        actualizer: The name of the actualizer for building the process list, as str.
        actualizer_pars: Actualizer parameters, as dict.
        result_dict: process responses dict keyed by process_enum.
        access: Access control group, as str.

        Returns:
        Nothing.
        """
        await app.orch.add_process_group(
            orch_name,
            process_group_label,
            actualizer,
            actualizer_pars,
            result_dict,
            access,
            prepend=True,
        )
        return {}

    @app.post("/insert_process_group")
    async def insert_process_group(
        idx: int,
        process_group_dict: dict = None,
        orch_name: str = None,
        process_group_label: str = None,
        actualizer: str = None,
        actualizer_pars: dict = {},
        result_dict: dict = {},
        access: str = "hte",
    ):
        """Insert a process_group object at process_group queue index.

        Args:
        idx: index in process_group queue for insertion, as int
        process_group_dict: process_group parameters (optional), as dict.
        orch_name: Orchestrator server key (optional), as str.
        plate_id: The sample's plate id (no checksum), as int.
        sample_no: A sample number, as int.
        actualizer: The name of the actualizer for building the process list, as str.
        actualizer_pars: Actualizer parameters, as dict.
        result_dict: process responses dict keyed by process_enum.
        access: Access control group, as str.

        Returns:
        Nothing.
        """
        await app.orch.add_process_group(
            process_group_dict,
            orch_name,
            process_group_label,
            actualizer,
            actualizer_pars,
            result_dict,
            access,
            at_index=idx,
        )
        return {}

    @app.post("/list_process_groups")
    def list_process_groups():
        """Return the current list of process_groups."""
        return app.orch.list_process_groups()

    @app.post("/active_process_group")
    def active_process_group():
        """Return the active process_group."""
        return app.orch.get_process_group(last=False)

    @app.post("/last_process_group")
    def last_process_group():
        """Return the last process_group."""
        return app.orch.get_process_group(last=True)

    @app.post("/list_processes")
    def list_processes():
        """Return the current list of processes."""
        return app.orch.list_processes()

    @app.post("/list_active_processes")
    def list_active_processes():
        """Return the current list of processes."""
        return app.orch.list_active_processes()

    @app.post("/endpoints")
    def get_all_urls():
        """Return a list of all endpoints on this server."""
        return app.orch.get_endpoint_urls(app)

    @app.on_event("shutdown")
    def disconnect():
        """Run shutdown processes."""
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
    writing, and data streaming via async tasks. Every instrument and process server
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
    {%y.%j}/  # process_group_date year.weeknum
        {%Y%m%d}/  # process_group_date
            {%H%M%S}__{process_group_label}/  # process_group_time
                {%Y%m%d.%H%M%S}__{process_server_name}__{process_name}__{process_uuid}/
                    {filename}.{ext}
                    {%Y%m%d.%H%M%S%f}.rcp  # process_datetime
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

    async def contain_process(
        self,
        process: cProcess,
        file_type: str = "helao__file",
        file_data_keys: Optional[str] = None, # this is also keyd by file_sample_keys
        file_sample_label: Optional[str] = None, # this is also keyd by file_sample_keys
        file_sample_keys: Optional[list] = None, # I need one key per datafile, but each datafile can still be based on multiple samples
        header: Optional[str] = None, # this is also keyd by file_sample_keys
    ):
        self.actives[process.process_uuid] = Base.Active(
            self,
            process=process,
            file_type=file_type,
            file_data_keys=file_data_keys,
            file_sample_label=file_sample_label,
            file_sample_keys=file_sample_keys,
            header=header,
        )
        await self.actives[process.process_uuid].myinit()
        return self.actives[process.process_uuid]


    async def get_active_info(self, process_uuid: str):
        if process_uuid in self.actives.keys():
            process_dict = await self.actives[process_uuid].active.as_dict()
            return process_dict
        else:
            self.print_message(
                f" ... Specified process uuid {process_uuid} was not found.", error=True
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
                        private_process="update_status",
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
                            private_process="update_status",
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


    async def set_realtime(
        self, epoch_ns: Optional[float] = None, offset: Optional[float] = None
    ):
        return self.set_realtime_nowait(epoch_ns=epoch_ns, offset=offset)


    def set_realtime_nowait(
        self, epoch_ns: Optional[float] = None, offset: Optional[float] = None
    ):
        if offset is None:
            if self.ntp_offset is not None:
                offset_ns = int(np.floor(self.ntp_offset * 1e9))
            else:
                offset_ns = 0.0
        else:
            offset_ns = int(np.floor(offset * 1e9))
        if epoch_ns is None:
            real_time = time_ns() + offset_ns
        else:
            real_time = epoch_ns + offset_ns
        return real_time


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
        """Active process holder which wraps data queing and rcp writing."""

        def __init__(
            self,
            base,  # outer instance
            process: cProcess,
            file_type: str = "helao__file",
            file_data_keys: Optional[str] = None,
            file_sample_label: Optional[str] = None,
            file_sample_keys: Optional[list] = None,
            header: Optional[str] = None,
        ):
            self.base = base
            self.process = process
            self.process.file_type = file_type
            self.process.file_group = "helao_files"
            self.process.file_data_keys = file_data_keys
            self.process.file_sample_label = file_sample_label
            self.process.header = header
            self.rcp_header = None
            
            
            if file_sample_keys is None:
                self.process.file_sample_keys = ["None"]
                self.process.file_sample_label = {"None":self.process.file_sample_label}
                self.process.file_data_keys = {"None":self.process.file_data_keys}
                self.process.header = {"None":self.process.header}
            else:
                self.process.file_sample_keys = file_sample_keys
                if type(self.process.file_sample_keys) is not list:
                    self.process.file_sample_keys = [self.process.file_sample_keys]
                if self.process.file_sample_label is None:
                    self.process.file_sample_label = {f"{file_sample_key}":None for file_sample_key in self.process.file_sample_keys}
                if self.process.file_data_keys is None:
                    self.process.file_data_keys = {f"{file_sample_key}":None for file_sample_key in self.process.file_sample_keys}
                if self.process.header is None:
                    self.process.header = {f"{file_sample_key}":None for file_sample_key in self.process.file_sample_keys}
                    


            self.process.set_atime(offset=self.base.ntp_offset)
            self.process.gen_uuid_process(self.base.hostname)
            # signals the data logger that it got data and hlo header was written or not
            # active.finish_hlo_header should be called within the driver before
            # any data is pushed to avoid a forced header end write
            self.finished_hlo_header = dict()
            self.file_conn = dict()
            # if cProcess is not created from process_group+Actualizer, cProcess is independent
            if self.process.process_group_timestamp is None:
                self.process.set_dtime(offset=self.base.ntp_offset)
                self.process.gen_uuid_process_group(self.base.hostname)
            process_group_date = self.process.process_group_timestamp.split(".")[0]
            process_group_time = self.process.process_group_timestamp.split(".")[-1]
            year_week = strftime("%y.%U", strptime(process_group_date, "%Y%m%d"))
            if not self.base.save_root:
                self.base.print_message(
                    " ... Root save directory not specified, cannot save process results."
                )
                self.process.save_data = False
                self.process.save_rcp = False
                self.process.output_dir = None
            else:
                if self.process.save_data is None:
                    self.process.save_data = False
                if self.process.save_rcp is None:
                    self.process.save_rcp = False
                # cannot save data without rcp
                if self.process.save_data is True:
                    self.process.save_rcp = True
                # self.process.save_data = True
                # self.process.save_rcp = True
                self.process.output_dir = os.path.join(
                    year_week,
                    process_group_date,
                    f"{process_group_time}_{self.process.process_group_label}",
                    f"{self.process.process_queue_time}__{self.process.process_server}__{self.process.process_name}__{self.process.process_uuid}",
                )
            self.data_logger = self.base.aloop.create_task(self.log_data_task())


        def update_rcp_header(self):
            # need to remove swagger workaround value if present
            if "scratch" in self.process.process_params:
                    del self.process.process_params["scratch"]

            if self.process.process_enum is None:
                self.process.process_enum = 0.0
 
            self.rcp_header = rcp_header(
                hlo_version=f"{hlo_version}",
                technique_name=self.process.technique_name,
                server_name=self.base.server_name,
                orchestrator=self.process.orch_name,
                machine_name=self.process.machine_name,
                access=self.process.access,
                output_dir=Path(self.process.output_dir).as_posix(),
                process_group_uuid=self.process.process_group_uuid,
                process_group_timestamp=self.process.process_group_timestamp,
                process_uuid=self.process.process_uuid,
                process_queue_time=self.process.process_queue_time,
                process_enum=self.process.process_enum,
                process_name=self.process.process_name,
                process_abbr=self.process.process_abbr,
                process_params=self.process.process_params,
            )


        async def myinit(self):
            if self.process.save_rcp:
                os.makedirs(os.path.join(self.base.save_root,self.process.output_dir), exist_ok=True)
                self.process.process_num = (
                    f"{self.process.process_abbr}-{self.process.process_enum}"
                )
                self.update_rcp_header()
                
                if self.process.save_data:
                    for i, file_sample_key in enumerate(self.process.file_sample_keys):
                        filename, header, file_info = self.init_datafile(
                            header = self.process.header.get(file_sample_key,None),
                            file_type = self.process.file_type,
                            file_data_keys = self.process.file_data_keys.get(file_sample_key,None),
                            file_sample_label = self.process.file_sample_label.get(file_sample_key,None),
                            filename = None, # always autogen a filename
                            file_group = self.process.file_group,
                            process_enum = self.process.process_enum,
                            process_abbr = self.process.process_abbr,
                            filenum=i
                        )
                        
                        self.process.file_dict.update({filename: file_info})
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
                process_enum,
                process_abbr,
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
                if len(file_sample_label)!=0:
                    file_info.update({"sample": file_sample_label})

            if filename is None:  # generate filename
                file_ext = "csv"
                if file_group == "helao_files":
                    file_ext = "hlo"
                    
                    header_dict = {
                        "hlo_version":hlo_version,
                        "process_name":self.process.process_abbr,
                        "column_headings":file_data_keys,
                        }
                    
                    if header is None:
                        header = pyaml.dump(header_dict, sort_dicts=False)
                    else:
                        header = pyaml.dump(header_dict, sort_dicts=False)+header
                else: # aux_files
                    pass
    
                if process_enum is not None:
                    filename = f"{process_abbr}-{process_enum:.1f}__{filenum}.{file_ext}"
                else:
                    filename = (
                        f"{process_abbr}-0.0__{filenum}.{file_ext}"
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
            self.base.status[self.process.process_name].append(self.process.process_uuid)
            self.base.print_message(
                f" ... Added {self.process.process_uuid} to {self.process.process_name} status list."
            )
            await self.base.status_q.put(
                {self.process.process_name: self.base.status[self.process.process_name]}
            )

        async def clear_status(self):
            if self.process.process_uuid in self.base.status[self.process.process_name]:
                self.base.status[self.process.process_name].remove(
                    self.process.process_uuid
                )
                self.base.print_message(
                    f" ... Removed {self.process.process_uuid} from {self.process.process_name} status list.",
                    info = True
                )
            else:
                self.base.print_message(
                    f" ... {self.process.process_uuid} did not excist in {self.process.process_name} status list.",
                    error = True
                )
            await self.base.status_q.put(
                {self.process.process_name: self.base.status[self.process.process_name]}
            )

        async def set_estop(self):
            self.base.status[self.process.process_name].remove(self.process.process_uuid)
            self.base.status[self.process.process_name].append(
                f"{self.process.process_uuid}__estop"
            )
            self.base.print_message(
                f" ... E-STOP {self.process.process_uuid} on {self.process.process_name} status.",
                error = True
            )
            await self.base.status_q.put(
                {self.process.process_name: self.base.status[self.process.process_name]}
            )

        async def set_error(self, err_msg: Optional[str] = None):
            self.base.status[self.process.process_name].remove(self.process.process_uuid)
            self.base.status[self.process.process_name].append(
                f"{self.process.process_uuid}__error"
            )
            self.base.print_message(
                f" ... ERROR {self.process.process_uuid} on {self.process.process_name} status.",
                error = True
            )
            if err_msg:
                self.process.error_code = err_msg
            else:
                self.process.error_code = "-1 unspecified error"
            await self.base.status_q.put(
                {self.process.process_name: self.base.status[self.process.process_name]}
            )


        async def set_realtime(
            self, epoch_ns: Optional[float] = None, offset: Optional[float] = None
        ):
            # return self.set_realtime_nowait(epoch_ns=epoch_ns, offset=offset)
            return self.base.set_realtime_nowait(epoch_ns=epoch_ns, offset=offset)


        def set_realtime_nowait(
            self, epoch_ns: Optional[float] = None, offset: Optional[float] = None
        ):
            return self.base.set_realtime_nowait(epoch_ns=epoch_ns, offset=offset)
            # if offset is None:
            #     if self.base.ntp_offset is not None:
            #         offset_ns = int(np.floor(self.base.ntp_offset * 1e9))
            #     else:
            #         offset_ns = 0.0
            # else:
            #     offset_ns = int(np.floor(offset * 1e9))
            # if epoch_ns is None:
            #     process_real_time = time_ns() + offset_ns
            # else:
            #     process_real_time = epoch_ns + offset_ns
            # return process_real_time


        async def set_output_file(self, filename: str, file_sample_key: str, header: Optional[str] = None):
            "Set active save_path, write header if supplied."
            output_path = os.path.join(self.base.save_root,self.process.output_dir, filename)
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
                self.process.process_uuid: {
                    "data": data_dict,
                    "process_name": self.process.process_name,
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
                        self.process.process_uuid in data_msg.keys()
                    ):  # only write data for this process
                        data_dict = data_msg[self.process.process_uuid]
                        data_val = data_dict["data"]
                        self.process.data.append(data_val)
                        for sample, sample_data in data_val.items():
                            if sample in self.file_conn:
                                if self.file_conn[sample]:
                                    # check if end of hlo header was writen
                                    # else force it here
                                    # e.g. just write the separator
                                    if not self.finished_hlo_header[sample]:
                                        self.base.print_message(
                                            f" ... {self.process.process_abbr} data file {sample} is missing hlo separator. Writing it.",
                                            error = True
                                        )
                                        self.finished_hlo_header[sample] = True
                                        await self.write_live_data(
                                             output_str=pyaml.dump({"epoch_ns":None})+"%%\n",
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
            if self.process.save_data:
                filename, header, file_info = self.init_datafile(
                    header = header,
                    file_type = file_type,
                    file_data_keys = file_data_keys, 
                    file_sample_label = file_sample_label,
                    filename = filename,
                    file_group = file_group,
                    process_enum = self.process.process_enum,
                    process_abbr = self.process.process_abbr,
                )
                output_path = os.path.join(self.base.save_root,self.process.output_dir, filename)
                self.base.print_message(f" ... writing non stream data to: {output_path}")

                file_instance = await aiofiles.open(output_path, mode="w")
                await file_instance.write(header + output_str)
                await file_instance.close()
                self.process.file_dict.update(
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
            if self.process.save_data:
                filename, header, file_info = self.init_datafile(
                    header = header,
                    file_type = file_type,
                    file_data_keys = file_data_keys, 
                    file_sample_label = file_sample_label,
                    filename = filename,
                    file_group = file_group,
                    process_enum = self.process.process_enum,
                    process_abbr = self.process.process_abbr,
                )
                output_path = os.path.join(self.base.save_root,self.process.output_dir, filename)
                self.base.print_message(f" ... writing non stream data to: {output_path}")

                file_instance = open(output_path, mode="w")
                file_instance.write(header + output_str)
                file_instance.close()
                self.process.file_dict.update(
                    {filename: file_info}
                )


        async def write_to_rcp(self, rcp_dict: dict):
            "Create new rcp if it doesn't exist, otherwise append rcp_dict to file."
            output_path = os.path.join(
                self.base.save_root,
                self.process.output_dir,
                f"{self.process.process_queue_time}.rcp"
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
            samples,
            IO: str,
            status: bool = None,
            inheritance: bool = None
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

            if samples is None:
                return

            if type(samples) is not list:
                   samples = [samples]
                    
            for sample in samples:
                if inheritance is None:
                    inheritance = "allow_both"
                if status is None:
                    status = "preserved"
    
                append_dict = sample.rcp_dict()
                if append_dict is not None:
                    if inheritance is not None:
                        append_dict.update({"inheritance": inheritance})
                    if status is not None:
                        if type(status) is not list:
                            status = [status]
                        append_dict.update({"status": status})            
        
                    # check if list for safety reasons
                    if type(self.process.rcp_samples_in) is not list:
                        self.process.rcp_samples_in = []
                    if type(self.process.rcp_samples_out) is not list:
                        self.process.rcp_samples_out = []

                    if IO == "in":
                        self.process.rcp_samples_in.append(append_dict)
                    elif IO == "out":
                        self.process.rcp_samples_out.append(append_dict)


        async def finish(self):
            "Close file_conn, finish rcp, copy aux, set endpoint status, and move active dict to past."
            await asyncio.sleep(1)
            self.base.print_message(" ... finishing data logging.")
            for filekey in self.file_conn.keys():
                if self.file_conn[filekey]:
                    await self.file_conn[filekey].close()
            self.file_conn = dict()
            # (1) update sample_in and sample_out
            if  self.process.rcp_samples_in:
                self.rcp_header.samples_in = self.process.rcp_samples_in
            if self.process.rcp_samples_out:
                 self.rcp_header.samples_out = self.process.rcp_samples_out
            # (2) update file dict in rcp header
            if self.process.file_dict:
                self.rcp_header.files = self.process.file_dict

            # write full rcp header to file
            await self.write_to_rcp(cleanupdict(self.rcp_header.dict()))

            await self.clear_status()
            self.data_logger.cancel()
            _ = self.base.actives.pop(self.process.process_uuid, None)
            return self.process


        async def track_file(self, file_type: str, file_path: str, sample_no: str):
            "Add auxiliary files to file dictionary."
            if os.path.dirname(file_path) != os.path.join(self.base.save_root,self.process.output_dir):
                self.process.file_paths.append(file_path)
            file_info = f"{file_type};{sample_no}"
            filename = os.path.basename(file_path)
            self.process.file_dict.update(
                {filename: file_info}
            )
            self.base.print_message(
                f" ... {filename} added to files_technique__{self.process.process_num} / aux_files list."
            )


        async def relocate_files(self):
            "Copy auxiliary files from folder path to rcp directory."
            for x in self.process.file_paths:
                new_path = os.path.join(
                    self.base.save_root,
                    self.process.output_dir,
                    os.path.basename(x)
                )
                await async_copy(x, new_path)


class Orch(Base):
    """Base class for async orchestrator with trigger support and pushed status update.

    Websockets are not used for critical communications. Orch will attach to all process
    servers listed in a config and maintain a dict of {serverName: status}, which is
    updated by POST requests from process servers. Orch will simultaneously dispatch as
    many process_dq as possible in process queue until it encounters any of the following
    conditions:
      (1) last executed process is final process in queue
      (2) last executed process is blocking
      (3) next process to execute is preempted
      (4) next process is on a busy process server
    which triggers a temporary async task to monitor the process server status dict until
    all conditions are cleared.

    POST requests from process servers are added to a multisubscriber queue and consumed
    by a self-subscriber task to update the process server status dict and log changes.
    """

    def __init__(self, fastapp: HelaoFastAPI):
        super().__init__(fastapp)
        # self.import_actualizers()
        self.process_lib = import_actualizers(
            world_config_dict=self.world_cfg,
            library_path=None,
            server_name=self.server_name,
        )
        # instantiate process_group/experiment queue, process queue
        self.process_group_dq = deque([])
        self.process_dq = deque([])
        self.dispatched_processes = {}
        self.active_process_group = None
        self.last_process_group = None

        # compilation of process server status dicts
        self.global_state_dict = defaultdict(lambda: defaultdict(list))
        self.global_state_dict["_internal"]["async_process_dispatcher"] = []
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

    async def check_wait_for_all_processes(self):
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
                        private_process="attach_client",
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
                " ... Orchestrator cannot process process_group_dq unless all FastAPI servers in config file are accessible."
            )

    async def update_status(self, process_serv: str, status_dict: dict):
        """Dict update method for process server to push status messages.

        Async task for updating orch status dict {process_serv_key: {act_name: [act_uuid]}}
        """
        last_dict = self.global_state_dict[process_serv]
        for act_name, acts in status_dict.items():
            if set(acts) != set(last_dict[act_name]):
                started = set(acts).difference(last_dict[act_name])
                removed = set(last_dict[act_name]).difference(acts)
                ongoing = set(acts).intersection(last_dict[act_name])
                if removed:
                    self.print_message(
                        f" ... '{process_serv}:{act_name}' finished {','.join(removed)}"
                    )
                if started:
                    self.print_message(
                        f" ... '{process_serv}:{act_name}' started {','.join(started)}"
                    )
                if ongoing:
                    self.print_message(
                        f" ... '{process_serv}:{act_name}' ongoing {','.join(ongoing)}"
                    )
        self.global_state_dict[process_serv].update(status_dict)
        await self.global_q.put(self.global_state_dict)
        return True

    async def update_global_state(self, status_dict: dict):
        _running_uuids = []
        for process_serv, act_named in status_dict.items():
            for act_name, uuids in act_named.items():
                for myuuid in uuids:
                    uuid_tup = (process_serv, act_name, myuuid)
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
        """Return global state of process servers."""
        running_states = []
        idle_states = []
        # self.print_message(" ... checking global state:")
        # self.print_message(self.global_state_dict.items())
        for process_serv, act_dict in self.global_state_dict.items():
            self.print_message(f" ... checking {process_serv} state")
            for act_name, act_uuids in act_dict.items():
                if len(act_uuids) == 0:
                    idle_states.append(f"{process_serv}:{act_name}")
                else:
                    running_states.append(f"{process_serv}:{act_name}:{len(act_uuids)}")
            await asyncio.sleep(
                0.001
            )  # allows status changes to affect between process_dq, also enforce unique timestamp
        return running_states, idle_states

    async def dispatch_loop_task(self):
        """Parse process_group and process queues, and dispatch process_dq while tracking run state flags."""
        self.print_message(" ... running operator orch")
        self.print_message(f" ... orch status: {self.global_state_str}")
        # clause for resuming paused process list
        self.print_message(f" ... orch descisions: {self.process_group_dq}")
        try:
            self.loop_state = "started"
            while self.loop_state == "started" and (self.process_dq or self.process_group_dq):
                self.print_message(
                    f" ... current content of process_dq: {self.process_dq}"
                )
                self.print_message(
                    f" ... current content of process_group_dq: {self.process_group_dq}"
                )
                await asyncio.sleep(
                    0.001
                )  # allows status changes to affect between process_dq, also enforce unique timestamp
                if not self.process_dq:
                    self.print_message(" ... getting process_dq from new process_group")
                    # generate uids when populating, generate timestamp when acquring
                    self.last_process_group = copy(self.active_process_group)
                    self.active_process_group = self.process_group_dq.popleft()
                    self.active_process_group.technique_name = self.technique_name
                    self.active_process_group.machine_name = self.hostname
                    self.active_process_group.set_dtime(offset=self.ntp_offset)
                    self.active_process_group.gen_uuid_process_group(self.hostname)
                    actualizer = self.active_process_group.actualizer
                    # additional actualizer params should be stored in process_group.actualizer_pars
                    unpacked_acts = self.process_lib[actualizer](self.active_process_group)
                    for i, act in enumerate(unpacked_acts):
                        act.process_enum = float(i)  # f"{i}"
                        # act.gen_uuid()
                    # TODO:update actualizer code
                    self.process_dq = deque(unpacked_acts)
                    self.dispatched_processes = {}
                    self.print_message(f" ... got: {self.process_dq}")
                    self.print_message(
                        f" ... optional params: {self.active_process_group.actualizer_pars}"
                    )
                else:
                    if self.loop_intent == "stop":
                        self.print_message(" ... stopping orchestrator")
                        # monitor status of running process_dq, then end loop
                        # async for _ in self.global_q.subscribe():
                        while True:
                            _ = await self.check_dispatch_queue()
                            if self.global_state_str == "idle":
                                self.loop_state = "stopped"
                                await self.intend_none()
                                break
                    elif self.loop_intent == "skip":
                        # clear process queue, forcing next process_group
                        self.process_dq.clear()
                        await self.intend_none()
                        self.print_message(" ... skipping to next process_group")
                    else:
                        # all process blocking is handled like preempt, check cProcess requirements
                        A = self.process_dq.popleft()
                        # append previous results to current process
                        A.result_dict = self.active_process_group.result_dict

                        # see async_process_dispatcher for unpacking
                        if isinstance(A.start_condition, int):
                            if A.start_condition == process_start_condition.no_wait:
                                self.print_message(
                                    " ... orch is dispatching an unconditional process"
                                )
                            else:
                                if (
                                    A.start_condition
                                    == process_start_condition.wait_for_endpoint
                                ):
                                    self.print_message(
                                        " ... orch is waiting for endpoint to become available"
                                    )
                                    # async for _ in self.global_q.subscribe():
                                    while True:
                                        _ = await self.check_dispatch_queue()
                                        endpoint_free = (
                                            len(
                                                self.global_state_dict[A.process_server][
                                                    A.process_name
                                                ]
                                            )
                                            == 0
                                        )
                                        if endpoint_free:
                                            break
                                elif (
                                    A.start_condition
                                    == process_start_condition.wait_for_server
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
                                                    A.process_server
                                                ].items()
                                            ]
                                        )
                                        if server_free:
                                            break
                                else:  # start_condition is 3 or unsupported value
                                    self.print_message(
                                        " ... orch is waiting for all process_dq to finish"
                                    )
                                    if not await self.check_wait_for_all_processes():
                                        while True:
                                            _ = await self.check_dispatch_queue()
                                            if await self.check_wait_for_all_processes():
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
                                " ... invalid start condition, waiting for all process_dq to finish"
                            )
                            # async for _ in self.global_q.subscribe():
                            while True:
                                _ = await self.check_dispatch_queue()
                                if await self.check_wait_for_all_processes():
                                    break

                        self.print_message(" ... copying global vars to process")

                        # copy requested global param to process params
                        for k, v in A.from_global_params.items():
                            self.print_message(f"{k}:{v}")
                            if k in self.active_process_group.global_params.keys():
                                A.process_params.update(
                                    {v: self.active_process_group.global_params[k]}
                                )

                        self.print_message(" ... dispatching process", A.as_dict())
                        self.print_message(
                            f" ... dispatching process {A.process_name} on server {A.process_server}"
                        )
                        # keep running list of dispatched processes
                        self.dispatched_processes[A.process_enum] = copy(A)
                        result = await async_process_dispatcher(self.world_cfg, A)
                        self.active_process_group.result_dict[A.process_enum] = result

                        self.print_message(" ... copying global vars back to process_group")
                        # self.print_message(result)
                        if "to_global_params" in result:
                            for k in result["to_global_params"]:
                                if k in result["process_params"].keys():
                                    if (
                                        result["process_params"][k] is None
                                        and k
                                        in self.active_process_group.global_params.keys()
                                    ):
                                        self.active_process_group.global_params.pop(k)
                                    else:
                                        self.active_process_group.global_params.update(
                                            {k: result["process_params"][k]}
                                        )
                        self.print_message(
                            " ... done copying global vars back to process_group"
                        )

            self.print_message(" ... process_group queue is empty")
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
        await self.force_stop_running_process_q()
        await self.intend_none()

    async def force_stop_running_process_q(self):
        running_uuids = []
        estop_uuids = []
        for process_serv, act_named in self.global_state_dict.items():
            for act_name, uuids in act_named.items():
                for myuuid in uuids:
                    uuid_tup = (process_serv, act_name, myuuid)
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
            for serv, process, myuuid in self.estop_uuids:
                self.print_message(f" ... clearing E-STOP {process} on {serv}")
                cleared_status[serv][process] = cleared_status[serv][process].remove(myuuid)
        if clear_error:
            for serv, process, myuuid in self.error_uuids:
                self.print_message(f" ... clearing error {process} on {serv}")
                cleared_status[serv][process] = cleared_status[serv][process].remove(myuuid)
        await self.global_q.put(cleared_status)
        self.print_message(" ... resetting dispatch loop state")
        self.loop_state = "stopped"
        self.print_message(
            f" ... {len(self.running_uuids)} running process_dq did not fully stop after E-STOP/error was raised"
        )

    async def add_process_group(
        self,
        orch_name: str = None,
        process_group_label: str = None,
        actualizer: str = None,
        actualizer_pars: dict = {},
        result_dict: dict = {},
        access: str = "hte",
        prepend: Optional[bool] = False,
        at_index: Optional[int] = None,
    ):

        D = cProcess_group(
            {
                "orch_name": orch_name,
                "process_group_label": process_group_label,
                "actualizer": actualizer,
                "actualizer_pars": actualizer_pars,
                "result_dict": result_dict,
                "access": access,
            }
        )

        # reminder: process_group_dict values take precedence over keyword args but we grab
        # active or last process_group label if process_group_label is not specified
        if D.orch_name is None:
            D.orch_name = self.server_name
        if process_group_label is None:
            if self.active_process_group is not None:
                active_label = self.active_process_group.process_group_label
                self.print_message(
                    f" ... process_group_label not specified, inheriting {active_label} from active process_group"
                )
                D.process_group_label = active_label
            elif self.last_process_group is not None:
                last_label = self.last_process_group.process_group_label
                self.print_message(
                    f" ... process_group_label not specified, inheriting {last_label} from previous process_group"
                )
                D.process_group_label = last_label
            else:
                self.print_message(
                    " ... process_group_label not specified, no past process_group_dq to inherit so using default 'nolabel"
                )
        await asyncio.sleep(0.001)
        if at_index:
            self.process_group_dq.insert(i=at_index, x=D)
        elif prepend:
            self.process_group_dq.appendleft(D)
            self.print_message(f" ... process_group {D.process_group_uuid} prepended to queue")
        else:
            self.process_group_dq.append(D)
            self.print_message(f" ... process_group {D.process_group_uuid} appended to queue")

    def list_process_groups(self):
        """Return the current queue of process_group_dq."""

        process_group_list = [
            return_process_group(
                index=i,
                uid=process_group.process_group_uuid,
                label=process_group.process_group_label,
                actualizer=process_group.actualizer,
                pars=process_group.actualizer_pars,
                access=process_group.access,
            )
            for i, process_group in enumerate(self.process_group_dq)
        ]
        retval = return_process_group_list(process_groups=process_group_list)
        return retval

    def get_process_group(self, last=False):
        """Return the active or last process_group."""
        if last:
            process_group = self.last_process_group
        else:
            process_group = self.active_process_group
        if process_group is not None:
            process_group_list = [
                return_process_group(
                    index=-1,
                    uid=process_group.process_group_uuid,
                    label=process_group.process_group_label,
                    actualizer=process_group.actualizer,
                    pars=process_group.actualizer_pars,
                    access=process_group.access,
                )
            ]
        else:
            process_group_list = [
                return_process_group(
                    index=-1,
                    uid=None,
                    label=None,
                    actualizer=None,
                    pars=None,
                    access=None,
                )
            ]
        retval = return_process_group_list(process_groups=process_group_list)
        return retval

    def list_active_processes(self):
        """Return the current queue running processes."""
        process_list = []
        index = 0
        for process_serv, process_dict in self.global_state_dict.items():
            for process_name, process_uuids in process_dict.items():
                for process_uuid in process_uuids:
                    process_list.append(
                        return_process(
                            index=index,
                            uid=process_uuid,
                            server=process_serv,
                            process=process_name,
                            pars=dict(),
                            preempt=-1,
                        )
                    )
                    index = index + 1
        retval = return_process_list(processes=process_list)
        return retval

    def list_processes(self):
        """Return the current queue of process_dq."""
        process_list = [
            return_process(
                index=i,
                uid=process.process_uuid,
                server=process.process_server,
                process=process.process_name,
                pars=process.process_params,
                preempt=process.start_condition,
            )
            for i, process in enumerate(self.process_dq)
        ]
        retval = return_process_list(processes=process_list)
        return retval

    def supplement_error_process(self, check_uuid: str, sup_process: cProcess):
        """Insert process at front of process queue with subversion of errored process, inherit parameters if desired."""
        if self.error_uuids == []:
            self.print_message("There are no error statuses to replace")
        else:
            matching_error = [tup for tup in self.error_uuids if tup[2] == check_uuid]
            if matching_error:
                _, _, error_uuid = matching_error[0]
                EA = [
                    A
                    for _, A in self.dispatched_processes.items()
                    if A.process_uuid == error_uuid
                ][0]
                # up to 99 supplements
                new_enum = round(EA.process_enum + 0.01, 2)
                new_process = sup_process
                new_process.process_enum = new_enum
                self.process_dq.appendleft(new_process)
            else:
                self.print_message(
                    f"uuid {check_uuid} not found in list of error statuses:"
                )
                self.print_message(", ".join(self.error_uuids))

    def remove_process_group(
        self, by_index: Optional[int] = None, by_uuid: Optional[str] = None
    ):
        """Remove process_group in list by enumeration index or uuid."""
        if by_index:
            i = by_index
        elif by_uuid:
            i = [
                i
                for i, D in enumerate(list(self.process_group_dq))
                if D.process_group_uuid == by_uuid
            ][0]
        else:
            self.print_message(
                "No arguments given for locating existing process_group to remove."
            )
            return None
        del self.process_group_dq[i]

    def replace_process(
        self,
        sup_process: cProcess,
        by_index: Optional[int] = None,
        by_uuid: Optional[str] = None,
        by_enum: Optional[Union[int, float]] = None,
    ):
        """Substitute a queued process."""
        if by_index:
            i = by_index
        elif by_uuid:
            i = [
                i
                for i, A in enumerate(list(self.process_dq))
                if A.process_uuid == by_uuid
            ][0]
        elif by_enum:
            i = [
                i
                for i, A in enumerate(list(self.process_dq))
                if A.process_enum == by_enum
            ][0]
        else:
            self.print_message(
                "No arguments given for locating existing process to replace."
            )
            return None
        current_enum = self.process_dq[i].process_enum
        new_process = sup_process
        new_process.process_enum = current_enum
        self.process_dq.insert(i, new_process)
        del self.process_dq[i + 1]

    def append_process(self, sup_process: cProcess):
        """Add process to end of current process queue."""
        if len(self.process_dq) == 0:
            last_enum = floor(max(list(self.dispatched_processes.keys())))
        else:
            last_enum = floor(self.process_dq[-1].process_enum)
        new_enum = int(last_enum + 1)
        new_process = sup_process
        new_process.process_enum = new_enum
        self.process_dq.append(new_process)

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
    process_lib = {}
    if library_path is None:
        library_path = world_config_dict.get(
            "process_library_path", os.path.join("helao", "library", "actualizer")
        )
    if not os.path.isdir(library_path):
        print_message(
            world_config_dict,
            server_name,
            f" ... library path {library_path} was specified but is not a valid directory",
        )
        return process_lib  # False
    sys.path.append(library_path)
    for actlib in world_config_dict["process_libraries"]:
        tempd = import_module(actlib).__dict__
        process_lib.update({func: tempd[func] for func in tempd["ACTUALIZERS"]})
    print_message(
        world_config_dict,
        server_name,
        f" ... imported {len(world_config_dict['process_libraries'])} actualizers specified by config.",
    )
    return process_lib  # True


async def async_process_dispatcher(world_config_dict: dict, A: cProcess):
    """Request non-blocking process_dq which may run concurrently.

    Send process object to process server for processing.

    Args:
        A: an process type object contain process server name, endpoint, parameters

    Returns:
        Response string from http POST request to process server
    """
    actd = world_config_dict["servers"][A.process_server]
    act_addr = actd["host"]
    act_port = actd["port"]
    url = f"http://{act_addr}:{act_port}/{A.process_server}/{A.process_name}"
    # splits process dict into suitable params and json parts
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
    private_process: str,
    params_dict: dict,
    json_dict: dict,
):
    """Request non-blocking private process which may run concurrently.

    Returns:
        Response string from http POST request to process server
    """

    actd = world_config_dict["servers"][server]
    act_addr = actd["host"]
    act_port = actd["port"]

    url = f"http://{act_addr}:{act_port}/{private_process}"

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
