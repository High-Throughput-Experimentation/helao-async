"""
Action library for AutoGDE

server_key must be a FastAPI action server defined in config
"""

__all__ = [
    "ECMS_sub_unload_cell",
    "ECMS_sub_load_solid",
    "ECMS_sub_load_liquid",
    "ECMS_sub_load_gas",
    "ECMS_sub_normal_state",
    "ECMS_sub_alloff",
    "ECMS_sub_electrolyte_fill_recirculationreservoir",
    "ECMS_sub_electrolyte_fill_cell",
    "ECMS_sub_electrolyte_fill_cell_recirculation",
    "ECMS_sub_prevacuum_cell",
    "ECMS_sub_headspace_purge_and_CO2baseline",
    "ECMS_sub_electrolyte_recirculation_on",
    "ECMS_sub_electrolyte_recirculation_off",
    "ECMS_sub_CA",
    "ECMS_sub_pulseCA",
    "ECMS_sub_CV",
    "ECMS_sub_drain_recirculation",
    "ECMS_sub_clean_cell_recirculation",
    "ECMS_sub_drain",
    "ECMS_sub_final_clean_cell",
    "ECMS_sub_cali", 
    "ECMS_sub_pulsecali",
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
CALIBRATIONMFC_server = MachineModel(server_name="CALIBRATIONMFC", machine_name=ORCH_HOST).as_dict()

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
                    "sample_no": solid_sample_no,
                    "plate_id": solid_plate_id,
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
                sample_no=reservoir_liquid_sample_no, machine_name=ORCH_HOST
            ).model_dump(),
            "volume_ml": volume_ul_cell_liquid / 1000,
            "combine_liquids": combine_True_False,
            "dilute_liquids": water_True_False,
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
                sample_no=reservoir_gas_sample_no, machine_name=ORCH_HOST
            ).model_dump(),
            "volume_ml": volume_ul_cell_gas / 1000,
        },
    )
    return apm.action_list


def ECMS_sub_normal_state(
    experiment: Experiment,
    experiment_version: int = 1,
):
    """Set ECMS to 'normal' state.

    All experiments begin and end in the following 'normal' state:
    - separate (old) MFC for CO2 is ON to bypass GDE cell but go to MS.

    Args:
        experiment (Experiment): Experiment object provided by Orch
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
    
    apm.add(
        CALIBRATIONMFC_server,
        "set_flowrate",
        {
            "flowrate_sccm": 0.0,
            "ramp_sccm_sec": 0.0,
            "device_name": "Caligas",
        },
        asc.no_wait,
    )
    apm.add(
        CALIBRATIONMFC_server,
        "hold_valve_closed_action",
        {
            "device_name": "Caligas"
        },
        asc.no_wait,
    )
    
    apm.add(NI_server, "gasvalve", {"gasvalve": "1", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "2A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "3A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "2B", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "6A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "6B", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0})
    #apm.add(ORCH_server, "wait", {"waittime": baseline_duration})
    return apm.action_list

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
    apm.add(
        CALIBRATIONMFC_server,
        "set_flowrate",
        {
            "flowrate_sccm": 0.0,
            "ramp_sccm_sec": 0.0,
            "device_name": "Caligas",
        },
        asc.no_wait,
    )
    apm.add(
        CALIBRATIONMFC_server,
        "hold_valve_closed_action",
        {
            "device_name": "Caligas"
        },
        asc.no_wait,
    )
    apm.add(NI_server, "gasvalve", {"gasvalve": "2B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "2A", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "3A", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "3B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "6A", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "6B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4A", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1-dir", "on": 0})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-dir", "on": 0})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-maxspd", "on": 0})

    return apm.action_list

def ECMS_sub_electrolyte_fill_recirculationreservoir(
    experiment: Experiment,
    experiment_version: int = 1,
    liquid_fill_time: float = 30,
):
    apm = ActionPlanMaker()

    # Fill cell with liquid
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1-dir", "on": 1})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": liquid_fill_time})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})

    return apm.action_list

def ECMS_sub_electrolyte_fill_cell(
    experiment: Experiment,
    experiment_version: int = 1,
    #liquid_forward_time: float = 20,
    liquid_backward_time: float = 10,
    reservoir_liquid_sample_no: int = 1,
    volume_ul_cell_liquid: int = 1
):
    """Add electrolyte volume to cell position.

    (1) create liquid sample using volume_ul_cell and liquid_sample_no
    """

    apm = ActionPlanMaker()

    # Fill cell with liquid
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4A", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 1})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-dir", "on": 1})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": liquid_backward_time})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4A", "on": 0})
    apm.add(
        PAL_server,
        "archive_custom_add_liquid",
        {
            "custom": "cell1_we",
            "source_liquid_in": LiquidSample(
                sample_no=reservoir_liquid_sample_no, machine_name=ORCH_HOST
            ).model_dump(),
            "volume_ml": volume_ul_cell_liquid,
            "combine_liquids": True,
            "dilute_liquids": True,
        },
    )
    return apm.action_list
# =============================================================================
# def ECMS_sub_electrolyte_fill_cell(
#     experiment: Experiment,
#     experiment_version: int = 1,
#     liquid_forward_time: float = 20,
#     liquid_backward_time: float = 10,
#     reservoir_liquid_sample_no: int = 1,
#     volume_ul_cell_liquid: int = 1
# ):
#     """Add electrolyte volume to cell position.
# 
#     (1) create liquid sample using volume_ul_cell and liquid_sample_no
#     """
# 
#     apm = ActionPlanMaker()
# 
#     # Fill cell with liquid
#     apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 1})
#     apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 1})
#     apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-dir", "on": 0})
#     apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 1})
#     apm.add(ORCH_server, "wait", {"waittime": liquid_forward_time})
#     apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-dir", "on": 1})
#     apm.add(ORCH_server, "wait", {"waittime": liquid_backward_time})
#     apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 0})
#     apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 0})
#     apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 0})
#     apm.add(
#         PAL_server,
#         "archive_custom_add_liquid",
#         {
#             "custom": "cell1_we",
#             "source_liquid_in": LiquidSample(
#                 sample_no=reservoir_liquid_sample_no, machine_name=ORCH_HOST
#             ).model_dump(),
#             "volume_ml": volume_ul_cell_liquid,
#             "combine_liquids": True,
#             "dilute_liquids": True,
#         },
#     )
#     return apm.action_list
# =============================================================================
def ECMS_sub_electrolyte_fill_cell_recirculation(
    experiment: Experiment,
    experiment_version: int = 1,
    liquid_backward_time: float = 80,
    reservoir_liquid_sample_no: int = 2,
    volume_ul_cell_liquid: float =1.0,
    
):
    """Add electrolyte volume to cell position.

    (1) create liquid sample using volume_ul_cell and liquid_sample_no
    """

    apm = ActionPlanMaker()

    # Fill cell with liquid
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 1})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-dir", "on": 1})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": liquid_backward_time})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 0})
    apm.add(
        PAL_server,
        "archive_custom_add_liquid",
        {
            "custom": "cell1_we",
            "source_liquid_in": LiquidSample(
                sample_no=reservoir_liquid_sample_no, machine_name=ORCH_HOST
            ).model_dump(),
            "volume_ml": volume_ul_cell_liquid,
            "combine_liquids": True,
            "dilute_liquids": True,
        },
    )
    return apm.action_list
# =============================================================================
# def ECMS_sub_electrolyte_fill_cell_recirculation(
#     experiment: Experiment,
#     experiment_version: int = 1,
#     #liquid_forward_time: float = 20,
#     liquid_backward_time: float = 10,
#     reservoir_liquid_sample_no: int = 1,
#     volume_ul_cell_liquid: int = 1
# ):
#     """Add electrolyte volume to cell position.
# 
#     (1) create liquid sample using volume_ul_cell and liquid_sample_no
#     """
# 
#     apm = ActionPlanMaker()
# 
#     # Fill cell with liquid
#     apm.add(NI_server, "liquidvalve", {"liquidvalve": "4A", "on": 1})
#     apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 1})
#     apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-dir", "on": 1})
#     apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 1})
#     apm.add(ORCH_server, "wait", {"waittime": liquid_backward_time})
#     apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 0})
#     apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 1})
#     apm.add(NI_server, "liquidvalve", {"liquidvalve": "4A", "on": 0})
#     apm.add(
#         PAL_server,
#         "archive_custom_add_liquid",
#         {
#             "custom": "cell1_we",
#             "source_liquid_in": LiquidSample(
#                 sample_no=reservoir_liquid_sample_no, machine_name=ORCH_HOST
#             ).model_dump(),
#             "volume_ml": volume_ul_cell_liquid,
#             "combine_liquids": True,
#             "dilute_liquids": True,
#         },
#     )
#     return apm.action_list
# =============================================================================

def ECMS_sub_prevacuum_cell(
    experiment: Experiment,
    experiment_version: int = 2,
    vacuum_time: float = 10,
):
    """prevacuum the cell gas phase side to make the electrolyte contact with GDE
    """

    apm = ActionPlanMaker()

    # Fill cell with liquid
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "2A", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "3B", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": vacuum_time})
    apm.add(NI_server, "gasvalve", {"gasvalve": "2A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "3B", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 0})

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
            "flowrate_sccm": flowrate_sccm,
            "ramp_sccm_sec": flow_ramp_sccm,
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
#             "flowrate_sccm": flowrate_sccm,
#             "ramp_sccm_sec": flow_ramp_sccm,
#             "acquisition_rate": co2measure_acqrate,
#             "duration": flow_duration,
#             "stay_open": True
#         },
#         asc.no_wait,
#     )
# =============================================================================
    apm.add(ORCH_server, "wait", {"waittime": CO2equilibrium_duration})
    apm.add(NI_server, "gasvalve", {"gasvalve": "2B", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "6B", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "6A", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": MS_baseline_duration})
    return apm.action_list

def ECMS_sub_electrolyte_recirculation_on(
    experiment: Experiment,
    experiment_version: int = 1,
):
    """Add electrolyte volume to cell position.

    (1) create liquid sample using volume_ul_cell and liquid_sample_no
    """

    apm = ActionPlanMaker()

    # Fill cell with liquid
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 1})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-dir", "on": 1})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 1})
    return apm.action_list

def ECMS_sub_electrolyte_recirculation_off(
    experiment: Experiment,
    experiment_version: int = 1,
):
    """Add electrolyte volume to cell position.

    (1) create liquid sample using volume_ul_cell and liquid_sample_no
    """

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 0})

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
    MS_equilibrium_time: float = 90.0,
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    if WE_versus == "ref":
        potential_vsRef = WE_potential__V - 1.0 * ref_offset__V
    elif WE_versus == "rhe":
        potential_vsRef = (
            WE_potential__V
            - 1.0 * ref_offset__V
            - 0.059 * pH
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
            "Tval__s": CA_duration_sec,
            "AcqInterval__s": SampleRate,
            "IErange": IErange,
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
    apm.add(ORCH_server, "wait", {"waittime": MS_equilibrium_time})
    # apm.add(ORCH_server, "wait", {"waittime": 10})

    return apm.action_list


def ECMS_sub_pulseCA(
    experiment: Experiment,
    experiment_version: int = 2,   
    Vinit__V: float = 0.0,
    Tinit__s: float = 0.5,
    Vstep__V: float = 0.5,
    Tstep__s: float = 0.5,
    Cycles: int = 5,
    AcqInterval__s: float = 0.01,  # acquisition rate
    run_OCV: bool = False,
    Tocv__s: float = 60.0,
    IErange: str = "auto",
    WE_versus: str = "ref",
    ref_offset__V: float = 0.0,
    ref_type: str = "leakless",
    pH: float = 6.8,
    MS_equilibrium_time: float = 90.0,
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
# =============================================================================
#     if WE_versus == "ref":
#         potential_vsRef = WE_potential__V - 1.0 * ref_offset__V
#     elif WE_versus == "rhe":
#         potential_vsRef = (
#             WE_potential__V
#             - 1.0 * ref_offset__V
#             - 0.059 * pH
#             - REF_TABLE[ref_type]
#         )
# =============================================================================
    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {"custom": "cell1_we"},
        to_globalexp_params=["_fast_samples_in"],
    )
    if run_OCV:
        # OCV
        apm.add(
            PSTAT_server,
            "run_OCV",
            {
                "Tval__s": Tocv__s,
                "SampleRate": 0.05,
                "IErange": IErange,
            },
            to_globalexp_params=["Ewe_V__mean_final"],
            from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
            technique_name="OCV",
            process_finish=True,
            process_contrib=[
                ProcessContrib.action_params,
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        )
        apm.add(
            PSTAT_server,
            "run_RCA",
            {
                #"Vinit__V": Vinit__V,
                "Tinit__s": Tinit__s,
                "Vstep__V": Vstep__V,
                "Tstep__s": Tstep__s,
                "Cycles": Cycles,
                "AcqInterval__s": AcqInterval__s,
            },
            from_globalexp_params= {"_fast_samples_in":"fast_samples_in","Ewe_V__mean_final":"Vinit__V"},
            process_finish=True,
            technique_name="CA",
            process_contrib=[
                ProcessContrib.action_params,
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        )
    else:
        apm.add(
            PSTAT_server,
            "run_RCA",
            {
                "Vinit__V": Vinit__V,
                "Tinit__s": Tinit__s,
                "Vstep__V": Vstep__V,
                "Tstep__s": Tstep__s,
                "Cycles": Cycles,
                "AcqInterval__s": AcqInterval__s,
            },
            from_globalexp_params= {"_fast_samples_in":"fast_samples_in"},
            process_finish=True,
            technique_name="CA",
            process_contrib=[
                ProcessContrib.action_params,
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        )
    apm.add(ORCH_server, "wait", {"waittime": MS_equilibrium_time})
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
    MS_equilibrium_time: float = 90.0,
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    if WE_versus == "ref":
        potential_init_vsRef = (
            WE_potential_init__V - 1.0 * ref_offset__V
        )
        potential_apex1_vsRef = (
            WE_potential_apex1__V - 1.0 * ref_offset__V
        )
        potential_apex2_vsRef = (
            WE_potential_apex2__V - 1.0 * ref_offset__V
        )
        potential_final_vsRef = (
            WE_potential_final__V - 1.0 * ref_offset__V
        )
    elif WE_versus == "rhe":
        potential_init_vsRef = (
            WE_potential_init__V
            - 1.0 * ref_offset__V
            - 0.059 * pH
            - REF_TABLE[ref_type]
        )
        potential_apex1_vsRef = (
            WE_potential_apex1__V
            - 1.0 * ref_offset__V
            - 0.059 * pH
            - REF_TABLE[ref_type]
        )
        potential_apex2_vsRef = (
            WE_potential_apex2__V
            - 1.0 * ref_offset__V
            - 0.059 * pH
            - REF_TABLE[ref_type]
        )
        potential_final_vsRef = (
            WE_potential_final__V
            - 1.0 * ref_offset__V
            - 0.059 * pH
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
            "ScanRate__V_s": ScanRate_V_s,
            "Cycles": Cycles,
            "AcqInterval__s": SampleRate,
            "IErange": IErange,
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
    apm.add(ORCH_server, "wait", {"waittime": MS_equilibrium_time})
    # apm.add(ORCH_server, "wait", {"waittime": 10})

    return apm.action_list

def ECMS_sub_drain_recirculation(
    experiment: Experiment,
    experiment_version: int = 1,
    tube_clear_time: float = 20,
    liquid_drain_time: float = 80,
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
    #apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-maxspd", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": tube_clear_time})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4A", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 0})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-dir", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": liquid_drain_time})
    #apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-maxspd", "on": 0})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 0})
    return apm.action_list
# =============================================================================
# def ECMS_sub_drain_recirculation(
#     experiment: Experiment,
#     experiment_version: int = 1,
#     liquid_drain_time: float = 60,
# ):
#     """Add electrolyte volume to cell position.
# 
#     (1) create liquid sample using volume_ul_cell and liquid_sample_no
#     """
# 
#     apm = ActionPlanMaker()
# 
#     # Fill cell with liquid
#     apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 1})
#     apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 1})
#     apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-dir", "on": 0})
#     apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 1})
#     apm.add(ORCH_server, "wait", {"waittime": liquid_drain_time})
#     apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 0})
#     apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 0})
#     apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 0})
#     return apm.action_list
# =============================================================================
def ECMS_sub_clean_cell_recirculation(
    experiment: Experiment,
    experiment_version: int = 1,
    cleaning_times: int = 2,
    
    liquid_fill_time: float = 30,
    
    volume_ul_cell_liquid: int = 1,
    liquid_backward_time: float = 80,
    reservoir_liquid_sample_no: int = 2,
    tube_clear_delaytime: float = 40.0,
    tube_clear_time: float = 20,
    liquid_drain_time: float = 80,
):
    """Add electrolyte volume to cell position.

    (1) create liquid sample using volume_ul_cell and liquid_sample_no
    """

    apm = ActionPlanMaker()


    for cycle in range(cleaning_times):
        apm.add_action_list(
            ECMS_sub_electrolyte_fill_recirculationreservoir(
                experiment=experiment,
                liquid_fill_time=liquid_fill_time
            )
        )
        apm.add_action_list(
            ECMS_sub_electrolyte_fill_cell_recirculation(
                experiment=experiment,
                volume_ul_cell_liquid=volume_ul_cell_liquid,
                liquid_backward_time=liquid_backward_time,
                reservoir_liquid_sample_no=reservoir_liquid_sample_no
            )
        )
# =============================================================================
#         apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 1})
#         apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 1})
#         apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-dir", "on": 0})
#         apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 1})
#         #apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-maxspd", "on": 1})
#         apm.add(ORCH_server, "wait", {"waittime": tube_clear_time+tube_clear_delaytime})
#         apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A", "on": 1})
#         apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 0})
#         apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-dir", "on": 1})
#         apm.add(ORCH_server, "wait", {"waittime": liquid_drain_time-tube_clear_delaytime})
#         #apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-maxspd", "on": 0})
#         apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 0})
#         apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A", "on": 0})
#         apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 0})
# =============================================================================
        apm.add_action_list(
            ECMS_sub_drain_recirculation(
                experiment=experiment,
                tube_clear_time=tube_clear_time,
                liquid_drain_time=liquid_drain_time
            )
        )
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
    apm.add(ORCH_server, "wait", {"waittime": liquid_drain_time})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4A", "on": 0})
    return apm.action_list

def ECMS_sub_final_clean_cell(
    experiment: Experiment,
    experiment_version: int = 1,
    liquid_backward_time_1: float = 300,
    liquid_backward_time_2: float = 300,
    reservoir_liquid_sample_no: int = 1,
    volume_ul_cell_liquid: int = 1
):
    """Add electrolyte volume to cell position.

    (1) create liquid sample using volume_ul_cell and liquid_sample_no
    """

    apm = ActionPlanMaker()

    # Fill cell with liquid
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4A", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 1})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-dir", "on": 1})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": liquid_backward_time_1})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 1})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": liquid_backward_time_2})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 0})

    apm.add(
        PAL_server,
        "archive_custom_add_liquid",
        {
            "custom": "cell1_we",
            "source_liquid_in": LiquidSample(
                sample_no=reservoir_liquid_sample_no, machine_name=ORCH_HOST
            ).model_dump(),
            "volume_ml": volume_ul_cell_liquid,
            "combine_liquids": True,
            "dilute_liquids": True,
        },
    )
    return apm.action_list

def ECMS_sub_cali(
    experiment: Experiment,
    experiment_version: int = 1,
    CO2flowrate_sccm: float = 20.0,
    Califlowrate_sccm: float = 0.0,
    flow_ramp_sccm: float = 0,
    MSsignal_quilibrium_time: float = 300,
):
    """prevacuum the cell gas phase side to make the electrolyte contact with GDE
    """

    apm = ActionPlanMaker()

    # set CO2 flow rate
    apm.add(
        MFC_server,
        "set_flowrate",
        {
            "flowrate_sccm": CO2flowrate_sccm,
            "ramp_sccm_sec": flow_ramp_sccm,
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
    # set Calibration gas flow rate
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 1})
    apm.add(
        CALIBRATIONMFC_server,
        "set_flowrate",
        {
            "flowrate_sccm": Califlowrate_sccm,
            "ramp_sccm_sec": flow_ramp_sccm,
            "device_name": "Caligas",
        },
        asc.no_wait,
    )
    apm.add(
        CALIBRATIONMFC_server,
        "cancel_hold_valve_action",
        {
            "device_name": "Caligas"
        },
        asc.no_wait,
    )
    apm.add(ORCH_server, "wait", {"waittime": MSsignal_quilibrium_time})

    return apm.action_list


def ECMS_sub_pulsecali(
    experiment: Experiment,
    experiment_version: int = 1,
    #CO2flowrate_sccm: float = 20.0,
    Califlowrate_sccm: float = 0.0,
    flow_ramp_sccm: float = 0,
    MSsignal_quilibrium_time: float = 300,
):
    """prevacuum the cell gas phase side to make the electrolyte contact with GDE
    """

    apm = ActionPlanMaker()
    apm.add(
        CALIBRATIONMFC_server,
        "set_flowrate",
        {
            "flowrate_sccm": Califlowrate_sccm,
            "ramp_sccm_sec": flow_ramp_sccm,
            "device_name": "Caligas",
        },
        asc.no_wait,
    )
    apm.add(
        CALIBRATIONMFC_server,
        "cancel_hold_valve_action",
        {
            "device_name": "Caligas"
        },
        asc.no_wait,
    )
    apm.add(ORCH_server, "wait", {"waittime": MSsignal_quilibrium_time})

    return apm.action_list