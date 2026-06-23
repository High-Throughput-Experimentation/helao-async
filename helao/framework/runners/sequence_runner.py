"""Thin in-process sequence runner.

Runs a single :class:`~helao.framework.domain.run_models.RunSequence` to
completion through the shared micro-orchestrator (same FSM + command glue as the
orchestrator app). The sequence is expanded into experiments (via
``sequence_lib``) and each experiment into actions (via ``experiment_lib``).
No HTTP server.
"""
from __future__ import annotations

from typing import Callable, Mapping, Optional

from helao.framework.domain.orchestration import OrchState
from helao.framework.domain.run_models import RunSequence
from helao.framework.ports.transport import Transport
from helao.framework.runners import micro_orch

__all__ = ["run_sequence"]


def run_sequence(
    sequence: RunSequence,
    *,
    sequence_lib: Optional[Mapping[str, Callable]] = None,
    experiment_lib: Optional[Mapping[str, Callable]] = None,
    transport: Optional[Transport] = None,
    save_root: Optional[str] = None,
) -> OrchState:
    """Drive ``sequence`` to completion in-process; return the final state."""
    return micro_orch.run_sequence(
        sequence,
        sequence_lib=sequence_lib,
        experiment_lib=experiment_lib,
        transport=transport,
        save_root=save_root,
    )
