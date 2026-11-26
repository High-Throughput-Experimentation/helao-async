"""Record shape (spec §3.1-3.2): lists leave the record, uuid lists replace them."""

import json
from uuid import UUID

from helao.core.helaodict import HelaoDict
from helao.core.models.experiment import ExperimentModel, ShortExperimentModel
from helao.core.models.sequence import SequenceModel
from helao.helpers.premodels import Action, Experiment, Sequence

U1 = UUID("00000000-0000-0000-0000-000000000001")
U2 = UUID("00000000-0000-0000-0000-000000000002")


def test_record_dict_drops_sequence_lists_clean_dict_keeps_them():
    seq = SequenceModel(
        sequence_name="s",
        planned_experiments=[ShortExperimentModel(experiment_name="e")],
        dispatched_experiments_abbr=[ShortExperimentModel(experiment_name="e")],
    )
    assert "planned_experiments" in seq.clean_dict()
    rec = seq.record_dict()
    assert "planned_experiments" not in rec
    assert "dispatched_experiments_abbr" not in rec
    assert rec["sequence_name"] == "s"


def test_record_dict_drops_experiment_lists():
    exp = ExperimentModel(
        experiment_name="e",
        planned_actions=[{"action_name": "a"}],
        dispatched_actions_abbr=[{"action_uuid": U1}],
    )
    rec = exp.record_dict()
    assert "planned_actions" not in rec and "dispatched_actions_abbr" not in rec


class _Rec(HelaoDict):
    RECORD_EXCLUDE = frozenset({"drop"})

    def __init__(self):
        self._hidden = 1
        self.keep = 2
        self.drop = 3


def test_record_dict_passes_strip_private_through():
    assert _Rec().record_dict() == {"_hidden": 1, "keep": 2}
    assert _Rec().record_dict(strip_private=True) == {"keep": 2}


def test_get_seq_fills_experiment_list_in_dispatch_order():
    seq = Sequence(sequence_name="s")
    seq.dispatched_experiments = [
        ExperimentModel(experiment_name="b", experiment_uuid=U2),
        ExperimentModel(experiment_name="a", experiment_uuid=U1),
    ]
    assert seq.get_seq().experiment_list == [U2, U1]


def test_get_seq_falls_back_to_a_directly_set_abbr_list():
    """Deployment-C converters set the abbreviated list, never the full one."""
    seq = Sequence(sequence_name="s")
    seq.dispatched_experiments_abbr = [
        ShortExperimentModel(experiment_name="a", experiment_uuid=U1)
    ]
    assert seq.get_seq().experiment_list == [U1]


def test_get_exp_action_list_keeps_dispatch_order_and_splits():
    exp = Experiment(experiment_name="e")
    exp.dispatched_actions = [
        Action(action_name="a", action_uuid=U2, action_order=0, action_split=0),
        Action(action_name="a", action_uuid=U1, action_order=0, action_split=1),
    ]
    assert exp.get_exp().action_list == [U2, U1]


def test_empty_lists_are_absent_from_the_record():
    rec = Sequence(sequence_name="s").get_seq().record_dict()
    assert "experiment_list" not in rec


def test_sequence_record_size_is_flat_in_planned_count():
    def size(n):
        planned = [
            ShortExperimentModel(
                experiment_name="e", experiment_params={"x": list(range(50))}
            )
            for _ in range(n)
        ]
        rec = SequenceModel(sequence_name="s", planned_experiments=planned)
        return len(json.dumps(rec.record_dict(), default=str))

    assert size(1) == size(200)


def test_old_record_with_lists_still_validates():
    old = {
        "sequence_name": "s",
        "planned_experiments": [{"experiment_name": "e", "experiment_params": {}}],
        "dispatched_experiments_abbr": [{"experiment_uuid": str(U1)}],
    }
    assert "planned_experiments" not in SequenceModel(**old).record_dict()
