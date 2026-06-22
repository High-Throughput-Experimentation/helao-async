"""Tests for :mod:`helao.framework.domain.plan_makers`.

Cover ``ExperimentPlanMaker.add`` (single/multiple), ``ActionPlanMaker.add``
and ``add_actions`` (merged params / start_condition / to_global /
from_global), the ``"true"``/``"false"`` -> bool coercion in ``self.pars``,
and both the contextvar (``EXPERIMENT_CTX``) and frame-inspection capture
paths.
"""

from uuid import uuid4

import pytest

from helao.framework.domain.plan_makers import (
    EXPERIMENT_CTX,
    ActionPlanMaker,
    ExperimentPlanMaker,
)
from helao.framework.domain.run_models import RunAction, RunExperiment
from helao.framework.models.action_start_condition import ActionStartCondition
from helao.framework.models.experiment import ShortExperimentModel
from helao.framework.models.machine import MachineModel


def _make_experiment(**overrides):
    """Build a RunExperiment with orchestrator populated (so as_dict round-trips).

    The framework ``ExperimentModel.orchestrator`` defaults to ``None`` while
    ``ActionModel.orchestrator`` is non-Optional, so a blank experiment cannot
    be fed through ``ActionPlanMaker.add``. A real run always has the
    orchestrator set; tests do the same.
    """
    kwargs = {
        "experiment_name": "dummy_exp",
        "experiment_params": {},
        "orchestrator": MachineModel(server_name="orch", machine_name="host"),
    }
    kwargs.update(overrides)
    return RunExperiment(**kwargs)


# --------------------------------------------------------------------------
# ExperimentPlanMaker
# --------------------------------------------------------------------------


def test_experiment_plan_maker_starts_empty():
    epm = ExperimentPlanMaker()
    assert epm.planned_experiments == []


def test_experiment_plan_maker_add_single():
    epm = ExperimentPlanMaker()
    epm.add("exp_a", {"x": 1})
    assert len(epm.planned_experiments) == 1
    sem = epm.planned_experiments[0]
    assert isinstance(sem, ShortExperimentModel)
    assert sem.experiment_name == "exp_a"
    assert sem.experiment_params == {"x": 1}
    assert sem.from_global_exp_params == {}


def test_experiment_plan_maker_add_multiple_and_kwargs():
    epm = ExperimentPlanMaker()
    epm.add("exp_a", {"x": 1}, from_global_exp_params={"g": "k"})
    epm.add("exp_b", {"y": 2}, experiment_comment="hello")
    assert len(epm.planned_experiments) == 2
    first, second = epm.planned_experiments
    assert first.experiment_name == "exp_a"
    assert first.from_global_exp_params == {"g": "k"}
    assert second.experiment_name == "exp_b"
    assert second.experiment_params == {"y": 2}
    assert second.experiment_comment == "hello"


# --------------------------------------------------------------------------
# ActionPlanMaker — capture paths
# --------------------------------------------------------------------------


def test_action_plan_maker_frame_capture():
    """The Experiment is discovered as a declared argument on the caller frame."""

    def experiment_func(experiment, voltage, label):
        apm = ActionPlanMaker()
        return apm

    exp = _make_experiment(experiment_params={"current": 0.5})
    apm = experiment_func(exp, voltage=1.0, label="run1")

    assert apm.expname == "experiment_func"
    # experiment_params entry surfaced on pars
    assert apm.pars.current == 0.5
    # local args (not the Experiment) surfaced on pars
    assert apm.pars.voltage == 1.0
    assert apm.pars.label == "run1"
    # the Experiment-typed argument is never exposed as a param
    assert not hasattr(apm.pars, "experiment")


def test_action_plan_maker_contextvar_capture():
    """The Experiment is recovered from EXPERIMENT_CTX (decorator path)."""

    def experiment_func(scan_rate):
        return ActionPlanMaker()

    exp = _make_experiment(experiment_params={"temp": 25})
    token = EXPERIMENT_CTX.set(exp)
    try:
        apm = experiment_func(scan_rate=10)
    finally:
        EXPERIMENT_CTX.reset(token)

    assert apm.pars.temp == 25
    assert apm.pars.scan_rate == 10


def test_action_plan_maker_contextvar_preferred_over_frame():
    """When both are present, the contextvar Experiment wins."""

    def experiment_func(experiment):
        return ActionPlanMaker()

    ctx_exp = _make_experiment(experiment_name="ctx_exp", experiment_params={"a": 1})
    frame_exp = _make_experiment(experiment_name="frame_exp", experiment_params={"b": 2})
    token = EXPERIMENT_CTX.set(ctx_exp)
    try:
        apm = experiment_func(frame_exp)
    finally:
        EXPERIMENT_CTX.reset(token)

    assert apm._experiment.experiment_name == "ctx_exp"
    assert apm.pars.a == 1
    assert not hasattr(apm.pars, "b")


def test_action_plan_maker_no_experiment_uses_blank():
    """With no Experiment in scope, a blank RunExperiment is used."""

    def experiment_func(value):
        return ActionPlanMaker()

    apm = experiment_func(value=3)
    assert isinstance(apm._experiment, RunExperiment)
    assert apm.pars.value == 3


# --------------------------------------------------------------------------
# ActionPlanMaker — bool-string coercion
# --------------------------------------------------------------------------


def test_bool_string_coercion_from_experiment_params():
    def experiment_func(experiment):
        return ActionPlanMaker()

    exp = _make_experiment(
        experiment_params={"enabled": "true", "disabled": "False", "name": "abc"}
    )
    apm = experiment_func(exp)
    assert apm.pars.enabled is True
    assert apm.pars.disabled is False
    assert apm.pars.name == "abc"


def test_bool_string_coercion_from_local_args():
    def experiment_func(experiment, flag_on, flag_off):
        return ActionPlanMaker()

    exp = _make_experiment(experiment_params={})
    apm = experiment_func(exp, flag_on="TRUE", flag_off="false")
    assert apm.pars.flag_on is True
    assert apm.pars.flag_off is False


# --------------------------------------------------------------------------
# ActionPlanMaker — add / add_actions
# --------------------------------------------------------------------------


def test_action_plan_maker_add_builds_runaction():
    def experiment_func(experiment):
        return ActionPlanMaker()

    exp = _make_experiment(
        experiment_name="cv_exp",
        experiment_params={"a": 1},
        experiment_uuid=uuid4(),
    )
    apm = experiment_func(exp)
    apm.add(
        action_server="motor",
        action_name="move",
        action_params={"x": 10},
        start_condition=ActionStartCondition.no_wait,
        to_global_params=["pos"],
        from_global_act_params={"g_x": "x"},
    )
    assert len(apm.planned_actions) == 1
    act = apm.planned_actions[0]
    assert isinstance(act, RunAction)
    assert act.action_name == "move"
    assert act.action_params == {"x": 10}
    assert act.start_condition == ActionStartCondition.no_wait
    assert act.to_global_params == ["pos"]
    assert act.from_global_act_params == {"g_x": "x"}
    # experiment provenance flows through as_dict() merge
    assert act.experiment_name == "cv_exp"
    assert act.experiment_params == {"a": 1}
    # string action_server coerced to MachineModel with HOST machine_name
    assert act.action_server.server_name == "motor"
    assert act.action_server.machine_name is not None


def test_action_plan_maker_add_server_as_machinemodel_and_dict():
    def experiment_func(experiment):
        return ActionPlanMaker()

    apm = experiment_func(_make_experiment())
    mm = MachineModel(server_name="pump", machine_name="rig1")
    apm.add(mm, "dispense", {"vol": 5})
    apm.add(mm.as_dict(), "aspirate", {"vol": 2})
    assert apm.planned_actions[0].action_server.server_name == "pump"
    assert apm.planned_actions[0].action_server.machine_name == "rig1"
    assert apm.planned_actions[1].action_server.server_name == "pump"


def test_action_plan_maker_add_run_use_defaults_from_experiment():
    from helao.framework.models.run_use import RunUse

    def experiment_func(experiment):
        return ActionPlanMaker()

    exp = _make_experiment(run_use=RunUse.ref)
    apm = experiment_func(exp)
    apm.add("dev", "act", {})
    assert apm.planned_actions[0].run_use == RunUse.ref


def test_action_plan_maker_add_run_use_kwarg_override():
    from helao.framework.models.run_use import RunUse

    def experiment_func(experiment):
        return ActionPlanMaker()

    exp = _make_experiment(run_use=RunUse.ref)
    apm = experiment_func(exp)
    apm.add("dev", "act", {}, run_use=RunUse.baseline)
    assert apm.planned_actions[0].run_use == RunUse.baseline


def test_action_plan_maker_add_default_start_condition():
    def experiment_func(experiment):
        return ActionPlanMaker()

    apm = experiment_func(_make_experiment())
    apm.add("dev", "act", {})
    assert apm.planned_actions[0].start_condition == ActionStartCondition.wait_for_all


def test_action_plan_maker_add_actions_appends():
    def experiment_func(experiment):
        return ActionPlanMaker()

    apm = experiment_func(_make_experiment())
    pre = [
        RunAction(action_name="a1", action_server=MachineModel(server_name="s")),
        RunAction(action_name="a2", action_server=MachineModel(server_name="s")),
    ]
    apm.add_actions(pre)
    assert [a.action_name for a in apm.planned_actions] == ["a1", "a2"]


def test_action_plan_maker_experiment_property_attaches_planned_actions():
    def experiment_func(experiment):
        return ActionPlanMaker()

    apm = experiment_func(_make_experiment(experiment_name="e"))
    apm.add("dev", "act", {})
    exp = apm.experiment
    assert isinstance(exp, RunExperiment)
    assert len(exp.planned_actions) == 1


def test_blank_experiment_add_raises_due_to_orchestrator_divergence():
    """Documents the framework-model divergence: blank RunExperiment.add fails.

    ``ExperimentModel.orchestrator`` defaults to ``None`` but
    ``ActionModel.orchestrator`` is non-Optional, so feeding a blank
    experiment's ``as_dict()`` into ``RunAction`` is a validation error. A real
    run always has the orchestrator set.
    """

    def experiment_func(value):
        return ActionPlanMaker()

    apm = experiment_func(value=1)
    with pytest.raises(Exception):
        apm.add("dev", "act", {})
