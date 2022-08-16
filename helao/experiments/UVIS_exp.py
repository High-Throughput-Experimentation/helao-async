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
    "UVIS_sub_relmove",
    "UVIS_sub_measure",
    "UVIS_sub_setup_ref",
]


from typing import Optional  # , List, Union
from socket import gethostname

from helaocore.models.sample import SolidSample  # , LiquidSample
from helaocore.models.machine import MachineModel as MM
from helaocore.models.process_contrib import ProcessContrib
from helaocore.models.run_use import RunUse
from helaocore.models.action_start_condition import ActionStartCondition


from helao.helpers.premodels import Experiment, ActionPlanMaker  # , Action
from helao.drivers.motion.enum import MoveModes, TransformationModes
from helao.drivers.io.enum import TriggerType
from helao.drivers.spec.enum import SpecType


EXPERIMENTS = __all__

MOTOR_server = MM(server_name="MOTOR", machine_name=gethostname()).json_dict()
IO_server = MM(server_name="IO", machine_name=gethostname()).json_dict()
SPEC_T_server = MM(server_name="SPEC_T", machine_name=gethostname()).json_dict()
SPEC_R_server = MM(server_name="SPEC_R", machine_name=gethostname()).json_dict()
ORCH_server = MM(server_name="ORCH", machine_name=gethostname()).json_dict()
PAL_server = MM(server_name="PAL", machine_name=gethostname()).json_dict()

toggle_triggertype = TriggerType.fallingedge


def UVIS_sub_unloadall_customs(experiment: Experiment):
    """Clear samples from measurement position."""
    apm = ActionPlanMaker()
    apm.add(PAL_server, "archive_custom_unloadall", {"destroy_liquid": True})
    return apm.action_list


def UVIS_sub_load_solid(
    experiment: Experiment,
    experiment_version: int = 1,
    solid_custom_position: Optional[str] = "cell1_we",
    solid_plate_id: Optional[int] = 4534,
    solid_sample_no: Optional[int] = 1,
):
    """Load solid sample onto measurement position."""
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(
        PAL_server,
        "archive_custom_load",
        {
            "custom": apm.pars.solid_custom_position,
            "load_sample_in": SolidSample(
                sample_no=apm.pars.solid_sample_no,
                plate_id=apm.pars.solid_plate_id,
                machine_name="legacy",
            ),
        },
    )
    return apm.action_list  # returns complete action list to orch


def UVIS_sub_startup(
    experiment: Experiment,
    experiment_version: int = 2,
    solid_custom_position: Optional[str] = "cell1_we",
    solid_plate_id: Optional[int] = 4534,
    solid_sample_no: Optional[int] = 1,
):

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add_action_list(UVIS_sub_unloadall_customs(experiment=experiment))

    # load new requested solid samples
    apm.add(
        PAL_server,
        "archive_custom_load",
        {
            "custom": apm.pars.solid_custom_position,
            "load_sample_in": SolidSample(
                sample_no=apm.pars.solid_sample_no,
                plate_id=apm.pars.solid_plate_id,
                machine_name="legacy",
            ),
        },
    )
    # get sample plate coordinates
    apm.add(
        MOTOR_server,
        "solid_get_samples_xy",
        {
            "plate_id": apm.pars.solid_plate_id,
            "sample_no": apm.pars.solid_sample_no,
        },
        to_global_params=["_platexy"],  # save new liquid_sample_no of cell to globals
    )
    # move to position
    apm.add(
        MOTOR_server,
        "move",
        {
            "axis": ["x", "y"],
            "mode": MoveModes.absolute,
            "transformation": TransformationModes.platexy,
        },
        from_global_params={"_platexy": "d_mm"},
    )
    return apm.action_list  # returns complete action list to orch


def UVIS_sub_shutdown(experiment: Experiment):
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
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(
        MOTOR_server,
        "solid_get_samples_xy",
        {
            "plate_id": apm.pars.solid_plate_id,
            "sample_no": apm.pars.solid_sample_no,
        },
        to_global_params=[
            "_platexy"
        ],  # save new liquid_sample_no of eche cell to globals
    )
    # move to position
    apm.add(
        MOTOR_server,
        "move",
        {
            "axis": ["x", "y"],
            "mode": MoveModes.absolute,
            "transformation": TransformationModes.platexy,
        },
        from_global_params={"_platexy": "d_mm"},
    )
    return apm.action_list  # returns complete action list to orch


def UVIS_sub_relmove(
    experiment: Experiment,
    experiment_version: int = 1,
    offset_x_mm: float = 1.0,
    offset_y_mm: float = 1.0,
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(
        MOTOR_server,
        "move",
        {
            "d_mm": [apm.pars.offset_x_mm, apm.pars.offset_y_mm],
            "axis": ["x", "y"],
            "mode": MoveModes.relative,
            "transformation": TransformationModes.platexy,
        },
    )
    return apm.action_list  # returns complete action list to orch


def UVIS_sub_measure(
    experiment: Experiment,
    experiment_version: int = 1,
    spec_type: Optional[SpecType] = "T",
    spec_n_avg: Optional[int] = 1,
    spec_int_time_ms: Optional[int] = 35,
    duration_sec: Optional[float] = -1,
    toggle_source: Optional[str] = "doric_wled",  # this could be a shutter
    toggle_is_shutter: Optional[bool] = False,
    illumination_wavelength: Optional[float] = -1,
    illumination_intensity: Optional[float] = -1,
    illumination_intensity_date: Optional[str] = "n/a",
    illumination_side: Optional[str] = "front",
    technique_name: Optional[str] = "T_UVVIS",
    run_use: Optional[RunUse] = "data",
    comment: Optional[str] = "",
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # query loaded sample in cell1_we position
    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {"custom": "cell1_we"},
        to_global_params=["_fast_samples_in"],
    )

    # set illumination state before measurement
    apm.add(
        IO_server,
        "set_digital_out",
        {
            "do_item": apm.pars.toggle_source,
            "on": False if apm.pars.run_use == "ref_dark" else True,
        },
    )

    # wait for 1 second for shutter to actuate
    if bool(apm.pars.toggle_is_shutter):
        apm.add(ORCH_server, "wait", {"waittime": 1})

    # setup spectrometer data collection
    apm.add(
        SPEC_T_server if apm.pars.spec_type == SpecType.T else SPEC_R_server,
        "acquire_spec",
        {
            "int_time_ms": apm.pars.spec_int_time_ms,
            "n_avg": apm.pars.spec_n_avg,
            "duration_sec": apm.pars.duration_sec,
        },
        from_global_params={"_fast_samples_in": "fast_samples_in"},
        run_use=apm.pars.run_use,
        technique_name=apm.pars.technique_name,
        process_finish=True,
        process_contrib=[
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
            ProcessContrib.run_use,
        ],
    )

    # set illumination state after measurement
    apm.add(
        IO_server,
        "set_digital_out",
        {
            "do_item": apm.pars.toggle_source,
            "on": True if bool(apm.pars.toggle_is_shutter) else False,
        },
    )

    return apm.action_list  # returns complete action list to orch


def UVIS_sub_setup_ref(
    experiment: Experiment,
    experiment_version: int = 1,
    reference_sample_type: str = "internal",
    solid_custom_position: Optional[str] = "cell1_we",
    solid_plate_id: int = 1,
    solid_sample_no: int = 2,
    specref_code: int = 1,
):
    """Determine initial and final reference measurements and move to position."""
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    if apm.pars.reference_sample_type == "internal":
        apm.add(
            MOTOR_server,
            "solid_get_nearest_specref",
            {
                "plate_id": apm.pars.solid_plate_id,
                "sample_no": apm.pars.solid_sample_no,
                "specref_code": apm.pars.specref_code
            },
            to_global_params=["_refno", "_refxy"]
        )
        apm.add(
            PAL_server,
            "archive_custom_load_solid",
            {
                "custom": apm.pars.solid_custom_position,
                "plate_id": apm.pars.solid_plate_id,
            },
            from_global_params={"_refno": "sample_no"}
        )
    elif apm.pars.reference_sample_type == "builtin":
        apm.add(
            MOTOR_server,
            "solid_get_builtin_specref", {},
            to_global_params=["_refno", "_refxy"]
        )
        apm.add(
            PAL_server,
            "archive_custom_load_solid",
            {
                "custom": apm.pars.solid_custom_position,
                "plate_id": apm.pars.solid_plate_id,
            },
            from_global_params={"_refno": "sample_no"}
        )
    elif apm.pars.reference_sample_type == "blank":
        apm.add(
            ORCH_server,
            "interrupt"
        )
        apm.add(
            PAL_server,
            "archive_custom_load",
            {
                "custom": apm.pars.solid_custom_position,
                "load_sample_in": SolidSample(
                    sample_no=apm.pars.solid_sample_no,
                    plate_id=apm.pars.solid_plate_id,
                    machine_name="legacy",
                ),
            },
        )
        apm.add(
            MOTOR_server,
            "solid_get_samples_xy",
            {
                "plate_id": apm.pars.solid_plate_id,
                "sample_no": apm.pars.solid_sample_no,
            },
            to_global_params={"_platexy": "_refxy"},
        )
    # move to position
    apm.add(
        MOTOR_server,
        "move",
        {
            "axis": ["x", "y"],
            "mode": MoveModes.absolute,
            "transformation": TransformationModes.platexy,
        },
        from_global_params={"_refxy": "d_mm"},
    )
    return apm.action_list  # returns complete action list to orch