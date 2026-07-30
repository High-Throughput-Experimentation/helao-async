"""Pure dispatch decision policy — the hexagon domain copy (spec §4.2.2).

Ported verbatim from helao/core/servers/orch_dispatch.py:128-482 (CARDS P5
inversion) per Q6 rewrite-with-reference. Line references in docstrings point
at the legacy orch.py the CARDS code annotated; they are retained as the
behavioral provenance. The async DispatchRunner effect shell is NOT ported —
the P1b app layer drives this policy through the reducer in
helao.hexagon.domain.orchestration.

Changes vs the source module (allowed by the porting rule, nothing else):
1. imports come from helao.hexagon.domain.models,
2. LOGGER is stdlib logging.getLogger(__name__),
3. DispatchRunner and its imports are dropped.
"""

__all__ = [
    "DispatchSnapshot",
    "FinalizationSnapshot",
    "DispatchPolicy",
    "ExitLoop",
    "DriverHealthWait",
    "StopLoop",
    "LaunchAction",
    "FinishThenDispatchExperiment",
    "FinishThenDispatchSequence",
    "LogQueuesEmpty",
    "PauseLoop",
    "DrainForStop",
    "SkipClearActions",
    "EstopClearActions",
    "ProceedDispatch",
    "NoWaitProceed",
    "AwaitEndpointFree",
    "AwaitServerFree",
    "AwaitWaitEndpointFree",
    "AwaitPreviousActionDone",
    "WaitAllActions",
    "CloseOutExperiment",
    "CloseOutSequence",
    "SetLoopStopped",
    "ClearIntent",
    "ExportQueues",
    "should_close_out_experiment",
    "should_close_out_sequence",
    "should_set_stopped",
    "should_export",
]

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Optional

from helao.hexagon.domain.models import (
    ActionStartCondition,
    LoopIntent,
    LoopStatus,
    OrchStatus,
)

LOGGER = logging.getLogger(__name__)


# ===========================================================================
# 1. Snapshots (frozen)
# ===========================================================================


@dataclass(frozen=True)
class DispatchSnapshot:
    """Top-of-iteration snapshot for the outer dispatch ladder (no lock held)."""

    loop_state: LoopStatus  # orch.globalstatusmodel.loop_state (:1127/:1166)
    loop_intent: LoopIntent  # orch.globalstatusmodel.loop_intent (:1166)
    n_acts: int  # len(orch.action_dq) (:1127/:1171)
    n_exps: int  # len(orch.experiment_dq) (:1127/:1206)
    n_seqs: int  # len(orch.sequence_dq) (:1127/:1215)
    na_drivers: tuple[str, ...]  # unknown drivers in orch.status_summary (:1141-1143)
    step_thru_actions: bool  # orch.step_thru_actions (:1179)
    step_thru_experiments: bool  # orch.step_thru_experiments (:1188)
    step_thru_sequences: bool  # orch.step_thru_sequences (:1199)


@dataclass(frozen=True)
class FinalizationSnapshot:
    """Post-loop snapshot for the finalization plan (guards re-checked live)."""

    n_acts: int  # len(orch.action_dq) (:1235/:1241)
    n_exps: int  # len(orch.experiment_dq) (:1240)
    active_experiment_present: bool  # orch.active_experiment is not None (:1235)
    active_sequence_present: bool  # orch.active_sequence is not None (:1242)
    loop_state: LoopStatus  # orch.globalstatusmodel.loop_state (:1247, Q2)


# ===========================================================================
# 2. DispatchStep -- the closed union
# ===========================================================================

# --- 2.1 outer-ladder steps (DispatchPolicy.next_step / ladder_step) ---


@dataclass(frozen=True)
class ExitLoop:
    """While-cond false (:1127) -> break inner loop, run finalization."""

    reason: str


@dataclass(frozen=True)
class DriverHealthWait:
    """Unknown driver states (:1140-1164) -- NON-terminal; runs once then falls through."""

    na_drivers: tuple[str, ...]


@dataclass(frozen=True)
class StopLoop:
    """estop outer branch (:1166-1170) -> orch.stop_loop(); error_code stays unspecified (Q1)."""


@dataclass(frozen=True)
class LaunchAction:
    """action branch (:1171-1205) -> coordinator + history-poll + step-thru sub-decision."""


@dataclass(frozen=True)
class FinishThenDispatchExperiment:
    """experiment branch (:1206-1213) -> finish active exp then dispatch exp."""


@dataclass(frozen=True)
class FinishThenDispatchSequence:
    """sequence branch (:1215-1222) -> finish active seq then dispatch seq."""


@dataclass(frozen=True)
class LogQueuesEmpty:
    """else branch (:1223-1225) -> two logs; error_code stays unspecified (Q1)."""


# --- 2.2 post-action sub-decision (DispatchPolicy.evaluate_step_thru) ---


@dataclass(frozen=True)
class PauseLoop:
    """step-thru pause (:1179-1205) -> set stop message, warn, orch.stop()."""

    reason: str


# --- 2.3 pre-dispatch intent sub-decision (DispatchPolicy.pre_dispatch_intent_step) ---


@dataclass(frozen=True)
class DrainForStop:
    """loop_intent==stop (:813-824) -> drain running actions then stop the loop."""


@dataclass(frozen=True)
class SkipClearActions:
    """loop_intent==skip (:826-831) -> clear action_dq + intend_none."""


@dataclass(frozen=True)
class EstopClearActions:
    """loop_intent==estop (:832-837) -> clear action_dq + intend_none + loop_state=estopped."""


@dataclass(frozen=True)
class ProceedDispatch:
    """no pre-dispatch intent (:838-839) -> continue to popleft + dispatch."""


# --- 2.3b start-condition sub-decision (DispatchPolicy.start_condition_step) ---


@dataclass(frozen=True)
class NoWaitProceed:
    """no_wait (:848-849) -> log only, no wait."""


@dataclass(frozen=True)
class AwaitEndpointFree:
    """wait_for_endpoint (:851-861)."""

    log_msg: str
    predicate: Callable


@dataclass(frozen=True)
class AwaitServerFree:
    """wait_for_server (:862-872)."""

    log_msg: str
    predicate: Callable


@dataclass(frozen=True)
class AwaitWaitEndpointFree:
    """wait_for_orch (:873-883) -- uses A.orchestrator + endpoint "wait"."""

    log_msg: str
    predicate: Callable


@dataclass(frozen=True)
class AwaitPreviousActionDone:
    """wait_for_previous (:884-896) -- uses orch.last_action_uuid."""

    log_msg: str
    predicate: Callable


@dataclass(frozen=True)
class WaitAllActions:
    """wait_for_all (:897-898) AND unsupported fallback (:900-901) -> orch_wait_for_all_actions()."""


# --- 2.4 finalization steps (DispatchPolicy.finalization_plan) ---


@dataclass(frozen=True)
class CloseOutExperiment:
    """post-loop finish exp (:1234-1238); guard: not action_dq and active_experiment."""


@dataclass(frozen=True)
class CloseOutSequence:
    """post-loop finish seq (:1239-1245); guard: not exp_dq and not act_dq and active_sequence."""


@dataclass(frozen=True)
class SetLoopStopped:
    """post-loop (:1247-1248) -> loop_state=stopped unless estopped (Q2)."""


@dataclass(frozen=True)
class ClearIntent:
    """post-loop (:1249) -> intend_none()."""


@dataclass(frozen=True)
class ExportQueues:
    """post-loop (:1251-1261) -> export_queues(timestamp_pck=True) if any dq non-empty."""


# ===========================================================================
# 3. DispatchPolicy (pure)
# ===========================================================================


def should_close_out_experiment(
    n_acts: int, active_exp_present: bool, loop_state=None
) -> bool:
    """Guard for :class:`CloseOutExperiment` (:1234-1236).

    Under E-STOP the clean close-out is skipped -- estop_finish_active is the
    sole finalizer -- so the experiment is not double-finalized.
    """
    return (n_acts == 0) and active_exp_present and loop_state != OrchStatus.estopped


def should_close_out_sequence(
    n_exps: int, n_acts: int, active_seq_present: bool, loop_state=None
) -> bool:
    """Guard for :class:`CloseOutSequence` (:1239-1243).

    Skipped under E-STOP (estop_finish_active finalizes the sequence instead).
    """
    return (
        (n_exps == 0)
        and (n_acts == 0)
        and active_seq_present
        and loop_state != OrchStatus.estopped
    )


def should_set_stopped(loop_state) -> bool:
    """Guard for :class:`SetLoopStopped` (:1247, Q2 -- compares against OrchStatus.estopped)."""
    return loop_state != OrchStatus.estopped


def should_export(n_seqs: int, n_exps: int, n_acts: int) -> bool:
    """Guard for :class:`ExportQueues` (:1251)."""
    return any(x > 0 for x in (n_seqs, n_exps, n_acts))


class DispatchPolicy:
    """Pure dispatch decision policy: snapshot/enum in -> ``DispatchStep`` out.

    No ``orch`` reference, no ``await``, no I/O, no mutation. Every method is
    directly unit-testable against ``DispatchSnapshot`` literals.
    """

    # --- outer ladder ---

    def next_step(self, snap: DispatchSnapshot):
        """Top-of-iteration decision: while-cond -> driver-health -> ladder (exact precedence)."""
        # while-cond (:1127-1129)
        if not (
            snap.loop_state == LoopStatus.started
            and (snap.n_acts or snap.n_exps or snap.n_seqs)
        ):
            return ExitLoop(
                reason=(
                    "loop_state_not_started"
                    if snap.loop_state != LoopStatus.started
                    else "all_queues_empty"
                )
            )
        # driver-health (:1140) -- precedence #1 within the running body. Kept a
        # separate NON-terminal step from the ladder so the runner can run it
        # once and then fall through to the ladder (matches the non-`continue`
        # fall-through of orch.py:1140-1164). See module docstring.
        if snap.na_drivers:
            return DriverHealthWait(na_drivers=snap.na_drivers)
        return self.ladder_step(snap)

    def ladder_step(self, snap: DispatchSnapshot):
        """The estop/action/exp/seq/else ladder (:1166-1225), driver-health already consumed."""
        if (
            snap.loop_state == LoopStatus.estopped
            or snap.loop_intent == LoopIntent.estop
        ):  # :1166
            return StopLoop()
        if snap.n_acts:  # :1171
            return LaunchAction()
        if snap.n_exps:  # :1206
            return FinishThenDispatchExperiment()
        if snap.n_seqs:  # :1215
            return FinishThenDispatchSequence()
        return LogQueuesEmpty()  # :1223 else (dead-but-present)

    # --- post-action step-thru sub-decision (:1179-1205) ---

    def evaluate_step_thru(self, snap: DispatchSnapshot) -> Optional[PauseLoop]:
        """Select a :class:`PauseLoop` per the enabled step-thru flag, else ``None``."""
        if snap.n_acts and snap.step_thru_actions:  # :1179
            return PauseLoop(
                reason="Step-thru actions is enabled, use 'Start Orch' to dispatch next action."
            )
        if (not snap.n_acts) and snap.n_exps and snap.step_thru_experiments:  # :1185
            return PauseLoop(
                reason="Step-thru experiments is enabled, use 'Start Orch' to dispatch next experiment."
            )
        if (
            (not snap.n_acts)
            and (not snap.n_exps)
            and snap.n_seqs
            and snap.step_thru_sequences
        ):  # :1195
            return PauseLoop(
                reason="Step-thru sequences is enabled, use 'Start Orch' to dispatch next sequence."
            )
        return None

    # --- pre-dispatch intent sub-decision (:813-839) ---

    def pre_dispatch_intent_step(self, loop_intent):
        """Select the pre-dispatch intent step from the live ``loop_intent``."""
        if loop_intent == LoopIntent.stop:
            return DrainForStop()  # :813
        if loop_intent == LoopIntent.skip:
            return SkipClearActions()  # :826
        if loop_intent == LoopIntent.estop:
            return EstopClearActions()  # :832
        return ProceedDispatch()  # :838

    # --- start-condition sub-decision (:848-901) ---

    def start_condition_step(self, sc):
        """Select the start-condition step (log_msg + pure predicate) for the head action."""
        if sc == ActionStartCondition.no_wait:  # :848
            return NoWaitProceed()
        if sc == ActionStartCondition.wait_for_endpoint:  # :851
            return AwaitEndpointFree(
                log_msg="orch is waiting for endpoint to become available",
                predicate=lambda gsm, A, orch: gsm.endpoint_free(
                    action_server=A.action_server, endpoint_name=A.action_name
                ),
            )
        if sc == ActionStartCondition.wait_for_server:  # :862
            return AwaitServerFree(
                log_msg="orch is waiting for server to become available",
                predicate=lambda gsm, A, orch: gsm.server_free(
                    action_server=A.action_server
                ),
            )
        if sc == ActionStartCondition.wait_for_orch:  # :873
            return AwaitWaitEndpointFree(
                log_msg="orch is waiting for wait action to end",
                predicate=lambda gsm, A, orch: gsm.endpoint_free(
                    action_server=A.orchestrator, endpoint_name="wait"
                ),
            )
        if sc == ActionStartCondition.wait_for_previous:  # :884
            # Original loops `while previous_action_active`; generic runner loop
            # is `while not predicate`, so the predicate is the NEGATION.
            return AwaitPreviousActionDone(
                log_msg="orch is waiting for previous action to finish",
                predicate=lambda gsm, A, orch: orch.last_action_uuid
                not in gsm.active_dict.keys(),
            )
        if sc == ActionStartCondition.wait_for_all:  # :897
            return WaitAllActions()
        return WaitAllActions()  # :900-901 fallback

    # --- finalization (:1234-1261) ---

    def finalization_plan(self, fsnap: FinalizationSnapshot) -> list:
        """The fixed ordered post-loop plan; per-step guards are re-checked live by the runner."""
        return [
            CloseOutExperiment(),
            CloseOutSequence(),
            SetLoopStopped(),
            ClearIntent(),
            ExportQueues(),
        ]
