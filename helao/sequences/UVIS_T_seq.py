"""
Sequence library for UVIS
"""

__all__ = ["UVIS_T", "UVIS_T_postseq"]

from helao.helpers.premodels import ExperimentPlanMaker


SEQUENCES = __all__


def UVIS_T(
    sequence_version: int = 5,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reference_mode: str = "internal",
    custom_position: str = "cell1_we",
    spec_n_avg: int = 5,
    spec_int_time_ms: int = 13,
    duration_sec: float = -1,
    specref_code: int = 1,
    led_type: str = "front",
    led_date: str = "n/a",
    led_names: list = ["doric_wled"],
    led_wavelengths_nm: list = [-1],
    led_intensities_mw: list = [0.432],
    toggle_is_shutter: bool = False,
    analysis_seq_uuid: str = "",
    use_z_motor: bool = False,
    cell_engaged_z: float = 1.5,
    cell_disengaged_z: float = 0,
):
    epm = ExperimentPlanMaker()
    epm.add_experiment("UVIS_sub_unloadall_customs", {})
    if use_z_motor:
        epm.add_experiment("ECHEUVIS_sub_disengage", {"clear_we": True, "clear_ce": True, "z_height": cell_disengaged_z})
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
    if use_z_motor:
        epm.add_experiment("ECHEUVIS_sub_engage", {"flow_we": False, "flow_ce": False, "z_height": cell_engaged_z})
    # dark ref
    epm.add_experiment(
        "UVIS_sub_measure",
        {
            "spec_type": "T",
            "spec_int_time_ms": spec_int_time_ms,
            "spec_n_avg": spec_n_avg,
            "duration_sec": duration_sec,
            "toggle_source": led_names[0],
            "toggle_is_shutter": toggle_is_shutter,
            "illumination_wavelength": led_wavelengths_nm[0],
            "illumination_intensity": led_intensities_mw[0],
            "illumination_intensity_date": led_date,
            "illumination_side": led_type,
            "technique_name": "T_UVVIS",
            "run_use": "ref_dark",
            "reference_mode": reference_mode,
        },
    )
    # light ref
    epm.add_experiment(
        "UVIS_sub_measure",
        {
            "spec_type": "T",
            "spec_int_time_ms": spec_int_time_ms,
            "spec_n_avg": spec_n_avg,
            "duration_sec": duration_sec,
            "toggle_source": led_names[0],
            "toggle_is_shutter": toggle_is_shutter,
            "illumination_wavelength": led_wavelengths_nm[0],
            "illumination_intensity": led_intensities_mw[0],
            "illumination_intensity_date": led_date,
            "illumination_side": led_type,
            "technique_name": "T_UVVIS",
            "run_use": "ref_light",
            "reference_mode": reference_mode,
        },
    )

    if use_z_motor:
        epm.add_experiment("ECHEUVIS_sub_disengage", {"clear_we": False, "clear_ce": False, "z_height": cell_disengaged_z})
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
        if use_z_motor:
            epm.add_experiment("ECHEUVIS_sub_engage", {"flow_we": False, "flow_ce": False, "z_height": cell_engaged_z})
        # perform transmission spec
        epm.add_experiment(
            "UVIS_sub_measure",
            {
                "spec_type": "T",
                "spec_int_time_ms": spec_int_time_ms,
                "spec_n_avg": spec_n_avg,
                "duration_sec": duration_sec,
                "toggle_source": led_names[0],
                "toggle_is_shutter": toggle_is_shutter,
                "illumination_wavelength": led_wavelengths_nm[0],
                "illumination_intensity": led_intensities_mw[0],
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "technique_name": "T_UVVIS",
                "run_use": "data",
                "reference_mode": reference_mode,
            },
        )
        if use_z_motor:
            epm.add_experiment("ECHEUVIS_sub_disengage", {"clear_we": False, "clear_ce": False, "z_height": cell_disengaged_z})

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
    if use_z_motor:
        epm.add_experiment("ECHEUVIS_sub_engage", {"flow_we": False, "flow_ce": False, "z_height": cell_engaged_z})
    # dark ref
    epm.add_experiment(
        "UVIS_sub_measure",
        {
            "spec_type": "T",
            "spec_int_time_ms": spec_int_time_ms,
            "spec_n_avg": spec_n_avg,
            "duration_sec": duration_sec,
            "toggle_source": led_names[0],
            "toggle_is_shutter": toggle_is_shutter,
            "illumination_wavelength": led_wavelengths_nm[0],
            "illumination_intensity": led_intensities_mw[0],
            "illumination_intensity_date": led_date,
            "illumination_side": led_type,
            "technique_name": "T_UVVIS",
            "run_use": "ref_dark",
            "reference_mode": reference_mode,
        },
    )
    # light ref
    epm.add_experiment(
        "UVIS_sub_measure",
        {
            "spec_type": "T",
            "spec_int_time_ms": spec_int_time_ms,
            "spec_n_avg": spec_n_avg,
            "duration_sec": duration_sec,
            "toggle_source": led_names[0],
            "toggle_is_shutter": toggle_is_shutter,
            "illumination_wavelength": led_wavelengths_nm[0],
            "illumination_intensity": led_intensities_mw[0],
            "illumination_intensity_date": led_date,
            "illumination_side": led_type,
            "technique_name": "T_UVVIS",
            "run_use": "ref_light",
            "reference_mode": reference_mode,
        },
    )

    if use_z_motor:
        epm.add_experiment("ECHEUVIS_sub_disengage", {"clear_we": False, "clear_ce": False, "z_height": cell_disengaged_z})
    epm.add_experiment("UVIS_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list


def UVIS_T_postseq(
    sequence_version: int = 1,
    analysis_seq_uuid: str = "",
    plate_id: int = 0,
    recent: bool = False,
):
    epm = ExperimentPlanMaker()
    epm.add_experiment(
        "UVIS_analysis_dry",
        {
            "sequence_uuid": analysis_seq_uuid,
            "plate_id": plate_id,
            "recent": recent,
        },
    )

    return epm.planned_experiments  # returns complete experiment list
