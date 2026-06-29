"""Tests for the sequence/experiment/action model bases and their Short* views.

Covers construction, defaults, required fields, and model_dump() round-trips,
plus a regression guard that action.py carries no premodels/runtime import
(the data->runtime circular import must stay broken).
"""
import ast
from pathlib import Path
from uuid import uuid4

import pytest

from helao.framework.models.action import ActionModel, ShortActionModel
from helao.framework.models.experiment import ExperimentModel, ShortExperimentModel
from helao.framework.models.sequence import SequenceModel, ShortSequenceModel
from helao.framework.models.machine import MachineModel
from helao.framework.models.run_use import RunUse
from helao.framework.models.action_start_condition import ActionStartCondition
from helao.framework.models.errors import ErrorCodes


# --------------------------------------------------------------------------- #
# Action
# --------------------------------------------------------------------------- #
def test_short_action_model_defaults():
    sa = ShortActionModel()
    assert sa.action_uuid is None
    assert sa.action_actual_order == 0
    assert isinstance(sa.action_server, MachineModel)
    assert sa.hlo_version is not None


def test_action_model_defaults():
    am = ActionModel()
    assert am.access == "hte"
    assert am.run_use == RunUse.data
    assert am.error_code == ErrorCodes.none
    assert am.start_condition == ActionStartCondition.wait_for_all
    assert am.save_act is True
    assert am.samples_in == []
    assert am.to_global_params == []


def test_action_model_url_property():
    am = ActionModel(
        action_name="doit",
        action_server=MachineModel(
            server_name="srv", hostname="host", port=8000
        ),
    )
    assert am.url == "http://host:8000/srv/doit"


def test_action_model_round_trip():
    am = ActionModel(
        action_uuid=uuid4(),
        experiment_uuid=uuid4(),
        action_name="doit",
        action_params={"x": 1},
    )
    assert ActionModel(**am.model_dump()).model_dump() == am.model_dump()


def test_short_action_model_round_trip():
    sa = ShortActionModel(action_uuid=uuid4(), action_comment="hi")
    assert ShortActionModel(**sa.model_dump()).model_dump() == sa.model_dump()


# --------------------------------------------------------------------------- #
# Experiment
# --------------------------------------------------------------------------- #
def test_short_experiment_model_defaults():
    se = ShortExperimentModel()
    assert se.experiment_uuid is None
    assert se.experiment_params == {}
    assert se.from_global_exp_params == {}


def test_experiment_model_defaults():
    em = ExperimentModel()
    assert em.access == "hte"
    assert em.run_use == RunUse.data
    assert em.orchestrator is None
    assert em.experiment_status == []
    assert em.dispatched_actions_abbr == []
    assert em.process_order_groups == {}
    assert em.hlo_version is not None


def test_experiment_model_has_experiment_order_default():
    em = ExperimentModel()
    assert em.experiment_order == 0


def test_experiment_order_round_trips():
    em = ExperimentModel(experiment_name="exp", experiment_order=3)
    assert ExperimentModel(**em.model_dump()).experiment_order == 3


def test_experiment_model_round_trip():
    em = ExperimentModel(
        experiment_uuid=uuid4(),
        sequence_uuid=uuid4(),
        experiment_name="exp",
        dispatched_actions_abbr=[ShortActionModel(action_uuid=uuid4())],
    )
    assert ExperimentModel(**em.model_dump()).model_dump() == em.model_dump()


def test_short_experiment_model_round_trip():
    se = ShortExperimentModel(experiment_uuid=uuid4(), experiment_name="exp")
    assert ShortExperimentModel(**se.model_dump()).model_dump() == se.model_dump()


# --------------------------------------------------------------------------- #
# Sequence
# --------------------------------------------------------------------------- #
def test_short_sequence_model_defaults():
    ss = ShortSequenceModel()
    assert ss.sequence_label == "noLabel"
    assert ss.planned_experiments == []
    assert ss.sequence_params == {}


def test_sequence_model_defaults():
    sm = SequenceModel()
    assert sm.access == "hte"
    assert sm.sequence_status == []
    assert isinstance(sm.orchestrator, MachineModel)
    assert sm.sync_data is True
    assert sm.hlo_version is not None


def test_sequence_model_round_trip():
    sm = SequenceModel(
        sequence_uuid=uuid4(),
        sequence_name="seq",
        planned_experiments=[ShortExperimentModel(experiment_name="exp")],
        dispatched_experiments_abbr=[ShortExperimentModel(experiment_name="exp")],
    )
    assert SequenceModel(**sm.model_dump()).model_dump() == sm.model_dump()


def test_short_sequence_model_round_trip():
    ss = ShortSequenceModel(sequence_name="seq")
    assert ShortSequenceModel(**ss.model_dump()).model_dump() == ss.model_dump()


def test_sequence_model_has_sequence_order_default():
    from helao.framework.models.sequence import SequenceModel
    sm = SequenceModel()
    assert sm.sequence_order == 0


def test_sequence_order_round_trips():
    from helao.framework.models.sequence import SequenceModel
    sm = SequenceModel(sequence_name="s", sequence_order=4)
    assert SequenceModel(**sm.model_dump()).sequence_order == 4


# --------------------------------------------------------------------------- #
# Regression: action.py has no premodels/runtime import
# --------------------------------------------------------------------------- #
def _imported_modules(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mods.add(node.module)
    return mods


def test_action_module_has_no_premodels_or_runtime_import():
    path = Path("helao/framework/models/action.py")
    mods = _imported_modules(path)
    # no legacy runtime / premodels coupling
    assert not any("premodels" in m for m in mods)
    # no imports outside the framework package
    assert not any(
        m.startswith("helao.core") or m.startswith("helao.helpers") for m in mods
    )
