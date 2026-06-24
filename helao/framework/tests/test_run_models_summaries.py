"""get_seq/get_exp summary snapshots on the orchestrator run_models."""
from datetime import datetime
from uuid import uuid4

from helao.framework.domain.run_models import RunSequence, RunExperiment
from helao.framework.models.sequence import SequenceModel
from helao.framework.models.experiment import ExperimentModel


def _seq():
    return RunSequence(sequence_name="seq0", sequence_label="lbl",
                       sequence_uuid=uuid4(), sequence_timestamp=datetime.now())


def _exp():
    return RunExperiment(experiment_name="exp0", experiment_uuid=uuid4(),
                         experiment_timestamp=datetime.now())


def test_get_seq_returns_sequence_model():
    s = _seq()
    out = s.get_seq()
    assert isinstance(out, SequenceModel)
    assert out.sequence_name == "seq0"
    assert out.sequence_label == "lbl"


def test_get_exp_returns_experiment_model():
    e = _exp()
    out = e.get_exp()
    assert isinstance(out, ExperimentModel)
    assert out.experiment_name == "exp0"
