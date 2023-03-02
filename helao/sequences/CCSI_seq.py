"""Sequence library for CCSI"""

__all__ = [
    #"CCSI_initialization_bysteps",
    "CCSI_initialization",
#    "CCSI_validation_KOH_procedure",
    "CCSI_repeated_KOH_testing",
    "CCSI_test_KOH_testing",
    "CCSI_debug_liquidloads",
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
#     DeltaDilute1_duration: float = 10,
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
#     epm.add_experiment("CCSI_sub_delta_purge", {"DeltaDilute1_duration": DeltaDilute1_duration})
#     for _ in range(headspace_purge_cycles):
#         epm.add_experiment("CCSI_sub_headspace_purge_and_measure", {"HSpurge_duration": HSpurge_duration, "HSmeasure1_duration":HSmeasure1_duration, "CO2measure_duration": CO2measure_duration, "CO2measure_acqrate": CO2measure_acqrate})
#     epm.add_experiment("CCSI_sub_initialization_end_state", {})

#     return epm.experiment_plan_list

def CCSI_initialization(
    sequence_version: int = 3,
    headspace_purge_cycles: int = 5,
    HSpurge1_duration: float = 60,
    Manpurge1_duration: float = 10,
    Alphapurge1_duration: float = 10,
    Probepurge1_duration: float = 10,
    Sensorpurge1_duration: float = 15,
    DeltaDilute1_duration: float = 10,
    HSpurge_duration: float = 20, 
 #   HSmeasure1_duration: float = 20,
    CO2measure_duration: float = 20,
    CO2measure_acqrate: float = 1,
    CO2threshold: float = 9000  # value and units????
):

    epm = ExperimentPlanMaker()
    
   #purges
    epm.add_experiment("CCSI_sub_initialization_firstpart", {
        "HSpurge1_duration": HSpurge1_duration,
        "Manpurge1_duration": Manpurge1_duration,
        "Alphapurge1_duration": Alphapurge1_duration,
        "Probepurge1_duration": Probepurge1_duration,
        "Sensorpurge1_duration": Sensorpurge1_duration,
        })

    epm.add_experiment("CCSI_sub_drain", {
        "HSpurge_duration": HSpurge_duration,
        "DeltaDilute1_duration": DeltaDilute1_duration,
        "initialization": True,
        })
    epm.add_experiment("CCSI_sub_headspace_purge_and_measure", {
        "HSpurge_duration": HSpurge_duration, 
        "DeltaDilute1_duration": DeltaDilute1_duration,
        "initialization": True,
        "co2measure_duration": CO2measure_duration, 
        "co2measure_acqrate": CO2measure_acqrate, 
        "co2_ppm_thresh": CO2threshold, 
        "purge_if": "below"
        })
    epm.add_experiment("CCSI_sub_initialization_end_state", {})

    return epm.experiment_plan_list


def CCSI_validation_KOH_procedure(
    sequence_version: int = 3,
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
    LiquidCleanPurge_duration: float = 60,
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
    epm.add_experiment("CCSI_sub_drain", {"HSpurge_duration": LiquidCleanPurge_duration})

 #   for _ in range(liquid_purge_cycles):
    epm.add_experiment("CCSI_sub_clean_inject", {
    "Waterclean_volume_ul": drainclean_volume_ul,
    "Syringe_retraction_ul": retraction_volume_ul,
    "Syringe_rate_ulsec": syringe_rate_ulsec,
    "LiquidFillWait_s": LiquidFillWait_s,
    "co2measure_duration": clean_co2measure_duration,
    "co2measure_acqrate": co2measure_acqrate,
    "co2_ppm_thresh": clean_co2_ppm_thresh,
    "purge_if": purge_if,
    "HSpurge_duration": LiquidCleanPurge_duration,
})
#    for _ in range(headspace_purge_cycles):
    epm.add_experiment("CCSI_sub_headspace_purge_and_measure", {"HSpurge_duration": LiquidCleanPurge_duration, "co2measure_duration": purge_co2measure_duration, "co2measure_acqrate": co2measure_acqrate, "co2_ppm_thresh": purge_co2threshhold, "purge_if": purge_if})

    epm.add_experiment("CCSI_sub_peripumpoff", {})
    epm.add_experiment("CCSI_sub_unload_cell",{})

    return epm.experiment_plan_list

def CCSI_repeated_KOH_testing(  #assumes initialization performed previously
    sequence_version: int = 1,
    gas_sample_no: int = 1,
    KOH_volume_ul: List[float] = [0,500, 50],
    KOH_reservoir_sample_no: int = 2,
    total_sample_volume_ul: float = 5000,
    Waterclean_reservoir_sample_no: int = 1,
    deadspace_volume_ul: float =50,
    backlash_volume_ul: float = 50,
    Syringe_retraction_ul: float = 150,
    syringe_rate_ulsec: float = 300,
    LiquidFillWait_s: float = 20,
    co2measure_duration: float = 300,
    co2measure_acqrate: float = 1,
    drainclean_volume_ul: float = 10000,
    headspace_purge_cycles: int = 2,
#    liquid_purge_cycles: int = 1,
    headspace_co2measure_duration: float = 30,
    clean_co2measure_duration: float = 120,
    LiquidCleanPurge_duration: float = 60,
#    clean_co2_ppm_thresh: float = 90000,
#    purge_if: Union[str, float] = "below",
    HSpurge_duration: float = 15,
    DeltaDilute1_duration: float = 15,
#    purge_co2measure_duration: float = 20,
#    purge_co2threshhold: float = 95000,
    
):

    epm = ExperimentPlanMaker()
    for KOHvolume in KOH_volume_ul:  # have to indent add expts if used
        if KOHvolume == 0:
            cleanloop = 1
        else:
            cleanloop = 4

        epm.add_experiment("CCSI_sub_unload_cell",{})

        epm.add_experiment("CCSI_sub_load_gas", {
            "reservoir_gas_sample_no": gas_sample_no,
            "volume_ul_cell_gas": 5000,
        })
        if KOHvolume != 0:
            epm.add_experiment("CCSI_sub_load_liquid", {
                "reservoir_liquid_sample_no": KOH_reservoir_sample_no,
                "volume_ul_cell_liquid": KOHvolume,
                "combine_True_False": False,
                "water_True_False": False,
            })
        watervolume = total_sample_volume_ul - KOHvolume
        if watervolume != 0:
            epm.add_experiment("CCSI_sub_load_liquid", {
                "reservoir_liquid_sample_no": Waterclean_reservoir_sample_no,
                "volume_ul_cell_liquid": watervolume,
                "combine_True_False": True,
                "water_True_False": True,
            })

        epm.add_experiment("CCSI_sub_liquidfill_syringes", {
            "Solution_volume_ul": KOHvolume,
            "Waterclean_volume_ul": watervolume,
            "deadspace_volume_ul": deadspace_volume_ul,
            "backlash_volume_ul": backlash_volume_ul,
            "Syringe_retraction_ul": Syringe_retraction_ul,
            "Syringe_rate_ulsec": syringe_rate_ulsec,
            "LiquidFillWait_s": LiquidFillWait_s,
            "co2measure_duration": co2measure_duration,
            "co2measure_acqrate": co2measure_acqrate,
        })
        epm.add_experiment("CCSI_sub_drain", {"HSpurge_duration": LiquidCleanPurge_duration})

        for _ in range(cleanloop):
            epm.add_experiment("CCSI_sub_clean_inject", {
                "Waterclean_volume_ul": drainclean_volume_ul,
                "deadspace_volume_ul": deadspace_volume_ul,
                "backlash_volume_ul": backlash_volume_ul,
                "Syringe_rate_ulsec": syringe_rate_ulsec,
                "Syringe_retraction_ul": Syringe_retraction_ul,
                "LiquidCleanWait_s": LiquidFillWait_s,
                "LiquidCleanPurge_duration": LiquidCleanPurge_duration,
                "co2measure_duration": clean_co2measure_duration,
                "co2measure_acqrate": co2measure_acqrate,
              #  "co2_ppm_thresh": clean_co2_ppm_thresh,
              #  "purge_if": purge_if,
              #  "HSpurge_duration": LiquidCleanPurge_duration,
            })
            epm.add_experiment("CCSI_sub_drain", {"HSpurge_duration": LiquidCleanPurge_duration})

        refill_volume = watervolume + drainclean_volume_ul*cleanloop
        epm.add_experiment("CCSI_sub_refill_clean", {
            "Waterclean_volume_ul": refill_volume ,
            "deadspace_volume_ul": deadspace_volume_ul,
            "Syringe_rate_ulsec": 1000,
        })
    
        for _ in range(headspace_purge_cycles):
            epm.add_experiment("CCSI_sub_drain", {
                "HSpurge_duration": HSpurge_duration,
                "DeltaDilute1_duration": DeltaDilute1_duration,
                })

    return epm.experiment_plan_list

def CCSI_test_KOH_testing(  #assumes initialization performed previously
    sequence_version: int = 1,
    gas_sample_no: int = 1,
    KOH_volume_ul: List[float] = [0,500, 50],
    KOH_reservoir_sample_no: int = 2,
    total_sample_volume_ul: float = 5000,
    Waterclean_reservoir_sample_no: int = 1,
    deadspace_volume_ul: float =50,
    backlash_volume_ul: float = 50,
    Syringe_retraction_ul: float = 150,
    syringe_rate_ulsec: float = 300,
    LiquidFillWait_s: float = 20,
    co2measure_duration: float = 300,
    co2measure_acqrate: float = 1,
    drainclean_volume_ul: float = 10000,
    headspace_purge_cycles: int = 2,
#    liquid_purge_cycles: int = 1,
    headspace_co2measure_duration: float = 30,
    clean_co2measure_duration: float = 120,
    LiquidCleanPurge_duration: float = 60,
#    clean_co2_ppm_thresh: float = 90000,
#    purge_if: Union[str, float] = "below",
    HSpurge_duration: float = 15,
    DeltaDilute1_duration: float = 15,
#    purge_co2measure_duration: float = 20,
#    purge_co2threshhold: float = 95000,
    
):

    epm = ExperimentPlanMaker()
    for KOHvolume in KOH_volume_ul:  # have to indent add expts if used
        # if KOHvolume == 0:
        #     cleanloop = 1
        # else:
        cleanloop = 4

        epm.add_experiment("CCSI_sub_unload_cell",{})

        epm.add_experiment("CCSI_sub_load_gas", {
            "reservoir_gas_sample_no": gas_sample_no,
            "volume_ul_cell_gas": 5000,
        })
        if KOHvolume != 0:
            epm.add_experiment("CCSI_sub_load_liquid", {
                "reservoir_liquid_sample_no": KOH_reservoir_sample_no,
                "volume_ul_cell_liquid": KOHvolume,
                "combine_True_False": False,
                "water_True_False": False,
            })
        watervolume = total_sample_volume_ul - KOHvolume
        if watervolume != 0:
            epm.add_experiment("CCSI_sub_load_liquid", {
                "reservoir_liquid_sample_no": Waterclean_reservoir_sample_no,
                "volume_ul_cell_liquid": watervolume,
                "combine_True_False": True,
                "water_True_False": True,
            })

        epm.add_experiment("CCSI_sub_liquidfill_syringes", {
            "Solution_volume_ul": KOHvolume,
            "Waterclean_volume_ul": watervolume,
            "deadspace_volume_ul": deadspace_volume_ul,
            "backlash_volume_ul": backlash_volume_ul,
            "Syringe_retraction_ul": Syringe_retraction_ul,
            "Syringe_rate_ulsec": syringe_rate_ulsec,
            "LiquidFillWait_s": LiquidFillWait_s,
            "co2measure_duration": co2measure_duration,
            "co2measure_acqrate": co2measure_acqrate,
        })
        epm.add_experiment("CCSI_sub_drain", {"HSpurge_duration": LiquidCleanPurge_duration,"DeltaDilute1_duration": DeltaDilute1_duration,})

        for _ in range(cleanloop):
            epm.add_experiment("CCSI_sub_clean_inject", {
                "Waterclean_volume_ul": drainclean_volume_ul,
                "deadspace_volume_ul": deadspace_volume_ul,
                "backlash_volume_ul": backlash_volume_ul,
                "Syringe_rate_ulsec": syringe_rate_ulsec,
                "Syringe_retraction_ul": Syringe_retraction_ul,
                "LiquidCleanWait_s": LiquidFillWait_s,
                "LiquidCleanPurge_duration": LiquidCleanPurge_duration,
                "co2measure_duration": clean_co2measure_duration,
                "co2measure_acqrate": co2measure_acqrate,
            #    "co2_ppm_thresh": clean_co2_ppm_thresh,
            #    "purge_if": purge_if,
              #  "HSpurge_duration": LiquidCleanPurge_duration,
            })
            epm.add_experiment("CCSI_sub_drain", {"HSpurge_duration": LiquidCleanPurge_duration,})

        refill_volume = watervolume + drainclean_volume_ul*cleanloop
        epm.add_experiment("CCSI_sub_refill_clean", {
            "Waterclean_volume_ul": refill_volume ,
            "deadspace_volume_ul": deadspace_volume_ul,
            "Syringe_rate_ulsec": 1000,
        })
    
        for _ in range(headspace_purge_cycles):
            epm.add_experiment("CCSI_sub_drain", {
                "HSpurge_duration": HSpurge_duration,
                "DeltaDilute1_duration": DeltaDilute1_duration,
                })

    return epm.experiment_plan_list

def CCSI_debug_liquidloads(  #assumes initialization performed previously
    sequence_version: int = 1,
    gas_sample_no: int = 1,
    KOH_volume_ul: float = 1000,
    KOH_reservoir_sample_no: int = 2,
    total_sample_volume_ul: float = 5000,
    Waterclean_reservoir_sample_no: int = 1,
    
):

    epm = ExperimentPlanMaker()

    epm.add_experiment("CCSI_sub_unload_cell",{})

    epm.add_experiment("CCSI_sub_load_gas", {
        "reservoir_gas_sample_no": gas_sample_no,
        "volume_ul_cell_gas": 5000,
    })
    epm.add_experiment("CCSI_sub_load_liquid", {
        "reservoir_liquid_sample_no": KOH_reservoir_sample_no,
        "volume_ul_cell_liquid": KOH_volume_ul,
        "water_True_False": False,
        "combine_True_False": False,
    })
    watervolume = total_sample_volume_ul - KOH_volume_ul

    epm.add_experiment("CCSI_sub_load_liquid", {
        "reservoir_liquid_sample_no": Waterclean_reservoir_sample_no,
        "volume_ul_cell_liquid": watervolume,
        "water_True_False": True,
        "combine_True_False": True,
    })

###############
    epm.add_experiment("CCSI_sub_unload_cell",{})

    # epm.add_experiment("CCSI_sub_load_gas", {
    #     "reservoir_gas_sample_no": gas_sample_no,
    #     "volume_ul_cell_gas": 5000,
    # })
    epm.add_experiment("CCSI_sub_load_liquid", {
        "reservoir_liquid_sample_no": KOH_reservoir_sample_no,
        "volume_ul_cell_liquid": KOH_volume_ul,
        "water_True_False": False,
        "combine_True_False": False,
    })
    watervolume = total_sample_volume_ul - KOH_volume_ul

    epm.add_experiment("CCSI_sub_load_liquid", {
        "reservoir_liquid_sample_no": Waterclean_reservoir_sample_no,
        "volume_ul_cell_liquid": watervolume,
        "water_True_False": True,
        "combine_True_False": True,
    })

    epm.add_experiment("CCSI_sub_load_gas", {
        "reservoir_gas_sample_no": gas_sample_no,
        "volume_ul_cell_gas": 5000,
    })

    ###############
    epm.add_experiment("CCSI_sub_unload_cell",{})

    epm.add_experiment("CCSI_sub_load_liquid", {
        "reservoir_liquid_sample_no": KOH_reservoir_sample_no,
        "volume_ul_cell_liquid": KOH_volume_ul,
        "water_True_False": False,
        "combine_True_False": False,
    })
    epm.add_experiment("CCSI_sub_load_gas", {
        "reservoir_gas_sample_no": gas_sample_no,
        "volume_ul_cell_gas": 5000,
    })
    watervolume = total_sample_volume_ul - KOH_volume_ul

    epm.add_experiment("CCSI_sub_load_liquid", {
        "reservoir_liquid_sample_no": Waterclean_reservoir_sample_no,
        "volume_ul_cell_liquid": watervolume,
        "water_True_False": True,  #dilution volume
        "combine_True_False": True,
    })

    # ###############
    # epm.add_experiment("CCSI_sub_unload_cell",{})

    # # epm.add_experiment("CCSI_sub_load_gas", {
    # #     "reservoir_gas_sample_no": gas_sample_no,
    # #     "volume_ul_cell_gas": 5000,
    # # })
    # epm.add_experiment("CCSI_sub_load_liquid", {
    #     "reservoir_liquid_sample_no": KOH_reservoir_sample_no,
    #     "volume_ul_cell_liquid": KOH_volume_ul,
    #     "water_True_False": False,
    #     "combine_True_False": False,
    # })
    # watervolume = total_sample_volume_ul - KOH_volume_ul

    # epm.add_experiment("CCSI_sub_load_liquid", {
    #     "reservoir_liquid_sample_no": Waterclean_reservoir_sample_no,
    #     "volume_ul_cell_liquid": watervolume,
    #     "water_True_False": True,  #dilution volume
    #     "combine_True_False": False,
    # })

    return epm.experiment_plan_list
