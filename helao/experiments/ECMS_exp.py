"""
Action library for ECMS

server_key must be a FastAPI action server defined in config
"""

__all__ = [
    "ECMS_sub_unload_cell",
    "ECMS_sub_load_solid",
    "ECMS_sub_load_liquid",
    "ECMS_sub_load_gas",
    "ECMS_sub_alloff",
    "ECMS_sub_electrolyte_fill_cell",
    "ECMS_sub_prevacuum_cell",
    "ECMS_sub_headspace_purge_and_CO2baseline",
    "ECMS_sub_CA",
    "ECMS_sub_CV",
    "ECMS_sub_headspace_flow_shutdown",
    "ECMS_sub_drain",
    "ECMS_sub_electrolyte_clean_cell"
]

###
from socket import gethostname
from typing import Optional, Union

from helao.helpers.premodels import Experiment, ActionPlanMaker
from helaocore.models.action_start_condition import ActionStartCondition as asc
from helao.drivers.robot.pal_driver import PALtools
from helaocore.models.sample import SolidSample, LiquidSample, GasSample
from helaocore.models.machine import MachineModel
from helaocore.models.process_contrib import ProcessContrib
from helao.helpers.ref_electrode import REF_TABLE
#from helao.drivers.motion.galil_motion_driver import MoveModes, TransformationModes
from helao.drivers.io.enum import TriggerType

# list valid experiment functions
EXPERIMENTS = __all__

ORCH_HOST = gethostname().lower()
PSTAT_server = MachineModel(server_name="PSTAT", machine_name=ORCH_HOST).as_dict()
#MOTOR_server = MachineModel(server_name="MOTOR", machine_name=ORCH_HOST).as_dict()
NI_server = MachineModel(server_name="NI", machine_name=ORCH_HOST).as_dict()
ORCH_server = MachineModel(server_name="ORCH", machine_name=ORCH_HOST).as_dict()
PAL_server = MachineModel(server_name="PAL", machine_name=ORCH_HOST).as_dict()
IO_server = MachineModel(server_name="IO", machine_name=ORCH_HOST).as_dict()
CALC_server = MachineModel(server_name="CALC", machine_name=ORCH_HOST).as_dict()
#CO2S_server = MachineModel(server_name="CO2SENSOR", machine_name=ORCH_HOST).as_dict()
MFC_server = MachineModel(server_name="MFC", machine_name=ORCH_HOST).as_dict()
# SOLUTIONPUMP_server = MachineModel(
#     server_name="SYRINGE0", machine_name=ORCH_HOST
# ).as_dict()
# WATERCLEANPUMP_server = MachineModel(
#     server_name="SYRINGE1", machine_name=ORCH_HOST
# ).as_dict()
toggle_triggertype = TriggerType.fallingedge



def ECMS_sub_unload_cell(experiment: Experiment, experiment_version: int = 1):
    """Unload Sample at 'cell1_we' position."""

    apm = ActionPlanMaker()
    apm.add(PAL_server, "archive_custom_unloadall", {})
    return apm.action_list


def ECMS_sub_load_solid(
    experiment: Experiment,
    experiment_version: int = 1,
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
):
    apm = ActionPlanMaker()

    apm.add(
        PAL_server,
        "archive_custom_load",
        {
            "custom": "cell1_we",
            "load_sample_in": SolidSample(
                **{
                    "sample_no": apm.pars.solid_sample_no,
                    "plate_id": apm.pars.solid_plate_id,
                    "machine_name": "legacy",
                }
            ).model_dump(),
        },
    )

    return apm.action_list


def ECMS_sub_load_liquid(
    experiment: Experiment,
    experiment_version: int = 2,
    reservoir_liquid_sample_no: int = 1,
    volume_ul_cell_liquid: int = 1000,
    water_True_False: bool = False,
    combine_True_False: bool = False,
):
    """Add liquid volume to cell position.

    (1) create liquid sample using volume_ul_cell and liquid_sample_no
    """

    apm = ActionPlanMaker()

    # (3) Create liquid sample and add to assembly
    apm.add(
        PAL_server,
        "archive_custom_add_liquid",
        {
            "custom": "cell1_we",
            "source_liquid_in": LiquidSample(
                sample_no=apm.pars.reservoir_liquid_sample_no, machine_name=ORCH_HOST
            ).model_dump(),
            "volume_ml": apm.pars.volume_ul_cell_liquid / 1000,
            "combine_liquids": apm.pars.combine_True_False,
            "dilute_liquids": apm.pars.water_True_False,
        },
    )
    return apm.action_list


def ECMS_sub_load_gas(
    experiment: Experiment,
    experiment_version: int = 2,
    reservoir_gas_sample_no: int = 1,
    volume_ul_cell_gas: int = 1000,
):
    """Add gas volume to cell position."""

    apm = ActionPlanMaker()
    apm.add(
        PAL_server,
        "archive_custom_load",  # not sure there is a server function for gas
        {
            "custom": "cell1_we",
            "load_sample_in": GasSample(
                sample_no=apm.pars.reservoir_gas_sample_no, machine_name=ORCH_HOST
            ).model_dump(),
            "volume_ml": apm.pars.volume_ul_cell_gas / 1000,
        },
    )
    return apm.action_list


#TODO add MFC off
def ECMS_sub_alloff(
    experiment: Experiment,
    experiment_version: int = 1,
):
    """

    Args:
        experiment (Experiment): Experiment object provided by Orch
    """

    apm = ActionPlanMaker()
    apm.add(
        NI_server,
        "pump",
        {
            "pump": "RecirculatingPeriPump1",
            "on": 0,
        },
    )
    apm.add(
        NI_server,
        "pump",
        {
            "pump": "RecirculatingPeriPump2",
            "on": 0,
        },
    )
    apm.add(
        MFC_server,
        "set_flowrate",
        {
            "flowrate_sccm": 0.0,
            "ramp_sccm_sec": 0.0,
            "device_name": "CO2",
        },
        asc.no_wait,
    )
    apm.add(
        MFC_server,
        "hold_valve_closed_action",
        {
            "device_name": "CO2"
        },
        asc.no_wait,
    )
# =============================================================================
#     apm.add(
#         MFC_server,
#         "cancel_acquire_flowrate",
#         {}
#     )
# =============================================================================
    apm.add(NI_server, "gasvalve", {"gasvalve": "2B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "2A", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "3A", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "3B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4A", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 0}, asc.no_wait)
    return apm.action_list



def ECMS_sub_electrolyte_fill_cell(
    experiment: Experiment,
    experiment_version: int = 1,
    liquid_forward_time: float = 20,
    liquid_backward_time: float = 10,
    reservoir_liquid_sample_no: int = 1,
    volume_ul_cell_liquid: int = 1
):
    """Add electrolyte volume to cell position.

    (1) create liquid sample using volume_ul_cell and liquid_sample_no
    """

    apm = ActionPlanMaker()

    # Fill cell with liquid
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 1})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-dir", "on": 0})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.liquid_forward_time})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-dir", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.liquid_backward_time})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 0})
    apm.add(
        PAL_server,
        "archive_custom_add_liquid",
        {
            "custom": "cell1_we",
            "source_liquid_in": LiquidSample(
                sample_no=apm.pars.reservoir_liquid_sample_no, machine_name=ORCH_HOST
            ).model_dump(),
            "volume_ml": apm.pars.volume_ul_cell_liquid,
            "combine_liquids": True,
            "dilute_liquids": True,
        },
    )
    return apm.action_list

def ECMS_sub_prevacuum_cell(
    experiment: Experiment,
    experiment_version: int = 1,
    vacuum_time: float = 10,
):
    """prevacuum the cell gas phase side to make the electrolyte contact with GDE
    """

    apm = ActionPlanMaker()

    # Fill cell with liquid
    apm.add(NI_server, "gasvalve", {"gasvalve": "2A", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "3B", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.vacuum_time})
    apm.add(NI_server, "gasvalve", {"gasvalve": "2A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "3B", "on": 0})
    return apm.action_list
    
    return apm.action_list

def ECMS_sub_headspace_purge_and_CO2baseline(
    experiment: Experiment,
    experiment_version: int = 1,
    CO2equilibrium_duration: float = 30,
    flowrate_sccm: float = 5.0,
    flow_ramp_sccm: float = 0,
    MS_baseline_duration: float = 300,
    #flow_duration: float = -1,
    #co2measure_acqrate: float = 0.5
):
    """prevacuum the cell gas phase side to make the electrolyte contact with GDE
    """

    apm = ActionPlanMaker()

    # Fill cell with liquid
    apm.add(NI_server, "gasvalve", {"gasvalve": "1", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "2A", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "3A", "on": 1})
    apm.add(
        MFC_server,
        "set_flowrate",
        {
            "flowrate_sccm": apm.pars.flowrate_sccm,
            "ramp_sccm_sec": apm.pars.flow_ramp_sccm,
            "device_name": "CO2",
        },
        asc.no_wait,
    )
    apm.add(
        MFC_server,
        "cancel_hold_valve_action",
        {
            "device_name": "CO2"
        },
        asc.no_wait,
    )
# =============================================================================
#     apm.add(
#         MFC_server,
#         "acquire_flowrate",
#         {
#             "flowrate_sccm": apm.pars.flowrate_sccm,
#             "ramp_sccm_sec": apm.pars.flow_ramp_sccm,
#             "acquisition_rate": apm.pars.co2measure_acqrate,
#             "duration": apm.pars.flow_duration,
#             "stay_open": True
#         },
#         asc.no_wait,
#     )
# =============================================================================
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.CO2equilibrium_duration})
    apm.add(NI_server, "gasvalve", {"gasvalve": "2B", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.MS_baseline_duration})
    return apm.action_list

def ECMS_sub_CA(
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

def ECMS_sub_CV(
    experiment: Experiment,
    experiment_version: int = 1,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    WE_potential_init__V: float = 0.0,
    WE_potential_apex1__V: float = -1.0,
    WE_potential_apex2__V: float = -0.5,
    WE_potential_final__V: float = -0.5,
    ScanRate_V_s: float = 0.01,
    Cycles: int = 1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    if apm.pars.WE_versus == "ref":
        potential_init_vsRef = (
            apm.pars.WE_potential_init__V - 1.0 * apm.pars.ref_offset__V
        )
        potential_apex1_vsRef = (
            apm.pars.WE_potential_apex1__V - 1.0 * apm.pars.ref_offset__V
        )
        potential_apex2_vsRef = (
            apm.pars.WE_potential_apex2__V - 1.0 * apm.pars.ref_offset__V
        )
        potential_final_vsRef = (
            apm.pars.WE_potential_final__V - 1.0 * apm.pars.ref_offset__V
        )
    elif apm.pars.WE_versus == "rhe":
        potential_init_vsRef = (
            apm.pars.WE_potential_init__V
            - 1.0 * apm.pars.ref_offset__V
            - 0.059 * apm.pars.pH
            - REF_TABLE[ref_type]
        )
        potential_apex1_vsRef = (
            apm.pars.WE_potential_apex1__V
            - 1.0 * apm.pars.ref_offset__V
            - 0.059 * apm.pars.pH
            - REF_TABLE[ref_type]
        )
        potential_apex2_vsRef = (
            apm.pars.WE_potential_apex2__V
            - 1.0 * apm.pars.ref_offset__V
            - 0.059 * apm.pars.pH
            - REF_TABLE[ref_type]
        )
        potential_final_vsRef = (
            apm.pars.WE_potential_final__V
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
        "run_CV",
        {
            "Vinit__V": potential_init_vsRef,
            "Vapex1__V": potential_apex1_vsRef,
            "Vapex2__V": potential_apex2_vsRef,
            "Vfinal__V": potential_final_vsRef,
            "ScanRate__V_s": apm.pars.ScanRate_V_s,
            "Cycles": apm.pars.Cycles,
            "AcqInterval__s": apm.pars.SampleRate,
            "IErange": apm.pars.IErange,
        },
        from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
        process_finish=True,
        technique_name=["CV"],
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )

    # apm.add(ORCH_server, "wait", {"waittime": 10})

    return apm.action_list

def ECMS_sub_headspace_flow_shutdown(
    experiment: Experiment,
    experiment_version: int = 1,
    #flow_duration: float = -1,
    #co2measure_acqrate: float = 0.5
):
    """prevacuum the cell gas phase side to make the electrolyte contact with GDE
    """

    apm = ActionPlanMaker()

    # Fill cell with liquid

    apm.add(
        MFC_server,
        "set_flowrate",
        {
            "flowrate_sccm": 0.0,
            "ramp_sccm_sec": 0.0,
            "device_name": "CO2",
        },
        asc.no_wait,
    )
    apm.add(
        MFC_server,
        "hold_valve_closed_action",
        {
            "device_name": "CO2"
        },
        asc.no_wait,
    )
    apm.add(NI_server, "gasvalve", {"gasvalve": "1", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "2A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "3A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "2B", "on": 0})
    #apm.add(ORCH_server, "wait", {"waittime": apm.pars.baseline_duration})
    return apm.action_list

def ECMS_sub_drain(
    experiment: Experiment,
    experiment_version: int = 1,
    liquid_drain_time: float = 30,
):
    apm = ActionPlanMaker()

    # Fill cell with liquid
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4A", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A", "on": 1})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1-dir", "on": 1})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.liquid_drain_time})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4A", "on": 0})
    return apm.action_list

def ECMS_sub_electrolyte_clean_cell(
    experiment: Experiment,
    experiment_version: int = 1,
    liquid_backward_time: float = 30,
    reservoir_liquid_sample_no: int = 2,
):
    """Add electrolyte volume to cell position.

    (1) create liquid sample using volume_ul_cell and liquid_sample_no
    """

    apm = ActionPlanMaker()
    
    # Fill cell with liquid
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4A", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 1})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 1})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-dir", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.liquid_backward_time})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 0})
    #apm.add_action_list(ECMS_sub_drain(experiment))

    return apm.action_list