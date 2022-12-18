"""Sequence library for CCSI"""

__all__ = ["CCSI_initialization",

]

from typing import List
from typing import Optional
from helao.helpers.premodels import ExperimentPlanMaker


SEQUENCES = __all__

def CCSI_initialization(
    sequence_version: int = 1,
    headspace_purge_cycles: int = 5,
    HSpurge1_duration: float = 30,
    Manpurge1_duration: float = 10,
    Alphapurge1_duration: float = 10,
    Probepurge1_duration: float = 10,
    Sensorpurge1_duration: float = 10,
    Deltapurge1_duration: float = 10,
    HSpurge_duration: float = 20, 
    HSmeasure1_duration: float = 20,
    CO2measure_duration: float = 20,
    CO2measure_acqrate: float = 0.1,
    CO2threshold: float = 1  # value and units????
):

    epm = ExperimentPlanMaker()
    
    # all off
    epm.add_experiment("CCSI_sub_alloff",{})
    
    #purges
    epm.add_experiment("CCSI_sub_headspace_purge_from_start", {"HSpurge1_duration": HSpurge1_duration})
    epm.add_experiment("CCSI_sub_solvent_purge", {"Manpurge1_duration": Manpurge1_duration})
    epm.add_experiment("CCSI_sub_alpha_purge", {"Alphapurge1_duration": Alphapurge1_duration})
    epm.add_experiment("CCSI_sub_probe_purge", {"Probepurge1_duration": Probepurge1_duration})
    epm.add_experiment("CCSI_sub_sensor_purge", {"Sensorpurge1_duration": Sensorpurge1_duration})
    epm.add_experiment("CCSI_sub_delta_purge", {"Deltapurge1_duration": Deltapurge1_duration})
    for _ in range(headspace_purge_cycles):
        epm.add_experiment("CCSI_sub_headspace_purge_and_measure", {"HSpurge_duration": HSpurge_duration, "HSmeasure1_duration":HSmeasure1_duration, "CO2measure_duration": CO2measure_duration, "CO2measure_acqrate": CO2measure_acqrate})
    epm.add_experiment("CCSI_sub_initialization_end_state", {})

    return epm.experiment_plan_list

def CCSI_initialization_faster(
    sequence_version: int = 1,
    headspace_purge_cycles: int = 5,
    HSpurge1_duration: float = 30,
    Manpurge1_duration: float = 10,
    Alphapurge1_duration: float = 10,
    Probepurge1_duration: float = 10,
    Sensorpurge1_duration: float = 10,
    Deltapurge1_duration: float = 10,
    HSpurge_duration: float = 20, 
    HSmeasure1_duration: float = 20,
    CO2measure_duration: float = 20,
    CO2measure_acqrate: float = 0.1,
    CO2threshold: float = 1  # value and units????
):

    epm = ExperimentPlanMaker()
    
   #purges
    epm.add_experiment("CCSI_sub_initialization_firstpart", {
        "HSpurge1_duration": HSpurge1_duration,
        "Manpurge1_duration": Manpurge1_duration,
        "Alphapurge1_duration": Alphapurge1_duration,
        "Probepurge1_duration": Probepurge1_duration,
        "Sensorpurge1_duration": Sensorpurge1_duration,
        "Deltapurge1_duration": Deltapurge1_duration
        })
    for _ in range(headspace_purge_cycles):
        epm.add_experiment("CCSI_sub_headspace_purge_and_measure", {"HSpurge_duration": HSpurge_duration, "HSmeasure1_duration":HSmeasure1_duration, "CO2measure_duration": CO2measure_duration, "CO2measure_acqrate": CO2measure_acqrate})
    epm.add_experiment("CCSI_sub_initialization_end_state", {})

    return epm.experiment_plan_list
