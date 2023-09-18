"""
Sequence library for ADSS
"""

__all__ = [
    "ADSS_CA_cell_1potential",
]

from typing import List
from helao.helpers.premodels import ExperimentPlanMaker


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
    insert_electrolyte: bool = False,
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
                "previous_liquid": use_electrolyte,
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
                "insert_electrolyte":insert_electrolyte,
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
                "insert_electrolyte":insert_electrolyte,
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

