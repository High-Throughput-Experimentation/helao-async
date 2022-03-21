"""
Action library for ANEC

server_key must be a FastAPI action server defined in config
"""

__all__ = [
    "ANEC_slave_drain_cell",
    "ANEC_slave_flush_fill_cell",
    "ANEC_slave_load_solid_only",
    "ANEC_slave_load_solid",
    "ANEC_slave_load_solid_and_clean_cell",
    "ANEC_slave_unload_cell",
    "ANEC_slave_unload_liquid",
    "ANEC_slave_normal_state",
    "ANEC_slave_GC_preparation",
    "ANEC_slave_cleanup",
    "ANEC_slave_CA_vsRef",
    "ANEC_slave_aliquot",
    "ANEC_slave_alloff",
]

###
from socket import gethostname
from typing import Optional

from helaocore.schema import Experiment, ActionPlanMaker
from helao.library.driver.pal_driver import PALtools
from helaocore.model.sample import SolidSample, LiquidSample
from helaocore.model.machine import MachineModel
from helaocore.model.action_start_condition import ActionStartCondition
from helaocore.model.process_contrib import ProcessContrib


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


def ANEC_slave_load_solid(
    experiment: Experiment,
    solid_plate_id: Optional[int] = 4534,
    solid_sample_no: Optional[int] = 1,
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
            ).dict(),
        },
    )

    return apm.action_list


def ANEC_slave_alloff(
    experiment: Experiment,
):
    """

    Args:
        experiment (Experiment): Experiment object provided by Orch
    """

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 0})
    apm.add(NI_server, "pump", {"pump": "PeriPump2", "on": 0})
    apm.add(NI_server, "pump", {"pump": "Direction", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "down", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "up", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "liquid", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "atm", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "CO2", "on": 0})
    return apm.action_list


def ANEC_slave_normal_state(
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


def ANEC_slave_flush_fill_cell(
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


def ANEC_slave_unload_cell(experiment: Experiment):
    """Unload Sample at 'cell1_we' position."""

    apm = ActionPlanMaker()
    apm.add(PAL_server, "archive_custom_unloadall", {})
    return apm.action_list


def ANEC_slave_unload_liquid(experiment: Experiment):
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


def ANEC_slave_drain_cell(
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
    apm.add_action_list(ANEC_slave_unload_liquid(experiment))
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.drain_time})
    apm.add_action_list(ANEC_slave_normal_state(experiment))
    return apm.action_list


def ANEC_slave_cleanup(
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
        ANEC_slave_flush_fill_cell(
            experiment=experiment,
            reservoir_liquid_sample_no=apm.pars.reservoir_liquid_sample_no,
        )
    )
    apm.add_action_list(ANEC_slave_drain_cell(experiment))
    return apm.action_list


def ANEC_slave_GC_preparation(
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
            "toolGC": apm.pars.toolGC,
            "source": "cell1_we",
            "volume_ul_GC": apm.pars.volume_ul_GC,
        },
        process_finish=True,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    return apm.action_list


def ANEC_slave_load_solid_only(
    experiment: Experiment,
    solid_plate_id: Optional[int] = 1,
    solid_sample_no: Optional[int] = 1,
):
    """Load solid and clean cell."""

    apm = ActionPlanMaker()
    apm.add_action_list(ANEC_slave_unload_cell(experiment))
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


def ANEC_slave_load_solid_and_clean_cell(
    experiment: Experiment,
    solid_plate_id: Optional[int] = 1,
    solid_sample_no: Optional[int] = 1,
    reservoir_liquid_sample_no: Optional[int] = 1,
    recirculation_time: Optional[float] = 60,
    toolGC: Optional[str] = "HS 2",
    volume_ul_GC: Optional[int] = 300,
):
    """Load solid and clean cell."""

    apm = ActionPlanMaker()
    apm.add_action_list(ANEC_slave_unload_cell(experiment))
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
    apm.add_action_list(ANEC_slave_drain_cell(experiment))
    apm.add_action_list(
        ANEC_slave_flush_fill_cell(
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
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 1})
    apm.add_action_list(ANEC_slave_drain_cell(experiment))
    return apm.action_list


def ANEC_slave_aliquot(
    experiment: Experiment,
    toolGC: Optional[str] = "HS 2",
    toolarchive: Optional[str] = "LS 3",
    volume_ul_GC: Optional[int] = 300,
    volume_ul_archive: Optional[int] = 500,
    wash1: Optional[bool] = True,
    wash2: Optional[bool] = True,
    wash3: Optional[bool] = True,
    wash4: Optional[bool] = False,
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
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    apm.add(NI_server, "pump", {"pump": "PeriPump1", "on": 1})

    return apm.action_list


def ANEC_slave_CA_vsRef(
    experiment: Experiment,
    CA_potential_vsRef: Optional[float] = 0.0,
    CA_duration_sec: Optional[float] = 0.1,
    SampleRate: Optional[float] = 0.01,
    IErange: Optional[str] = "auto",
    ref_vs_nhe: Optional[float] = 0.21,
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    potential_vsRef = apm.pars.CA_potential_vsRef - 1.0 * apm.pars.ref_vs_nhe

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
            "TTLwait": -1,  # -1 disables, else select TTL 0-3
            "TTLsend": -1,  # -1 disables, else select TTL 0-3
            "IErange": apm.pars.IErange,
        },
        from_global_params={"_fast_samples_in": "fast_samples_in"},
        process_finish=True,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )

    # apm.add(ORCH_server, "wait", {"waittime": 10})

    return apm.action_list
