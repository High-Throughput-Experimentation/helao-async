"""Command / result value objects returned by pure domain functions.

The domain layer never performs I/O. Pure functions (see
:mod:`helao.framework.domain.lifecycle`) compute the next run-model state plus a
description of the side effects to apply, and return them as immutable value
objects. The caller in ``app/`` realises those effects through the injected
ports.

Purity: this module imports only from ``helao.framework.models`` (and stdlib).
"""

__all__ = [
    "ActionInit",
    "SplitResult",
    "OrchDecision",
    "DispatchAction",
    "ExpandSequence",
    "ExpandExperiment",
    "PersistMeta",
    "EstopServers",
    "BroadcastGlobalStatus",
    "FinishExperiment",
    "FinishSequence",
    "MoveRunDir",
    "StopExecutor",
]

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Mapping, Optional
from uuid import UUID

from helao.framework.domain.run_models import RunAction


@dataclass(frozen=True)
class ActionInit:
    """Result of :func:`helao.framework.domain.lifecycle.init_action`.

    Attributes:
        action: The action with identity (timestamp/uuid/status/output_dir)
            assigned. When ``manual`` is true, synthetic sequence/experiment
            identity has also been initialised on it.
        manual: True when the action was auto-promoted to a manual run because
            it had no parent sequence/experiment timestamps.
    """

    action: RunAction
    manual: bool = False


@dataclass(frozen=True)
class SplitResult:
    """Result of :func:`helao.framework.domain.lifecycle.split_action`.

    Attributes:
        new_action: The freshly re-initialised current action (new uuid /
            timestamp / incremented ``action_split``).
        prev_action: A snapshot of the action prior to the split, marked
            ``HloStatus.split`` and linked to ``new_action`` as its child.
        open_file_conns: File-connection keys to open (header write) for the new
            action — one per prior file connection. Already mirrored onto
            ``new_action.file_conn_keys``.
        close_file_conns: File-connection keys to close on the previous action —
            the prior action's ``file_conn_keys``.
    """

    new_action: RunAction
    prev_action: RunAction
    open_file_conns: List[UUID] = field(default_factory=list)
    close_file_conns: List[UUID] = field(default_factory=list)


# --- orchestration FSM commands ------------------------------------------------
#
# The orchestrator FSM (:mod:`helao.framework.domain.orchestration`) is pure: its
# transition functions return ``(OrchState, [Command])`` where each command is one
# of the frozen value objects below. ``app/orch_api.py`` realises them through the
# injected transport/eventsink/storage ports. Commands never carry live ports or
# perform I/O; they are plain data describing *what* to do, not *how*.


class OrchDecision(str, Enum):
    """The next action the dispatch loop should take, per :func:`decide_next`.

    Ports the priority order of ``Orch.dispatch_loop_task``: pull an action, else
    finish/dispatch an experiment, else finish/dispatch a sequence, else wait or
    stop. ``decide_next`` is a pure read of :class:`OrchState`; it does not mutate.

    Members:
        DISPATCH_ACTION: ``action_dq`` is non-empty — dispatch its next action.
        DISPATCH_EXPERIMENT: actions drained, ``experiment_dq`` non-empty and
            actions idle — expand/dispatch the next experiment.
        DISPATCH_SEQUENCE: actions+experiments drained, ``sequence_dq`` non-empty
            and actions idle — expand/dispatch the next sequence.
        FINISH_EXPERIMENT: actions drained with a still-active experiment to wrap
            up before the next experiment/sequence.
        FINISH_SEQUENCE: actions+experiments drained with a still-active sequence
            to wrap up.
        WAIT: queues have work but actions are still running (gating exp/seq).
        STOP: a stop/estop intent or state means the loop should halt.
        IDLE: every queue is empty and nothing is active — loop is done.
    """

    DISPATCH_ACTION = "dispatch_action"
    DISPATCH_EXPERIMENT = "dispatch_experiment"
    DISPATCH_SEQUENCE = "dispatch_sequence"
    FINISH_EXPERIMENT = "finish_experiment"
    FINISH_SEQUENCE = "finish_sequence"
    WAIT = "wait"
    STOP = "stop"
    IDLE = "idle"


@dataclass(frozen=True)
class DispatchAction:
    """Dispatch ``action`` to its action server over the transport port.

    Ports the ``async_action_dispatcher`` call in
    ``Orch.loop_task_dispatch_action``. The FSM has already stamped identity
    (uuid/timestamp/order), folded in global params and self-registered the
    action in the global status model; ``app/`` performs the RPC/HTTP request and
    feeds the response back via :func:`orchestration.on_dispatch_result`.

    Attributes:
        action: The fully-prepared :class:`RunAction` to dispatch.
        nonblocking: Mirror of ``action.nonblocking``; when true the orchestrator
            does not self-register/await the action result.
    """

    action: RunAction
    nonblocking: bool = False


@dataclass(frozen=True)
class ExpandSequence:
    """Request expansion of the active sequence into planned experiments.

    Ports the ``unpack_sequence`` callback in ``loop_task_dispatch_sequence``. The
    library call is an ``app/`` side effect; its result is fed back into
    :func:`orchestration.dispatch_sequence` via the injected ``expand_result``.

    Attributes:
        sequence_name: Sequence library entry to expand.
        sequence_params: Keyword params forwarded to the sequence factory.
    """

    sequence_name: Optional[str]
    sequence_params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExpandExperiment:
    """Request expansion of the active experiment into planned actions.

    Ports the experiment-factory call in ``loop_task_dispatch_experiment``. The
    library call is an ``app/`` side effect; its result is fed back into
    :func:`orchestration.dispatch_experiment` via the injected ``expand_result``.

    Attributes:
        experiment_name: Experiment library entry to expand.
        experiment_params: Candidate keyword params for the factory.
    """

    experiment_name: Optional[str]
    experiment_params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PersistMeta:
    """Persist a sequence/experiment/action meta document via the storage port.

    Ports the ``write_seq`` / ``write_active_experiment_exp`` / ``.act`` writes the
    legacy dispatch loops issued when a queue item became active.

    Attributes:
        kind: One of ``"seq"``, ``"exp"``, ``"act"``.
        uuid: UUID of the object the meta describes.
        payload: Serialized meta document (``as_dict()`` form).
    """

    kind: str
    uuid: Optional[UUID]
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EstopServers:
    """Fan an ``estop`` action out to every registered action server.

    Ports ``Orch.estop_actions``. ``switch`` latches (True) or releases (False)
    the estop on each server.

    Attributes:
        switch: True to latch estop, False to release it (clear-estop path).
        reason: Free-form text appended to the stop message/alert.
    """

    switch: bool = False
    reason: str = ""


@dataclass(frozen=True)
class StopExecutor:
    """Tell one action server to stop a running non-blocking executor.

    Ports the per-entry ``stop_executor`` private dispatch in
    ``Orch.clear_nonblocking``.

    Attributes:
        server_key: Action-server key hosting the executor.
        executor_id: The executor id to stop.
        host: Action-server host.
        port: Action-server port.
    """

    server_key: str
    executor_id: Optional[str]
    host: Optional[str] = None
    port: Optional[int] = None


@dataclass(frozen=True)
class BroadcastGlobalStatus:
    """Broadcast the current :class:`GlobalStatusModel` to subscribers.

    Ports the ``interrupt_q`` / ``globstat_q`` push at the end of
    ``Orch.update_status`` and the intent transitions. ``payload`` is the
    ``as_json()`` form of the model captured at command-emit time.

    Attributes:
        payload: Serialized global status snapshot.
    """

    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FinishExperiment:
    """Finalize the active experiment (collect finished actions, write meta).

    Ports ``Orch.finish_active_experiment``. The aggregation of dispatched
    actions / samples / files and the meta write are realised by ``app/``.

    Attributes:
        experiment_uuid: UUID of the experiment to finalize.
    """

    experiment_uuid: Optional[UUID] = None


@dataclass(frozen=True)
class FinishSequence:
    """Finalize the active sequence (write meta, close out the run).

    Ports ``Orch.finish_active_sequence``.

    Attributes:
        sequence_uuid: UUID of the sequence to finalize.
    """

    sequence_uuid: Optional[UUID] = None


@dataclass(frozen=True)
class MoveRunDir:
    """Relocate a finished run's output directory via the storage port.

    Ports the move-to-synced step the legacy orchestrator performed when a run
    completed (``RUNS_*`` relocation).

    Attributes:
        src: Source run-directory relpath.
        dst: Destination run-directory relpath.
    """

    src: str
    dst: str
