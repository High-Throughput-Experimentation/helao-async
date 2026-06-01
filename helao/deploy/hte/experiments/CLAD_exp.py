"""Experiment library for the Closed-Loop Accelerated Durability (CLAD) station.

Defines sub-experiments that build action lists for an orchestrator. Each
function takes an ``Experiment`` and returns the list of actions to enqueue.
Action targets are referenced by ``server_key`` strings (e.g. ``MOTOR``,
``NI``, ``PAL``, ``WORKSYRINGE``, ``WATERSYRINGE``, ``CLEANSYRINGE``,
``ORCH``).
"""

__all__ = [
    "CLAD_sub_recirculate_alternating",
    "CLAD_sub_load_sample",
    "CLAD_sub_fill_cell",
    "CLAD_sub_setup_cell",
    "CLAD_sub_reference_setup",
    "CLAD_sub_OCV_bubble_check",
    "CLAD_sub_load_assembly",
    "CLAD_sub_clean_cell",
    "CLAD_sub_refill_syringe",
    "CLAD_sub_standby",
]


from typing import Optional
from socket import gethostname

from helao.helpers.premodels import Experiment, ActionPlanMaker
from helao.core.models.action_start_condition import ActionStartCondition
from helao.core.models.sample import SolidSample, LiquidSample, GasSample
from helao.core.models.machine import MachineModel
from helao.core.models.process_contrib import ProcessContrib

from helao.deploy.hte.drivers.motion.galil_motion_driver import (
    MoveModes,
    TransformationModes,
)

from helao.deploy.hte.experiments.ADSS_xtraclean_exp import (
    ADSS_sub_drain_cell,
    ADSS_sub_OCV,
)

from helao.core.models.run_use import RunUse
from helao.helpers.lib_decorators import experiment


EXPERIMENTS = __all__

# cannot save data without exp
debug_save_act = True
debug_save_data = True


### CONSOLIDATED EXPERIMENTS FOR SIMPLIFIED SEQUENCES


@experiment(version=1)
def CLAD_sub_recirculate_alternating(
    forward_duration_s: float = 30.0,
    reverse_duration_s: float = 15.0,
    final_duration_s: float = 5.0,
) -> list:
    """Recirculate by alternating peristaltic-pump direction forward, reverse, then forward again.

    Args:
        experiment: Orchestrator-provided experiment context.
        forward_duration_s: Initial forward-recirc time (s).
        reverse_duration_s: Reverse-recirc time (s).
        final_duration_s: Final forward-recirc time (s).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()

    # RECIRCULATE FORWARD
    apm.add("NI", "gasvalve", {"gasvalve": "inlet", "on": 1})
    apm.add("NI", "pump", {"pump": "direction", "on": 0})
    apm.add("NI", "pump", {"pump": "peripump", "on": 1})
    apm.add("ORCH", "wait", {"waittime": forward_duration_s})

    # RECIRCULATE REVERSE
    apm.add("NI", "gasvalve", {"gasvalve": "inlet", "on": 1})
    apm.add("NI", "pump", {"pump": "direction", "on": 1})
    apm.add("NI", "pump", {"pump": "peripump", "on": 1})
    apm.add("ORCH", "wait", {"waittime": reverse_duration_s})

    # RECIRCULATE FORWARD FINAL
    apm.add("NI", "gasvalve", {"gasvalve": "inlet", "on": 1})
    apm.add("NI", "pump", {"pump": "direction", "on": 0})
    apm.add("NI", "pump", {"pump": "peripump", "on": 1})
    apm.add("ORCH", "wait", {"waittime": final_duration_s})

    return apm.planned_actions


@experiment(version=1)
def CLAD_sub_load_sample(
    load_position: str = "cell1_we",
    clear_position: bool = True,
    solid_plate_id: Optional[int] = None,
    solid_sample_no: Optional[int] = None,
    liquid_sample_no: Optional[int] = None,
    liquid_volume_ul: Optional[float] = None,
    gas_sample_no: Optional[int] = None,
    gas_volume_ml: Optional[float] = None,
    bubbler_gas: Optional[str] = None,
) -> list:
    """Register optional solid/liquid/gas samples into a PAL custom position.

    Any sample type whose ``*_sample_no`` (and volume, where applicable) is
    not None is loaded; ``clear_position`` first unloads existing samples.

    Args:
        experiment: Orchestrator-provided experiment context.
        load_position: PAL custom position name.
        clear_position: Unload existing samples first.
        solid_plate_id: Plate identifier of the legacy solid sample.
        solid_sample_no: Sample index on the plate.
        liquid_sample_no: Liquid sample number on this host.
        liquid_volume_ul: Liquid volume to add (uL).
        gas_sample_no: Gas sample number.
        gas_volume_ml: Gas volume to add (mL).
        bubbler_gas: Informational gas label (unused by the actions).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()

    if clear_position:
        apm.add(
            "PAL",
            "archive_custom_unloadall",
            {},
            start_condition=ActionStartCondition.wait_for_orch,
            to_global_params=[
                "_unloaded_solid",
                "_unloaded_liquid",
                "_unloaded_liquid_vol",
            ],
        )

    if solid_sample_no is not None and solid_plate_id is not None:
        apm.add(
            "PAL",
            "archive_custom_load",
            {
                "custom": load_position,
                "load_sample_in": SolidSample(
                    sample_no=solid_sample_no,
                    plate_id=solid_plate_id,
                    machine_name="legacy",
                ).model_dump(),
            },
        )
    if liquid_sample_no is not None and liquid_volume_ul is not None:
        apm.add(
            "PAL",
            "archive_custom_add_liquid",
            {
                "custom": load_position,
                "source_liquid_in": LiquidSample(
                    sample_no=liquid_sample_no, machine_name=gethostname()
                ).model_dump(),
                "volume_ml": liquid_volume_ul / 1000,
                "combine_liquids": False,
                "dilute_liquids": False,
            },
            start_condition=ActionStartCondition.wait_for_previous,
        )
    if liquid_sample_no is not None and gas_volume_ml is not None:
        apm.add(
            "PAL",
            "archive_custom_add_gas",
            {
                "custom": load_position,
                "source_gas_in": GasSample(
                    sample_no=gas_sample_no, machine_name=gethostname()
                ).model_dump(),
                "volume_ml": gas_volume_ml,
            },
            technique_name="bubbling_gas",
            process_finish=True,
            process_contrib=[
                ProcessContrib.action_params,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        )

    return apm.planned_actions


@experiment(version=1)
def CLAD_sub_fill_cell(
    fill_volume_ul: float = 3000,
    fill_rate_ul_s: float = 300,
    load_sample: bool = False,
) -> list:
    """Infuse the work syringe into the cell, optionally tagging the current cell sample.

    When ``load_sample`` is True the current sample at ``cell1_we`` is
    queried into ``_fast_samples_in`` first, and the syringe infuse forwards
    that into the cell-fill technique.

    Args:
        experiment: Orchestrator-provided experiment context.
        fill_volume_ul: Fill volume (uL).
        fill_rate_ul_s: Syringe rate (uL/s).
        load_sample: Query the cell sample before infusing.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()

    if load_sample:
        apm.add(
            "PAL",
            "archive_custom_query_sample",
            {
                "custom": "cell1_we",
            },
            to_global_params={"_fast_samples_in": "_fast_samples_in"},
            # save new liquid_sample_no of eche cell to globals,
            start_condition=ActionStartCondition.no_wait,
        )

    apm.add(
        "NI",
        "gasvalve",
        {"gasvalve": "inlet", "on": 0},
        start_condition=ActionStartCondition.wait_for_orch,
    )
    apm.add(
        "WORKSYRINGE",
        "infuse",
        {
            "rate_uL_sec": fill_rate_ul_s,
            "volume_uL": fill_volume_ul,
        },
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        technique_name="cell_fill",
        process_finish=True,
        process_contrib=(
            [
                ProcessContrib.action_params,
                ProcessContrib.samples_in,
            ]
        ),
        start_condition=ActionStartCondition.wait_for_orch,
    )
    return apm.planned_actions


# 1. CLEAN CELL
@experiment(version=1)
def CLAD_sub_setup_cell(
    rinse_recirc_duration_s: float = 30.0,
    rinse_volume_ul: float = 3000.0,
    fill_rate_ul_s: float = 300.0,
    drain_wait_duration_s: float = 30.0,
) -> list:
    """Move to the rinse position, fill+forward-recirc, drain, then refill the work syringe.

    Args:
        experiment: Orchestrator-provided experiment context.
        rinse_recirc_duration_s: Forward recirculation duration (s).
        rinse_volume_ul: Cell rinse volume (uL).
        fill_rate_ul_s: Syringe rate (uL/s).
        drain_wait_duration_s: Drain wait passed to ``ADSS_sub_drain_cell`` (s).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()

    # MOVE TO CELL RINSE POSITION
    apm.add("MOTOR", "z_move", {"z_position": "load"})
    apm.add(
        "MOTOR",
        "solid_get_builtin_specref",
        {"ref_name": "builtin_ref_motorxy"},
        to_global_params={"_refxy": "_refxy"},
    )
    apm.add(
        "MOTOR",
        "move",
        {
            "axis": ["x", "y"],
            "mode": MoveModes.absolute,
            "transformation": TransformationModes.platexy,
        },
        from_global_act_params={"_refxy": "d_mm"},
    )
    apm.add("MOTOR", "z_move", {"z_position": "seal"})

    # FILL CELL WITHOUT SAMPLE LOAD
    apm.add_actions(
        CLAD_sub_fill_cell(
            fill_volume_ul=rinse_volume_ul,
            fill_rate_ul_s=fill_rate_ul_s,
            load_sample=False,
        )
    )

    # RECIRCULATE RINSE SOLUTION FORWARD DIRECTION
    apm.add("NI", "gasvalve", {"gasvalve": "inlet", "on": 1})
    apm.add("NI", "pump", {"pump": "direction", "on": 0})
    apm.add("NI", "pump", {"pump": "peripump", "on": 1})
    apm.add("ORCH", "wait", {"waittime": rinse_recirc_duration_s})

    # DRAIN CELL
    apm.add_actions(
        ADSS_sub_drain_cell(
            DrainWait_s=drain_wait_duration_s,
            ReturnLineReverseWait_s=5.0,
        )
    )

    # REFILL SYRINGE
    apm.add("NI", "liquidvalve", {"liquidvalve": "work_refill", "on": 1})
    apm.add("ORCH", "wait", {"waittime": 0.25})
    apm.add(
        "WORKSYRINGE",
        "withdraw",
        {
            "rate_uL_sec": fill_rate_ul_s,
            "volume_uL": rinse_volume_ul,
        },
    )
    apm.add("ORCH", "wait", {"waittime": 10})
    apm.add("NI", "liquidvalve", {"liquidvalve": "work_refill", "on": 0})

    return apm.planned_actions


# 2. REFERENCE MEASUREMENT
@experiment(version=1)
def CLAD_sub_reference_setup(
    reference_position_name: str = "builtin_ref_motorxy_2",
    reference_sample_label: str = "reference-fto__solid__11_1",
    load_position: str = "cell1_we",
    liquid_sample_no: int = 1053,
    fill_volume_ul: float = 7000.0,
    fill_rate_ul_s: float = 300.0,
    fill_recirc_fwd_duration_s: float = 30.0,
    fill_recirc_rev_duration_s: float = 15.0,
    electrolyte_ph: float = 1.0,
    reference_offset_V: float = 0.0,
    ocv_duration_s: float = 30.0,
    ocv_sample_rate_s: float = 0.1,
    gamry_i_range: str = "auto",
) -> list:
    """Move to a reference position, load a reference solid+liquid, fill, flow O2, recirculate, refill.

    Args:
        experiment: Orchestrator-provided experiment context.
        reference_position_name: Built-in specref position name.
        reference_sample_label: Informational solid label.
        load_position: PAL custom position for the reference assembly.
        liquid_sample_no: Liquid sample number.
        fill_volume_ul: Fill volume (uL).
        fill_rate_ul_s: Syringe rate (uL/s).
        fill_recirc_fwd_duration_s: Forward recirculation duration (s).
        fill_recirc_rev_duration_s: Reverse recirculation duration (s).
        electrolyte_ph: Electrolyte pH (informational here).
        reference_offset_V: Reference offset (V) (informational here).
        ocv_duration_s: OCV duration (s) (informational here).
        ocv_sample_rate_s: OCV sample rate (s) (informational here).
        gamry_i_range: Gamry current-range setting (informational here).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()

    # MOVE TO REFERENCE POSITION
    apm.add("MOTOR", "z_move", {"z_position": "load"})
    apm.add(
        "MOTOR",
        "solid_get_builtin_specref",
        {"ref_position_name": reference_position_name},
        to_global_params={"_refxy": "_refxy"},
    )
    apm.add(
        "MOTOR",
        "move",
        {
            "axis": ["x", "y"],
            "mode": MoveModes.absolute,
            "transformation": TransformationModes.motorxy,
        },
        from_global_act_params={"_refxy": "d_mm"},
    )
    apm.add("MOTOR", "z_move", {"z_position": "seal"})

    # LOAD REFERENCE SAMPLE
    apm.add(
        "PAL",
        "archive_custom_unloadall",
        {},
        start_condition=ActionStartCondition.wait_for_orch,
        to_global_params={
            "_unloaded_liquid": "_unloaded_liquid",
            "_unloaded_liquid_vol": "_unloaded_liquid_vol",
        },
    )
    # need to use custom solid label here, not supported by ADSS_sub_load
    apm.add(
        "PAL",
        "archive_custom_load",
        {
            "custom": load_position,
            "load_sample_in": SolidSample(
                sample_no=1, plate_id=11, machine_name="reference-fto"
            ).model_dump(),
        },
        start_condition=ActionStartCondition.wait_for_previous,
    )
    apm.add(
        "PAL",
        "archive_custom_add_liquid",
        {
            "custom": load_position,
            "source_liquid_in": LiquidSample(
                sample_no=liquid_sample_no, machine_name=gethostname()
            ).model_dump(),
            "volume_ml": fill_volume_ul / 1000,
            "combine_liquids": False,
            "dilute_liquids": False,
        },
        start_condition=ActionStartCondition.wait_for_previous,
    )

    # FILL CELL WITH LIQUID
    apm.add_actions(
        CLAD_sub_fill_cell(
            fill_volume_ul=fill_volume_ul,
            fill_rate_ul_s=fill_rate_ul_s,
            load_sample=True,
        )
    )

    # FLOW O2
    apm.add("NI", "gasvalve", {"gasvalve": "O2N2toggle", "on": False})

    # RECIRCULATE
    apm.add_actions(
        CLAD_sub_recirculate_alternating(
            forward_duration_s=fill_recirc_fwd_duration_s,
            reverse_duration_s=fill_recirc_rev_duration_s,
            final_duration_s=5.0,
        )
    )

    # REFILL SYRINGE
    apm.add_actions(
        CLAD_sub_refill_syringe(
            syringe="work",
            fill_volume_ul=fill_volume_ul,
            Syringe_rate_ulsec=300.0,
        )
    )

    return apm.planned_actions


@experiment(version=1)
def CLAD_sub_OCV_bubble_check(
    ocv_duration_s: float = 30.0,
    ocv_sample_rate_s: float = 0.1,
    electrolyte_ph: float = 1.0,
    reference_offset_V: float = 0.0,
    gamry_i_range: str = "auto",
    bubble_check: bool = True,
    aliquot_post_ocv: bool = True,
    run_use: RunUse = RunUse.data,
) -> list:
    """Optionally run a short OCV with bubble detection then run the main OCV (with aliquot).

    Args:
        experiment: Orchestrator-provided experiment context.
        ocv_duration_s: Main OCV duration (s).
        ocv_sample_rate_s: OCV sample rate (s).
        electrolyte_ph: Solution pH.
        reference_offset_V: Reference offset (V).
        gamry_i_range: Gamry current-range setting.
        bubble_check: Prepend a short bubble-check OCV when True.
        aliquot_post_ocv: Take a post-OCV PAL aliquot when True.
        run_use: ``RunUse`` tag forwarded to the main OCV.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()

    if bubble_check:
        # RUN BUBBLE-CHECK OCV
        apm.add_actions(
            ADSS_sub_OCV(
                check_bubble=True,
                Tval__s=10,
                samplerate_sec=ocv_sample_rate_s,
                gamry_i_range=gamry_i_range,
                ph=electrolyte_ph,
                ref_type="leakless",
                ref_offset__V=reference_offset_V,
                aliquot_insitu=False,
                bubbler_gas="O2",
                RSD_threshold=0.02,
                simple_threshold=0.3,
                signal_change_threshold=0.01,
                amplitude_threshold=0.05,
                bubble_pump_reverse_time_s=15.0,
                bubble_pump_forward_time_s=10.0,
                run_use=RunUse.ref,
            )
        )

    # OCV WITH ALIQUOT
    apm.add_actions(
        ADSS_sub_OCV(
            check_bubble=False,
            Tval__s=ocv_duration_s,
            samplerate_sec=ocv_sample_rate_s,
            gamry_i_range=gamry_i_range,
            ph=electrolyte_ph,
            ref_type="leakless",
            ref_offset__V=reference_offset_V,
            aliquot_insitu=False,
            aliquot_post=aliquot_post_ocv,
            bubbler_gas="O2",
            run_use=run_use,
        )
    )

    return apm.planned_actions


# 3. SETUP SAMPLE
@experiment(version=1)
def CLAD_sub_load_assembly(
    load_position: str = "cell1_we",
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
    liquid_sample_no: int = 1053,
    fill_volume_ul: float = 7000.0,
    fill_rate_ul_s: float = 300.0,
    gas_sample_no: int = 2,
    gas_volume_ml: float = 1.0,
    bubbler_gas: str = "O2",
) -> list:
    """Move to the plate sample, seal, register solid+liquid+gas, then infuse the cell.

    Args:
        experiment: Orchestrator-provided experiment context.
        load_position: PAL custom position name.
        solid_plate_id: Plate identifier of the legacy solid sample.
        solid_sample_no: Sample index on the plate.
        liquid_sample_no: Liquid sample number.
        fill_volume_ul: Cell fill volume (uL).
        fill_rate_ul_s: Syringe rate (uL/s).
        gas_sample_no: Gas sample number.
        gas_volume_ml: Gas volume to add (mL).
        bubbler_gas: Informational bubbled-gas label.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()

    apm.add(
        "NI",
        "pump",
        {
            "pump": "peripump",
            "on": 0,
        },
        start_condition=ActionStartCondition.wait_for_all,
    )

    # set pump flow forward
    apm.add(
        "NI",
        "pump",
        {
            "pump": "direction",
            "on": 0,
        },
        start_condition=ActionStartCondition.wait_for_all,
    )

    # move z to home
    apm.add("MOTOR", "z_move", {"z_position": "load"})

    # move to position
    apm.add(
        "MOTOR",
        "solid_get_samples_xy",
        {
            "plate_id": solid_plate_id,
            "sample_no": solid_sample_no,
        },
        to_global_params={"_platexy": "_platexy"},
        start_condition=ActionStartCondition.wait_for_all,
    )

    apm.add(
        "MOTOR",
        "move",
        {
            "axis": ["x", "y"],
            "mode": MoveModes.absolute,
            "transformation": TransformationModes.platexy,
        },
        from_global_act_params={"_platexy": "d_mm"},
        save_act=debug_save_act,
        save_data=debug_save_data,
        start_condition=ActionStartCondition.wait_for_all,
    )

    # seal cell
    apm.add("MOTOR", "z_move", {"z_position": "seal"})

    apm.add_actions(
        CLAD_sub_load_sample(
            load_position=load_position,
            clear_position=False,
            solid_plate_id=solid_plate_id,
            solid_sample_no=solid_sample_no,
            liquid_sample_no=liquid_sample_no,
            liquid_volume_ul=fill_volume_ul,
            gas_sample_no=gas_sample_no,
            gas_volume_ml=gas_volume_ml,
            bubbler_gas=bubbler_gas,
        )
    )

    apm.add_actions(
        CLAD_sub_fill_cell(
            fill_volume_ul=fill_volume_ul,
            fill_rate_ul_s=fill_rate_ul_s,
            load_sample=False,  # load whatever sample is in _fast_samples_in
        )
    )

    return apm.planned_actions


@experiment(version=1)
def CLAD_sub_clean_cell(
    nitric_volume_ul: float = 3000,
    water_volume_ul: float = 10000,
    Syringe_rate_ulsec: float = 300,
    PurgeWait_s: float = 3,
    ReturnLineWait_s: float = 60,
    DrainWait_s: float = 80,
    ReturnLineReverseWait_s: float = 15,
    lift: bool = False,
    #    ResidualWait_s: float = 15,
) -> list:
    """Sequentially flush the cell with nitric acid then water, draining between each.

    Args:
        experiment: Orchestrator-provided experiment context.
        nitric_volume_ul: Nitric flush volume (uL).
        water_volume_ul: Water rinse volume (uL).
        Syringe_rate_ulsec: Syringe rate (uL/s).
        PurgeWait_s: Reserved gas purge wait (s); not currently used.
        ReturnLineWait_s: Pump-forward time to clear the return line (s).
        DrainWait_s: Drain duration passed to ``ADSS_sub_drain_cell`` (s).
        ReturnLineReverseWait_s: Reverse pump time during drain (s).
        lift: Lift Z to load after cleaning when True.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()

    apm.add("NI", "gasvalve", {"gasvalve": "inlet", "on": 0})
    apm.add(
        "CLEANSYRINGE",
        "infuse",
        {
            "rate_uL_sec": Syringe_rate_ulsec,
            "volume_uL": nitric_volume_ul,
        },
    )
    apm.add("ORCH", "wait", {"waittime": 10})

    apm.add("NI", "pump", {"pump": "direction", "on": 0})
    apm.add("NI", "pump", {"pump": "peripump", "on": 1})
    apm.add("ORCH", "wait", {"waittime": ReturnLineWait_s})
    apm.add("NI", "pump", {"pump": "peripump", "on": 0})

    apm.add_actions(
        ADSS_sub_drain_cell(
            DrainWait_s=DrainWait_s,
            ReturnLineReverseWait_s=ReturnLineReverseWait_s,
            # ResidualWait_s=ResidualWait_s,
        )
    )

    apm.add(
        "WATERSYRINGE",
        "infuse",
        {
            "rate_uL_sec": Syringe_rate_ulsec,
            "volume_uL": water_volume_ul,
        },
    )

    apm.add("NI", "pump", {"pump": "direction", "on": 0})
    apm.add("NI", "pump", {"pump": "peripump", "on": 1})
    apm.add("ORCH", "wait", {"waittime": ReturnLineWait_s})
    apm.add("NI", "pump", {"pump": "peripump", "on": 0})

    apm.add_actions(
        ADSS_sub_drain_cell(
            DrainWait_s=DrainWait_s,
            ReturnLineReverseWait_s=ReturnLineReverseWait_s,
            # ResidualWait_s=ResidualWait_s,
        )
    )

    if lift:
        apm.add("MOTOR", "z_move", {"z_position": "load"})

    return apm.planned_actions


@experiment(version=1)
def CLAD_sub_refill_syringe(
    syringe: str = "clean",
    fill_volume_ul: float = 0,
    Syringe_rate_ulsec: float = 300,
) -> list:
    """Refill one of the named syringes (clean, water, work) via its refill liquid valve.

    Args:
        experiment: Orchestrator-provided experiment context.
        syringe: ``"clean"``, ``"water"``, or ``"work"``.
        fill_volume_ul: Withdraw volume (uL).
        Syringe_rate_ulsec: Syringe rate (uL/s).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()

    syringes = {"clean": "CLEANSYRINGE", "water": "WATERSYRINGE", "work": "WORKSYRINGE"}

    apm.add("NI", "liquidvalve", {"liquidvalve": f"{syringe}_refill", "on": 1})
    apm.add("ORCH", "wait", {"waittime": 0.25})
    apm.add(
        syringes[syringe],
        "withdraw",
        {
            "rate_uL_sec": Syringe_rate_ulsec,
            "volume_uL": fill_volume_ul,
        },
    )
    apm.add("ORCH", "wait", {"waittime": 10})
    apm.add("NI", "liquidvalve", {"liquidvalve": f"{syringe}_refill", "on": 0})

    return apm.planned_actions


@experiment(version=1)
def CLAD_sub_standby(
) -> list:
    """Drive the station to a safe standby: peristaltic pump off, inlet gas valve closed.

    Args:
        experiment: Orchestrator-provided experiment context.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    apm.add("NI", "pump", {"pump": "peripump", "on": 0})
    apm.add("NI", "gasvalve", {"gasvalve": "inlet", "on": 0})
    return apm.planned_actions
