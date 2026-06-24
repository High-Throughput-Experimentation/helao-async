"""Read-side orchestrator domain ops (payloads, lists, getters)."""
from datetime import datetime
from uuid import uuid4

import pytest

from helao.framework.domain import orchestration as orch
from helao.framework.domain.orchestration import OrchState
from helao.framework.domain.run_models import RunSequence, RunExperiment, RunAction


def _seq(name="seq0"):
    return RunSequence(sequence_name=name, sequence_label="lbl",
                       sequence_uuid=uuid4(), sequence_timestamp=datetime.now())


def _exp(name="exp0"):
    return RunExperiment(experiment_name=name, experiment_uuid=uuid4(),
                         experiment_timestamp=datetime.now())


def _act(name="noop"):
    return RunAction(action_name=name, action_uuid=uuid4(),
                     action_timestamp=datetime.now())


def test_histories_payload():
    s = OrchState()
    s.action_history = {"a1": {"action_name": "noop"}}
    s.experiment_history = {"e1": {"experiment_name": "exp0"}}
    s.sequence_history = {"s1": {"sequence_name": "seq0"}}
    assert orch.histories_payload(s) == {
        "action": [("a1", {"action_name": "noop"})],
        "experiment": [("e1", {"experiment_name": "exp0"})],
        "sequence": [("s1", {"sequence_name": "seq0"})],
    }


def test_status_summary_payload():
    s = OrchState()
    s.status_summary = {"motor": ("idle", "ok")}
    assert orch.status_summary_payload(s) == {"motor": ["idle", "ok"]}


def test_step_flags_roundtrip_and_unknown():
    s = OrchState()
    assert orch.step_flags_payload(s) == {
        "actions": False, "experiments": False, "sequences": False}
    assert orch.set_step_flag(s, "actions", True) == {"actions": True}
    assert s.step_thru_actions is True
    assert orch.step_flags_payload(s)["actions"] is True
    with pytest.raises(KeyError):
        orch.set_step_flag(s, "bogus", True)


def test_queue_counts():
    s = OrchState()
    s.sequence_dq = [_seq(), _seq(), _seq()]
    s.experiment_dq = [_exp()]
    s.action_dq = []
    assert orch.queue_counts(s) == {
        "n_sequences": 3, "n_experiments": 1, "n_actions": 0}


def test_queue_object_payload_and_bounds():
    s = OrchState()
    sq = _seq("seqX")
    s.sequence_dq = [sq]
    payload = orch.queue_object_payload(s, "sequence", 0)
    assert payload.get("sequence_name") == "seqX"
    assert orch.queue_object_payload(s, "sequence", 9) == {}     # out of range
    assert orch.queue_object_payload(s, "bogus", 0) == {}        # unknown kind


def test_list_sequences_limit_and_order():
    s = OrchState()
    s.sequence_dq = [_seq("a"), _seq("b"), _seq("c")]
    rows = orch.list_sequences(s, limit=2)
    assert len(rows) == 2
    assert rows[0].sequence_name == "a"  # front-of-deque first


def test_list_actions_and_experiments():
    s = OrchState()
    s.action_dq = [_act("noop")]
    s.experiment_dq = [_exp("exp0")]
    assert len(orch.list_actions(s)) == 1
    assert len(orch.list_experiments(s)) == 1


def test_orch_state_payload_shape():
    s = OrchState()
    s.sequence_dq = [_seq(), _seq()]
    s.current_stop_message = ""
    p = orch.orch_state_payload(s)
    assert set(p) >= {"loop_state", "n_sequences", "n_experiments",
                      "n_actions", "current_stop_message"}
    assert p["n_sequences"] == 2


def test_active_and_last_getters_default_empty():
    s = OrchState()
    assert orch.get_active_sequence(s) == {}
    assert orch.get_last_experiment(s) == {}
    s.active_sequence = _seq("act_seq")
    assert orch.get_active_sequence(s).get("sequence_name") == "act_seq"


def test_latest_uuid_lists():
    s = OrchState()
    s.sequence_history = {"s1": {}, "s2": {}}
    s.experiment_history = {"e1": {}}
    s.action_history = {"a1": {}}
    assert set(orch.latest_sequence_uuids(s)) == {"s1", "s2"}
    assert orch.latest_experiment_uuids(s) == ["e1"]
    assert orch.latest_action_uuids(s) == ["a1"]
