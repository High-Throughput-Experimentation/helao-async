__all__ = ["Base", "ActiveParams", "makeActionServ", "Active", "Executor", "DummyBase"]

import asyncio
import json
import os
import sys
from socket import gethostname
from time import ctime, time, time_ns
from typing import List, Optional, Dict
from types import MethodType
from uuid import UUID, uuid1
import hashlib
from copy import deepcopy
import inspect
import traceback

import aiofiles
import colorama
import ntplib
import numpy as np
import pyaml

from fastapi import Body, WebSocket
from fastapi.dependencies.utils import get_flat_params


from helao.helpers.server_api import HelaoFastAPI
from helao.helpers.dispatcher import async_private_dispatcher

from helao.helpers.helao_dirs import helao_dirs
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.print_message import print_message
from helao.helpers import async_copy
from helao.helpers.yml_finisher import move_dir
from helao.helpers.premodels import Action
from helaocore.models.hlostatus import HloStatus
from helaocore.models.sample import (
    SampleType,
    SampleUnion,
    NoneSample,
    SampleInheritance,
    SampleStatus,
    object_to_sample,
)
from helaocore.models.data import DataModel, DataPackageModel
from helaocore.models.machine import MachineModel
from helaocore.models.server import ActionServerModel, EndpointModel
from helaocore.models.action import ActionModel
from helao.helpers.active_params import ActiveParams
from helaocore.models.file import (
    FileConn,
    FileConnParams,
    HloFileGroup,
    FileInfo,
    HloHeaderModel,
)
from helao.helpers.file_in_use import file_in_use
from helaocore.error import ErrorCodes

# ANSI color codes converted to the Windows versions
# strip colors if stdout is redirected
colorama.init(strip=not sys.stdout.isatty())
# colorama.init()

hlotags_metadata = [
    {"name": "public", "description": "public action server endpoints"},
    {"name": "private", "description": "private action server endpoints"},
]

# TODO: major refactor, move makeActionServ & makeVisServ methods under Base
# 1. input confPrefix, servKey, helao_root to Base init
# 2. initialize driver and app in Base
# 3. Base method returns app for server templates
# 4. need to revise drivers that directly reference Base (almost all use printmsg),
#    better to remove Base dependency and use Executor as shim, and all external calls
#    to driver should return dict: {"response": ..., "data": ..., "error": ...}
# 5. Executors can be stored alongside driver module, but better to put in server


def makeActionServ(
    config,
    server_key,
    server_title,
    description,
    version,
    driver_class=None,
    dyn_endpoints=None,
):

    app = HelaoFastAPI(
        helao_cfg=config,
        helao_srv=server_key,
        title=server_title,
        description=description,
        version=version,
        openapi_tags=hlotags_metadata,
    )

    @app.on_event("startup")
    def startup_event():
        app.base = Base(app, driver_class, dyn_endpoints)

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

    @app.websocket("/ws_live")
    async def websocket_live(websocket: WebSocket):
        """Broadcast live buffer dicts.

        Args:
        websocket: a fastapi.WebSocket object
        """
        await app.base.ws_live(websocket)

    @app.post("/get_status", tags=["private"])
    def status_wrapper():
        return app.base.actionservermodel

    @app.post("/attach_client", tags=["private"])
    async def attach_client(client_servkey: str):
        return await app.base.attach_client(client_servkey)

    @app.post("/stop_executor", tags=["private"])
    def stop_executor(executor_id: str):
        return app.base.stop_executor(executor_id)

    @app.post("/endpoints", tags=["private"])
    def get_all_urls():
        """Return a list of all endpoints on this server."""
        return app.base.get_endpoint_urls()

    @app.post(f"/{server_key}/estop", tags=["public"])
    async def estop(
        action: Optional[Action] = Body({}, embed=True), switch: Optional[bool] = True
    ):
        active = await app.base.setup_and_contain_action(
            json_data_keys=["estop"], action_abbr="estop"
        )
        has_estop = getattr(app.driver, "estop", None)
        if has_estop is not None and callable(has_estop):
            app.driver.base.print_message("driver has estop function", info=True)
            await active.enqueue_data_dflt(
                datadict={
                    "estop": await app.driver.estop(**active.action.action_params)
                }
            )
        else:
            app.driver.base.print_message("driver has NO estop function", info=True)
            app.driver.base.actionservermodel.estop = switch
        if switch:
            active.action.action_status.append(HloStatus.estopped)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post("/get_lbuf", tags=["private"])
    def get_lbuf():
        return app.base.live_buffer

    @app.post("/list_executors", tags=["private"])
    def list_executors():
        return list(app.base.executors.keys())

    @app.post("/shutdown", tags=["private"])
    async def post_shutdown():
        await shutdown_event()

    @app.on_event("shutdown")
    async def shutdown_event():
        app.base.print_message("action shutdown", info=True)
        await app.base.shutdown()

        shutdown = getattr(app.driver, "shutdown", None)
        if shutdown is not None and callable(shutdown):
            app.driver.base.print_message("driver has shutdown function", info=True)
            retval = shutdown()
        else:
            app.driver.base.print_message("driver has NO shutdown function", error=True)
            retval = {"shutdown"}
        return retval

    return app


class Executor:
    """Generic template for action executor (steps 5-6 of action_loop_task).

    Hooks
    1. Device setup calls (optional)
        a. Suspend live polling task (optional)
    2. Execute action start, return {"data": ..., "error": ...}
    3. Polling (optional)
        a. Standard return dict has {"data": ..., "status": ..., "error": ...}
        b. Error handling
        c. Check for external stop if looping.
    4. Resume live polling task (optional)
        a. Cleanup calls (optional)
    """

    def __init__(
        self,
        active,
        poll_rate: float = 0.2,
        oneoff: bool = True,
        exid: Optional[str] = None,
    ):
        self.active = active
        self.oneoff = oneoff
        self.poll_rate = poll_rate
        if exid is None:
            self.exid = f"{active.action.action_name} {active.action.action_uuid}"
        else:
            self.exid = exid
        self.active.action.exid = self.exid

    async def _pre_exec(self):
        "Setup methods, return error state."
        self.active.base.print_message("generic Executor running setup methods.")
        self.setup_err = ErrorCodes.none
        return {"error": self.setup_err}

    def set_pre_exec(self, pre_exec_func):
        "Override the generic setup method."
        self._pre_exec = MethodType(pre_exec_func, self)

    async def _exec(self):
        "Perform device read/write."
        return {"data": {}, "error": ErrorCodes.none}

    def set_exec(self, exec_func):
        "Override the generic execute method."
        self._exec = MethodType(exec_func, self)

    async def _poll(self):
        "Perform one polling iteration."
        return {"data": {}, "error": ErrorCodes.none, "status": HloStatus.finished}

    def set_poll(self, poll_func):
        "Override the generic execute method."
        self._poll = MethodType(poll_func, self)

    async def _post_exec(self):
        "Cleanup methods, return error state."
        self.cleanup_err = ErrorCodes.none
        return {"error": self.cleanup_err}

    def set_post_exec(self, post_exec_func):
        "Override the generic cleanup method."
        self._post_exec = MethodType(post_exec_func, self)

    async def _manual_stop(self):
        "Perform device manual stop, return error state."
        self.stop_err = ErrorCodes.none
        return {"error": self.stop_err}

    def set_manual_stop(self, manual_stop_func):
        "Override the generic manual stop method."
        self._manual_stop = MethodType(manual_stop_func, self)


class Base:
    """Base class for all HELAO servers.

    Base is a general class which implements message passing,
    status update, data writing, and data streaming via async tasks.
    Every instrument and action server should import this class
    for efficient integration into an orchestrated environment.

    A Base initialized within a FastAPI startup event
    will launch three async tasks to the server's event loop for handling:
    (1) broadcasting status updates via websocket and
        http POST requests to an attached
        orchestrator's status updater if available,
    (2) data streaming via websocket,
    (3) data writing to local disk.

    Websocket connections are broadcast from a multisubscriber queue
    in order to handle consumption from multiple clients
    awaiting a single queue. Self-subscriber tasks are
    also created as initial subscribers
    to log all events and prevent queue overflow.

    The data writing method will update a class attribute
    with the currently open file.
    For a given root directory, files
    and folders will be written as follows: TBD
    """

    def __init__(self, fastapp: HelaoFastAPI, driver_class=None, dyn_endpoints=None):
        self.server = MachineModel(
            server_name=fastapp.helao_srv, machine_name=gethostname()
        )

        self.fastapp = fastapp
        self.server_cfg = self.fastapp.helao_cfg["servers"][self.server.server_name]
        self.server_params = self.fastapp.helao_cfg["servers"][
            self.server.server_name
        ].get("params", {})
        self.world_cfg = self.fastapp.helao_cfg
        self.run_type = None
        self.aloop = asyncio.get_running_loop()

        self.helaodirs = helao_dirs(self.world_cfg, self.server.server_name)

        if self.helaodirs.root is None:
            raise ValueError(
                "Warning: root directory was not defined. Logs, PRCs, PRGs, and data will not be written.",
                error=True,
            )

        if "run_type" in self.world_cfg:
            self.print_message(
                f"Found run_type in config: {self.world_cfg['run_type']}",
            )
            self.run_type = self.world_cfg["run_type"]
        else:
            raise ValueError(
                "Missing 'run_type' in config, cannot create server object.",
                error=True,
            )

        self.actives: Dict[UUID, object] = {}
        self.executors = {}  # shortcut to running Executors
        # basemodel to describe the full action server
        self.actionservermodel = ActionServerModel(action_server=self.server)
        self.actionservermodel.init_endpoints()

        self.status_q = MultisubscriberQueue()
        self.data_q = MultisubscriberQueue()
        self.live_q = MultisubscriberQueue()
        self.live_buffer = {}
        self.status_clients = set()
        self.ntp_server = "time.nist.gov"
        self.ntp_response = None
        self.ntp_offset = None  # add to system time for correction
        self.ntp_last_sync = None

        self.ntp_last_sync_file = None
        if self.helaodirs.root is not None:
            self.ntp_last_sync_file = os.path.join(
                self.helaodirs.states_root, "ntpLastSync.txt"
            )
            if os.path.exists(self.ntp_last_sync_file):
                with open(self.ntp_last_sync_file, "r") as f:
                    tmps = f.readline().strip().split(",")
                    if len(tmps) == 2:
                        self.ntp_last_sync, self.ntp_offset = tmps
                        self.ntp_offset = float(self.ntp_offset)

        if self.ntp_last_sync is None:
            asyncio.gather(self.get_ntp_time())

        self.sync_ntp_task_run = False
        self.ntp_syncer = self.aloop.create_task(self.sync_ntp_task())
        self.bufferer = self.aloop.create_task(self.live_buffer_task())

        if driver_class is not None:
            self.fastapp.driver = driver_class(self)

        # # if provided add more dynmaic endpoints after driver initialization
        # if callable(dyn_endpoints):
        #     asyncio.gather(dyn_endpoints(app=self.fastapp))

        asyncio.gather(self.init_endpoint_status(dyn_endpoints))

        self.fast_urls = self.get_endpoint_urls()
        self.status_logger = self.aloop.create_task(self.log_status_task())

    def print_message(self, *args, **kwargs):
        print_message(
            self.server_cfg,
            self.server.server_name,
            log_dir=self.helaodirs.log_root,
            *args,
            **kwargs,
        )

    async def init_endpoint_status(self, dyn_endpoints=None):
        """Populate status dict
        with FastAPI server endpoints for monitoring."""
        if callable(dyn_endpoints):
            await dyn_endpoints(app=self.fastapp)
        for route in self.fastapp.routes:
            # print(route.path)
            if route.path.startswith(f"/{self.server.server_name}"):
                self.actionservermodel.endpoints.update(
                    {route.name: EndpointModel(endpoint_name=route.name)}
                )

        self.print_message(
            f"Found {len(self.actionservermodel.endpoints.keys())} endpoints "
            f"for status monitoring on {self.server.server_name}."
        )

    def get_endpoint_urls(self):
        """Return a list of all endpoints on this server."""
        url_list = []
        for route in self.fastapp.routes:
            routeD = {"path": route.path, "name": route.name}
            if "dependant" in dir(route):
                flatParams = get_flat_params(route.dependant)
                paramD = {
                    par.name: {
                        "outer_type": str(par.outer_type_).split("'")[1]
                        if len(str(par.outer_type_).split("'")) >= 2
                        else str(par.outer_type_),
                        "type": str(par.type_).split("'")[1]
                        if len(str(par.type_).split("'")) >= 2
                        else str(par.type_),
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

    async def _get_action(self, frame) -> Action:
        _args, _varargs, _keywords, _locals = inspect.getargvalues(frame)
        action = None
        paramdict = {}

        for arg in _args:
            argparam = _locals.get(arg, None)
            if isinstance(argparam, Action):
                if action is None:
                    self.print_message(
                        f"found Action BaseModel under parameter '{arg}'", info=True
                    )
                    action = argparam
                else:
                    self.print_message(
                        f"critical error: found another Action BaseModel"
                        f" under parameter '{arg}',"
                        f" skipping it",
                        error=True,
                    )
            else:
                paramdict.update({arg: argparam})

        if action is None:
            self.print_message(
                "critical error: no Action BaseModel was found by setup_action, using blank Action.",
                error=True,
            )
            action = Action()

        for key, val in paramdict.items():
            if key not in action.action_params:
                self.print_message(
                    f"local var '{key}' not found in action.action_params, addding it.",
                    info=True,
                )
                action.action_params.update({key: val})

        self.print_message(f"Action.action_params: {action.action_params}", info=True)

        # name of the caller function
        calname = sys._getframe().f_back.f_back.f_code.co_name
        # fastapi url for caller function
        urlname = self.fastapp.url_path_for(calname)

        # action name should be the last one
        action_name = urlname.strip("/").split("/")[-1]
        # use the already known servKey, not the one from the url
        servKey = self.server.server_name

        action.action_server = MachineModel(
            server_name=servKey, machine_name=gethostname()
        )
        action.action_name = action_name

        if action.action_params is not None:
            if "fast_samples_in" in action.action_params:
                tmp_fast_samples_in = action.action_params.get("fast_samples_in", [])
                del action.action_params["fast_samples_in"]

                for sample in tmp_fast_samples_in:
                    action.samples_in.append(object_to_sample(sample))

        if action.action_abbr is None:
            action.action_abbr = action.action_name

        # setting some default values if action was not submitted via orch
        if action.run_type is None:
            action.run_type = self.run_type
            action.orchestrator = MachineModel(
                server_name="MANUAL", machine_name=gethostname()
            )
        return action

    async def setup_action(self) -> Action:
        return await self._get_action(frame=inspect.currentframe().f_back)

    async def setup_and_contain_action(
        self,
        json_data_keys: List[str] = [],
        action_abbr: Optional[str] = None,
        file_type: Optional[str] = "helao__file",
        hloheader: Optional[HloHeaderModel] = HloHeaderModel(),
    ) -> object:
        """This is a simple shortcut for very basic endpoints
        which just want to return some simple data"""
        action = await self._get_action(frame=inspect.currentframe().f_back)
        if action_abbr is not None:
            action.action_abbr = action_abbr
        active = await self.contain_action(
            ActiveParams(
                action=action,
                file_conn_params_dict={
                    self.dflt_file_conn_key(): FileConnParams(
                        file_conn_key=self.dflt_file_conn_key(),
                        json_data_keys=json_data_keys,
                        file_type=file_type,
                        hloheader=hloheader,
                    )
                },
            )
        )
        return active

    async def contain_action(self, activeparams: ActiveParams) -> object:
        """return an active Action:
        file_type: type of output data file
        json_data_keys: data keys for json encoded data (dict)
        file_sample_label: list of sample labels
        file_conn_keys:
        header: header for data file
        """
        self.actives[activeparams.action.action_uuid] = Active(
            self, activeparams=activeparams
        )
        await self.actives[activeparams.action.action_uuid].myinit()
        return self.actives[activeparams.action.action_uuid]

    async def get_active_info(self, action_uuid: UUID):
        if action_uuid in self.actives:
            action_dict = await self.actives[action_uuid].active.as_dict()
            return action_dict
        else:
            self.print_message(
                f"Specified action uuid {str(action_uuid)} was not found.", error=True
            )
            return None

    async def get_ntp_time(self):
        """Check system clock against NIST clock for trigger operations."""
        lock = asyncio.Lock()
        async with lock:
            c = ntplib.NTPClient()
            try:
                response = c.request(self.ntp_server, version=3)
                self.ntp_response = response
                self.ntp_last_sync = response.orig_time
                self.ntp_offset = response.offset
                self.print_message(
                    f"retrieved time at "
                    f"{ctime(self.ntp_response.tx_timestamp)} "
                    f"from {self.ntp_server}",
                )
            except ntplib.NTPException:
                self.print_message(f"{self.ntp_server} ntp timeout", error=True)
                self.ntp_last_sync = time()
                self.ntp_offset = 0.0

            self.print_message(f"ntp_offset: {self.ntp_offset}")
            self.print_message(f"ntp_last_sync: {self.ntp_last_sync}")

            if self.ntp_last_sync_file is not None:
                while file_in_use(self.ntp_last_sync_file):
                    self.print_message("ntp file already in use, waiting", info=True)
                    await asyncio.sleep(0.1)
                async with aiofiles.open(self.ntp_last_sync_file, "w") as f:
                    await f.write(f"{self.ntp_last_sync},{self.ntp_offset}")

    async def send_statuspackage(
        self,
        client_servkey: str,
        action_name: Optional[str] = None,
    ):
        # needs private dispatcher
        json_dict = {
            "actionservermodel": self.actionservermodel.get_fastapi_json(
                action_name=action_name
            )
        }
        response, error_code = await async_private_dispatcher(
            world_config_dict=self.world_cfg,
            server=client_servkey,
            private_action="update_status",
            params_dict={},
            json_dict=json_dict,
        )
        return response, error_code

    async def send_nbstatuspackage(
        self,
        client_servkey: str,
        actionmodel: ActionModel,
    ):
        # needs private dispatcher
        json_dict = {"actionmodel": actionmodel.json_dict()}
        self.print_message(f"sending non-blocking status: {json_dict}")
        response, error_code = await async_private_dispatcher(
            world_config_dict=self.world_cfg,
            server=client_servkey,
            private_action="update_nonblocking",
            params_dict={},
            json_dict=json_dict,
        )
        self.print_message(f"update_nonblocking request got response: {response}")
        return response, error_code

    async def attach_client(self, client_servkey: str, retry_limit=5):
        """Add client for pushing status updates via HTTP POST."""
        success = False

        if client_servkey in self.world_cfg["servers"]:

            if client_servkey in self.status_clients:
                self.print_message(
                    f"Client {client_servkey} is already subscribed to "
                    f"{self.server.server_name} status updates."
                )
                self.detach_client(client_servkey)

            self.status_clients.add(client_servkey)

            # sends current status of all endpoints (action_name = None)
            for _ in range(retry_limit):
                response, error_code = await self.send_statuspackage(
                    action_name=None, client_servkey=client_servkey
                )
                if response is not None and error_code == ErrorCodes.none:
                    self.print_message(
                        f"Added {client_servkey} to {self.server.server_name} status subscriber list."
                    )
                    success = True
                    break
                else:
                    self.print_message(
                        f"Failed to add {client_servkey} to "
                        f"{self.server.server_name} status subscriber list.",
                        error=True,
                    )

            if success:
                self.print_message(
                    f"Attached {client_servkey} to status ws on {self.server.server_name}."
                )
            else:
                self.print_message(
                    f"failed to attach {client_servkey} to status ws "
                    f"on {self.server.server_name} "
                    f"after {retry_limit} attempts.",
                    error=True,
                )

        return success

    def detach_client(self, client_servkey: str):
        """Remove client from receiving status updates via HTTP POST"""
        if client_servkey in self.status_clients:
            self.status_clients.remove(client_servkey)
            self.print_message(
                f"Client {client_servkey} will no longer receive status updates."
            )
        else:
            self.print_message(f"Client {client_servkey} is not subscribed.")

    async def ws_status(self, websocket: WebSocket):
        "Subscribe to status queue and send message to websocket client."
        self.print_message("got new status subscriber")
        await websocket.accept()
        try:
            async for status_msg in self.status_q.subscribe():
                await websocket.send_text(json.dumps(status_msg.json_dict()))
        # except WebSocketDisconnect:
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            self.print_message(
                f"Status websocket client {websocket.client[0]}:{websocket.client[1]} disconnected. {repr(e), tb,}",
                error=True,
            )

    async def ws_data(self, websocket: WebSocket):
        """Subscribe to data queue and send messages to websocket client."""
        self.print_message("got new data subscriber")
        await websocket.accept()
        try:
            async for data_msg in self.data_q.subscribe():
                await websocket.send_text(json.dumps(data_msg.json_dict()))
        # except WebSocketDisconnect:
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            self.print_message(
                f"Data websocket client {websocket.client[0]}:{websocket.client[1]} disconnected. {repr(e), tb,}",
                error=True,
            )

    async def ws_live(self, websocket: WebSocket):
        """Subscribe to data queue and send messages to websocket client."""
        self.print_message("got new live_buffer subscriber")
        await websocket.accept()
        try:
            async for live_msg in self.live_q.subscribe():
                await websocket.send_text(json.dumps(live_msg))
        # except WebSocketDisconnect:
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            self.print_message(
                f"Data websocket client {websocket.client[0]}:{websocket.client[1]} disconnected. {repr(e), tb,}",
                error=True,
            )

    async def live_buffer_task(self):
        """Self-subscribe to live_q, update live_buffer dict."""
        self.print_message(f"{self.server.server_name} live buffer task created.")
        async for live_msg in self.live_q.subscribe():
            self.live_buffer.update(live_msg)

    async def put_lbuf(self, live_dict):
        """Convert dict values to tuples of (val, timestamp), enqueue to live_q."""
        new_dict = {k: (v, time()) for k, v in live_dict.items()}
        await self.live_q.put(new_dict)

    def get_lbuf(self, live_key):
        return self.live_buffer[live_key]

    async def log_status_task(self, retry_limit: int = 5):
        """Self-subscribe to status queue, log status changes, POST to clients."""
        self.print_message(f"{self.server.server_name} status log task created.")

        try:
            # get the new ActionModel (status) from the queue
            async for status_msg in self.status_q.subscribe():
                # add it to the correct "EndpointModel"
                # in the "ActionServerModel"
                if status_msg.action_name not in self.actionservermodel.endpoints:
                    # a new endpoints became available
                    self.actionservermodel.endpoints[
                        status_msg.action_name
                    ] = EndpointModel(endpoint_name=status_msg.action_name)
                self.actionservermodel.endpoints[
                    status_msg.action_name
                ].active_dict.update({status_msg.action_uuid: status_msg})
                self.actionservermodel.last_action_uuid = status_msg.action_uuid

                # sort the status (nonactive_dict is empty at this point)
                self.actionservermodel.endpoints[status_msg.action_name].sort_status()
                self.print_message(
                    f"log_status_task sending status "
                    f"{status_msg.action_status} for action "
                    f"{status_msg.action_name} "
                    f"with uuid {status_msg.action_uuid} on "
                    f"{status_msg.action_server.disp_name()} "
                    f"to subscribers ({self.status_clients})."
                )
                for client_servkey in self.status_clients:
                    self.print_message(
                        f"log_status_task trying to send status to {client_servkey}."
                    )
                    success = False
                    for _ in range(retry_limit):
                        response, error_code = await self.send_statuspackage(
                            action_name=status_msg.action_name,
                            client_servkey=client_servkey,
                        )

                        if response and error_code == ErrorCodes.none:
                            success = True
                            break

                    if success:
                        self.print_message(
                            f"Pushed status message to {client_servkey}."
                        )
                    else:
                        self.print_message(
                            f"Failed to push status message to "
                            f"{client_servkey} after {retry_limit} attempts.",
                            error=True,
                        )
                # now delete the errored and finsihed statuses after
                # all are send to the subscribers
                self.actionservermodel.endpoints[
                    status_msg.action_name
                ].clear_finished()
                # TODO:write to log if save_root exists
                self.print_message("all log_status_task messages send.")

            self.print_message("log_status_task done.")

        # except asyncio.CancelledError:
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            self.print_message(
                f"status logger task was cancelled with error: {repr(e), tb,}",
                error=True,
            )

    async def detach_subscribers(self):
        await self.status_q.put(StopAsyncIteration)
        await self.data_q.put(StopAsyncIteration)
        await asyncio.sleep(1)

    async def get_realtime(
        self, epoch_ns: Optional[float] = None, offset: Optional[float] = None
    ) -> float:
        """returns epoch in ns"""
        return self.get_realtime_nowait(epoch_ns=epoch_ns, offset=offset)

    def get_realtime_nowait(
        self, epoch_ns: Optional[float] = None, offset: Optional[float] = None
    ) -> float:
        """returns epoch in ns"""
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

    async def sync_ntp_task(self, resync_time: int = 1800):
        "Regularly sync with NTP server."
        self.sync_ntp_task_run = True
        try:
            while self.sync_ntp_task_run:
                # await asyncio.sleep(10)
                # lock = asyncio.Lock()
                # async with lock:
                ntp_last_sync = ""
                if self.ntp_last_sync_file is not None:
                    async with aiofiles.open(self.ntp_last_sync_file, "r") as f:
                        ntp_last_sync = await f.readline()
                parts = ntp_last_sync.strip().split(",")
                if len(parts) == 2:
                    self.ntp_last_sync = float(parts[0])
                    self.ntp_offset = float(parts[1])
                else:
                    self.ntp_last_sync = float(parts[0])
                    self.ntp_offset = 0.0
                if time() - self.ntp_last_sync > resync_time:
                    # self.print_message(
                    #     f"last time check was more then {resync_time/60.0:.1f} minutes ago, syncing time again."
                    # )
                    await self.get_ntp_time()
                else:
                    # wait_time = time() - self.ntp_last_sync
                    wait_time = resync_time
                    # self.print_message(f"waiting {wait_time} until next time check")
                    await asyncio.sleep(wait_time)
        except asyncio.CancelledError:
            self.print_message("ntp sync task was cancelled", info=True)

    async def shutdown(self):
        self.sync_ntp_task_run = False
        await self.detach_subscribers()
        self.status_logger.cancel()
        self.ntp_syncer.cancel()

    async def write_act(self, action):
        "Create new exp if it doesn't exist."
        if action.save_act:
            act_dict = action.get_actmodel().clean_dict()
            output_path = os.path.join(
                self.helaodirs.save_root, action.action_output_dir
            )
            output_file = os.path.join(
                output_path,
                f"{action.action_timestamp.strftime('%Y%m%d.%H%M%S%f')}-act.yml",
            )

            self.print_message(f"writing to act meta file: {output_path}")

            if not os.path.exists(output_path):
                os.makedirs(output_path, exist_ok=True)

            async with aiofiles.open(output_file, mode="w+") as f:
                await f.write(pyaml.dump({"file_type": "action"}))
                await f.write(pyaml.dump(act_dict, sort_dicts=False))
        else:
            self.print_message(
                f"writing meta file for action '{action.action_name}' is disabled.",
                info=True,
            )

    async def write_exp(self, experiment, manual=False):
        exp_dict = experiment.get_exp().clean_dict()
        if manual:
            save_root = str(self.helaodirs.save_root).replace("ACTIVE", "DIAG")
        else:
            save_root = self.helaodirs.save_root
        output_path = os.path.join(save_root, experiment.get_experiment_dir())
        output_file = os.path.join(
            output_path,
            f"{experiment.experiment_timestamp.strftime('%Y%m%d.%H%M%S%f')}-exp.yml",
        )

        self.print_message(f"writing to exp meta file: {output_file}")
        output_str = pyaml.dump(exp_dict, sort_dicts=False)

        if not os.path.exists(output_path):
            os.makedirs(output_path, exist_ok=True)

        async with aiofiles.open(output_file, mode="w+") as f:
            await f.write(pyaml.dump({"file_type": "experiment"}))
            if not output_str.endswith("\n"):
                output_str += "\n"
            await f.write(output_str)

    async def write_seq(self, sequence, manual=False):
        seq_dict = sequence.get_seq().clean_dict()
        sequence_dir = sequence.get_sequence_dir()
        if manual:
            save_root = str(self.helaodirs.save_root).replace("ACTIVE", "DIAG")
        else:
            save_root = self.helaodirs.save_root
        output_path = os.path.join(save_root, sequence_dir)
        output_file = os.path.join(
            output_path,
            f"{sequence.sequence_timestamp.strftime('%Y%m%d.%H%M%S%f')}-seq.yml",
        )

        self.print_message(f"writing to seq meta file: {output_file}")
        output_str = pyaml.dump(seq_dict, sort_dicts=False)

        if not os.path.exists(output_path):
            os.makedirs(output_path, exist_ok=True)

        async with aiofiles.open(output_file, mode="w+") as f:
            await f.write(pyaml.dump({"file_type": "sequence"}))
            if not output_str.endswith("\n"):
                output_str += "\n"
            await f.write(output_str)

    async def append_exp_to_seq(self, exp, seq):
        append_dict = {
            "experiment_uuid": str(exp.experiment_uuid),
            "experiment_name": exp.experiment_name,
            "experiment_output_dir": exp.experiment_output_dir,
        }
        append_str = (
            "\n".join(["  " + x for x in pyaml.dump([append_dict]).split("\n")][:-1])
            + "\n"
        )
        sequence_dir = seq.get_sequence_dir()
        save_root = self.helaodirs.save_root
        output_path = os.path.join(save_root, sequence_dir)
        output_file = os.path.join(
            output_path,
            f"{seq.sequence_timestamp.strftime('%Y%m%d.%H%M%S%f')}-seq.yml",
        )
        async with aiofiles.open(output_file, mode="a") as f:
            await f.write(append_str)

    def new_file_conn_key(self, key: str) -> UUID:
        # return shortuuid.decode(key)
        # Instansiate new md5_hash
        md5_hash = hashlib.md5()
        # Pass the_string to the md5_hash as bytes
        md5_hash.update(key.encode("utf-8"))
        # Generate the hex md5 hash of all the read bytes
        the_md5_hex_str = md5_hash.hexdigest()
        # Return a String repersenation of the uuid of the md5 hash
        return UUID(the_md5_hex_str)

    def dflt_file_conn_key(self):
        """simply return a default None"""
        return self.new_file_conn_key(str(None))

    def replace_status(
        self, status_list: List[HloStatus], old_status: HloStatus, new_status: HloStatus
    ):
        if old_status in status_list:
            idx = status_list.index(old_status)
            status_list[idx] = new_status
        else:
            status_list.append(new_status)

    def get_main_error(self, errors) -> ErrorCodes:
        """select the main error from a list of errors
        currently return the first noty none error"""
        ret_error = ErrorCodes.none
        if isinstance(errors, list):
            for error in errors:
                if error != ErrorCodes.none:
                    ret_error = error
                    break
        else:
            ret_error = errors

        return ret_error

    def stop_executor(self, executor_id: str):
        try:
            self.executors[executor_id].stop_action_task()
            self.print_message(
                f"Signaling executor task {executor_id} to end polling loop."
            )
            return {"signal_stop": True}
        except KeyError:
            self.print_message(f"Could not find {executor_id} among active executors.")
            return {"signal_stop": False}


class Active:
    """Active action holder which wraps data queing and exp writing."""

    def __init__(self, base, activeparams: ActiveParams):  # outer instance
        self.base = base
        self.active_uuid = activeparams.action.action_uuid
        self.action = activeparams.action
        # a list of all actions for this active
        # the most recent one, which is identical to self.action is at
        # position 0
        self.action_list = [self.action]
        self.listen_uuids = []

        # this updates timestamp and uuid
        # only if they are None
        # They are None in manual, but already set in orch mode
        self.action.action_server = self.base.server
        if self.base.world_cfg.get("dummy", "False"):
            self.action.dummy = True
        if self.base.world_cfg.get("simulation", "False"):
            self.action.simulation = True
        self.action.init_act(time_offset=self.base.ntp_offset)
        self.add_new_listen_uuid(self.action.action_uuid)

        if self.action.manual_action:
            self.base.print_message("Manual Action.", info=True)

        if not self.base.helaodirs.save_root:
            self.base.print_message(
                "Root save directory not specified, cannot save action results."
            )
            self.action.save_data = False
            self.action.save_act = False
        else:
            if self.action.save_data is None:
                self.action.save_data = False
            if self.action.save_act is None:
                self.action.save_act = False
            # cannot save data without exp
            if self.action.save_data is True:
                self.action.save_act = True

        # better call this function instead of directly adding it
        # in case we modify the way the uuids are saved
        # self.add_new_listen_uuid(self.action.action_uuid)
        # action_uuid is added after action is init
        for aux_uuid in activeparams.aux_listen_uuids:
            self.add_new_listen_uuid(aux_uuid)

        self.file_conn_dict: Dict(str, FileConn) = {}
        for (
            file_conn_key,
            file_conn_param,
        ) in activeparams.file_conn_params_dict.items():
            self.file_conn_dict[file_conn_key] = FileConn(params=file_conn_param)
            self.action.file_conn_keys.append(file_conn_key)

        self.base.print_message(
            f"save_act is '{self.action.save_act}' for action '{self.action.action_name}'",
            info=True,
        )
        self.base.print_message(
            f"save_data is '{self.action.save_data}' for action '{self.action.action_name}'",
            info=True,
        )

        self.data_logger = self.base.aloop.create_task(self.log_data_task())

        self.manual_stop = False
        self.action_loop_running = False
        self.action_task = None

    async def start_executor(self, executor: Executor):
        self.action_task = self.base.aloop.create_task(self.action_loop_task(executor))
        return self.action.as_dict()

    async def update_act_file(self):
        await self.base.write_act(self.action)

    async def myinit(self):

        if self.action.save_act:
            os.makedirs(
                os.path.join(
                    self.base.helaodirs.save_root, self.action.action_output_dir
                ),
                exist_ok=True,
            )
            await self.update_act_file()

            # if self.action.manual_action:
            #     # create and write seq file for manual action
            #     await self.base.write_seq(self.action)
            #     # create and write exp file for manual action
            #     await self.base.write_exp(self.action)

        self.base.print_message(
            "init active: sending active data_stream_status package", info=True
        )

        await self.add_status()

    def init_datafile(
        self,
        header,
        file_type,
        json_data_keys,
        file_sample_label,
        filename,
        file_group: HloFileGroup,
        file_conn_key: Optional[str] = None,
        action: Optional[Action] = None,
    ):
        filenum = 0
        if action is None:
            action = self.action
        if action is not None:
            if file_conn_key in action.file_conn_keys:
                filenum = action.file_conn_keys.index(file_conn_key)
        if isinstance(header, dict):
            # {} is "{}\n" if not filtered
            if header:
                header = pyaml.dump(header, sort_dicts=False)
            else:
                header = ""
        elif isinstance(header, list):
            if header:
                header = "\n".join(header) + "\n"
            else:
                header = ""
        elif header is None:
            header = ""

        if json_data_keys is None:
            json_data_keys = []

        # determine ending of file
        if file_group == HloFileGroup.helao_files:
            file_ext = "hlo"
        else:  # aux_files
            file_ext = "csv"

        if filename is None:  # generate filename
            filename = f"{action.action_abbr}-{action.orch_submit_order}.{action.action_order}.{action.action_retry}.{action.action_split}__{filenum}.{file_ext}"

        if file_sample_label is None:
            file_sample_label = []
        if not isinstance(file_sample_label, list):
            file_sample_label = [file_sample_label]

        file_info = FileInfo(
            file_type=file_type,
            file_name=filename,
            data_keys=json_data_keys,
            sample=file_sample_label,
            # action ID is here not necessary, or should we still add it?
            # action_uuid: Optional[UUID]
        )

        if header:
            if not header.endswith("\n"):
                header += "\n"

        return header, file_info

    def finish_hlo_header(
        self,
        file_conn_keys: Optional[List[UUID]] = None,
        realtime: Optional[int] = None,
    ):
        """this just adds a timestamp for the data"""
        # needs to be a sync function
        if realtime is None:
            realtime = self.get_realtime_nowait()

        if file_conn_keys is None:
            # get all fileconn_keys
            file_conn_keys = []
            for action in self.action_list:
                for filekey in action.file_conn_keys:
                    file_conn_keys.append(filekey)

        for file_conn_key in file_conn_keys:
            self.file_conn_dict[file_conn_key].params.hloheader.epoch_ns = realtime

    async def add_status(self, action=None):
        """by default send the status of the most recent active action"""
        if action is None:
            action = self.action

        self.base.print_message(
            f"Adding {str(action.action_uuid)} to {action.action_name} status list."
        )

        if not action.nonblocking:
            await self.base.status_q.put(action.get_actmodel())

    async def set_estop(self, action: Optional[Action] = None):
        if action is None:
            action = self.action
        action.action_status.append(HloStatus.estopped)
        self.base.print_message(
            f"E-STOP {str(action.action_uuid)} on {action.action_name} status.",
            error=True,
        )

    async def set_error(
        self,
        error_code: Optional[ErrorCodes] = None,
        action: Optional[Action] = None,
    ):
        if action is None:
            action = self.action
        action.experiment_status.append(HloStatus.errored)

        if error_code:
            action.error_code = error_code
        else:
            action.error_code = ErrorCodes.unspecified

        self.base.print_message(
            f"ERROR {str(action.action_uuid)} on {action.action_name} status.",
            error=True,
        )

    async def get_realtime(
        self, epoch_ns: Optional[float] = None, offset: Optional[float] = None
    ) -> float:
        return self.base.get_realtime_nowait(epoch_ns=epoch_ns, offset=offset)

    def get_realtime_nowait(
        self, epoch_ns: Optional[float] = None, offset: Optional[float] = None
    ) -> float:
        return self.base.get_realtime_nowait(epoch_ns=epoch_ns, offset=offset)

    async def write_live_data(self, output_str: str, file_conn_key: UUID):
        """Appends lines to file_conn."""
        if file_conn_key in self.file_conn_dict:
            if self.file_conn_dict[file_conn_key].file:
                if not output_str.endswith("\n"):
                    output_str += "\n"
                await self.file_conn_dict[file_conn_key].file.write(output_str)

    async def enqueue_data_dflt(self, datadict: dict):
        """This is a simple wrapper for simple endpoints which just
        push data to a single file using a default data conn key
        """
        await self.enqueue_data(
            datamodel=DataModel(data={self.base.dflt_file_conn_key(): datadict})
        )

    async def enqueue_data(self, datamodel: DataModel, action: Optional[Action] = None):
        if action is None:
            action = self.action
        await self.base.data_q.put(
            self.assemble_data_msg(datamodel=datamodel, action=action)
        )

    def enqueue_data_nowait(
        self, datamodel: DataModel, action: Optional[Action] = None
    ):
        if action is None:
            action = self.action
        self.base.data_q.put_nowait(
            self.assemble_data_msg(datamodel=datamodel, action=action)
        )

    def assemble_data_msg(
        self, datamodel: DataModel, action: Optional[Action] = None
    ) -> DataPackageModel:
        if action is None:
            action = self.action
        return DataPackageModel(
            action_uuid=action.action_uuid,
            action_name=action.action_name,
            datamodel=datamodel,
            errors=datamodel.errors,
        )

    def add_new_listen_uuid(self, new_uuid: UUID):
        """adds a new uuid to the current data logger UUID list"""
        self.listen_uuids.append(new_uuid)

    def _get_action_for_file_conn_key(self, file_conn_key: UUID):
        output_action = None
        for action in self.action_list:
            if file_conn_key in action.file_conn_keys:
                output_action = action
                break
        return output_action

    async def log_data_set_output_file(self, file_conn_key: UUID):
        "Set active save_path, write header if supplied."

        self.base.print_message(f"creating file for file conn: {file_conn_key}")

        # get the action for the file_conn_key
        output_action = self._get_action_for_file_conn_key(file_conn_key=file_conn_key)

        if output_action is None:
            self.base.print_message(
                "data logger could not find action for file_conn_key", error=True
            )
            return

        # add some missing information to the hloheader
        if output_action.action_abbr is not None:
            self.file_conn_dict[
                file_conn_key
            ].params.hloheader.action_name = output_action.action_abbr
        else:
            self.file_conn_dict[
                file_conn_key
            ].params.hloheader.action_name = output_action.action_name

        self.file_conn_dict[
            file_conn_key
        ].params.hloheader.column_headings = self.file_conn_dict[
            file_conn_key
        ].params.json_data_keys
        # epoch_ns should have been set already
        # else we need to add it now because the header is now written
        # before data can be added to the file
        if self.file_conn_dict[file_conn_key].params.hloheader.epoch_ns is None:
            self.base.print_message("realtime_ns was not set, adding it now.")
            self.file_conn_dict[
                file_conn_key
            ].params.hloheader.epoch_ns = self.get_realtime_nowait()

        header, file_info = self.init_datafile(
            header=self.file_conn_dict[file_conn_key].params.hloheader.clean_dict(),
            file_type=self.file_conn_dict[file_conn_key].params.file_type,
            json_data_keys=self.file_conn_dict[file_conn_key].params.json_data_keys,
            file_sample_label=self.file_conn_dict[
                file_conn_key
            ].params.sample_global_labels,
            filename=None,  # always autogen a filename
            file_group=self.file_conn_dict[file_conn_key].params.file_group,
            file_conn_key=file_conn_key,
            action=output_action,
        )
        output_action.files.append(file_info)
        filename = file_info.file_name

        output_path = os.path.join(
            self.base.helaodirs.save_root, output_action.action_output_dir
        )
        output_file = os.path.join(output_path, filename)

        if not os.path.exists(output_path):
            os.makedirs(output_path, exist_ok=True)

        self.base.print_message(f"writing data to: {output_file}")
        # create output file and set connection
        self.file_conn_dict[file_conn_key].file = await aiofiles.open(
            output_file, mode="a+"
        )

        if header:
            self.base.print_message("adding header to new file")
            if not header.endswith("\n"):
                header += "\n"
            await self.file_conn_dict[file_conn_key].file.write(header)

    async def log_data_task(self):
        """Self-subscribe to data queue, write to present file path."""
        if not self.action.save_data:
            self.base.print_message("data writing disabled")
            return

        self.base.print_message(
            f"starting data logger for active action: {self.action.action_uuid}",
            info=True,
        )

        try:
            async for data_msg in self.base.data_q.subscribe():
                # check if the new data_msg is in listen_uuids
                if data_msg.action_uuid not in self.listen_uuids:
                    self.base.print_message(
                        f"data logger for "
                        f"active action: "
                        f"{self.action.action_uuid} ; "
                        f"UUID {data_msg.action_uuid} "
                        f"is not in listen_uuids:"
                        f" {self.listen_uuids}",
                        warning=True,
                    )
                    self.base.print_message(f"data_msg: \n{data_msg}", warning=True)

                    continue

                data_status = data_msg.datamodel.status
                data_dict = data_msg.datamodel.data

                self.action.data_stream_status = data_status

                if data_status not in (
                    None,
                    HloStatus.active,
                ):
                    self.base.print_message(
                        f"data_stream: skipping package for status: {data_status}",
                        info=True,
                    )
                    continue

                for file_conn_key, sample_data in data_dict.items():

                    output_action = self._get_action_for_file_conn_key(
                        file_conn_key=file_conn_key
                    )
                    if output_action is None:
                        self.base.print_message(
                            "data logger could not find action for file_conn_key",
                            error=True,
                        )
                        continue

                    if file_conn_key not in self.file_conn_dict:
                        if output_action.save_data:
                            self.base.print_message(
                                f"'{file_conn_key}' does not exist in "
                                "file_conn '{self.file_conn_dict}'.",
                                error=True,
                            )
                        else:
                            # got data but saving is disabled,
                            # e.g. no file was created,
                            # e.g. file_conn_key is not in self.file_conn_dict
                            self.base.print_message(
                                "data logging is disabled for action '{output_action.action_name}'",
                                info=True,
                            )

                        continue

                    # check if we need to create the file first
                    if self.file_conn_dict[file_conn_key].file is None:
                        if not self.file_conn_dict[file_conn_key].params.json_data_keys:
                            jsonkeys = [key for key in sample_data.keys()]
                            self.base.print_message(
                                "no json_data_keys defined, "
                                f"using keys from first "
                                f"data message: "
                                f"{jsonkeys[:10]}",
                                info=True,
                            )

                            self.file_conn_dict[
                                file_conn_key
                            ].params.json_data_keys = jsonkeys

                        self.base.print_message(
                            f"creating output file for {file_conn_key}"
                        )
                        # create the file for this data stream
                        await self.log_data_set_output_file(file_conn_key=file_conn_key)

                    # write only data if the file connection is open
                    if self.file_conn_dict[file_conn_key].file:
                        # check if separator was already written
                        # else add it
                        if not self.file_conn_dict[file_conn_key].added_hlo_separator:
                            self.file_conn_dict[
                                file_conn_key
                            ].added_hlo_separator = True
                            await self.write_live_data(
                                output_str="%%\n",
                                file_conn_key=file_conn_key,
                            )

                        if type(sample_data) is dict:
                            try:
                                output_str = json.dumps(sample_data)
                            except TypeError:
                                self.base.print_message(
                                    "Data is not json serializable.",
                                    error=True,
                                )
                                output_str = "Error: data was not serializable."
                            await self.write_live_data(
                                output_str=output_str,
                                file_conn_key=file_conn_key,
                            )
                        else:
                            await self.write_live_data(
                                output_str=sample_data, file_conn_key=file_conn_key
                            )
                    else:
                        self.base.print_message("output file closed?", error=True)

        # except asyncio.CancelledError:
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            self.base.print_message(
                f"data logger task was cancelled with error: {repr(e), tb,}",
                error=True,
            )

    async def write_file(
        self,
        output_str: str,
        file_type: str,
        filename: Optional[str] = None,
        file_group: Optional[HloFileGroup] = HloFileGroup.aux_files,
        header: Optional[str] = None,
        sample_str: Optional[str] = None,
        file_sample_label: Optional[str] = None,
        json_data_keys: Optional[str] = None,
        action: Optional[Action] = None,
    ):
        """Write complete file, not used with queue streaming."""
        if action is None:
            action = self.action
        if action.save_data:
            header, file_info = self.init_datafile(
                header=header,
                file_type=file_type,
                json_data_keys=json_data_keys,
                file_sample_label=file_sample_label,
                filename=filename,
                file_group=file_group,
            )
            action.files.append(file_info)
            output_path = os.path.join(
                self.base.helaodirs.save_root,
                action.action_output_dir,
            )
            output_file = os.path.join(output_path, file_info.file_name)

            if not os.path.exists(output_path):
                os.makedirs(output_path, exist_ok=True)

            self.base.print_message(f"writing non stream data to: {output_file}")

            async with aiofiles.open(output_file, mode="a+") as f:
                if header:
                    await f.write(header)
                await f.write("%%\n")
                await f.write(output_str)
                return output_file
        else:
            return None

    def write_file_nowait(
        self,
        output_str: str,
        file_type: str,
        filename: Optional[str] = None,
        file_group: Optional[HloFileGroup] = HloFileGroup.aux_files,
        header: Optional[str] = None,
        sample_str: Optional[str] = None,
        file_sample_label: Optional[str] = None,
        json_data_keys: Optional[str] = None,
        action: Optional[Action] = None,
    ):
        """Write complete file, not used with queue streaming."""
        if action is None:
            action = self.action

        if action.save_data:
            header, file_info = self.init_datafile(
                header=header,
                file_type=file_type,
                json_data_keys=json_data_keys,
                file_sample_label=file_sample_label,
                filename=filename,
                file_group=file_group,
            )

            output_path = os.path.join(
                self.base.helaodirs.save_root,
                action.action_output_dir,
            )
            output_file = os.path.join(output_path, file_info.file_name)

            if not os.path.exists(output_path):
                os.makedirs(output_path, exist_ok=True)
            self.base.print_message(f"writing non stream data to: {output_file}")
            with open(output_file, mode="a+") as f:
                if header:
                    f.write(header)
                f.write("%%\n")
                f.write(output_str)
                action.files.append(file_info)
                return output_file
        else:
            return None

    def set_sample_action_uuid(self, sample: SampleUnion, action_uuid: UUID):
        sample.action_uuid = [action_uuid]
        if sample.sample_type == SampleType.assembly:
            for part in sample.parts:
                self.set_sample_action_uuid(sample=part, action_uuid=action_uuid)

    async def append_sample(
        self, samples: List[SampleUnion], IO: str, action: Optional[Action] = None
    ):
        """Add sample to samples_out and samples_in dict"""
        if action is None:
            action = self.action
        # check if samples is empty
        if not samples:
            return

        for sample in samples:

            # skip NoneSamples
            if isinstance(sample, NoneSample):
                continue
            # update action_uuid to current one
            self.set_sample_action_uuid(sample=sample, action_uuid=action.action_uuid)

            if sample.inheritance is None:
                self.base.print_message(
                    "sample.inheritance is None. Using 'allow_both'."
                )
                sample.inheritance = SampleInheritance.allow_both

            if not sample.status:
                self.base.print_message(
                    "sample.status is None. Using '{SampleStatus.preserved}'."
                )
                sample.status = [SampleStatus.preserved]

            if IO == "in":
                if action.samples_in is None:
                    action.samples_in = []
                action.samples_in.append(sample)
            elif IO == "out":
                if action.samples_out is None:
                    action.samples_out
                action.samples_out.append(sample)

        # broadcast status when a sample is added (for operator table update)
        await self.add_status(action=action)

    async def split_and_keep_active(self):
        await self.split(uuid_list=[])

    async def split_and_finish_prev_uuids(self):
        await self.split(uuid_list=None)

    async def finish_all(self):
        await self.finish(finish_uuid_list=None)

    async def split(
        self,
        uuid_list: Optional[List[UUID]] = None,
        new_fileconnparams: Optional[FileConnParams] = None,
    ) -> List[UUID]:
        """splits the current action and
        finishes all previous action in uuid_list
        default uuid_list = None finishes all previous

        returns new file_conn_key
        """

        new_file_conn_keys = []

        self.base.print_message("got split action request", info=True)
        # add split status to current action
        if HloStatus.split not in self.action.action_status:
            self.action.action_status.append(HloStatus.split)
        # make a copy of prev_action
        prev_action = deepcopy(self.action)
        # set the data_stream_status
        prev_action.data_stream_status = HloStatus.split
        self.action.data_stream_status = HloStatus.active
        # increase split counter for new action
        # needs to happen before init_act
        # as its also used in the fodler name
        self.action.action_split += 1

        # now re-init current action
        # force action init (new action uuid and timestamp)
        self.action.init_act(time_offset=self.base.ntp_offset, force=True)
        # add new action uuid to listen_uuids
        self.add_new_listen_uuid(self.action.action_uuid)

        # add child and parent action uuids
        prev_action.child_action_uuid = self.action.action_uuid
        self.action.parent_action_uuid = prev_action.action_uuid

        # reset action sample list and others
        self.action.samples_in = []
        self.action.samples_out = []
        self.action.child_action_uuid = None
        self.action.files = []

        # reset all of the new actions file_conn uuids
        self.action.file_conn_keys = []

        # grab all fileconns from prev_action
        # some action are multi file out and each split action
        # needs to create the same number of new files
        for file_conn_key in prev_action.file_conn_keys:
            # await asyncio.sleep(0.1)
            self.base.print_message(
                "Creating new file_conn for split action", info=True
            )
            new_file_conn_key = self.base.new_file_conn_key(
                key=str(self.get_realtime_nowait())
            )
            if new_fileconnparams is None:
                # get last file conn
                new_file_conn = self.file_conn_dict[file_conn_key].deepcopy()
                # modify last file_conn
                new_file_conn.params.file_conn_key = new_file_conn_key
                # reset some of the file conn parameters
                new_file_conn.reset_file_conn()
                # add new timestamp
                new_file_conn.params.hloheader.epoch_ns = self.get_realtime_nowait()
            else:
                new_file_conn = FileConn(params=new_fileconnparams)
                new_file_conn.params.file_conn_key = new_file_conn_key

            new_file_conn_keys.append(new_file_conn_key)
            # add the new one to active file conn dict
            self.file_conn_dict[new_file_conn.params.file_conn_key] = new_file_conn
            # and add the new file_conn_uuid to the new split action
            self.action.file_conn_keys.append(new_file_conn.params.file_conn_key)

        # TODO:
        # update other action settings?
        # - sample name

        # add prev_action to action_list to 2nd spot
        if len(self.action_list) == 1:
            self.action_list.append(prev_action)
        else:
            self.action_list.insert(1, prev_action)

        # send status for new split action
        await self.add_status()

        # finish selected actions
        if uuid_list is None:
            # default: finish all except current one
            await self.finish(
                finish_uuid_list=[act.action_uuid for act in self.action_list[1:]]
            )

        else:
            # use the supplied uuid list
            await self.finish(finish_uuid_list=uuid_list)

        return new_file_conn_keys

    async def finish(
        self,
        finish_uuid_list: Optional[List[UUID]] = None
        # end_state: HloStatus = HloStatus.finished
    ) -> Action:
        """Close file_conn, finish exp, copy aux,
        set endpoint status, and move active dict to past.
        for action uuids of active defined in finish_uuid_list.
        default None finsihes all
        """

        # default behaviour
        # finishes all
        # and returns the last action (the one in self.action)
        if finish_uuid_list is None:
            finish_uuid_list = [action.action_uuid for action in self.action_list]

        # get the actions of active which should be finished
        # and are not finished yet (no HloStatus.finished status)
        finish_action_list = []
        for finish_uuid in finish_uuid_list:
            await asyncio.sleep(0.1)
            for action in self.action_list:
                if (
                    action.action_uuid == finish_uuid
                    and HloStatus.finished not in action.action_status
                ):
                    finish_action_list.append(action)

        # now finish all the actions in the list
        for finish_action in finish_action_list:

            # set status to finish
            # (replace active with finish)
            self.base.replace_status(
                status_list=finish_action.action_status,
                old_status=HloStatus.active,
                new_status=HloStatus.finished,
            )

            # write final act meta file (overwrite existing one)
            await self.base.write_act(action=finish_action)

            # send the last status
            await self.add_status(action=finish_action)

        # check if all actions are fininshed
        # if yes close datalogger etc
        all_finished = True
        for action in self.action_list:
            if HloStatus.finished not in action.action_status:
                # at least one is not finished
                all_finished = False
                break

        if all_finished:
            self.base.print_message(
                "finish active: sending finish data_stream_status package",
                info=True,
            )
            while not all(
                [
                    action.data_stream_status != HloStatus.active
                    for action in self.action_list
                ]
            ):
                await self.enqueue_data(
                    datamodel=DataModel(data={}, errors=[], status=HloStatus.finished)
                )
                self.base.print_message(
                    f"Waiting for data_stream finished"
                    f" packge: "
                    f" {[action.data_stream_status for action in self.action_list]}",
                    info=True,
                )
                await asyncio.sleep(0.5)

            # self.action_list[-1] is the very first action
            if self.action_list[-1].manual_action:
                await self.finish_manual_action()

            # all actions are finished
            self.base.print_message("finishing data logging.")
            for filekey in self.file_conn_dict:
                if self.file_conn_dict[filekey].file:
                    await self.file_conn_dict[filekey].file.close()
            self.file_conn_dict = {}

            # finish the data writer
            self.data_logger.cancel()
            _ = self.base.actives.pop(self.active_uuid, None)
            self.base.print_message(
                "all active action are done, closing active", info=True
            )

            # DB server call to finish_yml if DB exists
            for action in self.action_list:
                self.base.aloop.create_task(move_dir(action, base=self.base))

        # always returns the most recent action of active
        return self.action

    async def track_file(
        self,
        file_type: str,
        file_path: str,
        samples: List[SampleUnion],
        action: Optional[Action] = None,
    ) -> None:
        "Add auxiliary files to file dictionary."
        if action is None:
            action = self.action
        if os.path.dirname(file_path) != os.path.join(
            self.base.helaodirs.save_root, action.action_output_dir
        ):
            action.AUX_file_paths.append(file_path)

        file_info = FileInfo(
            file_type=file_type,
            file_name=os.path.basename(file_path),
            # data_keys = json_data_keys,
            sample=[sample.get_global_label() for sample in samples],
            # action_uuid: Optional[UUID]
        )

        action.files.append(file_info)
        self.base.print_message(
            f"{file_info.file_name} added to files_technique / aux_files list."
        )

    async def relocate_files(self):
        "Copy auxiliary files from folder path to exp directory."
        for x in self.action.AUX_file_paths:
            new_path = os.path.join(
                self.base.helaodirs.save_root,
                self.action.action_output_dir,
                os.path.basename(x),
            )
            await async_copy(x, new_path)

    async def finish_manual_action(self):
        # self.action_list[-1] is the very first action
        if self.action_list[-1].manual_action:
            exp = deepcopy(self.action_list[-1])
            exp.experiment_status = [HloStatus.finished]
            exp.sequence_status = [HloStatus.finished]
            exp.samples_in = []
            exp.samples_out = []
            exp.files = []

            # add actions to experiment
            for action in self.action_list:
                exp.actionmodel_list.append(action.get_actmodel())

            # add experiment to sequence
            exp.experimentmodel_list.append(action.get_exp())

            # this will write the correct
            # sequence and experiment meta files for
            # manual operation
            # create and write exp file for manual action
            await self.base.write_exp(exp, manual=True)
            # create and write seq file for manual action
            await self.base.write_seq(exp, manual=True)

    async def send_nonblocking_status(self, retry_limit: int = 3):
        for client_servkey in self.base.status_clients:
            self.base.print_message(
                f"executor trying to send non-blocking status to {client_servkey}."
            )
            success = False
            for _ in range(retry_limit):
                response, error_code = await self.base.send_nbstatuspackage(
                    client_servkey=client_servkey,
                    actionmodel=self.action.get_actmodel(),
                )

                if response.get("success", False) and error_code == ErrorCodes.none:
                    success = True
                    break

            if success:
                self.base.print_message(
                    f"Attached {client_servkey} to status ws on {self.base.server.server_name}."
                )
            else:
                self.base.print_message(
                    f"failed to attach {client_servkey} to status ws "
                    f"on {self.base.server.server_name} "
                    f"after {retry_limit} attempts.",
                    error=True,
                )

    async def action_loop_task(self, executor: Executor):
        """Generic replacement for 'IOloop'."""

        if self.action.nonblocking:
            await self.send_nonblocking_status()
        self.base.print_message("action_loop_task started")
        # pre-action operations
        setup_state = await executor._pre_exec()
        setup_error = setup_state.get("error", ErrorCodes.none)
        if setup_error == ErrorCodes.none:
            self.action_loop_running = True
        else:
            self.base.print_message("Error encountered during executor setup.")
            self.action.error_code = setup_error
            return await self.finish()

        # shortcut to active exectuors
        self.base.executors[executor.exid] = self

        # action operations
        result = await executor._exec()
        error = result.get("error", ErrorCodes.none)
        data = result.get("data", {})
        if data:
            datamodel = DataModel(
                data={self.action.file_conn_keys[0]: data},
                errors=[],
                status=HloStatus.active,
            )
            await self.enqueue_data(datamodel)  # write and broadcast

        # polling loop for ongoing action
        if not executor.oneoff:
            self.base.print_message("entering executor polling loop")
            while self.action_loop_running:
                result = await executor._poll()
                error = result.get("error", ErrorCodes.none)
                status = result.get("status", HloStatus.finished)
                data = result.get("data", {})
                if data:
                    datamodel = DataModel(
                        data={self.action.file_conn_keys[0]: data},
                        errors=[],
                        status=HloStatus.active,
                    )
                    await self.enqueue_data(datamodel)  # write and broadcast

                if status == HloStatus.active:
                    await asyncio.sleep(executor.poll_rate)
                else:
                    self.base.print_message("exiting executor polling loop")
                    self.action_loop_running = False

        if error != ErrorCodes.none:
            self.action.error_code = error
        self.action_loop_running = False

        # in case of manual stop, perform driver operations
        if self.manual_stop:
            result = await executor._manual_stop()
            error = result.get("error", {})
            if error != ErrorCodes.none:
                self.base.print_message("Error encountered during manual stop.")

        # post-action operations
        cleanup_state = await executor._post_exec()
        cleanup_error = cleanup_state.get("error", {})
        if cleanup_error != ErrorCodes.none:
            self.base.print_message("Error encountered during executor cleanup.")

        _ = self.base.executors.pop(executor.exid)
        await self.finish()
        if self.action.nonblocking:
            await self.send_nonblocking_status()

    def stop_action_task(self):
        "External method for stopping action_loop_task."
        self.base.print_message("Stop action request received. Stopping poll.")
        self.manual_stop = True
        self.action_loop_running = False


class DummyBase:
    def __init__(self) -> None:
        self.live_buffer = {}
        self.actionservermodel = ActionServerModel(
            action_server=MachineModel(server_name="DUMMY", machine_name="dummyhost"),
            last_action_uuid=uuid1(),
        )

    def print_message(self, message: str) -> None:
        print_message({}, "DUMMY", message)

    async def put_lbuf(self, message: dict) -> None:
        now = time.time()
        for k, v in message:
            self.live_buffer[k] = (v, now)

    async def get_lbuf(self, buf_key: str) -> tuple:
        buf_val, buf_ts = self.live_buffer[buf_key]
        return buf_val, buf_ts
