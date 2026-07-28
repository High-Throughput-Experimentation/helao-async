"""Dispatch FSM inversion -- ``DispatchPolicy`` (pure) + ``DispatchRunner``
(async effect shell) extracted from ``Orch`` (CARDS P5, Stage S8).

This module inverts the orchestrator's imperative dispatch loop
(``Orch.dispatch_loop_task`` and the ``loop_task_dispatch_{sequence,
experiment,action}`` coordinators) into a *pure decision policy* and an
*async effect runner*, per the frozen S8 design spec:

* ``DispatchSnapshot`` / ``FinalizationSnapshot`` -- frozen dataclasses that
  record the exact live reads the outer ladder / post-loop finalization made.
* ``DispatchStep`` -- a closed union of frozen dataclasses; every branch of the
  original ``dispatch_loop_task`` while-body, its post-loop finalization, and
  the two pure sub-decisions inside the action coordinator map to exactly one
  step.
* ``DispatchPolicy`` -- pure: no ``orch`` reference, no ``await``, no I/O, no
  mutation. Given a snapshot/enum it returns the step to run. Directly
  unit-testable (``unit_test_orch_dispatch_policy``).
* ``DispatchRunner`` -- async shell holding ONLY ``self.orch``; owns the loop
  task, the ``try/except`` wrapper, the post-loop finalization, and every
  *effect* (all awaits, the single ``aiolock`` critical section, all log lines,
  all mutations). The S7 action/experiment/sequence coordinator helpers migrate
  in here verbatim (``self.`` -> ``self.orch.``).

Per the P5 collaborator discipline (:doc:`CARDS_REFACTOR_P5.md` sec 3.1 rule 3):
``DispatchRunner`` caches no shared mutable state -- it holds only the ``orch``
back-reference and reads/writes ``globalstatusmodel``/``action_dq``/
``experiment_dq``/``sequence_dq``/``active_*``/``last_*``/``status_summary``/
``step_thru_*``/``global_params``/... through ``orch`` at call time, so a
reassignment made between construction and a call (e.g. ``import_queues``
reassigning the deques) is always observed. ``loop_state``/``loop_intent`` stay
``Orch`` attributes (reach-ins + pickle histories). Behavior is byte-identical
to the original inline loop.

Lock/queue ownership (rule 4) -- full map (also duplicated verbatim in
``orch_status_sync.py``, the other lock owner):

- ``aiolock`` -- acquired by ``StatusIngester`` (status ingestion) and
  ``DispatchRunner`` (the dispatch critical section).
- ``interrupt_q`` -- written by ``StatusIngester`` / ``ServerMonitor`` /
  e-stop; read by ``DispatchRunner``.
- ``globstat_q`` -- written by ``StatusIngester``; drained by its own
  broadcast task.

Concretely here: ``DispatchRunner`` acquires ``aiolock`` for the single
dispatch critical section noted above (:944-1058 in the original inline
loop); it reads ``interrupt_q`` via ``Orch.wait_for_interrupt`` (called from
the dispatch loop, method body remains on ``Orch``, cluster B); it never
touches ``globstat_q`` directly -- that queue is owned end-to-end by
``StatusIngester`` in ``orch_status_sync.py``.

CIRCULAR-IMPORT / MONKEYPATCH NOTE: this module must NOT import
``helao.core.servers.orch`` at module top (import-cycle rule). The two
module-globals the dispatch golden-master harness rebinds
(``helao.core.servers.orch.async_action_dispatcher`` and
``helao.core.servers.orch.PLATE_API``) are imported lazily inside the effect
methods that use them, so the external patch points keep working exactly as
they did before extraction (the same technique ``orch_lifecycle.py`` uses for
``move_dir``).

BEHAVIOR NOTE (driver-health fall-through): the design's inner-loop sketch
re-asked ``next_step`` after a ``DriverHealthWait`` (``continue``). That would
hang forever whenever the unknown-driver set never clears (``next_step`` checks
driver-health with higher precedence than the ladder, so it would keep
re-entering the retry+stop block). The original ``orch.py:1140-1164`` runs the
driver-health block once and then *falls through* to the ladder in the same
iteration (no ``continue``). To preserve that original behavior faithfully, the
policy exposes ``next_step`` (while-cond -> driver-health -> ladder, so the
"enter driver-health" decision stays unit-testable via N3/N4) and a separate
``ladder_step`` (estop/action/exp/seq/else only). The runner runs
``DriverHealthWait`` at most once per outer iteration, re-reads live state, then
asks ``ladder_step`` -- exactly matching the non-``continue`` fall-through.
"""

__all__ = [
    "DispatchSnapshot",
    "FinalizationSnapshot",
    "DispatchPolicy",
    "DispatchRunner",
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
]

import asyncio
import inspect
import traceback
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple
from uuid import UUID

from helao.helpers import helao_logging as logging
from helao.helpers.time_utils import gen_uuid
from helao.helpers.zdeque import zdeque
from helao.helpers.premodels import Action, Experiment
from helao.core.models.action_start_condition import ActionStartCondition
from helao.core.models.hlostatus import HloStatus
from helao.core.models.orchstatus import OrchStatus, LoopStatus, LoopIntent
from helao.core.error import ErrorCodes
from helao.core.servers.orch_global_params import (
    apply_from_globals,
    collect_to_globals,
)

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


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
    na_drivers: Tuple[str, ...]  # unknown drivers in orch.status_summary (:1141-1143)
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

    na_drivers: Tuple[str, ...]


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

    def finalization_plan(self, fsnap: FinalizationSnapshot) -> List:
        """The fixed ordered post-loop plan; per-step guards are re-checked live by the runner."""
        return [
            CloseOutExperiment(),
            CloseOutSequence(),
            SetLoopStopped(),
            ClearIntent(),
            ExportQueues(),
        ]


# ===========================================================================
# 4. DispatchRunner (async effect shell)
# ===========================================================================


class DispatchRunner:
    """Async shell that runs the dispatch FSM: owns the loop task + all effects.

    Holds only the ``orch`` back-reference (never a cached attribute), per the
    call-time state resolution rule -- see module docstring. ``self.policy`` is
    a stateless pure :class:`DispatchPolicy`.
    """

    def __init__(self, orch):
        self.orch = orch
        self.policy = DispatchPolicy()

    # ----- snapshots -----

    def _snapshot(self) -> DispatchSnapshot:
        orch = self.orch
        return DispatchSnapshot(
            loop_state=orch.globalstatusmodel.loop_state,
            loop_intent=orch.globalstatusmodel.loop_intent,
            n_acts=len(orch.action_dq),
            n_exps=len(orch.experiment_dq),
            n_seqs=len(orch.sequence_dq),
            na_drivers=tuple(
                k for k, (_, v) in orch.status_summary.items() if v == "unknown"
            ),
            step_thru_actions=orch.step_thru_actions,
            step_thru_experiments=orch.step_thru_experiments,
            step_thru_sequences=orch.step_thru_sequences,
        )

    def _finalization_snapshot(self) -> FinalizationSnapshot:
        orch = self.orch
        return FinalizationSnapshot(
            n_acts=len(orch.action_dq),
            n_exps=len(orch.experiment_dq),
            active_experiment_present=orch.active_experiment is not None,
            active_sequence_present=orch.active_sequence is not None,
            loop_state=orch.globalstatusmodel.loop_state,
        )

    # ----- 4.1 run() -- the wrapper (owns try/except, post-loop, return bool) -----

    async def run(self) -> bool:
        """Drive the main orchestrator loop until the queues are exhausted or it is stopped.

        Returns ``True`` on a clean exit and ``False`` on a raised exception
        (after triggering an E-STOP). Mirrors ``orch.py:1116-1273``.
        """
        orch = self.orch
        LOGGER.info("--- started operator orch ---")  # :1116
        LOGGER.info(
            f"current orch status: {orch.globalstatusmodel.orch_state}"
        )  # :1117
        orch.globalstatusmodel.loop_state = LoopStatus.started  # :1124 (before try)
        try:
            await self._loop()  # inner while
            await self._finalize()  # post-loop (:1234-1261)
            return True  # :1263
        # except asyncio.CancelledError:   -- stays commented out (:1265-1267)
        except Exception:  # :1269
            LOGGER.error("serious orch exception occurred")
            LOGGER.error("ERROR: ", exc_info=True)
            await orch.estop_loop()
            return False  # :1273

    # ----- 4.2 _loop() -- the inverted while -----

    async def _loop(self) -> None:
        orch = self.orch
        while True:
            snap = self._snapshot()
            step = self.policy.next_step(snap)
            if isinstance(step, ExitLoop):
                return  # while-cond false -> :1231
            error_code = ErrorCodes.unspecified  # :1130 per-iteration default
            self._log_deques()  # :1131-1139
            if isinstance(step, DriverHealthWait):
                # driver-health runs once then FALLS THROUGH to the ladder in
                # the SAME iteration (orch.py:1140-1164 has no `continue`).
                await self._exec_driver_health(step)
                snap = self._snapshot()  # re-read post-stop() live state
                step = self.policy.ladder_step(snap)
            error_code = await self._execute(step, error_code)
            if error_code is not ErrorCodes.none:  # :1227-1229
                LOGGER.error(f"stopping orch with error code: {error_code}")
                await orch.intend_stop()

    def _log_deques(self) -> None:
        orch = self.orch
        LOGGER.info(
            f"current content of action_dq: {[orch.action_dq[i] for i in range(min(len(orch.action_dq), 5))]}... ({len(orch.action_dq)})"
        )
        LOGGER.info(
            f"current content of experiment_dq: {[orch.experiment_dq[i] for i in range(min(len(orch.experiment_dq), 5))]}... ({len(orch.experiment_dq)})"
        )
        LOGGER.info(
            f"current content of sequence_dq: {[orch.sequence_dq[i] for i in range(min(len(orch.sequence_dq), 5))]}... ({len(orch.sequence_dq)})"
        )

    async def _exec_driver_health(self, step: DriverHealthWait) -> None:
        """Driver-health retry loop then conditional stop (:1144-1164), verbatim."""
        orch = self.orch
        na_drivers = list(step.na_drivers)
        na_driver_retries = 0
        while na_driver_retries < 5 and na_drivers:
            LOGGER.info(
                f"unknown driver states: {', '.join(na_drivers)}, retrying in 5 seconds"
            )
            await asyncio.sleep(5)
            na_drivers = [
                k for k, (_, v) in orch.status_summary.items() if v == "unknown"
            ]
            na_driver_retries += 1
        if na_drivers:
            orch.current_stop_message = (
                f"unknown driver states: {', '.join(na_drivers)}"
            )
            LOGGER.warning((f"unknown driver states: {', '.join(na_drivers)}"))
            await orch.stop()

    # ----- 4.3 _execute() -- outer-ladder effects -----

    async def _execute(self, step, error_code):
        """Run the effect for one terminal outer-ladder step; return the resulting error_code."""
        orch = self.orch
        if isinstance(step, StopLoop):  # :1166-1170
            await orch.stop_loop()
            return error_code  # unchanged unspecified (Q1)
        if isinstance(step, LaunchAction):  # :1171-1205
            LOGGER.info("!!!checking conditions for next action")
            error_code = await orch.loop_task_dispatch_action()
            while orch.last_dispatched_action_uuid not in orch.action_history.keys():
                await asyncio.sleep(0.2)  # :1174-1178 history-poll
            pause = self.policy.evaluate_step_thru(self._snapshot())
            if pause is not None:
                await self._exec_pause(pause)
            return error_code
        if isinstance(step, FinishThenDispatchExperiment):  # :1206-1213
            # The step was chosen from a snapshot; an EXTERNAL estop (e.g. the
            # status ingester's estop_loop) can flip loop_state and run
            # estop_finish_active concurrently between that decision and here.
            # Re-read live state and bail without the clean finish so
            # estop_finish_active stays the sole finalizer -- else both paths
            # finalize the same experiment (duplicate 'finished' + lost
            # 'estopped'). Mirrors should_close_out_experiment and the in-lock
            # estop recheck at :846.
            if orch.globalstatusmodel.loop_state == LoopStatus.estopped:
                LOGGER.info(
                    "orchestrator estopped, not finishing/dispatching experiment"
                )
                return ErrorCodes.estop
            LOGGER.info(
                "!!!waiting for all actions to finish before dispatching next experiment"
            )
            LOGGER.info("finishing last experiment")
            await orch.finish_active_experiment()
            LOGGER.info("!!!dispatching next experiment")
            return await orch.loop_task_dispatch_experiment()
        if isinstance(step, FinishThenDispatchSequence):  # :1215-1222
            # Same external-estop race guard as FinishThenDispatchExperiment
            # above -- skip the clean sequence close-out under estop.
            if orch.globalstatusmodel.loop_state == LoopStatus.estopped:
                LOGGER.info("orchestrator estopped, not finishing/dispatching sequence")
                return ErrorCodes.estop
            LOGGER.info(
                "!!!waiting for all actions to finish before dispatching next sequence"
            )
            LOGGER.info("finishing last sequence")
            await orch.finish_active_sequence()
            LOGGER.info("!!!dispatching next sequence")
            return await orch.loop_task_dispatch_sequence()
        if isinstance(step, LogQueuesEmpty):  # :1223-1225
            LOGGER.info("all queues are empty")
            LOGGER.info("--- stopping operator orch ---")
            return error_code  # unchanged unspecified (Q1)
        raise AssertionError(f"unhandled DispatchStep: {step!r}")

    async def _exec_pause(self, step: PauseLoop) -> None:
        """Step-thru pause effect (:1180-1205): set stop message, warn, stop()."""
        orch = self.orch
        orch.current_stop_message = step.reason
        LOGGER.warning(step.reason)
        await orch.stop()

    # ----- 4.4 _finalize() -- post-loop -----

    async def _finalize(self) -> None:
        for step in self.policy.finalization_plan(self._finalization_snapshot()):
            await self._execute_finalization(step)

    async def _execute_finalization(self, step) -> None:
        """Run one finalization step with its guard re-checked against LIVE state."""
        orch = self.orch
        if isinstance(step, CloseOutExperiment):  # :1234-1238
            # Guard delegated to the pure policy helper so the decision-table unit
            # test is authoritative for runtime (no helper/runtime drift). The
            # estop branch skips the clean close-out so estop_finish_active is the
            # sole finalizer (else both paths finalize -> duplicate 'finished' +
            # lost 'estopped').
            if should_close_out_experiment(
                len(orch.action_dq),
                orch.active_experiment is not None,
                orch.globalstatusmodel.loop_state,
            ):
                LOGGER.info("finishing final experiment")
                await orch.finish_active_experiment()
        elif isinstance(step, CloseOutSequence):  # :1239-1245
            if should_close_out_sequence(
                len(orch.experiment_dq),
                len(orch.action_dq),
                orch.active_sequence is not None,
                orch.globalstatusmodel.loop_state,
            ):
                LOGGER.info("finishing final sequence")
                await orch.finish_active_sequence()
        elif isinstance(step, SetLoopStopped):  # :1247-1248 (Q2)
            if orch.globalstatusmodel.loop_state != OrchStatus.estopped:
                orch.globalstatusmodel.loop_state = LoopStatus.stopped
        elif isinstance(step, ClearIntent):  # :1249
            await orch.intend_none()
        elif isinstance(step, ExportQueues):  # :1251-1261
            if any(
                [
                    len(x) > 0
                    for x in (
                        orch.sequence_dq,
                        orch.experiment_dq,
                        orch.action_dq,
                    )
                ]
            ):
                orch.export_queues(timestamp_pck=True)
        else:
            raise AssertionError(f"unhandled finalization step: {step!r}")

    # =======================================================================
    # 4.3b action coordinator -- migrated S7 helpers (self.->self.orch.),
    # with the two pure sub-decisions routed through the policy.
    # =======================================================================

    async def _launch_action(self) -> ErrorCodes:
        """Dispatch the next action honouring loop intent + start condition (:765-805)."""
        orch = self.orch
        # check again if action_dq is empty (:778-781)
        if not orch.action_dq:
            LOGGER.info("action_dq is empty, cannot dispatch actions")
            await orch.intend_none()
            return ErrorCodes.none

        # pre-dispatch loop-intent sub-decision (:784, decided by policy) (:807-839)
        intent_step = self.policy.pre_dispatch_intent_step(
            orch.globalstatusmodel.loop_intent
        )
        if not isinstance(intent_step, ProceedDispatch):
            await self._exec_pre_dispatch_intent(intent_step)
            return ErrorCodes.none  # :784-785 short-circuit

        A = orch.action_dq.popleft()  # :789

        rc = await self._wait_for_start_condition(A)  # :791-793
        if rc is not None:
            return rc

        self._stage_action_for_dispatch(A)  # :795

        rc, result_actiondict = await self._dispatch_action_locked(A)  # :797-799
        if rc is not None:
            return rc

        rc = await self._record_dispatch_result(A, result_actiondict)  # :801-803
        if rc is not None:
            return rc

        return ErrorCodes.none  # :805

    async def _exec_pre_dispatch_intent(self, step) -> None:
        """Run the effect for the pre-dispatch loop-intent step (:813-837), verbatim bodies."""
        orch = self.orch
        if isinstance(step, DrainForStop):  # :813-824
            LOGGER.info("stopping orchestrator")
            # monitor status of running action_dq, then end loop
            while orch.globalstatusmodel.loop_state != LoopStatus.stopped:
                # wait for all orch actions to finish first
                await orch.orch_wait_for_all_actions()
                if orch.globalstatusmodel.orch_state == OrchStatus.idle:
                    await orch.intend_none()
                    LOGGER.info("got stop")
                    orch.globalstatusmodel.loop_state = LoopStatus.stopped
                    break
        elif isinstance(step, SkipClearActions):  # :826-831
            # clear action queue, forcing next experiment
            orch.action_dq.clear()
            await orch.intend_none()
            LOGGER.info("skipping to next experiment")
        elif isinstance(step, EstopClearActions):  # :832-837
            orch.action_dq.clear()
            await orch.intend_none()
            LOGGER.info("estopping")
            orch.globalstatusmodel.loop_state = LoopStatus.estopped
        else:
            raise AssertionError(f"unhandled pre-dispatch intent step: {step!r}")

    async def _wait_for_start_condition(self, A) -> Optional[ErrorCodes]:
        """Wait per the head action's ``ActionStartCondition`` (:841-903).

        The policy selects WHICH condition (and its pure predicate/log); the
        runner owns the ``wait_for_interrupt`` loop. Returns ``ErrorCodes.none``
        if a wait loop is interrupted (early exit), ``None`` otherwise.
        """
        orch = self.orch
        # see async_action_dispatcher for unpacking
        step = self.policy.start_condition_step(A.start_condition)
        if isinstance(step, NoWaitProceed):
            LOGGER.info("orch is dispatching an unconditional action")  # :849
            return None
        if isinstance(step, WaitAllActions):
            # wait_for_all (:897-898) AND unsupported fallback (:900-901): no
            # extra log line, just wait for all actions.
            await orch.orch_wait_for_all_actions()
            return None
        # the four Await* conditions: log once, then loop while not satisfied
        LOGGER.info(step.log_msg)  # :852/:863/:874/:885
        predicate = step.predicate
        while not predicate(orch.globalstatusmodel, A, orch):
            if not await orch.wait_for_interrupt():
                return ErrorCodes.none  # :858/:869/:880/:892
        return None

    def _stage_action_for_dispatch(self, A) -> None:
        """Fold in globals, stamp run-id/submit-order, and init the action (:905-942), verbatim."""
        orch = self.orch
        # LOGGER.info("copying global vars to action")
        # copy requested global param to action params
        apply_from_globals(
            A.action_params,
            A.from_global_act_params,
            orch.global_params,
            logger_ctx="action",
        )

        # attach run_id
        if orch.active_run_id is not None:
            A.run_id = orch.active_run_id

        LOGGER.info(
            f"dispatching action {A.action_name} on server {A.action_server.server_name}"
        )
        # keep running counter of dispatched actions
        A.orch_submit_order = orch.globalstatusmodel.counter_dispatched_actions[
            orch.active_experiment.experiment_uuid
        ]
        orch.globalstatusmodel.counter_dispatched_actions[
            orch.active_experiment.experiment_uuid
        ] += 1

        A.init_act(time_offset=orch.ntp_offset)

    async def _dispatch_action_locked(
        self, A
    ) -> Tuple[Optional[ErrorCodes], Optional[dict]]:
        """Run the ``aiolock`` dispatch critical section intact (:944-1058), verbatim.

        The A12 in-lock estop recheck (:956-962) MUST stay a LIVE read inside
        the ``aiolock`` critical section (never lifted into a pre-lock
        snapshot): a concurrent estop can flip loop_intent/loop_state while the
        runner blocks on the lock.
        """
        orch = self.orch
        from helao.core.servers.orch import async_action_dispatcher

        result_actiondict = None
        async with orch.aiolock:
            try:
                if (
                    orch.globalstatusmodel.loop_intent == LoopIntent.estop
                    or orch.globalstatusmodel.loop_state == LoopStatus.estopped
                ):
                    LOGGER.info("orchestrator estopped, not dispatching action")
                    error_code = ErrorCodes.estop
                else:
                    result_actiondict, error_code = await async_action_dispatcher(
                        orch.world_cfg, A
                    )
            except Exception as e:
                LOGGER.info(f"Error while dispatching action {A.action_name}: {e}")
                error_code = ErrorCodes.http

            for cond, stop_message in [
                (
                    error_code != ErrorCodes.none,
                    f"Dispatching {A.action_name} did not return status 200. Pausing orch.",
                ),
                (
                    result_actiondict is None,
                    f"Dispatching {A.action_name} returned None object. Pausing orch.",
                ),
            ]:
                if cond:
                    orch.current_stop_message = stop_message
                    LOGGER.warning(stop_message)
                    await orch.stop()
                    LOGGER.info(f"Re-queuing {A.action_name}")
                    orch.action_dq.insert(0, A)
                    return ErrorCodes.none, None

            result_uuid = result_actiondict["action_uuid"]
            orch.last_action_uuid = result_uuid
            orch.track_action_uuid(UUID(result_uuid))
            LOGGER.info(f"Action {A.action_name} dispatched with uuid: {result_uuid}")
            orch.put_lbuf_nowait(
                {
                    result_uuid: {
                        "action_name": A.action_name,
                        "status": HloStatus.active.value,
                    }
                }
            )

            if not A.nonblocking:
                # orch gets back an active action dict, we can self-register the dispatched action in global status
                resmod = Action.model_validate(result_actiondict)
                srvname = resmod.action_server.server_name
                actname = resmod.action_name
                resuuid = resmod.action_uuid
                actstats = resmod.action_status
                srvkeys = orch.globalstatusmodel.server_dict.keys()
                srvkey = [k for k in srvkeys if k[0] == srvname][0]
                if HloStatus.active in actstats:
                    orch.globalstatusmodel.active_dict[resuuid] = resmod
                    orch.globalstatusmodel.server_dict[srvkey].endpoints[
                        actname
                    ].active_dict[resuuid] = resmod
                else:  # orch got back a nonactive result
                    for actstat in actstats:
                        try:
                            if resuuid in orch.globalstatusmodel.nonactive_dict.get(
                                actstat, {}
                            ):
                                break  # already in nonactive_dict

                            # need to populate nonactive and endpoint statuses
                            current_nonactive_status = (
                                orch.globalstatusmodel.nonactive_dict.get(actstat, {})
                            )
                            current_nonactive_status.update({resuuid: resmod})
                            orch.globalstatusmodel.nonactive_dict[actstat] = (
                                current_nonactive_status
                            )

                            current_endpoint_status = (
                                orch.globalstatusmodel.server_dict[srvkey]
                                .endpoints[actname]
                                .nonactive_dict.get(actstat, {})
                            )
                            current_endpoint_status.update({resuuid: resmod})
                            orch.globalstatusmodel.server_dict[srvkey].endpoints[
                                actname
                            ].nonactive_dict[actstat] = current_endpoint_status
                        except Exception:
                            LOGGER.info(
                                f"{actstat} not found in globalstatus.nonactive_dict",
                                exc_info=True,
                            )

        return None, result_actiondict

    async def _record_dispatch_result(
        self, A, result_actiondict
    ) -> Optional[ErrorCodes]:
        """Register the dispatch result and fold returned globals back out (:1060-1105), verbatim."""
        orch = self.orch
        try:
            result_action = Action.model_validate(result_actiondict)
            orch.active_experiment.dispatched_actions.append(result_action)
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            LOGGER.error(
                f"returned result is not a valid Action BaseModel: {repr(e), tb,}"
            )
            return ErrorCodes.critical_error

        if result_action.error_code is not ErrorCodes.none:
            LOGGER.error(
                f"Action result for '{result_action.action_name}' on '{result_action.action_server.disp_name()}' has error code: {result_action.error_code}"
            )
            stop_reason = f"{result_action.action_name} on {result_action.action_server.disp_name()} returned an error"
            await orch.estop_loop(stop_reason)
            return result_action.error_code

        collect_to_globals(
            result_action,
            orch.global_params,
            orch_key=orch.orch_key,
            orch_host=orch.orch_host,
            orch_port=orch.orch_port,
        )

        return None

    # =======================================================================
    # experiment coordinator -- migrated S7 helpers (self.->self.orch.)
    # =======================================================================

    async def dispatch_experiment(self) -> ErrorCodes:
        """Pop the next experiment, expand its actions, push onto action_dq (:536-567)."""
        orch = self.orch
        # check again if experiment_dq is empty
        if not orch.experiment_dq:
            LOGGER.info("experiment_dq is empty, cannot dispatch experiments")
            await orch.intend_none()
            return ErrorCodes.none

        await self._stage_experiment()

        rc, staged_acts = await self._expand_experiment_actions()
        if rc is not None:
            return rc

        await self._upload_exp_meta_s3()

        rc = await self._verify_experiment_plate()
        if rc is not None:
            return rc

        LOGGER.info("adding unpacked actions to action_dq")
        for act in staged_acts:
            orch.action_dq.append(act)

        return ErrorCodes.none

    async def _stage_experiment(self) -> None:
        """Pop the next experiment, make it active, and register it (:569-642), verbatim."""
        orch = self.orch
        LOGGER.info("action_dq is empty, getting new actions")
        # generate uids when populating, generate timestamp when acquring
        orch.active_experiment = orch.experiment_dq.popleft()

        orch.active_experiment.orch_key = orch.orch_key
        orch.active_experiment.orch_host = orch.orch_host
        orch.active_experiment.orch_port = orch.orch_port
        orch.active_experiment.sequence_uuid = orch.active_sequence.sequence_uuid
        if orch.active_sequence.campaign_name:
            orch.active_experiment.campaign_name = orch.active_sequence.campaign_name
            orch.active_experiment.campaign_uuid = orch.active_sequence.campaign_uuid
        orch.active_seq_exp_counter += 1

        # copy requested global param to experiment params
        apply_from_globals(
            orch.active_experiment.experiment_params,
            orch.active_experiment.from_global_exp_params,
            orch.global_params,
            logger_ctx="experiment --",
        )

        LOGGER.info(
            f"new active experiment is {orch.active_experiment.experiment_name}"
        )
        await orch.put_lbuf(
            {
                orch.active_experiment.experiment_uuid: {
                    "experiment_name": orch.active_experiment.experiment_name,
                    "status": HloStatus.active.value,
                }
            }
        )
        orch.active_experiment.dummy = orch.world_cfg.get("dummy", False)
        orch.active_experiment.simulation = orch.world_cfg.get("simulation", False)
        if orch.active_experiment.run_type is None:
            orch.active_experiment.run_type = orch.run_type
        orch.active_experiment.orchestrator = orch.server
        orch.active_experiment.init_exp(time_offset=orch.ntp_offset)
        orch.register_obj_uuid(
            orch.active_experiment.experiment_uuid,
            {
                "experiment_name": orch.active_experiment.experiment_name,
                "experiment_params": orch.active_experiment.experiment_params,
                "experiment_timestamp": f"{orch.active_experiment.experiment_timestamp: %m-%d %H:%M:%S}",
                "experiment_status": HloStatus.active.value,
                "sequence_label": orch.active_sequence.sequence_label,
                "campaign_name": (
                    orch.active_sequence.campaign_name
                    if orch.active_sequence.campaign_name
                    else None
                ),
            },
            "experiment",
        )
        LOGGER.debug(
            "registered experiment uuid: " + str(orch.active_experiment.experiment_uuid)
        )

        # attach run_id
        if orch.active_run_id is not None:
            orch.active_experiment.run_id = orch.active_run_id

        orch.globalstatusmodel.new_experiment(
            exp_uuid=orch.active_experiment.experiment_uuid
        )

    async def _expand_experiment_actions(
        self,
    ) -> Tuple[Optional[ErrorCodes], Optional[list]]:
        """Expand the active experiment into staged actions (:644-727), verbatim."""
        orch = self.orch
        exp_func = orch.experiment_lib[orch.active_experiment.experiment_name]
        exp_func_args = inspect.getfullargspec(exp_func).args
        supplied_params = {
            k: v
            for k, v in orch.active_experiment.experiment_params.items()
            if k in exp_func_args
        }
        exp_return = exp_func(orch.active_experiment, **supplied_params)

        unpacked_acts = None
        if isinstance(exp_return, list):
            unpacked_acts = exp_return
        elif isinstance(exp_return, Experiment):
            orch.active_experiment = exp_return
            unpacked_acts = orch.active_experiment.planned_actions

        orch.active_experiment.experiment_codehash = orch.experiment_codehash_lib[
            orch.active_experiment.experiment_name
        ]
        orch.active_experiment.experiment_codepath = orch.experiment_codepath_lib[
            orch.active_experiment.experiment_name
        ]
        orch.active_experiment.experiment_funcname = orch.experiment_lib[
            orch.active_experiment.experiment_name
        ].__name__
        if unpacked_acts is None:
            LOGGER.error("no actions in experiment")
            orch.action_dq = zdeque([])
            return ErrorCodes.none, None

        process_order_groups = defaultdict(list)
        process_count = 0
        init_process_uuids = [gen_uuid()]

        ## actions are not instantiated until experiment is unpacked
        staged_acts = []
        for i, act in enumerate(unpacked_acts):
            # init uuid now for tracking later
            act.action_uuid = gen_uuid()
            act.action_order = int(i)
            act.orch_key = orch.orch_key
            act.orch_host = orch.orch_host
            act.orch_port = orch.orch_port
            # actual order should be the same at the beginning
            # will be incremented as necessary
            act.orch_submit_order = int(i)
            if act.process_contrib:
                process_order_groups[process_count].append(i)
                act.process_uuid = init_process_uuids[process_count]
            if act.process_finish:
                process_count += 1
                init_process_uuids.append(gen_uuid())
            if orch.active_experiment.data_request_id is not None:
                act.data_request_id = orch.active_experiment.data_request_id
            actserv_cfg = orch.world_cfg["servers"][act.action_server.server_name]
            act.action_server.hostname = actserv_cfg["host"]
            act.action_server.port = actserv_cfg["port"]
            act.action_server.machine_name = orch.server.machine_name
            act.campaign_name = orch.active_experiment.campaign_name
            act.campaign_uuid = orch.active_experiment.campaign_uuid
            staged_acts.append(act)
        if process_order_groups:
            orch.active_experiment.process_order_groups = process_order_groups
            process_list = init_process_uuids[: len(process_order_groups)]
            orch.active_experiment.process_list = process_list

        LOGGER.info(f"got: {staged_acts}")
        LOGGER.info(f"optional params: {orch.active_experiment.experiment_params}")

        return None, staged_acts

    async def _upload_exp_meta_s3(self) -> None:
        """Write the temporary experiment and upload its meta json to S3 (:729-746), verbatim."""
        orch = self.orch
        # write a temporary exp
        orch.exp_model = orch.active_experiment.get_exp()
        await orch.write_active_experiment_exp()
        if orch.use_sync:
            try:
                meta_s3_key = f"experiment/{orch.exp_model.experiment_uuid}.json"
                LOGGER.info(
                    f"uploading initial active experiment json to s3 ({meta_s3_key})"
                )
                await orch.syncer.to_s3(
                    orch.exp_model.clean_dict(strip_private=True), meta_s3_key
                )
            except Exception as e:
                LOGGER.error(
                    f"Error uploading initial active experiment json to s3: {e}"
                )

    async def _verify_experiment_plate(self) -> Optional[ErrorCodes]:
        """Gate on plate verification (:748-763); returns ``not_available`` on failure."""
        orch = self.orch
        from helao.core.servers.orch import PLATE_API

        if orch.verify_plates and PLATE_API.has_access:
            plate_found = orch.verify_plate_in_params(
                orch.active_experiment.experiment_params
            )
            if not plate_found:
                stop_message = "experiment contains a plate_id parameter but plate_id could not be found"
                orch.current_stop_message = stop_message
                LOGGER.warning(stop_message)
                await orch.stop()
                orch.globalstatusmodel.loop_state = LoopStatus.stopped
                await orch.intend_none()
                return ErrorCodes.not_available

        return None

    # =======================================================================
    # sequence coordinator -- migrated S7 body (self.->self.orch.)
    # =======================================================================

    async def dispatch_sequence(self) -> ErrorCodes:
        """Pop the next sequence, activate/validate it, spawn its unpacker (:405-534), verbatim."""
        orch = self.orch
        from helao.core.servers.orch import PLATE_API

        if orch.sequence_dq:
            LOGGER.info("getting new sequence from sequence_dq")
            orch.active_sequence = orch.sequence_dq.popleft()

            LOGGER.info(f"new active sequence is {orch.active_sequence.sequence_name}")
            await orch.put_lbuf(
                {
                    orch.active_sequence.sequence_uuid: {
                        "sequence_name": orch.active_sequence.sequence_name,
                        "status": HloStatus.active.value,
                    }
                }
            )
            orch.active_sequence.dummy = orch.world_cfg.get("dummy", False)
            orch.active_sequence.simulation = orch.world_cfg.get("simulation", False)
            if orch.active_sequence.run_type is None:
                orch.active_sequence.run_type = orch.run_type
            orch.active_sequence.orchestrator = orch.server
            orch.active_sequence.init_seq(time_offset=orch.ntp_offset)
            orch.register_obj_uuid(
                orch.active_sequence.sequence_uuid,
                {
                    "sequence_name": orch.active_sequence.sequence_name,
                    "sequence_params": orch.active_sequence.sequence_params,
                    "sequence_timestamp": f"{orch.active_sequence.sequence_timestamp: %m-%d %H:%M:%S}",
                    "sequence_status": HloStatus.active.value,
                    "sequence_label": orch.active_sequence.sequence_label,
                    "campaign_name": (
                        orch.active_sequence.campaign_name
                        if orch.active_sequence.campaign_name
                        else None
                    ),
                },
                "sequence",
            )
            LOGGER.debug(
                "registered sequence uuid: " + str(orch.active_sequence.sequence_uuid)
            )

            # from global params
            apply_from_globals(
                orch.active_sequence.sequence_params,
                orch.active_sequence.from_global_seq_params,
                orch.global_params,
                logger_ctx="sequence",
            )

            # attach run_id (derive active_run_id from the dequeued sequence)
            orch._resolve_active_run_id(orch.active_sequence)

            # if planned_experiments is empty, unpack sequence,
            # otherwise operator already populated planned_experiments
            if orch.active_sequence.sequence_name in orch.sequence_lib:
                planned_experiments = orch.unpack_sequence(
                    orch.active_sequence.sequence_name,
                    orch.active_sequence.sequence_params,
                )
                if not orch.active_sequence.planned_experiments:
                    orch.active_sequence.planned_experiments = planned_experiments
                elif len(orch.active_sequence.planned_experiments) >= len(
                    planned_experiments
                ):
                    new_planned_experiments = []
                    for exp_model in orch.active_sequence.planned_experiments:
                        if not planned_experiments:
                            new_planned_experiments.append(exp_model)
                        else:
                            exp = planned_experiments.pop(0)
                            if exp.experiment_name == exp_model.experiment_name:
                                for k, v in vars(exp_model).items():
                                    setattr(exp, k, v)
                                new_planned_experiments.append(exp)
                            else:
                                break
                    if len(orch.active_sequence.planned_experiments) == len(
                        new_planned_experiments
                    ):
                        orch.active_sequence.planned_experiments = (
                            new_planned_experiments
                        )

            orch.seq_model = orch.active_sequence.get_seq()
            await orch.write_seq(orch.active_sequence)

            if orch.use_sync:
                try:
                    meta_s3_key = f"sequence/{orch.seq_model.sequence_uuid}.json"
                    LOGGER.info(
                        f"uploading initial active sequence json to s3 ({meta_s3_key})"
                    )
                    await orch.syncer.to_s3(
                        orch.seq_model.clean_dict(strip_private=True), meta_s3_key
                    )
                except Exception as e:
                    LOGGER.error(
                        f"Error uploading initial active sequence json to s3: {e}"
                    )

            if orch.verify_plates and PLATE_API.has_access:
                plate_found = orch.verify_plate_in_params(
                    orch.active_sequence.sequence_params
                )
                if not plate_found:
                    stop_message = "sequence contains a plate_id parameter but plate_id could not be found"
                    orch.current_stop_message = stop_message
                    LOGGER.warning(stop_message)
                    await orch.stop()
                    orch.globalstatusmodel.loop_state = LoopStatus.stopped
                    await orch.intend_none()
                    return ErrorCodes.not_available

            orch.aloop.create_task(orch.seq_unpacker())
            LOGGER.info("waiting for experiment queue to populate")
            while len(orch.experiment_dq) == 0:
                await asyncio.sleep(0.1)

        else:
            LOGGER.info("sequence queue is empty, cannot start orch loop")

            orch.globalstatusmodel.loop_state = LoopStatus.stopped
            await orch.intend_none()

        return ErrorCodes.none
