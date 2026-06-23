"""App composition layer for the action lifecycle (FastAPI-facing).

This is the framework port of ``helao.core.servers.base.Base``'s action-
containment surface (``_get_action`` / ``setup_action`` /
``setup_and_contain_action`` / ``contain_action`` / ``get_active_info``). It is
the *only* framework module besides ``app/factory.py`` allowed to import FastAPI.

It owns no business logic: it builds a :class:`RunAction` from request/params
context, injects the concrete adapters (``FsStorage`` / ``QueueEventSink`` /
``NtpClock`` / a ``Transport``), constructs an :class:`ActionSession` (the
``Active`` equivalent), and registers it in an ``actives`` registry. The public
method names are preserved so deployment authors keep the same surface.
"""
from __future__ import annotations

import asyncio
import os
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID

from helao.framework.domain.action_session import ActionSession
from helao.framework.domain.run_models import RunAction
from helao.framework.models.action import ActionModel
from helao.framework.models.errors import ErrorCodes
from helao.framework.models.machine import MachineModel
from helao.framework.models.server import ActionServerModel, EndpointModel
from helao.framework.ports.clock import Clock
from helao.framework.ports.eventsink import EventSink
from helao.framework.ports.storage import Storage
from helao.framework.ports.transport import Transport
from helao.framework.support.dispatcher import async_private_dispatcher

__all__ = [
    "ActionContext",
    "FrameworkBase",
    "Base",
    "ACTION_CTX",
    "BaseAPI",
    "ActionAPIRoute",
    "wrap_action_endpoint",
]


@dataclass
class ActionContext:
    """Per-request action context (framework analogue of ``ActionInvocation``).

    Carries the :class:`RunAction` being containerized plus the originating
    endpoint name (used to derive ``action_name`` when one is not already set).
    In a real server this is populated from the FastAPI request body + route.

    Attributes:
        action: The run-action submitted with the request.
        endpoint_name: Optional route name; supplies ``action_name`` if absent.
    """

    action: RunAction
    endpoint_name: Optional[str] = None


#: Per-request action context, set by the action-endpoint request wrapper
#: (Task D) and recovered by the no-arg :meth:`FrameworkBase.setup_and_contain_action`.
#: ``None`` outside an action request. Ports ``base_api.py:89``.
ACTION_CTX: ContextVar[Optional[ActionContext]] = ContextVar(
    "ACTION_CTX", default=None
)


class FrameworkBase:
    """Composition root for an action server.

    Holds the injected ports and an ``actives`` registry mapping
    ``action_uuid -> ActionSession``. Builds and contains actions through the
    preserved public surface. FastAPI assembly lives in ``app/factory.py``; this
    class is framework-internal and import-light.

    Attributes:
        server_key: This server's identifier (stamped onto each action).
        actives: ``action_uuid -> ActionSession`` for in-flight actions.
        history: ``action_uuid -> RunAction`` snapshot taken at contain time.
    """

    def __init__(
        self,
        server_key: str,
        *,
        storage: Storage,
        eventsink: EventSink,
        clock: Clock,
        transport: Optional[Transport] = None,
        postprocessors: Optional[List[str]] = None,
        world_cfg: Optional[dict] = None,
        server_cfg: Optional[dict] = None,
    ) -> None:
        """Wire the base to its server identity and injected adapters.

        Args:
            server_key: Server identifier stamped onto contained actions.
            storage: Storage adapter for HLO/meta/aux output.
            eventsink: EventSink adapter for status/data broadcast.
            clock: Clock adapter for timestamps.
            transport: Optional transport adapter (global-param export).
            postprocessors: Names of HLO post-processors to run at finish.
            world_cfg: Whole-group config (a.k.a. ``helao_cfg``); falls back to
                the global ``CONFIG`` when ``None`` and a config is loaded.
            server_cfg: This server's config block; ``server_cfg["params"]`` is
                exposed as :attr:`server_params`.
        """
        self.server_key = server_key
        self.storage = storage
        self.eventsink = eventsink
        self.clock = clock
        self.transport = transport
        self.postprocessors = list(postprocessors or [])
        self.actives: Dict[UUID, ActionSession] = {}
        self.history: Dict[UUID, RunAction] = {}

        # --- server config surface (port Base.__init__ config wiring) --------
        if world_cfg is None:
            world_cfg = self._load_global_cfg()
        self.world_cfg: dict = world_cfg or {}
        self.helao_cfg = self.world_cfg  # legacy alias
        self.server_cfg: dict = server_cfg or {}
        self.server_params: dict = self.server_cfg.get("params", {}) or {}
        # TODO(SP8): full helao_dirs wiring (RUNS_*/STATES/LOGS roots).
        self.helaodirs = None
        self.helao_dirs = self.helaodirs  # legacy alias

        # --- executor registry (exec_id -> Executor) ------------------------
        self.executors: Dict[str, Any] = {}

        # --- live buffer (port base.py:672-687) -----------------------------
        self.live_buffer: dict = {}
        self.live_q: asyncio.Queue = asyncio.Queue()
        self._live_task: Optional[asyncio.Task] = None

        # --- server identity + status model (port base.py:272-326, 479-799) --
        # Fuller MachineModel identity (SP8 WS-C): hostname/port come from this
        # server's config block; machine_name falls back server_cfg ->
        # world_cfg so a group-wide machine name is honored when the per-server
        # block omits it. server_params is exposed above.
        machine_name = self.server_cfg.get("machine_name")
        if machine_name is None:
            machine_name = self.world_cfg.get("machine_name")
        self.server = MachineModel(
            server_name=server_key,
            machine_name=machine_name,
            hostname=self.server_cfg.get("host"),
            port=self.server_cfg.get("port"),
        )
        self.actionservermodel = ActionServerModel(action_server=self.server)
        #: set of (client_servkey, client_host, client_port) status subscribers.
        self.status_clients: set = set()
        #: route descriptors (path/name) filled by init_endpoint_status.
        self.fast_urls: List[dict] = []
        #: orch coordinates for auto-attach (port base.py:765); None when unset.
        self.orch_key = self.server_cfg.get("orch_key")
        self.orch_host = self.server_cfg.get("orch_host")
        self.orch_port = self.server_cfg.get("orch_port")
        #: background drain handle for the status-push loop (started by myinit).
        self._status_task: Optional[asyncio.Task] = None

    @staticmethod
    def _load_global_cfg() -> dict:
        """Best-effort fetch of the module-level global ``CONFIG``.

        Defensive: returns ``{}`` when no config is loaded or the import is
        unavailable, so construction never depends on a launched group.
        """
        try:
            from helao.framework.support.config_loader import CONFIG

            return CONFIG or {}
        except Exception:
            return {}

    # --- lifecycle -----------------------------------------------------------

    async def myinit(self) -> None:
        """Start the background tasks. Ports ``Base.myinit`` (subset).

        Starts the live-buffer drain loop (SP7) **and** the status-push drain
        loop (SP8 WS-A): the latter consumes status emissions from the shared
        eventsink and POSTs status packages to each registered orch client.
        """
        self._live_task = asyncio.create_task(self._live_buffer_task())
        self._status_task = asyncio.create_task(self._status_push_task())

    async def shutdown(self) -> None:
        """Cancel the background tasks started by :meth:`myinit`.

        Cancels the live-buffer drain and status-push drain (the tasks this base
        owns). Driver-owned tasks are the host's responsibility (the FastAPI
        ``shutdown`` hook calls each driver's ``async_shutdown``/``shutdown``).
        Idempotent and safe to call when the tasks were never started.
        """
        for task in (self._status_task, self._live_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._status_task = None
        self._live_task = None

    # --- orchestrator status push (port base.py:272-326, 479-799) -----------

    async def init_endpoint_status(self, routes, dyn_endpoints=None) -> None:
        """Register every action endpoint with the status model. Ports base.py:272.

        ``FrameworkBase`` does not hold the FastAPI app, so the host
        (:class:`BaseAPI`) passes its ``self.routes`` in. For each route whose
        path starts with ``/{server_name}`` an :class:`EndpointModel` is
        registered (keyed by route name) and sorted; ``fast_urls`` is populated
        with route descriptors.

        Args:
            routes: Iterable of FastAPI routes (``app.routes``).
            dyn_endpoints: Optional callable invoked as ``dyn_endpoints(app=...)``
                before route scanning (accepted for parity; the host already
                registers dyn endpoints in ``__init__``).
        """
        if callable(dyn_endpoints):
            res = dyn_endpoints(app=self)
            if asyncio.iscoroutine(res):
                await res
        prefix = f"/{self.server.server_name}"
        for route in routes:
            path = getattr(route, "path", "")
            name = getattr(route, "name", None)
            if path.startswith(prefix) and name:
                self.actionservermodel.endpoints[name] = EndpointModel(
                    endpoint_name=name
                )
                self.actionservermodel.endpoints[name].sort_status()
        LOGGER.info(
            f"Found {len(self.actionservermodel.endpoints)} endpoints for status "
            f"monitoring on {self.server.server_name}."
        )
        self.fast_urls = self.get_endpoint_urls(routes)

    def get_endpoint_urls(self, routes) -> List[dict]:
        """Return ``[{path, name}]`` for every route. Ports base.py:296 (simplified).

        The legacy version also introspects flat params via ``route.dependant``;
        that introspection is fragile across FastAPI versions, so this port keeps
        the minimal ``{path, name}`` descriptor (documented simplification, WS-A).
        """
        url_list = []
        for route in routes:
            url_list.append(
                {
                    "path": getattr(route, "path", ""),
                    "name": getattr(route, "name", None),
                }
            )
        return url_list

    async def send_statuspackage(
        self,
        client_servkey: str,
        client_host: str,
        client_port: int,
        action_name: Optional[str] = None,
    ) -> tuple:
        """POST the action-server model to a subscriber's ``update_status``. Ports base.py:479."""
        json_dict = {
            "actionservermodel": self.actionservermodel.get_fastapi_json(
                action_name=action_name
            )
        }
        return await async_private_dispatcher(
            server_key=client_servkey,
            host=client_host,
            port=client_port,
            private_action="update_status",
            params_dict={
                "regular_task": "true" if action_name is None else "false"
            },
            json_dict=json_dict,
        )

    async def send_nbstatuspackage(
        self,
        client_servkey: str,
        client_host: str,
        client_port: int,
        actionmodel,
    ) -> tuple:
        """POST a single non-blocking action to ``update_nonblocking``. Ports base.py:512."""
        json_dict = {"actionmodel": actionmodel.as_dict()}
        params_dict = {
            "server_host": self.server_cfg.get("host"),
            "server_port": self.server_cfg.get("port"),
        }
        return await async_private_dispatcher(
            server_key=client_servkey,
            host=client_host,
            port=client_port,
            private_action="update_nonblocking",
            params_dict=params_dict,
            json_dict=json_dict,
        )

    async def attach_client(
        self,
        client_servkey: str,
        client_host: str,
        client_port: int,
        retry_limit: int = 5,
    ) -> bool:
        """Register a status subscriber and push an initial full snapshot. Ports base.py:550."""
        success = False
        combo_key = (client_servkey, client_host, client_port)
        self.status_clients.add(combo_key)
        for _ in range(retry_limit):
            response, error_code = await self.send_statuspackage(
                client_servkey=client_servkey,
                client_host=client_host,
                client_port=client_port,
                action_name=None,
            )
            if response is not None and error_code == ErrorCodes.none:
                success = True
                break
            LOGGER.error(
                f"Failed to add {combo_key} to {self.server.server_name} status "
                f"subscriber list."
            )
        return success

    def detach_client(
        self, client_servkey: str, client_host: str, client_port: int
    ) -> None:
        """Remove a status subscriber. Idempotent. Ports base.py:609."""
        combo_key = (client_servkey, client_host, client_port)
        if combo_key in self.status_clients:
            self.status_clients.remove(combo_key)

    async def _status_push_task(self, retry_limit: int = 5) -> None:
        """Drain status emissions and push to orch clients. Ports base.py:737 (WS-A subset).

        Subscribes to the shared eventsink's status queue. Each emission is an
        ``ActionModel``-shaped dict (from :meth:`ActionSession.add_status`);
        it is rehydrated into an :class:`ActionModel`, folded into the
        ``actionservermodel`` (active_dict + last_action_uuid + sort), pushed to
        every registered client (auto-attaching the orch when none are present),
        then the endpoint's finished bucket is cleared. The legacy unified/
        endpoint queue processing block (base.py:802-820) is WS-E and omitted.
        """
        subscribe = getattr(self.eventsink, "subscribe", None)
        if not callable(subscribe):
            LOGGER.error(
                "eventsink has no subscribe(); status push disabled "
                f"on {self.server.server_name}."
            )
            return
        queue = subscribe()
        LOGGER.info(f"{self.server.server_name} status push task created.")
        while True:
            payload = await queue.get()
            # QueueEventSink delivers (channel, payload); other sinks may deliver
            # the bare payload. Normalize to the status payload dict.
            if isinstance(payload, tuple) and len(payload) == 2:
                channel, body = payload
                from helao.framework.ports.eventsink import STATUS_CHANNEL

                if channel != STATUS_CHANNEL:
                    continue
                payload = body
            try:
                status_msg = ActionModel(**payload)
            except Exception:
                LOGGER.exception("could not rehydrate status payload to ActionModel")
                continue

            name = status_msg.action_name
            if name not in self.actionservermodel.endpoints:
                self.actionservermodel.endpoints[name] = EndpointModel(
                    endpoint_name=name
                )
            self.actionservermodel.endpoints[name].active_dict[
                status_msg.action_uuid
            ] = status_msg
            self.actionservermodel.last_action_uuid = status_msg.action_uuid
            self.actionservermodel.endpoints[name].sort_status()

            if len(self.status_clients) == 0 and self.orch_key is not None:
                await self.attach_client(
                    self.orch_key, self.orch_host, self.orch_port
                )

            for combo_key in self.status_clients.copy():
                client_servkey, client_host, client_port = combo_key
                for _ in range(retry_limit):
                    response, error_code = await self.send_statuspackage(
                        action_name=name,
                        client_servkey=client_servkey,
                        client_host=client_host,
                        client_port=client_port,
                    )
                    if response and error_code == ErrorCodes.none:
                        break
                # cooperative yield (legacy slept 0.3s between clients)
                await asyncio.sleep(0)
            self.actionservermodel.endpoints[name].clear_finished()

    # --- live buffer (port base.py:672-687) ---------------------------------

    @staticmethod
    def _stamp_lbuf_dict(live_dict: dict) -> dict:
        """Stamp each live value with the current wall-clock time."""
        return {k: (v, time.time()) for k, v in live_dict.items()}

    async def put_lbuf(self, live_dict: dict) -> None:
        """Enqueue a stamped live-buffer update (awaitable)."""
        await self.live_q.put(self._stamp_lbuf_dict(live_dict))

    def put_lbuf_nowait(self, live_dict: dict) -> None:
        """Enqueue a stamped live-buffer update without awaiting."""
        self.live_q.put_nowait(self._stamp_lbuf_dict(live_dict))

    def get_lbuf(self, live_key):
        """Return the ``(value, timestamp)`` tuple for ``live_key``."""
        return self.live_buffer[live_key]

    async def _live_buffer_task(self) -> None:
        """Background drain loop: merge queued updates into ``live_buffer``."""
        while True:
            msg = await self.live_q.get()
            self.live_buffer.update(msg)

    # --- request -> action ---------------------------------------------------

    def _get_action(self, ctx: ActionContext) -> RunAction:
        """Finalize the request's :class:`RunAction`. Ports ``Base._get_action``.

        Derives ``action_name`` from the endpoint name when unset and fills the
        ``action_abbr`` default, mirroring the legacy finalization (sans the
        FastAPI route-introspection and codehash steps, which are app-assembly
        concerns handled by ``factory.makeApp``).
        """
        action = ctx.action
        if not action.action_name and ctx.endpoint_name:
            action.action_name = ctx.endpoint_name
        if action.action_abbr is None:
            action.action_abbr = action.action_name
        return action

    def setup_action(self, ctx: ActionContext) -> RunAction:
        """Return the finalized :class:`RunAction` for a request. Ports ``Base.setup_action``."""
        return self._get_action(ctx)

    # --- contain -------------------------------------------------------------

    async def setup_and_contain_action(
        self,
        ctx: Optional[ActionContext] = None,
        *,
        header: str = "",
    ) -> ActionSession:
        """Build the request's action and wrap it in an :class:`ActionSession`.

        Ports ``Base.setup_and_contain_action``: finalize the action, default its
        file-connection header, and hand it to :meth:`contain_action`.

        Two call forms are supported:

        * **ctx-arg** (SP4 demo/tests): pass an explicit :class:`ActionContext`.
        * **no-arg** (request wrapper, Task D): omit ``ctx`` and recover it from
          the module-level :data:`ACTION_CTX` set by the endpoint wrapper.

        Args:
            ctx: The per-request action context, or ``None`` to recover from
                :data:`ACTION_CTX`.
            header: Default HLO header for this action's file connections.

        Returns:
            The :class:`ActionSession` now tracking this action.

        Raises:
            RuntimeError: When ``ctx`` is ``None`` and ``ACTION_CTX`` is unset.
        """
        if ctx is None:
            ctx = ACTION_CTX.get()
        if ctx is None:
            raise RuntimeError(
                "no ActionContext: ACTION_CTX unset and no ctx passed"
            )
        action = self._get_action(ctx)
        self._default_header = header
        return await self.contain_action(action)

    async def contain_action(self, action: RunAction) -> ActionSession:
        """Register ``action`` as active, substituting any prior session with the same UUID.

        Ports ``Base.contain_action``: a pre-existing session for the same
        ``action_uuid`` has its open handles closed (``substitute``) before being
        replaced; the new session is initialized (``myinit``) and a snapshot is
        recorded in ``history``.
        """
        if action.action_uuid in self.actives:
            await self.actives[action.action_uuid].substitute()

        from helao.framework.domain.executor import Executor

        # placeholder executor; the caller attaches the real one before driving
        # the loop (mirrors Active being constructed before start_executor).
        session = ActionSession(
            action,
            storage=self.storage,
            eventsink=self.eventsink,
            clock=self.clock,
            executor=Executor(active=_ActionWrap(action)),
            transport=self.transport,
            now_factory=self._clock_now,
            postprocessors=self.postprocessors,
            base=self,
        )
        self.actives[action.action_uuid] = session
        await session.myinit()
        # Auto-open the default file connection so a poll/streaming executor's
        # data lands in an .hlo without the endpoint calling open_file itself.
        # Ports the legacy default file connection (`dflt_file_conn_key()` +
        # FileConnParams) that `Base.setup_and_contain_action` registers; the
        # framework opens it eagerly here since there is no background data
        # logger to open it lazily on first write.
        if action.save_data and action.file_conn_keys:
            await session.open_file(
                action.file_conn_keys[0], header=self._default_header
            )
        self.history[action.action_uuid] = action.model_copy(deep=True)
        return session

    def get_active_info(self, action_uuid: UUID) -> Optional[dict]:
        """Return the dict form of an active action, or ``None``. Ports ``Base.get_active_info``."""
        if action_uuid in self.actives:
            return self.actives[action_uuid].action.as_dict()
        return None

    # --- clock bridge --------------------------------------------------------

    def _clock_now(self):
        """Wall-clock ``datetime`` from the injected clock port (ns -> datetime)."""
        now_dt = getattr(self.clock, "now_datetime", None)
        if callable(now_dt):
            return now_dt()
        from datetime import datetime

        return datetime.fromtimestamp(self.clock.now_ns() / 1e9)


@dataclass
class _ActionWrap:
    """Minimal wrapper exposing ``.action`` for :class:`Executor` construction."""

    action: RunAction = field(default=None)


#: Legacy export alias. Deploy code imports ``Base`` from the action-server
#: surface; the framework's composition root is :class:`FrameworkBase` (a
#: deliberate SP7 subset of legacy ``Base``).
Base = FrameworkBase


# ===========================================================================
# Action-endpoint request wrapper (port helao.core.servers.base_api.py:94-361)
# ---------------------------------------------------------------------------
# Repointed to the framework ``RunAction`` + ``ActionContext``. The legacy code
# stored ``ActionInvocation(action, endpoint_func)`` in ``ACTION_CTX``; here we
# store ``ActionContext(action=run_action, endpoint_name=fn.__name__)`` so the
# no-arg :meth:`FrameworkBase.setup_and_contain_action` can recover it.
# ===========================================================================

import asyncio  # noqa: E402  (grouped with the wrapper machinery)
import functools  # noqa: E402
import inspect  # noqa: E402
from collections import namedtuple  # noqa: E402
from typing import Callable  # noqa: E402

from helao.framework.support import helao_logging as logging  # noqa: E402

LOGGER = (
    logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
)


def _build_action_from_kwargs(
    kwargs: dict, default_params: Optional[dict] = None
) -> RunAction:
    """Build a :class:`RunAction` from an endpoint's parsed keyword arguments.

    Ports ``base_api.py:_build_action_from_kwargs``, repointed to
    :class:`RunAction`. Picks the first ``RunAction``-typed kwarg as the base
    action and folds every remaining kwarg into ``action.action_params`` unless
    that key was already provided. Signature defaults not supplied by the caller
    are folded in via ``default_params`` so the action record reflects the
    values the endpoint actually ran with.
    """
    action: Optional[RunAction] = None
    seen_action_param: Optional[str] = None
    for name, val in kwargs.items():
        if isinstance(val, RunAction):
            if action is None:
                action = val
                seen_action_param = name
            else:
                LOGGER.error(
                    f"critical error: found another RunAction under parameter "
                    f"'{name}', skipping it"
                )
    if action is None:
        LOGGER.error(
            "critical error: no RunAction was found by setup_action, using blank "
            "RunAction."
        )
        action = RunAction()
    else:
        LOGGER.info(f"found RunAction under parameter '{seen_action_param}'")

    for name, val in kwargs.items():
        if isinstance(val, RunAction):
            continue
        if name not in action.action_params:
            action.action_params[name] = val

    if default_params:
        for name, val in default_params.items():
            if name in kwargs:
                continue
            if name in action.action_params:
                continue
            action.action_params[name] = val

    return action


def _collect_default_params(sig: "inspect.Signature") -> dict:
    """Return ``{name: default}`` for sig params with usable Python defaults.

    Ports ``base_api.py:_collect_default_params``. Skips ``RunAction``-typed
    parameters (handled separately) and FastAPI parameter markers
    (``Body``/``Query``/``Path``/``Depends``/…), whose "default" is a sentinel.
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
        if isinstance(ann, type) and issubclass(ann, RunAction):
            continue
        defaults[name] = param.default
    return defaults


def _is_action_param(param: "inspect.Parameter") -> bool:
    """Return True if ``param`` is annotated as a :class:`RunAction` (sub)class."""
    ann = param.annotation
    return isinstance(ann, type) and issubclass(ann, RunAction)


def _build_action_endpoint_signature(fn: Callable, sig: "inspect.Signature"):
    """Augment ``fn``'s signature with an injected ``action`` param when absent.

    Ports the action-injection half of ``base_api.py``'s
    ``_build_action_endpoint_signature`` (SP7 subset: no ``action_version``
    decorator wiring — that's SP8). When the endpoint omits an explicit
    ``RunAction``-typed param we synthesize one (``action: RunAction =
    Body({}, embed=True)``) so FastAPI builds the request body schema and the
    wrapper can recover the action from kwargs.

    Returns:
        Tuple ``(exposed_sig, accepts_var_keyword, accepted_names)``.
    """
    from fastapi import Body

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

    if has_action:
        return sig, accepts_var_keyword, accepted_names

    injected = [
        inspect.Parameter(
            "action",
            kind=inspect.Parameter.KEYWORD_ONLY,
            default=Body({}, embed=True),
            annotation=RunAction,
        )
    ]
    # KEYWORD_ONLY injected params must precede any VAR_KEYWORD (**kwargs) param.
    non_var = [p for p in params if p.kind is not inspect.Parameter.VAR_KEYWORD]
    var_kw = [p for p in params if p.kind is inspect.Parameter.VAR_KEYWORD]
    exposed_sig = sig.replace(parameters=non_var + injected + var_kw)
    return exposed_sig, accepts_var_keyword, accepted_names


def wrap_action_endpoint(fn: Callable) -> Callable:
    """Wrap an action endpoint so each call populates :data:`ACTION_CTX`.

    Ports ``base_api.py:wrap_action_endpoint`` (SP7 subset). Exposes ``fn``'s
    signature (augmented with a synthesized ``action`` param when omitted) so
    FastAPI parameter resolution and schema generation work, rebuilds the parsed
    kwargs into a :class:`RunAction`, and sets/resets an :class:`ActionContext`
    (``action=run_action, endpoint_name=fn.__name__``) in :data:`ACTION_CTX`
    around the call. Only the parameters ``fn`` actually declares are forwarded.
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
                ActionContext(action=action, endpoint_name=fn.__name__)
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
                ActionContext(action=action, endpoint_name=fn.__name__)
            )
            try:
                return fn(**_forward_kwargs(kwargs))
            finally:
                ACTION_CTX.reset(token)

    wrapper.__signature__ = exposed_sig  # type: ignore[attr-defined]
    return wrapper


def _make_action_api_route():
    """Build the ``ActionAPIRoute`` class (FastAPI imported lazily here)."""
    from fastapi.routing import APIRoute

    class ActionAPIRoute(APIRoute):
        """``APIRoute`` subclass that auto-wraps endpoints tagged ``"action"``.

        Installing this as the router's ``route_class`` means every
        ``@app.post(..., tags=["action"])`` handler is passed through
        :func:`wrap_action_endpoint` at registration time (so the endpoint body
        recovers the :class:`RunAction` from :data:`ACTION_CTX`). Ports
        ``base_api.py:ActionAPIRoute``.
        """

        def __init__(self, *args, **kwargs):
            tags = kwargs.get("tags") or []
            if "action" in tags:
                endpoint = kwargs.get("endpoint")
                if endpoint is not None:
                    kwargs["endpoint"] = wrap_action_endpoint(endpoint)
            super().__init__(*args, **kwargs)

    return ActionAPIRoute


#: The ``APIRoute`` subclass installed as the action-server router route_class.
ActionAPIRoute = _make_action_api_route()


#: OpenAPI tag metadata (port legacy ``server_api.TAGS``).
TAGS = [
    {
        "name": "action",
        "description": "action endpoints will register status and block",
    },
    {"name": "private", "description": "private endpoints don't create actions"},
]


def _make_base_api_class():
    """Build the ``BaseAPI`` class (FastAPI imported lazily here)."""
    import tempfile

    from fastapi import FastAPI

    from helao.framework.adapters.fs_storage import FsStorage
    from helao.framework.adapters.ntp_clock import NtpClock
    from helao.framework.adapters.queue_eventsink import QueueEventSink
    from helao.framework.adapters.fakes.transport import FakeTransport

    class BaseAPI(FastAPI):
        """FastAPI action-server host (SP7 subset of legacy ``BaseAPI``).

        Hosts real ``test``-deployment action endpoints in-process: endpoints
        tagged ``["action"]`` are auto-wrapped by :class:`ActionAPIRoute` to
        populate :data:`ACTION_CTX`, so an endpoint body can call the no-arg
        ``app.base.setup_and_contain_action()`` and have its :class:`RunAction`
        recovered. The :class:`FrameworkBase` is built eagerly in ``__init__``
        (NOT a startup event) and injected with the default adapters exactly like
        :func:`helao.framework.app.factory.makeActionApp`.

        TODO(SP8): this subclasses ``fastapi.FastAPI`` directly rather than the
        legacy ``HelaoFastAPI``. The legacy class wires ZMQ-RPC, ``MachineModel``
        identity, and world-config plumbing; those — together with the
        ``/ws_status``/``/ws_data``/``/ws_live`` publishers, the admin endpoints
        (``/get_status``, ``/endpoints``, ``/stop_executor``, ``/shutdown``),
        the ``app_entry`` collision middleware, the estop exception handler, and
        the orch ``attach_client`` -> ``/update_status`` status push — are SP8.

        Attributes:
            base: The :class:`FrameworkBase` controller bound to this app.
            drivers: Named-tuple of constructed driver instances.
            driver: First entry of ``drivers`` (or ``None``).
        """

        def __init__(
            self,
            server_key,
            server_title="",
            description="",
            version="0.1",
            *,
            driver_classes=None,
            dyn_endpoints=None,
            save_root=None,
            transport=None,
            sequence_lib=None,
            experiment_lib=None,
            postprocessors=None,
        ):
            """Build the action-server app and its :class:`FrameworkBase`.

            Args:
                server_key: Server identifier (route prefix; stamped on actions).
                server_title: OpenAPI title.
                description: OpenAPI description.
                version: OpenAPI version string.
                driver_classes: Iterable of driver classes to instantiate against
                    the base (dual-convention: ``HelaoDriver`` subclasses get
                    ``config=server_params``; bare helpers get the base
                    positionally — see ``[[sp8-drivers-bare-helpers]]``).
                dyn_endpoints: Optional callable invoked as ``dyn_endpoints(app=self)``
                    after base construction to register extra routes.
                save_root: Output root for ``FsStorage``; a temp dir when ``None``.
                transport: Transport adapter; a :class:`FakeTransport` when ``None``.
                sequence_lib: Reserved (orchestrator concern; accepted for parity).
                experiment_lib: Reserved (orchestrator concern; accepted for parity).
                postprocessors: HLO post-processor names passed to the base.
            """
            super().__init__(
                title=server_title or f"{server_key} (framework SP7)",
                description=description,
                version=str(version),
                openapi_tags=TAGS,
            )
            # auto-wrap tags=["action"] endpoints to populate ACTION_CTX
            self.router.route_class = ActionAPIRoute

            if save_root is None:
                save_root = tempfile.mkdtemp(prefix="helao_framework_baseapi_")
            os.makedirs(save_root, exist_ok=True)

            world_cfg, server_cfg = self._load_server_cfg(server_key)

            base = FrameworkBase(
                server_key=server_key,
                storage=FsStorage(save_root=save_root),
                eventsink=QueueEventSink(),
                clock=NtpClock(),
                transport=transport if transport is not None else FakeTransport(),
                postprocessors=postprocessors,
                world_cfg=world_cfg,
                server_cfg=server_cfg,
            )
            self.base = base
            self.state.base = base
            self.state.save_root = save_root

            # --- driver instantiation (DEFERRED to startup) ----------------
            # Drivers are NOT built here: several ``test``-deployment drivers
            # start a poll task in ``__init__`` via
            # ``asyncio.get_event_loop().create_task(...)`` (e.g. ``WsSim``),
            # which is orphaned on a dead loop when built before uvicorn's loop
            # exists (this caused the SP7 golden-master 'sim_dict' KeyError).
            # Instantiation is moved to the FastAPI ``startup`` event (loop
            # running) so the driver's own ``create_task`` binds to the live
            # loop. ``app.driver``/``app.drivers`` stay ``None``/``()`` until
            # then.
            self._driver_classes = list(driver_classes or [])
            self.drivers = tuple()
            self.driver = None

            # --- dynamic endpoints -----------------------------------------
            if dyn_endpoints is not None:
                dyn_endpoints(app=self)

            # --- private status-client endpoints (port base.py attach/detach) ---
            self._register_status_endpoints(server_key, base)

            # --- startup hook: build drivers (loop live) + start base tasks --
            @self.on_event("startup")
            async def _framework_base_startup():
                # build drivers first: their __init__ may schedule poll tasks
                # onto the now-running loop.
                self._instantiate_drivers()
                await base.myinit()
                await base.init_endpoint_status(self.routes)

            # --- shutdown hook: stop driver + base background tasks ---------
            @self.on_event("shutdown")
            async def _framework_base_shutdown():
                await self._shutdown_drivers()
                await base.shutdown()

        def _instantiate_drivers(self):
            """Instantiate ``driver_classes`` against the base (dual-convention).

            Called from the ``startup`` event so any poll task a driver schedules
            in ``__init__`` (``asyncio.get_event_loop().create_task(...)``) binds
            to the running loop. Populates ``self.drivers`` (a namedtuple keyed by
            class name) and ``self.driver`` (the first entry). Idempotent.
            """
            if self.drivers or not self._driver_classes:
                return
            Drivers = namedtuple(
                "Drivers", [d.__name__ for d in self._driver_classes]
            )
            driver_dict = {}
            for driver_class in self._driver_classes:
                if self._is_helao_driver(driver_class):
                    driver_inst = driver_class(config=self.base.server_params)
                else:
                    driver_inst = driver_class(self.base)
                driver_dict[driver_class.__name__] = driver_inst
            self.drivers = Drivers(**driver_dict)
            self.driver = self.drivers[0] if self.drivers else None

        async def _shutdown_drivers(self):
            """Shut down each driver, preferring ``async_shutdown`` over ``shutdown``.

            For every constructed driver: ``await async_shutdown()`` if present,
            else call ``shutdown()`` if present. Failures are logged, not raised,
            so one driver's shutdown error does not block the rest.
            """
            for driver in self.drivers or ():
                async_shutdown = getattr(driver, "async_shutdown", None)
                if callable(async_shutdown):
                    try:
                        await async_shutdown()
                    except Exception:
                        LOGGER.exception(
                            f"async_shutdown failed for {type(driver).__name__}"
                        )
                    continue
                shutdown = getattr(driver, "shutdown", None)
                if callable(shutdown):
                    try:
                        shutdown()
                    except Exception:
                        LOGGER.exception(
                            f"shutdown failed for {type(driver).__name__}"
                        )

        def _register_status_endpoints(self, server_key, base):
            """Register the orch-facing private status-client endpoints.

            ``POST /{server_key}/attach_client`` and ``/detach_client`` delegate
            to the base so a live orchestrator can subscribe/unsubscribe to this
            action server's status pushes.
            """

            @self.post(f"/{server_key}/attach_client", tags=["private"])
            async def attach_client(
                client_servkey: str, client_host: str, client_port: int
            ):
                return await base.attach_client(
                    client_servkey, client_host, client_port
                )

            @self.post(f"/{server_key}/detach_client", tags=["private"])
            async def detach_client(
                client_servkey: str, client_host: str, client_port: int
            ):
                base.detach_client(client_servkey, client_host, client_port)
                return True

        @staticmethod
        def _load_server_cfg(server_key):
            """Best-effort ``(world_cfg, server_cfg)`` slice from the global ``CONFIG``.

            Defensive: returns ``({}, {})`` on any failure so construction never
            depends on a launched group. ``server_cfg["params"]`` populates
            :attr:`FrameworkBase.server_params`.
            """
            try:
                from helao.framework.support.config_loader import CONFIG

                world = CONFIG or {}
                servers = (world.get("servers") or {}) if hasattr(world, "get") else {}
                server = servers.get(server_key, {}) or {}
                return dict(world) if world else {}, dict(server) if server else {}
            except Exception:
                return {}, {}

        @staticmethod
        def _is_helao_driver(driver_class) -> bool:
            """True if ``driver_class`` is a ``HelaoDriver`` ABC subclass.

            Tries the framework ``HelaoDriver`` first, falling back to the legacy
            one; a missing import degrades to the bare-helper path (``False``).
            """
            try:
                from helao.framework.ports.driver import HelaoDriver
            except Exception:
                try:
                    from helao.core.drivers.helao_driver import HelaoDriver
                except Exception:
                    return False
            try:
                return isinstance(driver_class, type) and issubclass(
                    driver_class, HelaoDriver
                )
            except Exception:
                return False

    return BaseAPI


BaseAPI = _make_base_api_class()
