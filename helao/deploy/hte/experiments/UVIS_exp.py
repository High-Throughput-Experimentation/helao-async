"""Experiment library for UV-Vis transmission/reflection measurements.

Each `UVIS_sub_*` helper returns a list of planned actions assembled by an
`ActionPlanMaker` that the orchestrator can dispatch. The action graph drives
the SPEC_T/SPEC_R spectrometer servers, the motion and IO servers, the PAL
sample archive, and the CAM/PDU/CALC/ANA helpers.
"""

EXPERIMENTS = [
    "UVIS_analysis_dry",
    "UVIS_calc_abs",
    "UVIS_measure_references",
    "UVIS_sub_load_solid",
    "UVIS_sub_measure",
    "UVIS_sub_movetosample",
    "UVIS_sub_relmove",
    "UVIS_sub_setup_ref",
    "UVIS_sub_shutdown",
    "UVIS_sub_shutoff_lamp",
    "UVIS_sub_startup",
    "UVIS_sub_unloadall_customs",
]


from socket import gethostname

from helao.core.models.action_start_condition import ActionStartCondition
from helao.core.models.machine import MachineModel as MM
from helao.core.models.process_contrib import ProcessContrib
from helao.core.models.run_use import RunUse
from helao.core.models.sample import SolidSample
from helao.deploy.hte.drivers.io.enum import TriggerType
from helao.deploy.hte.drivers.motion.enum import MoveModes, TransformationModes
from helao.deploy.hte.drivers.spec.enum import SpecType
from helao.helpers.lib_decorators import experiment
from helao.helpers.premodels import ActionPlanMaker

MOTOR_server = MM(server_name="MOTOR", machine_name=gethostname().lower()).as_dict()
IO_server = MM(server_name="IO", machine_name=gethostname().lower()).as_dict()
SPEC_T_server = MM(server_name="SPEC_T", machine_name=gethostname().lower()).as_dict()
SPEC_R_server = MM(server_name="SPEC_R", machine_name=gethostname().lower()).as_dict()
ORCH_server = MM(server_name="ORCH", machine_name=gethostname().lower()).as_dict()
PAL_server = MM(server_name="PAL", machine_name=gethostname().lower()).as_dict()
SAMPLE_server = MM(server_name="SAMPLE", machine_name=gethostname().lower()).as_dict()
CALC_server = MM(server_name="CALC", machine_name=gethostname().lower()).as_dict()
ANA_server = MM(server_name="ANA", machine_name=gethostname().lower()).as_dict()
CAM_server = MM(server_name="CAM", machine_name=gethostname().lower()).as_dict()
PDU_server = MM(server_name="PDU", machine_name=gethostname().lower()).as_dict()

toggle_triggertype = TriggerType.fallingedge


@experiment(version=1)
def UVIS_sub_unloadall_customs() -> list:
    """Unload every sample from every custom position via PAL.

    Returns:
        List with a single PAL ``archive_custom_unloadall`` action.
    """
    apm = ActionPlanMaker()
    apm.add(
        SAMPLE_server,
        "archive_custom_unloadall",
        {"destroy_liquid": True},
        start_condition=ActionStartCondition.no_wait,
    )
    return apm.planned_actions


@experiment(version=1)
def UVIS_sub_load_solid(
    solid_custom_position: str = "cell1_we",
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
) -> list:
    """Load a solid sample into the named PAL custom position.

    Args:
        solid_custom_position: PAL custom position name.
        solid_plate_id: Plate id of the solid sample.
        solid_sample_no: Sample number on the plate.

    Returns:
        List with a single PAL ``archive_custom_load`` action.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(
        SAMPLE_server,
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


@experiment(version=2)
def UVIS_sub_startup(
    solid_custom_position: str = "cell1_we",
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
) -> list:
    """Start-up: unload existing samples, load the requested solid, move to XY.

    Calls :func:`UVIS_sub_unloadall_customs`, then loads the solid sample,
    queries the plate XY coordinates and moves the motor stage there.

    Args:
        solid_custom_position: PAL custom position name.
        solid_plate_id: Plate id of the solid sample.
        solid_sample_no: Sample number on the plate.

    Returns:
        List of PAL, MOTOR query, and motion actions composing the start-up.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add_actions(UVIS_sub_unloadall_customs())

    # load new requested solid samples
    apm.add(
        SAMPLE_server,
        "archive_custom_load",
        {
            "custom": solid_custom_position,
            "load_sample_in": SolidSample(
                sample_no=solid_sample_no,
                plate_id=solid_plate_id,
                machine_name="legacy",
            ),
        },
        start_condition=ActionStartCondition.wait_for_server,
    )
    # get sample plate coordinates
    apm.add(
        MOTOR_server,
        "solid_get_samples_xy",
        {
            "plate_id": solid_plate_id,
            "sample_no": solid_sample_no,
        },
        start_condition=ActionStartCondition.no_wait,
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
        start_condition=ActionStartCondition.wait_for_previous,
        from_global_act_params={"_platexy": "d_mm"},
    )
    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def UVIS_sub_shutdown(toggle_source: str = "lamp_shutter") -> list:
    """Shutdown: unload custom positions and switch off the lamp shutter line.

    Args:
        toggle_source: IO digital-out name driven low to close the shutter.

    Returns:
        List of PAL unload and IO ``set_digital_out`` actions.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    # unload all samples from custom positions
    apm.add_actions(UVIS_sub_unloadall_customs())
    apm.add(
        IO_server,
        "set_digital_out",
        {
            "do_item": toggle_source,
            "on": False,
        },
        start_condition=ActionStartCondition.no_wait,
    )
    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def UVIS_sub_movetosample(
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
) -> list:
    """Query a plate's XY for the given sample and move the motor stage to it.

    Args:
        solid_plate_id: Plate id of the solid sample.
        solid_sample_no: Sample number on the plate.

    Returns:
        List of MOTOR ``solid_get_samples_xy`` and ``move`` actions.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(
        MOTOR_server,
        "solid_get_samples_xy",
        {
            "plate_id": solid_plate_id,
            "sample_no": solid_sample_no,
        },
        start_condition=ActionStartCondition.no_wait,
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
        start_condition=ActionStartCondition.wait_for_previous,
        from_global_act_params={"_platexy": "d_mm"},
    )
    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def UVIS_sub_relmove(
    offset_x_mm: float = 1.0,
    offset_y_mm: float = 1.0,
) -> list:
    """Issue a relative platexy move on the MOTOR server.

    Args:
        offset_x_mm: Relative X offset in millimetres.
        offset_y_mm: Relative Y offset in millimetres.

    Returns:
        List with a single MOTOR ``move`` action in relative platexy mode.
    """
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


@experiment(version=2)
def UVIS_sub_measure(
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
) -> list:
    """Drive a single spectrometer acquisition with illumination/shutter control.

    Queries the loaded sample, toggles the illumination/shutter digital line
    according to ``run_use``/``spec_type``, optionally captures a webcam image,
    and runs the chosen SPEC_T/SPEC_R ``acquire_spec_adv`` action. For
    transmission measurements the illumination is reset after the acquisition.
    A ``reference_mode == 'blank'`` light reference also issues an orchestrator
    interrupt to prompt the operator to load the sample library.

    Args:
        spec_type: Spectrometer family (T or R).
        spec_n_avg: Number of spectra averaged per acquisition.
        spec_int_time_ms: Integration time in milliseconds.
        duration_sec: Total acquisition duration; ``-1`` uses driver defaults.
        toggle_source: IO digital-out name controlling the lamp/shutter.
        toggle_is_shutter: True if ``toggle_source`` actuates a shutter.
        illumination_wavelength: Recorded illumination wavelength (nm).
        illumination_intensity: Recorded illumination intensity (mW).
        illumination_intensity_date: Calibration date string for the intensity.
        illumination_side: Side label ("front"/"back").
        reference_mode: ``"internal"``, ``"builtin"``, or ``"blank"``.
        technique_name: Technique label stored in the action record.
        run_use: ``RunUse`` enum value (data, ref_light, ref_dark, ...).
        acquire_image: If True, capture a webcam image alongside the spectrum.
        comment: Free-form comment.

    Returns:
        List of PAL/IO/ORCH/CAM/SPEC actions producing the spectrum.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # query loaded sample in cell1_we position
    apm.add(
        SAMPLE_server,
        "archive_custom_query_sample",
        {"custom": "cell1_we"},
        start_condition=ActionStartCondition.no_wait,
        to_global_params=["_fast_samples_in"],
    )

    # set illumination state before measurement
    apm.add(
        IO_server,
        "set_digital_out",
        {
            "do_item": toggle_source,
            "on": (
                False
                if (run_use == "ref_dark" and spec_type == SpecType.T)
                or run_use == "shutter_closed"
                else True
            ),
        },
        start_condition=ActionStartCondition.no_wait,
    )

    # wait for 1 second for shutter to actuate
    if toggle_is_shutter:
        apm.add(
            ORCH_server,
            "wait",
            {"waittime": 1},
            start_condition=ActionStartCondition.wait_for_previous,
        )

    # take webcam image
    if acquire_image:
        apm.add(
            CAM_server,
            "acquire_image",
            {"duration": 0},
            start_condition=ActionStartCondition.wait_for_previous,
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


@experiment(version=1)
def UVIS_sub_setup_ref(
    reference_mode: str = "internal",
    solid_custom_position: str = "cell1_we",
    solid_plate_id: int = 1,
    solid_sample_no: int = 2,
    specref_code: int = 1,
    ref_position_name: str = "builtin_ref_motorxy",
) -> list:
    """Pick a reference target and move the stage to it.

    Branches on ``reference_mode``:

    * ``"internal"`` -- ask MOTOR for the nearest plate-borne specref sample
      and load it via PAL.
    * ``"builtin"`` -- look up the named builtin reference position on MOTOR
      and load the supplied sample number via PAL.
    * ``"blank"`` -- request an operator interrupt, load the supplied blank
      sample, and fetch its XY.

    After the reference is located, a MOTOR ``move`` action positions the
    stage using either platexy (internal/blank) or motorxy (builtin).

    Args:
        reference_mode: One of ``"internal"``, ``"builtin"``, ``"blank"``.
        solid_custom_position: PAL custom position used to host the reference.
        solid_plate_id: Plate id used to look up the reference sample.
        solid_sample_no: Sample number for blank/builtin modes.
        specref_code: Spec-ref code passed to ``solid_get_nearest_specref``.
        ref_position_name: Name of the builtin reference XY entry.

    Returns:
        List of MOTOR/PAL/ORCH actions performing the reference setup.
    """
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
            start_condition=ActionStartCondition.no_wait,
            to_global_params=["_refno", "_refxy"],
        )
        apm.add(
            SAMPLE_server,
            "archive_custom_load_solid",
            {
                "custom": solid_custom_position,
                "plate_id": solid_plate_id,
            },
            start_condition=ActionStartCondition.no_wait,
            from_global_act_params={"_refno": "sample_no"},
        )
    elif reference_mode == "builtin":
        apm.add(
            MOTOR_server,
            "solid_get_builtin_specref",
            {"ref_position_name": ref_position_name},
            start_condition=ActionStartCondition.wait_for_previous,
            to_global_params=["_refxy"],
        )
        apm.add(
            SAMPLE_server,
            "archive_custom_load_solid",
            {
                "custom": solid_custom_position,
                "sample_no": solid_sample_no,
                "plate_id": solid_plate_id,
            },
            start_condition=ActionStartCondition.no_wait,
        )
    elif reference_mode == "blank":
        apm.add(
            ORCH_server,
            "interrupt",
            {"reason": "Load blank substrate for reference measurement."},
        )
        apm.add(
            SAMPLE_server,
            "archive_custom_load",
            {
                "custom": solid_custom_position,
                "load_sample_in": SolidSample(
                    sample_no=solid_sample_no,
                    plate_id=solid_plate_id,
                    machine_name="legacy",
                ),
            },
            start_condition=ActionStartCondition.no_wait,
        )
        apm.add(
            MOTOR_server,
            "solid_get_samples_xy",
            {
                "plate_id": solid_plate_id,
                "sample_no": solid_sample_no,
            },
            to_global_params={"_platexy": "_refxy"},
            start_condition=ActionStartCondition.no_wait,
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
        start_condition=ActionStartCondition.wait_for_previous,
        from_global_act_params={"_refxy": "d_mm"},
    )
    return apm.planned_actions  # returns complete action list to orch


@experiment(version=2)
def UVIS_calc_abs(
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
) -> list:
    """Run the CALC server's UV-Vis absorption calculator.

    Args:
        ev_parts: Energy partition points (eV) for the calculator.
        bin_width: Spectral bin width (samples).
        window_length: Savitzky-Golay window length.
        poly_order: Savitzky-Golay polynomial order.
        lower_wl: Lower wavelength cutoff (nm).
        upper_wl: Upper wavelength cutoff (nm).
        max_mthd_allowed: Upper limit for the method-based detection.
        max_limit: Upper acceptance threshold.
        min_mthd_allowed: Lower limit for the method-based detection.
        min_limit: Lower acceptance threshold.

    Returns:
        List with a single CALC ``calc_uvis_abs`` action.
    """
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


@experiment(version=2)
def UVIS_analysis_dry(
    sequence_uuid: str = "",
    plate_id: int = 0,
    recent: bool = True,
    params: dict = {},
) -> list:
    """Run the ANA server's dry UV-Vis analysis for a sequence/plate.

    Args:
        sequence_uuid: Sequence UUID to analyse.
        plate_id: Plate id to filter on.
        recent: If True, restrict the analysis to recent runs.
        params: Free-form parameter dict forwarded to the analyzer.

    Returns:
        List with a single ANA ``analyze_dryuvis`` action.
    """
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


@experiment(version=2)
def UVIS_measure_references(
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
    """Acquire dark, detector-background, and light reference spectra.

    Unloads any prior samples, moves to the builtin black target, captures a
    shutter-closed background and a dark reference, moves to the builtin
    white target, and captures a light reference.

    Args:
        plate_id: Plate id used for builtin reference lookups.
        custom_position: PAL custom position for the reference solid.
        spec_n_avg: Number of spectra averaged per acquisition.
        spec_int_time_ms: Integration time in milliseconds.
        duration_sec: Acquisition duration (s); ``-1`` uses driver defaults.
        spec_type: Spectrometer family (T or R).
        specref_code: Spec-ref code passed to MOTOR.
        led_type: Illumination side label.
        led_date: Calibration date string for the LED intensities.
        led_names: Names of the LEDs/lamps available.
        led_wavelengths_nm: Per-LED wavelength (nm) list.
        led_intensities_mw: Per-LED intensity (mW) list.
        toggle_is_shutter: True if the first ``led_names`` entry is a shutter.
        technique_name: Technique label stored in the action records.

    Returns:
        List of planned actions producing the reference spectra.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    # 0) unregister samples from measurement location
    apm.add_actions(UVIS_sub_unloadall_customs())
    # 1) move to zero reflectance (black) reference
    apm.add_actions(
        UVIS_sub_setup_ref(
            reference_mode="builtin",
            solid_custom_position=custom_position,
            solid_plate_id=plate_id,
            solid_sample_no=0,
            specref_code=specref_code,
            ref_position_name="builtin_black_motorxy",
        )
    )
    # 2a) measure detector background (shutter closed)
    apm.add_actions(
        UVIS_sub_measure(
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
            run_use=RunUse.shutter_closed,
            reference_mode="builtin",
        )
    )
    # 2b) measure dark reference
    apm.add_actions(
        UVIS_sub_measure(
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


@experiment(version=1)
def UVIS_sub_shutoff_lamp(outlet_number: int = 1) -> list:
    """Switch a PDU outlet off (intended for the UV-Vis lamp).

    Args:
        outlet_number: PDU outlet index.

    Returns:
        List with a single PDU ``switch_outlet`` action.
    """
    apm = ActionPlanMaker()
    apm.add(
        PDU_server,
        "switch_outlet",
        {"outlet_number": outlet_number, "on": False},
        start_condition=ActionStartCondition.no_wait,
    )
    return apm.planned_actions
