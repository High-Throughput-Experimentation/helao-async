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

import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID

from helao.framework.domain.action_session import ActionSession
from helao.framework.domain.run_models import RunAction
from helao.framework.ports.clock import Clock
from helao.framework.ports.eventsink import EventSink
from helao.framework.ports.storage import Storage
from helao.framework.ports.transport import Transport

from helao.framework.support import helao_logging as logging

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
        # running executors keyed by exec_id; maps to the ActionSession driving
        # it (ports Base.executors). Deployment cancel-endpoints iterate this.
        self.executors: Dict[str, ActionSession] = {}
        # live data buffer: key -> (value, epoch_seconds). Ports Base.live_buffer.
        self.live_buffer: Dict[str, Any] = {}

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
