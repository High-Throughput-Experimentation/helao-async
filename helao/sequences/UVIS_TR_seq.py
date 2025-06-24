"""
Sequence library for UVIS
"""

__all__ = ["UVIS_TR"]


from helao.helpers.premodels import ExperimentPlanMaker


SEQUENCES = __all__


def UVIS_TR(
    sequence_version: int = 3,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reference_mode: str = "internal",
    custom_position: str = "cell1_we",
    spec_n_avg: int = 1,
    spec_int_time_ms: int = 10,
    duration_sec: float = -1,
    specref_code: int = 1,
    led_type: str = "front",
    led_date: str = "n/a",
    led_names: list = ["wl_source"],
    led_wavelengths_nm: list = [-1],
    led_intensities_mw: list = [-1],
    toggle_is_shutter: bool = True,
    calc_ev_parts: list = [1.5, 2.0, 2.5, 3.0],
    calc_bin_width: int = 3,
    calc_window_length: int = 45,
    calc_poly_order: int = 4,
    calc_lower_wl: float = 370.0,
    calc_upper_wl: float = 1020.0,
):
    specs = ["T", "R"]
    epm = ExperimentPlanMaker()
    epm.add_experiment("UVIS_sub_unloadall_customs", {})
    epm.add_experiment(
        "UVIS_sub_setup_ref",
        {
            "reference_mode": reference_mode,
            "solid_custom_position": custom_position,
            "solid_plate_id": plate_id,
            "solid_sample_no": plate_sample_no_list[0],
            "specref_code": specref_code,
        },
    )
    # dark refs
    for spec_type in specs:
        epm.add_experiment(
            "UVIS_sub_measure",
            {
                "spec_type": spec_type,
                "spec_int_time_ms": spec_int_time_ms,
                "spec_n_avg": spec_n_avg,
                "duration_sec": duration_sec,
                "toggle_source": led_names[0],
                "toggle_is_shutter": toggle_is_shutter,
                "illumination_wavelength": led_wavelengths_nm[0],
                "illumination_intensity": led_intensities_mw[0],
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "technique_name": "TR_UVVIS",
                "run_use": "ref_dark",
                "reference_mode": reference_mode,
            },
        )
    # light ref
    for spec_type in specs:
        epm.add_experiment(
            "UVIS_sub_measure",
            {
                "spec_type": spec_type,
                "spec_int_time_ms": spec_int_time_ms,
                "spec_n_avg": spec_n_avg,
                "duration_sec": duration_sec,
                "toggle_source": led_names[0],
                "toggle_is_shutter": toggle_is_shutter,
                "illumination_wavelength": led_wavelengths_nm[0],
                "illumination_intensity": led_intensities_mw[0],
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "technique_name": "TR_UVVIS",
                "run_use": "ref_light",
                "reference_mode": reference_mode,
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
        for spec_type in specs:
            epm.add_experiment(
                "UVIS_sub_measure",
                {
                    "spec_type": spec_type,
                    "spec_int_time_ms": spec_int_time_ms,
                    "spec_n_avg": spec_n_avg,
                    "duration_sec": duration_sec,
                    "toggle_source": led_names[0],
                    "toggle_is_shutter": toggle_is_shutter,
                    "illumination_wavelength": led_wavelengths_nm[0],
                    "illumination_intensity": led_intensities_mw[0],
                    "illumination_intensity_date": led_date,
                    "illumination_side": led_type,
                    "technique_name": "TR_UVVIS",
                    "run_use": "data",
                    "reference_mode": reference_mode,
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
            "specref_code": specref_code,
        },
    )
    # dark refs
    for spec_type in specs:
        epm.add_experiment(
            "UVIS_sub_measure",
            {
                "spec_type": spec_type,
                "spec_int_time_ms": spec_int_time_ms,
                "spec_n_avg": spec_n_avg,
                "duration_sec": duration_sec,
                "toggle_source": led_names[0],
                "toggle_is_shutter": toggle_is_shutter,
                "illumination_wavelength": led_wavelengths_nm[0],
                "illumination_intensity": led_intensities_mw[0],
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "technique_name": "TR_UVVIS",
                "run_use": "ref_dark",
                "reference_mode": reference_mode,
            },
        )
    # light ref
    for spec_type in specs:
        epm.add_experiment(
            "UVIS_sub_measure",
            {
                "spec_type": spec_type,
                "spec_int_time_ms": spec_int_time_ms,
                "spec_n_avg": spec_n_avg,
                "duration_sec": duration_sec,
                "toggle_source": led_names[0],
                "toggle_is_shutter": toggle_is_shutter,
                "illumination_wavelength": led_wavelengths_nm[0],
                "illumination_intensity": led_intensities_mw[0],
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "technique_name": "TR_UVVIS",
                "run_use": "ref_light",
                "reference_mode": reference_mode,
            },
        )
    epm.add_experiment(
        "UVIS_calc_abs",
        {
            "ev_parts": calc_ev_parts,
            "bin_width": calc_bin_width,
            "window_length": calc_window_length,
            "poly_order": calc_poly_order,
            "lower_wl": calc_lower_wl,
            "upper_wl": calc_upper_wl,
        },
    )
    epm.add_experiment("UVIS_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list
