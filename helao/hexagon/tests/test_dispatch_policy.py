"""Unit tests for the ported pure DispatchPolicy (core-01 §5b precedence)."""

import pytest

from helao.hexagon.domain.dispatch_policy import (
    AwaitEndpointFree,
    AwaitPreviousActionDone,
    AwaitServerFree,
    AwaitWaitEndpointFree,
    CloseOutExperiment,
    CloseOutSequence,
    ClearIntent,
    DispatchPolicy,
    DispatchSnapshot,
    DrainForStop,
    DriverHealthWait,
    EstopClearActions,
    ExitLoop,
    ExportQueues,
    FinalizationSnapshot,
    FinishThenDispatchExperiment,
    FinishThenDispatchSequence,
    LaunchAction,
    LogQueuesEmpty,
    NoWaitProceed,
    PauseLoop,
    ProceedDispatch,
    SetLoopStopped,
    SkipClearActions,
    StopLoop,
    WaitAllActions,
    should_close_out_experiment,
    should_close_out_sequence,
    should_export,
    should_set_stopped,
)
from helao.hexagon.domain.models import (
    ActionStartCondition,
    LoopIntent,
    LoopStatus,
    OrchStatus,
)

P = DispatchPolicy()


def snap(**kw) -> DispatchSnapshot:
    base = dict(
        loop_state=LoopStatus.started,
        loop_intent=LoopIntent.none,
        n_acts=0,
        n_exps=0,
        n_seqs=0,
        na_drivers=(),
        step_thru_actions=False,
        step_thru_experiments=False,
        step_thru_sequences=False,
    )
    base.update(kw)
    return DispatchSnapshot(**base)


# --- while-cond / exit ---


def test_exit_when_not_started():
    s = P.next_step(snap(loop_state=LoopStatus.stopped, n_acts=1))
    assert isinstance(s, ExitLoop) and s.reason == "loop_state_not_started"


def test_exit_when_all_queues_empty():
    s = P.next_step(snap())
    assert isinstance(s, ExitLoop) and s.reason == "all_queues_empty"


# --- driver-health precedes ladder, non-terminal ---


def test_driver_health_precedes_ladder():
    s = P.next_step(snap(n_acts=1, na_drivers=("PSTAT",)))
    assert isinstance(s, DriverHealthWait) and s.na_drivers == ("PSTAT",)


# --- ladder precedence: estop > acts > exps > seqs > else ---


def test_ladder_estop_state_wins_over_queues():
    s = P.ladder_step(snap(loop_state=LoopStatus.estopped, n_acts=5))
    assert isinstance(s, StopLoop)


def test_ladder_estop_intent_wins():
    s = P.ladder_step(snap(loop_intent=LoopIntent.estop, n_acts=5))
    assert isinstance(s, StopLoop)


def test_ladder_precedence_order():
    assert isinstance(P.ladder_step(snap(n_acts=1, n_exps=1, n_seqs=1)), LaunchAction)
    assert isinstance(
        P.ladder_step(snap(n_exps=1, n_seqs=1)), FinishThenDispatchExperiment
    )
    assert isinstance(P.ladder_step(snap(n_seqs=1)), FinishThenDispatchSequence)
    assert isinstance(P.ladder_step(snap()), LogQueuesEmpty)


# --- pre-dispatch intent ---


@pytest.mark.parametrize(
    "intent,cls",
    [
        (LoopIntent.stop, DrainForStop),
        (LoopIntent.skip, SkipClearActions),
        (LoopIntent.estop, EstopClearActions),
        (LoopIntent.none, ProceedDispatch),
    ],
)
def test_pre_dispatch_intent(intent, cls):
    assert isinstance(P.pre_dispatch_intent_step(intent), cls)


# --- start conditions ---


def test_start_condition_mapping():
    assert isinstance(
        P.start_condition_step(ActionStartCondition.no_wait), NoWaitProceed
    )
    assert isinstance(
        P.start_condition_step(ActionStartCondition.wait_for_endpoint),
        AwaitEndpointFree,
    )
    assert isinstance(
        P.start_condition_step(ActionStartCondition.wait_for_server),
        AwaitServerFree,
    )
    assert isinstance(
        P.start_condition_step(ActionStartCondition.wait_for_orch),
        AwaitWaitEndpointFree,
    )
    assert isinstance(
        P.start_condition_step(ActionStartCondition.wait_for_previous),
        AwaitPreviousActionDone,
    )
    assert isinstance(
        P.start_condition_step(ActionStartCondition.wait_for_all), WaitAllActions
    )
    # unknown fallback -> WaitAllActions (orch.py:900-901)
    assert isinstance(P.start_condition_step(object()), WaitAllActions)


# --- step-thru sub-decision ---


def test_step_thru_actions_pause():
    p = P.evaluate_step_thru(snap(n_acts=1, step_thru_actions=True))
    assert isinstance(p, PauseLoop) and "actions" in p.reason


def test_step_thru_experiments_only_when_no_acts():
    assert (
        P.evaluate_step_thru(snap(n_acts=1, n_exps=1, step_thru_experiments=True))
        is None
    )
    assert isinstance(
        P.evaluate_step_thru(snap(n_exps=1, step_thru_experiments=True)), PauseLoop
    )


def test_step_thru_none():
    assert P.evaluate_step_thru(snap(n_acts=1)) is None


# --- finalization guards (the third live estop re-check lives here) ---


def test_finalization_plan_order():
    plan = P.finalization_plan(
        FinalizationSnapshot(
            n_acts=0,
            n_exps=0,
            active_experiment_present=True,
            active_sequence_present=True,
            loop_state=LoopStatus.stopped,
        )
    )
    assert [type(x) for x in plan] == [
        CloseOutExperiment,
        CloseOutSequence,
        SetLoopStopped,
        ClearIntent,
        ExportQueues,
    ]


def test_close_out_guards_skip_under_estop():
    assert should_close_out_experiment(0, True, OrchStatus.estopped) is False
    assert should_close_out_experiment(0, True, LoopStatus.stopped) is True
    assert should_close_out_experiment(1, True, LoopStatus.stopped) is False
    assert should_close_out_sequence(0, 0, True, OrchStatus.estopped) is False
    assert should_close_out_sequence(0, 0, True, LoopStatus.stopped) is True
    assert should_set_stopped(OrchStatus.estopped) is False
    assert should_set_stopped(LoopStatus.stopped) is True
    assert should_export(0, 0, 1) is True
    assert should_export(0, 0, 0) is False
