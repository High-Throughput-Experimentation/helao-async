
__all__ = [
           "create_liquid", 
          ]


from typing import Optional, List, Union
from socket import gethostname

from helaocore.schema import Experiment, ActionPlanMaker
from helaocore.model.action_start_condition import ActionStartCondition
from helaocore.model.sample import (
                                    SolidSample,
                                    LiquidSample,
                                    GasSample
                                   )
from helaocore.model.machine import MachineModel


EXPERIMENTS = __all__

PAL_server = MachineModel(
                server_name = "PAL",
                machine_name = gethostname()
             ).json_dict()


def create_liquid(pg_Obj: Experiment, 
                  volume_ml: Optional[float] = 1.0, 
                  source: Optional[List[str]] = ["source1","source2"],
                  mass:  Optional[List[str]] = ["mass1","mass2"],
                  chemical: Optional[List[str]] = ["chemical1","chemical2"],
                  supplier: Optional[List[str]] = ["supplier1","supplier2"],
                  lot_number: Optional[List[str]] = ["lot1","lot2"],
                  comment: Optional[str] = "comment"
                 ):
    """creates a custom liquid sample"""
    sq = ActionPlanMaker(pg_Obj) # exposes function parameters via sq.pars

    sq.add_action({
        "action_server": PAL_server,
        "action_name": "db_new_sample",
        "action_params": {
                          "fast_samples_in": 
                              [LiquidSample(**{
                                              "machine_name":gethostname(),
                                              "source": sq.pars.source,
                                              "volume_ml": sq.pars.volume_ml,
                                              "chemical": sq.pars.chemical,
                                              "mass": sq.pars.mass,
                                              "supplier": sq.pars.supplier,
                                              "lot_number": sq.pars.lot_number,
                                              "comment": sq.pars.comment,
                             })],
                          },
        "start_condition": ActionStartCondition.wait_for_all,
        })

    return sq.action_list # returns complete action list to orch
