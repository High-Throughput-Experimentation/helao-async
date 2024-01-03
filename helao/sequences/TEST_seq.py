"""
Sequence library for Orchestrator testing
"""

__all__ = ["TEST_consecutive_noblocking"]

from typing import List
from helao.helpers.premodels import ExperimentPlanMaker


SEQUENCES = __all__


def TEST_consecutive_noblocking(
    sequence_version: int = 1,
    wait_time: float = 3.0,
    cycles: int = 5,
    dummy_list: List[List[float]] = [[0.0, 1.0], [2.0, 3.0]],
    *args,
    **kwrags,
):
    epm = ExperimentPlanMaker()

    for _ in range(cycles):
        epm.add_experiment("TEST_sub_noblocking", {"wait_time": wait_time})
        for i, l in enumerate(dummy_list):
            print(f"dummy_list index {i}:  {l} has types {[type(x) for x in l]}")

    return epm.experiment_plan_list  # returns complete experiment list
