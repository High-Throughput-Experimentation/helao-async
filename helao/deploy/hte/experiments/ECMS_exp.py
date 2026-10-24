"""Experiment library for the AutoGDE / ECMS station.

Defines sub-experiments that build action lists for an orchestrator. Each
function takes an ``Experiment`` and returns the list of actions to enqueue.
Action targets are referenced by ``server_key`` strings (e.g. ``PSTAT``,
``NI``, ``PAL``, ``IO``, ``CALC``, ``MFC``, ``CALIBRATIONMFC``,
``CALIBRATIONMFCSECOND``, ``ORCH``).
"""

# editted 111224
EXPERIMENTS = [
    "ECMS_sub_alloff",
    "ECMS_sub_CA",
    "ECMS_sub_CA_CO2flow",
    "ECMS_sub_cali",
    "ECMS_sub_clean_cell_recirculation",
    "ECMS_sub_CV",
    "ECMS_sub_drain",
    "ECMS_sub_drain_recirculation",
    "ECMS_sub_electrolyte_fill_cell",
    "ECMS_sub_electrolyte_fill_cell_recirculation",
    "ECMS_sub_electrolyte_fill_recirculationreservoir",
    "ECMS_sub_electrolyte_recirculation_off",
    "ECMS_sub_electrolyte_recirculation_on",
    "ECMS_sub_final_clean_cell",
    "ECMS_sub_headspace_purge_and_Arbaseline",
    "ECMS_sub_headspace_purge_and_CO2baseline",
    "ECMS_sub_inertgascali",
    "ECMS_sub_load_gas",
    "ECMS_sub_load_liquid",
    "ECMS_sub_load_solid",
    "ECMS_sub_load_solid_only",
    "ECMS_sub_normal_state",
    "ECMS_sub_preCA_CO2flow",
    "ECMS_sub_prevacuum_cell",
    "ECMS_sub_pulseCA",
    "ECMS_sub_pulsecali",
    "ECMS_sub_threegascali",
    "ECMS_sub_unload_cell",
    "ECMS_sub_cali_second",
]

###
from socket import gethostname

from helao.core.models.action_start_condition import ActionStartCondition as asc
from helao.core.models.echem_params import ref_offset, resolve_we_versus
from helao.core.models.machine import MachineModel
from helao.core.models.process_contrib import ProcessContrib
from helao.core.models.sample import GasSample, LiquidSample, SolidSample

# from helao.deploy.hte.drivers.motion.enum import MoveModes, TransformationModes
from helao.deploy.hte.drivers.io.enum import TriggerType
from helao.helpers.lib_decorators import experiment
from helao.helpers.premodels import ActionPlanMaker

# list valid experiment functions

ORCH_HOST = gethostname().lower()
PSTAT_server = MachineModel(server_name="PSTAT", machine_name=ORCH_HOST).as_dict()
# MOTOR_server = MachineModel(server_name="MOTOR", machine_name=ORCH_HOST).as_dict()
NI_server = MachineModel(server_name="NI", machine_name=ORCH_HOST).as_dict()
ORCH_server = MachineModel(server_name="ORCH", machine_name=ORCH_HOST).as_dict()
PAL_server = MachineModel(server_name="PAL", machine_name=ORCH_HOST).as_dict()
SAMPLE_server = MachineModel(server_name="SAMPLE", machine_name=ORCH_HOST).as_dict()
IO_server = MachineModel(server_name="IO", machine_name=ORCH_HOST).as_dict()
CALC_server = MachineModel(server_name="CALC", machine_name=ORCH_HOST).as_dict()
# CO2S_server = MachineModel(server_name="CO2SENSOR", machine_name=ORCH_HOST).as_dict()
MFC_server = MachineModel(server_name="MFC", machine_name=ORCH_HOST).as_dict()
CALIBRATIONMFC_server = MachineModel(
    server_name="CALIBRATIONMFC", machine_name=ORCH_HOST
).as_dict()
CALIBRATIONMFCSECOND_server = MachineModel(
    server_name="CALIBRATIONMFCSECOND", machine_name=ORCH_HOST
).as_dict()

# WORKSYRINGE_server = MachineModel(
#     server_name="WORKSYRINGE", machine_name=ORCH_HOST
# ).as_dict()
# CLEANSYRINGE_server = MachineModel(
#     server_name="CLEANSYRINGE", machine_name=ORCH_HOST
# ).as_dict()
toggle_triggertype = TriggerType.fallingedge


@experiment(version=1)
def ECMS_sub_unload_cell() -> list:
    """Unload every sample at the ``cell1_we`` PAL custom position.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()
    apm.add(SAMPLE_server, "archive_custom_unloadall", {})
    return apm.planned_actions


@experiment(version=1)
def ECMS_sub_load_solid(
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
) -> list:
    """Load a legacy solid plate sample into ``cell1_we``.

    Args:
        solid_plate_id: Plate identifier of the legacy solid sample.
        solid_sample_no: Sample index on the plate.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()

    apm.add(
        SAMPLE_server,
        "archive_custom_load",
        {
            "custom": "cell1_we",
            "load_sample_in": SolidSample.model_validate(
                {
                    "sample_no": solid_sample_no,
                    "plate_id": solid_plate_id,
                    "machine_name": "legacy",
                }
            ).model_dump(),
        },
    )

    return apm.planned_actions


@experiment(version=1)
def ECMS_sub_load_solid_only(
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
) -> list:
    """Unload the cell and load a legacy solid plate sample into ``cell1_we``.

    Args:
        solid_plate_id: Plate identifier of the legacy solid sample.
        solid_sample_no: Sample index on the plate.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    apm.add_actions(ECMS_sub_unload_cell())
    apm.add_actions(
        ECMS_sub_load_solid(
            solid_plate_id=solid_plate_id, solid_sample_no=solid_sample_no
        )
    )
    return apm.planned_actions


_ECMS_MFC = {
    "CO2": MFC_server,
    "Caligas": CALIBRATIONMFC_server,
    "Caligassecond": CALIBRATIONMFCSECOND_server,
}


def _ecms_mfc(
    apm,
    device,
    flowrate_sccm,
    ramp_sccm_sec,
    then="cancel_hold_valve_action",
    start=asc.no_wait,
):
    """Set one MFC's flow rate, then release (or close) its hold valve."""
    apm.add(
        _ECMS_MFC[device],
        "set_flowrate",
        {
            "flowrate_sccm": flowrate_sccm,
            "ramp_sccm_sec": ramp_sccm_sec,
            "device_name": device,
        },
        start,
    )
    apm.add(_ECMS_MFC[device], then, {"device_name": device}, asc.no_wait)


def _ecms_vs_ref(V, WE_versus, ref_offset__V, pH, ref_type):
    """Convert a WE potential to volts vs the reference electrode (arithmetic verbatim).

    ``"ocv"`` passes the potential through: the Gamry endpoint applies it relative
    to a measured OCV (see :func:`_ecms_ocv_params`).
    """
    WE_versus = resolve_we_versus(WE_versus)
    if WE_versus == "ref":
        return V - 1.0 * ref_offset__V
    if WE_versus == "rhe":
        return V - 1.0 * ref_offset__V - 0.059 * pH - ref_offset(ref_type)
    if WE_versus == "ocv":
        return V
    raise ValueError(f"WE_versus must be one of ref, rhe, ocv; got {WE_versus!r}")


def _ecms_ocv_params(WE_versus, OCV_duration__s):
    """PSTAT params that make the endpoint measure OCV first (empty unless ``"ocv"``)."""
    if resolve_we_versus(WE_versus) == "ocv":
        return {"versus_OCV": True, "OCV_duration__s": OCV_duration__s}
    return {}


def _ecms_pstat(apm, endpoint, params, technique):
    """Query the cell sample, then run one PSTAT technique on it."""
    apm.add(
        SAMPLE_server,
        "archive_custom_query_sample",
        {"custom": "cell1_we"},
        to_global_params=["_fast_samples_in"],
    )
    apm.add(
        PSTAT_server,
        endpoint,
        params,
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        process_finish=True,
        technique_name=technique,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )


def _ecms_add_liquid(apm, sample_no, volume_ul, combine=True, dilute=True):
    """Record `volume_ul` of reservoir liquid `sample_no` as added to the cell."""
    apm.add(
        SAMPLE_server,
        "archive_custom_add_liquid",
        {
            "custom": "cell1_we",
            "source_liquid_in": LiquidSample(
                sample_no=sample_no, machine_name=ORCH_HOST
            ).model_dump(),
            "volume_ml": volume_ul / 1000,
            "combine_liquids": combine,
            "dilute_liquids": dilute,
        },
    )


def _ecms_fill_cell(apm, inlet_valve, liquid_backward_time, sample_no, volume_ul):
    """Pump electrolyte into the cell through `inlet_valve` (4A reservoir, 4B recirculation)."""
    apm.add(NI_server, "liquidvalve", {"liquidvalve": inlet_valve, "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 1})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-dir", "on": 1})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": liquid_backward_time})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": inlet_valve, "on": 0})
    _ecms_add_liquid(apm, sample_no, volume_ul)
    return apm.planned_actions


def _ecms_headspace_purge(
    apm,
    device,
    equilibrium_duration,
    flowrate_sccm,
    flow_ramp_sccm,
    MS_baseline_duration,
):
    """Purge the headspace with `device`'s gas, then route it to the MS for a baseline."""
    apm.add(NI_server, "gasvalve", {"gasvalve": "1", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "2A", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "3A", "on": 1})
    _ecms_mfc(apm, device, flowrate_sccm, flow_ramp_sccm)
    apm.add(ORCH_server, "wait", {"waittime": equilibrium_duration})
    apm.add(NI_server, "gasvalve", {"gasvalve": "2B", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "6B", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "6A", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": MS_baseline_duration})
    return apm.planned_actions


@experiment(version=2)
def ECMS_sub_load_liquid(
    reservoir_liquid_sample_no: int = 1,
    volume_ul_cell_liquid: int = 1000,
    water_True_False: bool = False,
    combine_True_False: bool = False,
) -> list:
    """Archive a liquid sample addition into ``cell1_we``.

    Args:
        reservoir_liquid_sample_no: Liquid sample number in the reservoir.
        volume_ul_cell_liquid: Volume added (uL).
        water_True_False: Forwarded as ``dilute_liquids`` to PAL.
        combine_True_False: Forwarded as ``combine_liquids`` to PAL.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    _ecms_add_liquid(
        apm,
        reservoir_liquid_sample_no,
        volume_ul_cell_liquid,
        combine_True_False,
        water_True_False,
    )
    return apm.planned_actions


@experiment(version=2)
def ECMS_sub_load_gas(
    reservoir_gas_sample_no: int = 1,
    volume_ul_cell_gas: int = 1000,
) -> list:
    """Load a gas sample into ``cell1_we``.

    Args:
        reservoir_gas_sample_no: Gas sample number in the reservoir.
        volume_ul_cell_gas: Volume added (uL).

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()
    apm.add(
        SAMPLE_server,
        "archive_custom_load",  # not sure there is a server function for gas
        {
            "custom": "cell1_we",
            "load_sample_in": GasSample(
                sample_no=reservoir_gas_sample_no, machine_name=ORCH_HOST
            ).model_dump(),
            "volume_ml": volume_ul_cell_gas / 1000,
        },
    )
    return apm.planned_actions


@experiment(version=1)
def ECMS_sub_normal_state() -> list:
    """Drive the ECMS station to its idle/normal state.

    Closes all CO2 / calibration-gas MFC valves, closes every NI gas valve
    except ``6B`` (which is opened to route flow past the GDE cell to the
    MS).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    for device in ("CO2", "Caligas", "Caligassecond"):
        _ecms_mfc(apm, device, 0.0, 0.0, then="hold_valve_closed_action")
    apm.add(NI_server, "gasvalve", {"gasvalve": "1", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "2A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "3A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "2B", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "6A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "6B", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0})
    return apm.planned_actions


@experiment(version=1)
def ECMS_sub_alloff() -> list:
    """Turn off both peristaltic pumps, close MFC valves, and close every NI valve.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 0})
    for device in ("CO2", "Caligas"):
        _ecms_mfc(apm, device, 0.0, 0.0, then="hold_valve_closed_action")
    for valve in ("2B", "1", "2A", "3A", "3B", "6A", "6B", "7"):
        apm.add(NI_server, "gasvalve", {"gasvalve": valve, "on": 0}, asc.no_wait)
    for valve in ("4A", "4B", "5A", "5B"):
        apm.add(NI_server, "liquidvalve", {"liquidvalve": valve, "on": 0}, asc.no_wait)
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1-dir", "on": 0})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-dir", "on": 0})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-maxspd", "on": 0})
    return apm.planned_actions


@experiment(version=1)
def ECMS_sub_electrolyte_fill_recirculationreservoir(
    liquid_fill_time: float = 30,
) -> list:
    """Run the reservoir peristaltic pump forward to fill the recirculation reservoir.

    Args:
        liquid_fill_time: Pump-on duration (s).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()

    # Fill cell with liquid
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1-dir", "on": 1})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": liquid_fill_time})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})

    return apm.planned_actions


@experiment(version=2)
def ECMS_sub_electrolyte_fill_cell(
    # liquid_forward_time: float = 20,
    liquid_backward_time: float = 10,
    reservoir_liquid_sample_no: int = 1,
    volume_ul_cell_liquid: int = 1,
) -> list:
    """Reverse-pump electrolyte from reservoir into the cell and archive the addition.

    Args:
        liquid_backward_time: Reverse pump-on duration (s).
        reservoir_liquid_sample_no: Liquid sample number in the reservoir.
        volume_ul_cell_liquid: Volume archived to the cell (uL; converted to mL for PAL).

    Returns:
        List of planned actions for the orchestrator.
    """
    return _ecms_fill_cell(
        ActionPlanMaker(),
        "4A",
        liquid_backward_time,
        reservoir_liquid_sample_no,
        volume_ul_cell_liquid,
    )


@experiment(version=2)
def ECMS_sub_electrolyte_fill_cell_recirculation(
    liquid_backward_time: float = 80,
    reservoir_liquid_sample_no: int = 2,
    volume_ul_cell_liquid: float = 1.0,
) -> list:
    """Reverse-pump electrolyte into the cell via the recirculation path and archive the addition.

    Args:
        liquid_backward_time: Reverse pump-on duration (s).
        reservoir_liquid_sample_no: Liquid sample number in the reservoir.
        volume_ul_cell_liquid: Volume archived to the cell.

    Returns:
        List of planned actions for the orchestrator.
    """
    return _ecms_fill_cell(
        ActionPlanMaker(),
        "4B",
        liquid_backward_time,
        reservoir_liquid_sample_no,
        volume_ul_cell_liquid,
    )


@experiment(version=2)
def ECMS_sub_prevacuum_cell(
    vacuum_time: float = 10,
) -> list:
    """Open the vacuum path to evacuate the gas side and pull electrolyte against the GDE.

    Args:
        vacuum_time: Vacuum duration (s).

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()

    # Fill cell with liquid
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "2A", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "3B", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": vacuum_time})
    apm.add(NI_server, "gasvalve", {"gasvalve": "2A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "3B", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 0})

    return apm.planned_actions


@experiment(version=1)
def ECMS_sub_headspace_purge_and_CO2baseline(
    CO2equilibrium_duration: float = 30,
    flowrate_sccm: float = 5.0,
    flow_ramp_sccm: float = 0,
    MS_baseline_duration: float = 300,
    # flow_duration: float = -1,
    # co2measure_acqrate: float = 0.5
) -> list:
    """Open the CO2 gas path, set the MFC flow, equilibrate, then route to MS for a baseline.

    Args:
        CO2equilibrium_duration: Wait after starting CO2 flow (s).
        flowrate_sccm: CO2 flow rate (sccm).
        flow_ramp_sccm: MFC ramp rate (sccm/s).
        MS_baseline_duration: Baseline wait once routed to MS (s).

    Returns:
        List of planned actions for the orchestrator.
    """
    return _ecms_headspace_purge(
        ActionPlanMaker(),
        "CO2",
        CO2equilibrium_duration,
        flowrate_sccm,
        flow_ramp_sccm,
        MS_baseline_duration,
    )


@experiment(version=1)
def ECMS_sub_headspace_purge_and_Arbaseline(
    Arequilibrium_duration: float = 30,
    flowrate_sccm: float = 5.0,
    flow_ramp_sccm: float = 0,
    MS_baseline_duration: float = 100,
    # flow_duration: float = -1,
    # co2measure_acqrate: float = 0.5
) -> list:
    """Open the Ar/inert gas path, set the calibration MFC flow, then route to MS for a baseline.

    Args:
        Arequilibrium_duration: Wait after starting flow (s).
        flowrate_sccm: Inert-gas flow rate (sccm).
        flow_ramp_sccm: MFC ramp rate (sccm/s).
        MS_baseline_duration: Baseline wait once routed to MS (s).

    Returns:
        List of planned actions for the orchestrator.
    """
    return _ecms_headspace_purge(
        ActionPlanMaker(),
        "Caligassecond",
        Arequilibrium_duration,
        flowrate_sccm,
        flow_ramp_sccm,
        MS_baseline_duration,
    )


@experiment(version=1)
def ECMS_sub_electrolyte_recirculation_on() -> list:
    """Open the recirculation valves and start the recirculation pump in reverse direction.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()

    # Fill cell with liquid
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 1})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-dir", "on": 1})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 1})
    return apm.planned_actions


@experiment(version=1)
def ECMS_sub_electrolyte_recirculation_off() -> list:
    """Stop the recirculation pump and close the recirculation valves.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 0})

    return apm.planned_actions


@experiment(version=2)
def ECMS_sub_CA(
    WE_potential__V: float = 0.0,
    WE_versus: str = "ref",
    CA_duration_sec: float = 0.1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    ref_type: str = "leakless",
    pH: float = 6.8,
    MS_equilibrium_time: float = 90.0,
    OCV_duration__s: float = 2.0,
) -> list:
    """Run a CA experiment then wait for the MS signal to equilibrate.

    Args:
        WE_potential__V: Working-electrode potential (V).
        WE_versus: ``"ref"``, ``"rhe"`` or ``"ocv"``.
        CA_duration_sec: CA duration (s).
        SampleRate: Acquisition interval (s).
        IErange: Gamry current-range setting.
        ref_offset__V: Reference offset (V).
        ref_type: Reference electrode key into ``REF_TABLE``.
        pH: Solution pH (used in RHE conversion).
        MS_equilibrium_time: Post-CA wait for the MS signal to settle (s).
        OCV_duration__s: OCV measurement time (s); used only when ``WE_versus="ocv"``.

    Raises:
        ValueError: If ``WE_versus`` is not ``"ref"``, ``"rhe"`` or ``"ocv"``.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    _ecms_pstat(
        apm,
        "run_CA",
        {
            "Vval__V": _ecms_vs_ref(
                WE_potential__V, WE_versus, ref_offset__V, pH, ref_type
            ),
            "Tval__s": CA_duration_sec,
            "AcqInterval__s": SampleRate,
            "IErange": IErange,
            **_ecms_ocv_params(WE_versus, OCV_duration__s),
        },
        "CA",
    )
    apm.add(ORCH_server, "wait", {"waittime": MS_equilibrium_time})
    return apm.planned_actions


@experiment(version=3)
def ECMS_sub_pulseCA(
    Vinit__V: float = 0.0,
    Tinit__s: float = 0.5,
    Vstep__V: float = 0.5,
    Tstep__s: float = 0.5,
    Cycles: int = 5,
    AcqInterval__s: float = 0.01,  # acquisition rate
    run_OCV: bool = False,
    Tocv__s: float = 60.0,
    IErange: str = "auto",
    WE_versus: str = "ref",
    ref_offset__V: float = 0.0,
    ref_type: str = "leakless",
    pH: float = 6.8,
    MS_equilibrium_time: float = 90.0,
) -> list:
    """Run a pulsed (rectangular) CA via ``run_RCA``; optionally precede it with an OCV.

    When ``run_OCV`` is True an OCV is run first and its final Ewe is fed
    into ``run_RCA`` as the starting potential.

    Args:
        Vinit__V: Initial step potential (V) (ignored when ``run_OCV`` is True).
        Tinit__s: Initial step duration (s).
        Vstep__V: Step potential delta (V).
        Tstep__s: Step duration (s).
        Cycles: Number of pulse cycles.
        AcqInterval__s: Acquisition interval (s).
        run_OCV: Run an OCV first to set the starting potential.
        Tocv__s: OCV duration (s).
        IErange: Gamry current-range setting.
        WE_versus: Reference frame label (informational; not used in math).
        ref_offset__V: Reference offset (V).
        ref_type: Reference electrode key into ``REF_TABLE``.
        pH: Solution pH.
        MS_equilibrium_time: Post-CA wait for the MS signal to settle (s).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    # =============================================================================
    #     if WE_versus == "ref":
    #         potential_vsRef = WE_potential__V - 1.0 * ref_offset__V
    #     elif WE_versus == "rhe":
    #         potential_vsRef = (
    #             WE_potential__V
    #             - 1.0 * ref_offset__V
    #             - 0.059 * pH
    #             - REF_TABLE[ref_type]
    #         )
    # =============================================================================
    apm.add(
        SAMPLE_server,
        "archive_custom_query_sample",
        {"custom": "cell1_we"},
        to_global_params=["_fast_samples_in"],
    )
    if run_OCV:
        # OCV
        apm.add(
            PSTAT_server,
            "run_OCV",
            {
                "Tval__s": Tocv__s,
                "AcqInterval__s": 0.05,
                "IErange": IErange,
            },
            to_global_params=["Ewe_V__mean_final"],
            from_global_act_params={"_fast_samples_in": "fast_samples_in"},
            technique_name="OCV",
            process_finish=True,
            process_contrib=[
                ProcessContrib.action_params,
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        )
        apm.add(
            PSTAT_server,
            "run_RCA",
            {
                # "Vinit__V": Vinit__V,
                "Tinit__s": Tinit__s,
                "Vstep__V": Vstep__V,
                "Tstep__s": Tstep__s,
                "Cycles": Cycles,
                "AcqInterval__s": AcqInterval__s,
            },
            from_global_act_params={
                "_fast_samples_in": "fast_samples_in",
                "Ewe_V__mean_final": "Vinit__V",
            },
            process_finish=True,
            technique_name="CA",
            process_contrib=[
                ProcessContrib.action_params,
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        )
    else:
        apm.add(
            PSTAT_server,
            "run_RCA",
            {
                "Vinit__V": Vinit__V,
                "Tinit__s": Tinit__s,
                "Vstep__V": Vstep__V,
                "Tstep__s": Tstep__s,
                "Cycles": Cycles,
                "AcqInterval__s": AcqInterval__s,
            },
            from_global_act_params={"_fast_samples_in": "fast_samples_in"},
            process_finish=True,
            technique_name="CA",
            process_contrib=[
                ProcessContrib.action_params,
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        )
    apm.add(ORCH_server, "wait", {"waittime": MS_equilibrium_time})
    # apm.add(ORCH_server, "wait", {"waittime": 10})

    return apm.planned_actions


@experiment(version=3)
def ECMS_sub_CV(
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    SamplingMode: str = "SamplingModeFast",
    versus_OCV: bool = False,
    OCV_duration__s: float = 0.0,
    OCV_acquisition_period__s: float = 0.1,
    WE_potential_init__V: float = 0.0,
    WE_potential_apex1__V: float = -1.0,
    WE_potential_apex2__V: float = -0.5,
    WE_potential_final__V: float = -0.5,
    ScanRate_V_s: float = 0.01,
    Cycles: int = 1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    MS_equilibrium_time: float = 90.0,
) -> list:
    """Run a CV experiment then wait for the MS signal to equilibrate.

    Args:
        WE_versus: ``"ref"``, ``"rhe"`` or ``"ocv"``. ``"ocv"`` passes the
            potentials through and measures OCV first: the effective
            ``versus_OCV`` is ``versus_OCV or WE_versus == "ocv"``.
        ref_type: Reference electrode key into ``REF_TABLE``.
        pH: Solution pH (used in RHE conversion).
        versus_OCV: Measure OCV first and apply potentials relative to it.
        OCV_duration__s: OCV measurement time (s); used only when versus_OCV.
        WE_potential_init__V: Initial potential (V).
        WE_potential_apex1__V: Apex 1 potential (V).
        WE_potential_apex2__V: Apex 2 potential (V).
        WE_potential_final__V: Final potential (V).
        ScanRate_V_s: Scan rate (V/s).
        Cycles: CV cycle count.
        SampleRate: Acquisition interval (s).
        IErange: Gamry current-range setting.
        ref_offset__V: Reference offset (V).
        MS_equilibrium_time: Post-CV wait for the MS signal to settle (s).

    Raises:
        ValueError: If ``WE_versus`` is not ``"ref"``, ``"rhe"`` or ``"ocv"``.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    params = {
        "Vinit__V": _ecms_vs_ref(
            WE_potential_init__V, WE_versus, ref_offset__V, pH, ref_type
        ),
        "Vapex1__V": _ecms_vs_ref(
            WE_potential_apex1__V,
            WE_versus,
            ref_offset__V,
            pH,
            ref_type,
        ),
        "Vapex2__V": _ecms_vs_ref(
            WE_potential_apex2__V,
            WE_versus,
            ref_offset__V,
            pH,
            ref_type,
        ),
        "Vfinal__V": _ecms_vs_ref(
            WE_potential_final__V,
            WE_versus,
            ref_offset__V,
            pH,
            ref_type,
        ),
        "ScanRate__V_s": ScanRate_V_s,
        "Cycles": Cycles,
        "AcqInterval__s": SampleRate,
        "IErange": IErange,
        "SamplingMode": SamplingMode,
        "versus_OCV": versus_OCV or resolve_we_versus(WE_versus) == "ocv",
        "OCV_duration__s": OCV_duration__s,
        "OCV_acquisition_period__s": OCV_acquisition_period__s,
    }
    _ecms_pstat(apm, "run_CV", params, ["CV"])
    apm.add(ORCH_server, "wait", {"waittime": MS_equilibrium_time})
    return apm.planned_actions


@experiment(version=1)
def ECMS_sub_drain_recirculation(
    tube_clear_time: float = 20,
    liquid_drain_time: float = 80,
) -> list:
    """Clear the recirculation tubes then drain the cell via the recirculation pump.

    Args:
        tube_clear_time: Tube-clearing pump duration (s).
        liquid_drain_time: Liquid drain pump duration (s).

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()

    # Fill cell with liquid
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 1})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-dir", "on": 0})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 1})
    # apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-maxspd", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": tube_clear_time})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4A", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 0})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-dir", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": liquid_drain_time})
    # apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-maxspd", "on": 0})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 0})
    return apm.planned_actions


@experiment(version=2)
def ECMS_sub_clean_cell_recirculation(
    cleaning_times: int = 2,
    liquid_fill_time: float = 30,
    volume_ul_cell_liquid: int = 1,
    liquid_backward_time: float = 80,
    reservoir_liquid_sample_no: int = 2,
    tube_clear_delaytime: float = 40.0,
    tube_clear_time: float = 20,
    liquid_drain_time: float = 80,
) -> list:
    """Repeat fill-reservoir + recirc-fill + drain cycles to clean the cell.

    Args:
        cleaning_times: Number of fill/drain cycles.
        liquid_fill_time: Reservoir-fill pump duration (s).
        volume_ul_cell_liquid: Per-fill cell volume (uL forwarded).
        liquid_backward_time: Reverse-pump duration during fill (s).
        reservoir_liquid_sample_no: Liquid sample number in the reservoir.
        tube_clear_delaytime: Unused tube-clearing delay (s); reserved.
        tube_clear_time: Tube-clearing pump duration during drain (s).
        liquid_drain_time: Drain pump duration (s).

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()

    for cycle in range(cleaning_times):
        apm.add_actions(
            ECMS_sub_electrolyte_fill_recirculationreservoir(
                liquid_fill_time=liquid_fill_time
            )
        )
        apm.add_actions(
            ECMS_sub_electrolyte_fill_cell_recirculation(
                volume_ul_cell_liquid=volume_ul_cell_liquid,
                liquid_backward_time=liquid_backward_time,
                reservoir_liquid_sample_no=reservoir_liquid_sample_no,
            )
        )
        # =============================================================================
        #         apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 1})
        #         apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 1})
        #         apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-dir", "on": 0})
        #         apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 1})
        #         #apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-maxspd", "on": 1})
        #         apm.add(ORCH_server, "wait", {"waittime": tube_clear_time+tube_clear_delaytime})
        #         apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A", "on": 1})
        #         apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 0})
        #         apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-dir", "on": 1})
        #         apm.add(ORCH_server, "wait", {"waittime": liquid_drain_time-tube_clear_delaytime})
        #         #apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-maxspd", "on": 0})
        #         apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 0})
        #         apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A", "on": 0})
        #         apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 0})
        # =============================================================================
        apm.add_actions(
            ECMS_sub_drain_recirculation(
                tube_clear_time=tube_clear_time,
                liquid_drain_time=liquid_drain_time,
            )
        )
    return apm.planned_actions


@experiment(version=1)
def ECMS_sub_drain(
    liquid_drain_time: float = 30,
) -> list:
    """Drain the cell using the reservoir pump (peripump 1) in reverse direction.

    Args:
        liquid_drain_time: Drain pump duration (s).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()

    # Fill cell with liquid
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4A", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A", "on": 1})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1-dir", "on": 1})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": liquid_drain_time})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4A", "on": 0})
    return apm.planned_actions


@experiment(version=2)
def ECMS_sub_final_clean_cell(
    liquid_backward_time_1: float = 300,
    liquid_backward_time_2: float = 300,
    reservoir_liquid_sample_no: int = 1,
    volume_ul_cell_liquid: int = 1,
) -> list:
    """Run a two-stage final clean: reservoir-to-cell then cell-to-cell, then archive.

    Args:
        liquid_backward_time_1: First-stage reverse-pump duration (s).
        liquid_backward_time_2: Second-stage reverse-pump duration (s).
        reservoir_liquid_sample_no: Liquid sample number in the reservoir.
        volume_ul_cell_liquid: Volume archived to the cell.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4A", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 1})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2-dir", "on": 1})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": liquid_backward_time_1})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 1})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": liquid_backward_time_2})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4B", "on": 0})
    _ecms_add_liquid(apm, reservoir_liquid_sample_no, volume_ul_cell_liquid)
    return apm.planned_actions


# used for when calibration gas is connected to first MFC_caligas"
@experiment(version=1)
def ECMS_sub_cali(
    CO2flowrate_sccm: float = 20.0,
    Califlowrate_sccm: float = 0.0,
    flow_ramp_sccm: float = 0,
    MSsignal_quilibrium_time: float = 300,
) -> list:
    """Set CO2 and calibration-gas MFC flow rates and wait for the MS to equilibrate.

    Args:
        CO2flowrate_sccm: CO2 flow rate (sccm).
        Califlowrate_sccm: Calibration-gas flow rate (sccm).
        flow_ramp_sccm: MFC ramp rate (sccm/s).
        MSsignal_quilibrium_time: Equilibration wait (s).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    _ecms_mfc(apm, "CO2", CO2flowrate_sccm, flow_ramp_sccm)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 1})
    _ecms_mfc(apm, "Caligas", Califlowrate_sccm, flow_ramp_sccm)
    apm.add(ORCH_server, "wait", {"waittime": MSsignal_quilibrium_time})
    return apm.planned_actions


# used for when calibration gas is connected to second MFC_Caligassecond"
@experiment(version=2)
def ECMS_sub_cali_second(
    CO2flowrate_sccm: float = 20.0,
    Califlowrate_sccm: float = 0.0,
    flow_ramp_sccm: float = 0,
    MSsignal_quilibrium_time: float = 300,
) -> list:
    """Set CO2 and calibration-gas MFC flow rates and wait for the MS to equilibrate.

    Args:
        CO2flowrate_sccm: CO2 flow rate (sccm).
        Califlowrate_sccm: Calibration-gas flow rate (sccm).
        flow_ramp_sccm: MFC ramp rate (sccm/s).
        MSsignal_quilibrium_time: Equilibration wait (s).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    _ecms_mfc(apm, "CO2", CO2flowrate_sccm, flow_ramp_sccm)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 1})
    _ecms_mfc(apm, "Caligassecond", Califlowrate_sccm, flow_ramp_sccm)
    apm.add(ORCH_server, "wait", {"waittime": MSsignal_quilibrium_time})
    return apm.planned_actions


@experiment(version=1)
def ECMS_sub_threegascali(
    CO2flowrate_sccm: float = 5.0,
    Califlowrate_sccm: float = 5.0,  # O2
    Califlowrate_two_sccm: float = 0.0,  # Ar
    flow_ramp_sccm: float = 0,
    MSsignal_quilibrium_time: float = 300,
) -> list:
    """Set CO2, calibration-gas, and second calibration-gas MFC flow rates simultaneously.

    Args:
        CO2flowrate_sccm: CO2 flow rate (sccm).
        Califlowrate_sccm: First calibration-gas flow rate (sccm).
        Califlowrate_two_sccm: Second calibration-gas flow rate (sccm).
        flow_ramp_sccm: MFC ramp rate (sccm/s).
        MSsignal_quilibrium_time: Equilibration wait (s).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    _ecms_mfc(apm, "CO2", CO2flowrate_sccm, flow_ramp_sccm)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 1})
    _ecms_mfc(apm, "Caligas", Califlowrate_sccm, flow_ramp_sccm)
    _ecms_mfc(apm, "Caligassecond", Califlowrate_two_sccm, flow_ramp_sccm)
    apm.add(ORCH_server, "wait", {"waittime": MSsignal_quilibrium_time})
    return apm.planned_actions


@experiment(version=1)
def ECMS_sub_inertgascali(
    CO2flowrate_sccm: float = 5.0,
    Califlowrate_two_sccm: float = 0.0,  # Ar
    flow_ramp_sccm: float = 0,
    MSsignal_quilibrium_time: float = 300,
) -> list:
    """Set CO2 and second calibration-gas (inert) MFC flow rates and wait for the MS.

    Args:
        CO2flowrate_sccm: CO2 flow rate (sccm).
        Califlowrate_two_sccm: Second calibration-gas (inert) flow rate (sccm).
        flow_ramp_sccm: MFC ramp rate (sccm/s).
        MSsignal_quilibrium_time: Equilibration wait (s).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    _ecms_mfc(apm, "CO2", CO2flowrate_sccm, flow_ramp_sccm)
    _ecms_mfc(apm, "Caligassecond", Califlowrate_two_sccm, flow_ramp_sccm)
    apm.add(ORCH_server, "wait", {"waittime": MSsignal_quilibrium_time})
    return apm.planned_actions


@experiment(version=1)
def ECMS_sub_pulsecali(
    # CO2flowrate_sccm: float = 20.0,
    Califlowrate_sccm: float = 0.0,
    flow_ramp_sccm: float = 0,
    MSsignal_quilibrium_time: float = 300,
) -> list:
    """Set the calibration-gas MFC flow rate and wait for the MS to equilibrate.

    Args:
        Califlowrate_sccm: Calibration-gas flow rate (sccm).
        flow_ramp_sccm: MFC ramp rate (sccm/s).
        MSsignal_quilibrium_time: Equilibration wait (s).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    _ecms_mfc(apm, "Caligas", Califlowrate_sccm, flow_ramp_sccm)
    apm.add(ORCH_server, "wait", {"waittime": MSsignal_quilibrium_time})
    return apm.planned_actions


@experiment(version=1)
def ECMS_sub_preCA_CO2flow(
    MS_equilibrium_time: float = 10.0,
    total_MFC_flow_rate_sccm: float = 10.0,
    flow_change_duration_sec: list[float] = [10.0, 60.0],
    CO2_flow_rate_sccm: list[float] = [0.0, 10.0],
    # inert_gas_flow_rate_sccm: list[float] = [10.0,0.0,10.0]
) -> list:
    """Iterate through a CO2/inert-gas flow profile via the MFCs (no electrochemistry).

    For each step, the inert-gas flow rate is computed as
    ``total_MFC_flow_rate_sccm - CO2_flow_rate``.

    Args:
        MS_equilibrium_time: Final MS equilibration wait (s).
        total_MFC_flow_rate_sccm: Combined CO2 + inert MFC budget (sccm).
        flow_change_duration_sec: Step durations (s).
        CO2_flow_rate_sccm: CO2 flow rates per step (sccm).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    for CO2_flow_duration_sec, CO2_flow_rate in zip(
        flow_change_duration_sec, CO2_flow_rate_sccm
    ):
        apm.add(
            ORCH_server,
            "wait",
            {"waittime": CO2_flow_duration_sec},
            start_condition=asc.no_wait,
        )
        _ecms_mfc(apm, "CO2", CO2_flow_rate, 0.0, start=asc.wait_for_orch)
        _ecms_mfc(apm, "Caligassecond", total_MFC_flow_rate_sccm - CO2_flow_rate, 0.0)
    apm.add(ORCH_server, "wait", {"waittime": MS_equilibrium_time})
    return apm.planned_actions


@experiment(version=2)
def ECMS_sub_CA_CO2flow(
    WE_potential__V: float = 0.0,
    WE_versus: str = "ref",
    CA_duration_sec: float = 0.1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    ref_type: str = "leakless",
    pH: float = 6.8,
    MS_equilibrium_time: float = 10.0,
    total_MFC_flow_rate_sccm: float = 10.0,
    flow_change_duration_sec: list[float] = [60.0, 60.0, 60.0],
    CO2_flow_rate_sccm: list[float] = [0.0, 10.0, 0.0],
    # inert_gas_flow_rate_sccm: list[float] = [10.0,0.0,10.0]
    OCV_duration__s: float = 2.0,
) -> list:
    """Run a CA experiment in parallel with a stepped CO2/inert-gas flow profile.

    The flow steps run concurrently (``no_wait``) alongside the CA. For each
    step the inert-gas flow rate is computed as
    ``total_MFC_flow_rate_sccm - CO2_flow_rate``.

    Args:
        WE_potential__V: Working-electrode potential (V).
        WE_versus: ``"ref"``, ``"rhe"`` or ``"ocv"``.
        CA_duration_sec: CA duration (s).
        SampleRate: Acquisition interval (s).
        IErange: Gamry current-range setting.
        ref_offset__V: Reference offset (V).
        ref_type: Reference electrode key into ``REF_TABLE``.
        pH: Solution pH (used in RHE conversion).
        MS_equilibrium_time: Final MS equilibration wait (s).
        total_MFC_flow_rate_sccm: Combined CO2 + inert MFC budget (sccm).
        flow_change_duration_sec: Step durations (s).
        CO2_flow_rate_sccm: CO2 flow rates per step (sccm).
        OCV_duration__s: OCV measurement time (s); used only when ``WE_versus="ocv"``.

    Raises:
        ValueError: If ``WE_versus`` is not ``"ref"``, ``"rhe"`` or ``"ocv"``.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    _ecms_pstat(
        apm,
        "run_CA",
        {
            "Vval__V": _ecms_vs_ref(
                WE_potential__V, WE_versus, ref_offset__V, pH, ref_type
            ),
            "Tval__s": CA_duration_sec,
            "AcqInterval__s": SampleRate,
            "IErange": IErange,
            **_ecms_ocv_params(WE_versus, OCV_duration__s),
        },
        "CA",
    )
    apm.add_actions(
        ECMS_sub_preCA_CO2flow(
            MS_equilibrium_time=MS_equilibrium_time,
            total_MFC_flow_rate_sccm=total_MFC_flow_rate_sccm,
            flow_change_duration_sec=flow_change_duration_sec,
            CO2_flow_rate_sccm=CO2_flow_rate_sccm,
        )
    )
    return apm.planned_actions
