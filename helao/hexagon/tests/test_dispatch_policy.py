"""Unit tests for the ported pure DispatchPolicy (core-01 §5b precedence)."""

import pytest

from helao.hexagon.domain.dispatch_policy import (
    AwaitEndpointFree,
    AwaitPreviousActionDone,
    AwaitServerFree,
    AwaitWaitEndpointFree,
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
    NoWaitProceed,
    PauseLoop,
    ProceedDispatch,
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
    # base's inferred value type is a union of all field types, so pyright
    # cannot re-derive each field's precise literal type through **base.
    return DispatchSnapshot(**base)  # type: ignore[reportArgumentType]


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


def test_wait_for_previous_predicate_matches_a_str_uuid_against_uuid_keys():
    """``orch.last_action_uuid`` is the STRING the dispatch response carried
    (``as_dict`` serialises a UUID), while ``gsm.active_dict`` is keyed by
    ``UUID`` objects. Compared raw, the membership test was always False and
    wait_for_previous never waited for anything."""
    from types import SimpleNamespace
    from uuid import uuid4

    u = uuid4()
    step = P.start_condition_step(ActionStartCondition.wait_for_previous)
    assert isinstance(step, AwaitPreviousActionDone)  # narrows for the type checker
    orch = SimpleNamespace(last_action_uuid=str(u))
    gsm_busy = SimpleNamespace(active_dict={u: object()})
    gsm_idle = SimpleNamespace(active_dict={})
    # predicate is the NEGATION: True means "previous is done, proceed"
    assert step.predicate(gsm_busy, None, orch) is False
    assert step.predicate(gsm_idle, None, orch) is True


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


# --- ported from the retired unit_test_orch_dispatch_policy -----------------
# next_step is the whole outer ladder (while-cond, driver health, then the
# ladder); the tests above reach most of it through ladder_step alone.


def test_next_step_estopped_state_fails_the_while_cond():
    # estopped != started, so the loop exits before the ladder's StopLoop.
    s = P.next_step(snap(loop_state=LoopStatus.estopped, n_acts=3))
    assert isinstance(s, ExitLoop) and s.reason == "loop_state_not_started"


def test_next_step_estop_intent_beats_action():
    assert isinstance(
        P.next_step(snap(loop_intent=LoopIntent.estop, n_acts=3)), StopLoop
    )


def test_next_step_driver_health_beats_experiment_branch():
    s = P.next_step(snap(n_exps=1, na_drivers=("gpsim", "cpsim")))
    assert isinstance(s, DriverHealthWait) and s.na_drivers == ("gpsim", "cpsim")


@pytest.mark.parametrize(
    "kw,cls",
    [
        (dict(n_acts=2, n_exps=1, n_seqs=1), LaunchAction),
        (dict(n_exps=2, n_seqs=1), FinishThenDispatchExperiment),
        (dict(n_seqs=3), FinishThenDispatchSequence),
        # stop and skip are consumed inside the coordinator, not the outer ladder
        (dict(loop_intent=LoopIntent.stop, n_acts=1), LaunchAction),
        (dict(loop_intent=LoopIntent.skip, n_acts=1), LaunchAction),
    ],
)
def test_next_step_branches(kw, cls):
    assert isinstance(P.next_step(snap(**kw)), cls)


def test_step_thru_pause_reasons_name_what_is_next():
    a = P.evaluate_step_thru(snap(n_acts=2, step_thru_actions=True))
    e = P.evaluate_step_thru(snap(n_exps=1, step_thru_experiments=True))
    q = P.evaluate_step_thru(snap(n_seqs=1, step_thru_sequences=True))
    assert a is not None and a.reason.endswith("dispatch next action.")
    assert e is not None and e.reason.endswith("dispatch next experiment.")
    assert q is not None and q.reason.endswith("dispatch next sequence.")


def test_step_thru_experiment_flag_wins_regardless_of_the_action_flag():
    # the action branch needs n_acts truthy; with none queued the experiment
    # branch is next.
    p = P.evaluate_step_thru(
        snap(n_exps=1, step_thru_actions=True, step_thru_experiments=True)
    )
    assert p is not None and p.reason.endswith("dispatch next experiment.")


def test_step_thru_queued_actions_block_the_sequence_branch():
    assert (
        P.evaluate_step_thru(
            snap(n_acts=1, n_exps=1, n_seqs=1, step_thru_sequences=True)
        )
        is None
    )


def test_step_thru_all_flags_on_but_nothing_queued():
    assert (
        P.evaluate_step_thru(
            snap(
                step_thru_actions=True,
                step_thru_experiments=True,
                step_thru_sequences=True,
            )
        )
        is None
    )


class _FakeGSM:
    """Records the exact method and kwargs a start-condition predicate calls."""

    def __init__(self, endpoint_free=True, server_free=True):
        self._endpoint_free = endpoint_free
        self._server_free = server_free
        self.calls = []

    def endpoint_free(self, action_server=None, endpoint_name=None):
        self.calls.append(("endpoint_free", action_server, endpoint_name))
        return self._endpoint_free

    def server_free(self, action_server=None):
        self.calls.append(("server_free", action_server))
        return self._server_free


@pytest.mark.parametrize(
    "cond,gsm_kw,expected,call",
    [
        (
            ActionStartCondition.wait_for_endpoint,
            dict(endpoint_free=True),
            True,
            ("endpoint_free", "srv-obj", "my_action"),
        ),
        (
            ActionStartCondition.wait_for_server,
            dict(server_free=False),
            False,
            ("server_free", "srv-obj"),
        ),
        (
            ActionStartCondition.wait_for_orch,
            dict(endpoint_free=True),
            True,
            ("endpoint_free", "orch-obj", "wait"),
        ),
    ],
)
def test_start_condition_predicate_calls_the_exact_method_and_kwargs(
    cond, gsm_kw, expected, call
):
    from types import SimpleNamespace

    a = SimpleNamespace(
        action_server="srv-obj", action_name="my_action", orchestrator="orch-obj"
    )
    step = P.start_condition_step(cond)
    gsm = _FakeGSM(**gsm_kw)
    assert step.predicate(gsm, a, SimpleNamespace()) is expected  # type: ignore[attr-defined]
    assert gsm.calls == [call]


@pytest.mark.parametrize(
    "args,expected",
    [
        ((0, True), True),
        ((1, True), False),
        ((0, False), False),
        ((0, True, OrchStatus.estopped), False),
        ((0, True, LoopStatus.started), True),
    ],
)
def test_should_close_out_experiment(args, expected):
    assert should_close_out_experiment(*args) is expected


@pytest.mark.parametrize(
    "args,expected",
    [
        ((0, 0, True), True),
        ((1, 0, True), False),
        ((0, 1, True), False),
        ((0, 0, False), False),
        ((0, 0, True, OrchStatus.estopped), False),
        ((0, 0, True, LoopStatus.started), True),
    ],
)
def test_should_close_out_sequence(args, expected):
    assert should_close_out_sequence(*args) is expected


def test_should_set_stopped_compares_estopped_by_str_value():
    assert should_set_stopped(LoopStatus.stopped) is True
    assert should_set_stopped(LoopStatus.started) is True
    assert should_set_stopped(OrchStatus.estopped) is False
    assert should_set_stopped(LoopStatus.estopped) is False
    assert LoopStatus.estopped == OrchStatus.estopped


@pytest.mark.parametrize(
    "args,expected", [((0, 0, 0), False), ((1, 0, 0), True), ((0, 0, 3), True)]
)
def test_should_export(args, expected):
    assert should_export(*args) is expected
