"""Migration tests for SP7: test-deployment pilot onto helao.framework.*"""
import pytest
from helao.framework.support.lib_decorators import experiment, sequence
from helao.framework.domain.plan_makers import EXPERIMENT_CTX, ActionPlanMaker
from helao.framework.domain.run_models import RunExperiment


def _make_run_exp(**kw) -> RunExperiment:
    defaults = dict(
        experiment_name="test_exp",
        sequence_name="test_seq",
        sequence_label="test_seq__001",
        experiment_output_dir="26.25/0622/test",
    )
    defaults.update(kw)
    return RunExperiment(**defaults)


def test_experiment_decorator_sets_version():
    @experiment(version=3)
    def my_exp(param: float = 1.0):
        pass
    assert my_exp.experiment_version == 3


def test_experiment_decorator_injects_ctx():
    captured = []

    @experiment(version=1)
    def my_exp():
        captured.append(EXPERIMENT_CTX.get(None))

    run_exp = _make_run_exp()
    my_exp(run_exp)
    assert captured[0] is run_exp


def test_experiment_decorator_resets_ctx_after_call():
    @experiment(version=1)
    def my_exp():
        pass

    assert EXPERIMENT_CTX.get(None) is None
    my_exp(_make_run_exp())
    assert EXPERIMENT_CTX.get(None) is None


def test_experiment_decorator_positional_arg_form():
    received = []

    @experiment(version=1)
    def my_exp(experiment: RunExperiment, extra: int = 0):
        received.append(experiment)

    run_exp = _make_run_exp()
    my_exp(run_exp, extra=7)
    assert received[0] is run_exp


def test_sequence_decorator_sets_version():
    @sequence(version=5)
    def my_seq():
        pass
    assert my_seq.sequence_version == 5


def test_file_utils_importable():
    from helao.framework.support.file_utils import (
        file_in_use, rm_tree, rm_tree_async, zip_dir, unzpickle, zpickle
    )
    assert callable(file_in_use)
    assert callable(unzpickle)


def test_file_in_use_returns_false_for_nonexistent(tmp_path):
    from helao.framework.support.file_utils import file_in_use
    assert file_in_use(tmp_path / "no_such_file.txt") is False
