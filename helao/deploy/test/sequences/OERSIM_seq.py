"""Sequence library for the OER active-learning simulator."""

__all__ = [
    "OERSIM_activelearn",
]

from typing import Union
from helao.framework.domain.plan_makers import ExperimentPlanMaker
from helao.framework.support.lib_decorators import sequence


SEQUENCES = __all__


@sequence(version=1)
def OERSIM_activelearn(
    init_random_points: int = 5,
    stop_condition: str = "max_iters",  # {"none", "max_iters", "max_stdev", "max_ei"}
    thresh_value: Union[float, int] = 10,
) -> list:
    """Plan one ``OERSIM_sub_activelearn`` experiment that self-requeues.

    The single planned experiment uses Expected-Improvement acquisition and
    inserts further copies of itself until the stop condition is met.

    Args:
        init_random_points: Number of random initial compositions before the
            first EI iteration on a fresh plate.
        stop_condition: One of ``"none"``, ``"max_iters"``, ``"max_stdev"``,
            ``"max_ei"``.
        thresh_value: Threshold compared against the chosen stop condition.

    Returns:
        Planned experiments for the orchestrator to enqueue.
    """
    epm = ExperimentPlanMaker()
    epm.add(
        "OERSIM_sub_activelearn",
        {
            "init_random_points": init_random_points,
            "stop_condition": stop_condition,
            "thresh_value": thresh_value,
        },
    )
    return epm.planned_experiments
