"""In-process micro-orchestrator runners.

These runners drive the *same* pure FSM (:mod:`helao.framework.domain.orchestration`)
and the *same* command-execution glue (:func:`helao.framework.app.orch_api.execute_commands`)
as the long-lived :class:`~helao.framework.app.orch_api.OrchDriver`, but with no
HTTP server: a short-lived in-process loop builds an ``OrchState``, enqueues a
sequence/experiment/action, and runs it to completion. This realises the
"runner stubs get a real implementation for free" promise (parent spec §4.8) —
there is no duplicated dispatch logic.
"""

from helao.framework.runners.micro_orch import MicroOrch, run_sequence
from helao.framework.runners.action_runner import run_action
from helao.framework.runners.experiment_runner import run_experiment
from helao.framework.runners.sequence_runner import run_sequence as run_sequence_lib

__all__ = [
    "MicroOrch",
    "run_sequence",
    "run_action",
    "run_experiment",
    "run_sequence_lib",
]
