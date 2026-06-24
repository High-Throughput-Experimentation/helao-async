"""Pure queue-mutation orchestrator domain ops."""
from datetime import datetime
from uuid import uuid4

from helao.framework.domain import orchestration as orch
from helao.framework.domain.orchestration import OrchState
from helao.framework.domain.run_models import RunSequence, RunExperiment


def _seq(name):
    return RunSequence(sequence_name=name, sequence_label="l",
                       sequence_uuid=uuid4(), sequence_timestamp=datetime.now())


def _exp(name):
    return RunExperiment(experiment_name=name, experiment_uuid=uuid4(),
                         experiment_timestamp=datetime.now())


def _names(dq):
    return [s.sequence_name for s in dq]


def test_move_sequence_reorders():
    s = OrchState()
    s.sequence_dq = [_seq("a"), _seq("b"), _seq("c")]
    orch.move_sequence(s, 0, 2)
    assert _names(s.sequence_dq) == ["b", "c", "a"]


def test_move_sequence_out_of_range_noop():
    s = OrchState()
    s.sequence_dq = [_seq("a"), _seq("b")]
    orch.move_sequence(s, 5, 0)
    assert _names(s.sequence_dq) == ["a", "b"]


def test_remove_sequence_and_bounds():
    s = OrchState()
    s.sequence_dq = [_seq("a"), _seq("b"), _seq("c")]
    orch.remove_sequence(s, 1)
    assert _names(s.sequence_dq) == ["a", "c"]
    orch.remove_sequence(s, 99)  # no-op
    assert _names(s.sequence_dq) == ["a", "c"]


def test_prepend_sequences_order_and_uuids():
    s = OrchState()
    s.sequence_dq = [_seq("existing")]
    a, b = _seq("a"), _seq("b")
    uuids = orch.prepend_sequences(s, [a, b])
    assert _names(s.sequence_dq) == ["a", "b", "existing"]
    assert uuids == [a.sequence_uuid, b.sequence_uuid]


def test_prepend_empty_noop():
    s = OrchState()
    s.sequence_dq = [_seq("x")]
    assert orch.prepend_sequences(s, []) == []
    assert _names(s.sequence_dq) == ["x"]


def test_append_and_insert_sequence():
    s = OrchState()
    s.sequence_dq = [_seq("a")]
    orch.append_sequence(s, _seq("z"))
    assert _names(s.sequence_dq) == ["a", "z"]
    orch.insert_sequence(s, _seq("m"), 1)
    assert _names(s.sequence_dq) == ["a", "m", "z"]


def test_append_and_insert_experiment():
    s = OrchState()
    s.experiment_dq = [_exp("a")]
    orch.append_experiment(s, _exp("z"))
    orch.insert_experiment(s, _exp("m"), 1)
    assert [e.experiment_name for e in s.experiment_dq] == ["a", "m", "z"]


def test_clear_ops():
    s = OrchState()
    s.sequence_dq = [_seq("a")]
    s.experiment_dq = [_exp("b")]
    s.action_dq = ["x"]
    orch.clear_sequences(s)
    orch.clear_experiments(s)
    orch.clear_actions(s)
    assert s.sequence_dq == [] and s.experiment_dq == [] and s.action_dq == []
