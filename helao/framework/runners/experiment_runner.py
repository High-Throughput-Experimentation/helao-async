"""Thin in-process experiment runner.

Runs a single :class:`~helao.framework.domain.run_models.RunExperiment` to
completion through the shared micro-orchestrator (same FSM + command glue as the
orchestrator app). The experiment is expanded into actions via the injected
``experiment_lib`` map. No HTTP server.
"""
from __future__ import annotations

from typing import Callable, Mapping, Optional

from helao.framework.domain.orchestration import OrchState
from helao.framework.domain.run_models import RunExperiment
from helao.framework.ports.transport import Transport
from helao.framework.runners import micro_orch

__all__ = ["run_experiment"]


def run_experiment(
    experiment: RunExperiment,
    *,
    experiment_lib: Optional[Mapping[str, Callable]] = None,
    transport: Optional[Transport] = None,
    save_root: Optional[str] = None,
) -> OrchState:
    """Drive ``experiment`` to completion in-process; return the final state."""
    return micro_orch.run_experiment(
        experiment,
        experiment_lib=experiment_lib,
        transport=transport,
        save_root=save_root,
    )
