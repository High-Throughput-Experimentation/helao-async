"""Decision-table unit tests for ``DispatchPolicy`` extracted from ``Orch``
(CARDS P5, Stage S8): the pure dispatch FSM decision surface.

The dispatch golden master (``test_orch_dispatch_golden_master.py --check``)
pins the end-to-end decision *trace* for 9 driven scenarios, but several
branches of the inverted policy are NOT exercised by those scenarios (the
invalid-model ``critical_error`` path, every ``ActionStartCondition`` kind, the
``estop`` outer branch, each step-thru flag in isolation, the empty-queue exit,
the ``DriverHealthWait`` precedence). This module is the S8-specific
behavior-preservation gate for the pure decision layer: it constructs
``DispatchSnapshot`` literals and asserts ``DispatchPolicy`` returns the exact
expected ``DispatchStep`` -- no ``orch``, no server, no ``await``.

Pure and hermetic: no network, no disk I/O, no event loop. ``DispatchPolicy``
touches nothing but the snapshot/enum inputs it is handed, so the invariants are
checked against genuine enum values, not stand-ins.
"""

__all__ = ["orch_dispatch_policy_unit_test"]

from types import SimpleNamespace
from uuid import uuid4

from helao.core.tests._test_utils import TestReporter
from helao.core.error import ErrorCodes
from helao.core.models.action_start_condition import ActionStartCondition
from helao.core.models.orchstatus import OrchStatus, LoopStatus, LoopIntent
from helao.core.servers.orch_dispatch import (
    DispatchPolicy,
    DispatchSnapshot,
    FinalizationSnapshot,
    ExitLoop,
    DriverHealthWait,
    StopLoop,
    LaunchAction,
    FinishThenDispatchExperiment,
    FinishThenDispatchSequence,
    LogQueuesEmpty,
    PauseLoop,
    DrainForStop,
    SkipClearActions,
    EstopClearActions,
    ProceedDispatch,
    NoWaitProceed,
    AwaitEndpointFree,
    AwaitServerFree,
    AwaitWaitEndpointFree,
    AwaitPreviousActionDone,
    WaitAllActions,
    CloseOutExperiment,
    CloseOutSequence,
    SetLoopStopped,
    ClearIntent,
    ExportQueues,
    should_close_out_experiment,
    should_close_out_sequence,
    should_set_stopped,
    should_export,
)


def _snap(
    loop_state=LoopStatus.started,
    loop_intent=LoopIntent.none,
    n_acts=0,
    n_exps=0,
    n_seqs=0,
    na_drivers=(),
    step_thru_actions=False,
    step_thru_experiments=False,
    step_thru_sequences=False,
) -> DispatchSnapshot:
    return DispatchSnapshot(
        loop_state=loop_state,
        loop_intent=loop_intent,
        n_acts=n_acts,
        n_exps=n_exps,
        n_seqs=n_seqs,
        na_drivers=tuple(na_drivers),
        step_thru_actions=step_thru_actions,
        step_thru_experiments=step_thru_experiments,
        step_thru_sequences=step_thru_sequences,
    )


# ---------------------------------------------------------------------------
# next_step decision table (design sec 8.1)
# ---------------------------------------------------------------------------


def _check_next_step_table() -> bool:
    p = DispatchPolicy()
    ok = True

    # N1: stopped state -> ExitLoop(loop_state_not_started)
    s = p.next_step(_snap(loop_state=LoopStatus.stopped, n_acts=5))
    ok &= isinstance(s, ExitLoop) and s.reason == "loop_state_not_started"

    # N2: started, all queues empty -> ExitLoop(all_queues_empty)
    s = p.next_step(_snap(loop_state=LoopStatus.started))
    ok &= isinstance(s, ExitLoop) and s.reason == "all_queues_empty"

    # N3: driver-health beats action branch
    s = p.next_step(_snap(n_acts=1, na_drivers=("cpsim",)))
    ok &= isinstance(s, DriverHealthWait) and s.na_drivers == ("cpsim",)

    # N4: driver-health beats experiment branch, multiple unknown drivers
    s = p.next_step(_snap(n_exps=1, na_drivers=("gpsim", "cpsim")))
    ok &= isinstance(s, DriverHealthWait) and s.na_drivers == ("gpsim", "cpsim")

    # N5: estopped state fails while-cond (estopped != started) -> ExitLoop
    s = p.next_step(_snap(loop_state=LoopStatus.estopped, n_acts=3))
    ok &= isinstance(s, ExitLoop) and s.reason == "loop_state_not_started"

    # N6: intent-estop beats action (started + estop intent + acts)
    s = p.next_step(_snap(loop_intent=LoopIntent.estop, n_acts=3))
    ok &= isinstance(s, StopLoop)

    # N7: action branch
    ok &= isinstance(p.next_step(_snap(n_acts=2, n_exps=1, n_seqs=1)), LaunchAction)

    # N8: experiment branch (no acts)
    ok &= isinstance(
        p.next_step(_snap(n_acts=0, n_exps=2, n_seqs=1)),
        FinishThenDispatchExperiment,
    )

    # N9: sequence branch (no acts, no exps)
    ok &= isinstance(
        p.next_step(_snap(n_acts=0, n_exps=0, n_seqs=3)),
        FinishThenDispatchSequence,
    )

    # N10: intent-stop is NOT handled at the outer level -> LaunchAction
    ok &= isinstance(p.next_step(_snap(loop_intent=LoopIntent.stop, n_acts=1)), LaunchAction)

    # N11: intent-skip is consumed inside the coordinator -> LaunchAction
    ok &= isinstance(p.next_step(_snap(loop_intent=LoopIntent.skip, n_acts=1)), LaunchAction)

    return bool(ok)


def _check_ladder_else_branch() -> bool:
    """N13: the :1223 else -> LogQueuesEmpty. Logically unreachable via the
    while-cond (next_step returns ExitLoop for the all-empty case), so it is
    pinned by calling ladder_step directly -- the post-driver-health ladder
    that preserves the dead-but-present branch verbatim."""
    p = DispatchPolicy()
    s = p.ladder_step(_snap(loop_state=LoopStatus.started, n_acts=0, n_exps=0, n_seqs=0))
    return isinstance(s, LogQueuesEmpty)


# ---------------------------------------------------------------------------
# evaluate_step_thru decision table (design sec 8.2)
# ---------------------------------------------------------------------------


def _check_step_thru_table() -> bool:
    p = DispatchPolicy()
    ok = True

    # S1: acts + step_thru_actions -> PauseLoop(action)
    s = p.evaluate_step_thru(_snap(n_acts=2, step_thru_actions=True))
    ok &= isinstance(s, PauseLoop) and s.reason.endswith("dispatch next action.")

    # S2: acts but flag off -> None
    ok &= p.evaluate_step_thru(_snap(n_acts=2)) is None

    # S3: no acts, exps + step_thru_experiments -> PauseLoop(experiment)
    s = p.evaluate_step_thru(_snap(n_exps=1, step_thru_experiments=True))
    ok &= isinstance(s, PauseLoop) and s.reason.endswith("dispatch next experiment.")

    # S4: precedence pin -- n_acts==0, n_exps==1, ste=T -> PauseLoop(experiment)
    # regardless of sta (first branch requires n_acts truthy)
    s = p.evaluate_step_thru(
        _snap(n_acts=0, n_exps=1, step_thru_actions=True, step_thru_experiments=True)
    )
    ok &= isinstance(s, PauseLoop) and s.reason.endswith("dispatch next experiment.")

    # S5: no acts/exps, seqs + step_thru_sequences -> PauseLoop(sequence)
    s = p.evaluate_step_thru(_snap(n_seqs=1, step_thru_sequences=True))
    ok &= isinstance(s, PauseLoop) and s.reason.endswith("dispatch next sequence.")

    # S6: acts truthy blocks exp/seq branches; sta off -> None
    ok &= (
        p.evaluate_step_thru(
            _snap(n_acts=1, n_exps=1, n_seqs=1, step_thru_sequences=True)
        )
        is None
    )

    # S7: all flags on but all queues empty -> None
    ok &= (
        p.evaluate_step_thru(
            _snap(
                step_thru_actions=True,
                step_thru_experiments=True,
                step_thru_sequences=True,
            )
        )
        is None
    )

    return bool(ok)


# ---------------------------------------------------------------------------
# pre_dispatch_intent_step (design sec 8.3)
# ---------------------------------------------------------------------------


def _check_pre_dispatch_intent() -> bool:
    p = DispatchPolicy()
    return (
        isinstance(p.pre_dispatch_intent_step(LoopIntent.stop), DrainForStop)
        and isinstance(p.pre_dispatch_intent_step(LoopIntent.skip), SkipClearActions)
        and isinstance(p.pre_dispatch_intent_step(LoopIntent.estop), EstopClearActions)
        and isinstance(p.pre_dispatch_intent_step(LoopIntent.none), ProceedDispatch)
    )


# ---------------------------------------------------------------------------
# start_condition_step -- all 5 kinds + fallback + predicate identity (sec 8.4)
# ---------------------------------------------------------------------------


class _FakeGSM:
    """Recording fake global status model for predicate identity checks."""

    def __init__(self, endpoint_free=True, server_free=True, active_uuids=None):
        self._endpoint_free = endpoint_free
        self._server_free = server_free
        self.active_dict = {u: object() for u in (active_uuids or [])}
        self.calls = []

    def endpoint_free(self, action_server=None, endpoint_name=None):
        self.calls.append(("endpoint_free", action_server, endpoint_name))
        return self._endpoint_free

    def server_free(self, action_server=None):
        self.calls.append(("server_free", action_server))
        return self._server_free


def _check_start_condition_steps() -> bool:
    p = DispatchPolicy()
    ok = True

    ok &= isinstance(p.start_condition_step(ActionStartCondition.no_wait), NoWaitProceed)
    ok &= isinstance(
        p.start_condition_step(ActionStartCondition.wait_for_endpoint), AwaitEndpointFree
    )
    ok &= isinstance(
        p.start_condition_step(ActionStartCondition.wait_for_server), AwaitServerFree
    )
    ok &= isinstance(
        p.start_condition_step(ActionStartCondition.wait_for_orch), AwaitWaitEndpointFree
    )
    ok &= isinstance(
        p.start_condition_step(ActionStartCondition.wait_for_previous),
        AwaitPreviousActionDone,
    )
    ok &= isinstance(
        p.start_condition_step(ActionStartCondition.wait_for_all), WaitAllActions
    )
    # bogus/unsupported enum value (scenario-2 fallback) -> WaitAllActions
    ok &= isinstance(p.start_condition_step(99), WaitAllActions)

    return bool(ok)


def _check_start_condition_predicates() -> bool:
    p = DispatchPolicy()
    ok = True

    A = SimpleNamespace(
        action_server="srv-obj",
        action_name="my_action",
        orchestrator="orch-obj",
    )

    # wait_for_endpoint: gsm.endpoint_free(action_server=A.action_server,
    #                                       endpoint_name=A.action_name)
    step = p.start_condition_step(ActionStartCondition.wait_for_endpoint)
    gsm = _FakeGSM(endpoint_free=True)
    res = step.predicate(gsm, A, SimpleNamespace())
    ok &= res is True and gsm.calls == [("endpoint_free", "srv-obj", "my_action")]

    # wait_for_server: gsm.server_free(action_server=A.action_server)
    step = p.start_condition_step(ActionStartCondition.wait_for_server)
    gsm = _FakeGSM(server_free=False)
    res = step.predicate(gsm, A, SimpleNamespace())
    ok &= res is False and gsm.calls == [("server_free", "srv-obj")]

    # wait_for_orch: gsm.endpoint_free(action_server=A.orchestrator,
    #                                   endpoint_name="wait")
    step = p.start_condition_step(ActionStartCondition.wait_for_orch)
    gsm = _FakeGSM(endpoint_free=True)
    res = step.predicate(gsm, A, SimpleNamespace())
    ok &= res is True and gsm.calls == [("endpoint_free", "orch-obj", "wait")]

    # wait_for_previous: predicate is the NEGATION of `while previous_action_active`
    #   -> orch.last_action_uuid NOT in gsm.active_dict.keys()
    step = p.start_condition_step(ActionStartCondition.wait_for_previous)
    prev = uuid4()
    # previous action still active -> uuid IS in active_dict -> predicate False (keep waiting)
    gsm_active = _FakeGSM(active_uuids=[prev])
    res_active = step.predicate(gsm_active, A, SimpleNamespace(last_action_uuid=prev))
    # previous action done -> uuid NOT in active_dict -> predicate True (proceed)
    gsm_done = _FakeGSM(active_uuids=[])
    res_done = step.predicate(gsm_done, A, SimpleNamespace(last_action_uuid=prev))
    ok &= (res_active is False) and (res_done is True)

    return bool(ok)


# ---------------------------------------------------------------------------
# finalization_plan + guard predicates (design sec 8.5)
# ---------------------------------------------------------------------------


def _check_finalization_plan() -> bool:
    p = DispatchPolicy()
    fsnap = FinalizationSnapshot(
        n_acts=0,
        n_exps=0,
        active_experiment_present=False,
        active_sequence_present=False,
        loop_state=LoopStatus.stopped,
    )
    plan = p.finalization_plan(fsnap)
    order_ok = [type(s) for s in plan] == [
        CloseOutExperiment,
        CloseOutSequence,
        SetLoopStopped,
        ClearIntent,
        ExportQueues,
    ]
    return order_ok


def _check_finalization_guards() -> bool:
    ok = True
    # should_close_out_experiment == (n_acts==0) and active_exp_present
    ok &= should_close_out_experiment(0, True) is True
    ok &= should_close_out_experiment(1, True) is False
    ok &= should_close_out_experiment(0, False) is False

    # should_close_out_sequence == (n_exps==0) and (n_acts==0) and active_seq_present
    ok &= should_close_out_sequence(0, 0, True) is True
    ok &= should_close_out_sequence(1, 0, True) is False
    ok &= should_close_out_sequence(0, 1, True) is False
    ok &= should_close_out_sequence(0, 0, False) is False

    # should_set_stopped == loop_state != OrchStatus.estopped (Q2: uses OrchStatus,
    # and LoopStatus.estopped compares equal to OrchStatus.estopped by str value)
    ok &= should_set_stopped(LoopStatus.stopped) is True
    ok &= should_set_stopped(LoopStatus.started) is True
    ok &= should_set_stopped(OrchStatus.estopped) is False
    ok &= should_set_stopped(LoopStatus.estopped) is False  # str-enum value equality
    ok &= (LoopStatus.estopped == OrchStatus.estopped)  # Q2 pin

    # should_export == any(> 0)
    ok &= should_export(0, 0, 0) is False
    ok &= should_export(1, 0, 0) is True
    ok &= should_export(0, 0, 3) is True

    return bool(ok)


def orch_dispatch_policy_unit_test() -> bool:
    reporter = TestReporter("orch_dispatch_policy")

    reporter.section("next_step outer ladder")
    reporter.check(
        "while-cond/driver-health/estop/action/exp/seq precedence (N1-N11)",
        _check_next_step_table,
    )
    reporter.check(
        "ladder_step else branch -> LogQueuesEmpty (N13, dead-but-present)",
        _check_ladder_else_branch,
    )

    reporter.section("evaluate_step_thru")
    reporter.check(
        "per-flag step-thru pause selection + precedence (S1-S7)",
        _check_step_thru_table,
    )

    reporter.section("pre_dispatch_intent_step")
    reporter.check(
        "stop->Drain, skip->SkipClear, estop->EstopClear, none->Proceed",
        _check_pre_dispatch_intent,
    )

    reporter.section("start_condition_step")
    reporter.check(
        "all 5 ActionStartCondition kinds + unsupported fallback -> WaitAllActions",
        _check_start_condition_steps,
    )
    reporter.check(
        "predicate identity: exact method+kwargs and wait_for_previous polarity",
        _check_start_condition_predicates,
    )

    reporter.section("finalization")
    reporter.check(
        "finalization_plan is the fixed 5-step ordered list",
        _check_finalization_plan,
    )
    reporter.check(
        "guard predicates (close-out exp/seq, set-stopped Q2, export)",
        _check_finalization_guards,
    )

    return reporter.success()


if __name__ == "__main__":
    import sys

    sys.exit(0 if orch_dispatch_policy_unit_test() else 1)
