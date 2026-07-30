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
import os
import sys
from socket import gethostname
from time import time
from typing import Optional, Union
from collections.abc import Callable
from uuid import UUID, uuid1
from glob import glob
from copy import deepcopy, copy
import traceback

import aiodebug.hang_inspection
import aiodebug.log_slow_callbacks
import colorama

from fastapi import WebSocket

from helao.helpers.server_api import HelaoFastAPI
from helao.helpers.dispatcher import (
    async_private_dispatcher,
)  # noqa: F401 -- unused by base.py directly; retained as a `base` module attribute for golden-master save/restore patching (S8 LOW item)
from helao.helpers.executor import Executor
from helao.helpers.helao_dirs import helao_dirs
from helao.core.models.run_dir import RunDir
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.helao_logging import print_message
from helao.helpers.yml_tools import (
    move_dir,
)  # noqa: F401 -- unused by base.py directly; retained as a `base` module attribute for golden-master save/restore patching (S8 LOW item)
from helao.helpers.premodels import Action, Experiment, Sequence
from helao.helpers.ws_utils import WsPublisher
from helao.helpers import (
    async_copy,
)  # noqa: F401 -- unused by base.py directly; retained as a `base` module attribute for golden-master save/restore patching (S8 LOW item)
from helao.helpers.time_utils import (
    set_time,
)  # noqa: F401 -- unused by base.py directly; retained as a `base` module attribute for golden-master save/restore patching (S8 LOW item)
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
from helao.core.models.server import ActionServerModel
from helao.core.version import get_filehash
from helao.helpers.active_params import ActiveParams
from helao.helpers.zdeque import zdeque
from helao.core.models.file import (
    FileConn,
    FileConnParams,
    HloFileGroup,
    HloHeaderModel,
)
from helao.core.error import ErrorCodes
from helao.helpers import config_loader
from helao.helpers.config_loader import HelaoConfig, ServerConfig
from helao.helpers.processors import HloPostProcessor
from helao.helpers.dequedict import DequeDict
from helao.core.servers.base_primitives import (
    Timer,
)  # noqa: F401 -- re-export: base.Timer stays importable for backward compatibility
from helao.core.servers.base_live_buffer import LiveBuffer
from helao.core.servers.base_status import StatusBroadcaster
from helao.core.servers.base_meta_writer import MetaFileWriter
from helao.core.servers.base_action_queue import ActionQueueDispatcher
from helao.core.servers.base_endpoints import EndpointManager
from helao.core.servers.active_data_file import DataFileWriter
from helao.core.servers.active_data_stream import DataStreamer
from helao.core.servers.active_executor import ExecutorRunner
from helao.core.servers.active_finalizer import ActionFinalizer
from pydantic import ValidationError

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

# ANSI color codes converted to the Windows versions
# strip colors if stdout is redirected
colorama.init(strip=not sys.stdout.isatty())


class Base:
    """Core runtime controller shared by every HELAO action server.

    Owns the action lifecycle and broadcast plumbing for one FastAPI server:
    indexes registered endpoints, dispatches per-action ``Active`` instances,
    publishes status/data/live updates to subscriber WebSockets and remote
    clients, maintains NTP-corrected timestamps, drives the endpoint and
    per-server action queues, and writes action/experiment/sequence meta files
    plus HLO data files under the configured ``root``.
    """

    def __init__(
        self,
        app: HelaoFastAPI,
        dyn_endpoints=None,
        helao_cfg: Optional[HelaoConfig] = None,
    ):
        """Wire the controller to a running FastAPI app and read the world config.

        Args:
            app: The ``HelaoFastAPI`` instance that owns this controller.
            dyn_endpoints: Optional callable invoked with the app instance to
                register additional endpoints.
            helao_cfg: Optional validated :class:`HelaoConfig` to use instead
                of validating ``app.helao_cfg`` (injection seam for tests/
                future callers).

        Raises:
            ValueError: If the world config defines no ``root`` directory or
                fails ``HelaoConfig`` validation (e.g. missing ``run_type``).
        """

        self.app = app
        self.server = app.server
        self.dyn_endpoints = dyn_endpoints
        self.server_cfg = app.server_cfg
        self.server_params = app.server_params
        self.server.hostname = self.server_cfg["host"]
        self.server.port = self.server_cfg["port"]
        # Dict shim — stays the runtime source of truth for deployment code
        # reading self.base.world_cfg[...]; do not remove in 3b.
        self.world_cfg = self.app.helao_cfg
        # Typed view (3b injection seam). Injected for tests/future callers;
        # defaults to validating the same dict the shim exposes.
        try:
            self.typed_cfg: HelaoConfig = (
                helao_cfg
                if helao_cfg is not None
                else HelaoConfig.model_validate(self.world_cfg)
            )
        except ValidationError as exc:
            raise ValueError(
                f"world config failed HelaoConfig validation: {exc}"
            ) from exc
        self.typed_server_cfg: Optional[ServerConfig] = (
            self.typed_cfg.servers or {}
        ).get(self.server.server_name)

        servers_cfg = self.typed_cfg.servers or {}
        orch_keys = [k for k, s in servers_cfg.items() if s.group == "orchestrator"]
        if orch_keys:
            self.orch_key = orch_keys[0]
            self.orch_host = servers_cfg[self.orch_key].host
            self.orch_port = servers_cfg[self.orch_key].port
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

        LOGGER.info(f"Found run_type in config: {self.typed_cfg.run_type}")
        self.run_type = self.typed_cfg.run_type.lower()

        self.actives: dict[UUID, Active] = {}
        self.history = DequeDict(
            maxlen=200
        )  # store history of active actions (contained)
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

        # Optional zero-arg callable a server sets to report pending background
        # work (syncer/analysis/batch queues) to the hot-reload idle gate via
        # the /hotreload_busy endpoint. None => server has no background queue.
        self.hotreload_busy_hook: Optional[Callable[[], bool]] = None

        self.ntp_offset: float = 0.0  # add to system time for correction
        self.ntp_last_sync = None
        self.aiolock = asyncio.Lock()
        self.endpoint_queues = {}
        self.local_action_queue = zdeque([])
        self.fast_urls = []

        self.hlo_postprocessors: list[HloPostProcessor] = []
        self.hlo_postprocess_libs = self.server_cfg.get("hlo_postprocess_libs", [])

        self.import_postprocessors(
            self.hlo_postprocess_libs, self.hlo_postprocessors, HloPostProcessor
        )

        self.ntp_last_sync, self.ntp_offset = read_saved_offset(
            os.path.join(self.helaodirs.log_root, "ntpLastSync.txt")
        )

        self._init_collaborators()

    def _init_collaborators(self):
        """Construct the collaborators extracted from ``Base`` by CARDS P6.

        Called from ``__init__`` at the point each collaborator's state was
        previously constructed inline; test fixtures that bypass ``__init__``
        (e.g. the Active output golden-master harness's ``Base.__new__``
        construction) call this directly so collaborators exist without
        per-collaborator lazy guards.
        """
        self.live_buffer_mgr = LiveBuffer(self)
        self.status_broadcaster = StatusBroadcaster(self)
        self.meta_writer = MetaFileWriter(self)
        self.action_queue = ActionQueueDispatcher(self)
        self.endpoint_mgr = EndpointManager(self)

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
        self.endpoint_mgr.dyn_endpoints_init()

    def endpoint_queues_init(self):
        """Create a per-endpoint action queue for every action route on this server."""
        self.endpoint_mgr.endpoint_queues_init()

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
        await self.endpoint_mgr.init_endpoint_status(dyn_endpoints=dyn_endpoints)

    def get_endpoint_urls(self) -> list:
        """Return a list of route descriptors (path/name/params) for every endpoint."""
        return self.endpoint_mgr.get_endpoint_urls()

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
                    sample_actuuid_list = getattr(sample_obj, "action_uuid", [])
                    if not sample_actuuid_list:
                        sample_obj.action_uuid = [action.action_uuid]
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
        json_data_keys: list[str] = [],
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
        return await self.status_broadcaster.send_statuspackage(
            client_servkey=client_servkey,
            client_host=client_host,
            client_port=client_port,
            action_name=action_name,
        )

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
        return await self.status_broadcaster.send_nbstatuspackage(
            client_servkey=client_servkey,
            client_host=client_host,
            client_port=client_port,
            actionmodel=actionmodel,
        )

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
        return await self.status_broadcaster.attach_client(
            client_servkey, client_host, client_port, retry_limit=retry_limit
        )

    def detach_client(self, client_servkey: str, client_host: str, client_port: int):
        """Remove a remote client from this server's status subscriber set."""
        return self.status_broadcaster.detach_client(
            client_servkey, client_host, client_port
        )

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
        await self.status_broadcaster._ws_relay(
            websocket, queue, label, use_as_dict=use_as_dict
        )

    async def ws_status(self, websocket: WebSocket) -> None:
        """Stream compressed status messages over ``websocket`` until the client disconnects."""
        await self.status_broadcaster.ws_status(websocket)

    async def ws_data(self, websocket: WebSocket) -> None:
        """Stream compressed data packets over ``websocket`` until the client disconnects."""
        await self.status_broadcaster.ws_data(websocket)

    async def ws_live(self, websocket: WebSocket) -> None:
        """Stream compressed live-buffer updates over ``websocket`` until disconnect."""
        await self.status_broadcaster.ws_live(websocket)

    async def live_buffer_task(self):
        """Subscribe to the live queue and fold every published message into ``live_buffer``."""
        return await self.live_buffer_mgr.live_buffer_task()

    def _stamp_lbuf_dict(self, live_dict: dict) -> dict:
        """Wrap each value in a ``(value, now())`` tuple for the live buffer."""
        return self.live_buffer_mgr._stamp_lbuf_dict(live_dict)

    async def put_lbuf(self, live_dict: dict) -> None:
        """Timestamp ``live_dict`` and publish it to the live queue (awaited put)."""
        return await self.live_buffer_mgr.put_lbuf(live_dict)

    def put_lbuf_nowait(self, live_dict: dict) -> None:
        """Timestamp ``live_dict`` and publish it to the live queue without awaiting."""
        return self.live_buffer_mgr.put_lbuf_nowait(live_dict)

    def get_lbuf(self, live_key):
        """Return the most recent ``(value, timestamp)`` tuple stored under ``live_key``."""
        return self.live_buffer_mgr.get_lbuf(live_key)

    async def regular_status_task(self, delay: float = 10, retry_limit: int = 5):
        """Periodically push the action-server status to every subscribed client."""
        await self.status_broadcaster.regular_status_task(
            delay=delay, retry_limit=retry_limit
        )

    async def _dispatch_queued_action(self, action_queue, queue_label: str) -> None:
        """Pop one queued action, redispatch it with ``no_wait``, and requeue on failure.

        Args:
            action_queue: Deque of ``(action, extra_params)`` tuples.
            queue_label: Human-readable label used in log messages.
        """
        await self.action_queue._dispatch_queued_action(action_queue, queue_label)

    async def process_unified_queue(self) -> None:
        """Dispatch the next queued action when the server disallows concurrency."""
        await self.action_queue.process_unified_queue()

    async def process_endpoint_queue(self, status_msg: ActionModel) -> None:
        """Dispatch the next queued action for the endpoint that just transitioned status."""
        await self.action_queue.process_endpoint_queue(status_msg)

    async def log_status_task(self, retry_limit: int = 5):
        """Subscribe to the status queue, broadcast to subscribers, and drive endpoint/unified queues.

        Args:
            retry_limit: Number of attempts to deliver each status update to a subscriber.
        """
        await self.status_broadcaster.log_status_task(retry_limit=retry_limit)

    async def detach_subscribers(self):
        """Signal the status and data queues to terminate and yield long enough to drain them."""
        await self.status_broadcaster.detach_subscribers()

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
        return await self.live_buffer_mgr.get_realtime(epoch_ns=epoch_ns, offset=offset)

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
        return self.live_buffer_mgr.get_realtime_nowait(
            epoch_ns=epoch_ns, offset=offset
        )

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
        await self.meta_writer._write_meta_atomic(output_file, output_str)

    async def write_act(self, action: Action):
        """Write the action's metadata to ``<output_dir>/<timestamp>-act.yml`` if ``save_act``.

        Args:
            action: ``Action`` whose metadata should be persisted.
        """
        await self.meta_writer.write_act(action)

    async def write_exp(self, experiment: Experiment):
        """Write the experiment's metadata to ``<experiment_dir>/<timestamp>-exp.yml``.

        Args:
            experiment: ``Experiment`` whose metadata should be persisted.
        """
        await self.meta_writer.write_exp(experiment)

    async def write_seq(self, sequence: Sequence):
        """Write the sequence's metadata to ``<sequence_dir>/<timestamp>-seq.yml``.

        Args:
            sequence: ``Sequence`` whose metadata should be persisted.
        """
        await self.meta_writer.write_seq(sequence)

    def new_file_conn_key(self, key: str) -> UUID:
        """Return a UUID derived from the MD5 hash of ``key``.

        Args:
            key: Arbitrary string used to seed the hash.
        """
        return self.meta_writer.new_file_conn_key(key)

    def dflt_file_conn_key(self) -> UUID:
        """Return the default file-connection key (``md5(str(None))``)."""
        return self.meta_writer.dflt_file_conn_key()

    def replace_status(
        self, status_list: list[HloStatus], old_status: HloStatus, new_status: HloStatus
    ):
        """Swap ``old_status`` for ``new_status`` in ``status_list``, or append if missing.

        Prefer the model methods (``replace_action_status``/``replace_experiment_status``/
        ``replace_sequence_status``) for new call sites; this shim delegates to
        ``guarded_replace`` for callers still holding a bare ``status_list`` reference.
        """
        return self.status_broadcaster.replace_status(
            status_list, old_status, new_status
        )

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

    async def estop_actives(self) -> list:
        """Finalize every in-flight action as estopped without writing a new artifact.

        Replaces the old ``/estop`` behavior that fabricated a placeholder
        ``estop`` action on every server (including idle ones). Here only actions
        that were actually running are touched: ``HloStatus.estopped`` is appended
        to each and the action is finalized through its normal lifecycle
        (``write_act`` with the estopped status, then move to ``RUNS_FINISHED``).
        An idle server has no actives, so it writes nothing. ``finish`` is
        idempotent (guarded by ``finish_lock`` and the finished-status check), so
        a concurrent action-loop finish for the same active is safe.

        This is intentionally independent of the ``/estop`` ``switch`` flag (which
        only latches/releases the per-server estop state): whenever estop is
        signalled there may be running actions to finalize, and on release there
        simply are none, so calling it unconditionally is safe.

        Returns:
            List of finalized ``action_uuid`` strings.
        """
        finalized = []
        for active in list(self.actives.values()):
            try:
                for action in active.action_list:
                    if HloStatus.estopped not in action.action_status:
                        active.set_estop(action=action)
                await active.finish_all()
                finalized.extend(str(a.action_uuid) for a in active.action_list)
            except Exception:
                LOGGER.error(
                    "error finalizing an active action during estop", exc_info=True
                )
        return finalized

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
                    "helao",
                    "deploy",
                    config_loader.CONFIG["deployment"],
                    "processors",
                    f"{pplib}.py",
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

        # per-Active data-streaming collaborator (CARDS P6 S6). Constructed here
        # (before init_act below) because add_new_listen_uuid -- called during
        # __init__ -- now routes through it. Same per-Active pattern as
        # data_file_writer: it only back-refs this Active and reads
        # listen_uuids/num_data_*/file_conn_dict/base.data_q at call time, all
        # of which are already initialized above. myinit() launches the drain
        # loop via the log_data_task delegator.
        self.data_stream = DataStreamer(self)

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

        self.file_conn_dict: dict(str, FileConn) = {}
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

        # per-Active data-file collaborator (CARDS P6 S5). Constructed last: it
        # only holds a back-ref to this Active and reads file_conn_dict/action/
        # base at call time, so every attribute its methods touch already exists.
        # myinit() (the external lifecycle entry) runs after __init__ and reaches
        # the file helpers through the Active delegators below.
        self.data_file_writer = DataFileWriter(self)

        # per-Active executor-orchestration collaborator (CARDS P6 S7).
        # Constructed at the end of __init__ alongside the other collaborators:
        # start_executor is only called post-init by drivers, so nothing in
        # __init__ needs it yet. It back-refs this Active and reads
        # manual_stop/action_loop_running/action_task/action/base at call time
        # (all initialized above); those state attributes stay on Active.
        self.executor_runner = ExecutorRunner(self)

        # per-Active action-finalization collaborator (CARDS P6 S8, the LAST and
        # highest-risk Active extraction). Constructed at the end of __init__
        # alongside the other collaborators: finish/split/substitute are only
        # called post-init (by the executor loop, drivers, and the orch's
        # finish_active_* handlers), so nothing in __init__ needs it yet. It
        # back-refs this Active and reads action/action_list/listen_uuids/
        # num_data_*/file_conn_dict/data_logger/finish_lock/active_uuid/base at
        # call time (all initialized above); those state attributes stay on
        # Active and are never cached here (a cached counter/list = a finish that
        # closes before late data lands, or a lost split child).
        self.action_finalizer = ActionFinalizer(self)

    def executor_done_callback(self, futr):
        """Log any exception raised by the executor task on completion."""
        return self.executor_runner.executor_done_callback(futr)

    def start_executor(self, executor: Executor) -> dict:
        """Launch the action loop task for ``executor`` and return the action dict.

        Non-concurrent executors register on the unified local queue so the
        loop task stalls until previous actions finish.
        """
        return self.executor_runner.start_executor(executor)

    async def oneoff_executor(self, executor: Executor):
        """Run ``executor`` inline (no polling loop) and return its action result."""
        return await self.executor_runner.oneoff_executor(executor)

    async def update_act_file(self):
        """Rewrite the action's meta YAML to reflect the current state."""
        return await self.data_file_writer.update_act_file()

    async def myinit(self):
        """Start the data-logger task, create the action's output dir, and broadcast initial status."""
        self.data_logger = self.base.aloop.create_task(self.log_data_task())
        save_root = str(self.base.helaodirs.save_root)
        if self.action.manual_action:
            save_root = save_root.replace(RunDir.ACTIVE.value, RunDir.DIAG.value)
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
                exp.reset_experiment_status(HloStatus.active)
                exp.reset_sequence_status(HloStatus.active)
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
        return self.data_file_writer.init_datafile(
            header,
            file_type,
            json_data_keys,
            file_sample_label,
            filename,
            file_group,
            file_conn_key=file_conn_key,
            action=action,
        )

    def finish_hlo_header(
        self,
        file_conn_keys: Optional[list[UUID]] = None,
        realtime: Optional[int] = None,
    ):
        """Stamp ``epoch_ns`` on each file connection's HLO header if not already set.

        Args:
            file_conn_keys: Specific connection keys to update; defaults to every
                file connection across ``self.action_list``.
            realtime: Epoch nanoseconds to stamp; defaults to the current
                NTP-corrected time.
        """
        return self.data_file_writer.finish_hlo_header(
            file_conn_keys=file_conn_keys, realtime=realtime
        )

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
        action.append_action_status(HloStatus.estopped)
        LOGGER.error(
            f"E-STOP {str(action.action_uuid)} on {action.action_name} status."
        )

    async def set_error(
        self, error_code: Optional[ErrorCodes] = None, action: Optional[Action] = None
    ):
        """Mark the action as errored and record the error code (or ``ErrorCodes.unspecified``)."""
        if action is None:
            action = self.action
        # NOTE: appends to experiment_status (not action_status) — historical behavior, see open-questions
        action.append_experiment_status(HloStatus.errored)

        if error_code:
            action.error_code = error_code
        else:
            action.error_code = ErrorCodes.unspecified

        LOGGER.error(f"ERROR {str(action.action_uuid)} on {action.action_name} status.")

    async def get_realtime(
        self, epoch_ns: Optional[int] = None, offset: Optional[float] = None
    ) -> int:
        """Forward to :meth:`Base.get_realtime` for NTP-corrected nanoseconds."""
        return await self.data_stream.get_realtime(epoch_ns=epoch_ns, offset=offset)

    def get_realtime_nowait(
        self, epoch_ns: Optional[int] = None, offset: Optional[float] = None
    ) -> int:
        """Return NTP-corrected nanoseconds from the base controller (non-async)."""
        return self.data_stream.get_realtime_nowait(epoch_ns=epoch_ns, offset=offset)

    async def write_live_data(self, output_str: str, file_conn_key: UUID):
        """Append ``output_str`` (with a trailing newline) to the open file for ``file_conn_key``.

        Returns:
            None
        """
        return await self.data_stream.write_live_data(output_str, file_conn_key)

    async def enqueue_data_dflt(self, datadict: dict):
        """Enqueue ``datadict`` against the default file-connection key as an active ``DataModel``."""
        return await self.data_stream.enqueue_data_dflt(datadict)

    def _build_data_package(
        self, datamodel: DataModel, action: Optional[Action] = None
    ) -> tuple:
        """Return ``(DataPackageModel, has_data)`` derived from ``datamodel`` and ``action``."""
        return self.data_stream._build_data_package(datamodel, action)

    async def enqueue_data(self, datamodel: DataModel, action: Optional[Action] = None):
        """Publish ``datamodel`` onto the data queue and bump the queued counter if it had data."""
        return await self.data_stream.enqueue_data(datamodel, action)

    def enqueue_data_nowait(
        self, datamodel: DataModel, action: Optional[Action] = None
    ):
        """Non-awaiting variant of :meth:`enqueue_data`."""
        return self.data_stream.enqueue_data_nowait(datamodel, action)

    def assemble_data_msg(
        self, datamodel: DataModel, action: Optional[Action] = None
    ) -> DataPackageModel:
        """Wrap a ``DataModel`` and ``Action`` into a ``DataPackageModel`` for the data queue."""
        return self.data_stream.assemble_data_msg(datamodel, action)

    def add_new_listen_uuid(self, new_uuid: UUID):
        """Track ``new_uuid`` as a data-stream source for this active's data logger."""
        return self.data_stream.add_new_listen_uuid(new_uuid)

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
        return await self.data_file_writer.log_data_set_output_file(file_conn_key)

    async def log_data_task(self):
        """Subscribe to the data queue and write matching packets to the active's HLO files.

        Filters by tracked listen UUIDs, lazily opens output files, writes the
        HLO ``%%`` separator before the first data row, and serialises dict
        payloads as JSON. Runs until cancelled when the action finishes.
        """
        return await self.data_stream.log_data_task()

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
        return self.data_file_writer._resolve_output_path(
            file_type,
            filename,
            file_group,
            header,
            file_sample_label,
            json_data_keys,
            action,
        )

    async def write_file(
        self,
        output_str: str,
        file_type: str,
        filename: Optional[str] = None,
        file_group: HloFileGroup = HloFileGroup.aux_files,
        header: Optional[str] = None,
        sample_str: Optional[str] = None,
        file_sample_label: Optional[list[str] | str] = None,
        json_data_keys: Optional[list[str]] = None,
        action: Optional[Action] = None,
    ) -> Optional[str]:
        """Write a single complete file asynchronously and return its path, or ``None`` if save is disabled."""
        return await self.data_file_writer.write_file(
            output_str,
            file_type,
            filename=filename,
            file_group=file_group,
            header=header,
            sample_str=sample_str,
            file_sample_label=file_sample_label,
            json_data_keys=json_data_keys,
            action=action,
        )

    def write_file_nowait(
        self,
        output_str: str,
        file_type: str,
        filename: Optional[str] = None,
        file_group: HloFileGroup = HloFileGroup.aux_files,
        header: Optional[str] = None,
        sample_str: Optional[str] = None,
        file_sample_label: Optional[list[str] | str] = None,
        json_data_keys: Optional[list[str]] = None,
        action: Optional[Action] = None,
    ) -> Optional[str]:
        """Write a single complete file synchronously and return its path, or ``None`` if save is disabled."""
        return self.data_file_writer.write_file_nowait(
            output_str,
            file_type,
            filename=filename,
            file_group=file_group,
            header=header,
            sample_str=sample_str,
            file_sample_label=file_sample_label,
            json_data_keys=json_data_keys,
            action=action,
        )

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
        samples: list[
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
                sample.reset_sample_status(SampleStatus.preserved)

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
        return await self.action_finalizer.split_and_keep_active()

    async def split_and_finish_prev_uuids(self):
        """Split the current action and finish every previously held action."""
        return await self.action_finalizer.split_and_finish_prev_uuids()

    async def finish_all(self):
        """Finish every action tracked by this active wrapper."""
        return await self.action_finalizer.finish_all()

    async def split(
        self,
        uuid_list: Optional[list[UUID]] = None,
        new_fileconnparams: Optional[FileConnParams] = None,
    ) -> list[UUID]:
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
        return await self.action_finalizer.split(
            uuid_list=uuid_list, new_fileconnparams=new_fileconnparams
        )

    async def substitute(self):
        """Close every open HLO file for this active so a new active can take over."""
        return await self.action_finalizer.substitute()

    async def finish(
        self,
        finish_uuid_list: Optional[list[UUID]] = None,
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
        return await self.action_finalizer.finish(finish_uuid_list=finish_uuid_list)

    async def _finish(
        self,
        finish_uuid_list: Optional[list[UUID]] = None,
    ) -> Action:
        """Finalization body for :meth:`finish`; must be called under ``finish_lock``."""
        return await self.action_finalizer._finish(finish_uuid_list=finish_uuid_list)

    async def track_file(
        self,
        file_type: str,
        file_path: str,
        samples: list[
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
        return await self.data_file_writer.track_file(
            file_type, file_path, samples, action=action
        )

    async def relocate_files(self):
        """Copy any tracked auxiliary file paths into the action's output directory."""
        return await self.data_file_writer.relocate_files()

    async def finish_manual_action(self):
        """Finalize a manual action by writing its synthesized experiment and sequence meta files."""
        return await self.action_finalizer.finish_manual_action()

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
        return await self.executor_runner.action_loop_task(executor)

    def stop_action_task(self):
        """Signal the polling loop to exit on the next iteration and request a manual stop."""
        return self.executor_runner.stop_action_task()


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
