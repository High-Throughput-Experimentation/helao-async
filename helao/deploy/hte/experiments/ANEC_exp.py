"""Experiment library for the ANEC station.

Defines sub-experiments that build action lists for an orchestrator. Each
function takes an ``Experiment`` and returns the list of actions to enqueue.
Action targets are referenced by ``server_key`` strings (e.g. ``PSTAT``,
``MOTOR``, ``NI``, ``PAL``, ``IO``, ``TEC``, ``ORCH``) that must be present
in the orchestration config.
"""

__all__ = [
    "ANEC_sub_startup",
    "ANEC_sub_disengage",
    "ANEC_sub_drain_cell",
    "ANEC_sub_flush_fill_cell",
    "ANEC_sub_load_solid_only",
    "ANEC_sub_load_solid",
    "ANEC_sub_load_solid_and_clean_cell",
    "ANEC_sub_unload_cell",
    "ANEC_sub_unload_liquid",
    "ANEC_sub_normal_state",
    "ANEC_sub_GC_headspacealiquot_nomixing",
    "ANEC_sub_GC_preparation",
    "ANEC_sub_cleanup",
    "ANEC_sub_CP",
    "ANEC_sub_CA",
    # "ANEC_sub_HeatCA",
    "ANEC_sub_OCV",
    "ANEC_sub_liquidarchive",
    "ANEC_sub_aliquot",
    "ANEC_sub_aliquot_nomixing",
    "ANEC_sub_alloff",
    # "ANEC_sub_heatoff",
    # "ANEC_sub_setheat",
    "ANEC_sub_CV",
    # "ANEC_sub_HeatCV",
    "ANEC_sub_photo_CV",
    "ANEC_sub_photo_CA",
    "ANEC_sub_GCLiquid_analysis",
    "ANEC_sub_HPLCLiquid_analysis",
    "ANEC_sub_photo_LSV",
    "ANEC_sub_photo_CP",
]

###
from socket import gethostname
from typing import Optional

from helao.helpers.premodels import Experiment, ActionPlanMaker
from helao.deploy.hte.drivers.robot.pal_driver import PALtools
from helao.core.models.sample import SolidSample, LiquidSample
from helao.core.models.machine import MachineModel
from helao.core.models.action_start_condition import ActionStartCondition
from helao.core.models.process_contrib import ProcessContrib
from helao.helpers.constants import REF_TABLE
from helao.deploy.hte.drivers.motion.galil_motion_driver import (
    MoveModes,
    TransformationModes,
)
from helao.deploy.hte.drivers.io.enum import TriggerType
from helao.helpers.lib_decorators import experiment

# list valid experiment functions
EXPERIMENTS = __all__

ORCH_HOST = gethostname().lower()
PSTAT_server = MachineModel(server_name="PSTAT", machine_name=ORCH_HOST).as_dict()
MOTOR_server = MachineModel(server_name="MOTOR", machine_name=ORCH_HOST).as_dict()
NI_server = MachineModel(server_name="NI", machine_name=ORCH_HOST).as_dict()
ORCH_server = MachineModel(server_name="ORCH", machine_name=ORCH_HOST).as_dict()
PAL_server = MachineModel(server_name="PAL", machine_name=ORCH_HOST).as_dict()
IO_server = MachineModel(server_name="IO", machine_name=ORCH_HOST).as_dict()
TEC_server = MachineModel(server_name="TEC", machine_name=ORCH_HOST).as_dict()

toggle_triggertype = TriggerType.fallingedge


# z positions for ADSS cell
z_home = 0.0
# touches the bottom of cell
z_engage = 2.5
# moves it up to put pressure on seal
z_seal = 4.5


@experiment(version=1)
def ANEC_sub_startup(
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
    z_move_mm: float = 3.5,
) -> list:
    """Lower Z, move XY to a plate sample, then raise Z to the engage position.

    Args:
        experiment: Orchestrator-provided experiment context.
        solid_plate_id: Plate identifier of the legacy solid sample.
        solid_sample_no: Sample index on the plate.
        z_move_mm: Final absolute Z (motorxy frame).

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # move to z-down position
    apm.add(
        MOTOR_server,
        "move",
        {
            "d_mm": [0.1],
            "axis": ["z"],
            "mode": MoveModes.absolute,
            "transformation": TransformationModes.motorxy,
        },
        start_condition=ActionStartCondition.wait_for_all,
    )

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

    # move to z-up position
    apm.add(
        MOTOR_server,
        "move",
        {
            "d_mm": [z_move_mm],
            "axis": ["z"],
            "mode": MoveModes.absolute,
            "transformation": TransformationModes.motorxy,
        },
        start_condition=ActionStartCondition.wait_for_all,
    )

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def ANEC_sub_disengage() -> list:
    """Lower Z to disengage the electrochemical cell.

    Args:
        experiment: Orchestrator-provided experiment context.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # move to z-down position
    apm.add(
        MOTOR_server,
        "move",
        {
            "d_mm": [0.1],
            "axis": ["z"],
            "mode": MoveModes.absolute,
            "transformation": TransformationModes.motorxy,
        },
        start_condition=ActionStartCondition.wait_for_all,
    )

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def ANEC_sub_load_solid(
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
) -> list:
    """Load a legacy solid sample into the ``cell1_we`` PAL custom position.

    Args:
        experiment: Orchestrator-provided experiment context.
        solid_plate_id: Plate identifier of the legacy solid sample.
        solid_sample_no: Sample index on the plate.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()

    apm.add(
        PAL_server,
        "archive_custom_load",
        {
            "custom": "cell1_we",
            "load_sample_in": SolidSample(
                **{
                    "sample_no": solid_sample_no,
                    "plate_id": solid_plate_id,
                    "machine_name": "legacy",
                }
            ),
        },
    )

    return apm.planned_actions


@experiment(version=4)
def ANEC_sub_alloff(
) -> list:
    """Turn off both peristaltic pumps and close every NI gas/liquid valve.

    Args:
        experiment: Orchestrator-provided experiment context.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 0})
    apm.add(NI_server, "pump", {"pump": "PeriPump2", "on": 0})
    apm.add(NI_server, "pump", {"pump": "Direction", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "CO2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "down", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "up", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "liquid", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "atm", "on": 0})
    # apm.add(
    #     TEC_server,
    #     "cancel_record_tec",
    #     {}
    # )
    # apm.add(TEC_server, "disable_tec", {})

    return apm.planned_actions


@experiment(version=2)
def ANEC_sub_heatoff(
) -> list:
    """Cancel TEC recording and disable the TEC controller.

    Args:
        experiment: Orchestrator-provided experiment context.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()

    apm.add(TEC_server, "cancel_record_tec", {})
    apm.add(TEC_server, "disable_tec", {})

    return apm.planned_actions


@experiment(version=2)
def ANEC_sub_setheat(
    target_temperature_degc: float = 25.0,
) -> list:
    """Set a TEC setpoint, start non-blocking recording, enable TEC, wait until stable.

    Args:
        experiment: Orchestrator-provided experiment context.
        target_temperature_degc: TEC setpoint in degrees Celsius.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()
    apm.add(
        TEC_server,
        "set_temperature",
        {"target_temperature_degc": target_temperature_degc},
    )
    apm.add(
        TEC_server,
        "record_tec",
        {"duration": -1, "acquisition_rate": 0.2},
        nonblocking=True,
    )
    # =============================================================================
    apm.add(TEC_server, "enable_tec", {})
    apm.add(TEC_server, "wait_till_stable", {})

    return apm.planned_actions


@experiment(version=2)
def ANEC_sub_normal_state(
) -> list:
    """Drive the ANEC valves and pumps to the canonical idle/normal state.

    Resulting configuration:
        - Counter-electrode recirculation pump ON.
        - Working-electrode outlet pump ON.
        - Recirculation direction forward.
        - WE drain valve open, WE fill valve closed.
        - Liquid reservoir and gas flow-through valves closed.
        - WE CO2 inlet open.

    Args:
        experiment: Orchestrator-provided experiment context.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 1})
    apm.add(NI_server, "pump", {"pump": "Direction", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "down", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "CO2", "on": 1})
    apm.add(NI_server, "pump", {"pump": "PeriPump2", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "up", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "liquid", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "atm", "on": 0})

    return apm.planned_actions


@experiment(version=1)
def ANEC_sub_flush_fill_cell(
    liquid_flush_time: float = 70,
    co2_purge_time: float = 15,
    equilibration_time: float = 1.0,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: int = 1000,
) -> list:
    """Flush the cell with liquid, purge with CO2, then register an added liquid sample.

    Opens the fill path, reverses pump direction, flushes for
    ``liquid_flush_time`` seconds, switches to a CO2 purge, equilibrates,
    then archives a combined+diluted liquid into ``cell1_we``.

    Args:
        experiment: Orchestrator-provided experiment context.
        liquid_flush_time: Liquid flush duration (s).
        co2_purge_time: CO2 purge duration (s).
        equilibration_time: Post-purge equilibration time (s).
        reservoir_liquid_sample_no: Liquid sample number in the reservoir.
        volume_ul_cell_liquid: Volume archived into the cell (uL).

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()

    # Fill cell with liquid
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "down", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "up", "on": 1})
    apm.add(NI_server, "pump", {"pump": "Direction", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "CO2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "liquid", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": liquid_flush_time})
    # Stop flow and start CO2 purge
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "liquid", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "CO2", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": co2_purge_time})
    # Open headspace flow-through, stop purge
    apm.add(NI_server, "gasvalve", {"gasvalve": "atm", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "up", "on": 0})
    apm.add(NI_server, "pump", {"pump": "PeriPump2", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "CO2", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": equilibration_time})
    apm.add(NI_server, "gasvalve", {"gasvalve": "atm", "on": 0})
    # (3) Create liquid sample and add to assembly
    ## the hostname.lower() used in ORCH_HOST is incompatible with older liquids that were created with all-caps hostname
    liquid_sample_in = LiquidSample(
                sample_no=reservoir_liquid_sample_no, machine_name=gethostname().lower()
            )
    liquid_sample_in.global_label = liquid_sample_in.get_global_label()
    apm.add(
        PAL_server,
        "archive_custom_add_liquid",
        {
            "custom": "cell1_we",
            "source_liquid_in": liquid_sample_in,
            "volume_ml": volume_ul_cell_liquid,
            "combine_liquids": True,
            "dilute_liquids": True,
        },
    )
    return apm.planned_actions


@experiment(version=1)
def ANEC_sub_unload_cell() -> list:
    """Unload every sample currently tracked at the ``cell1_we`` PAL custom position.

    Args:
        experiment: Orchestrator-provided experiment context.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()
    apm.add(PAL_server, "archive_custom_unloadall", {})
    return apm.planned_actions


@experiment(version=1)
def ANEC_sub_unload_liquid(
) -> list:
    """Unload all samples then re-load the previously tracked solid at ``cell1_we``.

    Args:
        experiment: Orchestrator-provided experiment context.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()
    apm.add(
        PAL_server,
        "archive_custom_unloadall",
        {},
        to_global_params=["_unloaded_solid"],
    )
    apm.add(
        PAL_server,
        "archive_custom_load",
        {"custom": "cell1_we"},
        from_global_act_params={"_unloaded_solid": "load_sample_in"},
    )
    return apm.planned_actions


@experiment(version=3)
def ANEC_sub_drain_cell(
    drain_time: float = 60.0,
) -> list:
    """Return ANEC to normal state, unload the liquid, and wait for the cell to drain.

    Args:
        experiment: Orchestrator-provided experiment context.
        drain_time: Drain wait time (s).

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()
    apm.add_actions(ANEC_sub_normal_state())
    apm.add_actions(ANEC_sub_unload_liquid())
    apm.add(ORCH_server, "wait", {"waittime": drain_time})

    return apm.planned_actions


@experiment(version=1)
def ANEC_sub_cleanup(
    reservoir_liquid_sample_no: int = 1511,
) -> list:
    """Flush+fill the cell and then drain it.

    Args:
        experiment: Orchestrator-provided experiment context.
        reservoir_liquid_sample_no: Liquid sample number used to flush the cell.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add_actions(
        ANEC_sub_flush_fill_cell(
            reservoir_liquid_sample_no=reservoir_liquid_sample_no,
        )
    )
    apm.add_actions(ANEC_sub_drain_cell())
    return apm.planned_actions


@experiment(version=1)
def ANEC_sub_GC_headspacealiquot_nomixing(
    toolGC: str = "HS 2",
    volume_ul_GC: int = 300,
) -> list:
    """Stop PeriPump1 and sample the cell1_we headspace into the GC (no mixing pass).

    Args:
        experiment: Orchestrator-provided experiment context.
        toolGC: PAL headspace tool identifier.
        volume_ul_GC: GC injection volume (uL).

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 0})
    apm.add(
        PAL_server,
        "PAL_ANEC_GC",
        {
            "toolGC": toolGC,
            "source": "cell1_we",
            "volume_ul_GC": volume_ul_GC,
        },
        process_finish=True,
        technique_name=["headspace_GC_back_analysis", "headspace_GC_front_analysis"],
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    return apm.planned_actions


@experiment(version=1)
def ANEC_sub_GC_preparation(
    toolGC: str = "HS 2",
    volume_ul_GC: int = 300,
) -> list:
    """Cycle pump direction to mix cell contents and then sample headspace into GC.

    Performs two reverse/forward direction cycles with intervening waits to
    mix, stops PeriPump1, and runs ``PAL_ANEC_GC`` for the GC headspace
    injection.

    Args:
        experiment: Orchestrator-provided experiment context.
        toolGC: PAL headspace tool identifier.
        volume_ul_GC: GC injection volume (uL).

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(NI_server, "pump", {"pump": "Direction", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": 60})
    apm.add(NI_server, "pump", {"pump": "Direction", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": 30})
    apm.add(NI_server, "pump", {"pump": "Direction", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": 60})
    apm.add(NI_server, "pump", {"pump": "Direction", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": 30})
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 0})
    apm.add(
        PAL_server,
        "PAL_ANEC_GC",
        {
            "toolGC": toolGC,
            "source": "cell1_we",
            "volume_ul_GC": volume_ul_GC,
        },
        process_finish=True,
        technique_name=["headspace_GC_back_analysis", "headspace_GC_front_analysis"],
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    return apm.planned_actions


@experiment(version=1)
def ANEC_sub_load_solid_only(
    solid_plate_id: int = 1,
    solid_sample_no: int = 1,
) -> list:
    """Unload the cell and load a legacy solid sample into ``cell1_we``.

    Args:
        experiment: Orchestrator-provided experiment context.
        solid_plate_id: Plate identifier of the legacy solid sample.
        solid_sample_no: Sample index on the plate.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()
    apm.add_actions(ANEC_sub_unload_cell())
    apm.add(
        PAL_server,
        "archive_custom_load",
        {
            "custom": "cell1_we",
            "load_sample_in": SolidSample(
                sample_no=solid_sample_no,
                plate_id=solid_plate_id,
                machine_name="legacy",
            ),
        },
    )
    return apm.planned_actions


@experiment(version=1)
def ANEC_sub_load_solid_and_clean_cell(
    solid_plate_id: int = 1,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    recirculation_time: float = 60,
    toolGC: str = "HS 2",
    volume_ul_GC: int = 300,
) -> list:
    """Unload, load solid, drain+flush, recirculate, run GC, then drain again.

    Args:
        experiment: Orchestrator-provided experiment context.
        solid_plate_id: Plate identifier of the legacy solid sample.
        solid_sample_no: Sample index on the plate.
        reservoir_liquid_sample_no: Liquid sample number used for flushing.
        recirculation_time: Recirculation duration (s) before GC.
        toolGC: PAL headspace tool identifier (resolved through ``PALtools``).
        volume_ul_GC: GC injection volume (uL).

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()
    apm.add_actions(ANEC_sub_unload_cell())
    apm.add(
        PAL_server,
        "archive_custom_load",
        {
            "custom": "cell1_we",
            "load_sample_in": SolidSample(
                sample_no=solid_sample_no,
                plate_id=solid_plate_id,
                machine_name="legacy",
            ),
        },
    )
    apm.add_actions(ANEC_sub_drain_cell())
    apm.add_actions(
        ANEC_sub_flush_fill_cell(
            reservoir_liquid_sample_no=reservoir_liquid_sample_no,
        )
    )
    apm.add(ORCH_server, "wait", {"waittime": recirculation_time})
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 0})
    apm.add(
        PAL_server,
        "PAL_ANEC_GC",
        {
            "toolGC": PALtools(toolGC),
            "source": "cell1_we",
            "volume_ul_GC": volume_ul_GC,
        },
        process_finish=True,
        technique_name=["headspace_GC_back_analysis", "headspace_GC_front_analysis"],
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 1})
    apm.add_actions(ANEC_sub_drain_cell())
    return apm.planned_actions


@experiment(version=1)
def ANEC_sub_liquidarchive(
    toolarchive: str = "LS 3",
    volume_ul_archive: int = 500,
    wash1: bool = True,
    wash2: bool = True,
    wash3: bool = True,
    wash4: bool = False,
) -> list:
    """Stop PeriPump1, archive a liquid aliquot from the cell to a PAL tray, restart pump.

    Args:
        experiment: Orchestrator-provided experiment context.
        toolarchive: PAL liquid syringe tool identifier.
        volume_ul_archive: Archived volume (uL).
        wash1: Enable PAL wash slot 1.
        wash2: Enable PAL wash slot 2.
        wash3: Enable PAL wash slot 3.
        wash4: Enable PAL wash slot 4.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # first circulate the liquid back and forth
    # e.g. mix it by reversing the flow a few times

    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 0})
    apm.add(
        PAL_server,
        "PAL_archive",
        {
            "tool": toolarchive,
            "source": "cell1_we",
            "volume_ul": volume_ul_archive,
            "wash1": wash1,
            "wash2": wash2,
            "wash3": wash3,
            "wash4": wash4,
        },
        process_finish=True,
        technique_name=[
            "liquid_product_archive",
        ],
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 1})

    return apm.planned_actions


@experiment(version=1)
def ANEC_sub_aliquot_nomixing(
    toolGC: str = "HS 2",
    toolarchive: str = "LS 3",
    volume_ul_GC: int = 300,
    volume_ul_archive: int = 500,
    wash1: bool = True,
    wash2: bool = True,
    wash3: bool = True,
    wash4: bool = False,
) -> list:
    """Take a combined GC + liquid-archive aliquot from the cell without pre-mixing.

    Args:
        experiment: Orchestrator-provided experiment context.
        toolGC: PAL headspace tool identifier.
        toolarchive: PAL liquid archive tool identifier.
        volume_ul_GC: GC injection volume (uL).
        volume_ul_archive: Archived liquid volume (uL).
        wash1: Enable PAL wash slot 1.
        wash2: Enable PAL wash slot 2.
        wash3: Enable PAL wash slot 3.
        wash4: Enable PAL wash slot 4.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # first circulate the liquid back and forth
    # e.g. mix it by reversing the flow a few times
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 0})
    apm.add(
        PAL_server,
        "PAL_ANEC_aliquot",
        {
            "toolGC": toolGC,
            "toolarchive": toolarchive,
            "source": "cell1_we",
            "volume_ul_GC": volume_ul_GC,
            "volume_ul_archive": volume_ul_archive,
            "wash1": wash1,
            "wash2": wash2,
            "wash3": wash3,
            "wash4": wash4,
        },
        process_finish=True,
        technique_name=[
            "headspace_GC_back_analysis",
            "headspace_GC_front_analysis",
            "liquid_product_archive",
        ],
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 1})

    return apm.planned_actions


@experiment(version=1)
def ANEC_sub_aliquot(
    toolGC: str = "HS 2",
    toolarchive: str = "LS 3",
    volume_ul_GC: int = 300,
    volume_ul_archive: int = 500,
    wash1: bool = True,
    wash2: bool = True,
    wash3: bool = True,
    wash4: bool = False,
) -> list:
    """Mix the cell by reversing the pump, then take a GC + liquid-archive aliquot.

    Args:
        experiment: Orchestrator-provided experiment context.
        toolGC: PAL headspace tool identifier.
        toolarchive: PAL liquid archive tool identifier.
        volume_ul_GC: GC injection volume (uL).
        volume_ul_archive: Archived liquid volume (uL).
        wash1: Enable PAL wash slot 1.
        wash2: Enable PAL wash slot 2.
        wash3: Enable PAL wash slot 3.
        wash4: Enable PAL wash slot 4.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # first circulate the liquid back and forth
    # e.g. mix it by reversing the flow a few times
    apm.add(NI_server, "pump", {"pump": "Direction", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": 60})
    apm.add(NI_server, "pump", {"pump": "Direction", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": 30})
    apm.add(NI_server, "pump", {"pump": "Direction", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": 60})
    apm.add(NI_server, "pump", {"pump": "Direction", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": 30})
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 0})
    apm.add(
        PAL_server,
        "PAL_ANEC_aliquot",
        {
            "toolGC": toolGC,
            "toolarchive": toolarchive,
            "source": "cell1_we",
            "volume_ul_GC": volume_ul_GC,
            "volume_ul_archive": volume_ul_archive,
            "wash1": wash1,
            "wash2": wash2,
            "wash3": wash3,
            "wash4": wash4,
        },
        process_finish=True,
        technique_name=[
            "headspace_GC_back_analysis",
            "headspace_GC_front_analysis",
            "liquid_product_archive",
        ],
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 1})

    return apm.planned_actions


@experiment(version=1)
def ANEC_sub_CP(
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CP_current: float = 0.0,
    SampleRate: float = 0.01,
    CP_duration_sec: float = 60,
    IErange: str = "auto",
) -> list:
    """Run a chronopotentiometry (CP) experiment with the cell sample tracked.

    Args:
        experiment: Orchestrator-provided experiment context.
        WE_versus: Reference frame label.
        ref_type: Reference electrode key into ``REF_TABLE``.
        pH: Solution pH.
        CP_current: Applied current (A).
        SampleRate: Acquisition interval (s).
        CP_duration_sec: CP duration (s).
        IErange: Gamry current-range setting.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    if int(round(toggle_illum_time)) == -1:
        toggle_illum_time = CP_duration_sec

    # get sample for gamry
    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {"custom": "cell1_we"},
        to_global_params=["_fast_samples_in"],
    )

    apm.add(
        PSTAT_server,
        "run_CP",
        {
            "Ival": CP_current,
            "Tval__s": CP_duration_sec,
            "AcqInterval__s": SampleRate,
            "IErange": IErange,
        },
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        technique_name="CP",
        process_finish=True,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def ANEC_sub_CA(
    WE_potential__V: float = 0.0,
    WE_versus: str = "ref",
    CA_duration_sec: float = 0.1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    ref_type: str = "leakless",
    pH: float = 6.8,
) -> list:
    """Run a chronoamperometry (CA) experiment versus REF or RHE.

    Args:
        experiment: Orchestrator-provided experiment context.
        WE_potential__V: Working-electrode potential (V).
        WE_versus: ``"ref"`` or ``"rhe"``.
        CA_duration_sec: CA duration (s).
        SampleRate: Acquisition interval (s).
        IErange: Gamry current-range setting.
        ref_offset__V: Reference offset (V).
        ref_type: Reference electrode key into ``REF_TABLE``.
        pH: Solution pH (used in RHE conversion).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    if WE_versus == "ref":
        potential_vsRef = WE_potential__V - 1.0 * ref_offset__V
    elif WE_versus == "rhe":
        potential_vsRef = (
            WE_potential__V - 1.0 * ref_offset__V - 0.059 * pH - REF_TABLE[ref_type]
        )
    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {"custom": "cell1_we"},
        to_global_params=["_fast_samples_in"],
    )
    apm.add(
        PSTAT_server,
        "run_CA",
        {
            "Vval__V": potential_vsRef,
            "Tval__s": CA_duration_sec,
            "AcqInterval__s": SampleRate,
            "IErange": IErange,
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

    # apm.add(ORCH_server, "wait", {"waittime": 10})

    return apm.planned_actions


@experiment(version=2)
def ANEC_sub_HeatCA(
    WE_potential__V: float = 0.0,
    WE_versus: str = "ref",
    CA_duration_sec: float = 0.1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    ref_type: str = "leakless",
    pH: float = 6.8,
    target_temperature_degc: float = 25.0,
) -> list:
    """Stabilize TEC at a target temperature then run a CA experiment.

    Args:
        experiment: Orchestrator-provided experiment context.
        WE_potential__V: Working-electrode potential (V).
        WE_versus: ``"ref"`` or ``"rhe"``.
        CA_duration_sec: CA duration (s).
        SampleRate: Acquisition interval (s).
        IErange: Gamry current-range setting.
        ref_offset__V: Reference offset (V).
        ref_type: Reference electrode key into ``REF_TABLE``.
        pH: Solution pH (used in RHE conversion).
        target_temperature_degc: TEC setpoint (deg C).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    if WE_versus == "ref":
        potential_vsRef = WE_potential__V - 1.0 * ref_offset__V
    elif WE_versus == "rhe":
        potential_vsRef = (
            WE_potential__V - 1.0 * ref_offset__V - 0.059 * pH - REF_TABLE[ref_type]
        )
    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {"custom": "cell1_we"},
        to_global_params=["_fast_samples_in"],
    )
    apm.add(
        TEC_server,
        "set_temperature",
        {"target_temperature_degc": target_temperature_degc},
    )
    apm.add(
        TEC_server,
        "record_tec",
        {"duration": -1, "acquisition_rate": 0.2},
        nonblocking=True,
    )
    apm.add(TEC_server, "enable_tec", {})
    apm.add(TEC_server, "wait_till_stable", {})
    apm.add(
        PSTAT_server,
        "run_CA",
        {
            "Vval__V": potential_vsRef,
            "Tval__s": CA_duration_sec,
            "AcqInterval__s": SampleRate,
            "IErange": IErange,
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
    # apm.add(ORCH_server, "wait", {"waittime": 10})
    apm.add(TEC_server, "cancel_record_tec", {})

    return apm.planned_actions


@experiment(version=1)
def ANEC_sub_OCV(
    Tval__s: float = 900.0,
    IErange: str = "auto",
) -> list:
    """Run an open-circuit voltage measurement with the cell sample tracked.

    Args:
        experiment: Orchestrator-provided experiment context.
        Tval__s: OCV duration (s).
        IErange: Gamry current-range setting.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # get sample for gamry
    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {
            "custom": "cell1_we",
        },
        to_global_params=[
            "_fast_samples_in"
        ],  # save new liquid_sample_no of eche cell to globals
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
    )

    # OCV
    apm.add(
        PSTAT_server,
        "run_OCV",
        {
            "Tval__s": Tval__s,
            "SampleRate": 0.05,
            "IErange": IErange,
        },
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        technique_name="CP",
        process_finish=True,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    return apm.planned_actions  # returns complete action list to orch


@experiment(version=2)
def ANEC_sub_photo_CA(
    WE_potential__V: float = 0.0,
    WE_versus: str = "ref",
    CA_duration_sec: float = 0.1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    gamrychannelwait: int = -1,
    gamrychannelsend: int = 1,
    ref_offset__V: float = 0.0,
    ref_type: str = "leakless",
    pH: float = 6.8,
    illumination_source: str = "Thorlab_led",
    illumination_wavelength: float = 450.0,
    illumination_intensity: float = 9.0,
    illumination_intensity_date: str = "n/a",
    illumination_side: str = "front",
    toggle_dark_time_init: float = 0.0,
    toggle_illum_duty: float = 0.5,
    toggle_illum_period: float = 2.0,
    toggle_illum_time: float = -1,
) -> list:
    """Run a CA experiment with hardware-triggered LED toggling via the Galil IO.

    Programs a digital cycle on ``gamry_ttl0`` to drive the configured LED
    source for ``toggle_illum_time`` seconds (defaulting to the CA duration
    when ``-1``), runs CA with TTL handshake, then stops the digital cycle.

    Args:
        experiment: Orchestrator-provided experiment context.
        WE_potential__V: Working-electrode potential (V).
        WE_versus: ``"ref"`` or ``"rhe"``.
        CA_duration_sec: CA duration (s).
        SampleRate: Acquisition interval (s).
        IErange: Gamry current-range setting.
        gamrychannelwait: TTL channel to wait on (-1 disables).
        gamrychannelsend: TTL channel to send on (-1 disables).
        ref_offset__V: Reference offset (V).
        ref_type: Reference electrode key into ``REF_TABLE``.
        pH: Solution pH (used in RHE conversion).
        illumination_source: IO output name driving the LED.
        illumination_wavelength: LED wavelength (nm).
        illumination_intensity: LED intensity setting.
        illumination_intensity_date: Provenance date string for intensity.
        illumination_side: ``"front"`` or ``"back"``.
        toggle_dark_time_init: Initial dark delay (s).
        toggle_illum_duty: Illumination duty cycle.
        toggle_illum_period: Toggle period (s).
        toggle_illum_time: Total toggle duration (s); ``-1`` matches CA.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    if int(round(toggle_illum_time)) == -1:
        toggle_illum_time = CA_duration_sec
    if WE_versus == "ref":
        potential_vsRef = WE_potential__V - 1.0 * ref_offset__V
    elif WE_versus == "rhe":
        potential_vsRef = (
            WE_potential__V - 1.0 * ref_offset__V - 0.059 * pH - REF_TABLE[ref_type]
        )
    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {"custom": "cell1_we"},
        to_global_params=["_fast_samples_in"],
    )
    #    apm.add(NI_server, "led", {"led":"led", "on": 1})
    # adding IO server for Galil LED toggle control instead of NI
    apm.add(
        IO_server,
        "set_digital_cycle",
        {
            "trigger_name": "gamry_ttl0",
            "triggertype": toggle_triggertype,
            "out_name": illumination_source,
            "out_name_gamry": "gamry_aux",
            "toggle_init_delay": toggle_dark_time_init,
            "toggle_duty": toggle_illum_duty,
            "toggle_period": toggle_illum_period,
            "toggle_duration": toggle_illum_time,
        },
        process_finish=False,
        process_contrib=[
            ProcessContrib.files,
        ],
    )

    apm.add(
        PSTAT_server,
        "run_CA",
        {
            "Vval__V": potential_vsRef,
            "Tval__s": CA_duration_sec,
            "AcqInterval__s": SampleRate,
            "TTLwait": gamrychannelwait,  # -1 disables, else select TTL 0-3
            "TTLsend": gamrychannelsend,  # -1 disables, else select TTL 0-3
            "IErange": IErange,
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
    apm.add(
        IO_server,
        "stop_digital_cycle",
        {},
    )
    # #    apm.add(NI_server, "led", {"led":"led", "on": 0})
    # apm.add(ORCH_server, "wait", {"waittime": 10})

    return apm.planned_actions


@experiment(version=1)
def ANEC_sub_CV(
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    WE_potential_init__V: float = 0.0,
    WE_potential_apex1__V: float = -1.0,
    WE_potential_apex2__V: float = -0.5,
    WE_potential_final__V: float = -0.5,
    ScanRate_V_s: float = 0.01,
    Cycles: int = 1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
) -> list:
    """Run a cyclic voltammetry (CV) experiment versus REF or RHE.

    Args:
        experiment: Orchestrator-provided experiment context.
        WE_versus: ``"ref"`` or ``"rhe"``.
        ref_type: Reference electrode key into ``REF_TABLE``.
        pH: Solution pH (used in RHE conversion).
        WE_potential_init__V: Initial potential (V).
        WE_potential_apex1__V: Apex 1 potential (V).
        WE_potential_apex2__V: Apex 2 potential (V).
        WE_potential_final__V: Final potential (V).
        ScanRate_V_s: Scan rate (V/s).
        Cycles: CV cycle count.
        SampleRate: Acquisition interval (s).
        IErange: Gamry current-range setting.
        ref_offset__V: Reference offset (V).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    if WE_versus == "ref":
        potential_init_vsRef = WE_potential_init__V - 1.0 * ref_offset__V
        potential_apex1_vsRef = WE_potential_apex1__V - 1.0 * ref_offset__V
        potential_apex2_vsRef = WE_potential_apex2__V - 1.0 * ref_offset__V
        potential_final_vsRef = WE_potential_final__V - 1.0 * ref_offset__V
    elif WE_versus == "rhe":
        potential_init_vsRef = (
            WE_potential_init__V
            - 1.0 * ref_offset__V
            - 0.059 * pH
            - REF_TABLE[ref_type]
        )
        potential_apex1_vsRef = (
            WE_potential_apex1__V
            - 1.0 * ref_offset__V
            - 0.059 * pH
            - REF_TABLE[ref_type]
        )
        potential_apex2_vsRef = (
            WE_potential_apex2__V
            - 1.0 * ref_offset__V
            - 0.059 * pH
            - REF_TABLE[ref_type]
        )
        potential_final_vsRef = (
            WE_potential_final__V
            - 1.0 * ref_offset__V
            - 0.059 * pH
            - REF_TABLE[ref_type]
        )

    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {"custom": "cell1_we"},
        to_global_params=["_fast_samples_in"],
    )

    apm.add(
        PSTAT_server,
        "run_CV",
        {
            "Vinit__V": potential_init_vsRef,
            "Vapex1__V": potential_apex1_vsRef,
            "Vapex2__V": potential_apex2_vsRef,
            "Vfinal__V": potential_final_vsRef,
            "ScanRate__V_s": ScanRate_V_s,
            "Cycles": Cycles,
            "AcqInterval__s": SampleRate,
            "IErange": IErange,
        },
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        process_finish=True,
        technique_name=["CV"],
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )

    # apm.add(ORCH_server, "wait", {"waittime": 10})

    return apm.planned_actions


@experiment(version=2)
def ANEC_sub_HeatCV(
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    WE_potential_init__V: float = 0.0,
    WE_potential_apex1__V: float = -1.0,
    WE_potential_apex2__V: float = -0.5,
    WE_potential_final__V: float = -0.5,
    ScanRate_V_s: float = 0.01,
    Cycles: int = 1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    target_temperature_degc: float = 25.0,
) -> list:
    """Stabilize TEC at a target temperature then run a CV experiment.

    Args:
        experiment: Orchestrator-provided experiment context.
        WE_versus: ``"ref"`` or ``"rhe"``.
        ref_type: Reference electrode key into ``REF_TABLE``.
        pH: Solution pH (used in RHE conversion).
        WE_potential_init__V: Initial potential (V).
        WE_potential_apex1__V: Apex 1 potential (V).
        WE_potential_apex2__V: Apex 2 potential (V).
        WE_potential_final__V: Final potential (V).
        ScanRate_V_s: Scan rate (V/s).
        Cycles: CV cycle count.
        SampleRate: Acquisition interval (s).
        IErange: Gamry current-range setting.
        ref_offset__V: Reference offset (V).
        target_temperature_degc: TEC setpoint (deg C).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    if WE_versus == "ref":
        potential_init_vsRef = WE_potential_init__V - 1.0 * ref_offset__V
        potential_apex1_vsRef = WE_potential_apex1__V - 1.0 * ref_offset__V
        potential_apex2_vsRef = WE_potential_apex2__V - 1.0 * ref_offset__V
        potential_final_vsRef = WE_potential_final__V - 1.0 * ref_offset__V
    elif WE_versus == "rhe":
        potential_init_vsRef = (
            WE_potential_init__V
            - 1.0 * ref_offset__V
            - 0.059 * pH
            - REF_TABLE[ref_type]
        )
        potential_apex1_vsRef = (
            WE_potential_apex1__V
            - 1.0 * ref_offset__V
            - 0.059 * pH
            - REF_TABLE[ref_type]
        )
        potential_apex2_vsRef = (
            WE_potential_apex2__V
            - 1.0 * ref_offset__V
            - 0.059 * pH
            - REF_TABLE[ref_type]
        )
        potential_final_vsRef = (
            WE_potential_final__V
            - 1.0 * ref_offset__V
            - 0.059 * pH
            - REF_TABLE[ref_type]
        )

    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {"custom": "cell1_we"},
        to_global_params=["_fast_samples_in"],
    )

    apm.add(
        TEC_server,
        "set_temperature",
        {"target_temperature_degc": target_temperature_degc},
    )
    apm.add(
        TEC_server,
        "record_tec",
        {"duration": -1, "acquisition_rate": 0.2},
        nonblocking=True,
    )
    apm.add(TEC_server, "enable_tec", {})

    apm.add(TEC_server, "wait_till_stable", {})

    apm.add(
        PSTAT_server,
        "run_CV",
        {
            "Vinit__V": potential_init_vsRef,
            "Vapex1__V": potential_apex1_vsRef,
            "Vapex2__V": potential_apex2_vsRef,
            "Vfinal__V": potential_final_vsRef,
            "ScanRate__V_s": ScanRate_V_s,
            "Cycles": Cycles,
            "AcqInterval__s": SampleRate,
            "IErange": IErange,
        },
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        process_finish=True,
        technique_name=["CV"],
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )

    # apm.add(ORCH_server, "wait", {"waittime": 10})
    apm.add(TEC_server, "cancel_record_tec", {})

    return apm.planned_actions


@experiment(version=1)
def ANEC_sub_photo_CV(
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    WE_potential_init__V: float = 0.0,
    WE_potential_apex1__V: float = -1.0,
    WE_potential_apex2__V: float = -0.5,
    WE_potential_final__V: float = -0.5,
    ScanRate_V_s: float = 0.01,
    Cycles: int = 1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    gamrychannelwait: int = -1,
    gamrychannelsend: int = 1,
    ref_offset__V: float = 0.0,
    illumination_source: str = "Thorlab_led",
    illumination_wavelength: float = 450.0,
    illumination_intensity: float = 9.0,
    illumination_intensity_date: str = "n/a",
    illumination_side: str = "front",
    toggle_dark_time_init: float = 0.0,
    toggle_illum_duty: float = 0.5,
    toggle_illum_period: float = 2.0,
    toggle_illum_time: float = -1,
) -> list:
    """Run a CV experiment with hardware-triggered LED toggling via the Galil IO.

    Computes the CV total duration from the four vertices and ``Cycles`` to
    set the default ``toggle_illum_time`` when it is ``-1``, programs a
    digital cycle, runs CV with TTL handshake, then stops the digital cycle.

    Args:
        experiment: Orchestrator-provided experiment context.
        WE_versus: ``"ref"`` or ``"rhe"``.
        ref_type: Reference electrode key into ``REF_TABLE``.
        pH: Solution pH.
        WE_potential_init__V: Initial potential (V).
        WE_potential_apex1__V: Apex 1 potential (V).
        WE_potential_apex2__V: Apex 2 potential (V).
        WE_potential_final__V: Final potential (V).
        ScanRate_V_s: Scan rate (V/s).
        Cycles: CV cycle count.
        SampleRate: Acquisition interval (s).
        IErange: Gamry current-range setting.
        gamrychannelwait: TTL channel to wait on (-1 disables).
        gamrychannelsend: TTL channel to send on (-1 disables).
        ref_offset__V: Reference offset (V).
        illumination_source: IO output name driving the LED.
        illumination_wavelength: LED wavelength (nm).
        illumination_intensity: LED intensity setting.
        illumination_intensity_date: Provenance date string for intensity.
        illumination_side: ``"front"`` or ``"back"``.
        toggle_dark_time_init: Initial dark delay (s).
        toggle_illum_duty: Illumination duty cycle.
        toggle_illum_period: Toggle period (s).
        toggle_illum_time: Total toggle duration (s); ``-1`` matches the CV.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    CV_duration_sec = abs(WE_potential_apex1__V - WE_potential_init__V) / ScanRate_V_s
    CV_duration_sec += abs(WE_potential_final__V - WE_potential_apex2__V) / ScanRate_V_s
    CV_duration_sec += (
        abs(WE_potential_apex2__V - WE_potential_apex1__V)
        / ScanRate_V_s
        #        * Cycles
    )
    CV_duration_sec += (
        abs(WE_potential_apex2__V - WE_potential_apex1__V)
        / ScanRate_V_s
        * 2.0
        * (Cycles - 1)
    )

    if int(round(toggle_illum_time)) == -1:
        toggle_illum_time = CV_duration_sec
    if WE_versus == "ref":
        potential_init_vsRef = WE_potential_init__V - 1.0 * ref_offset__V
        potential_apex1_vsRef = WE_potential_apex1__V - 1.0 * ref_offset__V
        potential_apex2_vsRef = WE_potential_apex2__V - 1.0 * ref_offset__V
        potential_final_vsRef = WE_potential_final__V - 1.0 * ref_offset__V
    elif WE_versus == "rhe":
        potential_init_vsRef = (
            WE_potential_init__V
            - 1.0 * ref_offset__V
            - 0.059 * pH
            - REF_TABLE[ref_type]
        )
        potential_apex1_vsRef = (
            WE_potential_apex1__V
            - 1.0 * ref_offset__V
            - 0.059 * pH
            - REF_TABLE[ref_type]
        )
        potential_apex2_vsRef = (
            WE_potential_apex2__V
            - 1.0 * ref_offset__V
            - 0.059 * pH
            - REF_TABLE[ref_type]
        )
        potential_final_vsRef = (
            WE_potential_final__V
            - 1.0 * ref_offset__V
            - 0.059 * pH
            - REF_TABLE[ref_type]
        )

    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {"custom": "cell1_we"},
        to_global_params=["_fast_samples_in"],
    )

    #    apm.add(NI_server, "led", {"led":"led", "on": 1})
    # adding IO server for Galil LED toggle control instead of NI
    apm.add(
        IO_server,
        "set_digital_cycle",
        {
            "trigger_name": "gamry_ttl0",
            "triggertype": toggle_triggertype,
            "out_name": illumination_source,
            "out_name_gamry": "gamry_aux",
            "toggle_init_delay": toggle_dark_time_init,
            "toggle_duty": toggle_illum_duty,
            "toggle_period": toggle_illum_period,
            "toggle_duration": toggle_illum_time,
            #                "stop_via_ttl": False,
        },
        process_finish=False,
        process_contrib=[
            ProcessContrib.files,
        ],
    )

    apm.add(
        PSTAT_server,
        "run_CV",
        {
            "Vinit__V": potential_init_vsRef,
            "Vapex1__V": potential_apex1_vsRef,
            "Vapex2__V": potential_apex2_vsRef,
            "Vfinal__V": potential_final_vsRef,
            "ScanRate__V_s": ScanRate_V_s,
            "Cycles": Cycles,
            "AcqInterval__s": SampleRate,
            "TTLwait": gamrychannelwait,  # -1 disables, else select TTL 0-3
            "TTLsend": gamrychannelsend,  # -1 disables, else select TTL 0-3
            "IErange": IErange,
        },
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        process_finish=True,
        technique_name="CV",
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    apm.add(
        IO_server,
        "stop_digital_cycle",
        {},
    )
    # apm.add(ORCH_server, "wait", {"waittime": 10})

    return apm.planned_actions


@experiment(version=1)
def ANEC_sub_GCLiquid_analysis(
    # startGC: Optional[bool] = None,
    # sampletype: Optional[str] = None,
    tool: str = "LS 1",
    source_tray: int = 2,
    source_slot: int = 1,
    source_vial: int = 1,
    dest: str = "Injector 1",
    volume_ul: int = 2,
    wash1: bool = True,
    wash2: bool = True,
    wash3: bool = True,
    wash4: bool = False,
    GC_analysis_time: float = 520.0,
) -> list:
    """Inject a liquid aliquot from a PAL tray vial into the GC injector and wait.

    Args:
        experiment: Orchestrator-provided experiment context.
        tool: PAL liquid syringe tool identifier.
        source_tray: PAL tray index.
        source_slot: PAL slot index.
        source_vial: PAL vial index.
        dest: GC injector custom-position name.
        volume_ul: Injection volume (uL).
        wash1: Enable PAL wash slot 1.
        wash2: Enable PAL wash slot 2.
        wash3: Enable PAL wash slot 3.
        wash4: Enable PAL wash slot 4.
        GC_analysis_time: Post-injection wait (s).

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(
        PAL_server,
        "PAL_injection_tray_GC",
        {
            "tool": tool,
            "source_tray": source_tray,
            "source_slot": source_slot,
            "source_vial": source_vial,
            "dest": dest,
            "volume_ul": volume_ul,
            "wash1": wash1,
            "wash2": wash2,
            "wash3": wash3,
            "wash4": wash4,
        },
        process_finish=True,
        technique_name=["liquid_GC_front_analysis"],
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    apm.add(ORCH_server, "wait", {"waittime": GC_analysis_time})
    return apm.planned_actions


@experiment(version=1)
def ANEC_sub_HPLCLiquid_analysis(
    # startGC: Optional[bool] = None,
    # sampletype: Optional[str] = None,
    tool: str = "LS 1",
    source_tray: int = 2,
    source_slot: int = 1,
    source_vial: int = 1,
    dest: str = "LCInjector1",
    volume_ul: int = 25,
    wash1: bool = True,
    wash2: bool = True,
    wash3: bool = True,
    wash4: bool = False,
    HPLC_analysis_time: float = 1800,
) -> list:
    """Inject a liquid aliquot from a PAL tray vial into the HPLC injector and wait.

    Args:
        experiment: Orchestrator-provided experiment context.
        tool: PAL liquid syringe tool identifier.
        source_tray: PAL tray index.
        source_slot: PAL slot index.
        source_vial: PAL vial index.
        dest: HPLC injector custom-position name.
        volume_ul: Injection volume (uL).
        wash1: Enable PAL wash slot 1.
        wash2: Enable PAL wash slot 2.
        wash3: Enable PAL wash slot 3.
        wash4: Enable PAL wash slot 4.
        HPLC_analysis_time: Post-injection wait (s).

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(
        PAL_server,
        "PAL_injection_tray_HPLC",
        {
            "tool": tool,
            "source_tray": source_tray,
            "source_slot": source_slot,
            "source_vial": source_vial,
            "dest": dest,
            "volume_ul": volume_ul,
            "wash1": wash1,
            "wash2": wash2,
            "wash3": wash3,
            "wash4": wash4,
        },
        process_finish=True,
        technique_name=["liquid_HPLC_analysis"],
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    apm.add(ORCH_server, "wait", {"waittime": HPLC_analysis_time})
    return apm.planned_actions


@experiment(version=1)
def ANEC_sub_photo_LSV(
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    WE_potential_init__V: float = 0.0,
    WE_potential_apex1__V: float = -1.0,
    ScanRate_V_s: float = 0.01,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    gamrychannelwait: int = -1,
    gamrychannelsend: int = 1,
    ref_offset__V: float = 0.0,
    illumination_source: str = "Thorlab_led",
    illumination_wavelength: float = 450.0,
    illumination_intensity: float = 9.0,
    illumination_intensity_date: str = "n/a",
    illumination_side: str = "front",
    toggle_dark_time_init: float = 0.0,
    toggle_illum_duty: float = 0.5,
    toggle_illum_period: float = 2.0,
    toggle_illum_time: float = -1,
) -> list:
    """Run a linear sweep voltammetry (LSV) experiment with hardware-triggered LED toggling.

    Estimates the LSV duration from the init/apex potentials and the scan
    rate to default ``toggle_illum_time`` when it is ``-1``, programs the
    Galil digital cycle, runs ``run_LSV`` with TTL handshake, and stops the
    digital cycle.

    Args:
        experiment: Orchestrator-provided experiment context.
        WE_versus: ``"ref"`` or ``"rhe"``.
        ref_type: Reference electrode key into ``REF_TABLE``.
        pH: Solution pH.
        WE_potential_init__V: Initial potential (V).
        WE_potential_apex1__V: Final potential (V).
        ScanRate_V_s: Scan rate (V/s).
        SampleRate: Acquisition interval (s).
        IErange: Gamry current-range setting.
        gamrychannelwait: TTL channel to wait on (-1 disables).
        gamrychannelsend: TTL channel to send on (-1 disables).
        ref_offset__V: Reference offset (V).
        illumination_source: IO output name driving the LED.
        illumination_wavelength: LED wavelength (nm).
        illumination_intensity: LED intensity setting.
        illumination_intensity_date: Provenance date string for intensity.
        illumination_side: ``"front"`` or ``"back"``.
        toggle_dark_time_init: Initial dark delay (s).
        toggle_illum_duty: Illumination duty cycle.
        toggle_illum_period: Toggle period (s).
        toggle_illum_time: Total toggle duration (s); ``-1`` matches the sweep.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    CV_duration_sec = abs(WE_potential_apex1__V - WE_potential_init__V) / ScanRate_V_s

    if int(round(toggle_illum_time)) == -1:
        toggle_illum_time = CV_duration_sec
    if WE_versus == "ref":
        potential_init_vsRef = WE_potential_init__V - 1.0 * ref_offset__V
        potential_apex1_vsRef = WE_potential_apex1__V - 1.0 * ref_offset__V
    elif WE_versus == "rhe":
        potential_init_vsRef = (
            WE_potential_init__V
            - 1.0 * ref_offset__V
            - 0.059 * pH
            - REF_TABLE[ref_type]
        )
        potential_apex1_vsRef = (
            WE_potential_apex1__V
            - 1.0 * ref_offset__V
            - 0.059 * pH
            - REF_TABLE[ref_type]
        )

    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {"custom": "cell1_we"},
        to_global_params=["_fast_samples_in"],
    )

    #    apm.add(NI_server, "led", {"led":"led", "on": 1})
    # adding IO server for Galil LED toggle control instead of NI
    apm.add(
        IO_server,
        "set_digital_cycle",
        {
            "trigger_name": "gamry_ttl0",
            "triggertype": toggle_triggertype,
            "out_name": illumination_source,
            "out_name_gamry": "gamry_aux",
            "toggle_init_delay": toggle_dark_time_init,
            "toggle_duty": toggle_illum_duty,
            "toggle_period": toggle_illum_period,
            "toggle_duration": toggle_illum_time,
        },
        process_finish=False,
        process_contrib=[
            ProcessContrib.files,
        ],
    )

    apm.add(
        PSTAT_server,
        "run_LSV",
        {
            "Vinit__V": potential_init_vsRef,
            "Vfinal__V": potential_apex1_vsRef,
            "ScanRate__V_s": ScanRate_V_s,
            "AcqInterval__s": SampleRate,
            "TTLwait": gamrychannelwait,  # -1 disables, else select TTL 0-3
            "TTLsend": gamrychannelsend,  # -1 disables, else select TTL 0-3
            "IErange": IErange,
        },
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        process_finish=True,
        technique_name=["LSV"],
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    apm.add(
        IO_server,
        "stop_digital_cycle",
        {},
    )

    # apm.add(ORCH_server, "wait", {"waittime": 10})

    return apm.planned_actions


@experiment(version=1)
def ANEC_sub_photo_CP(
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CP_current: float = 0.0,
    SampleRate: float = 0.01,
    CP_duration_sec: float = 60,
    IErange: str = "auto",
    gamrychannelwait: int = -1,
    gamrychannelsend: int = 1,
    illumination_source: str = "Thorlab_led",
    illumination_wavelength: float = 450.0,
    illumination_intensity: float = 9.0,
    illumination_intensity_date: str = "n/a",
    illumination_side: str = "front",
    toggle_dark_time_init: float = 0.0,
    toggle_illum_duty: float = 0.5,
    toggle_illum_period: float = 2.0,
    toggle_illum_time: float = -1,
) -> list:
    """Run a chronopotentiometry (CP) experiment with hardware-triggered LED toggling.

    Programs a digital cycle on ``gamry_ttl0`` to drive the LED for the CP
    duration (or for ``toggle_illum_time`` when explicitly set), runs CP
    with TTL handshake, and stops the digital cycle.

    Args:
        experiment: Orchestrator-provided experiment context.
        WE_versus: Reference frame label.
        ref_type: Reference electrode key into ``REF_TABLE``.
        pH: Solution pH.
        CP_current: Applied current (A).
        SampleRate: Acquisition interval (s).
        CP_duration_sec: CP duration (s).
        IErange: Gamry current-range setting.
        gamrychannelwait: TTL channel to wait on (-1 disables).
        gamrychannelsend: TTL channel to send on (-1 disables).
        illumination_source: IO output name driving the LED.
        illumination_wavelength: LED wavelength (nm).
        illumination_intensity: LED intensity setting.
        illumination_intensity_date: Provenance date string for intensity.
        illumination_side: ``"front"`` or ``"back"``.
        toggle_dark_time_init: Initial dark delay (s).
        toggle_illum_duty: Illumination duty cycle.
        toggle_illum_period: Toggle period (s).
        toggle_illum_time: Total toggle duration (s); ``-1`` matches CP.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    if int(round(toggle_illum_time)) == -1:
        toggle_illum_time = CP_duration_sec

    # get sample for gamry
    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {"custom": "cell1_we"},
        to_global_params=["_fast_samples_in"],
    )

    apm.add(
        IO_server,
        "set_digital_cycle",
        {
            "trigger_name": "gamry_ttl0",
            "triggertype": toggle_triggertype,
            "out_name": illumination_source,
            "out_name_gamry": "gamry_aux",
            "toggle_init_delay": toggle_dark_time_init,
            "toggle_duty": toggle_illum_duty,
            "toggle_period": toggle_illum_period,
            "toggle_duration": toggle_illum_time,
        },
        process_finish=False,
        process_contrib=[
            ProcessContrib.files,
        ],
    )

    apm.add(
        PSTAT_server,
        "run_CP",
        {
            "Ival": CP_current,
            "Tval__s": CP_duration_sec,
            "AcqInterval__s": SampleRate,
            "TTLwait": gamrychannelwait,  # -1 disables, else select TTL 0-3
            "TTLsend": gamrychannelsend,  # -1 disables, else select TTL 0-3
            "IErange": IErange,
        },
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        technique_name="CP",
        process_finish=True,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    apm.add(
        IO_server,
        "stop_digital_cycle",
        {},
    )

    return apm.planned_actions  # returns complete action list to orch
