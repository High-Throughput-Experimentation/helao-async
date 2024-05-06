"""
Action library for ANEC

server_key must be a FastAPI action server defined in config
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
    "ANEC_sub_HeatCA",
    "ANEC_sub_OCV",
    "ANEC_sub_liquidarchive",
    "ANEC_sub_aliquot",
    "ANEC_sub_aliquot_nomixing",
    "ANEC_sub_alloff",
    "ANEC_sub_heatoff",
    "ANEC_sub_setheat",
    "ANEC_sub_CV",
    "ANEC_sub_HeatCV",
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


def ANEC_sub_startup(
    experiment: Experiment,
    experiment_version: int = 1,
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
    z_move_mm: float = 3.5,
):
    """Sub experiment
    last functionality test: -"""

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
            "plate_id": apm.pars.solid_plate_id,
            "sample_no": apm.pars.solid_sample_no,
        },
        to_globalexp_params=[
            "_platexy"
        ],  # save new liquid_sample_no of eche cell to globals
        start_condition=ActionStartCondition.wait_for_all,
    )

    # move to position
    apm.add(
        MOTOR_server,
        "move",
        {
            # "d_mm": [apm.pars.x_mm, apm.pars.y_mm],
            "axis": ["x", "y"],
            "mode": MoveModes.absolute,
            "transformation": TransformationModes.platexy,
        },
        from_globalexp_params={"_platexy": "d_mm"},
        start_condition=ActionStartCondition.wait_for_all,
    )

    # move to z-up position
    apm.add(
        MOTOR_server,
        "move",
        {
            "d_mm": [apm.pars.z_move_mm],
            "axis": ["z"],
            "mode": MoveModes.absolute,
            "transformation": TransformationModes.motorxy,
        },
        start_condition=ActionStartCondition.wait_for_all,
    )

    return apm.action_list  # returns complete action list to orch


def ANEC_sub_disengage(experiment: Experiment, experiment_version: int = 1):
    """Sub experiment
    Disengages and seals electrochemical cell."""

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

    return apm.action_list  # returns complete action list to orch


def ANEC_sub_load_solid(
    experiment: Experiment,
    experiment_version: int = 1,
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
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
            ).model_dump(),
        },
    )

    return apm.action_list


def ANEC_sub_alloff(
    experiment: Experiment,
    experiment_version: int = 4,
):
    """

    Args:
        experiment (Experiment): Experiment object provided by Orch
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
    apm.add(
        TEC_server,
        "cancel_record_tec",
        {}
    )
    apm.add(TEC_server, "disable_tec", {})

    return apm.action_list


def ANEC_sub_heatoff(
    experiment: Experiment,
    experiment_version: int = 2,
):
    """

    Args:
        experiment (Experiment): Experiment object provided by Orch
    """

    apm = ActionPlanMaker()

    apm.add(
        TEC_server,
        "cancel_record_tec",
        {}
    )
    apm.add(TEC_server, "disable_tec", {})

    return apm.action_list


def ANEC_sub_setheat(
    experiment: Experiment,
    experiment_version: int = 2,
    target_temperature_degc: float = 25.0,
):
    """

    Args:
        experiment (Experiment): Experiment object provided by Orch
    """

    apm = ActionPlanMaker()
    apm.add(
        TEC_server,
        "set_temperature",
        {"target_temperature_degc": apm.pars.target_temperature_degc},
    )
    apm.add(
        TEC_server,
        "record_tec",
        {"duration": -1,"acquisition_rate": 0.2},
        nonblocking=True,
    )
    # =============================================================================
    apm.add(TEC_server, "enable_tec", {})
    apm.add(TEC_server, "wait_till_stable", {})

    return apm.action_list


def ANEC_sub_normal_state(
    experiment: Experiment,
    experiment_version: int = 2,
):
    """Set ANEC to 'normal' state.

    All experiments begin and end in the following 'normal' state:
    - Counter electrode (CE) chamber recirculation pump is ON.
    - Working electrode (WE) chamber outlet pump is ON.
    - CE chamber recirculation pump direction is ON (forward).
    - WE chamber liquid drain valve is ON (open).
    - WE chamber liquid fill valve is OFF (closed).
    - Liquid reservoir valve is OFF (closed).
    - WE chamber gas flow-through valve is OFF (closed).
    - WE chamber CO2 inlet valve is ON (open).

    Args:
        experiment (Experiment): Experiment object provided by Orch
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

    return apm.action_list


def ANEC_sub_flush_fill_cell(
    experiment: Experiment,
    experiment_version: int = 1,
    liquid_flush_time: float = 70,
    co2_purge_time: float = 15,
    equilibration_time: float = 1.0,
    reservoir_liquid_sample_no: int = 1511,
    volume_ul_cell_liquid: int = 1000,
):
    """Add liquid volume to cell position.

    (1) create liquid sample using volume_ul_cell and liquid_sample_no
    """

    apm = ActionPlanMaker()

    # Fill cell with liquid
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "down", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "up", "on": 1})
    apm.add(NI_server, "pump", {"pump": "Direction", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "CO2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "liquid", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.liquid_flush_time})
    # Stop flow and start CO2 purge
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "liquid", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "CO2", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.co2_purge_time})
    # Open headspace flow-through, stop purge
    apm.add(NI_server, "gasvalve", {"gasvalve": "atm", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "up", "on": 0})
    apm.add(NI_server, "pump", {"pump": "PeriPump2", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "CO2", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.equilibration_time})
    apm.add(NI_server, "gasvalve", {"gasvalve": "atm", "on": 0})
    # (3) Create liquid sample and add to assembly
    apm.add(
        PAL_server,
        "archive_custom_add_liquid",
        {
            "custom": "cell1_we",
            "source_liquid_in": LiquidSample(
                sample_no=apm.pars.reservoir_liquid_sample_no, machine_name=ORCH_HOST
            ).model_dump(),
            "volume_ml": apm.pars.volume_ul_cell_liquid,
            "combine_liquids": True,
            "dilute_liquids": True,
        },
    )
    return apm.action_list


def ANEC_sub_unload_cell(experiment: Experiment, experiment_version: int = 1):
    """Unload Sample at 'cell1_we' position."""

    apm = ActionPlanMaker()
    apm.add(PAL_server, "archive_custom_unloadall", {})
    return apm.action_list


def ANEC_sub_unload_liquid(
    experiment: Experiment,
    experiment_version: int = 1,
):
    """Unload liquid sample at 'cell1_we' position and reload solid sample."""

    apm = ActionPlanMaker()
    apm.add(
        PAL_server,
        "archive_custom_unloadall",
        {},
        to_globalexp_params=["_unloaded_solid"],
    )
    apm.add(
        PAL_server,
        "archive_custom_load",
        {"custom": "cell1_we"},
        from_globalexp_params={"_unloaded_solid": "load_sample_in"},
    )
    return apm.action_list


def ANEC_sub_drain_cell(
    experiment: Experiment,
    experiment_version: int = 3,
    drain_time: float = 60.0,
):
    """Drain liquid from cell and unload liquid sample."""

    apm = ActionPlanMaker()
    apm.add_action_list(ANEC_sub_normal_state(experiment))
    apm.add_action_list(ANEC_sub_unload_liquid(experiment))
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.drain_time})

    return apm.action_list


def ANEC_sub_cleanup(
    experiment: Experiment,
    experiment_version: int = 1,
    reservoir_liquid_sample_no: int = 1511,
):
    """Flush and purge ANEC cell.

    (1) Flush/fill cell
    (2) Drain cell

    Args:
        exp (Experiment): Active experiment object supplied by Orchestrator
        toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
        volume_ul_GC: GC injection volume

    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add_action_list(
        ANEC_sub_flush_fill_cell(
            experiment=experiment,
            reservoir_liquid_sample_no=apm.pars.reservoir_liquid_sample_no,
        )
    )
    apm.add_action_list(ANEC_sub_drain_cell(experiment))
    return apm.action_list

def ANEC_sub_GC_headspacealiquot_nomixing(
    experiment: Experiment,
    experiment_version: int = 1,
    toolGC: str = "HS 2",
    volume_ul_GC: int = 300,
):
    """Sample headspace in cell1_we and inject into GC

    Args:
        exp (Experiment): Active experiment object supplied by Orchestrator
        toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
        volume_ul_GC: GC injection volume

    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 0})
    apm.add(
        PAL_server,
        "PAL_ANEC_GC",
        {
            "toolGC": apm.pars.toolGC,
            "source": "cell1_we",
            "volume_ul_GC": apm.pars.volume_ul_GC,
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
    return apm.action_list

def ANEC_sub_GC_preparation(
    experiment: Experiment,
    experiment_version: int = 1,
    toolGC: str = "HS 2",
    volume_ul_GC: int = 300,
):
    """Sample headspace in cell1_we and inject into GC

    Args:
        exp (Experiment): Active experiment object supplied by Orchestrator
        toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
        volume_ul_GC: GC injection volume

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
            "toolGC": apm.pars.toolGC,
            "source": "cell1_we",
            "volume_ul_GC": apm.pars.volume_ul_GC,
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
    return apm.action_list


def ANEC_sub_load_solid_only(
    experiment: Experiment,
    experiment_version: int = 1,
    solid_plate_id: int = 1,
    solid_sample_no: int = 1,
):
    """Load solid and clean cell."""

    apm = ActionPlanMaker()
    apm.add_action_list(ANEC_sub_unload_cell(experiment))
    apm.add(
        PAL_server,
        "archive_custom_load",
        {
            "custom": "cell1_we",
            "load_sample_in": SolidSample(
                sample_no=apm.pars.solid_sample_no,
                plate_id=apm.pars.solid_plate_id,
                machine_name="legacy",
            ).model_dump(),
        },
    )
    return apm.action_list


def ANEC_sub_load_solid_and_clean_cell(
    experiment: Experiment,
    experiment_version: int = 1,
    solid_plate_id: int = 1,
    solid_sample_no: int = 1,
    reservoir_liquid_sample_no: int = 1511,
    recirculation_time: float = 60,
    toolGC: str = "HS 2",
    volume_ul_GC: int = 300,
):
    """Load solid and clean cell."""

    apm = ActionPlanMaker()
    apm.add_action_list(ANEC_sub_unload_cell(experiment))
    apm.add(
        PAL_server,
        "archive_custom_load",
        {
            "custom": "cell1_we",
            "load_sample_in": SolidSample(
                sample_no=apm.pars.solid_sample_no,
                plate_id=apm.pars.solid_plate_id,
                machine_name="legacy",
            ).model_dump(),
        },
    )
    apm.add_action_list(ANEC_sub_drain_cell(experiment))
    apm.add_action_list(
        ANEC_sub_flush_fill_cell(
            experiment=experiment,
            reservoir_liquid_sample_no=apm.pars.reservoir_liquid_sample_no,
        )
    )
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.recirculation_time})
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 0})
    apm.add(
        PAL_server,
        "PAL_ANEC_GC",
        {
            "toolGC": PALtools(apm.pars.toolGC),
            "source": "cell1_we",
            "volume_ul_GC": apm.pars.volume_ul_GC,
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
    apm.add_action_list(ANEC_sub_drain_cell(experiment))
    return apm.action_list


def ANEC_sub_liquidarchive(
    experiment: Experiment,
    experiment_version: int = 1,
    toolarchive: str = "LS 3",
    volume_ul_archive: int = 500,
    wash1: bool = True,
    wash2: bool = True,
    wash3: bool = True,
    wash4: bool = False,
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # first circulate the liquid back and forth
    # e.g. mix it by reversing the flow a few times

    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 0})
    apm.add(
        PAL_server,
        "PAL_archive",
        {
            "tool": apm.pars.toolarchive,
            "source": "cell1_we",
            "volume_ul": apm.pars.volume_ul_archive,
            "wash1": apm.pars.wash1,
            "wash2": apm.pars.wash2,
            "wash3": apm.pars.wash3,
            "wash4": apm.pars.wash4,
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

    return apm.action_list


def ANEC_sub_aliquot_nomixing(
    experiment: Experiment,
    experiment_version: int = 1,
    toolGC: str = "HS 2",
    toolarchive: str = "LS 3",
    volume_ul_GC: int = 300,
    volume_ul_archive: int = 500,
    wash1: bool = True,
    wash2: bool = True,
    wash3: bool = True,
    wash4: bool = False,
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # first circulate the liquid back and forth
    # e.g. mix it by reversing the flow a few times
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 0})
    apm.add(
        PAL_server,
        "PAL_ANEC_aliquot",
        {
            "toolGC": apm.pars.toolGC,
            "toolarchive": apm.pars.toolarchive,
            "source": "cell1_we",
            "volume_ul_GC": apm.pars.volume_ul_GC,
            "volume_ul_archive": apm.pars.volume_ul_archive,
            "wash1": apm.pars.wash1,
            "wash2": apm.pars.wash2,
            "wash3": apm.pars.wash3,
            "wash4": apm.pars.wash4,
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

    return apm.action_list

def ANEC_sub_aliquot(
    experiment: Experiment,
    experiment_version: int = 1,
    toolGC: str = "HS 2",
    toolarchive: str = "LS 3",
    volume_ul_GC: int = 300,
    volume_ul_archive: int = 500,
    wash1: bool = True,
    wash2: bool = True,
    wash3: bool = True,
    wash4: bool = False,
):
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
            "toolGC": apm.pars.toolGC,
            "toolarchive": apm.pars.toolarchive,
            "source": "cell1_we",
            "volume_ul_GC": apm.pars.volume_ul_GC,
            "volume_ul_archive": apm.pars.volume_ul_archive,
            "wash1": apm.pars.wash1,
            "wash2": apm.pars.wash2,
            "wash3": apm.pars.wash3,
            "wash4": apm.pars.wash4,
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

    return apm.action_list


def ANEC_sub_CP(
    experiment: Experiment,
    experiment_version: int = 1,
    WE_versus: str = "ref",
    ref_type: str = "leakless",
    pH: float = 6.8,
    CP_current: float = 0.0,
    SampleRate: float = 0.01,
    CP_duration_sec: float = 60,
    IErange: str = "auto",
):
    """last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    if int(round(apm.pars.toggle_illum_time)) == -1:
        apm.pars.toggle_illum_time = apm.pars.CP_duration_sec

    # get sample for gamry
    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {"custom": "cell1_we"},
        to_globalexp_params=["_fast_samples_in"],
    )

    apm.add(
        PSTAT_server,
        "run_CP",
        {
            "Ival": apm.pars.CP_current,
            "Tval__s": apm.pars.CP_duration_sec,
            "AcqInterval__s": apm.pars.SampleRate,
            "IErange": apm.pars.IErange,
        },
        from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
        technique_name="CP",
        process_finish=True,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )

    return apm.action_list  # returns complete action list to orch


def ANEC_sub_CA(
    experiment: Experiment,
    experiment_version: int = 1,
    WE_potential__V: float = 0.0,
    WE_versus: str = "ref",
    CA_duration_sec: float = 0.1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    ref_type: str = "leakless",
    pH: float = 6.8,
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    if apm.pars.WE_versus == "ref":
        potential_vsRef = apm.pars.WE_potential__V - 1.0 * apm.pars.ref_offset__V
    elif apm.pars.WE_versus == "rhe":
        potential_vsRef = (
            apm.pars.WE_potential__V
            - 1.0 * apm.pars.ref_offset__V
            - 0.059 * apm.pars.pH
            - REF_TABLE[ref_type]
        )
    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {"custom": "cell1_we"},
        to_globalexp_params=["_fast_samples_in"],
    )
    apm.add(
        PSTAT_server,
        "run_CA",
        {
            "Vval__V": potential_vsRef,
            "Tval__s": apm.pars.CA_duration_sec,
            "AcqInterval__s": apm.pars.SampleRate,
            "IErange": apm.pars.IErange,
        },
        from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
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

    return apm.action_list


def ANEC_sub_HeatCA(
    experiment: Experiment,
    experiment_version: int = 2,
    WE_potential__V: float = 0.0,
    WE_versus: str = "ref",
    CA_duration_sec: float = 0.1,
    SampleRate: float = 0.01,
    IErange: str = "auto",
    ref_offset__V: float = 0.0,
    ref_type: str = "leakless",
    pH: float = 6.8,
    target_temperature_degc: float = 25.0,
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    if apm.pars.WE_versus == "ref":
        potential_vsRef = apm.pars.WE_potential__V - 1.0 * apm.pars.ref_offset__V
    elif apm.pars.WE_versus == "rhe":
        potential_vsRef = (
            apm.pars.WE_potential__V
            - 1.0 * apm.pars.ref_offset__V
            - 0.059 * apm.pars.pH
            - REF_TABLE[ref_type]
        )
    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {"custom": "cell1_we"},
        to_globalexp_params=["_fast_samples_in"],
    )
    apm.add(
        TEC_server,
        "set_temperature",
        {"target_temperature_degc": apm.pars.target_temperature_degc},
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
            "Tval__s": apm.pars.CA_duration_sec,
            "AcqInterval__s": apm.pars.SampleRate,
            "IErange": apm.pars.IErange,
        },
        from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
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

    return apm.action_list


def ANEC_sub_OCV(
    experiment: Experiment,
    experiment_version: int = 1,
    Tval__s: float = 900.0,
    IErange: str = "auto",
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # get sample for gamry
    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {
            "custom": "cell1_we",
        },
        to_globalexp_params=[
            "_fast_samples_in"
        ],  # save new liquid_sample_no of eche cell to globals
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
    )

    # OCV
    apm.add(
        PSTAT_server,
        "run_OCV",
        {
            "Tval__s": apm.pars.Tval__s,
            "SampleRate": 0.05,
            "IErange": apm.pars.IErange,
        },
        from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
        technique_name="CP",
        process_finish=True,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    return apm.action_list  # returns complete action list to orch


def ANEC_sub_photo_CA(
    experiment: Experiment,
    experiment_version: int = 2,
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
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    if int(round(apm.pars.toggle_illum_time)) == -1:
        apm.pars.toggle_illum_time = apm.pars.CA_duration_sec
    if apm.pars.WE_versus == "ref":
        potential_vsRef = apm.pars.WE_potential__V - 1.0 * apm.pars.ref_offset__V
    elif apm.pars.WE_versus == "rhe":
        potential_vsRef = (
            apm.pars.WE_potential__V
            - 1.0 * apm.pars.ref_offset__V
            - 0.059 * apm.pars.pH
            - REF_TABLE[ref_type]
        )
    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {"custom": "cell1_we"},
        to_globalexp_params=["_fast_samples_in"],
    )
    #    apm.add(NI_server, "led", {"led":"led", "on": 1})
    # adding IO server for Galil LED toggle control instead of NI
    apm.add(
        IO_server,
        "set_digital_cycle",
        {
            "trigger_name": "gamry_ttl0",
            "triggertype": toggle_triggertype,
            "out_name": apm.pars.illumination_source,
            "out_name_gamry": "gamry_aux",
            "toggle_init_delay": apm.pars.toggle_dark_time_init,
            "toggle_duty": apm.pars.toggle_illum_duty,
            "toggle_period": apm.pars.toggle_illum_period,
            "toggle_duration": apm.pars.toggle_illum_time,
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
            "Tval__s": apm.pars.CA_duration_sec,
            "AcqInterval__s": apm.pars.SampleRate,
            "TTLwait": apm.pars.gamrychannelwait,  # -1 disables, else select TTL 0-3
            "TTLsend": apm.pars.gamrychannelsend,  # -1 disables, else select TTL 0-3
            "IErange": apm.pars.IErange,
        },
        from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
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

    return apm.action_list


def ANEC_sub_CV(
    experiment: Experiment,
    experiment_version: int = 1,
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
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    if apm.pars.WE_versus == "ref":
        potential_init_vsRef = (
            apm.pars.WE_potential_init__V - 1.0 * apm.pars.ref_offset__V
        )
        potential_apex1_vsRef = (
            apm.pars.WE_potential_apex1__V - 1.0 * apm.pars.ref_offset__V
        )
        potential_apex2_vsRef = (
            apm.pars.WE_potential_apex2__V - 1.0 * apm.pars.ref_offset__V
        )
        potential_final_vsRef = (
            apm.pars.WE_potential_final__V - 1.0 * apm.pars.ref_offset__V
        )
    elif apm.pars.WE_versus == "rhe":
        potential_init_vsRef = (
            apm.pars.WE_potential_init__V
            - 1.0 * apm.pars.ref_offset__V
            - 0.059 * apm.pars.pH
            - REF_TABLE[ref_type]
        )
        potential_apex1_vsRef = (
            apm.pars.WE_potential_apex1__V
            - 1.0 * apm.pars.ref_offset__V
            - 0.059 * apm.pars.pH
            - REF_TABLE[ref_type]
        )
        potential_apex2_vsRef = (
            apm.pars.WE_potential_apex2__V
            - 1.0 * apm.pars.ref_offset__V
            - 0.059 * apm.pars.pH
            - REF_TABLE[ref_type]
        )
        potential_final_vsRef = (
            apm.pars.WE_potential_final__V
            - 1.0 * apm.pars.ref_offset__V
            - 0.059 * apm.pars.pH
            - REF_TABLE[ref_type]
        )

    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {"custom": "cell1_we"},
        to_globalexp_params=["_fast_samples_in"],
    )

    apm.add(
        PSTAT_server,
        "run_CV",
        {
            "Vinit__V": potential_init_vsRef,
            "Vapex1__V": potential_apex1_vsRef,
            "Vapex2__V": potential_apex2_vsRef,
            "Vfinal__V": potential_final_vsRef,
            "ScanRate__V_s": apm.pars.ScanRate_V_s,
            "Cycles": apm.pars.Cycles,
            "AcqInterval__s": apm.pars.SampleRate,
            "IErange": apm.pars.IErange,
        },
        from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
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

    return apm.action_list


def ANEC_sub_HeatCV(
    experiment: Experiment,
    experiment_version: int = 2,
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
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    if apm.pars.WE_versus == "ref":
        potential_init_vsRef = (
            apm.pars.WE_potential_init__V - 1.0 * apm.pars.ref_offset__V
        )
        potential_apex1_vsRef = (
            apm.pars.WE_potential_apex1__V - 1.0 * apm.pars.ref_offset__V
        )
        potential_apex2_vsRef = (
            apm.pars.WE_potential_apex2__V - 1.0 * apm.pars.ref_offset__V
        )
        potential_final_vsRef = (
            apm.pars.WE_potential_final__V - 1.0 * apm.pars.ref_offset__V
        )
    elif apm.pars.WE_versus == "rhe":
        potential_init_vsRef = (
            apm.pars.WE_potential_init__V
            - 1.0 * apm.pars.ref_offset__V
            - 0.059 * apm.pars.pH
            - REF_TABLE[ref_type]
        )
        potential_apex1_vsRef = (
            apm.pars.WE_potential_apex1__V
            - 1.0 * apm.pars.ref_offset__V
            - 0.059 * apm.pars.pH
            - REF_TABLE[ref_type]
        )
        potential_apex2_vsRef = (
            apm.pars.WE_potential_apex2__V
            - 1.0 * apm.pars.ref_offset__V
            - 0.059 * apm.pars.pH
            - REF_TABLE[ref_type]
        )
        potential_final_vsRef = (
            apm.pars.WE_potential_final__V
            - 1.0 * apm.pars.ref_offset__V
            - 0.059 * apm.pars.pH
            - REF_TABLE[ref_type]
        )

    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {"custom": "cell1_we"},
        to_globalexp_params=["_fast_samples_in"],
    )

    apm.add(
        TEC_server,
        "set_temperature",
        {"target_temperature_degc": apm.pars.target_temperature_degc},
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
            "ScanRate__V_s": apm.pars.ScanRate_V_s,
            "Cycles": apm.pars.Cycles,
            "AcqInterval__s": apm.pars.SampleRate,
            "IErange": apm.pars.IErange,
        },
        from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
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

    return apm.action_list


def ANEC_sub_photo_CV(
    experiment: Experiment,
    experiment_version: int = 1,
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
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    CV_duration_sec = (
        abs(apm.pars.WE_potential_apex1__V - apm.pars.WE_potential_init__V)
        / apm.pars.ScanRate_V_s
    )
    CV_duration_sec += (
        abs(apm.pars.WE_potential_final__V - apm.pars.WE_potential_apex2__V)
        / apm.pars.ScanRate_V_s
    )
    CV_duration_sec += (
        abs(apm.pars.WE_potential_apex2__V - apm.pars.WE_potential_apex1__V)
        / apm.pars.ScanRate_V_s
#        * apm.pars.Cycles
    )
    CV_duration_sec += (
        abs(apm.pars.WE_potential_apex2__V - apm.pars.WE_potential_apex1__V)
        / apm.pars.ScanRate_V_s
        * 2.0
        * (apm.pars.Cycles - 1)
    )

    if int(round(apm.pars.toggle_illum_time)) == -1:
        apm.pars.toggle_illum_time = CV_duration_sec
    if apm.pars.WE_versus == "ref":
        potential_init_vsRef = (
            apm.pars.WE_potential_init__V - 1.0 * apm.pars.ref_offset__V
        )
        potential_apex1_vsRef = (
            apm.pars.WE_potential_apex1__V - 1.0 * apm.pars.ref_offset__V
        )
        potential_apex2_vsRef = (
            apm.pars.WE_potential_apex2__V - 1.0 * apm.pars.ref_offset__V
        )
        potential_final_vsRef = (
            apm.pars.WE_potential_final__V - 1.0 * apm.pars.ref_offset__V
        )
    elif apm.pars.WE_versus == "rhe":
        potential_init_vsRef = (
            apm.pars.WE_potential_init__V
            - 1.0 * apm.pars.ref_offset__V
            - 0.059 * apm.pars.pH
            - REF_TABLE[ref_type]
        )
        potential_apex1_vsRef = (
            apm.pars.WE_potential_apex1__V
            - 1.0 * apm.pars.ref_offset__V
            - 0.059 * apm.pars.pH
            - REF_TABLE[ref_type]
        )
        potential_apex2_vsRef = (
            apm.pars.WE_potential_apex2__V
            - 1.0 * apm.pars.ref_offset__V
            - 0.059 * apm.pars.pH
            - REF_TABLE[ref_type]
        )
        potential_final_vsRef = (
            apm.pars.WE_potential_final__V
            - 1.0 * apm.pars.ref_offset__V
            - 0.059 * apm.pars.pH
            - REF_TABLE[ref_type]
        )

    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {"custom": "cell1_we"},
        to_globalexp_params=["_fast_samples_in"],
    )

    #    apm.add(NI_server, "led", {"led":"led", "on": 1})
    # adding IO server for Galil LED toggle control instead of NI
    apm.add(
        IO_server,
        "set_digital_cycle",
        {
            "trigger_name": "gamry_ttl0",
            "triggertype": toggle_triggertype,
            "out_name": apm.pars.illumination_source,
            "out_name_gamry": "gamry_aux",
            "toggle_init_delay": apm.pars.toggle_dark_time_init,
            "toggle_duty": apm.pars.toggle_illum_duty,
            "toggle_period": apm.pars.toggle_illum_period,
            "toggle_duration": apm.pars.toggle_illum_time,
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
            "ScanRate__V_s": apm.pars.ScanRate_V_s,
            "Cycles": apm.pars.Cycles,
            "AcqInterval__s": apm.pars.SampleRate,
            "TTLwait": apm.pars.gamrychannelwait,  # -1 disables, else select TTL 0-3
            "TTLsend": apm.pars.gamrychannelsend,  # -1 disables, else select TTL 0-3
            "IErange": apm.pars.IErange,
        },
        from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
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

    return apm.action_list


def ANEC_sub_GCLiquid_analysis(
    experiment: Experiment,
    experiment_version: int = 1,
    # startGC: bool = None,
    # sampletype: str = None,
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
):
    """Sample headspace in cell1_we and inject into GC

    Args:
        exp (Experiment): Active experiment object supplied by Orchestrator
        toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
        volume_ul_GC: GC injection volume

    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(
        PAL_server,
        "PAL_injection_tray_GC",
        {
            "tool": apm.pars.tool,
            "source_tray": apm.pars.source_tray,
            "source_slot": apm.pars.source_slot,
            "source_vial": apm.pars.source_vial,
            "dest": apm.pars.dest,
            "volume_ul": apm.pars.volume_ul,
            "wash1": apm.pars.wash1,
            "wash2": apm.pars.wash2,
            "wash3": apm.pars.wash3,
            "wash4": apm.pars.wash4,
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
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.GC_analysis_time})
    return apm.action_list


def ANEC_sub_HPLCLiquid_analysis(
    experiment: Experiment,
    experiment_version: int = 1,
    # startGC: bool = None,
    # sampletype: str = None,
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
):
    """Sample headspace in cell1_we and inject into GC

    Args:
        exp (Experiment): Active experiment object supplied by Orchestrator
        toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
        volume_ul_GC: GC injection volume

    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(
        PAL_server,
        "PAL_injection_tray_HPLC",
        {
            "tool": apm.pars.tool,
            "source_tray": apm.pars.source_tray,
            "source_slot": apm.pars.source_slot,
            "source_vial": apm.pars.source_vial,
            "dest": apm.pars.dest,
            "volume_ul": apm.pars.volume_ul,
            "wash1": apm.pars.wash1,
            "wash2": apm.pars.wash2,
            "wash3": apm.pars.wash3,
            "wash4": apm.pars.wash4,
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
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.HPLC_analysis_time})
    return apm.action_list


def ANEC_sub_photo_LSV(
    experiment: Experiment,
    experiment_version: int = 1,
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
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    CV_duration_sec = (
        abs(apm.pars.WE_potential_apex1__V - apm.pars.WE_potential_init__V)
        / apm.pars.ScanRate_V_s
    )

    if int(round(apm.pars.toggle_illum_time)) == -1:
        apm.pars.toggle_illum_time = CV_duration_sec
    if apm.pars.WE_versus == "ref":
        potential_init_vsRef = (
            apm.pars.WE_potential_init__V - 1.0 * apm.pars.ref_offset__V
        )
        potential_apex1_vsRef = (
            apm.pars.WE_potential_apex1__V - 1.0 * apm.pars.ref_offset__V
        )
    elif apm.pars.WE_versus == "rhe":
        potential_init_vsRef = (
            apm.pars.WE_potential_init__V
            - 1.0 * apm.pars.ref_offset__V
            - 0.059 * apm.pars.pH
            - REF_TABLE[ref_type]
        )
        potential_apex1_vsRef = (
            apm.pars.WE_potential_apex1__V
            - 1.0 * apm.pars.ref_offset__V
            - 0.059 * apm.pars.pH
            - REF_TABLE[ref_type]
        )

    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {"custom": "cell1_we"},
        to_globalexp_params=["_fast_samples_in"],
    )

    #    apm.add(NI_server, "led", {"led":"led", "on": 1})
    # adding IO server for Galil LED toggle control instead of NI
    apm.add(
        IO_server,
        "set_digital_cycle",
        {
            "trigger_name": "gamry_ttl0",
            "triggertype": toggle_triggertype,
            "out_name": apm.pars.illumination_source,
            "out_name_gamry": "gamry_aux",
            "toggle_init_delay": apm.pars.toggle_dark_time_init,
            "toggle_duty": apm.pars.toggle_illum_duty,
            "toggle_period": apm.pars.toggle_illum_period,
            "toggle_duration": apm.pars.toggle_illum_time,
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
            "ScanRate__V_s": apm.pars.ScanRate_V_s,
            "AcqInterval__s": apm.pars.SampleRate,
            "TTLwait": apm.pars.gamrychannelwait,  # -1 disables, else select TTL 0-3
            "TTLsend": apm.pars.gamrychannelsend,  # -1 disables, else select TTL 0-3
            "IErange": apm.pars.IErange,
        },
        from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
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

    return apm.action_list


def ANEC_sub_photo_CP(
    experiment: Experiment,
    experiment_version: int = 1,
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
):
    """last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    if int(round(apm.pars.toggle_illum_time)) == -1:
        apm.pars.toggle_illum_time = apm.pars.CP_duration_sec

    # get sample for gamry
    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {"custom": "cell1_we"},
        to_globalexp_params=["_fast_samples_in"],
    )

    apm.add(
        IO_server,
        "set_digital_cycle",
        {
            "trigger_name": "gamry_ttl0",
            "triggertype": toggle_triggertype,
            "out_name": apm.pars.illumination_source,
            "out_name_gamry": "gamry_aux",
            "toggle_init_delay": apm.pars.toggle_dark_time_init,
            "toggle_duty": apm.pars.toggle_illum_duty,
            "toggle_period": apm.pars.toggle_illum_period,
            "toggle_duration": apm.pars.toggle_illum_time,
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
            "Ival": apm.pars.CP_current,
            "Tval__s": apm.pars.CP_duration_sec,
            "AcqInterval__s": apm.pars.SampleRate,
            "TTLwait": apm.pars.gamrychannelwait,  # -1 disables, else select TTL 0-3
            "TTLsend": apm.pars.gamrychannelsend,  # -1 disables, else select TTL 0-3
            "IErange": apm.pars.IErange,
        },
        from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
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

    return apm.action_list  # returns complete action list to orch
