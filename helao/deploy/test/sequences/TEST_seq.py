"""Sequence library for exercising orchestrator scheduling features."""

__all__ = ["TEST_consecutive_noblocking"]

from typing import List
from helao.helpers.premodels import ExperimentPlanMaker
from helao.helpers.lib_decorators import sequence


SEQUENCES = __all__


@sequence(version=1)
def TEST_consecutive_noblocking(
    wait_time: float = 3.0,
    cycles: int = 5,
    dummy_list: List[List[float]] = [[0.0, 1.0], [2.0, 3.0]],
    plate_sample_no_list: List[int] = [1, 2, 3],
    *args,
    **kwargs,
) -> list:
    """Plan repeated ``TEST_sub_noblocking`` experiments across sample numbers.

    Generates one experiment per ``(sample_no, cycle)`` pair. After the first
    cycle for each sample, subsequent experiments pull ``dummy_param`` from
    the prior cycle's ``test_wait`` global to exercise param hand-off.

    Args:
        wait_time: Base wait used inside each sub-experiment.
        cycles: Number of cycles per sample.
        dummy_list: Unused placeholder list, kept for parameter-typing tests.
        plate_sample_no_list: Sample numbers to iterate over.
        *args: Ignored positional arguments.
        **kwargs: Ignored keyword arguments.

    Returns:
        Planned experiments for the orchestrator to enqueue.
    """
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
            # for i, l in enumerate(dummy_list):
            #     print(f"dummy_list index {i}:  {l} has types {[type(x) for x in l]}")

    return epm.planned_experiments  # returns complete experiment list
