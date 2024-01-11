"""
Experiment library for ECHE+UVIS
server_key must be a FastAPI action server defined in config
"""

__all__ = [
    "ECHEUVIS_sub_CV_led",
    "ECHEUVIS_sub_CA_led",
    "ECHEUVIS_sub_CP_led",
    "ECHEUVIS_sub_OCV_led",
    "ECHEUVIS_sub_interrupt",
    "ECHEUVIS_sub_startup",
    "ECHEUVIS_sub_shutdown",
    "ECHEUVIS_sub_engage",
    "ECHEUVIS_sub_disengage",
    "ECHEUVIS_analysis_stability",
]


from typing import Optional
from socket import gethostname

from helao.helpers.premodels import Experiment, ActionPlanMaker
from helao.helpers.spec_map import SPECSRV_MAP
from helaocore.models.action_start_condition import ActionStartCondition
from helaocore.models.machine import MachineModel as MM
from helaocore.models.process_contrib import ProcessContrib
from helaocore.models.electrolyte import Electrolyte

from helao.drivers.io.enum import TriggerType


EXPERIMENTS = __all__

PSTAT_server = MM(server_name="PSTAT", machine_name=gethostname().lower()).as_dict()
MOTOR_server = MM(server_name="MOTOR", machine_name=gethostname().lower()).as_dict()
IO_server = MM(server_name="IO", machine_name=gethostname().lower()).as_dict()
SPEC_T_server = MM(server_name="SPEC_T", machine_name=gethostname().lower()).as_dict()
SPEC_R_server = MM(server_name="SPEC_R", machine_name=gethostname().lower()).as_dict()
ORCH_server = MM(server_name="ORCH", machine_name=gethostname().lower()).as_dict()
PAL_server = MM(server_name="PAL", machine_name=gethostname().lower()).as_dict()
CAM_server = MM(server_name="CAM", machine_name=gethostname().lower()).as_dict()
KMOTOR_server = MM(server_name="KMOTOR", machine_name=gethostname().lower()).as_dict()
ANA_server = MM(server_name="ANA", machine_name=gethostname().lower()).as_dict()

toggle_triggertype = TriggerType.fallingedge


def ECHEUVIS_sub_startup(experiment: Experiment):
    """Unload custom position and enable IR emitter."""
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(PAL_server, "archive_custom_unloadall", {"destroy_liquid": True})
    apm.add(IO_server, "set_digital_out", {"do_item": "ir_emitter", "on": True})
    return apm.action_list  # returns complete action list to orch


def ECHEUVIS_sub_shutdown(experiment: Experiment):
    """Unload custom position and disable IR emitter."""
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(PAL_server, "archive_custom_unloadall", {"destroy_liquid": True})
    apm.add(IO_server, "set_digital_out", {"do_item": "ir_emitter", "on": False})
    return apm.action_list  # returns complete action list to orch


def ECHEUVIS_sub_CV_led(
    experiment: Experiment,
    experiment_version: int = 6,
    Vinit_vsRHE: float = 0.0,  # Initial value in volts or amps.
    Vapex1_vsRHE: float = 1.0,  # Apex 1 value in volts or amps.
    Vapex2_vsRHE: float = -1.0,  # Apex 2 value in volts or amps.
    Vfinal_vsRHE: float = 0.0,  # Final value in volts or amps.
    scanrate_voltsec: Optional[
        float
    ] = 0.02,  # scan rate in volts/second or amps/second.
    samplerate_sec: float = 0.1,
    cycles: int = 1,
    gamry_i_range: str = "auto",
    gamrychannelwait: int = -1,
    gamrychannelsend: int = 0,
    solution_ph: float = 0,
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,  # currently liquid sample database number
    solution_bubble_gas: str = "O2",
    measurement_area: float = 0.071,  # 3mm diameter droplet
    ref_electrode_type: str = "NHE",
    ref_vs_nhe: float = 0.21,
    illumination_source: str = "doric_wled",
    illumination_wavelength: float = 0.0,
    illumination_intensity: float = 0.0,
    illumination_intensity_date: str = "n/a",
    illumination_side: str = "front",
    toggle_dark_time_init: float = 0.0,
    toggle_illum_duty: float = 0.5,
    toggle_illum_period: float = 2.0,
    toggle_illum_time: float = -1,
    toggle2_source: str = "spec_trig",
    toggle2_init_delay: float = 0.0,
    toggle2_duty: float = 0.5,
    toggle2_period: float = 2.0,
    toggle2_time: float = -1,
    spec_int_time_ms: float = 15,
    spec_n_avg: int = 10,
    spec_technique: str = "T_UVVIS",
    comment: str = "",
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
    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {
            "custom": "cell1_we",
        },
        to_globalexp_params=[
            "_fast_samples_in"
        ],  # save new liquid_sample_no of eche cell to globals
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
    )

    # setup toggle on galil_io
    apm.add(
        IO_server,
        "set_digital_cycle",
        {
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
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        process_finish=False,
        process_contrib=[
            ProcessContrib.files,
            ProcessContrib.samples_out,
        ],
    )

    # apm.add(ORCH_server, "wait", {"waittime": 5})
    
    # apm.add(
    #     IO_server,
    #     "set_digital_out",
    #     {
    #         "do_item": apm.pars.illumination_source,
    #         "on": True,
    #     },
    # )

    apm.add(
        CAM_server,
        "acquire_image",
        {"duration": min(CV_duration_sec, 10), "acqusition_rate": 0.5},
        start_condition=ActionStartCondition.no_wait,
        nonblocking=True,
    )

    for ss in SPECSRV_MAP[apm.pars.spec_technique]:
        apm.add(
            ss,
            "acquire_spec_extrig",
            {
                "int_time": apm.pars.spec_int_time_ms,
                "n_avg": apm.pars.spec_n_avg,
                "duration": apm.pars.toggle2_time,
            },
            from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
            start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            technique_name=apm.pars.spec_technique,
            process_contrib=[
                ProcessContrib.files,
                ProcessContrib.samples_out,
            ],
        )
        # apm.add(
        #     ss,
        #     "acquire_spec_adv",
        #     {
        #         "int_time_ms": apm.pars.spec_int_time_ms,
        #         "n_avg": apm.pars.spec_n_avg,
        #         "duration_sec": apm.pars.toggle2_time,
        #     },
        #     from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
        #     run_use="data",
        #     technique_name=apm.pars.spec_technique,
        #     process_finish=False,
        #     process_contrib=[
        #         ProcessContrib.files,
        #         ProcessContrib.samples_out,
        #     ],
        #     start_condition=ActionStartCondition.no_wait,
        #     nonblocking=True,
        # )

    # apply potential
    apm.add(
        PSTAT_server,
        "run_CV",
        {
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
            "TTLwait": apm.pars.gamrychannelwait,  # -1 disables, else select TTL 0-3
            "TTLsend": apm.pars.gamrychannelsend,  # -1 disables, else select TTL 0-3
            "IErange": apm.pars.gamry_i_range,
        },
        from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
        start_condition=ActionStartCondition.wait_for_server,
        technique_name="CV",
        process_finish=True,
        process_contrib=[
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )

    # apm.add(
    #     IO_server,
    #     "set_digital_out",
    #     {
    #         "do_item": apm.pars.illumination_source,
    #         "on": False,
    #     },
    # )

    return apm.action_list  # returns complete action list to orch


def ECHEUVIS_sub_CA_led(
    experiment: Experiment,
    experiment_version: int = 6,
    CA_potential_vsRHE: float = 0.0,
    solution_ph: float = 9.53,
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,  # currently liquid sample database number
    solution_bubble_gas: str = "O2",
    measurement_area: float = 0.071,  # 3mm diameter droplet
    ref_electrode_type: str = "NHE",
    ref_vs_nhe: float = 0.21,
    samplerate_sec: float = 0.1,
    CA_duration_sec: float = 60,
    gamry_i_range: str = "auto",
    gamrychannelwait: int = -1,
    gamrychannelsend: int = 0,
    illumination_source: str = "doric_wled",
    illumination_wavelength: float = 0.0,
    illumination_intensity: float = 0.0,
    illumination_intensity_date: str = "n/a",
    illumination_side: str = "front",
    toggle_dark_time_init: float = 0.0,
    toggle_illum_duty: float = 0.5,
    toggle_illum_period: float = 2.0,
    toggle_illum_time: float = -1,
    toggle2_source: str = "spec_trig",
    toggle2_init_delay: float = 0.0,
    toggle2_duty: float = 0.5,
    toggle2_period: float = 2.0,
    toggle2_time: float = -1,
    spec_int_time_ms: float = 15,
    spec_n_avg: int = 10,
    spec_technique: str = "T_UVVIS",
    comment: str = "",
):
    """last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    if int(round(apm.pars.toggle_illum_time)) == -1:
        apm.pars.toggle_illum_time = apm.pars.CA_duration_sec
    if int(round(apm.pars.toggle2_time)) == -1:
        apm.pars.toggle2_time = apm.pars.CA_duration_sec

    # get sample for gamry
    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {
            "custom": "cell1_we",
        },
        to_globalexp_params=[
            "_fast_samples_in"
        ],  # save new liquid_sample_no of eche cell to globals
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
    )

    # setup toggle on galil_io
    apm.add(
        IO_server,
        "set_digital_cycle",
        {
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
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        process_finish=False,
        process_contrib=[
            ProcessContrib.files,
            ProcessContrib.samples_out,
        ],
    )

    # apm.add(ORCH_server, "wait", {"waittime": 5})

    # apm.add(
    #     IO_server,
    #     "set_digital_out",
    #     {
    #         "do_item": apm.pars.illumination_source,
    #         "on": True,
    #     },
    # )

    apm.add(
        CAM_server,
        "acquire_image",
        {"duration": min(apm.pars.CA_duration_sec, 10), "acqusition_rate": 0.5},
        start_condition=ActionStartCondition.no_wait,
        nonblocking=True,
    )

    for ss in SPECSRV_MAP[apm.pars.spec_technique]:
        apm.add(
            ss,
            "acquire_spec_extrig",
            {
                "int_time": apm.pars.spec_int_time_ms,
                "n_avg": apm.pars.spec_n_avg,
                "duration": apm.pars.toggle2_time,
            },
            from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
            start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            technique_name=apm.pars.spec_technique,
            process_contrib=[
                ProcessContrib.files,
                ProcessContrib.samples_out,
            ],
        )
        # apm.add(
        #     ss,
        #     "acquire_spec_adv",
        #     {
        #         "int_time_ms": apm.pars.spec_int_time_ms,
        #         "n_avg": apm.pars.spec_n_avg,
        #         "duration_sec": apm.pars.toggle2_time,
        #     },
        #     from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
        #     run_use="data",
        #     technique_name=apm.pars.spec_technique,
        #     process_finish=False,
        #     process_contrib=[
        #         ProcessContrib.files,
        #         ProcessContrib.samples_out,
        #     ],
        #     start_condition=ActionStartCondition.no_wait,
        #     nonblocking=True,
        # )

    # apply potential
    potential = (
        apm.pars.CA_potential_vsRHE
        - 1.0 * apm.pars.ref_vs_nhe
        - 0.059 * apm.pars.solution_ph
    )
    print(f"ECHE_sub_CA potential: {potential}")

    apm.add(
        PSTAT_server,
        "run_CA",
        {
            "Vval__V": potential,
            "Tval__s": apm.pars.CA_duration_sec,
            "AcqInterval__s": apm.pars.samplerate_sec,
            "TTLwait": apm.pars.gamrychannelwait,  # -1 disables, else select TTL 0-3
            "TTLsend": apm.pars.gamrychannelsend,  # -1 disables, else select TTL 0-3
            "IErange": apm.pars.gamry_i_range,
        },
        from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
        start_condition=ActionStartCondition.wait_for_server,
        technique_name="CA",
        process_finish=True,
        process_contrib=[
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )

    # apm.add(
    #     IO_server,
    #     "set_digital_out",
    #     {
    #         "do_item": apm.pars.illumination_source,
    #         "on": False,
    #     },
    # )

    return apm.action_list  # returns complete action list to orch


def ECHEUVIS_sub_CP_led(
    experiment: Experiment,
    experiment_version: int = 6,
    CP_current: float = 0.0,
    solution_ph: float = 9.53,
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,  # currently liquid sample database number
    solution_bubble_gas: str = "O2",
    measurement_area: float = 0.071,  # 3mm diameter droplet
    ref_electrode_type: str = "NHE",
    ref_vs_nhe: float = 0.21,
    samplerate_sec: float = 0.1,
    CP_duration_sec: float = 60,
    gamry_i_range: str = "auto",
    gamrychannelwait: int = -1,
    gamrychannelsend: int = 0,
    illumination_source: str = "doric_wled",
    illumination_wavelength: float = 0.0,
    illumination_intensity: float = 0.0,
    illumination_intensity_date: str = "n/a",
    illumination_side: str = "front",
    toggle_dark_time_init: float = 0.0,
    toggle_illum_duty: float = 0.5,
    toggle_illum_period: float = 2.0,
    toggle_illum_time: float = -1,
    toggle2_source: str = "spec_trig",
    toggle2_init_delay: float = 0.0,
    toggle2_duty: float = 0.5,
    toggle2_period: float = 2.0,
    toggle2_time: float = -1,
    spec_int_time_ms: float = 15,
    spec_n_avg: int = 10,
    spec_technique: str = "T_UVVIS",
    comment: str = "",
):
    """last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    if int(round(apm.pars.toggle_illum_time)) == -1:
        apm.pars.toggle_illum_time = apm.pars.CP_duration_sec
    if int(round(apm.pars.toggle2_time)) == -1:
        apm.pars.toggle2_time = apm.pars.CP_duration_sec

    # get sample for gamry
    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {
            "custom": "cell1_we",
        },
        to_globalexp_params=[
            "_fast_samples_in"
        ],  # save new liquid_sample_no of eche cell to globals
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
    )

    # setup toggle on galil_io
    apm.add(
        IO_server,
        "set_digital_cycle",
        {
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
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        process_finish=False,
        process_contrib=[
            ProcessContrib.files,
            ProcessContrib.samples_out,
        ],
    )

    # apm.add(ORCH_server, "wait", {"waittime": 5})
    
    # apm.add(
    #     IO_server,
    #     "set_digital_out",
    #     {
    #         "do_item": apm.pars.illumination_source,
    #         "on": True,
    #     },
    # )

    apm.add(
        CAM_server,
        "acquire_image",
        {"duration": min(apm.pars.CP_duration_sec, 10), "acqusition_rate": 0.5},
        start_condition=ActionStartCondition.no_wait,
        nonblocking=True,
    )
    
    for ss in SPECSRV_MAP[apm.pars.spec_technique]:
        apm.add(
            ss,
            "acquire_spec_extrig",
            {
                "int_time": apm.pars.spec_int_time_ms,
                "n_avg": apm.pars.spec_n_avg,
                "duration": apm.pars.toggle2_time,
            },
            from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
            start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            technique_name=apm.pars.spec_technique,
            process_contrib=[
                ProcessContrib.files,
                ProcessContrib.samples_out,
            ],
        )
        # apm.add(
        #     ss,
        #     "acquire_spec_adv",
        #     {
        #         "int_time_ms": apm.pars.spec_int_time_ms,
        #         "n_avg": apm.pars.spec_n_avg,
        #         "duration_sec": apm.pars.toggle2_time,
        #     },
        #     from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
        #     run_use="data",
        #     technique_name=apm.pars.spec_technique,
        #     process_finish=False,
        #     process_contrib=[
        #         ProcessContrib.files,
        #         ProcessContrib.samples_out,
        #     ],
        #     start_condition=ActionStartCondition.no_wait,
        #     nonblocking=True,
        # )


    apm.add(
        PSTAT_server,
        "run_CP",
        {
            "Ival__A": apm.pars.CP_current,
            "Tval__s": apm.pars.CP_duration_sec,
            "AcqInterval__s": apm.pars.samplerate_sec,
            "TTLwait": apm.pars.gamrychannelwait,  # -1 disables, else select TTL 0-3
            "TTLsend": apm.pars.gamrychannelsend,  # -1 disables, else select TTL 0-3
            "IErange": apm.pars.gamry_i_range,
        },
        from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
        start_condition=ActionStartCondition.wait_for_server,
        technique_name="CP",
        process_finish=True,
        process_contrib=[
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )

    # apm.add(
    #     IO_server,
    #     "set_digital_out",
    #     {
    #         "do_item": apm.pars.illumination_source,
    #         "on": False,
    #     },
    # )

    return apm.action_list  # returns complete action list to orch


def ECHEUVIS_sub_interrupt(
    experiment: Experiment,
    experiment_version: int = 1,
    reason: str = "wait",
):
    apm = ActionPlanMaker()
    apm.add(ORCH_server, "interrupt", {"reason": apm.pars.reason})
    return apm.action_list


def ECHEUVIS_sub_OCV_led(
    experiment: Experiment,
    experiment_version: int = 6,
    solution_ph: float = 9.53,
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,  # currently liquid sample database number
    solution_bubble_gas: str = "O2",
    measurement_area: float = 0.071,  # 3mm diameter droplet
    ref_electrode_type: str = "NHE",
    ref_vs_nhe: float = 0.21,
    samplerate_sec: float = 0.1,
    OCV_duration_sec: float = 0.0,
    gamry_i_range: str = "auto",
    gamrychannelwait: int = -1,
    gamrychannelsend: int = 0,
    illumination_source: str = "doric_wled",
    illumination_wavelength: float = 0.0,
    illumination_intensity: float = 0.0,
    illumination_intensity_date: str = "n/a",
    illumination_side: str = "front",
    toggle_dark_time_init: float = 0.0,
    toggle_illum_duty: float = 0.5,
    toggle_illum_period: float = 2.0,
    toggle_illum_time: float = -1,
    toggle2_source: str = "spec_trig",
    toggle2_init_delay: float = 0.0,
    toggle2_duty: float = 0.5,
    toggle2_period: float = 2.0,
    toggle2_time: float = -1,
    spec_int_time_ms: float = 15,
    spec_n_avg: int = 10,
    spec_technique: str = "T_UVVIS",
    comment: str = "",
):
    """last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    if int(round(apm.pars.toggle_illum_time)) == -1:
        apm.pars.toggle_illum_time = apm.pars.OCV_duration_sec
    if int(round(apm.pars.toggle2_time)) == -1:
        apm.pars.toggle2_time = apm.pars.OCV_duration_sec

    # get sample for gamry
    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {
            "custom": "cell1_we",
        },
        to_globalexp_params=[
            "_fast_samples_in"
        ],  # save new liquid_sample_no of eche cell to globals
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
    )

    # setup toggle on galil_io
    apm.add(
        IO_server,
        "set_digital_cycle",
        {
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
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        process_finish=False,
        process_contrib=[
            ProcessContrib.files,
            ProcessContrib.samples_out,
        ],
    )

    # apm.add(ORCH_server, "wait", {"waittime": 2})

    # apm.add(
    #     IO_server,
    #     "set_digital_out",
    #     {
    #         "do_item": apm.pars.illumination_source,
    #         "on": True,
    #     },
    # )

    apm.add(
        CAM_server,
        "acquire_image",
        {"duration": min(apm.pars.OCV_duration_sec, 10), "acqusition_rate": 0.5},
        start_condition=ActionStartCondition.wait_for_orch,
        nonblocking=True,
    )

    for ss in SPECSRV_MAP[apm.pars.spec_technique]:
        apm.add(
            ss,
            "acquire_spec_extrig",
            {
                "int_time": apm.pars.spec_int_time_ms,
                "n_avg": apm.pars.spec_n_avg,
                "duration": apm.pars.toggle2_time,
            },
            from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
            start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            technique_name=apm.pars.spec_technique,
            process_contrib=[
                ProcessContrib.files,
                ProcessContrib.samples_out,
            ],
        )
        # apm.add(
        #     ss,
        #     "acquire_spec_adv",
        #     {
        #         "int_time_ms": apm.pars.spec_int_time_ms,
        #         "n_avg": apm.pars.spec_n_avg,
        #         "duration_sec": apm.pars.toggle2_time,
        #     },
        #     from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
        #     run_use="data",
        #     technique_name=apm.pars.spec_technique,
        #     process_finish=False,
        #     process_contrib=[
        #         ProcessContrib.files,
        #         ProcessContrib.samples_out,
        #     ],
        #     start_condition=ActionStartCondition.no_wait,
        #     nonblocking=True,
        # )

    apm.add(
        PSTAT_server,
        "run_OCV",
        {
            "Tval__s": apm.pars.OCV_duration_sec,
            "AcqInterval__s": apm.pars.samplerate_sec,
            "TTLwait": apm.pars.gamrychannelwait,  # -1 disables, else select TTL 0-3
            "TTLsend": apm.pars.gamrychannelsend,  # -1 disables, else select TTL 0-3
            "IErange": apm.pars.gamry_i_range,
        },
        from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
        start_condition=ActionStartCondition.wait_for_server,
        technique_name="OCV",
        process_finish=True,
        process_contrib=[
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )

    apm.add(
        IO_server,
        "set_digital_out",
        {
            "do_item": apm.pars.illumination_source,
            "on": False,
        },
    )

    return apm.action_list  # returns complete action list to orch


def ECHEUVIS_sub_disengage(
    experiment: Experiment,
    experiment_version: int = 1,
    clear_we: bool = True,
    clear_ce: bool = False,
    z_height: float = 0,
    vent_wait: float = 10.0,
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    for clear_flag, items in (
        (apm.pars.clear_ce, ("ce_vent", "ce_pump")),
        (apm.pars.clear_we, ("we_vent", "we_pump")),
    ):
        for item in items:
            apm.add(
                IO_server,
                "set_digital_out",
                {"do_item": item, "on": clear_flag},
                ActionStartCondition.no_wait,
            )
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.vent_wait})
    # lower z (disengage)
    apm.add(
        KMOTOR_server, "kmove", {"move_mode": "absolute", "value_mm": apm.pars.z_height}
    )
    for i, item in enumerate(["we_vent", "we_pump", "ce_vent", "ce_pump"]):
        apm.add(
            IO_server,
            "set_digital_out",
            {"do_item": item, "on": False},
            ActionStartCondition.no_wait
            if i > 0
            else ActionStartCondition.wait_for_all,
        )
    return apm.action_list  # returns complete action list to orch


def ECHEUVIS_sub_engage(
    experiment: Experiment,
    experiment_version: int = 1,
    flow_we: bool = True,
    flow_ce: bool = True,
    z_height: float = 1.5,
    fill_wait: float = 10.0,
):
    # raise z (engage)
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(
        KMOTOR_server, "kmove", {"move_mode": "absolute", "value_mm": apm.pars.z_height}
    )
    # close vent valves
    for item in ("we_vent", "ce_vent"):
        apm.add(
            IO_server,
            "set_digital_out",
            {"do_item": item, "on": False},
            ActionStartCondition.no_wait,
        )
    # pull electrolyte through WE and CE chambers
    for item, flow_flag in (
        ("we_flow", apm.pars.flow_we),
        ("we_pump", apm.pars.flow_we),
        ("ce_pump", apm.pars.flow_ce),
    ):
        apm.add(
            IO_server,
            "set_digital_out",
            {"do_item": item, "on": flow_flag},
            ActionStartCondition.no_wait,
        )
    # wait for specified time (seconds)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.fill_wait})
    # stop high speed flow, but keep low speed flow if flow_we is True
    for i, (item, flow_flag) in enumerate(
        [("we_flow", apm.pars.flow_we), ("we_pump", False), ("ce_pump", False)]
    ):
        apm.add(
            IO_server,
            "set_digital_out",
            {"do_item": item, "on": flow_flag},
            ActionStartCondition.no_wait
            if i > 0
            else ActionStartCondition.wait_for_all,
        )
    return apm.action_list  # returns complete action list to orch


def ECHEUVIS_analysis_stability(
    experiment: Experiment,
    experiment_version: int = 2,
    sequence_uuid: str = "",
    plate_id: int = 0,
    recent: bool = True,
    params: dict = {},
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(
        ANA_server,
        "analyze_echeuvis",
        {
            "sequence_uuid": apm.pars.sequence_uuid,
            "plate_id": apm.pars.plate_id,
            "recent": apm.pars.recent,
            "params": apm.pars.params,
        },
    )
    return apm.action_list
