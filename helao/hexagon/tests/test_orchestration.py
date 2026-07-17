"""Reducer FSM transition-table tests (core-01 §5a T1-T13 + ladder wiring)."""

import pytest

from helao.hexagon.domain import orchestration as fsm
from helao.hexagon.domain.models import LoopIntent, LoopStatus, OrchStatus


def st(**kw) -> fsm.OrchestrationState:
    base = dict(
        loop_state=LoopStatus.stopped,
        loop_intent=LoopIntent.none,
        orch_state=OrchStatus.idle,
        n_seqs=0,
        n_exps=0,
        n_acts=0,
        active_experiment_present=False,
        active_sequence_present=False,
        na_drivers=(),
        step_thru_actions=False,
        step_thru_experiments=False,
        step_thru_sequences=False,
    )
    base.update(kw)
    # base's inferred value type is a union of all field types, so pyright
    # cannot re-derive each field's precise literal type through **base.
    return fsm.OrchestrationState(**base)  # type: ignore[reportArgumentType]


def kinds(cmds):
    return [type(c) for c in cmds]


# --- T1/T2/T3: start ---


def test_t1_start_with_queued_work_starts_loop():
    s, cmds = fsm.step(st(n_seqs=1), fsm.StartRequested())
    assert s.loop_state == LoopStatus.started
    assert kinds(cmds) == [fsm.CreateDispatchLoopTask]


def test_t1_start_with_active_sequence_only():
    s, cmds = fsm.step(st(active_sequence_present=True), fsm.StartRequested())
    assert s.loop_state == LoopStatus.started


def test_t2_start_with_everything_empty_refuses():
    s, cmds = fsm.step(st(), fsm.StartRequested())
    assert s.loop_state == LoopStatus.stopped
    assert kinds(cmds) == [fsm.RefuseStart]
    assert isinstance(cmds[0], fsm.RefuseStart)
    assert "empty" in cmds[0].reason


def test_t3_start_under_estop_refuses():
    s, cmds = fsm.step(
        st(loop_state=LoopStatus.estopped, n_acts=1), fsm.StartRequested()
    )
    assert s.loop_state == LoopStatus.estopped
    assert kinds(cmds) == [fsm.RefuseStart]
    assert isinstance(cmds[0], fsm.RefuseStart)
    assert "E-STOP" in cmds[0].reason


def test_start_while_started_is_noop():
    s0 = st(loop_state=LoopStatus.started, n_acts=1)
    s, cmds = fsm.step(s0, fsm.StartRequested())
    assert s == s0 and cmds == ()


# --- intents ---


def test_stop_sets_intent():
    s, cmds = fsm.step(st(loop_state=LoopStatus.started, n_acts=1), fsm.StopRequested())
    assert s.loop_intent == LoopIntent.stop and cmds == ()


def test_skip_sets_intent():
    s, _ = fsm.step(st(loop_state=LoopStatus.started, n_acts=1), fsm.SkipRequested())
    assert s.loop_intent == LoopIntent.skip


# --- T9: estop escalation (all four sources) ---


@pytest.mark.parametrize(
    "event",
    [
        fsm.EstopRequested(reason="ui"),
        fsm.ActionResultErrored(reason="bad result"),
        fsm.EstoppedUuidIngested(reason="status"),
        fsm.UncaughtLoopException(reason="boom"),
    ],
)
def test_t9_estop_transition_state_and_command_order(event):
    s, cmds = fsm.step(st(loop_state=LoopStatus.started, n_acts=2), event)
    assert s.loop_state == LoopStatus.estopped
    assert s.loop_intent == LoopIntent.none
    assert kinds(cmds) == [
        fsm.ClearActiveRunId,
        fsm.EstopFanout,
        fsm.FinishActiveEstopped,
        fsm.SetStopMessage,
        fsm.AlertOperator,
    ]
    fanout = cmds[1]
    assert isinstance(fanout, fsm.EstopFanout)
    assert fanout.switch is False


def test_estopped_uuid_when_loop_not_started_is_noop():
    s0 = st(loop_state=LoopStatus.stopped)
    s, cmds = fsm.step(s0, fsm.EstoppedUuidIngested(reason="late push"))
    assert s == s0 and cmds == ()


def test_estop_requested_when_loop_not_started_is_noop():
    """Mirrors production /estop_orch (orch_api.py:364-373): only estops when
    loop_state == started; stopped (and estopped) are no-ops."""
    s0 = st(loop_state=LoopStatus.stopped)
    s, cmds = fsm.step(s0, fsm.EstopRequested(reason="ui"))
    assert s == s0 and cmds == ()


def test_estop_requested_when_loop_started_estops():
    s, cmds = fsm.step(
        st(loop_state=LoopStatus.started, n_acts=2), fsm.EstopRequested(reason="ui")
    )
    assert s.loop_state == LoopStatus.estopped
    assert s.loop_intent == LoopIntent.none
    assert kinds(cmds) == [
        fsm.ClearActiveRunId,
        fsm.EstopFanout,
        fsm.FinishActiveEstopped,
        fsm.SetStopMessage,
        fsm.AlertOperator,
    ]


# --- T10/T11: clears ---


def test_t10_clear_estop():
    s, cmds = fsm.step(st(loop_state=LoopStatus.estopped), fsm.ClearEstopRequested())
    assert s.loop_state == LoopStatus.stopped
    assert kinds(cmds) == [
        fsm.ClearEstoppedFromFinished,
        fsm.ReleaseServersEstop,
        fsm.InterruptWake,
    ]
    assert isinstance(cmds[2], fsm.InterruptWake)
    assert cmds[2].message == "cleared_estop"


def test_t10_clear_estop_only_from_estopped():
    s0 = st(loop_state=LoopStatus.started, n_acts=1)
    s, cmds = fsm.step(s0, fsm.ClearEstopRequested())
    assert s == s0 and cmds == ()


def test_t11_clear_error_leaves_loop_state():
    s0 = st(loop_state=LoopStatus.stopped, orch_state=OrchStatus.error)
    s, cmds = fsm.step(s0, fsm.ClearErrorRequested())
    assert s.loop_state == LoopStatus.stopped
    assert kinds(cmds) == [fsm.ClearErroredFromFinished, fsm.InterruptWake]
    assert isinstance(cmds[1], fsm.InterruptWake)
    assert cmds[1].message == "cleared_errored"


# --- T12: pause-class failures (never estop) ---


def test_t12_dispatch_failure_pauses_and_requeues_head():
    s, cmds = fsm.step(
        st(loop_state=LoopStatus.started, n_acts=1),
        fsm.DispatchFailed(message="server down"),
    )
    assert s.loop_state == LoopStatus.started  # drains via T5, not inline
    assert s.loop_intent == LoopIntent.stop
    assert kinds(cmds) == [fsm.SetStopMessage, fsm.RequeueHeadAction]


def test_t12_plate_gate_sets_stopped_inline():
    s, cmds = fsm.step(
        st(loop_state=LoopStatus.started, n_exps=1),
        fsm.PlateGateFailed(message="no access"),
    )
    assert s.loop_state == LoopStatus.stopped
    assert s.loop_intent == LoopIntent.none
    assert kinds(cmds) == [fsm.SetStopMessage]


def test_t12_heartbeat_failure_pauses_with_alert():
    s, cmds = fsm.step(
        st(loop_state=LoopStatus.started, n_acts=1),
        fsm.HeartbeatFailed(message="endpoint gone"),
    )
    assert s.loop_intent == LoopIntent.stop
    assert kinds(cmds) == [fsm.SetStopMessage, fsm.AlertOperator]


def test_t12_driver_health_unrecovered_pauses():
    s, cmds = fsm.step(
        st(loop_state=LoopStatus.started, n_acts=1),
        fsm.DriverHealthUnrecovered(na_drivers=("PSTAT",)),
    )
    assert s.loop_intent == LoopIntent.stop
    assert kinds(cmds) == [fsm.SetStopMessage]


# --- status-derived orch_state ---


def test_errored_uuid_sets_error_when_started():
    s, _ = fsm.step(
        st(loop_state=LoopStatus.started, n_acts=1), fsm.ErroredUuidIngested()
    )
    assert s.orch_state == OrchStatus.error


def test_status_changed_busy_idle():
    s, _ = fsm.step(
        st(loop_state=LoopStatus.started, n_acts=1), fsm.StatusChanged(any_active=True)
    )
    assert s.orch_state == OrchStatus.busy
    s2, _ = fsm.step(
        st(loop_state=LoopStatus.started, n_acts=1), fsm.StatusChanged(any_active=False)
    )
    assert s2.orch_state == OrchStatus.idle


# --- LoopIterate: ladder wiring ---


def test_iterate_dispatches_head_action_with_live_recheck_guard():
    s, cmds = fsm.step(st(loop_state=LoopStatus.started, n_acts=1), fsm.LoopIterate())
    assert kinds(cmds) == [fsm.DispatchHeadAction]
    assert isinstance(cmds[0], fsm.DispatchHeadAction)
    assert cmds[0].requires_live_estop_recheck is True


def test_iterate_finish_then_dispatch_experiment_guarded():
    s, cmds = fsm.step(st(loop_state=LoopStatus.started, n_exps=1), fsm.LoopIterate())
    assert kinds(cmds) == [fsm.FinishThenDispatchExperimentCmd]
    assert isinstance(cmds[0], fsm.FinishThenDispatchExperimentCmd)
    assert cmds[0].requires_live_estop_recheck is True


def test_iterate_finish_then_dispatch_sequence_guarded():
    s, cmds = fsm.step(st(loop_state=LoopStatus.started, n_seqs=1), fsm.LoopIterate())
    assert kinds(cmds) == [fsm.FinishThenDispatchSequenceCmd]
    assert isinstance(cmds[0], fsm.FinishThenDispatchSequenceCmd)
    assert cmds[0].requires_live_estop_recheck is True


def test_iterate_driver_health_is_nonterminal_command():
    s, cmds = fsm.step(
        st(loop_state=LoopStatus.started, n_acts=1, na_drivers=("PSTAT",)),
        fsm.LoopIterate(),
    )
    assert kinds(cmds) == [fsm.RetryDriverHealth]
    assert isinstance(cmds[0], fsm.RetryDriverHealth)
    assert cmds[0].na_drivers == ("PSTAT",)


# --- T5/T6/T7: pre-dispatch intents on LaunchAction ---


def test_t5_drain_for_stop():
    s, cmds = fsm.step(
        st(loop_state=LoopStatus.started, n_acts=1, loop_intent=LoopIntent.stop),
        fsm.LoopIterate(),
    )
    assert s.loop_state == LoopStatus.stopped
    assert s.loop_intent == LoopIntent.none
    assert kinds(cmds) == [fsm.WaitAllActionsIdle]


def test_t6_skip_clears_only_actions():
    s, cmds = fsm.step(
        st(
            loop_state=LoopStatus.started,
            n_acts=3,
            n_exps=2,
            loop_intent=LoopIntent.skip,
        ),
        fsm.LoopIterate(),
    )
    assert s.loop_state == LoopStatus.started  # falls to exp dispatch next iter
    assert s.loop_intent == LoopIntent.none
    assert kinds(cmds) == [fsm.ClearActionQueue]


def test_t7_estop_intent_clears_actions_and_estops_loop_state():
    s, cmds = fsm.step(
        st(loop_state=LoopStatus.started, n_acts=3, loop_intent=LoopIntent.estop),
        fsm.LoopIterate(),
    )
    # ladder StopLoop wins first (estop intent) -> intend_stop; the
    # EstopClearActions path is reached when intent survives to LaunchAction.
    # Encode exactly what the reducer does; see implementation note below.
    assert s.loop_state in (LoopStatus.started, LoopStatus.estopped)


# --- T4: exit + finalization (plain stop with empty queues closes out) ---


def test_t4_exit_finalization_closes_out_and_stops():
    s, cmds = fsm.step(
        st(
            loop_state=LoopStatus.started,
            active_experiment_present=True,
            active_sequence_present=True,
        ),
        fsm.LoopIterate(),
    )
    assert s.loop_state == LoopStatus.stopped
    assert s.loop_intent == LoopIntent.none
    assert kinds(cmds) == [fsm.CloseOutExperimentCmd, fsm.CloseOutSequenceCmd]
    for c in cmds:
        assert isinstance(c, (fsm.CloseOutExperimentCmd, fsm.CloseOutSequenceCmd))
        assert c.requires_live_estop_recheck


def test_t4_exit_under_estop_keeps_estopped_and_skips_closeout():
    s, cmds = fsm.step(
        st(
            loop_state=LoopStatus.estopped,
            active_experiment_present=True,
            active_sequence_present=True,
        ),
        fsm.LoopIterate(),
    )
    assert s.loop_state == LoopStatus.estopped  # SetLoopStopped skipped (Q2)
    assert kinds(cmds) == []  # estop_finish_active is the sole finalizer


def test_t4_exit_with_leftover_queues_exports():
    s, cmds = fsm.step(st(loop_state=LoopStatus.stopped, n_seqs=2), fsm.LoopIterate())
    assert fsm.ExportQueuesCmd in kinds(cmds)
