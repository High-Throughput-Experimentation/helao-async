"""Effect runner: reducer commands -> thin legacy delegation, DD-2 delta
rules, DD-3 live re-checks. Uses a recording stub orch (app-layer unit
tests; the launched smoke exercises the real Orch)."""

import asyncio

import pytest

from helao.core.error import ErrorCodes
from helao.hexagon.adapters.fakes import FakeClock  # noqa: F401 (banner sanity)
from helao.hexagon.app.orch_effects import (
    OrchCommandRunner,
    apply_state_delta,
    derive_state,
)
from helao.hexagon.app.wiring import PortWiring
from helao.hexagon.domain.models import HloStatus, LoopIntent, LoopStatus, OrchStatus
from helao.hexagon.domain.orchestration import (
    AlertOperator,
    ClearActionQueue,
    ClearActiveRunId,
    ClearEstoppedFromFinished,
    CloseOutExperimentCmd,
    DispatchHeadAction,
    EstopFanout,
    ExportQueuesCmd,
    FinishActiveEstopped,
    FinishThenDispatchExperimentCmd,
    InterruptWake,
    OrchestrationState,
    RequeueHeadAction,
    SetStopMessage,
    WaitAllActionsIdle,
)


class _GSM:
    def __init__(self):
        self.loop_state = LoopStatus.stopped
        self.loop_intent = LoopIntent.none
        self.orch_state = OrchStatus.idle
        self.cleared = []

    def clear_in_finished(self, hlostatus):
        self.cleared.append(hlostatus)


class _StubOrch:
    """Records every effect; async methods mirror the legacy Orch surface."""

    def __init__(self):
        self.globalstatusmodel = _GSM()
        self.action_dq, self.experiment_dq, self.sequence_dq = [], [], []
        self.active_experiment: object | None = None
        self.active_sequence: object | None = None
        self.active_run_id = "RUN"
        self.status_summary = {}
        self.step_thru_actions = False
        self.step_thru_experiments = False
        self.step_thru_sequences = False
        self.current_stop_message = ""
        self.last_dispatched_action_uuid = "u1"
        self.action_history = {"u1": {}}
        self.interrupt_q = asyncio.Queue()
        self.calls = []
        self.dispatch_rc = ErrorCodes.none

    async def loop_task_dispatch_action(self):
        self.calls.append("loop_task_dispatch_action")
        return self.dispatch_rc

    async def loop_task_dispatch_experiment(self):
        self.calls.append("loop_task_dispatch_experiment")
        return ErrorCodes.none

    async def loop_task_dispatch_sequence(self):
        self.calls.append("loop_task_dispatch_sequence")
        return ErrorCodes.none

    async def finish_active_experiment(self):
        self.calls.append("finish_active_experiment")

    async def finish_active_sequence(self):
        self.calls.append("finish_active_sequence")

    async def orch_wait_for_all_actions(self):
        self.calls.append("orch_wait_for_all_actions")
        self.globalstatusmodel.orch_state = OrchStatus.idle

    async def intend_stop(self):
        self.calls.append("intend_stop")
        self.globalstatusmodel.loop_intent = LoopIntent.stop
        await self.interrupt_q.put("stop")

    async def intend_skip(self):
        self.calls.append("intend_skip")
        self.globalstatusmodel.loop_intent = LoopIntent.skip
        await self.interrupt_q.put("skip")

    async def intend_estop(self):
        self.calls.append("intend_estop")
        self.globalstatusmodel.loop_intent = LoopIntent.estop
        await self.interrupt_q.put("estop")

    async def intend_none(self):
        self.calls.append("intend_none")
        self.globalstatusmodel.loop_intent = LoopIntent.none
        await self.interrupt_q.put("none")

    async def estop_actions(self, switch: bool):
        self.calls.append(f"estop_actions:{switch}")

    async def estop_finish_active(self):
        self.calls.append("estop_finish_active")

    async def stop(self, reset_run_id: bool = False):
        self.calls.append("stop")

    def export_queues(self, timestamp_pck: bool = False):
        self.calls.append(f"export_queues:{timestamp_pck}")
        return "/tmp/queues.pck"


class _AlertSpy:
    def __init__(self):
        self.alerts = []

    def info(self, msg): ...
    def warning(self, msg): ...
    def error(self, msg, exc_info=False): ...

    def alert(self, msg):
        self.alerts.append(msg)

    def file_logger(self, server_key, log_root):
        raise AssertionError("unused")


def _runner(orch):
    spy = _AlertSpy()
    return OrchCommandRunner(orch, PortWiring(logging=spy)), spy


# --- derive_state -------------------------------------------------------------
def test_derive_state_reads_live_values():
    orch = _StubOrch()
    orch.action_dq = ["a"]
    orch.status_summary = {"PSTAT": (0.0, "unknown"), "MOTOR": (0.0, "ok")}
    orch.globalstatusmodel.loop_state = LoopStatus.started
    s = derive_state(orch)
    assert (s.n_acts, s.n_exps, s.n_seqs) == (1, 0, 0)
    assert s.na_drivers == ("PSTAT",)
    assert s.loop_state == LoopStatus.started


# --- apply_state_delta (DD-2) ---------------------------------------------------
@pytest.mark.asyncio
async def test_delta_routes_intent_through_legacy_intenders():
    orch = _StubOrch()
    old = derive_state(orch)
    new = OrchestrationState(loop_state=old.loop_state, loop_intent=LoopIntent.stop)
    await apply_state_delta(orch, old, new)
    assert "intend_stop" in orch.calls
    assert orch.interrupt_q.qsize() == 1  # wake preserved


@pytest.mark.asyncio
async def test_delta_never_clobbers_concurrent_estop():
    orch = _StubOrch()
    orch.globalstatusmodel.loop_state = LoopStatus.started
    old = derive_state(orch)  # sampled while started
    orch.globalstatusmodel.loop_state = LoopStatus.estopped  # concurrent E-STOP
    new = OrchestrationState(loop_state=LoopStatus.stopped)
    await apply_state_delta(orch, old, new)
    assert orch.globalstatusmodel.loop_state == LoopStatus.estopped  # preserved


@pytest.mark.asyncio
async def test_delta_t10_may_leave_estop():
    orch = _StubOrch()
    orch.globalstatusmodel.loop_state = LoopStatus.estopped
    old = derive_state(orch)  # input state IS estopped -> T10 transition
    new = OrchestrationState(loop_state=LoopStatus.stopped)
    await apply_state_delta(orch, old, new)
    assert orch.globalstatusmodel.loop_state == LoopStatus.stopped


@pytest.mark.asyncio
async def test_delta_t5_exception_skips_loop_state():
    orch = _StubOrch()
    orch.globalstatusmodel.loop_state = LoopStatus.started
    old = derive_state(orch)
    new = OrchestrationState(loop_state=LoopStatus.stopped)
    await apply_state_delta(orch, old, new, skip_loop_state=True)
    assert orch.globalstatusmodel.loop_state == LoopStatus.started  # drain body owns it


@pytest.mark.asyncio
async def test_apply_state_delta_writes_orch_state_back_dd2():
    """P2a DD-2: the reducer delta is now the SOLE orch_state writer.
    Unguarded overwrite is deliberate legacy parity: the legacy inline
    chain always overwrote orch_state with idle/busy on a fold."""
    orch = _StubOrch()
    old = OrchestrationState(orch_state=OrchStatus.idle)
    new = OrchestrationState(orch_state=OrchStatus.busy)
    await apply_state_delta(orch, old, new)
    assert orch.globalstatusmodel.orch_state == OrchStatus.busy


@pytest.mark.asyncio
async def test_apply_state_delta_skips_unchanged_orch_state():
    orch = _StubOrch()
    orch.globalstatusmodel.orch_state = OrchStatus.busy  # live drifted
    st = OrchestrationState(orch_state=OrchStatus.idle)
    await apply_state_delta(orch, st, st)  # no delta -> no write
    assert orch.globalstatusmodel.orch_state == OrchStatus.busy


# --- OrchCommandRunner ----------------------------------------------------------
@pytest.mark.asyncio
async def test_dispatch_head_action_happy_path():
    orch = _StubOrch()
    runner, _ = _runner(orch)
    rc = await runner.execute(DispatchHeadAction())
    assert rc is ErrorCodes.none
    assert orch.calls == ["loop_task_dispatch_action"]


@pytest.mark.asyncio
async def test_dispatch_head_action_live_recheck_bails_under_estop():
    orch = _StubOrch()
    orch.globalstatusmodel.loop_state = LoopStatus.estopped
    runner, _ = _runner(orch)
    rc = await runner.execute(DispatchHeadAction())
    assert rc is ErrorCodes.estop
    assert orch.calls == []  # never dispatched


@pytest.mark.asyncio
async def test_finish_then_dispatch_exp_recheck_and_order():
    orch = _StubOrch()
    runner, _ = _runner(orch)
    rc = await runner.execute(FinishThenDispatchExperimentCmd())
    assert rc is ErrorCodes.none
    assert orch.calls == ["finish_active_experiment", "loop_task_dispatch_experiment"]
    orch2 = _StubOrch()
    orch2.globalstatusmodel.loop_state = LoopStatus.estopped
    runner2, _ = _runner(orch2)
    assert (
        await runner2.execute(FinishThenDispatchExperimentCmd())
    ) is ErrorCodes.estop
    assert orch2.calls == []  # estop_finish_active stays SOLE finalizer


@pytest.mark.asyncio
async def test_close_out_experiment_guard_rechecked_live():
    orch = _StubOrch()
    orch.active_experiment = object()
    runner, _ = _runner(orch)
    await runner.execute(CloseOutExperimentCmd())
    assert orch.calls == ["finish_active_experiment"]
    orch2 = _StubOrch()
    orch2.active_experiment = object()
    orch2.globalstatusmodel.loop_state = LoopStatus.estopped  # live re-check #3
    runner2, _ = _runner(orch2)
    await runner2.execute(CloseOutExperimentCmd())
    assert orch2.calls == []


@pytest.mark.asyncio
async def test_estop_cascade_commands():
    orch = _StubOrch()
    runner, spy = _runner(orch)
    await runner.execute(ClearActiveRunId())
    assert orch.active_run_id is None
    await runner.execute(EstopFanout(switch=False))
    await runner.execute(FinishActiveEstopped())
    await runner.execute(SetStopMessage(message="E-STOP unit"))
    await runner.execute(AlertOperator(message="E-STOP unit"))
    assert orch.calls == ["estop_actions:False", "estop_finish_active"]
    assert orch.current_stop_message == "E-STOP unit"
    assert spy.alerts == ["E-STOP unit"]  # AlertOperator consumes the Logging PORT


@pytest.mark.asyncio
async def test_wait_all_actions_idle_drain_owns_stop_write():
    orch = _StubOrch()
    orch.globalstatusmodel.loop_state = LoopStatus.started
    runner, _ = _runner(orch)
    await runner.execute(WaitAllActionsIdle())
    assert orch.globalstatusmodel.loop_state == LoopStatus.stopped
    assert "orch_wait_for_all_actions" in orch.calls
    assert "intend_none" in orch.calls


@pytest.mark.asyncio
async def test_misc_effects():
    orch = _StubOrch()
    orch.action_dq = ["a", "b"]
    orch.sequence_dq = ["s"]
    runner, _ = _runner(orch)
    await runner.execute(ClearActionQueue())
    assert orch.action_dq == []
    await runner.execute(ExportQueuesCmd(timestamped=True))
    assert "export_queues:True" in orch.calls
    await runner.execute(ClearEstoppedFromFinished())
    assert orch.globalstatusmodel.cleared == [HloStatus.estopped]
    await runner.execute(InterruptWake(message="cleared_estop"))
    assert orch.interrupt_q.qsize() == 1
    # RequeueHeadAction is unreachable in P1b1 (DD-4): logged, not executed
    await runner.execute(RequeueHeadAction())
    assert orch.action_dq == []


@pytest.mark.asyncio
async def test_dispatch_head_action_poll_breaks_on_pruned_uuid():
    """P2a health-aware exit (Q3): the history poll must not spin forever
    when the dispatched uuid was pruned as dead."""
    orch = _StubOrch()
    orch.last_dispatched_action_uuid = "dead-uuid"
    orch.action_history = {}  # never fed — the legacy hang mode
    runner = OrchCommandRunner(orch, PortWiring(logging=_AlertSpy()))
    runner.pruned_uuids.add("dead-uuid")
    rc = await asyncio.wait_for(runner.execute(DispatchHeadAction()), timeout=3.0)
    assert rc == ErrorCodes.none
