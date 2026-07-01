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
import hashlib
import os
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
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
    "action_version",
    "ACTION_VERSION_ATTR",
    "DEFAULT_ACTION_VERSION",
    "Active",
]

# Compatibility alias: hte action servers import ``Active`` from the legacy base.
# The framework equivalent is ``ActionSession``; this alias lets those imports
# resolve without modifying the hte code until full migration is complete.
Active = ActionSession


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
        # Driver handles are owned by the app (BaseAPI) but mirrored here at
        # startup so ActionSession.driver (and executors via active.driver) can
        # reach the server's driver without an app back-reference — legacy
        # Active.driver == base.app.driver (base.py:1126).
        self.driver = None
        self.drivers = tuple()
        self.poller = None
        self.storage = storage
        self.eventsink = eventsink
        self.clock = clock
        self.transport = transport
        self.postprocessors = list(postprocessors or [])
        self.actives: Dict[UUID, ActionSession] = {}
        self.history: Dict[UUID, RunAction] = {}
        self._default_header: str = ""

        # --- server config surface (port Base.__init__ config wiring) --------
        if world_cfg is None:
            world_cfg = self._load_global_cfg()
        self.world_cfg: dict = world_cfg or {}
        self.helao_cfg = self.world_cfg  # legacy alias
        self.server_cfg: dict = server_cfg or {}
        self.server_params: dict = self.server_cfg.get("params", {}) or {}
        # SP-ARTIFACT Task 2: populate helaodirs when config has a root.
        # Called WITHOUT server_name to avoid re-zipping logs on Base
        # construction (the launcher already rotates logs — Constraint 6).
        if self.world_cfg.get("root"):
            from helao.framework.support.helao_dirs import helao_dirs as _helao_dirs
            self.helaodirs = _helao_dirs(self.world_cfg)
        else:
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
        #: optional in-process hook for nonblocking-action reports. Set by the
        #: orchestrator (makeOrchApp) to driver.on_nonblocking so the orch's OWN
        #: nonblocking actions are routed straight to the FSM without an HTTP/RPC
        #: self-loop. Action servers leave this None and push to the orch over RPC.
        self.nonblocking_sink: Optional[Callable] = None
        #: background drain handle for the status-push loop (started by myinit).
        self._status_task: Optional[asyncio.Task] = None

        # --- action-collision queues (port base.py:193-194, WS-E) -----------
        #: unified queue used when ``allow_concurrent_actions`` is False; a list
        #: of ``(RunAction, extra_params)`` tuples (ports ``local_action_queue``).
        from collections import deque as _deque

        self.local_action_queue = _deque()
        #: per-endpoint collision queues keyed by endpoint name; each a deque of
        #: ``(RunAction, extra_params)`` tuples (ports ``endpoint_queues``).
        self.endpoint_queues: Dict[str, Any] = {}
        #: optional async hook ``(action, extra) -> None`` used by the queue
        #: drain to re-dispatch a queued action. Defaults to the in-process
        #: re-dispatch (:meth:`_redispatch_queued`); tests may override it.
        self._redispatch_queued = self._default_redispatch_queued

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
        # WS-E: give every registered endpoint a collision queue.
        self.endpoint_queues_init()

    def endpoint_queues_init(self) -> None:
        """Create a per-endpoint collision queue for every registered endpoint.

        Ports ``Base.endpoint_queues_init`` (base.py:249): one ``deque`` per
        action endpoint so the ``app_entry`` middleware always has a queue to
        append a colliding action onto. Idempotent — existing queues are kept so
        a re-init (e.g. dyn endpoints) never drops a queued action.
        """
        from collections import deque as _deque

        for name in self.actionservermodel.endpoints:
            self.endpoint_queues.setdefault(name, _deque())

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

    def _resolve_orch_coords(self) -> Optional[tuple]:
        """Resolve the orchestrator's ``(server_key, host, port)`` for nonblocking push.

        Configs set ``orch_key`` on action servers but NOT ``orch_host``/
        ``orch_port`` (the framework's regular status path is WS-based), so the
        host/port are resolved from ``CONFIG["servers"][orch_key]``. Returns
        ``None`` when no orchestrator is configured (e.g. unit tests / standalone).
        """
        if self.orch_key is None:
            return None
        host, port = self.orch_host, self.orch_port
        if host is None or port is None:
            from helao.framework.support import config_loader

            cfg = config_loader.CONFIG or {}
            orch_cfg = (cfg.get("servers") or {}).get(self.orch_key) or {}
            host = host or orch_cfg.get("host")
            port = port or orch_cfg.get("port")
        if host is None or port is None:
            return None
        return (self.orch_key, host, int(port))

    async def send_nonblocking_status(self, action, retry_limit: int = 3) -> None:
        """Push a nonblocking action's status to the orchestrator. Ports base.py:2313.

        Unlike :meth:`_status_push_task` (the regular WS-relayed status path that
        ``ActionSession.add_status`` deliberately SKIPS for nonblocking actions),
        this delivers a single action's state to the orch's ``update_nonblocking``
        endpoint so the orch can track the nonblocking action separately (never in
        ``active_dict``), register it in the action history, and stop its executor
        at experiment finish. Targets the union of registered status_clients and
        the configured orchestrator so delivery does not depend on the (lazy /
        WS-superseded) auto-attach path.

        When ``nonblocking_sink`` is set (the orchestrator's own co-located base),
        the report is routed IN-PROCESS to ``driver.on_nonblocking`` instead — no
        HTTP/RPC self-loop, and no regular-status self-attach. The host/port handed
        to the sink are this server's own, so the resulting ``stop_executor`` at
        experiment finish targets this orchestrator.
        """
        sink = getattr(self, "nonblocking_sink", None)
        if callable(sink):
            host = self.server_cfg.get("host")
            port = self.server_cfg.get("port")
            await sink(action, host, int(port) if port is not None else 0)
            return

        targets = set(self.status_clients)
        orch_coords = self._resolve_orch_coords()
        if orch_coords is not None:
            targets.add(orch_coords)
        if not targets:
            LOGGER.warning(
                "send_nonblocking_status: no status clients / orch configured on "
                f"{self.server.server_name}; nonblocking action not reported."
            )
            return
        for client_servkey, client_host, client_port in targets:
            for _ in range(retry_limit):
                response, error_code = await self.send_nbstatuspackage(
                    client_servkey=client_servkey,
                    client_host=client_host,
                    client_port=client_port,
                    actionmodel=action,
                )
                if (
                    isinstance(response, dict)
                    and response.get("success", False)
                    and error_code == ErrorCodes.none
                ):
                    break

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

            # Guard the whole per-message body: a failure pushing one status
            # update (e.g. a transient dispatcher error or a malformed endpoint)
            # must NOT kill the drain task — that would silently stop ALL status
            # push and hang every sequence. Ports legacy log_status_task's
            # loop-level try/except (base.py:824-827) but per-message so the
            # loop keeps draining.
            try:
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

                # WS-E: drain the collision queues now that this endpoint may be
                # idle. Ports the legacy status-loop queue block (base.py:802-820)
                # that WS-A deliberately omitted. "Active non-queued" actions are
                # those NOT parked on this server (queued_on_actserv) unless they
                # have since been (re)launched (queued_launch).
                await self._drain_queues(name)
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception(
                    f"status push failed for action {status_msg.action_uuid} "
                    f"on {self.server.server_name}; continuing drain."
                )

    def _active_nonqueued(self) -> Dict[str, list]:
        """Per-endpoint UUIDs of actions actively occupying the server.

        Ports the ``active_nonqueued`` comprehension (base.py:802): a queued
        action (``queued_on_actserv``) does not count as occupying the endpoint
        until it is actually (re)launched (``queued_launch``).
        """
        result: Dict[str, list] = {}
        for endpoint, endmod in self.actionservermodel.endpoints.items():
            uuids = []
            for auuid, act in endmod.active_dict.items():
                params = getattr(act, "action_params", {}) or {}
                if not params.get("queued_on_actserv", False) or params.get(
                    "queued_launch", False
                ):
                    uuids.append(auuid)
            result[endpoint] = uuids
        return result

    async def _drain_queues(self, endpoint_name: str) -> None:
        """Dispatch the next queued action when the server/endpoint is idle.

        Ports base.py:813-820: when concurrency is disabled, drain the unified
        queue once nothing is actively running anywhere; otherwise drain this
        endpoint's queue once nothing is actively running on it.
        """
        active_nonqueued = self._active_nonqueued()
        active_nq = [x for y in active_nonqueued.values() for x in y]
        if not self.server_params.get("allow_concurrent_actions", True):
            if len(self.local_action_queue) > 0 and not active_nq:
                await self.process_unified_queue()
        else:
            queue = self.endpoint_queues.get(endpoint_name)
            if (
                queue
                and len(queue) > 0
                and not active_nonqueued.get(endpoint_name, [])
            ):
                await self.process_endpoint_queue(endpoint_name)

    async def process_unified_queue(self) -> None:
        """Dispatch the next action from the unified queue. Ports base.py:726."""
        await self._dispatch_queued_action(
            self.local_action_queue, "local unified"
        )

    async def process_endpoint_queue(self, endpoint_name: str) -> None:
        """Dispatch the next action from ``endpoint_name``'s queue. Ports base.py:730.

        Accepts the endpoint NAME (the legacy signature took an ``ActionModel``
        ``status_msg`` and read ``status_msg.action_name``; the framework drain
        already has the name in hand, so it is passed directly).
        """
        queue = self.endpoint_queues.get(endpoint_name)
        if queue is None:
            return
        await self._dispatch_queued_action(queue, f"endpoint '{endpoint_name}'")

    async def _dispatch_queued_action(self, action_queue, queue_label: str) -> None:
        """Pop one queued action, re-launch it ``no_wait``, requeue on failure.

        Ports ``Base._dispatch_queued_action`` (base.py:705). The popped action
        is stamped ``start_condition=no_wait`` + ``action_params.queued_launch``
        (so the middleware passes it through on re-entry) and handed to the
        configurable re-dispatch hook (:attr:`_redispatch_queued`). On any
        failure the action is re-queued at the head so it is not dropped.
        """
        if action_queue is None or len(action_queue) == 0:
            return
        qact, qpars = None, {}
        try:
            qact, qpars = action_queue.popleft()
            LOGGER.info(f"running queued {qact.action_name}")
            from helao.framework.models.action_start_condition import (
                ActionStartCondition,
            )

            qact.start_condition = ActionStartCondition.no_wait
            qact.action_params["queued_launch"] = True
            await self._redispatch_queued(qact, qpars)
        except Exception:
            LOGGER.error(f"Failed to process {queue_label} queue", exc_info=True)
            if qact is not None:
                LOGGER.info(f"re-queueing {qact.action_name}")
                action_queue.appendleft((qact, qpars))

    async def _default_redispatch_queued(self, action: RunAction, extra: dict) -> None:
        """Re-launch a queued action over HTTP via the dispatcher (in-process path).

        Ports the ``async_action_dispatcher`` call in
        ``Base._dispatch_queued_action`` (base.py:719). Re-POSTs the action to
        this server's own endpoint so it flows back through ``app_entry`` (now
        passing through, since ``queued_launch`` is set). The dispatch uses the
        configured host/port from this server's config.

        NB: this requires a live HTTP server (the launched group). Under the
        in-process golden-master tests there is no socket server, so tests
        override :attr:`_redispatch_queued` with an in-process recorder; the
        ordering/queuing behaviour is what is asserted there. The full
        socket-backed re-dispatch is exercised under the live orchestrator
        (WS-E live smoke), not in the unit gate.
        """
        host = self.server_cfg.get("host")
        port = self.server_cfg.get("port")
        if not host or not port:
            LOGGER.error(
                "cannot re-dispatch queued action: server host/port unknown "
                f"on {self.server.server_name}; leaving it queued."
            )
            raise RuntimeError("no host/port for queued re-dispatch")
        await async_private_dispatcher(
            server_key=self.server.server_name,
            host=host,
            port=port,
            private_action=action.action_name,
            params_dict={},
            json_dict={"action": action.as_dict()},
        )

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
        json_data_keys: Optional[List[str]] = None,
        action_abbr: Optional[str] = None,
        file_type: Optional[str] = None,
        hloheader=None,
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
        # Legacy Base.setup_and_contain_action parity: hte action endpoints pass
        # action_abbr / hloheader / file_type / json_data_keys. Apply action_abbr,
        # and when an HloHeaderModel is supplied serialize it to the header string
        # used when the default HLO connection opens lazily. file_type and
        # json_data_keys are accepted for signature parity but not threaded: the
        # default extension already matches ``{server}_helao__file`` and the HLO
        # column headings are inferred from the first data row (see
        # ActionSession._write_live_rows / _default_hlo_header).
        if action_abbr is not None:
            action.action_abbr = action_abbr
        if hloheader is not None:
            header = self.storage.serialize_hlo_header(hloheader.clean_dict())
        self._default_header = header
        return await self.contain_action(action)

    def _dflt_file_conn_key(self) -> UUID:
        """Return the legacy default file-connection UUID.

        Ports ``Base.dflt_file_conn_key()`` / ``new_file_conn_key(str(None))``:
        ``UUID(md5("None".encode("utf-8")).hexdigest())``.  The same deterministic
        key is used here so on-disk ``.hlo`` filenames are byte-for-byte identical
        to legacy output when no explicit ``file_conn_keys`` were supplied.
        """
        return UUID(hashlib.md5(str(None).encode("utf-8")).hexdigest())

    async def contain_action(self, action: RunAction) -> ActionSession:
        """Register ``action`` as active, substituting any prior session with the same UUID.

        Ports ``Base.contain_action``: a pre-existing session for the same
        ``action_uuid`` has its open handles closed (``substitute``) before being
        replaced; the new session is initialized (``myinit``) and a snapshot is
        recorded in ``history``.
        """
        if action.action_uuid in self.actives:
            await self.actives[action.action_uuid].substitute()

        # Inject the legacy default file-connection key when the dispatcher sent
        # an empty file_conn_keys list but the action still wants data saved.
        # Ports Base.setup_and_contain_action's dflt_file_conn_key() registration
        # (helao/core/servers/base.py:435/992/976/1177).  Guard is on save_data
        # (not save_act) so wait/no-data actions are unaffected.
        if action.save_data and not action.file_conn_keys:
            action.file_conn_keys.append(self._dflt_file_conn_key())

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
        # The default file connection is opened LAZILY on the first data write
        # (see ActionSession._write_live_rows), faithfully porting legacy
        # base.py:1633-1647: the .hlo is created only when data actually arrives,
        # by which point the endpoint has stamped action_abbr — so the filename
        # matches the legacy convention and an action that emits no data writes no
        # .hlo at all. An explicit header passed to setup_and_contain_action is
        # preserved for that lazy open.
        if self._default_header and action.save_data and action.file_conn_keys:
            session._pending_open_header = self._default_header
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

#: Attribute used to carry a per-endpoint action_version set via the
#: :func:`action_version` decorator until :func:`wrap_action_endpoint` reads it.
ACTION_VERSION_ATTR = "__helao_action_version__"

#: Default action schema version injected when an endpoint declares none.
DEFAULT_ACTION_VERSION = 1


def action_version(version: int) -> Callable:
    """Declare the schema version for a ``tags=["action"]`` endpoint.

    Stamps ``ACTION_VERSION_ATTR`` on the decorated function; the value is
    injected as the endpoint's ``action_version`` parameter by
    :func:`wrap_action_endpoint`, so it appears in the request schema and on
    the recorded action. Endpoints that still declare ``action_version`` inline
    keep that value and ignore this decorator.

    Args:
        version: The action schema version to advertise for the endpoint.

    Returns:
        A decorator that stamps ``version`` onto the endpoint function.
    """

    def decorator(fn: Callable) -> Callable:
        setattr(fn, ACTION_VERSION_ATTR, version)
        return fn

    return decorator


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
        # No RunAction wrapper in the request — normal for a manual/direct
        # invocation (e.g. a Swagger call that supplies only params). Build a
        # blank one and fold the kwargs into action_params below; myinit's
        # init_act() then stamps it as a manual run.
        LOGGER.info(
            "no RunAction in request kwargs; building a blank RunAction "
            "(manual/direct invocation)."
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
    """Augment ``fn``'s signature with injected ``action``/``action_version`` params.

    Ports ``base_api.py:_build_action_endpoint_signature`` (complete — including
    ``action_version`` decorator wiring added in hte recon T2). When the endpoint
    omits an explicit ``RunAction``-typed param we synthesize one (``action:
    RunAction = Body({}, embed=True)``). When the endpoint omits ``action_version``
    we inject it with the value from :func:`action_version` decorator if present,
    otherwise :data:`DEFAULT_ACTION_VERSION`.

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
    has_version = "action_version" in sig.parameters

    injected = []
    if not has_action:
        injected.append(
            inspect.Parameter(
                "action",
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=Body({}, embed=True),
                annotation=RunAction,
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

    from fastapi import FastAPI, WebSocket

    # Publish WebSocket into this module's globals so FastAPI can resolve the
    # ``websocket: WebSocket`` annotation on the ws-route handlers. This module
    # uses ``from __future__ import annotations`` (annotations are strings), and
    # FastAPI resolves them against each handler's ``__globals__`` (this module),
    # so a function-local import of WebSocket would NOT be visible to it. We
    # inject it here (lazy class-build time) rather than at module import to
    # preserve the lazy-FastAPI design.
    globals().setdefault("WebSocket", WebSocket)

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
            poller_class=None,
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
                dyn_endpoints: Optional callable (sync OR ``async def``) invoked
                    as ``dyn_endpoints(app=self)`` in the startup event, after the
                    drivers are built, to register extra routes. Async callables
                    are awaited (galil/gamry/sm303 use ``async def``).
                poller_class: Optional ``DriverPoller`` subclass; attached to the
                    first ``HelaoDriver`` at startup (legacy parity).
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

            world_cfg, server_cfg = self._load_server_cfg(server_key)

            # SP-ARTIFACT Task 2: derive save_root from config root when not
            # supplied explicitly. Tempdir is the fallback when no root key.
            if save_root is None:
                _root = world_cfg.get("root") if world_cfg else None
                if _root:
                    save_root = _root
                else:
                    save_root = tempfile.mkdtemp(prefix="helao_framework_baseapi_")
            os.makedirs(save_root, exist_ok=True)

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
            # Legacy parity: hte action servers read config off the *app*, not
            # the base — app.server_params (pal_server), app.helao_cfg (the whole
            # world config; mfc_server), app.server_cfg.
            self.server_params = base.server_params
            self.server_cfg = base.server_cfg
            self.helao_cfg = base.helao_cfg
            self.world_cfg = base.world_cfg

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
            self._poller_class = poller_class
            self.drivers = tuple()
            self.driver = None
            self.poller = None

            # dyn_endpoints is invoked in the startup event (after drivers are
            # built, loop live) so async callables can be awaited — see
            # _framework_base_startup. Registering it here would leave an async
            # dyn_endpoints coroutine un-awaited (routes never registered).
            self._dyn_endpoints = dyn_endpoints

            # --- private status-client endpoints (port base.py attach/detach) ---
            self._register_status_endpoints(server_key, base)

            # --- WS-B: ws publishers + admin/private endpoints --------------
            self._register_ws_routes(server_key, base)
            self._register_admin_endpoints(server_key, base)

            # --- WS-E: action-collision middleware + estop handler ----------
            self._register_concurrency_middleware(server_key, base)
            self._register_estop_handler(server_key, base)

            # --- startup hook: build drivers (loop live) + start base tasks --
            @self.on_event("startup")
            async def _framework_base_startup():
                # build drivers first: their __init__ may schedule poll tasks
                # onto the now-running loop.
                self._instantiate_drivers()
                await base.myinit()
                # dynamic endpoints: run AFTER drivers exist (dyn callables may
                # reference app.driver) and await async ones (galil/gamry/sm303).
                if self._dyn_endpoints is not None:
                    res = self._dyn_endpoints(app=self)
                    if inspect.iscoroutine(res):
                        await res
                await base.init_endpoint_status(self.routes)
                # WS-B: mirror every POST route as a HEAD route so the
                # dispatcher's endpoints_available HEAD probes return 200. Done
                # in startup (after all routes — incl. user dyn endpoints — are
                # registered) and is idempotent.
                self._add_head_mirrors()

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
            for i, driver_class in enumerate(self._driver_classes):
                if self._is_helao_driver(driver_class):
                    driver_inst = driver_class(config=self.base.server_params)
                    # legacy parity: attach the poller to the first HelaoDriver
                    if i == 0 and self._poller_class is not None:
                        self.poller = self._poller_class(
                            driver_inst,
                            self.base.server_cfg.get("polling_time", 0.1),
                        )
                        self.poller._base_hook = self.base
                else:
                    driver_inst = driver_class(self.base)
                driver_dict[driver_class.__name__] = driver_inst
            self.drivers = Drivers(**driver_dict)
            self.driver = self.drivers[0] if self.drivers else None
            # mirror onto the base so ActionSession.driver / active.driver reach
            # the server's driver (legacy Active.driver == base.app.driver).
            self.base.driver = self.driver
            self.base.drivers = self.drivers
            self.base.poller = self.poller

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

            @self.post("/attach_client", tags=["private"])
            async def attach_client(
                client_servkey: str, client_host: str, client_port: int
            ):
                return await base.attach_client(
                    client_servkey, client_host, client_port
                )

            @self.post("/detach_client", tags=["private"])
            async def detach_client(
                client_servkey: str, client_host: str, client_port: int
            ):
                base.detach_client(client_servkey, client_host, client_port)
                return True

        async def _ws_relay(self, websocket, channel: str) -> None:
            """Accept ``websocket`` and forward matching eventsink items until disconnect.

            Subscribes a fresh queue from the base's :class:`QueueEventSink`
            (multisubscriber, so this does not steal the status-push drain's
            events) and forwards the payload dict of every ``(channel, payload)``
            tuple whose channel equals ``channel``.

            WIRE FORMAT (SP8 WS-B): payloads are sent as **JSON** via
            ``send_json``. This DIFFERS from legacy ``Base._ws_relay``, which
            sends zstd-compressed pickle over a ``MultisubscriberQueue``. The
            framework visualizers (the only zstd-pickle consumers) are out of
            scope for SP8, so JSON parity with the Bokeh live-plot apps is
            deferred. Disconnects are handled cleanly: the loop stops on
            ``WebSocketDisconnect`` (or any send/recv error).
            """
            from starlette.websockets import WebSocketDisconnect

            from helao.framework.ports.eventsink import STATUS_CHANNEL

            await websocket.accept()
            subscribe = getattr(self.base.eventsink, "subscribe", None)
            if not callable(subscribe):
                await websocket.close()
                return
            queue = subscribe()
            try:
                while True:
                    item = await queue.get()
                    if isinstance(item, tuple) and len(item) == 2:
                        item_channel, payload = item
                    else:
                        # bare-payload sinks: forward only on the status channel
                        item_channel, payload = STATUS_CHANNEL, item
                    if item_channel != channel:
                        continue
                    await websocket.send_json(payload)
            except WebSocketDisconnect:
                return
            except Exception:
                # client gone / send failed: stop the relay quietly.
                return

        def _register_ws_routes(self, server_key, base):
            """Register the ``/ws_status`` / ``/ws_data`` / ``/ws_live`` publishers.

            Each route delegates to :meth:`_ws_relay` with its channel.
            ``ws_status`` forwards STATUS_CHANNEL items; ``ws_data`` and
            ``ws_live`` both forward DATA_CHANNEL items (legacy ``ws_live``
            relays live-buffer snapshots; the framework forwards the same data
            stream the live buffer is fed from — documented simplification, the
            visualizer live-plot parity is deferred to a later wave).
            """
            from helao.framework.ports.eventsink import (
                DATA_CHANNEL,
                STATUS_CHANNEL,
            )

            @self.websocket("/ws_status")
            async def ws_status(websocket: WebSocket):
                await self._ws_relay(websocket, STATUS_CHANNEL)

            @self.websocket("/ws_data")
            async def ws_data(websocket: WebSocket):
                await self._ws_relay(websocket, DATA_CHANNEL)

            @self.websocket("/ws_live")
            async def ws_live(websocket: WebSocket):
                await self._ws_relay(websocket, DATA_CHANNEL)

        def _register_admin_endpoints(self, server_key, base):
            """Register the legacy-named admin/private POST endpoints (WS-B).

            Mirrors ``helao.core.servers.base_api`` endpoint names/methods:
            ``get_status`` / ``get_config`` / ``endpoints`` / ``get_lbuf`` /
            ``list_executors`` / ``stop_executor`` / ``resend_active`` /
            ``shutdown`` plus the ``estop`` / ``stop`` action endpoints.
            """
            from fastapi import Body

            @self.post("/get_status", tags=["private"])
            def get_status():
                """Return the action-server model dump + driver status."""
                status_dict = base.actionservermodel.as_dict()
                driver_status = "not_implemented"
                drv = self.driver
                get_status_fn = getattr(drv, "get_status", None)
                if drv is not None and callable(get_status_fn):
                    try:
                        resp = get_status_fn()
                        driver_status = getattr(resp, "status", resp)
                    except Exception:
                        LOGGER.exception("driver get_status() failed")
                status_dict["_driver_status"] = driver_status
                return status_dict

            @self.post("/get_config", tags=["private"])
            def get_config():
                """Return this server's config block (no world secrets)."""
                return base.server_cfg

            @self.post("/endpoints", tags=["private"])
            def get_all_urls():
                """Return the registered route descriptors (``fast_urls``)."""
                return base.fast_urls

            @self.post("/get_lbuf", tags=["private"])
            def get_lbuf(live_key: str = Body(..., embed=True)):
                """Return the ``(value, timestamp)`` for ``live_key`` or ``None``."""
                try:
                    return base.get_lbuf(live_key)
                except KeyError:
                    return None

            @self.post("/list_executors", tags=["private"])
            def list_executors():
                """Return the ids of all registered executors."""
                return list(base.executors.keys())

            @self.post("/stop_executor", tags=["private"])
            def stop_executor(executor_id: str = Body(..., embed=True)):
                """Stop the named executor; report ``{stopped: bool}``."""
                executor = base.executors.get(executor_id)
                if executor is None:
                    return {"stopped": False, "executor_id": executor_id}
                stop_fn = getattr(executor, "stop_action_task", None)
                if callable(stop_fn):
                    stop_fn()
                return {"stopped": True, "executor_id": executor_id}

            @self.post("/resend_active", tags=["private"])
            def resend_active(action_uuid: str = Body(..., embed=True)):
                """Return the active action dict for ``action_uuid`` or ``None``."""
                try:
                    uuid = UUID(action_uuid)
                except (ValueError, AttributeError, TypeError):
                    return None
                return base.get_active_info(uuid)

            @self.post("/shutdown", tags=["private"])
            async def post_shutdown():
                """Trigger base + driver shutdown; report ``{ok: True}``."""
                await self._shutdown_drivers()
                await base.shutdown()
                return {"ok": True}

            @self.post(f"/{server_key}/estop", tags=["action"])
            async def estop(switch: bool = Body(True, embed=True)):
                """Latch the e-stop flag and stop every running executor."""
                base.actionservermodel.estop = bool(switch)
                for executor_id in list(base.executors):
                    executor = base.executors.get(executor_id)
                    stop_fn = getattr(executor, "stop_action_task", None)
                    if callable(stop_fn):
                        stop_fn()
                return {"estop": base.actionservermodel.estop}

            @self.post(f"/{server_key}/stop", tags=["action"])
            async def stop():
                """Generic stop: signal every running executor to stop."""
                for executor_id in list(base.executors):
                    executor = base.executors.get(executor_id)
                    stop_fn = getattr(executor, "stop_action_task", None)
                    if callable(stop_fn):
                        stop_fn()
                return {"ok": True}

        def _register_concurrency_middleware(self, server_key, base):
            """Register the ``app_entry`` action-collision HTTP middleware (WS-E).

            Ports ``helao.core.servers.base_api._make_app_entry_middleware``
            (383-481). Behaviour per request:

            * **HEAD** → return a bare 200 immediately (the dispatcher's
              ``endpoints_available`` probe; matches the WS-B HEAD mirrors —
              the middleware short-circuits before they are reached, which is
              fine since both answer 200).
            * **POST ``/{server_key}/...``** → inspect the target endpoint's
              ``active_dict``. If the endpoint is idle, the action starts with
              ``no_wait``, or it carries ``queued_launch`` (a re-dispatched
              queued action) → pass through (``call_next``). Otherwise queue it:
              the unified queue when concurrency is disabled and any endpoint is
              busy, else the per-endpoint queue. A queued action is stamped
              ``queued_on_actserv``, given a fresh uuid, has its status emitted
              through the shared eventsink (so the status drain folds it in and
              later re-dispatches it), and the queued action dict is returned.
            * **everything else** → ``call_next``.

            BODY REWIND: ``BaseHTTPMiddleware`` (what ``@app.middleware('http')``
            installs) drives the downstream app with its OWN receive channel, so
            a naive ``await request.body()`` here would drain the stream and the
            endpoint's ``await request.json()`` would hang waiting for a body
            that never arrives. We therefore re-inject the consumed bytes onto
            the request's receive channel (a one-shot ``http.request`` message
            carrying ``body_bytes``) BEFORE calling ``call_next``, so the
            downstream read succeeds without blocking. This is the anti-hang
            fix; ``test_passthrough_idle_endpoint_runs_and_returns`` proves a
            real POST runs end-to-end under ``asyncio.wait_for``.
            """
            from collections import deque

            from fastapi import Response
            from fastapi.responses import JSONResponse

            from helao.framework.models.action_start_condition import (
                ActionStartCondition,
            )

            prefix = f"{server_key}/"

            def _rewind_body(request, body_bytes):
                """Re-inject ``body_bytes`` so a downstream read does not hang."""
                sent = False

                async def receive():
                    nonlocal sent
                    if not sent:
                        sent = True
                        return {
                            "type": "http.request",
                            "body": body_bytes,
                            "more_body": False,
                        }
                    return {"type": "http.disconnect"}

                request._receive = receive

            @self.middleware("http")
            async def app_entry(request, call_next):
                if request.method == "HEAD":
                    # endpoint-checker probe: 200 immediately, no call_next.
                    return Response()

                path = request.url.path.strip("/")
                if not (path.startswith(prefix) and request.method == "POST"):
                    return await call_next(request)

                endpoint = path.split("/")[-1]
                body_bytes = await request.body()
                # rewind so the downstream endpoint can re-read the body.
                _rewind_body(request, body_bytes)
                try:
                    import json as _json

                    body_dict = _json.loads(body_bytes) if body_bytes else {}
                except Exception:
                    body_dict = {}
                action_dict = body_dict.get("action", {}) or {}
                params = action_dict.get("action_params", {}) or {}
                start_cond = action_dict.get(
                    "start_condition", ActionStartCondition.wait_for_all
                )

                endpoints = base.actionservermodel.endpoints
                endmod = endpoints.get(endpoint)
                idle = endmod is None or len(endmod.active_dict) == 0
                if (
                    idle
                    or start_cond == ActionStartCondition.no_wait
                    or params.get("queued_launch", False)
                ):
                    return await call_next(request)

                allow_concurrent = base.server_params.get(
                    "allow_concurrent_actions", True
                )
                if not allow_concurrent:
                    active_endpoints = [
                        ep
                        for ep, em in endpoints.items()
                        if em.active_dict
                    ]
                    if active_endpoints:
                        action = await self._queue_action(
                            base, server_key, endpoint, action_dict, request
                        )
                        base.local_action_queue.append((action, {}))
                        return JSONResponse(action.as_dict())
                    return await call_next(request)

                # same-endpoint collision: queue on the endpoint's own queue.
                action = await self._queue_action(
                    base, server_key, endpoint, action_dict, request
                )
                base.endpoint_queues.setdefault(endpoint, deque()).append(
                    (action, {})
                )
                return JSONResponse(action.as_dict())

        @staticmethod
        async def _queue_action(base, server_key, endpoint, action_dict, request):
            """Build a queued :class:`RunAction`, emit its status, and return it.

            Ports the queueing half of legacy ``app_entry`` (base_api.py:430-451):
            stamp ``queued_on_actserv``, mint a fresh uuid, set
            ``action_name``/``action_server``, and emit the status through the
            shared eventsink (legacy did ``status_q.put(action.get_act())``; the
            framework emits via ``eventsink.emit_status`` so the status-push
            drain folds it into ``actionservermodel`` and later re-dispatches it).
            """
            import uuid as _uuid

            action_dict = dict(action_dict)
            action_dict["action_params"] = dict(action_dict.get("action_params", {}))
            action_dict["action_params"]["queued_on_actserv"] = True
            action = RunAction(**action_dict)
            action.action_uuid = _uuid.uuid4()
            action.action_name = endpoint
            action.action_server = MachineModel(
                server_name=server_key,
                machine_name=base.server.machine_name,
            )
            await base.eventsink.emit_status(action.as_dict())
            return action

        def _register_estop_handler(self, server_key, base):
            """Register the estop-all-on-unhandled-error HTTP exception handler.

            Ports ``_make_http_exception_handler`` (base_api.py:486-512). When a
            request to a ``/{server_key}/...`` path raises, every active session
            is e-stopped and every registered executor is stopped, then the
            default FastAPI handler turns the exception into its HTTP response.

            Active-session e-stop is duck-typed: an :class:`ActionSession` has no
            ``set_estop`` (the legacy ``Active`` did), so we prefer ``set_estop``
            when present and otherwise append ``HloStatus.estopped`` to the
            action's status — matching the legacy ``Active.set_estop`` effect.

            Two handlers are registered. The legacy server only handled
            ``StarletteHTTPException`` because its ``status_q`` drain re-raised
            endpoint errors AS HTTP exceptions; the framework endpoint bodies can
            raise a bare ``Exception`` (e.g. a driver fault), which FastAPI would
            otherwise route straight to ``ServerErrorMiddleware`` as a 500 WITHOUT
            firing the HTTP-exception handler. We therefore also register a
            generic ``Exception`` handler that e-stops then RE-RAISES so the 500
            response is still produced by the server-error middleware.
            """
            from starlette.exceptions import HTTPException as StarletteHTTPException
            from fastapi.exception_handlers import http_exception_handler

            prefix = f"{server_key}/"

            def _estop_all():
                LOGGER.error(f"e-stopping all active work on {server_key}")
                for _, active in list(base.actives.items()):
                    self._estop_active(active)
                for executor_id in list(base.executors):
                    executor = base.executors.get(executor_id)
                    stop_fn = getattr(executor, "stop_action_task", None)
                    if callable(stop_fn):
                        try:
                            stop_fn()
                        except Exception:
                            LOGGER.exception(
                                f"stop_action_task failed for {executor_id}"
                            )

            @self.exception_handler(StarletteHTTPException)
            async def _estop_http_exception_handler(request, exc):
                if request.url.path.strip("/").startswith(prefix):
                    LOGGER.error(f"Could not process request: {repr(exc)}")
                    _estop_all()
                return await http_exception_handler(request, exc)

            @self.exception_handler(Exception)
            async def _estop_unhandled_exception_handler(request, exc):
                if request.url.path.strip("/").startswith(prefix):
                    LOGGER.error(f"Unhandled error processing request: {repr(exc)}")
                    _estop_all()
                # re-raise so ServerErrorMiddleware produces the 500 response.
                raise exc

        @staticmethod
        def _estop_active(active):
            """E-stop one active session (``set_estop`` or status fallback)."""
            from helao.framework.models.hlostatus import HloStatus

            set_estop = getattr(active, "set_estop", None)
            if callable(set_estop):
                try:
                    set_estop()
                    return
                except Exception:
                    LOGGER.exception("set_estop failed on active session")
            action = getattr(active, "action", None)
            if action is not None and HloStatus.estopped not in action.action_status:
                action.action_status.append(HloStatus.estopped)

        def _add_head_mirrors(self):
            """Add a lightweight HEAD route for every POST path (idempotent).

            The dispatcher's ``endpoints_available`` probes routes with HEAD
            requests and treats only a 2xx as "available"
            (``support/dispatcher.endpoints_available``). FastAPI registers only
            the declared POST handler per path, so a bare HEAD probe 405s.

            Unlike the legacy ``_add_default_head_endpoints`` (which shallow-
            copies the POST route and merely swaps its methods to HEAD), copying
            the route keeps the POST endpoint's body dependant — an action
            route's required ``action`` body then makes the HEAD probe 422
            (a *client* error, not 2xx). Instead this registers a dedicated
            no-arg HEAD handler per path that always returns 200, which is what
            the dispatcher's reachability probe actually needs.
            """
            from fastapi.routing import APIRoute

            existing_head = {
                getattr(r, "path", None)
                for r in self.routes
                if isinstance(r, APIRoute) and "HEAD" in (r.methods or set())
            }
            post_paths = {
                route.path
                for route in self.routes
                if isinstance(route, APIRoute)
                and "POST" in (route.methods or set())
            }
            for path in post_paths:
                if path in existing_head:
                    continue
                self.add_api_route(
                    path,
                    self._head_probe,
                    methods=["HEAD"],
                    include_in_schema=False,
                )
                existing_head.add(path)

        @staticmethod
        async def _head_probe():
            """No-op HEAD handler: 200 reachability marker for the dispatcher."""
            return None

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
