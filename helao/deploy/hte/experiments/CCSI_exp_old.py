"""Legacy experiment library for the CCSI station.

Earlier version of the CCSI experiment library, retained for reference.
Each function takes an ``Experiment`` and returns the list of actions to
enqueue. Action targets are referenced by ``server_key`` strings (e.g.
``PSTAT``, ``MOTOR``, ``NI``, ``PAL``, ``IO``, ``CALC``, ``CO2SENSOR``,
``MFC``, ``WORKSYRINGE``, ``WATERSYRINGE``, ``ORCH``).
"""

__all__ = [
    "CCSI_sub_unload_cell",
    "CCSI_sub_load_solid",
    "CCSI_sub_load_liquid",
    "CCSI_sub_load_gas",
    "CCSI_sub_alloff",
    "CCSI_sub_headspace_purge_and_measure",
    "CCSI_sub_drain",
    "CCSI_sub_initialization_end_state",
    "CCSI_sub_peripumpoff",
    "CCSI_sub_initialization_firstpart",
    "CCSI_sub_cellfill",
    "CCSI_sub_co2constantpressure",
    "CCSI_sub_co2mass_temp",
    "CCSI_sub_co2massdose",
    "CCSI_sub_co2maintainconcentration",
    "CCSI_sub_co2topup_mfcmassdose",
    "CCSI_sub_co2monitoring",
    "CCSI_sub_co2monitoring_mfcmasscotwo",
    "CCSI_sub_clean_inject",
    "CCSI_sub_refill_clean",
    "CCSI_debug_co2purge",
    "CCSI_sub_fill_syringe",
    "CCSI_sub_full_fill_syringe",
    "CCSI_leaktest_co2",
    "CCSI_sub_flowflush",
]

###
from socket import gethostname
from typing import Optional, Union

from helao.helpers.premodels import Experiment, ActionPlanMaker
from helao.core.models.action_start_condition import ActionStartCondition as asc
from helao.deploy.hte.drivers.robot.pal_driver import PALtools
from helao.core.models.sample import SolidSample, LiquidSample, GasSample
from helao.core.models.machine import MachineModel
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
CALC_server = MachineModel(server_name="CALC", machine_name=ORCH_HOST).as_dict()
CO2S_server = MachineModel(server_name="CO2SENSOR", machine_name=ORCH_HOST).as_dict()
MFC_server = MachineModel(server_name="MFC", machine_name=ORCH_HOST).as_dict()
WORKSYRINGE_server = MachineModel(
    server_name="WORKSYRINGE", machine_name=ORCH_HOST
).as_dict()
WATERCLEANSYRINGE_server = MachineModel(
    server_name="WATERSYRINGE", machine_name=ORCH_HOST
).as_dict()
toggle_triggertype = TriggerType.fallingedge


@experiment(version=1)
def CCSI_sub_unload_cell() -> list:
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
def CCSI_sub_load_solid(
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
) -> list:
    """Load a legacy solid plate sample into ``cell1_we``.

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
            ).dict(),
        },
    )

    return apm.planned_actions


@experiment(version=2)
def CCSI_sub_load_liquid(
    reservoir_liquid_sample_no: int = 1,
    volume_ul_cell_liquid: int = 1000,
    water_True_False: bool = False,
    combine_True_False: bool = False,
) -> list:
    """Archive a liquid sample addition into ``cell1_we``.

    Args:
        experiment: Orchestrator-provided experiment context.
        reservoir_liquid_sample_no: Liquid sample number in the reservoir.
        volume_ul_cell_liquid: Volume added (uL).
        water_True_False: Forwarded as ``dilute_liquids`` to PAL.
        combine_True_False: Forwarded as ``combine_liquids`` to PAL.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()

    # (3) Create liquid sample and add to assembly
    apm.add(
        PAL_server,
        "archive_custom_add_liquid",
        {
            "custom": "cell1_we",
            "source_liquid_in": LiquidSample(
                sample_no=reservoir_liquid_sample_no, machine_name=ORCH_HOST
            ).dict(),
            "volume_ml": volume_ul_cell_liquid / 1000,
            "combine_liquids": combine_True_False,
            "dilute_liquids": water_True_False,
        },
    )
    return apm.planned_actions


@experiment(version=2)
def CCSI_sub_load_gas(
    reservoir_gas_sample_no: int = 1,
    volume_ul_cell_gas: int = 1000,
) -> list:
    """Load a gas sample into ``cell1_we``.

    Args:
        experiment: Orchestrator-provided experiment context.
        reservoir_gas_sample_no: Gas sample number in the reservoir.
        volume_ul_cell_gas: Volume added (uL).

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()
    apm.add(
        PAL_server,
        "archive_custom_load",  # not sure there is a server function for gas
        {
            "custom": "cell1_we",
            "load_sample_in": GasSample(
                sample_no=reservoir_gas_sample_no, machine_name=ORCH_HOST
            ).dict(),
            "volume_ml": volume_ul_cell_gas / 1000,
        },
    )
    return apm.planned_actions


@experiment(version=1)
def CCSI_sub_alloff(
) -> list:
    """Turn the recirculating pump off and close every CCSI gas/liquid valve.

    Args:
        experiment: Orchestrator-provided experiment context.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()
    apm.add(
        NI_server,
        "pump",
        {
            "pump": "RecirculatingPeriPump1",
            "on": 0,
        },
    )
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "8", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "9", "on": 0}, asc.no_wait)

    return apm.planned_actions


@experiment(version=6)
def CCSI_sub_headspace_purge_and_measure(
    HSpurge_duration: float = 20,
    DeltaDilute1_duration: float = 0,
    initialization: bool = False,
    co2measure_duration: float = 20,
    co2measure_acqrate: float = 0.1,
    co2_ppm_thresh: float = 90000,
    purge_if: Union[str, float] = "below",
    max_repeats: int = 5,
) -> list:
    """Run a headspace purge then acquire CO2 from the recirculated headspace.

    Args:
        experiment: Orchestrator-provided experiment context.
        HSpurge_duration: Headspace purge time (s).
        DeltaDilute1_duration: Optional dilution recirc time (s); ``0`` skips.
        initialization: Toggle initialization-specific valve sequencing.
        co2measure_duration: Acquisition duration (s).
        co2measure_acqrate: Acquisition rate (s).
        co2_ppm_thresh: CO2 threshold for the calling sequence.
        purge_if: ``"above"``/``"below"`` or a numeric threshold.
        max_repeats: Maximum follow-up repeats for the calling sequence.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    if DeltaDilute1_duration == 0:
        apm.add(ORCH_server, "wait", {"waittime": 0.25})
    else:

        #
        # DILUTION PURGE
        apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})
        apm.add(
            ORCH_server, "wait", {"waittime": DeltaDilute1_duration}
        )  # DeltaDilute time usually 15

    #
    # MAIN HEADSPACE PURGE
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 1}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 1}, asc.no_wait)

    apm.add(ORCH_server, "wait", {"waittime": HSpurge_duration})

    if initialization:
        apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": 0.5})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0})

    if initialization:
        apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})

    #
    # HEADSPACE EVALUATION
    apm.add(
        CO2S_server,
        "acquire_co2",
        {
            "duration": co2measure_duration,
            "acquisition_rate": co2measure_acqrate,
        },
        technique_name="gas_purge",
        process_finish=True,
        process_contrib=[ProcessContrib.files],
    )
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1}, asc.no_wait)
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})

    return apm.planned_actions


@experiment(version=5)
def CCSI_sub_drain(
    HSpurge_duration: float = 20,
    DeltaDilute1_duration: float = 0,
    initialization: bool = False,
    recirculation: bool = False,
    recirculation_duration: float = 20,
) -> list:
    """Drain the cell with a valve+gas-purge sequence and optional recirculation.

    Args:
        experiment: Orchestrator-provided experiment context.
        HSpurge_duration: Headspace purge time (s).
        DeltaDilute1_duration: Optional dilution recirc time (s); ``0`` skips.
        initialization: Toggle initialization-specific valve sequencing.
        recirculation: Run a recirculation stage mid-purge when True.
        recirculation_duration: Recirculation time (s).

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()
    if DeltaDilute1_duration == 0:
        apm.add(ORCH_server, "wait", {"waittime": 0.25})
    else:

        #
        # DILUTION PURGE
        apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})
        apm.add(
            ORCH_server, "wait", {"waittime": DeltaDilute1_duration}
        )  # DeltaDilute time usually 15

    #
    # MAIN HEADSPACE PURGE and FILL
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 1}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 1}, asc.no_wait)

    apm.add(ORCH_server, "wait", {"waittime": HSpurge_duration})
    if recirculation:
        apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": recirculation_duration})
        apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})

    if initialization:
        apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": 0.5})

    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0})
    if initialization:
        apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0}, asc.no_wait)

    return apm.planned_actions


@experiment(version=1)
def CCSI_sub_initialization_end_state(
) -> list:
    """Place the system into its post-initialization state by turning the pump off.

    Args:
        experiment: Orchestrator-provided experiment context.

    Returns:
        List of planned actions for the orchestrator.
    """
    # only Pump off, 1A closed //

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    # apm.add(ORCH_server, "wait", {"waittime": 0.25})
    # apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 1})
    # apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1}, asc.no_wait)
    # apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1}, asc.no_wait)
    # apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0}, asc.no_wait)
    # apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0}, asc.no_wait)
    # apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0}, asc.no_wait)
    # apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0}, asc.no_wait)
    # apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0}, asc.no_wait)
    # apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0}, asc.no_wait)
    # apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0}, asc.no_wait)
    # apm.add(ORCH_server, "wait", {"waittime": 0.25})
    # apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0})
    # apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0}, asc.no_wait)
    # apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0}, asc.no_wait)
    #   apm.add(MFC---stuff Flow ON)
    return apm.planned_actions


@experiment(version=1)
def CCSI_sub_peripumpoff(
) -> list:
    """Turn the recirculating peristaltic pump off.

    Args:
        experiment: Orchestrator-provided experiment context.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    # apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 1}, asc.no_wait)
    # apm.add(ORCH_server, "wait", {"waittime": 0.25})
    # apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1})
    # apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1}, asc.no_wait)
    # apm.add(ORCH_server, "wait", {"waittime": 0.25})
    # apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0})
    # apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0}, asc.no_wait)
    # apm.add(NI_server, "gasvalve", {"gasvalve": "7", "on": 0}, asc.no_wait)

    return apm.planned_actions


@experiment(version=3)
def CCSI_sub_initialization_firstpart(
    HSpurge1_duration: float = 60,
    Manpurge1_duration: float = 10,
    Alphapurge1_duration: float = 10,
    Probepurge1_duration: float = 10,
    Sensorpurge1_duration: float = 15,
    #    DeltaDilute1_duration: float = 15,
) -> list:
    """Run the first-time CCSI initialization purge sequence (headspace → probe → sensor).

    Args:
        experiment: Orchestrator-provided experiment context.
        HSpurge1_duration: Main headspace purge duration (s).
        Manpurge1_duration: Manifold/solvent purge duration (s).
        Alphapurge1_duration: Line/alpha purge duration (s).
        Probepurge1_duration: Probe purge duration (s).
        Sensorpurge1_duration: pCO2 sensor purge duration (s).

    Returns:
        List of planned actions for the orchestrator.
    """
    #
    # ALL OFF
    apm = ActionPlanMaker()
    apm.add(
        NI_server,
        "pump",
        {
            "pump": "RecirculatingPeriPump1",
            "on": 0,
        },
    )
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "8", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "9", "on": 0}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})

    #
    # MAIN HEADSPACE PURGE and FILL
    # headspace flow purge cell via v1 v6
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 1}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": HSpurge1_duration})

    #  sub_solvent purge//headspace flow purge eta via v2 v6

    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 1}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 1}, asc.no_wait)
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD0", "on": 0}, asc.no_wait)
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD1", "on": 0}, asc.no_wait)
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD2", "on": 1}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": Manpurge1_duration})

    # line purge via v2 v5

    apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 1}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": Alphapurge1_duration})

    #
    # AUX PROBE PURGE
    # eche probe flow purge via v5
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5A-cell", "on": 0}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": Probepurge1_duration})

    #
    # pCO2 SENSOR PURGE
    # only valve 3 closed //differ from probe purge
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "3", "on": 0}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": Sensorpurge1_duration})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "7A", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0}, asc.no_wait)
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "4", "on": 0}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "5B-waste", "on": 0}, asc.no_wait)

    return apm.planned_actions


@experiment(version=1)
def CCSI_sub_cellfill(
    #   formerly def CCSI_sub_liquidfill_syringes(
    #    experiment_version: int = 10, #ver 6to7 implements multivalve, #10 gas push between
    Solution_description: str = "KOH",
    Solution_reservoir_sample_no: int = 2,
    Solution_volume_ul: float = 500,
    Clean_reservoir_sample_no: int = 1,
    Clean_volume_ul: float = 2500,
    Syringe_rate_ulsec: float = 300,
    LiquidFillWait_s: float = 15,
    #    co2measure_duration: float = 20,
    #    co2measure_acqrate: float = 0.5,
) -> list:
    """Fill the CCSI cell with the work-syringe solution and then a clean-syringe top-up.

    Each non-zero volume stage opens the multivalve, infuses via the
    corresponding syringe, and follows with a CO2 push by toggling gas
    valves.

    Args:
        experiment: Orchestrator-provided experiment context.
        Solution_description: Free-text solution label.
        Solution_reservoir_sample_no: Liquid sample number for the solution.
        Solution_volume_ul: Solution volume (uL); ``0`` skips.
        Clean_reservoir_sample_no: Liquid sample number for the clean stage.
        Clean_volume_ul: Clean volume (uL); ``0`` skips.
        Syringe_rate_ulsec: Syringe rate (uL/s).
        LiquidFillWait_s: Wait after each gas push (s).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {
            "custom": "cell1_we",
        },
        to_global_params=[
            "_fast_samples_in"
        ],  # save new liquid_sample_no of eche cell to globals
    )

    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 1}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    ### CO2 acquisition that matters //// does not.
    # during first infusion
    #    inf1_acqtime = Solution_volume_ul/Syringe_rate_ulsec + .25
    #    apm.add(CO2S_server, "acquire_co2", {"duration": inf1_acqtime, "acquisition_rate": co2measure_acqrate})

    if Solution_volume_ul == 0:
        apm.add(ORCH_server, "wait", {"waittime": 0.25})
    else:
        apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD2", "on": 1})
        apm.add(
            NI_server, "multivalve", {"multivalve": "multi_CMD1", "on": 1}, asc.no_wait
        )
        apm.add(
            NI_server, "multivalve", {"multivalve": "multi_CMD0", "on": 1}, asc.no_wait
        )
        if Clean_volume_ul == 0:
            procfinish = True
        else:
            procfinish = False
        apm.add(
            WORKSYRINGE_server,
            "infuse",
            {
                "rate_uL_sec": Syringe_rate_ulsec,
                "volume_uL": Solution_volume_ul,
            },
            from_global_act_params={"_fast_samples_in": "fast_samples_in"},
            technique_name="syringe_inject",
            process_finish=procfinish,
            process_contrib=[
                ProcessContrib.action_params,
                ProcessContrib.samples_in,
            ],
        )
        apm.add(ORCH_server, "wait", {"waittime": 5.25})
        apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 1})
        apm.add(
            NI_server, "multivalve", {"multivalve": "multi_CMD0", "on": 0}, asc.no_wait
        )
        apm.add(
            NI_server, "multivalve", {"multivalve": "multi_CMD1", "on": 0}, asc.no_wait
        )
        apm.add(
            NI_server, "multivalve", {"multivalve": "multi_CMD2", "on": 1}, asc.no_wait
        )
        apm.add(ORCH_server, "wait", {"waittime": LiquidFillWait_s})
        apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 0})

    apm.add(ORCH_server, "wait", {"waittime": 0.25})

    if Clean_volume_ul == 0:
        apm.add(ORCH_server, "wait", {"waittime": 0.25})
    else:
        apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD2", "on": 1})
        apm.add(
            NI_server, "multivalve", {"multivalve": "multi_CMD1", "on": 1}, asc.no_wait
        )
        apm.add(
            NI_server, "multivalve", {"multivalve": "multi_CMD0", "on": 0}, asc.no_wait
        )
        if Solution_volume_ul == 0:
            proccontrib = [
                ProcessContrib.action_params,
                ProcessContrib.samples_in,
            ]
        else:
            proccontrib = [
                ProcessContrib.action_params,
            ]

        apm.add(
            WATERCLEANSYRINGE_server,
            "infuse",
            {
                "rate_uL_sec": Syringe_rate_ulsec,
                "volume_uL": Clean_volume_ul,
            },
            from_global_act_params={"_fast_samples_in": "fast_samples_in"},
            technique_name="syringe_inject",
            process_finish=True,
            process_contrib=proccontrib,
        )
        apm.add(ORCH_server, "wait", {"waittime": 5.25})
        apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 1})
        apm.add(
            NI_server, "multivalve", {"multivalve": "multi_CMD0", "on": 0}, asc.no_wait
        )
        apm.add(
            NI_server, "multivalve", {"multivalve": "multi_CMD1", "on": 0}, asc.no_wait
        )
        apm.add(
            NI_server, "multivalve", {"multivalve": "multi_CMD2", "on": 1}, asc.no_wait
        )
        apm.add(ORCH_server, "wait", {"waittime": LiquidFillWait_s})
        apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 0})

    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": 1.75})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0}, asc.no_wait)
    return apm.planned_actions


@experiment(version=1)
def CCSI_sub_co2monitoring(
    co2measure_duration: float = 20,
    co2measure_acqrate: float = 0.5,
) -> list:
    """Acquire CO2 ppm in the recirculated headspace, then stop the pump.

    Args:
        experiment: Orchestrator-provided experiment context.
        co2measure_duration: Acquisition duration (s).
        co2measure_acqrate: Acquisition rate (s).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()

    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    #    apm.add(IO_server, "acquire_analog_in", {"duration":co2measure_duration + 1,"acquisition_rate": co2measure_acqrate, })
    apm.add(
        CO2S_server,
        "acquire_co2",
        {
            "duration": co2measure_duration,
            "acquisition_rate": co2measure_acqrate,
        },
        # asc.no_wait,
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        technique_name="Measure_recirculated_headspace",
        process_finish=True,
        process_contrib=[
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": co2measure_duration})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})

    return apm.planned_actions


@experiment(version=1)
def CCSI_sub_co2monitoring_mfcmasscotwo(
    co2measure_duration: float = 300,
    co2measure_acqrate: float = 0.5,
    flowrate_sccm: float = 0.3,
    flowramp_sccm: float = 9,
    init_max_flow_s: float = 30,
) -> list:
    """Step up MFC flow, then ramp to ``flowrate_sccm`` while recirculating and recording CO2.

    Args:
        experiment: Orchestrator-provided experiment context.
        co2measure_duration: Total CO2 acquisition duration (s).
        co2measure_acqrate: Acquisition rate (s).
        flowrate_sccm: Steady MFC flow rate (sccm).
        flowramp_sccm: MFC ramp rate (sccm/s).
        init_max_flow_s: Initial high-flow ramp duration (s).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()

    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    #    apm.add(IO_server, "acquire_analog_in", {"duration":co2measure_duration + 1,"acquisition_rate": co2measure_acqrate, }, nonblocking=True)
    apm.add(
        MFC_server,
        "acquire_flowrate",
        {
            "flowrate_sccm": 0.5,
            "ramp_sccm_sec": flowramp_sccm,
            "duration": init_max_flow_s,
            "acquisition_rate": co2measure_acqrate,
        },
        asc.no_wait,
    )
    # need to account for gas sample
    apm.add(
        CO2S_server,
        "acquire_co2",
        {
            "duration": co2measure_duration,
            "acquisition_rate": co2measure_acqrate,
        },
        asc.no_wait,
        nonblocking=True,
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        technique_name="Measure_recirculated_headspace",
        process_finish=True,
        process_contrib=[
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1}, asc.no_wait)

    apm.add(
        MFC_server,
        "acquire_flowrate",
        {
            "flowrate_sccm": flowrate_sccm,
            "ramp_sccm_sec": flowramp_sccm,
            "duration": co2measure_duration - init_max_flow_s,
            "acquisition_rate": co2measure_acqrate,
        },
    )

    #    apm.add(ORCH_server, "wait", {"waittime": co2measure_duration})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})

    return apm.planned_actions


@experiment(version=1)
def CCSI_sub_co2topup_mfcmassdose(
    co2measure_acqrate: float = 0.5,
    flowrate_sccm: float = 0.3,
    flowramp_sccm: float = 9,
    duration_s: float = 300,
    target_pressure: float = 14.30,
    total_gas_scc: float = 7.0,
    refill_freq_sec: float = 2.0,
) -> list:
    """Hold the cell at a target pressure by topping up CO2 via the MFC.

    Args:
        experiment: Orchestrator-provided experiment context.
        co2measure_acqrate: Acquisition rate (s).
        flowrate_sccm: MFC flow rate (sccm).
        flowramp_sccm: MFC ramp rate (sccm/s).
        duration_s: Pressure-maintenance duration (s).
        target_pressure: Pressure setpoint (psia).
        total_gas_scc: Allowance for total dispensed gas (scc).
        refill_freq_sec: Refill check interval (s).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()

    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    #    apm.add(IO_server, "acquire_analog_in", {"duration":duration_s,"acquisition_rate": co2measure_acqrate, })
    apm.add(
        MFC_server,
        "acquire_flowrate",
        {
            "flowrate_sccm": None,
            "duration": -1,
            "acquisition_rate": co2measure_acqrate,
        },
        technique_name="Measure_added_co2",
        process_finish=True,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
        ],
    )
    # need to account for gas sample
    apm.add(
        MFC_server,
        "maintain_pressure",
        {
            "flowrate_sccm": flowrate_sccm,
            "ramp_sccm_sec": flowramp_sccm,
            "duration": duration_s,
            "target_pressure": target_pressure,
            "total_gas_scc": total_gas_scc,
            "refill_freq_sec": refill_freq_sec,
        },
        asc.no_wait,
    )
    apm.add(MFC_server, "cancel_acquire_flowrate", {})

    return apm.planned_actions


@experiment(version=1)
def CCSI_sub_co2constantpressure(
    co2measure_duration: float = 20,
    co2measure_acqrate: float = 0.5,
    atm_pressure: float = 14.27,
    pressureramp: float = 2,
) -> list:
    """Hold a target pressure via the MFC and concurrently record CO2 ppm.

    Args:
        experiment: Orchestrator-provided experiment context.
        co2measure_duration: Acquisition duration (s).
        co2measure_acqrate: Acquisition rate (s).
        atm_pressure: Pressure setpoint (psia).
        pressureramp: Pressure ramp rate (psi/s).

    Returns:
        List of planned actions for the orchestrator.
    """
    # v2 v1ab open, sol inject clean inject

    apm = ActionPlanMaker()
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    #    apm.add(IO_server, "acquire_analog_in", {"duration":co2measure_duration + 1,"acquisition_rate": co2measure_acqrate, })
    apm.add(
        MFC_server,
        "acquire_pressure",
        {
            "pressure_psia": atm_pressure,
            "ramp_psi_sec": pressureramp,
            "duration": co2measure_duration,
            "acquisition_rate": co2measure_acqrate,
        },
        technique_name="Measure_added_co2",
        process_finish=False,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
        ],
    )
    # need to account for gas sample
    apm.add(
        CO2S_server,
        "acquire_co2",
        {
            "duration": co2measure_duration,
            "acquisition_rate": co2measure_acqrate,
        },
        asc.no_wait,
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        technique_name="Measure_recirculated_headspace",
        process_finish=True,
        process_contrib=[
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1}, asc.no_wait)
    #    apm.add(ORCH_server, "wait", {"waittime": co2measure_duration})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})

    return apm.planned_actions


@experiment(version=1)
def CCSI_sub_co2mass_temp(
    co2measure_duration: float = 300,
    co2measure_acqrate: float = 0.5,
    flowrate_sccm: float = 0.3,
    flowramp_sccm: float = 9,
    init_max_flow_s: float = 30,
) -> list:
    """Step up flow then ramp to ``flowrate_sccm`` while measuring CO2 and recirculating.

    Args:
        experiment: Orchestrator-provided experiment context.
        co2measure_duration: Total acquisition duration (s).
        co2measure_acqrate: Acquisition rate (s).
        flowrate_sccm: Steady MFC flow rate (sccm).
        flowramp_sccm: MFC ramp rate (sccm/s).
        init_max_flow_s: Initial high-flow ramp duration (s).

    Returns:
        List of planned actions for the orchestrator.
    """
    # v2 v1ab open, sol inject clean inject

    apm = ActionPlanMaker()
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    #    apm.add(IO_server, "acquire_analog_in", {"duration":co2measure_duration + 1,"acquisition_rate": co2measure_acqrate, }, nonblocking=True)
    apm.add(
        MFC_server,
        "acquire_flowrate",
        {
            "flowrate_sccm": 0.5,
            "ramp_sccm_sec": flowramp_sccm,
            "duration": init_max_flow_s,
            "acquisition_rate": co2measure_acqrate,
        },
        technique_name="Measure_added_co2",
        process_finish=False,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
        ],
    )
    # need to account for gas sample
    apm.add(
        CO2S_server,
        "acquire_co2",
        {
            "duration": co2measure_duration,
            "acquisition_rate": co2measure_acqrate,
        },
        asc.no_wait,
        nonblocking=True,
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        technique_name="Measure_recirculated_headspace",
        process_finish=False,
        process_contrib=[
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1}, asc.no_wait)

    apm.add(
        MFC_server,
        "acquire_flowrate",
        {
            "flowrate_sccm": flowrate_sccm,
            "ramp_sccm_sec": flowramp_sccm,
            "duration": co2measure_duration - init_max_flow_s,
            "acquisition_rate": co2measure_acqrate,
        },
        technique_name="Measure_added_co2",
        process_finish=True,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
        ],
    )

    #    apm.add(ORCH_server, "wait", {"waittime": co2measure_duration})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})

    return apm.planned_actions


@experiment(version=1)
def CCSI_sub_co2massdose(
    co2measure_duration: float = 300,
    co2measure_acqrate: float = 0.5,
    flowrate_sccm: float = 0.5,
    flowramp_sccm: float = 0,
    target_pressure: float = 14.30,
    total_gas_scc: float = 7.0,
    refill_freq_sec: float = 2.0,
) -> list:
    """Dose CO2 to a pressure setpoint while recording CO2 ppm.

    Args:
        experiment: Orchestrator-provided experiment context.
        co2measure_duration: CO2 acquisition duration (s).
        co2measure_acqrate: Acquisition rate (s).
        flowrate_sccm: MFC flow rate (sccm).
        flowramp_sccm: MFC ramp rate (sccm/s).
        target_pressure: Pressure setpoint (psia).
        total_gas_scc: Allowance for total dispensed gas (scc).
        refill_freq_sec: Refill check interval (s).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    #    apm.add(IO_server, "acquire_analog_in", {"duration":co2measure_duration + 1,"acquisition_rate": co2measure_acqrate, }, nonblocking=True)
    apm.add(
        MFC_server,
        "acquire_flowrate",
        {
            "flowrate_sccm": None,
            "duration": -1,
            "acquisition_rate": co2measure_acqrate,
        },
        nonblocking=True,
        technique_name="Measure_added_co2",
        process_finish=False,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
        ],
    )
    apm.add(
        MFC_server,
        "maintain_pressure",
        {
            "flowrate_sccm": flowrate_sccm,
            "ramp_sccm_sec": flowramp_sccm,
            "duration": co2measure_duration
            + 30,  # arbitrary time to allow for final correction
            "target_pressure": target_pressure,
            "total_gas_scc": total_gas_scc,
            "refill_freq_sec": refill_freq_sec,
        },
        asc.no_wait,
        nonblocking=True,
    )
    # need to account for gas sample
    apm.add(
        CO2S_server,
        "acquire_co2",
        {
            "duration": co2measure_duration,
            "acquisition_rate": co2measure_acqrate,
        },
        asc.no_wait,
        # nonblocking=True,
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        technique_name="Measure_recirculated_headspace",
        process_finish=True,
        process_contrib=[
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1}, asc.no_wait)

    #    apm.add(ORCH_server, "wait", {"waittime": co2measure_duration})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    apm.add(
        MFC_server,
        "cancel_acquire_flowrate",
        {},
    )

    return apm.planned_actions


@experiment(version=1)
def CCSI_sub_co2maintainconcentration(
    co2measure_duration: float = 300,
    co2measure_acqrate: float = 0.5,
    flowrate_sccm: float = 0.5,
    flowramp_sccm: float = 0,
    target_co2_ppm: float = 1e5,
    headspace_scc: float = 7.5,
    refill_freq_sec: float = 60.0,
) -> list:
    """Maintain a target CO2 concentration in the recirculated cell headspace.

    Args:
        experiment: Orchestrator-provided experiment context.
        co2measure_duration: Acquisition duration (s).
        co2measure_acqrate: Acquisition rate (s).
        flowrate_sccm: MFC flow rate (sccm).
        flowramp_sccm: MFC ramp rate (sccm/s).
        target_co2_ppm: Target CO2 concentration (ppm).
        headspace_scc: Headspace volume (scc).
        refill_freq_sec: Refill check interval (s).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {
            "custom": "cell1_we",
        },
        to_global_params=[
            "_fast_samples_in"
        ],  # save new liquid_sample_no of eche cell to globals
    )
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    #    apm.add(IO_server, "acquire_analog_in", {"duration":co2measure_duration + 1,"acquisition_rate": co2measure_acqrate, }, nonblocking=True)
    apm.add(
        MFC_server,
        "acquire_flowrate",
        {
            "flowrate_sccm": None,
            "duration": -1,
            "acquisition_rate": co2measure_acqrate,
        },
        nonblocking=True,
        technique_name="Measure_added_co2",
        process_finish=False,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
        ],
    )
    apm.add(
        MFC_server,
        "maintain_concentration",
        {
            "flowrate_sccm": flowrate_sccm,
            "ramp_sccm_sec": flowramp_sccm,
            "duration": co2measure_duration
            + 30,  # arbitrary time to allow for final correction
            "target_co2_ppm": target_co2_ppm,
            "headspace_scc": headspace_scc,
            "refill_freq_sec": refill_freq_sec,
        },
        asc.no_wait,
        nonblocking=True,
    )
    apm.add(
        CO2S_server,
        "acquire_co2",
        {
            "duration": co2measure_duration,
            "acquisition_rate": co2measure_acqrate,
        },
        asc.no_wait,
        # nonblocking=True,
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        technique_name="Measure_recirculated_headspace",
        process_finish=True,
        process_contrib=[
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1}, asc.no_wait)

    #    apm.add(ORCH_server, "wait", {"waittime": co2measure_duration})
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    apm.add(
        MFC_server,
        "cancel_acquire_flowrate",
        {},
    )

    return apm.planned_actions


@experiment(version=3)
def CCSI_sub_flowflush(
    co2measure_duration: float = 3600,
    co2measure_acqrate: float = 0.5,
    flowrate_sccm: float = 0.3,
    flowramp_sccm: float = 0,
) -> list:
    """Run a long flow-and-flush diagnostic with 60 valve-toggle cycles and CO2 logging.

    Args:
        experiment: Orchestrator-provided experiment context.
        co2measure_duration: Acquisition duration (s).
        co2measure_acqrate: Acquisition rate (s).
        flowrate_sccm: MFC flow rate (sccm).
        flowramp_sccm: MFC ramp rate (sccm/s).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()

    apm.add(
        MFC_server,
        "acquire_flowrate",
        {
            "flowrate_sccm": 0.5,
            "ramp_sccm_sec": flowramp_sccm,
            "duration": co2measure_duration,
            "acquisition_rate": co2measure_acqrate,
        },
        nonblocking=True,
    )
    apm.add(
        CO2S_server,
        "acquire_co2",
        {
            "duration": co2measure_duration,
            "acquisition_rate": co2measure_acqrate,
        },
        asc.no_wait,
        nonblocking=True,
    )
    apm.add(
        NI_server,
        "pump",
        {"pump": "RecirculatingPeriPump1", "on": 1},
        asc.no_wait,
        nonblocking=True,
    )

    # cycles = int(co2measure_duration / 30),
    for t in range(60):
        apm.add(ORCH_server, "wait", {"waittime": 28})
        apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": 2})
        apm.add(NI_server, "liquidvalve", {"liquidvalve": "6A-waste", "on": 0})
        apm.add(ORCH_server, "wait", {"waittime": 28})
        apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1})
        apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1}, asc.no_wait)
        apm.add(ORCH_server, "wait", {"waittime": 2})
        apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0})
        apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0}, asc.no_wait)

    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})
    return apm.planned_actions


#
# PRE CL
#


@experiment(version=7)
def CCSI_sub_clean_inject(
    Clean_volume_ul: float = 10000,
    Syringe_rate_ulsec: float = 500,
    LiquidCleanWait_s: float = 15,
    co2measure_duration: float = 20,
    co2measure_acqrate: float = 1,
    use_co2_check: bool = True,
    need_fill: bool = False,
    co2_ppm_thresh: float = 41000,
    purge_if: Union[str, float] = "below",
    max_repeats: int = 5,
    LiquidCleanPurge_duration: float = 60,  # set before determining actual
    DeltaDilute1_duration: float = 0,
    drainrecirc: bool = True,
) -> list:
    """Inject clean water, recirculate, measure CO2, then drain — repeating via calc if needed.

    Args:
        experiment: Orchestrator-provided experiment context.
        Clean_volume_ul: Clean water volume (uL).
        Syringe_rate_ulsec: Syringe rate (uL/s).
        LiquidCleanWait_s: Wait after liquid fill (s).
        co2measure_duration: CO2 acquisition duration (s).
        co2measure_acqrate: Acquisition rate (s).
        use_co2_check: Repeat via CALC threshold check when True.
        need_fill: Refill the water syringe before the clean injection.
        co2_ppm_thresh: CO2 ppm threshold for the repeat check.
        purge_if: ``"above"``/``"below"`` or a numeric threshold.
        max_repeats: Maximum follow-up repeats (informational).
        LiquidCleanPurge_duration: Drain purge duration forwarded to drain (s).
        DeltaDilute1_duration: Dilution recirc duration forwarded to drain (s).
        drainrecirc: Forwarded ``recirculation`` flag to drain.

    Returns:
        List of planned actions for the orchestrator.
    """
    # drain
    # only 1B 6A-waste opened 1A closed pump off//differ from delta purge

    apm = ActionPlanMaker()
    if need_fill:
        apm.add(NI_server, "liquidvalve", {"liquidvalve": "8", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": 0.25})
        apm.add(
            WATERCLEANSYRINGE_server,
            "withdraw",
            {
                "rate_uL_sec": Syringe_rate_ulsec,
                "volume_uL": Clean_volume_ul,
            },
        )
        apm.add(ORCH_server, "wait", {"waittime": 5.25})
        apm.add(NI_server, "liquidvalve", {"liquidvalve": "8", "on": 0})

    #
    # LIQUID FILL
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 1})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 1}, asc.no_wait)
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 1}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD2", "on": 1})
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD1", "on": 1}, asc.no_wait)
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD0", "on": 0}, asc.no_wait)
    apm.add(
        WATERCLEANSYRINGE_server,
        "infuse",
        {
            "rate_uL_sec": Syringe_rate_ulsec,
            "volume_uL": Clean_volume_ul,
        },
    )
    apm.add(
        WATERCLEANSYRINGE_server,
        "get_present_volume",
        {},
        to_global_params=["_present_volume_ul"],
    )
    apm.add(ORCH_server, "wait", {"waittime": 5.25})

    apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 1})
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD0", "on": 0}, asc.no_wait)
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD1", "on": 0}, asc.no_wait)
    apm.add(NI_server, "multivalve", {"multivalve": "multi_CMD2", "on": 1}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": LiquidCleanWait_s})

    #
    # HEADSPACE REC
    # mfc off, v2, v1ab v7 close
    # mfc off
    apm.add(NI_server, "gasvalve", {"gasvalve": "7B", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": 0.25})

    apm.add(NI_server, "liquidvalve", {"liquidvalve": "2", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1B", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "1A", "on": 0}, asc.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": 0.25})

    ### removed when separate pressure gauge removed from system
    # apm.add(
    #     IO_server,
    #     "acquire_analog_in",
    #     {
    #         "duration": co2measure_duration + 1,
    #         "acquisition_rate": co2measure_acqrate,
    #     },
    # )
    apm.add(
        CO2S_server,
        "acquire_co2",
        {
            "duration": co2measure_duration,
            "acquisition_rate": co2measure_acqrate,
        },
        asc.no_wait,
        technique_name="liquid_purge",
        process_finish=True,
        process_contrib=[
            ProcessContrib.files,
        ],
    )
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1}, asc.no_wait)
    if use_co2_check:
        apm.add(
            CO2S_server,
            "acquire_co2",
            {
                "duration": 1.5,
                "acquisition_rate": 0.5,
            },
        )
    apm.add(NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 0})

    if use_co2_check:
        apm.add(
            CALC_server,
            "check_co2_purge",
            {
                "co2_ppm_thresh": co2_ppm_thresh,
                "purge_if": purge_if,
                "repeat_experiment_name": "CCSI_sub_clean_inject",
                "repeat_experiment_params": {
                    k: v
                    for k, v in vars(apm.pars).items()
                    if not k.startswith("experiment")
                },
            },
            from_global_act_params={"_present_volume_ul": "present_syringe_volume_ul"},
        )

    #
    # LIQUID DRAIN
    apm.add_actions(
        CCSI_sub_drain(
            HSpurge_duration=LiquidCleanPurge_duration,
            recirculation=drainrecirc,
        )
    )

    return apm.planned_actions


@experiment(version=2)
def CCSI_sub_refill_clean(
    Clean_volume_ul: float = 5000,
    Syringe_rate_ulsec: float = 1000,
) -> list:
    """Refill the water syringe by opening valve 8 and withdrawing.

    Args:
        experiment: Orchestrator-provided experiment context.
        Clean_volume_ul: Withdraw volume (uL).
        Syringe_rate_ulsec: Syringe rate (uL/s).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "8", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": 0.25})

    apm.add(
        WATERCLEANSYRINGE_server,
        "withdraw",
        {
            "rate_uL_sec": Syringe_rate_ulsec,
            "volume_uL": Clean_volume_ul,
        },
    )
    apm.add(ORCH_server, "wait", {"waittime": 5.25})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "8", "on": 0})

    return apm.planned_actions


# def CCSI_sub_set_syringe_start(
#     experiment: Experiment,
#     experiment_version: int = 1,
#     syringe: str = "waterclean",
#     Starting_volume_ul: float = 50000,
# ):
#     apm = ActionPlanMaker()
#     if syringe == "waterclean":
#         apm.add(WATERCLEANSYRINGE_server, "set_present_volume", {"volume_uL": Starting_volume_ul})
#     if syringe == "solution1":
#         apm.add(WORKSYRINGE_server, "set_present_volume", {"volume_uL": Starting_volume_ul})
#     # if more syringes can add more names here
#     return apm.planned_actions


@experiment(version=2)
def CCSI_sub_full_fill_syringe(
    syringe: str = "waterclean",
    target_volume_ul: float = 50000,
    Syringe_rate_ulsec: float = 1000,
) -> list:
    """Query the syringe volume and queue a CALC repeat-fill if below a check threshold.

    Args:
        experiment: Orchestrator-provided experiment context.
        syringe: Syringe identifier (``"waterclean"`` or ``"solution1"``).
        target_volume_ul: Desired final volume (uL).
        Syringe_rate_ulsec: Syringe rate (uL/s).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    apm.add(
        WATERCLEANSYRINGE_server,
        "get_present_volume",
        {},
        to_global_params=["_present_volume_ul"],
    )
    apm.add(
        CALC_server,
        "fill_syringe_volume_check",
        {
            "check_volume_ul": 15000,
            "target_volume_ul": target_volume_ul,
            "repeat_experiment_name": "CCSI_sub_fill_syringe",
            "repeat_experiment_params": {
                "syringe": "waterclean",
                "fill_volume_ul": 0,
            },
        },
        from_global_act_params={"_present_volume_ul": "present_volume_ul"},
    )

    return apm.planned_actions


@experiment(version=1)
def CCSI_sub_fill_syringe(
    syringe: str = "waterclean",
    fill_volume_ul: float = 0,
    Syringe_rate_ulsec: float = 1000,
) -> list:
    """Refill a named syringe by withdrawing ``fill_volume_ul`` from its source.

    Args:
        experiment: Orchestrator-provided experiment context.
        syringe: ``"waterclean"`` opens valve 8; ``"solution1"`` uses the work syringe.
        fill_volume_ul: Withdraw volume (uL).
        Syringe_rate_ulsec: Syringe rate (uL/s).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    if syringe == "waterclean":
        apm.add(NI_server, "liquidvalve", {"liquidvalve": "8", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": 0.25})
        apm.add(
            WATERCLEANSYRINGE_server,
            "withdraw",
            {
                "rate_uL_sec": Syringe_rate_ulsec,
                "volume_uL": fill_volume_ul,
            },
        )
        apm.add(ORCH_server, "wait", {"waittime": 5.25})
        apm.add(NI_server, "liquidvalve", {"liquidvalve": "8", "on": 0})

    if syringe == "solution1":
        # need valve for this soln
        apm.add(ORCH_server, "wait", {"waittime": 0.25})
        apm.add(
            WORKSYRINGE_server,
            "withdraw",
            {
                "rate_uL_sec": Syringe_rate_ulsec,
                "volume_uL": fill_volume_ul,
            },
        )
        apm.add(ORCH_server, "wait", {"waittime": 5.25})
        # would need a valve for refill of this syringe, then copy steps from watersyringe

    return apm.planned_actions


@experiment(version=3)
def CCSI_debug_co2purge(
    co2measure_duration: float = 10,
    co2measure_acqrate: float = 0.1,
    co2_ppm_thresh: float = 90000,
    purge_if: Union[str, float] = -0.05,
) -> list:
    """Debug helper that acquires CO2 and conditionally re-queues itself via CALC.

    Args:
        experiment: Orchestrator-provided experiment context.
        co2measure_duration: Acquisition duration (s).
        co2measure_acqrate: Acquisition rate (s).
        co2_ppm_thresh: CO2 threshold for the repeat check.
        purge_if: ``"above"``/``"below"`` or a numeric threshold.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    apm.add(
        CO2S_server,
        "acquire_co2",
        {
            "duration": co2measure_duration,
            "acquisition_rate": co2measure_acqrate,
        },
        technique_name="liquid_purge",
        process_finish=True,
        process_contrib=[
            ProcessContrib.files,
        ],
    )
    apm.add(
        CALC_server,
        "check_co2_purge",
        {
            "co2_ppm_thresh": co2_ppm_thresh,
            "purge_if": purge_if,
            "repeat_experiment_name": "CCSI_debug_co2purge",
            "repeat_experiment_params": {
                k: v
                for k, v in vars(apm.pars).items()
                if not k.startswith("experiment")
            },
        },
    )
    return apm.planned_actions


@experiment(version=1)
def CCSI_leaktest_co2(
    co2measure_duration: float = 600,
    co2measure_acqrate: float = 1,
    recirculate: bool = True,
) -> list:
    """Run a long CO2 acquisition (optionally with recirculation) as a leak test.

    Args:
        experiment: Orchestrator-provided experiment context.
        co2measure_duration: Acquisition duration (s).
        co2measure_acqrate: Acquisition rate (s).
        recirculate: Run the recirculation pump during the test.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()

    apm.add(
        CO2S_server,
        "acquire_co2",
        {
            "duration": co2measure_duration,
            "acquisition_rate": co2measure_acqrate,
        },
    )
    if recirculate:
        apm.add(
            NI_server, "pump", {"pump": "RecirculatingPeriPump1", "on": 1}, asc.no_wait
        )

    return apm.planned_actions
