"""Tests for :mod:`helao.framework.support.lib_decorators`.

Cover both decorators:

* :func:`experiment` — sets ``.experiment_version``, preserves the wrapped
  function's signature, injects a :class:`RunExperiment` into
  :data:`EXPERIMENT_CTX` during the call and resets it afterward, and accepts
  a ``RunExperiment`` instance passed positionally (legacy orchestrator form)
  or by keyword.
* :func:`sequence` — sets ``.sequence_version`` without wrapping.
"""

import inspect

import pytest

from helao.framework.domain.plan_makers import EXPERIMENT_CTX
from helao.framework.domain.run_models import RunExperiment
from helao.framework.support.lib_decorators import experiment, sequence


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_exp(**kwargs):
    """Build a minimal RunExperiment for tests."""
    defaults = {"experiment_name": "test_exp", "experiment_params": {}}
    defaults.update(kwargs)
    return RunExperiment(**defaults)


# ---------------------------------------------------------------------------
# @experiment — version tag
# ---------------------------------------------------------------------------


def test_experiment_sets_default_version():
    @experiment()
    def my_exp():
        pass

    assert my_exp.experiment_version == 1


def test_experiment_sets_explicit_version():
    @experiment(version=7)
    def my_exp():
        pass

    assert my_exp.experiment_version == 7


def test_experiment_version_kwarg_form():
    @experiment(version=3)
    def my_exp():
        pass

    assert my_exp.experiment_version == 3


# ---------------------------------------------------------------------------
# @experiment — signature preservation
# ---------------------------------------------------------------------------


def test_experiment_preserves_wrapped_function_name():
    @experiment(version=1)
    def unique_name_exp(foo: float = 1.0):
        pass

    assert unique_name_exp.__name__ == "unique_name_exp"


def test_experiment_preserves_introspectable_signature():
    """The orchestrator inspects parameters via inspect.getfullargspec; the
    wrapper must expose the real (experiment-free) signature, not *args."""

    @experiment(version=2)
    def my_exp(voltage: float = 1.0, label: str = "run"):
        pass

    params = list(inspect.signature(my_exp).parameters)
    assert params == ["voltage", "label"]


# ---------------------------------------------------------------------------
# @experiment — EXPERIMENT_CTX injection and reset
# ---------------------------------------------------------------------------


def test_experiment_ctx_set_during_call():
    """EXPERIMENT_CTX holds the RunExperiment while the body executes."""
    captured = []

    @experiment(version=1)
    def my_exp():
        captured.append(EXPERIMENT_CTX.get(None))

    exp = _make_exp()
    my_exp(exp)
    assert len(captured) == 1
    assert captured[0] is exp


def test_experiment_ctx_reset_after_call():
    """EXPERIMENT_CTX is restored to its prior value after the call."""
    sentinel = _make_exp(experiment_name="outer")
    token = EXPERIMENT_CTX.set(sentinel)
    try:
        @experiment(version=1)
        def inner_exp():
            pass

        inner = _make_exp(experiment_name="inner")
        inner_exp(inner)
        # outer sentinel must be restored
        assert EXPERIMENT_CTX.get(None) is sentinel
    finally:
        EXPERIMENT_CTX.reset(token)


def test_experiment_ctx_reset_after_exception():
    """EXPERIMENT_CTX is reset even if the wrapped function raises."""
    prior = EXPERIMENT_CTX.get(None)

    @experiment(version=1)
    def bad_exp():
        raise RuntimeError("boom")

    exp = _make_exp()
    with pytest.raises(RuntimeError):
        bad_exp(exp)

    assert EXPERIMENT_CTX.get(None) is prior


def test_experiment_ctx_none_when_no_experiment_passed():
    """With no RunExperiment in scope, EXPERIMENT_CTX is set to None."""
    captured = []

    @experiment(version=1)
    def my_exp():
        captured.append(EXPERIMENT_CTX.get("MISSING"))

    my_exp()
    assert captured[0] is None


# ---------------------------------------------------------------------------
# @experiment — positional argument acceptance (legacy orchestrator form)
# ---------------------------------------------------------------------------


def test_experiment_accepts_run_experiment_positionally():
    """A RunExperiment passed as first positional arg is extracted from args."""
    received = []

    @experiment(version=1)
    def my_exp(voltage: float = 1.0):
        received.append(EXPERIMENT_CTX.get(None))

    exp = _make_exp()
    my_exp(exp, voltage=2.0)
    assert received[0] is exp


def test_experiment_positional_does_not_leak_into_function_params():
    """The RunExperiment is consumed by the decorator; the body sees only its
    own declared params."""
    received_args = []

    @experiment(version=1)
    def my_exp(voltage: float = 1.0):
        received_args.append(voltage)

    exp = _make_exp()
    my_exp(exp, voltage=3.5)
    assert received_args == [3.5]


def test_experiment_accepts_run_experiment_as_keyword():
    """A RunExperiment passed as ``experiment=...`` keyword is extracted."""
    captured = []

    @experiment(version=1)
    def my_exp():
        captured.append(EXPERIMENT_CTX.get(None))

    exp = _make_exp()
    my_exp(experiment=exp)
    assert captured[0] is exp


def test_experiment_inherits_ctx_when_no_explicit_experiment():
    """When no experiment is passed, the decorator inherits from an outer
    EXPERIMENT_CTX (as set by an enclosing @experiment call)."""
    outer_exp = _make_exp(experiment_name="outer")
    captured = []

    @experiment(version=1)
    def inner_exp():
        captured.append(EXPERIMENT_CTX.get(None))

    token = EXPERIMENT_CTX.set(outer_exp)
    try:
        inner_exp()
    finally:
        EXPERIMENT_CTX.reset(token)

    assert captured[0] is outer_exp


# ---------------------------------------------------------------------------
# @experiment — legacy function that still declares experiment parameter
# ---------------------------------------------------------------------------


def test_experiment_legacy_param_receives_experiment():
    """A function that declares ``experiment`` as first param still receives it."""
    received_exp = []

    @experiment(version=1)
    def legacy_exp(experiment, voltage: float = 1.0):
        received_exp.append(experiment)

    exp = _make_exp()
    legacy_exp(exp, voltage=5.0)
    assert received_exp[0] is exp


def test_experiment_legacy_annotated_param_receives_experiment():
    """A function with ``experiment: RunExperiment`` annotation also receives it."""
    received_exp = []

    @experiment(version=1)
    def typed_exp(experiment: RunExperiment, label: str = "x"):
        received_exp.append(experiment)

    exp = _make_exp()
    typed_exp(exp, label="y")
    assert received_exp[0] is exp


# ---------------------------------------------------------------------------
# @sequence — version tag
# ---------------------------------------------------------------------------


def test_sequence_sets_default_version():
    @sequence()
    def my_seq():
        pass

    assert my_seq.sequence_version == 1


def test_sequence_sets_explicit_version():
    @sequence(version=5)
    def my_seq():
        pass

    assert my_seq.sequence_version == 5


def test_sequence_does_not_wrap_function():
    """@sequence must return the original function object, not a wrapper."""

    @sequence(version=1)
    def my_seq(foo: float = 1.0):
        return foo

    # identity check: the function is the same object (not a functools.wraps copy)
    assert my_seq.__name__ == "my_seq"
    assert my_seq(foo=42.0) == 42.0


def test_sequence_preserves_signature():
    @sequence(version=2)
    def my_seq(a: int, b: str = "hi"):
        pass

    params = list(inspect.signature(my_seq).parameters)
    assert params == ["a", "b"]
