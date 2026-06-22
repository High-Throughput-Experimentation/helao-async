"""Tests for the flat runtime run-models (domain/run_models.py).

The legacy runtime ``Action`` (helao.helpers.premodels.Action) was a triple
diamond ``Action(Experiment(Sequence), ActionModel)``. The framework flattens
this to single inheritance: ``RunAction(ActionModel)`` with explicit, denormalised
sequence/experiment provenance fields. These tests assert the flattened model
carries EVERY field the legacy runtime Action exposed, that there is NO multiple
inheritance, and that serialization round-trips.

The expected legacy field set is derived dynamically from premodels so the test
tracks the source of truth. (Tests may import premodels; the domain module must
not — that is enforced by the boundary test.)
"""

from helao.framework.models.action import ActionModel
from helao.framework.models.experiment import ExperimentModel
from helao.framework.models.sequence import SequenceModel
from helao.framework.domain.run_models import (
    RunAction,
    RunExperiment,
    RunSequence,
)


def _legacy_action_fields() -> set:
    from helao.helpers.premodels import Action

    return set(Action.model_fields.keys())


def test_runaction_single_inheritance_no_diamond():
    assert RunAction.__bases__ == (ActionModel,)
    assert RunExperiment.__bases__ == (ExperimentModel,)
    assert RunSequence.__bases__ == (SequenceModel,)


def test_runaction_has_all_legacy_action_fields():
    expected = _legacy_action_fields()
    actual = set(RunAction.model_fields.keys())
    missing = expected - actual
    assert missing == set(), f"RunAction missing legacy fields: {sorted(missing)}"
    assert expected <= actual


def test_runaction_carries_runtime_only_fields():
    fields = RunAction.model_fields
    assert "file_conn_keys" in fields
    assert "data_stream_status" in fields
    # explicit sequence/experiment provenance now lives on RunAction
    for prov in (
        "sequence_uuid",
        "sequence_name",
        "sequence_timestamp",
        "sequence_label",
        "sequence_output_dir",
        "experiment_name",
        "experiment_output_dir",
    ):
        assert prov in fields, f"RunAction missing provenance field {prov}"


def test_runaction_constructible_and_defaults():
    ra = RunAction()
    assert ra.file_conn_keys == []
    assert ra.data_stream_status is None
    assert ra.sequence_label == "noLabel"
    assert ra.action_split == 0


def test_runaction_round_trips():
    ra = RunAction(
        action_name="noop",
        sequence_name="seq--noop",
        experiment_name="exp--noop",
        sequence_label="manual",
    )
    dumped = ra.model_dump()
    rebuilt = RunAction(**dumped)
    assert rebuilt.model_dump() == dumped
    assert rebuilt.action_name == "noop"
    assert rebuilt.sequence_name == "seq--noop"


def test_runsequence_runtime_tally():
    assert "dispatched_experiments" in RunSequence.model_fields
    rs = RunSequence()
    assert rs.dispatched_experiments == []


def test_runexperiment_runtime_tally():
    assert "dispatched_actions" in RunExperiment.model_fields
    re = RunExperiment()
    assert re.dispatched_actions == []
