"""
Sequence library for SDC
"""

__all__ = [
           "SDC_CA_toogle",
          ]


from typing import List
from helaocore.schema import ExperimentPlanMaker


SEQUENCES = __all__


def SDC_CA_toogle(
                 plate_sample_no_list: list = [2],
                ):
    pl = ExperimentPlanMaker()
    
    # pl.add_experiment(
    #                "nameofexp", 
    #                {
    #                 }
    #                )


    return pl.experiment_plan_list # returns complete experiment list
