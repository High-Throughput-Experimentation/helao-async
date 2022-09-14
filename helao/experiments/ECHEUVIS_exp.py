"""
Experiment library for ECHE+UVIS
server_key must be a FastAPI action server defined in config
"""

__all__ = [
    "ECHE_sub_CV_led_secondtrigger",
    "ECHE_sub_CA_led_secondtrigger",
    "ECHE_sub_CP_led_secondtrigger",
]


from typing import Optional
from socket import gethostname

from helao.helpers.premodels import Experiment, ActionPlanMaker
from helaocore.models.action_start_condition import ActionStartCondition
from helaocore.models.machine import MachineModel as MM
from helaocore.models.process_contrib import ProcessContrib
from helaocore.models.electrolyte import Electrolyte

from helao.drivers.io.enum import TriggerType
from helao.drivers.spec.enum import SpecType


EXPERIMENTS = __all__

PSTAT_server = MM(server_name="PSTAT", machine_name=gethostname()).json_dict()
MOTOR_server = MM(server_name="MOTOR", machine_name=gethostname()).json_dict()
IO_server = MM(server_name="IO", machine_name=gethostname()).json_dict()
SPEC_T_server = MM(server_name="SPEC_T", machine_name=gethostname()).json_dict()
ORCH_server = MM(server_name="ORCH", machine_name=gethostname()).json_dict()
PAL_server = MM(server_name="PAL", machine_name=gethostname()).json_dict()
CALC_server = MM(server_name="CALC", machine_name=gethostname()).json_dict()

toggle_triggertype = TriggerType.fallingedge


def ECHE_sub_CV_led_secondtrigger(
    experiment: Experiment,
    experiment_version: int = 3,
    Vinit_vsRHE: Optional[float] = 0.0,  # Initial value in volts or amps.
    Vapex1_vsRHE: Optional[float] = 1.0,  # Apex 1 value in volts or amps.
    Vapex2_vsRHE: Optional[float] = -1.0,  # Apex 2 value in volts or amps.
    Vfinal_vsRHE: Optional[float] = 0.0,  # Final value in volts or amps.
    scanrate_voltsec: Optional[
        float
    ] = 0.02,  # scan rate in volts/second or amps/second.
    samplerate_sec: Optional[float] = 0.1,
    cycles: Optional[int] = 1,
    gamry_i_range: Optional[str] = "auto",
    solution_ph: float = 0,
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,  # currently liquid sample database number
    solution_bubble_gas: str = "O2",
    measurement_area: float = 0.071,  # 3mm diameter droplet
    ref_electrode_type: str = "NHE",
    ref_vs_nhe: float = 0.21,
    illumination_source: Optional[str] = "doric_wled",
    illumination_wavelength: Optional[float] = 0.0,
    illumination_intensity: Optional[float] = 0.0,
    illumination_intensity_date: Optional[str] = "n/a",
    illumination_side: Optional[str] = "front",
    toggle_dark_time_init: Optional[float] = 0.0,
    toggle_illum_duty: Optional[float] = 0.5,
    toggle_illum_period: Optional[float] = 2.0,
    toggle_illum_time: Optional[float] = -1,
    toggle2_source: Optional[str] = "spec_trig",
    toggle2_init_delay: Optional[float] = 0.0,
    toggle2_duty: Optional[float] = 0.5,
    toggle2_period: Optional[float] = 2.0,
    toggle2_time: Optional[float] = -1,
    spec_int_time_ms: Optional[float] = 15,
    spec_n_avg: Optional[int] = 1,
    spec_type: Optional[SpecType] = "T",
    comment: Optional[str] = "",
):
    """last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    CV_duration_sec = (
        abs(apm.pars.Vapex1_vsRHE - apm.pars.Vinit_vsRHE) / apm.pars.scanrate_voltsec
    )
    CV_duration_sec += (
        abs(apm.pars.Vfinal_vsRHE - apm.pars.Vapex2_vsRHE) / apm.pars.scanrate_voltsec
    )
    CV_duration_sec += (
        abs(apm.pars.Vapex2_vsRHE - apm.pars.Vapex1_vsRHE)
        / apm.pars.scanrate_voltsec
        * apm.pars.cycles
    )
    CV_duration_sec += (
        abs(apm.pars.Vapex2_vsRHE - apm.pars.Vapex1_vsRHE)
        / apm.pars.scanrate_voltsec
        * 2.0
        * (apm.pars.cycles - 1)
    )

    if int(round(apm.pars.toggle_illum_time)) == -1:
        apm.pars.toggle_illum_time = CV_duration_sec
    if int(round(apm.pars.toggle2_time)) == -1:
        apm.pars.toggle2_time = CV_duration_sec

    # get sample for gamry
    apm.add_action(
        {
            "action_server": PAL_server,
            "action_name": "archive_custom_query_sample",
            "action_params": {
                "custom": "cell1_we",
            },
            "to_globalexp_params": [
                "_fast_samples_in"
            ],  # save new liquid_sample_no of eche cell to globals
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        }
    )

    # setup toggle on galil_io
    apm.add_action(
        {
            "action_server": IO_server,
            "action_name": "set_digital_cycle",
            "action_params": {
                "trigger_name": "gamry_ttl0",
                "triggertype": toggle_triggertype,
                "out_name": [apm.pars.illumination_source, apm.pars.toggle2_source],
                "out_name_gamry": None,
                "toggle_init_delay": [
                    apm.pars.toggle_dark_time_init,
                    apm.pars.toggle2_init_delay,
                ],
                "toggle_duty": [apm.pars.toggle_illum_duty, apm.pars.toggle2_duty],
                "toggle_period": [
                    apm.pars.toggle_illum_period,
                    apm.pars.toggle2_period,
                ],
                "toggle_duration": [apm.pars.toggle_illum_time, apm.pars.toggle2_time],
            },
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "process_finish": False,
            "process_contrib": [
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        },
    )

    apm.add_action(
        {
            "action_server": SPEC_T_server,
            "action_name": "acquire_spec_extrig",
            "from_globalexp_params": {"_fast_samples_in": "fast_samples_in"},
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "action_params": {
                "int_time": apm.pars.spec_int_time_ms,
                "n_avg": apm.pars.spec_n_avg,
            },
            "process_contrib": [
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        }
    )

    # apply potential
    apm.add_action(
        {
            "action_server": PSTAT_server,
            "action_name": "run_CV",
            "action_params": {
                "Vinit__V": apm.pars.Vinit_vsRHE
                - 1.0 * apm.pars.ref_vs_nhe
                - 0.059 * apm.pars.solution_ph,
                "Vapex1__V": apm.pars.Vapex1_vsRHE
                - 1.0 * apm.pars.ref_vs_nhe
                - 0.059 * apm.pars.solution_ph,
                "Vapex2__V": apm.pars.Vapex2_vsRHE
                - 1.0 * apm.pars.ref_vs_nhe
                - 0.059 * apm.pars.solution_ph,
                "Vfinal__V": apm.pars.Vfinal_vsRHE
                - 1.0 * apm.pars.ref_vs_nhe
                - 0.059 * apm.pars.solution_ph,
                "ScanRate__V_s": apm.pars.scanrate_voltsec,
                "AcqInterval__s": apm.pars.samplerate_sec,
                "Cycles": apm.pars.cycles,
                "TTLwait": -1,  # -1 disables, else select TTL 0-3
                "TTLsend": 0,  # -1 disables, else select TTL 0-3
                "IErange": apm.pars.gamry_i_range,
            },
            "from_globalexp_params": {"_fast_samples_in": "fast_samples_in"},
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "technique_name": "CV",
            "process_finish": True,
            "process_contrib": [
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        },
    )

    apm.add_action(
        {
            "action_server": SPEC_T_server,
            "action_name": "stop_extrig",
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "action_params": {},
        }
    )

    apm.add_action(
        {
            "action_server": IO_server,
            "action_name": "stop_digital_cycle",
            "action_params": {},
        },
    )

    return apm.action_list  # returns complete action list to orch


def ECHE_sub_CA_led_secondtrigger(
    experiment: Experiment,
    experiment_version: int = 3,
    CA_potential_vsRHE: Optional[float] = 0.0,
    solution_ph: float = 9.53,
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,  # currently liquid sample database number
    solution_bubble_gas: str = "O2",
    measurement_area: float = 0.071,  # 3mm diameter droplet
    ref_electrode_type: str = "NHE",
    ref_vs_nhe: float = 0.21,
    samplerate_sec: Optional[float] = 0.1,
    CA_duration_sec: Optional[float] = 60,
    gamry_i_range: Optional[str] = "auto",
    illumination_source: Optional[str] = "doric_wled",
    illumination_wavelength: Optional[float] = 0.0,
    illumination_intensity: Optional[float] = 0.0,
    illumination_intensity_date: Optional[str] = "n/a",
    illumination_side: Optional[str] = "front",
    toggle_dark_time_init: Optional[float] = 0.0,
    toggle_illum_duty: Optional[float] = 0.5,
    toggle_illum_period: Optional[float] = 2.0,
    toggle_illum_time: Optional[float] = -1,
    toggle2_source: Optional[str] = "spec_trig",
    toggle2_init_delay: Optional[float] = 0.0,
    toggle2_duty: Optional[float] = 0.5,
    toggle2_period: Optional[float] = 2.0,
    toggle2_time: Optional[float] = -1,
    spec_int_time_ms: Optional[float] = 15,
    spec_n_avg: Optional[int] = 1,
    spec_type: Optional[SpecType] = "T",
    comment: Optional[str] = "",
):
    """last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    if int(round(apm.pars.toggle_illum_time)) == -1:
        apm.pars.toggle_illum_time = apm.pars.CA_duration_sec
    if int(round(apm.pars.toggle2_time)) == -1:
        apm.pars.toggle2_time = apm.pars.CA_duration_sec

    # get sample for gamry
    apm.add_action(
        {
            "action_server": PAL_server,
            "action_name": "archive_custom_query_sample",
            "action_params": {
                "custom": "cell1_we",
            },
            "to_globalexp_params": [
                "_fast_samples_in"
            ],  # save new liquid_sample_no of eche cell to globals
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        }
    )

    # setup toggle on galil_io
    apm.add_action(
        {
            "action_server": IO_server,
            "action_name": "set_digital_cycle",
            "action_params": {
                "trigger_name": "gamry_ttl0",
                "triggertype": toggle_triggertype,
                "out_name": [apm.pars.illumination_source, apm.pars.toggle2_source],
                "out_name_gamry": None,
                "toggle_init_delay": [
                    apm.pars.toggle_dark_time_init,
                    apm.pars.toggle2_init_delay,
                ],
                "toggle_duty": [apm.pars.toggle_illum_duty, apm.pars.toggle2_duty],
                "toggle_period": [
                    apm.pars.toggle_illum_period,
                    apm.pars.toggle2_period,
                ],
                "toggle_duration": [apm.pars.toggle_illum_time, apm.pars.toggle2_time],
            },
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "process_finish": False,
            "process_contrib": [
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        },
    )

    apm.add_action(
        {
            "action_server": SPEC_T_server,
            "action_name": "acquire_spec_extrig",
            "from_globalexp_params": {"_fast_samples_in": "fast_samples_in"},
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "action_params": {
                "int_time": apm.pars.spec_int_time_ms,
                "n_avg": apm.pars.spec_n_avg,
            },
            "process_contrib": [
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        }
    )

    # apply potential
    potential = (
        apm.pars.CA_potential_vsRHE
        - 1.0 * apm.pars.ref_vs_nhe
        - 0.059 * apm.pars.solution_ph
    )
    print(f"ECHE_sub_CA potential: {potential}")
    apm.add_action(
        {
            "action_server": PSTAT_server,
            "action_name": "run_CA",
            "action_params": {
                "Vval__V": potential,
                "Tval__s": apm.pars.CA_duration_sec,
                "AcqInterval__s": apm.pars.samplerate_sec,
                "TTLwait": -1,  # -1 disables, else select TTL 0-3
                "TTLsend": 0,  # -1 disables, else select TTL 0-3
                "IErange": apm.pars.gamry_i_range,
            },
            "from_globalexp_params": {"_fast_samples_in": "fast_samples_in"},
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "technique_name": "CA",
            "process_finish": True,
            "process_contrib": [
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        },
    )

    apm.add_action(
        {
            "action_server": SPEC_T_server,
            "action_name": "stop_extrig",
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "action_params": {},
        }
    )

    apm.add_action(
        {
            "action_server": IO_server,
            "action_name": "stop_digital_cycle",
            "action_params": {},
        },
    )

    return apm.action_list  # returns complete action list to orch


def ECHE_sub_CP_led_secondtrigger(
    experiment: Experiment,
    experiment_version: int = 3,
    CP_current: Optional[float] = 0.0,
    solution_ph: float = 9.53,
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,  # currently liquid sample database number
    solution_bubble_gas: str = "O2",
    measurement_area: float = 0.071,  # 3mm diameter droplet
    ref_electrode_type: str = "NHE",
    ref_vs_nhe: float = 0.21,
    samplerate_sec: Optional[float] = 0.1,
    CP_duration_sec: Optional[float] = 60,
    gamry_i_range: Optional[str] = "auto",
    illumination_source: Optional[str] = "doric_wled",
    illumination_wavelength: Optional[float] = 0.0,
    illumination_intensity: Optional[float] = 0.0,
    illumination_intensity_date: Optional[str] = "n/a",
    illumination_side: Optional[str] = "front",
    toggle_dark_time_init: Optional[float] = 0.0,
    toggle_illum_duty: Optional[float] = 0.5,
    toggle_illum_period: Optional[float] = 2.0,
    toggle_illum_time: Optional[float] = -1,
    toggle2_source: Optional[str] = "spec_trig",
    toggle2_init_delay: Optional[float] = 0.0,
    toggle2_duty: Optional[float] = 0.5,
    toggle2_period: Optional[float] = 2.0,
    toggle2_time: Optional[float] = -1,
    spec_int_time_ms: Optional[float] = 15,
    spec_n_avg: Optional[int] = 1,
    spec_type: Optional[SpecType] = "T",
    comment: Optional[str] = "",
):
    """last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    if int(round(apm.pars.toggle_illum_time)) == -1:
        apm.pars.toggle_illum_time = apm.pars.CP_duration_sec
    if int(round(apm.pars.toggle2_time)) == -1:
        apm.pars.toggle2_time = apm.pars.CP_duration_sec

    # get sample for gamry
    apm.add_action(
        {
            "action_server": PAL_server,
            "action_name": "archive_custom_query_sample",
            "action_params": {
                "custom": "cell1_we",
            },
            "to_globalexp_params": [
                "_fast_samples_in"
            ],  # save new liquid_sample_no of eche cell to globals
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        }
    )

    # setup toggle on galil_io
    apm.add_action(
        {
            "action_server": IO_server,
            "action_name": "set_digital_cycle",
            "action_params": {
                "trigger_name": "gamry_ttl0",
                "triggertype": toggle_triggertype,
                "out_name": [apm.pars.illumination_source, apm.pars.toggle2_source],
                "out_name_gamry": None,
                "toggle_init_delay": [
                    apm.pars.toggle_dark_time_init,
                    apm.pars.toggle2_init_delay,
                ],
                "toggle_duty": [apm.pars.toggle_illum_duty, apm.pars.toggle2_duty],
                "toggle_period": [
                    apm.pars.toggle_illum_period,
                    apm.pars.toggle2_period,
                ],
                "toggle_duration": [apm.pars.toggle_illum_time, apm.pars.toggle2_time],
            },
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "process_finish": False,
            "process_contrib": [
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        },
    )

    apm.add_action(
        {
            "action_server": SPEC_T_server,
            "action_name": "acquire_spec_extrig",
            "from_globalexp_params": {"_fast_samples_in": "fast_samples_in"},
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "action_params": {
                "int_time": apm.pars.spec_int_time_ms,
                "n_avg": apm.pars.spec_n_avg,
            },
            "process_contrib": [
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        }
    )

    apm.add_action(
        {
            "action_server": PSTAT_server,
            "action_name": "run_CP",
            "action_params": {
                "Ival__A": CP_current,
                "Tval__s": apm.pars.CP_duration_sec,
                "AcqInterval__s": apm.pars.samplerate_sec,
                "TTLwait": -1,  # -1 disables, else select TTL 0-3
                "TTLsend": 0,  # -1 disables, else select TTL 0-3
                "IErange": apm.pars.gamry_i_range,
            },
            "from_globalexp_params": {"_fast_samples_in": "fast_samples_in"},
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "technique_name": "CP",
            "process_finish": True,
            "process_contrib": [
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        },
    )

    apm.add_action(
        {
            "action_server": SPEC_T_server,
            "action_name": "stop_extrig",
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "action_params": {},
        }
    )

    apm.add_action(
        {
            "action_server": IO_server,
            "action_name": "stop_digital_cycle",
            "action_params": {},
        },
    )

    return apm.action_list  # returns complete action list to orch
