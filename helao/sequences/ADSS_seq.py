"""
Sequence library for ADSS
"""

__all__ = [
    "ADSS_CV_nomove",
    "ADSS_CA_nomove",
    "ADSS_CombineEche",
    "ADSS_CA_NaOH_validation",
]

from typing import List
from helao.helpers.premodels import ExperimentPlanMaker


SEQUENCES = __all__


def ADSS_CV_nomove(
    sequence_version: int = 4,
    solid_custom_position: str = "cell1_we",
    plate_id: int = 4534,
    plate_sample_no_list: list = [1],  # list instead of map select
    liquid_custom_position: str = "elec_res1",
    liquid_sample_no: int = 1,
    CV1_Vinit_vsRHE: float = 0.7,
    CV1_Vapex1_vsRHE: float = 1,
    CV1_Vapex2_vsRHE: float = 0,
    CV1_Vfinal_vsRHE: float = 0,
    CV1_scanrate_voltsec: float = 0.02,
    CV1_samplerate_mV: float = 1,
    CV1_cycles: int = 1,
    preCV_duration: float = 3,
    gamry_i_range: str = "auto",
    ph: float = 9.53,
    ref_type: str = "inhouse",
    ref_offset__V: float = 0.0,
):

    epm = ExperimentPlanMaker()

    for solid_sample_no in plate_sample_no_list[:1]:  # have to indent add expts if used

        epm.add_experiment(
            "ADSS_sub_load",
            {
                "solid_custom_position": solid_custom_position,
                "solid_plate_id": plate_id,
                "solid_sample_no": solid_sample_no,
                "liquid_custom_position": liquid_custom_position,
                "liquid_sample_no": liquid_sample_no,
            },
        )

        epm.add_experiment(
            "ADSS_sub_CA",
            {
                "CA_potential": CV1_Vinit_vsRHE,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "gamry_i_range": gamry_i_range,
                "samplerate_sec": CV1_samplerate_mV / (CV1_scanrate_voltsec * 1000),
                "CA_duration_sec": preCV_duration,
            },
        )

        epm.add_experiment(
            "ADSS_sub_CV",
            {
                "Vinit_vsRHE": CV1_Vinit_vsRHE,
                "Vapex1_vsRHE": CV1_Vapex1_vsRHE,
                "Vapex2_vsRHE": CV1_Vapex2_vsRHE,
                "Vfinal_vsRHE": CV1_Vfinal_vsRHE,
                "scanrate_voltsec": CV1_scanrate_voltsec,
                "samplerate_sec": CV1_samplerate_mV / (CV1_scanrate_voltsec * 1000),
                "cycles": CV1_cycles,
                "gamry_i_range": gamry_i_range,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
            },
        )

        # epm.add_experiment("ADSS_sub_shutdown", {})

    return epm.experiment_plan_list  # returns complete experiment list


def ADSS_CA_nomove(
    sequence_version: int = 5,
    solid_custom_position: str = "cell1_we",
    plate_id: int = 4534,
    plate_sample_no_list: list = [1],  # list instead of map select
    liquid_custom_position: str = "elec_res1",
    liquid_sample_no: int = 1,
    CA_potentials_vsRHE: List[float] = [-0.2, 0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
    ph: float = 9.53,
    ref_type: str = "inhouse",
    ref_offset__V: float = 0.0,
    CA_duration_sec: float = 1320,
    aliquot_times_sec: List[float] = [60, 600, 1140],
    aliquot_volume_ul: int = 200,
    OCV_duration: float = 1,
    samplerate_sec: float = 0.05,
    filltime_sec: float = 10.0,
):

    """tbd

    last functionality test: tbd"""

    epm = ExperimentPlanMaker()

    for solid_sample_no in plate_sample_no_list[:1]:  # have to indent add expts if used

        epm.add_experiment(
            "ADSS_sub_load",
            {
                "solid_custom_position": solid_custom_position,
                "solid_plate_id": plate_id,
                "solid_sample_no": solid_sample_no,
                "liquid_custom_position": liquid_custom_position,
                "liquid_sample_no": liquid_sample_no,
            },
        )

        epm.add_experiment(
            "ADSS_sub_OCV",
            {
                "Tval__s": OCV_duration,
                "SampleRate": 0.05,
            },
        )

        for CA_potential_vsRHE in CA_potentials_vsRHE:

            epm.add_experiment(
                "ADSS_sub_CA",
                {
                    "CA_potential": CA_potential_vsRHE,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "samplerate_sec": samplerate_sec,
                    "CA_duration_sec": CA_duration_sec,
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "aliquot_times_sec": aliquot_times_sec,
                },
            )

        # epm.add_experiment("ADSS_sub_shutdown", {})

    return epm.experiment_plan_list  # returns complete experiment list


def ADSS_CombineEche(
    sequence_version: int = 2,
    solid_custom_position: str = "cell1_we",
    plate_id: int = 4534,
    plate_sample_no_list: list = [1],  # list instead of map select
    liquid_custom_position: str = "elec_res1",
    liquid_sample_no: int = 1,
    ph: float = 9.53,
    ref_type: str = "inhouse",
    ref_offset__V: float = 0.0,
    OCV_duration: float = 60.0,
    CV1_Vinit_vsRHE: float = 0.7,
    CV1_Vapex1_vsRHE: float = 1,
    CV1_Vapex2_vsRHE: float = 0,
    CV1_Vfinal_vsRHE: float = 0,
    CV1_scanrate_voltsec: float = 0.02,
    CV1_samplerate_mV: float = 1,
    CV1_cycles: int = 1,
    CV2_Vinit_vsRHE: float = 0.7,
    CV2_Vapex1_vsRHE: float = 1,
    CV2_Vapex2_vsRHE: float = 0,
    CV2_Vfinal_vsRHE: float = 0,
    CV2_scanrate_voltsec: float = 0.02,
    CV2_samplerate_mV: float = 1,
    CV2_cycles: int = 1,
    CA_potential_vsRHE: float = 1.0,
    CA_duration_sec: float = 1320,
    samplerate_sec: float = 0.05,
    gamry_i_range: str = "auto",
):

    """tbd

    last functionality test: tbd"""

    epm = ExperimentPlanMaker()

    for solid_sample_no in plate_sample_no_list[:1]:  # have to indent add expts if used

        epm.add_experiment(
            "ADSS_sub_load",
            {
                "solid_custom_position": solid_custom_position,
                "solid_plate_id": plate_id,
                "solid_sample_no": solid_sample_no,
                "liquid_custom_position": liquid_custom_position,
                "liquid_sample_no": liquid_sample_no,
            },
        )

        epm.add_experiment(
            "ADSS_sub_CV",
            {
                "Vinit_vsRHE": CV1_Vinit_vsRHE,
                "Vapex1_vsRHE": CV1_Vapex1_vsRHE,
                "Vapex2_vsRHE": CV1_Vapex2_vsRHE,
                "Vfinal_vsRHE": CV1_Vfinal_vsRHE,
                "scanrate_voltsec": CV1_scanrate_voltsec,
                "samplerate_sec": CV1_samplerate_mV / (CV1_scanrate_voltsec * 1000),
                "cycles": CV1_cycles,
                "gamry_i_range": gamry_i_range,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
            },
        )

        epm.add_experiment(
            "ADSS_sub_OCV",
            {
                "Tval__s": OCV_duration,
                "SampleRate": 0.1,
            },
        )

        epm.add_experiment(
            "ADSS_sub_CV",
            {
                "Vinit_vsRHE": CV2_Vinit_vsRHE,
                "Vapex1_vsRHE": CV2_Vapex1_vsRHE,
                "Vapex2_vsRHE": CV2_Vapex2_vsRHE,
                "Vfinal_vsRHE": CV2_Vfinal_vsRHE,
                "scanrate_voltsec": CV2_scanrate_voltsec,
                "samplerate_sec": CV2_samplerate_mV / (CV2_scanrate_voltsec * 1000),
                "cycles": CV2_cycles,
                "gamry_i_range": gamry_i_range,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
            },
        )

        epm.add_experiment(
            "ADSS_sub_OCV",
            {
                "Tval__s": OCV_duration,
                "SampleRate": 0.1,
            },
        )

        epm.add_experiment(
            "ADSS_sub_CA",
            {
                "CA_potential": CA_potential_vsRHE,
                "ph": ph,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "samplerate_sec": samplerate_sec,
                "CA_duration_sec": CA_duration_sec,
            },
        )

        #    epm.add_experiment("ADSS_sub_shutdown", {})

    return epm.experiment_plan_list  # returns complete experiment list


# def ADSS_tray_unload(
#     sequence_version: int = 1,
#     tray: int = 2,
#     slot: int = 1,
#     survey_runs: int = 1,
#     main_runs: int = 3,
#     rack: int = 2,
# ):
#     """Unloads a selected tray from PAL position tray-slot and creates
#     (1) json
#     (2) csv
#     (3) icpms
#     exports.

#     Parameters for ICPMS export are
#     survey_runs: rough sweep over the whole partial_molarity range
#     main_runs: sweep channel centered on element partial_molarity
#     rack: position of the tray in the icpms instrument, usually 2.
#     """
#     epm = ExperimentPlanMaker()

#     epm.add_experiment(
#         "ADSS_sub_tray_unload",
#         {
#             "tray": tray,
#             "slot": slot,
#             "survey_runs": survey_runs,
#             "main_runs": main_runs,
#             "rack": rack,
#         },
#     )
# #    epm.add_experiment("ADSS_sub_shutdown", {})

#     return epm.experiment_plan_list  # returns complete experiment list

# def ADSS_minimum_CV(
#     sequence_version: int = 1,
#     solid_custom_position: str = "cell1_we",
#     plate_id: int = 4534,
#     solid_sample_no: int = 1,
#     x_mm: float = 0.0,
#     y_mm: float = 0.0,
#     liquid_custom_position: str = "elec_res1",
#     liquid_sample_no: int = 1,
#     CV1_Vinit_vsRHE: float = 0.7,
#     CV1_Vapex1_vsRHE: float = 1,
#     CV1_Vapex2_vsRHE: float = 0,
#     CV1_Vfinal_vsRHE: float = 0,
#     CV1_scanrate_voltsec: float = 0.02,
#     CV1_samplerate_mV: float = 1,
#     CV1_cycles: int = 1,
#     gamry_i_range: str = "auto",
#     ph: float = 9.53,
#     ref_type: str = "inhouse",
#     ref_offset__V: float = 0.0,
#     aliquot_times_sec: List[float] = [60, 600, 1140],
#     filltime_sec: float = 10.0,
# ):

#     """tbd

#     last functionality test: tbd"""

#     epm = ExperimentPlanMaker()

#     epm.add_experiment("ADSS_sub_unloadall_customs",{})


#     epm.add_experiment(
#         "ADSS_sub_load_solid",
#         {
#             "solid_custom_position": solid_custom_position,
#             "solid_plate_id": plate_id,
#             "solid_sample_no": solid_sample_no,
#         },
#     )
#     epm.add_experiment(
#         "ADSS_sub_load_liquid",
#         {
#             "liquid_custom_position": liquid_custom_position,
#             "liquid_sample_no": liquid_sample_no,
#         },
#     )


#     epm.add_experiment(
#         "ADSS_sub_CV_noaliquots",
#         {
#             "Vinit_vsRHE": CV1_Vinit_vsRHE,
#             "Vapex1_vsRHE": CV1_Vapex1_vsRHE,
#             "Vapex2_vsRHE": CV1_Vapex2_vsRHE,
#             "Vfinal_vsRHE": CV1_Vfinal_vsRHE,
#             "scanrate_voltsec": CV1_scanrate_voltsec,
#             "samplerate_sec": CV1_samplerate_mV / (CV1_scanrate_voltsec * 1000),
#             "cycles": CV1_cycles,
#             "gamry_i_range": gamry_i_range,
#             "ph": ph,
#             "ref_type": ref_type,
#             "ref_offset__V": ref_offset__V,
#             "aliquot_times_sec": aliquot_times_sec,
#         },
#     )

# #    epm.add_experiment("ADSS_sub_shutdown", {})

#     return epm.experiment_plan_list  # returns complete experiment list


# def ADSS_minimum_CA(
#     sequence_version: int = 1,
#     solid_custom_position: str = "cell1_we",
#     plate_id: int = 4534,
#     solid_sample_no: int = 1,
#     x_mm: float = 0.0,
#     y_mm: float = 0.0,
#     liquid_custom_position: str = "elec_res1",
#     liquid_sample_no: int = 1,
#     CA_potential_vsRHE: float = 1.0,
# #    CA_potentials_vsRHE: List[float] = [-0.2, 0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
#     ph: float = 9.53,
#     ref_type: str = "inhouse",
#     ref_offset__V: float = 0.0,
#     CA_duration_sec: float = 1320,
#     aliquot_times_sec: List[float] = [60, 600, 1140],
#     OCV_duration_sec: float = 60,
#     samplerate_sec: float = 0.05,
#     filltime_sec: float = 10.0,
# ):

#     """tbd

#     last functionality test: tbd"""

#     epm = ExperimentPlanMaker()

#     # epm.add_experiment(
#     #     "ADSS_sub_startup",
#     #     {
#     #         "solid_custom_position": solid_custom_position,
#     #         "solid_plate_id": plate_id,
#     #         "solid_sample_no": solid_sample_no,
#     #         "liquid_custom_position": liquid_custom_position,
#     #         "liquid_sample_no": liquid_sample_no,
#     #     },
#     # )
#     epm.add_experiment("ADSS_sub_unloadall_customs",{})


#     epm.add_experiment(
#         "ADSS_sub_load_solid",
#         {
#             "solid_custom_position": solid_custom_position,
#             "solid_plate_id": plate_id,
#             "solid_sample_no": solid_sample_no,
#         },
#     )
#     epm.add_experiment(
#         "ADSS_sub_load_liquid",
#         {
#             "liquid_custom_position": liquid_custom_position,
#             "liquid_sample_no": liquid_sample_no,
#         },
#     )


#     epm.add_experiment(
#         "ADSS_sub_CA_noaliquots",
#         {
#             "CA_potential": CA_potential_vsRHE,
#             "ph": ph,
#             "ref_type": ref_type,
#             "ref_offset__V": ref_offset__V,
#             "samplerate_sec": samplerate_sec,
#             "OCV_duration_sec": OCV_duration_sec,
#             "CA_duration_sec": CA_duration_sec,
#             "aliquot_times_sec": aliquot_times_sec,
#         },
#     )
# #    epm.add_experiment("ADSS_sub_shutdown", {})
#     return epm.experiment_plan_list  # returns complete experiment list


# def ADSS_duaribilty_CAv1(
#     sequence_version: int = 1,
#     solid_custom_position: str = "cell1_we",
#     plate_id: int = 4534,
#     solid_sample_no: int = 1,
#     x_mm: float = 0.0,
#     y_mm: float = 0.0,
#     liquid_custom_position: str = "elec_res1",
#     liquid_sample_no: int = 3,
#     CA_potentials_vsRHE: List[float] = [-0.2, 0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
#     ph: float = 9.53,
#     ref_type: str = "inhouse",
#     ref_offset__V: float = 0.0,
#     CA_duration_sec: float = 1320,
#     aliquot_times_sec: List[float] = [60, 600, 1140],
#     OCV_duration_sec: float = 60,
#     samplerate_sec: float = 1,
#     filltime_sec: float = 10.0,
# ):

#     """tbd

#     last functionality test: tbd"""

#     epm = ExperimentPlanMaker()

#     epm.add_experiment(
#         "ADSS_sub_startup",
#         {
#             "x_mm": x_mm,
#             "y_mm": y_mm,
#             "solid_custom_position": solid_custom_position,
#             "solid_plate_id": plate_id,
#             "solid_sample_no": solid_sample_no,
#             "liquid_custom_position": liquid_custom_position,
#             "liquid_sample_no": liquid_sample_no,
#         },
#     )

#     for cycle, potential in enumerate(CA_potentials_vsRHE):
#         print(f" ... cycle {cycle} potential:", potential)
#         if cycle == 0:
#             epm.add_experiment(
#                 "ADSS_sub_fillfixed",
#                 {"fill_vol_ul": 10000, "filltime_sec": filltime_sec},
#             )

#         else:
#             epm.add_experiment("ADSS_sub_fill", {"fill_vol_ul": 1000})

#         epm.add_experiment(
#             "ADSS_sub_CA",
#             {
#                 "CA_potential": potential,
#                 "ph": ph,
#                 "ref_type": ref_type,
#                 "ref_offset__V": ref_offset__V,
#                 "samplerate_sec": samplerate_sec,
#                 "OCV_duration_sec": OCV_duration_sec,
#                 "CA_duration_sec": CA_duration_sec,
#                 "aliquot_times_sec": aliquot_times_sec,
#             },
#         )

#     epm.add_experiment("ADSS_sub_shutdown", {})

#     return epm.experiment_plan_list  # returns complete experiment list

def ADSS_CA_NiSb_validation(
    sequence_version: int = 6,
    solid_custom_position: str = "cell1_we",
    plate_id: int = 5917,
    plate_sample_no_list: list = [14050],  # list instead of map select
    liquid_custom_position: str = "elec_res1",
    liquid_sample_no: int = 1,
    liquid_sample_volume_ul: float = 4000,
    EquilibrationTime_s: float = 30,
    CA_potentials_vs: List[float] = [-0.2, 0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
    potential_versus: str = "oer",
    ph: float = 9.53,
    ref_type: str = "rhe",
    ref_offset__V: float = 0.0,
    CA_duration_sec: float = 1320,
    aliquot_times_sec: List[float] = [60, 600, 1140],
    aliquot_volume_ul: int = 200,
    OCV_duration: float = 60,
    samplerate_sec: float = 0.05,
    Syringe_rate_ulsec: float = 300,
    Cell_draintime_s: float = 60,
    ReturnLineWait_s: float = 30,
    ReturnLineReverseWait_s: float = 3,
    ResidualWait_s: float = 15,
    flush_volume_ul: float = 2000,
    clean_volume_ul: float = 5000,
    PAL_Injector: str = "LS 4"
):

    """tbd

    last functionality test: tbd"""

    epm = ExperimentPlanMaker()


    for solid_sample_no in plate_sample_no_list:  # have to indent add expts if used

        epm.add_experiment(
            "ADSS_sub_sample_start",
            {
                "solid_custom_position": solid_custom_position,
                "solid_plate_id": plate_id,
                "solid_sample_no": solid_sample_no,
                "liquid_custom_position": liquid_custom_position,
                "liquid_sample_no": liquid_sample_no,
            },
        )
        # epm.add_experiment(
        #     "ADSS_sub_cellfill",
        #     {
        #         "Solution_volume_ul": flush_volume_ul,
        #         "Syringe_rate_ulsec": Syringe_rate_ulsec,
        #         "ReturnLineWait_s": ReturnLineWait_s,
        #     }
        # )
        # epm.add_experiment(
        #     "ADSS_sub_drain_cell",
        #     {
        #         "DrainWait_s": Cell_draintime_s,
        #         "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
        #         "ResidualWait_s": ResidualWait_s,
        #     }
        # )
        for CA_potential_vs in CA_potentials_vs:

            epm.add_experiment(
                "ADSS_sub_cellfill_prefilled",
                {
                    "Solution_volume_ul": liquid_sample_volume_ul,
                    "Syringe_rate_ulsec": Syringe_rate_ulsec,
                }
            )
            epm.add_experiment(
                "ADSS_sub_load_liquid",
                {
                    "liquid_custom_position": liquid_custom_position,
                    "liquid_sample_no": liquid_sample_no,
                }
            )
            epm.add_experiment(
                "ADSS_sub_load_solid",
                {
                    "solid_custom_position": solid_custom_position,
                    "solid_plate_id": plate_id,
                    "solid_sample_no": solid_sample_no,
                }
            )
            epm.add_experiment(
                "ADSS_sub_sample_aliquot",
                {
                    "EquilibrationTime_s": EquilibrationTime_s,
                    "aliquot_volume_ul": aliquot_volume_ul,
                    "PAL_Injector": PAL_Injector,
                }
            )

            epm.add_experiment(
                "ADSS_sub_OCV",
                {
                    "Tval__s": OCV_duration,
                    "SampleRate": 0.05,
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
                },
            )

            epm.add_experiment(
                "ADSS_sub_drain_cell",
                {
                    "DrainWait_s": Cell_draintime_s,
                    "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
                    "ResidualWait_s": ResidualWait_s,
                }
            )
            epm.add_experiment(
                "ADSS_sub_cellfill_prefilled",
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
                    "ResidualWait_s": ResidualWait_s,
                }
            )
            epm.add_experiment("ADSS_sub_unload_liquid",{})

        epm.add_experiment(
            "ADSS_sub_clean_cell",
            {
                "Clean_volume_ul": clean_volume_ul,
                "Syringe_rate_ulsec": Syringe_rate_ulsec,
                "ReturnLineWait_s": ReturnLineWait_s,
        }
        )
        epm.add_experiment(
            "ADSS_sub_drain_cell",
            {
                "DrainWait_s": Cell_draintime_s,
                "ReturnLineReverseWait_s": ReturnLineReverseWait_s,
                "ResidualWait_s": ResidualWait_s,
            }
        )

#    epm.add_experiment("ADSS_sub_tray_unload",{})


        # epm.add_experiment("ADSS_sub_shutdown", {})

    return epm.experiment_plan_list  # returns complete experiment list

