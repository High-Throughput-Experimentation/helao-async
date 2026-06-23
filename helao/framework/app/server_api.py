"""Deployment-compatible FastAPI subclass wrapping FrameworkBase.

Port of the ``BaseAPI`` pattern from ``helao.core.servers.base_api``.
Deployment action servers do:

    app = BaseAPI(server_key=server_key, driver_classes=[MyDriver])

and then decorate ``@app.post(...)`` endpoints that call
``await app.base.setup_and_contain_action()``. This class wires a
``FrameworkBase`` with real adapters and exposes it as ``app.base``.

SP8 WS-B/WS-C add the production surface on top of the action-server core:
the ``/ws_status`` / ``/ws_data`` / ``/ws_live`` WebSocket publishers (backed
by the ``EventSink`` subscription), the per-server admin endpoints
(``/get_config`` / ``/endpoints`` / ``/get_lbuf`` / ``/list_executors`` /
``/stop_executor`` / ``/resend_active`` / ``/shutdown``), the ``estop`` /
generic ``stop`` action endpoints, HEAD mirrors of every POST route, dual-
convention driver instantiation, and the startup/shutdown lifecycle hooks.
"""

__all__ = ["BaseAPI", "ActionAPIRoute", "wrap_action_endpoint"]

import asyncio
import functools
import inspect
import tempfile
from copy import copy
from typing import Callable, Dict, List, Optional, Type

from fastapi import Body, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.routing import APIRoute

from helao.framework.app.base_api import FrameworkBase, ActionContext, ACTION_CTX
from helao.framework.adapters.fs_storage import FsStorage
from helao.framework.adapters.ntp_clock import NtpClock
from helao.framework.adapters.queue_eventsink import QueueEventSink
from helao.framework.adapters.fakes.transport import FakeTransport
from helao.framework.domain.run_models import RunAction
from helao.framework.models.action import ActionModel
from helao.framework.models.hlostatus import HloStatus
from helao.framework.ports.driver import HelaoDriver
from helao.framework.ports.eventsink import (
    DATA_CHANNEL,
    STATUS_CHANNEL,
)
import helao.framework.support.config_loader as _cfg

from helao.framework.support import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: Default action schema version injected when an endpoint declares none.
DEFAULT_ACTION_VERSION = 1


def _load_world_cfg() -> Dict:
    cfg = _cfg.CONFIG
    if cfg is None:
        return {}
    try:
        return dict(cfg)
    except Exception:
        return {}


# --- route introspection + HEAD mirrors (ports helao.core.servers.base_api) ---


def _build_fast_urls(app: FastAPI) -> List[dict]:
    """Return a ``fast_urls``-style descriptor list for every route on ``app``.

    Ports ``Base.get_endpoint_urls``: each entry is ``{"path", "name", "params"}``
    where ``params`` maps each flat request parameter name to its outer type. The
    orchestrator consumes this from the ``/endpoints`` POST endpoint to learn the
    server's callable surface.
    """
    try:
        from fastapi.dependencies.utils import get_flat_params
    except Exception:  # pragma: no cover - fastapi internals moved
        get_flat_params = None

    url_list: List[dict] = []
    for route in getattr(app, "routes", []):
        route_d: dict = {
            "path": getattr(route, "path", ""),
            "name": getattr(route, "name", ""),
        }
        dependant = getattr(route, "dependant", None)
        if dependant is not None and get_flat_params is not None:
            try:
                flat = get_flat_params(dependant)
                param_d = {}
                for par in flat:
                    ann = str(getattr(par.field_info, "annotation", par))
                    parts = ann.split("'")
                    outer = parts[1] if len(parts) >= 2 else ann
                    param_d[par.name] = {"outer_type": outer}
                route_d["params"] = param_d
            except Exception:
                route_d["params"] = {}
        else:
            route_d["params"] = []
        url_list.append(route_d)
    return url_list


def _add_default_head_endpoints(app: FastAPI) -> None:
    """Mirror every registered POST route as a HEAD route.

    Ports ``base_api._add_default_head_endpoints``: the dispatcher's
    ``endpoints_available`` check issues ``session.head()`` against each endpoint
    URL, so every POST route needs a matching HEAD route returning 200. Each
    mirror is a shallow copy of the POST route with its methods set to ``HEAD``
    and excluded from the OpenAPI schema.
    """
    for route in list(app.routes):
        if isinstance(route, APIRoute) and "POST" in (route.methods or set()):
            new_route = copy(route)
            new_route.methods = {"HEAD"}
            new_route.include_in_schema = False
            app.routes.append(new_route)


# --- websocket relay (ports Base._ws_relay / ws_status / ws_data / ws_live) ---


async def _ws_relay(
    base: FrameworkBase,
    websocket: WebSocket,
    channel: str,
    label: str,
) -> None:
    """Accept ``websocket`` and forward eventsink payloads on ``channel`` to it.

    Ports ``Base._ws_relay``: subscribes to the base's :class:`EventSink`
    (returns an :class:`asyncio.Queue` of ``(channel, payload)`` tuples), and for
    every tuple whose channel matches ``channel`` sends the payload as JSON until
    the client disconnects. On disconnect the subscription is simply dropped (the
    queue is garbage-collected).
    """
    LOGGER.info(f"got new {label} subscriber")
    await websocket.accept()
    sub = base.eventsink.subscribe()
    try:
        while True:
            ch, payload = await sub.get()
            if ch == channel:
                await websocket.send_json(dict(payload))
    except WebSocketDisconnect:
        LOGGER.info(f"{label} websocket client disconnected")
    except Exception as exc:  # connection reset / closed
        LOGGER.info(f"{label} websocket relay ended: {exc!r}")


async def _ws_live_relay(base: FrameworkBase, websocket: WebSocket) -> None:
    """Accept ``websocket`` and stream live-buffer snapshots to it.

    Ports ``Base.ws_live``: the framework has no separate live queue, so instead
    of relaying a stream this periodically sends the current ``live_buffer``
    snapshot (``{key: [value, epoch_s]}``) until the client disconnects.
    """
    LOGGER.info("got new live_buffer subscriber")
    await websocket.accept()
    try:
        while True:
            snapshot = {k: list(v) for k, v in base.live_buffer.items()}
            await websocket.send_json(snapshot)
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        LOGGER.info("live_buffer websocket client disconnected")
    except Exception as exc:
        LOGGER.info(f"live_buffer websocket relay ended: {exc!r}")


# --- action-endpoint request wrapping (ports helao.core.servers.base_api) -----


def _build_action_from_kwargs(kwargs: dict, default_params: Optional[dict] = None) -> RunAction:
    """Build a :class:`RunAction` from an endpoint's parsed keyword arguments.

    Picks the first ``ActionModel``-typed kwarg as the base action (coercing it
    to a :class:`RunAction`), then folds every remaining kwarg into
    ``action_params`` unless that key was already supplied (e.g. by the
    orchestrator dispatcher). Endpoint defaults not supplied by the caller are
    filled from ``default_params``. Ports ``base_api._build_action_from_kwargs``.
    """
    action: Optional[RunAction] = None
    seen: Optional[str] = None
    for name, val in kwargs.items():
        if isinstance(val, ActionModel):
            base = val if isinstance(val, RunAction) else RunAction(**val.model_dump())
            if action is None:
                action, seen = base, name
            else:
                LOGGER.error(
                    f"found another Action under parameter '{name}', skipping it"
                )
    if action is None:
        action = RunAction()
    else:
        LOGGER.info(f"found Action under parameter '{seen}'")

    for name, val in kwargs.items():
        if isinstance(val, ActionModel):
            continue
        if name not in action.action_params:
            action.action_params[name] = val

    if default_params:
        for name, val in default_params.items():
            if name in kwargs or name in action.action_params:
                continue
            action.action_params[name] = val
    return action


def _collect_default_params(sig: inspect.Signature) -> dict:
    """Return ``{name: default}`` for sig params with usable Python defaults.

    Skips ``ActionModel``-typed params and FastAPI parameter markers
    (``Body``/``Query``/…) whose default is a sentinel. Ports
    ``base_api._collect_default_params``.
    """
    try:
        from fastapi.params import Param as _Param, Depends as _Depends
        marker_types: tuple = (_Param, _Depends)
    except ImportError:
        marker_types = ()
    defaults: dict = {}
    for name, param in sig.parameters.items():
        if param.default is inspect.Parameter.empty:
            continue
        if marker_types and isinstance(param.default, marker_types):
            continue
        ann = param.annotation
        if isinstance(ann, type) and issubclass(ann, ActionModel):
            continue
        defaults[name] = param.default
    return defaults


def _is_action_param(param: inspect.Parameter) -> bool:
    """Return True if ``param`` is annotated as an ``ActionModel`` (sub)class."""
    ann = param.annotation
    return isinstance(ann, type) and issubclass(ann, ActionModel)


def _build_action_endpoint_signature(fn: Callable, sig: inspect.Signature):
    """Augment ``fn``'s signature with an injected ``action`` body param when absent.

    Ports ``base_api._build_action_endpoint_signature`` (minus the
    ``action_version`` envelope, kept simple): action endpoints that do not
    declare an ``ActionModel`` parameter get a synthesized
    ``action: RunAction = Body({}, embed=True)`` so FastAPI builds the request
    body schema and the orchestrator's ``{"action": ...}`` payload is parsed.
    """
    params = list(sig.parameters.values())
    accepts_var_keyword = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params)
    accepted_names = {
        p.name
        for p in params
        if p.kind is not inspect.Parameter.VAR_KEYWORD
        and p.kind is not inspect.Parameter.VAR_POSITIONAL
    }
    has_action = any(_is_action_param(p) for p in params)
    if has_action:
        return sig, accepts_var_keyword, accepted_names

    injected = inspect.Parameter(
        "action",
        kind=inspect.Parameter.KEYWORD_ONLY,
        default=Body({}, embed=True),
        annotation=RunAction,
    )
    non_var = [p for p in params if p.kind is not inspect.Parameter.VAR_KEYWORD]
    var_kw = [p for p in params if p.kind is inspect.Parameter.VAR_KEYWORD]
    exposed_sig = sig.replace(parameters=non_var + [injected] + var_kw)
    return exposed_sig, accepts_var_keyword, accepted_names


def wrap_action_endpoint(fn: Callable) -> Callable:
    """Wrap an action endpoint so each invocation populates :data:`ACTION_CTX`.

    The wrapper exposes ``fn``'s signature (augmented with a synthesized
    ``action`` body param when omitted) so FastAPI parameter resolution and
    schema generation work, rebuilds the parsed kwargs into a :class:`RunAction`,
    and stores it in :data:`ACTION_CTX` for the duration of the call so
    ``FrameworkBase.setup_and_contain_action()`` can recover it without
    arguments. Only the parameters ``fn`` declares are forwarded to it.
    """
    sig = inspect.signature(fn)
    exposed_sig, accepts_var_keyword, accepted_names = _build_action_endpoint_signature(fn, sig)
    default_params = _collect_default_params(exposed_sig)
    is_async = asyncio.iscoroutinefunction(fn)

    def _forward(kwargs: dict) -> dict:
        if accepts_var_keyword:
            return kwargs
        return {k: v for k, v in kwargs.items() if k in accepted_names}

    if is_async:

        @functools.wraps(fn)
        async def wrapper(**kwargs):
            action = _build_action_from_kwargs(kwargs, default_params)
            token = ACTION_CTX.set(ActionContext(action=action, endpoint_name=fn.__name__))
            try:
                return await fn(**_forward(kwargs))
            finally:
                ACTION_CTX.reset(token)

    else:

        @functools.wraps(fn)
        def wrapper(**kwargs):
            action = _build_action_from_kwargs(kwargs, default_params)
            token = ACTION_CTX.set(ActionContext(action=action, endpoint_name=fn.__name__))
            try:
                return fn(**_forward(kwargs))
            finally:
                ACTION_CTX.reset(token)

    wrapper.__signature__ = exposed_sig  # type: ignore[attr-defined]
    return wrapper


class ActionAPIRoute(APIRoute):
    """``APIRoute`` subclass that auto-wraps endpoints tagged ``"action"``.

    Installing this as the router's ``route_class`` means every
    ``@app.post(..., tags=["action"])`` handler is transparently passed through
    :func:`wrap_action_endpoint` at registration time, so deployment endpoint
    files need no changes.
    """

    def __init__(self, *args, **kwargs):
        """Wrap the registered endpoint with ``wrap_action_endpoint`` when tagged ``"action"``."""
        tags = kwargs.get("tags") or []
        if "action" in tags:
            endpoint = kwargs.get("endpoint")
            if endpoint is not None:
                kwargs["endpoint"] = wrap_action_endpoint(endpoint)
        super().__init__(*args, **kwargs)


class BaseAPI(FastAPI):
    """FastAPI subclass that wires ``FrameworkBase`` for deployment action servers."""

    def __init__(
        self,
        server_key: str,
        *,
        driver_classes: Optional[List[Type]] = None,
        poller_class: Optional[Type] = None,
        save_root: Optional[str] = None,
        **fastapi_kwargs,
    ) -> None:
        super().__init__(**fastapi_kwargs)
        # auto-wrap every subsequently-registered tags=["action"] endpoint so
        # it publishes ACTION_CTX (ports core.servers.base_api.ActionAPIRoute).
        self.router.route_class = ActionAPIRoute
        self.server_key = server_key
        world_cfg = _load_world_cfg()
        server_cfg = world_cfg.get("servers", {}).get(server_key, {})
        self.base = FrameworkBase(
            server_key=server_key,
            storage=FsStorage(
                save_root=save_root
                or server_cfg.get("root", None)
                or tempfile.mkdtemp()
            ),
            eventsink=QueueEventSink(),
            clock=NtpClock(),
            transport=FakeTransport(),  # TODO SP8: replace with real transport wiring
            world_cfg=world_cfg,
        )
        # server params exposed to HelaoDriver subclasses (ports Base.server_params).
        self.server_params: Dict = self.base.server_params
        self._driver_classes: List[Type] = list(driver_classes or [])
        self._poller_class = poller_class
        self.driver = None
        self.poller = None
        self.drivers: dict = {}

        # Driver instantiation (WS-C task 5/6): dual-convention. ``HelaoDriver``
        # subclasses get ``config=server_params``; bare helpers get ``base``.
        # We try eagerly here (keeps unit tests that assert ``app.driver`` right
        # after construction green — e.g. test_base_api_instantiates_driver), but
        # the test sim drivers (WsSim/GPSim/CPSim) call asyncio.get_event_loop()
        # in __init__, which raises under Python 3.12 with no running loop. When
        # eager construction raises we defer the whole set to the startup hook
        # (where the event loop exists). Either way ``app.driver`` / ``app.drivers``
        # end up populated.
        self._drivers_deferred = False
        if self._driver_classes:
            try:
                self._instantiate_drivers()
            except RuntimeError as exc:
                # almost always the asyncio.get_event_loop() flake — defer to startup
                LOGGER.info(
                    f"deferring driver instantiation to startup hook: {exc!r}"
                )
                self.driver = None
                self.poller = None
                self.drivers = {}
                self._drivers_deferred = True

        @self.post("/get_status", tags=["private"])
        def get_status():
            """Return the action-server status with driver/poller status appended."""
            status_dict = self.base.actionservermodel.model_dump()
            driver_status = "not_implemented"
            if self.poller is not None and hasattr(self.poller, "live_dict"):
                driver_status = "ok"
            elif isinstance(self.driver, HelaoDriver):
                try:
                    resp = self.driver.get_status()
                    driver_status = getattr(resp, "status", "ok")
                except Exception:
                    driver_status = "error"
            elif self.driver is not None and hasattr(self.driver, "get_status"):
                try:
                    resp = self.driver.get_status()
                    driver_status = getattr(resp, "status", "ok")
                except Exception:
                    driver_status = "error"
            status_dict["_driver_status"] = driver_status
            return status_dict

        @self.post("/get_config", tags=["private"])
        def get_config():
            """Return the world configuration dictionary."""
            return self.base.world_cfg

        @self.post("/attach_client", tags=["private"])
        async def attach_client(
            client_servkey: str, client_host: str, client_port: int
        ):
            return await self.base.attach_client(
                client_servkey, client_host, client_port
            )

        @self.post("/detach_client", tags=["private"])
        async def detach_client(
            client_servkey: str, client_host: str, client_port: int
        ):
            return self.base.detach_client(client_servkey, client_host, client_port)

        @self.post("/endpoints", tags=["private"])
        def get_all_urls():
            """Return the list of route descriptors registered on this server."""
            return _build_fast_urls(self)

        @self.post("/get_lbuf", tags=["private"])
        def get_lbuf(live_key: str):
            """Return the most recent ``(value, timestamp)`` stored under ``live_key``."""
            return self.base.get_lbuf(live_key)

        @self.post("/list_executors", tags=["private"])
        def list_executors():
            """Return the keys of all currently running executors."""
            return list(self.base.executors.keys())

        @self.post("/stop_executor", tags=["private"])
        def stop_executor(executor_id: str):
            """Signal the executor ``executor_id`` to stop its polling loop."""
            session = self.base.executors.get(executor_id)
            if session is None:
                LOGGER.info(f"Could not find {executor_id} among active executors.")
                return {"signal_stop": False}
            session.stop_action_task()
            return {"signal_stop": True}

        @self.post("/resend_active", tags=["private"])
        def resend_active(action_uuid: str):
            """Return the dict form of the active action ``action_uuid`` if present."""
            info = self.base.get_active_info(action_uuid)
            if info is not None:
                return info
            return ActionModel(action_uuid=action_uuid).as_dict()

        @self.post("/shutdown", tags=["private"])
        async def post_shutdown():
            """Trigger the graceful shutdown handler via an HTTP request."""
            return await self._sp8_shutdown()

        @self.websocket("/ws_status")
        async def websocket_status(websocket: WebSocket):
            """Stream status payloads to the client until it disconnects."""
            await _ws_relay(self.base, websocket, STATUS_CHANNEL, "status")

        @self.websocket("/ws_data")
        async def websocket_data(websocket: WebSocket):
            """Stream data payloads to the client until it disconnects."""
            await _ws_relay(self.base, websocket, DATA_CHANNEL, "data")

        @self.websocket("/ws_live")
        async def websocket_live(websocket: WebSocket):
            """Stream live-buffer snapshots to the client until it disconnects."""
            await _ws_live_relay(self.base, websocket)

        @self.post(f"/{server_key}/estop", tags=["action"])
        async def estop(switch: bool = True):
            """Emergency stop: call the driver estop hook, latch the flag, mark the
            action estopped, and stop all running executors. Returns the finished
            action as a dict. Ports ``base_api.estop``.
            """
            active = await self.base.setup_and_contain_action(
                json_data_keys=["estop"], action_abbr="estop"
            )
            has_estop = getattr(self.driver, "estop", None)
            if has_estop is not None and callable(has_estop):
                LOGGER.info("driver has estop function")
                await active.enqueue_data_dflt(
                    datadict={
                        "estop": await self.driver.estop(**active.action.action_params)
                    }
                )
            else:
                LOGGER.info("driver has NO estop function")
                self.base.actionservermodel.estop = switch
            if switch:
                active.action.action_status.append(HloStatus.estopped)
            for executor_id in list(self.base.executors):
                stop_executor(executor_id)
            finished_action = await active.finish()
            return finished_action.as_dict()

        @self.post(f"/{server_key}/stop", tags=["action"])
        async def stop():
            """Generic stop: stop all running executors and finish a marker action.

            Ports the legacy generic ``stop`` action endpoint.
            """
            active = await self.base.setup_and_contain_action(
                json_data_keys=["stop"], action_abbr="stop"
            )
            has_stop = getattr(self.driver, "stop", None)
            if has_stop is not None and callable(has_stop):
                LOGGER.info("driver has stop function")
                result = has_stop()
                if asyncio.iscoroutine(result):
                    result = await result
            for executor_id in list(self.base.executors):
                stop_executor(executor_id)
            finished_action = await active.finish()
            return finished_action.as_dict()

        # build the endpoint status model + start the status-drain task once the
        # loop exists and all action routes are registered (ports Base.myinit +
        # init_endpoint_status). Registered as a startup hook so decorators on the
        # deployment module have run by the time it fires.
        @self.on_event("startup")
        async def _sp8_status_startup():
            if self._drivers_deferred:
                # the event loop now exists; build the loop-touching drivers.
                self._instantiate_drivers()
                self._drivers_deferred = False
            _add_default_head_endpoints(self)
            self.base.init_endpoint_status(self)
            await self.base.start()

        @self.on_event("shutdown")
        async def _sp8_shutdown_event():
            await self._sp8_shutdown()

    # --- driver instantiation (WS-C task 5) ----------------------------------

    def _instantiate_drivers(self) -> None:
        """Construct every configured driver under the dual convention.

        ``HelaoDriver`` subclasses receive ``config=self.server_params``; bare
        helper classes (the test sims) receive the ``FrameworkBase`` instance.
        When a ``poller_class`` is configured it is attached to the first driver
        (ports ``base_api`` startup, lines 645-660). Sets ``self.drivers`` /
        ``self.driver`` / ``self.poller``.
        """
        drivers: dict = {}
        first_inst = None
        for i, cls in enumerate(self._driver_classes):
            if isinstance(cls, type) and issubclass(cls, HelaoDriver):
                inst = cls(config=self.server_params)
                if i == 0 and self._poller_class is not None:
                    self.poller = self._poller_class(
                        inst, self.base.server_cfg.get("polling_time", 0.1)
                    )
                    self.poller._base_hook = self.base
            else:
                inst = cls(self.base)
            drivers[cls.__name__] = inst
            if i == 0:
                first_inst = inst
        self.drivers = drivers
        self.driver = first_inst

    # --- graceful shutdown (WS-C task 7) -------------------------------------

    async def _sp8_shutdown(self) -> dict:
        """Run driver shutdown hooks and cancel the status-drain task.

        Ports the legacy ``shutdown_event``: invokes the driver's
        ``shutdown``/``async_shutdown`` if present, then cancels the base's
        status-drain background task. Returns the driver shutdown return values.
        """
        LOGGER.info("action shutdown")
        retvals: Dict = {}
        shutdown = getattr(self.driver, "shutdown", None)
        async_shutdown = getattr(self.driver, "async_shutdown", None)
        if callable(shutdown):
            LOGGER.info("driver has shutdown function")
            try:
                retvals["shutdown"] = shutdown()
            except Exception:
                LOGGER.error("driver shutdown raised", exc_info=True)
                retvals["shutdown"] = None
        else:
            retvals["shutdown"] = None
        if callable(async_shutdown):
            LOGGER.info("driver has async_shutdown function")
            try:
                retvals["async_shutdown"] = await async_shutdown()
            except Exception:
                LOGGER.error("driver async_shutdown raised", exc_info=True)
                retvals["async_shutdown"] = None
        else:
            retvals["async_shutdown"] = None

        task = getattr(self.base, "_status_drain_task", None)
        if task is not None and not task.done():
            task.cancel()
        return retvals
