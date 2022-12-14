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
    "CCSI_sub_headspace_purge_from_start",
    "CCSI_sub_solvent_purge",
    "CCSI_sub_alpha_purge",
    "CCSI_sub_probe_purge",
    "CCSI_sub_sensor_purge",
    "CCSI_sub_delta_purge",
    "CCSI_sub_headspace_purge_and_measure",
]

###
from socket import gethostname
from typing import Optional

from helao.helpers.premodels import Experiment, ActionPlanMaker
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
CO2S_server = MachineModel(server_name="CO2SENSOR", machine_name=ORCH_HOST).json_dict()
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
    apm.add(
        NI_server,
        "pump",
        {
            "pump": "RecirculatingPeriPump1tingPeriPump1tingPeriPump1tingPeriPump1tingPeriPump1",
            "on": 0,
        },
    )
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "8", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "9", "on": 0})

    return apm.action_list


def CCSI_sub_headspace_purge_from_start(
    experiment: Experiment,
    experiment_version: int = 1,
    HSpurge1_duration: float = 20,  # set before determining actual
):
    # only valve 1B and 6A-waste turned on//differ from power on state

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    #   apm.add(MFC---stuff Flow ON)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.HSpurge1_duration})

    return apm.action_list


def CCSI_sub_solvent_purge(
    experiment: Experiment,
    experiment_version: int = 1,
    Manpurge1_duration: float = 30,  # set before determining actual
):
    #  valve 2 and 7 opened, 1B closed//differ from headspace purge

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    #   apm.add(MFC---stuff Flow ON)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.Manpurge1_duration})

    return apm.action_list


def CCSI_sub_alpha_purge(
    experiment: Experiment,
    experiment_version: int = 1,
    Alphapurge1_duration: float = 15,  # set before determining actual
):
    # only valve 1B 5A-cellB 7 opened, and 2 6A-waste closed//differ from solvent purge

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    #   apm.add(MFC---stuff Flow ON)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.Alphapurge1_duration})

    return apm.action_list


def CCSI_sub_probe_purge(
    experiment: Experiment,
    experiment_version: int = 1,
    Probepurge1_duration: float = 60,  # set before determining actual
):
    # only valve 3 4 opened, and 5A-cell closed, pump on//differ from alpha purge

    apm = ActionPlanMaker()
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    #   apm.add(MFC---stuff Flow ON)
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.Probepurge1_duration})

    return apm.action_list


def CCSI_sub_sensor_purge(
    experiment: Experiment,
    experiment_version: int = 1,
    Sensorpurge1_duration: float = 60,  # set before determining actual
):
    # only valve 3 closed //differ from probe purge

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0})
    #    apm.add(ORCH_server,"wait",{"waittime": .25})
    #   apm.add(MFC---stuff Flow ON)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.Sensorpurge1_duration})

    return apm.action_list


def CCSI_sub_delta_purge(
    experiment: Experiment,
    experiment_version: int = 1,
    Deltapurge1_duration: float = 120,  # set before determining actual
):
    # recirculation loop
    # only valve 1B, 4, 5B-waste closed 1A opened//differ from sensor purge

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0})
    #    apm.add(ORCH_server,"wait",{"waittime": .25})
    #   apm.add(MFC---stuff Flow ON)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.Deltapurge1_duration})

    return apm.action_list


def CCSI_sub_headspace_purge_and_measure(
    experiment: Experiment,
    experiment_version: int = 1,
    HSpurge_duration: float = 20,  # set before determining actual
    HSmeasure1_duration: float = 60,  # set before determining actual
    CO2measure_duration: float = 1,
    CO2measure_acqrate: float = 0.1,
):
    # recirculation loop
    # only 1B 6A-waste opened 1A closed pump off//differ from delta purge

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 1})
    #   apm.add(MFC---stuff Flow ON)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.HSpurge_duration})

    # recirculation loop
    # only 1A 6A-waste opened 1B closed pump on//differ from purge

    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})
    #   apm.add(MFC---stuff Flow ON)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.HSmeasure1_duration})
    apm.add(
        CO2S_server,
        "acquire_co2",
        {
            "duration": apm.pars.CO2measure_duration,
            "acquisition_rate": apm.pars.CO2measure_acqrate,
        },
    )
    return apm.action_list
