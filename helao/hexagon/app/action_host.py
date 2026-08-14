"""Hexagon-native action-server host — route surface and construction (B1 Task 3a).

Replaces ``BaseAPI``/``Base`` as the object a deployment action module builds.
Where the graft imports a legacy module and rebinds methods onto the ``Base`` it
constructs, an ``ActionHost`` *is* the server.

**Scope of this module as it stands.** Task 3 split in two once the first attempt
showed the seam: the host's *route surface and construction* (here) are gateable
against the captured surface JSON with no action session at all, while the host's
*action entry* — the route class that builds an ``ActionContext``, the session
factory, the queuing middleware and the executor registry — belongs with Tasks
4–6. Everything here is complete for the state this module owns; nothing is
stubbed. ``executors`` and ``_actives`` are real registries that are simply empty
until Tasks 5 and 6 populate them, and every route that reads them is correct at
both stages.

Subclasses :class:`helao.helpers.server_api.HelaoFastAPI`, which is a **helper,
not engine** — it supplies ``server_cfg``/``server_params``, the ``MachineModel``
identity, and the co-located ZMQ RPC mirror every hexagon server must have.
A missing mirror is silent rather than loud: every ``async_private_dispatcher``
call would fall back to HTTP after a 3 s probe timeout, presenting as a sluggish
UI rather than a failure.

``host.base is host``. Twenty-one hte action modules reach ``app.base.<member>``;
rather than invent an indirection, the host answers to both names.

**One B7 follow-up, recorded not fixed:** ``HelaoFastAPI.__init__`` imports
``ActionAPIRoute`` from ``helao.core.servers.base_api`` unconditionally
(``server_api.py:71``). Nothing here uses it — Task 4 replaces the router's route
class — but the *import* still runs, so ``server_api.py`` must be made lazy or
parameterised before B7 can delete the engine.
"""

import asyncio
import faulthandler
import json
import os
import time
from collections import namedtuple
from typing import Annotated, Any, Callable, Optional

from fastapi import Body, WebSocket, WebSocketDisconnect
from websockets.exceptions import ConnectionClosedOK

from helao.core.drivers.helao_driver import DriverPoller, DriverStatus, HelaoDriver
from helao.core.models.server import ActionServerModel
from helao.helpers import helao_logging as logging
from helao.helpers.helao_dirs import helao_dirs
from helao.helpers.loaded_modules import loaded_repo_modules
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.premodels import Action
from helao.helpers.server_api import HelaoFastAPI
from helao.helpers.ws_utils import WsPublisher
from helao.helpers.zdeque import zdeque
from helao.hexagon.app.wiring import ACTION_REQUIRED, PortWiring

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: Keys that belong on the Action itself rather than in action_params when a
#: queued action is rebuilt from query/path params. Same list as legacy's.
ACTION_PARAM_KEYS = [
    "action_version",
    "start_condition",
    "from_global_seq_params",
    "from_global_exp_params",
    "from_global_act_params",
    "to_global_params",
    "manual_action",
    "nonblocking",
    "process_finish",
    "process_contrib",
    "save_act",
    "save_data",
    "process_uuid",
    "data_request_id",
    "campaign_name",
    "campaign_uuid",
    "sync_data",
]

__all__ = ["ActionHost"]


class ActionHost(HelaoFastAPI):
    """The native action server.

    Constructor arity matches ``BaseAPI.__init__`` deliberately — that part of
    the contract had no reason to change, and keeping it makes the per-module
    port a change of import and decorator rather than of shape.

    Attributes:
        base: ``self``. The member name every hte action module already uses.
        driver: First constructed driver, or None.
        drivers: Namedtuple of constructed drivers.
        poller: Optional ``DriverPoller`` attached to the first driver.
        root_dir: Resolved output root.
        fault_dir: Directory for faulthandler dumps.
        live_buffer: Latest live values keyed by datalab name.
        executors: Running executors by id (populated from Task 6).
        actionservermodel: This server's live status snapshot.
    """

    def __init__(
        self,
        server_key: str,
        server_title: str,
        description: str,
        version: Any,
        driver_classes: Optional[list] = None,
        dyn_endpoints: Optional[Callable] = None,
        poller_class: Optional[type] = None,
        wiring: Optional[PortWiring] = None,
        helao_cfg: Optional[dict] = None,
    ):
        """Build the app, its route surface, and its lifecycle hooks.

        Args:
            server_key: Server key in the launched config.
            server_title: OpenAPI title.
            description: OpenAPI description.
            version: Server version.
            driver_classes: Driver classes constructed at startup.
            dyn_endpoints: Callable invoked with the app to register late routes.
            poller_class: ``DriverPoller`` subclass attached to the first driver.
            wiring: Composed ports; built from the global config when omitted.
            helao_cfg: Config dict to use instead of the global ``CONFIG``. The
                same injection seam ``HelaoFastAPI`` offers, forwarded so a test
                can build a host without a launched config.
        """
        super().__init__(
            helao_srv=server_key,
            title=server_title,
            description=description,
            version=str(version),
            helao_cfg=helao_cfg,
        )
        # HelaoFastAPI installs the legacy ActionAPIRoute; replace it with a
        # subclass bound to THIS host before any route is registered, so no
        # legacy wrapping is ever applied and two hosts in one process do not
        # share a binding. See the module docstring for the B7 follow-up on the
        # import itself, which still runs.
        from helao.hexagon.app.action_route import bind_action_route

        self.router.route_class = bind_action_route(self)

        if wiring is None:
            from helao.hexagon.app.factory import build_wiring

            wiring = build_wiring(server_key)
        wiring.require(*ACTION_REQUIRED)
        self.hexagon_wiring = wiring

        self.server_key = server_key
        self.drivers: Any = tuple()
        self.driver: Any = None
        self.poller: Optional[DriverPoller] = None
        self._driver_classes = driver_classes
        self._poller_class = poller_class
        self._dyn_endpoints = dyn_endpoints

        self.world_cfg = self.helao_cfg
        self.root_dir = self.helao_cfg.get("root", None)
        self.fault_dir: Optional[str] = None
        self.fault_file = None

        self.live_buffer: dict = {}
        #: Non-concurrent executors serialize through this queue, by action
        #: uuid. Losing it lets two non-concurrent actions interleave on one
        #: server -- a hardware-safety property, not a tidiness one.
        self.local_action_task_queue: list = []
        #: Actions that arrived while busy, awaiting redispatch. DISTINCT from
        #: local_action_task_queue above: that one serializes executors inside
        #: one action's loop, this one holds whole actions the middleware
        #: parked. Conflating them deadlocks or double-dispatches.
        self.local_action_queue = zdeque([])
        #: Per-endpoint parking, keyed by endpoint name.
        self.endpoint_queues: dict = {}
        #: Route descriptors; populated by init_endpoint_status at startup.
        self.fast_urls: list = []
        #: Captured at startup; the executor runner's create_task target.
        self.aloop = None
        #: Running executors, keyed by executor id. Empty until Task 6.
        self.executors: dict = {}
        #: Live action sessions, keyed by action uuid. Named `actives` because the
        #: legacy estop handler and deployment code both use that spelling.
        self.actives: dict = {}
        self.last_10_active: list = []
        self.hotreload_busy_hook: Optional[Callable] = None

        self.actionservermodel = ActionServerModel(action_server=self.server)
        # Resolved output directories. In the frozen member surface and read by
        # HelaoSyncer.__init__ (sync_driver.py:2203) among others -- its absence
        # is a startup crash for any driver that writes, not a lazy failure.
        self.helaodirs = helao_dirs(self.world_cfg, self.server.server_name)

        self.status_q = MultisubscriberQueue()
        self.data_q = MultisubscriberQueue()
        self.live_q = MultisubscriberQueue()
        self.status_publisher = WsPublisher(self.status_q)
        self.data_publisher = WsPublisher(self.data_q)
        self.live_publisher = WsPublisher(self.live_q)

        # The meta writer is already native; the host owns it rather than
        # having it grafted on, and the file-conn key derivation below is the
        # only part of it the session needs before any file is opened.
        self.meta_writer = wiring.artifact_store.meta_writer_for(self)

        from helao.hexagon.app.endpoint_manager import (
            ActionQueueDispatcher,
            EndpointManager,
        )

        self.endpoint_mgr = EndpointManager(self)
        self.action_queue = ActionQueueDispatcher(self)

        self._register_middleware()
        self._register_exception_handler()
        self._register_websockets()
        self._register_private_routes()
        self._register_utility_routes()
        self._register_estop_route(server_key)
        self._register_lifecycle_hooks()

    # -- names deployment modules reach through ------------------------------

    @property
    def base(self) -> "ActionHost":
        """``app.base`` and ``app`` are the same object here."""
        return self

    # -- action entry --------------------------------------------------------

    def action(self, **route_kwargs) -> Callable:
        """Register an action endpoint.

        The handler declares ``ctx: ActionContext`` and receives the request's
        action explicitly; there is no ContextVar. The route class strips ``ctx``
        from the FastAPI-visible signature and injects it at call time.

        Args:
            **route_kwargs: Forwarded to ``self.post``. ``path`` defaults to
                ``/<server_key>/<function name>``, matching the legacy form.

        Returns:
            The registering decorator.
        """

        def decorate(func: Callable) -> Callable:
            path = route_kwargs.pop("path", f"/{self.server_key}/{func.__name__}")
            tags = route_kwargs.pop("tags", ["action"])
            self.post(path, tags=tags, **route_kwargs)(func)
            return func

        return decorate

    async def begin_session(self, action: Action, **kwargs):
        """Open the action's session — the ``Active`` equivalent.

        Args:
            action: The action this session tracks.
            **kwargs: ``json_data_keys``, ``action_abbr``, ``file_type``,
                ``hloheader`` — forwarded to :meth:`ActionSession.open`.

        Returns:
            The :class:`ActionSession` now tracking *action*.
        """
        from helao.hexagon.app.action_session import ActionSession

        return await ActionSession.open(self, action, **kwargs)

    # -- endpoint registration -------------------------------------------------

    def dyn_endpoints_init(self) -> None:
        """Register endpoint status, invoking ``dyn_endpoints`` first."""
        return self.endpoint_mgr.dyn_endpoints_init()

    async def init_endpoint_status(self, dyn_endpoints=None) -> None:
        """Register every action endpoint for status monitoring."""
        return await self.endpoint_mgr.init_endpoint_status(dyn_endpoints)

    def endpoint_queues_init(self) -> None:
        """Create a per-endpoint action queue for every action route."""
        return self.endpoint_mgr.endpoint_queues_init()

    def get_endpoint_urls(self) -> list:
        """Return a path/name/params descriptor for every route."""
        return self.endpoint_mgr.get_endpoint_urls()

    async def process_unified_queue(self) -> None:
        """Dispatch the next queued action when concurrency is disallowed."""
        return await self.action_queue.process_unified_queue()

    async def process_endpoint_queue(self, status_msg) -> None:
        """Dispatch the next queued action for the endpoint that just freed up."""
        return await self.action_queue.process_endpoint_queue(status_msg)

    # -- live buffer -----------------------------------------------------------

    @staticmethod
    def _stamp_lbuf_dict(live_dict: dict) -> dict:
        """Stamp each live value with its wall-clock epoch.

        This is the ``{datalab: (value, epoch)}`` shape ws_live carries, and the
        Reflex ingest normalizer is keyed to it -- a bare value here silently
        yields a panel with no numeric columns.
        """
        from time import time

        return {k: (v, time()) for k, v in live_dict.items()}

    async def put_lbuf(self, live_dict: dict) -> None:
        """Publish live values to the ws_live fan-out."""
        await self.live_q.put(self._stamp_lbuf_dict(live_dict))

    def put_lbuf_nowait(self, live_dict: dict) -> None:
        """Non-awaiting form, for driver poll loops."""
        self.live_q.put_nowait(self._stamp_lbuf_dict(live_dict))

    def get_lbuf(self, live_key):
        """Return the latest ``(value, epoch)`` for *live_key*."""
        return self.live_buffer[live_key]

    # -- file connection keys ------------------------------------------------

    def new_file_conn_key(self, key: str):
        """Derive a file-connection UUID from *key* (md5, via the meta writer)."""
        return self.meta_writer.new_file_conn_key(key)

    def dflt_file_conn_key(self):
        """The default file connection's key: ``new_file_conn_key(str(None))``.

        A constant, not the action uuid -- an action's default HLO file is keyed
        independently of it, and using the action uuid here silently produces a
        different on-disk layout.
        """
        return self.meta_writer.dflt_file_conn_key()

    # -- clock ---------------------------------------------------------------

    def get_realtime_nowait(
        self, epoch_ns: Optional[int] = None, offset: Optional[float] = None
    ) -> int:
        """Return NTP-corrected time in nanoseconds.

        Reproduces ``LiveBufferManager.get_realtime_nowait`` over the clock port
        instead of a cached ``ntp_offset``: an explicit *offset* wins, otherwise
        the port's, otherwise zero. Stamped onto every HLO header and every data
        message, so a drift here is a wire-visible artifact difference.
        """
        import math

        clock = self.hexagon_wiring.clock
        if offset is None:
            port_offset = clock.offset()
            offset_ns = int(math.floor(port_offset * 1e9)) if port_offset else 0
        else:
            offset_ns = int(math.floor(offset * 1e9))
        base_ns = clock.now_ns() if epoch_ns is None else epoch_ns
        return int(math.floor(base_ns + offset_ns))

    async def get_realtime(
        self, epoch_ns: Optional[int] = None, offset: Optional[float] = None
    ) -> int:
        """Async form; legacy delegates straight to the sync one, as here."""
        return self.get_realtime_nowait(epoch_ns=epoch_ns, offset=offset)

    # -- state the routes operate on -----------------------------------------

    async def attach_status_client(
        self,
        client_servkey: str,
        client_host: str,
        client_port: int,
        retry_limit: int = 5,
    ) -> bool:
        """Subscribe a remote client to this server's status updates."""
        return await self.hexagon_wiring.status.attach_client(
            client_servkey, client_host, client_port, retry_limit=retry_limit
        )

    async def detach_status_client(
        self, client_servkey: str, client_host: str, client_port: int
    ):
        """Remove a remote client from this server's status subscribers."""
        return await self.hexagon_wiring.status.detach_client(
            client_servkey, client_host, client_port
        )

    def stop_executor(self, executor_id: str) -> dict:
        """Legacy's spelling; the estop handler and clients both use it."""
        return self.stop_executor_by_id(executor_id)

    def stop_executor_by_id(self, executor_id: str) -> dict:
        """Signal one executor to stop its polling loop.

        Returns ``{"success": False}`` for an unknown id rather than raising:
        the orchestrator calls this during teardown, when an executor may
        already have finished on its own.
        """
        # The value is the SESSION, not the Executor: action_loop_task
        # registers `base.executors[exec_id] = self.active`, and the session is
        # what carries stop_action_task.
        session = self.executors.get(executor_id)
        if session is None:
            LOGGER.warning(f"no running executor '{executor_id}' to stop")
            return {"success": False, "executor_id": executor_id}
        session.stop_action_task()
        return {"success": True, "executor_id": executor_id}

    async def estop_actives(self) -> list:
        """Finalize every in-flight action with ``estopped`` status.

        Iterates the live session registry, which is empty until Task 5 opens
        sessions — an idle server estops with nothing to finalize, which is the
        correct outcome and is what an idle legacy server does too.
        """
        estopped = []
        for action_uuid, session in list(self.actives.items()):
            try:
                await session.set_estop()
                estopped.append(str(action_uuid))
            except Exception:
                LOGGER.exception(f"failed to estop active action {action_uuid}")
        return estopped

    # -- route registration --------------------------------------------------

    def _register_middleware(self) -> None:
        """Serialize colliding action POSTs, and pass everything else through.

        **Nothing in a route diff sees this.** Serialized and concurrent
        execution both return 200; only the interleaving differs, and on a
        station that difference is two actions driving one instrument at once.

        Three ways through, in the order legacy checks them:

        1. the endpoint is idle, or the caller said ``no_wait``, or this is
           already a requeued launch -- run it;
        2. the server disallows concurrency and *any* endpoint is busy -- park
           it on the unified queue;
        3. this endpoint is busy -- park it on that endpoint's queue.

        A parked action is answered 200 with its own action dict, not held
        open: the caller gets a real action uuid to track, and
        ``process_endpoint_queue`` redispatches it when the endpoint frees.
        """
        from socket import gethostname

        from starlette.requests import Request
        from starlette.responses import JSONResponse, Response

        from helao.core.models.action_start_condition import ActionStartCondition as ASC
        from helao.core.models.machine import MachineModel
        from helao.helpers.eval import eval_val
        from helao.helpers.time_utils import gen_uuid

        server_key = self.server_key

        def _park(action_dict, request, queue, why: str):
            """Build the queued action, announce it, and park it on *queue*."""
            action_dict["action_params"] = action_dict.get("action_params", {})
            action_dict["action_params"]["queued_on_actserv"] = True
            extra_params = {}
            action = Action.model_validate(action_dict)
            action.action_uuid = gen_uuid()
            for d in (request.query_params, request.path_params):
                for k, v in d.items():
                    if k in ACTION_PARAM_KEYS:
                        extra_params[k] = eval_val(v)
                    else:
                        action.action_params[k] = eval_val(v)
            action.action_name = request.url.path.strip("/").split("/")[-1]
            action.action_server = MachineModel(
                server_name=server_key, machine_name=gethostname().lower()
            )
            LOGGER.info(f"{why}, queuing action {action.action_uuid}")
            queue.append((action, extra_params))
            return action

        @self.middleware("http")
        async def app_entry(request: Request, call_next):
            """Queue colliding action POSTs; pass everything else through."""
            endpoint = request.url.path.strip("/").split("/")[-1]
            is_action_post = (
                request.url.path.strip("/").startswith(f"{server_key}/")
                and request.method == "POST"
            )

            if request.method == "HEAD":
                # The endpoint checker probes with session.head(); without this
                # a liveness probe gets 405 and reads the server as unhealthy.
                LOGGER.debug("got HEAD request in middleware")
                return Response()

            if not is_action_post:
                return await call_next(request)

            body_dict = json.loads(await request.body())
            action_dict = body_dict.get("action", {})
            start_cond = action_dict.get("start_condition", ASC.wait_for_all)
            ep_model = self.actionservermodel.endpoints.get(endpoint)
            busy = bool(ep_model.active_dict) if ep_model is not None else False

            if (
                not busy
                or start_cond == ASC.no_wait
                or action_dict.get("action_params", {}).get("queued_launch", False)
            ):
                return await call_next(request)

            if not self.server_params.get("allow_concurrent_actions", True):
                active_endpoints = [
                    ep
                    for ep, em in self.actionservermodel.endpoints.items()
                    if em.active_dict
                ]
                if not active_endpoints:
                    return await call_next(request)
                action = _park(
                    action_dict,
                    request,
                    self.local_action_queue,
                    "action server is busy and does not allow concurrency",
                )
                await self.status_q.put(action.get_act())
                return JSONResponse(action.as_dict())

            action = _park(
                action_dict,
                request,
                self.endpoint_queues[endpoint],
                "simultaneous action requests received",
            )
            await self.status_q.put(action.get_act())
            return JSONResponse(action.as_dict())

    def _register_exception_handler(self) -> None:
        """E-stop in-flight work when an action route raises.

        An exception escaping an action endpoint means the driver is in an
        unknown state while hardware may still be moving. Legacy latches estop
        on every live action and stops every executor before letting FastAPI
        render the error; a bare 500 would leave both running.

        Scoped to this server's own action paths -- a raising private route
        (``/get_status`` and friends) must not estop the station.
        """
        from fastapi.exception_handlers import http_exception_handler
        from starlette.exceptions import HTTPException as StarletteHTTPException

        @self.exception_handler(StarletteHTTPException)
        async def custom_http_exception_handler(request, exc):
            """Estop live actions, then delegate to FastAPI's default."""
            if request.url.path.strip("/").startswith(f"{self.server_key}/"):
                LOGGER.error(f"Could not process request: {repr(exc)}")
                for _, session in list(self.actives.items()):
                    session.set_estop()
                # list() on both: stop_action_task only sets flags, but the
                # executor loop pops its own exec_id on completion, so a
                # concurrent finish would mutate these mid-iteration. Legacy
                # iterates them live -- an internal defect, invisible on disk
                # and on the wire, so it is fixed here rather than reproduced.
                for executor_id in list(self.executors):
                    self.stop_executor(executor_id)
            return await http_exception_handler(request, exc)

    def _register_websockets(self) -> None:
        """Register the three broadcast channels.

        Encodings are the ``BaseAPI`` family's and are frozen (Amendment 2 §3):
        a pickled ``ActionModel`` on ws_status, a pickled ``DataPackageModel`` on
        ws_data, a ``{datalab: (value, epoch)}`` dict on ws_live. ``OrchAPI``
        puts dicts under the same three names; converging the families would
        blank every subscriber of whichever one moved, with no error on either
        side.

        These do not appear in ``openapi.json``, so the surface gate cannot see
        them — they need their own connect-and-decode test.
        """

        async def _stream(publisher: WsPublisher, websocket: WebSocket) -> None:
            await publisher.connect(websocket)
            try:
                await publisher.broadcast(websocket)
            except (WebSocketDisconnect, ConnectionClosedOK):
                publisher.disconnect(websocket)

        @self.websocket("/ws_status")
        async def websocket_status(websocket: WebSocket):
            """Stream status updates until the client disconnects."""
            await _stream(self.status_publisher, websocket)

        @self.websocket("/ws_data")
        async def websocket_data(websocket: WebSocket):
            """Stream data packets until the client disconnects."""
            await _stream(self.data_publisher, websocket)

        @self.websocket("/ws_live")
        async def websocket_live(websocket: WebSocket):
            """Stream live-buffer values until the client disconnects."""
            await _stream(self.live_publisher, websocket)

    def _register_private_routes(self) -> None:
        """Register the eleven server-specific private routes.

        The set and their methods come from
        ``checklists/hte/_baseapi_system_surface.json``, captured live — not from
        the markdown checklist, which omitted eight routes and marked five GET.
        """

        @self.post("/get_config", tags=["private"])
        def get_config():
            """Return the world configuration dictionary."""
            return self.world_cfg

        @self.post("/hotreload_busy", tags=["private"])
        def hotreload_busy():
            """Report pending background work to the hot-reload idle gate.

            Opt-in via ``hotreload_busy_hook``; a server without one is never
            background-busy. **A raising hook reports busy**, so the watcher
            defers rather than restarting into an unknown state.
            """
            hook = self.hotreload_busy_hook
            if not callable(hook):
                return {"busy": False}
            try:
                return {"busy": bool(hook())}
            except Exception:
                return {"busy": True}

        @self.post("/get_status", tags=["private"])
        def get_status():
            """Return the action-server status with driver status appended."""
            status_dict = self.actionservermodel.model_dump()
            driver_status = "not_implemented"
            if isinstance(self.poller, DriverPoller):
                driver_status = DriverStatus.ok
            elif isinstance(self.driver, HelaoDriver):
                driver_status = self.driver.get_status().status
            status_dict["_driver_status"] = driver_status
            return status_dict

        @self.post("/attach_client", tags=["private"])
        async def attach_client(
            client_servkey: str, client_host: str, client_port: int
        ):
            """Subscribe a remote client to this server's status updates."""
            return await self.attach_status_client(
                client_servkey, client_host, client_port
            )

        @self.post("/detach_client", tags=["private"])
        async def detach_client(
            client_servkey: str, client_host: str, client_port: int
        ):
            """Remove a client from this server's status subscribers."""
            return await self.detach_status_client(
                client_servkey, client_host, client_port
            )

        @self.post("/stop_executor", tags=["private"])
        def stop_executor(executor_id: str):
            """Signal one executor to stop its polling loop."""
            return self.stop_executor_by_id(executor_id)

        @self.post("/endpoints", tags=["private"])
        def get_all_urls():
            """Return the endpoints registered on this server."""
            return self.fast_urls

        @self.post("/get_lbuf", tags=["private"])
        def get_lbuf():
            """Return the live buffer's current contents."""
            return self.live_buffer

        @self.post("/list_executors", tags=["private"])
        def list_executors():
            """Return the ids of every running executor."""
            return list(self.executors.keys())

        @self.post("/resend_active", tags=["private"])
        def resend_active(action_uuid: str):
            """Return the most recent active action, or a fresh one if none."""
            recent = [entry for _, entry in self.last_10_active]
            if recent:
                return recent[0].action.as_dict()
            return Action(action_uuid=action_uuid).as_dict()

        @self.post("/shutdown", tags=["private"])
        async def post_shutdown():
            """Trigger the shutdown handler over HTTP."""
            await self._shutdown()

    def _register_utility_routes(self) -> None:
        """Register the five debug endpoints shared with the orchestrator.

        Reimplemented here rather than imported from
        ``base_api._register_utility_endpoints``: the host must not import the
        engine it replaces, and these are five short handlers.
        """

        @self.post("/loaded_modules", tags=["private"])
        def loaded_modules():
            """Return ``{repo_file_path: sha1}`` for every repo module imported.

            The hot-reload watcher intersects a pulled commit's changed files
            with this set to decide whether this server must restart, and uses
            the hashes to confirm the on-disk file differs from what was loaded.
            Pure read; safe to call anytime.
            """
            return loaded_repo_modules()

        @self.post("/_raise_exception", tags=["private"])
        def _raise_exception():
            """Raise a synchronous test exception for error-recovery debugging."""
            raise Exception("test exception for error recovery debugging")

        @self.post("/_raise_async_exception", tags=["private"])
        async def _raise_async_exception():
            """Schedule a coroutine that raises after a 10-second delay."""

            async def sleep_then_error():
                print(f"Start time: {time.time()}")
                await asyncio.sleep(10)
                print(f"End time: {time.time()}")
                raise Exception("test async exception for error recovery debugging")

            asyncio.get_running_loop().create_task(sleep_then_error())
            return True

        @self.post("/test_alert", tags=["private"])
        async def test_alert():
            """Emit a test alert through the HELAO logger."""
            try:
                LOGGER.alert("TEST ALERT: this is a test alert.")
                return True
            except Exception:
                LOGGER.error("Failed to trigger alert.")
                return False

        @self.post("/test_receive", tags=["private"])
        async def test_receive(text: Annotated[str, Body(..., embed=True)]):
            """Echo ``text`` to the logger at INFO level."""
            try:
                LOGGER.info("TEST RECEIVE: " + text)
                return True
            except Exception:
                LOGGER.error("Failed to trigger receive: " + text)
                return False

    def _register_estop_route(self, server_key: str) -> None:
        """Register ``/{server_key}/estop``.

        Does **not** fabricate a placeholder estop action: an idle server writes
        no artifact, and the estop is recorded through the ``*_status`` fields of
        whatever was actually running.
        """

        @self.post(f"/{server_key}/estop", tags=["action"])
        async def estop(switch: bool = True):
            """Latch E-STOP, stop executors, finalize in-flight actions."""
            driver_estop = getattr(self.driver, "estop", None)
            driver_resp = None
            if driver_estop is not None and callable(driver_estop):
                driver_resp = await driver_estop(switch=switch)
            self.actionservermodel.estop = switch
            for executor_id in list(self.executors):
                self.stop_executor_by_id(executor_id)
            estopped = await self.estop_actives()
            return {
                "estop": switch,
                "estopped_actions": estopped,
                "driver": driver_resp,
            }

    def _register_lifecycle_hooks(self) -> None:
        """Register startup (drivers, poller, dyn_endpoints) and shutdown."""

        @self.on_event("startup")
        def startup_event():
            """Construct drivers, the poller, the fault dir, and late routes."""
            # Captured here rather than at __init__: there is no running loop
            # until the app starts, and the executor runner needs this one.
            self.aloop = asyncio.get_running_loop()
            if self.root_dir is not None:
                self.fault_dir = os.path.join(self.root_dir, "FAULTS")
                os.makedirs(self.fault_dir, exist_ok=True)
                self.fault_file = open(
                    os.path.join(self.fault_dir, f"{self.server_key}_faults.txt"), "a"
                )
                faulthandler.enable(self.fault_file)

            if self._driver_classes:
                Drivers = namedtuple(
                    "Drivers", [d.__name__ for d in self._driver_classes]
                )
                built = {}
                for i, driver_class in enumerate(self._driver_classes):
                    # Dual convention, permanent (spec §4): a HelaoDriver takes
                    # its config; anything else takes the host. The test
                    # deployment's sims are bare helpers by standing decision,
                    # so this is not a migration stopgap.
                    if issubclass(driver_class, HelaoDriver):
                        inst = driver_class(config=self.server_params)
                        if i == 0 and self._poller_class is not None:
                            self.poller = self._poller_class(
                                inst, self.server_cfg.get("polling_time", 0.1)
                            )
                            self.poller._base_hook = self
                    else:
                        inst = driver_class(self)
                    built[driver_class.__name__] = inst
                self.drivers = Drivers(**built)
                self.driver = self.drivers[0]

            # Endpoint status registration also invokes dyn_endpoints, so it
            # replaces the direct call: registering before late routes exist
            # would leave them unmonitored and unqueueable.
            self.dyn_endpoints_init()

        @self.on_event("shutdown")
        async def shutdown_event():
            """Shut the host down and run the driver's shutdown hooks."""
            await self._shutdown()

    async def _shutdown(self) -> dict:
        """Stop the poller, run driver shutdown hooks, close the fault log.

        The poller stops **before** the driver disconnects: it loops on
        ``while True`` and is not otherwise cancelled, so a poll after
        ``disconnect()`` calls ``get_data()`` on a dead handle and spams errors
        until process exit.
        """
        LOGGER.info("action shutdown")
        if isinstance(self.poller, DriverPoller):
            LOGGER.info("stopping driver poller before disconnect")
            await self.poller.stop()

        retvals: dict = {}
        shutdown = getattr(self.driver, "shutdown", None)
        async_shutdown = getattr(self.driver, "async_shutdown", None)
        retvals["shutdown"] = shutdown() if callable(shutdown) else None
        retvals["async_shutdown"] = (
            await async_shutdown() if callable(async_shutdown) else None
        )

        if self.fault_file is not None:
            faulthandler.disable()
            self.fault_file.close()
            self.fault_file = None
        return retvals
