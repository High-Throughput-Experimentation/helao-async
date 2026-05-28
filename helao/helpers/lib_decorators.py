"""Decorators that tag experiment- and sequence-library functions with a version.

Library functions under ``helao/deploy/*/experiments`` and
``helao/deploy/*/sequences`` historically carried an ``experiment_version`` or
``sequence_version`` parameter that was never read by the function body and
never injected by the orchestrator — it served purely as a bookkeeping tag.
These decorators move that tag out of the call signature and onto the function
object, so the parameter no longer pollutes ``experiment_params`` /
``sequence_params`` nor the orchestrator's ``inspect.getfullargspec`` filter.
"""

__all__ = ["experiment", "sequence"]


def experiment(version: int = 1):
    """Tag an experiment-library function with its library version.

    Usage:

        @experiment(version=2)
        def MY_exp(experiment: Experiment, foo: float = 1.0):
            ...

    The tag is stored on ``func.experiment_version`` for any caller that wants
    to introspect it.
    """

    def decorator(func):
        func.experiment_version = version
        return func

    return decorator


def sequence(version: int = 1):
    """Tag a sequence-library function with its library version.

    Usage:

        @sequence(version=3)
        def MY_seq(foo: float = 1.0):
            ...

    The tag is stored on ``func.sequence_version`` for any caller that wants
    to introspect it.
    """

    def decorator(func):
        func.sequence_version = version
        return func

    return decorator
