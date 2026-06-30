"""Tests for the pure orchestration FSM ``helao.framework.domain.orchestration``.

All fixtures are hand-constructed plain data (mirroring ``test_domain_status.py``
and ``test_models_server.py``); no network, no asyncio. Transition functions are
exercised for their returned ``(state, commands)`` and for in-place state
mutation, covering: ``decide_next`` across the queue/idle matrix, every intent
transition incl. estop/clear, ``on_status_update`` reactions, all six
``start_condition_met`` cases, global-param fold in/out through dispatch steps,
the dispatch-sequence/experiment/action steps with injected now/uuid/expand
results, nonblocking bookkeeping, and the history maps.
"""
from datetime import datetime
from uuid import UUID, uuid4

from helao.framework.models.action import ActionModel
from helao.framework.models.errors import ErrorCodes
from helao.framework.models.experiment import ExperimentModel
from helao.framework.models.hlostatus import HloStatus
from helao.framework.models.machine import MachineModel
from helao.framework.models.orchstatus import LoopIntent, LoopStatus, OrchStatus
from helao.framework.models.action_start_condition import ActionStartCondition
from helao.framework.models.server import (
    ActionServerModel,
    EndpointModel,
    GlobalStatusModel,
)

from helao.framework.domain.run_models import RunAction, RunExperiment, RunSequence
from helao.framework.domain import orchestration as orch
from helao.framework.domain.commands import (
    BroadcastGlobalStatus,
    DispatchAction,
    EstopServers,
    ExpandExperiment,
    ExpandSequence,
    OrchDecision,
    PersistMeta,
    StopExecutor,
)

NOW = datetime(2026, 6, 22, 15, 0, 0)
SEED = UUID(int=1000)

ORCH = MachineModel(server_name="orch", machine_name="host")
SRV = MachineModel(server_name="act", machine_name="host")


def _gsm(**kw):
    return GlobalStatusModel(orchestrator=ORCH, **kw)


def _state(**kw):
    kw.setdefault("globalstatusmodel", _gsm())
    return orch.OrchState(**kw)


def _action(statuses=None, exp_uuid=None, action_uuid=None, **kw):
    return RunAction(
        action_uuid=action_uuid or uuid4(),
        experiment_uuid=exp_uuid,
        orchestrator=ORCH,
        action_server=kw.pop("action_server", SRV),
        action_status=list(statuses or []),
        **kw,
    )


def _server_model(action, endpoint_name="ep"):
    ep = EndpointModel(
        endpoint_name=endpoint_name, active_dict={action.action_uuid: action}
    )
    return ActionServerModel(action_server=SRV, endpoints={endpoint_name: ep})


# --------------------------------------------------------------------------- #
# OrchState property passthrough
# --------------------------------------------------------------------------- #
def test_loop_enums_read_through_model():
    st = _state()
    assert st.loop_state == LoopStatus.stopped
    st.loop_state = LoopStatus.started
    st.loop_intent = LoopIntent.stop
    st.orch_state = OrchStatus.busy
    assert st.globalstatusmodel.loop_state == LoopStatus.started
    assert st.globalstatusmodel.loop_intent == LoopIntent.stop
    assert st.globalstatusmodel.orch_state == OrchStatus.busy
    assert st.loop_intent == LoopIntent.stop
    assert st.orch_state == OrchStatus.busy


# --------------------------------------------------------------------------- #
# decide_next matrix
# --------------------------------------------------------------------------- #
def test_decide_next_idle_empty():
    assert orch.decide_next(_state()) == OrchDecision.IDLE


def test_decide_next_action_first():
    st = _state(action_dq=[_action()], experiment_dq=[RunExperiment()],
                sequence_dq=[RunSequence()])
    assert orch.decide_next(st) == OrchDecision.DISPATCH_ACTION


def test_decide_next_experiment_when_idle():
    st = _state(experiment_dq=[RunExperiment()])
    assert orch.decide_next(st) == OrchDecision.DISPATCH_EXPERIMENT


def test_decide_next_experiment_waits_when_busy():
    st = _state(experiment_dq=[RunExperiment()])
    active = _action([HloStatus.active])
    st.globalstatusmodel.update_global_with_acts(_server_model(active))
    assert orch.decide_next(st) == OrchDecision.WAIT


def test_decide_next_sequence_when_idle():
    st = _state(sequence_dq=[RunSequence()])
    assert orch.decide_next(st) == OrchDecision.DISPATCH_SEQUENCE


def test_decide_next_sequence_waits_when_busy():
    st = _state(sequence_dq=[RunSequence()])
    active = _action([HloStatus.active])
    st.globalstatusmodel.update_global_with_acts(_server_model(active))
    assert orch.decide_next(st) == OrchDecision.WAIT


def test_decide_next_finish_experiment():
    st = _state(active_experiment=RunExperiment())
    assert orch.decide_next(st) == OrchDecision.FINISH_EXPERIMENT


def test_decide_next_finish_sequence():
    st = _state(active_sequence=RunSequence())
    assert orch.decide_next(st) == OrchDecision.FINISH_SEQUENCE


def test_decide_next_finish_waits_when_busy():
    st = _state(active_experiment=RunExperiment())
    active = _action([HloStatus.active])
    st.globalstatusmodel.update_global_with_acts(_server_model(active))
    assert orch.decide_next(st) == OrchDecision.WAIT


def test_decide_next_stop_on_estopped_state():
    st = _state(action_dq=[_action()])
    st.loop_state = LoopStatus.estopped
    assert orch.decide_next(st) == OrchDecision.STOP


def test_decide_next_stop_on_stop_intent():
    st = _state(action_dq=[_action()])
    st.loop_intent = LoopIntent.stop
    assert orch.decide_next(st) == OrchDecision.STOP


def test_decide_next_stop_on_estop_intent():
    st = _state(action_dq=[_action()])
    st.loop_intent = LoopIntent.estop
    assert orch.decide_next(st) == OrchDecision.STOP


# --------------------------------------------------------------------------- #
# apply_intent
# --------------------------------------------------------------------------- #
def test_start_from_stopped_with_work():
    st = _state(action_dq=[_action()])
    st.current_stop_message = "old"
    st, cmds = orch.apply_intent(st, "start")
    assert st.loop_state == LoopStatus.started
    assert st.current_stop_message == ""
    assert any(isinstance(c, BroadcastGlobalStatus) for c in cmds)


def test_start_with_active_sequence_resumes():
    st = _state(active_sequence=RunSequence())
    st, _ = orch.apply_intent(st, "start")
    assert st.loop_state == LoopStatus.started


def test_start_with_empty_queues_is_noop():
    st = _state()
    st, _ = orch.apply_intent(st, "start")
    assert st.loop_state == LoopStatus.stopped


def test_start_under_estop_refused():
    st = _state(action_dq=[_action()])
    st.loop_state = LoopStatus.estopped
    st, _ = orch.apply_intent(st, "start")
    assert st.loop_state == LoopStatus.estopped


def test_stop_while_started_sets_intent():
    st = _state()
    st.loop_state = LoopStatus.started
    st, _ = orch.apply_intent(st, "stop")
    assert st.loop_intent == LoopIntent.stop


def test_stop_while_stopped_is_noop():
    st = _state()
    st, _ = orch.apply_intent(st, "stop")
    assert st.loop_intent == LoopIntent.none


def test_intend_stop_unconditional():
    st = _state()
    st, _ = orch.apply_intent(st, "intend_stop")
    assert st.loop_intent == LoopIntent.stop


def test_stop_default_keeps_run_id():
    st = _state()
    st.active_run_id = uuid4()
    rid = st.active_run_id
    st, _ = orch.apply_intent(st, "stop")
    assert st.active_run_id == rid


def test_stop_with_reset_clears_run_id():
    st = _state()
    st.active_run_id = uuid4()
    st, _ = orch.apply_intent(st, "stop", reset_run_id=True)
    assert st.active_run_id is None


def test_intend_stop_with_reset_clears_run_id():
    st = _state()
    st.active_run_id = uuid4()
    st, _ = orch.apply_intent(st, "intend_stop", reset_run_id=True)
    assert st.active_run_id is None


def test_skip_while_started_sets_intent():
    st = _state()
    st.loop_state = LoopStatus.started
    st, _ = orch.apply_intent(st, "skip")
    assert st.loop_intent == LoopIntent.skip


def test_skip_while_stopped_clears_actions():
    st = _state(action_dq=[_action(), _action()])
    st, _ = orch.apply_intent(st, "skip")
    assert st.action_dq == []
    assert st.loop_intent == LoopIntent.none


def test_intend_skip_unconditional():
    st = _state()
    st, _ = orch.apply_intent(st, "intend_skip")
    assert st.loop_intent == LoopIntent.skip


def test_intend_estop_and_none():
    st = _state()
    st, _ = orch.apply_intent(st, "intend_estop")
    assert st.loop_intent == LoopIntent.estop
    st, _ = orch.apply_intent(st, "intend_none")
    assert st.loop_intent == LoopIntent.none


def test_estop_transitions_to_estopped_and_emits():
    st = _state(active_run_id=uuid4())
    st.loop_intent = LoopIntent.stop
    st, cmds = orch.apply_intent(st, "estop", reason="boom")
    assert st.loop_state == LoopStatus.estopped
    assert st.active_run_id is None
    assert st.loop_intent == LoopIntent.none
    assert st.current_stop_message == "E-STOP boom"
    estops = [c for c in cmds if isinstance(c, EstopServers)]
    assert estops and estops[0].switch is False and estops[0].reason == "boom"


def test_clear_estop_returns_to_stopped_and_releases():
    st = _state()
    st.loop_state = LoopStatus.estopped
    # plant an estopped finished uuid
    st.globalstatusmodel.nonactive_dict[HloStatus.estopped] = {uuid4(): _action()}
    st, cmds = orch.apply_intent(st, "clear_estop")
    assert st.loop_state == LoopStatus.stopped
    assert st.globalstatusmodel.nonactive_dict[HloStatus.estopped] == {}
    assert any(isinstance(c, EstopServers) and c.switch is False for c in cmds)


def test_clear_error_clears_bucket():
    st = _state()
    st.globalstatusmodel.nonactive_dict[HloStatus.errored] = {uuid4(): _action()}
    st, _ = orch.apply_intent(st, "clear_error")
    assert st.globalstatusmodel.nonactive_dict[HloStatus.errored] == {}


def test_clear_queue_intents():
    st = _state(
        sequence_dq=[RunSequence()],
        experiment_dq=[RunExperiment()],
        action_dq=[_action()],
    )
    st, _ = orch.apply_intent(st, "clear_sequences")
    assert st.sequence_dq == []
    st, _ = orch.apply_intent(st, "clear_experiments")
    assert st.experiment_dq == []
    st, _ = orch.apply_intent(st, "clear_actions")
    assert st.action_dq == []


def test_unknown_intent_is_ignored():
    st = _state()
    st, cmds = orch.apply_intent(st, "bogus")
    assert cmds == []


# --------------------------------------------------------------------------- #
# on_status_update
# --------------------------------------------------------------------------- #
def test_status_update_none_is_noop():
    st = _state()
    st, cmds = orch.on_status_update(st, None)
    assert cmds == []


def test_status_update_idle():
    st = _state()
    done = _action([HloStatus.finished])
    st, cmds = orch.on_status_update(st, _server_model(done))
    assert st.orch_state == OrchStatus.idle
    assert any(isinstance(c, BroadcastGlobalStatus) for c in cmds)


def test_status_update_busy():
    st = _state()
    active = _action([HloStatus.active])
    st, _ = orch.on_status_update(st, _server_model(active))
    assert st.orch_state == OrchStatus.busy


def test_status_update_error_when_started():
    st = _state()
    st.loop_state = LoopStatus.started
    errored = _action([HloStatus.finished, HloStatus.errored])
    st, _ = orch.on_status_update(st, _server_model(errored))
    assert st.orch_state == OrchStatus.error


def test_status_update_estop_when_started():
    st = _state()
    st.loop_state = LoopStatus.started
    estopped = _action([HloStatus.finished, HloStatus.estopped])
    st, cmds = orch.on_status_update(st, _server_model(estopped))
    assert st.loop_state == LoopStatus.estopped
    assert any(isinstance(c, EstopServers) for c in cmds)


def test_status_update_error_ignored_when_not_started():
    st = _state()  # stopped
    errored = _action([HloStatus.finished, HloStatus.errored])
    st, _ = orch.on_status_update(st, _server_model(errored))
    # not started -> treated as idle, not error
    assert st.orch_state == OrchStatus.idle


# --------------------------------------------------------------------------- #
# nonblocking
# --------------------------------------------------------------------------- #
def test_on_nonblocking_add_and_remove():
    st = _state()
    am = ActionModel(
        action_uuid=uuid4(),
        action_name="meas",
        action_server=SRV,
        action_status=[HloStatus.active],
        exec_id="e1",
    )
    st, cmds = orch.on_nonblocking(st, am, "h", 9)
    assert ("act", "e1", "h", 9) in st.nonblocking
    assert am.action_uuid in st.action_history
    assert any(isinstance(c, BroadcastGlobalStatus) for c in cmds)
    # now report finished -> removed
    am.action_status = [HloStatus.finished]
    st, _ = orch.on_nonblocking(st, am, "h", 9)
    assert ("act", "e1", "h", 9) not in st.nonblocking


def test_on_nonblocking_records_experiment_context():
    exp = RunExperiment(experiment_uuid=uuid4(), experiment_name="myexp")
    seq = RunSequence(sequence_uuid=uuid4(), sequence_name="myseq")
    st = _state(active_experiment=exp, active_sequence=seq)
    am = ActionModel(
        action_uuid=uuid4(),
        action_name="meas",
        action_server=SRV,
        experiment_uuid=exp.experiment_uuid,
        action_status=[HloStatus.active],
        exec_id="e2",
    )
    st, _ = orch.on_nonblocking(st, am, "h", 9)
    hist = st.action_history[am.action_uuid]
    assert hist["experiment_name"] == "myexp"
    assert hist["sequence_name"] == "myseq"


def test_clear_nonblocking_emits_stop_executor_per_entry():
    st = _state(nonblocking=[("act", "e1", "h", 9), ("act2", "e2", "h2", 10)])
    st, cmds = orch.clear_nonblocking(st)
    assert len(cmds) == 2
    assert all(isinstance(c, StopExecutor) for c in cmds)
    assert cmds[0].executor_id == "e1" and cmds[1].server_key == "act2"


# --------------------------------------------------------------------------- #
# start_condition_met (all six)
# --------------------------------------------------------------------------- #
def test_scm_no_wait():
    st = _state()
    assert orch.start_condition_met(st, _action(start_condition=ActionStartCondition.no_wait))


def test_scm_wait_for_endpoint():
    st = _state()
    a = _action(start_condition=ActionStartCondition.wait_for_endpoint, action_name="ep")
    assert orch.start_condition_met(st, a) is True
    busy = _action([HloStatus.active], action_name="ep")
    st.globalstatusmodel.update_global_with_acts(_server_model(busy, "ep"))
    assert orch.start_condition_met(st, a) is False


def test_scm_wait_for_server():
    st = _state()
    a = _action(start_condition=ActionStartCondition.wait_for_server, action_name="ep")
    assert orch.start_condition_met(st, a) is True
    busy = _action([HloStatus.active], action_name="ep")
    st.globalstatusmodel.update_global_with_acts(_server_model(busy, "ep"))
    assert orch.start_condition_met(st, a) is False


def test_scm_wait_for_orch():
    st = _state()
    a = _action(start_condition=ActionStartCondition.wait_for_orch)
    assert orch.start_condition_met(st, a) is True
    # busy "wait" endpoint on the orchestrator machine
    waitact = ActionModel(
        action_uuid=uuid4(), orchestrator=ORCH, action_server=ORCH,
        action_name="wait", action_status=[HloStatus.active],
    )
    ep = EndpointModel(endpoint_name="wait", active_dict={waitact.action_uuid: waitact})
    asm = ActionServerModel(action_server=ORCH, endpoints={"wait": ep})
    st.globalstatusmodel.update_global_with_acts(asm)
    assert orch.start_condition_met(st, a) is False


def test_scm_wait_for_previous():
    st = _state()
    prev = uuid4()
    st.last_action_uuid = prev
    a = _action(start_condition=ActionStartCondition.wait_for_previous)
    assert orch.start_condition_met(st, a) is True  # not in active_dict
    st.globalstatusmodel.active_dict[prev] = _action([HloStatus.active])
    assert orch.start_condition_met(st, a) is False


def test_scm_wait_for_all():
    st = _state()
    a = _action(start_condition=ActionStartCondition.wait_for_all)
    assert orch.start_condition_met(st, a) is True
    busy = _action([HloStatus.active])
    st.globalstatusmodel.update_global_with_acts(_server_model(busy))
    assert orch.start_condition_met(st, a) is False


# --------------------------------------------------------------------------- #
# history helpers
# --------------------------------------------------------------------------- #
def test_register_and_track_uuid():
    st = _state()
    u = uuid4()
    orch.register_action_uuid(st, u, {"a": 1})
    assert st.action_history[u] == {"a": 1}
    orch.register_action_uuid(st, u, {"b": 2})
    assert st.action_history[u] == {"a": 1, "b": 2}
    orch.track_action_uuid(st, u)
    assert st.last_action_uuid == u


def test_register_obj_uuid_each_map():
    st = _state()
    su, eu = uuid4(), uuid4()
    orch.register_obj_uuid(st, su, {"x": 1}, "sequence")
    orch.register_obj_uuid(st, eu, {"y": 2}, "experiment")
    assert st.sequence_history[su] == {"x": 1}
    assert st.experiment_history[eu] == {"y": 2}


# --------------------------------------------------------------------------- #
# dispatch_sequence
# --------------------------------------------------------------------------- #
def test_dispatch_sequence_empty_noop():
    st = _state()
    st, cmds = orch.dispatch_sequence(st, now=NOW, uuid=SEED)
    assert cmds == []


def test_dispatch_sequence_emits_expand_when_no_result():
    seq = RunSequence(sequence_name="myseq")
    st = _state(sequence_dq=[seq])
    st, cmds = orch.dispatch_sequence(st, now=NOW, uuid=SEED)
    assert st.active_sequence is seq
    assert seq.sequence_uuid == SEED
    assert seq.sequence_timestamp == NOW
    assert st.active_run_id == SEED
    assert seq.sequence_uuid in st.sequence_history
    assert any(isinstance(c, ExpandSequence) for c in cmds)
    assert any(isinstance(c, PersistMeta) and c.kind == "seq" for c in cmds)


def test_dispatch_sequence_with_global_fold_and_result():
    seq = RunSequence(
        sequence_name="myseq",
        from_global_seq_params={"gk": "dest"},
        sequence_params={},
    )
    st = _state(sequence_dq=[seq], global_params={"gk": 42})
    planned = [ExperimentModel(experiment_name="e1")]
    st, cmds = orch.dispatch_sequence(st, now=NOW, uuid=SEED, expand_result=planned)
    assert seq.sequence_params["dest"] == 42
    assert seq.planned_experiments == planned
    assert not any(isinstance(c, ExpandSequence) for c in cmds)


def test_dispatch_sequence_uses_sequence_run_id():
    rid = uuid4()
    seq = RunSequence(sequence_name="s", run_id=rid)
    st = _state(sequence_dq=[seq])
    st, _ = orch.dispatch_sequence(st, now=NOW, uuid=SEED)
    assert st.active_run_id == rid


def test_dispatch_sequence_retains_prior_as_last():
    prior = RunSequence(sequence_name="old", sequence_uuid=uuid4())
    seq = RunSequence(sequence_name="new")
    st = _state(sequence_dq=[seq], active_sequence=prior)
    st, _ = orch.dispatch_sequence(st, now=NOW, uuid=SEED)
    assert st.last_sequence is prior
    assert st.active_sequence is seq


def test_dispatch_sequence_stamps_sequence_order_zero_first():
    seq = RunSequence(sequence_name="s0")
    st = _state(sequence_dq=[seq])
    st, _ = orch.dispatch_sequence(st, now=NOW, uuid=SEED)
    assert seq.sequence_order == 0
    assert st.active_run_seq_counter == 0


def test_dispatch_sequence_order_increments_within_same_run():
    s0 = RunSequence(sequence_name="s0")
    s1 = RunSequence(sequence_name="s1")
    st = _state(sequence_dq=[s0, s1])
    st, _ = orch.dispatch_sequence(st, now=NOW, uuid=SEED)        # seeds active_run_id
    st, _ = orch.dispatch_sequence(st, now=NOW, uuid=SEED)        # same run -> increment
    assert s0.sequence_order == 0
    assert s1.sequence_order == 1


def test_dispatch_sequence_order_resets_when_run_id_changes():
    s0 = RunSequence(sequence_name="s0")
    st = _state(sequence_dq=[s0])
    st, _ = orch.dispatch_sequence(st, now=NOW, uuid=SEED)
    assert s0.sequence_order == 0
    # a stop-with-reset (or estop) drops active_run_id -> next seq is a new run
    st.active_run_id = None
    s1 = RunSequence(sequence_name="s1")
    st.sequence_dq = [s1]
    st, _ = orch.dispatch_sequence(st, now=NOW, uuid=SEED)
    assert s1.sequence_order == 0


# --------------------------------------------------------------------------- #
# dispatch_experiment
# --------------------------------------------------------------------------- #
def test_dispatch_experiment_emits_expand_when_no_result():
    exp = RunExperiment(experiment_name="myexp")
    seq = RunSequence(sequence_uuid=uuid4())
    st = _state(experiment_dq=[exp], active_sequence=seq)
    st, cmds = orch.dispatch_experiment(st, now=NOW, uuid=SEED)
    assert st.active_experiment is exp
    assert exp.experiment_uuid == SEED
    assert exp.sequence_uuid == seq.sequence_uuid
    assert st.active_seq_exp_counter == 1
    assert exp.experiment_uuid in st.globalstatusmodel.counter_dispatched_actions
    assert exp.experiment_uuid in st.experiment_history
    assert any(isinstance(c, ExpandExperiment) for c in cmds)
    assert any(isinstance(c, PersistMeta) and c.kind == "exp" for c in cmds)


def test_dispatch_experiment_with_global_fold_and_staged_actions():
    exp = RunExperiment(
        experiment_name="myexp",
        from_global_exp_params={"gk": "dest"},
    )
    st = _state(experiment_dq=[exp], global_params={"gk": 7}, active_run_id=uuid4())
    acts = [_action(action_name="a0"), _action(action_name="a1")]
    st, cmds = orch.dispatch_experiment(st, now=NOW, uuid=SEED, expand_result=acts)
    assert exp.experiment_params["dest"] == 7
    assert len(st.action_dq) == 2
    assert st.action_dq[0].action_order == 0 and st.action_dq[1].action_order == 1
    assert st.action_dq[0].action_uuid is not None
    assert st.action_dq[0].experiment_uuid == exp.experiment_uuid
    assert exp.run_id == st.active_run_id
    assert not any(isinstance(c, ExpandExperiment) for c in cmds)


def test_dispatch_experiment_assigns_uuid_to_unidentified_actions():
    exp = RunExperiment(experiment_name="myexp")
    st = _state(experiment_dq=[exp])
    acts = [RunAction(action_uuid=None, orchestrator=ORCH, action_name="a0"),
            RunAction(action_uuid=None, orchestrator=ORCH, action_name="a1")]
    st, _ = orch.dispatch_experiment(st, now=NOW, uuid=SEED, expand_result=acts)
    assert st.action_dq[0].action_uuid is not None
    assert st.action_dq[1].action_uuid is not None
    assert st.action_dq[0].action_uuid != st.action_dq[1].action_uuid


def test_dispatch_experiment_empty_noop():
    st = _state()
    st, cmds = orch.dispatch_experiment(st, now=NOW, uuid=SEED)
    assert cmds == []


def test_dispatch_experiment_retains_prior_as_last():
    prior = RunExperiment(experiment_uuid=uuid4())
    exp = RunExperiment(experiment_name="new")
    st = _state(experiment_dq=[exp], active_experiment=prior)
    st, _ = orch.dispatch_experiment(st, now=NOW, uuid=SEED)
    assert st.last_experiment is prior


def test_dispatch_experiment_stamps_experiment_order():
    exp = RunExperiment(experiment_name="e0")
    seq = RunSequence(sequence_uuid=uuid4())
    st = _state(experiment_dq=[exp], active_sequence=seq)
    st, _ = orch.dispatch_experiment(st, now=NOW, uuid=SEED)
    assert exp.experiment_order == 0
    assert st.active_seq_exp_counter == 1


def test_dispatch_experiment_order_increments_then_resets_per_sequence():
    seq_a = RunSequence(sequence_uuid=uuid4())
    e0 = RunExperiment(experiment_name="e0")
    e1 = RunExperiment(experiment_name="e1")
    st = _state(experiment_dq=[e0, e1], active_sequence=seq_a)
    st, _ = orch.dispatch_experiment(st, now=NOW, uuid=SEED)
    st, _ = orch.dispatch_experiment(st, now=NOW, uuid=SEED)
    assert e0.experiment_order == 0
    assert e1.experiment_order == 1

    # a new sequence resets the per-sequence counter -> order restarts at 0
    seq_b = RunSequence(sequence_uuid=uuid4())
    st.sequence_dq = [seq_b]
    st, _ = orch.dispatch_sequence(st, now=NOW, uuid=SEED)
    e2 = RunExperiment(experiment_name="e2")
    st.experiment_dq = [e2]
    st, _ = orch.dispatch_experiment(st, now=NOW, uuid=SEED)
    assert e2.experiment_order == 0


def test_dispatch_experiment_parentless_resets_order_per_synth_sequence():
    # A parentless experiment (no active_sequence) synthesizes a one-experiment
    # wrapper sequence -> experiment_order 0.
    e0 = RunExperiment(experiment_name="bare0")
    st = _state(experiment_dq=[e0])
    st, _ = orch.dispatch_experiment(st, now=NOW, uuid=SEED)
    assert e0.experiment_order == 0
    assert st.active_seq_exp_counter == 1

    # The next parentless experiment (active_sequence cleared, e.g. prior synth
    # seq finished) synthesizes a FRESH wrapper sequence -> order resets to 0,
    # not the stale counter value 1.
    st.active_sequence = None
    e1 = RunExperiment(experiment_name="bare1")
    st.experiment_dq = [e1]
    st, _ = orch.dispatch_experiment(st, now=NOW, uuid=SEED)
    assert e1.experiment_order == 0


# --------------------------------------------------------------------------- #
# Task 5a — dispatch-time output-dir stamping (nested, deterministic)
# --------------------------------------------------------------------------- #
def _no_none_segment(path) -> bool:
    return "None" not in str(path).split("/")


def test_dispatch_sequence_stamps_nested_output_dir():
    seq = RunSequence(sequence_name="myseq")
    st = _state(sequence_dq=[seq])
    st, _ = orch.dispatch_sequence(st, now=NOW, uuid=SEED)
    assert seq.sequence_output_dir is not None
    assert _no_none_segment(seq.sequence_output_dir)
    # %y.%U/<date>/HHMMSS__name__label nested layout
    assert str(seq.sequence_output_dir) == "26.25/0622/150000__myseq__noLabel"


def test_dispatch_sequence_keeps_existing_output_dir():
    seq = RunSequence(sequence_name="myseq", sequence_output_dir="preset/dir")
    st = _state(sequence_dq=[seq])
    st, _ = orch.dispatch_sequence(st, now=NOW, uuid=SEED)
    assert str(seq.sequence_output_dir) == "preset/dir"


def test_dispatch_experiment_stamps_nested_output_dirs_and_threads_parent():
    seq = RunSequence(sequence_name="myseq")
    st = _state(sequence_dq=[seq])
    st, _ = orch.dispatch_sequence(st, now=NOW, uuid=SEED)

    exp = RunExperiment(experiment_name="myexp")
    st.experiment_dq = [exp]
    acts = [_action(action_name="a0"), _action(action_name="a1")]
    st, _ = orch.dispatch_experiment(st, now=NOW, uuid=SEED, expand_result=acts)

    # exp inherits seq identity (ExperimentModel has no sequence_output_dir field;
    # the nested seq dir is folded into experiment_output_dir instead)
    assert exp.sequence_uuid == seq.sequence_uuid
    assert exp.experiment_output_dir is not None
    assert str(exp.experiment_output_dir).startswith(str(seq.sequence_output_dir))
    assert _no_none_segment(exp.experiment_output_dir)
    assert str(exp.experiment_output_dir) == (
        "26.25/0622/150000__myseq__noLabel/260622.150000__myexp"
    )

    # each staged action fully stamped with no None segment
    for i, act in enumerate(st.action_dq):
        assert act.sequence_output_dir == seq.sequence_output_dir
        assert act.sequence_uuid == seq.sequence_uuid
        assert act.experiment_output_dir == exp.experiment_output_dir
        assert act.experiment_uuid == exp.experiment_uuid
        assert act.action_timestamp == NOW
        assert act.action_output_dir is not None
        assert _no_none_segment(act.action_output_dir)
        assert str(act.action_output_dir) == (
            f"26.25/0622/150000__myseq__noLabel/260622.150000__myexp/"
            f"{i}__0__act__a{i}"
        )


def test_dispatch_experiment_preserves_deterministic_action_uuid():
    """Stamping output_dirs must not perturb the deterministic uuid/now seeding."""
    seq = RunSequence(sequence_name="myseq")
    st = _state(sequence_dq=[seq])
    st, _ = orch.dispatch_sequence(st, now=NOW, uuid=SEED)
    exp = RunExperiment(experiment_name="myexp")
    st.experiment_dq = [exp]
    acts = [
        RunAction(action_uuid=None, orchestrator=ORCH, action_server=SRV, action_name="a0"),
        RunAction(action_uuid=None, orchestrator=ORCH, action_server=SRV, action_name="a1"),
    ]
    st, _ = orch.dispatch_experiment(st, now=NOW, uuid=SEED, expand_result=acts)
    # deterministic per-index uuid derived from the injected seed
    assert st.action_dq[0].action_uuid == UUID(int=(SEED.int + 1 + 0) % (1 << 128))
    assert st.action_dq[1].action_uuid == UUID(int=(SEED.int + 1 + 1) % (1 << 128))


def test_dispatch_experiment_keeps_injected_action_timestamp():
    """A pre-set action_timestamp must be preserved, not overwritten by `now`."""
    seq = RunSequence(sequence_name="myseq")
    st = _state(sequence_dq=[seq])
    st, _ = orch.dispatch_sequence(st, now=NOW, uuid=SEED)
    exp = RunExperiment(experiment_name="myexp")
    st.experiment_dq = [exp]
    preset = datetime(2020, 1, 1, 0, 0, 0)
    acts = [_action(action_name="a0", action_timestamp=preset)]
    st, _ = orch.dispatch_experiment(st, now=NOW, uuid=SEED, expand_result=acts)
    assert st.action_dq[0].action_timestamp == preset


# --------------------------------------------------------------------------- #
# C2: parentless experiment (no active_sequence) synthesizes a sequence
# --------------------------------------------------------------------------- #


def test_dispatch_experiment_parentless_yields_non_none_exp_output_dir():
    """When active_sequence is None, experiment_output_dir must be non-None and
    must not contain a 'None' path segment."""
    exp = RunExperiment(experiment_name="bareexp")
    acts = [_action(action_name="a0"), _action(action_name="a1")]
    st = _state(experiment_dq=[exp])
    assert st.active_sequence is None
    st, cmds = orch.dispatch_experiment(st, now=NOW, uuid=SEED, expand_result=acts)
    assert exp.experiment_output_dir is not None
    assert _no_none_segment(exp.experiment_output_dir)


def test_dispatch_experiment_parentless_staged_actions_have_valid_output_dirs():
    """Staged actions under a parentless experiment must have no 'None' in
    action_output_dir."""
    exp = RunExperiment(experiment_name="bareexp")
    acts = [_action(action_name="a0"), _action(action_name="a1")]
    st = _state(experiment_dq=[exp])
    st, _ = orch.dispatch_experiment(st, now=NOW, uuid=SEED, expand_result=acts)
    for act in st.action_dq:
        assert act.action_output_dir is not None
        assert _no_none_segment(act.action_output_dir)


def test_dispatch_experiment_parentless_sets_active_sequence():
    """A synthetic RunSequence must be created and set as active_sequence."""
    exp = RunExperiment(experiment_name="bareexp")
    st = _state(experiment_dq=[exp])
    assert st.active_sequence is None
    st, _ = orch.dispatch_experiment(st, now=NOW, uuid=SEED)
    assert st.active_sequence is not None
    assert st.active_sequence.sequence_output_dir is not None
    assert _no_none_segment(st.active_sequence.sequence_output_dir)


def test_dispatch_experiment_parentless_emits_persist_meta_seq():
    """A PersistMeta(kind='seq') command must be among the returned commands."""
    exp = RunExperiment(experiment_name="bareexp")
    st = _state(experiment_dq=[exp])
    st, cmds = orch.dispatch_experiment(st, now=NOW, uuid=SEED)
    assert any(isinstance(c, PersistMeta) and c.kind == "seq" for c in cmds)


def test_dispatch_experiment_parentless_seq_uuid_distinct_from_exp_uuid():
    """Synthetic sequence uuid must differ from the experiment uuid."""
    exp = RunExperiment(experiment_name="bareexp")
    st = _state(experiment_dq=[exp])
    st, _ = orch.dispatch_experiment(st, now=NOW, uuid=SEED)
    assert st.active_sequence.sequence_uuid != exp.experiment_uuid


def test_dispatch_experiment_parentless_syn_uuid_no_collision_with_actions():
    """Regression: synthetic sequence uuid must not collide with the experiment uuid
    OR with any staged action uuid when expand_result has >=1 action."""
    exp = RunExperiment(experiment_name="bareexp")
    acts = [_action(action_name="a0"), _action(action_name="a1")]
    st = _state(experiment_dq=[exp])
    st, _ = orch.dispatch_experiment(st, now=NOW, uuid=SEED, expand_result=acts)
    syn_uuid = st.active_sequence.sequence_uuid
    action_uuids = {act.action_uuid for act in st.action_dq}
    assert syn_uuid != exp.experiment_uuid
    assert syn_uuid not in action_uuids


def test_dispatch_experiment_parentless_stamps_sequence_order_zero():
    """The synthesized wrapper sequence gets sequence_order=0 and derives
    active_run_id from its own uuid (parity with the sequence-driven path)."""
    exp = RunExperiment(experiment_name="bareexp")
    st = _state(experiment_dq=[exp])
    st, _ = orch.dispatch_experiment(st, now=NOW, uuid=SEED)
    assert st.active_sequence.sequence_order == 0
    assert st.active_run_seq_counter == 0
    assert st.active_run_id == st.active_sequence.sequence_uuid


def test_dispatch_experiment_parentless_order_increments_within_same_run():
    """Two consecutive parentless wrappers in the same run (active_run_id held)
    increment sequence_order: 0 then 1."""
    exp0 = RunExperiment(experiment_name="bareexp0")
    st = _state(experiment_dq=[exp0])
    st, _ = orch.dispatch_experiment(st, now=NOW, uuid=SEED)
    seq0 = st.active_sequence
    # finish the wrapper sequence so the next parentless exp synthesizes a fresh
    # one, but keep active_run_id (mirrors a stop without reset_run_id)
    st.active_sequence = None
    exp1 = RunExperiment(experiment_name="bareexp1")
    st.experiment_dq = [exp1]
    st, _ = orch.dispatch_experiment(st, now=NOW, uuid=UUID(int=2000))
    seq1 = st.active_sequence
    assert seq0.sequence_order == 0
    assert seq1.sequence_order == 1


def test_dispatch_experiment_parentless_order_resets_after_run_reset():
    """After active_run_id is dropped (stop-with-reset / estop), the next
    parentless wrapper resets sequence_order to 0."""
    exp0 = RunExperiment(experiment_name="bareexp0")
    st = _state(experiment_dq=[exp0])
    st, _ = orch.dispatch_experiment(st, now=NOW, uuid=SEED)
    assert st.active_sequence.sequence_order == 0
    # stop-with-reset / estop drops both active_sequence and active_run_id
    st.active_sequence = None
    st.active_run_id = None
    exp1 = RunExperiment(experiment_name="bareexp1")
    st.experiment_dq = [exp1]
    st, _ = orch.dispatch_experiment(st, now=NOW, uuid=UUID(int=2000))
    assert st.active_sequence.sequence_order == 0


def test_dispatch_experiment_with_active_sequence_unchanged():
    """Regression: when active_sequence is already set, no extra synthesis occurs
    and output dirs nest under the existing sequence (unchanged behaviour)."""
    seq = RunSequence(sequence_name="myseq")
    st = _state(sequence_dq=[seq])
    st, _ = orch.dispatch_sequence(st, now=NOW, uuid=SEED)
    seq_uuid_before = st.active_sequence.sequence_uuid

    exp = RunExperiment(experiment_name="myexp")
    st.experiment_dq = [exp]
    acts = [_action(action_name="a0")]
    st, cmds = orch.dispatch_experiment(st, now=NOW, uuid=SEED, expand_result=acts)

    # same sequence — no new one synthesized
    assert st.active_sequence.sequence_uuid == seq_uuid_before
    # only one PersistMeta(kind="seq") must NOT appear (seq was already dispatched)
    assert not any(isinstance(c, PersistMeta) and c.kind == "seq" for c in cmds)
    # output dirs nest under the existing seq
    assert str(exp.experiment_output_dir).startswith(str(seq.sequence_output_dir))
    assert _no_none_segment(exp.experiment_output_dir)
    assert _no_none_segment(st.action_dq[0].action_output_dir)


# --------------------------------------------------------------------------- #
# dispatch_action
# --------------------------------------------------------------------------- #
def test_dispatch_action_empty_noop():
    st = _state()
    st, cmds = orch.dispatch_action(st, now=NOW, uuid=SEED)
    assert cmds == []


def test_dispatch_action_happy_path():
    exp = RunExperiment(experiment_uuid=uuid4())
    st = _state(active_experiment=exp, active_run_id=uuid4())
    st.globalstatusmodel.new_experiment(exp.experiment_uuid)
    a = RunAction(
        action_uuid=None,
        orchestrator=ORCH,
        action_server=SRV,
        action_name="meas",
        start_condition=ActionStartCondition.no_wait,
    )
    st.action_dq = [a]
    st, cmds = orch.dispatch_action(st, now=NOW, uuid=SEED)
    disp = [c for c in cmds if isinstance(c, DispatchAction)]
    assert disp and disp[0].action is a
    assert a.action_uuid == SEED
    assert a.action_timestamp == NOW
    assert a.run_id == st.active_run_id
    assert a.orch_submit_order == 0
    assert st.globalstatusmodel.counter_dispatched_actions[exp.experiment_uuid] == 1
    assert a.action_uuid in st.globalstatusmodel.active_dict
    assert st.last_action_uuid == a.action_uuid


def test_dispatch_action_global_fold_in():
    st = _state(global_params={"gk": "v"})
    a = _action(
        start_condition=ActionStartCondition.no_wait,
        from_global_act_params={"gk": "dest"},
    )
    st.action_dq = [a]
    st, _ = orch.dispatch_action(st, now=NOW, uuid=SEED)
    assert a.action_params["dest"] == "v"


def test_dispatch_action_requeues_when_condition_unmet():
    st = _state()
    # wait_for_all but a busy action -> not met
    busy = _action([HloStatus.active])
    st.globalstatusmodel.update_global_with_acts(_server_model(busy))
    a = _action(start_condition=ActionStartCondition.wait_for_all, action_name="x")
    st.action_dq = [a]
    st, cmds = orch.dispatch_action(st, now=NOW, uuid=SEED)
    assert cmds == []
    assert st.action_dq[0] is a  # re-queued at front


def test_dispatch_action_skip_intent_clears_queue():
    st = _state(action_dq=[_action(), _action()])
    st.loop_intent = LoopIntent.skip
    st, cmds = orch.dispatch_action(st, now=NOW, uuid=SEED)
    assert st.action_dq == []
    assert st.loop_intent == LoopIntent.none
    assert any(isinstance(c, BroadcastGlobalStatus) for c in cmds)


def test_dispatch_action_estop_intent():
    st = _state(action_dq=[_action()])
    st.loop_intent = LoopIntent.estop
    st, cmds = orch.dispatch_action(st, now=NOW, uuid=SEED)
    assert st.action_dq == []
    assert st.loop_state == LoopStatus.estopped
    assert any(isinstance(c, EstopServers) for c in cmds)


def test_dispatch_action_nonblocking_not_self_registered():
    st = _state(active_experiment=RunExperiment(experiment_uuid=uuid4()))
    st.globalstatusmodel.new_experiment(st.active_experiment.experiment_uuid)
    a = _action(start_condition=ActionStartCondition.no_wait, nonblocking=True)
    st.action_dq = [a]
    st, cmds = orch.dispatch_action(st, now=NOW, uuid=SEED)
    assert a.action_uuid not in st.globalstatusmodel.active_dict
    assert [c for c in cmds if isinstance(c, DispatchAction)][0].nonblocking is True


# --------------------------------------------------------------------------- #
# on_dispatch_result
# --------------------------------------------------------------------------- #
def test_on_dispatch_result_error_requeues_and_stops():
    st = _state()
    st.loop_state = LoopStatus.started
    a = _action(action_name="x")
    st, cmds = orch.on_dispatch_result(st, a, ErrorCodes.http)
    assert st.loop_intent == LoopIntent.stop
    assert st.action_dq[0] is a
    assert "Pausing orch" in st.current_stop_message


def test_on_dispatch_result_none_action_stops():
    st = _state()
    st.loop_state = LoopStatus.started
    st, cmds = orch.on_dispatch_result(st, None, ErrorCodes.none)
    assert st.loop_intent == LoopIntent.stop


def test_on_dispatch_result_action_error_estops():
    st = _state()
    st.loop_state = LoopStatus.started
    a = _action(action_name="x")
    a.error_code = ErrorCodes.critical_error
    st, cmds = orch.on_dispatch_result(st, a, ErrorCodes.none)
    assert st.loop_state == LoopStatus.estopped
    assert any(isinstance(c, EstopServers) for c in cmds)


def test_on_dispatch_result_happy_folds_globals():
    exp = RunExperiment(experiment_uuid=uuid4())
    st = _state(active_experiment=exp)
    a = _action(action_name="x")
    a.action_params = {"src": 99}
    a.to_global_params = {"src": "gk"}
    st, cmds = orch.on_dispatch_result(st, a, ErrorCodes.none)
    assert st.global_params["gk"] == 99
    assert exp.dispatched_actions == [a]
    assert cmds == []


# --------------------------------------------------------------------------- #
# BUG A regression: on_status_update registers actions into action_history
# (legacy Orch.update_status did this; the SP-ORCH-5 port dropped it, so the
# operator's Action history table was always empty).
# --------------------------------------------------------------------------- #
def test_on_status_update_registers_finished_action_in_history():
    st = _state()
    st.loop_state = LoopStatus.started
    auuid = uuid4()
    finished = _action(
        [HloStatus.finished],
        action_uuid=auuid,
        action_name="acquire_data",
        action_timestamp=NOW,
    )
    ep = EndpointModel(
        endpoint_name="acquire_data",
        active_dict={},
        nonactive_dict={HloStatus.finished: {auuid: finished}},
    )
    asm = ActionServerModel(action_server=SRV, endpoints={"acquire_data": ep})
    orch.on_status_update(st, asm)
    assert auuid in st.action_history
    entry = st.action_history[auuid]
    assert entry["action_name"] == "acquire_data"
    assert entry["action_server"] == "act"
    assert entry["action_timestamp"] is not None


def test_on_status_update_registers_active_then_updates_on_finish():
    st = _state()
    st.loop_state = LoopStatus.started
    auuid = uuid4()
    active = _action([HloStatus.active], action_uuid=auuid, action_name="acquire_data")
    orch.on_status_update(st, _server_model(active, endpoint_name="acquire_data"))
    assert auuid in st.action_history  # active actions appear too
    finished = _action(
        [HloStatus.finished],
        action_uuid=auuid,
        action_name="acquire_data",
        action_timestamp=NOW,
        action_finished_timestamp=NOW,
    )
    ep = EndpointModel(
        endpoint_name="acquire_data",
        active_dict={},
        nonactive_dict={HloStatus.finished: {auuid: finished}},
    )
    orch.on_status_update(st, ActionServerModel(action_server=SRV, endpoints={"acquire_data": ep}))
    # update-or-insert: same uuid, now carrying a finished timestamp
    assert st.action_history[auuid]["action_finished_timestamp"] is not None


def test_on_status_update_attributes_experiment_context_when_matching():
    exp_uuid = uuid4()
    exp = RunExperiment(experiment_uuid=exp_uuid, experiment_name="te")
    st = _state(active_experiment=exp)
    st.loop_state = LoopStatus.started
    auuid = uuid4()
    act = _action([HloStatus.active], action_uuid=auuid, exp_uuid=exp_uuid, action_name="x")
    orch.on_status_update(st, _server_model(act, endpoint_name="x"))
    assert st.action_history[auuid]["experiment_name"] == "te"


def test_on_nonblocking_dedups_duplicate_active_reports():
    """A doubly-delivered active report must track the executor only once."""
    st = _state()
    am = _action([HloStatus.active], action_uuid=uuid4(), action_name="nb")
    am.exec_id = "nb exec1"
    orch.on_nonblocking(st, am, "h", 9)
    orch.on_nonblocking(st, am, "h", 9)  # duplicate delivery
    assert sum(1 for t in st.nonblocking if t[1] == "nb exec1") == 1
    # a single finish report removes it cleanly (no orphan left behind)
    am.action_status = [HloStatus.finished]
    orch.on_nonblocking(st, am, "h", 9)
    assert not any(t[1] == "nb exec1" for t in st.nonblocking)


# --------------------------------------------------------------------------- #
# BUG: experiments must run SERIALLY — finish the active experiment before
# dispatching the next queued one (decide_next prioritises FINISH_EXPERIMENT).
# Previously the next experiment dispatched as soon as actions were idle,
# overwriting active_experiment so prior experiments never finished.
# --------------------------------------------------------------------------- #
def test_decide_next_finishes_active_experiment_before_next_queued():
    st = _state(active_experiment=RunExperiment(), experiment_dq=[RunExperiment()])
    # actions idle, active experiment present, more experiments queued ->
    # FINISH the active one first (not DISPATCH the next)
    assert orch.decide_next(st) == OrchDecision.FINISH_EXPERIMENT


def test_decide_next_dispatches_next_experiment_after_active_cleared():
    st = _state(active_experiment=None, experiment_dq=[RunExperiment()])
    assert orch.decide_next(st) == OrchDecision.DISPATCH_EXPERIMENT


def test_decide_next_finishes_active_sequence_before_next_queued():
    st = _state(active_sequence=RunSequence(), sequence_dq=[RunSequence()])
    # no active/queued experiments -> finish the active sequence before the next
    assert orch.decide_next(st) == OrchDecision.FINISH_SEQUENCE


def test_decide_next_active_experiment_waits_while_actions_busy():
    st = _state(active_experiment=RunExperiment(), experiment_dq=[RunExperiment()])
    active = _action([HloStatus.active])
    st.globalstatusmodel.update_global_with_acts(_server_model(active))
    # busy -> WAIT regardless of the finish/dispatch priority
    assert orch.decide_next(st) == OrchDecision.WAIT


# --------------------------------------------------------------------------- #
# complete_experiment / complete_sequence update history status to "finished"
# (operator history table showed dispatched exp/seq stuck as "active").
# --------------------------------------------------------------------------- #
def test_complete_experiment_marks_history_finished():
    exp = RunExperiment(experiment_uuid=uuid4(), experiment_name="te")
    st = _state(active_experiment=exp, active_sequence=RunSequence(sequence_label="lbl"))
    # dispatch-time registration would have set "active"
    orch.register_obj_uuid(st, exp.experiment_uuid, {"experiment_status": "active"}, "experiment")
    orch.complete_experiment(st, NOW)
    assert st.experiment_history[exp.experiment_uuid]["experiment_status"] == "finished"
    assert st.experiment_history[exp.experiment_uuid]["experiment_finished_timestamp"] is not None
    assert HloStatus.finished in exp.experiment_status


def test_complete_sequence_marks_history_finished():
    seq = RunSequence(sequence_uuid=uuid4(), sequence_name="ts")
    st = _state(active_sequence=seq)
    orch.register_obj_uuid(st, seq.sequence_uuid, {"sequence_status": "active"}, "sequence")
    orch.complete_sequence(st, NOW)
    assert st.sequence_history[seq.sequence_uuid]["sequence_status"] == "finished"
    assert HloStatus.finished in seq.sequence_status


def test_complete_experiment_noop_without_active():
    st = _state(active_experiment=None)
    orch.complete_experiment(st, NOW)  # must not raise
    assert st.experiment_history == {}
