__all__ = [
    "ECHEUVIS_CV_led",
    "ECHEUVIS_CA_led",
    "ECHEUVIS_multiCA_led",
    "ECHEUVIS_CP_led",
    "ECHEUVIS_postseq",
    "ECHEUVIS_diagnostic_CV"
]

import random
from typing import List
from helao.helpers.premodels import ExperimentPlanMaker
from helao.helpers.spec_map import SPEC_MAP
from helaocore.models.electrolyte import Electrolyte


SEQUENCES = __all__


def ECHEUVIS_CV_led(
    sequence_version: int = 5,
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
    spec_ref_duration: float = 2,
    spec_int_time_ms: float = 15,
    spec_n_avg: int = 1,
    spec_technique: str = "T_UVVIS",
    calc_ev_parts: list = [1.5, 2.0, 2.5, 3.0],
    calc_bin_width: int = 3,
    calc_window_length: int = 45,
    calc_poly_order: int = 4,
    calc_lower_wl: float = 370.0,
    calc_upper_wl: float = 1020.0,
    use_z_motor: bool = False,
    cell_engaged_z: float = 2.5,
    cell_disengaged_z: float = 0,
    cell_vent_wait: float = 10.0,
    cell_fill_wait: float = 30.0,
):
    epm = ExperimentPlanMaker()

    epm.add_experiment("ECHE_sub_unloadall_customs", {})
    if use_z_motor:
        epm.add_experiment(
            "ECHEUVIS_sub_disengage",
            {
                "clear_we": True,
                "clear_ce": False,
                "z_height": cell_disengaged_z,
                "vent_wait": cell_vent_wait,
            },
        )
    else:
        epm.add_experiment(
            "ECHEUVIS_sub_interrupt",
            {"reason": "Stop flow and prepare for xy motion to ref location."},
        )
    epm.add_experiment(
        "UVIS_sub_setup_ref",
        {
            "reference_mode": "builtin",
            "solid_custom_position": "cell1_we",
            "solid_plate_id": plate_id,
            "solid_sample_no": plate_sample_no_list[0],
            "specref_code": 1,
        },
    )
    if use_z_motor:
        epm.add_experiment(
            "ECHEUVIS_sub_engage",
            {
                "flow_we": True,
                "flow_ce": True,
                "z_height": cell_engaged_z,
                "fill_wait": cell_fill_wait,
            },
        )
    else:
        epm.add_experiment(
            "ECHEUVIS_sub_interrupt",
            {"reason": "Restore flow and prepare for reference measurement."},
        )

    # dark ref
    for st in SPEC_MAP[spec_technique]:
        epm.add_experiment(
            "UVIS_sub_measure",
            {
                "spec_type": st,
                "spec_int_time_ms": spec_int_time_ms,
                "spec_n_avg": spec_n_avg,
                "duration_sec": spec_ref_duration,
                "toggle_source": led_names[0],
                "toggle_is_shutter": False,
                "illumination_wavelength": led_wavelengths_nm[0],
                "illumination_intensity": led_intensities_mw[0],
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "technique_name": spec_technique,
                "run_use": "ref_dark",
                "reference_mode": "builtin",
            },
        )
    # light ref
    for st in SPEC_MAP[spec_technique]:
        epm.add_experiment(
            "UVIS_sub_measure",
            {
                "spec_type": st,
                "spec_int_time_ms": spec_int_time_ms,
                "spec_n_avg": spec_n_avg,
                "duration_sec": spec_ref_duration,
                "toggle_source": led_names[0],
                "toggle_is_shutter": False,
                "illumination_wavelength": led_wavelengths_nm[0],
                "illumination_intensity": led_intensities_mw[0],
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "technique_name": spec_technique,
                "run_use": "ref_light",
                "reference_mode": "builtin",
            },
        )
    if use_z_motor:
        epm.add_experiment(
            "ECHEUVIS_sub_disengage",
            {
                "clear_we": True,
                "clear_ce": False,
                "z_height": cell_disengaged_z,
                "vent_wait": cell_vent_wait,
            },
        )
    else:
        epm.add_experiment(
            "ECHEUVIS_sub_interrupt",
            {"reason": "Stop flow and prepare for xy motion to starting sample."},
        )

    for i, plate_sample in enumerate(plate_sample_no_list):
        if i > 0 and use_z_motor:
            epm.add_experiment(
                "ECHEUVIS_sub_disengage",
                {
                    "clear_we": True,
                    "clear_ce": False,
                    "z_height": cell_disengaged_z,
                    "vent_wait": cell_vent_wait,
                },
            )

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

        if use_z_motor:
            epm.add_experiment(
                "ECHEUVIS_sub_engage",
                {
                    "flow_we": True,
                    "flow_ce": True,
                    "z_height": cell_engaged_z,
                    "fill_wait": cell_fill_wait,
                },
            )
        else:
            if i == 0:  # initial sample
                epm.add_experiment(
                    "ECHEUVIS_sub_interrupt",
                    {"reason": "Restore flow and prepare for sample measurement."},
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
            "ECHEUVIS_sub_CV_led",
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

    epm.add_experiment("ECHE_sub_unloadall_customs", {})
    if use_z_motor:
        epm.add_experiment(
            "ECHEUVIS_sub_disengage",
            {
                "clear_we": True,
                "clear_ce": False,
                "z_height": cell_disengaged_z,
                "vent_wait": cell_vent_wait,
            },
        )
    else:
        epm.add_experiment(
            "ECHEUVIS_sub_interrupt",
            {"reason": "Stop flow and prepare for xy motion to ref location."},
        )
    epm.add_experiment(
        "UVIS_sub_setup_ref",
        {
            "reference_mode": "builtin",
            "solid_custom_position": "cell1_we",
            "solid_plate_id": plate_id,
            "solid_sample_no": plate_sample_no_list[-1],
            "specref_code": 1,
        },
    )

    if use_z_motor:
        epm.add_experiment(
            "ECHEUVIS_sub_engage",
            {
                "flow_we": True,
                "flow_ce": True,
                "z_height": cell_engaged_z,
                "fill_wait": cell_fill_wait,
            },
        )
    else:
        epm.add_experiment(
            "ECHEUVIS_sub_interrupt",
            {"reason": "Restore flow and prepare for reference measurement."},
        )
    # dark ref
    for st in SPEC_MAP[spec_technique]:
        epm.add_experiment(
            "UVIS_sub_measure",
            {
                "spec_type": st,
                "spec_int_time_ms": spec_int_time_ms,
                "spec_n_avg": spec_n_avg,
                "duration_sec": spec_ref_duration,
                "toggle_source": led_names[0],
                "toggle_is_shutter": False,
                "illumination_wavelength": led_wavelengths_nm[0],
                "illumination_intensity": led_intensities_mw[0],
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "technique_name": spec_technique,
                "run_use": "ref_dark",
                "reference_mode": "builtin",
            },
        )
    # light ref
    for st in SPEC_MAP[spec_technique]:
        epm.add_experiment(
            "UVIS_sub_measure",
            {
                "spec_type": st,
                "spec_int_time_ms": spec_int_time_ms,
                "spec_n_avg": spec_n_avg,
                "duration_sec": spec_ref_duration,
                "toggle_source": led_names[0],
                "toggle_is_shutter": False,
                "illumination_wavelength": led_wavelengths_nm[0],
                "illumination_intensity": led_intensities_mw[0],
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "technique_name": spec_technique,
                "run_use": "ref_light",
                "reference_mode": "builtin",
            },
        )

    if use_z_motor:
        # leave cell sealed w/solution for storage
        epm.add_experiment(
            "ECHEUVIS_sub_engage",
            {
                "flow_we": False,
                "flow_ce": False,
                "z_height": cell_engaged_z,
                "fill_wait": cell_fill_wait,
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
    epm.add_experiment("ECHE_sub_shutdown", {})

    return epm.experiment_plan_list  # returns complete experiment list


def ECHEUVIS_CA_led(
    sequence_version: int = 5,
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
    spec_ref_duration: float = 2,
    spec_int_time_ms: float = 15,
    spec_n_avg: int = 1,
    spec_technique: str = "T_UVVIS",
    calc_ev_parts: list = [1.5, 2.0, 2.5, 3.0],
    calc_bin_width: int = 3,
    calc_window_length: int = 45,
    calc_poly_order: int = 4,
    calc_lower_wl: float = 370.0,
    calc_upper_wl: float = 1020.0,
    use_z_motor: bool = False,
    cell_engaged_z: float = 2.5,
    cell_disengaged_z: float = 0,
    cell_vent_wait: float = 10.0,
    cell_fill_wait: float = 30.0,
):
    epm = ExperimentPlanMaker()

    epm.add_experiment("ECHE_sub_unloadall_customs", {})
    if use_z_motor:
        epm.add_experiment(
            "ECHEUVIS_sub_disengage",
            {
                "clear_we": True,
                "clear_ce": False,
                "z_height": cell_disengaged_z,
                "vent_wait": cell_vent_wait,
            },
        )
    else:
        epm.add_experiment(
            "ECHEUVIS_sub_interrupt",
            {"reason": "Stop flow and prepare for xy motion to ref location."},
        )
    epm.add_experiment(
        "UVIS_sub_setup_ref",
        {
            "reference_mode": "builtin",
            "solid_custom_position": "cell1_we",
            "solid_plate_id": plate_id,
            "solid_sample_no": plate_sample_no_list[0],
            "specref_code": 1,
        },
    )
    if use_z_motor:
        epm.add_experiment(
            "ECHEUVIS_sub_engage",
            {
                "flow_we": True,
                "flow_ce": True,
                "z_height": cell_engaged_z,
                "fill_wait": cell_fill_wait,
            },
        )
    else:
        epm.add_experiment(
            "ECHEUVIS_sub_interrupt",
            {"reason": "Restore flow and prepare for reference measurement."},
        )

    # dark ref
    for st in SPEC_MAP[spec_technique]:
        epm.add_experiment(
            "UVIS_sub_measure",
            {
                "spec_type": st,
                "spec_int_time_ms": spec_int_time_ms,
                "spec_n_avg": spec_n_avg,
                "duration_sec": spec_ref_duration,
                "toggle_source": led_names[0],
                "toggle_is_shutter": False,
                "illumination_wavelength": led_wavelengths_nm[0],
                "illumination_intensity": led_intensities_mw[0],
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "technique_name": spec_technique,
                "run_use": "ref_dark",
                "reference_mode": "builtin",
            },
        )
    # light ref
    for st in SPEC_MAP[spec_technique]:
        epm.add_experiment(
            "UVIS_sub_measure",
            {
                "spec_type": st,
                "spec_int_time_ms": spec_int_time_ms,
                "spec_n_avg": spec_n_avg,
                "duration_sec": spec_ref_duration,
                "toggle_source": led_names[0],
                "toggle_is_shutter": False,
                "illumination_wavelength": led_wavelengths_nm[0],
                "illumination_intensity": led_intensities_mw[0],
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "technique_name": spec_technique,
                "run_use": "ref_light",
                "reference_mode": "builtin",
            },
        )
    if use_z_motor:
        epm.add_experiment(
            "ECHEUVIS_sub_disengage",
            {
                "clear_we": True,
                "clear_ce": False,
                "z_height": cell_disengaged_z,
                "vent_wait": cell_vent_wait,
            },
        )
    else:
        epm.add_experiment(
            "ECHEUVIS_sub_interrupt",
            {"reason": "Stop flow and prepare for xy motion to starting sample."},
        )

    for i, plate_sample in enumerate(plate_sample_no_list):
        if i > 0 and use_z_motor:
            epm.add_experiment(
                "ECHEUVIS_sub_disengage",
                {
                    "clear_we": True,
                    "clear_ce": False,
                    "z_height": cell_disengaged_z,
                    "vent_wait": cell_vent_wait,
                },
            )

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

        if use_z_motor:
            epm.add_experiment(
                "ECHEUVIS_sub_engage",
                {
                    "flow_we": True,
                    "flow_ce": True,
                    "z_height": cell_engaged_z,
                    "fill_wait": cell_fill_wait,
                },
            )
        else:
            if i == 0:  # initial sample
                epm.add_experiment(
                    "ECHEUVIS_sub_interrupt",
                    {"reason": "Restore flow and prepare for sample measurement."},
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
            "ECHEUVIS_sub_CA_led",
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

    epm.add_experiment("ECHE_sub_unloadall_customs", {})
    if use_z_motor:
        epm.add_experiment(
            "ECHEUVIS_sub_disengage",
            {
                "clear_we": True,
                "clear_ce": False,
                "z_height": cell_disengaged_z,
                "vent_wait": cell_vent_wait,
            },
        )
    else:
        epm.add_experiment(
            "ECHEUVIS_sub_interrupt",
            {"reason": "Stop flow and prepare for xy motion to ref location."},
        )
    epm.add_experiment(
        "UVIS_sub_setup_ref",
        {
            "reference_mode": "builtin",
            "solid_custom_position": "cell1_we",
            "solid_plate_id": plate_id,
            "solid_sample_no": plate_sample_no_list[-1],
            "specref_code": 1,
        },
    )
    if use_z_motor:
        epm.add_experiment(
            "ECHEUVIS_sub_engage",
            {
                "flow_we": True,
                "flow_ce": True,
                "z_height": cell_engaged_z,
                "fill_wait": cell_fill_wait,
            },
        )
    else:
        epm.add_experiment(
            "ECHEUVIS_sub_interrupt",
            {"reason": "Restore flow and prepare for reference measurement."},
        )
    # dark ref
    for st in SPEC_MAP[spec_technique]:
        epm.add_experiment(
            "UVIS_sub_measure",
            {
                "spec_type": st,
                "spec_int_time_ms": spec_int_time_ms,
                "spec_n_avg": spec_n_avg,
                "duration_sec": spec_ref_duration,
                "toggle_source": led_names[0],
                "toggle_is_shutter": False,
                "illumination_wavelength": led_wavelengths_nm[0],
                "illumination_intensity": led_intensities_mw[0],
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "technique_name": spec_technique,
                "run_use": "ref_dark",
                "reference_mode": "builtin",
            },
        )
    # light ref
    for st in SPEC_MAP[spec_technique]:
        epm.add_experiment(
            "UVIS_sub_measure",
            {
                "spec_type": st,
                "spec_int_time_ms": spec_int_time_ms,
                "spec_n_avg": spec_n_avg,
                "duration_sec": spec_ref_duration,
                "toggle_source": led_names[0],
                "toggle_is_shutter": False,
                "illumination_wavelength": led_wavelengths_nm[0],
                "illumination_intensity": led_intensities_mw[0],
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "technique_name": spec_technique,
                "run_use": "ref_light",
                "reference_mode": "builtin",
            },
        )
    if use_z_motor:
        # leave cell sealed w/solution for storage
        epm.add_experiment(
            "ECHEUVIS_sub_engage",
            {
                "flow_we": False,
                "flow_ce": False,
                "z_height": cell_engaged_z,
                "fill_wait": cell_fill_wait,
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
    epm.add_experiment("ECHE_sub_shutdown", {})

    return epm.experiment_plan_list  # returns complete experiment list


def ECHEUVIS_CP_led(
    sequence_version: int = 5,
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
    spec_ref_duration: float = 2,
    spec_int_time_ms: float = 15,
    spec_n_avg: int = 1,
    spec_technique: str = "T_UVVIS",
    calc_ev_parts: list = [1.5, 2.0, 2.5, 3.0],
    calc_bin_width: int = 3,
    calc_window_length: int = 45,
    calc_poly_order: int = 4,
    calc_lower_wl: float = 370.0,
    calc_upper_wl: float = 1020.0,
    use_z_motor: bool = False,
    cell_engaged_z: float = 2.5,
    cell_disengaged_z: float = 0,
    cell_vent_wait: float = 10.0,
    cell_fill_wait: float = 30.0,
):
    epm = ExperimentPlanMaker()

    epm.add_experiment("ECHE_sub_unloadall_customs", {})
    if use_z_motor:
        epm.add_experiment(
            "ECHEUVIS_sub_disengage",
            {
                "clear_we": True,
                "clear_ce": False,
                "z_height": cell_disengaged_z,
                "vent_wait": cell_vent_wait,
            },
        )
    else:
        epm.add_experiment(
            "ECHEUVIS_sub_interrupt",
            {"reason": "Stop flow and prepare for xy motion to ref location."},
        )
    epm.add_experiment(
        "UVIS_sub_setup_ref",
        {
            "reference_mode": "builtin",
            "solid_custom_position": "cell1_we",
            "solid_plate_id": plate_id,
            "solid_sample_no": plate_sample_no_list[0],
            "specref_code": 1,
        },
    )
    if use_z_motor:
        epm.add_experiment(
            "ECHEUVIS_sub_engage",
            {
                "flow_we": True,
                "flow_ce": True,
                "z_height": cell_engaged_z,
                "fill_wait": cell_fill_wait,
            },
        )
    else:
        epm.add_experiment(
            "ECHEUVIS_sub_interrupt",
            {"reason": "Restore flow and prepare for reference measurement."},
        )

    # dark ref
    for st in SPEC_MAP[spec_technique]:
        epm.add_experiment(
            "UVIS_sub_measure",
            {
                "spec_type": st,
                "spec_int_time_ms": spec_int_time_ms,
                "spec_n_avg": spec_n_avg,
                "duration_sec": spec_ref_duration,
                "toggle_source": led_names[0],
                "toggle_is_shutter": False,
                "illumination_wavelength": led_wavelengths_nm[0],
                "illumination_intensity": led_intensities_mw[0],
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "technique_name": spec_technique,
                "run_use": "ref_dark",
                "reference_mode": "builtin",
            },
        )
    # light ref
    for st in SPEC_MAP[spec_technique]:
        epm.add_experiment(
            "UVIS_sub_measure",
            {
                "spec_type": st,
                "spec_int_time_ms": spec_int_time_ms,
                "spec_n_avg": spec_n_avg,
                "duration_sec": spec_ref_duration,
                "toggle_source": led_names[0],
                "toggle_is_shutter": False,
                "illumination_wavelength": led_wavelengths_nm[0],
                "illumination_intensity": led_intensities_mw[0],
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "technique_name": spec_technique,
                "run_use": "ref_light",
                "reference_mode": "builtin",
            },
        )
    if use_z_motor:
        epm.add_experiment(
            "ECHEUVIS_sub_disengage",
            {
                "clear_we": True,
                "clear_ce": False,
                "z_height": cell_disengaged_z,
                "vent_wait": cell_vent_wait,
            },
        )
    else:
        epm.add_experiment(
            "ECHEUVIS_sub_interrupt",
            {"reason": "Stop flow and prepare for xy motion to starting sample."},
        )

    for i, plate_sample in enumerate(plate_sample_no_list):
        if i > 0 and use_z_motor:
            epm.add_experiment(
                "ECHEUVIS_sub_disengage",
                {
                    "clear_we": True,
                    "clear_ce": False,
                    "z_height": cell_disengaged_z,
                    "vent_wait": cell_vent_wait,
                },
            )

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

        if use_z_motor:
            epm.add_experiment(
                "ECHEUVIS_sub_engage",
                {
                    "flow_we": True,
                    "flow_ce": True,
                    "z_height": cell_engaged_z,
                    "fill_wait": cell_fill_wait,
                },
            )
        else:
            if i == 0:  # initial sample
                epm.add_experiment(
                    "ECHEUVIS_sub_interrupt",
                    {"reason": "Restore flow and prepare for sample measurement."},
                )

        # CP1
        epm.add_experiment(
            "ECHEUVIS_sub_CP_led",
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

    epm.add_experiment("ECHE_sub_unloadall_customs", {})
    if use_z_motor:
        epm.add_experiment(
            "ECHEUVIS_sub_disengage",
            {
                "clear_we": True,
                "clear_ce": False,
                "z_height": cell_disengaged_z,
                "vent_wait": cell_vent_wait,
            },
        )
    else:
        epm.add_experiment(
            "ECHEUVIS_sub_interrupt",
            {"reason": "Stop flow and prepare for xy motion to ref location."},
        )
    epm.add_experiment(
        "UVIS_sub_setup_ref",
        {
            "reference_mode": "builtin",
            "solid_custom_position": "cell1_we",
            "solid_plate_id": plate_id,
            "solid_sample_no": plate_sample_no_list[-1],
            "specref_code": 1,
        },
    )
    if use_z_motor:
        epm.add_experiment(
            "ECHEUVIS_sub_engage",
            {
                "flow_we": True,
                "flow_ce": True,
                "z_height": cell_engaged_z,
                "fill_wait": cell_fill_wait,
            },
        )
    else:
        epm.add_experiment(
            "ECHEUVIS_sub_interrupt",
            {"reason": "Restore flow and prepare for reference measurement."},
        )
    # dark ref
    for st in SPEC_MAP[spec_technique]:
        epm.add_experiment(
            "UVIS_sub_measure",
            {
                "spec_type": st,
                "spec_int_time_ms": spec_int_time_ms,
                "spec_n_avg": spec_n_avg,
                "duration_sec": spec_ref_duration,
                "toggle_source": led_names[0],
                "toggle_is_shutter": False,
                "illumination_wavelength": led_wavelengths_nm[0],
                "illumination_intensity": led_intensities_mw[0],
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "technique_name": spec_technique,
                "run_use": "ref_dark",
                "reference_mode": "builtin",
            },
        )
    # light ref
    for st in SPEC_MAP[spec_technique]:
        epm.add_experiment(
            "UVIS_sub_measure",
            {
                "spec_type": st,
                "spec_int_time_ms": spec_int_time_ms,
                "spec_n_avg": spec_n_avg,
                "duration_sec": spec_ref_duration,
                "toggle_source": led_names[0],
                "toggle_is_shutter": False,
                "illumination_wavelength": led_wavelengths_nm[0],
                "illumination_intensity": led_intensities_mw[0],
                "illumination_intensity_date": led_date,
                "illumination_side": led_type,
                "technique_name": spec_technique,
                "run_use": "ref_light",
                "reference_mode": "builtin",
            },
        )
    if use_z_motor:
        # leave cell sealed w/solution for storage
        epm.add_experiment(
            "ECHEUVIS_sub_engage",
            {
                "flow_we": False,
                "flow_ce": False,
                "z_height": cell_engaged_z,
                "fill_wait": cell_fill_wait,
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
    epm.add_experiment("ECHE_sub_shutdown", {})

    return epm.experiment_plan_list  # returns complete experiment list


def ECHEUVIS_diagnostic_CV(
    sequence_version: int = 1,
    plate_id: int = 0,
    solid_sample_no: int = 0,
    reservoir_electrolyte: Electrolyte = "OER10",
    reservoir_liquid_sample_no: int = 1,
    solution_bubble_gas: str = "O2",
    solution_ph: float = 9.53,
    measurement_area: float = 0.071,  # 3mm diameter droplet
    liquid_volume_ml: float = 1.0,
    ref_vs_nhe: float = 0.21,
    ref_offset__V: float = 0.0,
    cell_engaged_z: float = 2.5,
    cell_disengaged_z: float = 0,
    cell_vent_wait: float = 10.0,
    cell_fill_wait: float = 30.0,
):
    epm = ExperimentPlanMaker()
    epm.add_experiment("ECHEUVIS_sub_startup", {})
    epm.add_experiment(
        "ECHEUVIS_sub_disengage",
        {
            "clear_we": True,
            "clear_ce": False,
            "z_height": cell_disengaged_z,
            "vent_wait": cell_vent_wait,
        },
    )
    epm.add_experiment(
        "UVIS_sub_setup_ref",
        {
            "reference_mode": "builtin",
            "solid_custom_position": "cell1_we",
            "solid_plate_id": plate_id,
            "solid_sample_no": solid_sample_no,
            "specref_code": 1,
        },
    )
    epm.add_experiment(
        "ECHEUVIS_sub_engage",
        {
            "flow_we": True,
            "flow_ce": True,
            "z_height": cell_engaged_z,
            "fill_wait": cell_fill_wait,
        },
    )
    epm.add_experiment(
        "ECHE_sub_preCV",
        {
            "CA_potential": 1.23 - ref_vs_nhe - ref_offset__V - 0.059 * solution_ph,
            "samplerate_sec": 0.1,
            "CA_duration_sec": 5.0,
        },
    )
    # CV1
    epm.add_experiment(
        "ECHE_sub_CV",
        {
            "Vinit_vsRHE": 1.23,
            "Vapex1_vsRHE": 1.98,
            "Vapex2_vsRHE": 1.23,
            "Vfinal_vsRHE": 1.23,
            "scanrate_voltsec": 0.1,
            "samplerate_sec": 0.1,
            "cycles": 2,
            "gamry_i_range": "1mA",
            "solution_ph": solution_ph,
            "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
            "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
            "solution_bubble_gas": solution_bubble_gas,
            "measurement_area": measurement_area,
            "ref_type": "leakless",
            "ref_offset__V": ref_offset__V,
        },
    )
    # leave cell sealed w/solution for storage
    epm.add_experiment(
        "ECHEUVIS_sub_engage",
        {
            "flow_we": False,
            "flow_ce": False,
            "z_height": cell_engaged_z,
            "fill_wait": 5.0,
        },
    )
    epm.add_experiment("ECHEUVIS_sub_shutdown", {})

    return epm.experiment_plan_list  # returns complete experiment list


def ECHEUVIS_multiCA_led(
    sequence_version: int = 5,
    plate_id: int = 1,
    plate_sample_no_list: list = [2],
    reservoir_electrolyte: Electrolyte = "OER10",
    reservoir_liquid_sample_no: int = 1,
    solution_bubble_gas: str = "O2",
    solution_ph: float = 9.53,
    measurement_area: float = 0.071,  # 3mm diameter droplet
    liquid_volume_ml: float = 1.0,
    ref_vs_nhe: float = 0.21,
    CA_potential_vsRHE: List[float] = [0.8, 0.6, 0.4, 0.2],
    CA_duration_sec: float = 300,
    CA_samplerate_sec: float = 0.05,
    OCV_duration_sec: float = 5,
    gamry_i_range: str = "auto",
    led_type: str = "front",
    led_date: str = "01/01/2000",
    led_names: list = ["doric_wled"],
    led_wavelengths_nm: list = [-1],
    led_intensities_mw: list = [0.432],
    led_name_CA: str = "doric_wled",
    toggleCA_illum_duty: float = 1.0,
    toggleCA_illum_period: float = 1.0,
    toggleCA_dark_time_init: float = 0,
    toggleCA_illum_time: float = -1,
    toggleSpec_duty: float = 0.5,
    toggleSpec_period: float = 0.25,
    toggleSpec_init_delay: float = 0.0,
    toggleSpec_time: float = -1,
    spec_ref_duration: float = 5,
    spec_int_time_ms: float = 13,
    spec_n_avg: int = 5,
    spec_technique: str = "T_UVVIS",
    random_start_potential: bool = True,
    use_z_motor: bool = False,
    cell_engaged_z: float = 2.5,
    cell_disengaged_z: float = 0,
    cell_vent_wait: float = 10.0,
    cell_fill_wait: float = 30.0,
):
    epm = ExperimentPlanMaker()

    epm.add_experiment("ECHEUVIS_sub_startup", {})
    # if use_z_motor:
    #     epm.add_experiment(
    #         "ECHEUVIS_sub_disengage",
    #         {
    #             "clear_we": True,
    #             "clear_ce": False,
    #             "z_height": cell_disengaged_z,
    #             "vent_wait": cell_vent_wait,
    #         },
    #     )
    # else:
    #     epm.add_experiment(
    #         "ECHEUVIS_sub_interrupt",
    #         {"reason": "Stop flow and prepare for xy motion to ref location."},
    #     )
    # epm.add_experiment(
    #     "UVIS_sub_setup_ref",
    #     {
    #         "reference_mode": "builtin",
    #         "solid_custom_position": "cell1_we",
    #         "solid_plate_id": plate_id,
    #         "solid_sample_no": plate_sample_no_list[0],
    #         "specref_code": 1,
    #     },
    # )
    # if use_z_motor:
    #     epm.add_experiment(
    #         "ECHEUVIS_sub_engage",
    #         {
    #             "flow_we": True,
    #             "flow_ce": True,
    #             "z_height": cell_engaged_z,
    #             "fill_wait": cell_fill_wait,
    #         },
    #     )
    # else:
    #     epm.add_experiment(
    #         "ECHEUVIS_sub_interrupt",
    #         {"reason": "Restore flow and prepare for reference measurement."},
    #     )

    # # dark ref
    # for st in SPEC_MAP[spec_technique]:
    #     epm.add_experiment(
    #         "UVIS_sub_measure",
    #         {
    #             "spec_type": st,
    #             "spec_int_time_ms": spec_int_time_ms,
    #             "spec_n_avg": spec_n_avg,
    #             "duration_sec": spec_ref_duration,
    #             "toggle_source": led_names[0],
    #             "toggle_is_shutter": False,
    #             "illumination_wavelength": led_wavelengths_nm[0],
    #             "illumination_intensity": led_intensities_mw[0],
    #             "illumination_intensity_date": led_date,
    #             "illumination_side": led_type,
    #             "technique_name": spec_technique,
    #             "run_use": "ref_dark",
    #             "reference_mode": "builtin",
    #         },
    #     )
    # # light ref
    # for st in SPEC_MAP[spec_technique]:
    #     epm.add_experiment(
    #         "UVIS_sub_measure",
    #         {
    #             "spec_type": st,
    #             "spec_int_time_ms": spec_int_time_ms,
    #             "spec_n_avg": spec_n_avg,
    #             "duration_sec": spec_ref_duration,
    #             "toggle_source": led_names[0],
    #             "toggle_is_shutter": False,
    #             "illumination_wavelength": led_wavelengths_nm[0],
    #             "illumination_intensity": led_intensities_mw[0],
    #             "illumination_intensity_date": led_date,
    #             "illumination_side": led_type,
    #             "technique_name": spec_technique,
    #             "run_use": "ref_light",
    #             "reference_mode": "builtin",
    #         },
    #     )
    if use_z_motor:
        epm.add_experiment(
            "ECHEUVIS_sub_disengage",
            {
                "clear_we": True,
                "clear_ce": False,
                "z_height": cell_disengaged_z,
                "vent_wait": cell_vent_wait,
            },
        )
    else:
        epm.add_experiment(
            "ECHEUVIS_sub_interrupt",
            {"reason": "Stop flow and prepare for xy motion to starting sample."},
        )

    for i, plate_sample in enumerate(plate_sample_no_list):
        if i > 0 and use_z_motor:
            epm.add_experiment(
                "ECHEUVIS_sub_disengage",
                {
                    "clear_we": True,
                    "clear_ce": False,
                    "z_height": cell_disengaged_z,
                    "vent_wait": cell_vent_wait,
                },
            )

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

        if use_z_motor:
            epm.add_experiment(
                "ECHEUVIS_sub_engage",
                {
                    "flow_we": True,
                    "flow_ce": True,
                    "z_height": cell_engaged_z,
                    "fill_wait": cell_fill_wait,
                },
            )
        else:
            if i == 0:  # initial sample
                epm.add_experiment(
                    "ECHEUVIS_sub_interrupt",
                    {"reason": "Restore flow and prepare for sample measurement."},
                )

        if random_start_potential:
            scan_down = random.choice([True, False])
            start_v = random.choice(CA_potential_vsRHE)
            ordered_vs = sorted(CA_potential_vsRHE, reverse=scan_down)
            init_direction = ordered_vs[ordered_vs.index(start_v) :]
            rev_direction = ordered_vs[: ordered_vs.index(start_v)][::-1]
            potential_list = init_direction + rev_direction
        else:
            potential_list = CA_potential_vsRHE
        for vrhe in potential_list:
            # OCV
            epm.add_experiment(
                "ECHEUVIS_sub_OCV_led",
                {
                    "solution_ph": solution_ph,
                    "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
                    "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
                    "solution_bubble_gas": solution_bubble_gas,
                    "measurement_area": measurement_area,
                    "reference_electrode_type": "NHE",
                    "ref_vs_nhe": ref_vs_nhe,
                    "samplerate_sec": CA_samplerate_sec,
                    "OCV_duration_sec": OCV_duration_sec,
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
            # CA1
            epm.add_experiment(
                "ECHEUVIS_sub_CA_led",
                {
                    "CA_potential_vsRHE": vrhe,
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

    epm.add_experiment("ECHE_sub_unloadall_customs", {})
    # if use_z_motor:
    #     epm.add_experiment(
    #         "ECHEUVIS_sub_disengage",
    #         {
    #             "clear_we": True,
    #             "clear_ce": False,
    #             "z_height": cell_disengaged_z,
    #             "vent_wait": cell_vent_wait,
    #         },
    #     )
    # else:
    #     epm.add_experiment(
    #         "ECHEUVIS_sub_interrupt",
    #         {"reason": "Stop flow and prepare for xy motion to ref location."},
    #     )
    # epm.add_experiment(
    #     "UVIS_sub_setup_ref",
    #     {
    #         "reference_mode": "builtin",
    #         "solid_custom_position": "cell1_we",
    #         "solid_plate_id": plate_id,
    #         "solid_sample_no": plate_sample_no_list[-1],
    #         "specref_code": 1,
    #     },
    # )
    # if use_z_motor:
    #     epm.add_experiment(
    #         "ECHEUVIS_sub_engage",
    #         {
    #             "flow_we": True,
    #             "flow_ce": True,
    #             "z_height": cell_engaged_z,
    #             "fill_wait": cell_fill_wait,
    #         },
    #     )
    # else:
    #     epm.add_experiment(
    #         "ECHEUVIS_sub_interrupt",
    #         {"reason": "Restore flow and prepare for reference measurement."},
    #     )
    # # dark ref
    # for st in SPEC_MAP[spec_technique]:
    #     epm.add_experiment(
    #         "UVIS_sub_measure",
    #         {
    #             "spec_type": st,
    #             "spec_int_time_ms": spec_int_time_ms,
    #             "spec_n_avg": spec_n_avg,
    #             "duration_sec": spec_ref_duration,
    #             "toggle_source": led_names[0],
    #             "toggle_is_shutter": False,
    #             "illumination_wavelength": led_wavelengths_nm[0],
    #             "illumination_intensity": led_intensities_mw[0],
    #             "illumination_intensity_date": led_date,
    #             "illumination_side": led_type,
    #             "technique_name": spec_technique,
    #             "run_use": "ref_dark",
    #             "reference_mode": "builtin",
    #         },
    #     )
    # # light ref
    # for st in SPEC_MAP[spec_technique]:
    #     epm.add_experiment(
    #         "UVIS_sub_measure",
    #         {
    #             "spec_type": st,
    #             "spec_int_time_ms": spec_int_time_ms,
    #             "spec_n_avg": spec_n_avg,
    #             "duration_sec": spec_ref_duration,
    #             "toggle_source": led_names[0],
    #             "toggle_is_shutter": False,
    #             "illumination_wavelength": led_wavelengths_nm[0],
    #             "illumination_intensity": led_intensities_mw[0],
    #             "illumination_intensity_date": led_date,
    #             "illumination_side": led_type,
    #             "technique_name": spec_technique,
    #             "run_use": "ref_light",
    #             "reference_mode": "builtin",
    #         },
    #     )
    if use_z_motor:
        # leave cell sealed w/solution for storage
        epm.add_experiment(
            "ECHEUVIS_sub_engage",
            {
                "flow_we": False,
                "flow_ce": False,
                "z_height": cell_engaged_z,
                "fill_wait": cell_fill_wait,
            },
        )
    # epm.add_experiment(
    #     "UVIS_calc_abs",
    #     {
    #         "ev_parts": calc_ev_parts,
    #         "bin_width": calc_bin_width,
    #         "window_length": calc_window_length,
    #         "poly_order": calc_poly_order,
    #         "lower_wl": calc_lower_wl,
    #         "upper_wl": calc_upper_wl,
    #         "skip_nspec": calc_skip_nspec,
    #     },
    # )
    epm.add_experiment("ECHEUVIS_sub_shutdown", {})

    return epm.experiment_plan_list  # returns complete experiment list


def ECHEUVIS_postseq(
    sequence_version: int = 1,
    analysis_seq_uuid: str = "",
    plate_id: int = 0,
    recent: bool = False,
):
    epm = ExperimentPlanMaker()
    epm.add_experiment(
        "ECHEUVIS_analysis_stability",
        {
            "sequence_uuid": analysis_seq_uuid,
            "plate_id": plate_id,
            "recent": recent,
        },
    )

    return epm.experiment_plan_list  # returns complete experiment list
