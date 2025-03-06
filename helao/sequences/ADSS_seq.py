"""
Sequence library for ADSS
"""

__all__ = [
    "ADSS_CA_cell_1potential",
    "ADSS_PA_CVs_CAs_cell",
    "ADSS_PA_CVs_CAs_CVs_autogasswitching",
    "ADSS_PA_CVs_CAs_CVs_cell_simple",
    "ADSS_PA_CVs_testing",
    "ADSS_PA_CV_TRI",
    "ADSS_PA_CV_TRI_new"
]

from typing import List
from helao.helpers.premodels import ExperimentPlanMaker
import pandas as pd
import numpy as np


SEQUENCES = __all__


def ADSS_CA_cell_1potential(
    sequence_version: int = 8, #v3 move led off to exp v4 electrolyte insertion v7 keep electrolyte
    #solid_custom_position: str = "cell1_we",
    plate_id: int = 5917,
    plate_sample_no: int = 14050,  #  instead of map select
    same_sample: bool = False,
    stay_sample: bool = False,
    #liquid_custom_position: str = "elec_res1",
    liquid_sample_no: int = 220,
    liquid_sample_volume_ul: float = 4000,
    CA_potential_vs: float = -0.2,
    potential_versus: str = "oer",
    ph: float = 9.53,
    ref_type: str = "leakless",
    ref_offset__V: float = 0.0,
    CA_duration_sec: float = 1320,
    aliquot_tf: bool = True,
    aliquot_times_sec: List[float] = [60, 600, 1140],
    aliquot_volume_ul: int = 200,
    insert_electrolyte_bool: bool = False,
    insert_electrolyte_ul: int = 0,
    insert_electrolyte_time_sec: float = 1800,
    keep_electrolyte: bool = False,
    use_electrolyte: bool = False,
    OCV_duration: float = 60,
    OCValiquot_times_sec: List[float] = [20],
    samplerate_sec: float = 1,
    led_illumination: bool = False,
    led_dutycycle: float = 1,
    led_wavelength: str = "385",
    Syringe_rate_ulsec: float = 300,
    Cell_draintime_s: float = 60,
    ReturnLineWait_s: float = 30,
    ReturnLineReverseWait_s: float = 3,
    ResidualWait_s: float = 15,
    flush_volume_ul: float = 2000,
    clean: bool = False,
    clean_volume_ul: float = 5000,
    refill: bool = False,
    refill_volume_ul: float = 6000,
    water_refill_volume_ul: float = 6000,
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "LS4_newsyringe040923"
):

    """tbd

    last functionality test: tbd"""

    epm = ExperimentPlanMaker()


    #for solid_sample_no in plate_sample_no_list:  # have to indent add expts if used

    if not same_sample:
        
        epm.add_experiment(
            "ADSS_sub_move_to_sample",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample_no,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            },
        )
    epm.add_experiment(
        "ADSS_sub_load",
        {
            "solid_custom_position": "cell1_we",
            "solid_plate_id": plate_id,
            "solid_sample_no": plate_sample_no,
            "previous_liquid": use_electrolyte,
            "liquid_custom_position": "cell1_we",
            "liquid_sample_no": liquid_sample_no,            
            "liquid_sample_volume_ul": liquid_sample_volume_ul,
        }
    )
    # if led_illumination:
    #     epm.add_experiment(
    #         "ADSS_sub_cell_illumination",
    #         {
    #             "led_wavelength": led_wavelength,
    #             "illumination_on": led_illumination,
    #         }
            
    #     )
    if not use_electrolyte:

        epm.add_experiment(
            "ADSS_sub_cellfill_prefilled",
            {
                "Solution_volume_ul": liquid_sample_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
            }
        )
# redundant?
    # epm.add_experiment(    
    #     "ADSS_sub_load_liquid",
    #     {
    #         "liquid_custom_position": liquid_custom_position,
    #         "liquid_sample_no": liquid_sample_no,
    #     }
    # )
    # epm.add_experiment(
    #     "ADSS_sub_load_solid",
    #     {
    #         "solid_custom_position": solid_custom_position,
    #         "solid_plate_id": plate_id,
    #         "solid_sample_no": plate_sample_no,
    #     }
    # )
    epm.add_experiment("ADSS_sub_recirculate",{})

    if led_illumination:

        epm.add_experiment(
            "ADSS_sub_OCV_photo",
            {
                "Tval__s": OCV_duration,
                "SampleRate": samplerate_sec,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "led_wavelength": led_wavelength,
                "toggle_illum_duty": led_dutycycle,
                "aliquot_volume_ul": aliquot_volume_ul,
                "aliquot_times_sec": OCValiquot_times_sec,
                "aliquot_insitu": aliquot_tf,
                "PAL_Injector": PAL_Injector,
                "PAL_Injector_id": PAL_Injector_id,
                "rinse_1": 1,
            },
        )
        epm.add_experiment(
            "ADSS_sub_CA_photo",
            {
                "CA_potential": CA_potential_vs,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "potential_versus": potential_versus,
                "samplerate_sec": samplerate_sec,
                "CA_duration_sec": CA_duration_sec,
                "led_wavelength": led_wavelength,
                "toggle_illum_duty": led_dutycycle,
                "insert_electrolyte_bool":insert_electrolyte_bool,
                "insert_electrolyte_volume_ul":insert_electrolyte_ul,
                "insert_electrolyte_time_sec":insert_electrolyte_time_sec,             
                "electrolyte_sample_no": liquid_sample_no,
                "aliquot_volume_ul": aliquot_volume_ul,
                "aliquot_times_sec": aliquot_times_sec,
                "aliquot_insitu": aliquot_tf,
                "PAL_Injector": PAL_Injector,
                "PAL_Injector_id": PAL_Injector_id,
            },
        )
        epm.add_experiment(
            "ADSS_sub_OCV_photo",
            {
                "Tval__s": OCV_duration,
                "SampleRate": samplerate_sec,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "led_wavelength": led_wavelength,
                "toggle_illum_duty": led_dutycycle,
                "aliquot_volume_ul": aliquot_volume_ul,
                "aliquot_times_sec": OCValiquot_times_sec,
                "aliquot_insitu": aliquot_tf,
                "PAL_Injector": PAL_Injector,
                "PAL_Injector_id": PAL_Injector_id,
                "rinse_1": 1,
                #"rinse_4": 1,

            },
        )
        epm.add_experiment(
            "ADSS_sub_cell_illumination",
            {
                "led_wavelength": led_wavelength,
                "illumination_on": False,
            }
        )
    else:

        epm.add_experiment(
            "ADSS_sub_OCV",
            {
                "Tval__s": OCV_duration,
                "SampleRate": samplerate_sec,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_volume_ul": aliquot_volume_ul,
                "aliquot_times_sec": OCValiquot_times_sec,
                "aliquot_insitu": aliquot_tf,
                "PAL_Injector": PAL_Injector,
                "PAL_Injector_id": PAL_Injector_id,
                "rinse_1": 1,
            },
        )
        epm.add_experiment(
            "ADSS_sub_CA",
            {
                "CA_potential": CA_potential_vs,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "potential_versus": potential_versus,
                "samplerate_sec": samplerate_sec,
                "CA_duration_sec": CA_duration_sec,
                "insert_electrolyte_bool":insert_electrolyte_bool,
                "insert_electrolyte_volume_ul":insert_electrolyte_ul,
                "insert_electrolyte_time_sec":insert_electrolyte_time_sec,             
                "electrolyte_sample_no": liquid_sample_no,
                "aliquot_volume_ul": aliquot_volume_ul,
                "aliquot_times_sec": aliquot_times_sec,
                "aliquot_insitu": aliquot_tf,
                "PAL_Injector": PAL_Injector,
                "PAL_Injector_id": PAL_Injector_id,
            },
        )
        epm.add_experiment(
            "ADSS_sub_OCV",
            {
                "Tval__s": OCV_duration,
                "SampleRate": samplerate_sec,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_volume_ul": aliquot_volume_ul,
                "aliquot_times_sec": OCValiquot_times_sec,
                "aliquot_insitu": True,
                "PAL_Injector": PAL_Injector,
                "PAL_Injector_id": PAL_Injector_id,
                "rinse_1": 1,
                #"rinse_4": 1,

            },
        )

    if keep_electrolyte:
        epm.add_experiment(
            "ADSS_sub_keep_electrolyte",
            {
                "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
            }
        )

    else:
        epm.add_experiment(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": Cell_draintime_s,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
            #    "ResidualWait_s": ResidualWait_s,
            }
        )
    if stay_sample:
        epm.add_experiment(
            "ADSS_sub_cellfill_flush",
            {
                "Solution_volume_ul": flush_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
                "ReturnLineWait_s": ReturnLineWait_s,
            }
        )
        epm.add_experiment(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": Cell_draintime_s,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
        #        "ResidualWait_s": ResidualWait_s,
            }
        )
    if keep_electrolyte:
        epm.add_experiment("ADSS_sub_unload_solid",{})

    else:

        epm.add_experiment("ADSS_sub_unloadall_customs",{})



    if clean:

        epm.add_experiment(
            "ADSS_sub_move_to_clean_cell",
            {}
        )

        epm.add_experiment(
            "ADSS_sub_clean_cell",
            {
                "Clean_volume_ul": clean_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
                "ReturnLineWait_s": ReturnLineWait_s,
                "DrainWait_s": Cell_draintime_s,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
            #    "ResidualWait_s": ResidualWait_s,
        }
        )
    if refill:
        epm.add_experiment("ADSS_sub_refill_syringes", {
            "Waterclean_volume_ul": water_refill_volume_ul ,
            "Solution_volume_ul": refill_volume_ul,
            "Syringe_rate_ulsec": 300,
        })

#    epm.add_experiment("ADSS_sub_tray_unload",{})


        # epm.add_experiment("ADSS_sub_shutdown", {})

    return epm.experiment_plan_list  # returns complete experiment list

def ADSS_PA_CVs_CAs_cell(
    sequence_version: int = 5, 
    #solid_custom_position: str = "cell1_we",
    plate_id: int = 5917,
    plate_sample_no: int = 14050,  #  instead of map select
    same_sample: bool = False,
    stay_sample: bool = False,
    #liquid_custom_position: str = "elec_res1",
    liquid_sample_no: int = 220,
    liquid_sample_volume_ul: float = 4000,
    recirculate_wait_time_m: float = 0.5,
    CV_cycles: List[int] = [5,3,3],
    Vinit_vsRHE: List[float] = [1.23, 1.23, 1.23],  # Initial value in volts or amps.
    Vapex1_vsRHE: List[float] = [1.23, 1.23, 1.23],  # Apex 1 value in volts or amps.
    Vapex2_vsRHE: List[float] = [0.6, 0.4, 0],  # Apex 2 value in volts or amps.
    Vfinal_vsRHE: List[float] = [0.6, 0.4, 0],  # Final value in volts or amps.
    scanrate_voltsec: List[float] = [0.02,0.02,0.02],  # scan rate in volts/second or amps/second.
    CV_samplerate_sec: float = 0.05,
    #number_of_preCAs: int = 3,
    number_of_postCAs: int = 2,
    CA_potentials_vs: List[float] = [0.6,0.4],
    potential_versus: str = "rhe",
    CA_duration_sec: List[float] = [60,60],
    CA_samplerate_sec: float = 0.1,
    gamry_i_range: str = "auto",
    ph: float = 9.53,
    ref_type: str = "leakless",
    ref_offset__V: float = 0.0,
    aliquot_postCV: List[int] = [1,0,0],
    aliquot_postCA: List[int] = [1,0],
    aliquot_volume_ul: int = 200,
    Syringe_rate_ulsec: float = 300,
    Drain: bool = False,
    Cell_draintime_s: float = 60,
    ReturnLineWait_s: float = 30,
    ReturnLineReverseWait_s: float = 3,
    ResidualWait_s: float = 15,
    flush_volume_ul: float = 2000,
    clean: bool = False,
    clean_volume_ul: float = 5000,
    refill: bool = False,
    refill_volume_ul: float = 6000,
    water_refill_volume_ul: float = 6000,
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "LS4_newsyringe040923"
):

    """tbd

    last functionality test: tbd"""

    epm = ExperimentPlanMaker()


    #for solid_sample_no in plate_sample_no_list:  # have to indent add expts if used

    if not same_sample:
        
        epm.add_experiment(
            "ADSS_sub_move_to_sample",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample_no,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            },
        )
    epm.add_experiment(
        "ADSS_sub_load",
        {
            "solid_custom_position": "cell1_we",
            "solid_plate_id": plate_id,
            "solid_sample_no": plate_sample_no,
           # "previous_liquid": use_electrolyte,
            "liquid_custom_position": "cell1_we",
            "liquid_sample_no": liquid_sample_no,            
            "liquid_sample_volume_ul": liquid_sample_volume_ul,
        }
    )
    # if led_illumination:
    #     epm.add_experiment(
    #         "ADSS_sub_cell_illumination",
    #         {
    #             "led_wavelength": led_wavelength,
    #             "illumination_on": led_illumination,
    #         }
            
    #     )
    #if not use_electrolyte:

    epm.add_experiment(
        "ADSS_sub_cellfill_prefilled",
        {
            "Solution_volume_ul": liquid_sample_volume_ul,
            "Syringe_rate_ulsec": Syringe_rate_ulsec,
        }
    )
# redundant?
    # epm.add_experiment(    
    #     "ADSS_sub_load_liquid",
    #     {
    #         "liquid_custom_position": liquid_custom_position,
    #         "liquid_sample_no": liquid_sample_no,
    #     }
    # )
    # epm.add_experiment(
    #     "ADSS_sub_load_solid",
    #     {
    #         "solid_custom_position": solid_custom_position,
    #         "solid_plate_id": plate_id,
    #         "solid_sample_no": plate_sample_no,
    #     }
    # )
    epm.add_experiment(
        "ADSS_sub_recirculate",
        {
            "wait_time_s": recirculate_wait_time_m * 60,
        })
    washmod = 0

    for i, CV_cycle in enumerate(CV_cycles):

        epm.add_experiment(
            "ADSS_sub_CV",
            {
                "Vinit_vsRHE": Vinit_vsRHE[i],
                "Vapex1_vsRHE": Vapex1_vsRHE[i],
                "Vapex2_vsRHE": Vapex2_vsRHE[i],
                "Vfinal_vsRHE": Vfinal_vsRHE[i],
                "scanrate_voltsec": scanrate_voltsec[i],
                "SampleRate": CV_samplerate_sec,
                "cycles": CV_cycle,
                "gamry_i_range": gamry_i_range,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_insitu": False,
            },
        )
        if aliquot_postCV[i] == 1:
            washmod += 1
            washone = washmod %4 %3 %2
            washtwo = (washmod + 1) %4 %3 %2
            washthree = (washmod + 2) %4 %3 %2
            washfour = (washmod + 3) %4 %3 %2

            epm.add_experiment(
                "ADSS_sub_sample_aliquot",
                {
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "EquilibrationTime_s": 0,
                    "PAL_Injector": PAL_Injector,
                    "PAL_Injector_id": PAL_Injector_id,
                    "rinse_1": washone,
                    "rinse_2": washtwo,
                    "rinse_3": washthree,
                    "rinse_4": washfour,
                }
            )

    for i, CA_potential_vs in enumerate(CA_potentials_vs):

        epm.add_experiment(
            "ADSS_sub_CA",
            {
                "CA_potential": CA_potential_vs,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "potential_versus": potential_versus,
                "samplerate_sec": CA_samplerate_sec,
                "CA_duration_sec": CA_duration_sec[i],
                "gamry_i_range": gamry_i_range,
                "aliquot_insitu": False,
            },
        )
        if aliquot_postCA[i] == 1:
            washmod += 1
            washone = washmod %4 %3 %2
            washtwo = (washmod + 1) %4 %3 %2
            washthree = (washmod + 2) %4 %3 %2
            washfour = (washmod + 3) %4 %3 %2

            epm.add_experiment(
                "ADSS_sub_sample_aliquot",
                {
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "EquilibrationTime_s": 0,
                    "PAL_Injector": PAL_Injector,
                    "PAL_Injector_id": PAL_Injector_id,
                    "rinse_1": washone,
                    "rinse_2": washtwo,
                    "rinse_3": washthree,
                    "rinse_4": washfour,
                }
            )

    if Drain:
        epm.add_experiment(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": Cell_draintime_s,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
            #    "ResidualWait_s": ResidualWait_s,
            }
        )

    if stay_sample:
        epm.add_experiment(
            "ADSS_sub_cellfill_flush",
            {
                "Solution_volume_ul": flush_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
                "ReturnLineWait_s": ReturnLineWait_s,
            }
        )
        epm.add_experiment(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": Cell_draintime_s,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
        #        "ResidualWait_s": ResidualWait_s,
            }
        )
    # if keep_electrolyte:
    #     epm.add_experiment("ADSS_sub_unload_solid",{})

    # else:

    #     epm.add_experiment("ADSS_sub_unloadall_customs",{})

    if clean:

        epm.add_experiment(
            "ADSS_sub_move_to_clean_cell",
            {}
        )

        epm.add_experiment(
            "ADSS_sub_clean_cell",
            {
                "Clean_volume_ul": clean_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
                "ReturnLineWait_s": ReturnLineWait_s,
                "DrainWait_s": Cell_draintime_s,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
            #    "ResidualWait_s": ResidualWait_s,
        }
        )
    if refill:
        epm.add_experiment("ADSS_sub_refill_syringes", {
            "Waterclean_volume_ul": water_refill_volume_ul ,
            "Solution_volume_ul": refill_volume_ul,
            "Syringe_rate_ulsec": 300,
        })

#    epm.add_experiment("ADSS_sub_tray_unload",{})


        # epm.add_experiment("ADSS_sub_shutdown", {})

    return epm.experiment_plan_list  # returns complete experiment list

def ADSS_PA_CVs_CAs_CVs_cell_simple(
    sequence_version: int = 8, #make sample list 
    #solid_custom_position: str = "cell1_we",
    plate_id: int = 5917,
    plate_sample_no: List[int] = [16304],  #  instead of map select
    same_sample: bool = False,
    keep_electrolyte: bool = False,
    use_electrolyte: bool = False,
    Move_to_clean_and_clean: bool = True,
    #liquid_custom_position: str = "elec_res1",
    liquid_sample_no: int = 220,
    liquid_sample_volume_ul: float = 4000,
    recirculate_wait_time_m: float = 0.5,
    recirculate_reverse_wait_time_s: float = 1,
    CV_cycles: List[int] = [5,3,3],
    Vinit_vsRHE: List[float] = [1.23, 1.23, 1.23],  # Initial value in volts or amps.
    Vapex1_vsRHE: List[float] = [1.23, 1.23, 1.23],  # Apex 1 value in volts or amps.
    Vapex2_vsRHE: List[float] = [0.6, 0.4, 0],  # Apex 2 value in volts or amps.
    Vfinal_vsRHE: List[float] = [0.6, 0.4, 0],  # Final value in volts or amps.
    scanrate_voltsec: List[float] = [0.02,0.02,0.02],  # scan rate in volts/second or amps/second.
    CV_samplerate_sec: float = 0.05,
    #number_of_preCAs: int = 3,
    number_of_postCAs: int = 2,
    CA_potentials_vs: List[float] = [0.6,0.4],
    potential_versus: str = "rhe",
    CA_duration_sec: List[float] = [60,60],
    CA_samplerate_sec: float = 0.1,
    CV2_cycles: List[int] = [5,3,3],
    CV2_Vinit_vsRHE: List[float] = [1.23, 1.23, 1.23],  # Initial value in volts or amps.
    CV2_Vapex1_vsRHE: List[float] = [1.23, 1.23, 1.23],  # Apex 1 value in volts or amps.
    CV2_Vapex2_vsRHE: List[float] = [0.6, 0.4, 0],  # Apex 2 value in volts or amps.
    CV2_Vfinal_vsRHE: List[float] = [0.6, 0.4, 0],  # Final value in volts or amps.
    CV2_scanrate_voltsec: List[float] = [0.02,0.02,0.02],  # scan rate in volts/second or amps/second.
    CV2_samplerate_sec: float = 0.05,
    gamry_i_range: str = "auto",
    ph: float = 1.24,
    ref_type: str = "leakless",
    ref_offset__V: float = 0.0,
    aliquot_init: bool = True,
    aliquot_postCV: List[int] = [1,0,0],
    aliquot_postCA: List[int] = [1,0],
    aliquot_volume_ul: int = 200,
    Syringe_rate_ulsec: float = 300,
    # Drain: bool = False,
    Cell_draintime_s: float = 60,
    # ReturnLineWait_s: float = 30,
    ReturnLineReverseWait_s: float = 10,
    # ResidualWait_s: float = 15,
    # flush_volume_ul: float = 2000,
    # clean: bool = False,
    # clean_volume_ul: float = 5000,
    # refill: bool = False,
    # refill_volume_ul: float = 6000,
    # water_refill_volume_ul: float = 6000,
    Clean_volume_ul: float = 12000,
    Clean_recirculate_s: float = 30,
    Clean_drain_s: float = 60,
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "LS4_peek"
):

    """tbd

    last functionality test: tbd"""

    epm = ExperimentPlanMaker()


    #for solid_sample_no in plate_sample_no_list:  # have to indent add expts if used
    for sample in plate_sample_no:

        if not same_sample:
            
            epm.add_experiment(
                "ADSS_sub_move_to_sample",
                {
                    "solid_custom_position": "cell1_we",
                    "solid_plate_id": plate_id,
                    "solid_sample_no": sample,
                    "liquid_custom_position": "cell1_we",
                    "liquid_sample_no": liquid_sample_no,
                    "liquid_sample_volume_ul": liquid_sample_volume_ul,
                },
            )
        epm.add_experiment(
            "ADSS_sub_load",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": sample,
                "previous_liquid": use_electrolyte,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,            
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            }
        )
        # if led_illumination:
        #     epm.add_experiment(
        #         "ADSS_sub_cell_illumination",
        #         {
        #             "led_wavelength": led_wavelength,
        #             "illumination_on": led_illumination,
        #         }
                
        #     )
        if not use_electrolyte:

            epm.add_experiment(
                "ADSS_sub_cellfill_prefilled",
                {
                    "Solution_volume_ul": liquid_sample_volume_ul,
                    "Syringe_rate_ulsec": Syringe_rate_ulsec,
                }
            )

        # pump recirculate forward
        epm.add_experiment(
            "ADSS_sub_recirculate",
            {
                "wait_time_s": recirculate_wait_time_m * 60,
            })
        
        # pump recirculate reverse (for bubbles)
        epm.add_experiment(
            "ADSS_sub_recirculate",
            {
                "direction_forward_or_reverse": "reverse",
                "wait_time_s": recirculate_reverse_wait_time_s,
            })
        
        # pump recirculate forward
        epm.add_experiment(
            "ADSS_sub_recirculate",
            {
                "wait_time_s": 10,
            })

        washmod = 0

        if aliquot_init: #stops gas purge, takes aliquote, starts gas purge again
            
            washmod += 1
            washone = washmod %4 %3 %2
            washtwo = (washmod + 1) %4 %3 %2
            washthree = (washmod + 2) %4 %3 %2
            washfour = (washmod + 3) %4 %3 %2

            epm.add_experiment(
                "ADSS_sub_sample_aliquot",
                {
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "EquilibrationTime_s": 0,
                    "PAL_Injector": PAL_Injector,
                    "PAL_Injector_id": PAL_Injector_id,
                    "rinse_1": washone,
                    "rinse_2": washtwo,
                    "rinse_3": washthree,
                    "rinse_4": washfour,
                })



        for i, CV_cycle in enumerate(CV_cycles):

            epm.add_experiment(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": Vinit_vsRHE[i],
                    "Vapex1_vsRHE": Vapex1_vsRHE[i],
                    "Vapex2_vsRHE": Vapex2_vsRHE[i],
                    "Vfinal_vsRHE": Vfinal_vsRHE[i],
                    "scanrate_voltsec": scanrate_voltsec[i],
                    "SampleRate": CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                },
            )
            if aliquot_postCV[i] == 1:
                
                washmod += 1
                washone = washmod %4 %3 %2
                washtwo = (washmod + 1) %4 %3 %2
                washthree = (washmod + 2) %4 %3 %2
                washfour = (washmod + 3) %4 %3 %2

                epm.add_experiment(
                    "ADSS_sub_sample_aliquot",
                    {
                        "aliquot_volume_ul": aliquot_volume_ul,
                        "EquilibrationTime_s": 0,
                        "PAL_Injector": PAL_Injector,
                        "PAL_Injector_id": PAL_Injector_id,
                        "rinse_1": washone,
                        "rinse_2": washtwo,
                        "rinse_3": washthree,
                        "rinse_4": washfour,
                    }
                )


        for i, CA_potential_vs in enumerate(CA_potentials_vs):

            epm.add_experiment(
                "ADSS_sub_CA",
                {
                    "CA_potential": CA_potential_vs,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "potential_versus": potential_versus,
                    "samplerate_sec": CA_samplerate_sec,
                    "CA_duration_sec": CA_duration_sec[i],
                    "gamry_i_range": gamry_i_range,
                    "aliquot_insitu": False,
                },
            )
            if aliquot_postCA[i] == 1:
                            
                washmod += 1
                washone = washmod %4 %3 %2
                washtwo = (washmod + 1) %4 %3 %2
                washthree = (washmod + 2) %4 %3 %2
                washfour = (washmod + 3) %4 %3 %2

                epm.add_experiment(
                    "ADSS_sub_sample_aliquot",
                    {
                        "aliquot_volume_ul": aliquot_volume_ul,
                        "EquilibrationTime_s": 0,
                        "PAL_Injector": PAL_Injector,
                        "PAL_Injector_id": PAL_Injector_id,
                        "rinse_1": washone,
                        "rinse_2": washtwo,
                        "rinse_3": washthree,
                        "rinse_4": washfour,
                    }
                )


        #epm.add_experiment(
        #       "ADSS_sub_interrupt",
        #      {
        #         "reason":"Pause for injection of phosphoric"
            #    },
            #)

        for i, CV_cycle in enumerate(CV2_cycles):

            epm.add_experiment(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": CV2_Vinit_vsRHE[i],
                    "Vapex1_vsRHE": CV2_Vapex1_vsRHE[i],
                    "Vapex2_vsRHE": CV2_Vapex2_vsRHE[i],
                    "Vfinal_vsRHE": CV2_Vfinal_vsRHE[i],
                    "scanrate_voltsec": CV2_scanrate_voltsec[i],
                    "SampleRate": CV2_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                },
            )
            if aliquot_postCV[i] == 1:
                
                washmod += 1
                washone = washmod %4 %3 %2
                washtwo = (washmod + 1) %4 %3 %2
                washthree = (washmod + 2) %4 %3 %2
                washfour = (washmod + 3) %4 %3 %2

                epm.add_experiment(
                    "ADSS_sub_sample_aliquot",
                    {
                        "aliquot_volume_ul": aliquot_volume_ul,
                        "EquilibrationTime_s": 0,
                        "PAL_Injector": PAL_Injector,
                        "PAL_Injector_id": PAL_Injector_id,
                        "rinse_1": washone,
                        "rinse_2": washtwo,
                        "rinse_3": washthree,
                        "rinse_4": washfour,
                    }
                )

        if keep_electrolyte:
            epm.add_experiment("ADSS_sub_unload_solid",{})

        else:

            epm.add_experiment("ADSS_sub_unloadall_customs",{})
            epm.add_experiment(
                "ADSS_sub_drain_cell",
                {
                    "DrainWait_s": Cell_draintime_s,
                    "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
                #    "ResidualWait_s": ResidualWait_s,
                }
            )

        if Move_to_clean_and_clean:
            epm.add_experiment("ADSS_sub_move_to_clean_cell", {})
            epm.add_experiment("ADSS_sub_clean_cell",
                            {
                                "Clean_volume_ul": Clean_volume_ul,
                                "ReturnLineWait_s": Clean_recirculate_s,
                                "DrainWait_s": Clean_drain_s,
                            })

    return epm.experiment_plan_list  # returns complete experiment list



def ADSS_CA_cell_multipotential(
    sequence_version: int = 2,
    #solid_custom_position: str = "cell1_we",
    plate_id: int = 5917,
    plate_sample_no: int = 14050,  #  instead of map select
    same_sample: bool = False,
    stay_sample: bool = False,
    #liquid_custom_position: str = "elec_res1",
    liquid_sample_no: int = 220,
    liquid_sample_volume_ul: float = 4000,
    CA_potentials_vs: List[float] = [-0.5, 0.0, 0.5, 1.0],
    potential_versus: str = "oer",
    ph: float = 9.53,
    ref_type: str = "leakless",
    ref_offset__V: float = 0.0,
    CA_duration_sec: float = 1320,
    aliquot_times_sec: List[float] = [60, 600, 1140],
    aliquot_volume_ul: int = 200,
    OCV_duration: float = 60,
    OCValiquot_times_sec: List[float] = [20],
    samplerate_sec: float = 1,
    led_illumination: bool = False,
    led_dutycycle: float = 1,
    led_wavelength: str = "385",
    Syringe_rate_ulsec: float = 300,
    Cell_draintime_s: float = 60,
    ReturnLineWait_s: float = 30,
    ReturnLineReverseWait_s: float = 3,
    ResidualWait_s: float = 15,
    flush_volume_ul: float = 2000,
    clean: bool = False,
    clean_volume_ul: float = 5000,
    refill: bool = False,
    refill_volume_ul: float = 6000,
    water_refill_volume_ul: float = 6000,
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "LS4_newsyringe040923"
):

    """tbd

    last functionality test: tbd"""

    epm = ExperimentPlanMaker()


    #for solid_sample_no in plate_sample_no_list:  # have to indent add expts if used

    if same_sample:
        epm.add_experiment(
            "ADSS_sub_load",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample_no,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,            
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            }
        )
    else:    
        epm.add_experiment(
            "ADSS_sub_sample_start",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample_no,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            },
        )
    if led_illumination:
        epm.add_experiment(
            "ADSS_sub_cell_illumination",
            {
                "led_wavelength": led_wavelength,
                "illumination_on": led_illumination,
            }
            
        )
    epm.add_experiment(
        "ADSS_sub_cellfill_prefilled",
        {
            "Solution_volume_ul": liquid_sample_volume_ul,
            "Syringe_rate_ulsec": Syringe_rate_ulsec,
        }
    )
# redundant?
    # epm.add_experiment(    
    #     "ADSS_sub_load_liquid",
    #     {
    #         "liquid_custom_position": liquid_custom_position,
    #         "liquid_sample_no": liquid_sample_no,
    #     }
    # )
    # epm.add_experiment(
    #     "ADSS_sub_load_solid",
    #     {
    #         "solid_custom_position": solid_custom_position,
    #         "solid_plate_id": plate_id,
    #         "solid_sample_no": plate_sample_no,
    #     }
    # )
    epm.add_experiment("ADSS_sub_recirculate",{})

    if led_illumination:

        epm.add_experiment(
            "ADSS_sub_OCV_photo",
            {
                "Tval__s": OCV_duration,
                "SampleRate": samplerate_sec,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "led_wavelength": led_wavelength,
                "toggle_illum_duty": led_dutycycle,
                "aliquot_volume_ul": aliquot_volume_ul,
                "aliquot_times_sec": OCValiquot_times_sec,
                "aliquot_insitu": True,
                "PAL_Injector": PAL_Injector,
                "PAL_Injector_id": PAL_Injector_id,
                "rinse_1": 1,
            },
        )
        epm.add_experiment(
            "ADSS_sub_CA_photo",
            {
                "CA_potential": CA_potential_vs,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "potential_versus": potential_versus,
                "samplerate_sec": samplerate_sec,
                "CA_duration_sec": CA_duration_sec,
                "led_wavelength": led_wavelength,
                "toggle_illum_duty": led_dutycycle,
                "aliquot_volume_ul": aliquot_volume_ul,
                "aliquot_times_sec": aliquot_times_sec,
                "aliquot_insitu": True,
                "PAL_Injector": PAL_Injector,
                "PAL_Injector_id": PAL_Injector_id,
            },
        )
        epm.add_experiment(
            "ADSS_sub_OCV_photo",
            {
                "Tval__s": OCV_duration,
                "SampleRate": samplerate_sec,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "led_wavelength": led_wavelength,
                "toggle_illum_duty": led_dutycycle,
                "aliquot_volume_ul": aliquot_volume_ul,
                "aliquot_times_sec": OCValiquot_times_sec,
                "aliquot_insitu": True,
                "PAL_Injector": PAL_Injector,
                "PAL_Injector_id": PAL_Injector_id,
                "rinse_1": 0,
                "rinse_4": 1,

            },
        )
        epm.add_experiment(
            "ADSS_sub_cell_illumination",
            {
                "led_wavelength": led_wavelength,
                "illumination_on": False,
            }
        )
    else:

        epm.add_experiment(
            "ADSS_sub_OCV",
            {
                "Tval__s": OCV_duration,
                "SampleRate": samplerate_sec,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_volume_ul": aliquot_volume_ul,
                "aliquot_times_sec": OCValiquot_times_sec,
                "aliquot_insitu": True,
                "PAL_Injector": PAL_Injector,
                "PAL_Injector_id": PAL_Injector_id,
                "rinse_1": 1,
            },
        )
        epm.add_experiment(
            "ADSS_sub_CA",
            {
                "CA_potential": CA_potential_vs,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "potential_versus": potential_versus,
                "samplerate_sec": samplerate_sec,
                "CA_duration_sec": CA_duration_sec,
                "aliquot_volume_ul": aliquot_volume_ul,
                "aliquot_times_sec": aliquot_times_sec,
                "aliquot_insitu": True,
                "PAL_Injector": PAL_Injector,
                "PAL_Injector_id": PAL_Injector_id,
            },
        )
        epm.add_experiment(
            "ADSS_sub_OCV",
            {
                "Tval__s": OCV_duration,
                "SampleRate": samplerate_sec,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_volume_ul": aliquot_volume_ul,
                "aliquot_times_sec": OCValiquot_times_sec,
                "aliquot_insitu": True,
                "PAL_Injector": PAL_Injector,
                "PAL_Injector_id": PAL_Injector_id,
                "rinse_1": 0,
                "rinse_4": 1,

            },
        )


    epm.add_experiment(
        "ADSS_sub_drain_cell",
        {
            "DrainWait_s": Cell_draintime_s,
            "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
        #    "ResidualWait_s": ResidualWait_s,
        }
    )
    if stay_sample:
        epm.add_experiment(
            "ADSS_sub_cellfill_flush",
            {
                "Solution_volume_ul": flush_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
                "ReturnLineWait_s": ReturnLineWait_s,
            }
        )
        epm.add_experiment(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": Cell_draintime_s,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
        #        "ResidualWait_s": ResidualWait_s,
            }
        )
    epm.add_experiment("ADSS_sub_unload_liquid",{})

    epm.add_experiment("ADSS_sub_unloadall_customs",{})

    if clean:

        epm.add_experiment(
            "ADSS_sub_move_to_clean_cell",
            {}
        )

        epm.add_experiment(
            "ADSS_sub_clean_cell",
            {
                "Clean_volume_ul": clean_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
                "ReturnLineWait_s": ReturnLineWait_s,
                "DrainWait_s": Cell_draintime_s,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
        #        "ResidualWait_s": ResidualWait_s,
        }
        )
    if refill:
        epm.add_experiment("ADSS_sub_refill_syringes", {
            "Waterclean_volume_ul": water_refill_volume_ul ,
            "Solution_volume_ul": refill_volume_ul,
            "Syringe_rate_ulsec": 300,
        })

#    epm.add_experiment("ADSS_sub_tray_unload",{})


        # epm.add_experiment("ADSS_sub_shutdown", {})

    return epm.experiment_plan_list  # returns complete experiment list



def ADSS_PA_CVs_testing(
    sequence_version: int = 1, 
    #solid_custom_position: str = "cell1_we",
    plate_id: int = 6307,
    plate_sample_no: int = 14050,  #  instead of map select
    second_sample_no: int = 14050,
    same_sample: bool = False,
    keep_electrolyte: bool = False,
    keep_electrolyte_post: bool = False,
    use_electrolyte: bool = False,
    #liquid_custom_position: str = "elec_res1",
    liquid_sample_no: int = 220,
    liquid_sample_volume_ul: float = 4000,
    recirculate_wait_time_m: float = 5,
    CV_cycles: List[int] = [10,3],
    Vinit_vsRHE: List[float] = [0.05,0.05,0.05],  # Initial value in volts or amps.
    Vapex1_vsRHE: List[float] = [0.05,0.05,0.05],  # Apex 1 value in volts or amps.
    Vapex2_vsRHE: List[float] = [1.2,1.2,1.2],  # Apex 2 value in volts or amps.
    Vfinal_vsRHE: List[float] = [0.05,0.05,0.05],  # Final value in volts or amps.
    scanrate_voltsec: List[float] = [0.1,0.02,0.02],  # scan rate in volts/second or amps/second.
    CV_samplerate_sec: float = 0.05,
    #number_of_preCAs: int = 3,
    # number_of_postCAs: int = 2,
    # CA_potentials_vs: List[float] = [0.6,0.4],
    potential_versus: str = "rhe",
    # CA_duration_sec: List[float] = [60,60],
    # CA_samplerate_sec: float = 0.1,
    CV2_cycles: List[int] = [3],
    CV2_Vinit_vsRHE: List[float] = [0.05],  # Initial value in volts or amps.
    CV2_Vapex1_vsRHE: List[float] = [0.05],  # Apex 1 value in volts or amps.
    CV2_Vapex2_vsRHE: List[float] = [1.2],  # Apex 2 value in volts or amps.
    CV2_Vfinal_vsRHE: List[float] = [0.05],  # Final value in volts or amps.
    CV2_scanrate_voltsec: List[float] = [0.02],  # scan rate in volts/second or amps/second.
    CV2_samplerate_sec: float = 0.05,
    gamry_i_range: str = "auto",
    ph: float = 9.53,
    ref_type: str = "leakless",
    ref_offset__V: float = 0.0,
    # aliquot_postCV: List[int] = [1,0,0],
    # aliquot_postCA: List[int] = [1,0],
    # aliquot_volume_ul: int = 200,
    Syringe_rate_ulsec: float = 300,
    # Drain: bool = False,
     Cell_draintime_s: float = 60,
     #ReturnLineWait_s: float = 30,
     ReturnLineReverseWait_s: float = 10,
     Clean_volume_ul: float = 6000,
     CleanDrainWait_s: float = 60,
    # ResidualWait_s: float = 15,
    # flush_volume_ul: float = 2000,
    # clean: bool = False,
    # clean_volume_ul: float = 5000,
    # refill: bool = False,
    # refill_volume_ul: float = 6000,
    # water_refill_volume_ul: float = 6000,
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "LS4_newsyringe040923"
):

    """tbd

    last functionality test: tbd"""

    epm = ExperimentPlanMaker()


    #for solid_sample_no in plate_sample_no_list:  # have to indent add expts if used

    if not same_sample:
        
        epm.add_experiment(
            "ADSS_sub_move_to_sample",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample_no,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            },
        )
    epm.add_experiment(
        "ADSS_sub_load",
        {
            "solid_custom_position": "cell1_we",
            "solid_plate_id": plate_id,
            "solid_sample_no": plate_sample_no,
            "previous_liquid": use_electrolyte,
            "liquid_custom_position": "cell1_we",
            "liquid_sample_no": liquid_sample_no,            
            "liquid_sample_volume_ul": liquid_sample_volume_ul,
        }
    )
    # if led_illumination:
    #     epm.add_experiment(
    #         "ADSS_sub_cell_illumination",
    #         {
    #             "led_wavelength": led_wavelength,
    #             "illumination_on": led_illumination,
    #         }
            
    #     )
    if not use_electrolyte:

        epm.add_experiment(
            "ADSS_sub_cellfill_prefilled",
            {
                "Solution_volume_ul": liquid_sample_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
            }
        )

    epm.add_experiment(
        "ADSS_sub_recirculate",
        {
            "wait_time_s": recirculate_wait_time_m * 60,
        })
    washmod = 0
#N2clean cvs
    for i, CV_cycle in enumerate(CV_cycles):

        epm.add_experiment(
            "ADSS_sub_CV",
            {
                "Vinit_vsRHE": Vinit_vsRHE[i],
                "Vapex1_vsRHE": Vapex1_vsRHE[i],
                "Vapex2_vsRHE": Vapex2_vsRHE[i],
                "Vfinal_vsRHE": Vfinal_vsRHE[i],
                "scanrate_voltsec": scanrate_voltsec[i],
                "SampleRate": CV_samplerate_sec,
                "cycles": CV_cycle,
                "gamry_i_range": gamry_i_range,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_insitu": False,
            },
        )
        if i == 1:
            epm.add_experiment(
                "ADSS_sub_interrupt",
                {
                    "reason":"Pause for switch to oxygen"
                },
            )
        # if aliquot_postCV[i] == 1:
        #     washmod += 1
        #     washone = washmod %4 %3 %2
        #     washtwo = (washmod + 1) %4 %3 %2
        #     washthree = (washmod + 2) %4 %3 %2
        #     washfour = (washmod + 3) %4 %3 %2

        #     epm.add_experiment(
        #         "ADSS_sub_sample_aliquot",
        #         {
        #             "aliquot_volume_ul": aliquot_volume_ul,
        #             "EquilibrationTime_s": 0,
        #             "PAL_Injector": PAL_Injector,
        #             "PAL_Injector_id": PAL_Injector_id,
        #             "rinse_1": washone,
        #             "rinse_2": washtwo,
        #             "rinse_3": washthree,
        #             "rinse_4": washfour,
        #         }
        #     )

    # for i, CA_potential_vs in enumerate(CA_potentials_vs):

    #     epm.add_experiment(
    #         "ADSS_sub_CA",
    #         {
    #             "CA_potential": CA_potential_vs,
    #             "ph": ph,
    #             "ref_type": ref_type,
    #             "ref_offset__V": ref_offset__V,
    #             "potential_versus": potential_versus,
    #             "samplerate_sec": CA_samplerate_sec,
    #             "CA_duration_sec": CA_duration_sec[i],
    #             "gamry_i_range": gamry_i_range,
    #             "aliquot_insitu": False,
    #         },
    #     )
    #     if aliquot_postCA[i] == 1:
    #         washmod += 1
    #         washone = washmod %4 %3 %2
    #         washtwo = (washmod + 1) %4 %3 %2
    #         washthree = (washmod + 2) %4 %3 %2
    #         washfour = (washmod + 3) %4 %3 %2

    #         epm.add_experiment(
    #             "ADSS_sub_sample_aliquot",
    #             {
    #                 "aliquot_volume_ul": aliquot_volume_ul,
    #                 "EquilibrationTime_s": 0,
    #                 "PAL_Injector": PAL_Injector,
    #                 "PAL_Injector_id": PAL_Injector_id,
    #                 "rinse_1": washone,
    #                 "rinse_2": washtwo,
    #                 "rinse_3": washthree,
    #                 "rinse_4": washfour,
    #             }
    #         )
    epm.add_experiment(
            "ADSS_sub_interrupt",
            {
                "reason":"Pause for injection of phosphoric"
            },
        )
    epm.add_experiment(
        "ADSS_sub_recirculate",
        {
            "wait_time_s": 10,
        })

    for i, CV_cycle in enumerate(CV2_cycles):

        epm.add_experiment(
            "ADSS_sub_CV",
            {
                "Vinit_vsRHE": CV2_Vinit_vsRHE[i],
                "Vapex1_vsRHE": CV2_Vapex1_vsRHE[i],
                "Vapex2_vsRHE": CV2_Vapex2_vsRHE[i],
                "Vfinal_vsRHE": CV2_Vfinal_vsRHE[i],
                "scanrate_voltsec": CV2_scanrate_voltsec[i],
                "SampleRate": CV2_samplerate_sec,
                "cycles": CV_cycle,
                "gamry_i_range": gamry_i_range,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_insitu": False,
            },
        )
        # if aliquot_postCV[i] == 1:
        #     washmod += 1
        #     washone = washmod %4 %3 %2
        #     washtwo = (washmod + 1) %4 %3 %2
        #     washthree = (washmod + 2) %4 %3 %2
        #     washfour = (washmod + 3) %4 %3 %2

        #     epm.add_experiment(
        #         "ADSS_sub_sample_aliquot",
        #         {
        #             "aliquot_volume_ul": aliquot_volume_ul,
        #             "EquilibrationTime_s": 0,
        #             "PAL_Injector": PAL_Injector,
        #             "PAL_Injector_id": PAL_Injector_id,
        #             "rinse_1": washone,
        #             "rinse_2": washtwo,
        #             "rinse_3": washthree,
        #             "rinse_4": washfour,
        #         }
        #     )

    if keep_electrolyte:
        epm.add_experiment("ADSS_sub_unload_solid",{})

    else:

        epm.add_experiment("ADSS_sub_unloadall_customs",{})
        epm.add_experiment(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": Cell_draintime_s,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
            #    "ResidualWait_s": ResidualWait_s,
            }
        )
        epm.add_experiment("ADSS_sub_move_to_clean_cell",{})
        epm.add_experiment(
            "ADSS_sub_clean_cell",
            {
                "Clean_volume": Clean_volume_ul,
                "DrainWait_s": CleanDrainWait_s,
            #    "ResidualWait_s": ResidualWait_s,
            }
        )
        epm.add_experiment(
                "ADSS_sub_interrupt",
                {
                    "reason":"Pause for switch to nitrogen"
                },
            )

        epm.add_experiment(
            "ADSS_sub_move_to_sample",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": second_sample_no,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            },
        )
        epm.add_experiment(
            "ADSS_sub_load",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample_no,
                "previous_liquid": use_electrolyte,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,            
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            }
        )
    
        epm.add_experiment(
            "ADSS_sub_cellfill_prefilled",
            {
                "Solution_volume_ul": liquid_sample_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
            }
        )

        epm.add_experiment(
            "ADSS_sub_recirculate",
            {
                "wait_time_s": recirculate_wait_time_m * 60,
            })
        washmod = 0
    #N2clean cvs
        for i, CV_cycle in enumerate(CV_cycles):

            epm.add_experiment(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": Vinit_vsRHE[i],
                    "Vapex1_vsRHE": Vapex1_vsRHE[i],
                    "Vapex2_vsRHE": Vapex2_vsRHE[i],
                    "Vfinal_vsRHE": Vfinal_vsRHE[i],
                    "scanrate_voltsec": scanrate_voltsec[i],
                    "SampleRate": CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                },
            )
            if i == 0:
                epm.add_experiment(
                    "ADSS_sub_interrupt",
                    {
                        "reason":"Pause for switch to oxygen"
                    },
                )
            if i == 1: break

        if keep_electrolyte_post:
            epm.add_experiment("ADSS_sub_unload_solid",{})

        else:

            epm.add_experiment("ADSS_sub_unloadall_customs",{})
            epm.add_experiment(
                "ADSS_sub_drain_cell",
                {
                    "DrainWait_s": Cell_draintime_s,
                    "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
                #    "ResidualWait_s": ResidualWait_s,
                }
            )

            


    return epm.experiment_plan_list  # returns complete experiment list

def ADSS_PA_CVs_CAs_CVs_autogasswitching(
    sequence_version: int = 1, 
    #solid_custom_position: str = "cell1_we",
    plate_id: int = 6307,
    plate_sample_no: int = 14050,  #  instead of map select
    same_sample: bool = False,
    use_electrolyte: bool = False,
    keep_electrolyte: bool = False,
    #liquid_custom_position: str = "elec_res1",
    liquid_sample_no: int = 1053,
    liquid_sample_volume_ul: float = 4000,
    phosphoric_sample_no: int = 99999,
    phosphoric_location: List[int] = [2,2,54],
    phosphoric_quantity_ul: int = 0,
    recirculate_wait_time_m: float = 5,
    postN2_recirculate_wait_time_m: float = 5,
    CleaningCV_cycles: int = 6,
    CleaningCV_Vinit_vsRHE: float = 0.05,
    CleaningCV_Vapex2_vsRHE: float = 1.5,
    CleaningCV_scanrate_voltsec: float = 0.1,
    CV_cycles: List[int] = [10,3],
    Vinit_vsRHE: List[float] = [0.05,0.05,0.05],  # Initial value in volts or amps.
    Vapex1_vsRHE: List[float] = [0.05,0.05,0.05],  # Apex 1 value in volts or amps.
    Vapex2_vsRHE: List[float] = [1.2,1.2,1.2],  # Apex 2 value in volts or amps.
    Vfinal_vsRHE: List[float] = [0.05,0.05,0.05],  # Final value in volts or amps.
    scanrate_voltsec: List[float] = [0.1,0.02,0.02],  # scan rate in volts/second or amps/second.
    CV_samplerate_sec: float = 0.05,
    CA_potentials_vs: List[float] = [0.6,0.4],
    potential_versus: str = "rhe",
    CA_duration_sec: List[float] = [60,60],
    CA_samplerate_sec: float = 0.1,
    CV2_cycles: List[int] = [3],
    CV2_Vinit_vsRHE: List[float] = [0.05],  # Initial value in volts or amps.
    CV2_Vapex1_vsRHE: List[float] = [0.05],  # Apex 1 value in volts or amps.
    CV2_Vapex2_vsRHE: List[float] = [1.2],  # Apex 2 value in volts or amps.
    CV2_Vfinal_vsRHE: List[float] = [0.05],  # Final value in volts or amps.
    CV2_scanrate_voltsec: List[float] = [0.02],  # scan rate in volts/second or amps/second.
    CV2_samplerate_sec: float = 0.05,
    gamry_i_range: str = "auto",
    ph: float = 1.24,
    ref_type: str = "leakless",
    ref_offset__V: float = 0.0,
    aliquot_init: bool = True,
    aliquot_postCV: List[int] = [1,0,0],
    aliquot_postCA: List[int] = [1,0],
    aliquot_volume_ul: int = 100,
    Syringe_rate_ulsec: float = 300,
    # Drain: bool = False,
    Cell_draintime_s: float = 60,
     #ReturnLineWait_s: float = 30,
    ReturnLineReverseWait_s: float = 10,
    clean_cell: bool = False,
    Clean_volume_ul: float = 12000,
    CleanDrainWait_s: float = 80,
    # ResidualWait_s: float = 15,
    # flush_volume_ul: float = 2000,
    # clean: bool = False,
    # clean_volume_ul: float = 5000,
    # refill: bool = False,
    # refill_volume_ul: float = 6000,
    # water_refill_volume_ul: float = 6000,
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "LS4_peek"
):

    """tbd

    last functionality test: tbd"""

    epm = ExperimentPlanMaker()

    if phosphoric_quantity_ul:
        #may need vial unload, also vial liquid load

        epm.add_experiment(
                "ADSS_sub_interrupt",
                {
                    "reason":"this is where phosphoric source is set"
                },
            )

        # epm.add_experiment(
        #     "archive_custom_add_liquid",
        #     {},
        # )


#need to put phosphoric into helao vial tracking


    #for solid_sample_no in plate_sample_no_list:  # have to indent add expts if used

    if not same_sample:
        
        epm.add_experiment(
            "ADSS_sub_move_to_sample",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample_no,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            },
        )
    epm.add_experiment(
        "ADSS_sub_load",
        {
            "solid_custom_position": "cell1_we",
            "solid_plate_id": plate_id,
            "solid_sample_no": plate_sample_no,
            "previous_liquid": use_electrolyte,
            "liquid_custom_position": "cell1_we",
            "liquid_sample_no": liquid_sample_no,            
            "liquid_sample_volume_ul": liquid_sample_volume_ul,
        }
    )
    washmod = 0

    # if led_illumination:
    #     epm.add_experiment(
    #         "ADSS_sub_cell_illumination",
    #         {
    #             "led_wavelength": led_wavelength,
    #             "illumination_on": led_illumination,
    #         }
            
    #     )
    if not use_electrolyte:

        epm.add_experiment(
            "ADSS_sub_cellfill_prefilled",
            {
                "Solution_volume_ul": liquid_sample_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
            }
        )
#N2 gas for initial cleaning
    epm.add_experiment("ADSS_sub_gasvalve_N2flow",{"open": True,})
    epm.add_experiment("ADSS_sub_recirculate",{"wait_time_s": recirculate_wait_time_m * 60,})
    
    if aliquot_init: 
        
        washmod += 1
        washone = washmod %4 %3 %2
        washtwo = (washmod + 1) %4 %3 %2
        washthree = (washmod + 2) %4 %3 %2
        washfour = (washmod + 3) %4 %3 %2

        epm.add_experiment(
            "ADSS_sub_sample_aliquot",
            {
                "aliquot_volume_ul": aliquot_volume_ul,
                "EquilibrationTime_s": 0,
                "PAL_Injector": PAL_Injector,
                "PAL_Injector_id": PAL_Injector_id,
                "rinse_1": washone,
                "rinse_2": washtwo,
                "rinse_3": washthree,
                "rinse_4": washfour,
            })


#N2clean cvs
    
    epm.add_experiment(
        "ADSS_sub_CV",
        {
            "Vinit_vsRHE": CleaningCV_Vinit_vsRHE,
            "Vapex1_vsRHE": CleaningCV_Vinit_vsRHE,
            "Vapex2_vsRHE": CleaningCV_Vapex2_vsRHE,
            "Vfinal_vsRHE": CleaningCV_Vinit_vsRHE,
            "scanrate_voltsec": CleaningCV_scanrate_voltsec,
            "SampleRate": CV_samplerate_sec,
            "cycles": CleaningCV_cycles,
            "gamry_i_range": gamry_i_range,
            "ph": ph,
            "ref_type": ref_type,
            "ref_offset__V": ref_offset__V,
            "aliquot_insitu": False,
        },
    )
#switch back to oxygen
    epm.add_experiment("ADSS_sub_gasvalve_N2flow",{"open": False,})
    epm.add_experiment("ADSS_sub_recirculate",{"wait_time_s": postN2_recirculate_wait_time_m * 60,})



# CV cycles of interest

    for i, CV_cycle in enumerate(CV_cycles):

        epm.add_experiment(
            "ADSS_sub_CV",
            {
                "Vinit_vsRHE": Vinit_vsRHE[i],
                "Vapex1_vsRHE": Vapex1_vsRHE[i],
                "Vapex2_vsRHE": Vapex2_vsRHE[i],
                "Vfinal_vsRHE": Vfinal_vsRHE[i],
                "scanrate_voltsec": scanrate_voltsec[i],
                "SampleRate": CV_samplerate_sec,
                "cycles": CV_cycle,
                "gamry_i_range": gamry_i_range,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_insitu": False,
            },
        )
        if aliquot_postCV[i] == 1:
            washmod += 1
            washone = washmod %4 %3 %2
            washtwo = (washmod + 1) %4 %3 %2
            washthree = (washmod + 2) %4 %3 %2
            washfour = (washmod + 3) %4 %3 %2

            epm.add_experiment(
                "ADSS_sub_sample_aliquot",
                {
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "EquilibrationTime_s": 0,
                    "PAL_Injector": PAL_Injector,
                    "PAL_Injector_id": PAL_Injector_id,
                    "rinse_1": washone,
                    "rinse_2": washtwo,
                    "rinse_3": washthree,
                    "rinse_4": washfour,
                }
            )

    for i, CA_potential_vs in enumerate(CA_potentials_vs):

        epm.add_experiment(
            "ADSS_sub_CA",
            {
                "CA_potential": CA_potential_vs,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "potential_versus": potential_versus,
                "samplerate_sec": CA_samplerate_sec,
                "CA_duration_sec": CA_duration_sec[i],
                "gamry_i_range": gamry_i_range,
                "aliquot_insitu": False,
            },
        )
        if aliquot_postCA[i] == 1:
            washmod += 1
            washone = washmod %4 %3 %2
            washtwo = (washmod + 1) %4 %3 %2
            washthree = (washmod + 2) %4 %3 %2
            washfour = (washmod + 3) %4 %3 %2

            epm.add_experiment(
                "ADSS_sub_sample_aliquot",
                {
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "EquilibrationTime_s": 0,
                    "PAL_Injector": PAL_Injector,
                    "PAL_Injector_id": PAL_Injector_id,
                    "rinse_1": washone,
                    "rinse_2": washtwo,
                    "rinse_3": washthree,
                    "rinse_4": washfour,
                }
            )
    # epm.add_experiment(
    #         "ADSS_sub_interrupt",
    #         {
    #             "reason":"Pause for injection of phosphoric",
    #         },
    #     )

    epm.add_experiment(
        "ADSS_sub_tranfer_liquid_in",
        {
            "destination": "cell1_we",
            "source_tray": phosphoric_location[0],
            "source_slot": phosphoric_location[1],
            "source_vial": phosphoric_location[2],            
            "liquid_sample_no": phosphoric_sample_no,
            "aliquot_volume_ul": phosphoric_quantity_ul,
            "PAL_Injector": PAL_Injector,
            "PAL_Injector_id": PAL_Injector_id,
            "rinse_1": True,
            "rinse_2": False,
            "rinse_3": False,
            "rinse_4": True,
        },
    )




    epm.add_experiment(
        "ADSS_sub_recirculate",
        {
            "wait_time_s": 10,
        })

    for i, CV_cycle in enumerate(CV2_cycles):

        epm.add_experiment(
            "ADSS_sub_CV",
            {
                "Vinit_vsRHE": CV2_Vinit_vsRHE[i],
                "Vapex1_vsRHE": CV2_Vapex1_vsRHE[i],
                "Vapex2_vsRHE": CV2_Vapex2_vsRHE[i],
                "Vfinal_vsRHE": CV2_Vfinal_vsRHE[i],
                "scanrate_voltsec": CV2_scanrate_voltsec[i],
                "SampleRate": CV2_samplerate_sec,
                "cycles": CV_cycle,
                "gamry_i_range": gamry_i_range,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "aliquot_insitu": False,
            },
        )
        if aliquot_postCV[i] == 1:
            washmod += 1
            washone = washmod %4 %3 %2
            washtwo = (washmod + 1) %4 %3 %2
            washthree = (washmod + 2) %4 %3 %2
            washfour = (washmod + 3) %4 %3 %2

            epm.add_experiment(
                "ADSS_sub_sample_aliquot",
                {
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "EquilibrationTime_s": 0,
                    "PAL_Injector": PAL_Injector,
                    "PAL_Injector_id": PAL_Injector_id,
                    "rinse_1": washone,
                    "rinse_2": washtwo,
                    "rinse_3": washthree,
                    "rinse_4": washfour,
                }
            )

    if keep_electrolyte:
        epm.add_experiment("ADSS_sub_unload_solid",{})

    else:

        epm.add_experiment("ADSS_sub_unloadall_customs",{})
        epm.add_experiment(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": Cell_draintime_s,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
            #    "ResidualWait_s": ResidualWait_s,
            }
        )
        if clean_cell:
            epm.add_experiment("ADSS_sub_move_to_clean_cell",{})
            epm.add_experiment(
                "ADSS_sub_clean_cell",
                {
                    "Clean_volume": Clean_volume_ul,
                    "DrainWait_s": CleanDrainWait_s,
                #    "ResidualWait_s": ResidualWait_s,
                }
            )


    return epm.experiment_plan_list  # returns complete experiment list



def ADSS_PA_CV_TRI(
    sequence_version: int = 4, #bubble removal
    #note: str = "need as many samples as you expect combinations of UPL and LPL",
    
    #sample info
    #solid_custom_position: str = "cell1_we",
    plate_id: int = 6307,
    plate_id_ref_Pt: int = 6173,
    plate_sample_no_list: List[int] = [16304],  #  need as many samples as you expect combinations of UPL and LPL
    LPL_list: List[float] = [0.05, 0.55, 0.05, 0.55,],
    UPL_list: List[float] = [1.3, 0.8, 1.3, 0.8,],

    #side info
    same_sample: bool = False,
    use_bubble_removal: bool = True,
    use_current_electrolyte: bool = False,
    pump_reversal_during_filling: bool = False,
    keep_electrolyte_at_end: bool = False,
    move_to_clean_and_clean: bool = True,
    measure_ref_Pt_at_beginning: bool = True,
    name_ref_Pt_at_beginning: str = "builtin_ref_motorxy_2",
    measure_ref_Pt_at_end: bool = True,
    name_ref_Pt_at_end: str = "builtin_ref_motorxy_3",
    
    #bubble removal OCV
    bubble_removal_OCV_t_s: int = 10,
    bubble_removal_pump_reverse_t_s: int = 15,
    bubble_removal_pump_forward_t_s: int = 10,
    bubble_removal_RSD_threshold: float = 0.2,
    bubble_removal_simple_threshold: float = 0.3,
    bubble_removal_signal_change_threshold: float = 0.01,
    bubble_removal_amplitude_threshold: float = 0.05,

    #purge wait times
    purge_wait_initialN2_min: int = 10,
    purge_wait_N2_to_O2_min: int = 5,
    purge_wait_O2_to_N2_min: int = 15,

    #electrolyte info
    rinse_with_electrolyte_bf_prefill: bool = True,
    rinse_with_electrolyte_bf_prefill_volume_uL: float = 3000,
    rinse_with_electrolyte_bf_prefill_recirculate_wait_time_sec: float = 30,
    rinse_with_electrolyte_bf_prefill_drain_time_sec: float = 30,
    ph: float = 1.24,
    liquid_sample_no: int = 1053,
    liquid_sample_volume_ul: float = 7000,
    Syringe_rate_ulsec: float = 300,
    fill_recirculate_wait_time_sec: float = 30,    
    fill_recirculate_reverse_wait_time_sec: float = 15,
    
    #phosphoric acid injection info
    Inject_PA: bool= True,
    phosphoric_sample_no: int = 1261,
    phosphoric_location: List[int] = [2,3,54],
    phosphoric_quantity_ul: int = 90,
    inject_recirculate_wait_time_sec: float = 60,
    #liquid_custom_position: str = "elec_res1",

    #Ref Pt measurement CVs
    ref_CV_cycles: List[int] = [8],
    ref_Vinit_vsRHE: List[float] = [0.05],  # Initial value in volts or amps.
    ref_Vapex1_vsRHE: List[float] = [1.3],  # Apex 1 value in volts or amps.
    ref_Vapex2_vsRHE: List[float] = [0.05],  # Apex 2 value in volts or amps.
    ref_Vfinal_vsRHE: List[float] = [0.05],  # Final value in volts or amps.
    ref_CV_scanrate_voltsec: List[float] = [0.1],  # scan rate in volts/second or amps/second.
    ref_CV_samplerate_sec: float = 0.01,

    #cleaning CVs 
    cleaning_CV_cycles: List[int] = [20],
    cleaning_Vinit_vsRHE: List[float] = [0.05],  # Initial value in volts or amps.
    cleaning_Vapex1_vsRHE: List[float] = [1.5],  # Apex 1 value in volts or amps.
    cleaning_Vapex2_vsRHE: List[float] = [0.05],  # Apex 2 value in volts or amps.
    cleaning_Vfinal_vsRHE: List[float] = [0.05],  # Final value in volts or amps.
    cleaning_scanrate_voltsec: List[float] = [0.2],  # scan rate in volts/second or amps/second.
    cleaning_CV_samplerate_sec: float = 0.02,

    #testing CV info
    testing_CV_scanrate_voltsec: float= 0.1,
    testing_CV_samplerate_sec: float = 0.01,

    #CVs in N2 for background
    CV_N2_cycles: List[int] = [5],
    #CV_N2_Vinit_vsRHE: List[float] = [1.23, 1.23, 1.23],  # Initial value in volts or amps.
    #CV_N2_Vapex1_vsRHE: List[float] = [1.23, 1.23, 1.23],  # Apex 1 value in volts or amps.
    #CV_N2_Vapex2_vsRHE: List[float] = [0.6, 0.4, 0],  # Apex 2 value in volts or amps.
    #CV_N2_Vfinal_vsRHE: List[float] = [0.6, 0.4, 0],  # Final value in volts or amps.
    #CV_N2_scanrate_voltsec: List[float] = [0.02,0.02,0.02],  # scan rate in volts/second or amps/second.
    #CV_N2_samplerate_sec: float = 0.05,

    #CVs in O2 and with and without PA
    CV_O2_cycles: List[int] = [5,25,50],
    #CV_O2_Vinit_vsRHE: List[float] = [1.23, 1.23, 1.23],  # Initial value in volts or amps.
    #CV_O2_Vapex1_vsRHE: List[float] = [1.23, 1.23, 1.23],  # Apex 1 value in volts or amps.
    #CV_O2_Vapex2_vsRHE: List[float] = [0.6, 0.4, 0],  # Apex 2 value in volts or amps.
    #CV_O2_Vfinal_vsRHE: List[float] = [0.6, 0.4, 0],  # Final value in volts or amps.
    #CV_O2_scanrate_voltsec: List[float] = [0.02,0.02,0.02],  # scan rate in volts/second or amps/second.
    #CV_O2_samplerate_sec: float = 0.05,

    #OCP info
    OCP_samplerate_sec: float = 0.5,

    #Pstat and ref info
    gamry_i_range: str = "auto",
    ref_type: str = "leakless",
    ref_offset__V: float = -0.005,
    
    #aliquote info
    aliquot_init: bool = True,
    aliquot_after_cleaningCV: List[int] = [0],
    aliquote_after_CV_init: List[int] = [1],
    aliquote_CV_O2: List[int] = [1,1,1],
    aliquote_CV_final: List[int] = [0],
    aliquot_volume_ul: int = 100,
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "LS4_peek",
    
    #cell drain info
    cell_draintime_sec: float = 60,
    ReturnLineReverseWait_sec: float = 5,
    
    #cell clean info
    number_of_cleans: int = 2,
    clean_volume_ul: float = 12000,
    clean_recirculate_sec: float = 60,
    clean_drain_sec: float = 120,
    # ResidualWait_s: float = 15,
    # flush_volume_ul: float = 2000,
    # clean: bool = False,
    # clean_volume_ul: float = 5000,
    # refill: bool = False,
    # refill_volume_ul: float = 6000,
    # water_refill_volume_ul: float = 6000,

):

    """
    This sequence is the most recent one for the TRI Pt dissolution project using ADSS.
    Included features:
    - scheduled aliquotes and injection of phosphoric acid
    - track gas saturation with OCV during N2-O2 and O2-N2 switches
    - automatic refill of syringes
    - you can define number of cleaning cycles (to make sure we are cleaning off Co and Ni residues)
    - include reference Pt measurements before and after sequence
    - generating sample-LPL-UPL combinations
    - bubble removal using OCV. bubble removal = reversal of pumps for some seconds 

    """

    epm = ExperimentPlanMaker()

###################################################################
#REF MEASUREMENT AT BEGINNING OF SEQUENCE
###################################################################

    #ref measurement at beginning of sequence
    if measure_ref_Pt_at_beginning:
        epm.add_experiment(
            "ADSS_sub_move_to_ref_measurement",
            {
                "reference_position_name": name_ref_Pt_at_beginning
            }
        )

        epm.add_experiment(
            "ADSS_sub_load",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id_ref_Pt,
                "solid_sample_no": 1,################### can i use the sample id for all ref measurements?
                "previous_liquid": use_current_electrolyte,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            }
        )

        #rinse with electrolyte to remove cleaning liquid residuals
        if rinse_with_electrolyte_bf_prefill:
            epm.add_experiment(
                "ADSS_sub_cellfill_prefilled",
                {
                    "Solution_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                    "Syringe_rate_ulsec": Syringe_rate_ulsec,
                }
            )
            epm.add_experiment(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "forward",
                    "wait_time_s": rinse_with_electrolyte_bf_prefill_recirculate_wait_time_sec,
                }
            )
            epm.add_experiment(
                "ADSS_sub_drain_cell",
                {
                    "DrainWait_s": rinse_with_electrolyte_bf_prefill_drain_time_sec,
                    "ReturnLineReverseWait_s": 5,
                #    "ResidualWait_s": ResidualWait_s,
                }
            )
            epm.add_experiment("ADSS_sub_refill_syringe", {
                "syringe": "electrolyte",
                "fill_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
                }
            )         


        #electrolyte filling for experiment
        epm.add_experiment(
            "ADSS_sub_cellfill_prefilled",
            {
                "Solution_volume_ul": liquid_sample_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
            }
        )

        #set initial gas to N2
        epm.add_experiment("ADSS_sub_gasvalve_N2flow",{"open": True,})

        # pump recirculate forward
        epm.add_experiment(
            "ADSS_sub_recirculate",
            {
                "direction_forward_or_reverse": "forward",
                "wait_time_s": fill_recirculate_wait_time_sec,
            }
        )
        
        # pump recirculate reverse (for bubbles)
        if pump_reversal_during_filling:
            epm.add_experiment(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "reverse",
                    "wait_time_s": fill_recirculate_reverse_wait_time_sec,
                })
        
            # pump recirculate forward
            epm.add_experiment(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "forward",
                    "wait_time_s": 5,
                }
            )

        #refill electrolyte syringe here so that ADSS can recirculate and N2 saturate while filling syringe
        if not use_current_electrolyte:
            epm.add_experiment("ADSS_sub_refill_syringe", {
                "syringe": "electrolyte",
                "fill_volume_ul": liquid_sample_volume_ul,
                "Syringe_rate_ulsec": 300,
                }
            )

        #check for bubbles that could interfere with echem measurments with OCV
        if use_bubble_removal:
            epm.add_experiment("ADSS_sub_OCV",
                               {
                                "check_bubble": True,
                                "Tval__s": bubble_removal_OCV_t_s,
                                "samplerate_sec": 0.1,
                                "gamry_i_range": gamry_i_range,
                                "ph": ph,
                                "ref_type": ref_type,
                                "ref_offset__V": ref_offset__V,
                                "aliquot_insitu": False,
                                "run_use": "ref",
                                "RSD_threshold": bubble_removal_RSD_threshold,
                                "simple_threshold": bubble_removal_simple_threshold,
                                "signal_change_threshold": bubble_removal_signal_change_threshold,
                                "amplitude_threshold": bubble_removal_amplitude_threshold,
                                "bubble_pump_reverse_time_s": bubble_removal_pump_reverse_t_s,
                                "bubble_pump_forward_time_s": bubble_removal_pump_forward_t_s,
                                })

        #saturate electrolyte with N2 and measure OCV while saturation
        epm.add_experiment("ADSS_sub_OCV", 
                           {
                               "Tval__s": purge_wait_initialN2_min * 60,
                               "samplerate_sec": OCP_samplerate_sec,
                               "gamry_i_range": gamry_i_range,
                               "ph": ph,
                               "ref_type": ref_type,
                               "ref_offset__V": ref_offset__V,
                               "aliquot_insitu": False,
                               "run_use": "ref"
                           })

        # epm.add_experiment(
        #     "orch_sub_wait",
        #     {
        #         "wait_time_s": purge_wait_initialN2_min * 60,
        #     }
        # )
        
        #start cleaning CVs in N2
        for i, CV_cycle in enumerate(cleaning_CV_cycles):
            epm.add_experiment(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": cleaning_Vinit_vsRHE[i],
                    "Vapex1_vsRHE": cleaning_Vapex1_vsRHE[i],
                    "Vapex2_vsRHE": cleaning_Vapex2_vsRHE[i],
                    "Vfinal_vsRHE": cleaning_Vfinal_vsRHE[i],
                    "scanrate_voltsec": cleaning_scanrate_voltsec[i],
                    "SampleRate": cleaning_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "run_use": "ref"
                }
            )
            
        #start background CVs in N2
        for i, CV_cycle in enumerate(ref_CV_cycles):
            epm.add_experiment(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": ref_Vinit_vsRHE,
                    "Vapex1_vsRHE": ref_Vapex1_vsRHE,
                    "Vapex2_vsRHE": ref_Vapex2_vsRHE,
                    "Vfinal_vsRHE": ref_Vfinal_vsRHE,
                    "scanrate_voltsec": ref_CV_scanrate_voltsec,
                    "SampleRate": ref_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "run_use": "ref"
                }
            )
        
        #switch from N2 to O2 and saturate
        epm.add_experiment("ADSS_sub_gasvalve_N2flow",{"open": False,})
        epm.add_experiment("ADSS_sub_OCV", 
                    {
                        "Tval__s": purge_wait_N2_to_O2_min * 60,
                        "samplerate_sec": OCP_samplerate_sec,
                        "gamry_i_range": gamry_i_range,
                        "ph": ph,
                        "ref_type": ref_type,
                        "ref_offset__V": ref_offset__V,
                        "aliquot_insitu": False,
                        "run_use": "ref"
                    })
#        epm.add_experiment(
#            "orch_sub_wait",
#            {
#                "wait_time_s": purge_wait_N2_to_O2_min * 60,
#            }
#        )

        #start O2 cycles
        for i, CV_cycle in enumerate(ref_CV_cycles):
            epm.add_experiment(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": ref_Vinit_vsRHE,
                    "Vapex1_vsRHE": ref_Vapex1_vsRHE,
                    "Vapex2_vsRHE": ref_Vapex2_vsRHE,
                    "Vfinal_vsRHE": ref_Vfinal_vsRHE,
                    "scanrate_voltsec": ref_CV_scanrate_voltsec,
                    "SampleRate": ref_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "run_use": "ref"
                }
            )
        
        #switch from O2 to N2 and saturate
        epm.add_experiment("ADSS_sub_gasvalve_N2flow",{"open": True,})

        #unload sample
        epm.add_experiment("ADSS_sub_unloadall_customs",{})
        
        #drain cell
        epm.add_experiment(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": cell_draintime_sec,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_sec,
            #    "ResidualWait_s": ResidualWait_s,
            }
        )

        #clean cell
        if move_to_clean_and_clean:
            epm.add_experiment("ADSS_sub_move_to_clean_cell", {})
            for i in range(number_of_cleans):
                epm.add_experiment("ADSS_sub_clean_cell",
                                {
                                    "Clean_volume_ul": clean_volume_ul,
                                    "ReturnLineWait_s": clean_recirculate_sec,
                                    "DrainWait_s": clean_drain_sec,
                                }
                            )
                #if working with more than 10mL cleaning V, then by default a precleaning with 6mL is done. This would also be needed to refill
                if clean_volume_ul > 10000:
                    volume = 6000 + clean_volume_ul
                else:
                    volume = clean_volume_ul

                epm.add_experiment("ADSS_sub_refill_syringe", {
                    "syringe": "waterclean",
                    "fill_volume_ul": volume,
                    "Syringe_rate_ulsec": 300,
                    }
                )  

###################################################################
#SEQUENCE FOR ACTUAL SAMPLE
###################################################################

    #for solid_sample_no in plate_sample_no_list:  # have to indent add expts if used
    for lpl, upl, sample_no in zip(LPL_list, UPL_list, plate_sample_no_list):
        print("##########################################################\n" +
                "Current LPL is {} Vrhe\n".format(lpl) + 
                "Current UPL is {} Vrhe\n".format(upl) + 
                "Current Sample is {}\n".format(sample_no) + 
                "##########################################################")

        if not same_sample:
            
            epm.add_experiment(
                "ADSS_sub_move_to_sample",
                {
                    "solid_custom_position": "cell1_we",
                    "solid_plate_id": plate_id,
                    "solid_sample_no": sample_no,
                    "liquid_custom_position": "cell1_we",
                    "liquid_sample_no": liquid_sample_no,
                    "liquid_sample_volume_ul": liquid_sample_volume_ul,
                }
            )

        epm.add_experiment(
            "ADSS_sub_load",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": sample_no,
                "previous_liquid": use_current_electrolyte,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,            
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            }
        )

        #rinse with electrolyte to remove cleaning liquid residuals
        if rinse_with_electrolyte_bf_prefill:
            epm.add_experiment(
                "ADSS_sub_cellfill_prefilled",
                {
                    "Solution_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                    "Syringe_rate_ulsec": Syringe_rate_ulsec,
                }
            )
            epm.add_experiment(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "forward",
                    "wait_time_s": rinse_with_electrolyte_bf_prefill_recirculate_wait_time_sec,
                }
            )
            epm.add_experiment(
                "ADSS_sub_drain_cell",
                {
                    "DrainWait_s": rinse_with_electrolyte_bf_prefill_drain_time_sec,
                    "ReturnLineReverseWait_s": 5,
                #    "ResidualWait_s": ResidualWait_s,
                }
            )
            epm.add_experiment("ADSS_sub_refill_syringe", {
                "syringe": "electrolyte",
                "fill_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
                }
            )

        #electrolyte filling for experiment
        if not use_current_electrolyte:
            epm.add_experiment(
                "ADSS_sub_cellfill_prefilled",
                {
                    "Solution_volume_ul": liquid_sample_volume_ul,
                    "Syringe_rate_ulsec": Syringe_rate_ulsec,
                }
            )

        #set initial gas to N2
        epm.add_experiment("ADSS_sub_gasvalve_N2flow",{"open": True,})

        # pump recirculate forward
        epm.add_experiment(
            "ADSS_sub_recirculate",
            {
                "direction_forward_or_reverse": "forward",
                "wait_time_s": fill_recirculate_wait_time_sec,
            }
        )
        
        # pump recirculate reverse (for bubbles)
        if pump_reversal_during_filling:
            epm.add_experiment(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "reverse",
                    "wait_time_s": fill_recirculate_reverse_wait_time_sec,
                })
        
            # pump recirculate forward
            epm.add_experiment(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "forward",
                    "wait_time_s": 5,
                }
            )

        #refill electrolyte syringe here so that ADSS can recirculate and N2 saturate while filling syringe
        if not use_current_electrolyte:
            epm.add_experiment("ADSS_sub_refill_syringe", {
                "syringe": "electrolyte",
                "fill_volume_ul": liquid_sample_volume_ul,
                "Syringe_rate_ulsec": 300,
                }
            )

        washmod = 0

        if aliquot_init: #stops gas purge, takes aliquote, starts gas purge again
            
            washmod += 1
            washone = washmod %4 %3 %2
            washtwo = (washmod + 1) %4 %3 %2
            washthree = (washmod + 2) %4 %3 %2
            washfour = (washmod + 3) %4 %3 %2

            epm.add_experiment(
                "ADSS_sub_sample_aliquot",
                {
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "EquilibrationTime_s": 0,
                    "PAL_Injector": PAL_Injector,
                    "PAL_Injector_id": PAL_Injector_id,
                    "rinse_1": washone,
                    "rinse_2": washtwo,
                    "rinse_3": washthree,
                    "rinse_4": washfour,
                }
            )

        #check for bubbles that could interfere with echem measurments with OCV
        if use_bubble_removal:
            epm.add_experiment("ADSS_sub_OCV",
                               {
                                "check_bubble": True,
                                "Tval__s": bubble_removal_OCV_t_s,
                                "samplerate_sec": 0.1,
                                "gamry_i_range": gamry_i_range,
                                "ph": ph,
                                "ref_type": ref_type,
                                "ref_offset__V": ref_offset__V,
                                "aliquot_insitu": False,
                                "RSD_threshold": bubble_removal_RSD_threshold,
                                "simple_threshold": bubble_removal_simple_threshold,
                                "signal_change_threshold": bubble_removal_signal_change_threshold,
                                "amplitude_threshold": bubble_removal_amplitude_threshold,
                                "bubble_pump_reverse_time_s": bubble_removal_pump_reverse_t_s,
                                "bubble_pump_forward_time_s": bubble_removal_pump_forward_t_s,
                                })

        #saturate electrolyte with N2
        epm.add_experiment("ADSS_sub_OCV", 
                    {
                        "Tval__s": purge_wait_initialN2_min * 60,
                        "samplerate_sec": OCP_samplerate_sec,
                        "gamry_i_range": gamry_i_range,
                        "ph": ph,
                        "ref_type": ref_type,
                        "ref_offset__V": ref_offset__V,
                        "aliquot_insitu": False,                        
                    })
        
        # epm.add_experiment(
        #     "orch_sub_wait",
        #     {
        #         "wait_time_s": purge_wait_initialN2_min * 60,
        #     }
        # )
        
        #start cleaning CVs in N2
        for i, CV_cycle in enumerate(cleaning_CV_cycles):
            epm.add_experiment(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": cleaning_Vinit_vsRHE[i],
                    "Vapex1_vsRHE": cleaning_Vapex1_vsRHE[i],
                    "Vapex2_vsRHE": cleaning_Vapex2_vsRHE[i],
                    "Vfinal_vsRHE": cleaning_Vfinal_vsRHE[i],
                    "scanrate_voltsec": cleaning_scanrate_voltsec[i],
                    "SampleRate": cleaning_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                }
            )
            if aliquot_after_cleaningCV[i] == 1:
                
                washmod += 1
                washone = washmod %4 %3 %2
                washtwo = (washmod + 1) %4 %3 %2
                washthree = (washmod + 2) %4 %3 %2
                washfour = (washmod + 3) %4 %3 %2

                epm.add_experiment(
                    "ADSS_sub_sample_aliquot",
                    {
                        "aliquot_volume_ul": aliquot_volume_ul,
                        "EquilibrationTime_s": 0,
                        "PAL_Injector": PAL_Injector,
                        "PAL_Injector_id": PAL_Injector_id,
                        "rinse_1": washone,
                        "rinse_2": washtwo,
                        "rinse_3": washthree,
                        "rinse_4": washfour,
                    }
                )

        #start background CVs in N2
        for i, CV_cycle in enumerate(CV_N2_cycles):
            epm.add_experiment(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": lpl,
                    "Vapex1_vsRHE": upl,
                    "Vapex2_vsRHE": lpl,
                    "Vfinal_vsRHE": lpl,
                    "scanrate_voltsec": testing_CV_scanrate_voltsec,
                    "SampleRate": testing_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                }
            )
            if aliquote_after_CV_init[i] == 1:
                
                washmod += 1
                washone = washmod %4 %3 %2
                washtwo = (washmod + 1) %4 %3 %2
                washthree = (washmod + 2) %4 %3 %2
                washfour = (washmod + 3) %4 %3 %2

                epm.add_experiment(
                    "ADSS_sub_sample_aliquot",
                    {
                        "aliquot_volume_ul": aliquot_volume_ul,
                        "EquilibrationTime_s": 0,
                        "PAL_Injector": PAL_Injector,
                        "PAL_Injector_id": PAL_Injector_id,
                        "rinse_1": washone,
                        "rinse_2": washtwo,
                        "rinse_3": washthree,
                        "rinse_4": washfour,
                    }
                )

        
        #switch from N2 to O2 and saturate
        epm.add_experiment("ADSS_sub_gasvalve_N2flow",{"open": False,})
        epm.add_experiment("ADSS_sub_OCV", 
                    {
                        "Tval__s": purge_wait_N2_to_O2_min * 60,
                        "samplerate_sec": OCP_samplerate_sec,
                        "gamry_i_range": gamry_i_range,
                        "ph": ph,
                        "ref_type": ref_type,
                        "ref_offset__V": ref_offset__V,
                        "aliquot_insitu": False,
                    })        
        
        # epm.add_experiment(
        #     "orch_sub_wait",
        #     {
        #         "wait_time_s": purge_wait_N2_to_O2_min * 60,
        #     }
        # )

        #start O2 cycles
        for i, CV_cycle in enumerate(CV_O2_cycles):

            epm.add_experiment(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": lpl,
                    "Vapex1_vsRHE": upl,
                    "Vapex2_vsRHE": lpl,
                    "Vfinal_vsRHE": lpl,
                    "scanrate_voltsec": testing_CV_scanrate_voltsec,
                    "SampleRate": testing_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                }
            )
            if aliquote_CV_O2[i] == 1:
                
                washmod += 1
                washone = washmod %4 %3 %2
                washtwo = (washmod + 1) %4 %3 %2
                washthree = (washmod + 2) %4 %3 %2
                washfour = (washmod + 3) %4 %3 %2

                epm.add_experiment(
                    "ADSS_sub_sample_aliquot",
                    {
                        "aliquot_volume_ul": aliquot_volume_ul,
                        "EquilibrationTime_s": 0,
                        "PAL_Injector": PAL_Injector,
                        "PAL_Injector_id": PAL_Injector_id,
                        "rinse_1": washone,
                        "rinse_2": washtwo,
                        "rinse_3": washthree,
                        "rinse_4": washfour,
                    }
                )

        #inject phosphoric acid
        if Inject_PA:
            washmod += 1
            washone = washmod %4 %3 %2
            washtwo = (washmod + 1) %4 %3 %2
            washthree = (washmod + 2) %4 %3 %2
            washfour = (washmod + 3) %4 %3 %2

            epm.add_experiment(
            "ADSS_sub_transfer_liquid_in",
            {
                "destination": "cell1_we",
                "source_tray": phosphoric_location[0],
                "source_slot": phosphoric_location[1],
                "source_vial": phosphoric_location[2],            
                "liquid_sample_no": phosphoric_sample_no,
                "aliquot_volume_ul": phosphoric_quantity_ul,
                "PAL_Injector": PAL_Injector,
                "PAL_Injector_id": PAL_Injector_id,
                "rinse_1": washone,
                "rinse_2": washtwo,
                "rinse_3": washthree,
                "rinse_4": washfour,
            }
        )

            #recirculate to mix PA into electrolyte
            epm.add_experiment(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "forward",
                    "wait_time_s": inject_recirculate_wait_time_sec,
                }
            )

        #start O2 cycles with PA
        for i, CV_cycle in enumerate(CV_O2_cycles):

            epm.add_experiment(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": lpl,
                    "Vapex1_vsRHE": upl,
                    "Vapex2_vsRHE": lpl,
                    "Vfinal_vsRHE": lpl,
                    "scanrate_voltsec": testing_CV_scanrate_voltsec,
                    "SampleRate": testing_CV_samplerate_sec,                    
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                },
            )

            if aliquote_CV_O2[i] == 1:
                
                washmod += 1
                washone = washmod %4 %3 %2
                washtwo = (washmod + 1) %4 %3 %2
                washthree = (washmod + 2) %4 %3 %2
                washfour = (washmod + 3) %4 %3 %2

                epm.add_experiment(
                    "ADSS_sub_sample_aliquot",
                    {
                        "aliquot_volume_ul": aliquot_volume_ul,
                        "EquilibrationTime_s": 0,
                        "PAL_Injector": PAL_Injector,
                        "PAL_Injector_id": PAL_Injector_id,
                        "rinse_1": washone,
                        "rinse_2": washtwo,
                        "rinse_3": washthree,
                        "rinse_4": washfour,
                    }
                )

        #switch from O2 to N2 and saturate
        epm.add_experiment("ADSS_sub_gasvalve_N2flow",{"open": True,})
        #measure OCP (default of OCV exp is to not take any aliquots)
        epm.add_experiment("ADSS_sub_OCV", 
                           {
                               "Tval__s": purge_wait_O2_to_N2_min * 60,
                               "samplerate_sec": OCP_samplerate_sec,
                               "gamry_i_range": gamry_i_range,
                               "ph": ph,
                               "ref_type": ref_type,
                               "ref_offset__V": ref_offset__V,
                               "aliquot_insitu": False,
                           })
        
        # epm.add_experiment(
        #     "orch_sub_wait",
        #     {
        #         "wait_time_s": purge_wait_O2_to_N2_m * 60,
        #     }
        # )
        
        #start background CVs in N2 with phosphoric acid
        for i, CV_cycle in enumerate(CV_N2_cycles):
            epm.add_experiment(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": lpl,
                    "Vapex1_vsRHE": upl,
                    "Vapex2_vsRHE": lpl,
                    "Vfinal_vsRHE": lpl,
                    "scanrate_voltsec": testing_CV_scanrate_voltsec,
                    "SampleRate": testing_CV_scanrate_voltsec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                }
            )
            
            if aliquote_CV_final[i] == 1:
                
                washmod += 1
                washone = washmod %4 %3 %2
                washtwo = (washmod + 1) %4 %3 %2
                washthree = (washmod + 2) %4 %3 %2
                washfour = (washmod + 3) %4 %3 %2

                epm.add_experiment(
                    "ADSS_sub_sample_aliquot",
                    {
                        "aliquot_volume_ul": aliquot_volume_ul,
                        "EquilibrationTime_s": 0,
                        "PAL_Injector": PAL_Injector,
                        "PAL_Injector_id": PAL_Injector_id,
                        "rinse_1": washone,
                        "rinse_2": washtwo,
                        "rinse_3": washthree,
                        "rinse_4": washfour,
                    }
                )

        if keep_electrolyte_at_end:
            epm.add_experiment("ADSS_sub_unload_solid",{})

        else:

            epm.add_experiment("ADSS_sub_unloadall_customs",{})
            epm.add_experiment(
                "ADSS_sub_drain_cell",
                {
                    "DrainWait_s": cell_draintime_sec,
                    "ReturnLineReverseWait_s": ReturnLineReverseWait_sec,
                #    "ResidualWait_s": ResidualWait_s,
                }
            )

        if move_to_clean_and_clean:
            epm.add_experiment("ADSS_sub_move_to_clean_cell", {})
            for i in range(number_of_cleans):
                epm.add_experiment("ADSS_sub_clean_cell",
                                {
                                    "Clean_volume_ul": clean_volume_ul,
                                    "ReturnLineWait_s": clean_recirculate_sec,
                                    "DrainWait_s": clean_drain_sec,
                                }
                            )
                #if working with more than 10mL cleaning V, then by default a precleaning with 6mL is done. This would also be needed to refill
                if clean_volume_ul > 10000:
                    volume = 6000 + clean_volume_ul
                else:
                    volume = clean_volume_ul

                epm.add_experiment("ADSS_sub_refill_syringe", {
                    "syringe": "waterclean",
                    "fill_volume_ul": volume,
                    "Syringe_rate_ulsec": 300,
                    }
                )

###################################################################
#REF MEASUREMENT AT END OF SEQUENCE
###################################################################

    #ref measurement at end of sequence
    if measure_ref_Pt_at_end:
        epm.add_experiment(
            "ADSS_sub_move_to_ref_measurement",
            {
                "reference_position_name": name_ref_Pt_at_end,
            }
        )

        epm.add_experiment(
            "ADSS_sub_load",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id_ref_Pt,
                "solid_sample_no": 1,################### can i use the sample id for all ref measurements?
                "previous_liquid": use_current_electrolyte,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,            
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            }
        )

        #rinse with electrolyte to remove cleaning liquid residuals
        if rinse_with_electrolyte_bf_prefill:
            epm.add_experiment(
                "ADSS_sub_cellfill_prefilled",
                {
                    "Solution_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                    "Syringe_rate_ulsec": Syringe_rate_ulsec,
                }
            )
            epm.add_experiment(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "forward",
                    "wait_time_s": rinse_with_electrolyte_bf_prefill_recirculate_wait_time_sec,
                }
            )
            epm.add_experiment(
                "ADSS_sub_drain_cell",
                {
                    "DrainWait_s": rinse_with_electrolyte_bf_prefill_drain_time_sec,
                    "ReturnLineReverseWait_s": 5,
                #    "ResidualWait_s": ResidualWait_s,
                }
            )
            epm.add_experiment("ADSS_sub_refill_syringe", {
                "syringe": "electrolyte",
                "fill_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
                }
            )

        #electrolyte filling for experiment
        epm.add_experiment(
            "ADSS_sub_cellfill_prefilled",
            {
                "Solution_volume_ul": liquid_sample_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
            }
        )

        #set initial gas to N2
        epm.add_experiment("ADSS_sub_gasvalve_N2flow",{"open": True,})

        # pump recirculate forward
        epm.add_experiment(
            "ADSS_sub_recirculate",
            {
                "direction_forward_or_reverse": "forward",
                "wait_time_s": fill_recirculate_wait_time_sec,
            }
        )
        
        # pump recirculate reverse (for bubbles)
        if pump_reversal_during_filling:
            epm.add_experiment(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "reverse",
                    "wait_time_s": fill_recirculate_reverse_wait_time_sec,
                })
        
            # pump recirculate forward
            epm.add_experiment(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "forward",
                    "wait_time_s": 5,
                }
            )

        #refill electrolyte syringe here so that ADSS can recirculate and N2 saturate while filling syringe
        if not use_current_electrolyte:
            epm.add_experiment("ADSS_sub_refill_syringe", {
                "syringe": "electrolyte",
                "fill_volume_ul": liquid_sample_volume_ul,
                "Syringe_rate_ulsec": 300,
                }
            )       

        #check for bubbles that could interfere with echem measurments with OCV
        if use_bubble_removal:
            epm.add_experiment("ADSS_sub_OCV",
                               {
                                "check_bubble": True,
                                "Tval__s": bubble_removal_OCV_t_s,
                                "samplerate_sec": 0.1,
                                "gamry_i_range": gamry_i_range,
                                "ph": ph,
                                "ref_type": ref_type,
                                "ref_offset__V": ref_offset__V,
                                "aliquot_insitu": False,
                                "run_use": "ref",
                                "RSD_threshold": bubble_removal_RSD_threshold,
                                "simple_threshold": bubble_removal_simple_threshold,
                                "signal_change_threshold": bubble_removal_signal_change_threshold,
                                "amplitude_threshold": bubble_removal_amplitude_threshold,
                                "bubble_pump_reverse_time_s": bubble_removal_pump_reverse_t_s,
                                "bubble_pump_forward_time_s": bubble_removal_pump_forward_t_s,
                                })

        #saturate electrolyte with N2
        epm.add_experiment("ADSS_sub_OCV", 
                    {
                        "Tval__s": purge_wait_initialN2_min * 60,
                        "samplerate_sec": OCP_samplerate_sec,
                        "gamry_i_range": gamry_i_range,
                        "ph": ph,
                        "ref_type": ref_type,
                        "ref_offset__V": ref_offset__V,
                        "aliquot_insitu": False,
                        "run_use": "ref"
                    })
        
        # epm.add_experiment(
        #     "orch_sub_wait",
        #     {
        #         "wait_time_s": purge_wait_initialN2_min * 60,
        #     }
        # )
        
        #start cleaning CVs in N2
        for i, CV_cycle in enumerate(cleaning_CV_cycles):
            epm.add_experiment(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": cleaning_Vinit_vsRHE[i],
                    "Vapex1_vsRHE": cleaning_Vapex1_vsRHE[i],
                    "Vapex2_vsRHE": cleaning_Vapex2_vsRHE[i],
                    "Vfinal_vsRHE": cleaning_Vfinal_vsRHE[i],
                    "scanrate_voltsec": cleaning_scanrate_voltsec[i],
                    "SampleRate": cleaning_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "run_use": "ref"
                }
            )
            
        #start background CVs in N2
        for i, CV_cycle in enumerate(ref_CV_cycles):
            epm.add_experiment(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": ref_Vinit_vsRHE,
                    "Vapex1_vsRHE": ref_Vapex1_vsRHE,
                    "Vapex2_vsRHE": ref_Vapex2_vsRHE,
                    "Vfinal_vsRHE": ref_Vfinal_vsRHE,
                    "scanrate_voltsec": ref_CV_scanrate_voltsec,
                    "SampleRate": ref_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "run_use": "ref"
                }
            )
        
        #switch from N2 to O2 and saturate
        epm.add_experiment("ADSS_sub_gasvalve_N2flow",{"open": False,})
        epm.add_experiment("ADSS_sub_OCV", 
                           {
                               "Tval__s": purge_wait_N2_to_O2_min * 60,
                               "samplerate_sec": OCP_samplerate_sec,
                               "gamry_i_range": gamry_i_range,
                               "ph": ph,
                               "ref_type": ref_type,
                               "ref_offset__V": ref_offset__V,
                               "aliquot_insitu": False,
                               "run_use": "ref"
                           })        
#        epm.add_experiment(
#            "orch_sub_wait",
#            {
#                "wait_time_s": purge_wait_N2_to_O2_min * 60,
#            }
#        )

        #start O2 cycles
        for i, CV_cycle in enumerate(ref_CV_cycles):
            epm.add_experiment(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": ref_Vinit_vsRHE,
                    "Vapex1_vsRHE": ref_Vapex1_vsRHE,
                    "Vapex2_vsRHE": ref_Vapex2_vsRHE,
                    "Vfinal_vsRHE": ref_Vfinal_vsRHE,
                    "scanrate_voltsec": ref_CV_scanrate_voltsec,
                    "SampleRate": ref_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "run_use": "ref"
                }
            )
        
        #switch from O2 to N2 and saturate
        epm.add_experiment("ADSS_sub_gasvalve_N2flow",{"open": True,})

        #unload sample
        epm.add_experiment("ADSS_sub_unloadall_customs",{})
        
        #drain cell
        epm.add_experiment(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": cell_draintime_sec,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_sec,
            #    "ResidualWait_s": ResidualWait_s,
            }
        )

        #clean cell
        if move_to_clean_and_clean:
            epm.add_experiment("ADSS_sub_move_to_clean_cell", {})
            for i in range(number_of_cleans):
                epm.add_experiment("ADSS_sub_clean_cell",
                                {
                                    "Clean_volume_ul": clean_volume_ul,
                                    "ReturnLineWait_s": clean_recirculate_sec,
                                    "DrainWait_s": clean_drain_sec,
                                }
                            )
                #if working with more than 10mL cleaning V, then by default a precleaning with 6mL is done. This would also be needed to refill
                if clean_volume_ul > 10000:
                    volume = 6000 + clean_volume_ul
                else:
                    volume = clean_volume_ul

                epm.add_experiment("ADSS_sub_refill_syringe", {
                    "syringe": "waterclean",
                    "fill_volume_ul": volume,
                    "Syringe_rate_ulsec": 300,
                    }
                )       

    return epm.experiment_plan_list  # returns complete experiment list


def ADSS_PA_CV_TRI_new(
    sequence_version: int = 8, #8 pal deepclean and empty vial xfer #6 new transfer syringe#5 shift aliquots to expts, bubble removal
    #note: str = "need as many samples as you expect combinations of UPL and LPL",
    
    #sample info
    #solid_custom_position: str = "cell1_we",
    plate_id: int = 6307,
    plate_id_ref_Pt: int = 6173,
    plate_sample_no_list: List[int] = [16304],  #  need as many samples as you expect combinations of UPL and LPL
    LPL_list: List[float] = [0.05, 0.55, 0.05, 0.55,],
    UPL_list: List[float] = [1.3, 0.8, 1.3, 0.8,],

    #side info
    same_sample: bool = False,
    aliquot_init: bool = True,
    Inject_PA: bool= True,
    use_bubble_removal: bool = True,
    rinse_with_electrolyte_bf_prefill: bool = True,
    use_current_electrolyte: bool = False,
    pump_reversal_during_filling: bool = False,
    keep_electrolyte_at_end: bool = False,
    move_to_clean_and_clean: bool = True,
    measure_ref_Pt_at_beginning: bool = True,
    name_ref_Pt_at_beginning: str = "builtin_ref_motorxy_2",
    measure_ref_Pt_at_end: bool = True,
    name_ref_Pt_at_end: str = "builtin_ref_motorxy_3",
    
    #bubble removal OCV
    bubble_removal_OCV_t_s: int = 10,
    bubble_removal_pump_reverse_t_s: int = 15,
    bubble_removal_pump_forward_t_s: int = 10,
    bubble_removal_RSD_threshold: float = 0.2,
    bubble_removal_simple_threshold: float = 0.3,
    bubble_removal_signal_change_threshold: float = 0.01,
    bubble_removal_amplitude_threshold: float = 0.05,

    #purge wait times
    purge_wait_initialN2_min: int = 10,
    purge_wait_N2_to_O2_min: int = 5,
    purge_wait_O2_to_N2_min: int = 15,

    #electrolyte info
    rinse_with_electrolyte_bf_prefill_volume_uL: float = 3000,
    rinse_with_electrolyte_bf_prefill_recirculate_wait_time_sec: float = 30,
    rinse_with_electrolyte_bf_prefill_drain_time_sec: float = 30,
    ph: float = 1.24,
    liquid_sample_no: int = 1053,
    liquid_sample_volume_ul: float = 7000,
    Syringe_rate_ulsec: float = 300,
    fill_recirculate_wait_time_sec: float = 30,    
    fill_recirculate_reverse_wait_time_sec: float = 15,
    
    #phosphoric acid injection info
    phosphoric_sample_no: int = 1261,
    phosphoric_location: List[int] = [2,3,54],
    phosphoric_quantity_ul: int = 90,
    inject_recirculate_wait_time_sec: float = 60,
    #liquid_custom_position: str = "elec_res1",
    phos_PAL_Injector: str = "LS 5",
    phos_PAL_Injector_id: str = "LS5_peek",
    PAL_cleanvol_ul: int = 500,

    #Ref Pt measurement CVs
    ref_CV_cycles: List[int] = [8],
    ref_Vinit_vsRHE: List[float] = [0.05],  # Initial value in volts or amps.
    ref_Vapex1_vsRHE: List[float] = [1.3],  # Apex 1 value in volts or amps.
    ref_Vapex2_vsRHE: List[float] = [0.05],  # Apex 2 value in volts or amps.
    ref_Vfinal_vsRHE: List[float] = [0.05],  # Final value in volts or amps.
    ref_CV_scanrate_voltsec: List[float] = [0.1],  # scan rate in volts/second or amps/second.
    ref_CV_samplerate_sec: float = 0.01,

    #cleaning CVs 
    cleaning_CV_cycles: List[int] = [20],
    cleaning_Vinit_vsRHE: List[float] = [0.05],  # Initial value in volts or amps.
    cleaning_Vapex1_vsRHE: List[float] = [1.5],  # Apex 1 value in volts or amps.
    cleaning_Vapex2_vsRHE: List[float] = [0.05],  # Apex 2 value in volts or amps.
    cleaning_Vfinal_vsRHE: List[float] = [0.05],  # Final value in volts or amps.
    cleaning_scanrate_voltsec: List[float] = [0.2],  # scan rate in volts/second or amps/second.
    cleaning_CV_samplerate_sec: float = 0.02,

    #testing CV info
    testing_CV_scanrate_voltsec: float= 0.1,
    testing_CV_samplerate_sec: float = 0.01,

    #CVs in N2 for background
    CV_N2_cycles: List[int] = [5],
    #CV_N2_Vinit_vsRHE: List[float] = [1.23, 1.23, 1.23],  # Initial value in volts or amps.
    #CV_N2_Vapex1_vsRHE: List[float] = [1.23, 1.23, 1.23],  # Apex 1 value in volts or amps.
    #CV_N2_Vapex2_vsRHE: List[float] = [0.6, 0.4, 0],  # Apex 2 value in volts or amps.
    #CV_N2_Vfinal_vsRHE: List[float] = [0.6, 0.4, 0],  # Final value in volts or amps.
    #CV_N2_scanrate_voltsec: List[float] = [0.02,0.02,0.02],  # scan rate in volts/second or amps/second.
    #CV_N2_samplerate_sec: float = 0.05,

    #CVs in O2 and with and without PA
    CV_O2_cycles: List[int] = [5,25,50],
    #CV_O2_Vinit_vsRHE: List[float] = [1.23, 1.23, 1.23],  # Initial value in volts or amps.
    #CV_O2_Vapex1_vsRHE: List[float] = [1.23, 1.23, 1.23],  # Apex 1 value in volts or amps.
    #CV_O2_Vapex2_vsRHE: List[float] = [0.6, 0.4, 0],  # Apex 2 value in volts or amps.
    #CV_O2_Vfinal_vsRHE: List[float] = [0.6, 0.4, 0],  # Final value in volts or amps.
    #CV_O2_scanrate_voltsec: List[float] = [0.02,0.02,0.02],  # scan rate in volts/second or amps/second.
    #CV_O2_samplerate_sec: float = 0.05,

    #OCP info
    OCP_samplerate_sec: float = 0.5,

    #Pstat and ref info
    gamry_i_range: str = "auto",
    ref_type: str = "leakless",
    ref_offset__V: float = -0.005,
    
    #aliquote info
    aliquot_after_cleaningCV: List[int] = [0],
    aliquote_after_CV_init: List[int] = [1],
    aliquote_CV_O2: List[int] = [1,1,1],
    aliquote_CV_final: List[int] = [0],
    aliquot_volume_ul: int = 100,
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "LS4_peek",
    
    #cell drain info
    cell_draintime_sec: float = 60,
    ReturnLineReverseWait_sec: float = 5,
    
    #cell clean info
    number_of_cleans: int = 2,
    clean_volume_ul: float = 12000,
    clean_recirculate_sec: float = 60,
    clean_drain_sec: float = 120,
    # ResidualWait_s: float = 15,
    # flush_volume_ul: float = 2000,
    # clean: bool = False,
    # clean_volume_ul: float = 5000,
    # refill: bool = False,
    # refill_volume_ul: float = 6000,
    # water_refill_volume_ul: float = 6000,

):

    """
    This sequence is the most recent one for the TRI Pt dissolution project using ADSS.
    Included features:
    - scheduled aliquotes and injection of phosphoric acid
    - track gas saturation with OCV during N2-O2 and O2-N2 switches
    - automatic refill of syringes
    - you can define number of cleaning cycles (to make sure we are cleaning off Co and Ni residues)
    - include reference Pt measurements before and after sequence
    - generating sample-LPL-UPL combinations
    - bubble removal using OCV. bubble removal = reversal of pumps for some seconds 

    """

    epm = ExperimentPlanMaker()


    if rinse_with_electrolyte_bf_prefill:
        epm.add_experiment("ADSS_sub_move_to_clean_cell", {})
        epm.add_experiment(
            "ADSS_sub_cellfill_prefilled_nosampleload",
            {
                "Solution_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
            }
        )
        epm.add_experiment(
            "ADSS_sub_recirculate",
            {
                "direction_forward_or_reverse": "forward",
                "wait_time_s": rinse_with_electrolyte_bf_prefill_recirculate_wait_time_sec,
            }
        )
        epm.add_experiment(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": rinse_with_electrolyte_bf_prefill_drain_time_sec,
                "ReturnLineReverseWait_s": 5,
            #    "ResidualWait_s": ResidualWait_s,
            }
        )
        epm.add_experiment("ADSS_sub_refill_syringe", {
            "syringe": "electrolyte",
            "fill_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
            "Syringe_rate_ulsec": Syringe_rate_ulsec,
            }
        )  

###################################################################
#REF MEASUREMENT AT BEGINNING OF SEQUENCE
###################################################################

    #ref measurement at beginning of sequence
    if measure_ref_Pt_at_beginning:
        epm.add_experiment(
            "ADSS_sub_move_to_ref_measurement",
            {
                "reference_position_name": name_ref_Pt_at_beginning
            }
        )

        epm.add_experiment(
            "ADSS_sub_load",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id_ref_Pt,
                "solid_sample_no": 1,################### can i use the sample id for all ref measurements?
                "previous_liquid": use_current_electrolyte,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            }
        )   


        #electrolyte filling for experiment
        epm.add_experiment(
            "ADSS_sub_cellfill_prefilled",
            {
                "Solution_volume_ul": liquid_sample_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
            }
        )

        #set initial gas to N2
        epm.add_experiment("ADSS_sub_gasvalve_N2flow",{"open": True,})
        epm.add_experiment("ADSS_sub_PAL_load_gas",{"bubbled_gas": "N2","reservoir_gas_sample_no":1,})

        # pump recirculate forward
        epm.add_experiment(
            "ADSS_sub_recirculate",
            {
                "direction_forward_or_reverse": "forward",
                "wait_time_s": fill_recirculate_wait_time_sec,
            }
        )
        
        # pump recirculate reverse (for bubbles)
        if pump_reversal_during_filling:
            epm.add_experiment(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "reverse",
                    "wait_time_s": fill_recirculate_reverse_wait_time_sec,
                })
        
            # pump recirculate forward
            epm.add_experiment(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "forward",
                    "wait_time_s": 5,
                }
            )

        #refill electrolyte syringe here so that ADSS can recirculate and N2 saturate while filling syringe
        if not use_current_electrolyte:
            epm.add_experiment("ADSS_sub_refill_syringe", {
                "syringe": "electrolyte",
                "fill_volume_ul": liquid_sample_volume_ul,
                "Syringe_rate_ulsec": 300,
                }
            )

        #check for bubbles that could interfere with echem measurments with OCV
        if use_bubble_removal:
            epm.add_experiment("ADSS_sub_OCV",
                               {
                                "check_bubble": True,
                                "Tval__s": bubble_removal_OCV_t_s,
                                "samplerate_sec": 0.1,
                                "gamry_i_range": gamry_i_range,
                                "ph": ph,
                                "ref_type": ref_type,
                                "ref_offset__V": ref_offset__V,
                                "aliquot_insitu": False,
                                "bubbler_gas": "N2",
                                "run_use": "ref",
                                "RSD_threshold": bubble_removal_RSD_threshold,
                                "simple_threshold": bubble_removal_simple_threshold,
                                "signal_change_threshold": bubble_removal_signal_change_threshold,
                                "amplitude_threshold": bubble_removal_amplitude_threshold,
                                "bubble_pump_reverse_time_s": bubble_removal_pump_reverse_t_s,
                                "bubble_pump_forward_time_s": bubble_removal_pump_forward_t_s,
                                })

        #saturate electrolyte with N2 and measure OCV while saturation
        epm.add_experiment("ADSS_sub_OCV", 
                           {
                               "Tval__s": purge_wait_initialN2_min * 60,
                               "samplerate_sec": OCP_samplerate_sec,
                               "gamry_i_range": gamry_i_range,
                               "ph": ph,
                               "ref_type": ref_type,
                               "ref_offset__V": ref_offset__V,
                               "aliquot_insitu": False,
                               "bubbler_gas": "N2",
                               "run_use": "ref"
                           })

        # epm.add_experiment(
        #     "orch_sub_wait",
        #     {
        #         "wait_time_s": purge_wait_initialN2_min * 60,
        #     }
        # )
        
        #start cleaning CVs in N2
        for i, CV_cycle in enumerate(cleaning_CV_cycles):
            epm.add_experiment(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": cleaning_Vinit_vsRHE[i],
                    "Vapex1_vsRHE": cleaning_Vapex1_vsRHE[i],
                    "Vapex2_vsRHE": cleaning_Vapex2_vsRHE[i],
                    "Vfinal_vsRHE": cleaning_Vfinal_vsRHE[i],
                    "scanrate_voltsec": cleaning_scanrate_voltsec[i],
                    "SampleRate": cleaning_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "bubbler_gas": "N2",
                    "run_use": "ref"
                }
            )
            
        #start background CVs in N2
        for i, CV_cycle in enumerate(ref_CV_cycles):
            epm.add_experiment(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": ref_Vinit_vsRHE,
                    "Vapex1_vsRHE": ref_Vapex1_vsRHE,
                    "Vapex2_vsRHE": ref_Vapex2_vsRHE,
                    "Vfinal_vsRHE": ref_Vfinal_vsRHE,
                    "scanrate_voltsec": ref_CV_scanrate_voltsec,
                    "SampleRate": ref_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "bubbler_gas": "N2",
                    "run_use": "ref"
                }
            )
        
        #switch from N2 to O2 and saturate
        epm.add_experiment("ADSS_sub_gasvalve_N2flow",{"open": False,})
    #need to remove N2 gas sample
        epm.add_experiment("ADSS_sub_unload_gas_only",{})
    #test need
        epm.add_experiment("ADSS_sub_PAL_load_gas",{"bubbled_gas": "O2","reservoir_gas_sample_no":2,})
        epm.add_experiment("ADSS_sub_OCV", 
                    {
                        "Tval__s": purge_wait_N2_to_O2_min * 60,
                        "samplerate_sec": OCP_samplerate_sec,
                        "gamry_i_range": gamry_i_range,
                        "ph": ph,
                        "ref_type": ref_type,
                        "ref_offset__V": ref_offset__V,
                        "aliquot_insitu": False,
                        "bubbler_gas": "O2",
                        "run_use": "ref"
                    })
#        epm.add_experiment(
#            "orch_sub_wait",
#            {
#                "wait_time_s": purge_wait_N2_to_O2_min * 60,
#            }
#        )

        #start O2 cycles
        for i, CV_cycle in enumerate(ref_CV_cycles):
            epm.add_experiment(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": ref_Vinit_vsRHE,
                    "Vapex1_vsRHE": ref_Vapex1_vsRHE,
                    "Vapex2_vsRHE": ref_Vapex2_vsRHE,
                    "Vfinal_vsRHE": ref_Vfinal_vsRHE,
                    "scanrate_voltsec": ref_CV_scanrate_voltsec,
                    "SampleRate": ref_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "bubbler_gas": "O2",
                    "run_use": "ref"
                }
            )
        
        #switch from O2 to N2 and saturate
        epm.add_experiment("ADSS_sub_gasvalve_N2flow",{"open": True,})
    #need to remove O2 gas sample
        epm.add_experiment("ADSS_sub_unload_gas_only",{})
    #test need
        epm.add_experiment("ADSS_sub_PAL_load_gas",{"bubbled_gas": "N2","reservoir_gas_sample_no":1,})

        #unload sample
        epm.add_experiment("ADSS_sub_unloadall_customs",{})
        
        #drain cell
        epm.add_experiment(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": cell_draintime_sec,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_sec,
            #    "ResidualWait_s": ResidualWait_s,
            }
        )

        #clean cell
        if move_to_clean_and_clean:
            epm.add_experiment("ADSS_sub_move_to_clean_cell", {})
            for i in range(number_of_cleans):
                epm.add_experiment("ADSS_sub_clean_cell",
                                {
                                    "Clean_volume_ul": clean_volume_ul,
                                    "ReturnLineWait_s": clean_recirculate_sec,
                                    "DrainWait_s": clean_drain_sec,
                                }
                            )
                #if working with more than 10mL cleaning V, then by default a precleaning with 6mL is done. This would also be needed to refill
                if clean_volume_ul > 10000:
                    volume = 6000 + clean_volume_ul
                else:
                    volume = clean_volume_ul

                epm.add_experiment("ADSS_sub_refill_syringe", {
                    "syringe": "waterclean",
                    "fill_volume_ul": volume,
                    "Syringe_rate_ulsec": 300,
                    }
                )

            #rinse with electrolyte to remove cleaning liquid residuals
            if rinse_with_electrolyte_bf_prefill:
                epm.add_experiment(
                    "ADSS_sub_cellfill_prefilled_nosampleload",
                    {
                        "Solution_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                        "Syringe_rate_ulsec": Syringe_rate_ulsec,
                    }
                )
                epm.add_experiment(
                    "ADSS_sub_recirculate",
                    {
                        "direction_forward_or_reverse": "forward",
                        "wait_time_s": rinse_with_electrolyte_bf_prefill_recirculate_wait_time_sec,
                    }
                )
                epm.add_experiment(
                    "ADSS_sub_drain_cell",
                    {
                        "DrainWait_s": rinse_with_electrolyte_bf_prefill_drain_time_sec,
                        "ReturnLineReverseWait_s": 5,
                    #    "ResidualWait_s": ResidualWait_s,
                    }
                )
                epm.add_experiment("ADSS_sub_refill_syringe", {
                    "syringe": "electrolyte",
                    "fill_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                    "Syringe_rate_ulsec": Syringe_rate_ulsec,
                    }
                )

###################################################################
#SEQUENCE FOR ACTUAL SAMPLE
###################################################################

    #for solid_sample_no in plate_sample_no_list:  # have to indent add expts if used
 
    washmod = 0

    for lpl, upl, sample_no in zip(LPL_list, UPL_list, plate_sample_no_list):
        print("##########################################################\n" +
                "Current LPL is {} Vrhe\n".format(lpl) + 
                "Current UPL is {} Vrhe\n".format(upl) + 
                "Current Sample is {}\n".format(sample_no) + 
                "##########################################################")

        if not same_sample:
            
            epm.add_experiment(
                "ADSS_sub_move_to_sample",
                {
                    "solid_custom_position": "cell1_we",
                    "solid_plate_id": plate_id,
                    "solid_sample_no": sample_no,
                    "liquid_custom_position": "cell1_we",
                    "liquid_sample_no": liquid_sample_no,
                    "liquid_sample_volume_ul": liquid_sample_volume_ul,
                }
            )

        epm.add_experiment(
            "ADSS_sub_load",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": sample_no,
                "previous_liquid": use_current_electrolyte,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,            
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            }
        )

        #electrolyte filling for experiment
        if not use_current_electrolyte:
            epm.add_experiment(
                "ADSS_sub_cellfill_prefilled",
                {
                    "Solution_volume_ul": liquid_sample_volume_ul,
                    "Syringe_rate_ulsec": Syringe_rate_ulsec,
                }
            )
            previous_liquid_injected = ""

        #set initial gas to N2
        epm.add_experiment("ADSS_sub_gasvalve_N2flow",{"open": True,})
        epm.add_experiment("ADSS_sub_PAL_load_gas",{"bubbled_gas": "N2","reservoir_gas_sample_no":1,})

        # pump recirculate forward
        epm.add_experiment(
            "ADSS_sub_recirculate",
            {
                "direction_forward_or_reverse": "forward",
                "wait_time_s": fill_recirculate_wait_time_sec,
            }
        )
        
        # pump recirculate reverse (for bubbles)
        if pump_reversal_during_filling:
            epm.add_experiment(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "reverse",
                    "wait_time_s": fill_recirculate_reverse_wait_time_sec,
                })
        
            # pump recirculate forward
            epm.add_experiment(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "forward",
                    "wait_time_s": 5,
                }
            )

        #refill electrolyte syringe here so that ADSS can recirculate and N2 saturate while filling syringe
        if not use_current_electrolyte:
            epm.add_experiment("ADSS_sub_refill_syringe", {
                "syringe": "electrolyte",
                "fill_volume_ul": liquid_sample_volume_ul,
                "Syringe_rate_ulsec": 300,
                }
            )

        # washmod = 0

        if aliquot_init: #stops gas purge, takes aliquote, starts gas purge again
            
            washmod += 1
            firstaliquot = True
        else: firstaliquot = False

        #check for bubbles that could interfere with echem measurments with OCV
        if use_bubble_removal:
            epm.add_experiment("ADSS_sub_OCV",
                               {
                                "check_bubble": True,
                                "Tval__s": bubble_removal_OCV_t_s,
                                "samplerate_sec": 0.1,
                                "gamry_i_range": gamry_i_range,
                                "ph": ph,
                                "ref_type": ref_type,
                                "ref_offset__V": ref_offset__V,
                                "aliquot_insitu": False,
                                "RSD_threshold": bubble_removal_RSD_threshold,
                                "simple_threshold": bubble_removal_simple_threshold,
                                "signal_change_threshold": bubble_removal_signal_change_threshold,
                                "amplitude_threshold": bubble_removal_amplitude_threshold,
                                "bubble_pump_reverse_time_s": bubble_removal_pump_reverse_t_s,
                                "bubble_pump_forward_time_s": bubble_removal_pump_forward_t_s,
                                "bubbler_gas": "N2",
                                })

        #saturate electrolyte with N2
        epm.add_experiment("ADSS_sub_OCV", 
                    {
                        "Tval__s": purge_wait_initialN2_min * 60,
                        "samplerate_sec": OCP_samplerate_sec,
                        "gamry_i_range": gamry_i_range,
                        "ph": ph,
                        "ref_type": ref_type,
                        "ref_offset__V": ref_offset__V,
                        "aliquot_insitu": False,
                        "PAL_Injector":PAL_Injector,
                        "PAL_Injector_id":PAL_Injector_id,
                        "aliquot_pre": firstaliquot,
                        "aliquot_volume_ul": aliquot_volume_ul,
                        "washmod_in": washmod,
                        "bubbler_gas": "N2",                        
                    })
        
        # epm.add_experiment(
        #     "orch_sub_wait",
        #     {
        #         "wait_time_s": purge_wait_initialN2_min * 60,
        #     }
        # )
        
        #start cleaning CVs in N2
        for i, CV_cycle in enumerate(cleaning_CV_cycles):

            if aliquot_after_cleaningCV[i] == 1:
                washmod += 1
                postaliquot = True
            else: postaliquot = False

            epm.add_experiment(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": cleaning_Vinit_vsRHE[i],
                    "Vapex1_vsRHE": cleaning_Vapex1_vsRHE[i],
                    "Vapex2_vsRHE": cleaning_Vapex2_vsRHE[i],
                    "Vfinal_vsRHE": cleaning_Vfinal_vsRHE[i],
                    "scanrate_voltsec": cleaning_scanrate_voltsec[i],
                    "SampleRate": cleaning_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "PAL_Injector":PAL_Injector,
                    "PAL_Injector_id":PAL_Injector_id,
                    "aliquot_post": postaliquot,
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "washmod_in": washmod,
                    "bubbler_gas": "N2",
                },
            )

        #start background CVs in N2
        for i, CV_cycle in enumerate(CV_N2_cycles):

            if aliquote_after_CV_init[i] == 1:
                washmod += 1
                postaliquot = True
            else: postaliquot = False

            epm.add_experiment(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": lpl,
                    "Vapex1_vsRHE": upl,
                    "Vapex2_vsRHE": lpl,
                    "Vfinal_vsRHE": lpl,
                    "scanrate_voltsec": testing_CV_scanrate_voltsec,
                    "SampleRate": testing_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "PAL_Injector":PAL_Injector,
                    "PAL_Injector_id":PAL_Injector_id,
                    "aliquot_post": postaliquot,
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "washmod_in": washmod,
                    "bubbler_gas": "N2",
                }
            )
        
        #switch from N2 to O2 and saturate
        epm.add_experiment("ADSS_sub_gasvalve_N2flow",{"open": False,})
    #need to remove N2 gas sample
        epm.add_experiment("ADSS_sub_unload_gas_only",{})
    #test need
        epm.add_experiment("ADSS_sub_PAL_load_gas",{"bubbled_gas": "O2","reservoir_gas_sample_no":2,})

        epm.add_experiment("ADSS_sub_OCV", 
                    {
                        "Tval__s": purge_wait_N2_to_O2_min * 60,
                        "samplerate_sec": OCP_samplerate_sec,
                        "gamry_i_range": gamry_i_range,
                        "ph": ph,
                        "ref_type": ref_type,
                        "ref_offset__V": ref_offset__V,
                        "aliquot_insitu": False,
                        "bubbler_gas": "O2",
                    })        
        
        # epm.add_experiment(
        #     "orch_sub_wait",
        #     {
        #         "wait_time_s": purge_wait_N2_to_O2_min * 60,
        #     }
        # )

        #start O2 cycles
        for i, CV_cycle in enumerate(CV_O2_cycles):

            if aliquote_CV_O2[i] == 1:
                washmod += 1
                postaliquot = True
            else: postaliquot = False

            epm.add_experiment(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": lpl,
                    "Vapex1_vsRHE": upl,
                    "Vapex2_vsRHE": lpl,
                    "Vfinal_vsRHE": lpl,
                    "scanrate_voltsec": testing_CV_scanrate_voltsec,
                    "SampleRate": testing_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "PAL_Injector":PAL_Injector,
                    "PAL_Injector_id":PAL_Injector_id,
                    "aliquot_post": postaliquot,
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "washmod_in": washmod,
           ####             "EquilibrationTime_s": 0,
                    "bubbler_gas": "O2",
                }
            )

        #inject phosphoric acid
        if Inject_PA:
################################# temporary manual injection of phos
            epm.add_experiment(
                "ADSS_sub_load_liquid_only",
                {
                    "liquid_sample_no": phosphoric_sample_no,
                    "liquid_custom_position": "cell1_we",
                    "liquid_sample_volume_ul": phosphoric_quantity_ul,
                    "combine_liquids": True,
                }
            )

            epm.add_experiment(
                "ADSS_sub_interrupt",
                {
                    "reason": "Manual injection of phosphoric",
                }
            )



############################ actual syringe injection
        #     previous_liquid_injected = "phosphoric"
        #     washmod += 1
        #     washone = washmod %4 %3 %2
        #     washtwo = (washmod + 1) %4 %3 %2
        #     washthree = (washmod + 2) %4 %3 %2
        #     washfour = (washmod + 3) %4 %3 %2

        #     epm.add_experiment(
        #     "ADSS_sub_transfer_liquid_in",
        #     {
        #         "destination": "cell1_we",
        #         "source_tray": phosphoric_location[0],
        #         "source_slot": phosphoric_location[1],
        #         "source_vial": phosphoric_location[2],            
        #         "liquid_sample_no": phosphoric_sample_no,
        #         "aliquot_volume_ul": phosphoric_quantity_ul,
        #         "PAL_Injector": phos_PAL_Injector,
        #         "PAL_Injector_id": phos_PAL_Injector_id,
        #         "rinse_1": washone,
        #         "rinse_2": washtwo,
        #         "rinse_3": washthree,
        #         "rinse_4": washfour,
        #     }
        # )
###################################
            #recirculate to mix PA into electrolyte
            epm.add_experiment(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "forward",
                    "wait_time_s": inject_recirculate_wait_time_sec,
                }
            )
        else:
            previous_liquid_injected = ""

        #start O2 cycles with PA
        for i, CV_cycle in enumerate(CV_O2_cycles):

            if aliquote_CV_O2[i] == 1:
                washmod += 1
                postaliquot = True
            else: postaliquot = False

            epm.add_experiment(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": lpl,
                    "Vapex1_vsRHE": upl,
                    "Vapex2_vsRHE": lpl,
                    "Vfinal_vsRHE": lpl,
                    "scanrate_voltsec": testing_CV_scanrate_voltsec,
                    "SampleRate": testing_CV_samplerate_sec,                    
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "PAL_Injector":PAL_Injector,
                    "PAL_Injector_id":PAL_Injector_id,
                    "aliquot_post": postaliquot,
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "washmod_in": washmod,
           ####             "EquilibrationTime_s": 0,
                    "bubbler_gas": "O2",
                    "previous_liquid_injected": previous_liquid_injected,
                },
            )


        #switch from O2 to N2 and saturate
        epm.add_experiment("ADSS_sub_gasvalve_N2flow",{"open": True,})
    #need to remove O2 gas sample
        epm.add_experiment("ADSS_sub_unload_gas_only",{})
    #test need
        epm.add_experiment("ADSS_sub_PAL_load_gas",{"bubbled_gas": "N2","reservoir_gas_sample_no":1,})

        #measure OCP (default of OCV exp is to not take any aliquots)
        epm.add_experiment("ADSS_sub_OCV", 
                           {
                               "Tval__s": purge_wait_O2_to_N2_min * 60,
                               "samplerate_sec": OCP_samplerate_sec,
                               "gamry_i_range": gamry_i_range,
                               "ph": ph,
                               "ref_type": ref_type,
                               "ref_offset__V": ref_offset__V,
                               "aliquot_insitu": False,
                               "bubbler_gas": "N2",
                               "previous_liquid_injected": previous_liquid_injected,
                           })
        
        # epm.add_experiment(
        #     "orch_sub_wait",
        #     {
        #         "wait_time_s": purge_wait_O2_to_N2_m * 60,
        #     }
        # )
        
        #start background CVs in N2 with phosphoric acid
        for i, CV_cycle in enumerate(CV_N2_cycles):

            if aliquote_CV_final[i] == 1:
                washmod += 1
                postaliquot = True
            else: postaliquot = False

            epm.add_experiment(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": lpl,
                    "Vapex1_vsRHE": upl,
                    "Vapex2_vsRHE": lpl,
                    "Vfinal_vsRHE": lpl,
                    "scanrate_voltsec": testing_CV_scanrate_voltsec,
                    "SampleRate": testing_CV_scanrate_voltsec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "PAL_Injector":PAL_Injector,
                    "PAL_Injector_id":PAL_Injector_id,
                    "aliquot_post": postaliquot,
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "washmod_in": washmod,
           ####             "EquilibrationTime_s": 0,
                    "bubbler_gas": "N2",
                    "previous_liquid_injected": previous_liquid_injected,
                }
            )
################# extra clean of syringe used for phos injection
        # if Inject_PA:
        #     washmod += 1
        #     #determine last used rinse, then use next two  
        #     remainder = washmod %4
        #     washone, washtwo, washthree, washfour = (0,)*4
        #     if remainder == 0:
        #         washone, washtwo = 1,1
        #     if remainder == 1:
        #         washone, washfour= 1,1
        #     if remainder == 2:
        #         washthree,washfour = 1,1
        #     if remainder ==3:
        #         washtwo, washthree=1,1
        #     washmod += 1

        #     epm.add_experiment(
        #     "ADSS_sub_PAL_deep_clean",
        #     {
        #         "clean_volume_ul": PAL_cleanvol_ul,
        #         "PAL_Injector": phos_PAL_Injector,
        #         "rinse_1": washone,
        #         "rinse_2": washtwo,
        #         "rinse_3": washthree,
        #         "rinse_4": washfour,
        #     }
        # )

        #     washmod += 1
        #     #determine last used rinse, then use next two  
        #     remainder = washmod %4
        #     washone, washtwo, washthree, washfour = (0,)*4
        #     if remainder == 0:
        #         washone, washtwo = 1,1
        #     if remainder == 1:
        #         washone, washfour= 1,1
        #     if remainder == 2:
        #         washthree,washfour = 1,1
        #     if remainder ==3:
        #         washtwo, washthree=1,1
        #     washmod += 1

        #     epm.add_experiment(
        #     "ADSS_sub_PAL_tray_to_tray",  #hard-coded source and destination vials
        #     {
        #         "volume_ul": PAL_cleanvol_ul,
        #         "source_tray": 2,
        #         "source_slot": 3,
        #         "source_vial": 53,
        #         "dest_tray": 2,
        #         "dest_slot": 3,
        #         "dest_vial": 52,
        #         "PAL_Injector": phos_PAL_Injector,
        #         "rinse_1": washone,
        #         "rinse_2": washtwo,
        #         "rinse_3": washthree,
        #         "rinse_4": washfour,
        #     }
        # )
########################

        if keep_electrolyte_at_end:
            epm.add_experiment("ADSS_sub_unload_solid",{})
    #unload gas too?
            epm.add_experiment("ADSS_sub_unload_gas_only",{})
    #test need
        else:

            epm.add_experiment("ADSS_sub_unloadall_customs",{})
            epm.add_experiment(
                "ADSS_sub_drain_cell",
                {
                    "DrainWait_s": cell_draintime_sec,
                    "ReturnLineReverseWait_s": ReturnLineReverseWait_sec,
                #    "ResidualWait_s": ResidualWait_s,
                }
            )

        if move_to_clean_and_clean:
            epm.add_experiment("ADSS_sub_move_to_clean_cell", {})
            for i in range(number_of_cleans):
                epm.add_experiment("ADSS_sub_clean_cell",
                                {
                                    "Clean_volume_ul": clean_volume_ul,
                                    "ReturnLineWait_s": clean_recirculate_sec,
                                    "DrainWait_s": clean_drain_sec,
                                }
                            )
                #if working with more than 10mL cleaning V, then by default a precleaning with 6mL is done. This would also be needed to refill
                if clean_volume_ul > 10000:
                    volume = 6000 + clean_volume_ul
                else:
                    volume = clean_volume_ul

                epm.add_experiment("ADSS_sub_refill_syringe", {
                    "syringe": "waterclean",
                    "fill_volume_ul": volume,
                    "Syringe_rate_ulsec": 300,
                    }
                )
            #rinse with electrolyte to remove cleaning liquid residuals
            if rinse_with_electrolyte_bf_prefill:
                epm.add_experiment(
                    "ADSS_sub_cellfill_prefilled_nosampleload",
                    {
                        "Solution_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                        "Syringe_rate_ulsec": Syringe_rate_ulsec,
                    }
                )
                epm.add_experiment(
                    "ADSS_sub_recirculate",
                    {
                        "direction_forward_or_reverse": "forward",
                        "wait_time_s": rinse_with_electrolyte_bf_prefill_recirculate_wait_time_sec,
                    }
                )
                epm.add_experiment(
                    "ADSS_sub_drain_cell",
                    {
                        "DrainWait_s": rinse_with_electrolyte_bf_prefill_drain_time_sec,
                        "ReturnLineReverseWait_s": 5,
                    #    "ResidualWait_s": ResidualWait_s,
                    }
                )
                epm.add_experiment("ADSS_sub_refill_syringe", {
                    "syringe": "electrolyte",
                    "fill_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                    "Syringe_rate_ulsec": Syringe_rate_ulsec,
                    }
                )

###################################################################
#REF MEASUREMENT AT END OF SEQUENCE
###################################################################

    #ref measurement at end of sequence
    if measure_ref_Pt_at_end:
        epm.add_experiment(
            "ADSS_sub_move_to_ref_measurement",
            {
                "reference_position_name": name_ref_Pt_at_end,
            }
        )

        epm.add_experiment(
            "ADSS_sub_load",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id_ref_Pt,
                "solid_sample_no": 1,################### can i use the sample id for all ref measurements?
                "previous_liquid": use_current_electrolyte,
                "liquid_custom_position": "cell1_we",
                "liquid_sample_no": liquid_sample_no,            
                "liquid_sample_volume_ul": liquid_sample_volume_ul,
            }
        )

        #electrolyte filling for experiment
        epm.add_experiment(
            "ADSS_sub_cellfill_prefilled",
            {
                "Solution_volume_ul": liquid_sample_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
            }
        )

        #set initial gas to N2
        epm.add_experiment("ADSS_sub_gasvalve_N2flow",{"open": True,})
        epm.add_experiment("ADSS_sub_PAL_load_gas",{"bubbled_gas": "N2","reservoir_gas_sample_no":1,})

        # pump recirculate forward
        epm.add_experiment(
            "ADSS_sub_recirculate",
            {
                "direction_forward_or_reverse": "forward",
                "wait_time_s": fill_recirculate_wait_time_sec,
            }
        )
        
        # pump recirculate reverse (for bubbles)
        if pump_reversal_during_filling:
            epm.add_experiment(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "reverse",
                    "wait_time_s": fill_recirculate_reverse_wait_time_sec,
                })
        
            # pump recirculate forward
            epm.add_experiment(
                "ADSS_sub_recirculate",
                {
                    "direction_forward_or_reverse": "forward",
                    "wait_time_s": 5,
                }
            )

        #refill electrolyte syringe here so that ADSS can recirculate and N2 saturate while filling syringe
        if not use_current_electrolyte:
            epm.add_experiment("ADSS_sub_refill_syringe", {
                "syringe": "electrolyte",
                "fill_volume_ul": liquid_sample_volume_ul,
                "Syringe_rate_ulsec": 300,
                }
            )       

        #check for bubbles that could interfere with echem measurments with OCV
        if use_bubble_removal:
            epm.add_experiment("ADSS_sub_OCV",
                               {
                                "check_bubble": True,
                                "Tval__s": bubble_removal_OCV_t_s,
                                "samplerate_sec": 0.1,
                                "gamry_i_range": gamry_i_range,
                                "ph": ph,
                                "ref_type": ref_type,
                                "ref_offset__V": ref_offset__V,
                                "aliquot_insitu": False,
                                "run_use": "ref",
                                "RSD_threshold": bubble_removal_RSD_threshold,
                                "simple_threshold": bubble_removal_simple_threshold,
                                "signal_change_threshold": bubble_removal_signal_change_threshold,
                                "amplitude_threshold": bubble_removal_amplitude_threshold,
                                "bubble_pump_reverse_time_s": bubble_removal_pump_reverse_t_s,
                                "bubble_pump_forward_time_s": bubble_removal_pump_forward_t_s,
                                "bubbler_gas": "N2",
                                })

        #saturate electrolyte with N2
        epm.add_experiment("ADSS_sub_OCV", 
                    {
                        "Tval__s": purge_wait_initialN2_min * 60,
                        "samplerate_sec": OCP_samplerate_sec,
                        "gamry_i_range": gamry_i_range,
                        "ph": ph,
                        "ref_type": ref_type,
                        "ref_offset__V": ref_offset__V,
                        "aliquot_insitu": False,
                        "bubbler_gas": "N2",
                        "run_use": "ref"
                        
                    })
        
        # epm.add_experiment(
        #     "orch_sub_wait",
        #     {
        #         "wait_time_s": purge_wait_initialN2_min * 60,
        #     }
        # )
        
        #start cleaning CVs in N2
        for i, CV_cycle in enumerate(cleaning_CV_cycles):
            epm.add_experiment(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": cleaning_Vinit_vsRHE[i],
                    "Vapex1_vsRHE": cleaning_Vapex1_vsRHE[i],
                    "Vapex2_vsRHE": cleaning_Vapex2_vsRHE[i],
                    "Vfinal_vsRHE": cleaning_Vfinal_vsRHE[i],
                    "scanrate_voltsec": cleaning_scanrate_voltsec[i],
                    "SampleRate": cleaning_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "bubbler_gas": "N2",
                    "run_use": "ref"
                }
            )
            
        #start background CVs in N2
        for i, CV_cycle in enumerate(ref_CV_cycles):
            epm.add_experiment(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": ref_Vinit_vsRHE,
                    "Vapex1_vsRHE": ref_Vapex1_vsRHE,
                    "Vapex2_vsRHE": ref_Vapex2_vsRHE,
                    "Vfinal_vsRHE": ref_Vfinal_vsRHE,
                    "scanrate_voltsec": ref_CV_scanrate_voltsec,
                    "SampleRate": ref_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "bubbler_gas": "N2",
                    "run_use": "ref"
                }
            )
        
        #switch from N2 to O2 and saturate
        epm.add_experiment("ADSS_sub_gasvalve_N2flow",{"open": False,})
    #need to remove N2 gas sample
        epm.add_experiment("ADSS_sub_unload_gas_only",{})
    #test need
        epm.add_experiment("ADSS_sub_PAL_load_gas",{"bubbled_gas": "O2","reservoir_gas_sample_no":2,})

        epm.add_experiment("ADSS_sub_OCV", 
                           {
                               "Tval__s": purge_wait_N2_to_O2_min * 60,
                               "samplerate_sec": OCP_samplerate_sec,
                               "gamry_i_range": gamry_i_range,
                               "ph": ph,
                               "ref_type": ref_type,
                               "ref_offset__V": ref_offset__V,
                               "aliquot_insitu": False,
                               "bubbler_gas": "O2",
                               "run_use": "ref"
                           })        
#        epm.add_experiment(
#            "orch_sub_wait",
#            {
#                "wait_time_s": purge_wait_N2_to_O2_min * 60,
#            }
#        )

        #start O2 cycles
        for i, CV_cycle in enumerate(ref_CV_cycles):
            epm.add_experiment(
                "ADSS_sub_CV",
                {
                    "Vinit_vsRHE": ref_Vinit_vsRHE,
                    "Vapex1_vsRHE": ref_Vapex1_vsRHE,
                    "Vapex2_vsRHE": ref_Vapex2_vsRHE,
                    "Vfinal_vsRHE": ref_Vfinal_vsRHE,
                    "scanrate_voltsec": ref_CV_scanrate_voltsec,
                    "SampleRate": ref_CV_samplerate_sec,
                    "cycles": CV_cycle,
                    "gamry_i_range": gamry_i_range,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "aliquot_insitu": False,
                    "bubbler_gas": "O2",
                    "run_use": "ref"
                }
            )
        
        #switch from O2 to N2 and saturate
        epm.add_experiment("ADSS_sub_gasvalve_N2flow",{"open": True,})

        #unload sample
        epm.add_experiment("ADSS_sub_unloadall_customs",{})
        
        #drain cell
        epm.add_experiment(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": cell_draintime_sec,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_sec,
            #    "ResidualWait_s": ResidualWait_s,
            }
        )

        #clean cell
        if move_to_clean_and_clean:
            epm.add_experiment("ADSS_sub_move_to_clean_cell", {})
            for i in range(number_of_cleans):
                epm.add_experiment("ADSS_sub_clean_cell",
                                {
                                    "Clean_volume_ul": clean_volume_ul,
                                    "ReturnLineWait_s": clean_recirculate_sec,
                                    "DrainWait_s": clean_drain_sec,
                                }
                            )
                #if working with more than 10mL cleaning V, then by default a precleaning with 6mL is done. This would also be needed to refill
                if clean_volume_ul > 10000:
                    volume = 6000 + clean_volume_ul
                else:
                    volume = clean_volume_ul

                epm.add_experiment("ADSS_sub_refill_syringe", {
                    "syringe": "waterclean",
                    "fill_volume_ul": volume,
                    "Syringe_rate_ulsec": 300,
                    }
                )

            #rinse with electrolyte to remove cleaning liquid residuals
            if rinse_with_electrolyte_bf_prefill:
                epm.add_experiment(
                    "ADSS_sub_cellfill_prefilled_nosampleload",
                    {
                        "Solution_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                        "Syringe_rate_ulsec": Syringe_rate_ulsec,
                    }
                )
                epm.add_experiment(
                    "ADSS_sub_recirculate",
                    {
                        "direction_forward_or_reverse": "forward",
                        "wait_time_s": rinse_with_electrolyte_bf_prefill_recirculate_wait_time_sec,
                    }
                )
                epm.add_experiment(
                    "ADSS_sub_drain_cell",
                    {
                        "DrainWait_s": rinse_with_electrolyte_bf_prefill_drain_time_sec,
                        "ReturnLineReverseWait_s": 5,
                    #    "ResidualWait_s": ResidualWait_s,
                    }
                )
                epm.add_experiment("ADSS_sub_refill_syringe", {
                    "syringe": "electrolyte",
                    "fill_volume_ul": rinse_with_electrolyte_bf_prefill_volume_uL,
                    "Syringe_rate_ulsec": Syringe_rate_ulsec,
                    }
                )  
    epm.add_experiment("ADSS_sub_gasvalve_N2flow",{"open": False,})
 

    return epm.experiment_plan_list  # returns complete experiment list