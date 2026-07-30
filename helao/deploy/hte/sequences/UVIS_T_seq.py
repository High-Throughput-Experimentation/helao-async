"""Sequence library exposing UV-Vis transmission programs and a post-analysis."""

SEQUENCES = ["UVIS_T", "UVIS_T_postseq"]

from helao.helpers.lib_decorators import sequence
from helao.helpers.premodels import ExperimentPlanMaker


@sequence(version=5)
def UVIS_T(
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
) -> list:
    """Build a UV-Vis transmission sequence over plate samples.

    Optionally disengages the cell via the z-motor, sets up the reference,
    captures dark and light transmission references, then for each sample
    in ``plate_sample_no_list`` moves to the sample (engaging/disengaging
    the z-motor as configured) and captures transmission data. A second
    reference block and the shutdown experiment finish the sequence.

    Args:
        plate_id: Material library plate identifier.
        plate_sample_no_list: Sample numbers on the plate to measure.
        reference_mode: Reference mode passed to UVIS sub-experiments.
        custom_position: Solid custom position name to address the cell.
        spec_n_avg: Number of spectra averaged per acquisition.
        spec_int_time_ms: Spectrometer integration time in milliseconds.
        duration_sec: Per-measurement duration in seconds; negative uses
            the action's default.
        specref_code: Spectral reference code for ``UVIS_sub_setup_ref``.
        led_type: Illumination side label.
        led_date: Date string for the LED intensity calibration.
        led_names: Names of LEDs/sources used (first element drives toggle).
        led_wavelengths_nm: Wavelengths in nm corresponding to ``led_names``.
        led_intensities_mw: Intensities in mW corresponding to ``led_names``.
        toggle_is_shutter: Whether the toggle source acts as a shutter.
        analysis_seq_uuid: Optional analysis sequence UUID retained for
            downstream consumers.
        use_z_motor: Use the z-motor to engage/disengage the cell.
        cell_engaged_z: Cell engaged z-height in mm.
        cell_disengaged_z: Cell disengaged z-height in mm.

    Returns:
        list: Ordered list of planned ``Experiment`` objects.
    """
    epm = ExperimentPlanMaker()
    epm.add("UVIS_sub_unloadall_customs", {})
    if use_z_motor:
        epm.add(
            "ECHEUVIS_sub_disengage",
            {"clear_we": True, "clear_ce": True, "z_height": cell_disengaged_z},
        )
    epm.add(
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
        epm.add(
            "ECHEUVIS_sub_engage",
            {"flow_we": False, "flow_ce": False, "z_height": cell_engaged_z},
        )
    # dark ref
    epm.add(
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
    epm.add(
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
        epm.add(
            "ECHEUVIS_sub_disengage",
            {"clear_we": False, "clear_ce": False, "z_height": cell_disengaged_z},
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
        if use_z_motor:
            epm.add(
                "ECHEUVIS_sub_engage",
                {"flow_we": False, "flow_ce": False, "z_height": cell_engaged_z},
            )
        # perform transmission spec
        epm.add(
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
            epm.add(
                "ECHEUVIS_sub_disengage",
                {"clear_we": False, "clear_ce": False, "z_height": cell_disengaged_z},
            )

    epm.add("UVIS_sub_unloadall_customs", {})
    epm.add(
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
        epm.add(
            "ECHEUVIS_sub_engage",
            {"flow_we": False, "flow_ce": False, "z_height": cell_engaged_z},
        )
    # dark ref
    epm.add(
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
    epm.add(
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
        epm.add(
            "ECHEUVIS_sub_disengage",
            {"clear_we": False, "clear_ce": False, "z_height": cell_disengaged_z},
        )
    epm.add("UVIS_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list


@sequence(version=1)
def UVIS_T_postseq(
    analysis_seq_uuid: str = "",
    plate_id: int = 0,
    recent: bool = False,
) -> list:
    """Build a post-sequence that runs the dry UVIS analysis.

    Args:
        analysis_seq_uuid: UUID of the source sequence to analyze.
        plate_id: Plate identifier scoping the analysis.
        recent: Restrict to the most recent matching run when True.

    Returns:
        list: Ordered list of planned ``Experiment`` objects.
    """
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
