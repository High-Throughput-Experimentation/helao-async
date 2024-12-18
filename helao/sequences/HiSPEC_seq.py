__all__ = [
    "HiSpEC_CV",
    #"ECHEUVIS_CV_led",
   # "ECHEUVIS_CA_led",
    #"ECHEUVIS_CP_led",
    "ECHEUVIS_postseq",
]

import random
from typing import List, Optional
from helao.helpers.premodels import ExperimentPlanMaker
from helao.helpers.spec_map import SPEC_MAP
from helao.core.models.electrolyte import Electrolyte


SEQUENCES = __all__


def HiSpEC_CV(
    sequence_version: int = 1, # @Dan - what is this? -- this is a version number for the sequence, you should increment it when you modify sequence arguments and the experiment list
    plate_id: int = 1, # @Dan - what is this? -- plate_id is the ID of the material library in our database. it's first assigned to a substrate after which we can use this ID to track the library's deposition, annealing, and experiment history
    plate_sample_no_list: list = [2], # @Dan - what is this? -- the sample_no is uniquely assigned to an x,y location on a material library according to its plate map which was defined at the synthesis step
    reservoir_electrolyte: Electrolyte = "HISPEC-A",  # @Ben -- this is an enum for a common abbreviation we give to our electrolytes used in our screening protocols, they typically have an integer pH at the end, see helao.core.models.electrolyte and add one there if needed
    reservoir_liquid_sample_no: int = 1, # @Dan -- what is this? -- this is the liquid sample number in the liquid sample database, you will need to 'create' a liquid sample for the electrolyte you're using, so that the cell is filled with a liquid sample that inherits the reservoir attributes
    solution_bubble_gas: str = "None",
    solution_ph: float = 0,

    #######
    #Vinit_vsRHE: float = 0.0,  # Initial value in volts or amps.
    Vapex1_vsRHE: float = 1.0,  # Apex 1 value in volts or amps.
    Vapex2_vsRHE: float = -1.0,  # Apex 2 value in volts or amps.
    Vfinal_vsRHE: float = 0.0,  # Final value in volts or amps.
    #scanrate_voltsec: Optional[float] = 0.02,  # scan rate in volts/second or amps/second.
    samplerate_sec: float = 0.1,
    cycles: int = 1,
    gamrychannelwait: int = -1,
    gamrychannelsend: int = 0,
    IRange: str = "m10",
    ERange: str = "v10",
    Bandwidth: str = "BW4",
    ref_vs_nhe: float = 0,
    toggle1_source: str = "spec_trig",
    toggle1_init_delay: float = 0.0,
    toggle1_duty: float = 0.5,
    toggle1_period: float = 2.0,
    toggle1_time: float = -1,
    # toggle2_source: str = "spec_trig",
    # toggle2_init_delay: float = 0.0,
    # toggle2_duty: float = 0.5,
    # toggle2_period: float = 2.0,
    # toggle2_time: float = -1,
    comment: str = "",
    #####
    measurement_area: float = 0.071,  # 3mm diameter droplet
    liquid_volume_ml: float = 1.0,
    use_z_motor: bool = True,  # @Ben -- I think this should default to True
    cell_engaged_z: float = 2.5, # need to find out what this should be.
    cell_disengaged_z: float = 0,
    cell_vent_wait: float = 10.0,
    cell_fill_wait: float = 30.0,
):
    epm = ExperimentPlanMaker()

    epm.add_experiment("ECHEUVIS_sub_startup", {})  # @Ben -- if you use this experiment, you'll need to update the hispec.yml config to include ECHEUVIS_exp under experiment_libraries
    
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
                    "calibrate_intensity": False, #@Dan - kept this action but turned this flag to false to prevent it trying to access doric WLED - not sure if this will work... -- it should work because the references to doric_wled aren't going to be used
                    "max_integration_time": int(10)
                },
            )
        else:
            if i == 0:  # initial sample
                epm.add_experiment(
                    "ECHEUVIS_sub_interrupt",
                    {"reason": "Restore flow and prepare for sample measurement."},
                )

        epm.add_experiment(
            "ECHE_sub_OCV",
            {
                "Tval__s": 0.1,
                "SampleRate":0.01,
            }
                )

        epm.add_experiment(
            "HiSPEC_sub_SpEC",
            {
                #"Vinit_vsRHE": Vinit_vsRHE,

                "Vapex1_vsRHE": Vapex1_vsRHE,
                "Vapex2_vsRHE": Vapex2_vsRHE,
                "Vfinal_vsRHE": Vfinal_vsRHE,
                "samplerate_sec": samplerate_sec,
                "cycles": cycles,
                "gamrychannelwait": gamrychannelwait,
                "gamrychannelsend": gamrychannelsend,
                "IRange": IRange,
                "ERange": ERange,
                "Bandwidth": Bandwidth,
                "solution_ph": solution_ph,
                "ref_vs_nhe": ref_vs_nhe,
                "toggle1_source": toggle1_source,
                "toggle1_init_delay": toggle1_init_delay,
                "toggle1_duty": toggle1_duty,
            }, from_globalexp_params={"HiSpEC_OCV": "Vinit_vsRHE"})

    epm.add_experiment("ECHE_sub_unloadall_customs", {})

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
    spec_n_avg: int = 1,
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
            "calibrate_intensity": True,
        },
    )
    epm.add_experiment(
        "ECHEUVIS_sub_CA_led",
        {
            "CA_potential_vsRHE": 1.23,
            "solution_ph": solution_ph,
            "reservoir_liquid_sample_no": reservoir_liquid_sample_no,  # currently liquid sample database number
            "reservoir_electrolyte": reservoir_electrolyte,  # currently liquid sample database number
            "solution_bubble_gas": solution_bubble_gas,
            "measurement_area": measurement_area,
            "reference_electrode_type": "NHE",
            "ref_vs_nhe": ref_vs_nhe,
            "samplerate_sec": 0.1,
            "CA_duration_sec": 10,
            "gamry_i_range": "1mA",
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
            # "spec_int_time_ms": spec_int_time_ms,
            "spec_n_avg": 3,
            "spec_technique": "T_UVVIS",
        },
        from_globalexp_params={"calibrated_int_time_ms": "spec_int_time_ms"},
    )
    # CV1
    epm.add_experiment(
        "ECHEUVIS_sub_CV_led",
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
            "reference_electrode_type": "NHE",
            "ref_vs_nhe": ref_vs_nhe,
            "illumination_source": led_name_CA,
            "illumination_wavelength": led_wavelengths_nm[
                led_names.index(led_name_CA)
            ],
            "illumination_intensity": led_intensities_mw[
                led_names.index(led_name_CA)
            ],
            "illumination_intensity_date": led_date,
            "illumination_side": led_type,
            "toggle_illum_duty": 1.0,
            "toggle_illum_period": 1.0,
            "toggle_illum_time": -1,
            "toggle_dark_time_init": 0,
            "toggle2_duty": toggleSpec_duty,
            "toggle2_period": toggleSpec_period,
            "toggle2_init_delay": toggleSpec_init_delay,
            "toggle2_time": toggleSpec_time,
            # "spec_int_time_ms": spec_int_time_ms,
            "spec_n_avg": spec_n_avg,
            "spec_technique": "T_UVVIS",
        },
        from_globalexp_params={"calibrated_int_time_ms": "spec_int_time_ms"},
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
                    "calibrate_intensity": True,
                    "max_integration_time": int(1000 * toggleSpec_period / spec_n_avg)
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
                    # "spec_int_time_ms": spec_int_time_ms,
                    "spec_n_avg": spec_n_avg,
                    "spec_technique": spec_technique,
                },
                from_globalexp_params={"calibrated_int_time_ms": "spec_int_time_ms"},
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
                    # "spec_int_time_ms": spec_int_time_ms,
                    "spec_n_avg": spec_n_avg,
                    "spec_technique": spec_technique,
                },
                from_globalexp_params={"calibrated_int_time_ms": "spec_int_time_ms"},
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
