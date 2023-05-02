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
    "UVIS_calc_abs",
]


from typing import Optional
from socket import gethostname

from helaocore.models.sample import SolidSample
from helaocore.models.machine import MachineModel as MM
from helaocore.models.process_contrib import ProcessContrib
from helaocore.models.run_use import RunUse


from helao.helpers.premodels import Experiment, ActionPlanMaker
from helao.drivers.motion.enum import MoveModes, TransformationModes
from helao.drivers.io.enum import TriggerType
from helao.drivers.spec.enum import SpecType


EXPERIMENTS = __all__

MOTOR_server = MM(server_name="MOTOR", machine_name=gethostname().lower()).as_dict()
IO_server = MM(server_name="IO", machine_name=gethostname().lower()).as_dict()
SPEC_T_server = MM(server_name="SPEC_T", machine_name=gethostname().lower()).as_dict()
SPEC_R_server = MM(server_name="SPEC_R", machine_name=gethostname().lower()).as_dict()
ORCH_server = MM(server_name="ORCH", machine_name=gethostname().lower()).as_dict()
PAL_server = MM(server_name="PAL", machine_name=gethostname().lower()).as_dict()
CALC_server = MM(server_name="CALC", machine_name=gethostname().lower()).as_dict()

toggle_triggertype = TriggerType.fallingedge


def UVIS_sub_unloadall_customs(experiment: Experiment):
    """Clear samples from measurement position."""
    apm = ActionPlanMaker()
    apm.add(PAL_server, "archive_custom_unloadall", {"destroy_liquid": True})
    return apm.action_list


def UVIS_sub_load_solid(
    experiment: Experiment,
    experiment_version: int = 1,
    solid_custom_position: str = "cell1_we",
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
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
    solid_custom_position: str = "cell1_we",
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
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
        to_globalexp_params=[
            "_platexy"
        ],  # save new liquid_sample_no of cell to globals
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
        from_globalexp_params={"_platexy": "d_mm"},
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
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(
        MOTOR_server,
        "solid_get_samples_xy",
        {
            "plate_id": apm.pars.solid_plate_id,
            "sample_no": apm.pars.solid_sample_no,
        },
        to_globalexp_params=[
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
        from_globalexp_params={"_platexy": "d_mm"},
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
    spec_type: SpecType = "T",
    spec_n_avg: int = 1,
    spec_int_time_ms: int = 10,
    duration_sec: float = -1,
    toggle_source: str = "doric_wled",  # this could be a shutter
    toggle_is_shutter: bool = False,
    illumination_wavelength: float = -1,
    illumination_intensity: float = -1,
    illumination_intensity_date: str = "n/a",
    illumination_side: str = "front",
    reference_mode: str = "internal",
    technique_name: str = "T_UVVIS",
    run_use: RunUse = "data",
    comment: str = "",
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # query loaded sample in cell1_we position
    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {"custom": "cell1_we"},
        to_globalexp_params=["_fast_samples_in"],
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
    if apm.pars.toggle_is_shutter:
        apm.add(ORCH_server, "wait", {"waittime": 1})

    # setup spectrometer data collection
    apm.add(
        SPEC_T_server if apm.pars.spec_type == SpecType.T else SPEC_R_server,
        "acquire_spec_adv",
        {
            "int_time_ms": apm.pars.spec_int_time_ms,
            "n_avg": apm.pars.spec_n_avg,
            "duration_sec": apm.pars.duration_sec,
        },
        from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
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
            "on": True if apm.pars.toggle_is_shutter else False,
        },
    )

    if apm.pars.reference_mode == "blank" and apm.pars.run_use == "ref_light":
        apm.add(
            ORCH_server,
            "interrupt",
            {"reason": "Reference measurement complete, load sample library."},
        )
        apm.add(ORCH_server, "wait", {"waittime": 1})

    return apm.action_list  # returns complete action list to orch


def UVIS_sub_setup_ref(
    experiment: Experiment,
    experiment_version: int = 1,
    reference_mode: str = "internal",
    solid_custom_position: str = "cell1_we",
    solid_plate_id: int = 1,
    solid_sample_no: int = 2,
    specref_code: int = 1,
):
    """Determine initial and final reference measurements and move to position."""
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    if apm.pars.reference_mode == "internal":
        apm.add(
            MOTOR_server,
            "solid_get_nearest_specref",
            {
                "plate_id": apm.pars.solid_plate_id,
                "sample_no": apm.pars.solid_sample_no,
                "specref_code": apm.pars.specref_code,
            },
            to_globalexp_params=["_refno", "_refxy"],
        )
        apm.add(
            PAL_server,
            "archive_custom_load_solid",
            {
                "custom": apm.pars.solid_custom_position,
                "plate_id": apm.pars.solid_plate_id,
            },
            from_globalexp_params={"_refno": "sample_no"},
        )
    elif apm.pars.reference_mode == "builtin":
        apm.add(
            MOTOR_server,
            "solid_get_builtin_specref",
            {},
            to_globalexp_params=["_refxy"],
        )
        apm.add(
            PAL_server,
            "archive_custom_load_solid",
            {
                "custom": apm.pars.solid_custom_position,
                "sample_no": apm.pars.solid_sample_no,
                "plate_id": apm.pars.solid_plate_id,
            },
        )
    elif apm.pars.reference_mode == "blank":
        apm.add(
            ORCH_server,
            "interrupt",
            {"reason": "Load blank substrate for reference measurement."},
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
            to_globalexp_params={"_platexy": "_refxy"},
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
        from_globalexp_params={"_refxy": "d_mm"},
    )
    return apm.action_list  # returns complete action list to orch


def UVIS_calc_abs(
    experiment: Experiment,
    experiment_version: int = 2,
    ev_parts: list = [1.5, 2.0, 2.5, 3.0],
    bin_width: int = 3,
    window_length: int = 45,
    poly_order: int = 4,
    lower_wl: float = 370.0,
    upper_wl: float = 1020.0,
    max_mthd_allowed: float = 1.2,
    max_limit: float = 0.99,
    min_mthd_allowed: float = -0.2,
    min_limit: float = 0.01,
):
    """Calculate absorption from sequence info."""
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(
        CALC_server,
        "calc_uvis_abs",
        {
            "ev_parts": apm.pars.ev_parts,
            "bin_width": apm.pars.bin_width,
            "window_length": apm.pars.window_length,
            "poly_order": apm.pars.poly_order,
            "lower_wl": apm.pars.lower_wl,
            "upper_wl": apm.pars.upper_wl,
            "max_mthd_allowed": apm.pars.max_mthd_allowed,
            "max_limit": apm.pars.max_limit,
            "min_mthd_allowed": apm.pars.min_mthd_allowed,
            "min_limit": apm.pars.min_limit,
        },
    )
    return apm.action_list  # returns complete action list to orch
