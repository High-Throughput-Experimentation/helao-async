"""Orchestration reducer FSM (spec §4.2.2, KEEP #2): pure
``step(state, event) -> (state, commands)``.

Encodes core-01's loop-state transition table T1-T13 and drives the ported
DispatchPolicy ladder for LoopIterate events. The P1b app layer owns the
single long-lived Event-parked dispatch loop that feeds LoopIterate events in
and executes the returned commands; this module never awaits, never touches a
queue object, never performs I/O.

THE THREE LIVE ESTOP RE-CHECKS (core-01 §8): a concurrent estop can land
between this reducer's decision and the runner's effect. Commands that legacy
guards re-check live carry ``requires_live_estop_recheck=True``:
- DispatchHeadAction        (in-lock re-check inside the dispatch lock)
- FinishThenDispatch*Cmd    (re-check at the top of the effect)
- CloseOut*Cmd              (finalization guard ``loop_state != estopped`` so
                             estop_finish_active stays the SOLE finalizer)
The P1b effect runner must re-read live state before executing them, or
serialize estop with the loop — and test both races either way (spec
§4.2.2); P1a asserts the guards exist.
"""

from dataclasses import dataclass, replace
from typing import Tuple, Union

from helao.hexagon.domain.dispatch_policy import (
    DispatchPolicy,
    DispatchSnapshot,
    DrainForStop,
    DriverHealthWait,
    EstopClearActions,
    ExitLoop,
    FinishThenDispatchExperiment,
    FinishThenDispatchSequence,
    LaunchAction,
    LogQueuesEmpty,
    ProceedDispatch,
    SkipClearActions,
    StopLoop,
    should_close_out_experiment,
    should_close_out_sequence,
    should_export,
    should_set_stopped,
)
from helao.hexagon.domain.models import LoopIntent, LoopStatus, OrchStatus

_POLICY = DispatchPolicy()


# ===========================================================================
# State
# ===========================================================================


@dataclass(frozen=True)
class OrchestrationState:
    loop_state: LoopStatus = LoopStatus.stopped
    loop_intent: LoopIntent = LoopIntent.none
    orch_state: OrchStatus = OrchStatus.idle
    n_seqs: int = 0
    n_exps: int = 0
    n_acts: int = 0
    active_experiment_present: bool = False
    active_sequence_present: bool = False
    na_drivers: Tuple[str, ...] = ()
    step_thru_actions: bool = False
    step_thru_experiments: bool = False
    step_thru_sequences: bool = False

    def snapshot(self) -> DispatchSnapshot:
        return DispatchSnapshot(
            loop_state=self.loop_state,
            loop_intent=self.loop_intent,
            n_acts=self.n_acts,
            n_exps=self.n_exps,
            n_seqs=self.n_seqs,
            na_drivers=self.na_drivers,
            step_thru_actions=self.step_thru_actions,
            step_thru_experiments=self.step_thru_experiments,
            step_thru_sequences=self.step_thru_sequences,
        )


# ===========================================================================
# Events
# ===========================================================================


@dataclass(frozen=True)
class StartRequested:
    """POST /start (T1/T2/T3)."""


@dataclass(frozen=True)
class StopRequested:
    """POST /stop -> intend_stop (drains via T5)."""


@dataclass(frozen=True)
class SkipRequested:
    """POST /skip_experiment -> intend_skip (T6)."""


@dataclass(frozen=True)
class EstopRequested:
    """POST /estop_orch (T9)."""

    reason: str = ""


@dataclass(frozen=True)
class ClearEstopRequested:
    """POST /clear_estop (T10)."""


@dataclass(frozen=True)
class ClearErrorRequested:
    """POST /clear_error (T11)."""


@dataclass(frozen=True)
class DispatchFailed:
    """Transport failure / None result (T12: pause + head-requeue, NOT estop)."""

    message: str


@dataclass(frozen=True)
class PlateGateFailed:
    """Plate verification gate (T12; sets loop_state=stopped inline)."""

    message: str


@dataclass(frozen=True)
class HeartbeatFailed:
    """active_action_monitor probe failure (T12 + alert). P2a: carries the
    dead server's active action uuids (stringified) so the reducer can order
    a PruneDeadActions — the pure-hexagon dead-peer exit (decision Q3)."""

    message: str
    dead_action_uuids: Tuple[str, ...] = ()


@dataclass(frozen=True)
class DriverHealthUnrecovered:
    """DriverHealthWait retries exhausted, still unknown (T12)."""

    na_drivers: Tuple[str, ...]


@dataclass(frozen=True)
class ActionResultErrored:
    """Dispatch result carried error_code != none — ESCALATES to estop (T9)."""

    reason: str


@dataclass(frozen=True)
class EstoppedUuidIngested:
    """Status fold found estopped uuids in finished (T9, guard: started)."""

    reason: str


@dataclass(frozen=True)
class ErroredUuidIngested:
    """Status fold found errored uuids (orch_state=error while started)."""


@dataclass(frozen=True)
class StatusChanged:
    """Generic ingestion outcome (orch_state busy/idle derivation)."""

    any_active: bool


@dataclass(frozen=True)
class UncaughtLoopException:
    """run() caught an exception (T13 -> estop)."""

    reason: str


@dataclass(frozen=True)
class LoopIterate:
    """Top-of-iteration tick from the app loop -> ladder decision."""


Event = Union[
    StartRequested,
    StopRequested,
    SkipRequested,
    EstopRequested,
    ClearEstopRequested,
    ClearErrorRequested,
    DispatchFailed,
    PlateGateFailed,
    HeartbeatFailed,
    DriverHealthUnrecovered,
    ActionResultErrored,
    EstoppedUuidIngested,
    ErroredUuidIngested,
    StatusChanged,
    UncaughtLoopException,
    LoopIterate,
]


# ===========================================================================
# Commands (executed by the P1b app-layer runner; NEVER by the domain)
# ===========================================================================


@dataclass(frozen=True)
class CreateDispatchLoopTask:
    """start_loop(): create dispatch_loop_task (T1)."""


@dataclass(frozen=True)
class RefuseStart:
    reason: str


@dataclass(frozen=True)
class DispatchHeadAction:
    """popleft + start-condition wait + locked dispatch + result fold.
    Live re-check #1 happens inside the dispatch lock."""

    requires_live_estop_recheck: bool = True


@dataclass(frozen=True)
class FinishThenDispatchExperimentCmd:
    """finish_active_experiment() then dispatch_experiment().
    Live re-check #2 at the top of the effect."""

    requires_live_estop_recheck: bool = True


@dataclass(frozen=True)
class FinishThenDispatchSequenceCmd:
    requires_live_estop_recheck: bool = True


@dataclass(frozen=True)
class RetryDriverHealth:
    """Re-read status_summary <=5 x 5 s; feed DriverHealthUnrecovered back on
    exhaustion; then FALL THROUGH to the ladder in the same iteration (no
    continue — re-asking next_step would livelock)."""

    na_drivers: Tuple[str, ...]


@dataclass(frozen=True)
class WaitAllActionsIdle:
    """DrainForStop: wait actions_idle before the loop parks (T5)."""


@dataclass(frozen=True)
class RequeueHeadAction:
    """action_dq.insert(0, A) — head re-insert of the popped action."""


@dataclass(frozen=True)
class ClearActionQueue:
    """action_dq.clear() — skip/estop intents clear ONLY actions (T6/T7)."""


@dataclass(frozen=True)
class SetStopMessage:
    message: str


@dataclass(frozen=True)
class AlertOperator:
    message: str


@dataclass(frozen=True)
class EstopFanout:
    """Fan a minimal estop Action (params={'switch': switch}) to every server
    in server_dict; servers finalize their own in-flight actions; NO
    fabricated placeholder artifacts (post-bd8b83ab semantics)."""

    switch: bool = False


@dataclass(frozen=True)
class ClearActiveRunId:
    """active_run_id = None."""


@dataclass(frozen=True)
class FinishActiveEstopped:
    """estop_finish_active(): exp then seq, [finished, estopped] terminal
    status, deferred child-dir-aware promotion. The SOLE finalizer under
    estop."""


@dataclass(frozen=True)
class CloseOutExperimentCmd:
    """finish_active_experiment() in finalization. Live re-check #3: the
    runner re-checks should_close_out_experiment against LIVE loop_state."""

    requires_live_estop_recheck: bool = True


@dataclass(frozen=True)
class CloseOutSequenceCmd:
    requires_live_estop_recheck: bool = True


@dataclass(frozen=True)
class ExportQueuesCmd:
    timestamped: bool = True


@dataclass(frozen=True)
class ClearEstoppedFromFinished:
    """globalstatusmodel.clear_in_finished(estopped) (T10)."""


@dataclass(frozen=True)
class ClearErroredFromFinished:
    """clear_in_finished(errored) (T11)."""


@dataclass(frozen=True)
class ReleaseServersEstop:
    """estop_actions(switch=False) on clear_estop (T10)."""


@dataclass(frozen=True)
class InterruptWake:
    message: str


@dataclass(frozen=True)
class PruneDeadActions:
    """Dead-peer exit (item-6, P2a): pop the uuids from active_dict (global
    AND per-endpoint, like /clear_actives), bucket them finished-terminal,
    register history — makes legacy orch_wait_for_all_actions's
    actions_idle() true WITHOUT editing it (decision Q3)."""

    action_uuids: Tuple[str, ...]


Command = Union[
    CreateDispatchLoopTask,
    RefuseStart,
    DispatchHeadAction,
    FinishThenDispatchExperimentCmd,
    FinishThenDispatchSequenceCmd,
    RetryDriverHealth,
    WaitAllActionsIdle,
    RequeueHeadAction,
    ClearActionQueue,
    SetStopMessage,
    AlertOperator,
    EstopFanout,
    ClearActiveRunId,
    FinishActiveEstopped,
    CloseOutExperimentCmd,
    CloseOutSequenceCmd,
    ExportQueuesCmd,
    ClearEstoppedFromFinished,
    ClearErroredFromFinished,
    ReleaseServersEstop,
    InterruptWake,
    PruneDeadActions,
]

StepResult = Tuple[OrchestrationState, Tuple[Command, ...]]


# ===========================================================================
# Reducer
# ===========================================================================


def _estop_transition(state: OrchestrationState, reason: str) -> StepResult:
    """T9/T13: the estop_loop sequence (core-01 §7), exact command order.

    Idempotent re-entry guard (DD-3): ``ActionResultErrored`` and
    ``UncaughtLoopException`` escalate to estop unconditionally (no
    started-only guard, unlike ``EstopRequested``/``EstoppedUuidIngested`` —
    both must stay reachable so an escalation landing mid-finalization can
    still be observed). A second escalation racing in while already estopped
    (e.g. a stale in-flight dispatch effect that crashes against
    post-finalize state) must therefore no-op here instead of re-running the
    cascade: ``FinishActiveEstopped`` is the SOLE finalizer and must never
    fire twice."""
    if state.loop_state == LoopStatus.estopped:
        return state, ()
    new = replace(
        state,
        loop_state=LoopStatus.estopped,
        loop_intent=LoopIntent.none,
        orch_state=OrchStatus.estopped,
    )
    return new, (
        ClearActiveRunId(),
        EstopFanout(switch=False),
        FinishActiveEstopped(),
        SetStopMessage(message=reason),
        AlertOperator(message=reason),
    )


def _finalization(state: OrchestrationState) -> StepResult:
    """T4 / ExitLoop: CloseOutExperiment?, CloseOutSequence?, SetLoopStopped
    (skipped if estopped, Q2), ClearIntent, ExportQueues?."""
    cmds: list = []
    if should_close_out_experiment(
        state.n_acts, state.active_experiment_present, state.loop_state
    ):
        cmds.append(CloseOutExperimentCmd())
    if should_close_out_sequence(
        state.n_exps,
        state.n_acts,
        state.active_sequence_present,
        state.loop_state,
    ):
        cmds.append(CloseOutSequenceCmd())
    new_loop_state = (
        LoopStatus.stopped if should_set_stopped(state.loop_state) else state.loop_state
    )
    if should_export(state.n_seqs, state.n_exps, state.n_acts):
        cmds.append(ExportQueuesCmd(timestamped=True))
    new = replace(state, loop_state=new_loop_state, loop_intent=LoopIntent.none)
    return new, tuple(cmds)


def _iterate(state: OrchestrationState) -> StepResult:
    ladder = _POLICY.next_step(state.snapshot())
    if isinstance(ladder, ExitLoop):
        return _finalization(state)
    if isinstance(ladder, DriverHealthWait):
        return state, (RetryDriverHealth(na_drivers=ladder.na_drivers),)
    if isinstance(ladder, StopLoop):
        # stop_loop() == intend_stop(); drains via T5 on the next iteration
        return replace(state, loop_intent=LoopIntent.stop), ()
    if isinstance(ladder, LaunchAction):
        intent = _POLICY.pre_dispatch_intent_step(state.loop_intent)
        if isinstance(intent, DrainForStop):  # T5
            new = replace(
                state,
                loop_state=LoopStatus.stopped,
                loop_intent=LoopIntent.none,
            )
            return new, (WaitAllActionsIdle(),)
        if isinstance(intent, SkipClearActions):  # T6
            return (
                replace(state, loop_intent=LoopIntent.none),
                (ClearActionQueue(),),
            )
        if isinstance(intent, EstopClearActions):  # T7
            new = replace(
                state,
                loop_state=LoopStatus.estopped,
                loop_intent=LoopIntent.none,
            )
            return new, (ClearActionQueue(),)
        assert isinstance(intent, ProceedDispatch)
        return state, (DispatchHeadAction(),)
    if isinstance(ladder, FinishThenDispatchExperiment):
        return state, (FinishThenDispatchExperimentCmd(),)
    if isinstance(ladder, FinishThenDispatchSequence):
        return state, (FinishThenDispatchSequenceCmd(),)
    assert isinstance(ladder, LogQueuesEmpty)
    return state, ()


def step(state: OrchestrationState, event: Event) -> StepResult:
    """The reducer. Pure: same (state, event) in, same (state, commands) out."""
    if isinstance(event, StartRequested):
        if state.loop_state == LoopStatus.estopped:  # T3
            return state, (RefuseStart(reason="clear E-STOP first"),)
        if state.loop_state == LoopStatus.started:
            return state, ()
        has_work = (
            state.n_acts
            or state.n_exps
            or state.n_seqs
            or state.active_sequence_present
        )
        if not has_work:  # T2
            return state, (RefuseStart(reason="experiment list is empty"),)
        return (  # T1
            replace(state, loop_state=LoopStatus.started),
            (CreateDispatchLoopTask(),),
        )

    if isinstance(event, StopRequested):
        return replace(state, loop_intent=LoopIntent.stop), ()

    if isinstance(event, SkipRequested):
        return replace(state, loop_intent=LoopIntent.skip), ()

    if isinstance(event, EstopRequested):  # T9 (API source)
        if state.loop_state != LoopStatus.started:
            return state, ()
        return _estop_transition(state, event.reason)

    if isinstance(event, ActionResultErrored):  # T9 (result escalation)
        return _estop_transition(state, event.reason)

    if isinstance(event, UncaughtLoopException):  # T13
        return _estop_transition(state, event.reason)

    if isinstance(event, EstoppedUuidIngested):  # T9 (status source)
        if state.loop_state != LoopStatus.started:
            return state, ()
        return _estop_transition(state, event.reason)

    if isinstance(event, ClearEstopRequested):  # T10
        if state.loop_state != LoopStatus.estopped:
            return state, ()
        new = replace(
            state,
            loop_state=LoopStatus.stopped,
            orch_state=OrchStatus.idle,
        )
        return new, (
            ClearEstoppedFromFinished(),
            ReleaseServersEstop(),
            InterruptWake(message="cleared_estop"),
        )

    if isinstance(event, ClearErrorRequested):  # T11
        return state, (
            ClearErroredFromFinished(),
            InterruptWake(message="cleared_errored"),
        )

    if isinstance(event, DispatchFailed):  # T12
        return (
            replace(state, loop_intent=LoopIntent.stop),
            (SetStopMessage(message=event.message), RequeueHeadAction()),
        )

    if isinstance(event, PlateGateFailed):  # T12 (inline stopped)
        new = replace(state, loop_state=LoopStatus.stopped, loop_intent=LoopIntent.none)
        return new, (SetStopMessage(message=event.message),)

    if isinstance(event, HeartbeatFailed):  # T12 (+ P2a dead-peer prune)
        cmds: Tuple[Command, ...] = (
            SetStopMessage(message=event.message),
            AlertOperator(message=event.message),
        )
        if event.dead_action_uuids:
            cmds = cmds + (PruneDeadActions(action_uuids=event.dead_action_uuids),)
        return replace(state, loop_intent=LoopIntent.stop), cmds

    if isinstance(event, DriverHealthUnrecovered):  # T12
        msg = f"unknown driver states: {', '.join(event.na_drivers)}"
        return (
            replace(state, loop_intent=LoopIntent.stop),
            (SetStopMessage(message=msg),),
        )

    if isinstance(event, ErroredUuidIngested):
        if state.loop_state == LoopStatus.started:
            return replace(state, orch_state=OrchStatus.error), ()
        return state, ()

    if isinstance(event, StatusChanged):
        new_orch = OrchStatus.busy if event.any_active else OrchStatus.idle
        return replace(state, orch_state=new_orch), ()

    assert isinstance(event, LoopIterate)
    return _iterate(state)


__all__ = [
    "OrchestrationState",
    "StartRequested",
    "StopRequested",
    "SkipRequested",
    "EstopRequested",
    "ClearEstopRequested",
    "ClearErrorRequested",
    "DispatchFailed",
    "PlateGateFailed",
    "HeartbeatFailed",
    "DriverHealthUnrecovered",
    "ActionResultErrored",
    "EstoppedUuidIngested",
    "ErroredUuidIngested",
    "StatusChanged",
    "UncaughtLoopException",
    "LoopIterate",
    "Event",
    "CreateDispatchLoopTask",
    "RefuseStart",
    "DispatchHeadAction",
    "FinishThenDispatchExperimentCmd",
    "FinishThenDispatchSequenceCmd",
    "RetryDriverHealth",
    "WaitAllActionsIdle",
    "RequeueHeadAction",
    "ClearActionQueue",
    "SetStopMessage",
    "AlertOperator",
    "EstopFanout",
    "ClearActiveRunId",
    "FinishActiveEstopped",
    "CloseOutExperimentCmd",
    "CloseOutSequenceCmd",
    "ExportQueuesCmd",
    "ClearEstoppedFromFinished",
    "ClearErroredFromFinished",
    "ReleaseServersEstop",
    "InterruptWake",
    "PruneDeadActions",
    "Command",
    "StepResult",
    "step",
]
