"""
Sequence library for ECHE
"""

__all__ = ["UVIS_T"]


from helao.helpers.premodels import ExperimentPlanMaker
from helaocore.models.electrolyte import Electrolyte


SEQUENCES = __all__


def UVIS_T(
    sequence_version: int = 2,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reference_mode: str = "internal",
    custom_position: str = "cell1_we",
    spec_n_avg: int = 1,
    spec_int_time_ms: int = 35,
    duration_sec: float = -1,
    led_type: str = "front",
    led_date: str = "n/a",
    led_names: list = ["doric_wled"],
    led_wavelengths_nm: list = [-1],
    led_intensities_mw: list = [-1],
):
    epm = ExperimentPlanMaker()
    epm.add_experiment("UVIS_sub_unloadall_customs", {})
    epm.add_experiment(
        "UVIS_sub_setup_ref",
        {
            "reference_mode": reference_mode,
            "solid_custom_position": custom_position,
            "solid_plate_id": plate_id,
            "solid_sample_no": plate_sample_no_list[0],
        },
    )
    # dark ref
    epm.add_experiment(
        "UVIS_sub_measure",
        {
            "spec_type": "T",
            "spec_int_time": spec_integration_time_ms,
            "spec_n_avg": spec_n_avg,
            "duration_sec": toggle_illum_time_sec,
            "toggle_source": led_names[0],
            "illumination_wavelength": led_wavelengths_nm[0],
            "illumination_intensity": led_intensities_mw[0],
            "illumination_intensity_date": led_date,
            "technique_name": "T_UVVIS",
            "run_use": "ref_dark",
        },
    )
    # light ref
    epm.add_experiment(
        "UVIS_sub_measure",
        {
            "spec_type": "T",
            "spec_int_time": spec_integration_time_ms,
            "spec_n_avg": spec_n_avg,
            "duration_sec": toggle_illum_time_sec,
            "toggle_source": led_names[0],
            "illumination_wavelength": led_wavelengths_nm[0],
            "illumination_intensity": led_intensities_mw[0],
            "illumination_intensity_date": led_date,
            "technique_name": "T_UVVIS",
            "run_use": "ref_light",
        },
    )

    for plate_sample in plate_sample_no_list:
        epm.add_experiment("UVIS_sub_unloadall_customs", {})
        epm.add_experiment(
            "UVIS_sub_startup",  # move to solid sample, assign to cell position
            {
                "solid_custom_position": custom_position,
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample,
            },
        )
        # perform transmission spec
        epm.add_experiment(
            "UVIS_sub_measure",
            {
                "spec_type": "T",
                "spec_int_time": spec_integration_time_ms,
                "spec_n_avg": spec_n_avg,
                "duration_sec": toggle_illum_time_sec,
                "toggle_source": led_names[0],
                "illumination_wavelength": led_wavelengths_nm[0],
                "illumination_intensity": led_intensities_mw[0],
                "illumination_intensity_date": led_date,
                "technique_name": "T_UVVIS",
                "run_use": "data",
            },
        )

    epm.add_experiment("UVIS_sub_unloadall_customs", {})
    epm.add_experiment(
        "UVIS_sub_setup_ref",
        {
            "reference_mode": reference_mode,
            "solid_custom_position": custom_position,
            "solid_plate_id": plate_id,
            "solid_sample_no": plate_sample_no_list[-1],
        },
    )
    # dark ref
    epm.add_experiment(
        "UVIS_sub_measure",
        {
            "spec_type": "T",
            "spec_int_time": spec_integration_time_ms,
            "spec_n_avg": spec_n_avg,
            "duration_sec": toggle_illum_time_sec,
            "toggle_source": led_names[0],
            "illumination_wavelength": led_wavelengths_nm[0],
            "illumination_intensity": led_intensities_mw[0],
            "illumination_intensity_date": led_date,
            "technique_name": "T_UVVIS",
            "run_use": "ref_dark",
        },
    )
    # light ref
    epm.add_experiment(
        "UVIS_sub_measure",
        {
            "spec_type": "T",
            "spec_int_time": spec_integration_time_ms,
            "spec_n_avg": spec_n_avg,
            "duration_sec": toggle_illum_time_sec,
            "toggle_source": led_names[0],
            "illumination_wavelength": led_wavelengths_nm[0],
            "illumination_intensity": led_intensities_mw[0],
            "illumination_intensity_date": led_date,
            "technique_name": "T_UVVIS",
            "run_use": "ref_light",
        },
    )
    epm.add_experiment("UVIS_sub_shutdown", {})

    return epm.experiment_plan_list  # returns complete experiment list
