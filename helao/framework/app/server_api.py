"""Deployment-compatible FastAPI subclass wrapping FrameworkBase.

Port of the ``BaseAPI`` pattern from ``helao.core.servers.base_api``.
Deployment action servers do:

    app = BaseAPI(server_key=server_key, driver_classes=[MyDriver])

and then decorate ``@app.post(...)`` endpoints that call
``await app.base.setup_and_contain_action()``. This class wires a
``FrameworkBase`` with real adapters and exposes it as ``app.base``.

Only the action-server surface is implemented here. WebSocket status/data
publishers and the per-server admin endpoints are added in the full
production wiring (a later SP).
"""

__all__ = ["BaseAPI", "ActionAPIRoute", "wrap_action_endpoint"]

import asyncio
import functools
import inspect
import tempfile
from typing import Callable, Dict, List, Optional, Type

from fastapi import Body, FastAPI
from fastapi.routing import APIRoute

from helao.framework.app.base_api import FrameworkBase, ActionContext, ACTION_CTX
from helao.framework.adapters.fs_storage import FsStorage
from helao.framework.adapters.ntp_clock import NtpClock
from helao.framework.adapters.queue_eventsink import QueueEventSink
from helao.framework.adapters.fakes.transport import FakeTransport
from helao.framework.domain.run_models import RunAction
from helao.framework.models.action import ActionModel
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
        self.driver = None
        self.drivers: dict = {}
        if driver_classes:
            for cls in driver_classes:
                inst = cls(self.base)
                self.drivers[cls.__name__] = inst
            self.driver = next(iter(self.drivers.values())) if self.drivers else None

        @self.post("/get_status", tags=["private"])
        def get_status():
            driver_status = "not_implemented"
            if self.driver is not None and hasattr(self.driver, "get_status"):
                try:
                    resp = self.driver.get_status()
                    driver_status = getattr(resp, "status", "ok")
                except Exception:
                    driver_status = "error"
            return {"_driver_status": driver_status, "endpoints": {}}

        @self.post("/attach_client", tags=["private"])
        async def attach_client(
            client_servkey: str, client_host: str, client_port: int
        ):
            # TODO SP8: implement real status-subscriber wiring
            return True
