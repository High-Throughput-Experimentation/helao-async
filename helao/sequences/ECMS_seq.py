"""Sequence library for CCSI"""

__all__ = [
    #"CCSI_initialization_bysteps",
    "CCSI_initialization",
#    "CCSI_validation_KOH_procedure",
    #"CCSI_repeated_KOH_testing",
#    "CCSI_test_KOH_testing",
#    "CCSI_newer_KOH_testing",
    "CCSI_Solution_testing",
    "CCSI_Solution_test_constantpressure",
    "CCSI_Solution_testing_fixed_cleans",
    "CCSI_priming",
    "CCSI_leaktest",
    #"CCSI_debug_liquidloads",
]

from typing import List
from typing import Optional, Union
from helao.helpers.premodels import ExperimentPlanMaker


SEQUENCES = __all__


# =============================================================================
#     experiment: Experiment,
#     experiment_version: int = 1,
#     liquid_forward_time: float = 20,
#     liquid_backward_time: float = 10,
#     reservoir_liquid_sample_no: int = 1511,
#     volume_ul_cell_liquid: int = 1
# ):
# =============================================================================
def ANEC_series_CA(
    sequence_version: int = 1,
    plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: float = 1000,
    WE_potential__V: List[float] = [-0.9, -1.0, -1.1, -1.2, -1.3],
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CA_duration_sec: List[float] = [900, 900, 900, 900, 900],
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    toolGC: str = "HS 2",
    toolarchive: str = "LS 3",
    volume_ul_GC: int = 300,
    volume_ul_archive: int = 500,
    liquidDrain_time: float = 80.0,
    wash1: bool = True,
    wash2: bool = True,
    wash3: bool = True,
    wash4: bool = False,
):
    """running CA at different potentials and aliquot sampling at the cell1_we position.

    Flush and fill cell, run CA, and drain.

    (1) Fill cell with liquid for 90 seconds
    (2) Equilibrate for 15 seconds
    (3) run CA
    (4) mix product
    (5) Drain cell and purge with CO2 for 60 seconds

    Args:
        exp (Experiment): Active experiment object supplied by Orchestrator
        toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
        volume_ul_GC: GC injection volume



    """

    epm = ExperimentPlanMaker()

    # housekeeping
    epm.add_experiment("ECMS_sub_unload_cell", {})

    #epm.add_experiment("ANEC_sub_normal_state", {})

    epm.add_experiment(
        "ECMS_sub_load_solid",
        {"solid_plate_id": plate_id, "solid_sample_no": solid_sample_no},
    )

    for cycle, (potential, time) in enumerate(zip(WE_potential__V, CA_duration_sec)):
        print(f" ... cycle {cycle} potential:", potential, f" ... cycle {cycle} duration:", time)

        epm.add_experiment(
            "ECMS_sub_electrolyte_fill_cell",
            {
                "liquid_flush_time": 80,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )

        epm.add_experiment("ECMS_sub_prevacuum_cell",{})

        epm.add_experiment(
            "ECMS__sub_headspace_purge_and_CO2baseline",
            {
                "liquid_flush_time": 80,
                "co2_purge_time": 15,
                "equilibration_time": 1.0,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "volume_ul_cell_liquid": volume_ul_cell_liquid,
            },
        )
        
        epm.add_experiment(
            "ECMS_sub_CA",
            {
                "WE_potential__V": potential,
                "WE_versus": WE_versus,
                "ref_type": ref_type,
                "pH": pH,
                "ref_offset__V": ref_offset__V,
                "CA_duration_sec": time,
                "SampleRate": SampleRate,
                "IErange": IErange,
            },
        )

        epm.add_experiment("ECMS_sub_drain",{"liquid_drain_time": liquid_drain_time})


        epm.add_experiment("ECMS_sub_drain_cell", {"drain_time": liquidDrain_time})

    epm.add_experiment("ECMS_sub_alloff", {})
    
    return epm.experiment_plan_list















def CCSI_initialization(
    sequence_version: int = 4, #removed subdrain, added clean inject
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
    CO2threshold: float = 9000,  # value and units????
    Waterclean_volume_ul: float = 10000,
    Syringe_rate_ulsec: float = 500,
    LiquidCleanWait_s: float = 15,
    use_co2_check: bool = True,
    need_fill: bool = False,
    max_repeats: int = 5,
    drainrecirc: bool = True,
):

    epm = ExperimentPlanMaker()

#    
# MAIN HEADSPACE PURGE, AUX PROBE PURGE, PCO2 SENSOR PURGE
    epm.add_experiment("CCSI_sub_initialization_firstpart", {
        "HSpurge1_duration": HSpurge1_duration,
        "Manpurge1_duration": Manpurge1_duration,
        "Alphapurge1_duration": Alphapurge1_duration,
        "Probepurge1_duration": Probepurge1_duration,
        "Sensorpurge1_duration": Sensorpurge1_duration,
        })

#
# DILUTION PURGE, MAIN HEADSPACE PURGE AND HEADSPACE EVALUATION
    epm.add_experiment("CCSI_sub_headspace_purge_and_measure", {
        "HSpurge_duration": HSpurge_duration, 
        "DeltaDilute1_duration": DeltaDilute1_duration,
        "initialization": True,
        "co2measure_duration": CO2measure_duration, 
        "co2measure_acqrate": CO2measure_acqrate, 
        "co2_ppm_thresh": CO2threshold, 
        "purge_if": "below"
        })
#    
# PRE CLEAN PROCEDURE
    epm.add_experiment("CCSI_sub_clean_inject", {
        "Waterclean_volume_ul": Waterclean_volume_ul,
        "Syringe_rate_ulsec": Syringe_rate_ulsec,
        "LiquidCleanWait_s": LiquidCleanWait_s,
        "use_co2_check": use_co2_check,
        "LiquidCleanPurge_duration": HSpurge_duration, 
        "DeltaDilute1_duration": DeltaDilute1_duration,
        "initialization": True,
        "co2measure_duration": CO2measure_duration, 
        "co2measure_acqrate": CO2measure_acqrate, 
        "use_co2_check": False,
        "co2_ppm_thresh": CO2threshold, 
        "purge_if": "below",
        "drainrecirc": drainrecirc,
        })
    epm.add_experiment("CCSI_sub_clean_inject", {
        "Waterclean_volume_ul": Waterclean_volume_ul,
        "Syringe_rate_ulsec": Syringe_rate_ulsec,
        "LiquidCleanWait_s": LiquidCleanWait_s,
        "use_co2_check": use_co2_check,
        "LiquidCleanPurge_duration": HSpurge_duration, 
        "DeltaDilute1_duration": DeltaDilute1_duration,
        "initialization": True,
        "co2measure_duration": 0, 
        "use_co2_check": False,
        "drainrecirc": drainrecirc,
        "need_fill": need_fill,
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
    clean_co2_ppm_thresh: float = 41000,
    purge_if: Union[str, float] = "below",
    HSpurge_duration: float = 15,
    DeltaDilute1_duration: float = 15,
    cleanloops: int = 2,
#    purge_co2measure_duration: float = 20,
#    purge_co2threshhold: float = 95000,
    
):

    epm = ExperimentPlanMaker()
    for KOHvolume in KOH_volume_ul:  # have to indent add expts if used
        # if KOHvolume == 0:
        #     cleanloop = 1
        # else:
        #cleanloop = 2

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
#        epm.add_experiment("CCSI_sub_drain_wcirc", {"HSpurge_duration": LiquidCleanPurge_duration})

        for _ in range(cleanloops):
        #cleanloops = 1
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
                "co2_ppm_thresh": clean_co2_ppm_thresh,
                "purge_if": purge_if,
                #  "HSpurge_duration": LiquidCleanPurge_duration,
            })
            #epm.add_experiment("CCSI_sub_drain", {"HSpurge_duration": LiquidCleanPurge_duration,})

        refill_volume = watervolume + drainclean_volume_ul*cleanloops
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

def CCSI_newer_KOH_testing(  #assumes initialization performed previously
    sequence_version: int = 2,
    gas_sample_no: int = 1,
    KOH_volume_ul: List[float] = [0,500, 50],
    KOH_reservoir_sample_no: int = 2,
    total_sample_volume_ul: float = 5000,
    Waterclean_reservoir_sample_no: int = 1,
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
    clean_co2_ppm_thresh: float = 41000,
#    purge_if: Union[str, float] = "below",
    HSpurge_duration: float = 15,
    DeltaDilute1_duration: float = 15,
    cleanloops: int = 2,
    initcleans: int = 2,
    drainrecirc: bool = True,
#    purge_co2measure_duration: float = 20,
#    purge_co2threshhold: float = 95000,
    
):

    epm = ExperimentPlanMaker()
    for _ in range(initcleans):
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
            "co2_ppm_thresh": clean_co2_ppm_thresh,
            "purge_if": purge_if,
            "drainrecirc": drainrecirc,
            #  "HSpurge_duration": LiquidCleanPurge_duration,
        })

    refill_volume = drainclean_volume_ul*(init)
    epm.add_experiment("CCSI_sub_refill_clean", {
        "Waterclean_volume_ul": refill_volume ,
        "deadspace_volume_ul": deadspace_volume_ul,
        "Syringe_rate_ulsec": 1000,
    })

    for KOHvolume in KOH_volume_ul:  # have to indent add expts if used
        # if KOHvolume == 0:
        #     cleanloop = 1
        # else:
        #cleanloop = 2

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
        epm.add_experiment("CCSI_sub_drain", {"HSpurge_duration": LiquidCleanPurge_duration,"DeltaDilute1_duration": DeltaDilute1_duration,"recirculation":drainrecirc,})

        for _ in range(cleanloops):
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
                "co2_ppm_thresh": clean_co2_ppm_thresh,
                "purge_if": purge_if,
                #  "HSpurge_duration": LiquidCleanPurge_duration,
            })
        #epm.add_experiment("CCSI_sub_drain", {"HSpurge_duration": LiquidCleanPurge_duration,})

        refill_volume = watervolume + drainclean_volume_ul*(cleanloops)
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

def CCSI_Solution_testing(  #assumes initialization performed previously
    sequence_version: int = 6, #6 split of liquidfill to cellfill and co2monitoring exps
    gas_sample_no: int = 2,
    Solution_volume_ul: List[float] = [0,500, 50],
    Solution_reservoir_sample_no: int = 2,
    Solution_name: str = "",
    total_sample_volume_ul: float = 5000,
    Waterclean_reservoir_sample_no: int = 1,
    syringe_rate_ulsec: float = 300,
    LiquidFillWait_s: float = 20,
    co2measure_duration: float = 300,
    co2measure_acqrate: float = 1,
    drainclean_volume_ul: float = 10000,
    headspace_purge_cycles: int = 2,
#    liquid_purge_cycles: int = 1,
    headspace_co2measure_duration: float = 30,
    clean_co2measure_duration: float = 120,
    SamplePurge_duration: float = 60,
    LiquidCleanPurge_duration: float = 100,
    clean_co2_ppm_thresh: float = 51500,
    max_repeats: int = 5,
    purge_if: Union[str, float] = 0.03,
    HSpurge_duration: float = 15,
    DeltaDilute1_duration: float = 15,
    #initcleans: int = 3,
    drainrecirc: bool = True,
    need_fill: bool = False,
    
):

    epm = ExperimentPlanMaker()
    #for _ in range(initcleans):
    epm.add_experiment("CCSI_sub_clean_inject", {
        "Waterclean_volume_ul": drainclean_volume_ul,
        "Syringe_rate_ulsec": syringe_rate_ulsec,
        "LiquidCleanWait_s": LiquidFillWait_s,
        "LiquidCleanPurge_duration": LiquidCleanPurge_duration,
        "co2measure_duration": clean_co2measure_duration,
        "co2measure_acqrate": co2measure_acqrate,
        "use_co2_check": True,
        "co2_ppm_thresh": clean_co2_ppm_thresh,
        "max_repeats": max_repeats,
        "purge_if": purge_if,
        "drainrecirc": drainrecirc,
        "need_fill": need_fill,
        #  "HSpurge_duration": LiquidCleanPurge_duration,
    })

    epm.add_experiment("CCSI_sub_full_fill_syringe", {
        "syringe": "waterclean",
        "target_volume_ul": 55000 ,
        "Syringe_rate_ulsec": 1000,
    })

    for solnvolume in Solution_volume_ul:  

        epm.add_experiment("CCSI_sub_unload_cell",{})

        epm.add_experiment("CCSI_sub_load_gas", {
            "reservoir_gas_sample_no": gas_sample_no,
            "volume_ul_cell_gas": 5000,
        })
        if solnvolume != 0:
            epm.add_experiment("CCSI_sub_load_liquid", {
                "reservoir_liquid_sample_no": Solution_reservoir_sample_no,
                "volume_ul_cell_liquid": solnvolume,
                "combine_True_False": False,
                "water_True_False": False,
            })
        watervolume = total_sample_volume_ul - solnvolume
        if watervolume != 0:
            epm.add_experiment("CCSI_sub_load_liquid", {
                "reservoir_liquid_sample_no": Waterclean_reservoir_sample_no,
                "volume_ul_cell_liquid": watervolume,
                "combine_True_False": True,
                "water_True_False": True,
            })

        epm.add_experiment("CCSI_sub_cellfill", {
            "Solution_volume_ul": solnvolume,
            "Waterclean_volume_ul": watervolume,
            "Syringe_rate_ulsec": syringe_rate_ulsec,
            "LiquidFillWait_s": LiquidFillWait_s,
        })
        epm.add_experiment("CCSI_sub_co2monitoring", {
            "co2measure_duration": co2measure_duration,
            "co2measure_acqrate": co2measure_acqrate,
        })
        epm.add_experiment("CCSI_sub_drain", {"HSpurge_duration": SamplePurge_duration,"DeltaDilute1_duration": DeltaDilute1_duration,"recirculation":drainrecirc,})

        epm.add_experiment("CCSI_sub_clean_inject", {
            "Waterclean_volume_ul": drainclean_volume_ul,
            "Syringe_rate_ulsec": syringe_rate_ulsec,
            "LiquidCleanWait_s": LiquidFillWait_s,
            "LiquidCleanPurge_duration": LiquidCleanPurge_duration,
            "co2measure_duration": clean_co2measure_duration,
            "co2measure_acqrate": co2measure_acqrate,
            "use_co2_check": True,
            "co2_ppm_thresh": clean_co2_ppm_thresh,
            "purge_if": purge_if,
            "max_repeats": max_repeats,
            "drainrecirc": drainrecirc,
            #  "HSpurge_duration": LiquidCleanPurge_duration,
        })

        epm.add_experiment("CCSI_sub_full_fill_syringe", {
            "syringe": "waterclean",
            "target_volume_ul": 55000 ,
            "Syringe_rate_ulsec": 1000,
        })
    
        for _ in range(headspace_purge_cycles):
            epm.add_experiment("CCSI_sub_drain", {
                "HSpurge_duration": HSpurge_duration,
                "DeltaDilute1_duration": DeltaDilute1_duration,
                })

    return epm.experiment_plan_list

def CCSI_Solution_test_constantpressure(  #assumes initialization performed previously
    sequence_version: int = 6, #4 new threshold criteria 5, sample purgetime, 6 no preclean
    gas_sample_no: int = 2,
    Solution_volume_ul: List[float] = [0,500, 50],
    Solution_reservoir_sample_no: int = 2,
    Solution_name: str = "",
    total_sample_volume_ul: float = 5000,
    Waterclean_reservoir_sample_no: int = 1,
    syringe_rate_ulsec: float = 300,
    LiquidFillWait_s: float = 20,
    co2measure_duration: float = 300,
    co2measure_acqrate: float = 1,
    atm_pressure: float = 14.27,
    pressureramp: float = 2,
    drainclean_volume_ul: float = 10000,
    headspace_purge_cycles: int = 2,
#    liquid_purge_cycles: int = 1,
    headspace_co2measure_duration: float = 30,
    clean_co2measure_duration: float = 120,
    SamplePurge_duration: float = 60,
    LiquidCleanPurge_duration: float = 100,
    clean_co2_ppm_thresh: float = 51500,
    max_repeats: int = 5,
    purge_if: Union[str, float] = 0.03,
    HSpurge_duration: float = 15,
    DeltaDilute1_duration: float = 15,
    #initcleans: int = 3,
    drainrecirc: bool = True,
    need_fill: bool = False,
    
):

    epm = ExperimentPlanMaker()
    # #for _ in range(initcleans):
    # epm.add_experiment("CCSI_sub_clean_inject", {
    #     "Waterclean_volume_ul": drainclean_volume_ul,
    #     "Syringe_rate_ulsec": syringe_rate_ulsec,
    #     "LiquidCleanWait_s": LiquidFillWait_s,
    #     "LiquidCleanPurge_duration": LiquidCleanPurge_duration,
    #     "co2measure_duration": clean_co2measure_duration,
    #     "co2measure_acqrate": co2measure_acqrate,
    #     "use_co2_check": True,
    #     "co2_ppm_thresh": clean_co2_ppm_thresh,
    #     "max_repeats": max_repeats,
    #     "purge_if": purge_if,
    #     "drainrecirc": drainrecirc,
    #     "need_fill": need_fill,
    #     #  "HSpurge_duration": LiquidCleanPurge_duration,
    # })

    # epm.add_experiment("CCSI_sub_full_fill_syringe", {
    #     "syringe": "waterclean",
    #     "target_volume_ul": 55000 ,
    #     "Syringe_rate_ulsec": 1000,
    # })

    for solnvolume in Solution_volume_ul:  

        epm.add_experiment("CCSI_sub_unload_cell",{})

        epm.add_experiment("CCSI_sub_load_gas", {
            "reservoir_gas_sample_no": gas_sample_no,
            "volume_ul_cell_gas": 5000,
        })
        if solnvolume != 0:
            epm.add_experiment("CCSI_sub_load_liquid", {
                "reservoir_liquid_sample_no": Solution_reservoir_sample_no,
                "volume_ul_cell_liquid": solnvolume,
                "combine_True_False": False,
                "water_True_False": False,
            })
        watervolume = total_sample_volume_ul - solnvolume
        if watervolume != 0:
            epm.add_experiment("CCSI_sub_load_liquid", {
                "reservoir_liquid_sample_no": Waterclean_reservoir_sample_no,
                "volume_ul_cell_liquid": watervolume,
                "combine_True_False": True,
                "water_True_False": True,
            })

        epm.add_experiment("CCSI_sub_cellfill_constantcotwo", {
            "Solution_volume_ul": solnvolume,
            "Waterclean_volume_ul": watervolume,
            "Syringe_rate_ulsec": syringe_rate_ulsec,
            "LiquidFillWait_s": LiquidFillWait_s,
            "co2measure_duration": co2measure_duration,
            "co2measure_acqrate": co2measure_acqrate,
            "atm_pressure" : atm_pressure,
            "pressureramp": pressureramp,
        })
        epm.add_experiment("CCSI_sub_drain", {"HSpurge_duration": SamplePurge_duration,"DeltaDilute1_duration": DeltaDilute1_duration,"recirculation":drainrecirc,})

        epm.add_experiment("CCSI_sub_clean_inject", {
            "Waterclean_volume_ul": drainclean_volume_ul,
            "Syringe_rate_ulsec": syringe_rate_ulsec,
            "LiquidCleanWait_s": LiquidFillWait_s,
            "LiquidCleanPurge_duration": LiquidCleanPurge_duration,
            "co2measure_duration": clean_co2measure_duration,
            "co2measure_acqrate": co2measure_acqrate,
            "use_co2_check": True,
            "co2_ppm_thresh": clean_co2_ppm_thresh,
            "purge_if": purge_if,
            "max_repeats": max_repeats,
            "drainrecirc": drainrecirc,
            #  "HSpurge_duration": LiquidCleanPurge_duration,
        })

        epm.add_experiment("CCSI_sub_full_fill_syringe", {
            "syringe": "waterclean",
            "target_volume_ul": 55000 ,
            "Syringe_rate_ulsec": 1000,
        })
    
        for _ in range(headspace_purge_cycles):
            epm.add_experiment("CCSI_sub_drain", {
                "HSpurge_duration": HSpurge_duration,
                "DeltaDilute1_duration": DeltaDilute1_duration,
                })

    return epm.experiment_plan_list


def CCSI_Solution_testing_fixed_cleans(  #assumes initialization performed previously
    sequence_version: int = 2, #v2 elim front refill
    gas_sample_no: int = 2,
    Solution_volume_ul: List[float] = [0,500, 50],
    Solution_reservoir_sample_no: int = 2,
    Solution_name: str = "",
    total_sample_volume_ul: float = 5000,
    Waterclean_reservoir_sample_no: int = 1,
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
    HSpurge_duration: float = 15,
    DeltaDilute1_duration: float = 15,
    cleanloops: int = 2,
    initcleans: int = 2,
    drainrecirc: bool = True,
    
):

    epm = ExperimentPlanMaker()
    for _ in range(initcleans):
        epm.add_experiment("CCSI_sub_clean_inject", {
            "Waterclean_volume_ul": drainclean_volume_ul,
            "Syringe_rate_ulsec": syringe_rate_ulsec,
            "LiquidCleanWait_s": LiquidFillWait_s,
            "LiquidCleanPurge_duration": LiquidCleanPurge_duration,
            "co2measure_duration": clean_co2measure_duration,
            "co2measure_acqrate": co2measure_acqrate,
            "use_co2_check": False,
            "drainrecirc": drainrecirc,
            #  "HSpurge_duration": LiquidCleanPurge_duration,
        })

    # refill_volume = drainclean_volume_ul*(initcleans)
    # epm.add_experiment("CCSI_sub_refill_clean", {
    #     "Waterclean_volume_ul": refill_volume ,
    #     "Syringe_rate_ulsec": 1000,
    # })

    for solnvolume in Solution_volume_ul:

        epm.add_experiment("CCSI_sub_unload_cell",{})

        epm.add_experiment("CCSI_sub_load_gas", {
            "reservoir_gas_sample_no": gas_sample_no,
            "volume_ul_cell_gas": 5000,
        })
        if solnvolume != 0:
            epm.add_experiment("CCSI_sub_load_liquid", {
                "reservoir_liquid_sample_no": Solution_reservoir_sample_no,
                "volume_ul_cell_liquid": solnvolume,
                "combine_True_False": False,
                "water_True_False": False,
            })
        watervolume = total_sample_volume_ul - solnvolume
        if watervolume != 0:
            epm.add_experiment("CCSI_sub_load_liquid", {
                "reservoir_liquid_sample_no": Waterclean_reservoir_sample_no,
                "volume_ul_cell_liquid": watervolume,
                "combine_True_False": True,
                "water_True_False": True,
            })

        epm.add_experiment("CCSI_sub_liquidfill_syringes", {
            "Solution_volume_ul": solnvolume,
            "Waterclean_volume_ul": watervolume,
            "Syringe_rate_ulsec": syringe_rate_ulsec,
            "LiquidFillWait_s": LiquidFillWait_s,
            "co2measure_duration": co2measure_duration,
            "co2measure_acqrate": co2measure_acqrate,
        })
        epm.add_experiment("CCSI_sub_drain", {"HSpurge_duration": LiquidCleanPurge_duration,"DeltaDilute1_duration": DeltaDilute1_duration,"recirculation":drainrecirc,})

        for _ in range(cleanloops):
            epm.add_experiment("CCSI_sub_clean_inject", {
                "Waterclean_volume_ul": drainclean_volume_ul,
                "Syringe_rate_ulsec": syringe_rate_ulsec,
                "LiquidCleanWait_s": LiquidFillWait_s,
                "LiquidCleanPurge_duration": LiquidCleanPurge_duration,
                "co2measure_duration": clean_co2measure_duration,
                "co2measure_acqrate": co2measure_acqrate,
                "use_co2_check": False,
                "drainrecirc": drainrecirc,
                #  "HSpurge_duration": LiquidCleanPurge_duration,
            })

        refill_volume = watervolume + drainclean_volume_ul*(cleanloops)
        epm.add_experiment("CCSI_sub_refill_clean", {
            "Waterclean_volume_ul": refill_volume ,
            "Syringe_rate_ulsec": 1000,
        })
    
        for _ in range(headspace_purge_cycles):
            epm.add_experiment("CCSI_sub_drain", {
                "HSpurge_duration": HSpurge_duration,
                "DeltaDilute1_duration": DeltaDilute1_duration,
                })

    return epm.experiment_plan_list
def CCSI_priming(  #assumes initialization performed previously
    sequence_version: int = 1,
    Solution_volume_ul: List[float] = [2000],
    Solution_reservoir_sample_no: int = 2,
    Solution_name: str = "",
    total_sample_volume_ul: float = 5000,
    Waterclean_reservoir_sample_no: int = 1,
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
    clean_co2_ppm_thresh: float = 51500,
    max_repeats: int = 5,
    purge_if: Union[str, float] = 0.03,
    HSpurge_duration: float = 15,
    DeltaDilute1_duration: float = 15,
    #initcleans: int = 3,
    drainrecirc: bool = True,
    need_fill: bool = False,
    
):

    epm = ExperimentPlanMaker()
    for solnvolume in Solution_volume_ul:  

        epm.add_experiment("CCSI_sub_unload_cell",{})

        if solnvolume != 0:
            epm.add_experiment("CCSI_sub_load_liquid", {
                "reservoir_liquid_sample_no": Solution_reservoir_sample_no,
                "volume_ul_cell_liquid": solnvolume,
                "combine_True_False": False,
                "water_True_False": False,
            })
        watervolume = total_sample_volume_ul - solnvolume
        if watervolume != 0:
            epm.add_experiment("CCSI_sub_load_liquid", {
                "reservoir_liquid_sample_no": Waterclean_reservoir_sample_no,
                "volume_ul_cell_liquid": watervolume,
                "combine_True_False": True,
                "water_True_False": True,
            })

        epm.add_experiment("CCSI_sub_liquidfill_syringes", {
            "Solution_volume_ul": solnvolume,
            "Waterclean_volume_ul": watervolume,
            "Syringe_rate_ulsec": syringe_rate_ulsec,
            "LiquidFillWait_s": LiquidFillWait_s,
            "co2measure_duration": co2measure_duration,
            "co2measure_acqrate": co2measure_acqrate,
        })
        epm.add_experiment("CCSI_sub_drain", {"HSpurge_duration": LiquidCleanPurge_duration,"DeltaDilute1_duration": DeltaDilute1_duration,"recirculation":drainrecirc,})

        epm.add_experiment("CCSI_sub_clean_inject", {
            "Waterclean_volume_ul": drainclean_volume_ul,
            "Syringe_rate_ulsec": syringe_rate_ulsec,
            "LiquidCleanWait_s": LiquidFillWait_s,
            "LiquidCleanPurge_duration": LiquidCleanPurge_duration,
            "co2measure_duration": clean_co2measure_duration,
            "co2measure_acqrate": co2measure_acqrate,
            "use_co2_check": True,
            "co2_ppm_thresh": clean_co2_ppm_thresh,
            "purge_if": purge_if,
            "max_repeats": max_repeats,
            "drainrecirc": drainrecirc,
            #  "HSpurge_duration": LiquidCleanPurge_duration,
        })

        epm.add_experiment("CCSI_sub_full_fill_syringe", {
            "syringe": "waterclean",
            "target_volume_ul": 55000 ,
            "Syringe_rate_ulsec": 1000,
        })
    
        for _ in range(headspace_purge_cycles):
            epm.add_experiment("CCSI_sub_drain", {
                "HSpurge_duration": HSpurge_duration,
                "DeltaDilute1_duration": DeltaDilute1_duration,
                })

    return epm.experiment_plan_list

def CCSI_leaktest(
    sequence_version: int = 1,
    headspace_purge_cycles: int = 5,
    HSpurge1_duration: float = 60,
    Manpurge1_duration: float = 10,
    Alphapurge1_duration: float = 10,
    Probepurge1_duration: float = 10,
    Sensorpurge1_duration: float = 15,
    DeltaDilute1_duration: float = 10,
    HSpurge_duration: float = 20, 
 #   HSmeasure1_duration: float = 20,
    CO2measure_duration: float = 600,
    CO2measure_acqrate: float = 1,
    recirculate: bool = True,
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
        })
    epm.add_experiment("CCSI_sub_initialization_end_state", {})

    epm.add_experiment("CCSI_leaktest_co2", {
        "recirculate": recirculate,
        "co2measure_duration": CO2measure_duration, 
        "co2measure_acqrate": CO2measure_acqrate, 
        })
    epm.add_experiment("CCSI_sub_peripumpoff",{})

    return epm.experiment_plan_list
