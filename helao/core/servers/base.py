"""Core action-server runtime: the ``Base`` controller, ``Active`` action wrapper,
and supporting helpers (status WebSockets, NTP-corrected timestamps, HLO file
writers, executor lifecycle, sample bookkeeping, action splitting).

The module also exposes ``ActiveParams`` (re-exported from
``helao.helpers.active_params``) and a ``DummyBase`` for code paths that need a
lightweight stand-in for the live controller.
"""

__all__ = ["Base", "ActiveParams", "Active", "DummyBase"]

from helao.helpers import helao_logging as logging

from importlib.util import spec_from_file_location
from importlib.util import module_from_spec
from importlib.machinery import SourceFileLoader

import asyncio
import json
import os
import sys
import pickle
import pathlib
from socket import gethostname
from time import time, time_ns, sleep, perf_counter_ns
from typing import List, Dict, Optional, Union
from uuid import UUID, uuid1
from glob import glob
import hashlib
from copy import deepcopy, copy
import traceback

import aiodebug.hang_inspection
import aiodebug.log_slow_callbacks
import aiofiles
import colorama
import numpy as np
import pyzstd

from fastapi import WebSocket
from fastapi.dependencies.utils import get_flat_params

from helao.helpers.server_api import HelaoFastAPI
from helao.helpers.dispatcher import async_private_dispatcher, async_action_dispatcher
from helao.helpers.executor import Executor
from helao.helpers.helao_dirs import helao_dirs
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.helao_logging import print_message
from helao.helpers import async_copy
from helao.helpers.yml_tools import yml_dumps
from helao.helpers.yml_tools import move_dir
from helao.helpers.premodels import Action, Experiment, Sequence
from helao.core.models.action_start_condition import ActionStartCondition as ASC
from helao.helpers.ws_utils import WsPublisher
from helao.helpers.time_utils import set_time
from helao.helpers.time_utils import read_saved_offset
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
from helao.core.error import ErrorCodes
from helao.helpers import config_loader
from helao.helpers.processors import HloPostProcessor
from helao.helpers.dequedict import DequeDict

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
CONFIG = config_loader.CONFIG

# ANSI color codes converted to the Windows versions
# strip colors if stdout is redirected
colorama.init(strip=not sys.stdout.isatty())


class Timer:
    """Monotonic time source that returns nanoseconds aligned to the wall clock."""

    def __init__(self):
        """Capture the offset between the wall clock and the monotonic counter."""
        self._offset_ns = time_ns() - perf_counter_ns()

    def time_ns(self) -> int:
        """Return the current time in nanoseconds derived from the monotonic counter."""
        return self._offset_ns + perf_counter_ns()


class Base:
    """Core runtime controller shared by every HELAO action server.

    Owns the action lifecycle and broadcast plumbing for one FastAPI server:
    indexes registered endpoints, dispatches per-action ``Active`` instances,
    publishes status/data/live updates to subscriber WebSockets and remote
    clients, maintains NTP-corrected timestamps, drives the endpoint and
    per-server action queues, and writes action/experiment/sequence meta files
    plus HLO data files under the configured ``root``.
    """

    # TODO: add world_cfg: dict parameter for BaseAPI to pass config instead of fastapp
    def __init__(self, app: HelaoFastAPI, dyn_endpoints=None):
        """Wire the controller to a running FastAPI app and read the world config.

        Args:
            app: The ``HelaoFastAPI`` instance that owns this controller.
            dyn_endpoints: Optional callable invoked with the app instance to
                register additional endpoints.

        Raises:
            ValueError: If the world config defines no ``root`` directory or
                is missing the ``run_type`` key.
        """

        self.app = app
        self.server = app.server
        self.dyn_endpoints = dyn_endpoints
        self.server_cfg = app.server_cfg
        self.server_params = app.server_params
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
        self.history = DequeDict(maxlen=200)  # store history of active actions (contained)
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

        self.ntp_offset: float = 0.0  # add to system time for correction
        self.ntp_last_sync = None
        self.aiolock = asyncio.Lock()
        self.endpoint_queues = {}
        self.local_action_queue = zdeque([])
        self.fast_urls = []

        self.hlo_postprocessors: List[HloPostProcessor] = []
        self.hlo_postprocess_libs = self.server_cfg.get("hlo_postprocess_libs", [])

        self.import_postprocessors(
            self.hlo_postprocess_libs, self.hlo_postprocessors, HloPostProcessor
        )

        self.ntp_last_sync, self.ntp_offset = read_saved_offset(
            os.path.join(self.helaodirs.log_root, "ntpLastSync.txt")
        )

    def exception_handler(self, loop, context):
        """Log uncaught coroutine exceptions caught by the asyncio event loop.

        Args:
            loop: Event loop reporting the exception.
            context: Mapping with the exception under the ``"exception"`` key.
        """
        LOGGER.error(f"Got exception from coroutine: {context}")
        exc = context.get("exception")
        LOGGER.error(f"{traceback.format_exception(type(exc), exc, exc.__traceback__)}")
        # LOGGER.info("setting E-STOP flag on active actions")
        # for _, active in self.actives.items():
        #     active.set_estop()

    def myinit(self):
        """Start the background tasks for live buffering, status logging, and hang inspection."""
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

        self.bufferer = self.aloop.create_task(self.live_buffer_task())

        self.status_logger = self.aloop.create_task(self.log_status_task())
        if self.server_cfg.get("regular_update", False):
            regular_delay = self.server_cfg.get("regular_update_delay", 10)
            self.regular_updater = self.aloop.create_task(
                self.regular_status_task(regular_delay)
            )

    def dyn_endpoints_init(self):
        """Initialize endpoint status entries via the configured ``dyn_endpoints`` callback."""
        asyncio.gather(self.init_endpoint_status(self.dyn_endpoints))

    def endpoint_queues_init(self):
        """Create a per-endpoint action queue for every action route on this server."""
        for urld in self.fast_urls:
            if urld.get("path", "").strip("/").startswith(self.server.server_name):
                endpoint_name = urld["path"].strip("/").split("/")[-1]
                self.endpoint_queues[endpoint_name] = zdeque([])

    def print_message(self, *args, **kwargs):
        """Forward a log message through the shared HELAO logger.

        Args:
            *args: Positional message arguments passed through to ``print_message``.
            **kwargs: Keyword arguments forwarded to the logger.
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
        """Register every action endpoint with the action-server status model.

        Optionally invokes ``dyn_endpoints(app=self.app)`` first to allow late
        registration of routes.

        Args:
            dyn_endpoints: Optional async callable invoked with the FastAPI app.
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

    def get_endpoint_urls(self) -> list:
        """Return a list of route descriptors (path/name/params) for every endpoint."""
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
                        # "type": (
                        #     str(par.type_).split("'")[1]
                        #     if len(str(par.type_).split("'")) >= 2
                        #     else str(par.type_)
                        # ),
                        # "required": par.required,
                        # "shape": par.shape,
                        # "default": par.default if par.default is not ... else None,
                    }
                    for par in flatParams
                }
                routeD["params"] = paramD
            else:
                routeD["params"] = []
            url_list.append(routeD)
        return url_list

    def _get_action(self) -> Action:
        """Build the per-request ``Action`` from the current ``ACTION_CTX``.

        Reads the ``ActionInvocation`` set by ``ActionAPIRoute``'s wrapper,
        annotates the action with this server's identity, derives action name
        and code hash/path from the endpoint function, and folds any
        ``fast_samples_in`` payload into ``samples_in``.

        Returns:
            The finalized ``Action`` for the current request.
        """
        from helao.core.servers.base_api import ACTION_CTX

        ctx = ACTION_CTX.get()
        if ctx is None:
            LOGGER.error(
                "setup_action called outside an action endpoint context; "
                "returning a blank Action."
            )
            action = Action()
            endpoint_func = None
        else:
            action = ctx.action
            endpoint_func = ctx.endpoint_func

        if endpoint_func is not None:
            try:
                urlname = self.app.url_path_for(endpoint_func.__name__)
                action_name = urlname.strip("/").split("/")[-1]
            except Exception:
                action_name = endpoint_func.__name__
        else:
            action_name = action.action_name or ""

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
                    sample_obj = object_to_sample(sample)
                    if sample_obj.action_uuid is None:
                        sample_obj.action_uuid = action.action_uuid
                    action.samples_in.append(sample_obj)

        if action.action_abbr is None:
            action.action_abbr = action.action_name

        # setting some default values if action was not submitted via orch
        if action.run_type is None:
            action.run_type = self.run_type
            action.orchestrator = MachineModel(
                server_name="MANUAL", machine_name=gethostname().lower()
            )

        if endpoint_func is not None:
            code = endpoint_func.__code__
            action.action_codehash = get_filehash(code.co_filename)
            action.action_codepath = "/".join(
                code.co_filename.replace(os.getcwd(), "")
                .strip("\\")
                .strip("/")
                .split(os.sep)
            )
            action.action_funcname = code.co_name
        return action

    def setup_action(self) -> Action:
        """Return the finalized ``Action`` for the current action-endpoint request."""
        return self._get_action()

    async def setup_and_contain_action(
        self,
        json_data_keys: List[str] = [],
        action_abbr: Optional[str] = None,
        file_type: Optional[str] = None,
        hloheader: Optional[HloHeaderModel] = None,
    ):
        """Build the current request's ``Action`` and wrap it in an ``Active``.

        Args:
            json_data_keys: Column names recorded in the default HLO file connection.
            action_abbr: Optional short abbreviation stored on the action.
            file_type: Optional HLO file type; defaults to ``"<server>_helao__file"``.
            hloheader: Optional HLO header; defaults to a fresh header stamped
                with the current real-time.

        Returns:
            The ``Active`` instance now tracking this action.
        """
        action = self._get_action()
        if action_abbr is not None:
            action.action_abbr = action_abbr
        if file_type is None:
            file_type = f"{self.server.server_name.lower()}_helao__file"
        if hloheader is None:
            hloheader = HloHeaderModel(epoch_ns=self.get_realtime_nowait())
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
        """Register an action as ``Active`` on the server, substituting any prior one with the same UUID.

        Args:
            activeparams: Parameters describing the action to contain.

        Returns:
            The newly created ``Active`` instance for the action.
        """
        if activeparams.action.action_uuid in self.actives:
            await self.actives[activeparams.action.action_uuid].substitute()
        self.actives[activeparams.action.action_uuid] = Active(
            self, activeparams=activeparams
        )
        await self.actives[activeparams.action.action_uuid].myinit()
        cact = copy(self.actives[activeparams.action.action_uuid].action)
        self.history[cact.action_uuid] = cact
        # register action_uuid in local action task queue
        return self.actives[activeparams.action.action_uuid]

    def get_active_info(self, action_uuid: UUID):
        """Return the dict representation of an active action, or ``None`` if not found.

        Args:
            action_uuid: UUID of the active action to look up.
        """
        if action_uuid in self.actives:
            action_dict = self.actives[action_uuid].action.as_dict()
            return action_dict
        else:
            LOGGER.error(f"Specified action uuid {str(action_uuid)} was not found.")
            return None

    async def send_statuspackage(
        self,
        client_servkey: str,
        client_host: str,
        client_port: int,
        action_name: Optional[str] = None,
    ) -> tuple:
        """Send the current action-server model to a remote subscriber.

        Args:
            client_servkey: Service key of the target client.
            client_host: Host of the target client.
            client_port: Port of the target client.
            action_name: Optional endpoint name to restrict the payload.

        Returns:
            ``(response, error_code)`` from the dispatcher.
        """
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
    ) -> tuple:
        """Send a single non-blocking action status update to a remote subscriber.

        Args:
            client_servkey: Service key of the target client.
            client_host: Host of the target client.
            client_port: Port of the target client.
            actionmodel: ``Action`` describing the non-blocking event.

        Returns:
            ``(response, error_code)`` from the dispatcher.
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
    ) -> bool:
        """Register a remote client as a status subscriber and push an initial snapshot.

        Args:
            client_servkey: Service key of the client.
            client_host: Host of the client.
            client_port: Port of the client.
            retry_limit: Number of attempts to deliver the initial status.

        Returns:
            ``True`` if the initial snapshot was delivered, ``False`` otherwise.
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
        """Remove a remote client from this server's status subscriber set."""
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

    async def _ws_relay(
        self,
        websocket: WebSocket,
        queue: MultisubscriberQueue,
        label: str,
        use_as_dict: bool = True,
    ) -> None:
        """Accept ``websocket`` and stream zstd-compressed pickled messages from ``queue`` until disconnect.

        Args:
            websocket: WebSocket connection to serve.
            queue: Source queue providing messages.
            label: Short identifier used in log lines.
            use_as_dict: When True, call ``msg.as_dict()`` before serialising.
        """
        LOGGER.info(f"got new {label} subscriber")
        await websocket.accept()
        sub = queue.subscribe()
        try:
            async for msg in sub:
                payload = msg.as_dict() if use_as_dict else msg
                await websocket.send_bytes(pyzstd.compress(pickle.dumps(payload)))
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            LOGGER.error(
                f"{label.capitalize()} websocket client "
                f"{websocket.client[0]}:{websocket.client[1]} disconnected. "
                f"{repr(e), tb,}"
            )
            if sub in queue.subscribers:
                queue.remove(sub)

    async def ws_status(self, websocket: WebSocket) -> None:
        """Stream compressed status messages over ``websocket`` until the client disconnects."""
        await self._ws_relay(websocket, self.status_q, "status")

    async def ws_data(self, websocket: WebSocket) -> None:
        """Stream compressed data packets over ``websocket`` until the client disconnects."""
        await self._ws_relay(websocket, self.data_q, "data")

    async def ws_live(self, websocket: WebSocket) -> None:
        """Stream compressed live-buffer updates over ``websocket`` until disconnect."""
        await self._ws_relay(websocket, self.live_q, "live_buffer", use_as_dict=False)

    async def live_buffer_task(self):
        """Subscribe to the live queue and fold every published message into ``live_buffer``."""
        LOGGER.info(f"{self.server.server_name} live buffer task created.")
        async for live_msg in self.live_q.subscribe():
            self.live_buffer.update(live_msg)

    @staticmethod
    def _stamp_lbuf_dict(live_dict: dict) -> dict:
        """Wrap each value in a ``(value, now())`` tuple for the live buffer."""
        return {k: (v, time()) for k, v in live_dict.items()}

    async def put_lbuf(self, live_dict: dict) -> None:
        """Timestamp ``live_dict`` and publish it to the live queue (awaited put)."""
        await self.live_q.put(self._stamp_lbuf_dict(live_dict))

    def put_lbuf_nowait(self, live_dict: dict) -> None:
        """Timestamp ``live_dict`` and publish it to the live queue without awaiting."""
        self.live_q.put_nowait(self._stamp_lbuf_dict(live_dict))

    def get_lbuf(self, live_key):
        """Return the most recent ``(value, timestamp)`` tuple stored under ``live_key``."""
        return self.live_buffer[live_key]

    async def regular_status_task(self, delay: float = 10, retry_limit: int = 5):
        """Periodically push the action-server status to every subscribed client."""
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

    async def _dispatch_queued_action(self, action_queue, queue_label: str) -> None:
        """Pop one queued action, redispatch it with ``no_wait``, and requeue on failure.

        Args:
            action_queue: Deque of ``(action, extra_params)`` tuples.
            queue_label: Human-readable label used in log messages.
        """
        qact, qpars = None, {}
        try:
            qact, qpars = action_queue.popleft()
            LOGGER.info(f"{qact.action_name} was previously queued")
            LOGGER.info(f"running queued {qact.action_name}")
            qact.start_condition = ASC.no_wait
            qact.action_params["queued_launch"] = True
            await async_action_dispatcher(self.world_cfg, qact, qpars)
        except Exception:
            LOGGER.error(f"Failed to process {queue_label} queue", exc_info=True)
            if qact is not None:
                LOGGER.info(f"re-queueing {qact.action_name}")
                action_queue.appendleft((qact, qpars))

    async def process_unified_queue(self) -> None:
        """Dispatch the next queued action when the server disallows concurrency."""
        await self._dispatch_queued_action(self.local_action_queue, "local unified")

    async def process_endpoint_queue(self, status_msg: ActionModel) -> None:
        """Dispatch the next queued action for the endpoint that just transitioned status."""
        await self._dispatch_queued_action(
            self.endpoint_queues[status_msg.action_name],
            f"endpoint '{status_msg.action_name}'",
        )

    async def log_status_task(self, retry_limit: int = 5):
        """Subscribe to the status queue, broadcast to subscribers, and drive endpoint/unified queues.

        Args:
            retry_limit: Number of attempts to deliver each status update to a subscriber.
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
                    LOGGER.debug(
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
                LOGGER.debug("all log_status_task messages sent.")

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
        """Signal the status and data queues to terminate and yield long enough to drain them."""
        await self.status_q.put(StopAsyncIteration)
        await self.data_q.put(StopAsyncIteration)
        await asyncio.sleep(1)

    async def get_realtime(
        self, epoch_ns: Optional[int] = None, offset: Optional[float] = None
    ) -> int:
        """Asynchronous wrapper around :meth:`get_realtime_nowait`.

        Args:
            epoch_ns: Optional epoch time in nanoseconds; defaults to now.
            offset: Optional clock offset in seconds; defaults to ``ntp_offset``.

        Returns:
            NTP-corrected wall-clock time in nanoseconds.
        """
        return self.get_realtime_nowait(epoch_ns=epoch_ns, offset=offset)

    def get_realtime_nowait(
        self, epoch_ns: Optional[int] = None, offset: Optional[float] = None
    ) -> int:
        """Return the wall-clock time in nanoseconds, optionally with a custom offset.

        Args:
            epoch_ns: Optional epoch time in nanoseconds; defaults to now.
            offset: Optional clock offset in seconds; defaults to ``ntp_offset``.

        Returns:
            NTP-corrected wall-clock time in nanoseconds.
        """
        if offset is None:
            if self.ntp_offset is not None:
                offset_ns = int(np.floor(self.ntp_offset * 1e9))
            else:
                offset_ns = 0
        else:
            offset_ns = int(np.floor(offset * 1e9))
        if epoch_ns is None:
            timer = Timer()
            real_time = timer.time_ns() + offset_ns
        else:
            real_time = epoch_ns + offset_ns
        return int(np.floor(real_time))

    async def shutdown(self):
        """Detach all subscribers and cancel the status logger background task."""
        await self.detach_subscribers()
        self.status_logger.cancel()

    async def _write_meta_atomic(self, output_file: str, output_str: str):
        """Atomically write ``output_str`` to ``output_file``.

        Meta writers (``write_act``/``write_exp``/``write_seq``) can be driven
        concurrently for the same file -- e.g. a driver polling loop and the
        action loop both reaching ``finish()``, or a manual action's ``myinit``
        racing its ``finish_manual_action``. A plain ``"w+"`` truncate-then-write
        from two coroutines interleaves at the same offset and yields a torn
        meta file (e.g. a partially copied ``samples_in`` block), and a reader
        (syncer/move_dir) or a crash mid-write can also observe a truncated
        file. Writing to a unique temp file in the same directory and
        ``os.replace()``-ing it in makes the swap atomic: readers only ever see
        a complete file and the last writer wins cleanly.
        """
        if not output_str.endswith("\n"):
            output_str += "\n"
        output_path = os.path.dirname(output_file)
        os.makedirs(output_path, exist_ok=True)
        tmp_file = os.path.join(
            output_path,
            f".{os.path.basename(output_file)}.{uuid1().hex}.tmp",
        )
        async with aiofiles.open(tmp_file, mode="w") as f:
            await f.write(output_str)
        os.replace(tmp_file, output_file)

    async def write_act(self, action: Action):
        """Write the action's metadata to ``<output_dir>/<timestamp>-act.yml`` if ``save_act``.

        Args:
            action: ``Action`` whose metadata should be persisted.
        """
        if action.save_act:
            act_dict = action.get_act().clean_dict()
            save_root = str(self.helaodirs.save_root)
            if action.manual_action:
                save_root = save_root.replace("RUNS_ACTIVE", "RUNS_DIAG")
            output_path = os.path.join(save_root, action.action_output_dir)
            output_file = os.path.join(
                output_path,
                f"{action.action_timestamp.strftime('%y%m%d.%H%M%S%f')}-act.yml",
            )

            LOGGER.info(f"writing to act meta file: {output_path}")

            output_dict = {"file_type": "action"}
            output_dict.update(act_dict)
            await self._write_meta_atomic(output_file, yml_dumps(output_dict))
        else:
            LOGGER.info(
                f"writing meta file for action '{action.action_name}' is disabled."
            )

    async def write_exp(self, experiment: Experiment):
        """Write the experiment's metadata to ``<experiment_dir>/<timestamp>-exp.yml``.

        Args:
            experiment: ``Experiment`` whose metadata should be persisted.
        """
        exp_dict = experiment.get_exp().clean_dict()
        save_root = str(self.helaodirs.save_root)
        if experiment.manual_action:
            save_root = save_root.replace("RUNS_ACTIVE", "RUNS_DIAG")
        output_path = os.path.join(save_root, experiment.get_experiment_dir())
        output_file = os.path.join(
            output_path,
            f"{experiment.experiment_timestamp.strftime('%y%m%d.%H%M%S%f')}-exp.yml",
        )

        LOGGER.info(f"writing to exp meta file: {output_file}")
        output_dict = {"file_type": "experiment"}
        output_dict.update(exp_dict)
        await self._write_meta_atomic(output_file, yml_dumps(output_dict))

    async def write_seq(self, sequence: Sequence):
        """Write the sequence's metadata to ``<sequence_dir>/<timestamp>-seq.yml``.

        Args:
            sequence: ``Sequence`` whose metadata should be persisted.
        """
        seq_dict = sequence.get_seq().clean_dict()
        sequence_dir = sequence.get_sequence_dir()
        save_root = str(self.helaodirs.save_root)
        if sequence.manual_action:
            save_root = save_root.replace("RUNS_ACTIVE", "RUNS_DIAG")
        output_path = os.path.join(save_root, sequence_dir)
        output_file = os.path.join(
            output_path,
            f"{sequence.sequence_timestamp.strftime('%y%m%d.%H%M%S%f')}-seq.yml",
        )

        LOGGER.info(f"writing to seq meta file: {output_file}")
        output_dict = {"file_type": "sequence"}
        output_dict.update(seq_dict)
        await self._write_meta_atomic(output_file, yml_dumps(output_dict))

    def new_file_conn_key(self, key: str) -> UUID:
        """Return a UUID derived from the MD5 hash of ``key``.

        Args:
            key: Arbitrary string used to seed the hash.
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

    def dflt_file_conn_key(self) -> UUID:
        """Return the default file-connection key (``md5(str(None))``)."""
        return self.new_file_conn_key(str(None))

    def replace_status(
        self, status_list: List[HloStatus], old_status: HloStatus, new_status: HloStatus
    ):
        """Swap ``old_status`` for ``new_status`` in ``status_list``, or append if missing."""
        if old_status in status_list:
            idx = status_list.index(old_status)
            status_list[idx] = new_status
        else:
            status_list.append(new_status)

    def get_main_error(self, errors) -> ErrorCodes:
        """Return the first non-``none`` error code, or the input itself if not a list."""
        ret_error = ErrorCodes.none
        if isinstance(errors, list):
            for error in errors:
                if error != ErrorCodes.none:
                    ret_error = error
                    break
        else:
            ret_error = errors

        return ret_error

    def stop_executor(self, executor_id: str) -> dict:
        """Signal a running executor to end its polling loop.

        Args:
            executor_id: Identifier of the executor to stop.

        Returns:
            ``{"signal_stop": True}`` if the executor existed, ``{"signal_stop": False}`` otherwise.
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
        """Stop every running executor whose key starts with ``action_name``.

        Args:
            action_name: Prefix matched against executor keys.
            match_vars: Optional attribute/value pairs that must also be present
                on the executor instance for it to be stopped.
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

    def import_postprocessors(self, name_list, class_list, proc_class):
        """Resolve and append post-processor classes from file paths or deployment names.

        Args:
            name_list: Sequence of file paths or processor-library names.
            class_list: Output list mutated with matching ``proc_class`` subclasses.
            proc_class: Base class that every loaded processor must subclass.
        """
        proc_class_type = (
            proc_class.__name__.split("Post")[0].split("Processor")[0].lower()
        )
        for pplib in name_list:
            mod_name = os.path.basename(pplib).split(".py")[0]
            if pplib.endswith(".py") and os.path.exists(pplib):
                LOGGER.info(f"Loading {proc_class_type} post-processor from {pplib}")
                mod_name = os.path.basename(pplib).split(".py")[0]
                ppclass = SourceFileLoader(mod_name, pplib).load_module().PostProcess
                if issubclass(ppclass, proc_class):
                    class_list.append(ppclass)
            else:
                script_path = None
                LOGGER.info(f"Looking for {pplib} post-processor in deployments")
                deploy_script_path = os.path.join(
                    "helao", "deploy", CONFIG["deployment"], "processors", f"{pplib}.py"
                )
                hte_path = os.path.join(
                    "helao", "deploy", "hte", "processors", f"{pplib}.py"
                )
                any_paths = glob(
                    os.path.join("helao", "deploy", "*", "processors", f"{pplib}.py")
                )
                if os.path.exists(deploy_script_path):
                    script_path = deploy_script_path
                elif os.path.exists(hte_path):
                    script_path = hte_path
                elif len(any_paths) > 0:
                    script_path = any_paths[0]
                if script_path is not None:
                    LOGGER.info(
                        f"Loading {proc_class_type} post-processor from {pplib} processors module"
                    )
                    proc_spec = spec_from_file_location(mod_name, script_path)
                    proc_mod = module_from_spec(proc_spec)
                    proc_spec.loader.exec_module(proc_mod)
                    ppclass = proc_mod.PostProcess
                    if issubclass(ppclass, proc_class):
                        class_list.append(ppclass)
                else:
                    LOGGER.info(
                        f"Post-processor {pplib} was not found in processors module"
                    )


class Active:
    """Per-action runtime tracked by :class:`Base`.

    Owns one action and any split children: drives the executor loop, opens
    and writes HLO files, broadcasts data packets, manages sample
    bookkeeping, persists action/experiment/sequence meta files, and runs
    cleanup at the end of the action chain.
    """

    def __init__(self, base, activeparams: ActiveParams):  # outer instance
        """Initialize the active wrapper from a ``Base`` and an ``ActiveParams``.

        Args:
            base: The owning ``Base`` controller.
            activeparams: Parameters describing the action and its file connections.
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
        self.action.dummy = self.base.world_cfg.get("dummy", False)
        self.action.simulation = self.base.world_cfg.get("simulation", False)
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
        # serialize finish() so the action loop and a driver polling loop can't
        # both run the finalization (and its write_act) for this active at once
        self.finish_lock = asyncio.Lock()

    def executor_done_callback(self, futr):
        """Log any exception raised by the executor task on completion."""
        try:
            _ = futr.result()
        except Exception as exc:
            LOGGER.info(
                f"{traceback.format_exception(type(exc), exc, exc.__traceback__)}"
            )

    def start_executor(self, executor: Executor) -> dict:
        """Launch the action loop task for ``executor`` and return the action dict.

        Non-concurrent executors register on the unified local queue so the
        loop task stalls until previous actions finish.
        """
        # append action_uuid to local queue before running task if concurrency not allowed
        if not executor.concurrent:
            self.base.local_action_task_queue.append(executor.active.action.action_uuid)
        self.action_task = self.base.aloop.create_task(self.action_loop_task(executor))
        self.action_task.add_done_callback(self.executor_done_callback)
        LOGGER.info("Executor task started.")
        return self.action.as_dict()

    async def oneoff_executor(self, executor: Executor):
        """Run ``executor`` inline (no polling loop) and return its action result."""
        return await self.action_loop_task(executor)

    async def update_act_file(self):
        """Rewrite the action's meta YAML to reflect the current state."""
        await self.base.write_act(self.action)

    async def myinit(self):
        """Start the data-logger task, create the action's output dir, and broadcast initial status."""
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
    ) -> tuple:
        """Build the file header string and ``FileInfo`` record for a new data file.

        Args:
            header: Header content as a dict, list of lines, string, or ``None``.
            file_type: HELAO file-type label stored on the ``FileInfo``.
            json_data_keys: Column keys for the file's data payload.
            file_sample_label: Sample label(s) recorded on the ``FileInfo``.
            filename: Output filename; auto-generated if ``None``.
            file_group: Selects ``.hlo`` (helao group) or ``.csv`` (aux group).
            file_conn_key: File-connection key used for filename ordering.
            action: Action associated with the file (defaults to ``self.action``).

        Returns:
            ``(header_str, FileInfo)`` ready for use by the data writer.
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
        realtime: Optional[int] = None,
    ):
        """Stamp ``epoch_ns`` on each file connection's HLO header if not already set.

        Args:
            file_conn_keys: Specific connection keys to update; defaults to every
                file connection across ``self.action_list``.
            realtime: Epoch nanoseconds to stamp; defaults to the current
                NTP-corrected time.
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
            if self.file_conn_dict[file_conn_key].params.hloheader.epoch_ns is None:
                self.file_conn_dict[file_conn_key].params.hloheader.epoch_ns = realtime

    async def add_status(self, action=None):
        """Publish the action's current status to the status queue (no-op for nonblocking actions).

        Args:
            action: Optional action to publish; defaults to ``self.action``.
        """
        if action is None:
            action = self.action

        LOGGER.info(
            f"Adding {str(action.action_uuid)} to {action.action_name} status list."
        )

        if not action.nonblocking:
            await self.base.status_q.put(action.get_act())

    def set_estop(self, action: Optional[Action] = None):
        """Append ``HloStatus.estopped`` to ``action.action_status`` (defaults to ``self.action``)."""
        if action is None:
            action = self.action
        action.action_status.append(HloStatus.estopped)
        LOGGER.error(
            f"E-STOP {str(action.action_uuid)} on {action.action_name} status."
        )

    async def set_error(
        self, error_code: Optional[ErrorCodes] = None, action: Optional[Action] = None
    ):
        """Mark the action as errored and record the error code (or ``ErrorCodes.unspecified``)."""
        if action is None:
            action = self.action
        action.experiment_status.append(HloStatus.errored)

        if error_code:
            action.error_code = error_code
        else:
            action.error_code = ErrorCodes.unspecified

        LOGGER.error(f"ERROR {str(action.action_uuid)} on {action.action_name} status.")

    async def get_realtime(
        self, epoch_ns: Optional[int] = None, offset: Optional[float] = None
    ) -> int:
        """Forward to :meth:`Base.get_realtime` for NTP-corrected nanoseconds."""
        return await self.base.get_realtime(epoch_ns=epoch_ns, offset=offset)

    def get_realtime_nowait(
        self, epoch_ns: Optional[int] = None, offset: Optional[float] = None
    ) -> int:
        """Return NTP-corrected nanoseconds from the base controller (non-async)."""
        return int(
            np.floor(self.base.get_realtime_nowait(epoch_ns=epoch_ns, offset=offset))
        )

    async def write_live_data(self, output_str: str, file_conn_key: UUID):
        """Append ``output_str`` (with a trailing newline) to the open file for ``file_conn_key``.

        Returns:
            None
        """
        if file_conn_key in self.file_conn_dict:
            if self.file_conn_dict[file_conn_key].file:
                if not output_str.endswith("\n"):
                    output_str += "\n"
                await self.file_conn_dict[file_conn_key].file.write(output_str)

    async def enqueue_data_dflt(self, datadict: dict):
        """Enqueue ``datadict`` against the default file-connection key as an active ``DataModel``."""
        await self.enqueue_data(
            datamodel=DataModel(
                data={self.base.dflt_file_conn_key(): datadict},
                errors=[],
                status=HloStatus.active,
            )
        )

    def _build_data_package(
        self, datamodel: DataModel, action: Optional[Action] = None
    ) -> tuple:
        """Return ``(DataPackageModel, has_data)`` derived from ``datamodel`` and ``action``."""
        if action is None:
            action = self.action
        return self.assemble_data_msg(datamodel=datamodel, action=action), bool(datamodel.data)

    async def enqueue_data(self, datamodel: DataModel, action: Optional[Action] = None):
        """Publish ``datamodel`` onto the data queue and bump the queued counter if it had data."""
        msg, has_data = self._build_data_package(datamodel, action)
        await self.base.data_q.put(msg)
        if has_data:
            self.num_data_queued += 1

    def enqueue_data_nowait(
        self, datamodel: DataModel, action: Optional[Action] = None
    ):
        """Non-awaiting variant of :meth:`enqueue_data`."""
        msg, has_data = self._build_data_package(datamodel, action)
        self.base.data_q.put_nowait(msg)
        if has_data:
            self.num_data_queued += 1

    def assemble_data_msg(
        self, datamodel: DataModel, action: Optional[Action] = None
    ) -> DataPackageModel:
        """Wrap a ``DataModel`` and ``Action`` into a ``DataPackageModel`` for the data queue."""
        if action is None:
            action = self.action
        return DataPackageModel(
            action_uuid=action.action_uuid,
            action_name=action.action_name,
            datamodel=datamodel,
            errors=datamodel.errors,
        )

    def add_new_listen_uuid(self, new_uuid: UUID):
        """Track ``new_uuid`` as a data-stream source for this active's data logger."""
        self.listen_uuids.append(new_uuid)

    def _get_action_for_file_conn_key(self, file_conn_key: UUID):
        """Return the action whose ``file_conn_keys`` contains ``file_conn_key``, or ``None``."""
        output_action = None
        for action in self.action_list:
            if file_conn_key in action.file_conn_keys:
                output_action = action
                break
        return output_action

    async def log_data_set_output_file(self, file_conn_key: UUID):
        """Open the HLO output file for ``file_conn_key`` and write its header.

        Args:
            file_conn_key: Connection key identifying the target file slot.
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
            LOGGER.debug("realtime_ns was not set, adding it now.")
            self.file_conn_dict[file_conn_key].params.hloheader.epoch_ns = (
                await self.get_realtime()
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
            LOGGER.debug("adding header to new file")
            if not header.endswith("\n"):
                header += "\n"
            await self.file_conn_dict[file_conn_key].file.write(header)

    async def log_data_task(self):
        """Subscribe to the data queue and write matching packets to the active's HLO files.

        Filters by tracked listen UUIDs, lazily opens output files, writes the
        HLO ``%%`` separator before the first data row, and serialises dict
        payloads as JSON. Runs until cancelled when the action finishes.
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
                    LOGGER.debug(
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
                            LOGGER.debug(
                                "no json_data_keys defined, using keys from first data message: {jsonkeys[:10]}"
                            )

                            self.file_conn_dict[file_conn_key].params.json_data_keys = (
                                jsonkeys
                            )

                        LOGGER.debug(f"creating output file for {file_conn_key}")
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
            LOGGER.debug("removing data_q subscription for active")
            if dq_sub in self.base.data_q.subscribers:
                self.base.data_q.remove(dq_sub)
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            LOGGER.error(f"data LOGGER task failed with error: {repr(e), tb,}")

    def _resolve_output_path(
        self,
        file_type: str,
        filename: Optional[str],
        file_group: HloFileGroup,
        header: Optional[str],
        file_sample_label,
        json_data_keys,
        action: Action,
    ):
        """Resolve write parameters for a one-shot output file.

        Returns ``(header, file_info, output_path, output_file)`` when
        ``action.save_data`` is True, otherwise ``None``. Used by both
        :meth:`write_file` and :meth:`write_file_nowait`.
        """
        if not action.save_data:
            return None
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
        return header, file_info, output_path, output_file

    async def write_file(
        self,
        output_str: str,
        file_type: str,
        filename: Optional[str] = None,
        file_group: HloFileGroup = HloFileGroup.aux_files,
        header: Optional[str] = None,
        sample_str: Optional[str] = None,
        file_sample_label: Optional[List[str] | str] = None,
        json_data_keys: Optional[List[str]] = None,
        action: Optional[Action] = None,
    ) -> Optional[str]:
        """Write a single complete file asynchronously and return its path, or ``None`` if save is disabled."""
        if action is None:
            action = self.action
        result = self._resolve_output_path(
            file_type, filename, file_group, header, file_sample_label, json_data_keys, action
        )
        if result is None:
            return None
        header, file_info, output_path, output_file = result
        action.files.append(file_info)
        LOGGER.info(f"writing non stream data to: {output_file}")
        async with aiofiles.open(output_file, mode="a+") as f:
            if header:
                await f.write(header)
            await f.write("%%\n")
            await f.write(output_str)
        return output_file

    def write_file_nowait(
        self,
        output_str: str,
        file_type: str,
        filename: Optional[str] = None,
        file_group: HloFileGroup = HloFileGroup.aux_files,
        header: Optional[str] = None,
        sample_str: Optional[str] = None,
        file_sample_label: Optional[List[str] | str] = None,
        json_data_keys: Optional[List[str]] = None,
        action: Optional[Action] = None,
    ) -> Optional[str]:
        """Write a single complete file synchronously and return its path, or ``None`` if save is disabled."""
        if action is None:
            action = self.action
        result = self._resolve_output_path(
            file_type, filename, file_group, header, file_sample_label, json_data_keys, action
        )
        if result is None:
            return None
        header, file_info, output_path, output_file = result
        LOGGER.info(f"writing non stream data to: {output_file}")
        with open(output_file, mode="a+") as f:
            if header:
                f.write(header)
            f.write("%%\n")
            f.write(output_str)
        action.files.append(file_info)
        return output_file

    def set_sample_action_uuid(
        self,
        sample: Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample],
        action_uuid: UUID,
    ):
        """Tag a sample (and any sub-parts of an assembly) with the given action UUID."""
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
        """Append samples to the action's ``samples_in``/``samples_out`` and broadcast status.

        ``NoneSample`` entries are skipped; remaining samples have their
        ``action_uuid``, ``inheritance`` and ``status`` defaults filled in.

        Args:
            samples: Samples to append.
            IO: Either ``"in"`` or ``"out"``.
            action: Target action; defaults to ``self.action``.
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
        """Split the current action while leaving every previous action open."""
        await self.split(uuid_list=[])

    async def split_and_finish_prev_uuids(self):
        """Split the current action and finish every previously held action."""
        await self.split(uuid_list=None)

    async def finish_all(self):
        """Finish every action tracked by this active wrapper."""
        await self.finish(finish_uuid_list=None)

    async def split(
        self,
        uuid_list: Optional[List[UUID]] = None,
        new_fileconnparams: Optional[FileConnParams] = None,
    ) -> List[UUID]:
        """Fork the current action into a new sibling with fresh file connections.

        The previous action is marked split, a new action UUID is generated,
        new file connections are opened (copying the prior parameters unless
        ``new_fileconnparams`` is provided), and either all or a chosen subset
        of prior actions are finished.

        Args:
            uuid_list: UUIDs to finish; ``None`` finishes all except the new one.
            new_fileconnparams: Optional parameters for the new file connections.

        Returns:
            The keys of the newly created file connections.
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
                current_epoch_ns = await self.get_realtime()
                new_file_conn_key = self.base.new_file_conn_key(
                    key=str(current_epoch_ns)
                )
                if new_fileconnparams is None:
                    # get last file conn
                    new_file_conn = self.file_conn_dict[file_conn_key].deepcopy()
                    # modify last file_conn
                    new_file_conn.params.file_conn_key = new_file_conn_key
                    # reset some of the file conn parameters
                    new_file_conn.reset_file_conn()
                    # add new timestamp
                    new_file_conn.params.hloheader.epoch_ns = current_epoch_ns
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
        """Close every open HLO file for this active so a new active can take over."""
        for filekey in self.file_conn_dict:
            if self.file_conn_dict[filekey].file:
                await self.file_conn_dict[filekey].file.close()

    async def finish(
        self,
        finish_uuid_list: Optional[List[UUID]] = None,
        # end_state: HloStatus = HloStatus.finished
    ) -> Action:
        """Finalize the listed actions (or all of them) and clean up file/data resources.

        Exports global parameters, drains the data queue, runs HLO
        post-processors, closes file connections, schedules the run directory
        move, and broadcasts the final status for each finished action.

        Serialized via ``finish_lock`` so the action loop and a driver polling
        loop cannot run finalization (and its ``write_act``) concurrently for
        the same active.

        Args:
            finish_uuid_list: UUIDs to finish; ``None`` finishes every action.

        Returns:
            The current ``self.action`` after finalisation.
        """
        async with self.finish_lock:
            return await self._finish(finish_uuid_list=finish_uuid_list)

    async def _finish(
        self,
        finish_uuid_list: Optional[List[UUID]] = None,
    ) -> Action:
        """Finalization body for :meth:`finish`; must be called under ``finish_lock``."""
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
                action.action_finished_timestamp = set_time(offset=self.base.ntp_offset)

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
                    LOGGER.debug(
                        f"Waiting for data_stream finished package: {[action.data_stream_status for action in self.action_list]}"
                    )
                    await asyncio.sleep(0.1)
                except Exception:
                    LOGGER.error(
                        "Failed to enqueue finished data stream package",
                        exc_info=True,
                    )
                retry_counter += 1

            LOGGER.debug("checking if all queued data has written.")
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
                LOGGER.debug("finishing data logging.")
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
                if self.base.hlo_postprocessors:
                    for hpp, libname in zip(
                        self.base.hlo_postprocessors, self.base.hlo_postprocess_libs
                    ):
                        LOGGER.info(
                            f"Running custom HLO post-processor: {os.path.basename(libname).split('.py')[0]}"
                        )
                        loop = asyncio.get_running_loop()
                        postprocessor = hpp(self.action, save_root)
                        updated_file_list = await loop.run_in_executor(
                            None, postprocessor.process
                        )
                        self.action.files = updated_file_list
            except Exception:
                LOGGER.error("Failed to run custom HLO post-processor", exc_info=True)
            try:
                l10 = self.base.actives.pop(self.active_uuid, None)
                if l10 is not None:
                    self.base.history[l10.action.action_uuid] = copy(l10.action)
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
        """Record an auxiliary file on the action and queue it for relocation if needed.

        Args:
            file_type: HELAO file-type label stored on the ``FileInfo``.
            file_path: Path to the existing file.
            samples: Samples associated with the file (used to build labels).
            action: Target action; defaults to ``self.action``.
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
        """Copy any tracked auxiliary file paths into the action's output directory."""
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
        """Finalize a manual action by writing its synthesized experiment and sequence meta files."""
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
        """Push the action's status to every status subscriber, retrying on failure.

        Args:
            retry_limit: Maximum delivery attempts per subscriber.
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
        """Drive the full executor lifecycle: pre-exec, exec, polling, manual stop, post-exec.

        Stalls until earlier non-concurrent actions finish, then runs
        ``executor._pre_exec``, ``_exec``, optionally ``_poll`` (unless
        ``oneoff``), ``_manual_stop`` (if signalled), and ``_post_exec``.
        Data returned at any stage is broadcast on the data queue.

        Args:
            executor: The executor implementing the action.

        Returns:
            The action returned by :meth:`finish`.
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
        """Signal the polling loop to exit on the next iteration and request a manual stop."""
        LOGGER.info("Stop action request received. Stopping poll.")
        self.manual_stop = True
        self.action_loop_running = False


class DummyBase:
    """Minimal stand-in for :class:`Base` providing a live buffer and an action-server model.

    Used by code paths that need a base-like object (e.g. simulator drivers
    or stand-alone scripts) without spinning up the full FastAPI runtime.
    """

    def __init__(self) -> None:
        """Initialize an empty live buffer and a ``DUMMY`` ``ActionServerModel``."""
        self.live_buffer = {}
        self.actionservermodel = ActionServerModel(
            action_server=MachineModel(server_name="DUMMY", machine_name="dummyhost"),
            last_action_uuid=uuid1(),
        )

    def print_message(self, message: str) -> None:
        """Log ``message`` through the shared logger under the ``DUMMY`` server name."""
        print_message(LOGGER, "DUMMY", message)

    async def put_lbuf(self, message: dict) -> None:
        """Timestamp each item in ``message`` and store it in the live buffer."""
        now = time()
        for k, v in message:
            self.live_buffer[k] = (v, now)

    def get_lbuf(self, buf_key: str) -> tuple:
        """Return the ``(value, timestamp)`` stored for ``buf_key`` in the live buffer."""
        buf_val, buf_ts = self.live_buffer[buf_key]
        return buf_val, buf_ts
