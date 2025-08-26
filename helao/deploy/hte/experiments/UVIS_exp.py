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
    "UVIS_analysis_dry",
    "UVIS_measure_references",
]


from socket import gethostname

from helao.core.models.sample import SolidSample
from helao.core.models.machine import MachineModel as MM
from helao.core.models.process_contrib import ProcessContrib
from helao.core.models.run_use import RunUse
from helao.core.models.action_start_condition import ActionStartCondition


from helao.helpers.premodels import Experiment, ActionPlanMaker
from helao.deploy.hte.drivers.motion.enum import MoveModes, TransformationModes
from helao.deploy.hte.drivers.io.enum import TriggerType
from helao.deploy.hte.drivers.spec.enum import SpecType


EXPERIMENTS = __all__

MOTOR_server = MM(server_name="MOTOR", machine_name=gethostname().lower()).as_dict()
IO_server = MM(server_name="IO", machine_name=gethostname().lower()).as_dict()
SPEC_T_server = MM(server_name="SPEC_T", machine_name=gethostname().lower()).as_dict()
SPEC_R_server = MM(server_name="SPEC_R", machine_name=gethostname().lower()).as_dict()
ORCH_server = MM(server_name="ORCH", machine_name=gethostname().lower()).as_dict()
PAL_server = MM(server_name="PAL", machine_name=gethostname().lower()).as_dict()
CALC_server = MM(server_name="CALC", machine_name=gethostname().lower()).as_dict()
ANA_server = MM(server_name="ANA", machine_name=gethostname().lower()).as_dict()
CAM_server = MM(server_name="CAM", machine_name=gethostname().lower()).as_dict()

toggle_triggertype = TriggerType.fallingedge


def UVIS_sub_unloadall_customs(experiment: Experiment):
    """Clear samples from measurement position."""
    apm = ActionPlanMaker()
    apm.add(PAL_server, "archive_custom_unloadall", {"destroy_liquid": True})
    return apm.planned_actions


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
            "custom": solid_custom_position,
            "load_sample_in": SolidSample(
                sample_no=solid_sample_no,
                plate_id=solid_plate_id,
                machine_name="legacy",
            ),
        },
    )
    return apm.planned_actions  # returns complete action list to orch


def UVIS_sub_startup(
    experiment: Experiment,
    experiment_version: int = 2,
    solid_custom_position: str = "cell1_we",
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add_actions(UVIS_sub_unloadall_customs(experiment=experiment))

    # load new requested solid samples
    apm.add(
        PAL_server,
        "archive_custom_load",
        {
            "custom": solid_custom_position,
            "load_sample_in": SolidSample(
                sample_no=solid_sample_no,
                plate_id=solid_plate_id,
                machine_name="legacy",
            ),
        },
    )
    # get sample plate coordinates
    apm.add(
        MOTOR_server,
        "solid_get_samples_xy",
        {
            "plate_id": solid_plate_id,
            "sample_no": solid_sample_no,
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
        from_global_act_params={"_platexy": "d_mm"},
    )
    return apm.planned_actions  # returns complete action list to orch


def UVIS_sub_shutdown(experiment: Experiment):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    # unload all samples from custom positions
    apm.add_actions(UVIS_sub_unloadall_customs(experiment=experiment))
    return apm.planned_actions  # returns complete action list to orch


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
            "plate_id": solid_plate_id,
            "sample_no": solid_sample_no,
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
        from_global_act_params={"_platexy": "d_mm"},
    )
    return apm.planned_actions  # returns complete action list to orch


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
            "d_mm": [offset_x_mm, offset_y_mm],
            "axis": ["x", "y"],
            "mode": MoveModes.relative,
            "transformation": TransformationModes.platexy,
        },
    )
    return apm.planned_actions  # returns complete action list to orch


def UVIS_sub_measure(
    experiment: Experiment,
    experiment_version: int = 2,
    spec_type: SpecType = SpecType.T,
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
    run_use: RunUse = RunUse.data,
    acquire_image: bool = False,
    comment: str = "",
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # query loaded sample in cell1_we position
    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {"custom": "cell1_we"},
        to_global_params=["_fast_samples_in"],
    )

    if spec_type == SpecType.T:
        # set illumination state before measurement
        apm.add(
            IO_server,
            "set_digital_out",
            {
                "do_item": toggle_source,
                "on": False if run_use == "ref_dark" and spec_type == SpecType.T else True,
            },
        )

        # wait for 1 second for shutter to actuate
        if toggle_is_shutter:
            apm.add(ORCH_server, "wait", {"waittime": 1})

    # take webcam image
    if acquire_image:
        apm.add(
            CAM_server,
            "acquire_image",
            {"duration": 0},
            from_global_act_params={"_fast_samples_in": "fast_samples_in"},
            run_use=run_use,
            technique_name=technique_name,
            process_finish=False,
            process_contrib=[
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.run_use,
            ],
        )

    # setup spectrometer data collection
    apm.add(
        SPEC_T_server if spec_type == SpecType.T else SPEC_R_server,
        "acquire_spec_adv",
        {
            "int_time_ms": spec_int_time_ms,
            "n_avg": spec_n_avg,
            "duration_sec": duration_sec,
        },
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        run_use=run_use,
        technique_name=technique_name,
        start_condition=ActionStartCondition.no_wait,
        process_finish=True,
        process_contrib=[
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
            ProcessContrib.run_use,
        ],
    )

    if spec_type == SpecType.T:
        # set illumination state after measurement
        apm.add(
            IO_server,
            "set_digital_out",
            {
                "do_item": toggle_source,
                "on": True if toggle_is_shutter else False,
            },
        )

    if reference_mode == "blank" and run_use == "ref_light":
        apm.add(
            ORCH_server,
            "interrupt",
            {"reason": "Reference measurement complete, load sample library."},
        )
        apm.add(ORCH_server, "wait", {"waittime": 1})

    return apm.planned_actions  # returns complete action list to orch


def UVIS_sub_setup_ref(
    experiment: Experiment,
    experiment_version: int = 1,
    reference_mode: str = "internal",
    solid_custom_position: str = "cell1_we",
    solid_plate_id: int = 1,
    solid_sample_no: int = 2,
    specref_code: int = 1,
    ref_position_name: str = "builtin_ref_motorxy",
):
    """Determine initial and final reference measurements and move to position."""
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    if reference_mode == "internal":
        apm.add(
            MOTOR_server,
            "solid_get_nearest_specref",
            {
                "plate_id": solid_plate_id,
                "sample_no": solid_sample_no,
                "specref_code": specref_code,
            },
            to_global_params=["_refno", "_refxy"],
        )
        apm.add(
            PAL_server,
            "archive_custom_load_solid",
            {
                "custom": solid_custom_position,
                "plate_id": solid_plate_id,
            },
            from_global_act_params={"_refno": "sample_no"},
        )
    elif reference_mode == "builtin":
        apm.add(
            MOTOR_server,
            "solid_get_builtin_specref",
            {"ref_position_name": ref_position_name},
            to_global_params=["_refxy"],
        )
        apm.add(
            PAL_server,
            "archive_custom_load_solid",
            {
                "custom": solid_custom_position,
                "sample_no": solid_sample_no,
                "plate_id": solid_plate_id,
            },
        )
    elif reference_mode == "blank":
        apm.add(
            ORCH_server,
            "interrupt",
            {"reason": "Load blank substrate for reference measurement."},
        )
        apm.add(
            PAL_server,
            "archive_custom_load",
            {
                "custom": solid_custom_position,
                "load_sample_in": SolidSample(
                    sample_no=solid_sample_no,
                    plate_id=solid_plate_id,
                    machine_name="legacy",
                ),
            },
        )
        apm.add(
            MOTOR_server,
            "solid_get_samples_xy",
            {
                "plate_id": solid_plate_id,
                "sample_no": solid_sample_no,
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
            "transformation": (
                TransformationModes.platexy
                if reference_mode != "builtin"
                else TransformationModes.motorxy
            ),
        },
        from_global_act_params={"_refxy": "d_mm"},
    )
    return apm.planned_actions  # returns complete action list to orch


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
            "ev_parts": ev_parts,
            "bin_width": bin_width,
            "window_length": window_length,
            "poly_order": poly_order,
            "lower_wl": lower_wl,
            "upper_wl": upper_wl,
            "max_mthd_allowed": max_mthd_allowed,
            "max_limit": max_limit,
            "min_mthd_allowed": min_mthd_allowed,
            "min_limit": min_limit,
        },
    )
    return apm.planned_actions  # returns complete action list to orch


def UVIS_analysis_dry(
    experiment: Experiment,
    experiment_version: int = 2,
    sequence_uuid: str = "",
    plate_id: int = 0,
    recent: bool = True,
    params: dict = {},
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(
        ANA_server,
        "analyze_dryuvis",
        {
            "sequence_uuid": sequence_uuid,
            "plate_id": plate_id,
            "recent": recent,
            "params": params,
        },
    )
    return apm.planned_actions


def UVIS_measure_references(
    experiment: Experiment,
    experiment_version: int = 1,
    plate_id: int = 1,
    custom_position: str = "cell1_we",
    spec_n_avg: int = 5,
    spec_int_time_ms: int = 300,
    duration_sec: float = -1,
    spec_type: SpecType = SpecType.R,
    specref_code: int = 1,
    led_type: str = "front",
    led_date: str = "n/a",
    led_names: list = ["xenon"],
    led_wavelengths_nm: list = [-1],
    led_intensities_mw: list = [-1],
    toggle_is_shutter: bool = True,
    technique_name: str = "R_UVVIS",
) -> list:
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    # 0) unregister samples from measurement location
    apm.add_actions(UVIS_sub_unloadall_customs(experiment=experiment))
    # 1) move to zero reflectance (black) reference
    apm.add_actions(
        UVIS_sub_setup_ref(
            experiment=experiment,
            reference_mode="builtin",
            solid_custom_position=custom_position,
            solid_plate_id=plate_id,
            solid_sample_no=0,
            specref_code=specref_code,
            ref_position_name="builtin_black_motorxy",
        )
    )
    # 2) measure dark reference
    apm.add_actions(
        UVIS_sub_measure(
            experiment=experiment,
            spec_type=spec_type,
            spec_int_time_ms=spec_int_time_ms,
            spec_n_avg=spec_n_avg,
            duration_sec=duration_sec,
            toggle_source=led_names[0],
            toggle_is_shutter=toggle_is_shutter,
            illumination_wavelength=led_wavelengths_nm[0],
            illumination_intensity=led_intensities_mw[0],
            illumination_intensity_date=led_date,
            illumination_side=led_type,
            technique_name=technique_name,
            run_use=RunUse.ref_dark,
            reference_mode="builtin",
        )
    )
    # 3) move to full reflectance (white) reference
    apm.add_actions(
        UVIS_sub_setup_ref(
            experiment=experiment,
            reference_mode="builtin",
            solid_custom_position=custom_position,
            solid_plate_id=plate_id,
            solid_sample_no=0,
            specref_code=specref_code,
            ref_position_name="builtin_ref_motorxy",
        )
    )
    # 3) measure light reference
    apm.add_actions(
        UVIS_sub_measure(
            experiment=experiment,
            spec_type=spec_type,
            spec_int_time_ms=spec_int_time_ms,
            spec_n_avg=spec_n_avg,
            duration_sec=duration_sec,
            toggle_source=led_names[0],
            toggle_is_shutter=toggle_is_shutter,
            illumination_wavelength=led_wavelengths_nm[0],
            illumination_intensity=led_intensities_mw[0],
            illumination_intensity_date=led_date,
            illumination_side=led_type,
            technique_name=technique_name,
            run_use=RunUse.ref_light,
            reference_mode="builtin",
        )
    )
    return apm.planned_actions
