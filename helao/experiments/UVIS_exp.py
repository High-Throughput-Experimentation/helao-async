"""
Experiment library for UVIS
server_key must be a FastAPI action server defined in config
"""

__all__ = [
    "UVIS_sub_unloadall_customs",
    "UVIS_sub_load_solid",
    "UVIS_sub_startup",
    "UVIS_sub_shutdown",
    "UVIS_sub_movetosample",
    "UVIS_sub_move",
    "UVIS_sub_spectrometer_T",
    "UVIS_sub_spectrometer_R",
]


from typing import Optional, List, Union
from socket import gethostname

from helao.helpers.premodels import Action, Experiment, ActionPlanMaker
from helaocore.models.action_start_condition import ActionStartCondition
from helaocore.models.sample import SolidSample, LiquidSample
from helaocore.models.machine import MachineModel
from helaocore.models.process_contrib import ProcessContrib
from helaocore.models.electrolyte import Electrolyte

from helao.drivers.motion.enum import MoveModes, TransformationModes
from helao.drivers.io.enum import TriggerType
from helao.drivers.robot.enum import PALtools, Spacingmethod


EXPERIMENTS = __all__

PSTAT_server = MachineModel(server_name="PSTAT", machine_name=gethostname()).json_dict()

MOTOR_server = MachineModel(server_name="MOTOR", machine_name=gethostname()).json_dict()
IO_server = MachineModel(server_name="IO", machine_name=gethostname()).json_dict()
SPEC_T_server = MachineModel(
    server_name="SPEC_T", machine_name=gethostname()
).json_dict()
SPEC_R_server = MachineModel(
    server_name="SPEC_R", machine_name=gethostname()
).json_dict()

ORCH_server = MachineModel(server_name="ORCH", machine_name=gethostname()).json_dict()
PAL_server = MachineModel(server_name="PAL", machine_name=gethostname()).json_dict()

toggle_triggertype = TriggerType.fallingedge


def UVIS_sub_unloadall_customs(experiment: Experiment):
    """last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    apm.add_action(
        {
            "action_server": PAL_server,
            "action_name": "archive_custom_unloadall",
            "action_params": {
                "destroy_liquid": True,
            },
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        }
    )

    return apm.action_list  # returns complete action list to orch


def UVIS_sub_load_solid(
    experiment: Experiment,
    experiment_version: int = 1,
    solid_custom_position: Optional[str] = "cell1_we",
    solid_plate_id: Optional[int] = 4534,
    solid_sample_no: Optional[int] = 1,
):
    """last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    apm.add_action(
        {
            "action_server": PAL_server,
            "action_name": "archive_custom_load",
            "action_params": {
                "custom": apm.pars.solid_custom_position,
                "load_sample_in": SolidSample(
                    **{
                        "sample_no": apm.pars.solid_sample_no,
                        "plate_id": apm.pars.solid_plate_id,
                        "machine_name": "legacy",
                    }
                ).dict(),
            },
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        }
    )

    return apm.action_list  # returns complete action list to orch


def UVIS_sub_startup(
    experiment: Experiment,
    experiment_version: int = 2,
    solid_custom_position: Optional[str] = "cell1_we",
    solid_plate_id: Optional[int] = 4534,
    solid_sample_no: Optional[int] = 1,
):
    """Sub experiment
    last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # unload all samples from custom positions
    apm.add_action_list(UVIS_sub_unloadall_customs(experiment=experiment))

    # load new requested solid samples
    apm.add_action_list(
        UVIS_sub_load_solid(
            experiment=experiment,
            solid_custom_position=apm.pars.solid_custom_position,
            solid_plate_id=apm.pars.solid_plate_id,
            solid_sample_no=apm.pars.solid_sample_no,
        )
    )

    # get sample plate coordinates
    apm.add_action(
        {
            "action_server": MOTOR_server,
            "action_name": "solid_get_samples_xy",
            "action_params": {
                "plate_id": apm.pars.solid_plate_id,
                "sample_no": apm.pars.solid_sample_no,
            },
            "to_global_params": [
                "_platexy"
            ],  # save new liquid_sample_no of eche cell to globals
            "start_condition": ActionStartCondition.wait_for_all,
        }
    )

    # move to position
    apm.add_action(
        {
            "action_server": MOTOR_server,
            "action_name": "move",
            "action_params": {
                # "d_mm": [apm.pars.x_mm, apm.pars.y_mm],
                "axis": ["x", "y"],
                "mode": MoveModes.absolute,
                "transformation": TransformationModes.platexy,
            },
            "from_global_params": {"_platexy": "d_mm"},
            "start_condition": ActionStartCondition.wait_for_all,
        }
    )

    return apm.action_list  # returns complete action list to orch


def UVIS_sub_shutdown(experiment: Experiment):
    """Sub experiment

    last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # unload all samples from custom positions
    apm.add_action_list(UVIS_sub_unloadall_customs(experiment=experiment))

    return apm.action_list  # returns complete action list to orch


def UVIS_sub_movetosample(
    experiment: Experiment,
    experiment_version: int = 1,
    solid_plate_id: Optional[int] = 4534,
    solid_sample_no: Optional[int] = 1,
):
    """Sub experiment
    last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # get sample plate coordinates
    apm.add_action(
        {
            "action_server": MOTOR_server,
            "action_name": "solid_get_samples_xy",
            "action_params": {
                "plate_id": apm.pars.solid_plate_id,
                "sample_no": apm.pars.solid_sample_no,
            },
            "to_global_params": [
                "_platexy"
            ],  # save new liquid_sample_no of eche cell to globals
            "start_condition": ActionStartCondition.wait_for_all,
        }
    )

    # move to position
    apm.add_action(
        {
            "action_server": MOTOR_server,
            "action_name": "move",
            "action_params": {
                # "d_mm": [apm.pars.x_mm, apm.pars.y_mm],
                "axis": ["x", "y"],
                "mode": MoveModes.absolute,
                "transformation": TransformationModes.platexy,
            },
            "from_global_params": {"_platexy": "d_mm"},
            "start_condition": ActionStartCondition.wait_for_all,
        }
    )

    return apm.action_list  # returns complete action list to orch


def UVIS_sub_move(
    experiment: Experiment,
    experiment_version: int = 1,
    x_mm: float = 1.0,
    y_mm: float = 1.0,
):
    """Sub experiment
    last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # move to position
    apm.add_action(
        {
            "action_server": MOTOR_server,
            "action_name": "move",
            "action_params": {
                "d_mm": [apm.pars.x_mm, apm.pars.y_mm],
                "axis": ["x", "y"],
                "mode": MoveModes.relative,
                "transformation": TransformationModes.platexy,
            },
            #            "from_global_params": {"_platexy": "d_mm"},
            "start_condition": ActionStartCondition.wait_for_all,
        }
    )

    return apm.action_list  # returns complete action list to orch


def UVIS_sub_spectrometer_T(
    experiment: Experiment,
    experiment_version: int = 1,
    toggle_illum_time: Optional[float] = -1,
    spec_n_avg: Optional[int] = 1,
    spec_int_time: Optional[int] = 35,
    comment: Optional[str] = "",
):
    """last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # get sample for gamry
    apm.add_action(
        {
            "action_server": PAL_server,
            "action_name": "archive_custom_query_sample",
            "action_params": {
                "custom": "cell1_we",
            },
            "to_global_params": [
                "_fast_samples_in"
            ],  # save new liquid_sample_no of eche cell to globals
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        }
    )

    # setup spectrometer data collection
    apm.add_action(
        {
            "action_server": SPEC_T_server,
            "action_name": "acquire_spec",
            "action_params": {
                "int_time": apm.pars.spec_int_time,
                #                "n_avg": apm.pars.spec_n_avg,
                #                "duration": apm.pars.toggle_illum_time,
            },
            "from_global_params": {"_fast_samples_in": "fast_samples_in"},
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "process_finish": False,
            "process_contrib": [
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        },
    )

    return apm.action_list  # returns complete action list to orch


def UVIS_sub_spectrometer_R(
    experiment: Experiment,
    experiment_version: int = 1,
    toggle_illum_time: Optional[float] = -1,
    spec_n_avg: Optional[int] = 1,
    spec_int_time: Optional[int] = 35,
    comment: Optional[str] = "",
):
    """last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # get sample for gamry
    apm.add_action(
        {
            "action_server": PAL_server,
            "action_name": "archive_custom_query_sample",
            "action_params": {
                "custom": "cell1_we",
            },
            "to_global_params": [
                "_fast_samples_in"
            ],  # save new liquid_sample_no of eche cell to globals
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        }
    )

    # setup spectrometer data collection
    apm.add_action(
        {
            "action_server": SPEC_R_server,
            "action_name": "acquire_spec",
            "action_params": {
                "int_time": apm.pars.spec_int_time,
                #                "n_avg": apm.pars.spec_n_avg,
                #                "duration": apm.pars.toggle_illum_time,
            },
            "from_global_params": {"_fast_samples_in": "fast_samples_in"},
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "process_finish": False,
            "process_contrib": [
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        },
    )

    return apm.action_list  # returns complete action list to orch
