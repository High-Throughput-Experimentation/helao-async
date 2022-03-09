
__all__ = [
           "create_liquid_sample",
           "create_gas_sample",
           "create_assembly_sample",
          ]


from typing import Optional, List, Union
from socket import gethostname

from helaocore.schema import Experiment, ActionPlanMaker
from helaocore.model.action_start_condition import ActionStartCondition
from helaocore.model.sample import (
                                    LiquidSample,
                                    GasSample,
                                    AssemblySample,
                                    SolidSample,
                                   )
from helaocore.model.machine import MachineModel


EXPERIMENTS = __all__

PAL_server = MachineModel(
                server_name = "PAL",
                machine_name = gethostname()
             ).json_dict()


def create_liquid_sample(experiment: Experiment, 
                         volume_ml: Optional[float] = 1.0, 
                         source: Optional[List[str]] = ["source1","source2"],
                         mass:  Optional[List[str]] = ["mass1","mass2"],
                         chemical: Optional[List[str]] = ["chemical1","chemical2"],
                         supplier: Optional[List[str]] = ["supplier1","supplier2"],
                         lot_number: Optional[List[str]] = ["lot1","lot2"],
                         comment: Optional[str] = "comment"
                        ):
    """creates a custom liquid sample
       input fields contain json strings"""
    sq = ActionPlanMaker(experiment) # exposes function parameters via sq.pars

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


def create_gas_sample(experiment: Experiment, 
                      volume_ml: Optional[float] = 1.0, 
                      source: Optional[List[str]] = ["source1","source2"],
                      mass:  Optional[List[str]] = ["mass1","mass2"],
                      chemical: Optional[List[str]] = ["chemical1","chemical2"],
                      supplier: Optional[List[str]] = ["supplier1","supplier2"],
                      lot_number: Optional[List[str]] = ["lot1","lot2"],
                      comment: Optional[str] = "comment"
                     ):
    """creates a custom gas sample
       input fields contain json strings"""
    sq = ActionPlanMaker(experiment) # exposes function parameters via sq.pars

    sq.add_action({
        "action_server": PAL_server,
        "action_name": "db_new_sample",
        "action_params": {
                          "fast_samples_in": 
                              [GasSample(**{
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


def create_assembly_sample(experiment: Experiment, 
                           liquid_sample_nos: Optional[List[int]] = [1, 2],
                           gas_sample_nos: Optional[List[int]] = [1, 2],
                           solid_plate_ids: Optional[List[int]] = [1, 2],
                           solid_sample_nos: Optional[List[int]] = [1, 2],
                           volume_ml: Optional[float] = 1.0, 
                           # source: Optional[List[str]] = ["source1","source2"],
                           # mass:  Optional[List[str]] = ["mass1","mass2"],
                           # chemical: Optional[List[str]] = ["chemical1","chemical2"],
                           # supplier: Optional[List[str]] = ["supplier1","supplier2"],
                           # lot_number: Optional[List[str]] = ["lot1","lot2"],
                           comment: Optional[str] = "comment"
                          ):
    """creates a custom assembly sample
       from local samples
       input fields contain json strings
       Args:
           liquid_sample_nos: liquid sample numbers from local liquid sample db
           gas_sample_nos: liquid sample numbers from local gas sample db
           solid_plate_ids: plate ids
           solid_sample_nos: sample_no on plate (one plate_id for each sample_no)
           """
    sq = ActionPlanMaker(experiment) # exposes function parameters via sq.pars
    # check first 
    if len(sq.pars.solid_plate_ids) != len(sq.pars.solid_sample_nos):
        print(f"!!! ERROR: len(solid_plate_ids) != len(solid_sample_nos): "
              f"{len(sq.pars.solid_plate_ids)} != {len(sq.pars.solid_sample_nos)}")
        return sq.action_list


    liquid_list = [LiquidSample(machine_name=gethostname(), sample_no=sample_no) for sample_no in sq.pars.liquid_sample_nos]
    gas_list = [GasSample(machine_name=gethostname(), sample_no=sample_no) for sample_no in sq.pars.gas_sample_nos]
    solid_list = [SolidSample(machine_name="legacy", plate_id=plate_id, sample_no=sample_no) for plate_id, sample_no in zip(sq.pars.solid_plate_ids, sq.pars.solid_sample_nos)]

    # combine all samples now in a partlist
    parts = []
    for liquid in liquid_list:
        parts.append(liquid)
    for gas in gas_list:
        parts.append(gas)
    for solid in solid_list:
        parts.append(solid)

    sq.add_action({
        "action_server": PAL_server,
        "action_name": "db_new_sample",
        "action_params": {
                          "fast_samples_in": 
                              [AssemblySample(**{
                                              "machine_name":gethostname(),
                                              "parts":parts,
                                              # "source": sq.pars.source,
                                               "volume_ml": sq.pars.volume_ml,
                                              # "chemical": sq.pars.chemical,
                                              # "mass": sq.pars.mass,
                                              # "supplier": sq.pars.supplier,
                                              # "lot_number": sq.pars.lot_number,
                                              "comment": sq.pars.comment,
                             })],
                          },
        "start_condition": ActionStartCondition.wait_for_all,
        })

    return sq.action_list # returns complete action list to orch
