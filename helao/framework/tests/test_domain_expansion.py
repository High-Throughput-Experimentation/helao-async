"""Tests for the pure expansion + global-param folding functions.

These port the orchestrator's sequence/experiment unpacking and the
``from_global_*`` / ``to_global_params`` plumbing. Library maps and the platemap
resolver are injected, so every test drives the function with plain fakes (a
dict of name->callable, a resolver lambda) and asserts on the returned value
with no I/O.
"""

from helao.framework.models.experiment import ExperimentModel
from helao.framework.domain.run_models import RunAction, RunExperiment
from helao.framework.domain.expansion import (
    unpack_sequence,
    unpack_experiment,
    fold_in_global,
    fold_out_global,
    verify_plate_in_params,
)


# --- unpack_sequence -----------------------------------------------------------


def test_unpack_sequence_invokes_factory_with_params():
    captured = {}

    def myseq(**kwargs):
        captured.update(kwargs)
        return [ExperimentModel(experiment_name="e1"), ExperimentModel(experiment_name="e2")]

    lib = {"myseq": myseq}
    result = unpack_sequence("myseq", {"a": 1, "b": 2}, sequence_lib=lib)

    assert [e.experiment_name for e in result] == ["e1", "e2"]
    assert captured == {"a": 1, "b": 2}


def test_unpack_sequence_unknown_name_returns_empty():
    assert unpack_sequence("nope", {"a": 1}, sequence_lib={}) == []


# --- unpack_experiment ---------------------------------------------------------


def test_unpack_experiment_returns_list_directly():
    def myexp(experiment, gain=1.0):
        return [RunAction(action_name="act1"), RunAction(action_name="act2")]

    exp = RunExperiment(experiment_name="myexp")
    result = unpack_experiment(exp, {"gain": 2.0}, experiment_lib={"myexp": myexp})

    assert [a.action_name for a in result] == ["act1", "act2"]


def test_unpack_experiment_filters_unknown_params():
    seen = {}

    def myexp(experiment, gain=1.0):
        seen["gain"] = gain
        seen["experiment"] = experiment
        return []

    exp = RunExperiment(experiment_name="myexp")
    # 'bogus' is not a factory arg and must be dropped before the call
    unpack_experiment(exp, {"gain": 5.0, "bogus": 9}, experiment_lib={"myexp": myexp})

    assert seen["gain"] == 5.0
    assert seen["experiment"] is exp


def test_unpack_experiment_returns_planned_actions_from_returned_experiment():
    def myexp(experiment):
        experiment.planned_actions = [RunAction(action_name="planned")]
        return experiment

    exp = RunExperiment(experiment_name="myexp")
    result = unpack_experiment(exp, {}, experiment_lib={"myexp": myexp})

    assert [a.action_name for a in result] == ["planned"]


def test_unpack_experiment_unknown_name_returns_empty():
    exp = RunExperiment(experiment_name="missing")
    assert unpack_experiment(exp, {}, experiment_lib={}) == []


def test_unpack_experiment_non_list_non_experiment_return_is_empty():
    def myexp(experiment):
        return None

    exp = RunExperiment(experiment_name="myexp")
    assert unpack_experiment(exp, {}, experiment_lib={"myexp": myexp}) == []


# --- fold_in_global ------------------------------------------------------------


def test_fold_in_global_dict_rename():
    out = fold_in_global(
        {"existing": 0},
        {"gkey": "dest_key"},
        {"gkey": 42},
    )
    assert out == {"existing": 0, "dest_key": 42}


def test_fold_in_global_list_dest_writes_all():
    out = fold_in_global({}, {"gkey": ["k1", "k2"]}, {"gkey": "v"})
    assert out == {"k1": "v", "k2": "v"}


def test_fold_in_global_missing_global_key_skipped():
    out = fold_in_global({"a": 1}, {"absent": "dest"}, {"present": 5})
    assert out == {"a": 1}


def test_fold_in_global_does_not_mutate_input():
    target = {"a": 1}
    out = fold_in_global(target, {"g": "b"}, {"g": 2})
    assert target == {"a": 1}
    assert out == {"a": 1, "b": 2}


def test_fold_in_global_empty_map_is_noop():
    target = {"a": 1}
    out = fold_in_global(target, {}, {"g": 2})
    assert out == {"a": 1}
    assert out is not target  # still a copy


# --- fold_out_global -----------------------------------------------------------


def test_fold_out_global_list_same_name():
    delta = fold_out_global(["x", "y"], {"x": 1}, {"y": 2})
    assert delta == {"x": 1, "y": 2}


def test_fold_out_global_list_params_take_precedence_over_output():
    delta = fold_out_global(["x"], {"x": "from_params"}, {"x": "from_output"})
    assert delta == {"x": "from_params"}


def test_fold_out_global_list_falls_back_to_output():
    delta = fold_out_global(["x"], {}, {"x": "from_output"})
    assert delta == {"x": "from_output"}


def test_fold_out_global_list_missing_key_skipped():
    delta = fold_out_global(["missing"], {"a": 1}, {"b": 2})
    assert delta == {}


def test_fold_out_global_dict_rename():
    delta = fold_out_global({"src": "dst"}, {"src": 7}, {})
    assert delta == {"dst": 7}


def test_fold_out_global_dict_params_precedence_and_output_fallback():
    delta = fold_out_global(
        {"a": "A", "b": "B"},
        {"a": "pa"},
        {"b": "ob"},
    )
    assert delta == {"A": "pa", "B": "ob"}


def test_fold_out_global_dict_missing_key_skipped():
    delta = fold_out_global({"missing": "dst"}, {"a": 1}, {"b": 2})
    assert delta == {}


def test_fold_out_global_empty_inputs():
    assert fold_out_global([], {}, {}) == {}
    assert fold_out_global({}, {"a": 1}, {"b": 2}) == {}


def test_fold_out_global_none_to_global_is_noop():
    # neither list nor dict -> no export
    assert fold_out_global(None, {"a": 1}, {"b": 2}) == {}


# --- verify_plate_in_params ----------------------------------------------------


def test_verify_plate_no_plate_param_is_ok():
    assert verify_plate_in_params({"foo": 1}, resolver=lambda pid: None) is True


def test_verify_plate_present_and_resolves():
    calls = []

    def resolver(pid):
        calls.append(pid)
        return {"map": "data"}

    assert verify_plate_in_params({"plate_id": 123}, resolver=resolver) is True
    assert calls == [123]


def test_verify_solid_plate_id_resolves_first():
    # solid_plate_id is checked before plate_id
    def resolver(pid):
        return {"map": pid} if pid == 99 else None

    assert (
        verify_plate_in_params(
            {"solid_plate_id": 99, "plate_id": 7}, resolver=resolver
        )
        is True
    )


def test_verify_plate_present_but_unresolved_is_false():
    assert verify_plate_in_params({"plate_id": 5}, resolver=lambda pid: None) is False


def test_verify_plate_none_value_is_treated_as_absent():
    # key present but value None -> no valid map -> False
    assert (
        verify_plate_in_params({"plate_id": None}, resolver=lambda pid: {"m": 1})
        is False
    )


def test_verify_plate_falls_through_to_plate_id_when_solid_absent():
    def resolver(pid):
        return {"map": pid} if pid == 7 else None

    assert (
        verify_plate_in_params({"solid_plate_id": None, "plate_id": 7}, resolver=resolver)
        is True
    )
