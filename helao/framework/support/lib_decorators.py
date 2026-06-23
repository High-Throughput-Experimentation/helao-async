"""Decorators that tag experiment- and sequence-library functions with a version.

Port of ``helao.helpers.lib_decorators``, rewired to use
:class:`~helao.framework.domain.run_models.RunExperiment` and
:data:`~helao.framework.domain.plan_makers.EXPERIMENT_CTX` from the framework.
"""

__all__ = ["experiment", "sequence"]

import functools
import inspect

from pydantic import BaseModel

from helao.framework.domain.run_models import RunExperiment
from helao.framework.domain.plan_makers import EXPERIMENT_CTX


def _is_experiment_obj(obj) -> bool:
    """Duck-typed check: any BaseModel with experiment_name is treated as an experiment context.

    Accepts both legacy Experiment (helao.helpers.premodels) and RunExperiment
    so the decorator works when called from an old-style orchestrator.
    """
    return isinstance(obj, BaseModel) and hasattr(obj, "experiment_name")


def _declares_experiment_param(sig: inspect.Signature) -> bool:
    params = [
        p
        for p in sig.parameters.values()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if not params:
        return False
    first = params[0]
    ann = first.annotation
    if isinstance(ann, type) and issubclass(ann, RunExperiment):
        return True
    return first.name == "experiment"


def experiment(version: int = 1):
    """Tag an experiment-library function and supply its parent experiment.

    Ports ``helao.helpers.lib_decorators.experiment`` using
    :class:`RunExperiment` instead of the legacy ``Experiment``.
    """
    def decorator(func):
        sig = inspect.signature(func)
        declares_exp = _declares_experiment_param(sig)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            exp = None
            if args and _is_experiment_obj(args[0]):
                exp, args = args[0], args[1:]
            if _is_experiment_obj(kwargs.get("experiment")):
                exp = kwargs.pop("experiment")
            if exp is None:
                exp = EXPERIMENT_CTX.get(None)
            token = EXPERIMENT_CTX.set(exp)
            try:
                if declares_exp:
                    return func(exp, *args, **kwargs)
                return func(*args, **kwargs)
            finally:
                EXPERIMENT_CTX.reset(token)

        wrapper.experiment_version = version
        wrapper.__signature__ = sig
        return wrapper

    return decorator


def sequence(version: int = 1):
    """Tag a sequence-library function with its library version."""
    def decorator(func):
        func.sequence_version = version
        return func
    return decorator
