"""Experiment library for the ADSS (Anodic Dissolution Sampling System) station.

Defines sub-experiments that build action lists for an orchestrator. Each
function takes an ``Experiment`` instance plus experiment-specific keyword
arguments and returns the list of actions to enqueue. Action targets are
referenced by ``server_key`` strings (e.g. ``PSTAT``, ``MOTOR``, ``NI``,
``PAL``, ``WORKSYRINGE``, ``CLEANSYRINGE``, ``ORCH``) that must be present
in the orchestration config.
"""

__all__ = [
    #    "ADSS_sub_sample_start",
    "ADSS_sub_drain_cell",
    "ADSS_sub_move_to_clean_cell",
    "ADSS_sub_clean_cell",
    "ADSS_sub_z_move",
    "ADSS_sub_refill_syringe",
    "ADSS_sub_move_to_sample",
    "ADSS_sub_CA",  # latest
    "ADSS_sub_CV",  # latest
    "ADSS_sub_OCV",  # at beginning of all sequences
    "ADSS_sub_recirculate",
    "ADSS_sub_unloadall_customs",
    "ADSS_sub_unload_liquid",
    "ADSS_sub_unload_solid",
    "ADSS_sub_load",
    "ADSS_sub_load_solid",
    "ADSS_sub_load_liquid",
    "ADSS_sub_add_liquid",
    "ADSS_sub_load_liquid_only",
    "ADSS_sub_PAL_load_gas",
    "ADSS_sub_unload_gas_only",
    #    "ADSS_sub_fillfixed",
    #    "ADSS_sub_fill",
    "ADSS_sub_tray_unload",
    #    "ADSS_sub_rel_move",
    #    "ADSS_sub_heat",
    #    "ADSS_sub_stopheat",
    "ADSS_sub_shutdown",
    #    "ADSS_sub_drain",
    "ADSS_sub_clean_PALtool",
    "ADSS_sub_PAL_deep_clean",
    "ADSS_sub_PAL_tray_to_tray",
    "ADSS_sub_PAL_export_icpms",
    "ADSS_sub_cellfill_prefilled",
    "ADSS_sub_cellfill_flush",
    "ADSS_sub_keep_electrolyte",
    #    "ADSS_sub_empty_cell",
    "ADSS_sub_sample_aliquot",
    "ADSS_sub_insitu_actions",
    #    "ADSS_sub_abs_move",
    "ADSS_sub_cell_illumination",
    "ADSS_sub_CA_photo",
    "ADSS_sub_OCV_photo",
    "ADSS_sub_interrupt",
    "ADSS_sub_gasvalve_toggle",
    "ADSS_sub_gasvalve_N2flow",
    "ADSS_sub_transfer_liquid_in",
    "ADSS_sub_tray_icpms_export",
    "ADSS_sub_move_to_ref_measurement",
    "ADSS_sub_remove_bubble",
    "ADSS_sub_cellfill_prefilled_nosampleload",
]


from typing import Optional, List
from socket import gethostname

from helao.helpers.premodels import Experiment, ActionPlanMaker
from helao.core.models.action_start_condition import ActionStartCondition
from helao.core.models.sample import SolidSample, LiquidSample, GasSample
from helao.core.models.machine import MachineModel
from helao.core.models.process_contrib import ProcessContrib
from helao.helpers.constants import REF_TABLE

from helao.deploy.hte.drivers.motion.galil_motion_driver import (
    MoveModes,
    TransformationModes,
)
from helao.deploy.hte.drivers.robot.pal_driver import Spacingmethod, PALtools

from helao.core.models.run_use import RunUse
from helao.helpers.lib_decorators import experiment


EXPERIMENTS = __all__

ORCH_HOST = gethostname()
PSTAT_server = MachineModel(server_name="PSTAT", machine_name=ORCH_HOST).as_dict()
MOTOR_server = MachineModel(server_name="MOTOR", machine_name=ORCH_HOST).as_dict()
NI_server = MachineModel(server_name="NI", machine_name=ORCH_HOST).as_dict()
ORCH_server = MachineModel(server_name="ORCH", machine_name=ORCH_HOST).as_dict()
PAL_server = MachineModel(server_name="PAL", machine_name=ORCH_HOST).as_dict()
WORKSYRINGE_server = MachineModel(
    server_name="WORKSYRINGE", machine_name=ORCH_HOST
).as_dict()
CLEANSYRINGE_server = MachineModel(
    server_name="CLEANSYRINGE", machine_name=ORCH_HOST
).as_dict()


# cannot save data without exp
debug_save_act = True
debug_save_data = True


@experiment(version=1)
def ADSS_sub_unloadall_customs() -> list:
    """Unload every custom-position sample currently tracked by PAL.

    Args:
        experiment: Orchestrator-provided experiment context.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    apm.add(
        PAL_server,
        "archive_custom_unloadall",
        {
            #                "destroy_liquid": False,
        },
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
    )

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=2)
def ADSS_sub_unload_liquid(
) -> list:
    """Unload the liquid sample at ``cell1_we`` while keeping the solid in place.

    Args:
        experiment: Orchestrator-provided experiment context.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()
    apm.add(
        PAL_server,
        "archive_custom_unload",
        {
            "keep_solid": True,
            "custom": "cell1_we",
        },
        start_condition=ActionStartCondition.wait_for_orch,
        # to_global_params=["_unloaded_solid"],
    )
    # apm.add(
    #     PAL_server,
    #     "archive_custom_load",
    #     {"custom": "cell1_we"},
    #     from_global_act_params={"_unloaded_solid": "load_sample_in"},
    # )
    return apm.planned_actions


@experiment(version=2)
def ADSS_sub_unload_solid(
) -> list:
    """Unload the solid sample at ``cell1_we`` while keeping the liquid in place.

    Args:
        experiment: Orchestrator-provided experiment context.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()
    # apm.add(
    #     PAL_server,
    #     "archive_custom_unloadall",
    #     {},
    #     to_global_params=["_unloaded_liquid"],
    # )
    apm.add(
        PAL_server,
        "archive_custom_unload",
        {
            "custom": "cell1_we",
            "keep_liquid": True,
        },
        start_condition=ActionStartCondition.wait_for_orch,
        # from_global_act_params={"_unloaded_liquid": "load_sample_in"},
    )
    return apm.planned_actions


@experiment(version=1)
def ADSS_sub_load_solid(
    solid_custom_position: str = "cell1_we",
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
) -> list:
    """Unload all customs and load the specified solid plate sample to ``cell1_we``.

    Re-loads any previously unloaded liquid back into the same cell position.

    Args:
        experiment: Orchestrator-provided experiment context.
        solid_custom_position: PAL custom position the solid is loaded into.
        solid_plate_id: Plate identifier of the legacy solid sample.
        solid_sample_no: Sample index on the plate.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(
        PAL_server,
        "archive_custom_unloadall",
        {},
        to_global_params=["_unloaded_liquid"],
    )
    apm.add(
        PAL_server,
        "archive_custom_load",
        {
            "custom": solid_custom_position,
            "load_sample_in": SolidSample(
                **{
                    "sample_no": solid_sample_no,
                    "plate_id": solid_plate_id,
                    "machine_name": "legacy",
                }
            ).model_dump(),
        },
        start_condition=ActionStartCondition.wait_for_orch,  #
    )
    apm.add(
        PAL_server,
        "archive_custom_load",
        {
            "custom": "cell1_we",
        },
        from_global_act_params={"_unloaded_liquid": "load_sample_in"},
        start_condition=ActionStartCondition.wait_for_previous,
    )
    return apm.planned_actions  # returns complete action list to orch


@experiment(version=3)
def ADSS_sub_load_liquid(
    liquid_custom_position: str = "cell1_we",
    liquid_sample_no: int = 1,
    volume_ul_cell_liquid: int = 1000,
    combine_liquids: bool = False,
    dilute_liquids: bool = False,
) -> list:
    """Add a liquid sample to a custom cell position.

    Args:
        experiment: Orchestrator-provided experiment context.
        liquid_custom_position: Target PAL custom position.
        liquid_sample_no: Liquid sample number registered to this host.
        volume_ul_cell_liquid: Volume to add in microliters.
        combine_liquids: Forwarded to PAL to combine with the existing liquid.
        dilute_liquids: Forwarded to PAL to dilute the existing liquid.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(
        PAL_server,
        "archive_custom_add_liquid",
        {
            "custom": liquid_custom_position,
            "source_liquid_in": LiquidSample(
                **{
                    "sample_no": liquid_sample_no,
                    "machine_name": gethostname(),
                }
            ).model_dump(),
            "volume_ml": volume_ul_cell_liquid / 1000,
            "combine_liquids": combine_liquids,
            "dilute_liquids": dilute_liquids,
        },
        start_condition=ActionStartCondition.wait_for_orch,  #
    )
    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def ADSS_sub_load_liquid_only(
    liquid_custom_position: str = "cell1_we",
    liquid_sample_no: int = 1,
    liquid_sample_volume_ul: float = 4000,
    combine_liquids: bool = False,
    dilute_liquids: bool = False,
) -> list:
    """Add a liquid sample to a custom cell position and finish a liquid-addition process.

    Args:
        experiment: Orchestrator-provided experiment context.
        liquid_custom_position: Target PAL custom position.
        liquid_sample_no: Liquid sample number registered to this host.
        liquid_sample_volume_ul: Volume to add in microliters.
        combine_liquids: Forwarded to PAL to combine with the existing liquid.
        dilute_liquids: Forwarded to PAL (ignored — call passes ``False``).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()

    # add liquid to cell position
    apm.add(
        PAL_server,
        "archive_custom_add_liquid",
        {
            "custom": liquid_custom_position,
            "source_liquid_in": LiquidSample(
                **{
                    "sample_no": liquid_sample_no,
                    "machine_name": gethostname(),
                }
            ).model_dump(),
            "volume_ml": liquid_sample_volume_ul / 1000,
            "combine_liquids": combine_liquids,
            "dilute_liquids": False,
        },
        technique_name="liquid_addition",
        process_finish=True,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
        start_condition=ActionStartCondition.wait_for_orch,
    )

    return apm.planned_actions


######
@experiment(version=1)
def ADSS_sub_PAL_load_gas(
    custom_position: str = "cell1_we",
    bubbled_gas: str = "N2",
    reservoir_gas_sample_no: int = 1,
    volume_ul_cell_gas: int = 1,
) -> list:
    """Add gas volume to a cell position and finish a bubbling-gas process.

    Args:
        experiment: Orchestrator-provided experiment context.
        custom_position: Target PAL custom position.
        bubbled_gas: Label for the bubbled gas.
        reservoir_gas_sample_no: Gas sample number in the source reservoir.
        volume_ul_cell_gas: Volume to add in microliters.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()
    apm.add(
        PAL_server,
        "archive_custom_add_gas",
        {
            "custom": custom_position,
            "source_gas_in": GasSample(
                **{
                    "sample_no": reservoir_gas_sample_no,
                    "machine_name": gethostname(),
                }
            ).model_dump(),
            "volume_ml": volume_ul_cell_gas / 1000,
        },
        technique_name="bubbling_gas",
        process_finish=True,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def ADSS_sub_unload_gas_only(
) -> list:
    """Unload only the gas sample at ``cell1_we`` while keeping liquid and solid.

    Args:
        experiment: Orchestrator-provided experiment context.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()
    # apm.add(
    #     PAL_server,
    #     "archive_custom_unloadall",
    #     {},
    #     to_global_params=["_unloaded_liquid", "unloaded_solid"],
    # )
    apm.add(
        PAL_server,
        "archive_custom_unload",
        {
            "custom": "cell1_we",
            "keep_liquid": True,
            "keep_solid": True,
        },
        start_condition=ActionStartCondition.wait_for_orch,
        # from_global_act_params={"_unloaded_liquid": "load_sample_in"},
    )
    return apm.planned_actions


#######


@experiment(version=3)
def ADSS_sub_load(
    solid_custom_position: str = "cell1_we",
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
    previous_liquid: bool = False,
    liquid_custom_position: str = "cell1_we",
    liquid_sample_no: int = 1,
    liquid_sample_volume_ul: float = 4000,
) -> list:
    """Clear customs, load a solid plate sample, then add liquid to the cell.

    When ``previous_liquid`` is True the previously unloaded liquid is reused
    instead of a freshly resolved liquid sample.

    Args:
        experiment: Orchestrator-provided experiment context.
        solid_custom_position: PAL custom position for the solid.
        solid_plate_id: Plate identifier of the legacy solid sample.
        solid_sample_no: Sample index on the plate.
        previous_liquid: Reuse the prior unloaded liquid if True.
        liquid_custom_position: Target PAL custom position for added liquid.
        liquid_sample_no: Liquid sample number on this host.
        liquid_sample_volume_ul: Liquid volume to add in microliters.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()

    # clear cell position and track unloaded liquid
    apm.add(
        PAL_server,
        "archive_custom_unloadall",
        {},
        start_condition=ActionStartCondition.wait_for_orch,
        to_global_params=["_unloaded_liquid", "_unloaded_liquid_vol"],
    )
    # load solid into cell position
    apm.add(
        PAL_server,
        "archive_custom_load",
        {
            "custom": solid_custom_position,
            "load_sample_in": SolidSample(
                **{
                    "sample_no": solid_sample_no,
                    "plate_id": solid_plate_id,
                    "machine_name": "legacy",
                }
            ).model_dump(),
        },
        start_condition=ActionStartCondition.wait_for_previous,
    )
    # add liquid to cell position
    if previous_liquid:
        apm.add(
            PAL_server,
            "archive_custom_add_liquid",
            {
                "custom": liquid_custom_position,
                "combine_liquids": False,
                "dilute_liquids": False,
            },
            from_global_act_params={
                "_unloaded_liquid": "source_liquid_in",
                "_unloaded_liquid_vol": "volume_ml",
            },
            start_condition=ActionStartCondition.wait_for_previous,
        )
    else:
        apm.add(
            PAL_server,
            "archive_custom_add_liquid",
            {
                "custom": liquid_custom_position,
                "source_liquid_in": LiquidSample(
                    **{
                        "sample_no": liquid_sample_no,
                        "machine_name": gethostname(),
                    }
                ).model_dump(),
                "volume_ml": liquid_sample_volume_ul / 1000,
                "combine_liquids": False,
                "dilute_liquids": False,
            },
            start_condition=ActionStartCondition.wait_for_previous,
        )

    return apm.planned_actions


@experiment(version=4)
def ADSS_sub_move_to_sample(
    solid_custom_position: str = "cell1_we",
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
    #    x_mm: float = 0.0,
    #    y_mm: float = 0.0,
) -> list:
    """Lift cell, move XY to the plate sample, and seal the cell.

    Turns the peristaltic pump off, sets forward direction, moves Z to load,
    resolves plate XY for the sample, moves there, and lowers to seal.

    Args:
        experiment: Orchestrator-provided experiment context.
        solid_custom_position: PAL custom position label (informational).
        solid_plate_id: Plate identifier of the legacy solid sample.
        solid_sample_no: Sample index on the plate.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # turn pump off
    apm.add(
        NI_server,
        "pump",
        {
            "pump": "peripump",
            "on": 0,
        },
        start_condition=ActionStartCondition.wait_for_all,
    )

    # set pump flow forward
    apm.add(
        NI_server,
        "pump",
        {
            "pump": "direction",
            "on": 0,
        },
        start_condition=ActionStartCondition.wait_for_all,
    )

    # move z to home
    apm.add(MOTOR_server, "z_move", {"z_position": "load"})

    # move to position
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

    apm.add(
        MOTOR_server,
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
    apm.add(MOTOR_server, "z_move", {"z_position": "seal"})

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=4)
def ADSS_sub_sample_start(
    solid_custom_position: str = "cell1_we",
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
    #    x_mm: float = 0.0,
    #    y_mm: float = 0.0,
    previous_liquid: bool = False,
    liquid_custom_position: str = "cell1_we",
    liquid_sample_no: int = 1,
    liquid_sample_volume_ul: float = 4000,
) -> list:
    """Full sample start: unload, load solid+liquid, move to position, seal cell.

    Wraps ``ADSS_sub_load`` then turns the pump off (forward direction), lifts
    Z to load, moves to the plate XY for the sample, and lowers to seal.

    Args:
        experiment: Orchestrator-provided experiment context.
        solid_custom_position: PAL custom position for the solid.
        solid_plate_id: Plate identifier of the legacy solid sample.
        solid_sample_no: Sample index on the plate.
        previous_liquid: Reuse the previously unloaded liquid if True.
        liquid_custom_position: Target PAL custom position for the liquid.
        liquid_sample_no: Liquid sample number on this host.
        liquid_sample_volume_ul: Liquid volume to add in microliters.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    apm.add_actions(
        ADSS_sub_load(
            solid_custom_position=solid_custom_position,
            solid_plate_id=solid_plate_id,
            solid_sample_no=solid_sample_no,
            previous_liquid=previous_liquid,
            liquid_custom_position=liquid_custom_position,
            liquid_sample_no=liquid_sample_no,
            liquid_sample_volume_ul=liquid_sample_volume_ul,
        )
    )

    # turn pump off
    apm.add(
        NI_server,
        "pump",
        {
            "pump": "peripump",
            "on": 0,
        },
        start_condition=ActionStartCondition.wait_for_all,
    )

    # set pump flow forward
    apm.add(
        NI_server,
        "pump",
        {
            "pump": "direction",
            "on": 0,
        },
        start_condition=ActionStartCondition.wait_for_all,
    )

    # move z to home
    apm.add(MOTOR_server, "z_move", {"z_position": "load"})

    # move to position
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

    apm.add(
        MOTOR_server,
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
    apm.add(MOTOR_server, "z_move", {"z_position": "seal"})

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def ADSS_sub_shutdown() -> list:
    """Run a shutdown sequence: deep-clean PAL, reverse pump, wait, then stop pump.

    Args:
        experiment: Orchestrator-provided experiment context.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # deep clean
    apm.add_actions(
        ADSS_sub_clean_PALtool(clean_tool=PALtools.LS3, clean_volume_ul=500)
    )

    # set pump flow backward
    apm.add(
        NI_server,
        "pump",
        {
            "pump": "direction",
            "on": 1,
        },
        start_condition=ActionStartCondition.wait_for_all,
    )

    # wait some time to pump out the liquid
    apm.add(
        ORCH_server,
        "wait",
        {
            "waittime": 120,
        },
        start_condition=ActionStartCondition.wait_for_all,
    )

    # drain, TODO
    # apm.add_actions(ADSS_sub_drain())

    # turn pump off
    apm.add(
        NI_server,
        "pump",
        {
            "pump": "peripump",
            "on": 0,
        },
        start_condition=ActionStartCondition.wait_for_all,
    )

    # set pump flow forward
    apm.add(
        NI_server,
        "pump",
        {
            "pump": "direction",
            "on": 0,
        },
        start_condition=ActionStartCondition.wait_for_all,
    )

    # move z to home
    # cannot do this without proper drain for now
    # apm.add_actions(ADSS_sub_disengage())

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def ADSS_sub_drain() -> list:
    """Placeholder drain sub-experiment that currently emits no actions.

    Args:
        experiment: Orchestrator-provided experiment context.

    Returns:
        Empty list of planned actions.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    # TODO
    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def ADSS_sub_clean_PALtool(
    clean_tool: str = PALtools.LS3,
    clean_volume_ul: int = 500,
) -> list:
    """Perform a deep clean of the selected PAL tool.

    Args:
        experiment: Orchestrator-provided experiment context.
        clean_tool: PAL tool identifier (e.g. ``PALtools.LS3``).
        clean_volume_ul: Cleaning volume per wash in microliters.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # deep clean
    apm.add(
        PAL_server,
        "PAL_deepclean",
        {
            "tool": clean_tool,
            "volume_ul": clean_volume_ul,
        },
        start_condition=ActionStartCondition.wait_for_all,
    )

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def ADSS_sub_fillfixed(
    fill_vol_ul: int = 10000,
    filltime_sec: float = 10.0,
    PAL_Injector: str = "PALtools.LS3",
) -> list:
    """Fill ``cell1_we`` from ``elec_res1`` using PAL fixed-volume fill, then run pump.

    Args:
        experiment: Orchestrator-provided experiment context.
        fill_vol_ul: Fixed fill volume in microliters.
        filltime_sec: Time the peristaltic pump runs after the PAL fill.
        PAL_Injector: PAL tool identifier.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # fill liquid, no wash (assume it was cleaned before)
    apm.add(
        PAL_server,
        "PAL_fillfixed",
        {
            "tool": PAL_Injector,
            "source": "elec_res1",
            "dest": "cell1_we",
            "volume_ul": fill_vol_ul,
            "wash1": 0,
            "wash2": 0,
            "wash3": 0,
            "wash4": 0,
        },
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
    )

    # set pump flow forward
    apm.add(
        NI_server,
        "pump",
        {
            "pump": "direction",
            "on": 0,
        },
        start_condition=ActionStartCondition.wait_for_all,
    )

    # turn on pump
    apm.add(
        NI_server,
        "pump",
        {
            "pump": "peripump",
            "on": 1,
        },
        start_condition=ActionStartCondition.wait_for_all,
    )

    # wait some time to pump in the liquid
    apm.add(
        ORCH_server,
        "wait",
        {
            "waittime": filltime_sec,
        },
        start_condition=ActionStartCondition.wait_for_all,
    )

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def ADSS_sub_fill(
    fill_vol_ul: int = 1000,
    PAL_Injector: str = "PALtools.LS3",
) -> list:
    """Fill ``cell1_we`` from ``elec_res1`` using PAL variable fill (no wash).

    Args:
        experiment: Orchestrator-provided experiment context.
        fill_vol_ul: Fill volume in microliters.
        PAL_Injector: PAL tool identifier.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # fill liquid, no wash (assume it was cleaned before)
    apm.add(
        PAL_server,
        "PAL_fill",
        {
            "tool": PAL_Injector,
            "source": "elec_res1",
            "dest": "cell1_we",
            "volume_ul": fill_vol_ul,
            "wash1": 0,
            "wash2": 0,
            "wash3": 0,
            "wash4": 0,
        },
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
    )

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=12)
def ADSS_sub_CA(
    CA_potential: float = 0.0,
    ph: float = 9.53,
    potential_versus: str = "rhe",
    ref_type: str = "inhouse",
    ref_offset__V: float = 0.0,
    gamry_i_range: str = "auto",
    samplerate_sec: float = 0.05,
    CA_duration_sec: float = 1800,
    insert_electrolyte_bool: bool = False,  # rename this to insert_electrolyte_bool to avoid confusion
    insert_electrolyte_volume_ul: int = 0,
    insert_electrolyte_time_sec: float = 1800,
    electrolyte_sample_no: int = 1,
    bubbler_gas: str = "",
    previous_liquid_injected: str = "",
    aliquot_volume_ul: int = 200,
    aliquot_times_sec: List[float] = [],
    aliquot_insitu: bool = False,
    aliquot_pre: bool = False,
    aliquot_post: bool = False,
    washmod_in: int = 0,
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "fill serial number here",
) -> list:
    """Run a chronoamperometry (CA) experiment with optional PAL aliquots.

    Queries the current cell sample, optionally takes a pre-CA aliquot,
    applies a referenced potential for the configured duration, then
    optionally runs in-situ aliquot/electrolyte insertion and a post-CA
    aliquot.

    Args:
        experiment: Orchestrator-provided experiment context.
        CA_potential: Applied potential before reference correction (V).
        ph: Solution pH used for Nernst conversion.
        potential_versus: ``"rhe"`` or ``"oer"`` reference frame.
        ref_type: Reference electrode key into ``REF_TABLE``.
        ref_offset__V: Calibration offset of the reference electrode (V).
        gamry_i_range: Gamry current-range setting.
        samplerate_sec: Acquisition interval (s).
        CA_duration_sec: Total CA duration (s).
        insert_electrolyte_bool: Insert electrolyte mid-CA when True.
        insert_electrolyte_volume_ul: Volume to insert (uL).
        insert_electrolyte_time_sec: Time after CA start to insert (s).
        electrolyte_sample_no: Liquid sample number of the electrolyte.
        bubbler_gas: Informational label for bubbled gas.
        previous_liquid_injected: Informational label for prior injection.
        aliquot_volume_ul: Aliquot volume (uL).
        aliquot_times_sec: Aliquot timestamps (s) relative to CA start.
        aliquot_insitu: Take aliquots concurrent with CA when True.
        aliquot_pre: Take an aliquot before CA when True.
        aliquot_post: Take an aliquot after CA when True.
        washmod_in: Starting wash counter used to cycle PAL washes.
        PAL_Injector: PAL injector tool identifier.
        PAL_Injector_id: PAL injector serial-number string.

    Returns:
        List of planned actions for the orchestrator.
    """
    washmod = washmod_in

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

    # calculate potential
    versus = 0  # for vs rhe
    if potential_versus == "oer":
        versus = 1.23
    if ref_type == "rhe":
        potential = CA_potential - ref_offset__V + versus
    else:
        potential = (
            CA_potential
            - 1.0 * ref_offset__V
            + versus
            - 0.059 * ph
            - REF_TABLE[ref_type]
        )
    print(f"ADSS_sub_CA potential: {potential}")

    if aliquot_pre:
        washmod += 1
        washone = washmod % 4 % 3 % 2
        washtwo = (washmod + 1) % 4 % 3 % 2
        washthree = (washmod + 2) % 4 % 3 % 2
        washfour = (washmod + 3) % 4 % 3 % 2

        apm.add_actions(
            ADSS_sub_sample_aliquot(
                aliquot_volume_ul=aliquot_volume_ul,
                EquilibrationTime_s=0,
                PAL_Injector=PAL_Injector,
                PAL_Injector_id=PAL_Injector_id,
                rinse_1=washone,
                rinse_2=washtwo,
                rinse_3=washthree,
                rinse_4=washfour,
            )
        )

    # apply potential
    apm.add(
        PSTAT_server,
        "run_CA",
        {
            "Vval__V": potential,
            "Tval__s": CA_duration_sec,
            "AcqInterval__s": samplerate_sec,
            "IErange": gamry_i_range,
        },
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        technique_name="CA",
        process_finish=True,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
            ProcessContrib.run_use,
        ],
    )
    """
        intervals between PAL_archive aliquots include gas valving off
        before aliquot, and a -65- second wait to turn back on gas valve
        that occurs before full PAL action is completed
    """
    if aliquot_insitu or insert_electrolyte_bool:

        apm.add_actions(
            ADSS_sub_insitu_actions(
                aliquot_insitu=aliquot_insitu,
                insert_electrolyte_bool=insert_electrolyte_bool,
                insert_electrolyte_volume_ul=insert_electrolyte_volume_ul,
                insert_electrolyte_time_sec=insert_electrolyte_time_sec,
                electrolyte_sample_no=electrolyte_sample_no,
                aliquot_volume_ul=aliquot_volume_ul,
                aliquot_times_sec=aliquot_times_sec,
                washmod_in=washmod,
                PAL_Injector=PAL_Injector,
                PAL_Injector_id=PAL_Injector_id,
            )
        )

    if aliquot_post:
        washmod += 1
        washone = washmod % 4 % 3 % 2
        washtwo = (washmod + 1) % 4 % 3 % 2
        washthree = (washmod + 2) % 4 % 3 % 2
        washfour = (washmod + 3) % 4 % 3 % 2

        apm.add_actions(
            ADSS_sub_sample_aliquot(
                aliquot_volume_ul=aliquot_volume_ul,
                EquilibrationTime_s=0,
                PAL_Injector=PAL_Injector,
                PAL_Injector_id=PAL_Injector_id,
                rinse_1=washone,
                rinse_2=washtwo,
                rinse_3=washthree,
                rinse_4=washfour,
            )
        )

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=8)
def ADSS_sub_CA_photo(
    CA_potential: float = 0.0,
    ph: float = 9.53,
    potential_versus: str = "rhe",
    ref_type: str = "inhouse",
    ref_offset__V: float = 0.0,
    gamry_i_range: str = "auto",
    samplerate_sec: float = 0.05,
    CA_duration_sec: float = 1800,
    led_wavelength: str = "385",
    toggle_illum_duty: float = 1,
    insert_electrolyte_bool: bool = False,
    insert_electrolyte_volume_ul: int = 0,
    insert_electrolyte_time_sec: float = 1800,
    electrolyte_sample_no: int = 1,
    bubbler_gas: str = "",
    previous_liquid_injected: str = "",
    aliquot_volume_ul: int = 200,
    aliquot_times_sec: List[float] = [],
    aliquot_insitu: bool = False,
    aliquot_pre: bool = False,
    aliquot_post: bool = False,
    washmod_in: int = 0,
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "fill serial number here",
) -> list:
    """Run a CA experiment with LED illumination and optional PAL aliquots.

    Same as ``ADSS_sub_CA`` but turns the NI LED on before CA and off after
    in-situ actions. The pre/post aliquot timing and reference correction
    match the non-photo CA variant.

    Args:
        experiment: Orchestrator-provided experiment context.
        CA_potential: Applied potential before reference correction (V).
        ph: Solution pH used for Nernst conversion.
        potential_versus: ``"rhe"`` or ``"oer"`` reference frame.
        ref_type: Reference electrode key into ``REF_TABLE``.
        ref_offset__V: Calibration offset of the reference electrode (V).
        gamry_i_range: Gamry current-range setting.
        samplerate_sec: Acquisition interval (s).
        CA_duration_sec: Total CA duration (s).
        led_wavelength: LED wavelength label.
        toggle_illum_duty: Illumination duty cycle parameter.
        insert_electrolyte_bool: Insert electrolyte mid-CA when True.
        insert_electrolyte_volume_ul: Volume to insert (uL).
        insert_electrolyte_time_sec: Time after CA start to insert (s).
        electrolyte_sample_no: Liquid sample number of the electrolyte.
        bubbler_gas: Informational label for bubbled gas.
        previous_liquid_injected: Informational label for prior injection.
        aliquot_volume_ul: Aliquot volume (uL).
        aliquot_times_sec: Aliquot timestamps (s).
        aliquot_insitu: Take aliquots concurrent with CA when True.
        aliquot_pre: Take an aliquot before CA when True.
        aliquot_post: Take an aliquot after CA when True.
        washmod_in: Starting wash counter used to cycle PAL washes.
        PAL_Injector: PAL injector tool identifier.
        PAL_Injector_id: PAL injector serial-number string.

    Returns:
        List of planned actions for the orchestrator.
    """
    washmod = washmod_in

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

    if aliquot_pre:
        washmod += 1
        washone = washmod % 4 % 3 % 2
        washtwo = (washmod + 1) % 4 % 3 % 2
        washthree = (washmod + 2) % 4 % 3 % 2
        washfour = (washmod + 3) % 4 % 3 % 2

        apm.add_actions(
            ADSS_sub_sample_aliquot(
                aliquot_volume_ul=aliquot_volume_ul,
                EquilibrationTime_s=0,
                PAL_Injector=PAL_Injector,
                PAL_Injector_id=PAL_Injector_id,
                rinse_1=washone,
                rinse_2=washtwo,
                rinse_3=washthree,
                rinse_4=washfour,
            )
        )

    apm.add(NI_server, "led", {"led": "led", "on": 1})

    # calculate potential
    versus = 0  # for vs rhe
    if potential_versus == "oer":
        versus = 1.23
    if ref_type == "rhe":
        potential = CA_potential - ref_offset__V + versus
    else:
        potential = (
            CA_potential
            - 1.0 * ref_offset__V
            + versus
            - 0.059 * ph
            - REF_TABLE[ref_type]
        )
    print(f"ADSS_sub_CA potential: {potential}")

    # apply potential
    apm.add(
        PSTAT_server,
        "run_CA",
        {
            "Vval__V": potential,
            "Tval__s": CA_duration_sec,
            "AcqInterval__s": samplerate_sec,
            "IErange": gamry_i_range,
        },
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        technique_name="CA_photo",
        process_finish=True,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
            ProcessContrib.run_use,
        ],
    )
    """
        intervals between PAL_archive aliquots include gas valving off
        before aliquot, and a -65- second wait to turn back on gas valve
        that occurs before full PAL action is completed
    """
    if aliquot_insitu or insert_electrolyte_bool:

        apm.add_actions(
            ADSS_sub_insitu_actions(
                aliquot_insitu=aliquot_insitu,
                insert_electrolyte_bool=insert_electrolyte_bool,
                insert_electrolyte_volume_ul=insert_electrolyte_volume_ul,
                insert_electrolyte_time_sec=insert_electrolyte_time_sec,
                electrolyte_sample_no=electrolyte_sample_no,
                aliquot_volume_ul=aliquot_volume_ul,
                aliquot_times_sec=aliquot_times_sec,
                washmod_in=washmod,
                PAL_Injector=PAL_Injector,
                PAL_Injector_id=PAL_Injector_id,
            )
        )

    apm.add(NI_server, "led", {"led": "led", "on": 0})

    if aliquot_post:
        washmod += 1
        washone = washmod % 4 % 3 % 2
        washtwo = (washmod + 1) % 4 % 3 % 2
        washthree = (washmod + 2) % 4 % 3 % 2
        washfour = (washmod + 3) % 4 % 3 % 2

        apm.add_actions(
            ADSS_sub_sample_aliquot(
                aliquot_volume_ul=aliquot_volume_ul,
                EquilibrationTime_s=0,
                PAL_Injector=PAL_Injector,
                PAL_Injector_id=PAL_Injector_id,
                rinse_1=washone,
                rinse_2=washtwo,
                rinse_3=washthree,
                rinse_4=washfour,
            )
        )

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=8)
def ADSS_sub_CV(
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
    ph: float = 9.53,
    ref_type: str = "inhouse",
    ref_offset__V: float = 0.0,
    insert_electrolyte_bool: bool = False,
    insert_electrolyte_volume_ul: int = 0,
    insert_electrolyte_time_sec: float = 1800,
    electrolyte_sample_no: int = 1,
    aliquot_volume_ul: int = 200,
    aliquot_times_sec: List[float] = [],
    aliquot_insitu: bool = False,
    aliquot_pre: bool = False,
    aliquot_post: bool = False,
    washmod_in: int = 0,
    bubbler_gas: str = "",
    previous_liquid_injected: str = "",
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "fill serial number here",
    run_use: RunUse = "data",
) -> list:
    """Run a cyclic voltammetry (CV) experiment with optional PAL aliquots.

    Reference-corrects the four CV vertices versus the chosen reference at
    the given pH, queries the cell sample, optionally takes pre/post and
    in-situ aliquots, and dispatches ``run_CV`` to the potentiostat.

    Args:
        experiment: Orchestrator-provided experiment context.
        Vinit_vsRHE: Initial potential vs RHE (V).
        Vapex1_vsRHE: First apex potential vs RHE (V).
        Vapex2_vsRHE: Second apex potential vs RHE (V).
        Vfinal_vsRHE: Final potential vs RHE (V).
        scanrate_voltsec: Scan rate (V/s).
        samplerate_sec: Acquisition interval (s).
        cycles: Number of CV cycles.
        gamry_i_range: Gamry current-range setting.
        ph: Solution pH used for Nernst conversion.
        ref_type: Reference electrode key into ``REF_TABLE``.
        ref_offset__V: Calibration offset of the reference electrode (V).
        insert_electrolyte_bool: Insert electrolyte during CV when True.
        insert_electrolyte_volume_ul: Volume to insert (uL).
        insert_electrolyte_time_sec: Time after CV start to insert (s).
        electrolyte_sample_no: Liquid sample number of the electrolyte.
        aliquot_volume_ul: Aliquot volume (uL).
        aliquot_times_sec: Aliquot timestamps (s).
        aliquot_insitu: Take aliquots concurrent with CV when True.
        aliquot_pre: Take an aliquot before CV when True.
        aliquot_post: Take an aliquot after CV when True.
        washmod_in: Starting wash counter used to cycle PAL washes.
        bubbler_gas: Informational label for bubbled gas.
        previous_liquid_injected: Informational label for prior injection.
        PAL_Injector: PAL injector tool identifier.
        PAL_Injector_id: PAL injector serial-number string.
        run_use: ``RunUse`` tag forwarded to the potentiostat action.

    Returns:
        List of planned actions for the orchestrator.
    """

    washmod = washmod_in

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

    if aliquot_pre:
        washmod += 1
        washone = washmod % 4 % 3 % 2
        washtwo = (washmod + 1) % 4 % 3 % 2
        washthree = (washmod + 2) % 4 % 3 % 2
        washfour = (washmod + 3) % 4 % 3 % 2

        apm.add_actions(
            ADSS_sub_sample_aliquot(
                aliquot_volume_ul=aliquot_volume_ul,
                EquilibrationTime_s=0,
                PAL_Injector=PAL_Injector,
                PAL_Injector_id=PAL_Injector_id,
                rinse_1=washone,
                rinse_2=washtwo,
                rinse_3=washthree,
                rinse_4=washfour,
            )
        )

    # apply potential
    apm.add(
        PSTAT_server,
        "run_CV",
        {
            "Vinit__V": Vinit_vsRHE
            - 1.0 * ref_offset__V
            - REF_TABLE[ref_type]
            - 0.059 * ph,
            "Vapex1__V": Vapex1_vsRHE
            - 1.0 * ref_offset__V
            - REF_TABLE[ref_type]
            - 0.059 * ph,
            "Vapex2__V": Vapex2_vsRHE
            - 1.0 * ref_offset__V
            - REF_TABLE[ref_type]
            - 0.059 * ph,
            "Vfinal__V": Vfinal_vsRHE
            - 1.0 * ref_offset__V
            - REF_TABLE[ref_type]
            - 0.059 * ph,
            "ScanRate__V_s": scanrate_voltsec,
            "AcqInterval__s": samplerate_sec,
            "Cycles": cycles,
            "IErange": gamry_i_range,
        },
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        run_use=run_use,
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        technique_name="CV",
        process_finish=True,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
            ProcessContrib.run_use,
        ],
    )
    if aliquot_insitu or insert_electrolyte_bool:

        apm.add_actions(
            ADSS_sub_insitu_actions(
                aliquot_insitu=aliquot_insitu,
                insert_electrolyte_bool=insert_electrolyte_bool,
                insert_electrolyte_volume_ul=insert_electrolyte_volume_ul,
                insert_electrolyte_time_sec=insert_electrolyte_time_sec,
                electrolyte_sample_no=electrolyte_sample_no,
                aliquot_volume_ul=aliquot_volume_ul,
                aliquot_times_sec=aliquot_times_sec,
                washmod_in=washmod,
                PAL_Injector=PAL_Injector,
                PAL_Injector_id=PAL_Injector_id,
            )
        )

    if aliquot_post:
        washmod += 1
        washone = washmod % 4 % 3 % 2
        washtwo = (washmod + 1) % 4 % 3 % 2
        washthree = (washmod + 2) % 4 % 3 % 2
        washfour = (washmod + 3) % 4 % 3 % 2

        apm.add_actions(
            ADSS_sub_sample_aliquot(
                aliquot_volume_ul=aliquot_volume_ul,
                EquilibrationTime_s=0,
                PAL_Injector=PAL_Injector,
                PAL_Injector_id=PAL_Injector_id,
                rinse_1=washone,
                rinse_2=washtwo,
                rinse_3=washthree,
                rinse_4=washfour,
            )
        )

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=8)
def ADSS_sub_OCV(
    Tval__s: float = 60.0,
    gamry_i_range: str = "auto",
    samplerate_sec: float = 0.05,
    ph: float = 9.53,
    ref_type: str = "inhouse",
    ref_offset__V: float = 0.0,
    bubbler_gas: str = "",
    previous_liquid_injected: str = "",
    aliquot_volume_ul: int = 200,
    aliquot_times_sec: List[float] = [],
    aliquot_insitu: bool = False,
    aliquot_pre: bool = False,
    aliquot_post: bool = False,
    washmod_in: int = 0,
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "fill serial number here",
    rinse_1: int = 1,
    rinse_4: int = 0,
    check_bubble: bool = False,
    RSD_threshold: float = 1,
    simple_threshold: float = 0.3,
    signal_change_threshold: float = 0.01,
    amplitude_threshold: float = 0.05,
    bubble_pump_reverse_time_s: float = 15,
    bubble_pump_forward_time_s: float = 10,
    run_use: RunUse = "data",
) -> list:
    """Run an open-circuit voltage (OCV) experiment with optional PAL aliquots.

    Queries the cell sample, optionally takes a pre-OCV aliquot, dispatches
    ``run_OCV`` with bubble-detection thresholds, and on ``check_bubble``
    queues a conditional ``ADSS_sub_remove_bubble`` experiment when a
    bubble is detected.

    Args:
        experiment: Orchestrator-provided experiment context.
        Tval__s: OCV duration (s).
        gamry_i_range: Gamry current-range setting.
        samplerate_sec: Acquisition interval (s).
        ph: Solution pH (used by the conditional bubble removal).
        ref_type: Reference electrode key into ``REF_TABLE``.
        ref_offset__V: Calibration offset of the reference electrode (V).
        bubbler_gas: Informational label for bubbled gas.
        previous_liquid_injected: Informational label for prior injection.
        aliquot_volume_ul: Aliquot volume (uL).
        aliquot_times_sec: Aliquot timestamps (s).
        aliquot_insitu: Take aliquots concurrent with OCV when True.
        aliquot_pre: Take an aliquot before OCV when True.
        aliquot_post: Take an aliquot after OCV when True.
        washmod_in: Starting wash counter used to cycle PAL washes.
        PAL_Injector: PAL injector tool identifier.
        PAL_Injector_id: PAL injector serial-number string.
        rinse_1: PAL wash slot 1 setting (unused outside conditional path).
        rinse_4: PAL wash slot 4 setting (unused outside conditional path).
        check_bubble: Queue conditional bubble removal when True.
        RSD_threshold: Bubble-detection RSD threshold.
        simple_threshold: Bubble-detection simple threshold.
        signal_change_threshold: Bubble-detection signal-change threshold.
        amplitude_threshold: Bubble-detection amplitude threshold.
        bubble_pump_reverse_time_s: Pump-reverse time for bubble removal (s).
        bubble_pump_forward_time_s: Pump-forward time for bubble removal (s).
        run_use: ``RunUse`` tag forwarded to the potentiostat action.

    Returns:
        List of planned actions for the orchestrator.
    """

    washmod = washmod_in

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

    if aliquot_pre:
        washmod += 1
        washone = washmod % 4 % 3 % 2
        washtwo = (washmod + 1) % 4 % 3 % 2
        washthree = (washmod + 2) % 4 % 3 % 2
        washfour = (washmod + 3) % 4 % 3 % 2

        apm.add_actions(
            ADSS_sub_sample_aliquot(
                aliquot_volume_ul=aliquot_volume_ul,
                EquilibrationTime_s=0,
                PAL_Injector=PAL_Injector,
                PAL_Injector_id=PAL_Injector_id,
                rinse_1=washone,
                rinse_2=washtwo,
                rinse_3=washthree,
                rinse_4=washfour,
            )
        )

    # OCV
    apm.add(
        PSTAT_server,
        "run_OCV",
        {
            "Tval__s": Tval__s,
            "AcqInterval__s": samplerate_sec,
            "IErange": gamry_i_range,
            "RSD_threshold": RSD_threshold,
            "simple_threshold": simple_threshold,
            "signal_change_threshold": signal_change_threshold,
            "amplitude_threshold": amplitude_threshold,
        },
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        to_global_params=["has_bubble"],
        run_use=run_use,
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        technique_name="OCV",
        process_finish=True,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
            ProcessContrib.run_use,
        ],
    )
    if aliquot_insitu:

        apm.add_actions(
            ADSS_sub_insitu_actions(
                aliquot_insitu=aliquot_insitu,
                aliquot_volume_ul=aliquot_volume_ul,
                aliquot_times_sec=aliquot_times_sec,
                washmod_in=washmod,
                PAL_Injector=PAL_Injector,
                PAL_Injector_id=PAL_Injector_id,
            )
        )

    if check_bubble:
        apm.add(
            ORCH_server,
            "conditional_exp",
            {
                "check_parameter": "has_bubble",
                "check_condition": "equals",
                "check_value": True,
                "conditional_experiment_name": "ADSS_sub_remove_bubble",
                "conditional_experiment_params": {
                    "Tval__s": Tval__s,
                    "gamry_i_range": gamry_i_range,
                    "samplerate_sec": samplerate_sec,
                    "ph": ph,
                    "ref_type": ref_type,
                    "ref_offset__V": ref_offset__V,
                    "pump_reverse_time_s": bubble_pump_reverse_time_s,
                    "pump_forward_time_s": bubble_pump_forward_time_s,
                    "RSD_threshold": RSD_threshold,
                    "simple_threshold": simple_threshold,
                    "signal_change_threshold": signal_change_threshold,
                    "amplitude_threshold": amplitude_threshold,
                    "run_use": run_use,
                },
            },
            from_global_act_params={"has_bubble": "has_bubble"},
        )

    if aliquot_post:
        washmod += 1
        washone = washmod % 4 % 3 % 2
        washtwo = (washmod + 1) % 4 % 3 % 2
        washthree = (washmod + 2) % 4 % 3 % 2
        washfour = (washmod + 3) % 4 % 3 % 2

        apm.add_actions(
            ADSS_sub_sample_aliquot(
                aliquot_volume_ul=aliquot_volume_ul,
                EquilibrationTime_s=0,
                PAL_Injector=PAL_Injector,
                PAL_Injector_id=PAL_Injector_id,
                rinse_1=washone,
                rinse_2=washtwo,
                rinse_3=washthree,
                rinse_4=washfour,
            )
        )

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=9)
def ADSS_sub_OCV_photo(
    Tval__s: float = 60.0,
    gamry_i_range: str = "auto",
    samplerate_sec: float = 0.05,
    ph: float = 9.53,
    ref_type: str = "inhouse",
    ref_offset__V: float = 0.0,
    led_wavelength: str = "385",
    toggle_illum_duty: float = 1,
    bubbler_gas: str = "",
    previous_liquid_injected: str = "",
    aliquot_volume_ul: int = 200,
    aliquot_times_sec: List[float] = [],
    aliquot_insitu: bool = False,
    aliquot_pre: bool = False,
    aliquot_post: bool = False,
    washmod_in: int = 0,
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "fill serial number here",
    rinse_1: int = 1,
    rinse_4: int = 0,
) -> list:
    """Run an OCV experiment with LED illumination and optional PAL aliquots.

    Same as ``ADSS_sub_OCV`` but turns the LED on before the OCV action and
    off after any in-situ aliquots.

    Args:
        experiment: Orchestrator-provided experiment context.
        Tval__s: OCV duration (s).
        gamry_i_range: Gamry current-range setting.
        samplerate_sec: Acquisition interval (s).
        ph: Solution pH.
        ref_type: Reference electrode key into ``REF_TABLE``.
        ref_offset__V: Calibration offset of the reference electrode (V).
        led_wavelength: LED wavelength label.
        toggle_illum_duty: Illumination duty cycle parameter.
        bubbler_gas: Informational label for bubbled gas.
        previous_liquid_injected: Informational label for prior injection.
        aliquot_volume_ul: Aliquot volume (uL).
        aliquot_times_sec: Aliquot timestamps (s).
        aliquot_insitu: Take aliquots concurrent with OCV when True.
        aliquot_pre: Take an aliquot before OCV when True.
        aliquot_post: Take an aliquot after OCV when True.
        washmod_in: Starting wash counter used to cycle PAL washes.
        PAL_Injector: PAL injector tool identifier.
        PAL_Injector_id: PAL injector serial-number string.
        rinse_1: PAL wash slot 1 setting (informational).
        rinse_4: PAL wash slot 4 setting (informational).

    Returns:
        List of planned actions for the orchestrator.
    """

    washmod = washmod_in

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

    if aliquot_pre:
        washmod += 1
        washone = washmod % 4 % 3 % 2
        washtwo = (washmod + 1) % 4 % 3 % 2
        washthree = (washmod + 2) % 4 % 3 % 2
        washfour = (washmod + 3) % 4 % 3 % 2

        apm.add_actions(
            ADSS_sub_sample_aliquot(
                aliquot_volume_ul=aliquot_volume_ul,
                EquilibrationTime_s=0,
                PAL_Injector=PAL_Injector,
                PAL_Injector_id=PAL_Injector_id,
                rinse_1=washone,
                rinse_2=washtwo,
                rinse_3=washthree,
                rinse_4=washfour,
            )
        )

    apm.add(NI_server, "led", {"led": "led", "on": 1})

    # OCV
    apm.add(
        PSTAT_server,
        "run_OCV",
        {
            "Tval__s": Tval__s,
            "AcqInterval__s": samplerate_sec,
            "IErange": gamry_i_range,
        },
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        technique_name="OCV_photo",
        process_finish=True,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
            ProcessContrib.run_use,
        ],
    )
    if aliquot_insitu:

        apm.add_actions(
            ADSS_sub_insitu_actions(
                aliquot_insitu=aliquot_insitu,
                aliquot_volume_ul=aliquot_volume_ul,
                aliquot_times_sec=aliquot_times_sec,
                washmod_in=washmod,
                PAL_Injector=PAL_Injector,
                PAL_Injector_id=PAL_Injector_id,
            )
        )

        apm.add(NI_server, "led", {"led": "led", "on": 0})

    if aliquot_post:
        washmod += 1
        washone = washmod % 4 % 3 % 2
        washtwo = (washmod + 1) % 4 % 3 % 2
        washthree = (washmod + 2) % 4 % 3 % 2
        washfour = (washmod + 3) % 4 % 3 % 2

        apm.add_actions(
            ADSS_sub_sample_aliquot(
                aliquot_volume_ul=aliquot_volume_ul,
                EquilibrationTime_s=0,
                PAL_Injector=PAL_Injector,
                PAL_Injector_id=PAL_Injector_id,
                rinse_1=washone,
                rinse_2=washtwo,
                rinse_3=washthree,
                rinse_4=washfour,
            )
        )

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=3)
def ADSS_sub_insitu_actions(
    insert_electrolyte_bool: bool = False,
    insert_electrolyte_volume_ul: int = 0,
    insert_electrolyte_time_sec: float = 1800,
    electrolyte_sample_no: int = 1,
    aliquot_volume_ul: int = 200,
    aliquot_times_sec: List[float] = [],
    aliquot_insitu: bool = True,
    injector_wash_one: bool = False,
    washmod_in: int = 0,
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "fill serial number here",
) -> list:
    """Build a timeline of in-situ aliquot draws and/or electrolyte injections.

    Computes interval gaps between aliquot times and an optional electrolyte
    insertion time, schedules gas-valve toggles around each PAL aliquot, and
    interleaves electrolyte additions via ``ADSS_sub_cellfill_prefilled``.

    Args:
        experiment: Orchestrator-provided experiment context.
        insert_electrolyte_bool: Insert electrolyte at ``insert_electrolyte_time_sec``.
        insert_electrolyte_volume_ul: Volume to insert (uL).
        insert_electrolyte_time_sec: Insertion time after start (s).
        electrolyte_sample_no: Liquid sample number of the electrolyte.
        aliquot_volume_ul: Aliquot volume (uL).
        aliquot_times_sec: Aliquot timestamps (s) relative to the start.
        aliquot_insitu: Schedule aliquots when True; else inject only.
        injector_wash_one: If True, fix washes to ``[1, 0, 0, 0]``.
        washmod_in: Starting wash counter used to cycle PAL washes.
        PAL_Injector: PAL injector tool identifier.
        PAL_Injector_id: PAL injector serial-number string.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    """
        intervals between PAL_archive aliquots include gas valving off
        before aliquot, and a -65- second wait to turn back on gas valve
        that occurs before full PAL action is completed
    """

    atimes = aliquot_times_sec
    etime = insert_electrolyte_time_sec
    mlist = [("aliquot", t) for t in atimes]
    waitcond = ActionStartCondition.no_wait
    intervals = []

    if aliquot_insitu:

        if insert_electrolyte_bool:
            eidx = [i for i, v in enumerate(atimes) if v < etime]
            mlist.insert(max(eidx) + 1, ("electrolyte", etime))

        vwait = 0
        if len(mlist) > 1:
            intervals = [mlist[0][1]] + [
                x[1] - y[1] for x, y in zip(mlist[1:], mlist[:-1])
            ]
        elif len(mlist) == 1:
            intervals = [mlist[0][1]]
            print(mlist)
            print(intervals)

        washmod = washmod_in
        if injector_wash_one:
            washone = 1
            washtwo = 0
            washthree = 0
            washfour = 0
        else:
            washmod += 1
            washone = washmod % 4 % 3 % 2
            washtwo = (washmod + 1) % 4 % 3 % 2
            washthree = (washmod + 2) % 4 % 3 % 2
            washfour = (washmod + 3) % 4 % 3 % 2

        for mtup, interval in zip(mlist, intervals):
            if mtup[0] == "aliquot":
                apm.add(
                    ORCH_server, "wait", {"waittime": interval - vwait - 1}, waitcond
                )
                apm.add(
                    NI_server,
                    "gasvalve",
                    {"gasvalve": "inlet", "on": 0},
                    ActionStartCondition.wait_for_orch,
                )
                apm.add(
                    PAL_server,
                    "PAL_archive",
                    {
                        "tool": PAL_Injector,
                        "source": "cell1_we",
                        "volume_ul": aliquot_volume_ul,
                        "sampleperiod": [0.0],
                        "spacingmethod": Spacingmethod.linear,
                        "spacingfactor": 1.0,
                        "timeoffset": 0.0,
                        "wash1": washone,
                        "wash2": washtwo,
                        "wash3": washthree,
                        "wash4": washfour,
                    },
                    start_condition=ActionStartCondition.no_wait,
                    technique_name="liquid_product_archive",
                    process_finish=True,
                    process_contrib=[
                        ProcessContrib.action_params,
                        ProcessContrib.files,
                        ProcessContrib.samples_in,
                        ProcessContrib.samples_out,
                        ProcessContrib.run_use,
                    ],
                )
                vwait = 61  # orig 65
                if not injector_wash_one:
                    washmod += 1
                    washone = washmod % 4 % 3 % 2
                    washtwo = (washmod + 1) % 4 % 3 % 2
                    washthree = (washmod + 2) % 4 % 3 % 2
                    washfour = (washmod + 3) % 4 % 3 % 2

                apm.add(ORCH_server, "wait", {"waittime": vwait}, waitcond)
                apm.add(
                    NI_server,
                    "gasvalve",
                    {"gasvalve": "inlet", "on": 1},
                    ActionStartCondition.wait_for_orch,
                )
            elif mtup[0] == "electrolyte":
                #                if insert_electrolyte_bool:
                # apm.add_actions(
                #     ADSS_sub_load_liquid(
                #         experiment=experiment,
                #         liquid_custom_position="cell1_we",
                #         liquid_sample_no=electrolyte_sample_no,
                #         volume_ul_cell_liquid=insert_electrolyte_ul,
                #     )
                # )

                apm.add(
                    ORCH_server,
                    "wait",
                    {"waittime": interval - vwait},
                    waitcond,  # remove -vwait
                )
                apm.add(
                    PAL_server,
                    "archive_custom_add_liquid",
                    {
                        "custom": "cell1_we",
                        "source_liquid_in": LiquidSample(
                            **{
                                "sample_no": electrolyte_sample_no,
                                "machine_name": gethostname(),
                            }
                        ).model_dump(),
                        "volume_ml": insert_electrolyte_volume_ul / 1000,
                        "combine_liquids": True,
                        "dilute_liquids": False,
                    },
                    ActionStartCondition.wait_for_orch,
                )
                apm.add_actions(
                    ADSS_sub_cellfill_prefilled(
                        Solution_volume_ul=insert_electrolyte_volume_ul,
                        Syringe_rate_ulsec=300,
                    )
                )
                # apm.add(ORCH_server, "wait", {"waittime": vwait}, waitcond) #
                apm.add(
                    ORCH_server,
                    "wait",
                    {"waittime": 0.1},
                    ActionStartCondition.wait_for_orch,
                )
    elif insert_electrolyte_bool:
        apm.add(ORCH_server, "wait", {"waittime": etime}, waitcond)
        apm.add(
            PAL_server,
            "archive_custom_add_liquid",
            {
                "custom": "cell1_we",
                "source_liquid_in": LiquidSample(
                    **{
                        "sample_no": electrolyte_sample_no,
                        "machine_name": gethostname(),
                    }
                ).model_dump(),
                "volume_ml": insert_electrolyte_volume_ul / 1000,
                "combine_liquids": True,
                "dilute_liquids": False,
            },
            ActionStartCondition.wait_for_orch,
        )
        apm.add_actions(
            ADSS_sub_cellfill_prefilled(
                Solution_volume_ul=insert_electrolyte_volume_ul,
                Syringe_rate_ulsec=300,
            )
        )
        # apm.add(ORCH_server, "wait", {"waittime": 8}, waitcond)  #orig wait is 60 but can't remember why
        apm.add(
            ORCH_server,
            "wait",
            {"waittime": 0.1},
            ActionStartCondition.wait_for_orch,
        )

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def ADSS_sub_add_liquid(
    virtual_add: bool = False,
    added_liquid_volume_ul: int = 0,
    liquid_sample_no: int = 1,
) -> list:
    """Add liquid to ``cell1_we`` and optionally infuse via the work syringe.

    Args:
        experiment: Orchestrator-provided experiment context.
        virtual_add: Skip the syringe infusion when True (archive-only update).
        added_liquid_volume_ul: Volume to add (uL).
        liquid_sample_no: Liquid sample number on this host.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    apm.add(
        PAL_server,
        "archive_custom_add_liquid",
        {
            "custom": "cell1_we",
            "source_liquid_in": LiquidSample(
                **{
                    "sample_no": liquid_sample_no,
                    "machine_name": gethostname(),
                }
            ).model_dump(),
            "volume_ml": added_liquid_volume_ul / 1000,
            "combine_liquids": True,
            "dilute_liquids": False,
        },
        ActionStartCondition.wait_for_orch,
    )
    if not virtual_add:
        apm.add_actions(
            ADSS_sub_cellfill_prefilled(
                Solution_volume_ul=added_liquid_volume_ul,
                Syringe_rate_ulsec=300,
            )
        )

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def ADSS_sub_tray_unload(
    tray: int = 2,
    slot: int = 1,
    survey_runs: int = 1,
    main_runs: int = 3,
    rack: int = 2,
) -> list:
    """Export a PAL tray (JSON, CSV, ICPMS) and then unload it.

    Args:
        experiment: Orchestrator-provided experiment context.
        tray: PAL tray index.
        slot: PAL slot index on that tray.
        survey_runs: ICPMS rough sweep count over the partial-molarity range.
        main_runs: ICPMS sweeps centered on the element partial molarity.
        rack: ICPMS instrument tray rack position.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    apm.add(
        PAL_server,
        "archive_tray_export_json",
        {
            "tray": tray,
            "slot": slot,
        },
        start_condition=ActionStartCondition.wait_for_all,
    )

    apm.add(
        PAL_server,
        "archive_tray_export_csv",
        {
            "tray": tray,
            "slot": slot,
        },
        start_condition=ActionStartCondition.wait_for_all,
    )

    apm.add(
        PAL_server,
        "archive_tray_export_icpms",
        {
            "tray": tray,
            "slot": slot,
            "survey_runs": survey_runs,
            "main_runs": main_runs,
            "rack": rack,
        },
        start_condition=ActionStartCondition.wait_for_all,
    )

    apm.add(
        PAL_server,
        "archive_tray_unload",
        {
            "tray": tray,
            "slot": slot,
        },
        start_condition=ActionStartCondition.wait_for_all,
    )

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def ADSS_sub_tray_icpms_export(
    tray: int = 2,
    slot: int = 1,
    survey_runs: int = 1,
    main_runs: int = 3,
    rack: int = 2,
    dilution_factor: float = 10,
) -> list:
    """Export a single PAL tray to ICPMS without unloading it.

    Args:
        experiment: Orchestrator-provided experiment context.
        tray: PAL tray index.
        slot: PAL slot index.
        survey_runs: ICPMS rough sweep count.
        main_runs: ICPMS centered sweeps count.
        rack: ICPMS rack position.
        dilution_factor: Sample dilution factor.

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    apm.add(
        PAL_server,
        "archive_tray_export_icpms",
        {
            "tray": tray,
            "slot": slot,
            "survey_runs": survey_runs,
            "main_runs": main_runs,
            "rack": rack,
            "dilution_factor": dilution_factor,
        },
    )

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def ADSS_sub_z_move(
    offset_z_mm: float = -8.0,
) -> list:
    """Move the motor Z axis by a relative offset (platexy transformation).

    Args:
        experiment: Orchestrator-provided experiment context.
        offset_z_mm: Relative Z displacement (mm).

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # move to position
    apm.add(
        MOTOR_server,
        "move",
        {
            "d_mm": [0, 0, offset_z_mm],
            "axis": ["x", "y", "z"],
            "mode": MoveModes.relative,
            "transformation": TransformationModes.platexy,
        },
        #            "from_global_act_params": {"_platexy": "d_mm"},
        start_condition=ActionStartCondition.wait_for_all,
    )

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def ADSS_sub_rel_move(
    offset_x_mm: float = 1.0,
    offset_y_mm: float = 1.0,
    offset_z_mm: float = 0.0,
) -> list:
    """Move the motor X/Y/Z axes by relative offsets (platexy transformation).

    Args:
        experiment: Orchestrator-provided experiment context.
        offset_x_mm: Relative X displacement (mm).
        offset_y_mm: Relative Y displacement (mm).
        offset_z_mm: Relative Z displacement (mm).

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # move to position
    apm.add(
        MOTOR_server,
        "move",
        {
            "d_mm": [offset_x_mm, offset_y_mm, offset_z_mm],
            "axis": ["x", "y", "z"],
            "mode": MoveModes.relative,
            "transformation": TransformationModes.platexy,
        },
        #            "from_global_act_params": {"_platexy": "d_mm"},
        start_condition=ActionStartCondition.wait_for_all,
    )

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def ADSS_sub_abs_move(
    x_mm: float = 80.0,
    y_mm: float = 50.0,
    #    offset_z_mm: float = 0.0,
) -> list:
    """Lift Z to load and move X/Y to an absolute position (platexy frame).

    Args:
        experiment: Orchestrator-provided experiment context.
        x_mm: Absolute X position (mm).
        y_mm: Absolute Y position (mm).

    Returns:
        List of planned actions for the orchestrator.
    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    apm.add(MOTOR_server, "z_move", {"z_position": "load"})
    # move to position
    apm.add(
        MOTOR_server,
        "move",
        {
            "d_mm": [x_mm, y_mm],
            "axis": ["x", "y"],
            "mode": MoveModes.absolute,
            "transformation": TransformationModes.platexy,
        },
        #            "from_global_act_params": {"_platexy": "d_mm"},
        start_condition=ActionStartCondition.wait_for_all,
    )

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def ADSS_sub_heat(
    duration_hrs: float = 2.0,
    celltemp_min_C: float = 74.5,
    celltemp_max_C: float = 75.5,
    reservoir2_min_C: float = 84.5,
    reservoir2_max_C: float = 85.5,
) -> list:
    """Start the NI monitoring loop and a temperature-control heat loop.

    Args:
        experiment: Orchestrator-provided experiment context.
        duration_hrs: Heat-loop duration (hours).
        celltemp_min_C: Cell low-temperature setpoint (deg C).
        celltemp_max_C: Cell high-temperature setpoint (deg C).
        reservoir2_min_C: Reservoir 2 low-temperature setpoint (deg C).
        reservoir2_max_C: Reservoir 2 high-temperature setpoint (deg C).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    apm.add(
        NI_server,
        "monloop",
        {},
    )
    apm.add(
        NI_server,
        "heatloop",
        {
            "duration_hrs": duration_hrs,
            "celltemp_min_C": celltemp_min_C,
            "celltemp_max_C": celltemp_max_C,
            "reservoir2_min_C": reservoir2_min_C,
            "reservoir2_max_C": reservoir2_max_C,
        },
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        process_finish=False,
        process_contrib=[
            ProcessContrib.files,
        ],
    )
    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def ADSS_sub_stopheat(
) -> list:
    """Stop the heat loop and the monitoring loop.

    Args:
        experiment: Orchestrator-provided experiment context.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    apm.add(
        NI_server,
        "heatloopstop",
        {},
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
    )
    apm.add(
        NI_server,
        "monloopstop",
        {},
    )
    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def ADSS_sub_cellfill_prefilled_nosampleload(
    Solution_volume_ul: float = 3000,
    Syringe_rate_ulsec: float = 300,
    #    deadvolume_ul: int = 0,
    #    PurgeWait_s: float = 2,
    ReturnLineWait_s: float = 0,
) -> list:
    """Infuse the work syringe into a prefilled cell without querying the sample.

    Closes the gas inlet, infuses, and optionally runs the peristaltic pump
    forward for ``ReturnLineWait_s`` seconds to clear the return line.

    Args:
        experiment: Orchestrator-provided experiment context.
        Solution_volume_ul: Volume to infuse (uL).
        Syringe_rate_ulsec: Syringe infuse rate (uL/s).
        ReturnLineWait_s: Optional pump-forward time after infusion (s).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()

    apm.add(
        NI_server,
        "gasvalve",
        {"gasvalve": "inlet", "on": 0},
        start_condition=ActionStartCondition.wait_for_orch,
    )
    # apm.add(NI_server, "liquidvalve", {"liquidvalve": "work_refill", "on": 1})
    # apm.add(
    #     WORKSYRINGE_server,
    #     "withdraw",
    #     {
    #         "rate_uL_sec": Syringe_rate_ulsec,
    #         "volume_uL": Solution_volume_ul,
    #     },
    # )
    # apm.add(NI_server, "liquidvalve", {"liquidvalve": "work_refill", "on": 0})
    apm.add(
        WORKSYRINGE_server,
        "infuse",
        {
            "rate_uL_sec": Syringe_rate_ulsec,
            "volume_uL": Solution_volume_ul,
        },
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        technique_name="cell_fill",
        process_finish=True,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.samples_in,
        ],
        start_condition=ActionStartCondition.wait_for_orch,
    )
    if ReturnLineWait_s != 0:
        apm.add(
            NI_server,
            "pump",
            {"pump": "direction", "on": 0},
            start_condition=ActionStartCondition.wait_for_previous,
        )
        apm.add(
            NI_server,
            "pump",
            {"pump": "peripump", "on": 1},
            start_condition=ActionStartCondition.wait_for_previous,
        )
        apm.add(
            ORCH_server,
            "wait",
            {"waittime": ReturnLineWait_s},
            start_condition=ActionStartCondition.wait_for_previous,
        )
        apm.add(
            NI_server,
            "pump",
            {"pump": "peripump", "on": 0},
            start_condition=ActionStartCondition.wait_for_previous,
        )

    #    apm.add(NI_server, "gasvalve", {"gasvalve": "inlet", "on": 1})

    return apm.planned_actions


@experiment(version=1)
def ADSS_sub_cellfill_prefilled(
    Solution_volume_ul: float = 3000,
    Syringe_rate_ulsec: float = 300,
    #    deadvolume_ul: int = 0,
    #    PurgeWait_s: float = 2,
    ReturnLineWait_s: float = 0,
) -> list:
    """Query the cell sample, close gas inlet, infuse the work syringe, run return-line pump.

    Args:
        experiment: Orchestrator-provided experiment context.
        Solution_volume_ul: Volume to infuse (uL).
        Syringe_rate_ulsec: Syringe infuse rate (uL/s).
        ReturnLineWait_s: Optional pump-forward time after infusion (s).

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
        ],  # save new liquid_sample_no of eche cell to globals,
        start_condition=ActionStartCondition.no_wait,
    )
    apm.add(
        NI_server,
        "gasvalve",
        {"gasvalve": "inlet", "on": 0},
        start_condition=ActionStartCondition.wait_for_orch,
    )
    # apm.add(NI_server, "liquidvalve", {"liquidvalve": "work_refill", "on": 1})
    # apm.add(
    #     WORKSYRINGE_server,
    #     "withdraw",
    #     {
    #         "rate_uL_sec": Syringe_rate_ulsec,
    #         "volume_uL": Solution_volume_ul,
    #     },
    # )
    # apm.add(NI_server, "liquidvalve", {"liquidvalve": "work_refill", "on": 0})
    apm.add(
        WORKSYRINGE_server,
        "infuse",
        {
            "rate_uL_sec": Syringe_rate_ulsec,
            "volume_uL": Solution_volume_ul,
        },
        from_global_act_params={"_fast_samples_in": "fast_samples_in"},
        technique_name="cell_fill",
        process_finish=True,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.samples_in,
        ],
        start_condition=ActionStartCondition.wait_for_orch,
    )
    if ReturnLineWait_s != 0:
        apm.add(
            NI_server,
            "pump",
            {"pump": "direction", "on": 0},
            start_condition=ActionStartCondition.wait_for_previous,
        )
        apm.add(
            NI_server,
            "pump",
            {"pump": "peripump", "on": 1},
            start_condition=ActionStartCondition.wait_for_previous,
        )
        apm.add(
            ORCH_server,
            "wait",
            {"waittime": ReturnLineWait_s},
            start_condition=ActionStartCondition.wait_for_previous,
        )
        apm.add(
            NI_server,
            "pump",
            {"pump": "peripump", "on": 0},
            start_condition=ActionStartCondition.wait_for_previous,
        )

    #    apm.add(NI_server, "gasvalve", {"gasvalve": "inlet", "on": 1})

    return apm.planned_actions


@experiment(version=1)
def ADSS_sub_cellfill_flush(
    Solution_volume_ul: float = 3000,
    Syringe_rate_ulsec: float = 300,
    #    deadvolume_ul: int = 0,
    #    PurgeWait_s: float = 2,
    ReturnLineWait_s: float = 0,
) -> list:
    """Close gas inlet, infuse the work syringe (no process tagging), run return-line pump.

    Args:
        experiment: Orchestrator-provided experiment context.
        Solution_volume_ul: Volume to infuse (uL).
        Syringe_rate_ulsec: Syringe infuse rate (uL/s).
        ReturnLineWait_s: Optional pump-forward time after infusion (s).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    apm.add(NI_server, "gasvalve", {"gasvalve": "inlet", "on": 0})
    # apm.add(NI_server, "liquidvalve", {"liquidvalve": "work_refill", "on": 1})
    # apm.add(
    #     WORKSYRINGE_server,
    #     "withdraw",
    #     {
    #         "rate_uL_sec": Syringe_rate_ulsec,
    #         "volume_uL": Solution_volume_ul,
    #     },
    # )
    # apm.add(NI_server, "liquidvalve", {"liquidvalve": "work_refill", "on": 0})
    apm.add(
        WORKSYRINGE_server,
        "infuse",
        {
            "rate_uL_sec": Syringe_rate_ulsec,
            "volume_uL": Solution_volume_ul,
        },
    )
    if ReturnLineWait_s != 0:
        apm.add(NI_server, "pump", {"pump": "direction", "on": 0})
        apm.add(NI_server, "pump", {"pump": "peripump", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": ReturnLineWait_s})
        apm.add(NI_server, "pump", {"pump": "peripump", "on": 0})

    #    apm.add(NI_server, "gasvalve", {"gasvalve": "inlet", "on": 1})

    return apm.planned_actions


@experiment(version=3)
def ADSS_sub_drain_cell(
    DrainWait_s: float = 60,
    ReturnLineReverseWait_s: float = 5,
    #    ResidualWait_s: float = 15,
) -> list:
    """Drain the cell: reverse the return line, switch to drain valve, gas purge.

    Args:
        experiment: Orchestrator-provided experiment context.
        DrainWait_s: Total drain time, split before/after gas inlet purge (s).
        ReturnLineReverseWait_s: Time to run the pump in reverse to clear the
            return line (s).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "inlet", "on": 0})
    apm.add(NI_server, "pump", {"pump": "direction", "on": 1})
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 1})  # clearing return line
    apm.add(ORCH_server, "wait", {"waittime": ReturnLineReverseWait_s})
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "pump_drain", "on": 1})
    apm.add(NI_server, "pump", {"pump": "direction", "on": 0})
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 1})  # draining reservoir
    apm.add(ORCH_server, "wait", {"waittime": DrainWait_s / 2})
    apm.add(NI_server, "gasvalve", {"gasvalve": "inlet", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": DrainWait_s / 2})
    apm.add(NI_server, "gasvalve", {"gasvalve": "inlet", "on": 0})
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 0})
    #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "water_refill", "on": 1})
    #    apm.add(NI_server, "pump", {"pump": "peripump", "on": 1})  # draining cell
    #    apm.add(ORCH_server, "wait", {"waittime": ResidualWait_s})
    #    apm.add(NI_server, "pump", {"pump": "peripump", "on": 0})
    apm.add(NI_server, "liquidvalve", {"liquidvalve": "pump_drain", "on": 0})
    #    apm.add(NI_server, "liquidvalve", {"liquidvalve": "water_refill", "on": 0})

    return apm.planned_actions


@experiment(version=1)
def ADSS_sub_keep_electrolyte(
    ReturnLineReverseWait_s: float = 5,
    #    ResidualWait_s: float = 15,
) -> list:
    """Reverse the return line briefly then interrupt to save electrolyte in reservoir.

    Args:
        experiment: Orchestrator-provided experiment context.
        ReturnLineReverseWait_s: Reverse-pump duration (s).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "inlet", "on": 0})
    apm.add(NI_server, "pump", {"pump": "direction", "on": 1})
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 1})  # clearing return line
    apm.add(ORCH_server, "wait", {"waittime": ReturnLineReverseWait_s})
    apm.add(ORCH_server, "interrupt", {"reason": "Save electrolyte in reservoir."})
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 0})
    apm.add(NI_server, "pump", {"pump": "direction", "on": 0})

    return apm.planned_actions


# def ADSS_sub_empty_cell(
#     experiment: Experiment,
#     experiment_version: int = 1,
#     ReversePurgeWait_s: float = 20,
# ):

#     apm = ActionPlanMaker()
#     apm.add(NI_server, "gasvalve", {"gasvalve": "inlet", "on": 0})
#     apm.add(NI_server, "pump", {"pump": "peripump", "on": 0})
#     apm.add(NI_server, "pump", {"pump": "direction", "on": 1})
#     apm.add(NI_server, "pump", {"pump": "peripump", "on": 1})
#     apm.add(ORCH_server, "wait", {"waittime": ReversePurgeWait_s})
#     apm.add(NI_server, "pump", {"pump": "peripump", "on": 0})

#     return apm.planned_actions


# need to move to clean spot first before beginning clean
@experiment(version=3)
def ADSS_sub_clean_cell(
    Clean_volume_ul: float = 3000,
    Syringe_rate_ulsec: float = 300,
    PurgeWait_s: float = 3,
    ReturnLineWait_s: float = 30,
    DrainWait_s: float = 60,
    ReturnLineReverseWait_s: float = 5,
    lift: bool = False,
    #    ResidualWait_s: float = 15,
) -> list:
    """Run a clean-water flush through the cell followed by a drain.

    If ``Clean_volume_ul`` exceeds 10000 uL the cycle is split into two
    infuse/drain passes. Optionally lifts Z to load at the end.

    Args:
        experiment: Orchestrator-provided experiment context.
        Clean_volume_ul: Total clean-syringe volume (uL).
        Syringe_rate_ulsec: Clean syringe infuse rate (uL/s).
        PurgeWait_s: Gas purge wait between infuse and drain (s).
        ReturnLineWait_s: Pump-forward time to clear the return line (s).
        DrainWait_s: Drain duration forwarded to ``ADSS_sub_drain_cell`` (s).
        ReturnLineReverseWait_s: Reverse pump time during drain (s).
        lift: Lift Z to load after cleaning when True.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()

    apm.add(NI_server, "gasvalve", {"gasvalve": "inlet", "on": 0})
    if Clean_volume_ul > 10000:
        apm.add(
            CLEANSYRINGE_server,
            "infuse",
            {
                "rate_uL_sec": Syringe_rate_ulsec,
                "volume_uL": 6000,
            },
        )
        apm.add(ORCH_server, "wait", {"waittime": 10})
        apm.add(NI_server, "gasvalve", {"gasvalve": "inlet", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": PurgeWait_s})
        apm.add(NI_server, "gasvalve", {"gasvalve": "inlet", "on": 0})

        apm.add(NI_server, "pump", {"pump": "direction", "on": 0})
        apm.add(NI_server, "pump", {"pump": "peripump", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": ReturnLineWait_s})
        apm.add(NI_server, "pump", {"pump": "peripump", "on": 0})

        apm.add_actions(
            ADSS_sub_drain_cell(
                DrainWait_s=40,
                ReturnLineReverseWait_s=ReturnLineReverseWait_s,
                # ResidualWait_s=ResidualWait_s,
            )
        )

    apm.add(
        CLEANSYRINGE_server,
        "infuse",
        {
            "rate_uL_sec": Syringe_rate_ulsec,
            "volume_uL": Clean_volume_ul,
        },
    )
    apm.add(ORCH_server, "wait", {"waittime": 10})
    if Clean_volume_ul < 7000:
        apm.add(NI_server, "gasvalve", {"gasvalve": "inlet", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": PurgeWait_s})
        apm.add(NI_server, "gasvalve", {"gasvalve": "inlet", "on": 0})

    apm.add(NI_server, "pump", {"pump": "direction", "on": 0})
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": ReturnLineWait_s})
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 0})

    apm.add_actions(
        ADSS_sub_drain_cell(
            DrainWait_s=DrainWait_s,
            ReturnLineReverseWait_s=ReturnLineReverseWait_s,
            # ResidualWait_s=ResidualWait_s,
        )
    )
    if lift:
        apm.add(MOTOR_server, "z_move", {"z_position": "load"})

    return apm.planned_actions


@experiment(version=1)
def ADSS_sub_move_to_clean_cell(
) -> list:
    """Lift Z, query the built-in clean-cell reference XY, move there, then seal.

    Args:
        experiment: Orchestrator-provided experiment context.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    apm.add(MOTOR_server, "z_move", {"z_position": "load"})
    apm.add(
        MOTOR_server,
        "solid_get_builtin_specref",
        {"ref_name": "builtin_ref_motorxy"},
        to_global_params=["_refxy"],
    )
    apm.add(
        MOTOR_server,
        "move",
        {
            "axis": ["x", "y"],
            "mode": MoveModes.absolute,
            "transformation": TransformationModes.platexy,
        },
        from_global_act_params={"_refxy": "d_mm"},
    )

    apm.add(MOTOR_server, "z_move", {"z_position": "seal"})

    return apm.planned_actions


@experiment(version=1)
def ADSS_sub_move_to_ref_measurement(
    reference_position_name: str = "builtin_ref_motorxy_2",
) -> list:
    """Move to a named built-in reference position and seal the cell.

    Uses the platexy transformation when ``reference_position_name`` is
    ``"builtin_ref_motorxy"``; otherwise uses the motorxy transformation.

    Args:
        experiment: Orchestrator-provided experiment context.
        reference_position_name: Name of the builtin specref position.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    apm.add(MOTOR_server, "z_move", {"z_position": "load"})
    apm.add(
        MOTOR_server,
        "solid_get_builtin_specref",
        {"ref_position_name": reference_position_name},
        to_global_params=["_refxy"],
    )
    if (
        reference_position_name == "builtin_ref_motorxy"
    ):  # if using clean cell position with this experiment, then use platexy. otherwise motorxy
        apm.add(
            MOTOR_server,
            "move",
            {
                "axis": ["x", "y"],
                "mode": MoveModes.absolute,
                "transformation": TransformationModes.platexy,
            },
            from_global_act_params={"_refxy": "d_mm"},
        )
    else:
        apm.add(
            MOTOR_server,
            "move",
            {
                "axis": ["x", "y"],
                "mode": MoveModes.absolute,
                "transformation": TransformationModes.motorxy,
            },
            from_global_act_params={"_refxy": "d_mm"},
        )
    apm.add(MOTOR_server, "z_move", {"z_position": "seal"})

    return apm.planned_actions


# def ADSS_sub_refill_syringes(
#     experiment: Experiment,
#     experiment_version: int = 1,
#     Solution_volume_ul: float = 0,
#     Waterclean_volume_ul: float = 5000,
#     Syringe_rate_ulsec: float = 300,
# ):
#     apm = ActionPlanMaker()
#     if Solution_volume_ul != 0:
#         apm.add(NI_server, "liquidvalve", {"liquidvalve": "work_refill", "on": 1})
#         apm.add(ORCH_server, "wait", {"waittime": 0.25})
#         apm.add(
#             WORKSYRINGE_server,
#             "withdraw",
#             {
#                 "rate_uL_sec": Syringe_rate_ulsec,
#                 "volume_uL": Solution_volume_ul + 25,
#             },
#         )
#         apm.add(
#             WORKSYRINGE_server,
#             "infuse",
#             {"rate_uL_sec": Syringe_rate_ulsec, "volume_uL": 25},
#         )
#         apm.add(ORCH_server, "wait", {"waittime": 40})
#         apm.add(NI_server, "liquidvalve", {"liquidvalve": "work_refill", "on": 0})

#     if Waterclean_volume_ul != 0:
#         apm.add(NI_server, "liquidvalve", {"liquidvalve": "clean_refill", "on": 1})
#         apm.add(ORCH_server, "wait", {"waittime": 0.25})
#         apm.add(
#             CLEANSYRINGE_server,
#             "withdraw",
#             {
#                 "rate_uL_sec": Syringe_rate_ulsec,
#                 "volume_uL": Waterclean_volume_ul + 25,
#             },
#         )
#         apm.add(
#             CLEANSYRINGE_server,
#             "infuse",
#             {"rate_uL_sec": Syringe_rate_ulsec, "volume_uL": 25},
#         )
#         apm.add(ORCH_server, "wait", {"waittime": 10})
#         apm.add(NI_server, "liquidvalve", {"liquidvalve": "clean_refill", "on": 0})

#     return apm.planned_actions


@experiment(version=4)
def ADSS_sub_sample_aliquot(
    aliquot_volume_ul: int = 200,
    EquilibrationTime_s: float = 30,
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "fill serial number here",
    rinse_1: int = 1,
    rinse_2: int = 0,
    rinse_3: int = 0,
    rinse_4: int = 0,
) -> list:
    """Take a single PAL aliquot from ``cell1_we`` with pump equilibration and washes.

    Queries the cell sample, closes the gas inlet, runs the peristaltic pump
    forward to equilibrate, dispatches ``PAL_archive``, and re-opens the gas
    inlet.

    Args:
        experiment: Orchestrator-provided experiment context.
        aliquot_volume_ul: Aliquot volume (uL).
        EquilibrationTime_s: Pump equilibration time before sampling (s).
        PAL_Injector: PAL injector tool identifier.
        PAL_Injector_id: PAL injector serial-number string.
        rinse_1: PAL wash slot 1 count.
        rinse_2: PAL wash slot 2 count.
        rinse_3: PAL wash slot 3 count.
        rinse_4: PAL wash slot 4 count.

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
    apm.add(NI_server, "gasvalve", {"gasvalve": "inlet", "on": 0})
    apm.add(NI_server, "pump", {"pump": "direction", "on": 0})
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": EquilibrationTime_s})
    apm.add(
        PAL_server,
        "PAL_archive",
        {
            "tool": PAL_Injector,
            "source": "cell1_we",
            "volume_ul": aliquot_volume_ul,
            "sampleperiod": [0.0],
            "spacingmethod": Spacingmethod.custom,
            "spacingfactor": 1.0,
            "timeoffset": 0.0,
            "wash1": rinse_1,
            "wash2": rinse_2,
            "wash3": rinse_3,
            "wash4": rinse_4,
        },
        start_condition=ActionStartCondition.wait_for_orch,
        technique_name="liquid_product_archive",
        process_finish=True,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
            ProcessContrib.run_use,
        ],
    )
    apm.add(NI_server, "gasvalve", {"gasvalve": "inlet", "on": 1})

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=2)
def ADSS_sub_recirculate(
    direction_forward_or_reverse: str = "forward",
    wait_time_s: float = 10,
) -> list:
    """Open the gas inlet and run the peristaltic pump for a fixed duration.

    Args:
        experiment: Orchestrator-provided experiment context.
        direction_forward_or_reverse: ``"forward"`` (0) or any other value (1).
        wait_time_s: Recirculation duration (s).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    if direction_forward_or_reverse == "forward":
        dir = 0
    else:
        dir = 1
    apm.add(NI_server, "gasvalve", {"gasvalve": "inlet", "on": 1})
    apm.add(NI_server, "pump", {"pump": "direction", "on": dir})
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": wait_time_s})
    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def ADSS_sub_cell_illumination(
    led_wavelength: str = "385",
    illumination_on: bool = False,
) -> list:
    """Turn the NI LED on or off and tag the action with a process technique.

    Args:
        experiment: Orchestrator-provided experiment context.
        led_wavelength: Informational wavelength label.
        illumination_on: Set the LED on when True, off otherwise.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    if illumination_on:
        apm.add(
            NI_server,
            "led",
            {"led": "led", "on": 1},
            technique_name="led_on",
            process_finish=True,
            process_contrib=[
                ProcessContrib.action_params,
            ],
        )
    else:
        apm.add(
            NI_server,
            "led",
            {"led": "led", "on": 0},
            technique_name="led_off",
            process_finish=True,
            process_contrib=[
                ProcessContrib.action_params,
            ],
        )

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def ADSS_sub_interrupt(
    reason: str = "wait",
) -> list:
    """Emit a single orchestrator interrupt action with the given reason.

    Args:
        experiment: Orchestrator-provided experiment context.
        reason: Human-readable reason string for the interrupt.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    apm.add(ORCH_server, "interrupt", {"reason": reason})
    return apm.planned_actions


@experiment(version=1)
def ADSS_sub_refill_syringe(
    syringe: str = "waterclean",
    fill_volume_ul: float = 0,
    Syringe_rate_ulsec: float = 1000,
) -> list:
    """Refill the clean or electrolyte (work) syringe via its refill liquid valve.

    Args:
        experiment: Orchestrator-provided experiment context.
        syringe: ``"waterclean"`` for the clean syringe or ``"electrolyte"``
            for the work syringe; other values produce no actions.
        fill_volume_ul: Withdraw volume (uL).
        Syringe_rate_ulsec: Withdraw rate (uL/s).

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    if syringe == "waterclean":
        apm.add(NI_server, "liquidvalve", {"liquidvalve": "clean_refill", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": 0.25})
        apm.add(
            CLEANSYRINGE_server,
            "withdraw",
            {
                "rate_uL_sec": Syringe_rate_ulsec,
                "volume_uL": fill_volume_ul,
            },
        )
        apm.add(ORCH_server, "wait", {"waittime": 10})
        apm.add(NI_server, "liquidvalve", {"liquidvalve": "clean_refill", "on": 0})

    if syringe == "electrolyte":
        # need valve for this soln
        apm.add(NI_server, "liquidvalve", {"liquidvalve": "work_refill", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": 0.25})
        apm.add(
            WORKSYRINGE_server,
            "withdraw",
            {
                "rate_uL_sec": Syringe_rate_ulsec,
                "volume_uL": fill_volume_ul,
            },
        )
        apm.add(ORCH_server, "wait", {"waittime": 10})
        apm.add(NI_server, "liquidvalve", {"liquidvalve": "work_refill", "on": 0})

    return apm.planned_actions


@experiment(version=1)
def ADSS_sub_gasvalve_toggle(
    open: bool = True,
) -> list:
    """Toggle the gas-inlet valve open or closed.

    Args:
        experiment: Orchestrator-provided experiment context.
        open: True to open, False to close.

    Returns:
        List of planned actions for the orchestrator.
    """
    # true for N2 flow
    apm = ActionPlanMaker()
    apm.add(NI_server, "gasvalve", {"gasvalve": "inlet", "on": open})

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def ADSS_sub_gasvalve_N2flow(
    open: bool = True,
) -> list:
    """Toggle the O2/N2 selector valve (True selects N2 flow).

    Args:
        experiment: Orchestrator-provided experiment context.
        open: True selects N2, False selects O2.

    Returns:
        List of planned actions for the orchestrator.
    """
    # true for N2 flow
    apm = ActionPlanMaker()
    apm.add(NI_server, "gasvalve", {"gasvalve": "O2N2toggle", "on": open})

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def ADSS_sub_transfer_liquid_in(
    liquid_sample_no: int = 1,
    aliquot_volume_ul: int = 200,
    source_tray: int = 2,
    source_slot: int = 2,
    source_vial: int = 54,
    destination: str = "cell1_we",
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "fill serial number here",
    rinse_1: int = 1,
    rinse_2: int = 0,
    rinse_3: int = 0,
    rinse_4: int = 0,
) -> list:
    """Archive an added liquid then PAL-transfer it from a tray vial to a cell.

    Args:
        experiment: Orchestrator-provided experiment context.
        liquid_sample_no: Liquid sample number to register in the archive.
        aliquot_volume_ul: Transfer volume (uL).
        source_tray: PAL source tray index.
        source_slot: PAL source slot index.
        source_vial: PAL source vial index.
        destination: PAL destination custom position.
        PAL_Injector: PAL injector tool identifier.
        PAL_Injector_id: PAL injector serial-number string.
        rinse_1: PAL wash slot 1 count.
        rinse_2: PAL wash slot 2 count.
        rinse_3: PAL wash slot 3 count.
        rinse_4: PAL wash slot 4 count.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    apm.add(
        PAL_server,
        "archive_custom_add_liquid",
        {
            "custom": destination,
            "source_liquid_in": LiquidSample(
                **{
                    "sample_no": liquid_sample_no,
                    "machine_name": gethostname(),
                }
            ).model_dump(),
            "volume_ml": aliquot_volume_ul / 1000,
            "combine_liquids": True,
            "dilute_liquids": False,
        },
        technique_name="liquid_addition",
        process_finish=True,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )

    apm.add(
        PAL_server,
        "PAL_transfer_tray_custom",
        {
            "volume_ul": aliquot_volume_ul,
            "source_tray": source_tray,
            "source_slot": source_slot,
            "source_vial": source_vial,
            "dest": destination,
            "tool": PAL_Injector,
            "wash1": rinse_1,
            "wash2": rinse_2,
            "wash3": rinse_3,
            "wash4": rinse_4,
        },
    )

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def ADSS_sub_remove_bubble(
    pump_reverse_time_s: float = 15,
    pump_forward_time_s: float = 10,
    Tval__s: float = 10.0,
    gamry_i_range: str = "auto",
    samplerate_sec: float = 0.1,
    ph: float = 1.24,
    ref_type: str = "inhouse",
    ref_offset__V: float = -0.01,
    check_bubble: bool = True,
    RSD_threshold: float = 0.2,
    simple_threshold: float = 0.3,
    signal_change_threshold: float = 0.01,
    amplitude_threshold: float = 0.05,
    bubble_pump_reverse_time_s: float = 15,
    bubble_pump_forward_time_s: float = 10,
    run_use: RunUse = RunUse.data,
) -> list:
    """Reverse-then-forward the pump to dislodge a bubble, then re-check via OCV.

    Args:
        experiment: Orchestrator-provided experiment context.
        pump_reverse_time_s: Reverse-pump duration (s).
        pump_forward_time_s: Forward-pump duration after reverse (s).
        Tval__s: Duration of the follow-up OCV (s).
        gamry_i_range: Gamry current-range setting.
        samplerate_sec: Acquisition interval (s).
        ph: Solution pH.
        ref_type: Reference electrode key into ``REF_TABLE``.
        ref_offset__V: Calibration offset of the reference electrode (V).
        check_bubble: Forwarded to follow-up OCV.
        RSD_threshold: Bubble-detection RSD threshold.
        simple_threshold: Bubble-detection simple threshold.
        signal_change_threshold: Bubble-detection signal-change threshold.
        amplitude_threshold: Bubble-detection amplitude threshold.
        bubble_pump_reverse_time_s: Reverse time used by the follow-up OCV (s).
        bubble_pump_forward_time_s: Forward time used by the follow-up OCV (s).
        run_use: ``RunUse`` tag forwarded to OCV.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 1})
    apm.add(NI_server, "pump", {"pump": "direction", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": pump_reverse_time_s})
    apm.add(NI_server, "pump", {"pump": "direction", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": pump_forward_time_s})
    apm.add_actions(
        ADSS_sub_OCV(
            Tval__s=Tval__s,
            gamry_i_range=gamry_i_range,
            samplerate_sec=samplerate_sec,
            ph=ph,
            ref_type=ref_type,
            ref_offset__V=ref_offset__V,
            check_bubble=check_bubble,
            RSD_threshold=RSD_threshold,
            simple_threshold=simple_threshold,
            signal_change_threshold=signal_change_threshold,
            amplitude_threshold=amplitude_threshold,
            bubble_pump_forward_time_s=bubble_pump_forward_time_s,
            bubble_pump_reverse_time_s=bubble_pump_reverse_time_s,
            run_use=run_use,
        )
    )
    return apm.planned_actions


@experiment(version=1)
def ADSS_sub_PAL_deep_clean(
    clean_volume_ul: int = 500,
    PAL_Injector: str = "LS 4",
    rinse_1: int = 1,
    rinse_2: int = 0,
    rinse_3: int = 0,
    rinse_4: int = 0,
) -> list:
    """Deep-clean the PAL injector with configurable wash counts.

    Args:
        experiment: Orchestrator-provided experiment context.
        clean_volume_ul: Cleaning volume per wash (uL).
        PAL_Injector: PAL injector tool identifier.
        rinse_1: PAL wash slot 1 count.
        rinse_2: PAL wash slot 2 count.
        rinse_3: PAL wash slot 3 count.
        rinse_4: PAL wash slot 4 count.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()

    apm.add(
        PAL_server,
        "PAL_deepclean",
        {
            "volume_ul": clean_volume_ul,
            "tool": PAL_Injector,
            "wash1": rinse_1,
            "wash2": rinse_2,
            "wash3": rinse_3,
            "wash4": rinse_4,
        },
    )

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def ADSS_sub_PAL_tray_to_tray(
    volume_ul: int = 500,
    source_tray: int = 2,
    source_slot: int = 2,
    source_vial: int = 53,
    dest_tray: int = 2,
    dest_slot: int = 2,
    dest_vial: int = 52,
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "fill serial number here",
    rinse_1: int = 1,
    rinse_2: int = 0,
    rinse_3: int = 0,
    rinse_4: int = 0,
) -> list:
    """Transfer liquid between two PAL tray vials.

    Args:
        experiment: Orchestrator-provided experiment context.
        volume_ul: Transfer volume (uL).
        source_tray: PAL source tray index.
        source_slot: PAL source slot index.
        source_vial: PAL source vial index.
        dest_tray: PAL destination tray index.
        dest_slot: PAL destination slot index.
        dest_vial: PAL destination vial index.
        PAL_Injector: PAL injector tool identifier.
        PAL_Injector_id: PAL injector serial-number string.
        rinse_1: PAL wash slot 1 count.
        rinse_2: PAL wash slot 2 count.
        rinse_3: PAL wash slot 3 count.
        rinse_4: PAL wash slot 4 count.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()

    apm.add(
        PAL_server,
        "PAL_transfer_tray_tray",
        {
            "volume_ul": volume_ul,
            "source_tray": source_tray,
            "source_slot": source_slot,
            "source_vial": source_vial,
            "dest_tray": dest_tray,
            "dest_slot": dest_slot,
            "dest_vial": dest_vial,
            "tool": PAL_Injector,
            "wash1": rinse_1,
            "wash2": rinse_2,
            "wash3": rinse_3,
            "wash4": rinse_4,
        },
    )

    return apm.planned_actions  # returns complete action list to orch


@experiment(version=1)
def ADSS_sub_PAL_export_icpms(
    tray: int = 2,
    slot: int = 1,
    survey_runs: int = 1,
    main_runs: int = 3,
    rack: int = 2,
    dilution_factor: float = 10,
) -> list:
    """Export a PAL tray slot to ICPMS without unloading it.

    Args:
        experiment: Orchestrator-provided experiment context.
        tray: PAL tray index.
        slot: PAL slot index.
        survey_runs: ICPMS rough sweep count.
        main_runs: ICPMS centered sweeps count.
        rack: ICPMS rack position.
        dilution_factor: Sample dilution factor.

    Returns:
        List of planned actions for the orchestrator.
    """
    apm = ActionPlanMaker()

    apm.add(
        PAL_server,
        "archive_tray_export_icpms",
        {
            "tray": tray,
            "slot": slot,
            "survey_runs": survey_runs,
            "main_runs": main_runs,
            "rack": rack,
            "dilution_factor": dilution_factor,
        },
    )

    return apm.planned_actions  # returns complete action list to orch
