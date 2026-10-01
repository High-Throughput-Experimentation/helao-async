"""Single-drainer loop: park/unpark, ladder-to-park mini-run, refusals,
estop funnel + race seed (DD-3), driver-health exhaustion. Uses the Task 8
stub orch extended with a scripted dispatch that drains its own queues."""

import asyncio
from typing import Optional

import pytest

from helao.core.error import ErrorCodes
from helao.hexagon.app.dispatch_loop import HexDispatchLoop, HexRuntime
from helao.hexagon.app.orch_effects import OrchCommandRunner
from helao.hexagon.app.wiring import PortWiring
from helao.hexagon.domain.models import LoopStatus
from helao.hexagon.domain.orchestration import StartRequested
from helao.hexagon.tests.test_orch_effects import _AlertSpy, _StubOrch


class _ScriptedOrch(_StubOrch):
    """Dispatch effects consume the scripted queues so a run drains."""

    def __init__(self, n_acts=2, n_exps=1, n_seqs=1):
        super().__init__()
        self.action_dq = [f"a{i}" for i in range(n_acts)]
        self.experiment_dq = [f"e{i}" for i in range(n_exps)]
        self.sequence_dq = [f"s{i}" for i in range(n_seqs)]
        self.block_dispatch: Optional[asyncio.Event] = None  # stall mid-effect
        self.fail_after_block = False  # the stalled effect crashes on resume

    async def loop_task_dispatch_action(self):
        self.calls.append("loop_task_dispatch_action")
        if self.block_dispatch is not None:
            await self.block_dispatch.wait()
        if self.fail_after_block:
            raise AttributeError("stale step dereferenced a finalized record")
        self.action_dq.pop(0)
        return ErrorCodes.none

    async def loop_task_dispatch_experiment(self):
        self.calls.append("loop_task_dispatch_experiment")
        self.experiment_dq.pop(0)
        self.active_experiment = object()
        self.action_dq.append("a_from_exp")
        return ErrorCodes.none

    async def loop_task_dispatch_sequence(self):
        self.calls.append("loop_task_dispatch_sequence")
        self.sequence_dq.pop(0)
        self.active_sequence = object()
        self.experiment_dq.append("e_from_seq")
        return ErrorCodes.none

    async def finish_active_experiment(self):
        # mirrors orch_lifecycle.finish_active_experiment's guard: a no-op
        # (no observable call) when there is nothing active to finish, same
        # as the real Orch — the ladder's "finish previous, dispatch next"
        # step is unconditional even on the very first dispatch.
        if self.active_experiment is not None:
            self.calls.append("finish_active_experiment")
        self.active_experiment = None

    async def finish_active_sequence(self):
        if self.active_sequence is not None:
            self.calls.append("finish_active_sequence")
        self.active_sequence = None


def _make(orch):
    runtime = HexRuntime(orch, OrchCommandRunner(orch, PortWiring(logging=_AlertSpy())))
    loop = HexDispatchLoop(runtime)
    return runtime, loop


@pytest.mark.asyncio
async def test_start_with_empty_queues_refuses_and_stays_parked():
    orch = _ScriptedOrch(n_acts=0, n_exps=0, n_seqs=0)
    runtime, loop = _make(orch)
    loop.start()
    await runtime.handle(StartRequested())
    await asyncio.sleep(0.05)
    assert orch.globalstatusmodel.loop_state == LoopStatus.stopped
    assert orch.calls == []  # nothing dispatched
    await loop.close()


@pytest.mark.asyncio
async def test_full_mini_run_drains_and_parks():
    orch = _ScriptedOrch(n_acts=1, n_exps=1, n_seqs=1)
    runtime, loop = _make(orch)
    loop.start()
    await runtime.handle(StartRequested())
    for _ in range(200):  # ~2 s budget
        if orch.globalstatusmodel.loop_state == LoopStatus.stopped and not (
            orch.action_dq or orch.experiment_dq or orch.sequence_dq
        ):
            break
        await asyncio.sleep(0.01)
    assert orch.globalstatusmodel.loop_state == LoopStatus.stopped
    assert not (orch.action_dq or orch.experiment_dq or orch.sequence_dq)
    # ladder order held: actions before exp-finish before seq-finish
    assert orch.calls.index("loop_task_dispatch_action") < orch.calls.index(
        "finish_active_experiment"
    )
    # finalization closed out the last experiment+sequence exactly once each
    assert orch.calls.count("finish_active_sequence") == 1
    assert orch.active_experiment is None and orch.active_sequence is None
    await loop.close()


@pytest.mark.asyncio
async def test_estop_funnel_race_seed_single_finalizer():
    """DD-3 race seed (P1b2 grows this into §10.3 item 3): estop lands while
    the loop is BLOCKED inside a dispatch effect; the cascade runs at the
    trigger site; the in-flight marked command's follow-up iterate bails; the
    estop finalizer runs exactly once and clean close-out never fires."""
    orch = _ScriptedOrch(n_acts=2)
    orch.active_experiment = object()
    orch.block_dispatch = asyncio.Event()
    runtime, loop = _make(orch)
    loop.start()
    await runtime.handle(StartRequested())
    for _ in range(100):
        if "loop_task_dispatch_action" in orch.calls:
            break
        await asyncio.sleep(0.01)
    # trigger-site estop while the loop is stalled mid-effect
    from helao.hexagon.domain.orchestration import EstopRequested

    await runtime.handle(EstopRequested(reason="race seed"))
    assert orch.globalstatusmodel.loop_state == LoopStatus.estopped
    assert orch.calls.count("estop_finish_active") == 1
    assert orch.block_dispatch is not None
    orch.block_dispatch.set()  # release the stalled effect
    await asyncio.sleep(0.2)
    # SOLE finalizer: the clean finish_active_experiment never ran
    assert orch.calls.count("finish_active_experiment") == 0
    assert orch.globalstatusmodel.loop_state == LoopStatus.estopped  # parked estopped
    await loop.close()


@pytest.mark.asyncio
async def test_stale_loop_exception_after_estop_and_clear_does_not_relatch():
    """eche10 2026-09-30: a step parked mid-effect while an E-STOP landed and
    was cleared crashed on resume; its UncaughtLoopException re-latched the
    cleared E-STOP (second cascade + alert). It started before the E-STOP, so
    the reducer must drop it. A crash in a step that started AFTER the clear
    (below) must still escalate."""
    from helao.hexagon.domain.orchestration import (
        ClearEstopRequested,
        EstopRequested,
    )

    orch = _ScriptedOrch(n_acts=2)
    orch.active_experiment = object()
    orch.block_dispatch = asyncio.Event()
    orch.fail_after_block = True
    runtime, loop = _make(orch)
    loop.start()
    await runtime.handle(StartRequested())
    for _ in range(100):
        if "loop_task_dispatch_action" in orch.calls:
            break
        await asyncio.sleep(0.01)
    await runtime.handle(EstopRequested(reason="stale step"))
    await runtime.handle(ClearEstopRequested())
    assert orch.globalstatusmodel.loop_state == LoopStatus.stopped
    assert orch.calls.count("estop_finish_active") == 1
    orch.block_dispatch.set()  # the parked step resumes and crashes
    await asyncio.sleep(0.2)
    assert orch.globalstatusmodel.loop_state == LoopStatus.stopped  # not re-latched
    assert orch.calls.count("estop_finish_active") == 1  # one finalizer
    assert orch.calls.count("estop_actions:True") == 1  # one estop fan-out
    await loop.close()


@pytest.mark.asyncio
async def test_estop_generation_bumps_on_latch_and_on_clear():
    from helao.hexagon.domain.orchestration import (
        ClearEstopRequested,
        EstopRequested,
    )

    orch = _ScriptedOrch(n_acts=1)
    runtime, _ = _make(orch)
    orch.globalstatusmodel.loop_state = LoopStatus.started
    assert runtime.estop_gen == 0
    await runtime.handle(EstopRequested(reason="x"))
    assert runtime.estop_gen == 1
    await runtime.handle(ClearEstopRequested())
    assert runtime.estop_gen == 2


@pytest.mark.asyncio
async def test_loop_exception_in_a_step_started_after_the_clear_still_escalates():
    from helao.hexagon.domain.orchestration import (
        ClearEstopRequested,
        EstopRequested,
    )

    orch = _ScriptedOrch(n_acts=2)
    orch.active_experiment = object()
    orch.fail_after_block = True
    runtime, loop = _make(orch)
    await runtime.handle(StartRequested())  # parks nothing: loop not started
    await runtime.handle(EstopRequested(reason="first"))
    await runtime.handle(ClearEstopRequested())
    loop.start()
    orch.globalstatusmodel.loop_state = LoopStatus.started  # fresh run
    runtime.loop_wake.set()
    await asyncio.sleep(0.2)  # the new step crashes
    assert orch.globalstatusmodel.loop_state == LoopStatus.estopped
    assert orch.calls.count("estop_finish_active") == 2  # first + the real crash
    await loop.close()


@pytest.mark.asyncio
async def test_driver_health_exhaustion_feeds_unrecovered_event(monkeypatch):
    """P2a: RetryDriverHealth exhaustion now constructs the
    DriverHealthUnrecovered event (same stop-message wording via the
    reducer) instead of the executor calling stop() directly."""
    import helao.hexagon.app.orch_effects as fx

    monkeypatch.setattr(fx, "DRIVER_HEALTH_RETRY_DELAY_S", 0.01)
    orch = _ScriptedOrch(n_acts=1, n_exps=0, n_seqs=0)
    orch.status_summary = {"MOTOR": ("idle", "unknown")}
    runtime, loop = _make(orch)
    loop.start()
    from helao.hexagon.domain.orchestration import StartRequested

    await runtime.handle(StartRequested())
    for _ in range(300):
        if orch.current_stop_message:
            break
        await asyncio.sleep(0.01)
    assert orch.current_stop_message == "unknown driver states: MOTOR"
    await loop.close()
