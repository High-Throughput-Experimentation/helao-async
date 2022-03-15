"""
Action library for ANEC

server_key must be a FastAPI action server defined in config
"""

__all__ = [
    "ANEC_drain_cell",
    "ANEC_flush_fill_cell",
    "ANEC_load_solid_only",
    "ANEC_load_solid",
    "ANEC_unload_cell",
    "ANEC_unload_liquid",
    "ANEC_normal_state",
    "ANEC_GC_preparation",
    "ANEC_cleanup",
    "ANEC_run_CA_vsRHE",
    "ANEC_run_CA_vsRef",
]

###
from socket import gethostname
from typing import Optional

from helaocore.schema import Experiment, ActionPlanMaker
from helao.library.driver.pal_driver import PALtools
from helaocore.model.sample import SolidSample, LiquidSample
from helaocore.model.machine import MachineModel

# list valid experiment functions
EXPERIMENTS = __all__

ORCH_HOST = gethostname()
PSTAT_server = MachineModel(server_name="PSTAT", machine_name=ORCH_HOST).json_dict()
MOTOR_server = MachineModel(server_name="MOTOR", machine_name=ORCH_HOST).json_dict()
NI_server = MachineModel(server_name="NI", machine_name=ORCH_HOST).json_dict()
ORCH_server = MachineModel(server_name="ORCH", machine_name=ORCH_HOST).json_dict()
PAL_server = MachineModel(server_name="PAL", machine_name=ORCH_HOST).json_dict()

# z positions for ADSS cell
z_home = 0.0
# touches the bottom of cell
z_engage = 2.5
# moves it up to put pressure on seal
z_seal = 4.5


def ANEC_normal_state(
    experiment: Experiment,
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
    apm.add(NI_server, "pump", {"pump": "PeriPump2", "on": 1})
    apm.add(NI_server, "pump", {"pump": "Direction", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "down", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "up", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "liquid", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "atm", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "CO2", "on": 1})
    return apm.action_list


def ANEC_flush_fill_cell(
    experiment: Experiment,
    liquid_flush_time: Optional[float] = 90,
    co2_purge_time: Optional[float] = 15,
    equilibration_time: Optional[float] = 1.0,
    reservoir_liquid_sample_no: Optional[int] = 0,
    volume_ul_cell_liquid: Optional[int] = 1000,
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
            ).dict(),
            "volume_ml": apm.pars.volume_ul_cell_liquid,
            "combine_liquids": True,
            "dilute_liquids": True,
        },
    )
    return apm.action_list


def ANEC_unload_cell(experiment: Experiment):
    """Unload Sample at 'cell1_we' position."""

    apm = ActionPlanMaker()
    apm.add(PAL_server, "archive_custom_unloadall", {})
    return apm.action_list


def ANEC_unload_liquid(experiment: Experiment):
    """Unload liquid sample at 'cell1_we' position and reload solid sample."""

    apm = ActionPlanMaker()
    apm.add(
        PAL_server, "archive_custom_unloadall", {}, to_global_params=["_unloaded_solid"]
    )
    apm.add(
        PAL_server,
        "archive_custom_load",
        {"custom": "cell1_we"},
        from_global_params={"_unloaded_solid": "load_sample_in"},
    )
    return apm.action_list


def ANEC_drain_cell(
    experiment: Experiment,
    drain_time: Optional[float] = 60.0,
):
    """Drain liquid from cell and unload liquid sample."""

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 1})
    apm.add(NI_server, "pump", {"pump": "Direction", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "down", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "CO2", "on": 1})
    apm.add(NI_server, "pump", {"pump": "PeriPump2", "on": 1})
    apm.add_action_list(ANEC_unload_liquid(experiment))
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.drain_time})
    apm.add_action_list(ANEC_normal_state(experiment))
    return apm.action_list


def ANEC_cleanup(
    experiment: Experiment,
    reservoir_liquid_sample_no: Optional[int] = 0,
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
        ANEC_flush_fill_cell(
            experiment=experiment,
            reservoir_liquid_sample_no=apm.pars.reservoir_liquid_sample_no,
        )
    )
    apm.add_action_list(ANEC_drain_cell(experiment))
    return apm.action_list


def ANEC_GC_preparation(
    experiment: Experiment,
    toolGC: Optional[str] = "HS 2",
    volume_ul_GC: Optional[int] = 300,
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
        "PAL_ANEC_GC",
        {
            "toolGC": PALtools(apm.pars.toolGC),
            "source": "cell1_we",
            "volume_ul_GC": apm.pars.volume_ul_GC,
        },
    )
    return apm.action_list


def ANEC_load_solid_only(
    experiment: Experiment,
    solid_plate_id: Optional[int] = 0,
    solid_sample_no: Optional[int] = 0,
):
    """Load solid and clean cell."""
    
    apm = ActionPlanMaker()
    apm.add_action_list(ANEC_unload_cell(experiment))
    apm.add(
        PAL_server,
        "archive_custom_load",
        {
            "custom": "cell1_we",
            "load_sample_in": SolidSample(
                sample_no=apm.pars.solid_sample_no,
                plate_id=apm.pars.solid_plate_id,
                machine_name="legacy",
            ).dict(),
        },
    )
    return apm.action_list


def ANEC_load_solid(
    experiment: Experiment,
    solid_plate_id: Optional[int] = 0,
    solid_sample_no: Optional[int] = 0,
    reservoir_liquid_sample_no: Optional[int] = 0,
    recirculation_time: Optional[float] = 60,
    toolGC: Optional[str] = "HS 2",
    volume_ul_GC: Optional[int] = 300,
):
    """Load solid and clean cell."""

    apm = ActionPlanMaker()
    apm.add_action_list(ANEC_unload_cell(experiment))
    apm.add(
        PAL_server,
        "archive_custom_load",
        {
            "custom": "cell1_we",
            "load_sample_in": SolidSample(
                sample_no=apm.pars.solid_sample_no,
                plate_id=apm.pars.solid_plate_id,
                machine_name="legacy",
            ).dict(),
        },
    )
    apm.add_action_list(ANEC_drain_cell(experiment))
    apm.add_action_list(
        ANEC_flush_fill_cell(
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
    )
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 1})
    apm.add_action_list(ANEC_drain_cell(experiment))
    return apm.action_list


def ANEC_run_CA_vsRef(
    experiment: Experiment,
    CA_potential_vsRef: Optional[float] = 0.0,
    CA_duration_sec: Optional[float] = 0.1,
    ref_vs_nhe: Optional[float] = 0.21,
    reservoir_liquid_sample_no: Optional[int] = 0,
    volume_ul_cell_liquid: Optional[int] = 1000,
    toolGC: Optional[str] = "HS 2",
    toolarchive: Optional[str] = "LS 3",
    source: Optional[str] = "cell1_we",
    volume_ul_GC: Optional[int] = 300,
    volume_ul_archive: Optional[int] = 500,
    wash1: Optional[bool] = True,
    wash2: Optional[bool] = True,
    wash3: Optional[bool] = True,
    wash4: Optional[bool] = False,
    SampleRate: Optional[float] = 0.01,
    TTLwait: Optional[int] = -1,
    TTLsend: Optional[int] = -1,
    IErange: Optional[str] = "auto",
):
    """Flush and fill cell, run CA, and drain.
    
    (1) Fill cell with liquid for 90 seconds
    (2) Equilibrate for 15 seconds
    (3) run CA
    (4) mix product
    (5) Drain cell and purge with CO2 for 60 seconds

    Args:
        exp (Experiment): Active experiment object supplied by Orchestrator
        toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
        volume_ul_GC: GC injection volume

    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    potential_vsRef = (
        apm.pars.CA_potential_vsRef
        - 1.0 * apm.pars.ref_vs_nhe
    )
    apm.add_action_list(
        ANEC_flush_fill_cell(
            experiment=experiment,
            reservoir_liquid_sample_no=apm.pars.reservoir_liquid_sample_no,
            volume_ul_cell_liquid=apm.pars.volume_ul_cell_liquid,
        )
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
            "Vval": potential_vsRef, 
            "Tval": apm.pars.CA_duration_sec,
            "SampleRate": apm.pars.SampleRate,
            "TTLwait": apm.pars.TTLwait,  # -1 disables, else select TTL 0-3
            "TTLsend": apm.pars.TTLsend,  # -1 disables, else select TTL 0-3
            "IErange": apm.pars.IErange,
        },
        from_global_params={"_fast_samples_in": "fast_samples_in"},
    )
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
    )
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 1})
    apm.add_action_list(ANEC_drain_cell(experiment))
    apm.add_action_list(ANEC_normal_state(experiment))
    return apm.action_list


def ANEC_run_CA_vsRHE(
    experiment: Experiment,
    CA_potential_vsRHE: Optional[float] = 0.0,
    CA_duration_sec: Optional[float] = 0.1,
    solution_ph: Optional[float] = 9.0,
    ref_vs_nhe: Optional[float] = 0.21,
    reservoir_liquid_sample_no: Optional[int] = 0,
    volume_ul_cell_liquid: Optional[int] = 1000,
    toolGC: Optional[str] = "HS 2",
    toolarchive: Optional[str] = "LS 3",
    source: Optional[str] = "cell1_we",
    volume_ul_GC: Optional[int] = 300,
    volume_ul_archive: Optional[int] = 500,
    wash1: Optional[bool] = True,
    wash2: Optional[bool] = True,
    wash3: Optional[bool] = True,
    wash4: Optional[bool] = False,
    SampleRate: Optional[float] = 0.01,
    TTLwait: Optional[int] = -1,
    TTLsend: Optional[int] = -1,
    IErange: Optional[str] = "auto",
):
    """Flush and fill cell, run CA, and drain.
    
    (1) Fill cell with liquid for 90 seconds
    (2) Equilibrate for 15 seconds
    (3) run CA
    (4) mix product
    (5) Drain cell and purge with CO2 for 60 seconds

    Args:
        exp (Experiment): Active experiment object supplied by Orchestrator
        toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
        volume_ul_GC: GC injection volume

    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    potential_vsWE = (
        apm.pars.CA_potential_vsRHE
        - 1.0 * apm.pars.ref_vs_nhe
        - 0.059 * apm.pars.solution_ph
    )
    apm.add_action_list(
        ANEC_flush_fill_cell(
            experiment=experiment,
            reservoir_liquid_sample_no=apm.pars.reservoir_liquid_sample_no,
            volume_ul_cell_liquid=apm.pars.volume_ul_cell_liquid,
        )
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
            "Vval": potential_vsWE,
            "Tval": apm.pars.CA_duration_sec,
            "SampleRate": apm.pars.SampleRate,
            "TTLwait": apm.pars.TTLwait,  # -1 disables, else select TTL 0-3
            "TTLsend": apm.pars.TTLsend,  # -1 disables, else select TTL 0-3
            "IErange": apm.pars.IErange,
        },
        from_global_params={"_fast_samples_in": "fast_samples_in"},
    )
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
    )
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 1})
    apm.add_action_list(ANEC_drain_cell(experiment))
    apm.add_action_list(ANEC_normal_state(experiment))
    return apm.action_list


# def ANEC_slave_engage(experiment: Experiment):
#     """Slave experiment
#     Engages and seals electrochemical cell.

#     last functionality test: untested"""

#     apm = ActionPlanMaker()  # exposes function parameters via apm.pars

#     # engage
#     apm.add_action(
#         {
#             "action_server": MOTOR_server,
#             "action_name": "move",
#             "action_params": {
#                 "d_mm": [z_engage],
#                 "axis": ["z"],
#                 "mode": MoveModes.absolute,
#                 "transformation": TransformationModes.instrxy,
#             },
#             "save_act": debug_save_act,
#             "save_data": debug_save_data,
#             "start_condition": ActionStartCondition.wait_for_all,
#         }
#     )

#     # seal
#     apm.add_action(
#         {
#             "action_server": MOTOR_server,
#             "action_name": "move",
#             "action_params": {
#                 "d_mm": [z_seal],
#                 "axis": ["z"],
#                 "mode": MoveModes.absolute,
#                 "transformation": TransformationModes.instrxy,
#             },
#             "save_act": debug_save_act,
#             "save_data": debug_save_data,
#             "start_condition": ActionStartCondition.wait_for_all,
#         }
#     )

#     return apm.action_list  # returns complete action list to orch


# def ANEC_slave_disengage(experiment: Experiment):
#     """Slave experiment
#     Disengages and seals electrochemical cell.

#     last functionality test: untested"""

#     apm = ActionPlanMaker()  # exposes function parameters via apm.pars

#     apm.add_action(
#         {
#             "action_server": MOTOR_server,
#             "action_name": "move",
#             "action_params": {
#                 "d_mm": [z_home],
#                 "axis": ["z"],
#                 "mode": MoveModes.absolute,
#                 "transformation": TransformationModes.instrxy,
#             },
#             "save_act": debug_save_act,
#             "save_data": debug_save_data,
#             "start_condition": ActionStartCondition.wait_for_all,
#         }
#     )

#     return apm.action_list  # returns complete action list to orch


# def ANEC_slave_clean_PALtool(
#     experiment: Experiment,
#     clean_tool: Optional[str] = PALtools.LS3,
#     clean_volume_ul: Optional[int] = 500,
# ):
#     """Slave experiment
#     Performs deep clean of selected PAL tool.

#     last functionality test: untested"""

#     apm = ActionPlanMaker()  # exposes function parameters via apm.pars

#     # deep clean
#     apm.add_action(
#         {
#             "action_server": PAL_server,
#             "action_name": "PAL_deepclean",
#             "action_params": {
#                 "tool": apm.pars.clean_tool,
#                 "volume_ul": apm.pars.clean_volume_ul,
#             },
#             "start_condition": ActionStartCondition.wait_for_all,
#         }
#     )

#     return apm.action_list  # returns complete action list to orch


# def ANEC_slave_CA(
#     experiment: Experiment,
#     CA_potential: Optional[float] = 0.0,
#     ph: float = 9.53,
#     ref_vs_nhe: float = 0.21,
#     samplerate_sec: Optional[float] = 1,
#     OCV_duration_sec: Optional[float] = 60,
#     CA_duration_sec: Optional[float] = 1320,
#     aliquot_times_sec: Optional[List[float]] = [60, 600, 1140],
# ):
#     """last functionality test: untested"""

#     apm = ActionPlanMaker()  # exposes function parameters via apm.pars

#     # get sample for gamry
#     apm.add_action(
#         {
#             "action_server": PAL_server,
#             "action_name": "archive_custom_query_sample",
#             "action_params": {
#                 "custom": "cell1_we",
#             },
#             "to_global_params": [
#                 "_fast_sample_in"
#             ],  # save new liquid_sample_no of eche cell to globals
#             "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
#         }
#     )

#     # OCV
#     apm.add_action(
#         {
#             "action_server": PSTAT_server,
#             "action_name": "run_OCV",
#             "action_params": {
#                 "Tval": apm.pars.OCV_duration_sec,
#                 "SampleRate": apm.pars.samplerate_sec,
#                 "TTLwait": -1,  # -1 disables, else select TTL 0-3
#                 "TTLsend": -1,  # -1 disables, else select TTL 0-3
#                 "IErange": "auto",
#             },
#             "from_global_params": {"_fast_sample_in": "fast_samples_in"},
#             "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
#         }
#     )

#     # take liquid sample
#     apm.add_action(
#         {
#             "action_server": PAL_server,
#             "action_name": "PAL_archive",
#             "action_params": {
#                 "tool": PALtools.LS3,
#                 "source": "cell1_we",
#                 "volume_ul": 200,
#                 "sampleperiod": [0.0],
#                 "spacingmethod": Spacingmethod.linear,
#                 "spacingfactor": 1.0,
#                 "timeoffset": 0.0,
#                 "wash1": 0,
#                 "wash2": 0,
#                 "wash3": 0,
#                 "wash4": 0,
#             },
#             "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
#         }
#     )

#     apm.add_action(
#         {
#             "action_server": PAL_server,
#             "action_name": "archive_custom_query_sample",
#             "action_params": {
#                 "custom": "cell1_we",
#             },
#             "to_global_params": [
#                 "_fast_sample_in"
#             ],  # save new liquid_sample_no of eche cell to globals
#             "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
#         }
#     )

#     # apmply potential
#     potential = apm.pars.CA_potential - 1.0 * apm.pars.ref_vs_nhe - 0.059 * apm.pars.ph
#     print(f"ANEC_slave_CA potential: {potential}")
#     apm.add_action(
#         {
#             "action_server": PSTAT_server,
#             "action_name": "run_CA",
#             "action_params": {
#                 "Vval": potential,
#                 "Tval": apm.pars.CA_duration_sec,
#                 "SampleRate": apm.pars.samplerate_sec,
#                 "TTLwait": -1,  # -1 disables, else select TTL 0-3
#                 "TTLsend": -1,  # -1 disables, else select TTL 0-3
#                 "IErange": "auto",
#             },
#             "from_global_params": {"_fast_sample_in": "fast_samples_in"},
#             "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
#         }
#     )

#     # take multiple scheduled liquid samples
#     apm.add_action(
#         {
#             "action_server": PAL_server,
#             "action_name": "PAL_archive",
#             "action_params": {
#                 "tool": PALtools.LS3,
#                 "source": "cell1_we",
#                 "volume_ul": 200,
#                 "sampleperiod": apm.pars.aliquot_times_sec,  # 1min, 10min, 10min
#                 "spacingmethod": Spacingmethod.custom,
#                 "spacingfactor": 1.0,
#                 "timeoffset": 60.0,
#                 "wash1": 0,
#                 "wash2": 0,
#                 "wash3": 0,
#                 "wash4": 0,
#             },
#             "start_condition": ActionStartCondition.wait_for_endpoint,  # orch is waiting for all action_dq to finish
#         }
#     )

#     # take last liquid sample and clean
#     apm.add_action(
#         {
#             "action_server": PAL_server,
#             "action_name": "PAL_archive",
#             "action_params": {
#                 "tool": PALtools.LS3,
#                 "source": "cell1_we",
#                 "volume_ul": 200,
#                 "sampleperiod": [0.0],
#                 "spacingmethod": Spacingmethod.linear,
#                 "spacingfactor": 1.0,
#                 "timeoffset": 0.0,
#                 "wash1": 1,  # dont use True or False but 0 AND 1
#                 "wash2": 1,
#                 "wash3": 1,
#                 "wash4": 1,
#             },
#             "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
#         }
#     )

#     return apm.action_list  # returns complete action list to orch


# def ANEC_slave_tray_unload(
#     experiment: Experiment,
#     tray: Optional[int] = 2,
#     slot: Optional[int] = 1,
#     survey_runs: Optional[int] = 1,
#     main_runs: Optional[int] = 3,
#     rack: Optional[int] = 2,
# ):
#     """Unloads a selected tray from PAL position tray-slot and creates
#     (1) json
#     (2) csv
#     (3) icpms
#     exports.

#     Parameters for ICPMS export are
#     survey_runs: rough sweep over the whole mass range
#     main_runs: sweep channel centered on element mass
#     rack: position of the tray in the icpms instrument, usually 2.
#     """

#     apm = ActionPlanMaker()  # exposes function parameters via apm.pars

#     apm.add_action(
#         {
#             "action_server": PAL_server,
#             "action_name": "archive_tray_export_json",
#             "action_params": {
#                 "tray": apm.pars.tray,
#                 "slot": apm.pars.slot,
#             },
#             "start_condition": ActionStartCondition.wait_for_all,
#         }
#     )

#     apm.add_action(
#         {
#             "action_server": PAL_server,
#             "action_name": "archive_tray_export_csv",
#             "action_params": {
#                 "tray": apm.pars.tray,
#                 "slot": apm.pars.slot,
#             },
#             "start_condition": ActionStartCondition.wait_for_all,
#         }
#     )

#     apm.add_action(
#         {
#             "action_server": PAL_server,
#             "action_name": "archive_tray_export_icpms",
#             "action_params": {
#                 "tray": apm.pars.tray,
#                 "slot": apm.pars.slot,
#                 "survey_runs": apm.pars.survey_runs,
#                 "main_runs": apm.pars.main_runs,
#                 "rack": apm.pars.rack,
#             },
#             "start_condition": ActionStartCondition.wait_for_all,
#         }
#     )

#     apm.add_action(
#         {
#             "action_server": PAL_server,
#             "action_name": "archive_tray_unload",
#             "action_params": {
#                 "tray": apm.pars.tray,
#                 "slot": apm.pars.slot,
#             },
#             "start_condition": ActionStartCondition.wait_for_all,
#         }
#     )

#     return apm.action_list  # returns complete action list to orch
