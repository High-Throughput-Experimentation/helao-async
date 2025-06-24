"""
Sequence library for ECHE
"""

__all__ = [
    "ECHE_4CA_led_1CV_led",
    "ECHE_CV_CA_CV",
    "ECHE_CV",
    "ECHE_CV_led",
    "ECHE_CA",
    "ECHE_CA_led",
    "ECHE_CP",
    "ECHE_CP_led",
    "ECHE_movetosample",
    "ECHE_move",
    "ECHE_CVs_CAs",
    "ECHE_cleanCVs_regCVs_CAs",
]


from helao.helpers.premodels import ExperimentPlanMaker
from helao.core.models.electrolyte import Electrolyte
from helao.helpers.ref_electrode import REF_TABLE


SEQUENCES = __all__


def ECHE_movetosample(
    sequence_version: int = 1,
    plate_id: int = 1,
    plate_sample_no: int = 1,
):

    epm = ExperimentPlanMaker()

    epm.add_experiment(
        "ECHE_sub_movetosample",
        {
            #            "solid_custom_position": "cell1_we",
            "solid_plate_id": plate_id,
            "solid_sample_no": plate_sample_no,
        },
    )

    epm.add_experiment("ECHE_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list


def ECHE_move(
    sequence_version: int = 1,
    move_x_mm: float = 1.0,
    move_y_mm: float = 1.0,
):

    epm = ExperimentPlanMaker()

    epm.add_experiment(
        "ECHE_sub_rel_move",
        {
            "offset_x_mm": move_x_mm,
            "offset_y_mm": move_y_mm,
        },
    )

    epm.add_experiment("ECHE_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list


def ECHE_4CA_led_1CV_led(
    sequence_version: int = 4,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,
    solution_bubble_gas: str = "O2",
    solution_ph: float = 9.53,
    ref_type: str = "inhouse",
    ref_offset__V: float = 0.0,
    measurement_area: float = 0.071,  # 3mm diameter droplet
    liquid_volume_ml: float = 1.0,
    ref_vs_nhe: float = 0.21,
    CA1_potential: float = 1.23,
    CA1_duration_sec: float = 15,
    CA2_potential: float = 1.23,
    CA2_duration_sec: float = 4,
    CA3_potential: float = 1.23,
    CA3_duration_sec: float = 4,
    CA4_potential: float = 1.23,
    CA4_duration_sec: float = 4,
    CA_samplerate_sec: float = 0.05,
    CV_Vinit_vsRHE: float = 1.23,
    CV_Vapex1_vsRHE: float = 0.73,
    CV_Vapex2_vsRHE: float = 1.73,
    CV_Vfinal_vsRHE: float = 1.73,
    CV_scanrate_voltsec: float = 0.02,
    CV_samplerate_mV: float = 1,
    CV_cycles: int = 1,
    preCV_duration: float = 3,
    OCV_duration: float = 1,
    gamry_i_range: str = "auto",
    gamrychannelwait: int= -1,
    gamrychannelsend: int= 0,
    led_type: str = "front",
    led_date: str = "01/01/2000",
    led_names: list = ["doric_led1", "doric_led2", "doric_led3", "doric_led4"],
    led_wavelengths_nm: list = [385, 450, 515, 595],
    led_intensities_mw: list = [-1, -1, -1, -1],
    led_name_CA1: str = "doric_led1",
    led_name_CA2: str = "doric_led2",
    led_name_CA3: str = "doric_led3",
    led_name_CA4: str = "doric_led4",
    led_name_CV: str = "doric_led1",
    toggleCA_illum_duty: float = 0.5,
    toggleCA_illum_period: float = 1.0,
    toggleCA_dark_time_init: float = 0,
    toggleCA_illum_time: float = -1,
    toggleCV_illum_duty: float = 0.667,
    toggleCV_illum_period: float = 3.0,
    toggleCV_dark_time_init: float = 0,
    toggleCV_illum_time: float = -1,
):

    epm = ExperimentPlanMaker()

    # (1) house keeping
    epm.add_experiment("ECHE_sub_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        epm.add_experiment(
            "ECHE_sub_startup",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "solution_bubble_gas": solution_bubble_gas,
                "liquid_volume_ml": liquid_volume_ml,
            },
        )
        # OCV
        epm.add_experiment(
            "ECHE_sub_OCV",
            {
                "Tval__s": OCV_duration,
                "SampleRate": 0.05,
            },
        )
        # CA1
        epm.add_experiment(
            "ECHE_sub_CA_led",
            {
                "CA_potential": CA1_potential,
                "solution_ph": solution_ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "measurement_area": measurement_area,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "samplerate_sec": CA_samplerate_sec,
                "CA_duration_sec": CA1_duration_sec,
                "gamry_i_range": gamry_i_range,
                "gamrychannelwait": gamrychannelwait,
                "gamrychannelsend": gamrychannelsend,
                "illumination_source": led_name_CA1,
                "illumination_wavelength": led_wavelengths_nm[
                    led_names.index(led_name_CA1)
                ],
                "illumination_intensity": led_intensities_mw[
                    led_names.index(led_name_CA1)
                ],
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "toggle_illum_duty": toggleCA_illum_duty,
                "toggle_illum_period": toggleCA_illum_period,
                "toggle_illum_time": toggleCA_illum_time,
                "toggle_dark_time_init": toggleCA_dark_time_init,
            },
        )
        # OCV
        epm.add_experiment(
            "ECHE_sub_OCV",
            {
                "Tval__s": OCV_duration,
                "SampleRate": 0.05,
            },
        )
        # CA2
        epm.add_experiment(
            "ECHE_sub_CA_led",
            {
                "CA_potential": CA2_potential,
                "solution_ph": solution_ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "measurement_area": measurement_area,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "samplerate_sec": CA_samplerate_sec,
                "CA_duration_sec": CA2_duration_sec,
                "gamry_i_range": gamry_i_range,
                "illumination_source": led_name_CA2,
                "illumination_wavelength": led_wavelengths_nm[
                    led_names.index(led_name_CA2)
                ],
                "illumination_intensity": led_intensities_mw[
                    led_names.index(led_name_CA2)
                ],
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "toggle_illum_duty": toggleCA_illum_duty,
                "toggle_illum_period": toggleCA_illum_period,
                "toggle_illum_time": toggleCA_illum_time,
                "toggle_dark_time_init": toggleCA_dark_time_init,
            },
        )
        # OCV
        epm.add_experiment(
            "ECHE_sub_OCV",
            {
                "Tval__s": OCV_duration,
                "SampleRate": 0.05,
            },
        )
        # CA3
        epm.add_experiment(
            "ECHE_sub_CA_led",
            {
                "CA_potential": CA3_potential,
                "solution_ph": solution_ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "measurement_area": measurement_area,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "samplerate_sec": CA_samplerate_sec,
                "CA_duration_sec": CA3_duration_sec,
                "gamry_i_range": gamry_i_range,
                "illumination_source": led_name_CA3,
                "illumination_wavelength": led_wavelengths_nm[
                    led_names.index(led_name_CA3)
                ],
                "illumination_intensity": led_intensities_mw[
                    led_names.index(led_name_CA3)
                ],
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "toggle_illum_duty": toggleCA_illum_duty,
                "toggle_illum_period": toggleCA_illum_period,
                "toggle_illum_time": toggleCA_illum_time,
                "toggle_dark_time_init": toggleCA_dark_time_init,
            },
        )
        # OCV
        epm.add_experiment(
            "ECHE_sub_OCV",
            {
                "Tval__s": OCV_duration,
                "SampleRate": 0.05,
            },
        )
        # CA4
        epm.add_experiment(
            "ECHE_sub_CA_led",
            {
                "CA_potential": CA4_potential,
                "solution_ph": solution_ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "measurement_area": measurement_area,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "samplerate_sec": CA_samplerate_sec,
                "CA_duration_sec": CA4_duration_sec,
                "gamry_i_range": gamry_i_range,
                "illumination_source": led_name_CA4,
                "illumination_wavelength": led_wavelengths_nm[
                    led_names.index(led_name_CA4)
                ],
                "illumination_intensity": led_intensities_mw[
                    led_names.index(led_name_CA4)
                ],
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "toggle_illum_duty": toggleCA_illum_duty,
                "toggle_illum_period": toggleCA_illum_period,
                "toggle_illum_time": toggleCA_illum_time,
                "toggle_dark_time_init": toggleCA_dark_time_init,
            },
        )

        # CV1
        epm.add_experiment(
            "ECHE_sub_preCV",
            {
                "CA_potential": CV_Vinit_vsRHE - 1.0 * ref_vs_nhe - 0.059 * solution_ph,
                "samplerate_sec": CV_samplerate_mV / (CV_scanrate_voltsec * 1000),
                "CA_duration_sec": preCV_duration,
            },
        )
        epm.add_experiment(
            "ECHE_sub_CV_led",
            {
                "Vinit_vsRHE": CV_Vinit_vsRHE,
                "Vapex1_vsRHE": CV_Vapex1_vsRHE,
                "Vapex2_vsRHE": CV_Vapex2_vsRHE,
                "Vfinal_vsRHE": CV_Vfinal_vsRHE,
                "scanrate_voltsec": CV_scanrate_voltsec,
                "samplerate_sec": CV_samplerate_mV / (CV_scanrate_voltsec * 1000),
                "cycles": CV_cycles,
                "gamry_i_range": gamry_i_range,
                "solution_ph": solution_ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "measurement_area": measurement_area,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "illumination_source": led_name_CV,
                "illumination_wavelength": led_wavelengths_nm[
                    led_names.index(led_name_CV)
                ],
                "illumination_intensity": led_intensities_mw[
                    led_names.index(led_name_CV)
                ],
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "toggle_illum_duty": toggleCV_illum_duty,
                "toggle_illum_period": toggleCV_illum_period,
                "toggle_illum_time": toggleCV_illum_time,
                "toggle_dark_time_init": toggleCV_dark_time_init,
            },
        )

        epm.add_experiment("ECHE_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list


def ECHE_CV_CA_CV(
    sequence_version: int = 4,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,
    solution_bubble_gas: str = "O2",
    solution_ph: float = 9.53,
    ref_type: str = "inhouse",
    ref_offset__V: float = 0.0,
    measurement_area: float = 0.071,  # 3mm diameter droplet    reference_electrode_type: str = "NHE",
    liquid_volume_ml: float = 1.0,
    CV1_Vinit_vsRHE: float = 1.23,
    CV1_Vapex1_vsRHE: float = 0.73,
    CV1_Vapex2_vsRHE: float = 1.73,
    CV1_Vfinal_vsRHE: float = 1.73,
    CV1_scanrate_voltsec: float = 0.02,
    CV1_samplerate_mV: float = 1,
    CV1_cycles: int = 1,
    preCV_duration: float = 3,
    OCV_duration: float = 1,
    CA2_potential: float = 1.23,
    CA2_duration_sec: float = 4,
    CA_samplerate_sec: float = 0.05,
    CV3_Vinit_vsRHE: float = 1.23,
    CV3_Vapex1_vsRHE: float = 0.73,
    CV3_Vapex2_vsRHE: float = 1.73,
    CV3_Vfinal_vsRHE: float = 1.73,
    CV3_scanrate_voltsec: float = 0.02,
    CV3_samplerate_mV: float = 1,
    CV3_cycles: int = 1,
    gamry_i_range: str = "auto",
):

    epm = ExperimentPlanMaker()

    # (1) house keeping
    epm.add_experiment("ECHE_sub_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        epm.add_experiment(
            "ECHE_sub_startup",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "liquid_volume_ml": liquid_volume_ml,
            },
        )

        epm.add_experiment(
            "ECHE_sub_preCV",
            {
                "CA_potential": CV1_Vinit_vsRHE
                - 1.0 * ref_offset__V
                - REF_TABLE[ref_type]
                - 0.059 * solution_ph,
                "samplerate_sec": CV1_samplerate_mV / (CV1_scanrate_voltsec * 1000),
                "CA_duration_sec": preCV_duration,
            },
        )
        # CV1
        epm.add_experiment(
            "ECHE_sub_CV",
            {
                "Vinit_vsRHE": CV1_Vinit_vsRHE,
                "Vapex1_vsRHE": CV1_Vapex1_vsRHE,
                "Vapex2_vsRHE": CV1_Vapex2_vsRHE,
                "Vfinal_vsRHE": CV1_Vfinal_vsRHE,
                "scanrate_voltsec": CV1_scanrate_voltsec,
                "samplerate_sec": CV1_samplerate_mV / (CV1_scanrate_voltsec * 1000),
                "cycles": CV1_cycles,
                "gamry_i_range": gamry_i_range,
                "solution_ph": solution_ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "measurement_area": measurement_area,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
            },
        )

        # OCV
        epm.add_experiment(
            "ECHE_sub_OCV",
            {
                "Tval__s": OCV_duration,
                "SampleRate": 0.05,
            },
        )
        # CA2
        epm.add_experiment(
            "ECHE_sub_CA",
            {
                "CA_potential": CA2_potential,
                "solution_ph": solution_ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "measurement_area": measurement_area,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "samplerate_sec": CA_samplerate_sec,
                "CA_duration_sec": CA2_duration_sec,
                "gamry_i_range": gamry_i_range,
            },
        )

        epm.add_experiment(
            "ECHE_sub_preCV",
            {
                "CA_potential": CV3_Vinit_vsRHE
                - 1.0 * ref_offset__V
                - REF_TABLE[ref_type]
                - 0.059 * solution_ph,
                "samplerate_sec": CV3_samplerate_mV / (CV3_scanrate_voltsec * 1000),
                "CA_duration_sec": preCV_duration,
            },
        )
        # CV3
        epm.add_experiment(
            "ECHE_sub_CV",
            {
                "Vinit_vsRHE": CV3_Vinit_vsRHE,
                "Vapex1_vsRHE": CV3_Vapex1_vsRHE,
                "Vapex2_vsRHE": CV3_Vapex2_vsRHE,
                "Vfinal_vsRHE": CV3_Vfinal_vsRHE,
                "scanrate_voltsec": CV3_scanrate_voltsec,
                "samplerate_sec": CV3_samplerate_mV / (CV3_scanrate_voltsec * 1000),
                "cycles": CV3_cycles,
                "gamry_i_range": gamry_i_range,
                "solution_ph": solution_ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "measurement_area": measurement_area,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
            },
        )

        epm.add_experiment("ECHE_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list


def ECHE_CV(
    sequence_version: int = 4,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,
    solution_bubble_gas: str = "O2",
    solution_ph: float = 9.53,
    measurement_area: float = 0.071,  # 3mm diameter droplet
    liquid_volume_ml: float = 1.0,
    ref_type: str = "inhouse",
    ref_offset__V: float = 0.0,
    CV1_Vinit_vsRHE: float = 0.7,
    CV1_Vapex1_vsRHE: float = 1,
    CV1_Vapex2_vsRHE: float = 0,
    CV1_Vfinal_vsRHE: float = 0,
    CV1_scanrate_voltsec: float = 0.02,
    CV1_samplerate_mV: float = 1,
    CV1_cycles: int = 1,
    preCV_duration: float = 3,
    gamry_i_range: str = "auto",
):

    epm = ExperimentPlanMaker()

    # (1) house keeping
    epm.add_experiment("ECHE_sub_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        epm.add_experiment(
            "ECHE_sub_startup",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "solution_bubble_gas": solution_bubble_gas,
                "liquid_volume_ml": liquid_volume_ml,
            },
        )

        epm.add_experiment(
            "ECHE_sub_preCV",
            {
                "CA_potential": CV1_Vinit_vsRHE
                - 1.0 * ref_offset__V
                - REF_TABLE[ref_type]
                - 0.059 * solution_ph,
                "samplerate_sec": CV1_samplerate_mV / (CV1_scanrate_voltsec * 1000),
                "CA_duration_sec": preCV_duration,
            },
        )
        # CV1
        epm.add_experiment(
            "ECHE_sub_CV",
            {
                "Vinit_vsRHE": CV1_Vinit_vsRHE,
                "Vapex1_vsRHE": CV1_Vapex1_vsRHE,
                "Vapex2_vsRHE": CV1_Vapex2_vsRHE,
                "Vfinal_vsRHE": CV1_Vfinal_vsRHE,
                "scanrate_voltsec": CV1_scanrate_voltsec,
                "samplerate_sec": CV1_samplerate_mV / (CV1_scanrate_voltsec * 1000),
                "cycles": CV1_cycles,
                "gamry_i_range": gamry_i_range,
                "solution_ph": solution_ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "measurement_area": measurement_area,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
            },
        )

        epm.add_experiment("ECHE_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list


def ECHE_CA(
    sequence_version: int = 4,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,
    solution_bubble_gas: str = "O2",
    solution_ph: float = 9.53,
    measurement_area: float = 0.071,  # 3mm diameter droplet
    liquid_volume_ml: float = 1.0,
    ref_type: str = "inhouse",
    ref_offset__V: float = 0.0,
    CA_potential: float = 1.23,
    CA_duration_sec: float = 4,
    CA_samplerate_sec: float = 0.05,
    OCV_duration: float = 1,
    gamry_i_range: str = "auto",
):

    epm = ExperimentPlanMaker()

    # (1) house keeping
    epm.add_experiment("ECHE_sub_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        epm.add_experiment(
            "ECHE_sub_startup",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "solution_bubble_gas": solution_bubble_gas,
                "liquid_volume_ml": liquid_volume_ml,
            },
        )

        # OCV
        epm.add_experiment(
            "ECHE_sub_OCV",
            {
                "Tval__s": OCV_duration,
                "SampleRate": 0.05,
            },
        )
        # CA1
        epm.add_experiment(
            "ECHE_sub_CA",
            {
                "CA_potential": CA_potential,
                "solution_ph": solution_ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "measurement_area": measurement_area,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "samplerate_sec": CA_samplerate_sec,
                "CA_duration_sec": CA_duration_sec,
                "gamry_i_range": gamry_i_range,
            },
        )

        epm.add_experiment("ECHE_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list


def ECHE_CA_led(
    sequence_version: int = 4,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,
    solution_bubble_gas: str = "O2",
    solution_ph: float = 9.53,
    measurement_area: float = 0.071,  # 3mm diameter droplet
    liquid_volume_ml: float = 1.0,
    ref_type: str = "inhouse",
    ref_offset__V: float = 0.0,
    CA_potential: float = 1.23,
    CA_duration_sec: float = 15,
    CA_samplerate_sec: float = 0.05,
    OCV_duration: float = 1,
    gamry_i_range: str = "auto",
    gamrychannelwait: int= -1,
    gamrychannelsend: int= 0,
    led_type: str = "front",
    led_date: str = "01/01/2000",
    led_names: list = ["doric_led1", "doric_led2", "doric_led3", "doric_led4"],
    led_wavelengths_nm: list = [385, 450, 515, 595],
    led_intensities_mw: list = [-1, -1, -1, -1],
    led_name_CA: str = "doric_led1",
    toggleCA_illum_duty: float = 0.5,
    toggleCA_illum_period: float = 1.0,
    toggleCA_dark_time_init: float = 0,
    toggleCA_illum_time: float = -1,
):

    epm = ExperimentPlanMaker()

    # (1) house keeping
    epm.add_experiment("ECHE_sub_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        epm.add_experiment(
            "ECHE_sub_startup",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "solution_bubble_gas": solution_bubble_gas,
                "liquid_volume_ml": liquid_volume_ml,
            },
        )
        # OCV
        epm.add_experiment(
            "ECHE_sub_OCV",
            {
                "Tval__s": OCV_duration,
                "SampleRate": 0.05,
            },
        )
        # CA1
        epm.add_experiment(
            "ECHE_sub_CA_led",
            {
                "CA_potential": CA_potential,
                "solution_ph": solution_ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "measurement_area": measurement_area,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "samplerate_sec": CA_samplerate_sec,
                "CA_duration_sec": CA_duration_sec,
                "gamry_i_range": gamry_i_range,
                "gamrychannelwait": gamrychannelwait,
                "gamrychannelsend": gamrychannelsend,
                "illumination_source": led_name_CA,
                "illumination_wavelength": led_wavelengths_nm[
                    led_names.index(led_name_CA)
                ],
                "illumination_intensity": led_intensities_mw[
                    led_names.index(led_name_CA)
                ],
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "toggle_illum_duty": toggleCA_illum_duty,
                "toggle_illum_period": toggleCA_illum_period,
                "toggle_illum_time": toggleCA_illum_time,
                "toggle_dark_time_init": toggleCA_dark_time_init,
            },
        )

        epm.add_experiment("ECHE_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list


def ECHE_CV_led(
    sequence_version: int = 4,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,
    solution_bubble_gas: str = "O2",
    solution_ph: float = 9.53,
    measurement_area: float = 0.071,  # 3mm diameter droplet
    liquid_volume_ml: float = 1.0,
    ref_type: str = "inhouse",
    ref_offset__V: float = 0.0,
    CV_Vinit_vsRHE: float = 1.23,
    CV_Vapex1_vsRHE: float = 0.73,
    CV_Vapex2_vsRHE: float = 1.73,
    CV_Vfinal_vsRHE: float = 1.73,
    CV_scanrate_voltsec: float = 0.02,
    CV_samplerate_mV: float = 1,
    CV_cycles: int = 1,
    preCV_duration: float = 3,
    gamry_i_range: str = "auto",
    gamrychannelwait: int= -1,
    gamrychannelsend: int= 0,
    led_type: str = "front",
    led_date: str = "01/01/2000",
    led_names: list = ["doric_led1", "doric_led2", "doric_led3", "doric_led4"],
    led_wavelengths_nm: list = [385, 450, 515, 595],
    led_intensities_mw: list = [-1, -1, -1, -1],
    led_name_CV: str = "doric_led1",
    toggleCV_illum_duty: float = 0.667,
    toggleCV_illum_period: float = 3.0,
    toggleCV_dark_time_init: float = 0,
    toggleCV_illum_time: float = -1,
):

    epm = ExperimentPlanMaker()

    # (1) house keeping
    epm.add_experiment("ECHE_sub_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        epm.add_experiment(
            "ECHE_sub_startup",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "solution_bubble_gas": solution_bubble_gas,
                "liquid_volume_ml": liquid_volume_ml,
            },
        )

        # CV1
        epm.add_experiment(
            "ECHE_sub_preCV",
            {
                "CA_potential": CV_Vinit_vsRHE
                - 1.0 * ref_offset__V
                - REF_TABLE[ref_type]
                - 0.059 * solution_ph,
                "samplerate_sec": CV_samplerate_mV / (CV_scanrate_voltsec * 1000),
                "CA_duration_sec": preCV_duration,
            },
        )
        epm.add_experiment(
            "ECHE_sub_CV_led",
            {
                "Vinit_vsRHE": CV_Vinit_vsRHE,
                "Vapex1_vsRHE": CV_Vapex1_vsRHE,
                "Vapex2_vsRHE": CV_Vapex2_vsRHE,
                "Vfinal_vsRHE": CV_Vfinal_vsRHE,
                "scanrate_voltsec": CV_scanrate_voltsec,
                "samplerate_sec": CV_samplerate_mV / (CV_scanrate_voltsec * 1000),
                "cycles": CV_cycles,
                "gamry_i_range": gamry_i_range,
                "gamrychannelwait": gamrychannelwait,
                "gamrychannelsend": gamrychannelsend,
                "solution_ph": solution_ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "measurement_area": measurement_area,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "illumination_source": led_name_CV,
                "illumination_wavelength": led_wavelengths_nm[
                    led_names.index(led_name_CV)
                ],
                "illumination_intensity": led_intensities_mw[
                    led_names.index(led_name_CV)
                ],
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "toggle_illum_duty": toggleCV_illum_duty,
                "toggle_illum_period": toggleCV_illum_period,
                "toggle_illum_time": toggleCV_illum_time,
                "toggle_dark_time_init": toggleCV_dark_time_init,
            },
        )

        epm.add_experiment("ECHE_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list


def ECHE_CP(
    sequence_version: int = 3,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,
    solution_bubble_gas: str = "O2",
    solution_ph: float = 9.53,
    measurement_area: float = 0.071,  # 3mm diameter droplet
    liquid_volume_ml: float = 1.0,
    ref_type: str = "inhouse",
    ref_offset__V: float = 0.0,
    CP_current: float = 0.000001,
    CP_duration_sec: float = 4,
    CP_samplerate_sec: float = 0.05,
    gamry_i_range: str = "auto",
):

    epm = ExperimentPlanMaker()

    # (1) house keeping
    epm.add_experiment("ECHE_sub_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        epm.add_experiment(
            "ECHE_sub_startup",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "solution_bubble_gas": solution_bubble_gas,
                "liquid_volume_ml": liquid_volume_ml,
            },
        )

        # CP1
        epm.add_experiment(
            "ECHE_sub_CP",
            {
                "CP_current": CP_current,
                "solution_ph": solution_ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "measurement_area": measurement_area,
                "reference_electrode_type": "NHE",
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "samplerate_sec": CP_samplerate_sec,
                "CP_duration_sec": CP_duration_sec,
                "gamry_i_range": gamry_i_range,
            },
        )

        epm.add_experiment("ECHE_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list


def ECHE_CP_led(
    sequence_version: int = 3,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,
    solution_bubble_gas: str = "O2",
    solution_ph: float = 9.53,
    measurement_area: float = 0.071,  # 3mm diameter droplet
    liquid_volume_ml: float = 1.0,
    ref_type: str = "inhouse",
    ref_offset__V: float = 0.0,
    CP_current: float = 0.000001,
    CP_duration_sec: float = 15,
    CP_samplerate_sec: float = 0.05,
    gamry_i_range: str = "auto",
    gamrychannelwait: int= -1,
    gamrychannelsend: int= 0,
    led_name_CP: str = "doric_led1",
    led_type: str = "front",
    led_date: str = "01/01/2000",
    led_names: list = ["doric_led1", "doric_led2", "doric_led3", "doric_led4"],
    led_wavelengths_nm: list = [385, 450, 515, 595],
    led_intensities_mw: list = [-1, -1, -1, -1],
    toggleCP_illum_duty: float = 0.5,
    toggleCP_illum_period: float = 1.0,
    toggleCP_dark_time_init: float = 0.0,
    toggleCP_illum_time: float = -1,
):

    epm = ExperimentPlanMaker()

    # (1) house keeping
    epm.add_experiment("ECHE_sub_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        epm.add_experiment(
            "ECHE_sub_startup",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "solution_bubble_gas": solution_bubble_gas,
                "liquid_volume_ml": liquid_volume_ml,
            },
        )
        # CP1
        epm.add_experiment(
            "ECHE_sub_CP_led",
            {
                "CP_current": CP_current,
                "solution_ph": solution_ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "measurement_area": measurement_area,
                "reference_electrode_type": "NHE",
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "samplerate_sec": CP_samplerate_sec,
                "CP_duration_sec": CP_duration_sec,
                "gamry_i_range": gamry_i_range,
                "gamrychannelwait": gamrychannelwait,
                "gamrychannelsend": gamrychannelsend,
                "illumination_source": led_name_CP,
                "illumination_wavelength": led_wavelengths_nm[
                    led_names.index(led_name_CP)
                ],
                "illumination_intensity": led_intensities_mw[
                    led_names.index(led_name_CP)
                ],
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "toggle_illum_duty": toggleCP_illum_duty,
                "toggle_illum_period": toggleCP_illum_period,
                "toggle_illum_time": toggleCP_illum_time,
                "toggle_dark_time_init": toggleCP_dark_time_init,
            },
        )

        epm.add_experiment("ECHE_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list

def ECHE_CVs_CAs(
    sequence_version: int = 1,
    plate_id: int = 6307,
    plate_sample_no_list: list = [2],
    reservoir_electrolyte: Electrolyte = "perchloric acid",
    reservoir_liquid_sample_no: int = 27,
    solution_bubble_gas: str = "O2",
    solution_ph: float = 1.24,
    ref_type: str = "inhouse",
    ref_offset__V: float = 0.0,
    measurement_area: float = 0.071,  # 3mm diameter droplet    reference_electrode_type: str = "NHE",
    liquid_volume_ml: float = 1.0,
    CV1_Vinit_vsRHE: float = 1.23,
    CV1_Vapex1_vsRHE: float = 1.23,
    CV1_Vapex2_vsRHE: float = 0.6,
    CV1_Vfinal_vsRHE: float = 0.6,
    CV1_scanrate_voltsec: float = 0.02,
    CV1_samplerate_mV: float = 1,
    CV1_cycles: int = 5,
    CV2_Vinit_vsRHE: float = 1.23,
    CV2_Vapex1_vsRHE: float = 1.23,
    CV2_Vapex2_vsRHE: float = 0.4,
    CV2_Vfinal_vsRHE: float = 0.4,
    CV2_scanrate_voltsec: float = 0.02,
    CV2_samplerate_mV: float = 1,
    CV2_cycles: int = 3,
    CV3_Vinit_vsRHE: float = 1.23,
    CV3_Vapex1_vsRHE: float = 1.23,
    CV3_Vapex2_vsRHE: float = 0,
    CV3_Vfinal_vsRHE: float = 0,
    CV3_scanrate_voltsec: float = 0.02,
    CV3_samplerate_mV: float = 1,
    CV3_cycles: int = 3,
    preCV_duration: float = 3,
    OCV_duration: float = 1,
    CA1_potential: float = 0.6,
    CA1_duration_sec: float = 300,
    CA2_potential: float = 0.4,
    CA2_duration_sec: float = 300,
    CA_samplerate_sec: float = 0.05,
    gamry_i_range: str = "auto",
):

    epm = ExperimentPlanMaker()

    # (1) house keeping
    epm.add_experiment("ECHE_sub_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        epm.add_experiment(
            "ECHE_sub_startup",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "liquid_volume_ml": liquid_volume_ml,
            },
        )

        # epm.add_experiment(
        #     "ECHE_sub_preCV",
        #     {
        #         "CA_potential": CV1_Vinit_vsRHE
        #         - 1.0 * ref_offset__V
        #         - REF_TABLE[ref_type]
        #         - 0.059 * solution_ph,
        #         "samplerate_sec": CV1_samplerate_mV / (CV1_scanrate_voltsec * 1000),
        #         "CA_duration_sec": preCV_duration,
        #     },
        # )
        # CV1
        epm.add_experiment(
            "ECHE_sub_CV",
            {
                "Vinit_vsRHE": CV1_Vinit_vsRHE,
                "Vapex1_vsRHE": CV1_Vapex1_vsRHE,
                "Vapex2_vsRHE": CV1_Vapex2_vsRHE,
                "Vfinal_vsRHE": CV1_Vfinal_vsRHE,
                "scanrate_voltsec": CV1_scanrate_voltsec,
                "samplerate_sec": CV1_samplerate_mV / (CV1_scanrate_voltsec * 1000),
                "cycles": CV1_cycles,
                "gamry_i_range": gamry_i_range,
                "solution_ph": solution_ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "measurement_area": measurement_area,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
            },
        )
        epm.add_experiment(
            "ECHE_sub_CV",
            {
                "Vinit_vsRHE": CV2_Vinit_vsRHE,
                "Vapex1_vsRHE": CV2_Vapex1_vsRHE,
                "Vapex2_vsRHE": CV2_Vapex2_vsRHE,
                "Vfinal_vsRHE": CV2_Vfinal_vsRHE,
                "scanrate_voltsec": CV2_scanrate_voltsec,
                "samplerate_sec": CV2_samplerate_mV / (CV2_scanrate_voltsec * 1000),
                "cycles": CV2_cycles,
                "gamry_i_range": gamry_i_range,
                "solution_ph": solution_ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "measurement_area": measurement_area,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
            },
        )
        # CV3
        epm.add_experiment(
            "ECHE_sub_CV",
            {
                "Vinit_vsRHE": CV3_Vinit_vsRHE,
                "Vapex1_vsRHE": CV3_Vapex1_vsRHE,
                "Vapex2_vsRHE": CV3_Vapex2_vsRHE,
                "Vfinal_vsRHE": CV3_Vfinal_vsRHE,
                "scanrate_voltsec": CV3_scanrate_voltsec,
                "samplerate_sec": CV3_samplerate_mV / (CV3_scanrate_voltsec * 1000),
                "cycles": CV3_cycles,
                "gamry_i_range": gamry_i_range,
                "solution_ph": solution_ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "measurement_area": measurement_area,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
            },
        )
        epm.add_experiment(
            "ECHE_sub_CA",
            {
                "CA_potential": CA1_potential,
                "solution_ph": solution_ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "measurement_area": measurement_area,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "samplerate_sec": CA_samplerate_sec,
                "CA_duration_sec": CA1_duration_sec,
                "gamry_i_range": gamry_i_range,
            },
        )

        # # OCV
        # epm.add_experiment(
        #     "ECHE_sub_OCV",
        #     {
        #         "Tval__s": OCV_duration,
        #         "SampleRate": 0.05,
        #     },
        # )
        # CA2
        epm.add_experiment(
            "ECHE_sub_CA",
            {
                "CA_potential": CA2_potential,
                "solution_ph": solution_ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "measurement_area": measurement_area,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "samplerate_sec": CA_samplerate_sec,
                "CA_duration_sec": CA2_duration_sec,
                "gamry_i_range": gamry_i_range,
            },
        )

        # epm.add_experiment(
        #     "ECHE_sub_preCV",
        #     {
        #         "CA_potential": CV3_Vinit_vsRHE
        #         - 1.0 * ref_offset__V
        #         - REF_TABLE[ref_type]
        #         - 0.059 * solution_ph,
        #         "samplerate_sec": CV3_samplerate_mV / (CV3_scanrate_voltsec * 1000),
        #         "CA_duration_sec": preCV_duration,
        #     },
        # )

        epm.add_experiment("ECHE_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list

def ECHE_cleanCVs_regCVs_CAs(
    sequence_version: int = 1,
    plate_id: int = 6307,
    plate_sample_no_list: list = [2],
    reservoir_electrolyte: Electrolyte = "perchloric acid",
    reservoir_liquid_sample_no: int = 27,
    solution_bubble_gas: str = "O2",
    solution_ph: float = 1.24,
    ref_type: str = "inhouse",
    ref_offset__V: float = 0.0,
    measurement_area: float = 0.071,  # 3mm diameter droplet    reference_electrode_type: str = "NHE",
    liquid_volume_ml: float = 1.0,
    CVcln_Vinit_vsRHE: float = 1.23,
    CVcln_Vapex1_vsRHE: float = 1.23,
    CVcln_Vapex2_vsRHE: float = 0,
    CVcln_Vfinal_vsRHE: float = 0,
    CVcln_scanrate_voltsec: float = 0.1,
    CVcln_samplerate_mV: float = 1,
    CVcln_cycles: int = 20,
    CV1_Vinit_vsRHE: float = 1.23,
    CV1_Vapex1_vsRHE: float = 1.23,
    CV1_Vapex2_vsRHE: float = 0.6,
    CV1_Vfinal_vsRHE: float = 0.6,
    CV1_scanrate_voltsec: float = 0.02,
    CV1_samplerate_mV: float = 1,
    CV1_cycles: int = 5,
    CV2_Vinit_vsRHE: float = 1.23,
    CV2_Vapex1_vsRHE: float = 1.23,
    CV2_Vapex2_vsRHE: float = 0.4,
    CV2_Vfinal_vsRHE: float = 0.4,
    CV2_scanrate_voltsec: float = 0.02,
    CV2_samplerate_mV: float = 1,
    CV2_cycles: int = 3,
    CV3_Vinit_vsRHE: float = 1.23,
    CV3_Vapex1_vsRHE: float = 1.23,
    CV3_Vapex2_vsRHE: float = 0,
    CV3_Vfinal_vsRHE: float = 0,
    CV3_scanrate_voltsec: float = 0.02,
    CV3_samplerate_mV: float = 1,
    CV3_cycles: int = 3,
    preCV_duration: float = 3,
    OCV_duration: float = 1,
    CA1_potential: float = 0.6,
    CA1_duration_sec: float = 300,
    CA2_potential: float = 0.4,
    CA2_duration_sec: float = 300,
    CA_samplerate_sec: float = 0.05,
    gamry_i_range: str = "auto",
):

    epm = ExperimentPlanMaker()

    # (1) house keeping
    epm.add_experiment("ECHE_sub_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        epm.add_experiment(
            "ECHE_sub_startup",
            {
                "solid_custom_position": "cell1_we",
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "liquid_volume_ml": liquid_volume_ml,
            },
        )

        # epm.add_experiment(
        #     "ECHE_sub_preCV",
        #     {
        #         "CA_potential": CV1_Vinit_vsRHE
        #         - 1.0 * ref_offset__V
        #         - REF_TABLE[ref_type]
        #         - 0.059 * solution_ph,
        #         "samplerate_sec": CV1_samplerate_mV / (CV1_scanrate_voltsec * 1000),
        #         "CA_duration_sec": preCV_duration,
        #     },
        # )
        #CVcleansweepfirst
        epm.add_experiment(
            "ECHE_sub_CV",
            {
                "Vinit_vsRHE": CVcln_Vinit_vsRHE,
                "Vapex1_vsRHE": CVcln_Vapex1_vsRHE,
                "Vapex2_vsRHE": CVcln_Vapex2_vsRHE,
                "Vfinal_vsRHE": CVcln_Vfinal_vsRHE,
                "scanrate_voltsec": CVcln_scanrate_voltsec,
                "samplerate_sec": CVcln_samplerate_mV / (CVcln_scanrate_voltsec * 1000),
                "cycles": CVcln_cycles,
                "gamry_i_range": gamry_i_range,
                "solution_ph": solution_ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "measurement_area": measurement_area,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
            },
        )


        # CV1
        epm.add_experiment(
            "ECHE_sub_CV",
            {
                "Vinit_vsRHE": CV1_Vinit_vsRHE,
                "Vapex1_vsRHE": CV1_Vapex1_vsRHE,
                "Vapex2_vsRHE": CV1_Vapex2_vsRHE,
                "Vfinal_vsRHE": CV1_Vfinal_vsRHE,
                "scanrate_voltsec": CV1_scanrate_voltsec,
                "samplerate_sec": CV1_samplerate_mV / (CV1_scanrate_voltsec * 1000),
                "cycles": CV1_cycles,
                "gamry_i_range": gamry_i_range,
                "solution_ph": solution_ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "measurement_area": measurement_area,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
            },
        )
        epm.add_experiment(
            "ECHE_sub_CV",
            {
                "Vinit_vsRHE": CV2_Vinit_vsRHE,
                "Vapex1_vsRHE": CV2_Vapex1_vsRHE,
                "Vapex2_vsRHE": CV2_Vapex2_vsRHE,
                "Vfinal_vsRHE": CV2_Vfinal_vsRHE,
                "scanrate_voltsec": CV2_scanrate_voltsec,
                "samplerate_sec": CV2_samplerate_mV / (CV2_scanrate_voltsec * 1000),
                "cycles": CV2_cycles,
                "gamry_i_range": gamry_i_range,
                "solution_ph": solution_ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "measurement_area": measurement_area,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
            },
        )
        # CV3
        epm.add_experiment(
            "ECHE_sub_CV",
            {
                "Vinit_vsRHE": CV3_Vinit_vsRHE,
                "Vapex1_vsRHE": CV3_Vapex1_vsRHE,
                "Vapex2_vsRHE": CV3_Vapex2_vsRHE,
                "Vfinal_vsRHE": CV3_Vfinal_vsRHE,
                "scanrate_voltsec": CV3_scanrate_voltsec,
                "samplerate_sec": CV3_samplerate_mV / (CV3_scanrate_voltsec * 1000),
                "cycles": CV3_cycles,
                "gamry_i_range": gamry_i_range,
                "solution_ph": solution_ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "measurement_area": measurement_area,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
            },
        )
        epm.add_experiment(
            "ECHE_sub_CA",
            {
                "CA_potential": CA1_potential,
                "solution_ph": solution_ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "measurement_area": measurement_area,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "samplerate_sec": CA_samplerate_sec,
                "CA_duration_sec": CA1_duration_sec,
                "gamry_i_range": gamry_i_range,
            },
        )

        # # OCV
        # epm.add_experiment(
        #     "ECHE_sub_OCV",
        #     {
        #         "Tval__s": OCV_duration,
        #         "SampleRate": 0.05,
        #     },
        # )
        # CA2
        epm.add_experiment(
            "ECHE_sub_CA",
            {
                "CA_potential": CA2_potential,
                "solution_ph": solution_ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "measurement_area": measurement_area,
                "ref_type": ref_type,
                "ref_offset__V": ref_offset__V,
                "samplerate_sec": CA_samplerate_sec,
                "CA_duration_sec": CA2_duration_sec,
                "gamry_i_range": gamry_i_range,
            },
        )

        # epm.add_experiment(
        #     "ECHE_sub_preCV",
        #     {
        #         "CA_potential": CV3_Vinit_vsRHE
        #         - 1.0 * ref_offset__V
        #         - REF_TABLE[ref_type]
        #         - 0.059 * solution_ph,
        #         "samplerate_sec": CV3_samplerate_mV / (CV3_scanrate_voltsec * 1000),
        #         "CA_duration_sec": preCV_duration,
        #     },
        # )

        epm.add_experiment("ECHE_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list
