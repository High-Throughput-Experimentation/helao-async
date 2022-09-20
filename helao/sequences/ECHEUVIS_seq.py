__all__ = [
    "ECHE_CV_led_spectrometer",
    "ECHE_CA_led_spectrometer",
    "ECHE_CP_led_spectrometer",
]


from helao.helpers.premodels import ExperimentPlanMaker
from helaocore.models.electrolyte import Electrolyte


SEQUENCES = __all__


def ECHE_CV_led_spectrometer(
    sequence_version: int = 3,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,
    solution_bubble_gas: str = "O2",
    solution_ph: float = 9.53,
    measurement_area: float = 0.071,  # 3mm diameter droplet
    liquid_volume_ml: float = 1.0,
    ref_vs_nhe: float = 0.21,
    CV_Vinit_vsRHE: float = 1.23,
    CV_Vapex1_vsRHE: float = 0.73,
    CV_Vapex2_vsRHE: float = 1.73,
    CV_Vfinal_vsRHE: float = 1.73,
    CV_scanrate_voltsec: float = 0.02,
    CV_samplerate_mV: float = 1,
    CV_cycles: int = 1,
    preCV_duration: float = 3,
    gamry_i_range: str = "auto",
    led_type: str = "front",
    led_date: str = "01/01/2000",
    led_names: list = ["doric_wled"],
    led_wavelengths_nm: list = [-1],
    led_intensities_mw: list = [0.432],
    led_name_CV: str = "doric_wled",
    toggleCV_illum_duty: float = 0.667,
    toggleCV_illum_period: float = 3.0,
    toggleCV_dark_time_init: float = 0,
    toggleCV_illum_time: float = -1,
    toggleSpec_duty: float = 0.167,
    toggleSpec_period: float = 0.6,
    toggleSpec_init_delay: float = 0.0,
    toggleSpec_time: float = -1,
    spec_int_time_ms: float = 15,
    spec_n_avg: int = 1,
    spec_technique: str = "T_UVVIS",
):

    pl = ExperimentPlanMaker()

    # (1) house keeping
    pl.add_experiment("ECHE_sub_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        pl.add_experiment(
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
        pl.add_experiment(
            "ECHE_sub_preCV",
            {
                "CA_potential": CV_Vinit_vsRHE - 1.0 * ref_vs_nhe - 0.059 * solution_ph,
                "samplerate_sec": CV_samplerate_mV / (CV_scanrate_voltsec * 1000),
                "CA_duration_sec": preCV_duration,
            },
        )
        pl.add_experiment(
            "ECHE_sub_CV_led_UVVIS",
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
                "reference_electrode_type": "NHE",
                "ref_vs_nhe": ref_vs_nhe,
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
                "toggle2_duty": toggleSpec_duty,
                "toggle2_period": toggleSpec_period,
                "toggle2_init_delay": toggleSpec_init_delay,
                "toggle2_time": toggleSpec_time,
                "spec_int_time_ms": spec_int_time_ms,
                "spec_n_avg": spec_n_avg,
                "spec_technique": spec_technique,
            },
        )

        pl.add_experiment("ECHE_sub_shutdown", {})

    return pl.experiment_plan_list  # returns complete experiment list


def ECHE_CA_led_spectrometer(
    sequence_version: int = 3,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,
    solution_bubble_gas: str = "O2",
    solution_ph: float = 9.53,
    measurement_area: float = 0.071,  # 3mm diameter droplet
    liquid_volume_ml: float = 1.0,
    ref_vs_nhe: float = 0.21,
    CA_potential_vsRHE: float = 1.23,
    CA_duration_sec: float = 15,
    CA_samplerate_sec: float = 0.05,
    OCV_duration: float = 1,
    gamry_i_range: str = "auto",
    led_type: str = "front",
    led_date: str = "01/01/2000",
    led_names: list = ["doric_wled"],
    led_wavelengths_nm: list = [-1],
    led_intensities_mw: list = [0.432],
    led_name_CA: str = "doric_wled",
    toggleCA_illum_duty: float = 0.5,
    toggleCA_illum_period: float = 1.0,
    toggleCA_dark_time_init: float = 0,
    toggleCA_illum_time: float = -1,
    toggleSpec_duty: float = 0.167,
    toggleSpec_period: float = 0.6,
    toggleSpec_init_delay: float = 0.0,
    toggleSpec_time: float = -1,
    spec_int_time_ms: float = 15,
    spec_n_avg: int = 1,
    spec_technique: str = "T_UVVIS",
):

    pl = ExperimentPlanMaker()

    # (1) house keeping
    pl.add_experiment("ECHE_sub_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        pl.add_experiment(
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
        pl.add_experiment(
            "ECHE_sub_OCV",
            {
                "Tval__s": OCV_duration,
                "SampleRate": 0.05,
            },
        )
        # CA1
        pl.add_experiment(
            "ECHE_sub_CA_led_UVVIS",
            {
                "CA_potential_vsRHE": CA_potential_vsRHE,
                "solution_ph": solution_ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "measurement_area": measurement_area,
                "reference_electrode_type": "NHE",
                "ref_vs_nhe": ref_vs_nhe,
                "samplerate_sec": CA_samplerate_sec,
                "CA_duration_sec": CA_duration_sec,
                "gamry_i_range": gamry_i_range,
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
                "toggle2_duty": toggleSpec_duty,
                "toggle2_period": toggleSpec_period,
                "toggle2_init_delay": toggleSpec_init_delay,
                "toggle2_time": toggleSpec_time,
                "spec_int_time_ms": spec_int_time_ms,
                "spec_n_avg": spec_n_avg,
                "spec_technique": spec_technique,
            },
        )

        pl.add_experiment("ECHE_sub_shutdown", {})

    return pl.experiment_plan_list  # returns complete experiment list


def ECHE_CP_led_spectrometer(
    sequence_version: int = 2,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,
    solution_bubble_gas: str = "O2",
    solution_ph: float = 9.53,
    measurement_area: float = 0.071,  # 3mm diameter droplet
    liquid_volume_ml: float = 1.0,
    ref_vs_nhe: float = 0.21,
    CP_current: float = 0.000001,
    CP_duration_sec: float = 15,
    CP_samplerate_sec: float = 0.05,
    gamry_i_range: str = "auto",
    led_type: str = "front",
    led_date: str = "01/01/2000",
    led_names: list = ["doric_wled"],
    led_wavelengths_nm: list = [-1],
    led_intensities_mw: list = [0.432],
    led_name_CP: str = "doric_wled",
    toggleCP_illum_duty: float = 0.5,
    toggleCP_illum_period: float = 1.0,
    toggleCP_dark_time_init: float = 0.0,
    toggleCP_illum_time: float = -1,
    toggleSpec_duty: float = 0.167,
    toggleSpec_period: float = 0.6,
    toggleSpec_init_delay: float = 0.0,
    toggleSpec_time: float = -1,
    spec_int_time_ms: float = 15,
    spec_n_avg: int = 1,
    spec_technique: str = "T_UVVIS",
):

    pl = ExperimentPlanMaker()

    # (1) house keeping
    pl.add_experiment("ECHE_sub_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        pl.add_experiment(
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
        pl.add_experiment(
            "ECHE_sub_CP_led_UVVIS",
            {
                "CP_current": CP_current,
                "solution_ph": solution_ph,
                "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
                "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                "solution_bubble_gas": solution_bubble_gas,
                "measurement_area": measurement_area,
                "reference_electrode_type": "NHE",
                "ref_vs_nhe": ref_vs_nhe,
                "samplerate_sec": CP_samplerate_sec,
                "CP_duration_sec": CP_duration_sec,
                "gamry_i_range": gamry_i_range,
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
                "toggle2_duty": toggleSpec_duty,
                "toggle2_period": toggleSpec_period,
                "toggle2_init_delay": toggleSpec_init_delay,
                "toggle2_time": toggleSpec_time,
                "spec_int_time_ms": spec_int_time_ms,
                "spec_n_avg": spec_n_avg,
                "spec_technique": spec_technique,
            },
        )

        pl.add_experiment("ECHE_sub_shutdown", {})

    return pl.experiment_plan_list  # returns complete experiment list
