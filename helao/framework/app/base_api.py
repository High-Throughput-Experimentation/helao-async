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
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID

from helao.framework.domain.action_session import ActionSession
from helao.framework.domain.run_models import RunAction
from helao.framework.models.action import ActionModel
from helao.framework.models.errors import ErrorCodes
from helao.framework.models.hlostatus import HloStatus
from helao.framework.models.machine import MachineModel
from helao.framework.models.server import ActionServerModel, EndpointModel
from helao.framework.ports.clock import Clock
from helao.framework.ports.eventsink import EventSink
from helao.framework.ports.storage import Storage
from helao.framework.ports.transport import Transport

from helao.framework.support import helao_logging as logging

#: A registered status-client coordinate: ``(server_key, host, port)``.
ClientCoord = Tuple[str, str, int]

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

__all__ = ["ActionContext", "ACTION_CTX", "FrameworkBase"]


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


#: Per-request action context published by the action-endpoint wrapper in
#: ``server_api.wrap_action_endpoint`` and read by
#: ``FrameworkBase.setup_and_contain_action`` when no ctx is passed explicitly.
ACTION_CTX: "ContextVar[Optional[ActionContext]]" = ContextVar(
    "helao_framework_action_ctx", default=None
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
        world_cfg: Optional[Dict] = None,
    ) -> None:
        """Wire the base to its server identity and injected adapters.

        Args:
            server_key: Server identifier stamped onto contained actions.
            storage: Storage adapter for HLO/meta/aux output.
            eventsink: EventSink adapter for status/data broadcast.
            clock: Clock adapter for timestamps.
            transport: Optional transport adapter (global-param export).
            postprocessors: Names of HLO post-processors to run at finish.
            world_cfg: Full HELAO world config dict (from CONFIG singleton).
        """
        self.server_key = server_key
        self.storage = storage
        self.eventsink = eventsink
        self.clock = clock
        self.transport = transport
        self.postprocessors = list(postprocessors or [])
        self.actives: Dict[UUID, ActionSession] = {}
        self.history: Dict[UUID, RunAction] = {}
        self.world_cfg: Dict = world_cfg or {}
        self.server_cfg: Dict = self.world_cfg.get("servers", {}).get(server_key, {})
        # per-server params block (ports Base.server_params); HelaoDriver
        # subclasses are constructed with ``config=server_params`` (SP8 WS-C).
        self.server_params: Dict = self.server_cfg.get("params", {})
        # running executors keyed by exec_id; maps to the ActionSession driving
        # it (ports Base.executors). Deployment cancel-endpoints iterate this.
        self.executors: Dict[str, ActionSession] = {}
        # live data buffer: key -> (value, epoch_seconds). Ports Base.live_buffer.
        self.live_buffer: Dict[str, Any] = {}

        # --- orch status-push surface (ports Base; SP8 WS-A) -----------------
        # server identity used by the action-server status model + nb params.
        self.server = MachineModel(
            server_name=server_key,
            machine_name=self.server_cfg.get("machine_name"),
            hostname=self.server_cfg.get("host"),
            port=self.server_cfg.get("port"),
        )
        # live per-endpoint/per-server status snapshot (ports Base.actionservermodel).
        self.actionservermodel = ActionServerModel(action_server=self.server)
        self.actionservermodel.init_endpoints()
        # registered orchestrator status subscribers (ports Base.status_clients).
        self.status_clients: Set[ClientCoord] = set()
        # background task draining the eventsink status stream -> push to clients.
        # Started lazily (first attach_client) or by the startup hook's start();
        # never assume a running loop at __init__ (Python 3.12 raises).
        self._status_drain_task: Optional[asyncio.Task] = None

    # --- live buffer (ports Base.put_lbuf / get_lbuf) ------------------------

    @staticmethod
    def _stamp_lbuf_dict(live_dict: dict) -> dict:
        """Wrap each value in a ``(value, epoch_s)`` tuple for the live buffer."""
        now = time.time()
        return {k: (v, now) for k, v in live_dict.items()}

    async def put_lbuf(self, live_dict: dict) -> None:
        """Timestamp ``live_dict`` and fold it into the live buffer."""
        self.live_buffer.update(self._stamp_lbuf_dict(live_dict))

    def put_lbuf_nowait(self, live_dict: dict) -> None:
        """Timestamp ``live_dict`` and fold it into the live buffer (sync)."""
        self.live_buffer.update(self._stamp_lbuf_dict(live_dict))

    def get_lbuf(self, live_key):
        """Return the most recent ``(value, timestamp)`` tuple stored under ``live_key``."""
        return self.live_buffer[live_key]

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
        action_abbr: Optional[str] = None,
        json_data_keys: Optional[List[str]] = None,
        file_type: Optional[str] = None,
        hloheader: Optional[Any] = None,
        header: str = "",
    ) -> ActionSession:
        """Build the request's action and wrap it in an :class:`ActionSession`.

        Ports ``Base.setup_and_contain_action``. When ``ctx`` is omitted the
        per-request :data:`ACTION_CTX` (published by the action-endpoint wrapper
        in ``server_api``) supplies the action, so deployment endpoints can call
        ``await app.base.setup_and_contain_action()`` with no arguments exactly
        as they did against the legacy ``Base``.

        Args:
            ctx: Optional per-request action context. Falls back to ``ACTION_CTX``.
            action_abbr: Optional short abbreviation stored on the action.
            json_data_keys: Column names for the default HLO file connection
                (accepted for legacy parity; file-connection wiring is an
                app/adapter concern handled at finish time).
            file_type: Optional HLO file type (legacy parity).
            hloheader: Optional HLO header (legacy parity).
            header: Default HLO header string for this action's file connections.

        Returns:
            The :class:`ActionSession` now tracking this action.
        """
        if ctx is None:
            ctx = ACTION_CTX.get(None)
        if ctx is None:
            LOGGER.error(
                "setup_and_contain_action called outside an action endpoint "
                "context and with no ctx; using a blank RunAction."
            )
            ctx = ActionContext(action=RunAction())
        action = self._get_action(ctx)
        if action_abbr is not None:
            action.action_abbr = action_abbr
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
        self.history[action.action_uuid] = action.model_copy(deep=True)
        return session

    def get_active_info(self, action_uuid: UUID) -> Optional[dict]:
        """Return the dict form of an active action, or ``None``. Ports ``Base.get_active_info``."""
        if action_uuid in self.actives:
            return self.actives[action_uuid].action.as_dict()
        return None

    # --- orch status model (ports Base.init_endpoint_status; SP8 WS-A) -------

    def init_endpoint_status(self, app: Any) -> None:
        """Register every action route on ``app`` with the status model.

        Ports ``Base.init_endpoint_status``: each route whose path begins
        ``/<server_key>`` becomes an :class:`EndpointModel` in
        ``actionservermodel.endpoints`` keyed by the route name. Sorting each
        endpoint's status leaves it with an empty ``finished`` bucket so the
        first emitted status sorts cleanly.

        Args:
            app: The FastAPI app whose ``routes`` are introspected.
        """
        prefix = f"/{self.server_key}"
        for route in getattr(app, "routes", []):
            path = getattr(route, "path", "")
            name = getattr(route, "name", None)
            if name and path.startswith(prefix):
                self.actionservermodel.endpoints[name] = EndpointModel(
                    endpoint_name=name
                )
                self.actionservermodel.endpoints[name].sort_status()
        LOGGER.info(
            f"Found {len(self.actionservermodel.endpoints)} endpoints for "
            f"status monitoring on {self.server_key}."
        )

    # --- status clients (ports Base.attach_client / detach_client) -----------

    async def attach_client(
        self,
        client_servkey: str,
        client_host: str,
        client_port: int,
        retry_limit: int = 5,
    ) -> bool:
        """Register an orchestrator as a status subscriber; push an initial snapshot.

        Ports ``Base.attach_client``. The background status-drain task is started
        lazily here (we are now guaranteed a running loop) so the first attach
        wires up the emit->push pipeline. The current full status snapshot
        (``action_name=None``) is delivered to the new client.

        Returns:
            ``True`` if the initial snapshot was delivered, ``False`` otherwise.
        """
        self._ensure_status_drain()
        combo_key: ClientCoord = (client_servkey, client_host, client_port)
        if combo_key in self.status_clients:
            LOGGER.info(f"Client {combo_key} already subscribed to {self.server_key}.")
        self.status_clients.add(combo_key)

        success = False
        for _ in range(retry_limit):
            response, error_code = await self.send_statuspackage(
                client_servkey=client_servkey,
                client_host=client_host,
                client_port=client_port,
                action_name=None,
            )
            if response is not None and error_code == ErrorCodes.none:
                LOGGER.info(f"Added {combo_key} to {self.server_key} subscribers.")
                success = True
                break
            LOGGER.error(f"Failed to add {combo_key} to {self.server_key} subscribers.")
        return success

    def detach_client(
        self, client_servkey: str, client_host: str, client_port: int
    ) -> bool:
        """Remove an orchestrator from the status subscriber set. Ports ``Base.detach_client``."""
        combo_key: ClientCoord = (client_servkey, client_host, client_port)
        if combo_key in self.status_clients:
            self.status_clients.remove(combo_key)
            LOGGER.info(f"Client {combo_key} will no longer receive status updates.")
            return True
        LOGGER.info(f"Client {combo_key} is not subscribed.")
        return False

    # --- status push (ports Base.send_statuspackage / send_nbstatuspackage) --

    async def send_statuspackage(
        self,
        client_servkey: str,
        client_host: str,
        client_port: int,
        action_name: Optional[str] = None,
    ) -> tuple:
        """POST the current action-server model to one subscriber's ``update_status``.

        Ports ``Base.send_statuspackage``: the payload is byte-compatible with
        what the orchestrator's ``update_status`` parses
        (``{"actionservermodel": ActionServerModel.get_fastapi_json(...)}``).
        """
        from helao.framework.support.dispatcher import async_private_dispatcher

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
        actionmodel: ActionModel,
    ) -> tuple:
        """POST a single non-blocking action transition to ``update_nonblocking``.

        Ports ``Base.send_nbstatuspackage``.
        """
        from helao.framework.support.dispatcher import async_private_dispatcher

        json_dict = {"actionmodel": actionmodel.as_dict()}
        params_dict = {
            "server_host": self.server_cfg.get("host"),
            "server_port": self.server_cfg.get("port"),
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

    # --- status-drain background task (ports Base.log_status_task) -----------

    def _ensure_status_drain(self) -> None:
        """Start the eventsink->client drain task if not already running.

        Started lazily so ``__init__`` never assumes a running loop (Python 3.12
        raises ``RuntimeError`` if there is none). Idempotent.
        """
        if self._status_drain_task is not None and not self._status_drain_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            LOGGER.debug("no running loop; status drain not started yet")
            return
        sub = getattr(self.eventsink, "subscribe", None)
        if not callable(sub):
            LOGGER.warning("eventsink has no subscribe(); status drain disabled")
            return
        self._status_q = self.eventsink.subscribe()
        self._status_drain_task = loop.create_task(self._status_drain_loop())

    async def start(self) -> None:
        """Async startup hook: ensure the status-drain task is running.

        Called by the server startup hook once the event loop exists. Safe to
        call when no status clients are attached yet.
        """
        self._ensure_status_drain()

    async def _status_drain_loop(self, retry_limit: int = 5) -> None:
        """Drain status emissions and push each to every registered client.

        Ports ``Base.log_status_task``: each ``(channel, payload)`` pulled off the
        eventsink status subscription is parsed back into an :class:`ActionModel`,
        folded into ``actionservermodel`` (active bucket + ``last_action_uuid``),
        sorted, then ``send_statuspackage`` POSTs it to each subscriber's
        ``update_status``; finished/errored entries are cleared afterwards so the
        next snapshot starts clean (matching the legacy ``clear_finished``).
        """
        from helao.framework.ports.eventsink import (
            STATUS_CHANNEL,
            NONBLOCKING_STATUS_CHANNEL,
        )

        LOGGER.info(f"{self.server_key} status drain task created.")
        try:
            while True:
                channel, payload = await self._status_q.get()
                if channel not in (STATUS_CHANNEL, NONBLOCKING_STATUS_CHANNEL):
                    continue
                try:
                    status_msg = ActionModel(**dict(payload))
                except Exception:
                    LOGGER.error("could not parse status payload", exc_info=True)
                    continue
                if channel == NONBLOCKING_STATUS_CHANNEL:
                    await self._push_nonblocking_status(
                        status_msg, retry_limit=retry_limit
                    )
                else:
                    await self._fold_and_push_status(
                        status_msg, retry_limit=retry_limit
                    )
        except asyncio.CancelledError:
            LOGGER.info(f"{self.server_key} status drain task cancelled.")
            raise

    async def _fold_and_push_status(
        self, status_msg: ActionModel, retry_limit: int = 5
    ) -> None:
        """Fold one action status into the model and push to every client."""
        name = status_msg.action_name
        if name not in self.actionservermodel.endpoints:
            self.actionservermodel.endpoints[name] = EndpointModel(endpoint_name=name)
        self.actionservermodel.endpoints[name].active_dict.update(
            {status_msg.action_uuid: status_msg}
        )
        self.actionservermodel.last_action_uuid = status_msg.action_uuid
        self.actionservermodel.endpoints[name].sort_status()

        for combo_key in self.status_clients.copy():
            client_servkey, client_host, client_port = combo_key
            success = False
            for _ in range(retry_limit):
                response, error_code = await self.send_statuspackage(
                    client_servkey=client_servkey,
                    client_host=client_host,
                    client_port=client_port,
                    action_name=name,
                )
                if response and error_code == ErrorCodes.none:
                    success = True
                    break
            if success:
                LOGGER.info(f"Pushed status message to {client_servkey}.")
            else:
                LOGGER.error(
                    f"Failed to push status to {client_servkey} after "
                    f"{retry_limit} attempts."
                )
        # clear finished/errored after pushing so the next snapshot starts clean
        self.actionservermodel.endpoints[name].clear_finished()

    async def _push_nonblocking_status(
        self, status_msg: ActionModel, retry_limit: int = 5
    ) -> None:
        """Push one non-blocking action transition to every client's ``update_nonblocking``.

        Ports the legacy ``Active.send_nonblocking_status`` (single-action POST to
        ``update_nonblocking``); non-blocking actions are never folded into the
        ``actionservermodel`` snapshot.
        """
        for combo_key in self.status_clients.copy():
            client_servkey, client_host, client_port = combo_key
            success = False
            for _ in range(retry_limit):
                response, error_code = await self.send_nbstatuspackage(
                    client_servkey=client_servkey,
                    client_host=client_host,
                    client_port=client_port,
                    actionmodel=status_msg,
                )
                if (
                    isinstance(response, dict)
                    and response.get("success", False)
                    and error_code == ErrorCodes.none
                ):
                    success = True
                    break
            if not success:
                LOGGER.error(
                    f"Failed to push nonblocking status to {client_servkey} "
                    f"after {retry_limit} attempts."
                )

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
