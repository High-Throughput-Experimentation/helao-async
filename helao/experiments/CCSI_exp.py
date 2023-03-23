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
    # "CCSI_sub_headspace_purge_from_start",
    # "CCSI_sub_solvent_purge",
    # "CCSI_sub_alpha_purge",
    # "CCSI_sub_probe_purge",
    # "CCSI_sub_sensor_purge",
    # "CCSI_sub_delta_purge",
    "CCSI_sub_headspace_purge_and_measure",
    "CCSI_sub_drain",
    "CCSI_sub_drain_wcirc",
    "CCSI_sub_initialization_end_state",
    "CCSI_sub_peripumpoff",
    "CCSI_sub_initialization_firstpart",
    "CCSI_sub_liquidfill_syringes",
    "CCSI_sub_clean_inject",
    "CCSI_sub_clean_inject_withcheck",    
    "CCSI_sub_refill_clean",
    "CCSI_debug_co2purge",
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
from helao.drivers.motion.galil_motion_driver import MoveModes, TransformationModes
from helao.drivers.io.enum import TriggerType

# list valid experiment functions
EXPERIMENTS = __all__

ORCH_HOST = gethostname()
PSTAT_server = MachineModel(server_name="PSTAT", machine_name=ORCH_HOST).json_dict()
MOTOR_server = MachineModel(server_name="MOTOR", machine_name=ORCH_HOST).json_dict()
NI_server = MachineModel(server_name="NI", machine_name=ORCH_HOST).json_dict()
ORCH_server = MachineModel(server_name="ORCH", machine_name=ORCH_HOST).json_dict()
PAL_server = MachineModel(server_name="PAL", machine_name=ORCH_HOST).json_dict()
IO_server = MachineModel(server_name="IO", machine_name=ORCH_HOST).json_dict()
CALC_server = MachineModel(server_name="CALC", machine_name=ORCH_HOST).json_dict()
CO2S_server = MachineModel(server_name="CO2SENSOR", machine_name=ORCH_HOST).json_dict()
SOLUTIONPUMP_server = MachineModel(
    server_name="SYRINGE0", machine_name=ORCH_HOST
).json_dict()
WATERCLEANPUMP_server = MachineModel(
    server_name="SYRINGE1", machine_name=ORCH_HOST
).json_dict()
toggle_triggertype = TriggerType.fallingedge


# z positions for  cell
z_home = 0.0
# touches the bottom of cell
z_engage = 2.5
# moves it up to put pressure on seal
z_seal = 4.5


def CCSI_sub_unload_cell(experiment: Experiment, experiment_version: int = 1):
    """Unload Sample at 'cell1_we' position."""

    apm = ActionPlanMaker()
    apm.add(PAL_server, "archive_custom_unloadall", {})
    return apm.action_list


# def ANEC_sub_unload_liquid(
#     experiment: Experiment,
#     experiment_version: int = 1,
# ):
#     """Unload liquid sample at 'cell1_we' position and reload solid sample."""

#     apm = ActionPlanMaker()
#     apm.add(
#         PAL_server,
#         "archive_custom_unloadall",
#         {},
#         to_globalexp_params=["_unloaded_solid"],
#     )
#     apm.add(
#         PAL_server,
#         "archive_custom_load",
#         {"custom": "cell1_we"},
#         from_globalexp_params={"_unloaded_solid": "load_sample_in"},
#     )
#     return apm.action_list


def CCSI_sub_load_solid(
    experiment: Experiment,
    experiment_version: int = 1,
    solid_plate_id: Optional[int] = 4534,
    solid_sample_no: Optional[int] = 1,
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
            ).dict(),
        },
    )

    return apm.action_list


def CCSI_sub_load_liquid(
    experiment: Experiment,
    experiment_version: int = 2,
    reservoir_liquid_sample_no: Optional[int] = 1,
    volume_ul_cell_liquid: Optional[int] = 1000,
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
            ).dict(),
            "volume_ml": apm.pars.volume_ul_cell_liquid / 1000,
            "combine_liquids": apm.pars.combine_True_False,
            "dilute_liquids": apm.pars.water_True_False,
        },
    )
    return apm.action_list


def CCSI_sub_load_gas(
    experiment: Experiment,
    experiment_version: int = 2,
    reservoir_gas_sample_no: Optional[int] = 1,
    volume_ul_cell_gas: Optional[int] = 1000,
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
            ).dict(),
            "volume_ml": apm.pars.volume_ul_cell_gas / 1000,
        },
    )
    return apm.action_list


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

    return apm.action_list


def CCSI_sub_headspace_purge_from_start(
    experiment: Experiment,
    experiment_version: int = 2,
    HSpurge1_duration: float = 30,  # set before determining actual
):
    # only valve 1B and 6A-waste turned on//differ from power on state

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 1}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 0}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 1}, asc.no_wait)
    #   apm.add(MFC---stuff Flow ON)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.HSpurge1_duration})

    return apm.action_list


def CCSI_sub_solvent_purge(
    experiment: Experiment,
    experiment_version: int = 3,  #vers 2 to 3 implementing multivalve
    Manpurge1_duration: float = 10,  # set before determining actual
):
    #  valve 2 and 7 opened, 1B closed//differ from headspace purge

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 1}, asc.no_wait)
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD0", "on": 0}, asc.no_wait)
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD1", "on": 0}, asc.no_wait)
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD2", "on": 1}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    #   apm.add(MFC---stuff Flow ON)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.Manpurge1_duration})

    return apm.action_list


def CCSI_sub_alpha_purge(
    experiment: Experiment,
    experiment_version: int = 2,
    Alphapurge1_duration: float = 10,  # set before determining actual
):
    # only valve 1B 5A-cellB opened, and 2 6A-waste 7 closed//differ from solvent purge

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    #   apm.add(MFC---stuff Flow ON)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 1}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.Alphapurge1_duration})

    return apm.action_list


def CCSI_sub_probe_purge(
    experiment: Experiment,
    experiment_version: int = 2,
    Probepurge1_duration: float = 10,  # set before determining actual
):
    # only valve 3 4 opened, and 5A-cell closed, pump on//differ from alpha purge

    apm = ActionPlanMaker()
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 1}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    #   apm.add(MFC---stuff Flow ON)
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.Probepurge1_duration})

    return apm.action_list


def CCSI_sub_sensor_purge(
    experiment: Experiment,
    experiment_version: int = 2,
    Sensorpurge1_duration: float = 10,  # set before determining actual
):
    # only valve 3 closed //differ from probe purge

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0}, asc.no_wait)
    # apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0}, asc.no_wait)
    #    apm.add(ORCH_server,"wait",{"waittime": .25})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.Sensorpurge1_duration})

    return apm.action_list


def CCSI_sub_delta_purge(
    experiment: Experiment,
    experiment_version: int = 2,
    DeltaDilute1_duration: float = 10,  # set before determining actual
):
    # recirculation loop
    # only valve 1B, 4, 5B-waste closed 1A opened//differ from sensor purge

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0}, asc.no_wait)
    # apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0}, asc.no_wait)
    #    apm.add(ORCH_server,"wait",{"waittime": .25})
    #   apm.add(MFC---stuff Flow ON)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.DeltaDilute1_duration})

    return apm.action_list


def CCSI_sub_headspace_purge_and_measure(
    experiment: Experiment,
    experiment_version: int = 6,
    HSpurge_duration: float = 20,  # set before determining actual
    DeltaDilute1_duration: float = 0,
    initialization: bool = False,
    co2measure_duration: float = 20,
    co2measure_acqrate: float = 0.1,
    co2_ppm_thresh: float = 90000,
    purge_if: Union[str, float] = "below",
    max_purge_iters: int = 5,
    # HSmeasure1_duration: float = 20,  # set before determining actual
):

    apm = ActionPlanMaker()
    if apm.pars.DeltaDilute1_duration == 0:
        apm.add(ORCH_server, "wait", {"waittime": 0.25})
    else:   
        apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": apm.pars.DeltaDilute1_duration})  #DeltaDilute time usually 15
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0}, asc.no_wait)
    #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0}, asc.no_wait)
    #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0}, asc.no_wait)
    #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0}, asc.no_wait)
    #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0}, asc.no_wait)
    #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0}, asc.no_wait)
    #    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 1}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 1}, asc.no_wait)
    #   apm.add(MFC---stuff Flow ON)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.HSpurge_duration})

    if apm.pars.initialization:
        apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": 0.5})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0},asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0})
    if apm.pars.initialization:
        apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0}, asc.no_wait)
    #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0}, asc.no_wait)
    #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0}, asc.no_wait)
    #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0}, asc.no_wait)
    #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0}, asc.no_wait)
    #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0}, asc.no_wait)
    #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0}, asc.no_wait)
    # apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(
        CO2S_server,
        "acquire_co2",
        {
            "duration": apm.pars.co2measure_duration,
            "acquisition_rate": apm.pars.co2measure_acqrate,
        },
        technique_name="gas_purge",
        process_finish=True,
        process_contrib=[ProcessContrib.files],
    )
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1}, asc.no_wait)
#    apm.add(ORCH_server, "wait", {"waittime": apm.pars.co2measure_duration}, asc.no_wait)
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})

    # apm.add(
    #     CALC_server,
    #     "check_co2_purge",
    #     {
    #         "co2_ppm_thresh": apm.pars.co2_ppm_thresh,
    #         "purge_if": apm.pars.purge_if,
    #         "repeat_experiment_name": "CCSI_sub_headspace_purge_and_measure",
    #         "repeat_experiment_params": {
    #             k: v
    #             for k, v in vars(apm.pars).items()
    #             if not k.startswith("experiment")
    #         },
    #     },
    # )

    return apm.action_list


def CCSI_sub_drain(
    experiment: Experiment,
    experiment_version: int =2,
    HSpurge_duration: float = 20,  # set before determining actual
    DeltaDilute1_duration: float = 0,
    initialization: bool = False,
    recirculation: bool = True
):
    # recirculation loop

    apm = ActionPlanMaker()
    if apm.pars.DeltaDilute1_duration == 0:
        apm.add(ORCH_server, "wait", {"waittime": 0.25})
    else:   
        apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": apm.pars.DeltaDilute1_duration})  #DeltaDilute time usually 15
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0}, asc.no_wait)
    #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0}, asc.no_wait)
    #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0}, asc.no_wait)
    #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0}, asc.no_wait)
    #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0}, asc.no_wait)
    #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0}, asc.no_wait)
    #    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 1}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 1}, asc.no_wait)
    if apm.pars.recirculation:
        apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1}, asc.no_wait)
        apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 1}, asc.no_wait)
   #   apm.add(MFC---stuff Flow ON)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.HSpurge_duration})
    if apm.pars.recirculation:
        apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0})
        apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0}, asc.no_wait)

    if apm.pars.initialization:
        apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": 0.5})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server,"liquidvalve",{"liquidvalve": "6A-waste", "on": 0})
    if apm.pars.initialization:
        apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0}, asc.no_wait)

    return apm.action_list

def CCSI_sub_drain_wcirc(
    experiment: Experiment,
    experiment_version: int =1,
    HSpurge_duration: float = 20,  # set before determining actual
    DeltaDilute1_duration: float = 0,
    initialization: bool = False,
):
    # recirculation loop

    apm = ActionPlanMaker()
    if apm.pars.DeltaDilute1_duration == 0:
        apm.add(ORCH_server, "wait", {"waittime": 0.25})
    else:   
        apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": apm.pars.DeltaDilute1_duration})  #DeltaDilute time usually 15
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0}, asc.no_wait)
    #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0}, asc.no_wait)
    #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0}, asc.no_wait)
    #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0}, asc.no_wait)
    #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0}, asc.no_wait)
    #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0}, asc.no_wait)
    #    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 1}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 1}, asc.no_wait)
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 1}, asc.no_wait)
   #   apm.add(MFC---stuff Flow ON)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.HSpurge_duration})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0}, asc.no_wait)

    if apm.pars.initialization:
        apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": 0.5})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server,"liquidvalve",{"liquidvalve": "6A-waste", "on": 0})
    if apm.pars.initialization:
        apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0}, asc.no_wait)

    return apm.action_list

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
    return apm.action_list


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

    return apm.action_list


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
    apm.add(ORCH_server, "wait", {"waittime": 0.25})

    # headspace flow purge cell via v1 v6
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1}, asc.no_wait)
 #   apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 1}, asc.no_wait)
    #   apm.add(MFC---stuff Flow ON)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.HSpurge1_duration})

    #  sub_solvent purge//headspace flow purge eta via v2 v6

    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 1}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 1}, asc.no_wait)
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD0", "on": 0}, asc.no_wait)
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD1", "on": 0}, asc.no_wait)
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD2", "on": 1}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.Manpurge1_duration})

    # alpha flow purge via v2 v5

    apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 1}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.Alphapurge1_duration})

    # eche probe flow purge via v5
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.Probepurge1_duration})

    # only valve 3 closed //differ from probe purge
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0}, asc.no_wait)
    #    apm.add(ORCH_server,"wait",{"waittime": .25})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.Sensorpurge1_duration})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0}, asc.no_wait)

            # # recirculation loop
            # # only valve 1A opened valve 1B, 4, 5B-waste closed//differ from sensor purge

            # apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1})
            # apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0}, asc.no_wait)
            # apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0}, asc.no_wait)
            # apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0}, asc.no_wait)
            # #    apm.add(ORCH_server,"wait",{"waittime": .25})
            # apm.add(ORCH_server, "wait", {"waittime": apm.pars.DeltaDilute1_duration})

    return apm.action_list


def CCSI_sub_liquidfill_syringes(
    experiment: Experiment,
    experiment_version: int = 9, #ver 6to7 implements multivalve
    Solution_description: str = "KOH",
    Solution_reservoir_sample_no: int = 2,
    Solution_volume_ul: float = 500,
    Waterclean_reservoir_sample_no: int = 1,
    Waterclean_volume_ul: float = 2500,
    Syringe_retraction_ul: float = 150,
    Syringe_rate_ulsec: float = 300,
    deadspace_volume_ul: float = 50,
    backlash_volume_ul: float = 50,
    LiquidFillWait_s: float = 15,
    co2measure_duration: float = 20,
    co2measure_acqrate: float = 0.5,
):
    # v2 v1ab open, sol inject clean inject

    apm = ActionPlanMaker()
    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {
            "custom": "cell1_we",
        },
        to_globalexp_params=[
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
#    apm.add(CO2S_server, "acquire_co2", {"duration": inf1_acqtime, "acquisition_rate": apm.pars.co2measure_acqrate})

    if apm.pars.Solution_volume_ul == 0:
        apm.add(ORCH_server, "wait", {"waittime": 0.25})
    else:
        apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD2", "on": 1})
        apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD1", "on": 1}, asc.no_wait)
        apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD0", "on": 1}, asc.no_wait)
        if apm.pars.Waterclean_volume_ul == 0:
            procfinish = True
        else:
            procfinish = False
        apm.add(
            SOLUTIONPUMP_server,
            "infuse",
            {
                "rate_uL_sec": apm.pars.Syringe_rate_ulsec,
                "volume_uL": apm.pars.Solution_volume_ul + apm.pars.deadspace_volume_ul,
            },
            
            from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
            technique_name="syringe_inject",
            process_finish= procfinish,
            process_contrib=[
                ProcessContrib.action_params,
                ProcessContrib.samples_in,
            ],
    )
    apm.add(ORCH_server, "wait", {"waittime": 0.25})

    if apm.pars.Waterclean_volume_ul == 0:
        apm.add(ORCH_server, "wait", {"waittime": 0.25})
    else:    
        apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD2", "on": 1})
        apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD1", "on": 1}, asc.no_wait)
        apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD0", "on": 0}, asc.no_wait)
        if apm.pars.Solution_volume_ul == 0:
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
                "rate_uL_sec": apm.pars.Syringe_rate_ulsec,
                "volume_uL": apm.pars.Waterclean_volume_ul + apm.pars.deadspace_volume_ul,
            },
            
            from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
            technique_name="syringe_inject",
            process_finish=True,
            process_contrib= proccontrib,
    )    
    apm.add(ORCH_server, "wait", {"waittime": 0.25})

    # v7  open, mfc flow, wait, syringes retract
#    apm.add(CO2S_server, "acquire_co2", {"duration": apm.pars.LiquidFillWait_s, "acquisition_rate": apm.pars.co2measure_acqrate})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 1})
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD0", "on": 0}, asc.no_wait)
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD1", "on": 0}, asc.no_wait)
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD2", "on": 1})
    # mfc stuff add here
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.LiquidFillWait_s})

#     if apm.pars.Solution_volume_ul == 0:
#         apm.add(ORCH_server, "wait", {"waittime": 0.25})
#     else:
#         apm.add(
#             SOLUTIONPUMP_server,
#             "withdraw",
#             {
#                 "rate_uL_sec": apm.pars.Syringe_rate_ulsec,
#                 "volume_uL": apm.pars.Syringe_retraction_ul,
#             },
        
#         )
#         apm.add(ORCH_server, "wait", {"waittime": 0.25})
#         apm.add(
#             SOLUTIONPUMP_server,
#             "infuse",
#             {
#                 "rate_uL_sec": apm.pars.Syringe_rate_ulsec,
#                 "volume_uL": apm.pars.backlash_volume_ul,
#             },
            
#         )
# #    if Waterclean_volume_ul != 0:
# #    apm.add(CO2S_server, "acquire_co2", {"duration": withdr_acqtime, "acquisition_rate": apm.pars.co2measure_acqrate})
#     if apm.pars.Waterclean_volume_ul == 0:
#         apm.add(ORCH_server, "wait", {"waittime": 0.25})
#     else:    
#         apm.add(
#             WATERCLEANPUMP_server,
#             "withdraw",
#             {
#                 "rate_uL_sec": apm.pars.Syringe_rate_ulsec,
#                 "volume_uL": apm.pars.Syringe_retraction_ul,
#             },
            
#         )
#         apm.add(ORCH_server, "wait", {"waittime": 0.25})
#         apm.add(
#             WATERCLEANPUMP_server,
#             "infuse",
#             {
#                 "rate_uL_sec": apm.pars.Syringe_rate_ulsec,
#                 "volume_uL": apm.pars.backlash_volume_ul,
#             },
            
#         )

    # mfc off, v2, v1ab v7 close
    # mfc off
    apm.add(ORCH_server, "wait", {"waittime": 0.25})

    apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(IO_server, "acquire_analog_in", {"duration":apm.pars.co2measure_duration + 1,"acquisition_rate": apm.pars.co2measure_acqrate, })
    apm.add(
        CO2S_server,
        "acquire_co2",
        {
            "duration": apm.pars.co2measure_duration,
            "acquisition_rate": apm.pars.co2measure_acqrate,
        },
        asc.no_wait,
        from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
        technique_name="Recirculate_headspace",
        process_finish=True,
        process_contrib=[
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1}, asc.no_wait)
#    apm.add(ORCH_server, "wait", {"waittime": apm.pars.co2measure_duration})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})

    return apm.action_list

def CCSI_sub_clean_inject(
    experiment: Experiment,
    experiment_version: int = 4,  #ver 2 implements multivalve, ver 3 conditional
    Waterclean_volume_ul: float = 5000,
    deadspace_volume_ul: float = 50,
    backlash_volume_ul: float = 50,
    Syringe_rate_ulsec: float = 500,
    Syringe_retraction_ul: float = 150,
    LiquidCleanWait_s: float = 15,
    co2measure_duration: float = 20,
    co2measure_acqrate: float = 0.1,
    co2_ppm_thresh: float = 41000,
    purge_if: Union[str, float] = "below",
    max_purge_iters: int = 5,
    LiquidCleanPurge_duration: float = 60,  # set before determining actual
    drainrecirc: bool = True,
):
    # drain
    # only 1B 6A-waste opened 1A closed pump off//differ from delta purge

    apm = ActionPlanMaker()
    # apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    # #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0}, asc.no_wait)
    # #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0}, asc.no_wait)
    # #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0}, asc.no_wait)
    # #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0}, asc.no_wait)
    # #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0}, asc.no_wait)
    # #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0}, asc.no_wait)
    # #    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0}, asc.no_wait)
    # apm.add(ORCH_server, "wait", {"waittime": 0.25})
    # apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    # apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 1})
    # apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1}, asc.no_wait)
    # apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 1}, asc.no_wait)
    # #   apm.add(MFC---stuff Flow ON)
    # apm.add(ORCH_server, "wait", {"waittime": apm.pars.LiquidCleanPurge_duration})
    # #  MFC off
    # apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 0})
    # apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0}, asc.no_wait)
    # apm.add(ORCH_server, "wait", {"waittime": 0.25})
    # apm.add(
    #     NI_server,
    #     "liquidvalve",
    #     {"liquidvalve": "6A-waste", "on": 0},
    # )

    # v2 v1ab open, clean inject

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
            "rate_uL_sec": apm.pars.Syringe_rate_ulsec,
            "volume_uL": apm.pars.Waterclean_volume_ul + apm.pars.deadspace_volume_ul,
        },
    )
    apm.add(ORCH_server, "wait", {"waittime": 0.25})

    # v7  open, mfc flow, wait, syringe retract

    apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 1})
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD0", "on": 0}, asc.no_wait)
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD1", "on": 0}, asc.no_wait)
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD2", "on": 1})
    # mfc stuff add here
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.LiquidCleanWait_s})
    # apm.add(
    #     WATERCLEANPUMP_server,
    #     "withdraw",
    #     {
    #         "rate_uL_sec": apm.pars.Syringe_rate_ulsec,
    #         "volume_uL": apm.pars.Syringe_retraction_ul,
    #     },
    # )
    # apm.add(ORCH_server, "wait", {"waittime": 0.25})
    # apm.add(
    #     WATERCLEANPUMP_server,
    #     "infuse",
    #     {
    #         "rate_uL_sec": apm.pars.Syringe_rate_ulsec,
    #         "volume_uL": apm.pars.backlash_volume_ul,
    #     },
        
    # )

    # mfc off, v2, v1ab v7 close
    # mfc off
    apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": 0.25})

    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(IO_server, "acquire_analog_in", {"duration":apm.pars.co2measure_duration + 1,"acquisition_rate": apm.pars.co2measure_acqrate, })
    apm.add(
        CO2S_server,
        "acquire_co2",
        {
            "duration": apm.pars.co2measure_duration,
            "acquisition_rate": apm.pars.co2measure_acqrate,
        },
        asc.no_wait,
        technique_name="liquid_purge",
        process_finish=True,
        process_contrib=[
            ProcessContrib.files,
        ],
    )
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1}, asc.no_wait)
#    apm.add(ORCH_server, "wait", {"waittime": apm.pars.co2measure_duration})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})

    # apm.add(
    #     CALC_server,
    #     "check_co2_purge",
    #     {
    #         "co2_ppm_thresh": apm.pars.co2_ppm_thresh,
    #         "purge_if": apm.pars.purge_if,
    #         "repeat_experiment_name": "CCSI_sub_clean_inject",
    #         "repeat_experiment_params": {
    #             k: v
    #             for k, v in vars(apm.pars).items()
    #             if not k.startswith("experiment")
    #         },
    #     },
    # )
    apm.add_action_list(CCSI_sub_drain(experiment=experiment,HSpurge_duration=apm.pars.LiquidCleanPurge_duration,recirculation=apm.pars.drainrecirc))

    return apm.action_list

def CCSI_sub_clean_inject_withcheck(
    experiment: Experiment,
    experiment_version: int = 3,  #ver 2 implements multivalve, ver 3 conditional
    Waterclean_volume_ul: float = 5000,
    deadspace_volume_ul: float = 50,
    backlash_volume_ul: float = 50,
    Syringe_rate_ulsec: float = 500,
    Syringe_retraction_ul: float = 150,
    LiquidCleanWait_s: float = 15,
    co2measure_duration: float = 20,
    co2measure_acqrate: float = 0.1,
    co2_ppm_thresh: float = 41000,
    purge_if: Union[str, float] = "below",
    max_purge_iters: int = 5,
    LiquidCleanPurge_duration: float = 60,  # set before determining actual
):
    # drain
    # only 1B 6A-waste opened 1A closed pump off//differ from delta purge

    apm = ActionPlanMaker()
    # apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    # #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0}, asc.no_wait)
    # #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0}, asc.no_wait)
    # #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0}, asc.no_wait)
    # #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0}, asc.no_wait)
    # #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0}, asc.no_wait)
    # #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0}, asc.no_wait)
    # #    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0}, asc.no_wait)
    # apm.add(ORCH_server, "wait", {"waittime": 0.25})
    # apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    # apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 1})
    # apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1}, asc.no_wait)
    # apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 1}, asc.no_wait)
    # #   apm.add(MFC---stuff Flow ON)
    # apm.add(ORCH_server, "wait", {"waittime": apm.pars.LiquidCleanPurge_duration})
    # #  MFC off
    # apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 0})
    # apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0}, asc.no_wait)
    # apm.add(ORCH_server, "wait", {"waittime": 0.25})
    # apm.add(
    #     NI_server,
    #     "liquidvalve",
    #     {"liquidvalve": "6A-waste", "on": 0},
    # )

    # v2 v1ab open, clean inject

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
            "rate_uL_sec": apm.pars.Syringe_rate_ulsec,
            "volume_uL": apm.pars.Waterclean_volume_ul + apm.pars.deadspace_volume_ul,
        },
    )
    apm.add(ORCH_server, "wait", {"waittime": 0.25})

    # v7  open, mfc flow, wait, syringe retract

    apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 1})
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD0", "on": 0}, asc.no_wait)
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD1", "on": 0}, asc.no_wait)
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD2", "on": 1})
    # mfc stuff add here
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.LiquidCleanWait_s})
    # apm.add(
    #     WATERCLEANPUMP_server,
    #     "withdraw",
    #     {
    #         "rate_uL_sec": apm.pars.Syringe_rate_ulsec,
    #         "volume_uL": apm.pars.Syringe_retraction_ul,
    #     },
    # )
    # apm.add(ORCH_server, "wait", {"waittime": 0.25})
    # apm.add(
    #     WATERCLEANPUMP_server,
    #     "infuse",
    #     {
    #         "rate_uL_sec": apm.pars.Syringe_rate_ulsec,
    #         "volume_uL": apm.pars.backlash_volume_ul,
    #     },
        
    # )

    # mfc off, v2, v1ab v7 close
    # mfc off
    apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": 0.25})

    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(
        CO2S_server,
        "acquire_co2",
        {
            "duration": apm.pars.co2measure_duration,
            "acquisition_rate": apm.pars.co2measure_acqrate,
        },
        technique_name="liquid_purge",
        process_finish=True,
        process_contrib=[
            ProcessContrib.files,
        ],
    )
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1}, asc.no_wait)
#    apm.add(ORCH_server, "wait", {"waittime": apm.pars.co2measure_duration})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})

    apm.add(
        CALC_server,
        "check_co2_purge",
        {
            "co2_ppm_thresh": apm.pars.co2_ppm_thresh,
            "purge_if": apm.pars.purge_if,
            "repeat_experiment_name": "CCSI_sub_clean_inject",
            "repeat_experiment_params": {
                k: v
                for k, v in vars(apm.pars).items()
                if not k.startswith("experiment")
            },
        },
    )
    apm.add_action_list(CCSI_sub_drain(experiment=experiment,HSpurge_duration=LiquidCleanPurge_duration))

    return apm.action_list

def CCSI_sub_refill_clean(
    experiment: Experiment,
    experiment_version: int = 1,
    Waterclean_volume_ul: float = 5000,
    Syringe_rate_ulsec: float = 1000,
):
    apm = ActionPlanMaker()
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "8", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": 0.25})

    apm.add(WATERCLEANPUMP_server, "withdraw", {"rate_uL_sec": apm.pars.Syringe_rate_ulsec, "volume_uL": apm.pars.Waterclean_volume_ul + 25})    
    apm.add(WATERCLEANPUMP_server, "infuse", {"rate_uL_sec": apm.pars.Syringe_rate_ulsec, "volume_uL": 25})    
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "8", "on": 0})
    
    return apm.action_list


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
            "duration": apm.pars.co2measure_duration,
            "acquisition_rate": apm.pars.co2measure_acqrate,
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
            "co2_ppm_thresh": apm.pars.co2_ppm_thresh,
            "purge_if": apm.pars.purge_if,
            "repeat_experiment_name": "CCSI_debug_co2purge",
            "repeat_experiment_params": {
                k: v
                for k, v in vars(apm.pars).items()
                if not k.startswith("experiment")
            },
        },
    )
    return apm.action_list
