"""Sequence library for ECHE (electrochemistry without spectroscopy).

Each public ``ECHE_*`` function builds an experiment list via
``ExperimentPlanMaker``. Sequences typically chain sample movement,
startup, OCV/CV/CA/CP electrochemistry (including LED-toggled photo
variants), and shutdown sub-experiments from the ECHE experiment library.
"""

__all__ = [
    "ECHE_4CA_led_1CV_led",
    "ECHE_CA",
    "ECHE_CA_led",
    "ECHE_CP",
    "ECHE_CP_led",
    "ECHE_CV",
    "ECHE_CV_CA_CV",
    "ECHE_CV_led",
    "ECHE_CVs_CAs",
    "ECHE_cleanCVs_regCVs_CAs",
    "ECHE_move",
    "ECHE_movetosample",
]


from helao.core.models.echem_params import ref_offset
from helao.core.models.electrolyte import Electrolyte
from helao.helpers.lib_decorators import sequence
from helao.helpers.premodels import ExperimentPlanMaker

SEQUENCES = __all__


@sequence(version=1)
def ECHE_movetosample(
    plate_id: int = 1,
    plate_sample_no: int = 1,
) -> list:
    """Move the ECHE stage to a particular plate sample.

    Issues one ``ECHE_sub_movetosample`` followed by an ``ECHE_sub_shutdown``.

    Args:
        plate_id: Plate ID of the solid sample library.
        plate_sample_no: Solid-sample number on the plate to measure.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    epm.add(
        "ECHE_sub_movetosample",
        {
            #            "solid_custom_position": "cell1_we",
            "solid_plate_id": plate_id,
            "solid_sample_no": plate_sample_no,
        },
    )

    epm.add("ECHE_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list


@sequence(version=1)
def ECHE_move(
    move_x_mm: float = 1.0,
    move_y_mm: float = 1.0,
) -> list:
    """Issue a relative move on the ECHE motor stage.

    Calls ``ECHE_sub_rel_move`` then ``ECHE_sub_shutdown``.

    Args:
        move_x_mm: Target x position to move to (mm).
        move_y_mm: Target y position to move to (mm).

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    epm.add(
        "ECHE_sub_rel_move",
        {
            "offset_x_mm": move_x_mm,
            "offset_y_mm": move_y_mm,
        },
    )

    epm.add("ECHE_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list


@sequence(version=4)
def ECHE_4CA_led_1CV_led(
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
    gamrychannelwait: int = -1,
    gamrychannelsend: int = 0,
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
) -> list:
    """Run four photo-CA potentials followed by one photo-CV.

    For each sample: startup, OCV, four CA-LED steps with OCVs between them, then a CV-LED scan and shutdown.

    Args:
        plate_id: Plate ID of the solid sample library.
        plate_sample_no_list: List of solid-sample numbers on the plate to measure.
        reservoir_electrolyte: Name of the electrolyte in the reservoir.
        reservoir_liquid_sample_no: Liquid-sample number of the reservoir electrolyte.
        solution_bubble_gas: Gas used to bubble/sparge the solution.
        solution_ph: pH of the solution.
        ref_type: Reference-electrode type.
        ref_offset__V: Reference-electrode potential offset (V).
        measurement_area: Electrode measurement area (cm^2).
        ref_vs_nhe: Reference-electrode potential vs NHE (V).
        CA1_potential: Chronoamperometry 1 potential.
        CA1_duration_sec: Chronoamperometry 1 duration (s).
        CA2_potential: Chronoamperometry 2 potential.
        CA2_duration_sec: Chronoamperometry 2 duration (s).
        CA3_potential: Chronoamperometry 3 potential.
        CA3_duration_sec: Chronoamperometry 3 duration (s).
        CA4_potential: Chronoamperometry 4 potential.
        CA4_duration_sec: Chronoamperometry 4 duration (s).
        CA_samplerate_sec: Chronoamperometry sample rate (s).
        CV_Vinit_vsRHE: Cyclic-voltammetry initial potential vs RHE.
        CV_Vapex1_vsRHE: Cyclic-voltammetry apex-1 potential vs RHE.
        CV_Vapex2_vsRHE: Cyclic-voltammetry apex-2 potential vs RHE.
        CV_Vfinal_vsRHE: Cyclic-voltammetry final potential vs RHE.
        CV_scanrate_voltsec: Cyclic-voltammetry scan rate (V/s).
        CV_samplerate_mV: Cyclic-voltammetry sample rate (mV).
        CV_cycles: Cyclic-voltammetry cycle count.
        preCV_duration: Pre cyclic-voltammetry duration.
        OCV_duration: Open-circuit-voltage duration.
        gamry_i_range: Gamry potentiostat current range setting.
        gamrychannelwait: Gamry channel index to wait on before dispatching.
        gamrychannelsend: Gamry channel index to dispatch the action to.
        led_type: LED type identifier.
        led_date: LED calibration date.
        led_names: Identifiers of the LEDs to use.
        led_wavelengths_nm: LED peak wavelengths (nm).
        led_intensities_mw: LED intensities (mW).
        led_name_CA1: LED name chronoamperometry 1.
        led_name_CA2: LED name chronoamperometry 2.
        led_name_CA3: LED name chronoamperometry 3.
        led_name_CA4: LED name chronoamperometry 4.
        led_name_CV: LED name cyclic-voltammetry.
        toggleCA_illum_duty: Toggled chronoamperometry illumination duty cycle.
        toggleCA_illum_period: Toggled chronoamperometry illumination period.
        toggleCA_dark_time_init: Toggled chronoamperometry dark time initial.
        toggleCA_illum_time: Toggled chronoamperometry illumination time.
        toggleCV_illum_duty: Toggled cyclic-voltammetry illumination duty cycle.
        toggleCV_illum_period: Toggled cyclic-voltammetry illumination period.
        toggleCV_dark_time_init: Toggled cyclic-voltammetry dark time initial.
        toggleCV_illum_time: Toggled cyclic-voltammetry illumination time.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # (1) house keeping
    epm.add("ECHE_sub_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        epm.add(
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
        epm.add(
            "ECHE_sub_OCV",
            {
                "Tval__s": OCV_duration,
                "SampleRate": 0.05,
            },
        )
        # CA1
        epm.add(
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
        epm.add(
            "ECHE_sub_OCV",
            {
                "Tval__s": OCV_duration,
                "SampleRate": 0.05,
            },
        )
        # CA2
        epm.add(
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
        epm.add(
            "ECHE_sub_OCV",
            {
                "Tval__s": OCV_duration,
                "SampleRate": 0.05,
            },
        )
        # CA3
        epm.add(
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
        epm.add(
            "ECHE_sub_OCV",
            {
                "Tval__s": OCV_duration,
                "SampleRate": 0.05,
            },
        )
        # CA4
        epm.add(
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
        epm.add(
            "ECHE_sub_preCV",
            {
                "CA_potential": CV_Vinit_vsRHE - 1.0 * ref_vs_nhe - 0.059 * solution_ph,
                "samplerate_sec": CV_samplerate_mV / (CV_scanrate_voltsec * 1000),
                "CA_duration_sec": preCV_duration,
            },
        )
        epm.add(
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

        epm.add("ECHE_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list


@sequence(version=4)
def ECHE_CV_CA_CV(
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
) -> list:
    """Run a CV / CA / CV photo protocol on each sample.

    Loads sample, runs preCV, CA, then CV with LED toggling and shutdown.

    Args:
        plate_id: Plate ID of the solid sample library.
        plate_sample_no_list: List of solid-sample numbers on the plate to measure.
        reservoir_electrolyte: Name of the electrolyte in the reservoir.
        reservoir_liquid_sample_no: Liquid-sample number of the reservoir electrolyte.
        solution_bubble_gas: Gas used to bubble/sparge the solution.
        solution_ph: pH of the solution.
        ref_type: Reference-electrode type.
        ref_offset__V: Reference-electrode potential offset (V).
        measurement_area: Electrode measurement area (cm^2).
        liquid_volume_ml: Liquid volume to dispense (mL).
        CV1_Vinit_vsRHE: Cyclic-voltammetry 1 initial potential vs RHE.
        CV1_Vapex1_vsRHE: Cyclic-voltammetry 1 apex-1 potential vs RHE.
        CV1_Vapex2_vsRHE: Cyclic-voltammetry 1 apex-2 potential vs RHE.
        CV1_Vfinal_vsRHE: Cyclic-voltammetry 1 final potential vs RHE.
        CV1_scanrate_voltsec: Cyclic-voltammetry 1 scan rate (V/s).
        CV1_samplerate_mV: Cyclic-voltammetry 1 sample rate (mV).
        CV1_cycles: Cyclic-voltammetry 1 cycle count.
        preCV_duration: Pre cyclic-voltammetry duration.
        OCV_duration: Open-circuit-voltage duration.
        CA2_potential: Chronoamperometry 2 potential.
        CA2_duration_sec: Chronoamperometry 2 duration (s).
        CA_samplerate_sec: Chronoamperometry sample rate (s).
        CV3_Vinit_vsRHE: Cyclic-voltammetry 3 initial potential vs RHE.
        CV3_Vapex1_vsRHE: Cyclic-voltammetry 3 apex-1 potential vs RHE.
        CV3_Vapex2_vsRHE: Cyclic-voltammetry 3 apex-2 potential vs RHE.
        CV3_Vfinal_vsRHE: Cyclic-voltammetry 3 final potential vs RHE.
        CV3_scanrate_voltsec: Cyclic-voltammetry 3 scan rate (V/s).
        CV3_samplerate_mV: Cyclic-voltammetry 3 sample rate (mV).
        CV3_cycles: Cyclic-voltammetry 3 cycle count.
        gamry_i_range: Gamry potentiostat current range setting.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # (1) house keeping
    epm.add("ECHE_sub_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        epm.add(
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

        epm.add(
            "ECHE_sub_preCV",
            {
                "CA_potential": CV1_Vinit_vsRHE
                - 1.0 * ref_offset__V
                - ref_offset(ref_type)
                - 0.059 * solution_ph,
                "samplerate_sec": CV1_samplerate_mV / (CV1_scanrate_voltsec * 1000),
                "CA_duration_sec": preCV_duration,
            },
        )
        # CV1
        epm.add(
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
        epm.add(
            "ECHE_sub_OCV",
            {
                "Tval__s": OCV_duration,
                "SampleRate": 0.05,
            },
        )
        # CA2
        epm.add(
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

        epm.add(
            "ECHE_sub_preCV",
            {
                "CA_potential": CV3_Vinit_vsRHE
                - 1.0 * ref_offset__V
                - ref_offset(ref_type)
                - 0.059 * solution_ph,
                "samplerate_sec": CV3_samplerate_mV / (CV3_scanrate_voltsec * 1000),
                "CA_duration_sec": preCV_duration,
            },
        )
        # CV3
        epm.add(
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

        epm.add("ECHE_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list


@sequence(version=4)
def ECHE_CV(
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
) -> list:
    """Standalone CV scan for ECHE without illumination.

    Loads the sample, runs OCV, performs a CV scan, and shuts down.

    Args:
        plate_id: Plate ID of the solid sample library.
        plate_sample_no_list: List of solid-sample numbers on the plate to measure.
        reservoir_electrolyte: Name of the electrolyte in the reservoir.
        reservoir_liquid_sample_no: Liquid-sample number of the reservoir electrolyte.
        solution_bubble_gas: Gas used to bubble/sparge the solution.
        solution_ph: pH of the solution.
        measurement_area: Electrode measurement area (cm^2).
        ref_type: Reference-electrode type.
        ref_offset__V: Reference-electrode potential offset (V).
        CV1_Vinit_vsRHE: Cyclic-voltammetry 1 initial potential vs RHE.
        CV1_Vapex1_vsRHE: Cyclic-voltammetry 1 apex-1 potential vs RHE.
        CV1_Vapex2_vsRHE: Cyclic-voltammetry 1 apex-2 potential vs RHE.
        CV1_Vfinal_vsRHE: Cyclic-voltammetry 1 final potential vs RHE.
        CV1_scanrate_voltsec: Cyclic-voltammetry 1 scan rate (V/s).
        CV1_samplerate_mV: Cyclic-voltammetry 1 sample rate (mV).
        CV1_cycles: Cyclic-voltammetry 1 cycle count.
        preCV_duration: Pre cyclic-voltammetry duration.
        gamry_i_range: Gamry potentiostat current range setting.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # (1) house keeping
    epm.add("ECHE_sub_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        epm.add(
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

        epm.add(
            "ECHE_sub_preCV",
            {
                "CA_potential": CV1_Vinit_vsRHE
                - 1.0 * ref_offset__V
                - ref_offset(ref_type)
                - 0.059 * solution_ph,
                "samplerate_sec": CV1_samplerate_mV / (CV1_scanrate_voltsec * 1000),
                "CA_duration_sec": preCV_duration,
            },
        )
        # CV1
        epm.add(
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

        epm.add("ECHE_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list


@sequence(version=4)
def ECHE_CA(
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
) -> list:
    """Standalone CA hold for ECHE without illumination.

    Loads the sample, runs OCV, performs a CA hold, and shuts down.

    Args:
        plate_id: Plate ID of the solid sample library.
        plate_sample_no_list: List of solid-sample numbers on the plate to measure.
        reservoir_electrolyte: Name of the electrolyte in the reservoir.
        reservoir_liquid_sample_no: Liquid-sample number of the reservoir electrolyte.
        solution_bubble_gas: Gas used to bubble/sparge the solution.
        solution_ph: pH of the solution.
        measurement_area: Electrode measurement area (cm^2).
        ref_type: Reference-electrode type.
        ref_offset__V: Reference-electrode potential offset (V).
        CA_potential: Chronoamperometry potential.
        CA_duration_sec: Chronoamperometry duration (s).
        CA_samplerate_sec: Chronoamperometry sample rate (s).
        OCV_duration: Open-circuit-voltage duration.
        gamry_i_range: Gamry potentiostat current range setting.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # (1) house keeping
    epm.add("ECHE_sub_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        epm.add(
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
        epm.add(
            "ECHE_sub_OCV",
            {
                "Tval__s": OCV_duration,
                "SampleRate": 0.05,
            },
        )
        # CA1
        epm.add(
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

        epm.add("ECHE_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list


@sequence(version=4)
def ECHE_CA_led(
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
    gamrychannelwait: int = -1,
    gamrychannelsend: int = 0,
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
) -> list:
    """Photo-CA hold for ECHE with LED toggling.

    Loads the sample, runs OCV, performs a CA-LED hold, and shuts down.

    Args:
        plate_id: Plate ID of the solid sample library.
        plate_sample_no_list: List of solid-sample numbers on the plate to measure.
        reservoir_electrolyte: Name of the electrolyte in the reservoir.
        reservoir_liquid_sample_no: Liquid-sample number of the reservoir electrolyte.
        solution_bubble_gas: Gas used to bubble/sparge the solution.
        solution_ph: pH of the solution.
        measurement_area: Electrode measurement area (cm^2).
        ref_type: Reference-electrode type.
        ref_offset__V: Reference-electrode potential offset (V).
        CA_potential: Chronoamperometry potential.
        CA_duration_sec: Chronoamperometry duration (s).
        CA_samplerate_sec: Chronoamperometry sample rate (s).
        OCV_duration: Open-circuit-voltage duration.
        gamry_i_range: Gamry potentiostat current range setting.
        gamrychannelwait: Gamry channel index to wait on before dispatching.
        gamrychannelsend: Gamry channel index to dispatch the action to.
        led_type: LED type identifier.
        led_date: LED calibration date.
        led_names: Identifiers of the LEDs to use.
        led_wavelengths_nm: LED peak wavelengths (nm).
        led_intensities_mw: LED intensities (mW).
        led_name_CA: LED name chronoamperometry.
        toggleCA_illum_duty: Toggled chronoamperometry illumination duty cycle.
        toggleCA_illum_period: Toggled chronoamperometry illumination period.
        toggleCA_dark_time_init: Toggled chronoamperometry dark time initial.
        toggleCA_illum_time: Toggled chronoamperometry illumination time.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # (1) house keeping
    epm.add("ECHE_sub_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        epm.add(
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
        epm.add(
            "ECHE_sub_OCV",
            {
                "Tval__s": OCV_duration,
                "SampleRate": 0.05,
            },
        )
        # CA1
        epm.add(
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

        epm.add("ECHE_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list


@sequence(version=4)
def ECHE_CV_led(
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
    gamrychannelwait: int = -1,
    gamrychannelsend: int = 0,
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
) -> list:
    """Photo-CV for ECHE with LED toggling.

    Loads the sample, runs OCV, performs a CV-LED sweep, and shuts down.

    Args:
        plate_id: Plate ID of the solid sample library.
        plate_sample_no_list: List of solid-sample numbers on the plate to measure.
        reservoir_electrolyte: Name of the electrolyte in the reservoir.
        reservoir_liquid_sample_no: Liquid-sample number of the reservoir electrolyte.
        solution_bubble_gas: Gas used to bubble/sparge the solution.
        solution_ph: pH of the solution.
        measurement_area: Electrode measurement area (cm^2).
        ref_type: Reference-electrode type.
        ref_offset__V: Reference-electrode potential offset (V).
        CV_Vinit_vsRHE: Cyclic-voltammetry initial potential vs RHE.
        CV_Vapex1_vsRHE: Cyclic-voltammetry apex-1 potential vs RHE.
        CV_Vapex2_vsRHE: Cyclic-voltammetry apex-2 potential vs RHE.
        CV_Vfinal_vsRHE: Cyclic-voltammetry final potential vs RHE.
        CV_scanrate_voltsec: Cyclic-voltammetry scan rate (V/s).
        CV_samplerate_mV: Cyclic-voltammetry sample rate (mV).
        CV_cycles: Cyclic-voltammetry cycle count.
        preCV_duration: Pre cyclic-voltammetry duration.
        gamry_i_range: Gamry potentiostat current range setting.
        gamrychannelwait: Gamry channel index to wait on before dispatching.
        gamrychannelsend: Gamry channel index to dispatch the action to.
        led_type: LED type identifier.
        led_date: LED calibration date.
        led_names: Identifiers of the LEDs to use.
        led_wavelengths_nm: LED peak wavelengths (nm).
        led_intensities_mw: LED intensities (mW).
        led_name_CV: LED name cyclic-voltammetry.
        toggleCV_illum_duty: Toggled cyclic-voltammetry illumination duty cycle.
        toggleCV_illum_period: Toggled cyclic-voltammetry illumination period.
        toggleCV_dark_time_init: Toggled cyclic-voltammetry dark time initial.
        toggleCV_illum_time: Toggled cyclic-voltammetry illumination time.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # (1) house keeping
    epm.add("ECHE_sub_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        epm.add(
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
        epm.add(
            "ECHE_sub_preCV",
            {
                "CA_potential": CV_Vinit_vsRHE
                - 1.0 * ref_offset__V
                - ref_offset(ref_type)
                - 0.059 * solution_ph,
                "samplerate_sec": CV_samplerate_mV / (CV_scanrate_voltsec * 1000),
                "CA_duration_sec": preCV_duration,
            },
        )
        epm.add(
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

        epm.add("ECHE_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list


@sequence(version=3)
def ECHE_CP(
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
) -> list:
    """Standalone CP hold for ECHE without illumination.

    Loads the sample, runs OCV, performs a CP hold, and shuts down.

    Args:
        plate_id: Plate ID of the solid sample library.
        plate_sample_no_list: List of solid-sample numbers on the plate to measure.
        reservoir_electrolyte: Name of the electrolyte in the reservoir.
        reservoir_liquid_sample_no: Liquid-sample number of the reservoir electrolyte.
        solution_bubble_gas: Gas used to bubble/sparge the solution.
        solution_ph: pH of the solution.
        measurement_area: Electrode measurement area (cm^2).
        ref_type: Reference-electrode type.
        ref_offset__V: Reference-electrode potential offset (V).
        CP_current: Chronopotentiometry current.
        CP_duration_sec: Chronopotentiometry duration (s).
        CP_samplerate_sec: Chronopotentiometry sample rate (s).
        gamry_i_range: Gamry potentiostat current range setting.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # (1) house keeping
    epm.add("ECHE_sub_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        epm.add(
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
        epm.add(
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

        epm.add("ECHE_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list


@sequence(version=3)
def ECHE_CP_led(
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
    gamrychannelwait: int = -1,
    gamrychannelsend: int = 0,
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
) -> list:
    """Photo-CP hold for ECHE with LED toggling.

    Loads the sample, runs OCV, performs a CP-LED hold, and shuts down.

    Args:
        plate_id: Plate ID of the solid sample library.
        plate_sample_no_list: List of solid-sample numbers on the plate to measure.
        reservoir_electrolyte: Name of the electrolyte in the reservoir.
        reservoir_liquid_sample_no: Liquid-sample number of the reservoir electrolyte.
        solution_bubble_gas: Gas used to bubble/sparge the solution.
        solution_ph: pH of the solution.
        measurement_area: Electrode measurement area (cm^2).
        ref_type: Reference-electrode type.
        ref_offset__V: Reference-electrode potential offset (V).
        CP_current: Chronopotentiometry current.
        CP_duration_sec: Chronopotentiometry duration (s).
        CP_samplerate_sec: Chronopotentiometry sample rate (s).
        gamry_i_range: Gamry potentiostat current range setting.
        gamrychannelwait: Gamry channel index to wait on before dispatching.
        gamrychannelsend: Gamry channel index to dispatch the action to.
        led_name_CP: LED name chronopotentiometry.
        led_type: LED type identifier.
        led_date: LED calibration date.
        led_names: Identifiers of the LEDs to use.
        led_wavelengths_nm: LED peak wavelengths (nm).
        led_intensities_mw: LED intensities (mW).
        toggleCP_illum_duty: Toggled chronopotentiometry illumination duty cycle.
        toggleCP_illum_period: Toggled chronopotentiometry illumination period.
        toggleCP_dark_time_init: Toggled chronopotentiometry dark time initial.
        toggleCP_illum_time: Toggled chronopotentiometry illumination time.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # (1) house keeping
    epm.add("ECHE_sub_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        epm.add(
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
        epm.add(
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

        epm.add("ECHE_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list


@sequence(version=1)
def ECHE_CVs_CAs(
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
) -> list:
    """Run a CV list followed by a CA list per sample.

    Iterates over CV cycle/potential lists then CA potential/duration lists.

    Args:
        plate_id: Plate ID of the solid sample library.
        plate_sample_no_list: List of solid-sample numbers on the plate to measure.
        reservoir_electrolyte: Name of the electrolyte in the reservoir.
        reservoir_liquid_sample_no: Liquid-sample number of the reservoir electrolyte.
        solution_bubble_gas: Gas used to bubble/sparge the solution.
        solution_ph: pH of the solution.
        ref_type: Reference-electrode type.
        ref_offset__V: Reference-electrode potential offset (V).
        measurement_area: Electrode measurement area (cm^2).
        liquid_volume_ml: Liquid volume to dispense (mL).
        CV1_Vinit_vsRHE: Cyclic-voltammetry 1 initial potential vs RHE.
        CV1_Vapex1_vsRHE: Cyclic-voltammetry 1 apex-1 potential vs RHE.
        CV1_Vapex2_vsRHE: Cyclic-voltammetry 1 apex-2 potential vs RHE.
        CV1_Vfinal_vsRHE: Cyclic-voltammetry 1 final potential vs RHE.
        CV1_scanrate_voltsec: Cyclic-voltammetry 1 scan rate (V/s).
        CV1_samplerate_mV: Cyclic-voltammetry 1 sample rate (mV).
        CV1_cycles: Cyclic-voltammetry 1 cycle count.
        CV2_Vinit_vsRHE: Cyclic-voltammetry 2 initial potential vs RHE.
        CV2_Vapex1_vsRHE: Cyclic-voltammetry 2 apex-1 potential vs RHE.
        CV2_Vapex2_vsRHE: Cyclic-voltammetry 2 apex-2 potential vs RHE.
        CV2_Vfinal_vsRHE: Cyclic-voltammetry 2 final potential vs RHE.
        CV2_scanrate_voltsec: Cyclic-voltammetry 2 scan rate (V/s).
        CV2_samplerate_mV: Cyclic-voltammetry 2 sample rate (mV).
        CV2_cycles: Cyclic-voltammetry 2 cycle count.
        CV3_Vinit_vsRHE: Cyclic-voltammetry 3 initial potential vs RHE.
        CV3_Vapex1_vsRHE: Cyclic-voltammetry 3 apex-1 potential vs RHE.
        CV3_Vapex2_vsRHE: Cyclic-voltammetry 3 apex-2 potential vs RHE.
        CV3_Vfinal_vsRHE: Cyclic-voltammetry 3 final potential vs RHE.
        CV3_scanrate_voltsec: Cyclic-voltammetry 3 scan rate (V/s).
        CV3_samplerate_mV: Cyclic-voltammetry 3 sample rate (mV).
        CV3_cycles: Cyclic-voltammetry 3 cycle count.
        preCV_duration: Pre cyclic-voltammetry duration.
        OCV_duration: Open-circuit-voltage duration.
        CA1_potential: Chronoamperometry 1 potential.
        CA1_duration_sec: Chronoamperometry 1 duration (s).
        CA2_potential: Chronoamperometry 2 potential.
        CA2_duration_sec: Chronoamperometry 2 duration (s).
        CA_samplerate_sec: Chronoamperometry sample rate (s).
        gamry_i_range: Gamry potentiostat current range setting.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # (1) house keeping
    epm.add("ECHE_sub_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        epm.add(
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

        # epm.add(
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
        epm.add(
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
        epm.add(
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
        epm.add(
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
        epm.add(
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
        # epm.add(
        #     "ECHE_sub_OCV",
        #     {
        #         "Tval__s": OCV_duration,
        #         "SampleRate": 0.05,
        #     },
        # )
        # CA2
        epm.add(
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

        # epm.add(
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

        epm.add("ECHE_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list


@sequence(version=1)
def ECHE_cleanCVs_regCVs_CAs(
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
) -> list:
    """Run cleaning CVs followed by regular CVs and CAs.

    Loads each sample, runs N cleaning CV cycles, then the main CV list, then the CA list.

    Args:
        plate_id: Plate ID of the solid sample library.
        plate_sample_no_list: List of solid-sample numbers on the plate to measure.
        reservoir_electrolyte: Name of the electrolyte in the reservoir.
        reservoir_liquid_sample_no: Liquid-sample number of the reservoir electrolyte.
        solution_bubble_gas: Gas used to bubble/sparge the solution.
        solution_ph: pH of the solution.
        ref_type: Reference-electrode type.
        ref_offset__V: Reference-electrode potential offset (V).
        measurement_area: Electrode measurement area (cm^2).
        liquid_volume_ml: Liquid volume to dispense (mL).
        CVcln_Vinit_vsRHE: Cyclic-voltammetry cleaning initial potential vs RHE.
        CVcln_Vapex1_vsRHE: Cyclic-voltammetry cleaning apex-1 potential vs RHE.
        CVcln_Vapex2_vsRHE: Cyclic-voltammetry cleaning apex-2 potential vs RHE.
        CVcln_Vfinal_vsRHE: Cyclic-voltammetry cleaning final potential vs RHE.
        CVcln_scanrate_voltsec: Cyclic-voltammetry cleaning scan rate (V/s).
        CVcln_samplerate_mV: Cyclic-voltammetry cleaning sample rate (mV).
        CVcln_cycles: Cyclic-voltammetry cleaning cycle count.
        CV1_Vinit_vsRHE: Cyclic-voltammetry 1 initial potential vs RHE.
        CV1_Vapex1_vsRHE: Cyclic-voltammetry 1 apex-1 potential vs RHE.
        CV1_Vapex2_vsRHE: Cyclic-voltammetry 1 apex-2 potential vs RHE.
        CV1_Vfinal_vsRHE: Cyclic-voltammetry 1 final potential vs RHE.
        CV1_scanrate_voltsec: Cyclic-voltammetry 1 scan rate (V/s).
        CV1_samplerate_mV: Cyclic-voltammetry 1 sample rate (mV).
        CV1_cycles: Cyclic-voltammetry 1 cycle count.
        CV2_Vinit_vsRHE: Cyclic-voltammetry 2 initial potential vs RHE.
        CV2_Vapex1_vsRHE: Cyclic-voltammetry 2 apex-1 potential vs RHE.
        CV2_Vapex2_vsRHE: Cyclic-voltammetry 2 apex-2 potential vs RHE.
        CV2_Vfinal_vsRHE: Cyclic-voltammetry 2 final potential vs RHE.
        CV2_scanrate_voltsec: Cyclic-voltammetry 2 scan rate (V/s).
        CV2_samplerate_mV: Cyclic-voltammetry 2 sample rate (mV).
        CV2_cycles: Cyclic-voltammetry 2 cycle count.
        CV3_Vinit_vsRHE: Cyclic-voltammetry 3 initial potential vs RHE.
        CV3_Vapex1_vsRHE: Cyclic-voltammetry 3 apex-1 potential vs RHE.
        CV3_Vapex2_vsRHE: Cyclic-voltammetry 3 apex-2 potential vs RHE.
        CV3_Vfinal_vsRHE: Cyclic-voltammetry 3 final potential vs RHE.
        CV3_scanrate_voltsec: Cyclic-voltammetry 3 scan rate (V/s).
        CV3_samplerate_mV: Cyclic-voltammetry 3 sample rate (mV).
        CV3_cycles: Cyclic-voltammetry 3 cycle count.
        preCV_duration: Pre cyclic-voltammetry duration.
        OCV_duration: Open-circuit-voltage duration.
        CA1_potential: Chronoamperometry 1 potential.
        CA1_duration_sec: Chronoamperometry 1 duration (s).
        CA2_potential: Chronoamperometry 2 potential.
        CA2_duration_sec: Chronoamperometry 2 duration (s).
        CA_samplerate_sec: Chronoamperometry sample rate (s).
        gamry_i_range: Gamry potentiostat current range setting.

    Returns:
        List of planned experiments to dispatch.
    """

    epm = ExperimentPlanMaker()

    # (1) house keeping
    epm.add("ECHE_sub_unloadall_customs", {})

    for plate_sample in plate_sample_no_list:

        epm.add(
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

        # epm.add(
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
        # CVcleansweepfirst
        epm.add(
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
        epm.add(
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
        epm.add(
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
        epm.add(
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
        epm.add(
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
        # epm.add(
        #     "ECHE_sub_OCV",
        #     {
        #         "Tval__s": OCV_duration,
        #         "SampleRate": 0.05,
        #     },
        # )
        # CA2
        epm.add(
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

        # epm.add(
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

        epm.add("ECHE_sub_shutdown", {})

    return epm.planned_experiments  # returns complete experiment list
