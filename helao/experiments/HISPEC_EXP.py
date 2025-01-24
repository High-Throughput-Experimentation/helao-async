"""
Experiment library for HISPEC
server_key must be a FastAPI action server defined in config
"""

# everything is a 'machine model schema'
__all__ = [
    "HISPEC_sub_SpEC",
    # "HISPEC_sub_CV_DOtrigger",
    # "HISPEC_sub_CA_led",
    # "HISPEC_sub_CP_led",
    # "HISPEC_sub_OCV_led",
    # "HISPEC_sub_interrupt",
    "HISPEC_sub_startup",
    "HISPEC_sub_shutdown",
    "HiSPEC_sub_PEIS",
    # "HISPEC_sub_engage",
    # "HISPEC_sub_disengage",
    # "HISPEC_analysis_stability",
]

from helao.helpers import logging

if logging.LOGGER is None:
    logger = logging.make_logger(__file__)
else:
    logger = logging.LOGGER

from helao.helpers import config_loader

if config_loader.CONFIG is None:
    rootcfg = {}
else:
    rootcfg = config_loader.CONFIG

from typing import Optional
from socket import gethostname

from helao.helpers.premodels import Experiment, ActionPlanMaker
from helao.helpers.spec_map import SPECSRV_MAP
from helao.drivers.io.enum import TriggerType

from helao.core.models.action_start_condition import ActionStartCondition
from helao.core.models.machine import MachineModel as MM
from helao.core.models.process_contrib import ProcessContrib
from helao.core.models.electrolyte import Electrolyte


EXPERIMENTS = __all__
# these must all be defined but you may not use any of them in the experiment
PSTAT_server = MM(
    server_name="PSTAT", machine_name=gethostname().lower()
).as_dict()  # get host name as local server
MOTOR_server = MM(server_name="MOTOR", machine_name=gethostname().lower()).as_dict()
IO_server = MM(server_name="IO", machine_name=gethostname().lower()).as_dict()
ANDOR_server = MM(server_name="ANDOR", machine_name=gethostname().lower()).as_dict()
ORCH_server = MM(server_name="ORCH", machine_name=gethostname().lower()).as_dict()
PAL_server = MM(server_name="PAL", machine_name=gethostname().lower()).as_dict()
# CAM_server = MM(server_name="CAM", machine_name=gethostname().lower()).as_dict()
KMOTOR_server = MM(server_name="KMOTOR", machine_name=gethostname().lower()).as_dict()
# ANA_server = MM(server_name="ANA", machine_name=gethostname().lower()).as_dict()

toggle_triggertype = TriggerType.risingedge


def HISPEC_sub_startup(experiment: Experiment):
    """Unload custom position."""
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(PAL_server, "archive_custom_unloadall", {"destroy_liquid": True})
    return apm.action_list  # returns complete action list to orch


def HISPEC_sub_shutdown(experiment: Experiment):
    """Unload custom position and disable IR emitter."""
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(PAL_server, "archive_custom_unloadall", {"destroy_liquid": True})
    return apm.action_list  # returns complete action list to orch


# implement Biologic trigger actions
#  use easy_biologic's BiologicDevice.load_techniques() method

# HISPEC_sub_OCVtoCAtoCV -- use OCV potential for conditioning CA and starting CV; CV needs to locally queue after CA
# HISPEC_sub_EIS

# HISPEC_sub_LoSpEC -- CA to SpEC, conditional SpEC
# HISPEC_sub_PD_LoSpEC


# spectral electrochemistry experiment
def HISPEC_sub_SpEC(
    experiment: Experiment,
    experiment_version: int = 1,
    OCV_vsRef: float = 0.0,
    # Vinit_vsRHE: float = 0.0,  # Initial value in volts or amps.
    Vapex1_vsRHE: float = 1.0,  # Apex 1 value in volts or amps.
    # Vapex2_vsRHE: float = -1.0,  # Apex 2 value in volts or amps.
    # Vfinal_vsRHE: float = 0.0,  # Final value in volts or amps.
    scanrate_voltsec: float = 0.02,  # scan rate in volts/second or amps/second.
    samplerate_sec: float = 0.1,
    cycles: int = 1,
    # gamry_i_range: str = "auto",
    gamrychannelwait: int = -1,
    gamrychannelsend: int = 0,
    IRange: str = "m10",
    ERange: str = "v10",
    Bandwidth: str = "BW4",
    solution_ph: float = 0,
    ref_vs_nhe: float = 0.0,
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
):
    """last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    CV_duration_sec = (
        abs(Vapex1_vsRHE - OCV_vsRef) / scanrate_voltsec
    )  # time from initial to Vertex 1
    CV_duration_sec += (
        abs(OCV_vsRef - OCV_vsRef) / scanrate_voltsec
    )  # time from vertex 1 to vertex 2 (imagine for now num scans =1)
    CV_duration_sec += (
        abs(OCV_vsRef - Vapex1_vsRHE) / scanrate_voltsec
    )  # time from vertex to to final
    CV_duration_sec += (
        abs(OCV_vsRef - Vapex1_vsRHE)
        / scanrate_voltsec
        * 2.0
        * (
            cycles - 1
        )  # now, if C>1 we have c-1 triangular waveforms inserted after the first vertex 1.
    )

    if int(round(toggle1_time)) == -1:
        toggle1_time = CV_duration_sec
    # if int(round(toggle2_time)) == -1:
    #     toggle2_time = CV_duration_sec

    # setup Andor camera external trigger acquisition
    apm.add(
        ANDOR_server,
        "acquire",
        {
            "external_trigger": True,
            "duration": CV_duration_sec * 1.05,
            "frames_per_poll": 100,
            "buffer_count": 10,
            "exp_time": 0.0098,
            "framerate": 98,
            "timeout": 15000,
        },
        sync_data=False,
    )

    apm.add(
        ORCH_server,
        "wait",
        {
            "waittime": 3,
        },
        start_condition=ActionStartCondition.no_wait,
    )

    # setup toggle on galil_io
    apm.add(
        IO_server,
        "set_digital_cycle",
        {
            "trigger_name": "gamry_ttl0",
            "triggertype": 1,  # rising edge
            "out_name": ["spec_trig", toggle1_source],  # TODO: parameterize outs
            "out_name_gamry": None,
            "toggle_init_delay": [toggle1_init_delay, toggle1_init_delay],
            "toggle_duty": [toggle1_duty, toggle1_duty],
            "toggle_period": [toggle1_period, toggle1_period],
            "toggle_duration": [toggle1_time, toggle1_time],
        },
        start_condition=ActionStartCondition.wait_for_previous,  # orch is waiting for all action_dq to finish
        process_finish=False,
        process_contrib=[ProcessContrib.files, ProcessContrib.samples_out],
    )

    # apply potential
    apm.add(
        PSTAT_server,
        "run_CV",
        {
            "Vinit__V": OCV_vsRef - 1.0 * ref_vs_nhe - 0.059 * solution_ph,
            "Vapex1__V": Vapex1_vsRHE - 1.0 * ref_vs_nhe - 0.059 * solution_ph,
            "Vapex2__V": OCV_vsRef - 1.0 * ref_vs_nhe - 0.059 * solution_ph,
            "Vfinal__V": OCV_vsRef - 1.0 * ref_vs_nhe - 0.059 * solution_ph,
            "ScanRate__V_s": scanrate_voltsec,
            "AcqInterval__s": samplerate_sec,
            "Cycles": cycles,
            "TTLwait": gamrychannelwait,  # -1 disables, else select TTL 0-3
            "TTLsend": gamrychannelsend,  # -1 disables, else select TTL 0-3
            "IRange": IRange,
            "ERange": ERange,
            "Bandwidth": Bandwidth,
        },
        # from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
        start_condition=ActionStartCondition.wait_for_previous,
        technique_name="CV",
        process_finish=True,
        process_contrib=[
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    return apm.action_list  # returns complete action list to orch


def HiSPEC_sub_PEIS(
    experiment: Experiment,
    experiment_version: int = 1,
    Vinit__V: float = 0.0,  # Initial value in volts or amps.
    Vamp__V: float = 0.01,  # Amplitude value in volts
    Finit__Hz: float = 1,  # Initial frequency in Hz.
    Ffinal__Hz: float = 2000000,  # Final frequency in Hz.
    FrequencyNumber: int = 60,
    Duration__s: float = 0,  # Duration in seconds.
    AcqInterval__s: float = 0.1,  # Time between data acq in seconds.
    SweepMode: str = "log",
    Repeats: int = 10,
    DelayFraction: float = 0.1,
    # vs_initial: bool = False,  # True if vs initial, False if vs previous.
    IRange: str = "m10",
    ERange: str = "v10",
    Bandwidth: str = "BW4",
    channel: int = 0,
    TTLwait: int = -1,
    TTLsend: int = -1,
    TTLduration: float = 1.0,
):

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(
        action_server=PSTAT_server,
        action_name="run_PEIS",
        action_params={
            "Vinit__V": Vinit__V,
            "Vamp__V": Vamp__V,
            "Finit__Hz": Finit__Hz,
            "Ffinal__Hz": Ffinal__Hz,
            "FrequencyNumber": FrequencyNumber,
            "Duration__s": Duration__s,
            "AcqInterval__s": AcqInterval__s,
            "SweepMode": SweepMode,
            "Repeats": Repeats,
            "DelayFraction": DelayFraction,
            "IRange": IRange,
            "ERange": ERange,
            "Bandwidth": Bandwidth,
            "channel": channel,
            "TTLwait": TTLwait,
            "TTLsend": TTLsend,
            "TTLduration": TTLduration,
        },
        start_condition=ActionStartCondition.wait_for_previous,
        technique_name="PEIS",
        process_finish=True,
        process_contrib=[
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    return apm.action_list  # returns complete action list to orch


# def HISPEC_sub_CV_DOtrigger(
#     experiment: Experiment,
#     experiment_version: int = 1,
#     Vinit_vsRHE: float = 0.0,  # Initial value in volts or amps.
#     Vapex1_vsRHE: float = 1.0,  # Apex 1 value in volts or amps.
#     Vapex2_vsRHE: float = -1.0,  # Apex 2 value in volts or amps.
#     Vfinal_vsRHE: float = 0.0,  # Final value in volts or amps.
#     scanrate_voltsec: Optional[
#         float
#     ] = 0.02,  # scan rate in volts/second or amps/second.
#     samplerate_sec: float = 0.1,
#     cycles: int = 1,
#     gamry_i_range: str = "auto",
#     gamrychannelwait: int = 0,
#     gamrychannelsend: int = -1,
#     solution_ph: float = 0,
#     ref_vs_nhe: float = 0.21,
#     toggle1_source: str = "spec_trig",
#     toggle1_init_delay: float = 0.0,
#     toggle1_duty: float = 0.5,
#     toggle1_period: float = 2.0,
#     toggle1_time: float = -1,
#     toggle2_source: str = "doric_wled",
#     # toggle2_init_delay: float = 0.0,
#     # toggle2_duty: float = 0.5,
#     # toggle2_period: float = 2.0,
#     # toggle2_time: float = -1,
#     comment: str = "",
# ):
#     """last functionality test: -"""

#     apm = ActionPlanMaker()  # exposes function parameters via apm.pars

#     CV_duration_sec = abs(Vapex1_vsRHE - Vinit_vsRHE) / scanrate_voltsec
#     CV_duration_sec += abs(Vfinal_vsRHE - Vapex2_vsRHE) / scanrate_voltsec
#     CV_duration_sec += abs(Vapex2_vsRHE - Vapex1_vsRHE) / scanrate_voltsec * cycles
#     CV_duration_sec += (
#         abs(Vapex2_vsRHE - Vapex1_vsRHE) / scanrate_voltsec * 2.0 * (cycles - 1)
#     )

#     if int(round(toggle1_time)) == -1:
#         toggle1_time = CV_duration_sec + 1
#     # if int(round(toggle2_time)) == -1:
#     #     toggle2_time = CV_duration_sec

#     # setup Andor camera external trigger acquisition
#     apm.add(
#         ANDOR_server,
#         "acquire",
#         {
#             "external_trigger": True,
#             "duration": CV_duration_sec + 1,
#             "frames_per_poll": 100,
#             "buffer_count": 10,
#             "exp_time": 0.0098,
#             "framerate": 98,
#             "timeout": 10000,
#         },
#     )

#     # apply potential
#     apm.add(
#         PSTAT_server,
#         "run_CV",
#         {
#             "Vinit__V": Vinit_vsRHE - 1.0 * ref_vs_nhe - 0.059 * solution_ph,
#             "Vapex1__V": Vapex1_vsRHE - 1.0 * ref_vs_nhe - 0.059 * solution_ph,
#             "Vapex2__V": Vapex2_vsRHE - 1.0 * ref_vs_nhe - 0.059 * solution_ph,
#             "Vfinal__V": Vfinal_vsRHE - 1.0 * ref_vs_nhe - 0.059 * solution_ph,
#             "ScanRate__V_s": scanrate_voltsec,
#             "AcqInterval__s": samplerate_sec,
#             "Cycles": cycles,
#             "TTLwait": gamrychannelwait,  # -1 disables, else select TTL 0-3
#             "TTLsend": gamrychannelsend,  # -1 disables, else select TTL 0-3
#             "IErange": gamry_i_range,
#         },
#         # from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
#         start_condition=ActionStartCondition.no_wait,
#         technique_name="CV",
#         process_finish=True,
#         process_contrib=[
#             ProcessContrib.files,
#             ProcessContrib.samples_in,
#             ProcessContrib.samples_out,
#         ],
#     )


#     # setup toggle on galil_io
#     apm.add(
#         IO_server,
#         "set_digital_cycle",
#         {
#             "trigger_name": "gamry_ttl0",
#             "triggertype": 1,  # rising edge
#             "out_name": [toggle1_source, toggle2_source],
#             "out_name_gamry": None,
#             "toggle_init_delay": [toggle1_init_delay, toggle1_init_delay],
#             "toggle_duty": [toggle1_duty, toggle1_duty],
#             "toggle_period": [toggle1_period, toggle1_period],
#             "toggle_duration": [toggle1_time, toggle1_time],
#         },
#         start_condition=ActionStartCondition.wait_for_previous,  # orch is waiting for all action_dq to finish
#         process_finish=False,
#         process_contrib=[ProcessContrib.files, ProcessContrib.samples_out],
#     )

#     apm.add(ORCH_server, "wait", {"waittime": 3}, ActionStartCondition.wait_for_previous)

#     apm.add(
#         IO_server,
#         "set_digital_out",
#         {"do_item": "ir_emitter", "on": True},
#         start_condition=ActionStartCondition.wait_for_previous,
#     )
#     apm.add(ORCH_server, "wait", {"waittime": toggle1_time}, ActionStartCondition.wait_for_previous)
#     apm.add(ORCH_server, "wait", {"waittime": 5}, ActionStartCondition.wait_for_all)
#     apm.add(
#         IO_server,
#         "set_digital_out",
#         {"do_item": "ir_emitter", "on": False},
#         start_condition=ActionStartCondition.wait_for_all,
#     )

#     apm.add(IO_server, "stop_digital_cycle", {}, start_condition=ActionStartCondition.wait_for_all)

#     return apm.action_list  # returns complete action list to orch


# def HISPEC_sub_CA_led(
#     experiment: Experiment,
#     experiment_version: int = 6,
#     CA_potential_vsRHE: float = 0.0,
#     solution_ph: float = 9.53,
#     reservoir_electrolyte: Electrolyte = "SLF10",
#     reservoir_liquid_sample_no: int = 1,  # currently liquid sample database number
#     solution_bubble_gas: str = "O2",
#     measurement_area: float = 0.071,  # 3mm diameter droplet
#     ref_electrode_type: str = "NHE",
#     ref_vs_nhe: float = 0.21,
#     samplerate_sec: float = 0.1,
#     CA_duration_sec: float = 60,
#     gamry_i_range: str = "auto",
#     gamrychannelwait: int = -1,
#     gamrychannelsend: int = 0,
#     toggle1_source: str = "doric_wled",
#     illumination_wavelength: float = 0.0,
#     illumination_intensity: float = 0.0,
#     illumination_intensity_date: str = "n/a",
#     illumination_side: str = "front",
#     toggle1_init_delay: float = 0.0,
#     toggle1_duty: float = 0.5,
#     toggle1_period: float = 2.0,
#     toggle1_time: float = -1,
#     toggle2_source: str = "spec_trig",
#     toggle2_init_delay: float = 0.0,
#     toggle2_duty: float = 0.5,
#     toggle2_period: float = 2.0,
#     toggle2_time: float = -1,
#     spec_int_time_ms: float = 15,
#     spec_n_avg: int = 10,
#     spec_technique: str = "T_UVVIS",
#     comment: str = "",
# ):
#     """last functionality test: -"""

#     apm = ActionPlanMaker()  # exposes function parameters via apm.pars

#     if int(round(toggle1_time)) == -1:
#         toggle1_time = CA_duration_sec
#     if int(round(toggle2_time)) == -1:
#         toggle2_time = CA_duration_sec

#     # get sample for gamry
#     apm.add(
#         PAL_server,
#         "archive_custom_query_sample",
#         {
#             "custom": "cell1_we",
#         },
#         to_globalexp_params=[
#             "_fast_samples_in"
#         ],  # save new liquid_sample_no of eche cell to globals
#         start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
#     )

#     # setup toggle on galil_io
#     apm.add(
#         IO_server,
#         "set_digital_cycle",
#         {
#             "trigger_name": "gamry_ttl0",
#             "triggertype": toggle_triggertype,
#             "out_name": [toggle1_source, toggle2_source],
#             "out_name_gamry": None,
#             "toggle_init_delay": [
#                 toggle1_init_delay,
#                 toggle2_init_delay,
#             ],
#             "toggle_duty": [toggle1_duty, toggle2_duty],
#             "toggle_period": [
#                 toggle1_period,
#                 toggle2_period,
#             ],
#             "toggle_duration": [toggle1_time, toggle2_time],
#         },
#         start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
#         process_finish=False,
#         process_contrib=[
#             ProcessContrib.files,
#             ProcessContrib.samples_out,
#         ],
#     )

#     # apm.add(ORCH_server, "wait", {"waittime": 5})

#     # apm.add(
#     #     IO_server,
#     #     "set_digital_out",
#     #     {
#     #         "do_item": toggle1_source,
#     #         "on": True,
#     #     },
#     # )

#     apm.add(
#         CAM_server,
#         "acquire_image",
#         {"duration": min(CA_duration_sec, 10), "acqusition_rate": 0.5},
#         start_condition=ActionStartCondition.no_wait,
#         nonblocking=True,
#     )

#     for ss in SPECSRV_MAP[spec_technique]:
#         apm.add(
#             ss,
#             "acquire_spec_extrig",
#             {
#                 "int_time": spec_int_time_ms,
#                 "n_avg": spec_n_avg,
#                 "duration": toggle2_time,
#             },
#             from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
#             start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
#             technique_name=spec_technique,
#             process_contrib=[
#                 ProcessContrib.files,
#                 ProcessContrib.samples_out,
#             ],
#         )
#         # apm.add(
#         #     ss,
#         #     "acquire_spec_adv",
#         #     {
#         #         "int_time_ms": spec_int_time_ms,
#         #         "n_avg": spec_n_avg,
#         #         "duration_sec": toggle2_time,
#         #     },
#         #     from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
#         #     run_use="data",
#         #     technique_name=spec_technique,
#         #     process_finish=False,
#         #     process_contrib=[
#         #         ProcessContrib.files,
#         #         ProcessContrib.samples_out,
#         #     ],
#         #     start_condition=ActionStartCondition.no_wait,
#         #     nonblocking=True,
#         # )

#     # apply potential
#     potential = (
#         CA_potential_vsRHE
#         - 1.0 * ref_vs_nhe
#         - 0.059 * solution_ph
#     )
#     print(f"ECHE_sub_CA potential: {potential}")

#     apm.add(
#         PSTAT_server,
#         "run_CA",
#         {
#             "Vval__V": potential,
#             "Tval__s": CA_duration_sec,
#             "AcqInterval__s": samplerate_sec,
#             "TTLwait": gamrychannelwait,  # -1 disables, else select TTL 0-3
#             "TTLsend": gamrychannelsend,  # -1 disables, else select TTL 0-3
#             "IErange": gamry_i_range,
#         },
#         from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
#         start_condition=ActionStartCondition.wait_for_server,
#         technique_name="CA",
#         process_finish=True,
#         process_contrib=[
#             ProcessContrib.files,
#             ProcessContrib.samples_in,
#             ProcessContrib.samples_out,
#         ],
#     )

#     # apm.add(
#     #     IO_server,
#     #     "set_digital_out",
#     #     {
#     #         "do_item": toggle1_source,
#     #         "on": False,
#     #     },
#     # )

#     return apm.action_list  # returns complete action list to orch


# def HISPEC_sub_CP_led(
#     experiment: Experiment,
#     experiment_version: int = 6,
#     CP_current: float = 0.0,
#     solution_ph: float = 9.53,
#     reservoir_electrolyte: Electrolyte = "SLF10",
#     reservoir_liquid_sample_no: int = 1,  # currently liquid sample database number
#     solution_bubble_gas: str = "O2",
#     measurement_area: float = 0.071,  # 3mm diameter droplet
#     ref_electrode_type: str = "NHE",
#     ref_vs_nhe: float = 0.21,
#     samplerate_sec: float = 0.1,
#     CP_duration_sec: float = 60,
#     gamry_i_range: str = "auto",
#     gamrychannelwait: int = -1,
#     gamrychannelsend: int = 0,
#     toggle1_source: str = "doric_wled",
#     illumination_wavelength: float = 0.0,
#     illumination_intensity: float = 0.0,
#     illumination_intensity_date: str = "n/a",
#     illumination_side: str = "front",
#     toggle1_init_delay: float = 0.0,
#     toggle1_duty: float = 0.5,
#     toggle1_period: float = 2.0,
#     toggle1_time: float = -1,
#     toggle2_source: str = "spec_trig",
#     toggle2_init_delay: float = 0.0,
#     toggle2_duty: float = 0.5,
#     toggle2_period: float = 2.0,
#     toggle2_time: float = -1,
#     spec_int_time_ms: float = 15,
#     spec_n_avg: int = 10,
#     spec_technique: str = "T_UVVIS",
#     comment: str = "",
# ):
#     """last functionality test: -"""

#     apm = ActionPlanMaker()  # exposes function parameters via apm.pars

#     if int(round(toggle1_time)) == -1:
#         toggle1_time = CP_duration_sec
#     if int(round(toggle2_time)) == -1:
#         toggle2_time = CP_duration_sec

#     # get sample for gamry
#     apm.add(
#         PAL_server,
#         "archive_custom_query_sample",
#         {
#             "custom": "cell1_we",
#         },
#         to_globalexp_params=[
#             "_fast_samples_in"
#         ],  # save new liquid_sample_no of eche cell to globals
#         start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
#     )

#     # setup toggle on galil_io
#     apm.add(
#         IO_server,
#         "set_digital_cycle",
#         {
#             "trigger_name": "gamry_ttl0",
#             "triggertype": toggle_triggertype,
#             "out_name": [toggle1_source, toggle2_source],
#             "out_name_gamry": None,
#             "toggle_init_delay": [
#                 toggle1_init_delay,
#                 toggle2_init_delay,
#             ],
#             "toggle_duty": [toggle1_duty, toggle2_duty],
#             "toggle_period": [
#                 toggle1_period,
#                 toggle2_period,
#             ],
#             "toggle_duration": [toggle1_time, toggle2_time],
#         },
#         start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
#         process_finish=False,
#         process_contrib=[
#             ProcessContrib.files,
#             ProcessContrib.samples_out,
#         ],
#     )

#     # apm.add(ORCH_server, "wait", {"waittime": 5})

#     # apm.add(
#     #     IO_server,
#     #     "set_digital_out",
#     #     {
#     #         "do_item": toggle1_source,
#     #         "on": True,
#     #     },
#     # )

#     apm.add(
#         CAM_server,
#         "acquire_image",
#         {"duration": min(CP_duration_sec, 10), "acqusition_rate": 0.5},
#         start_condition=ActionStartCondition.no_wait,
#         nonblocking=True,
#     )

#     for ss in SPECSRV_MAP[spec_technique]:
#         apm.add(
#             ss,
#             "acquire_spec_extrig",
#             {
#                 "int_time": spec_int_time_ms,
#                 "n_avg": spec_n_avg,
#                 "duration": toggle2_time,
#             },
#             from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
#             start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
#             technique_name=spec_technique,
#             process_contrib=[
#                 ProcessContrib.files,
#                 ProcessContrib.samples_out,
#             ],
#         )
#         # apm.add(
#         #     ss,
#         #     "acquire_spec_adv",
#         #     {
#         #         "int_time_ms": spec_int_time_ms,
#         #         "n_avg": spec_n_avg,
#         #         "duration_sec": toggle2_time,
#         #     },
#         #     from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
#         #     run_use="data",
#         #     technique_name=spec_technique,
#         #     process_finish=False,
#         #     process_contrib=[
#         #         ProcessContrib.files,
#         #         ProcessContrib.samples_out,
#         #     ],
#         #     start_condition=ActionStartCondition.no_wait,
#         #     nonblocking=True,
#         # )


#     apm.add(
#         PSTAT_server,
#         "run_CP",
#         {
#             "Ival__A": CP_current,
#             "Tval__s": CP_duration_sec,
#             "AcqInterval__s": samplerate_sec,
#             "TTLwait": gamrychannelwait,  # -1 disables, else select TTL 0-3
#             "TTLsend": gamrychannelsend,  # -1 disables, else select TTL 0-3
#             "IErange": gamry_i_range,
#         },
#         from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
#         start_condition=ActionStartCondition.wait_for_server,
#         technique_name="CP",
#         process_finish=True,
#         process_contrib=[
#             ProcessContrib.files,
#             ProcessContrib.samples_in,
#             ProcessContrib.samples_out,
#         ],
#     )

#     # apm.add(
#     #     IO_server,
#     #     "set_digital_out",
#     #     {
#     #         "do_item": toggle1_source,
#     #         "on": False,
#     #     },
#     # )

#     return apm.action_list  # returns complete action list to orch


# def HISPEC_sub_interrupt(
#     experiment: Experiment,
#     experiment_version: int = 1,
#     reason: str = "wait",
# ):
#     apm = ActionPlanMaker()
#     apm.add(ORCH_server, "interrupt", {"reason": reason})
#     return apm.action_list


# def HISPEC_sub_OCV_led(
#     experiment: Experiment,
#     experiment_version: int = 6,
#     solution_ph: float = 9.53,
#     reservoir_electrolyte: Electrolyte = "SLF10",
#     reservoir_liquid_sample_no: int = 1,  # currently liquid sample database number
#     solution_bubble_gas: str = "O2",
#     measurement_area: float = 0.071,  # 3mm diameter droplet
#     ref_electrode_type: str = "NHE",
#     ref_vs_nhe: float = 0.21,
#     samplerate_sec: float = 0.1,
#     OCV_duration_sec: float = 0.0,
#     gamry_i_range: str = "auto",
#     gamrychannelwait: int = -1,
#     gamrychannelsend: int = 0,
#     toggle1_source: str = "doric_wled",
#     illumination_wavelength: float = 0.0,
#     illumination_intensity: float = 0.0,
#     illumination_intensity_date: str = "n/a",
#     illumination_side: str = "front",
#     toggle1_init_delay: float = 0.0,
#     toggle1_duty: float = 0.5,
#     toggle1_period: float = 2.0,
#     toggle1_time: float = -1,
#     toggle2_source: str = "spec_trig",
#     toggle2_init_delay: float = 0.0,
#     toggle2_duty: float = 0.5,
#     toggle2_period: float = 2.0,
#     toggle2_time: float = -1,
#     spec_int_time_ms: float = 15,
#     spec_n_avg: int = 10,
#     spec_technique: str = "T_UVVIS",
#     comment: str = "",
# ):
#     """last functionality test: -"""

#     apm = ActionPlanMaker()  # exposes function parameters via apm.pars

#     if int(round(toggle1_time)) == -1:
#         toggle1_time = OCV_duration_sec
#     if int(round(toggle2_time)) == -1:
#         toggle2_time = OCV_duration_sec

#     # get sample for gamry
#     apm.add(
#         PAL_server,
#         "archive_custom_query_sample",
#         {
#             "custom": "cell1_we",
#         },
#         to_globalexp_params=[
#             "_fast_samples_in"
#         ],  # save new liquid_sample_no of eche cell to globals
#         start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
#     )

#     # setup toggle on galil_io
#     apm.add(
#         IO_server,
#         "set_digital_cycle",
#         {
#             "trigger_name": "gamry_ttl0",
#             "triggertype": toggle_triggertype,
#             "out_name": [toggle1_source, toggle2_source],
#             "out_name_gamry": None,
#             "toggle_init_delay": [
#                 toggle1_init_delay,
#                 toggle2_init_delay,
#             ],
#             "toggle_duty": [toggle1_duty, toggle2_duty],
#             "toggle_period": [
#                 toggle1_period,
#                 toggle2_period,
#             ],
#             "toggle_duration": [toggle1_time, toggle2_time],
#         },
#         start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
#         process_finish=False,
#         process_contrib=[
#             ProcessContrib.files,
#             ProcessContrib.samples_out,
#         ],
#     )

#     # apm.add(ORCH_server, "wait", {"waittime": 2})

#     # apm.add(
#     #     IO_server,
#     #     "set_digital_out",
#     #     {
#     #         "do_item": toggle1_source,
#     #         "on": True,
#     #     },
#     # )

#     apm.add(
#         CAM_server,
#         "acquire_image",
#         {"duration": min(OCV_duration_sec, 10), "acqusition_rate": 0.5},
#         start_condition=ActionStartCondition.wait_for_orch,
#         nonblocking=True,
#     )

#     for ss in SPECSRV_MAP[spec_technique]:
#         apm.add(
#             ss,
#             "acquire_spec_extrig",
#             {
#                 "int_time": spec_int_time_ms,
#                 "n_avg": spec_n_avg,
#                 "duration": toggle2_time,
#             },
#             from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
#             start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
#             technique_name=spec_technique,
#             process_contrib=[
#                 ProcessContrib.files,
#                 ProcessContrib.samples_out,
#             ],
#         )
#         # apm.add(
#         #     ss,
#         #     "acquire_spec_adv",
#         #     {
#         #         "int_time_ms": spec_int_time_ms,
#         #         "n_avg": spec_n_avg,
#         #         "duration_sec": toggle2_time,
#         #     },
#         #     from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
#         #     run_use="data",
#         #     technique_name=spec_technique,
#         #     process_finish=False,
#         #     process_contrib=[
#         #         ProcessContrib.files,
#         #         ProcessContrib.samples_out,
#         #     ],
#         #     start_condition=ActionStartCondition.no_wait,
#         #     nonblocking=True,
#         # )

#     apm.add(
#         PSTAT_server,
#         "run_OCV",
#         {
#             "Tval__s": OCV_duration_sec,
#             "AcqInterval__s": samplerate_sec,
#             "TTLwait": gamrychannelwait,  # -1 disables, else select TTL 0-3
#             "TTLsend": gamrychannelsend,  # -1 disables, else select TTL 0-3
#             "IErange": gamry_i_range,
#         },
#         from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
#         start_condition=ActionStartCondition.wait_for_server,
#         technique_name="OCV",
#         process_finish=True,
#         process_contrib=[
#             ProcessContrib.files,
#             ProcessContrib.samples_in,
#             ProcessContrib.samples_out,
#         ],
#     )

#     apm.add(
#         IO_server,
#         "set_digital_out",
#         {
#             "do_item": toggle1_source,
#             "on": False,
#         },
#     )

#     return apm.action_list  # returns complete action list to orch


# def HISPEC_sub_disengage(
#     experiment: Experiment,
#     experiment_version: int = 1,
#     clear_we: bool = True,
#     clear_ce: bool = False,
#     z_height: float = 0,
#     vent_wait: float = 10.0,
# ):
#     apm = ActionPlanMaker()  # exposes function parameters via apm.pars
#     for clear_flag, items in (
#         (clear_ce, ("ce_vent", "ce_pump")),
#         (clear_we, ("we_vent", "we_pump")),
#     ):
#         for item in items:
#             apm.add(
#                 IO_server,
#                 "set_digital_out",
#                 {"do_item": item, "on": clear_flag},
#                 ActionStartCondition.no_wait,
#             )
#     apm.add(ORCH_server, "wait", {"waittime": vent_wait})
#     # lower z (disengage)
#     apm.add(
#         KMOTOR_server, "kmove", {"move_mode": "absolute", "value_mm": z_height}
#     )
#     for i, item in enumerate(["we_vent", "we_pump", "ce_vent", "ce_pump"]):
#         apm.add(
#             IO_server,
#             "set_digital_out",
#             {"do_item": item, "on": False},
#             ActionStartCondition.no_wait
#             if i > 0
#             else ActionStartCondition.wait_for_all,
#         )
#     return apm.action_list  # returns complete action list to orch


# def HISPEC_sub_engage(
#     experiment: Experiment,
#     experiment_version: int = 1,
#     flow_we: bool = True,
#     flow_ce: bool = True,
#     z_height: float = 1.5,
#     fill_wait: float = 10.0,
# ):
#     # raise z (engage)
#     apm = ActionPlanMaker()  # exposes function parameters via apm.pars
#     apm.add(
#         KMOTOR_server, "kmove", {"move_mode": "absolute", "value_mm": z_height}
#     )
#     # close vent valves
#     for item in ("we_vent", "ce_vent"):
#         apm.add(
#             IO_server,
#             "set_digital_out",
#             {"do_item": item, "on": False},
#             ActionStartCondition.no_wait,
#         )
#     # pull electrolyte through WE and CE chambers
#     for item, flow_flag in (
#         ("we_flow", flow_we),
#         ("we_pump", flow_we),
#         ("ce_pump", flow_ce),
#     ):
#         apm.add(
#             IO_server,
#             "set_digital_out",
#             {"do_item": item, "on": flow_flag},
#             ActionStartCondition.no_wait,
#         )
#     # wait for specified time (seconds)
#     apm.add(ORCH_server, "wait", {"waittime": fill_wait})
#     # stop high speed flow, but keep low speed flow if flow_we is True
#     for i, (item, flow_flag) in enumerate(
#         [("we_flow", flow_we), ("we_pump", False), ("ce_pump", False)]
#     ):
#         apm.add(
#             IO_server,
#             "set_digital_out",
#             {"do_item": item, "on": flow_flag},
#             ActionStartCondition.no_wait
#             if i > 0
#             else ActionStartCondition.wait_for_all,
#         )
#     return apm.action_list  # returns complete action list to orch


# def HISPEC_analysis_stability(
#     experiment: Experiment,
#     experiment_version: int = 2,
#     sequence_uuid: str = "",
#     plate_id: int = 0,
#     recent: bool = True,
#     params: dict = {},
# ):
#     apm = ActionPlanMaker()  # exposes function parameters via apm.pars
#     apm.add(
#         ANA_server,
#         "analyze_echeuvis",
#         {
#             "sequence_uuid": sequence_uuid,
#             "plate_id": plate_id,
#             "recent": recent,
#             "params": params,
#         },
#     )
#     return apm.action_list
