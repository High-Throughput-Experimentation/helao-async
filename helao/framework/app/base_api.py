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

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID

from helao.framework.domain.action_session import ActionSession
from helao.framework.domain.run_models import RunAction
from helao.framework.ports.clock import Clock
from helao.framework.ports.eventsink import EventSink
from helao.framework.ports.storage import Storage
from helao.framework.ports.transport import Transport

__all__ = ["ActionContext", "FrameworkBase"]


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
    ) -> None:
        """Wire the base to its server identity and injected adapters.

        Args:
            server_key: Server identifier stamped onto contained actions.
            storage: Storage adapter for HLO/meta/aux output.
            eventsink: EventSink adapter for status/data broadcast.
            clock: Clock adapter for timestamps.
            transport: Optional transport adapter (global-param export).
            postprocessors: Names of HLO post-processors to run at finish.
        """
        self.server_key = server_key
        self.storage = storage
        self.eventsink = eventsink
        self.clock = clock
        self.transport = transport
        self.postprocessors = list(postprocessors or [])
        self.actives: Dict[UUID, ActionSession] = {}
        self.history: Dict[UUID, RunAction] = {}

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
        ctx: ActionContext,
        *,
        header: str = "",
    ) -> ActionSession:
        """Build the request's action and wrap it in an :class:`ActionSession`.

        Ports ``Base.setup_and_contain_action``: finalize the action, default its
        file-connection header, and hand it to :meth:`contain_action`.

        Args:
            ctx: The per-request action context.
            header: Default HLO header for this action's file connections.

        Returns:
            The :class:`ActionSession` now tracking this action.
        """
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
