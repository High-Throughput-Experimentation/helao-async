
__all__ = [
           "create_liquid_sample",
           "create_gas_sample",
           "create_assembly_sample",
          ]


from typing import Optional, List
from socket import gethostname

from helaocore.schema import Experiment, ActionPlanMaker
# from helaocore.model.action_start_condition import ActionStartCondition
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
    apm = ActionPlanMaker() # exposes function parameters via apm.pars
    
    
    apm.add(PAL_server, "db_new_sample",
                        {
                          "fast_samples_in": 
                              [LiquidSample(**{
                                              "machine_name":gethostname(),
                                              "source": apm.pars.source,
                                              "volume_ml": apm.pars.volume_ml,
                                              "chemical": apm.pars.chemical,
                                              "mass": apm.pars.mass,
                                              "supplier": apm.pars.supplier,
                                              "lot_number": apm.pars.lot_number,
                                              "comment": apm.pars.comment,
                             })],
                          })


    return apm.action_list # returns complete action list to orch


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
    apm = ActionPlanMaker() # exposes function parameters via apm.pars

    apm.add(PAL_server, "db_new_sample",
                          {"fast_samples_in": 
                              [GasSample(**{
                                              "machine_name":gethostname(),
                                              "source": apm.pars.source,
                                              "volume_ml": apm.pars.volume_ml,
                                              "chemical": apm.pars.chemical,
                                              "mass": apm.pars.mass,
                                              "supplier": apm.pars.supplier,
                                              "lot_number": apm.pars.lot_number,
                                              "comment": apm.pars.comment,
                             })],
                          })

    return apm.action_list # returns complete action list to orch


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
    apm = ActionPlanMaker() # exposes function parameters via apm.pars
    # check first 
    if len(apm.pars.solid_plate_ids) != len(apm.pars.solid_sample_nos):
        print(f"!!! ERROR: len(solid_plate_ids) != len(solid_sample_nos): "
              f"{len(apm.pars.solid_plate_ids)} != {len(apm.pars.solid_sample_nos)}")
        return apm.action_list


    liquid_list = [LiquidSample(machine_name=gethostname(), sample_no=sample_no) for sample_no in apm.pars.liquid_sample_nos]
    gas_list = [GasSample(machine_name=gethostname(), sample_no=sample_no) for sample_no in apm.pars.gas_sample_nos]
    solid_list = [SolidSample(machine_name="legacy", plate_id=plate_id, sample_no=sample_no) for plate_id, sample_no in zip(apm.pars.solid_plate_ids, apm.pars.solid_sample_nos)]

    # combine all samples now in a partlist
    parts = []
    for liquid in liquid_list:
        parts.append(liquid)
    for gas in gas_list:
        parts.append(gas)
    for solid in solid_list:
        parts.append(solid)

    apm.add(PAL_server, "db_new_sample", 
                          {"fast_samples_in": 
                              [AssemblySample(**{
                                              "machine_name":gethostname(),
                                              "parts":parts,
                                              # "source": apm.pars.source,
                                               "volume_ml": apm.pars.volume_ml,
                                              # "chemical": apm.pars.chemical,
                                              # "mass": apm.pars.mass,
                                              # "supplier": apm.pars.supplier,
                                              # "lot_number": apm.pars.lot_number,
                                              "comment": apm.pars.comment,
                             })],
                          })

    return apm.action_list # returns complete action list to orch
