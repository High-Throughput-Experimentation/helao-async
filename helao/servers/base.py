__all__ = ["Base", "ActiveParams", "Active", "DummyBase"]

from helao.helpers import helao_logging as logging

if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER

from importlib.util import spec_from_file_location
from importlib.util import module_from_spec
from importlib.machinery import SourceFileLoader

import asyncio
import json
import os
import sys
import pickle
import pathlib
from random import randint
from socket import gethostname
from time import ctime, time, time_ns, sleep
from typing import List, Dict, Optional, Union
from uuid import UUID, uuid1
import hashlib
from copy import deepcopy, copy
import inspect
import traceback

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

from helao.helpers.server_api import HelaoFastAPI
from helao.helpers.dispatcher import async_private_dispatcher, async_action_dispatcher
from helao.helpers.executor import Executor
from helao.helpers.helao_dirs import helao_dirs
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.print_message import print_message
from helao.helpers import async_copy
from helao.helpers.yml_tools import yml_dumps
from helao.helpers.yml_finisher import move_dir
from helao.helpers.premodels import Action, Experiment, Sequence
from helao.core.models.action_start_condition import ActionStartCondition as ASC
from helao.helpers.ws_publisher import WsPublisher
from helao.core.models.hlostatus import HloStatus
from helao.core.models.sample import (
    SampleType,
    AssemblySample,
    LiquidSample,
    GasSample,
    SolidSample,
    NoneSample,
    SampleInheritance,
    SampleStatus,
    object_to_sample,
)
from helao.core.models.action import ActionModel
from helao.core.models.data import DataModel, DataPackageModel
from helao.core.models.machine import MachineModel
from helao.core.models.server import ActionServerModel, EndpointModel
from helao.core.version import get_filehash
from helao.helpers.active_params import ActiveParams
from helao.helpers.zdeque import zdeque
from helao.core.models.file import (
    FileConn,
    FileConnParams,
    HloFileGroup,
    FileInfo,
    HloHeaderModel,
)
from helao.helpers.file_in_use import file_in_use
from helao.core.error import ErrorCodes
from helao.helpers import config_loader
CONFIG = config_loader.CONFIG

# ANSI color codes converted to the Windows versions
# strip colors if stdout is redirected
colorama.init(strip=not sys.stdout.isatty())


class Base:
    """
    Base class for managing server configurations, endpoints, and actions.

    Attributes:
        server (MachineModel): The server machine model.
        app (FastAPI): The FastAPI application instance.
        dyn_endpoints (callable, optional): Dynamic endpoints initializer.
        server_cfg (dict): Server configuration.
        server_params (dict): Server parameters.
        world_cfg (dict): Global configuration.
        orch_key (str, optional): Orchestrator key.
        orch_host (str, optional): Orchestrator host.
        orch_port (int, optional): Orchestrator port.
        run_type (str, optional): Run type.
        helaodirs (HelaoDirs): Directory paths for Helao.
        actives (Dict[UUID, object]): Active actions.
        last_10_active (list): Last 10 active actions.
        executors (dict): Running executors.
        actionservermodel (ActionServerModel): Action server model.
        status_q (MultisubscriberQueue): Status queue.
        data_q (MultisubscriberQueue): Data queue.
        live_q (MultisubscriberQueue): Live queue.
        live_buffer (dict): Live buffer.
        status_clients (set): Status clients.
        local_action_task_queue (list): Local action task queue.
        status_publisher (WsPublisher): Status WebSocket publisher.
        data_publisher (WsPublisher): Data WebSocket publisher.
        live_publisher (WsPublisher): Live WebSocket publisher.
        ntp_server (str): NTP server.
        ntp_response (NTPResponse, optional): NTP response.
        ntp_offset (float, optional): NTP offset.
        ntp_last_sync (float, optional): Last NTP sync time.
        aiolock (asyncio.Lock): Asyncio lock.
        endpoint_queues (dict): Endpoint queues.
        local_action_queue (deque): Local action queue.
        fast_urls (list): FastAPI URLs.
        ntp_last_sync_file (str, optional): NTP last sync file path.
        ntplockpath (str, optional): NTP lock file path.
        ntplock (FileLock, optional): NTP file lock.
        aloop (asyncio.AbstractEventLoop, optional): Asyncio event loop.
        dumper (aiodebug.hang_inspection.HangInspector, optional): Hang inspector.
        dumper_task (asyncio.Task, optional): Hang inspector task.
        sync_ntp_task_run (bool): NTP sync task running flag.
        ntp_syncer (asyncio.Task, optional): NTP sync task.
        bufferer (asyncio.Task, optional): Live buffer task.
        status_logger (asyncio.Task, optional): Status logger task.

    Methods:
        __init__(self, app, dyn_endpoints=None): Initialize the Base class.
        exception_handler(self, loop, context): Handle exceptions in the event loop.
        myinit(self): Initialize the event loop and tasks.
        dyn_endpoints_init(self): Initialize dynamic endpoints.
        endpoint_queues_init(self): Initialize endpoint queues.
        print_message(self, *args, **kwargs): Print a message with server context.
        init_endpoint_status(self, dyn_endpoints=None): Initialize endpoint status.
        get_endpoint_urls(self): Get a list of all endpoints on this server.
        _get_action(self, frame) -> Action: Get the action from the current frame.
        setup_action(self) -> Action: Setup an action.
        setup_and_contain_action(self, json_data_keys: List[str], action_abbr: str, file_type: str, hloheader: HloHeaderModel): Setup and contain an action.
        contain_action(self, activeparams: ActiveParams): Contain an action.
        get_active_info(self, action_uuid: UUID): Get active action information.
        get_ntp_time(self): Get the current time from the NTP server.
        send_statuspackage(self, client_servkey: str, client_host: str, client_port: int, action_name: Optional[str] = None): Send a status package to a client.
        send_nbstatuspackage(self, client_servkey: str, client_host: str, client_port: int, actionmodel: Action): Send a non-blocking status package to a client.
        attach_client(self, client_servkey: str, client_host: str, client_port: int, retry_limit=5): Attach a client for status updates.
        detach_client(self, client_servkey: str, client_host: str, client_port: int): Detach a client from status updates.
        ws_status(self, websocket: WebSocket): Handle WebSocket status subscriptions.
        ws_data(self, websocket: WebSocket): Handle WebSocket data subscriptions.
        ws_live(self, websocket: WebSocket): Handle WebSocket live subscriptions.
        live_buffer_task(self): Task to update the live buffer.
        put_lbuf(self, live_dict): Put data into the live buffer.
        put_lbuf_nowait(self, live_dict): Put data into the live buffer without waiting.
        get_lbuf(self, live_key): Get data from the live buffer.
        log_status_task(self, retry_limit: int = 5): Task to log status changes and send updates to clients.
        detach_subscribers(self): Detach all subscribers.
        get_realtime(self, epoch_ns: Optional[float] = None, offset: Optional[float] = None) -> float: Get the current real-time.
        get_realtime_nowait(self, epoch_ns: Optional[float] = None, offset: Optional[float] = None) -> float: Get the current real-time without waiting.
        sync_ntp_task(self, resync_time: int = 1800): Task to regularly sync with the NTP server.
        shutdown(self): Shutdown the server and tasks.
        write_act(self, action): Write action metadata to a file.
        write_exp(self, experiment): Write experiment metadata to a file.
        write_seq(self, sequence): Write sequence metadata to a file.
        append_exp_to_seq(self, exp, seq): Append experiment metadata to a sequence file.
        new_file_conn_key(self, key: str) -> UUID: Generate a new file connection key.
        dflt_file_conn_key(self): Get the default file connection key.
        replace_status(self, status_list: List[HloStatus], old_status: HloStatus, new_status: HloStatus): Replace a status in the status list.
        get_main_error(self, errors) -> ErrorCodes: Get the main error from a list of errors.
        stop_executor(self, executor_id: str): Stop an executor.
        stop_all_executor_prefix(self, action_name: str, match_vars: dict = {}): Stop all executors with a given prefix.
    """

    # TODO: add world_cfg: dict parameter for BaseAPI to pass config instead of fastapp
    def __init__(self, app: HelaoFastAPI, dyn_endpoints=None):
        """
        Initialize the server object.

        Args:
            fastapp: The FastAPI application instance.
            dyn_endpoints (optional): Dynamic endpoints for the server.

        Raises:
            ValueError: If the root directory is not defined or 'run_type' is missing in the configuration.
        """
        self.server = MachineModel(
            server_name=app.helao_srv, machine_name=gethostname().lower()
        )

        self.app = app
        self.dyn_endpoints = dyn_endpoints
        self.server_cfg = self.app.helao_cfg["servers"][self.server.server_name]
        self.server_params = self.app.helao_cfg["servers"][self.server.server_name].get(
            "params", {}
        )
        self.server.hostname = self.server_cfg["host"]
        self.server.port = self.server_cfg["port"]
        self.world_cfg = self.app.helao_cfg
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
            LOGGER.info(f"Found run_type in config: {self.world_cfg['run_type']}")
            self.run_type = self.world_cfg["run_type"].lower()
        else:
            raise ValueError(
                "Missing 'run_type' in config, cannot create server object.",
            )

        self.actives: Dict[UUID, Active] = {}
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
        # only executors register into local_action_task_queue, default executors ignore queue
        self.local_action_task_queue = []

        self.status_publisher = WsPublisher(self.status_q)
        self.data_publisher = WsPublisher(self.data_q)
        self.live_publisher = WsPublisher(self.live_q)

        self.ntp_server = "time.nist.gov"
        self.ntp_response = None
        self.ntp_offset = None  # add to system time for correction
        self.ntp_last_sync = None
        self.aiolock = asyncio.Lock()
        self.endpoint_queues = {}
        self.local_action_queue = zdeque([])
        self.fast_urls = []

        self.hlo_postprocess_script = self.server_cfg.get("hlo_postprocess_script", "")

        if self.hlo_postprocess_script.endswith(".py") and os.path.exists(
            self.hlo_postprocess_script
        ):
            LOGGER.info(
                f"Loading hlo post-processor from {self.hlo_postprocess_script}"
            )
            self.hlo_postprocessor = (
                SourceFileLoader(
                    "hlo_post",
                    self.hlo_postprocess_script,
                )
                .load_module()
                .PostProcess
            )
        elif self.hlo_postprocess_script:
            LOGGER.info("Loading hlo post-processor from processors module")
            proc_spec = spec_from_file_location(
                "hlo_post",
                os.path.join(
                    "helao", "processors", f"{self.hlo_postprocess_script}.py"
                ),
            )
            proc_mod = module_from_spec(proc_spec)
            proc_spec.loader.exec_module(proc_mod)
            self.hlo_postprocessor = proc_mod.PostProcess
        else:
            self.hlo_postprocessor = None

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
        """
        Handles exceptions raised by coroutines in the event loop.

        This method is intended to be used as an exception handler for asyncio event loops.
        It logs the exception details and sets an emergency stop (E-STOP) flag on all active actions.

        Args:
            loop (asyncio.AbstractEventLoop): The event loop where the exception occurred.
            context (dict): A dictionary containing information about the exception, including
                            the exception object itself under the key "exception".

        Logs:
            - The context of the exception.
            - The formatted exception traceback.
            - A message indicating that the E-STOP flag is being set on active actions.
        """
        LOGGER.error(f"Got exception from coroutine: {context}")
        exc = context.get("exception")
        LOGGER.error(f"{traceback.format_exception(type(exc), exc, exc.__traceback__)}")
        # LOGGER.info("setting E-STOP flag on active actions")
        # for _, active in self.actives.items():
        #     active.set_estop()

    def myinit(self):
        """
        Initializes the asynchronous event loop and various tasks for the server.

        This method performs the following actions:
        - Retrieves the current running event loop.
        - Enables logging of slow callbacks that take longer than a specified interval.
        - Starts the hang inspection to dump coroutine stack traces when the event loop hangs.
        - Creates a task to stop the hang inspection.
        - Sets a custom exception handler for the event loop.
        - Gathers NTP time if it has not been synced yet.
        - Initializes and starts tasks for NTP synchronization, live buffering, and status logging.

        Attributes:
            aloop (asyncio.AbstractEventLoop): The current running event loop.
            dumper (aiodebug.hang_inspection.HangInspector): The hang inspection instance.
            dumper_task (asyncio.Task): The task to stop the hang inspection.
            sync_ntp_task_run (bool): Flag indicating if the NTP sync task has run.
            ntp_syncer (asyncio.Task): The task for NTP synchronization.
            bufferer (asyncio.Task): The task for live buffering.
            status_logger (asyncio.Task): The task for logging status.
        """
        self.aloop = asyncio.get_running_loop()
        # produce warnings on coroutines taking longer than interval
        aiodebug.log_slow_callbacks.enable(30.0)
        # dump coroutine stack traces when event loop hangs for longer than interval
        self.dumper = aiodebug.hang_inspection.start(
            os.path.join(self.helaodirs.root, "FAULTS"), interval=5.0
        )
        self.dumper_task = self.aloop.create_task(
            aiodebug.hang_inspection.stop_wait(self.dumper)
        )
        self.aloop.set_exception_handler(self.exception_handler)
        if self.ntp_last_sync is None:
            asyncio.gather(self.get_ntp_time())

        self.sync_ntp_task_run = False
        self.ntp_syncer = self.aloop.create_task(self.sync_ntp_task())
        self.bufferer = self.aloop.create_task(self.live_buffer_task())

        self.status_logger = self.aloop.create_task(self.log_status_task())
        if self.server_cfg.get("regular_update", False):
            regular_delay = self.server_cfg.get("regular_update_delay", 10)
            self.regular_updater = self.aloop.create_task(
                self.regular_status_task(regular_delay)
            )

    def dyn_endpoints_init(self):
        """
        Initializes dynamic endpoints by gathering asynchronous tasks.

        This method uses `asyncio.gather` to concurrently initialize the status
        of dynamic endpoints.

        Returns:
            None
        """
        asyncio.gather(self.init_endpoint_status(self.dyn_endpoints))

    def endpoint_queues_init(self):
        """
        Initializes endpoint queues for the server.

        This method iterates over the URLs in `self.fast_urls` and checks if the
        path of each URL starts with the server's name. If it does, it extracts
        the endpoint name from the URL path and initializes a queue for that
        endpoint, storing it in `self.endpoint_queues`.

        Returns:
            None
        """
        for urld in self.fast_urls:
            if urld.get("path", "").strip("/").startswith(self.server.server_name):
                endpoint_name = urld["path"].strip("/").split("/")[-1]
                self.endpoint_queues[endpoint_name] = zdeque([])

    def print_message(self, *args, **kwargs):
        """
        Print a message with the server configuration and server name.

        Args:
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        Keyword Args:
            log_dir (str): Directory where logs are stored.
        """
        print_message(
            LOGGER,
            self.server.server_name,
            log_dir=self.helaodirs.log_root,
            *args,
            **kwargs,
        )

    # TODO: add app: FastAPI parameter for BaseAPI to pass app
    async def init_endpoint_status(self, dyn_endpoints=None):
        """
        Initializes the endpoint status for the server.

        This method performs the following tasks:
        1. If `dyn_endpoints` is a callable, it invokes it with the `fastapp` instance.
        2. Iterates through the routes of the `fastapp` instance and updates the
           `actionservermodel.endpoints` dictionary with the endpoint names that
           start with the server's name.
        3. Sorts the status of each endpoint.
        4. Prints a message indicating the number of endpoints found for status monitoring.
        5. Retrieves and stores the URLs of the endpoints.
        6. Initializes the endpoint queues.

        Args:
            dyn_endpoints (Optional[Callable]): A callable that takes the `fastapp`
                                                instance as an argument. Default is None.
        """
        if callable(dyn_endpoints):
            await dyn_endpoints(app=self.app)
        for route in self.app.routes:
            # print(route.path)
            if route.path.startswith(f"/{self.server.server_name}"):
                self.actionservermodel.endpoints.update(
                    {route.name: EndpointModel(endpoint_name=route.name)}
                )
                self.actionservermodel.endpoints[route.name].sort_status()
        LOGGER.info(
            f"Found {len(self.actionservermodel.endpoints.keys())} endpoints for status monitoring on {self.server.server_name}."
        )
        self.fast_urls = self.get_endpoint_urls()
        self.endpoint_queues_init()

    def get_endpoint_urls(self):
        """
        Return a list of all endpoints on this server.

        This method iterates over all routes in the FastAPI application (`self.app.routes`)
        and constructs a list of dictionaries, each representing an endpoint. Each dictionary
        contains the following keys:

        - "path": The path of the route.
        - "name": The name of the route.
        - "params": A dictionary of parameters for the route, where each key is the parameter
          name and the value is another dictionary with the following keys:
            - "outer_type": The outer type of the parameter.
            - "type": The type of the parameter.
            - "required": A boolean indicating if the parameter is required.
            - "default": The default value of the parameter, or `None` if there is no default.

        Returns:
            list: A list of dictionaries, each representing an endpoint with its path, name,
                  and parameters.
        """
        url_list = []
        for route in self.app.routes:
            routeD = {"path": route.path, "name": route.name}
            if "dependant" in dir(route):
                flatParams = get_flat_params(route.dependant)
                paramD = {
                    par.name: {
                        "outer_type": (
                            str(par.field_info.annotation).split("'")[1]
                            if len(str(par.field_info.annotation).split("'")) >= 2
                            else str(par.field_info.annotation)
                        ),
                        "type": (
                            str(par.type_).split("'")[1]
                            if len(str(par.type_).split("'")) >= 2
                            else str(par.type_)
                        ),
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
        """
        Extracts and constructs an Action object from the given frame.

        This method inspects the local variables of the provided frame to find an
        instance of the Action class. It also collects other parameters and updates
        the action's parameters accordingly. If no Action instance is found, a blank
        Action is created. The method also sets various attributes of the Action
        object, such as action name, server key, and action parameters.

        Args:
            frame: The frame object from which to extract the Action.

        Returns:
            Action: The constructed or updated Action object.
        """
        _args, _varargs, _keywords, _locals = inspect.getargvalues(frame)
        action = None
        paramdict = {}

        for arg in _args:
            argparam = _locals.get(arg, None)
            if isinstance(argparam, Action):
                if action is None:
                    LOGGER.info(f"found Action BaseModel under parameter '{arg}'")
                    action = argparam
                else:
                    LOGGER.error(
                        f"critical error: found another Action BaseModel under parameter '{arg}', skipping it"
                    )
            else:
                paramdict.update({arg: argparam})

        if action is None:
            LOGGER.error(
                "critical error: no Action BaseModel was found by setup_action, using blank Action."
            )
            action = Action()

        for key, val in paramdict.items():
            if key not in action.action_params:
                LOGGER.info(
                    f"local var '{key}' not found in action.action_params, addding it."
                )
                action.action_params.update({key: val})

        LOGGER.info(f"Action.action_params: {action.action_params}")

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
        urlname = self.app.url_path_for(calname)

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
        """
        Sets up and returns an Action object.

        This method retrieves the current frame's caller frame and uses it to
        initialize and return an Action object.

        Returns:
            Action: The initialized Action object.
        """
        return self._get_action(frame=inspect.currentframe().f_back)

    async def setup_and_contain_action(
        self,
        json_data_keys: List[str] = [],
        action_abbr: Optional[str] = None,
        file_type: str = "helao__file",
        hloheader: HloHeaderModel = HloHeaderModel(),
    ):
        """
        Asynchronously sets up and contains an action.

        This method initializes an action with the provided parameters and then
        contains it using the `contain_action` method.

        Args:
            json_data_keys (List[str], optional): A list of JSON data keys. Defaults to an empty list.
            action_abbr (str, optional): An abbreviation for the action. Defaults to None.
            file_type (str, optional): The type of file. Defaults to "helao__file".
            hloheader (HloHeaderModel, optional): The header model for HLO. Defaults to an instance of HloHeaderModel.

        Returns:
            ActiveParams: The active parameters after containing the action.
        """
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
        """
        Handles the containment of an action by either substituting an existing action
        or creating a new one, and maintains a record of the last 10 active actions.

        Args:
            activeparams (ActiveParams): The parameters of the action to be contained.

        Returns:
            Active: The active action instance that has been contained.
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
        # register action_uuid in local action task queue
        return self.actives[activeparams.action.action_uuid]

    def get_active_info(self, action_uuid: UUID):
        """
        Retrieve the active action information for a given action UUID.

        Args:
            action_uuid (UUID): The unique identifier of the action to retrieve.

        Returns:
            dict: A dictionary containing the action information if the action UUID is found.
            None: If the action UUID is not found, returns None and logs an error message.
        """
        if action_uuid in self.actives:
            action_dict = self.actives[action_uuid].action.as_dict()
            return action_dict
        else:
            LOGGER.error(f"Specified action uuid {str(action_uuid)} was not found.")
            return None

    async def get_ntp_time(self):
        """
        Asynchronously retrieves the current time from an NTP server and updates the
        instance variables with the response.

        This method acquires a lock to ensure thread safety while accessing the NTP
        server. It sends a request to the specified NTP server and updates the
        following instance variables based on the response:
        - ntp_response: The full response from the NTP server.
        - ntp_last_sync: The original time from the NTP response.
        - ntp_offset: The offset time from the NTP response.

        If the request to the NTP server fails, it logs a timeout message and sets
        ntp_last_sync to the current time and ntp_offset to 0.0.

        Additionally, it logs the ntp_offset and ntp_last_sync values. If a file path
        for ntp_last_sync_file is provided, it waits until the file is not in use,
        then writes the ntp_last_sync and ntp_offset values to the file.

        Raises:
            ntplib.NTPException: If there is an error in the NTP request.

        Returns:
            None
        """
        with self.ntplock:
            c = ntplib.NTPClient()
            try:
                response = c.request(self.ntp_server, version=3)
                self.ntp_response = response
                self.ntp_last_sync = response.orig_time
                self.ntp_offset = response.offset
                LOGGER.debug(
                    f"retrieved time at {ctime(self.ntp_response.tx_timestamp)} from {self.ntp_server}"
                )
            except ntplib.NTPException:
                LOGGER.info(f"{self.ntp_server} ntp timeout")
                self.ntp_last_sync = time()
                self.ntp_offset = 0.0

            LOGGER.debug(f"ntp_offset: {self.ntp_offset}")
            LOGGER.debug(f"ntp_last_sync: {self.ntp_last_sync}")

            if self.ntp_last_sync_file is not None:
                while file_in_use(self.ntp_last_sync_file):
                    LOGGER.info("ntp file already in use, waiting")
                    await asyncio.sleep(0.1)
                async with aiofiles.open(self.ntp_last_sync_file, "w") as f:
                    await f.write(f"{self.ntp_last_sync},{self.ntp_offset}")

    async def send_statuspackage(
        self,
        client_servkey: str,
        client_host: str,
        client_port: int,
        action_name: Optional[str] = None,
    ):
        """
        Asynchronously sends a status package to a specified client.

        Args:
            client_servkey (str): The service key of the client.
            client_host (str): The host address of the client.
            client_port (int): The port number of the client.
            action_name (str, optional): The name of the action to include in the status package. Defaults to None.

        Returns:
            tuple: A tuple containing the response and error code from the private dispatcher.
        """
        # needs private dispatcher
        json_dict = {
            "actionservermodel": self.actionservermodel.get_fastapi_json(
                action_name=action_name,
            ),
        }
        response, error_code = await async_private_dispatcher(
            server_key=client_servkey,
            host=client_host,
            port=client_port,
            private_action="update_status",
            params_dict={"regular_task": "true" if action_name is None else "false"},
            json_dict=json_dict,
        )
        return response, error_code

    async def send_nbstatuspackage(
        self,
        client_servkey: str,
        client_host: str,
        client_port: int,
        actionmodel: Action,
    ):
        """
        Sends a non-blocking status package to a specified client.

        Args:
            client_servkey (str): The server key of the client.
            client_host (str): The host address of the client.
            client_port (int): The port number of the client.
            actionmodel (Action): The action model to be sent.

        Returns:
            tuple: A tuple containing the response and error code from the dispatcher.

        """
        # needs private dispatcher
        json_dict = {
            "actionmodel": actionmodel.as_dict(),
        }
        params_dict = {
            "server_host": self.server_cfg["host"],
            "server_port": self.server_cfg["port"],
        }
        LOGGER.info(f"sending non-blocking status: {json_dict}")
        response, error_code = await async_private_dispatcher(
            server_key=client_servkey,
            host=client_host,
            port=client_port,
            private_action="update_nonblocking",
            params_dict=params_dict,
            json_dict=json_dict,
        )
        LOGGER.info(f"update_nonblocking request got response: {response}")
        return response, error_code

    async def attach_client(
        self, client_servkey: str, client_host: str, client_port: int, retry_limit=5
    ):
        """
        Attach a client to the status subscriber list.

        This method attempts to attach a client to the server's status subscriber list.
        It retries the attachment process up to `retry_limit` times if it fails.

        Args:
            client_servkey (str): The service key of the client.
            client_host (str): The host address of the client.
            client_port (int): The port number of the client.
            retry_limit (int, optional): The number of times to retry the attachment process. Defaults to 5.

        Returns:
            bool: True if the client was successfully attached, False otherwise.
        """
        success = False
        combo_key = (
            client_servkey,
            client_host,
            client_port,
        )
        LOGGER.info("attaching status subscriber")

        if combo_key in self.status_clients:
            LOGGER.info(
                f"Client {combo_key} is already subscribed to {self.server.server_name} status updates."
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
                LOGGER.info(
                    f"Added {combo_key} to {self.server.server_name} status subscriber list."
                )
                success = True
                break
            else:
                LOGGER.error(
                    f"Failed to add {combo_key} to {self.server.server_name} status subscriber list."
                )

            if success:
                LOGGER.info(
                    f"Attached {combo_key} to status ws on {self.server.server_name}."
                )
            else:
                LOGGER.error(
                    f"failed to attach {combo_key} to status ws on {self.server.server_name} after {retry_limit} attempts."
                )

        return success

    def detach_client(self, client_servkey: str, client_host: str, client_port: int):
        """
        Detaches a client from receiving status updates.

        Parameters:
        client_servkey (str): The service key of the client.
        client_host (str): The host address of the client.
        client_port (int): The port number of the client.

        Removes the client identified by the combination of service key, host,
        and port from the list of clients receiving status updates. If the client
        is not found in the list, a message indicating that the client is not
        subscribed will be printed.
        """
        combo_key = (
            client_servkey,
            client_host,
            client_port,
        )
        if combo_key in self.status_clients:
            self.status_clients.remove(combo_key)
            LOGGER.info(f"Client {combo_key} will no longer receive status updates.")
        else:
            LOGGER.info(f"Client {combo_key} is not subscribed.")

    async def ws_status(self, websocket: WebSocket):
        """
        Handle WebSocket connections for status updates.

        This asynchronous method accepts a WebSocket connection, subscribes to
        status updates, and sends compressed status messages to the client. If an
        exception occurs, it logs the error and removes the subscriber from the
        status queue.

        Args:
            websocket (WebSocket): The WebSocket connection instance.

        Raises:
            Exception: If an error occurs during the WebSocket communication.
        """
        LOGGER.info("got new status subscriber")
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
            LOGGER.error(
                f"Status websocket client {websocket.client[0]}:{websocket.client[1]} disconnected. {repr(e), tb,}"
            )
            if status_sub in self.status_q.subscribers:
                self.status_q.remove(status_sub)

    async def ws_data(self, websocket: WebSocket):
        """
        Handle WebSocket connections for data subscribers.

        This asynchronous method accepts a WebSocket connection, subscribes to a data queue,
        and sends compressed data messages to the WebSocket client. If an exception occurs,
        it logs the error and removes the subscriber from the data queue.

        Args:
            websocket (WebSocket): The WebSocket connection instance.

        Raises:
            Exception: If any exception occurs during the WebSocket communication.
        """
        LOGGER.info("got new data subscriber")
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
            LOGGER.error(
                f"Data websocket client {websocket.client[0]}:{websocket.client[1]} disconnected. {repr(e), tb,}"
            )
            if data_sub in self.data_q.subscribers:
                self.data_q.remove(data_sub)

    async def ws_live(self, websocket: WebSocket):
        """
        Handle a new WebSocket connection for live data streaming.

        This coroutine accepts a WebSocket connection, subscribes to the live data queue,
        and sends compressed live data messages to the client. If an exception occurs,
        it logs the error and removes the subscriber from the live data queue.

        Args:
            websocket (WebSocket): The WebSocket connection instance.

        Raises:
            Exception: If an error occurs during the WebSocket communication or data processing.
        """
        LOGGER.info("got new live_buffer subscriber")
        await websocket.accept()
        live_sub = self.live_q.subscribe()
        try:
            async for live_msg in live_sub:
                await websocket.send_bytes(pyzstd.compress(pickle.dumps(live_msg)))
        # except WebSocketDisconnect:
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            LOGGER.error(
                f"Data websocket client {websocket.client[0]}:{websocket.client[1]} disconnected. {repr(e), tb,}"
            )
            if live_sub in self.live_q.subscribers:
                self.live_q.remove(live_sub)

    async def live_buffer_task(self):
        """
        Asynchronous task that processes messages from a live queue and updates the live buffer.

        This method subscribes to the live queue and iterates over incoming messages.
        Each message is used to update the live buffer.

        The method logs a message indicating that the live buffer task has been created.

        Returns:
            None
        """
        LOGGER.info(f"{self.server.server_name} live buffer task created.")
        async for live_msg in self.live_q.subscribe():
            self.live_buffer.update(live_msg)

    async def put_lbuf(self, live_dict):
        """
        Asynchronously puts a dictionary with updated timestamps into the live queue.

        Args:
            live_dict (dict): A dictionary where each key-value pair will be updated with the current time.

        Returns:
            None
        """
        new_dict = {k: (v, time()) for k, v in live_dict.items()}
        await self.live_q.put(new_dict)

    def put_lbuf_nowait(self, live_dict):
        """
        Puts a dictionary with current timestamps into the live queue without waiting.

        Args:
            live_dict (dict): A dictionary where each key-value pair will be updated
                              with the current time and then put into the live queue.
        """
        new_dict = {k: (v, time()) for k, v in live_dict.items()}
        self.live_q.put_nowait(new_dict)

    def get_lbuf(self, live_key):
        """
        Retrieve the live buffer associated with the given key.

        Args:
            live_key (str): The key to identify the live buffer.

        Returns:
            object: The live buffer associated with the given key.
        """
        return self.live_buffer[live_key]

    async def regular_status_task(self, delay: float = 10, retry_limit: int = 5):
        while True:
            for combo_key in self.status_clients.copy():
                client_servkey, client_host, client_port = combo_key
                for _ in range(retry_limit):
                    response, error_code = await self.send_statuspackage(
                        action_name=None,
                        client_servkey=client_servkey,
                        client_host=client_host,
                        client_port=client_port,
                    )
                    if response and error_code == ErrorCodes.none:
                        break
            await asyncio.sleep(delay)

    async def process_unified_queue(self):
        qact, qpars = None, {}
        try:
            # unified local queue, separate endpoints cannot be concurrent
            qact, qpars = self.local_action_queue.popleft()
            LOGGER.info(f"{qact.action_name} was previously queued")
            LOGGER.info(f"running queued {qact.action_name}")
            qact.start_condition = ASC.no_wait
            qact.action_params["queued_launch"] = True
            await async_action_dispatcher(self.world_cfg, qact, qpars)
        except Exception:
            LOGGER.error(
                "Failed to process local unified queue",
                exc_info=True,
            )
            if qact is not None:
                LOGGER.info(f"re-queing {qact.action_name}")
                self.local_action_queue.appendleft(
                    (
                        qact,
                        qpars,
                    )
                )

    async def process_endpoint_queue(self, status_msg: ActionModel):
        qact, qpars = None, None
        try:
            # process individiual endpoint queues, can be concurrent
            qact, qpars = self.endpoint_queues[status_msg.action_name].popleft()
            LOGGER.info(f"{status_msg.action_name} was previously queued")
            LOGGER.info(f"running queued {status_msg.action_name}")
            qact.start_condition = ASC.no_wait
            qact.action_params["queued_launch"] = True
            await async_action_dispatcher(self.world_cfg, qact, qpars)
        except Exception:
            LOGGER.error(
                "Failed to process local endpoint queue",
                exc_info=True,
            )
            if qact is not None:
                LOGGER.info(f"re-queing {status_msg.action_name}")
                self.endpoint_queues[status_msg.action_name].appendleft(
                    (
                        qact,
                        qpars,
                    )
                )

    async def log_status_task(self, retry_limit: int = 5):
        """
        Asynchronous task to log and send status updates to clients.

        This task subscribes to a status queue and processes incoming status messages.
        It updates the internal action server model with the new status, sends the status
        to subscribed clients, and handles retries in case of failures.

        Args:
            retry_limit (int): The number of retry attempts for sending status updates to clients. Default is 5.

        Raises:
            Exception: If an error occurs during the execution of the task, it logs the error and traceback.
        """
        LOGGER.info(f"{self.server.server_name} status log task created.")

        try:
            # get the new Action (status) from the queue
            async for status_msg in self.status_q.subscribe():
                # add it to the correct "EndpointModel"
                # in the "ActionServerModel"
                if status_msg.action_name not in self.actionservermodel.endpoints:
                    # a new endpoints became available
                    self.actionservermodel.endpoints[status_msg.action_name] = (
                        EndpointModel(endpoint_name=status_msg.action_name)
                    )
                self.actionservermodel.endpoints[
                    status_msg.action_name
                ].active_dict.update({status_msg.action_uuid: status_msg})
                self.actionservermodel.last_action_uuid = status_msg.action_uuid

                # sort the status (nonactive_dict is empty at this point)
                self.actionservermodel.endpoints[status_msg.action_name].sort_status()
                LOGGER.info(
                    f"log_status_task sending status {status_msg.action_status} for action {status_msg.action_name} with uuid {status_msg.action_uuid} on {status_msg.action_server.disp_name()} to subscribers ({self.status_clients})."
                )
                if len(self.status_clients) == 0 and self.orch_key is not None:
                    await self.attach_client(
                        self.orch_key, self.orch_host, self.orch_port
                    )

                for combo_key in self.status_clients.copy():
                    client_servkey, client_host, client_port = combo_key
                    LOGGER.info(
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
                        LOGGER.info(f"Pushed status message to {client_servkey}.")
                    else:
                        LOGGER.error(
                            f"Failed to push status message to {client_servkey} after {retry_limit} attempts."
                        )
                    sleep(0.3)
                # now delete the errored and finsihed statuses after
                # all are send to the subscribers
                self.actionservermodel.endpoints[
                    status_msg.action_name
                ].clear_finished()
                LOGGER.info("all log_status_task messages send.")

                active_nonqueued = {
                    endpoint: [
                        auuid
                        for auuid, act in endmod.active_dict.items()
                        if not act.action_params.get("queued_on_actserv", False)
                        or act.action_params.get("queued_launch", False)
                    ]
                    for endpoint, endmod in self.actionservermodel.endpoints.items()
                }
                active_nq = [x for y in active_nonqueued.values() for x in y]

                if not self.server_params.get("allow_concurrent_actions", True):
                    if len(self.local_action_queue) > 0 and not active_nq:
                        await self.process_unified_queue()
                else:
                    if len(
                        self.endpoint_queues[status_msg.action_name]
                    ) > 0 and not active_nonqueued.get(status_msg.action_name, []):
                        await self.process_endpoint_queue(status_msg)

            LOGGER.info("log_status_task done.")

        # except asyncio.CancelledError:
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            LOGGER.error(f"status logger task was cancelled with error: {repr(e), tb,}")

    async def detach_subscribers(self):
        """
        Asynchronously detaches subscribers by signaling the termination of
        status and data queues and then waits for a short period.

        This method performs the following actions:
        1. Puts a `StopAsyncIteration` exception into the `status_q` queue.
        2. Puts a `StopAsyncIteration` exception into the `data_q` queue.
        3. Waits for 1 second to allow the queues to process the termination signal.

        Returns:
            None
        """
        await self.status_q.put(StopAsyncIteration)
        await self.data_q.put(StopAsyncIteration)
        await asyncio.sleep(1)

    async def get_realtime(
        self, epoch_ns: Optional[float] = None, offset: Optional[float] = None
    ) -> float:
        """
        Asynchronously retrieves the real-time value.

        Args:
            epoch_ns (float, optional): The epoch time in nanoseconds. Defaults to None.
            offset (float, optional): The offset to be applied to the epoch time. Defaults to None.

        Returns:
            float: The real-time value.
        """
        return self.get_realtime_nowait(epoch_ns=epoch_ns, offset=offset)

    def get_realtime_nowait(
        self, epoch_ns: Optional[float] = None, offset: Optional[float] = None
    ) -> float:
        """
        Calculate the real-time in nanoseconds, optionally adjusted by an offset.

        Parameters:
        epoch_ns (float, optional): The epoch time in nanoseconds. If None, the current time is used.
        offset (float, optional): The offset in seconds to adjust the time. If None, the instance's NTP offset is used.

        Returns:
        float: The calculated real-time in nanoseconds.
        """
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
        """
        Periodically synchronizes the system time with an NTP server.

        This asynchronous task runs in a loop, checking the last synchronization
        time from a file and determining if a resynchronization is needed based
        on the provided `resync_time` interval. If the time since the last
        synchronization exceeds `resync_time`, it triggers an NTP time sync.
        The task can be cancelled gracefully.

        Args:
            resync_time (int): The interval in seconds to wait before
                               resynchronizing the time. Default is 1800 seconds (30 minutes).

        Raises:
            asyncio.CancelledError: If the task is cancelled during execution.
        """
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
                    # LOGGER.info(f"waiting {wait_time} until next time check")
                    await asyncio.sleep(wait_time)
        except asyncio.CancelledError:
            LOGGER.info("ntp sync task was cancelled")

    async def shutdown(self):
        """
        Asynchronously shuts down the server.

        This method performs the following actions:
        1. Sets the `sync_ntp_task_run` flag to False to stop NTP synchronization.
        2. Detaches all subscribers by calling `detach_subscribers`.
        3. Cancels the `status_logger` task.
        4. Cancels the `ntp_syncer` task.

        Returns:
            None
        """
        self.sync_ntp_task_run = False
        await self.detach_subscribers()
        self.status_logger.cancel()
        self.ntp_syncer.cancel()

    async def write_act(self, action: Action):
        """
        Asynchronously writes action metadata to a YAML file if saving is enabled.

        Args:
            action (Action): The action object containing metadata to be saved.

        The function constructs the output file path and name based on the action's
        timestamp and other attributes. If the directory does not exist, it creates
        it. The metadata is then written to a YAML file in the specified directory.

        If saving is disabled for the action, a message indicating this is printed.

        Raises:
            OSError: If there is an issue creating the directory or writing the file.
        """
        if action.save_act:
            act_dict = action.get_act().clean_dict()
            save_root = str(self.helaodirs.save_root)
            if action.manual_action:
                save_root = save_root.replace("RUNS_ACTIVE", "RUNS_DIAG")
            output_path = os.path.join(save_root, action.action_output_dir)
            output_file = os.path.join(
                output_path,
                f"{action.action_timestamp.strftime('%Y%m%d.%H%M%S%f')}-act.yml",
            )

            LOGGER.info(f"writing to act meta file: {output_path}")

            os.makedirs(output_path, exist_ok=True)

            output_dict = {"file_type": "action"}
            output_dict.update(act_dict)
            async with aiofiles.open(output_file, mode="w+") as f:
                await f.write(yml_dumps(output_dict))
        else:
            LOGGER.info(
                f"writing meta file for action '{action.action_name}' is disabled."
            )

    async def write_exp(self, experiment: Experiment):
        """
        Asynchronously writes the experiment data to a YAML file.

        Args:
            experiment (Experiment): The experiment object containing the data to be written.
            manual (bool, optional): If True, saves the file in the DIAG directory. Defaults to False.

        Writes:
            A YAML file containing the experiment data to the specified directory.
        """
        exp_dict = experiment.get_exp().clean_dict()
        save_root = str(self.helaodirs.save_root)
        if experiment.manual_action:
            save_root = save_root.replace("RUNS_ACTIVE", "RUNS_DIAG")
        output_path = os.path.join(save_root, experiment.get_experiment_dir())
        output_file = os.path.join(
            output_path,
            f"{experiment.experiment_timestamp.strftime('%Y%m%d.%H%M%S%f')}-exp.yml",
        )

        LOGGER.info(f"writing to exp meta file: {output_file}")
        output_dict = {"file_type": "experiment"}
        output_dict.update(exp_dict)
        output_str = yml_dumps(output_dict)
        if not output_str.endswith("\n"):
            output_str += "\n"

        os.makedirs(output_path, exist_ok=True)

        async with aiofiles.open(output_file, mode="w+") as f:
            await f.write(output_str)

    async def write_seq(self, sequence: Sequence):
        """
        Asynchronously writes a sequence to a YAML file.

        Args:
            sequence (Sequence): The sequence object to be written.
            manual (bool, optional): If True, the sequence will be saved in the "DIAG" directory.
                                     If False, it will be saved in the default save_root directory.
                                     Defaults to False.

        Writes:
            A YAML file containing the sequence data to the specified directory.
        """
        seq_dict = sequence.get_seq().clean_dict()
        sequence_dir = sequence.get_sequence_dir()
        save_root = str(self.helaodirs.save_root)
        if sequence.manual_action:
            save_root = save_root.replace("RUNS_ACTIVE", "RUNS_DIAG")
        output_path = os.path.join(save_root, sequence_dir)
        output_file = os.path.join(
            output_path,
            f"{sequence.sequence_timestamp.strftime('%Y%m%d.%H%M%S%f')}-seq.yml",
        )

        LOGGER.info(f"writing to seq meta file: {output_file}")
        output_dict = {"file_type": "sequence"}
        output_dict.update(seq_dict)
        output_str = yml_dumps(output_dict)
        if not output_str.endswith("\n"):
            output_str += "\n"

        os.makedirs(output_path, exist_ok=True)

        async with aiofiles.open(output_file, mode="w+") as f:
            await f.write(output_str)

    async def append_exp_to_seq(self, exp, seq):
        """
        Appends experiment details to a sequence file in YAML format.

        Args:
            exp: An object containing experiment details such as experiment_uuid,
                 experiment_name, experiment_output_dir, orch_key, orch_host, and orch_port.
            seq: An object representing the sequence to which the experiment details
                 will be appended. It should have methods get_sequence_dir() and
                 sequence_timestamp.

        Writes:
            A YAML formatted string containing the experiment details to a file named
            with the sequence timestamp in the sequence directory.
        """
        append_dict = {
            "experiment_uuid": str(exp.experiment_uuid),
            "experiment_name": exp.experiment_name,
            "experiment_output_dir": str(exp.experiment_output_dir),
            "orch_key": str(exp.orch_key),
            "orch_host": str(exp.orch_host),
            "orch_port": int(exp.orch_port),
            "data_request_id": str(exp.data_request_id),
        }
        append_str = yml_dumps([append_dict])
        sequence_dir = seq.get_sequence_dir()
        save_root = str(self.helaodirs.save_root)
        if seq.manual_action:
            save_root = save_root.replace("RUNS_ACTIVE", "RUNS_DIAG")
        output_path = os.path.join(save_root, sequence_dir)
        output_file = os.path.join(
            output_path,
            f"{seq.sequence_timestamp.strftime('%Y%m%d.%H%M%S%f')}-seq.yml",
        )
        async with aiofiles.open(output_file, mode="a") as f:
            await f.write(append_str)

    def new_file_conn_key(self, key: str) -> UUID:
        """
        Generates a UUID based on the MD5 hash of the provided key string.

        Args:
            key (str): The input string to be hashed and converted to a UUID.

        Returns:
            UUID: A UUID object generated from the MD5 hash of the input string.
        """
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
        """
        Generates a default file connection key.

        This method returns a new file connection key using the string representation
        of `None`.

        Returns:
            str: A new file connection key.
        """
        return self.new_file_conn_key(str(None))

    def replace_status(
        self, status_list: List[HloStatus], old_status: HloStatus, new_status: HloStatus
    ):
        """
        Replaces an old status with a new status in the given status list. If the old status
        is not found in the list, the new status is appended to the list.

        Args:
            status_list (List[HloStatus]): The list of statuses to be modified.
            old_status (HloStatus): The status to be replaced.
            new_status (HloStatus): The status to replace with.

        Returns:
            None
        """
        if old_status in status_list:
            idx = status_list.index(old_status)
            status_list[idx] = new_status
        else:
            status_list.append(new_status)

    def get_main_error(self, errors) -> ErrorCodes:
        """
        Determines the main error from a list of errors or a single error.

        Args:
            errors (Union[List[ErrorCodes], ErrorCodes]): A list of error codes or a single error code.

        Returns:
            ErrorCodes: The first non-none error code found in the list, or the single error code if not a list.
        """
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
        """
        Stops the executor task associated with the given executor ID.

        This method attempts to stop the action task of the specified executor by signaling it to end its polling loop.
        If the executor ID is not found among the active executors, an error message is printed.

        Args:
            executor_id (str): The ID of the executor to stop.

        Returns:
            dict: A dictionary indicating whether the stop signal was successfully sent.
                  The dictionary contains a single key "signal_stop" with a boolean value:
                  - True if the stop signal was successfully sent.
                  - False if the executor ID was not found.
        """
        try:
            self.executors[executor_id].stop_action_task()
            LOGGER.info(f"Signaling executor task {executor_id} to end polling loop.")
            return {"signal_stop": True}
        except KeyError:
            LOGGER.info(f"Could not find {executor_id} among active executors.")
            LOGGER.info(f"Current executors are: {self.executors.keys()}")
            return {"signal_stop": False}

    def stop_all_executor_prefix(self, action_name: str, match_vars: dict = {}):
        """
        Stops all executors whose keys start with the given action name prefix.

        Args:
            action_name (str): The prefix of the executor keys to match.
            match_vars (dict, optional): A dictionary of variable names and values to further filter the executors.
                Only executors whose variables match the provided values will be stopped. Defaults to an empty dictionary.

        Returns:
            None
        """
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
    """
        The Active class represents an active action within a server. It manages the lifecycle of an action, including initialization, execution, data logging, and finalization. The class provides methods to handle various aspects of an action, such as starting executors, logging data, handling errors, and managing file connections.

        Attributes:
            base: The base server instance.
            active_uuid: The unique identifier for the active action.
            action: The current action being managed.
            action_list: A list of all actions associated with this active instance.
            listen_uuids: A list of UUIDs to listen for data logging.
            num_data_queued: The number of data items queued for logging.
            num_data_written: The number of data items written to files.
            file_conn_dict: A dictionary mapping file connection keys to FileConn instances.
            manual_stop: A flag indicating if the action should be manually stopped.
            action_loop_running: A flag indicating if the action loop is currently running.
            action_task: The asyncio task for the action loop.

        Methods:
            __init__(self, base, activeparams: ActiveParams):
                Initializes the Active instance with the given base server and active parameters.

            executor_done_callback(self, futr):
                Callback function to handle the completion of an executor.

            start_executor(self, executor: Executor):
                Starts the executor for the action.

            oneoff_executor(self, executor: Executor):
                Executes a one-off action using the executor.

            update_act_file(self):
                Updates the action file with the current action state.

            myinit(self):
                Initializes the data logger and action file.

            init_datafile(self, header, file_type, json_data_keys, file_sample_label, filename, file_group: HloFileGroup, file_conn_key: Optional[str] = None, action: Optional[Action] = None):
                Initializes a data file with the given parameters.

            finish_hlo_header(self, file_conn_keys: Optional[List[UUID]] = None, realtime: Optional[float] = None):
                Adds a timestamp to the data file header.

            add_status(self, action=None):
                Sends the status of the most recent active action.

            set_estop(self, action: Optional[Action] = None):
                Sets the emergency stop status for the action.

            set_error(self, error_code: Optional[ErrorCodes] = None, action: Optional[Action] = None):
                Sets the error status for the action.

            get_realtime(self, epoch_ns: Optional[float] = None, offset: Optional[float] = None) -> float:
                Gets the current real-time with optional epoch and offset.

            get_realtime_nowait(self, epoch_ns: Optional[float] = None, offset: Optional[float] = None) -> float:
                Gets the current real-time without waiting.

            write_live_data(self, output_str: str, file_conn_key: UUID):
                Appends lines to the file connection.

            enqueue_data_dflt(self, datadict: dict):
                Enqueues data to a default file connection key.

            enqueue_data(self, datamodel: DataModel, action: Optional[Action] = None):
                Enqueues data to the data queue.

            enqueue_data_nowait(self, datamodel: DataModel, action: Optional[Action] = None):
                Enqueues data to the data queue without waiting.

            assemble_data_msg(self, datamodel: DataModel, action: Optional[Action] = None) -> DataPackageModel:
                Assembles a data message for the given data model and action.

            add_new_listen_uuid(self, new_uuid: UUID):
                Adds a new UUID to the data logger UUID list.

            _get_action_for_file_conn_key(self, file_conn_key: UUID):
                Gets the action associated with the given file connection key.

            log_data_set_output_file(self, file_conn_key: UUID):
                Sets the output file for logging data.

            log_data_task(self):
                Subscribes to the data queue and writes data to the file.

            write_file(self, output_str: str, file_type: str, filename: Optional[str] = None, file_group: HloFileGroup = HloFileGroup.aux_files, header: Optional[str] = None, sample_str: Optional[str] = None, file_sample_label: Optional[str] = None, json_data_keys: Optional[str] = None, action: Optional[Action] = None):
                Writes a complete file with the given parameters.

            write_file_nowait(self, output_str: str, file_type: str, filename: Optional[str] = None, file_group: HloFileGroup = HloFileGroup.aux_files, header: Optional[str] = None, sample_str: Optional[str] = None, file_sample_label: Optional[str] = None, json_data_keys: Optional[str] = None, action: Optional[Action] = None):
                Writes a complete file with the given parameters without waiting.

            set_sample_action_uuid(self, sample: Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample], action_uuid: UUID):
                Sets the action UUID for the given sample.

            append_sample(self, samples: List[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
    ], IO: str, action: Optional[Action] = None):
                Adds samples to the input or output sample list.

            split_and_keep_active(self):
                Splits the current action and keeps it active.

            split_and_finish_prev_uuids(self):
                Splits the current action and finishes previous UUIDs.

            finish_all(self):
                Finishes all actions.

            split(self, uuid_list: Optional[List[UUID]] = None, new_fileconnparams: Optional[FileConnParams] = None) -> List[UUID]:
                Splits the current action and finishes previous actions in the UUID list.

            substitute(self):
                Closes all file connections.

            finish(self, finish_uuid_list: Optional[List[UUID]] = None) -> Action:
                Finishes the actions in the UUID list and performs cleanup.

            track_file(self, file_type: str, file_path: str, samples: List[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
    ], action: Optional[Action] = None):
                Adds auxiliary files to the file dictionary.

            relocate_files(self):
                Copies auxiliary files to the experiment directory.

            finish_manual_action(self):
                Finishes a manual action and writes the sequence and experiment meta files.

            send_nonblocking_status(self, retry_limit: int = 3):
                Sends the non-blocking status to clients.

            action_loop_task(self, executor: Executor):
                The main loop for executing an action.

            stop_action_task(self):
                Stops the action loop task.
    """

    def __init__(self, base, activeparams: ActiveParams):  # outer instance
        """
        Initializes an instance of the class.

        Args:
            base: The base instance.
            activeparams (ActiveParams): The active parameters.

        Attributes:
            base: The base instance.
            active_uuid: The UUID of the active action.
            action: The active action.
            action_list: A list of all actions for this active instance, with the most recent one at position 0.
            listen_uuids: A list of UUIDs to listen to.
            num_data_queued: The number of data items queued.
            num_data_written: The number of data items written.
            file_conn_dict (Dict[str, FileConn]): A dictionary mapping file connection keys to FileConn instances.
            manual_stop: A flag indicating whether the action has been manually stopped.
            action_loop_running: A flag indicating whether the action loop is running.
            action_task: The task associated with the action.

        Notes:
            - Updates the timestamp and UUID of the action if they are None.
            - Sets the action to dummy or simulation mode based on the world configuration.
            - Initializes the action with a time offset.
            - Adds the action UUID to the list of listen UUIDs.
            - Prints a message if the action is a manual action.
            - Checks if the root save directory is specified and sets the save flags accordingly.
            - Adds auxiliary listen UUIDs from the active parameters.
            - Initializes file connections from the active parameters and updates the action's file connection keys.
            - Prints messages indicating the save flags for the action.
        """
        self.base = base
        self.driver = self.base.app.driver
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
        self.action.dummy = self.base.world_cfg.get("dummy", "False")
        self.action.simulation = self.base.world_cfg.get("simulation", "False")
        self.action.init_act(time_offset=self.base.ntp_offset)
        self.add_new_listen_uuid(self.action.action_uuid)

        if self.action.manual_action:
            LOGGER.info("Manual Action.")

        if not self.base.helaodirs.save_root:
            LOGGER.info(
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

        LOGGER.info(
            f"save_act is '{self.action.save_act}' for action '{self.action.action_name}'"
        )
        LOGGER.info(
            f"save_data is '{self.action.save_data}' for action '{self.action.action_name}'"
        )

        self.manual_stop = False
        self.action_loop_running = False
        self.action_task = None

    def executor_done_callback(self, futr):
        """
        Callback function to handle the completion of a future.

        This function is called when a future is done. It attempts to retrieve the
        result of the future. If an exception occurred during the execution of the
        future, it catches the exception and prints the traceback.

        Args:
            futr (concurrent.futures.Future): The future object that has completed.
        """
        try:
            _ = futr.result()
        except Exception as exc:
            LOGGER.info(
                f"{traceback.format_exception(type(exc), exc, exc.__traceback__)}"
            )

    def start_executor(self, executor: Executor):
        """
        Starts the executor task and manages its execution.

        Args:
            executor (Executor): The executor instance to be started.

        Returns:
            dict: A dictionary representation of the action associated with the executor.

        Notes:
            - If the executor does not allow concurrency, the action UUID is appended to the local queue before running the task.
            - The executor task is created and started using the event loop.
            - A callback is added to handle the completion of the executor task.
            - A message indicating the start of the executor task is printed.
        """
        # append action_uuid to local queue before running task if concurrency not allowed
        if not executor.concurrent:
            self.base.local_action_task_queue.append(executor.active.action.action_uuid)
        self.action_task = self.base.aloop.create_task(self.action_loop_task(executor))
        self.action_task.add_done_callback(self.executor_done_callback)
        LOGGER.info("Executor task started.")
        return self.action.as_dict()

    async def oneoff_executor(self, executor: Executor):
        """
        Executes a one-off task using the provided executor.

        Args:
            executor (Executor): The executor instance to run the task.

        Returns:
            The result of the action loop task executed by the provided executor.
        """
        return await self.action_loop_task(executor)

    async def update_act_file(self):
        """
        Asynchronously updates the action file by writing the current action.

        This method calls the `write_act` method of the `base` object, passing the
        current action as an argument. It ensures that the action file is updated
        with the latest action data.

        Returns:
            None
        """
        await self.base.write_act(self.action)

    async def myinit(self):
        """
        Asynchronous initialization method for setting up logging and directories.

        This method performs the following tasks:
        1. Creates a task for logging data.
        2. If the action requires saving, it creates necessary directories and updates the action file.
        3. Prints a message indicating the initialization status.
        4. Adds the current status.

        Returns:
            None
        """
        self.data_logger = self.base.aloop.create_task(self.log_data_task())
        save_root = str(self.base.helaodirs.save_root)
        if self.action.manual_action:
            save_root = save_root.replace("RUNS_ACTIVE", "RUNS_DIAG")
        if self.action.save_act:
            full_action_output_path = os.path.join(
                save_root,
                self.action.action_output_dir,
            )
            if self.action.manual_action:
                full_action_output_path = full_action_output_path.replace(
                    "ACTIVE",
                    "DIAG",
                )
            os.makedirs(full_action_output_path, exist_ok=True)
            await self.update_act_file()

            if self.action.manual_action:
                exp = deepcopy(self.action_list[-1])
                exp.experiment_status = [HloStatus.active]
                exp.sequence_status = [HloStatus.active]
                exp.samples_in = []
                exp.samples_out = []
                exp.files = []

                # add actions to experiment
                for action in self.action_list:
                    exp.dispatched_actions.append(self.action.get_act())

                # add experiment to sequence
                exp.dispatched_experiments.append(self.action.get_exp())
                # create and write seq file for manual action
                await self.base.write_seq(self.action)
                # create and write exp file for manual action
                await self.base.write_exp(self.action)

        LOGGER.info("init active: sending active data_stream_status package")

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
        """
        Initializes a data file with the provided parameters and generates the necessary file information.

        Args:
            header (Union[dict, list, str, None]): The header information for the file. Can be a dictionary, list, string, or None.
            file_type (str): The type of the file.
            json_data_keys (list): List of keys for JSON data.
            file_sample_label (Union[list, str, None]): Labels for the file samples. Can be a list, string, or None.
            filename (str): The name of the file. If None, a filename will be generated.
            file_group (HloFileGroup): The group to which the file belongs (e.g., heloa_files or aux_files).
            file_conn_key (str, optional): The connection key for the file. Defaults to None.
            action (Action, optional): The action associated with the file. Defaults to None.

        Returns:
            tuple: A tuple containing the header (str) and file information (FileInfo).
        """
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
            nosync=(
                True if not action.sync_data and filename.endswith(".hlo") else False
            ),
        )

        if header:
            if not header.endswith("\n"):
                header += "\n"

        return header, file_info

    def finish_hlo_header(
        self,
        file_conn_keys: Optional[List[UUID]] = None,
        realtime: Optional[float] = None,
    ):
        """
        Finalizes the HLO header for the given file connection keys.

        This method updates the `epoch_ns` field in the HLO header of each file
        connection specified by `file_conn_keys` with the provided `realtime` value.
        If `realtime` is not provided, the current real-time value is used. If
        `file_conn_keys` is not provided, the method will update the HLO header for
        all file connections associated with the actions in `self.action_list`.

        Args:
            file_conn_keys (List[UUID], optional): A list of file connection keys
                to update. If None, all file connection keys from `self.action_list`
                will be used. Defaults to None.
            realtime (float, optional): The real-time value to set in the HLO header.
                If None, the current real-time value will be used. Defaults to None.
        """
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
        """
        Adds the given action to the status list and logs the action.

        If the action is not provided, it defaults to `self.action`.

        Args:
            action (Optional[Action]): The action to be added to the status list. If None, defaults to `self.action`.

        Returns:
            None

        Side Effects:
            - Logs a message indicating the action being added to the status list.
            - If the action is blocking, it waits until the action is added to the status queue.
        """
        if action is None:
            action = self.action

        LOGGER.info(
            f"Adding {str(action.action_uuid)} to {action.action_name} status list."
        )

        if not action.nonblocking:
            await self.base.status_q.put(action.get_act())

    def set_estop(self, action: Optional[Action] = None):
        """
        Sets the emergency stop (E-STOP) status for the given action.

        Parameters:
        action (Action, optional): The action to set the E-STOP status for.
                                   If None, the current action is used.

        Returns:
        None
        """
        if action is None:
            action = self.action
        action.action_status.append(HloStatus.estopped)
        LOGGER.error(
            f"E-STOP {str(action.action_uuid)} on {action.action_name} status."
        )

    async def set_error(
        self, error_code: Optional[ErrorCodes] = None, action: Optional[Action] = None
    ):
        """
        Sets the error status and error code for the given action.

        Args:
            error_code (ErrorCodes, optional): The error code to set. Defaults to None.
            action (Action, optional): The action to update. Defaults to None, in which case self.action is used.

        Side Effects:
            - Appends HloStatus.errored to the experiment_status of the action.
            - Sets the error_code of the action to the provided error_code or ErrorCodes.unspecified if not provided.
            - Prints an error message with the action's UUID and name.

        """
        if action is None:
            action = self.action
        action.experiment_status.append(HloStatus.errored)

        if error_code:
            action.error_code = error_code
        else:
            action.error_code = ErrorCodes.unspecified

        LOGGER.error(f"ERROR {str(action.action_uuid)} on {action.action_name} status.")

    async def get_realtime(
        self, epoch_ns: Optional[float] = None, offset: Optional[float] = None
    ) -> float:
        """
        Asynchronously retrieves the real-time value.

        Args:
            epoch_ns (float, optional): The epoch time in nanoseconds. Defaults to None.
            offset (float, optional): The offset to be applied to the real-time value. Defaults to None.

        Returns:
            float: The real-time value with the applied offset.
        """
        return self.base.get_realtime_nowait(epoch_ns=epoch_ns, offset=offset)

    def get_realtime_nowait(
        self, epoch_ns: Optional[float] = None, offset: Optional[float] = None
    ) -> float:
        """
        Retrieve the current real-time value without waiting.

        Args:
            epoch_ns (float, optional): The epoch time in nanoseconds. Defaults to None.
            offset (float, optional): The offset to be applied to the epoch time. Defaults to None.

        Returns:
            float: The current real-time value.
        """
        return self.base.get_realtime_nowait(epoch_ns=epoch_ns, offset=offset)

    async def write_live_data(self, output_str: str, file_conn_key: UUID):
        """
        Asynchronously writes a string to a live data file connection.

        Args:
            output_str (str): The string to be written to the file. A newline character
                              will be appended if it is not already present.
            file_conn_key (UUID): The unique identifier for the file connection in the
                                  file connection dictionary.

        Returns:
            None
        """
        if file_conn_key in self.file_conn_dict:
            if self.file_conn_dict[file_conn_key].file:
                if not output_str.endswith("\n"):
                    output_str += "\n"
                await self.file_conn_dict[file_conn_key].file.write(output_str)

    async def enqueue_data_dflt(self, datadict: dict):
        """
        Asynchronously enqueues data using the default file connection key.

        Args:
            datadict (dict): The data dictionary to be enqueued.

        Returns:
            None
        """
        await self.enqueue_data(
            datamodel=DataModel(
                data={self.base.dflt_file_conn_key(): datadict},
                errors=[],
                status=HloStatus.active,
            )
        )

    async def enqueue_data(self, datamodel: DataModel, action: Optional[Action] = None):
        """
        Asynchronously enqueues data into the data queue.

        Args:
            datamodel (DataModel): The data model instance containing the data to be enqueued.
            action (Action, optional): The action associated with the data. If not provided,
                                       the default action will be used.

        Returns:
            None
        """
        if action is None:
            action = self.action
        await self.base.data_q.put(
            self.assemble_data_msg(datamodel=datamodel, action=action)
        )
        if datamodel.data:
            self.num_data_queued += 1

    def enqueue_data_nowait(
        self, datamodel: DataModel, action: Optional[Action] = None
    ):
        """
        Enqueues a data message into the queue without waiting.

        Args:
            datamodel (DataModel): The data model to be enqueued.
            action (Action, optional): The action associated with the data. Defaults to None.

        Raises:
            queue.Full: If the queue is full and the data cannot be enqueued.

        Notes:
            If `action` is not provided, the method uses the instance's `self.action`.
            Increments `self.num_data_queued` if `datamodel.data` is not empty.
        """
        if action is None:
            action = self.action
        self.base.data_q.put_nowait(
            self.assemble_data_msg(datamodel=datamodel, action=action)
        )
        if datamodel.data:
            self.num_data_queued += 1

    def assemble_data_msg(
        self, datamodel: DataModel, action: Optional[Action] = None
    ) -> DataPackageModel:
        """
        Assembles a data message package from the given data model and action.

        Args:
            datamodel (DataModel): The data model containing the data to be packaged.
            action (Action, optional): The action associated with the data. If not provided,
                                       the default action of the instance will be used.

        Returns:
            DataPackageModel: A data package model containing the action UUID, action name,
                              data model, and any errors from the data model.
        """
        if action is None:
            action = self.action
        return DataPackageModel(
            action_uuid=action.action_uuid,
            action_name=action.action_name,
            datamodel=datamodel,
            errors=datamodel.errors,
        )

    def add_new_listen_uuid(self, new_uuid: UUID):
        """
        Adds a new UUID to the listen_uuids list.

        Args:
            new_uuid (UUID): The new UUID to be added to the list.
        """
        self.listen_uuids.append(new_uuid)

    def _get_action_for_file_conn_key(self, file_conn_key: UUID):
        """
        Retrieve the action associated with a given file connection key.

        Args:
            file_conn_key (UUID): The unique identifier for the file connection key.

        Returns:
            Action or None: The action associated with the given file connection key,
                            or None if no matching action is found.
        """
        output_action = None
        for action in self.action_list:
            if file_conn_key in action.file_conn_keys:
                output_action = action
                break
        return output_action

    async def log_data_set_output_file(self, file_conn_key: UUID):
        """
        Asynchronously logs data and sets up an output file for a given file connection key.

        Args:
            file_conn_key (UUID): The unique identifier for the file connection.

        Returns:
            None

        This method performs the following steps:
        1. Logs the creation of a file for the given file connection key.
        2. Retrieves the action associated with the file connection key.
        3. Adds missing information to the header if necessary.
        4. Initializes the data file with the appropriate header and metadata.
        5. Creates the output file and sets up the file connection.
        6. Writes the header to the new file if it exists.
        """

        LOGGER.info(f"creating file for file conn: {file_conn_key}")

        # get the action for the file_conn_key
        output_action = self._get_action_for_file_conn_key(file_conn_key=file_conn_key)

        if output_action is None:
            LOGGER.error("data LOGGER could not find action for file_conn_key")
            return

        # add some missing information to the hloheader
        if output_action.action_abbr is not None:
            self.file_conn_dict[file_conn_key].params.hloheader.action_name = (
                output_action.action_abbr
            )
        else:
            self.file_conn_dict[file_conn_key].params.hloheader.action_name = (
                output_action.action_name
            )

        self.file_conn_dict[file_conn_key].params.hloheader.column_headings = (
            self.file_conn_dict[file_conn_key].params.json_data_keys
        )
        # epoch_ns should have been set already
        # else we need to add it now because the header is now written
        # before data can be added to the file
        if self.file_conn_dict[file_conn_key].params.hloheader.epoch_ns is None:
            LOGGER.info("realtime_ns was not set, adding it now.")
            self.file_conn_dict[file_conn_key].params.hloheader.epoch_ns = (
                self.get_realtime_nowait()
            )

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
        save_root = str(self.base.helaodirs.save_root)
        if self.action.manual_action:
            save_root = save_root.replace("RUNS_ACTIVE", "RUNS_DIAG")
        output_path = os.path.join(save_root, output_action.action_output_dir)
        output_file = os.path.join(output_path, filename)

        os.makedirs(output_path, exist_ok=True)

        LOGGER.info(f"writing data to: {output_file}")
        # create output file and set connection
        self.file_conn_dict[file_conn_key].file = await aiofiles.open(
            output_file, mode="a+"
        )

        if header:
            LOGGER.info("adding header to new file")
            if not header.endswith("\n"):
                header += "\n"
            await self.file_conn_dict[file_conn_key].file.write(header)

    async def log_data_task(self):
        """
        Asynchronous task to log data messages from a data queue.

        This method subscribes to a data queue and processes incoming data messages.
        It checks if data logging is enabled, verifies the status of the data, and
        writes the data to the appropriate output files.

        The method handles the following:
        - Subscribes to the data queue.
        - Filters data messages based on action UUIDs.
        - Checks the status of the data and skips messages with certain statuses.
        - Retrieves the appropriate action for each data message.
        - Creates output files if they do not exist.
        - Writes data to the output files in JSON format or as raw data.
        - Handles errors and exceptions during the logging process.

        Exceptions:
            asyncio.CancelledError: Raised when the task is cancelled.
            Exception: Catches all other exceptions and logs the error message and traceback.

        Returns:
            None
        """
        if not self.action.save_data:
            LOGGER.info("data writing disabled")
            return

        # self.base.print_message(
        #     f"starting data LOGGER for active action: {self.action.action_uuid}",
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

                if data_status not in (None, HloStatus.active):
                    LOGGER.info(
                        f"data_stream: skipping package for status: {data_status}"
                    )
                    continue

                for file_conn_key, sample_data in data_dict.items():
                    output_action = self._get_action_for_file_conn_key(
                        file_conn_key=file_conn_key
                    )
                    if output_action is None:
                        LOGGER.error(
                            "data LOGGER could not find action for file_conn_key"
                        )
                        continue

                    if file_conn_key not in self.file_conn_dict:
                        if output_action.save_data:
                            LOGGER.warning(
                                f"'{file_conn_key}' does not exist in file_conn '{self.file_conn_dict}'."
                            )
                        else:
                            # got data but saving is disabled,
                            # e.g. no file was created,
                            # e.g. file_conn_key is not in self.file_conn_dict
                            LOGGER.info(
                                "data logging is disabled for action '{output_action.action_name}'"
                            )

                        continue

                    # check if we need to create the file first
                    if self.file_conn_dict[file_conn_key].file is None:
                        if not self.file_conn_dict[file_conn_key].params.json_data_keys:
                            jsonkeys = [key for key in sample_data.keys()]
                            LOGGER.info(
                                "no json_data_keys defined, using keys from first data message: {jsonkeys[:10]}"
                            )

                            self.file_conn_dict[file_conn_key].params.json_data_keys = (
                                jsonkeys
                            )

                        LOGGER.info(f"creating output file for {file_conn_key}")
                        # create the file for this data stream
                        await self.log_data_set_output_file(file_conn_key=file_conn_key)

                    # write only data if the file connection is open
                    if self.file_conn_dict[file_conn_key].file:
                        # check if separator was already written
                        # else add it
                        if not self.file_conn_dict[file_conn_key].added_hlo_separator:
                            self.file_conn_dict[file_conn_key].added_hlo_separator = (
                                True
                            )
                            await self.write_live_data(
                                output_str="%%\n",
                                file_conn_key=file_conn_key,
                            )

                        if isinstance(sample_data, dict):
                            try:
                                output_str = json.dumps(sample_data)
                            except TypeError:
                                LOGGER.error("Data is not json serializable.")
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
                        LOGGER.error("output file closed?")
                if data_dict:
                    self.num_data_written += 1

        except asyncio.CancelledError:
            LOGGER.info("removing data_q subscription for active")
            if dq_sub in self.base.data_q.subscribers:
                self.base.data_q.remove(dq_sub)
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            LOGGER.error(f"data LOGGER task failed with error: {repr(e), tb,}")

    async def write_file(
        self,
        output_str: str,
        file_type: str,
        filename: Optional[str] = None,
        file_group: HloFileGroup = HloFileGroup.aux_files,
        header: Optional[str] = None,
        sample_str: Optional[str] = None,
        file_sample_label: Optional[List[str] | str] = None,
        json_data_keys: Optional[str] = None,
        action: Optional[Action] = None,
    ):
        """
        Asynchronously writes a string to a file with specified parameters.

        Parameters:
        -----------
        output_str : str
            The string content to be written to the file.
        file_type : str
            The type of the file to be written.
        filename : str, optional
            The name of the file. If not provided, a default name will be used.
        file_group : HloFileGroup, optional
            The group to which the file belongs. Default is HloFileGroup.aux_files.
        header : str, optional
            The header content to be written at the beginning of the file.
        sample_str : str, optional
            A sample string related to the file content.
        file_sample_label : str, optional
            A label for the file sample.
        json_data_keys : str, optional
            JSON data keys related to the file content.
        action : Action, optional
            The action context in which the file is being written. If not provided,
            the current action context will be used.

        Returns:
        --------
        str or None
            The path to the written file if the action's save_data attribute is True,
            otherwise None.

        Notes:
        ------
        - The method ensures the output directory exists before writing the file.
        - Handles different OS path conventions (Windows and POSIX).
        - Writes the header and output string to the file, separated by '%%\n'.
        """
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
            save_root = str(self.base.helaodirs.save_root)
            if action.manual_action:
                save_root = save_root.replace("RUNS_ACTIVE", "RUNS_DIAG")
            output_path = os.path.join(save_root, action.action_output_dir)
            output_file = os.path.join(output_path, file_info.file_name)
            if os.name == "nt":
                output_file = str(pathlib.PureWindowsPath(output_file))
            elif os.name == "posix":
                output_file = str(
                    pathlib.PurePosixPath(pathlib.PureWindowsPath(output_file))
                ).strip("\\")
            else:
                LOGGER.info("could not detect OS, path seps may be mixed")

            os.makedirs(output_path, exist_ok=True)

            LOGGER.info(f"writing non stream data to: {output_file}")

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
        file_group: HloFileGroup = HloFileGroup.aux_files,
        header: Optional[str] = None,
        sample_str: Optional[str] = None,
        file_sample_label: Optional[List[str] | str] = None,
        json_data_keys: Optional[str] = None,
        action: Optional[Action] = None,
    ):
        """
        Writes a file asynchronously without waiting for the operation to complete.

        Args:
            output_str (str): The string content to be written to the file.
            file_type (str): The type of the file to be written.
            filename (str, optional): The name of the file. Defaults to None.
            file_group (HloFileGroup, optional): The group to which the file belongs. Defaults to HloFileGroup.aux_files.
            header (str, optional): The header content to be written at the beginning of the file. Defaults to None.
            sample_str (str, optional): The sample string associated with the file. Defaults to None.
            file_sample_label (str, optional): The label for the file sample. Defaults to None.
            json_data_keys (str, optional): The JSON data keys associated with the file. Defaults to None.
            action (Action, optional): The action associated with the file writing operation. Defaults to None.

        Returns:
            str: The path to the written file if the action's save_data attribute is True, otherwise None.
        """
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
            save_root = str(self.base.helaodirs.save_root)
            if action.manual_action:
                save_root = save_root.replace("RUNS_ACTIVE", "RUNS_DIAG")
            output_path = os.path.join(save_root, action.action_output_dir)
            output_file = os.path.join(output_path, file_info.file_name)
            if os.name == "nt":
                output_file = str(pathlib.PureWindowsPath(output_file))
            elif os.name == "posix":
                output_file = str(
                    pathlib.PurePosixPath(pathlib.PureWindowsPath(output_file))
                ).strip("\\")
            else:
                LOGGER.info("could not detect OS, path seps may be mixed")

            os.makedirs(output_path, exist_ok=True)
            LOGGER.info(f"writing non stream data to: {output_file}")
            with open(output_file, mode="a+") as f:
                if header:
                    f.write(header)
                f.write("%%\n")
                f.write(output_str)
                action.files.append(file_info)
                return output_file
        else:
            return None

    def set_sample_action_uuid(
        self,
        sample: Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample],
        action_uuid: UUID,
    ):
        """
        Sets the action UUID for a given sample and its parts if the sample is of type 'assembly'.

        Args:
            sample (Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]): The sample object for which the action UUID is to be set.
            action_uuid (UUID): The action UUID to be assigned to the sample.

        Returns:
            None
        """
        sample.action_uuid = [action_uuid]
        if sample.sample_type == SampleType.assembly:
            for part in sample.parts:
                self.set_sample_action_uuid(sample=part, action_uuid=action_uuid)

    async def append_sample(
        self,
        samples: List[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ],
        IO: str,
        action: Optional[Action] = None,
    ):
        """
                Append samples to the specified action's input or output list.

                Args:
                    samples (List[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ]): A list of samples to be appended.
                    IO (str): Specifies whether the samples are to be appended to the input ('in') or output ('out') list.
                    action (Action, optional): The action to which the samples will be appended. If not provided, the current action is used.

                Returns:
                    None

                Notes:
                    - If the `samples` list is empty, the function returns immediately.
                    - Samples of type `NoneSample` are skipped.
                    - The `action_uuid` of each sample is updated to the current action's UUID.
                    - If a sample's inheritance is `None`, it is set to `SampleInheritance.allow_both`.
                    - If a sample's status is `None`, it is set to `[SampleStatus.preserved]`.
                    - The function broadcasts the status when a sample is added for operator table updates.
        """
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
                LOGGER.info("sample.inheritance is None. Using 'allow_both'.")
                sample.inheritance = SampleInheritance.allow_both

            if not sample.status:
                LOGGER.info("sample.status is None. Using '{SampleStatus.preserved}'.")
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
        """
        Asynchronously splits and keeps active.

        This method calls the `split` method with an empty `uuid_list`.

        Returns:
            None
        """
        await self.split(uuid_list=[])

    async def split_and_finish_prev_uuids(self):
        """
        Asynchronously splits and finishes previous UUIDs.

        This method calls the `split` method with `uuid_list` set to None,
        which processes and finalizes any previous UUIDs.

        Returns:
            None
        """
        await self.split(uuid_list=None)

    async def finish_all(self):
        await self.finish(finish_uuid_list=None)

    async def split(
        self,
        uuid_list: Optional[List[UUID]] = None,
        new_fileconnparams: Optional[FileConnParams] = None,
    ) -> List[UUID]:
        """
        Splits the current action into a new action, creating new file connections
        and updating the action status accordingly.

        Args:
            uuid_list (Optional[List[UUID]]): List of UUIDs to finish. If None, all actions except the current one will be finished.
            new_fileconnparams (Optional[FileConnParams]): Parameters for the new file connection. If None, the previous file connection parameters will be used.

        Returns:
            List[UUID]: List of new file connection keys.

        Raises:
            Exception: If the split operation fails.
        """

        try:
            new_file_conn_keys = []

            LOGGER.info("got split action request")
            # add split status to current action
            if HloStatus.split not in self.action.action_status:
                self.action.action_status.append(HloStatus.split)
            # make a copy of prev_action
            prev_action = deepcopy(self.action)
            prev_action_list = deepcopy(self.action_list)
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
            self.action_list += prev_action_list
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
                LOGGER.info("Creating new file_conn for split action")
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
                self.action.file_conn_keys = [
                    new_file_conn.params.file_conn_key
                ] + self.action.file_conn_keys
                self.num_data_queued = 0
                self.num_data_written = 0

            # TODO:
            # update other action settings?
            # - sample name

            # # prepend new action to previous action list
            # self.action_list.append(prev_action)

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
        except Exception:
            LOGGER.error("Active.split() failed", exc_info=True)

        return new_file_conn_keys

    async def substitute(self):
        for filekey in self.file_conn_dict:
            if self.file_conn_dict[filekey].file:
                await self.file_conn_dict[filekey].file.close()

    async def finish(
        self,
        finish_uuid_list: Optional[List[UUID]] = None,
        # end_state: HloStatus = HloStatus.finished
    ) -> Action:
        """
        Finish the actions specified by the given UUIDs or finish all actions if no UUIDs are provided.

        This method updates the status of the specified actions to `finished`, sends global parameters if required,
        and ensures that all actions are properly finalized. It also handles the closing of data streams and files,
        updates the database, and processes any queued actions.

        Args:
            finish_uuid_list (List[UUID], optional): A list of UUIDs of the actions to be finished. If None, all actions will be finished.

        Returns:
            Action: The most recent action of the active.

        Raises:
            Exception: If any error occurs during the finishing process.
        """
        if finish_uuid_list is None:
            finish_uuid_list = [action.action_uuid for action in self.action_list]

        for action in self.action_list:
            if action.action_uuid not in finish_uuid_list:
                continue
            if HloStatus.finished in action.action_status:
                continue

            try:
                # set status to finish
                # (replace active with finish)
                self.base.replace_status(
                    status_list=action.action_status,
                    old_status=HloStatus.active,
                    new_status=HloStatus.finished,
                )

                if action.error_code != ErrorCodes.none:
                    if HloStatus.errored not in action.action_status:
                        action.action_status.append(HloStatus.errored)

                # send globalparams
                if action.to_global_params:
                    export_params = {}
                    if isinstance(action.to_global_params, list):
                        for k in action.to_global_params:
                            if k in action.action_params:
                                LOGGER.info(f"updating {k} in orch global vars")
                                export_params[k] = action.action_params[k]
                            elif k in action.action_output:
                                LOGGER.info(f"updating {k} in orch global vars")
                                export_params[k] = action.action_output[k]
                            else:
                                LOGGER.info(
                                    f"key {k} not found in action output or params"
                                )
                    elif isinstance(action.to_global_params, dict):
                        for k1, k2 in action.to_global_params.items():
                            if k1 in action.action_params:
                                LOGGER.info(f"updating {k2} in global vars")
                                export_params[k2] = action.action_params[k1]
                            elif k1 in action.action_output:
                                LOGGER.info(f"updating {k2} in global vars")
                                export_params[k2] = action.action_output[k1]
                            else:
                                LOGGER.info(
                                    f"key {k1} not found in action output or params"
                                )
                    _, error_code = await async_private_dispatcher(
                        server_key=action.orch_key,
                        host=action.orch_host,
                        port=action.orch_port,
                        private_action="update_global_params",
                        json_dict=export_params,
                    )
                    if error_code == ErrorCodes.none:
                        LOGGER.info("Successfully updated global params.")
            except Exception:
                LOGGER.error(
                    f"Failed to update global params for action {action.action_uuid}",
                    exc_info=True,
                )

        # check if all actions are fininshed
        # if yes close dataLOGGER etc
        all_finished = True
        for action in self.action_list:
            if HloStatus.finished not in action.action_status:
                # at least one is not finished
                all_finished = False
                break

        if all_finished:
            LOGGER.info("finish active: sending finish data_stream_status package")
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
                try:
                    await self.enqueue_data(
                        datamodel=DataModel(
                            data={}, errors=[], status=HloStatus.finished
                        )
                    )
                    LOGGER.info(
                        f"Waiting for data_stream finished package: {[action.data_stream_status for action in self.action_list]}"
                    )
                    await asyncio.sleep(0.1)
                except Exception:
                    LOGGER.error(
                        "Failed to enqueue finished data stream package",
                        exc_info=True,
                    )
                retry_counter += 1

            LOGGER.info("checking if all queued data has written.")
            write_retries = 5
            write_iter = 0
            while (
                self.num_data_queued > self.num_data_written
                and write_iter < write_retries
            ):
                try:
                    LOGGER.info(
                        f"num_queued {self.num_data_queued} > num_written {self.num_data_written}, sleeping for 0.1 second."
                    )
                    for action in self.action_list:
                        if action.data_stream_status != HloStatus.active:
                            await self.enqueue_data(
                                datamodel=DataModel(
                                    data={}, errors=[], status=HloStatus.finished
                                )
                            )
                            LOGGER.info(
                                f"Setting datastream to finished: {action.data_stream_status}"
                            )
                except Exception:
                    LOGGER.error(
                        "Failed to requeue finished data stream package",
                        exc_info=True,
                    )
                write_iter += 1
                await asyncio.sleep(0.1)

            try:
                # self.action_list[-1] is the very first action
                if self.action_list[-1].manual_action:
                    await self.finish_manual_action()

                # all actions are finished
                LOGGER.info("finishing data logging.")
                for filekey in self.file_conn_dict:
                    if self.file_conn_dict[filekey].file:
                        await self.file_conn_dict[filekey].file.close()
                self.file_conn_dict = {}

                # finish the data writer
                self.data_logger.cancel()
            except Exception:
                LOGGER.error("Failed to finish data logging", exc_info=True)

            save_root = str(self.base.helaodirs.save_root)
            if self.action.manual_action:
                save_root = save_root.replace("RUNS_ACTIVE", "RUNS_DIAG")
            try:
                # call custom hlo post-processor if it exists
                if self.base.hlo_postprocessor is not None:
                    loop = asyncio.get_running_loop()
                    postprocessor = self.base.hlo_postprocessor(self.action, save_root)
                    updated_file_list = await loop.run_in_executor(
                        None, postprocessor.process
                    )
                    self.action.files = updated_file_list
            except Exception:
                LOGGER.error("Failed to run custom HLO post-processor", exc_info=True)
            try:
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
            except Exception:
                LOGGER.error(
                    "Failed to remove active from base.actives or last_10_active",
                    exc_info=True,
                )

            LOGGER.info("all active action are done, closing active")

            # DB server call to finish_yml if DB exists
            for action in self.action_list:
                try:
                    # write final act meta file (overwrite existing one)
                    await self.base.write_act(action=action)
                except Exception:
                    LOGGER.error(
                        f"Failed to write act meta file for action {action.action_uuid}",
                        exc_info=True,
                    )
                try:
                    # send the last status
                    await self.add_status(action=action)
                except Exception:
                    LOGGER.error(
                        f"Failed to send last status for action {action.action_uuid}",
                        exc_info=True,
                    )
                if not self.action.manual_action:
                    try:
                        self.base.aloop.create_task(move_dir(action, base=self.base))
                        # pop from local action task queue
                    except Exception:
                        LOGGER.error(
                            f"Failed to move directory for action {action.action_uuid}",
                            exc_info=True,
                        )
                else:
                    LOGGER.info(
                        f"Action {action.action_uuid} is a manual action, skipping directory move."
                    )
                if action.action_uuid in self.base.local_action_task_queue:
                    self.base.local_action_task_queue.remove(action.action_uuid)

        return self.action

    async def track_file(
        self,
        file_type: str,
        file_path: str,
        samples: List[
            Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ],
        action: Optional[Action] = None,
    ) -> None:
        """
                Tracks a file by adding its information to the associated action.

                Args:
                    file_type (str): The type of the file being tracked.
                    file_path (str): The path to the file being tracked.
                    samples (List[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]
        ]): A list of samples associated with the file.
                    action (Action, optional): The action associated with the file. If not provided,
                                               the current action will be used.

                Returns:
                    None
        """
        if action is None:
            action = self.action
        save_root = str(self.base.helaodirs.save_root)
        if action.manual_action:
            save_root = save_root.replace("RUNS_ACTIVE", "RUNS_DIAG")
        if os.path.dirname(file_path) != os.path.join(
            save_root, action.action_output_dir
        ):
            action.aux_file_paths.append(file_path)

        file_info = FileInfo(
            file_type=file_type,
            file_name=os.path.basename(file_path),
            # data_keys = json_data_keys,
            sample=[sample.get_global_label() for sample in samples],
            action_uuid=action.action_uuid,
            run_use=action.run_use,
        )

        action.files.append(file_info)
        LOGGER.info(f"{file_info.file_name} added to files_technique / aux_files list.")

    async def relocate_files(self):
        """
        Asynchronously relocates files from their current locations to new paths.

        This method iterates over the file paths listed in `self.action.aux_file_paths`
        and moves each file to a new directory specified by combining `self.base.helaodirs.save_root`
        and `self.action.action_output_dir`. If the source path and the new path are different,
        the file is copied to the new location using `async_copy`.

        Returns:
            None
        """
        save_root = str(self.base.helaodirs.save_root)
        if self.action.manual_action:
            save_root = save_root.replace("RUNS_ACTIVE", "RUNS_DIAG")
        for x in self.action.aux_file_paths:
            new_path = os.path.join(
                save_root,
                self.action.action_output_dir,
                os.path.basename(x),
            )
            if x != new_path:
                await async_copy(x, new_path)

    async def finish_manual_action(self):
        """
        Finalizes the most recent manual action in the action list.

        This method checks if the most recent action in the action list is a manual action.
        If it is, it creates a deep copy of the action and updates its status to finished.
        It then clears the samples and files associated with the action.

        The method proceeds to add all actions in the action list to the experiment model
        and adds the experiment to the sequence model. Finally, it writes the experiment
        and sequence metadata files for the manual operation.

        Returns:
            None
        """
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
                exp.dispatched_actions.append(action.get_act())

            # add experiment to sequence
            exp.dispatched_experiments.append(action.get_exp())

            # this will write the correct
            # sequence and experiment meta files for
            # manual operation
            # create and write exp file for manual action
            await self.base.write_exp(exp)
            # create and write seq file for manual action
            await self.base.write_seq(exp)

    async def send_nonblocking_status(self, retry_limit: int = 3):
        """
        Sends a non-blocking status update to all clients in `self.base.status_clients`.

        This method attempts to send a status update to each client up to `retry_limit` times.
        If the update is successful, a success message is printed. If the update fails after
        the specified number of retries, an error message is printed.

        Args:
            retry_limit (int): The maximum number of retry attempts for sending the status update.
                               Defaults to 3.

        Returns:
            None
        """
        for combo_key in self.base.status_clients:
            client_servkey, client_host, client_port = combo_key
            LOGGER.info(
                f"executor trying to send non-blocking status to {client_servkey}."
            )
            success = False
            for _ in range(retry_limit):
                response, error_code = await self.base.send_nbstatuspackage(
                    client_servkey=client_servkey,
                    client_host=client_host,
                    client_port=client_port,
                    actionmodel=self.action.get_act(),
                )

                if response.get("success", False) and error_code == ErrorCodes.none:
                    success = True
                    break

            if success:
                LOGGER.info(
                    f"Attached {client_servkey} to status ws on {self.base.server.server_name}."
                )
            else:
                LOGGER.error(
                    f"failed to attach {client_servkey} to status ws on {self.base.server.server_name} after {retry_limit} attempts."
                )

    async def action_loop_task(self, executor: Executor):
        """
        Asynchronous task that manages the execution of an action loop.

        This method handles the lifecycle of an action, including pre-execution setup,
        execution, polling for ongoing actions, manual stopping, and post-execution cleanup.
        It also manages the registration and deregistration of executors, and handles
        non-blocking actions.

        Args:
            executor (Executor): The executor responsible for running the action.

        Returns:
            The result of the action's finish method.

        Raises:
            Exception: If any exception occurs during the execution or polling of the action.
        """
        # stall action_loop task if concurrency is not allowed
        while (
            self.base.local_action_task_queue
            and self.base.local_action_task_queue[0] != self.action.action_uuid
            and not executor.concurrent
        ):
            await asyncio.sleep(0.1)

        if self.action.nonblocking:
            await self.send_nonblocking_status()
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

        # shortcut to active exectuors
        LOGGER.info(f"Registering exec_id: '{executor.exec_id}' with server")
        self.base.executors[executor.exec_id] = self

        # action operations
        LOGGER.info("Running executor._exec() method")
        try:
            result = await executor._exec()
        except Exception:
            LOGGER.error("Executor._exec() failed", exc_info=True)
            result = {}
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
            LOGGER.info("entering executor polling loop")
            while self.action_loop_running:
                try:
                    result = await executor._poll()
                except Exception:
                    LOGGER.error("Executor._poll() failed", exc_info=True)
                    result = {}
                # LOGGER.info(f"got result: {result}")
                error = result.get("error", ErrorCodes.none)
                status = result.get("status", HloStatus.finished)
                data = result.get("data", {})
                if data:
                    # LOGGER.info(f"got data from poll iter: {data}")
                    datamodel = DataModel(
                        data={self.action.file_conn_keys[0]: data},
                        errors=[],
                        status=HloStatus.active,
                    )
                    self.enqueue_data_nowait(datamodel)  # write and broadcast

                if status == HloStatus.active:
                    await asyncio.sleep(executor.poll_rate)
                else:
                    LOGGER.info("exiting executor polling loop")
                    self.action_loop_running = False

        if error != ErrorCodes.none:
            self.action.error_code = error
        self.action_loop_running = False

        # in case of manual stop, perform driver operations
        if self.manual_stop:
            result = await executor._manual_stop()
            error = result.get("error", {})
            if error != ErrorCodes.none:
                LOGGER.info("Error encountered during manual stop.")

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
            LOGGER.info("Error encountered during executor cleanup.")

        _ = self.base.executors.pop(executor.exec_id)
        retval = await self.finish()
        if self.action.nonblocking:
            await self.send_nonblocking_status()
        return retval

    def stop_action_task(self):
        """
        Stops the current action task.

        This method sets the `manual_stop` flag to True and stops the action loop
        by setting `action_loop_running` to False. It also logs a message indicating
        that a stop action request has been received.
        """
        LOGGER.info("Stop action request received. Stopping poll.")
        self.manual_stop = True
        self.action_loop_running = False


class DummyBase:
    """
    A dummy base class for demonstration purposes.

    Attributes:
        live_buffer (dict): A dictionary to store live buffer data.
        actionservermodel (ActionServerModel): An instance of ActionServerModel.

    Methods:
        __init__(): Initializes the DummyBase instance.
        print_message(message: str): Prints a message with a dummy server name.
        async put_lbuf(message: dict): Asynchronously updates the live buffer with the given message.
        get_lbuf(buf_key: str): Retrieves the value and timestamp from the live buffer for the given key.
    """

    def __init__(self) -> None:
        """
        Initializes the base server with default settings.

        Attributes:
            live_buffer (dict): A dictionary to store live data.
            actionservermodel (ActionServerModel): An instance of ActionServerModel initialized with a dummy server and machine name, and a unique action UUID.
        """
        self.live_buffer = {}
        self.actionservermodel = ActionServerModel(
            action_server=MachineModel(server_name="DUMMY", machine_name="dummyhost"),
            last_action_uuid=uuid1(),
        )

    def print_message(self, message: str) -> None:
        """
        Prints a message to the console.

        Args:
            message (str): The message to be printed.
        """
        print_message(LOGGER, "DUMMY", message)

    async def put_lbuf(self, message: dict) -> None:
        """
        Updates the live buffer with the provided message.

        Args:
            message (dict): A dictionary containing key-value pairs to be added to the live buffer.
        """
        now = time()
        for k, v in message:
            self.live_buffer[k] = (v, now)

    def get_lbuf(self, buf_key: str) -> tuple:
        """
        Retrieve the value and timestamp from the live buffer for a given key.

        Args:
            buf_key (str): The key to look up in the live buffer.

        Returns:
            tuple: A tuple containing the value and timestamp associated with the given key.
        """
        buf_val, buf_ts = self.live_buffer[buf_key]
        return buf_val, buf_ts
