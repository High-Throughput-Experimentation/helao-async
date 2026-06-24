"""Test that legacy-name aliases are available in run_models."""

from helao.framework.domain import run_models as rm


def test_legacy_aliases_are_run_classes():
    """Verify that Action/Experiment/Sequence alias the Run* classes."""
    assert rm.Action is rm.RunAction
    assert rm.Experiment is rm.RunExperiment
    assert rm.Sequence is rm.RunSequence


def test_aliases_in_all():
    """Verify that aliases are in __all__."""
    for n in ("Action", "Experiment", "Sequence"):
        assert n in rm.__all__
