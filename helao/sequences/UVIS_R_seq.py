"""
Sequence library for UVIS
"""

__all__ = ["UVIS_R", "UVIS_R_postseq"]

from helao.helpers.premodels import ExperimentPlanMaker


SEQUENCES = __all__


def UVIS_R(
    sequence_version: int = 5,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reference_after_sample_list: list = [],
    reference_mode: str = "builtin",
    custom_position: str = "cell1_we",
    spec_n_avg: int = 5,
    spec_int_time_ms: int = 300,
    duration_sec: float = -1,
    specref_code: int = 1,
    led_type: str = "front",
    led_date: str = "n/a",
    led_names: list = ["xenon"],
    led_wavelengths_nm: list = [-1],
    led_intensities_mw: list = [-1],
    toggle_is_shutter: bool = False,
):
    epm = ExperimentPlanMaker()
    epm.add(
        "UVIS_measure_references",
        {
            "plate_id": plate_id,
            "custom_position": custom_position,
            "spec_n_avg": spec_n_avg,
            "spec_int_time_ms": spec_int_time_ms,
            "duration_sec": duration_sec,
            "specref_code": specref_code,
            "led_type": led_type,
            "led_date": led_date,
            "led_names": led_names,
            "led_wavelengths_nm": led_wavelengths_nm,
            "led_intensities_mw": led_intensities_mw,
            "toggle_is_shutter": toggle_is_shutter,
        },
    )

    for plate_sample in plate_sample_no_list:
        epm.add("UVIS_sub_unloadall_customs", {})
        epm.add(
            "UVIS_sub_startup",  # move to solid sample, assign to cell position
            {
                "solid_custom_position": custom_position,
                "solid_plate_id": plate_id,
                "solid_sample_no": plate_sample,
            },
        )
        # perform transmission spec
        epm.add(
            "UVIS_sub_measure",
            {
                "spec_type": "R",
                "spec_int_time_ms": spec_int_time_ms,
                "spec_n_avg": spec_n_avg,
                "duration_sec": duration_sec,
                "toggle_source": led_names[0],
                "toggle_is_shutter": toggle_is_shutter,
                "illumination_wavelength": led_wavelengths_nm[0],
                "illumination_intensity": led_intensities_mw[0],
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "technique_name": "R_UVVIS",
                "run_use": "data",
                "reference_mode": reference_mode,
            },
        )
        if plate_sample in reference_after_sample_list:
            epm.add(
                "UVIS_measure_references",
                {
                    "plate_id": plate_id,
                    "custom_position": custom_position,
                    "spec_n_avg": spec_n_avg,
                    "spec_int_time_ms": spec_int_time_ms,
                    "duration_sec": duration_sec,
                    "specref_code": specref_code,
                    "led_type": led_type,
                    "led_date": led_date,
                    "led_names": led_names,
                    "led_wavelengths_nm": led_wavelengths_nm,
                    "led_intensities_mw": led_intensities_mw,
                    "toggle_is_shutter": toggle_is_shutter,
                },
            )

    epm.add("UVIS_sub_unloadall_customs", {})
    epm.add("UVIS_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list


def UVIS_R_postseq(
    sequence_version: int = 1,
    analysis_seq_uuid: str = "",
    plate_id: int = 0,
    recent: bool = False,
):
    epm = ExperimentPlanMaker()
    epm.add(
        "UVIS_analysis_dry",
        {
            "sequence_uuid": analysis_seq_uuid,
            "plate_id": plate_id,
            "recent": recent,
        },
    )

    return epm.planned_experiments  # returns complete experiment list
