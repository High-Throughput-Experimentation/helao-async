"""Experiment library for the ECHE station.

Defines sub-experiments that build action lists for an orchestrator. Each
function takes an ``Experiment`` and returns the list of actions to enqueue.
Action targets are referenced by ``server_key`` strings (e.g. ``PSTAT``,
``MOTOR``, ``IO``, ``PAL``, ``ORCH``).
"""

EXPERIMENTS = [
    "ECHE_sub_add_liquid",
    "ECHE_sub_CA",
    "ECHE_sub_CA_led",
    "ECHE_sub_CP",
    "ECHE_sub_CP_led",
    "ECHE_sub_CV",
    "ECHE_sub_CV_led",
    "ECHE_sub_load_solid",
    "ECHE_sub_movetosample",
    "ECHE_sub_OCV",
    "ECHE_sub_preCV",
    "ECHE_sub_rel_move",
    "ECHE_sub_shutdown",
    "ECHE_sub_startup",
    "ECHE_sub_unloadall_customs",
]


from socket import gethostname
from typing import Optional

from helao.core.models.action_start_condition import ActionStartCondition
from helao.core.models.echem_params import ref_offset, resolve_potential_versus
from helao.core.models.electrolyte import Electrolyte
from helao.core.models.machine import MachineModel
from helao.core.models.process_contrib import ProcessContrib
from helao.core.models.sample import LiquidSample, SolidSample
from helao.deploy.hte.drivers.io.enum import TriggerType
from helao.deploy.hte.drivers.motion.enum import MoveModes, TransformationModes
from helao.helpers.lib_decorators import experiment
from helao.helpers.premodels import ActionPlanMaker

PSTAT_server = MachineModel(
    server_name="PSTAT", machine_name=gethostname().lower()
).as_dict()

MOTOR_server = MachineModel(
    server_name="MOTOR", machine_name=gethostname().lower()
).as_dict()
IO_server = MachineModel(server_name="IO", machine_name=gethostname().lower()).as_dict()


ORCH_server = MachineModel(
    server_name="ORCH", machine_name=gethostname().lower()
).as_dict()
PAL_server = MachineModel(
    server_name="PAL", machine_name=gethostname().lower()
).as_dict()
SAMPLE_server = MachineModel(
    server_name="SAMPLE", machine_name=gethostname().lower()
).as_dict()

toggle_triggertype = TriggerType.fallingedge


@experiment(version=1)
def ECHE_sub_unloadall_customs() -> list:
    """Unload every sample from PAL custom positions and destroy any tracked liquid.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    apm.add(
        SAMPLE_server,
        "archive_custom_unloadall",
        {
            "destroy_liquid": True,
        },
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
    )

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=2)
def ECHE_sub_add_liquid(
    solid_custom_position: str = "cell1_we",
    reservoir_liquid_sample_no: int = 1,
    solution_bubble_gas: str = "O2",
    liquid_volume_ml: float = 1.0,
) -> list:
    """Add liquid (combined + diluted) to the ECHE cell position.

    Args:
        solid_custom_position: PAL custom position name.
        reservoir_liquid_sample_no: Liquid sample number in the reservoir.
        solution_bubble_gas: Bubbler-gas label passed to PAL.
        liquid_volume_ml: Volume to add (mL).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    apm.add(
        SAMPLE_server,
        "archive_custom_add_liquid",
        {
            "custom": solid_custom_position,
            "source_liquid_in": LiquidSample.model_validate(
                {
                    "sample_no": reservoir_liquid_sample_no,
                    "machine_name": gethostname().lower(),
                }
            ).model_dump(),
            "volume_ml": liquid_volume_ml,
            "reservoir_bubbler_gas": solution_bubble_gas,
            "combine_liquids": True,
            "dilute_liquids": True,
        },
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
    )

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def ECHE_sub_load_solid(
    solid_custom_position: str = "cell1_we",
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
) -> list:
    """Load a legacy solid plate sample into a PAL custom position.

    Args:
        solid_custom_position: PAL custom position name.
        solid_plate_id: Plate identifier of the legacy solid sample.
        solid_sample_no: Sample index on the plate.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    apm.add(
        SAMPLE_server,
        "archive_custom_load",
        {
            "custom": solid_custom_position,
            "load_sample_in": SolidSample.model_validate(
                {
                    "sample_no": solid_sample_no,
                    "plate_id": solid_plate_id,
                    "machine_name": "legacy",
                }
            ).model_dump(),
        },
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
    )

    return apm.planned_actions  # returns complete action list to orch


_ECHE_PSTAT_CONTRIB = [
    ProcessContrib.files,
    ProcessContrib.samples_in,
    ProcessContrib.samples_out,
]


def _eche_cell_pstat(
    apm,
    endpoint,
    technique,
    params,
    led=None,
    led_contrib=_ECHE_PSTAT_CONTRIB,
    **kwargs,
):
    """query cell1_we -> [LED cycle on] -> run_<technique> -> [LED cycle off].

    led: (out_name, init_delay, duty, period, duration) for set_digital_cycle.
    """
    apm.add(
        SAMPLE_server,
        "archive_custom_query_sample",
        {"custom": "cell1_we"},
        to_global_params=["_fast_samples_in"],
        start_condition=ActionStartCondition.wait_for_all,
    )
    if led is not None:
        apm.add(
            IO_server,
            "set_digital_cycle",
            {
                "trigger_name": "gamry_ttl0",
                "triggertype": toggle_triggertype,
                "out_name": led[0],
                "out_name_gamry": "gamry_aux",
                "toggle_init_delay": led[1],
                "toggle_duty": led[2],
                "toggle_period": led[3],
                "toggle_duration": led[4],
            },
            start_condition=ActionStartCondition.wait_for_all,
            process_finish=False,
            process_contrib=list(led_contrib),
        )
    apm.add(
        PSTAT_server,
        endpoint,
        params,
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        start_condition=ActionStartCondition.wait_for_all,
        technique_name=technique,
        process_finish=True,
        process_contrib=list(_ECHE_PSTAT_CONTRIB),
        **kwargs,
    )
    if led is not None:
        apm.add(IO_server, "stop_digital_cycle", {})
    return apm.planned_actions


def _eche_ca_potential(
    CA_potential, potential_versus, ref_type, ref_offset__V, solution_ph
):
    versus = 1.23 if resolve_potential_versus(potential_versus) == "oer" else 0
    if ref_type == "rhe":
        potential = CA_potential - ref_offset__V + versus
    else:
        potential = (
            CA_potential
            - 1.0 * ref_offset__V
            + versus
            - 0.059 * solution_ph
            - ref_offset(ref_type)
        )
    print(f"ECHE_sub_CA potential: {potential}")
    return potential


def _eche_cv_params(
    Vinit, Vapex1, Vapex2, Vfinal, ref_offset__V, ref_type, solution_ph
):
    def vs(v):
        return v - 1.0 * ref_offset__V - ref_offset(ref_type) - 0.059 * solution_ph

    return {
        "Vinit__V": vs(Vinit),
        "Vapex1__V": vs(Vapex1),
        "Vapex2__V": vs(Vapex2),
        "Vfinal__V": vs(Vfinal),
    }


@experiment(version=2)
def ECHE_sub_startup(
    solid_custom_position: str = "cell1_we",
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1,
    solution_bubble_gas: str = "N2",
    liquid_volume_ml: float = 1.0,
) -> list:
    """Unload customs, load a solid sample, add liquid, then move to that sample.

    Args:
        solid_custom_position: PAL custom position name.
        solid_plate_id: Plate identifier of the legacy solid sample.
        solid_sample_no: Sample index on the plate.
        reservoir_liquid_sample_no: Liquid sample number in the reservoir.
        solution_bubble_gas: Bubbler-gas label passed to PAL.
        liquid_volume_ml: Liquid volume to add (mL).

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()
    apm.add_actions(ECHE_sub_unloadall_customs())
    apm.add_actions(
        ECHE_sub_load_solid(
            solid_custom_position=solid_custom_position,
            solid_plate_id=solid_plate_id,
            solid_sample_no=solid_sample_no,
        )
    )
    apm.add_actions(
        ECHE_sub_add_liquid(
            solid_custom_position=solid_custom_position,
            reservoir_liquid_sample_no=reservoir_liquid_sample_no,
            solution_bubble_gas=solution_bubble_gas,
            liquid_volume_ml=liquid_volume_ml,
        )
    )
    apm.add_actions(
        ECHE_sub_movetosample(
            solid_plate_id=solid_plate_id, solid_sample_no=solid_sample_no
        )
    )
    return apm.planned_actions


@experiment(version=1)
def ECHE_sub_shutdown() -> list:
    """Unload all samples from PAL custom positions.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # unload all samples from custom positions
    apm.add_actions(ECHE_sub_unloadall_customs())

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=4)
def ECHE_sub_CA_led(
    CA_potential: float = 0.0,
    potential_versus: str = "rhe",
    ref_type: str = "inhouse",
    ref_offset__V: float = 0.0,
    solution_ph: float = 9.53,
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,  # currently liquid sample database number
    solution_bubble_gas: str = "O2",
    measurement_area: float = 0.071,  # 3mm diameter droplet
    samplerate_sec: float = 0.1,
    CA_duration_sec: float = 60,
    gamry_i_range: str = "auto",
    gamrychannelwait: int = -1,
    gamrychannelsend: int = 0,
    illumination_source: str = "doric_led1",
    illumination_wavelength: float = 0.0,
    illumination_intensity: float = 0.0,
    illumination_intensity_date: str = "n/a",
    illumination_side: str = "front",
    toggle_dark_time_init: float = 0.0,
    toggle_illum_duty: float = 0.5,
    toggle_illum_period: float = 2.0,
    toggle_illum_time: float = -1,
    comment: str = "",
) -> list:
    """Run a CA experiment with hardware-triggered LED toggling.

    Args:
        CA_potential: Applied potential before reference correction (V).
        potential_versus: ``"rhe"`` or ``"oer"`` reference frame.
        ref_type: Reference electrode key into ``REF_TABLE``.
        ref_offset__V: Calibration offset of the reference electrode (V).
        solution_ph: Solution pH used for the Nernst conversion.
        reservoir_electrolyte: ``Electrolyte`` enum label (informational).
        reservoir_liquid_sample_no: Liquid sample number (informational).
        solution_bubble_gas: Bubbled gas label (informational).
        measurement_area: Droplet contact area (informational).
        samplerate_sec: Acquisition interval (s).
        CA_duration_sec: CA duration (s).
        gamry_i_range: Gamry current-range setting.
        gamrychannelwait: TTL channel to wait on (-1 disables).
        gamrychannelsend: TTL channel to send on (-1 disables).
        illumination_source: IO output name driving the LED.
        illumination_wavelength: LED wavelength (nm).
        illumination_intensity: LED intensity setting.
        illumination_intensity_date: Provenance date string for intensity.
        illumination_side: ``"front"`` or ``"back"``.
        toggle_dark_time_init: Initial dark delay (s).
        toggle_illum_duty: Illumination duty cycle.
        toggle_illum_period: Illumination toggle period (s).
        toggle_illum_time: Total illumination duration (s); ``-1`` matches CA.
        comment: Free-form comment (informational).

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()
    if int(round(toggle_illum_time)) == -1:
        toggle_illum_time = CA_duration_sec
    potential = _eche_ca_potential(
        CA_potential, potential_versus, ref_type, ref_offset__V, solution_ph
    )
    return _eche_cell_pstat(
        apm,
        "run_CA",
        "CA",
        {
            "Vval__V": potential,
            "Tval__s": CA_duration_sec,
            "AcqInterval__s": samplerate_sec,
            "TTLwait": gamrychannelwait,
            "TTLsend": gamrychannelsend,
            "IErange": gamry_i_range,
        },
        led=(
            illumination_source,
            toggle_dark_time_init,
            toggle_illum_duty,
            toggle_illum_period,
            toggle_illum_time,
        ),
        led_contrib=[ProcessContrib.files],
    )


@experiment(version=2)
def ECHE_sub_OCV(
    Tval__s: float = 1,
    SampleRate: float = 0.05,
) -> list:
    """Run an OCV experiment and store the mean final Ewe to ``HISPEC_OCV`` globals.

    Args:
        Tval__s: OCV duration (s).
        SampleRate: Acquisition interval (s).

    Returns:
        List of planned actions for the orchestrator.
    """

    return _eche_cell_pstat(
        ActionPlanMaker(),
        "run_OCV",
        "OCV",
        {
            "Tval__s": Tval__s,
            "AcqInterval__s": SampleRate,
            "TTLwait": -1,
            "TTLsend": -1,
        },
        to_global_params={"Ewe_V__mean_final": "HISPEC_OCV"},
    )


@experiment(version=2)
def ECHE_sub_preCV(
    CA_potential: float = 0.0,  # need to get from CV initial
    samplerate_sec: float = 0.05,
    CA_duration_sec: float = 3,  # adjustable pre_CV time
) -> list:
    """Run a short CA pre-conditioning step before a CV.

    Args:
        CA_potential: Applied potential (V).
        samplerate_sec: Acquisition interval (s).
        CA_duration_sec: Pre-CV CA duration (s).

    Returns:
        List of planned actions for the orchestrator.
    """

    return _eche_cell_pstat(
        ActionPlanMaker(),
        "run_CA",
        "CA",
        {
            "Vval__V": CA_potential,
            "Tval__s": CA_duration_sec,
            "AcqInterval__s": samplerate_sec,
            "TTLwait": -1,
            "TTLsend": -1,
            "IErange": "auto",
        },
    )


@experiment(version=3)
def ECHE_sub_CA(
    CA_potential: float = 0.0,
    potential_versus: str = "rhe",
    ref_type: str = "inhouse",
    ref_offset__V: float = 0.0,
    solution_ph: float = 9.53,
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,  # currently liquid sample database number
    solution_bubble_gas: str = "O2",
    measurement_area: float = 0.071,  # 3mm diameter droplet
    samplerate_sec: float = 0.1,
    CA_duration_sec: float = 60,
    gamry_i_range: str = "auto",
    comment: str = "",
) -> list:
    """Run a CA experiment without illumination.

    Args:
        CA_potential: Applied potential before reference correction (V).
        potential_versus: ``"rhe"`` or ``"oer"`` reference frame.
        ref_type: Reference electrode key into ``REF_TABLE``.
        ref_offset__V: Calibration offset of the reference electrode (V).
        solution_ph: Solution pH used for the Nernst conversion.
        reservoir_electrolyte: ``Electrolyte`` enum label (informational).
        reservoir_liquid_sample_no: Liquid sample number (informational).
        solution_bubble_gas: Bubbled gas label (informational).
        measurement_area: Droplet contact area (informational).
        samplerate_sec: Acquisition interval (s).
        CA_duration_sec: CA duration (s).
        gamry_i_range: Gamry current-range setting.
        comment: Free-form comment (informational).

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()
    potential = _eche_ca_potential(
        CA_potential, potential_versus, ref_type, ref_offset__V, solution_ph
    )
    return _eche_cell_pstat(
        apm,
        "run_CA",
        "CA",
        {
            "Vval__V": potential,
            "Tval__s": CA_duration_sec,
            "AcqInterval__s": samplerate_sec,
            "IErange": gamry_i_range,
        },
    )


@experiment(version=4)
def ECHE_sub_CV_led(
    Vinit_vsRHE: float = 0.0,  # Initial value in volts or amps.
    Vapex1_vsRHE: float = 1.0,  # Apex 1 value in volts or amps.
    Vapex2_vsRHE: float = -1.0,  # Apex 2 value in volts or amps.
    Vfinal_vsRHE: float = 0.0,  # Final value in volts or amps.
    scanrate_voltsec: Optional[
        float
    ] = 0.02,  # scan rate in volts/second or amps/second.
    samplerate_sec: float = 0.1,
    cycles: int = 1,
    gamry_i_range: str = "auto",
    gamrychannelwait: int = -1,
    gamrychannelsend: int = 0,
    solution_ph: float = 0,
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,  # currently liquid sample database number
    solution_bubble_gas: str = "O2",
    measurement_area: float = 0.071,  # 3mm diameter droplet
    ref_type: str = "inhouse",
    ref_offset__V: float = 0.0,
    illumination_source: str = "doric_led1",
    illumination_wavelength: float = 0.0,
    illumination_intensity: float = 0.0,
    illumination_intensity_date: str = "n/a",
    illumination_side: str = "front",
    toggle_dark_time_init: float = 0.0,
    toggle_illum_duty: float = 0.5,
    toggle_illum_period: float = 2.0,
    toggle_illum_time: float = -1,
    comment: str = "",
) -> list:
    """Run a CV experiment with hardware-triggered LED toggling.

    Computes the CV total duration from the four vertices and ``cycles`` to
    default ``toggle_illum_time`` when it is ``-1``, programs the Galil
    digital cycle, dispatches ``run_CV``, and stops the digital cycle.

    Args:
        Vinit_vsRHE: Initial CV potential vs RHE (V).
        Vapex1_vsRHE: Apex 1 vs RHE (V).
        Vapex2_vsRHE: Apex 2 vs RHE (V).
        Vfinal_vsRHE: Final vs RHE (V).
        scanrate_voltsec: Scan rate (V/s).
        samplerate_sec: Acquisition interval (s).
        cycles: CV cycle count.
        gamry_i_range: Gamry current-range setting.
        gamrychannelwait: TTL channel to wait on (-1 disables).
        gamrychannelsend: TTL channel to send on (-1 disables).
        solution_ph: Solution pH used for the Nernst conversion.
        reservoir_electrolyte: ``Electrolyte`` enum label (informational).
        reservoir_liquid_sample_no: Liquid sample number (informational).
        solution_bubble_gas: Bubbled gas label (informational).
        measurement_area: Droplet contact area (informational).
        ref_type: Reference electrode key into ``REF_TABLE``.
        ref_offset__V: Calibration offset of the reference electrode (V).
        illumination_source: IO output name driving the LED.
        illumination_wavelength: LED wavelength (nm).
        illumination_intensity: LED intensity setting.
        illumination_intensity_date: Provenance date string for intensity.
        illumination_side: ``"front"`` or ``"back"``.
        toggle_dark_time_init: Initial dark delay (s).
        toggle_illum_duty: Illumination duty cycle.
        toggle_illum_period: Illumination toggle period (s).
        toggle_illum_time: Total illumination duration (s); ``-1`` matches CV.
        comment: Free-form comment (informational).

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()
    CV_duration_sec = abs(Vapex1_vsRHE - Vinit_vsRHE) / scanrate_voltsec
    CV_duration_sec += abs(Vfinal_vsRHE - Vapex2_vsRHE) / scanrate_voltsec
    CV_duration_sec += abs(Vapex2_vsRHE - Vapex1_vsRHE) / scanrate_voltsec
    CV_duration_sec += (
        abs(Vapex2_vsRHE - Vapex1_vsRHE) / scanrate_voltsec * 2.0 * (cycles - 1)
    )
    if int(round(toggle_illum_time)) == -1:
        toggle_illum_time = CV_duration_sec
    params = _eche_cv_params(
        Vinit_vsRHE,
        Vapex1_vsRHE,
        Vapex2_vsRHE,
        Vfinal_vsRHE,
        ref_offset__V,
        ref_type,
        solution_ph,
    )
    params.update(
        ScanRate__V_s=scanrate_voltsec,
        AcqInterval__s=samplerate_sec,
        Cycles=cycles,
        TTLwait=gamrychannelwait,
        TTLsend=gamrychannelsend,
        IErange=gamry_i_range,
    )
    return _eche_cell_pstat(
        apm,
        "run_CV",
        "CV",
        params,
        led=(
            illumination_source,
            toggle_dark_time_init,
            toggle_illum_duty,
            toggle_illum_period,
            toggle_illum_time,
        ),
    )


@experiment(version=3)
def ECHE_sub_CV(
    Vinit_vsRHE: float = 0.0,  # Initial value in volts or amps.
    Vapex1_vsRHE: float = 1.0,  # Apex 1 value in volts or amps.
    Vapex2_vsRHE: float = -1.0,  # Apex 2 value in volts or amps.
    Vfinal_vsRHE: float = 0.0,  # Final value in volts or amps.
    scanrate_voltsec: Optional[
        float
    ] = 0.020,  # scan rate in volts/second or amps/second.
    samplerate_sec: float = 0.1,
    cycles: int = 1,
    gamry_i_range: str = "auto",
    solution_ph: float = 0,
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,  # currently liquid sample database number
    solution_bubble_gas: str = "O2",
    measurement_area: float = 0.071,  # 3mm diameter droplet
    ref_type: str = "inhouse",
    ref_offset__V: float = 0.0,
    comment: str = "",
) -> list:
    """Run a CV experiment without illumination.

    Args:
        Vinit_vsRHE: Initial CV potential vs RHE (V).
        Vapex1_vsRHE: Apex 1 vs RHE (V).
        Vapex2_vsRHE: Apex 2 vs RHE (V).
        Vfinal_vsRHE: Final vs RHE (V).
        scanrate_voltsec: Scan rate (V/s).
        samplerate_sec: Acquisition interval (s).
        cycles: CV cycle count.
        gamry_i_range: Gamry current-range setting.
        solution_ph: Solution pH used for the Nernst conversion.
        reservoir_electrolyte: ``Electrolyte`` enum label (informational).
        reservoir_liquid_sample_no: Liquid sample number (informational).
        solution_bubble_gas: Bubbled gas label (informational).
        measurement_area: Droplet contact area (informational).
        ref_type: Reference electrode key into ``REF_TABLE``.
        ref_offset__V: Calibration offset of the reference electrode (V).
        comment: Free-form comment (informational).

    Returns:
        List of planned actions for the orchestrator.
    """

    params = _eche_cv_params(
        Vinit_vsRHE,
        Vapex1_vsRHE,
        Vapex2_vsRHE,
        Vfinal_vsRHE,
        ref_offset__V,
        ref_type,
        solution_ph,
    )
    params.update(
        ScanRate__V_s=scanrate_voltsec,
        AcqInterval__s=samplerate_sec,
        Cycles=cycles,
        IErange=gamry_i_range,
    )
    return _eche_cell_pstat(ActionPlanMaker(), "run_CV", "CV", params)


@experiment(version=3)
def ECHE_sub_CP(
    CP_current: float = 0.0,
    solution_ph: float = 9.53,
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,  # currently liquid sample database number
    solution_bubble_gas: str = "O2",
    measurement_area: float = 0.071,  # 3mm diameter droplet
    ref_type: str = "inhouse",
    ref_offset__V: float = 0.0,
    samplerate_sec: float = 0.1,
    CP_duration_sec: float = 60,
    gamry_i_range: str = "auto",
    comment: str = "",
) -> list:
    """Run a CP experiment without illumination.

    Args:
        CP_current: Applied current (A).
        solution_ph: Solution pH (informational here).
        reservoir_electrolyte: ``Electrolyte`` enum label (informational).
        reservoir_liquid_sample_no: Liquid sample number (informational).
        solution_bubble_gas: Bubbled gas label (informational).
        measurement_area: Droplet contact area (informational).
        ref_type: Reference electrode label (informational).
        ref_offset__V: Reference offset (informational here).
        samplerate_sec: Acquisition interval (s).
        CP_duration_sec: CP duration (s).
        gamry_i_range: Gamry current-range setting.
        comment: Free-form comment (informational).

    Returns:
        List of planned actions for the orchestrator.
    """

    return _eche_cell_pstat(
        ActionPlanMaker(),
        "run_CP",
        "CP",
        {
            "Ival__A": CP_current,
            "Tval__s": CP_duration_sec,
            "AcqInterval__s": samplerate_sec,
            "IErange": gamry_i_range,
        },
    )


@experiment(version=4)
def ECHE_sub_CP_led(
    CP_current: float = 0.0,
    solution_ph: float = 9.53,
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1,  # currently liquid sample database number
    solution_bubble_gas: str = "O2",
    measurement_area: float = 0.071,  # 3mm diameter droplet
    ref_type: str = "inhouse",
    ref_offset__V: float = 0.0,
    samplerate_sec: float = 0.1,
    CP_duration_sec: float = 60,
    gamry_i_range: str = "auto",
    gamrychannelwait: int = -1,
    gamrychannelsend: int = 0,
    illumination_source: str = "doric_led1",
    illumination_wavelength: float = 0.0,
    illumination_intensity: float = 0.0,
    illumination_intensity_date: str = "n/a",
    illumination_side: str = "front",
    toggle_dark_time_init: float = 0.0,
    toggle_illum_duty: float = 0.5,
    toggle_illum_period: float = 2.0,
    toggle_illum_time: float = -1,
    comment: str = "",
) -> list:
    """Run a CP experiment with hardware-triggered LED toggling.

    Args:
        CP_current: Applied current (A).
        solution_ph: Solution pH (informational here).
        reservoir_electrolyte: ``Electrolyte`` enum label (informational).
        reservoir_liquid_sample_no: Liquid sample number (informational).
        solution_bubble_gas: Bubbled gas label (informational).
        measurement_area: Droplet contact area (informational).
        ref_type: Reference electrode label (informational).
        ref_offset__V: Reference offset (informational here).
        samplerate_sec: Acquisition interval (s).
        CP_duration_sec: CP duration (s).
        gamry_i_range: Gamry current-range setting.
        gamrychannelwait: TTL channel to wait on (-1 disables).
        gamrychannelsend: TTL channel to send on (-1 disables).
        illumination_source: IO output name driving the LED.
        illumination_wavelength: LED wavelength (nm).
        illumination_intensity: LED intensity setting.
        illumination_intensity_date: Provenance date string for intensity.
        illumination_side: ``"front"`` or ``"back"``.
        toggle_dark_time_init: Initial dark delay (s).
        toggle_illum_duty: Illumination duty cycle.
        toggle_illum_period: Illumination toggle period (s).
        toggle_illum_time: Total illumination duration (s); ``-1`` matches CP.
        comment: Free-form comment (informational).

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()
    if int(round(toggle_illum_time)) == -1:
        toggle_illum_time = CP_duration_sec
    return _eche_cell_pstat(
        apm,
        "run_CP",
        "CP",
        {
            "Ival__A": CP_current,
            "Tval__s": CP_duration_sec,
            "AcqInterval__s": samplerate_sec,
            "TTLwait": gamrychannelwait,
            "TTLsend": gamrychannelsend,
            "IErange": gamry_i_range,
        },
        led=(
            illumination_source,
            toggle_dark_time_init,
            toggle_illum_duty,
            toggle_illum_period,
            toggle_illum_time,
        ),
    )


@experiment(version=1)
def ECHE_sub_movetosample(
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
) -> list:
    """Resolve plate XY for a sample and move there in platexy frame.

    Args:
        solid_plate_id: Plate identifier of the legacy solid sample.
        solid_sample_no: Sample index on the plate.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # get sample plate coordinates
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
        start_condition=ActionStartCondition.wait_for_all,
    )

    # move to position
    apm.add(
        MOTOR_server,
        "move",
        {
            # "d_mm": [x_mm, y_mm],
            "axis": ["x", "y"],
            "mode": MoveModes.absolute,
            "transformation": TransformationModes.platexy,
        },
        from_global_act_params={"_platexy": "d_mm"},
        start_condition=ActionStartCondition.wait_for_all,
    )

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def ECHE_sub_rel_move(
    offset_x_mm: float = 1.0,
    offset_y_mm: float = 1.0,
) -> list:
    """Move X/Y by relative offsets (platexy transformation).

    Args:
        offset_x_mm: Relative X displacement (mm).
        offset_y_mm: Relative Y displacement (mm).

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # move to position
    apm.add(
        MOTOR_server,
        "move",
        {
            "d_mm": [offset_x_mm, offset_y_mm],
            "axis": ["x", "y"],
            "mode": MoveModes.relative,
            "transformation": TransformationModes.platexy,
        },
        #            "from_global_act_params": {"_platexy": "d_mm"},
        start_condition=ActionStartCondition.wait_for_all,
    )

    return apm.planned_actions  # returns complete action list to orch
