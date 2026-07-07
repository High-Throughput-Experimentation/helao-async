"""FastAPI scaffolding for HELAO action servers.

Provides the ``BaseAPI`` application class, the action-endpoint route wrapper
that captures the per-request ``Action`` into a ``ContextVar``, the middleware
that queues simultaneous action POSTs, and the shared private/utility
endpoints registered on every Base- or Orch-style server.
"""

import os
import json
import time
import asyncio
import inspect
import functools
import faulthandler
from contextvars import ContextVar
from copy import copy
from dataclasses import dataclass
from socket import gethostname
from collections import namedtuple
from typing import Callable, Optional
from typing_extensions import Annotated

from helao.core.drivers.helao_driver import HelaoDriver, DriverPoller, DriverStatus
from helao.helpers.eval import eval_val
from helao.helpers.time_utils import gen_uuid
from helao.core.servers.base import Base
from helao.helpers.server_api import HelaoFastAPI
from helao.helpers.premodels import Action
from helao.core.models.machine import MachineModel
from fastapi import Body, WebSocket, WebSocketDisconnect, Request
from fastapi.routing import APIRoute
from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException as StarletteHTTPException
from helao.core.models.hlostatus import HloStatus
from helao.core.models.action_start_condition import ActionStartCondition as ASC
from starlette.responses import JSONResponse, Response
from websockets.exceptions import ConnectionClosedOK
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

# ---------------------------------------------------------------------------
# Module-level helpers shared between BaseAPI and OrchAPI
# ---------------------------------------------------------------------------

#: Query/path parameter keys that belong to the action envelope (not action_params).
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


# ---------------------------------------------------------------------------
# Action context: lets Base.setup_action / Base.setup_and_contain_action
# recover the route's Action + endpoint reference without inspecting frames.
# Populated by the per-request wrapper installed via ActionAPIRoute.
# ---------------------------------------------------------------------------


@dataclass
class ActionInvocation:
    """Snapshot of an action-tagged endpoint invocation for one request.

    Attributes:
        action: The ``Action`` reconstructed from the request's kwargs.
        endpoint_func: The underlying endpoint function being invoked.
    """

    action: Action
    endpoint_func: Callable


ACTION_CTX: ContextVar[Optional[ActionInvocation]] = ContextVar(
    "helao_action_ctx", default=None
)


def _build_action_from_kwargs(
    kwargs: dict, default_params: Optional[dict] = None
) -> Action:
    """Build an ``Action`` from an endpoint's parsed keyword arguments.

    Picks the first ``Action``-typed kwarg as the base action and folds every
    remaining kwarg into ``action.action_params`` unless that key has already
    been provided (for example by the orchestrator dispatcher). Endpoint
    parameters with Python defaults that were not supplied by the caller
    (e.g. omitted by the ZMQ-RPC fast path, which does not synthesize
    defaults) are also folded in via ``default_params`` so the action
    record reflects the values the endpoint actually ran with.

    Args:
        kwargs: Mapping of parameter name to value as resolved by FastAPI.
        default_params: Optional mapping of parameter name to default value
            collected from the wrapped function's signature. Used to fill
            in defaults that were not supplied via ``kwargs``.

    Returns:
        The reconstructed ``Action`` instance.
    """
    action: Optional[Action] = None
    seen_action_param: Optional[str] = None
    for name, val in kwargs.items():
        if isinstance(val, Action):
            if action is None:
                action = val
                seen_action_param = name
            else:
                LOGGER.error(
                    f"critical error: found another Action BaseModel under parameter '{name}', skipping it"
                )
    if action is None:
        LOGGER.error(
            "critical error: no Action BaseModel was found by setup_action, using blank Action."
        )
        action = Action()
    else:
        LOGGER.info(f"found Action BaseModel under parameter '{seen_action_param}'")

    for name, val in kwargs.items():
        if isinstance(val, Action):
            continue
        if name not in action.action_params:
            LOGGER.info(
                f"local var '{name}' not found in action.action_params, adding it."
            )
            action.action_params[name] = val

    if default_params:
        for name, val in default_params.items():
            if name in kwargs:
                continue
            if name in action.action_params:
                continue
            LOGGER.info(
                f"default for '{name}' not supplied in kwargs, adding to action.action_params."
            )
            action.action_params[name] = val

    LOGGER.info(f"Action.action_params: {action.action_params}")
    return action


def _collect_default_params(sig: inspect.Signature) -> dict:
    """Return ``{name: default}`` for sig parameters with usable Python defaults.

    Skips ``Action``-typed parameters (the Action itself is handled separately)
    and FastAPI parameter markers (``Body``/``Query``/``Path``/``Depends``/…),
    whose "default" is a sentinel rather than the value the endpoint sees.
    """
    try:
        from fastapi.params import Param as _FastAPIParam, Depends as _FastAPIDepends
        marker_types: tuple = (_FastAPIParam, _FastAPIDepends)
    except ImportError:
        marker_types = ()

    defaults: dict = {}
    for name, param in sig.parameters.items():
        if param.default is inspect.Parameter.empty:
            continue
        if marker_types and isinstance(param.default, marker_types):
            continue
        ann = param.annotation
        if isinstance(ann, type) and issubclass(ann, Action):
            continue
        defaults[name] = param.default
    return defaults


#: Attribute used to carry a per-endpoint action_version set via the
#: :func:`action_version` decorator until :func:`wrap_action_endpoint` reads it.
ACTION_VERSION_ATTR = "__helao_action_version__"

#: Default action schema version injected when an endpoint declares none.
DEFAULT_ACTION_VERSION = 1


def action_version(version: int) -> Callable:
    """Declare the schema version for a ``tags=["action"]`` endpoint.

    Apply below the route decorator on an action endpoint whose schema version
    differs from the default of ``1``. The value is injected as the endpoint's
    ``action_version`` parameter by :func:`wrap_action_endpoint`, so it appears
    in the request schema, in :meth:`Base.get_endpoint_urls`, and on the
    recorded action exactly as an inline ``action_version: int = N`` declaration
    used to. Endpoints that still declare ``action_version`` inline keep that
    value and ignore this decorator.

    Example::

        @app.post(f"/{server_key}/stop", tags=["action"])
        @action_version(2)
        async def stop():
            ...

    Args:
        version: The action schema version to advertise for the endpoint.

    Returns:
        A decorator that stamps ``version`` onto the endpoint function.
    """

    def decorator(fn: Callable) -> Callable:
        setattr(fn, ACTION_VERSION_ATTR, version)
        return fn

    return decorator


def _is_action_param(param: inspect.Parameter) -> bool:
    """Return True if ``param`` is annotated as an ``Action`` (sub)class."""
    ann = param.annotation
    return isinstance(ann, type) and issubclass(ann, Action)


def _build_action_endpoint_signature(fn: Callable, sig: inspect.Signature):
    """Augment ``fn``'s signature with injected ``action``/``action_version`` params.

    Action endpoints used to declare ``action: Action = Body({}, embed=True)``
    and ``action_version: int = N`` by hand. Those parameters exist purely so
    FastAPI builds the request body/query schema and so the orchestrator can
    introspect them; the endpoint body recovers the action from ``ACTION_CTX``
    instead. This helper synthesizes the same parameters on the
    FastAPI-visible signature when the endpoint omits them, keeping the
    generated schema and ``Base.get_endpoint_urls`` output identical to the
    old inline form.

    The ``action_version`` value is taken from an inline declaration if present,
    otherwise from the :func:`action_version` decorator attribute, otherwise
    :data:`DEFAULT_ACTION_VERSION`.

    Args:
        fn: The endpoint function being wrapped (source of the version attr).
        sig: ``fn``'s own signature.

    Returns:
        Tuple of ``(exposed_sig, accepts_var_keyword, accepted_names)`` where
        ``exposed_sig`` is the signature FastAPI should see, ``accepts_var_keyword``
        indicates whether ``fn`` has a ``**kwargs`` parameter, and
        ``accepted_names`` is the set of parameter names ``fn`` itself declares.
    """
    params = list(sig.parameters.values())
    accepts_var_keyword = any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in params
    )
    accepted_names = {
        p.name
        for p in params
        if p.kind is not inspect.Parameter.VAR_KEYWORD
        and p.kind is not inspect.Parameter.VAR_POSITIONAL
    }
    has_action = any(_is_action_param(p) for p in params)
    has_version = "action_version" in sig.parameters

    injected = []
    if not has_action:
        injected.append(
            inspect.Parameter(
                "action",
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=Body({}, embed=True),
                annotation=Action,
            )
        )
    if not has_version:
        version = getattr(fn, ACTION_VERSION_ATTR, DEFAULT_ACTION_VERSION)
        injected.append(
            inspect.Parameter(
                "action_version",
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=version,
                annotation=int,
            )
        )

    if not injected:
        return sig, accepts_var_keyword, accepted_names

    # KEYWORD_ONLY injected params must precede any VAR_KEYWORD (**kwargs) param.
    non_var = [p for p in params if p.kind is not inspect.Parameter.VAR_KEYWORD]
    var_kw = [p for p in params if p.kind is inspect.Parameter.VAR_KEYWORD]
    exposed_sig = sig.replace(parameters=non_var + injected + var_kw)
    return exposed_sig, accepts_var_keyword, accepted_names


def wrap_action_endpoint(fn: Callable) -> Callable:
    """Wrap an action endpoint so each invocation populates ``ACTION_CTX``.

    The wrapper exposes ``fn``'s signature (augmented with synthesized
    ``action``/``action_version`` parameters when the endpoint omits them; see
    :func:`_build_action_endpoint_signature`) so FastAPI parameter resolution,
    schema generation, and the ZMQ-RPC fast-path continue to work. The parsed
    kwargs are rebuilt into an ``Action`` and stored in a ``ContextVar`` so
    ``Base.setup_action`` and ``Base.setup_and_contain_action`` can recover the
    action without inspecting caller frames. Only the parameters ``fn`` actually
    declares are forwarded to it, so the injected envelope parameters never leak
    into endpoints that do not declare them.

    Args:
        fn: The action endpoint function to wrap.

    Returns:
        A wrapper exposing the augmented signature that sets ``ACTION_CTX``
        for the duration of the call.
    """
    sig = inspect.signature(fn)
    exposed_sig, accepts_var_keyword, accepted_names = (
        _build_action_endpoint_signature(fn, sig)
    )
    default_params = _collect_default_params(exposed_sig)
    is_async = asyncio.iscoroutinefunction(fn)

    def _forward_kwargs(kwargs: dict) -> dict:
        """Keep only the kwargs ``fn`` declares (all of them if it has **kwargs)."""
        if accepts_var_keyword:
            return kwargs
        return {k: v for k, v in kwargs.items() if k in accepted_names}

    if is_async:

        @functools.wraps(fn)
        async def wrapper(**kwargs):
            action = _build_action_from_kwargs(kwargs, default_params)
            token = ACTION_CTX.set(
                ActionInvocation(action=action, endpoint_func=fn)
            )
            try:
                return await fn(**_forward_kwargs(kwargs))
            finally:
                ACTION_CTX.reset(token)

    else:

        @functools.wraps(fn)
        def wrapper(**kwargs):
            action = _build_action_from_kwargs(kwargs, default_params)
            token = ACTION_CTX.set(
                ActionInvocation(action=action, endpoint_func=fn)
            )
            try:
                return fn(**_forward_kwargs(kwargs))
            finally:
                ACTION_CTX.reset(token)

    wrapper.__signature__ = exposed_sig  # type: ignore[attr-defined]
    return wrapper


class ActionAPIRoute(APIRoute):
    """``APIRoute`` subclass that auto-wraps endpoints tagged ``"action"``.

    Installing this as the router's ``route_class`` means every
    ``@app.post(..., tags=["action"])`` handler is transparently passed
    through :func:`wrap_action_endpoint` at registration time, with no
    changes needed in deployment endpoint files.
    """

    def __init__(self, *args, **kwargs):
        """Wrap the registered endpoint with ``wrap_action_endpoint`` when tagged ``"action"``."""
        tags = kwargs.get("tags") or []
        if "action" in tags:
            endpoint = kwargs.get("endpoint")
            if endpoint is not None:
                kwargs["endpoint"] = wrap_action_endpoint(endpoint)
        super().__init__(*args, **kwargs)


def _make_app_entry_middleware(server_key: str, get_srv) -> Callable:
    """Build the per-request ``app_entry`` middleware for an action server.

    The middleware queues incoming action POSTs when the endpoint is busy
    or when concurrency is disabled, dispatches HEAD requests to a no-op
    response, and otherwise forwards to ``call_next``.

    Args:
        server_key: Server key used to recognize routed action endpoints.
        get_srv: Zero-argument callable returning the live ``Base`` or
            ``Orch`` instance (resolved lazily, after startup).

    Returns:
        The middleware coroutine to register with the FastAPI app.
    """

    async def app_entry(request: Request, call_next):
        """Queue colliding action POSTs and pass other requests through."""
        srv = get_srv()
        endpoint = request.url.path.strip("/").split("/")[-1]
        if request.method == "HEAD":  # comes from endpoint checker, session.head()
            LOGGER.debug("got HEAD request in middleware")
            response = Response()
        elif (
            request.url.path.strip("/").startswith(f"{server_key}/")
            and request.method == "POST"
        ):
            LOGGER.debug("got action POST request in middleware")
            body_bytes = await request.body()
            body_dict = json.loads(body_bytes)
            action_dict = body_dict.get("action", {})
            start_cond = action_dict.get("start_condition", ASC.wait_for_all)
            if (
                len(srv.actionservermodel.endpoints[endpoint].active_dict) == 0
                or start_cond == ASC.no_wait
                or action_dict.get("action_params", {}).get("queued_launch", False)
            ):
                LOGGER.debug("action endpoint is available")
                response = await call_next(request)
            elif not srv.server_params.get("allow_concurrent_actions", True):
                active_endpoints = [
                    ep
                    for ep, em in srv.actionservermodel.endpoints.items()
                    if em.active_dict
                ]
                if len(active_endpoints) > 0:
                    LOGGER.info("action server is busy, queuing")
                    action_dict["action_params"] = action_dict.get("action_params", {})
                    action_dict["action_params"]["queued_on_actserv"] = True
                    extra_params = {}
                    action = Action(**action_dict)
                    action.action_uuid = gen_uuid()
                    for d in (request.query_params, request.path_params):
                        for k, v in d.items():
                            if k in ACTION_PARAM_KEYS:
                                extra_params[k] = eval_val(v)
                            else:
                                action.action_params[k] = eval_val(v)
                    action.action_name = endpoint
                    action.action_server = MachineModel(
                        server_name=server_key, machine_name=gethostname().lower()
                    )
                    await srv.status_q.put(action.get_act())
                    response = JSONResponse(action.as_dict())
                    LOGGER.info(
                        f"action request for {action.action_name} received, but server"
                        f" does not allow concurrency, queuing action {action.action_uuid}"
                    )
                    srv.local_action_queue.append((action, extra_params))
                else:
                    LOGGER.debug("action server is available")
                    response = await call_next(request)
            else:  # collision between two requests for one endpoint, queue
                LOGGER.info("action endpoint is busy, queuing")
                action_dict["action_params"] = action_dict.get("action_params", {})
                action_dict["action_params"]["queued_on_actserv"] = True
                extra_params = {}
                action = Action(**action_dict)
                action.action_uuid = gen_uuid()
                for d in (request.query_params, request.path_params):
                    for k, v in d.items():
                        if k in ACTION_PARAM_KEYS:
                            extra_params[k] = eval_val(v)
                        else:
                            action.action_params[k] = eval_val(v)
                action.action_name = endpoint
                action.action_server = MachineModel(
                    server_name=server_key, machine_name=gethostname().lower()
                )
                await srv.status_q.put(action.get_act())
                response = JSONResponse(action.as_dict())
                LOGGER.info(
                    f"simultaneous action requests for {action.action_name} received,"
                    f" queuing action {action.action_uuid}"
                )
                srv.endpoint_queues[endpoint].append((action, extra_params))
        else:
            response = await call_next(request)
        return response

    return app_entry


def _make_http_exception_handler(server_key: str, get_srv) -> Callable:
    """Build the Starlette HTTP exception handler for an action server.

    The returned handler triggers an emergency stop on all active actions
    and stops all executors when a routed action endpoint raises.

    Args:
        server_key: Server key used to recognize routed action endpoints.
        get_srv: Zero-argument callable returning the live ``Base`` or
            ``Orch`` instance.

    Returns:
        The exception handler coroutine to register with the FastAPI app.
    """

    async def custom_http_exception_handler(request, exc):
        """E-stop active work, then delegate to FastAPI's default handler."""
        if request.url.path.strip("/").startswith(f"{server_key}/"):
            print(f"Could not process request: {repr(exc)}")
            srv = get_srv()
            for _, active in srv.actives.items():
                active.set_estop()
            for executor_id in srv.executors:
                srv.stop_executor(executor_id)
        return await http_exception_handler(request, exc)

    return custom_http_exception_handler


def _add_default_head_endpoints(app) -> None:
    """Mirror every POST route as a HEAD route used by the endpoint checker."""
    for route in app.routes:
        if isinstance(route, APIRoute) and "POST" in route.methods:
            new_route = copy(route)
            new_route.methods = {"HEAD"}
            new_route.include_in_schema = False
            app.routes.append(new_route)


def _register_utility_endpoints(fastapp) -> None:
    """Register the shared debug/private endpoints used by Base and Orch APIs."""

    @fastapp.post("/_raise_exception", tags=["private"])
    def _raise_exception():
        """Raise a synchronous test exception for error-recovery debugging."""
        raise Exception("test exception for error recovery debugging")

    @fastapp.post("/_raise_async_exception", tags=["private"])
    async def _raise_async_exception():
        """Schedule a coroutine that raises after a 10-second delay."""

        async def sleep_then_error():
            print(f"Start time: {time.time()}")
            await asyncio.sleep(10)
            print(f"End time: {time.time()}")
            raise Exception("test async exception for error recovery debugging")

        loop = asyncio.get_running_loop()
        loop.create_task(sleep_then_error())
        return True

    @fastapp.post("/test_alert", tags=["private"])
    async def test_alert():
        """Emit a test alert through the HELAO logger."""
        try:
            LOGGER.alert("TEST ALERT: this is a test alert.")
            return True
        except Exception:
            LOGGER.error("Failed to trigger alert.")
            return False

    @fastapp.post("/test_receive", tags=["private"])
    async def test_receive(text: Annotated[str, Body(..., embed=True)]):
        """Echo ``text`` to the logger at INFO level."""
        try:
            LOGGER.info("TEST RECEIVE: " + text)
            return True
        except Exception:
            LOGGER.error("Failed to trigger receive: " + text)
            return False


class BaseAPI(HelaoFastAPI):
    """FastAPI application class used by every HELAO action server.

    Wires up the ``Base`` controller as a startup event, installs the
    action-queueing middleware and HTTP exception handler, exposes the
    status/data/live WebSocket endpoints, and registers the standard
    private endpoints (config, status, client attach/detach, executor
    control, debug utilities, emergency stop, shutdown).

    Attributes:
        base: The ``Base`` controller instance bound to this app.
        driver: First entry of ``drivers`` if any, else ``None``.
        poller: Optional ``DriverPoller`` instance.
        drivers: Named-tuple of constructed driver instances.
        root_dir: Resolved root directory for outputs.
        fault_dir: Directory used for fault dumps and logs.
    """

    base: Base
    root_dir: str
    fault_dir: str
    drivers: tuple

    def __init__(
        self,
        server_key,
        server_title,
        description,
        version,
        driver_classes=None,
        dyn_endpoints=None,
        poller_class=None,
    ):
        """Initialize the BaseAPI app and register its routes and events.

        Args:
            server_key: Unique key identifying the server in the world config.
            server_title: Title of the server, surfaced to the OpenAPI docs.
            description: OpenAPI description of the server.
            version: Server/version string.
            driver_classes: Optional iterable of driver classes to instantiate
                on startup; ``HelaoDriver`` subclasses receive ``server_params``,
                others receive the ``Base`` instance.
            dyn_endpoints: Optional callable invoked with the app instance to
                register additional routes at startup.
            poller_class: Optional ``DriverPoller`` subclass attached to the
                first driver if a poller is desired.
        """
        super().__init__(
            helao_srv=server_key,
            title=server_title,
            description=description,
            version=str(version),
        )
        self.drivers = tuple()
        self.driver = None
        self.poller = None

        self.middleware("http")(_make_app_entry_middleware(server_key, lambda: self.base))
        self.exception_handler(StarletteHTTPException)(
            _make_http_exception_handler(server_key, lambda: self.base)
        )

        @self.on_event("startup")
        def startup_event():
            """Construct the ``Base`` controller, drivers, poller and fault dir on startup."""
            self.base = Base(app=self, dyn_endpoints=dyn_endpoints)

            self.root_dir = self.base.world_cfg.get("root", None)
            if self.root_dir is not None:
                self.fault_dir = os.path.join(self.root_dir, "FAULTS")
                os.makedirs(self.fault_dir, exist_ok=True)
                fault_path = os.path.join(self.fault_dir, f"{server_key}_faults.txt")
                self.fault_file = open(fault_path, "a")
                faulthandler.enable(self.fault_file)

            self.base.myinit()
            if driver_classes is not None:
                Drivers = namedtuple("Drivers", [d.__name__ for d in driver_classes])
                driver_dict = {}
                for i, driver_class in enumerate(driver_classes):
                    if issubclass(driver_class, HelaoDriver):
                        driver_inst = driver_class(config=self.server_params)
                        if i == 0 and poller_class is not None:
                            self.poller = poller_class(
                                driver_inst, self.server_cfg.get("polling_time", 0.1)
                            )
                            self.poller._base_hook = self.base
                    else:
                        driver_inst = driver_class(self.base)
                    driver_dict[driver_class.__name__] = driver_inst
                self.drivers = Drivers(**driver_dict)
                self.driver = self.drivers[0]
            self.base.dyn_endpoints_init()

        self.on_event("startup")(lambda: _add_default_head_endpoints(self))

        @self.websocket("/ws_status")
        async def websocket_status(websocket: WebSocket):
            """Subscribe the client to the status publisher and stream updates until disconnect."""
            await self.base.status_publisher.connect(websocket)
            try:
                await self.base.status_publisher.broadcast(websocket)
            except WebSocketDisconnect:
                self.base.status_publisher.disconnect(websocket)
            except ConnectionClosedOK:
                self.base.status_publisher.disconnect(websocket)

        @self.websocket("/ws_data")
        async def websocket_data(websocket: WebSocket):
            """Subscribe the client to the data publisher and stream packets until disconnect."""
            await self.base.data_publisher.connect(websocket)
            try:
                await self.base.data_publisher.broadcast(websocket)
            except WebSocketDisconnect:
                self.base.data_publisher.disconnect(websocket)
            except ConnectionClosedOK:
                self.base.data_publisher.disconnect(websocket)

        @self.websocket("/ws_live")
        async def websocket_live(websocket: WebSocket):
            """Subscribe the client to the live-buffer publisher and stream until disconnect."""
            await self.base.live_publisher.connect(websocket)
            try:
                await self.base.live_publisher.broadcast(websocket)
            except WebSocketDisconnect:
                self.base.live_publisher.disconnect(websocket)
            except ConnectionClosedOK:
                self.base.live_publisher.disconnect(websocket)

        @self.post("/get_config", tags=["private"])
        def get_config():
            """Return the world configuration dictionary."""
            return self.base.world_cfg

        @self.post("/get_status", tags=["private"])
        def get_status():
            """Return the action server status with the driver/poller status appended."""
            status_dict = self.base.actionservermodel.model_dump()
            driver_status = "not_implemented"
            # first check if poller is available
            if isinstance(self.poller, DriverPoller):
                resp = self.poller.live_dict
                driver_status = DriverStatus.ok
            # if no poller, but HelaoDriver, use get_status method
            elif isinstance(self.driver, HelaoDriver):
                resp = self.driver.get_status()
                driver_status = resp.status
            status_dict["_driver_status"] = driver_status
            return status_dict

        @self.post("/attach_client", tags=["private"])
        async def attach_client(
            client_servkey: str, client_host: str, client_port: int
        ):
            """Subscribe a remote client to this server's status updates.

            Args:
                client_servkey: Service key of the client to subscribe.
                client_host: Hostname of the client.
                client_port: Port the client listens on.

            Returns:
                Result of ``Base.attach_client`` (True on success).
            """
            return await self.base.attach_client(
                client_servkey, client_host, client_port
            )

        @self.post("/detach_client", tags=["private"])
        def detach_client(client_servkey: str, client_host: str, client_port: int):
            """Remove a client from this server's status subscriber list."""
            return self.base.detach_client(client_servkey, client_host, client_port)

        @self.post("/stop_executor", tags=["private"])
        def stop_executor(executor_id: str):
            """Signal the executor with ``executor_id`` to stop its polling loop."""
            return self.base.stop_executor(executor_id)

        @self.post("/endpoints", tags=["private"])
        def get_all_urls():
            """Return the list of endpoints registered on this server."""
            return self.base.fast_urls

        @self.post("/get_lbuf", tags=["private"])
        def get_lbuf():
            """Return the current contents of the live buffer."""
            return self.base.live_buffer

        @self.post("/list_executors", tags=["private"])
        def list_executors():
            """Return the keys of all currently running executors."""
            return list(self.base.executors.keys())

        _register_utility_endpoints(self)

        @self.post("/resend_active", tags=["private"])
        def resend_active(action_uuid: str):
            """Return the most recent active action or a fresh ``Action`` if none exist."""
            l10 = [y for x, y in self.base.last_10_active]
            if l10:
                return l10[0].action.as_dict()
            else:
                return Action(action_uuid=action_uuid).as_dict()

        @self.post("/shutdown", tags=["private"])
        async def post_shutdown():
            """Trigger the FastAPI shutdown handler via an HTTP request."""
            await shutdown_event()

        @self.on_event("shutdown")
        async def shutdown_event():
            """Shut down the ``Base`` controller, invoke driver shutdown hooks, and close fault logs.

            Returns:
                A dict with the return values of the driver's ``shutdown`` and
                ``async_shutdown`` methods (or ``None`` if not implemented).
            """
            LOGGER.info("action shutdown")
            await self.base.shutdown()

            shutdown = getattr(self.driver, "shutdown", None)
            async_shutdown = getattr(self.driver, "async_shutdown", None)

            retvals = {}
            if shutdown is not None and callable(shutdown):
                LOGGER.info("driver has shutdown function")
                retvals["shutdown"] = shutdown()
            else:
                LOGGER.info("driver has NO shutdown function")
                retvals["shutdown"] = None
            if async_shutdown is not None and callable(async_shutdown):
                LOGGER.info("driver has async_shutdown function")
                retvals["async_shutdown"] = await async_shutdown()
            else:
                LOGGER.info("driver has NO async_shutdown function")
                retvals["async_shutdown"] = None

            if self.root_dir is not None:
                faulthandler.disable()
                self.fault_file.close()
            return retvals

        @self.post(f"/{server_key}/estop", tags=["action"])
        async def estop(
            switch: bool = True,
        ):
            """Trigger an emergency stop.

            Calls the driver's estop hook (if any), latches the E-STOP flag,
            stops all running executors, and finalizes any actions that were
            actually in-flight with ``estopped`` status (moving them to
            ``RUNS_FINISHED`` via their normal lifecycle).

            Unlike the previous implementation, this does NOT fabricate a
            placeholder ``estop`` action. An idle server writes no artifact; the
            estop is recorded purely through the ``*_status`` fields of the
            actions/experiment/sequence that were running.
            """
            has_estop = getattr(self.driver, "estop", None)
            driver_resp = None
            if has_estop is not None and callable(has_estop):
                LOGGER.info("driver has estop function")
                driver_resp = await self.driver.estop(switch=switch)
            else:
                LOGGER.info("driver has NO estop function")
            self.base.actionservermodel.estop = switch
            for executor_id in list(self.base.executors):
                self.base.stop_executor(executor_id)
            estopped_actions = await self.base.estop_actives()
            return {
                "estop": switch,
                "estopped_actions": estopped_actions,
                "driver": driver_resp,
            }

