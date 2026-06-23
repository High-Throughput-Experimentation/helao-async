"""Thin in-process action runner.

Runs a single :class:`~helao.framework.domain.run_models.RunAction` to
completion through the shared micro-orchestrator (and therefore the same FSM +
command glue as the orchestrator app). No HTTP server.
"""
from __future__ import annotations

from typing import Optional

from helao.framework.domain.orchestration import OrchState
from helao.framework.domain.run_models import RunAction
from helao.framework.ports.transport import Transport
from helao.framework.runners import micro_orch

__all__ = ["run_action"]


def run_action(
    action: RunAction,
    *,
    transport: Optional[Transport] = None,
    save_root: Optional[str] = None,
) -> OrchState:
    """Drive ``action`` to completion in-process; return the final state."""
    return micro_orch.run_action(action, transport=transport, save_root=save_root)
