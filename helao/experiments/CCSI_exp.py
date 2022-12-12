"""
Action library for CCSI

server_key must be a FastAPI action server defined in config
"""

__all__ = [
    "ANEC_sub_startup",
    
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

ORCH_HOST = gethostname()
PSTAT_server = MachineModel(server_name="PSTAT", machine_name=ORCH_HOST).json_dict()
MOTOR_server = MachineModel(server_name="MOTOR", machine_name=ORCH_HOST).json_dict()
NI_server = MachineModel(server_name="NI", machine_name=ORCH_HOST).json_dict()
ORCH_server = MachineModel(server_name="ORCH", machine_name=ORCH_HOST).json_dict()
PAL_server = MachineModel(server_name="PAL", machine_name=ORCH_HOST).json_dict()
IO_server = MachineModel(server_name="IO", machine_name=ORCH_HOST).json_dict()
CO2S_server = MachineModel(server_name="SENSOR", machine_name=ORCH_HOST).json_dict()
toggle_triggertype = TriggerType.fallingedge


# z positions for ADSS cell
z_home = 0.0
# touches the bottom of cell
z_engage = 2.5
# moves it up to put pressure on seal
z_seal = 4.5

def CCSI_sub_alloff(
    experiment: Experiment,
    experiment_version: int = 1,
):
    """

    Args:
        experiment (Experiment): Experiment object provided by Orch
    """

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "8", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "9", "on": 0})

    return apm.action_list

def CCSI_sub_headspace_purge_from_start(
    experiment: Experiment,
    experiment_version: int = 1,
    HSpurge1_duration: float = 20, #set before determining actual
):
# only valve 1B and 6A turned on//differ from power on state

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0})
    apm.add(ORCH_server,"wait",{"waittime": .25})
#   apm.add(MFC---stuff Flow ON)
    apm.add(ORCH_server,"wait",{"waittime": apm.pars.HSpurge1_duration})

    return apm.action_list

def CCSI_sub_solvent_purge(
    experiment: Experiment,
    experiment_version: int = 1,
    Manpurge1_duration: float = 30, #set before determining actual
):
#  valve 2 and 7 opened, 1B closed//differ from headspace purge

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 1})
    apm.add(ORCH_server,"wait",{"waittime": .25})
#   apm.add(MFC---stuff Flow ON)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0})
    apm.add(ORCH_server,"wait",{"waittime": apm.pars.Manpurge1_duration})

    return apm.action_list

def CCSI_sub_alpha_purge(
    experiment: Experiment,
    experiment_version: int = 1,
    Alphapurge1_duration: float = 15, #set before determining actual
):
# only valve 1B 5AB 7 opened, and 2 6A closed//differ from solvent purge

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0})
    apm.add(ORCH_server,"wait",{"waittime": .25})
#   apm.add(MFC---stuff Flow ON)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0})
    apm.add(ORCH_server,"wait",{"waittime": apm.pars.Alphapurge1_duration})

    return apm.action_list

def CCSI_sub_probe_purge(
    experiment: Experiment,
    experiment_version: int = 1,
    Probepurge1_duration: float = 60, #set before determining actual
):
# only valve 3 4 opened, and 5A closed, pump on//differ from alpha purge

    apm = ActionPlanMaker()
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0})
    apm.add(ORCH_server,"wait",{"waittime": .25})
#   apm.add(MFC---stuff Flow ON)
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 1})
    apm.add(ORCH_server,"wait",{"waittime": apm.pars.Probepurge1_duration})

    return apm.action_list

def CCSI_sub_sensor_purge(
    experiment: Experiment,
    experiment_version: int = 1,
    Sensorpurge1_duration: float = 60, #set before determining actual
):
# only valve 3 closed //differ from probe purge

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0})
#    apm.add(ORCH_server,"wait",{"waittime": .25})
#   apm.add(MFC---stuff Flow ON)
    apm.add(ORCH_server,"wait",{"waittime": apm.pars.Sensorpurge1_duration})

    return apm.action_list

def CCSI_sub_delta_purge(
    experiment: Experiment,
    experiment_version: int = 1,
    Deltapurge1_duration: float = 120, #set before determining actual
):
# recirculation loop
# only valve 1B, 4, 5B closed 1A opened//differ from sensor purge

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0})
#    apm.add(ORCH_server,"wait",{"waittime": .25})
#   apm.add(MFC---stuff Flow ON)
    apm.add(ORCH_server,"wait",{"waittime": apm.pars.Deltapurge1_duration})

    return apm.action_list

def CCSI_sub_headspace_purge(
    experiment: Experiment,
    experiment_version: int = 1,
    HSpurge1_duration: float = 20, #set before determining actual
):
# recirculation loop
# only 1B 6A opened 1A closed pump off//differ from delta purge

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0})
    apm.add(ORCH_server,"wait",{"waittime": .25})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A", "on": 1})
#   apm.add(MFC---stuff Flow ON)
    apm.add(ORCH_server,"wait",{"waittime": apm.pars.HSpurge1_duration})

    return apm.action_list

def CCSI_sub_measure_headspace_frompurge(
    experiment: Experiment,
    experiment_version: int = 1,
    HSmeasure1_duration: float = 60, #set before determining actual
):
# recirculation loop
# only 1A 6A opened 1B closed pump on//differ from delta purge

    apm = ActionPlanMaker()
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0})
    apm.add(ORCH_server,"wait",{"waittime": .25})
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 1})
#   apm.add(MFC---stuff Flow ON)
##  apm.add(CO2S_server, "acquire_co2",{})
    apm.add(ORCH_server,"wait",{"waittime": apm.pars.HSmeasure1_duration})
    apm.add(CO2S_server,"acquire_co2", {"duration": 1, "acquisition_rate": 0.1})
    return apm.action_list
