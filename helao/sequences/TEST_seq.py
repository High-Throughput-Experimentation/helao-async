"""
Sequence library for Orchestrator testing
"""

__all__ = []


from helao.helpers.premodels import ExperimentPlanMaker


SEQUENCES = __all__


def TEST_consecutive_noblocking(
    sequence_version: int = 1,
    wait_time: float = 10.0,
    cycles: int = 5
):
    epm = ExperimentPlanMaker()
    epm.add_experiment("TEST_sub_noblocking", {"wait_time": wait_time})

    return epm.experiment_plan_list  # returns complete experiment list
