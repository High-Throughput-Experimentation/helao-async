"""Sequence library for CCSI"""

__all__ = [
    "OERSIM_activelearn",
]

from typing import Union
from helao.helpers.premodels import ExperimentPlanMaker


SEQUENCES = __all__


def OERSIM_activelearn(
    sequence_version: int = 1,
    init_random_points: int = 5,
    stop_condition: str = "max_iters",  # {"none", "max_iters", "max_stdev", "max_ei"}
    thresh_value: Union[float, int] = 10,
):
    """Active-learning sequence using EI acquisition with various stop conditions."""
    epm = ExperimentPlanMaker()
    epm.add_experiment(
        "OERSIM_sub_activelearn",
        {
            "init_random_points": init_random_points,
            "stop_condition": stop_condition,
            "thresh_value": thresh_value,
        },
    )
    return epm.planned_experiments
