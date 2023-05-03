"""
Action library for ANEC

server_key must be a FastAPI action server defined in config
"""

__all__ = [
    "ANEC_sub_startup",
    "ANEC_sub_disengage",
    "ANEC_sub_drain_cell",
    "ANEC_sub_flush_fill_cell",
    "ANEC_sub_load_solid_only",
    "ANEC_sub_load_solid",
    "ANEC_sub_load_solid_and_clean_cell",
    "ANEC_sub_unload_cell",
    "ANEC_sub_unload_liquid",
    "ANEC_sub_normal_state",
    "ANEC_sub_GC_preparation",
    "ANEC_sub_cleanup",
    "ANEC_sub_CP",
    "ANEC_sub_CA",
    "ANEC_sub_OCV",
    "ANEC_sub_liquidarchive",
    "ANEC_sub_aliquot",
    "ANEC_sub_alloff",
    "ANEC_sub_CV",
    "ANEC_sub_photo_CV",
    "ANEC_sub_photo_CA",
    "ANEC_sub_GCLiquid_analysis",
    "ANEC_sub_HPLCLiquid_analysis",
    "ANEC_sub_photo_LSV",
    "ANEC_sub_photo_CP",
]

###
from socket import gethostname
from typing import Optional

from helao.helpers.premodels import Experiment, ActionPlanMaker
from helao.drivers.robot.pal_driver import PALtools
from helaocore.models.sample import SolidSample, LiquidSample
from helaocore.models.machine import MachineModel
from helaocore.models.action_start_condition import ActionStartCondition
from helaocore.models.process_contrib import ProcessContrib
from helao.helpers.ref_electrode import REF_TABLE
from helao.drivers.motion.galil_motion_driver import MoveModes, TransformationModes
from helao.drivers.io.enum import TriggerType

# list valid experiment functions
EXPERIMENTS = __all__

ORCH_HOST = gethostname().lower()
PSTAT_server = MachineModel(server_name="PSTAT", machine_name=ORCH_HOST).as_dict()
MOTOR_server = MachineModel(server_name="MOTOR", machine_name=ORCH_HOST).as_dict()
NI_server = MachineModel(server_name="NI", machine_name=ORCH_HOST).as_dict()
ORCH_server = MachineModel(server_name="ORCH", machine_name=ORCH_HOST).as_dict()
PAL_server = MachineModel(server_name="PAL", machine_name=ORCH_HOST).as_dict()
IO_server = MachineModel(server_name="IO", machine_name=ORCH_HOST).as_dict()

toggle_triggertype = TriggerType.fallingedge


# z positions for ADSS cell
z_home = 0.0
# touches the bottom of cell
z_engage = 2.5
# moves it up to put pressure on seal
z_seal = 4.5



def ANEC_sub_CP(
    experiment: Experiment,
    experiment_version: int = 1,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CP_current: float = 0.0,
    SampleRate: float = 0.01,
    CP_duration_sec: float = 60,
    IErange: str = "auto",
):
    """last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    if int(round(apm.pars.toggle_illum_time)) == -1:
        apm.pars.toggle_illum_time = apm.pars.CP_duration_sec

    # get sample for gamry
    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {"custom": "cell1_we"},
        to_globalexp_params=["_fast_samples_in"],
    )

    apm.add(
        PSTAT_server,
        "run_CP",
        {
            "Ival": apm.pars.CP_current,
            "Tval__s": apm.pars.CP_duration_sec,
            "AcqInterval__s": apm.pars.SampleRate,
            "IErange": apm.pars.IErange,
        },
        from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
        technique_name="CP",
        process_finish=True,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )


    return apm.action_list  # returns complete action list to orch


def ANEC_sub_CA(
    experiment: Experiment,
    experiment_version: int = 1,
    WE_potential__V: float = 0.0,
    WE_versus: str = "ref",
    CA_duration_sec: float = 0.1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    ref_type: str = "leakless",
    pH: float = 6.8,
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    if apm.pars.WE_versus == "ref":
        potential_vsRef = apm.pars.WE_potential__V - 1.0 * apm.pars.ref_offset__V
    elif apm.pars.WE_versus == "rhe":
        potential_vsRef = (
            apm.pars.WE_potential__V
            - 1.0 * apm.pars.ref_offset__V
            - 0.059 * apm.pars.pH
            - REF_TABLE[ref_type]
        )
    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {"custom": "cell1_we"},
        to_globalexp_params=["_fast_samples_in"],
    )
    apm.add(
        PSTAT_server,
        "run_CA",
        {
            "Vval__V": potential_vsRef,
            "Tval__s": apm.pars.CA_duration_sec,
            "AcqInterval__s": apm.pars.SampleRate,
            "IErange": apm.pars.IErange,
        },
        from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
        process_finish=True,
        technique_name="CA",
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )

    # apm.add(ORCH_server, "wait", {"waittime": 10})

    return apm.action_list


def ANEC_sub_OCV(
    experiment: Experiment,
    experiment_version: int = 1,
    Tval__s: float = 900.0,
    IErange: str = "auto",
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

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

    # OCV
    apm.add(
        PSTAT_server,
        "run_OCV",
        {
            "Tval__s": apm.pars.Tval__s,
            "SampleRate": 0.05,
            "IErange": apm.pars.IErange,
        },
        from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
        technique_name="CP",
        process_finish=True,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    return apm.action_list  # returns complete action list to orch

