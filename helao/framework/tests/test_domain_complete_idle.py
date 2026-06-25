"""SP-ORCH-5: complete_idle — natural-completion loop_state transition.

When the dispatch loop drains every queue (decide_next -> IDLE) it must transition
loop_state started -> stopped and broadcast, so subscribers (the operator) stop
showing the orchestrator as "running" after a sequence completes. Regression for the
live test-deploy symptom: experiment fully completes (FINISH_EXPERIMENT +
FINISH_SEQUENCE) but the operator kept showing it "running" because loop_state stayed
started.
"""

from helao.framework.domain.orchestration import OrchState, complete_idle
from helao.framework.domain.commands import BroadcastGlobalStatus
from helao.framework.models.orchstatus import LoopStatus, LoopIntent


def test_complete_idle_started_to_stopped_with_broadcast():
    state = OrchState()
    state.globalstatusmodel.loop_state = LoopStatus.started
    state.globalstatusmodel.loop_intent = LoopIntent.stop  # lingering intent

    _st, cmds = complete_idle(state)

    assert state.globalstatusmodel.loop_state == LoopStatus.stopped
    assert state.globalstatusmodel.loop_intent == LoopIntent.none
    assert len(cmds) == 1 and isinstance(cmds[0], BroadcastGlobalStatus)


def test_complete_idle_noop_when_not_started():
    # Already stopped: no transition, no broadcast (idempotent / no spurious events).
    state = OrchState()
    state.globalstatusmodel.loop_state = LoopStatus.stopped

    _st, cmds = complete_idle(state)

    assert state.globalstatusmodel.loop_state == LoopStatus.stopped
    assert cmds == []


def test_complete_idle_noop_when_estopped():
    state = OrchState()
    state.globalstatusmodel.loop_state = LoopStatus.estopped

    _st, cmds = complete_idle(state)

    # estop must NOT be downgraded to stopped, and nothing is emitted.
    assert state.globalstatusmodel.loop_state == LoopStatus.estopped
    assert cmds == []
