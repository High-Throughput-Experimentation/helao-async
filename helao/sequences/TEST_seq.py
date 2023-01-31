"""
Sequence library for Orchestrator testing
"""

__all__ = ["TEST_consecutive_noblocking"]


from helao.helpers.premodels import ExperimentPlanMaker


SEQUENCES = __all__


def TEST_consecutive_noblocking(
    sequence_version: int = 1,
    wait_time: float = 3.0,
    cycles: int = 5
):
    epm = ExperimentPlanMaker()

    for _ in range(cycles):
        epm.add_experiment("TEST_sub_noblocking", {"wait_time": wait_time})

    return epm.experiment_plan_list  # returns complete experiment list
