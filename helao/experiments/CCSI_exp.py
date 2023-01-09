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
    "CCSI_sub_headspace_purge",
    "CCSI_sub_initialization_end_state",
    "CCSI_sub_atm_equilibrate",
    "CCSI_sub_initialization_firstpart",
    "CCSI_sub_liquidfill_syringes",
    "CCSI_sub_drain_and_clean",


]

###
from socket import gethostname
from typing import Optional, Union

from helao.helpers.premodels import Experiment, ActionPlanMaker
from helaocore.models.action_start_condition import ActionStartCondition
from helao.drivers.robot.pal_driver import PALtools
from helaocore.models.sample import SolidSample, LiquidSample, GasSample
from helaocore.models.machine import MachineModel
from helaocore.models.action_start_condition import ActionStartCondition
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
SOLUTIONPUMP_server = MachineModel(server_name="SYRINGE0", machine_name=ORCH_HOST).json_dict()
WATERCLEANPUMP_server = MachineModel(server_name="SYRINGE1", machine_name=ORCH_HOST).json_dict()
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
    experiment_version: int = 1,
    reservoir_liquid_sample_no: Optional[int] = 1,
    volume_ul_cell_liquid: Optional[int] = 1000,
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
            "volume_ml": apm.pars.volume_ul_cell_liquid,
            # "combine_liquids": True,
            # "dilute_liquids": True,
        },
    )
    return apm.action_list


def CCSI_sub_load_gas(
    experiment: Experiment,
    experiment_version: int = 1,
    reservoir_gas_sample_no: Optional[int] = 1,
    volume_ul_cell_gas: Optional[int] = 1000,
):
    """Add gas volume to cell position."""

    apm = ActionPlanMaker()
    apm.add(
        PAL_server,
        "archive_custom_add_liquid",  # not sure there is a server function for gas
        {
            "custom": "cell1_we",
            "source_liquid_in": GasSample(
                sample_no=apm.pars.reservoir_gas_sample_no, machine_name=ORCH_HOST
            ).dict(),
            "volume_ml": apm.pars.volume_ul_cell_gas,
            # "combine_liquids": True,
            # "dilute_liquids": True,
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
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1","on": 0,},)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "8", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "9", "on": 0},start_condition=ActionStartCondition.no_wait)

    return apm.action_list


def CCSI_sub_headspace_purge_from_start(
    experiment: Experiment,
    experiment_version: int = 2,
    HSpurge1_duration: float = 30,  # set before determining actual
):
    # only valve 1B and 6A-waste turned on//differ from power on state

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 1},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    #   apm.add(MFC---stuff Flow ON)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.HSpurge1_duration})

    return apm.action_list


def CCSI_sub_solvent_purge(
    experiment: Experiment,
    experiment_version: int = 1,
    Manpurge1_duration: float = 10,  # set before determining actual
):
    #  valve 2 and 7 opened, 1B closed//differ from headspace purge

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 1},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 1},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 1},start_condition=ActionStartCondition.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    #   apm.add(MFC---stuff Flow ON)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.Manpurge1_duration})

    return apm.action_list


def CCSI_sub_alpha_purge(
    experiment: Experiment,
    experiment_version: int = 1,
    Alphapurge1_duration: float = 10,  # set before determining actual
):
    # only valve 1B 5A-cellB opened, and 2 6A-waste 7 closed//differ from solvent purge

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 1},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 1},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    #   apm.add(MFC---stuff Flow ON)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.Alphapurge1_duration})

    return apm.action_list


def CCSI_sub_probe_purge(
    experiment: Experiment,
    experiment_version: int = 1,
    Probepurge1_duration: float = 10,  # set before determining actual
):
    # only valve 3 4 opened, and 5A-cell closed, pump on//differ from alpha purge

    apm = ActionPlanMaker()
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 1},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 1},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 1},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    #   apm.add(MFC---stuff Flow ON)
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.Probepurge1_duration})

    return apm.action_list


def CCSI_sub_sensor_purge(
    experiment: Experiment,
    experiment_version: int = 1,
    Sensorpurge1_duration: float = 10,  # set before determining actual
):
    # only valve 3 closed //differ from probe purge

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 1},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 1},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0},start_condition=ActionStartCondition.no_wait)
    #    apm.add(ORCH_server,"wait",{"waittime": .25})
    #   apm.add(MFC---stuff Flow ON)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.Sensorpurge1_duration})

    return apm.action_list


def CCSI_sub_delta_purge(
    experiment: Experiment,
    experiment_version: int = 1,
    Deltapurge1_duration: float = 10,  # set before determining actual
):
    # recirculation loop
    # only valve 1B, 4, 5B-waste closed 1A opened//differ from sensor purge

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0},start_condition=ActionStartCondition.no_wait)
    #    apm.add(ORCH_server,"wait",{"waittime": .25})
    #   apm.add(MFC---stuff Flow ON)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.Deltapurge1_duration})

    return apm.action_list


def CCSI_sub_headspace_purge_and_measure(
    experiment: Experiment,
    experiment_version: int = 3,
    HSpurge_duration: float = 20,  # set before determining actual
    co2measure_duration: float = 20,
    co2measure_acqrate: float = 0.1,
    # co2_ppm_thresh: float = 95000,
    # purge_if: Union[str, float] = "below",
#    HSmeasure1_duration: float = 20,  # set before determining actual
):
    # recirculation loop
    # only 1B 6A-waste opened 1A closed pump off//differ from delta purge

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
#    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0},start_condition=ActionStartCondition.no_wait)
#    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0},start_condition=ActionStartCondition.no_wait)
#    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0},start_condition=ActionStartCondition.no_wait)
#    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0},start_condition=ActionStartCondition.no_wait)
#    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0},start_condition=ActionStartCondition.no_wait)
#    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0},start_condition=ActionStartCondition.no_wait)
#    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 1},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1},start_condition=ActionStartCondition.no_wait)
    #   apm.add(MFC---stuff Flow ON)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.HSpurge_duration})

    # recirculation loop
    # 1A open , 6A-waste 1B closed pump on//differ from purge

    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0},start_condition=ActionStartCondition.no_wait)
#    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0},start_condition=ActionStartCondition.no_wait)
#    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0},start_condition=ActionStartCondition.no_wait)
#    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0},start_condition=ActionStartCondition.no_wait)
#    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0},start_condition=ActionStartCondition.no_wait)
#    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0},start_condition=ActionStartCondition.no_wait)
#    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0},start_condition=ActionStartCondition.no_wait)
#    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})
#    apm.add(ORCH_server, "wait", {"waittime": apm.pars.HSmeasure1_duration})

    apm.add(CO2S_server, "acquire_co2", {"duration": apm.pars.co2measure_duration, "acquisition_rate": apm.pars.co2measure_acqrate})
#    apm.add(CALC_server, "check_co2_purge", {"co2_ppm_thresh": apm.pars.co2_ppm_thresh, "purge_if": apm.pars.purge_if, "repeat_experiment_name": "CCSI_sub_headspace_purge_and_measure", "repeat_experiment_params": {"HSpurge_duration": 20} })

    return apm.action_list

def CCSI_sub_headspace_purge(
    experiment: Experiment,
    experiment_version: int = 2,
    HSpurge_duration: float = 20,  # set before determining actual
):
    # recirculation loop
    # only 1B 6A-waste opened 1A closed pump off//differ from delta purge

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
#    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0},start_condition=ActionStartCondition.no_wait)
#    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0},start_condition=ActionStartCondition.no_wait)
#    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0},start_condition=ActionStartCondition.no_wait)
#    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0},start_condition=ActionStartCondition.no_wait)
#    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0},start_condition=ActionStartCondition.no_wait)
#    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0},start_condition=ActionStartCondition.no_wait)
#    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 1},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1},start_condition=ActionStartCondition.no_wait)
    #   apm.add(MFC---stuff Flow ON)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.HSpurge_duration})
    #  MFC off
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0},)


    return apm.action_list


def CCSI_sub_initialization_end_state(
    experiment: Experiment,
    experiment_version: int = 1,
):
    # only Pump off, 1A closed //

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    #   apm.add(MFC---stuff Flow ON)
    return apm.action_list

def CCSI_sub_atm_equilibrate(
    experiment: Experiment,
    experiment_version: int = 1,
):
    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1},start_condition=ActionStartCondition.no_wait)

    return apm.action_list


def CCSI_sub_initialization_firstpart(
    experiment: Experiment,
    experiment_version: int = 1,
    HSpurge1_duration: float = 30,
    Manpurge1_duration: float = 10,
    Alphapurge1_duration: float = 10,
    Probepurge1_duration: float = 10,
    Sensorpurge1_duration: float = 10,
    Deltapurge1_duration: float = 10,
    
):
    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1","on": 0,},)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "8", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "9", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})

    # only valve 1B and 6A-waste turned on//differ from power on state
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1},start_condition=ActionStartCondition.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    #   apm.add(MFC---stuff Flow ON)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.HSpurge1_duration})

    #  valve 2 and 7 opened, 1B closed//differ from headspace purge

    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 1},start_condition=ActionStartCondition.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    #   apm.add(MFC---stuff Flow ON)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.Manpurge1_duration})

    # only valve 1B 5A-cellB opened, and 2 6A-waste 7 closed//differ from solvent purge

    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 1},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 1},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    #   apm.add(MFC---stuff Flow ON)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.Alphapurge1_duration})

    # only valve 3 4 opened, and 5A-cell closed, pump on//differ from alpha purge
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 1},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    #   apm.add(MFC---stuff Flow ON)
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.Probepurge1_duration})

    # only valve 3 closed //differ from probe purge
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0},start_condition=ActionStartCondition.no_wait)
    #    apm.add(ORCH_server,"wait",{"waittime": .25})
    #   apm.add(MFC---stuff Flow ON)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.Sensorpurge1_duration})

    # recirculation loop
    # only valve 1A opened valve 1B, 4, 5B-waste closed//differ from sensor purge

    apm = ActionPlanMaker()
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0},start_condition=ActionStartCondition.no_wait)
    #    apm.add(ORCH_server,"wait",{"waittime": .25})
    #   apm.add(MFC---stuff Flow ON)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.Deltapurge1_duration})

    return apm.action_list


def CCSI_sub_liquidfill_syringes(
    experiment: Experiment,
    experiment_version: int = 1,
    Solution_volume_ul: float = 5000,
    Waterclean_volume_ul: float = 5000,
    Syringe_retraction_ul: float = 500,
    Syringe_rate_ulsec: float = 500,
    LiquidFillWait_s: float = 15,
    co2measure_True_False:  bool = True,
    co2measure_duration: float = 120,
    co2measure_acqrate: float = 0.1,

):
    # v2 v1ab open, sol inject clean inject

    apm = ActionPlanMaker()
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 1},start_condition=ActionStartCondition.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
### CO2 acquisition that matters
    if co2measure_True_False:
        apm.add(CO2S_server, "acquire_co2", {"duration": apm.pars.co2measure_duration, "acquisition_rate": apm.pars.co2measure_acqrate})
    if Solution_volume_ul != 0:
        apm.add(SOLUTIONPUMP_server, "infuse", {"rate_uL_sec": apm.pars.Syringe_rate_ulsec , "volume_uL": apm.pars.Solution_volume_ul + apm.pars.Syringe_retraction_ul})
        apm.add(ORCH_server, "wait", {"waittime": 0.25})
    if Waterclean_volume_ul != 0:
        apm.add(WATERCLEANPUMP_server, "infuse", {"rate_uL_sec": apm.pars.Syringe_rate_ulsec, "volume_uL": apm.pars.Waterclean_volume_ul + apm.pars.Syringe_retraction_ul})    
        apm.add(ORCH_server, "wait", {"waittime": 0.25})

    #v7  open, mfc flow, wait, syringes retract

    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 1})
#mfc stuff add here
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.LiquidFillWait_s})
    if Solution_volume_ul != 0:
        apm.add(SOLUTIONPUMP_server, "withdraw", {"rate_uL_sec": apm.pars.Syringe_rate_ulsec , "volume_uL": apm.pars.Syringe_retraction_ul})
        apm.add(ORCH_server, "wait", {"waittime": 0.25})
    if Waterclean_volume_ul != 0:
        apm.add(WATERCLEANPUMP_server, "withdraw", {"rate_uL_sec": apm.pars.Syringe_rate_ulsec, "volume_uL": apm.pars.Syringe_retraction_ul})    

    #mfc off, v2, v1ab v7 close    
#mfc off
    apm.add(ORCH_server, "wait", {"waittime": 0.25})

    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})

    return apm.action_list

def CCSI_sub_drain_and_clean(
    experiment: Experiment,
    experiment_version: int = 2,
    Waterclean_volume_ul: float = 5000,
    Syringe_retraction_ul: float = 500,
    Syringe_rate_ulsec: float = 500,
    LiquidFillWait_s: float = 15,
    co2measure_duration: float = 120,
    co2measure_acqrate: float = 0.1,
    co2_ppm_thresh: float = 90000,
    purge_if: Union[str, float] = "below",
    HSpurge_duration: float = 20,  # set before determining actual
):
    # recirculation loop
    # only 1B 6A-waste opened 1A closed pump off//differ from delta purge

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
#    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0},start_condition=ActionStartCondition.no_wait)
#    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0},start_condition=ActionStartCondition.no_wait)
#    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0},start_condition=ActionStartCondition.no_wait)
#    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0},start_condition=ActionStartCondition.no_wait)
#    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0},start_condition=ActionStartCondition.no_wait)
#    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0},start_condition=ActionStartCondition.no_wait)
#    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 1},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1},start_condition=ActionStartCondition.no_wait)
    #   apm.add(MFC---stuff Flow ON)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.HSpurge_duration})
    #  MFC off
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0},)


    # v2 v1ab open, clean inject

    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 1},start_condition=ActionStartCondition.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(WATERCLEANPUMP_server, "infuse", {"rate_uL_sec": apm.pars.Syringe_rate_ulsec, "volume_uL": apm.pars.Waterclean_volume_ul + apm.pars.Syringe_retraction_ul})    
    apm.add(ORCH_server, "wait", {"waittime": 0.25})

    #v7  open, mfc flow, wait, syringe retract

    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 1})
#mfc stuff add here
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.LiquidFillWait_s})
    apm.add(WATERCLEANPUMP_server, "withdraw", {"rate_uL_sec": apm.pars.Syringe_rate_ulsec, "volume_uL": apm.pars.Syringe_retraction_ul})    

    #mfc off, v2, v1ab v7 close    
#mfc off
    apm.add(ORCH_server, "wait", {"waittime": 0.25})

    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0},start_condition=ActionStartCondition.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})

    apm.add(CO2S_server, "acquire_co2", {"duration": apm.pars.co2measure_duration, "acquisition_rate": apm.pars.co2measure_acqrate})
    # apm.add(CALC_server, "check_co2_purge", {"co2_ppm_thresh": apm.pars.co2_ppm_thresh, "purge_if": apm.pars.purge_if, "repeat_experiment_name": "CCSI_drain_and_clean", "repeat_experiment_params":  
    # {"Waterclean_volume_ul": 5000,
    # "Syringe_retraction_ul": 500,
    # "Syringe_rate_ulsec": 500,
    # "LiquidFillWait_s": 15,
    # "co2measure_duration": 20,
    # "co2measure_acqrate": 0.1,
    # "co2_ppm_thresh": 90000,
    # "purge_if": "below",
    # "HSpurge_duration": 20} 
    # })

    return apm.action_list


