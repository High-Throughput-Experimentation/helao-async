"""Decorators that tag experiment- and sequence-library functions with a version.

Library functions under ``helao/deploy/*/experiments`` and
``helao/deploy/*/sequences`` historically carried an ``experiment_version`` or
``sequence_version`` parameter that was never read by the function body and
never injected by the orchestrator — it served purely as a bookkeeping tag.
These decorators move that tag out of the call signature and onto the function
object, so the parameter no longer pollutes ``experiment_params`` /
``sequence_params`` nor the orchestrator's ``inspect.getfullargspec`` filter.

In addition to versioning, :func:`experiment` takes over supplying the parent
:class:`~helao.framework.domain.run_models.RunExperiment`. Experiment-library
functions used to declare an ``experiment: RunExperiment`` first parameter that
the orchestrator passed positionally and that nested calls forwarded by hand.
The decorator now captures that experiment — whether passed positionally (by
the orchestrator), by keyword, or inherited from an enclosing experiment via
:data:`~helao.framework.domain.plan_makers.EXPERIMENT_CTX` — and exposes it
through the context var instead, so function bodies (and
:class:`~helao.framework.domain.plan_makers.ActionPlanMaker`) no longer need
the parameter. Legacy functions that still declare a ``RunExperiment``
parameter keep receiving it, so the decorator works during an incremental
migration.

This is the framework-native port of ``helao.helpers.lib_decorators``.
"""

__all__ = ["experiment", "sequence"]

import functools
import inspect

from helao.framework.domain.plan_makers import EXPERIMENT_CTX
from helao.framework.domain.run_models import RunExperiment


def _declares_experiment_param(sig: inspect.Signature) -> bool:
    """Return True if ``sig``'s first parameter is the parent ``RunExperiment``.

    Recognizes either a ``RunExperiment`` (sub)class annotation or a parameter
    literally named ``experiment``, matching how library functions historically
    declared the orchestrator-supplied parent experiment.
    """
    params = [
        p
        for p in sig.parameters.values()
        if p.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
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

    Usage::

        @experiment(version=2)
        def MY_exp(foo: float = 1.0):
            apm = ActionPlanMaker()
            ...

    The version tag is stored on the returned function's ``experiment_version``
    attribute for any caller that wants to introspect it. The wrapper also
    extracts the parent :class:`~helao.framework.domain.run_models.RunExperiment`
    (passed positionally, by keyword, or inherited from
    :data:`~helao.framework.domain.plan_makers.EXPERIMENT_CTX`) and publishes
    it on :data:`EXPERIMENT_CTX` for the duration of the call, so neither the
    function signature nor nested calls need to thread it explicitly.

    Args:
        version: The experiment-library schema version to advertise.

    Returns:
        A decorator that wraps the library function with experiment-context
        management while preserving its introspectable signature.
    """

    def decorator(func):
        sig = inspect.signature(func)
        declares_exp = _declares_experiment_param(sig)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            exp = None
            if args and isinstance(args[0], RunExperiment):
                exp, args = args[0], args[1:]
            if isinstance(kwargs.get("experiment"), RunExperiment):
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
        # Expose the underlying signature so the orchestrator's
        # inspect.getfullargspec(exp_func) param filter still sees the real
        # (experiment-free) parameter list rather than the wrapper's *args.
        wrapper.__signature__ = sig
        return wrapper

    return decorator


def sequence(version: int = 1):
    """Tag a sequence-library function with its library version.

    Usage::

        @sequence(version=3)
        def MY_seq(foo: float = 1.0):
            ...

    The tag is stored on ``func.sequence_version`` for any caller that wants
    to introspect it.

    Args:
        version: The sequence-library schema version to advertise.

    Returns:
        The original function with ``.sequence_version`` set (no wrapping).
    """

    def decorator(func):
        func.sequence_version = version
        return func

    return decorator
