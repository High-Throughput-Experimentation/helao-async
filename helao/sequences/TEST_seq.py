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
    plate_sample_no_list: List[int] = [1, 2, 3],
    *args,
    **kwrags,
):
    epm = ExperimentPlanMaker()

    for smp in plate_sample_no_list:
        for i in range(cycles):
            if i == 0:
                epm.add(
                    "TEST_sub_noblocking",
                    {"wait_time": wait_time, "sample_no": smp},
                )
            else:
                epm.add(
                    "TEST_sub_noblocking",
                    {"wait_time": wait_time, "sample_no": smp},
                    from_global_exp_params={"test_wait": "dummy_param"},
                )
            for i, l in enumerate(dummy_list):
                print(f"dummy_list index {i}:  {l} has types {[type(x) for x in l]}")

    return epm.planned_experiments  # returns complete experiment list
