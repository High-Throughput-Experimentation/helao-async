__all__ = ["Base", "ActiveParams", "Active", "DummyBase"]

import asyncio
import json
import os
import sys
import pickle
import pathlib
from random import randint
from socket import gethostname
from time import ctime, time, time_ns, sleep
from typing import List, Dict, Optional
from uuid import UUID, uuid1
import hashlib
from copy import deepcopy, copy
import inspect
import traceback
from queue import Queue

import aiodebug.hang_inspection
import aiodebug.log_slow_callbacks
import aiofiles
import colorama
import ntplib
import numpy as np
import pyzstd

from filelock import FileLock
from fastapi import WebSocket
from fastapi.dependencies.utils import get_flat_params

from helao.helpers.dispatcher import async_private_dispatcher, async_action_dispatcher
from helao.helpers.executor import Executor
from helao.helpers.helao_dirs import helao_dirs
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.print_message import print_message
from helao.helpers import async_copy
from helao.helpers.yml_tools import yml_dumps
from helao.helpers.yml_finisher import move_dir
from helao.helpers.premodels import Action
from helaocore.models.action_start_condition import ActionStartCondition as ASC
from helao.helpers.ws_publisher import WsPublisher
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
from helaocore.version import get_filehash
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

    # TODO: add world_cfg: dict parameter for BaseAPI to pass config instead of fastapp
    def __init__(self, fastapp, dyn_endpoints=None):
        self.server = MachineModel(
            server_name=fastapp.helao_srv, machine_name=gethostname().lower()
        )

        self.fastapp = fastapp
        self.dyn_endpoints = dyn_endpoints
        self.server_cfg = self.fastapp.helao_cfg["servers"][self.server.server_name]
        self.server_params = self.fastapp.helao_cfg["servers"][
            self.server.server_name
        ].get("params", {})
        self.server.hostname = self.server_cfg["host"]
        self.server.port = self.server_cfg["port"]
        self.world_cfg = self.fastapp.helao_cfg
        orch_keys = [
            k
            for k, d in self.world_cfg.get("servers", {}).items()
            if d["group"] == "orchestrator"
        ]
        if orch_keys:
            self.orch_key = orch_keys[0]
            self.orch_host = self.world_cfg["servers"][self.orch_key]["host"]
            self.orch_port = self.world_cfg["servers"][self.orch_key]["port"]
        else:
            self.orch_key = None
            self.orch_host = None
            self.orch_port = None
        self.run_type = None

        self.helaodirs = helao_dirs(self.world_cfg, self.server.server_name)

        if self.helaodirs.root is None:
            raise ValueError(
                "Warning: root directory was not defined. Logs, PRCs, PRGs, and data will not be written.",
            )

        if "run_type" in self.world_cfg:
            self.print_message(
                f"Found run_type in config: {self.world_cfg['run_type']}",
            )
            self.run_type = self.world_cfg["run_type"].lower()
        else:
            raise ValueError(
                "Missing 'run_type' in config, cannot create server object.",
            )

        self.actives: Dict[UUID, object] = {}
        self.last_10_active = []
        self.executors = {}  # shortcut to running Executors
        # basemodel to describe the full action server
        self.actionservermodel = ActionServerModel(action_server=self.server)
        self.actionservermodel.init_endpoints()

        self.status_q = MultisubscriberQueue()
        self.data_q = MultisubscriberQueue()
        self.live_q = MultisubscriberQueue()
        self.live_buffer = {}
        self.status_clients = set()

        self.status_publisher = WsPublisher(self.status_q)
        self.data_publisher = WsPublisher(self.data_q)
        self.live_publisher = WsPublisher(self.live_q)

        self.ntp_server = "time.nist.gov"
        self.ntp_response = None
        self.ntp_offset = None  # add to system time for correction
        self.ntp_last_sync = None
        self.aiolock = asyncio.Lock()
        self.endpoint_queues = {}
        self.fast_urls = []

        self.ntp_last_sync_file = None
        if self.helaodirs.root is not None:
            self.ntp_last_sync_file = os.path.join(
                self.helaodirs.states_root, "ntpLastSync.txt"
            )
            self.ntplockpath = str(self.ntp_last_sync_file) + ".lock"
            self.ntplock = FileLock(self.ntplockpath)
            if not os.path.exists(self.ntplockpath):
                os.makedirs(os.path.dirname(self.ntplockpath), exist_ok=True)
                with open(self.ntplockpath, "w") as _:
                    pass
            if os.path.exists(self.ntp_last_sync_file):
                with self.ntplock:
                    with open(self.ntp_last_sync_file, "r") as f:
                        tmps = f.readline().strip().split(",")
                        if len(tmps) == 2:
                            self.ntp_last_sync, self.ntp_offset = tmps
                            self.ntp_offset = float(self.ntp_offset)

    def exception_handler(self, loop, context):
        self.print_message(f"Got exception from coroutine: {context}", error=True)
        exc = context.get("exception")
        self.print_message(
            f"{traceback.format_exception(type(exc), exc, exc.__traceback__)}", error=True
        )
        self.print_message("setting E-STOP flag on active actions")
        for _, active in self.actives.items():
            active.set_estop()
            

    def myinit(self):
        self.aloop = asyncio.get_running_loop()
        # produce warnings on coroutines taking longer than interval
        aiodebug.log_slow_callbacks.enable(30.0)
        # dump coroutine stack traces when event loop hangs for longer than interval
        self.dumper = aiodebug.hang_inspection.start(os.path.join(self.helaodirs.root, "FAULTS"), interval=5.0)
        self.dumper_task = self.aloop.create_task(aiodebug.hang_inspection.stop_wait(self.dumper))
        self.aloop.set_exception_handler(self.exception_handler)
        if self.ntp_last_sync is None:
            asyncio.gather(self.get_ntp_time())

        self.sync_ntp_task_run = False
        self.ntp_syncer = self.aloop.create_task(self.sync_ntp_task())
        self.bufferer = self.aloop.create_task(self.live_buffer_task())

        self.status_logger = self.aloop.create_task(self.log_status_task())

    def dyn_endpoints_init(self):
        asyncio.gather(self.init_endpoint_status(self.dyn_endpoints))

    def endpoint_queues_init(self):
        for urld in self.fast_urls:
            if urld.get("path", "").strip("/").startswith(self.server.server_name):
                endpoint_name = urld["path"].strip("/").split("/")[-1]
                self.endpoint_queues[endpoint_name] = Queue()

    def print_message(self, *args, **kwargs):
        print_message(
            self.server_cfg,
            self.server.server_name,
            log_dir=self.helaodirs.log_root,
            *args,
            **kwargs,
        )

    # TODO: add app: FastAPI parameter for BaseAPI to pass app
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
                self.actionservermodel.endpoints[route.name].sort_status()
        self.print_message(
            f"Found {len(self.actionservermodel.endpoints.keys())} endpoints "
            f"for status monitoring on {self.server.server_name}."
        )
        self.fast_urls = self.get_endpoint_urls()
        self.endpoint_queues_init()

    def get_endpoint_urls(self):
        """Return a list of all endpoints on this server."""
        url_list = []
        for route in self.fastapp.routes:
            routeD = {"path": route.path, "name": route.name}
            if "dependant" in dir(route):
                flatParams = get_flat_params(route.dependant)
                paramD = {
                    par.name: {
                        "outer_type": str(par.field_info.annotation).split("'")[1]
                        if len(str(par.field_info.annotation).split("'")) >= 2
                        else str(par.field_info.annotation),
                        "type": str(par.type_).split("'")[1]
                        if len(str(par.type_).split("'")) >= 2
                        else str(par.type_),
                        "required": par.required,
                        # "shape": par.shape,
                        "default": par.default if par.default is not ... else None,
                    }
                    for par in flatParams
                }
                routeD["params"] = paramD
            else:
                routeD["params"] = []
            url_list.append(routeD)
        return url_list

    def _get_action(self, frame) -> Action:
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
        # self.print_message(
        #     f"this code's filename was: {sys._getframe(0).f_code.co_filename}"
        # )
        # self.print_message(
        #     f"caller's filename was: {sys._getframe(1).f_code.co_filename}"
        # )
        # self.print_message(
        #     f"callercaller's filename was: {sys._getframe(2).f_code.co_filename}"
        # )
        # TODO: build calname: urlname dict mapping during init_endpoint_status
        # fastapi url for caller function
        urlname = self.fastapp.url_path_for(calname)

        # action name should be the last one
        action_name = urlname.strip("/").split("/")[-1]
        # use the already known server_key, not the one from the url
        server_key = self.server.server_name

        action.action_server = MachineModel(
            server_name=server_key, machine_name=gethostname().lower()
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
                server_name="MANUAL", machine_name=gethostname().lower()
            )
        action.action_codehash = get_filehash(sys._getframe(2).f_code.co_filename)
        return action

    def setup_action(self) -> Action:
        return self._get_action(frame=inspect.currentframe().f_back)

    async def setup_and_contain_action(
        self,
        json_data_keys: List[str] = [],
        action_abbr: str = None,
        file_type: str = "helao__file",
        hloheader: HloHeaderModel = HloHeaderModel(),
    ):
        """This is a simple shortcut for very basic endpoints
        which just want to return some simple data"""
        action = self._get_action(frame=inspect.currentframe().f_back)
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

    async def contain_action(self, activeparams: ActiveParams):
        """return an active Action:
        file_type: type of output data file
        json_data_keys: data keys for json encoded data (dict)
        file_sample_label: list of sample labels
        file_conn_keys:
        header: header for data file
        """
        if activeparams.action.action_uuid in self.actives:
            await self.actives[activeparams.action.action_uuid].substitute()
        self.actives[activeparams.action.action_uuid] = Active(
            self, activeparams=activeparams
        )
        await self.actives[activeparams.action.action_uuid].myinit()
        l10 = copy(self.actives[activeparams.action.action_uuid])
        if len(self.last_10_active) == 10:
            _ = self.last_10_active.pop(0)
        self.last_10_active.append((l10.action.action_uuid, l10))
        return self.actives[activeparams.action.action_uuid]

    def get_active_info(self, action_uuid: UUID):
        if action_uuid in self.actives:
            action_dict = self.actives[action_uuid].action.as_dict()
            return action_dict
        else:
            self.print_message(
                f"Specified action uuid {str(action_uuid)} was not found.", error=True
            )
            return None

    async def get_ntp_time(self):
        """Check system clock against NIST clock for trigger operations."""
        with self.ntplock:
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
                self.print_message(f"{self.ntp_server} ntp timeout", info=True)
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
        client_host: str,
        client_port: int,
        action_name: str = None,
    ):
        # needs private dispatcher
        json_dict = {
            "actionservermodel": self.actionservermodel.get_fastapi_json(
                action_name=action_name
            )
        }
        response, error_code = await async_private_dispatcher(
            server_key=client_servkey,
            host=client_host,
            port=client_port,
            private_action="update_status",
            params_dict={},
            json_dict=json_dict,
        )
        return response, error_code

    async def send_nbstatuspackage(
        self,
        client_servkey: str,
        client_host: str,
        client_port: int,
        actionmodel: ActionModel,
    ):
        # needs private dispatcher
        json_dict = {
            "actionmodel": actionmodel.as_dict(),
        }
        params_dict = {
            "server_host": self.server_cfg["host"],
            "server_port": self.server_cfg["port"],
        }
        self.print_message(f"sending non-blocking status: {json_dict}")
        response, error_code = await async_private_dispatcher(
            server_key=client_servkey,
            host=client_host,
            port=client_port,
            private_action="update_nonblocking",
            params_dict=params_dict,
            json_dict=json_dict,
        )
        self.print_message(f"update_nonblocking request got response: {response}")
        return response, error_code

    async def attach_client(
        self, client_servkey: str, client_host: str, client_port: int, retry_limit=5
    ):
        """Add client for pushing status updates via HTTP POST."""
        success = False
        combo_key = (
            client_servkey,
            client_host,
            client_port,
        )
        self.print_message("attaching status subscriber", combo_key)

        if combo_key in self.status_clients:
            self.print_message(
                f"Client {combo_key} is already subscribed to "
                f"{self.server.server_name} status updates."
            )
            # self.detach_client(client_servkey, client_host, client_port)  # refresh
        self.status_clients.add(combo_key)

        # sends current status of all endpoints (action_name = None)
        for _ in range(retry_limit):
            response, error_code = await self.send_statuspackage(
                client_servkey=client_servkey,
                client_host=client_host,
                client_port=client_port,
                action_name=None,
            )
            if response is not None and error_code == ErrorCodes.none:
                self.print_message(
                    f"Added {combo_key} to {self.server.server_name} status subscriber list."
                )
                success = True
                break
            else:
                self.print_message(
                    f"Failed to add {combo_key} to "
                    f"{self.server.server_name} status subscriber list.",
                    error=True,
                )

            if success:
                self.print_message(
                    f"Attached {combo_key} to status ws on {self.server.server_name}."
                )
            else:
                self.print_message(
                    f"failed to attach {combo_key} to status ws "
                    f"on {self.server.server_name} "
                    f"after {retry_limit} attempts.",
                    error=True,
                )

        return success

    def detach_client(self, client_servkey: str, client_host: str, client_port: int):
        """Remove client from receiving status updates via HTTP POST"""
        combo_key = (
            client_servkey,
            client_host,
            client_port,
        )
        if combo_key in self.status_clients:
            self.status_clients.remove(combo_key)
            self.print_message(
                f"Client {combo_key} will no longer receive status updates."
            )
        else:
            self.print_message(f"Client {combo_key} is not subscribed.")

    async def ws_status(self, websocket: WebSocket):
        "Subscribe to status queue and send message to websocket client."
        self.print_message("got new status subscriber")
        await websocket.accept()
        status_sub = self.status_q.subscribe()
        try:
            async for status_msg in status_sub:
                await websocket.send_bytes(
                    pyzstd.compress(pickle.dumps(status_msg.as_dict()))
                )
        # except WebSocketDisconnect:
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            self.print_message(
                f"Status websocket client {websocket.client[0]}:{websocket.client[1]} disconnected. {repr(e), tb,}",
                error=True,
            )
            if status_sub in self.status_q.subscribers:
                self.status_q.remove(status_sub)

    async def ws_data(self, websocket: WebSocket):
        """Subscribe to data queue and send messages to websocket client."""
        self.print_message("got new data subscriber")
        await websocket.accept()
        data_sub = self.data_q.subscribe()
        try:
            async for data_msg in data_sub:
                await websocket.send_bytes(
                    pyzstd.compress(pickle.dumps(data_msg.as_dict()))
                )
        # except WebSocketDisconnect:
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            self.print_message(
                f"Data websocket client {websocket.client[0]}:{websocket.client[1]} disconnected. {repr(e), tb,}",
                error=True,
            )
            if data_sub in self.data_q.subscribers:
                self.data_q.remove(data_sub)

    async def ws_live(self, websocket: WebSocket):
        """Subscribe to data queue and send messages to websocket client."""
        self.print_message("got new live_buffer subscriber")
        await websocket.accept()
        live_sub = self.live_q.subscribe()
        try:
            async for live_msg in live_sub:
                await websocket.send_bytes(pyzstd.compress(pickle.dumps(live_msg)))
        # except WebSocketDisconnect:
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            self.print_message(
                f"Data websocket client {websocket.client[0]}:{websocket.client[1]} disconnected. {repr(e), tb,}",
                error=True,
            )
            if live_sub in self.live_q.subscribers:
                self.live_q.remove(live_sub)

    async def live_buffer_task(self):
        """Self-subscribe to live_q, update live_buffer dict."""
        self.print_message(f"{self.server.server_name} live buffer task created.")
        async for live_msg in self.live_q.subscribe():
            self.live_buffer.update(live_msg)

    async def put_lbuf(self, live_dict):
        """Convert dict values to tuples of (val, timestamp), enqueue to live_q."""
        new_dict = {k: (v, time()) for k, v in live_dict.items()}
        await self.live_q.put(new_dict)

    def put_lbuf_nowait(self, live_dict):
        """Convert dict values to tuples of (val, timestamp), enqueue to live_q."""
        new_dict = {k: (v, time()) for k, v in live_dict.items()}
        self.live_q.put_nowait(new_dict)

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
                if len(self.status_clients)==0 and self.orch_key is not None:
                    await self.attach_client(self.orch_key, self.orch_host, self.orch_port)
                    
                for combo_key in self.status_clients.copy():
                    client_servkey, client_host, client_port = combo_key
                    self.print_message(
                        f"log_status_task trying to send status to {client_servkey}."
                    )
                    success = False
                    for _ in range(retry_limit):
                        response, error_code = await self.send_statuspackage(
                            action_name=status_msg.action_name,
                            client_servkey=client_servkey,
                            client_host=client_host,
                            client_port=client_port,
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
                    sleep(0.3)
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

    async def get_realtime(self, epoch_ns: float = None, offset: float = None) -> float:
        """returns epoch in ns"""
        return self.get_realtime_nowait(epoch_ns=epoch_ns, offset=offset)

    def get_realtime_nowait(
        self, epoch_ns: float = None, offset: float = None
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
                    await asyncio.sleep(randint(5, 10))
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

            output_dict = {"file_type": "action"}
            output_dict.update(act_dict)
            async with aiofiles.open(output_file, mode="w+") as f:
                await f.write(yml_dumps(output_dict))
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
        output_dict = {"file_type": "experiment"}
        output_dict.update(exp_dict)
        output_str = yml_dumps(output_dict)
        if not output_str.endswith("\n"):
            output_str += "\n"

        if not os.path.exists(output_path):
            os.makedirs(output_path, exist_ok=True)

        async with aiofiles.open(output_file, mode="w+") as f:
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
        output_dict = {"file_type": "sequence"}
        output_dict.update(seq_dict)
        output_str = yml_dumps(output_dict)
        if not output_str.endswith("\n"):
            output_str += "\n"

        if not os.path.exists(output_path):
            os.makedirs(output_path, exist_ok=True)

        async with aiofiles.open(output_file, mode="w+") as f:
            await f.write(output_str)

    async def append_exp_to_seq(self, exp, seq):
        append_dict = {
            "experiment_uuid": str(exp.experiment_uuid),
            "experiment_name": exp.experiment_name,
            "experiment_output_dir": str(exp.experiment_output_dir),
        }
        append_str = (
            "\n".join(["  " + x for x in yml_dumps([append_dict]).split("\n")][:-1])
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
            self.print_message(f"Current executors are: {self.executors.keys()}")
            return {"signal_stop": False}

    def stop_all_executor_prefix(self, action_name: str, match_vars: dict = {}):
        matching_execs = [k for k in self.executors if k.startswith(action_name)]
        if match_vars:
            matching_execs = [
                ek
                for ek, ex in self.executors.items()
                if any([vars(ex).get(vk, "") == vv for vk, vv in match_vars.items()])
                and ek in matching_execs
            ]
        for exec_key in matching_execs:
            self.stop_executor(exec_key)


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
        self.num_data_queued = 0
        self.num_data_written = 0

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


        self.manual_stop = False
        self.action_loop_running = False
        self.action_task = None

    def executor_done_callback(self, futr):
        try:
            _ = futr.result()
        except Exception as exc:
            self.base.print_message(
                f"{traceback.format_exception(type(exc), exc, exc.__traceback__)}"
            )

    def start_executor(self, executor: Executor):
        self.action_task = self.base.aloop.create_task(self.action_loop_task(executor))
        self.action_task.add_done_callback(self.executor_done_callback)
        self.base.print_message("Executor task started.")
        return self.action.as_dict()

    async def update_act_file(self):
        await self.base.write_act(self.action)

    async def myinit(self):
        self.data_logger = self.base.aloop.create_task(self.log_data_task())
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
        file_conn_key: str = None,
        action: Action = None,
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
                header = yml_dumps(header)
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
            action_uuid=action.action_uuid,
            run_use=action.run_use,
        )

        if header:
            if not header.endswith("\n"):
                header += "\n"

        return header, file_info

    def finish_hlo_header(
        self,
        file_conn_keys: List[UUID] = None,
        realtime: float = None,
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

    def set_estop(self, action: Action = None):
        if action is None:
            action = self.action
        action.action_status.append(HloStatus.estopped)
        self.base.print_message(
            f"E-STOP {str(action.action_uuid)} on {action.action_name} status.",
            error=True,
        )

    async def set_error(
        self,
        error_code: ErrorCodes = None,
        action: Action = None,
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

    async def get_realtime(self, epoch_ns: float = None, offset: float = None) -> float:
        return self.base.get_realtime_nowait(epoch_ns=epoch_ns, offset=offset)

    def get_realtime_nowait(
        self, epoch_ns: float = None, offset: float = None
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
            datamodel=DataModel(
                data={self.base.dflt_file_conn_key(): datadict},
                errors=[],
                status=HloStatus.active,
            )
        )

    async def enqueue_data(self, datamodel: DataModel, action: Action = None):
        if action is None:
            action = self.action
        await self.base.data_q.put(
            self.assemble_data_msg(datamodel=datamodel, action=action)
        )
        if datamodel.data:
            self.num_data_queued += 1

    def enqueue_data_nowait(self, datamodel: DataModel, action: Action = None):
        if action is None:
            action = self.action
        self.base.data_q.put_nowait(
            self.assemble_data_msg(datamodel=datamodel, action=action)
        )
        if datamodel.data:
            self.num_data_queued += 1

    def assemble_data_msg(
        self, datamodel: DataModel, action: Action = None
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

        # self.base.print_message(
        #     f"starting data logger for active action: {self.action.action_uuid}",
        #     info=True,
        # )

        dq_sub = self.base.data_q.subscribe()

        try:
            async for data_msg in dq_sub:
                # check if the new data_msg is in listen_uuids
                if data_msg.action_uuid not in self.listen_uuids:
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

                        if isinstance(sample_data, dict):
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
                if data_dict:
                    self.num_data_written += 1

        except asyncio.CancelledError:
            self.base.print_message("removing data_q subscription for active", info=True)
            if dq_sub in self.base.data_q.subscribers:
                self.base.data_q.remove(dq_sub)
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            self.base.print_message(
                f"data logger task failed with error: {repr(e), tb,}",
                error=True,
            )

    async def write_file(
        self,
        output_str: str,
        file_type: str,
        filename: str = None,
        file_group: HloFileGroup = HloFileGroup.aux_files,
        header: str = None,
        sample_str: str = None,
        file_sample_label: str = None,
        json_data_keys: str = None,
        action: Action = None,
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
            if os.name == "nt":
                output_file = str(pathlib.PureWindowsPath(output_file))
            elif os.name == "posix":
                output_file = str(
                    pathlib.PurePosixPath(pathlib.PureWindowsPath(output_file))
                ).strip("\\")
            else:
                self.base.print_message("could not detect OS, path seps may be mixed")

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
        filename: str = None,
        file_group: HloFileGroup = HloFileGroup.aux_files,
        header: str = None,
        sample_str: str = None,
        file_sample_label: str = None,
        json_data_keys: str = None,
        action: Action = None,
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
            if os.name == "nt":
                output_file = str(pathlib.PureWindowsPath(output_file))
            elif os.name == "posix":
                output_file = str(
                    pathlib.PurePosixPath(pathlib.PureWindowsPath(output_file))
                ).strip("\\")
            else:
                self.base.print_message("could not detect OS, path seps may be mixed")

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
        self, samples: List[SampleUnion], IO: str, action: Action = None
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
        self.action_list = [self.action]
        # add new action uuid to listen_uuids
        self.add_new_listen_uuid(self.action.action_uuid)
        # remove previous listen_uuid to stop writing to previous hlo file
        self.listen_uuids.remove(prev_action.action_uuid)

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
            self.action.file_conn_keys = [new_file_conn.params.file_conn_key] + self.action.file_conn_keys
            self.num_data_queued = 0
            self.num_data_written = 0


        # TODO:
        # update other action settings?
        # - sample name

        # prepend new action to previous action list
        self.action_list.append(prev_action)

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

    async def substitute(self):
        for filekey in self.file_conn_dict:
            if self.file_conn_dict[filekey].file:
                await self.file_conn_dict[filekey].file.close()

    async def finish(
        self,
        finish_uuid_list: List[UUID] = None
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

            # send globalparams
            if finish_action.to_globalexp_params:
                export_params = {
                    k: finish_action.action_params[k]
                    for k in finish_action.to_globalexp_params
                }
                _, error_code = await async_private_dispatcher(
                    server_key=finish_action.orch_key,
                    host=finish_action.orch_host,
                    port=finish_action.orch_port,
                    private_action="update_globalexp_params",
                    json_dict=export_params,
                )
                if error_code == ErrorCodes.none:
                    self.base.print_message("Successfully updated globalexp params.")

            if finish_action.to_globalseq_params:
                pass

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
            retry_counter = 0
            while (
                not all(
                    [
                        action.data_stream_status != HloStatus.active
                        for action in self.action_list
                    ]
                )
                and retry_counter < 5
            ):
                await self.enqueue_data(
                    datamodel=DataModel(data={}, errors=[], status=HloStatus.finished)
                )
                self.base.print_message(
                    f"Waiting for data_stream finished"
                    f" package: "
                    f" {[action.data_stream_status for action in self.action_list]}",
                    info=True,
                )
                await asyncio.sleep(0.1)
                retry_counter += 1

            self.base.print_message("checking if all queued data has written.")
            write_retries = 5
            write_iter = 0
            while self.num_data_queued > self.num_data_written and write_iter < write_retries:
                self.base.print_message(f"num_queued {self.num_data_queued} > num_written {self.num_data_written}, sleeping for 0.1 second.")
                for action in self.action_list:
                    if action.data_stream_status != HloStatus.active:
                        await self.enqueue_data(
                            datamodel=DataModel(
                                data={}, errors=[], status=HloStatus.finished
                            )
                        )
                        self.base.print_message(
                            f"Setting datastream to finished:"
                            f" {action.data_stream_status}",
                            info=True,
                        )
                write_iter += 1
                asyncio.sleep(0.1)

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
            l10 = self.base.actives.pop(self.active_uuid, None)
            if l10 is not None:
                i10 = [
                    i
                    for i, (x, _) in enumerate(self.base.last_10_active)
                    if x == self.active_uuid
                ]
                if i10:
                    self.base.last_10_active.pop(i10[0])
                if len(self.base.last_10_active) > 10:
                    self.base.last_10_active.pop(0)
                self.base.last_10_active.append((l10.action.action_uuid, l10))

            self.base.print_message(
                "all active action are done, closing active", info=True
            )

            # DB server call to finish_yml if DB exists
            for action in self.action_list:
                # write final act meta file (overwrite existing one)
                await self.base.write_act(action=action)
                # send the last status
                await self.add_status(action=action)
                self.base.aloop.create_task(move_dir(action, base=self.base))

            # since all sub-actions of active are finished process endpoint queue
            if self.base.endpoint_queues[action.action_name].qsize() > 0:
                self.base.print_message(f"{action.action_name} was previously queued")
                qact, qpars = self.base.endpoint_queues[action.action_name].get()
                self.base.print_message(f"running queued {action.action_name}")
                qact.start_condition = ASC.no_wait
                await async_action_dispatcher(self.base.world_cfg, qact, qpars)

        # always returns the most recent action of active
        return self.action

    async def track_file(
        self,
        file_type: str,
        file_path: str,
        samples: List[SampleUnion],
        action: Action = None,
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
            action_uuid=action.action_uuid,
            run_use=action.run_use,
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
            if x != new_path:
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
        for combo_key in self.base.status_clients:
            client_servkey, client_host, client_port = combo_key
            self.base.print_message(
                f"executor trying to send non-blocking status to {client_servkey}."
            )
            success = False
            for _ in range(retry_limit):
                response, error_code = await self.base.send_nbstatuspackage(
                    client_servkey=client_servkey,
                    client_host=client_host,
                    client_port=client_port,
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
        self.base.print_message(
            f"Registering exec_id: '{executor.exec_id}' with server"
        )
        self.base.executors[executor.exec_id] = self

        # action operations
        self.base.print_message("Running executor._exec() method")
        result = await executor._exec()
        error = result.get("error", ErrorCodes.none)
        data = result.get("data", {})
        if data:
            datamodel = DataModel(
                data={self.action.file_conn_keys[0]: data},
                errors=[],
                status=HloStatus.active,
            )
            self.enqueue_data_nowait(datamodel)  # write and broadcast

        # polling loop for ongoing action
        if not executor.oneoff:
            self.base.print_message("entering executor polling loop")
            while self.action_loop_running:
                result = await executor._poll()
                # self.base.print_message(f"got result: {result}")
                error = result.get("error", ErrorCodes.none)
                status = result.get("status", HloStatus.finished)
                data = result.get("data", {})
                if data:
                    # self.base.print_message(f"got data from poll iter: {data}")
                    datamodel = DataModel(
                        data={self.action.file_conn_keys[0]: data},
                        errors=[],
                        status=HloStatus.active,
                    )
                    self.enqueue_data_nowait(datamodel)  # write and broadcast

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
        data = cleanup_state.get("data", {})
        if data:
            datamodel = DataModel(
                data={self.action.file_conn_keys[0]: data},
                errors=[],
                status=HloStatus.active,  # must be active for data writer to write
            )
            self.enqueue_data_nowait(datamodel)  # write and broadcast
        if cleanup_error != ErrorCodes.none:
            self.base.print_message("Error encountered during executor cleanup.")

        _ = self.base.executors.pop(executor.exec_id)
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

    def get_lbuf(self, buf_key: str) -> tuple:
        buf_val, buf_ts = self.live_buffer[buf_key]
        return buf_val, buf_ts
