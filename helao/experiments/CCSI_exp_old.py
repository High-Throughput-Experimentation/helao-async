"""
Action library for CCSI

server_key must be a FastAPI action server defined in config
"""

__all__ = [
    "CCSI_sub_unload_cell",
    "CCSI_sub_load_solid",
    "CCSI_sub_load_liquid",
    "CCSI_sub_load_gas",
    "CCSI_sub_alloff",
    "CCSI_sub_headspace_purge_and_measure",
    "CCSI_sub_drain",
    "CCSI_sub_initialization_end_state",
    "CCSI_sub_peripumpoff",
    "CCSI_sub_initialization_firstpart",
    "CCSI_sub_cellfill",
    "CCSI_sub_co2constantpressure",
    "CCSI_sub_co2mass_temp",
    "CCSI_sub_co2massdose",
    "CCSI_sub_co2maintainconcentration",
    "CCSI_sub_co2topup_mfcmassdose",
    "CCSI_sub_co2monitoring",
    "CCSI_sub_co2monitoring_mfcmasscotwo",
    "CCSI_sub_clean_inject",
    "CCSI_sub_refill_clean",
    "CCSI_debug_co2purge",
    "CCSI_sub_fill_syringe",
    "CCSI_sub_full_fill_syringe",
    "CCSI_leaktest_co2",
    "CCSI_sub_flowflush",
]

###
from socket import gethostname
from typing import Optional, Union

from helao.helpers.premodels import Experiment, ActionPlanMaker
from helao.core.models.action_start_condition import ActionStartCondition as asc
from helao.drivers.robot.pal_driver import PALtools
from helao.core.models.sample import SolidSample, LiquidSample, GasSample
from helao.core.models.machine import MachineModel
from helao.core.models.process_contrib import ProcessContrib
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
CALC_server = MachineModel(server_name="CALC", machine_name=ORCH_HOST).as_dict()
CO2S_server = MachineModel(server_name="CO2SENSOR", machine_name=ORCH_HOST).as_dict()
MFC_server = MachineModel(server_name="MFC", machine_name=ORCH_HOST).as_dict()
SOLUTIONPUMP_server = MachineModel(
    server_name="SYRINGE0", machine_name=ORCH_HOST
).as_dict()
WATERCLEANPUMP_server = MachineModel(
    server_name="SYRINGE1", machine_name=ORCH_HOST
).as_dict()
toggle_triggertype = TriggerType.fallingedge



def CCSI_sub_unload_cell(experiment: Experiment, experiment_version: int = 1):
    """Unload Sample at 'cell1_we' position."""

    apm = ActionPlanMaker()
    apm.add(PAL_server, "archive_custom_unloadall", {})
    return apm.planned_actions


def CCSI_sub_load_solid(
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
            ).dict(),
        },
    )

    return apm.planned_actions


def CCSI_sub_load_liquid(
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
            ).dict(),
            "volume_ml": volume_ul_cell_liquid / 1000,
            "combine_liquids": combine_True_False,
            "dilute_liquids": water_True_False,
        },
    )
    return apm.planned_actions


def CCSI_sub_load_gas(
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
            ).dict(),
            "volume_ml": volume_ul_cell_gas / 1000,
        },
    )
    return apm.planned_actions


def CCSI_sub_alloff(
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
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "8", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "9", "on": 0}, asc.no_wait)

    return apm.planned_actions


def CCSI_sub_headspace_purge_and_measure(
    experiment: Experiment,
    experiment_version: int = 6,
    HSpurge_duration: float = 20, 
    DeltaDilute1_duration: float = 0,
    initialization: bool = False,
    co2measure_duration: float = 20,
    co2measure_acqrate: float = 0.1,
    co2_ppm_thresh: float = 90000,
    purge_if: Union[str, float] = "below",
    max_repeats: int = 5,
):
    apm = ActionPlanMaker()
    if DeltaDilute1_duration == 0:
        apm.add(ORCH_server, "wait", {"waittime": 0.25})
    else:

#
# DILUTION PURGE        
        apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": DeltaDilute1_duration})  # DeltaDilute time usually 15

#
# MAIN HEADSPACE PURGE
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 1}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 1}, asc.no_wait)

    apm.add(ORCH_server, "wait", {"waittime": HSpurge_duration})

    if initialization:
        apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": 0.5})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0})
 
    if initialization:
        apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})

#
# HEADSPACE EVALUATION
    apm.add(
        CO2S_server,
        "acquire_co2",
        {
            "duration": co2measure_duration,
            "acquisition_rate": co2measure_acqrate,
        },
        technique_name="gas_purge",
        process_finish=True,
        process_contrib=[ProcessContrib.files],
    )
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1}, asc.no_wait)
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})


    return apm.planned_actions


def CCSI_sub_drain(
    experiment: Experiment,
    experiment_version: int = 5,  
    HSpurge_duration: float = 20,  
    DeltaDilute1_duration: float = 0,
    initialization: bool = False,
    recirculation: bool = False,
    recirculation_duration: float = 20,
):

    apm = ActionPlanMaker()
    if DeltaDilute1_duration == 0:
        apm.add(ORCH_server, "wait", {"waittime": 0.25})
    else:

#
# DILUTION PURGE        
        apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": DeltaDilute1_duration})  # DeltaDilute time usually 15

#
# MAIN HEADSPACE PURGE and FILL
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 1}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 1}, asc.no_wait)

    apm.add(ORCH_server, "wait", {"waittime": HSpurge_duration})
    if recirculation:
        apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": recirculation_duration})
        apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})

    if initialization:
        apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": 0.5})

    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0})
    if initialization:
        apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0}, asc.no_wait)

    return apm.planned_actions




def CCSI_sub_initialization_end_state(
    experiment: Experiment,
    experiment_version: int = 1,
):
    # only Pump off, 1A closed //

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    # apm.add(ORCH_server, "wait", {"waittime": 0.25})
    # apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 1})
    # apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1}, asc.no_wait)
    # apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1}, asc.no_wait)
    # apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0}, asc.no_wait)
    # apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0}, asc.no_wait)
    # apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0}, asc.no_wait)
    # apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0}, asc.no_wait)
    # apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0}, asc.no_wait)
    # apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0}, asc.no_wait)
    # apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0}, asc.no_wait)
    # apm.add(ORCH_server, "wait", {"waittime": 0.25})
    # apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0})
    # apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0}, asc.no_wait)
    # apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0}, asc.no_wait)
    #   apm.add(MFC---stuff Flow ON)
    return apm.planned_actions


def CCSI_sub_peripumpoff(
    experiment: Experiment,
    experiment_version: int = 1,
):
    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    # apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 1}, asc.no_wait)
    # apm.add(ORCH_server, "wait", {"waittime": 0.25})
    # apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1})
    # apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1}, asc.no_wait)
    # apm.add(ORCH_server, "wait", {"waittime": 0.25})
    # apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0})
    # apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0}, asc.no_wait)
    # apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0}, asc.no_wait)

    return apm.planned_actions


def CCSI_sub_initialization_firstpart(
    experiment: Experiment,
    experiment_version: int = 3,
    HSpurge1_duration: float = 60,
    Manpurge1_duration: float = 10,
    Alphapurge1_duration: float = 10,
    Probepurge1_duration: float = 10,
    Sensorpurge1_duration: float = 15,
    #    DeltaDilute1_duration: float = 15,
):
 #   
 # ALL OFF
    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0,},)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "8", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "9", "on": 0}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})

#
# MAIN HEADSPACE PURGE and FILL
    # headspace flow purge cell via v1 v6
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 1}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": HSpurge1_duration})

    #  sub_solvent purge//headspace flow purge eta via v2 v6

    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 1}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 1}, asc.no_wait)
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD0", "on": 0}, asc.no_wait)
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD1", "on": 0}, asc.no_wait)
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD2", "on": 1}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": Manpurge1_duration})

    # line purge via v2 v5

    apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 1}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": Alphapurge1_duration})

#
# AUX PROBE PURGE
    # eche probe flow purge via v5
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": Probepurge1_duration})

#
# pCO2 SENSOR PURGE
    # only valve 3 closed //differ from probe purge
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": Sensorpurge1_duration})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0}, asc.no_wait)

    return apm.planned_actions


def CCSI_sub_cellfill(
    #   formerly def CCSI_sub_liquidfill_syringes(
    experiment: Experiment,
    experiment_version: int = 1,  # move co2 monitoring to separate exp
    #    experiment_version: int = 10, #ver 6to7 implements multivalve, #10 gas push between
    Solution_description: str = "KOH",
    Solution_reservoir_sample_no: int = 2,
    Solution_volume_ul: float = 500,
    Clean_reservoir_sample_no: int = 1,
    Clean_volume_ul: float = 2500,
    Syringe_rate_ulsec: float = 300,
    LiquidFillWait_s: float = 15,
    #    co2measure_duration: float = 20,
    #    co2measure_acqrate: float = 0.5,
):
    apm = ActionPlanMaker()
    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {
            "custom": "cell1_we",
        },
        to_global_params=[
            "_fast_samples_in"
        ],  # save new liquid_sample_no of eche cell to globals
    )

    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 1}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    ### CO2 acquisition that matters //// does not.
    # during first infusion
    #    inf1_acqtime = Solution_volume_ul/Syringe_rate_ulsec + .25
    #    apm.add(CO2S_server, "acquire_co2", {"duration": inf1_acqtime, "acquisition_rate": co2measure_acqrate})

    if Solution_volume_ul == 0:
        apm.add(ORCH_server, "wait", {"waittime": 0.25})
    else:
        apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD2", "on": 1})
        apm.add(
            NI_server, "multivalve", {"multivalve": "multi_CMD1", "on": 1}, asc.no_wait
        )
        apm.add(
            NI_server, "multivalve", {"multivalve": "multi_CMD0", "on": 1}, asc.no_wait
        )
        if Clean_volume_ul == 0:
            procfinish = True
        else:
            procfinish = False
        apm.add(
            SOLUTIONPUMP_server,
            "infuse",
            {
                "rate_uL_sec": Syringe_rate_ulsec,
                "volume_uL": Solution_volume_ul,
            },
            from_global_act_params={"_fast_samples_in": "fast_samples_in"},
            technique_name="syringe_inject",
            process_finish=procfinish,
            process_contrib=[
                ProcessContrib.action_params,
                ProcessContrib.samples_in,
            ],
        )
        apm.add(ORCH_server, "wait", {"waittime": 5.25})
        apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 1})
        apm.add(
            NI_server, "multivalve", {"multivalve": "multi_CMD0", "on": 0}, asc.no_wait
        )
        apm.add(
            NI_server, "multivalve", {"multivalve": "multi_CMD1", "on": 0}, asc.no_wait
        )
        apm.add(
            NI_server, "multivalve", {"multivalve": "multi_CMD2", "on": 1}, asc.no_wait
        )
        apm.add(ORCH_server, "wait", {"waittime": LiquidFillWait_s})
        apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 0})

    apm.add(ORCH_server, "wait", {"waittime": 0.25})

    if Clean_volume_ul == 0:
        apm.add(ORCH_server, "wait", {"waittime": 0.25})
    else:
        apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD2", "on": 1})
        apm.add(
            NI_server, "multivalve", {"multivalve": "multi_CMD1", "on": 1}, asc.no_wait
        )
        apm.add(
            NI_server, "multivalve", {"multivalve": "multi_CMD0", "on": 0}, asc.no_wait
        )
        if Solution_volume_ul == 0:
            proccontrib = [
                ProcessContrib.action_params,
                ProcessContrib.samples_in,
            ]
        else:
            proccontrib = [
                ProcessContrib.action_params,
            ]

        apm.add(
            WATERCLEANPUMP_server,
            "infuse",
            {
                "rate_uL_sec": Syringe_rate_ulsec,
                "volume_uL": Clean_volume_ul,
            },
            from_global_act_params={"_fast_samples_in": "fast_samples_in"},
            technique_name="syringe_inject",
            process_finish=True,
            process_contrib=proccontrib,
        )
        apm.add(ORCH_server, "wait", {"waittime": 5.25})
        apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 1})
        apm.add(
            NI_server, "multivalve", {"multivalve": "multi_CMD0", "on": 0}, asc.no_wait
        )
        apm.add(
            NI_server, "multivalve", {"multivalve": "multi_CMD1", "on": 0}, asc.no_wait
        )
        apm.add(
            NI_server, "multivalve", {"multivalve": "multi_CMD2", "on": 1}, asc.no_wait
        )
        apm.add(ORCH_server, "wait", {"waittime": LiquidFillWait_s})
        apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 0})

    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": 1.75})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0}, asc.no_wait)
    return apm.planned_actions


def CCSI_sub_co2monitoring(
    experiment: Experiment,
    experiment_version: int = 1,  # move co2 monitoring to separate exp
    co2measure_duration: float = 20,
    co2measure_acqrate: float = 0.5,
):
    apm = ActionPlanMaker()

    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    #    apm.add(IO_server, "acquire_analog_in", {"duration":co2measure_duration + 1,"acquisition_rate": co2measure_acqrate, })
    apm.add(
        CO2S_server,
        "acquire_co2",
        {
            "duration": co2measure_duration,
            "acquisition_rate": co2measure_acqrate,
        },
        # asc.no_wait,
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        technique_name="Measure_recirculated_headspace",
        process_finish=True,
        process_contrib=[
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": co2measure_duration})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})

    return apm.planned_actions


def CCSI_sub_co2monitoring_mfcmasscotwo(
    experiment: Experiment,
    experiment_version: int = 1,
    co2measure_duration: float = 300,
    co2measure_acqrate: float = 0.5,
    flowrate_sccm: float = 0.3,
    flowramp_sccm: float = 9,
    init_max_flow_s: float = 30,
):
    apm = ActionPlanMaker()

    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    #    apm.add(IO_server, "acquire_analog_in", {"duration":co2measure_duration + 1,"acquisition_rate": co2measure_acqrate, }, nonblocking=True)
    apm.add(
        MFC_server,
        "acquire_flowrate",
        {
            "flowrate_sccm": 0.5,
            "ramp_sccm_sec": flowramp_sccm,
            "duration": init_max_flow_s,
            "acquisition_rate": co2measure_acqrate,
        },
        asc.no_wait,
    )
    # need to account for gas sample
    apm.add(
        CO2S_server,
        "acquire_co2",
        {
            "duration": co2measure_duration,
            "acquisition_rate": co2measure_acqrate,
        },
        asc.no_wait,
        nonblocking=True,
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        technique_name="Measure_recirculated_headspace",
        process_finish=True,
        process_contrib=[
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1}, asc.no_wait)

    apm.add(
        MFC_server,
        "acquire_flowrate",
        {
            "flowrate_sccm": flowrate_sccm,
            "ramp_sccm_sec": flowramp_sccm,
            "duration": co2measure_duration - init_max_flow_s,
            "acquisition_rate": co2measure_acqrate,
        },
    )

    #    apm.add(ORCH_server, "wait", {"waittime": co2measure_duration})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})

    return apm.planned_actions


def CCSI_sub_co2topup_mfcmassdose(
    experiment: Experiment,
    experiment_version: int = 1,
    co2measure_acqrate: float = 0.5,
    flowrate_sccm: float = 0.3,
    flowramp_sccm: float = 9,
    duration_s: float = 300,
    target_pressure: float = 14.30,
    total_gas_scc: float = 7.0,
    refill_freq_sec: float = 2.0,
):
    apm = ActionPlanMaker()

    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    #    apm.add(IO_server, "acquire_analog_in", {"duration":duration_s,"acquisition_rate": co2measure_acqrate, })
    apm.add(
        MFC_server,
        "acquire_flowrate",
        {
            "flowrate_sccm": None,
            "duration": -1,
            "acquisition_rate": co2measure_acqrate,
        },
        technique_name="Measure_added_co2",
        process_finish=True,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
        ],
    )
    # need to account for gas sample
    apm.add(
        MFC_server,
        "maintain_pressure",
        {
            "flowrate_sccm": flowrate_sccm,
            "ramp_sccm_sec": flowramp_sccm,
            "duration": duration_s,
            "target_pressure": target_pressure,
            "total_gas_scc": total_gas_scc,
            "refill_freq_sec": refill_freq_sec,
        },
        asc.no_wait,
    )
    apm.add(MFC_server, "cancel_acquire_flowrate", {})

    return apm.planned_actions


def CCSI_sub_co2constantpressure(
    experiment: Experiment,
    experiment_version: int = 1,
    co2measure_duration: float = 20,
    co2measure_acqrate: float = 0.5,
    atm_pressure: float = 14.27,
    pressureramp: float = 2,
):
    # v2 v1ab open, sol inject clean inject

    apm = ActionPlanMaker()
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    #    apm.add(IO_server, "acquire_analog_in", {"duration":co2measure_duration + 1,"acquisition_rate": co2measure_acqrate, })
    apm.add(
        MFC_server,
        "acquire_pressure",
        {
            "pressure_psia": atm_pressure,
            "ramp_psi_sec": pressureramp,
            "duration": co2measure_duration,
            "acquisition_rate": co2measure_acqrate,
        },
        technique_name="Measure_added_co2",
        process_finish=False,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
        ],
    )
    # need to account for gas sample
    apm.add(
        CO2S_server,
        "acquire_co2",
        {
            "duration": co2measure_duration,
            "acquisition_rate": co2measure_acqrate,
        },
        asc.no_wait,
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        technique_name="Measure_recirculated_headspace",
        process_finish=True,
        process_contrib=[
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1}, asc.no_wait)
    #    apm.add(ORCH_server, "wait", {"waittime": co2measure_duration})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})

    return apm.planned_actions


def CCSI_sub_co2mass_temp(
    experiment: Experiment,
    experiment_version: int = 1,
    co2measure_duration: float = 300,
    co2measure_acqrate: float = 0.5,
    flowrate_sccm: float = 0.3,
    flowramp_sccm: float = 9,
    init_max_flow_s: float = 30,
):
    # v2 v1ab open, sol inject clean inject

    apm = ActionPlanMaker()
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    #    apm.add(IO_server, "acquire_analog_in", {"duration":co2measure_duration + 1,"acquisition_rate": co2measure_acqrate, }, nonblocking=True)
    apm.add(
        MFC_server,
        "acquire_flowrate",
        {
            "flowrate_sccm": 0.5,
            "ramp_sccm_sec": flowramp_sccm,
            "duration": init_max_flow_s,
            "acquisition_rate": co2measure_acqrate,
        },
        technique_name="Measure_added_co2",
        process_finish=False,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
        ],
    )
    # need to account for gas sample
    apm.add(
        CO2S_server,
        "acquire_co2",
        {
            "duration": co2measure_duration,
            "acquisition_rate": co2measure_acqrate,
        },
        asc.no_wait,
        nonblocking=True,
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        technique_name="Measure_recirculated_headspace",
        process_finish=False,
        process_contrib=[
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1}, asc.no_wait)

    apm.add(
        MFC_server,
        "acquire_flowrate",
        {
            "flowrate_sccm": flowrate_sccm,
            "ramp_sccm_sec": flowramp_sccm,
            "duration": co2measure_duration - init_max_flow_s,
            "acquisition_rate": co2measure_acqrate,
        },
        technique_name="Measure_added_co2",
        process_finish=True,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
        ],
    )

    #    apm.add(ORCH_server, "wait", {"waittime": co2measure_duration})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})

    return apm.planned_actions


def CCSI_sub_co2massdose(
    experiment: Experiment,
    experiment_version: int = 1,
    co2measure_duration: float = 300,
    co2measure_acqrate: float = 0.5,
    flowrate_sccm: float = 0.5,
    flowramp_sccm: float = 0,
    target_pressure: float = 14.30,
    total_gas_scc: float = 7.0,
    refill_freq_sec: float = 2.0,
):
    apm = ActionPlanMaker()
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    #    apm.add(IO_server, "acquire_analog_in", {"duration":co2measure_duration + 1,"acquisition_rate": co2measure_acqrate, }, nonblocking=True)
    apm.add(
        MFC_server,
        "acquire_flowrate",
        {
            "flowrate_sccm": None,
            "duration": -1,
            "acquisition_rate": co2measure_acqrate,
        },
        nonblocking=True,
        technique_name="Measure_added_co2",
        process_finish=False,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
        ],
    )
    apm.add(
        MFC_server,
        "maintain_pressure",
        {
            "flowrate_sccm": flowrate_sccm,
            "ramp_sccm_sec": flowramp_sccm,
            "duration": co2measure_duration
            + 30,  # arbitrary time to allow for final correction
            "target_pressure": target_pressure,
            "total_gas_scc": total_gas_scc,
            "refill_freq_sec": refill_freq_sec,
        },
        asc.no_wait,
        nonblocking=True,
    )
    # need to account for gas sample
    apm.add(
        CO2S_server,
        "acquire_co2",
        {
            "duration": co2measure_duration,
            "acquisition_rate": co2measure_acqrate,
        },
        asc.no_wait,
        # nonblocking=True,
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        technique_name="Measure_recirculated_headspace",
        process_finish=True,
        process_contrib=[
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1}, asc.no_wait)

    #    apm.add(ORCH_server, "wait", {"waittime": co2measure_duration})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    apm.add(
        MFC_server,
        "cancel_acquire_flowrate",
        {},
    )

    return apm.planned_actions


def CCSI_sub_co2maintainconcentration(
    experiment: Experiment,
    experiment_version: int = 1,
    co2measure_duration: float = 300,
    co2measure_acqrate: float = 0.5,
    flowrate_sccm: float = 0.5,
    flowramp_sccm: float = 0,
    target_co2_ppm: float = 1e5,
    headspace_scc: float = 7.5,
    refill_freq_sec: float = 60.0,
):
    apm = ActionPlanMaker()
    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {
            "custom": "cell1_we",
        },
        to_global_params=[
            "_fast_samples_in"
        ],  # save new liquid_sample_no of eche cell to globals
    )
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    #    apm.add(IO_server, "acquire_analog_in", {"duration":co2measure_duration + 1,"acquisition_rate": co2measure_acqrate, }, nonblocking=True)
    apm.add(
        MFC_server,
        "acquire_flowrate",
        {
            "flowrate_sccm": None,
            "duration": -1,
            "acquisition_rate": co2measure_acqrate,
        },
        nonblocking=True,
        technique_name="Measure_added_co2",
        process_finish=False,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
        ],
    )
    apm.add(
        MFC_server,
        "maintain_concentration",
        {
            "flowrate_sccm": flowrate_sccm,
            "ramp_sccm_sec": flowramp_sccm,
            "duration": co2measure_duration + 30,  # arbitrary time to allow for final correction
            "target_co2_ppm": target_co2_ppm,
            "headspace_scc": headspace_scc,
            "refill_freq_sec": refill_freq_sec,
        },
        asc.no_wait,
        nonblocking=True,
    )
    apm.add(
        CO2S_server,
        "acquire_co2",
        {
            "duration": co2measure_duration,
            "acquisition_rate": co2measure_acqrate,
        },
        asc.no_wait,
        # nonblocking=True,
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        technique_name="Measure_recirculated_headspace",
        process_finish=True,
        process_contrib=[
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1}, asc.no_wait)


    #    apm.add(ORCH_server, "wait", {"waittime": co2measure_duration})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    apm.add(
        MFC_server,
        "cancel_acquire_flowrate",
        {},
    )

    return apm.planned_actions


def CCSI_sub_flowflush(
    experiment: Experiment,
    experiment_version: int = 3,
    co2measure_duration: float = 3600,
    co2measure_acqrate: float = 0.5,
    flowrate_sccm: float = 0.3,
    flowramp_sccm: float = 0,
):
    apm = ActionPlanMaker()

    apm.add(
        MFC_server,
        "acquire_flowrate",
        {
            "flowrate_sccm": 0.5,
            "ramp_sccm_sec": flowramp_sccm,
            "duration": co2measure_duration,
            "acquisition_rate": co2measure_acqrate,
        },
        nonblocking=True,
    )
    apm.add(
        CO2S_server,
        "acquire_co2",
        {
            "duration": co2measure_duration,
            "acquisition_rate": co2measure_acqrate,
        },
        asc.no_wait,
        nonblocking=True,
    )
    apm.add(
        NI_server,
        "pump",
        {"pump": "RecirculatingPeriPump1", "on": 1},
        asc.no_wait,
        nonblocking=True,
    )

    # cycles = int(co2measure_duration / 30),
    for t in range(60):
        apm.add(ORCH_server, "wait", {"waittime": 28})
        apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": 2})
        apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0})
        apm.add(ORCH_server, "wait", {"waittime": 28})
        apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1})
        apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1}, asc.no_wait)
        apm.add(ORCH_server, "wait", {"waittime": 2})
        apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
        apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0}, asc.no_wait)

    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    return apm.planned_actions

#
# PRE CL
#

def CCSI_sub_clean_inject(
    experiment: Experiment,
    experiment_version: int = 7,  # ver 2 implements multivalve, ver 3 conditional, ver6 co2checktargetvolumerefills
    Clean_volume_ul: float = 10000,
    Syringe_rate_ulsec: float = 500,
    LiquidCleanWait_s: float = 15,
    co2measure_duration: float = 20,
    co2measure_acqrate: float = 1,
    use_co2_check: bool = True,
    need_fill: bool = False,
    co2_ppm_thresh: float = 41000,
    purge_if: Union[str, float] = "below",
    max_repeats: int = 5,
    LiquidCleanPurge_duration: float = 60,  # set before determining actual
    DeltaDilute1_duration: float = 0,
    drainrecirc: bool = True,
):
    # drain
    # only 1B 6A-waste opened 1A closed pump off//differ from delta purge

    apm = ActionPlanMaker()
    if need_fill:
        apm.add(NI_server, "liquidvalve", {"liquidvalve": "8", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": 0.25})
        apm.add(
            WATERCLEANPUMP_server,
            "withdraw",
            {
                "rate_uL_sec": Syringe_rate_ulsec,
                "volume_uL": Clean_volume_ul,
            },
        )
        apm.add(ORCH_server, "wait", {"waittime": 5.25})
        apm.add(NI_server, "liquidvalve", {"liquidvalve": "8", "on": 0})

#
# LIQUID FILL
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 1}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD2", "on": 1})
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD1", "on": 1}, asc.no_wait)
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD0", "on": 0}, asc.no_wait)
    apm.add(
        WATERCLEANPUMP_server,
        "infuse",
        {
            "rate_uL_sec": Syringe_rate_ulsec,
            "volume_uL": Clean_volume_ul,
        },
    )
    apm.add(
        WATERCLEANPUMP_server,
        "get_present_volume",
        {},
        to_global_params=["_present_volume_ul"],
    )
    apm.add(ORCH_server, "wait", {"waittime": 5.25})


    apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 1})
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD0", "on": 0}, asc.no_wait)
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD1", "on": 0}, asc.no_wait)
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD2", "on": 1}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": LiquidCleanWait_s})


#
# HEADSPACE REC
    # mfc off, v2, v1ab v7 close
    # mfc off
    apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": 0.25})

    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})

    ### removed when separate pressure gauge removed from system
    # apm.add(
    #     IO_server,
    #     "acquire_analog_in",
    #     {
    #         "duration": co2measure_duration + 1,
    #         "acquisition_rate": co2measure_acqrate,
    #     },
    # )
    apm.add(
        CO2S_server,
        "acquire_co2",
        {
            "duration": co2measure_duration,
            "acquisition_rate": co2measure_acqrate,
        },
        asc.no_wait,
        technique_name="liquid_purge",
        process_finish=True,
        process_contrib=[
            ProcessContrib.files,
        ],
    )
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1}, asc.no_wait)
    if use_co2_check:
        apm.add(
            CO2S_server,
            "acquire_co2",
            {
                "duration": 1.5,
                "acquisition_rate": 0.5,
            },
        )
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})

    if use_co2_check:
        apm.add(
            CALC_server,
            "check_co2_purge",
            {
                "co2_ppm_thresh": co2_ppm_thresh,
                "purge_if": purge_if,
                "repeat_experiment_name": "CCSI_sub_clean_inject",
                "repeat_experiment_params": {
                    k: v
                    for k, v in vars(apm.pars).items()
                    if not k.startswith("experiment")
                },
            },
            from_global_act_params={"_present_volume_ul": "present_syringe_volume_ul"},
        )

#
# LIQUID DRAIN
    apm.add_actions(
        CCSI_sub_drain(
            experiment=experiment,
            HSpurge_duration=LiquidCleanPurge_duration,
            recirculation=drainrecirc,
        )
    )

    return apm.planned_actions


def CCSI_sub_refill_clean(
    experiment: Experiment,
    experiment_version: int = 2,  # v2 no backlash volume
    Clean_volume_ul: float = 5000,
    Syringe_rate_ulsec: float = 1000,
):
    apm = ActionPlanMaker()
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "8", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": 0.25})

    apm.add(
        WATERCLEANPUMP_server,
        "withdraw",
        {
            "rate_uL_sec": Syringe_rate_ulsec,
            "volume_uL": Clean_volume_ul,
        },
    )
    apm.add(ORCH_server, "wait", {"waittime": 5.25})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "8", "on": 0})

    return apm.planned_actions


# def CCSI_sub_set_syringe_start(
#     experiment: Experiment,
#     experiment_version: int = 1,
#     syringe: str = "waterclean",
#     Starting_volume_ul: float = 50000,
# ):
#     apm = ActionPlanMaker()
#     if syringe == "waterclean":
#         apm.add(WATERCLEANPUMP_server, "set_present_volume", {"volume_uL": Starting_volume_ul})
#     if syringe == "solution1":
#         apm.add(SOLUTIONPUMP_server, "set_present_volume", {"volume_uL": Starting_volume_ul})
#     # if more syringes can add more names here
#     return apm.planned_actions


def CCSI_sub_full_fill_syringe(
    experiment: Experiment,
    experiment_version: int = 2,  # v2 check volume of 15ml
    syringe: str = "waterclean",
    target_volume_ul: float = 50000,
    Syringe_rate_ulsec: float = 1000,
):
    apm = ActionPlanMaker()
    apm.add(
        WATERCLEANPUMP_server,
        "get_present_volume",
        {},
        to_global_params=["_present_volume_ul"],
    )
    apm.add(
        CALC_server,
        "fill_syringe_volume_check",
        {
            "check_volume_ul": 15000,
            "target_volume_ul": target_volume_ul,
            "repeat_experiment_name": "CCSI_sub_fill_syringe",
            "repeat_experiment_params": {
                "syringe": "waterclean",
                "fill_volume_ul": 0,
            },
        },
        from_global_act_params={"_present_volume_ul": "present_volume_ul"},
    )

    return apm.planned_actions


def CCSI_sub_fill_syringe(
    experiment: Experiment,
    experiment_version: int = 1,
    syringe: str = "waterclean",
    fill_volume_ul: float = 0,
    Syringe_rate_ulsec: float = 1000,
):
    apm = ActionPlanMaker()
    if syringe == "waterclean":
        apm.add(NI_server, "liquidvalve", {"liquidvalve": "8", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": 0.25})
        apm.add(
            WATERCLEANPUMP_server,
            "withdraw",
            {
                "rate_uL_sec": Syringe_rate_ulsec,
                "volume_uL": fill_volume_ul,
            },
        )
        apm.add(ORCH_server, "wait", {"waittime": 5.25})
        apm.add(NI_server, "liquidvalve", {"liquidvalve": "8", "on": 0})

    if syringe == "solution1":
        # need valve for this soln
        apm.add(ORCH_server, "wait", {"waittime": 0.25})
        apm.add(
            SOLUTIONPUMP_server,
            "withdraw",
            {
                "rate_uL_sec": Syringe_rate_ulsec,
                "volume_uL": fill_volume_ul,
            },
        )
        apm.add(ORCH_server, "wait", {"waittime": 5.25})
        # would need a valve for refill of this syringe, then copy steps from watersyringe

    return apm.planned_actions


def CCSI_debug_co2purge(
    experiment: Experiment,
    experiment_version: int = 3,
    co2measure_duration: float = 10,
    co2measure_acqrate: float = 0.1,
    co2_ppm_thresh: float = 90000,
    purge_if: Union[str, float] = -0.05,
):
    apm = ActionPlanMaker()
    apm.add(
        CO2S_server,
        "acquire_co2",
        {
            "duration": co2measure_duration,
            "acquisition_rate": co2measure_acqrate,
        },
        technique_name="liquid_purge",
        process_finish=True,
        process_contrib=[
            ProcessContrib.files,
        ],
    )
    apm.add(
        CALC_server,
        "check_co2_purge",
        {
            "co2_ppm_thresh": co2_ppm_thresh,
            "purge_if": purge_if,
            "repeat_experiment_name": "CCSI_debug_co2purge",
            "repeat_experiment_params": {
                k: v
                for k, v in vars(apm.pars).items()
                if not k.startswith("experiment")
            },
        },
    )
    return apm.planned_actions


def CCSI_leaktest_co2(
    experiment: Experiment,
    experiment_version: int = 1,
    co2measure_duration: float = 600,
    co2measure_acqrate: float = 1,
    recirculate: bool = True,
):
    apm = ActionPlanMaker()

    apm.add(
        CO2S_server,
        "acquire_co2",
        {
            "duration": co2measure_duration,
            "acquisition_rate": co2measure_acqrate,
        },
    )
    if recirculate:
        apm.add(
            NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1}, asc.no_wait
        )

    return apm.planned_actions
