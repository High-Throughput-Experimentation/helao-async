"""Sequence library for CCSI"""

__all__ = ["ANEC_sample_ready",

]

from typing import List
from typing import Optional
from helao.helpers.premodels import ExperimentPlanMaker


SEQUENCES = __all__

def CCSI_initialization(
    sequence_version: int = 1,
    headspace_purge_cycles: int = 5,
    HSpurge1_duration: float = 20,
    Manpurge1_duration: float = 30,
    Alphapurge1_duration: float = 15,
    Probepurge1_duration: float = 60,
    Sensorpurge1_duration: float = 60,
    Deltapurge1_duration: float = 120,
    HSpurge_duration: float = 20, 
    HSmeasure1_duration: float = 60,
    CO2measure_duration: float = 1,
    CO2measure_acqrate: float = 0.1,
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
        epm.add_experiment("CCSI_sub_headspace_purge", {"HSpurge_duration": HSpurge_duration})
        epm.add_experiment("CCSI_sub_measure_headspace_frompurge",{"HSmeasure1_duration":HSmeasure1_duration, "CO2measure_duration": CO2measure_duration, "CO2measure_acqrate": CO2measure_acqrate})


    return epm.experiment_plan_list
