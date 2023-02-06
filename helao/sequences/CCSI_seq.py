"""Sequence library for CCSI"""

__all__ = [
    #"CCSI_initialization_bysteps",
    "CCSI_initialization",
    "CCSI_validation_KOH_procedure",
]

from typing import List
from typing import Optional, Union
from helao.helpers.premodels import ExperimentPlanMaker


SEQUENCES = __all__

# def CCSI_initialization_bysteps(
#     sequence_version: int = 1,
#     headspace_purge_cycles: int = 5,
#     HSpurge1_duration: float = 30,
#     Manpurge1_duration: float = 10,
#     Alphapurge1_duration: float = 10,
#     Probepurge1_duration: float = 10,
#     Sensorpurge1_duration: float = 10,
#     Deltapurge1_duration: float = 10,
#     HSpurge_duration: float = 20, 
#     HSmeasure1_duration: float = 20,
#     CO2measure_duration: float = 20,
#     CO2measure_acqrate: float = 0.1,
#     CO2threshold: float = 1  # value and units????
# ):

#     epm = ExperimentPlanMaker()
    
#     # all off
#     epm.add_experiment("CCSI_sub_alloff",{})
    
#     #purges
#     epm.add_experiment("CCSI_sub_headspace_purge_from_start", {"HSpurge1_duration": HSpurge1_duration})
#     epm.add_experiment("CCSI_sub_solvent_purge", {"Manpurge1_duration": Manpurge1_duration})
#     epm.add_experiment("CCSI_sub_alpha_purge", {"Alphapurge1_duration": Alphapurge1_duration})
#     epm.add_experiment("CCSI_sub_probe_purge", {"Probepurge1_duration": Probepurge1_duration})
#     epm.add_experiment("CCSI_sub_sensor_purge", {"Sensorpurge1_duration": Sensorpurge1_duration})
#     epm.add_experiment("CCSI_sub_delta_purge", {"Deltapurge1_duration": Deltapurge1_duration})
#     for _ in range(headspace_purge_cycles):
#         epm.add_experiment("CCSI_sub_headspace_purge_and_measure", {"HSpurge_duration": HSpurge_duration, "HSmeasure1_duration":HSmeasure1_duration, "CO2measure_duration": CO2measure_duration, "CO2measure_acqrate": CO2measure_acqrate})
#     epm.add_experiment("CCSI_sub_initialization_end_state", {})

#     return epm.experiment_plan_list

def CCSI_initialization(
    sequence_version: int = 2,
    headspace_purge_cycles: int = 5,
    HSpurge1_duration: float = 30,
    Manpurge1_duration: float = 10,
    Alphapurge1_duration: float = 10,
    Probepurge1_duration: float = 10,
    Sensorpurge1_duration: float = 10,
    Deltapurge1_duration: float = 10,
    HSpurge_duration: float = 20, 
 #   HSmeasure1_duration: float = 20,
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
        epm.add_experiment("CCSI_sub_headspace_purge_and_measure", {"HSpurge_duration": HSpurge_duration, "co2measure_duration": CO2measure_duration, "co2measure_acqrate": CO2measure_acqrate, "co2_ppm_thresh": CO2threshold, "purge_if": "below"})
    epm.add_experiment("CCSI_sub_initialization_end_state", {})

    return epm.experiment_plan_list


def CCSI_validation_KOH_procedure(
    sequence_version: int = 2,
    gas_sample_no: int = 1,
    KOH_volume_ul: float = 500,
    KOH_reservoir_sample_no: int = 2,
    water_volume_ul: float = 2500,
    Waterclean_reservoir_sample_no: int = 1,
    retraction_volume_ul: float =150,
    syringe_rate_ulsec: float = 300,
    LiquidFillWait_s: float = 15,
    co2measure_duration: float = 120,
    co2measure_acqrate: float = 1,
    drainclean_volume_ul: float = 9000,
    headspace_purge_cycles: int = 1,
    liquid_purge_cycles: int = 1,
    clean_co2measure_duration: float = 120,
    clean_co2_ppm_thresh: float = 90000,
    purge_if: Union[str, float] = "below",
    HSpurge_duration: float = 30,
    purge_co2measure_duration: float = 20,
    purge_co2threshhold: float = 95000,
    
):

    epm = ExperimentPlanMaker()

    epm.add_experiment("CCSI_sub_unload_cell",{})
    epm.add_experiment("CCSI_sub_load_solid", {})

#    epm.add_experiment("CCSI_sub_load_gas", {
#        "reservoir_gas_sample_no": gas_sample_no,
#    })
    epm.add_experiment("CCSI_sub_load_liquid", {
        "reservoir_liquid_sample_no": KOH_reservoir_sample_no,
        "volume_ul_cell_liquid": KOH_volume_ul,
        "water_True_False": False,
    })

    epm.add_experiment("CCSI_sub_load_liquid", {
        "reservoir_liquid_sample_no": Waterclean_reservoir_sample_no,
        "volume_ul_cell_liquid": water_volume_ul,
        "water_True_False": True,
    })

    epm.add_experiment("CCSI_sub_liquidfill_syringes", {
        "Solution_volume_ul": KOH_volume_ul,
        "Waterclean_volume_ul": water_volume_ul,
        "Syringe_retraction_ul": retraction_volume_ul,
        "Syringe_rate_ulsec": syringe_rate_ulsec,
        "LiquidFillWait_s": LiquidFillWait_s,
        "co2measure_duration": co2measure_duration,
        "co2measure_acqrate": co2measure_acqrate,
    })

 #   for _ in range(liquid_purge_cycles):
    epm.add_experiment("CCSI_sub_drain_and_clean", {
    "Waterclean_volume_ul": drainclean_volume_ul,
    "Syringe_retraction_ul": retraction_volume_ul,
    "Syringe_rate_ulsec": syringe_rate_ulsec,
    "LiquidFillWait_s": LiquidFillWait_s,
    "co2measure_duration": clean_co2measure_duration,
    "co2measure_acqrate": co2measure_acqrate,
    "co2_ppm_thresh": clean_co2_ppm_thresh,
    "purge_if": purge_if,
    "HSpurge_duration": HSpurge_duration,
})
#    for _ in range(headspace_purge_cycles):
    epm.add_experiment("CCSI_sub_headspace_purge_and_measure", {"HSpurge_duration": HSpurge_duration, "co2measure_duration": purge_co2measure_duration, "co2measure_acqrate": co2measure_acqrate, "co2_ppm_thresh": purge_co2threshhold, "purge_if": purge_if})

    epm.add_experiment("CCSI_sub_peripumpoff", {})
    epm.add_experiment("CCSI_sub_unload_cell",{})

    return epm.experiment_plan_list
