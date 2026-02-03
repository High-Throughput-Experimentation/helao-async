""" Experiment library for Closed Loop Accelerated Durability (CLAD)
"""

__all__ = [
    "CLAD_sub_recirculate_alternating",
    "CLAD_sub_load_sample",
    "CLAD_sub_fill_cell",
    "CLAD_sub_setup_cell",
    "CLAD_sub_reference_setup",
    "CLAD_sub_OCV_bubble_check",
    "CLAD_sub_load_assembly",
]


from typing import Optional, List
from socket import gethostname

from helao.helpers.premodels import Experiment, ActionPlanMaker
from helao.core.models.action_start_condition import ActionStartCondition
from helao.core.models.sample import SolidSample, LiquidSample, GasSample
from helao.core.models.machine import MachineModel
from helao.core.models.process_contrib import ProcessContrib
from helao.helpers.ref_electrode import REF_TABLE

from helao.deploy.hte.drivers.motion.galil_motion_driver import (
    MoveModes,
    TransformationModes,
)
from helao.deploy.hte.drivers.robot.pal_driver import Spacingmethod, PALtools

from .ADSS_exp import (
    ADSS_sub_drain_cell,
    ADSS_sub_refill_syringe,
    ADSS_sub_OCV,
)

from helao.core.models.run_use import RunUse


EXPERIMENTS = __all__

ORCH_HOST = gethostname()
PSTAT_server = MachineModel(server_name="PSTAT", machine_name=ORCH_HOST).as_dict()
MOTOR_server = MachineModel(server_name="MOTOR", machine_name=ORCH_HOST).as_dict()
NI_server = MachineModel(server_name="NI", machine_name=ORCH_HOST).as_dict()
ORCH_server = MachineModel(server_name="ORCH", machine_name=ORCH_HOST).as_dict()
PAL_server = MachineModel(server_name="PAL", machine_name=ORCH_HOST).as_dict()
SOLUTIONPUMP_server = MachineModel(
    server_name="SYRINGE0", machine_name=ORCH_HOST
).as_dict()
WATERCLEANPUMP_server = MachineModel(
    server_name="SYRINGE1", machine_name=ORCH_HOST
).as_dict()


# cannot save data without exp
debug_save_act = True
debug_save_data = True


### CONSOLIDATED EXPERIMENTS FOR SIMPLIFIED SEQUENCES


def CLAD_sub_recirculate_alternating(
    experiment: Experiment,
    experiment_version: int = 1,
    forward_duration_s: float = 30.0,
    reverse_duration_s: float = 15.0,
    final_duration_s: float = 5.0,
):
    apm = ActionPlanMaker()

    # RECIRCULATE FORWARD
    apm.add(NI_server, "gasvalve", {"gasvalve": "V1", "on": 1})
    apm.add(NI_server, "pump", {"pump": "direction", "on": 0})
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": forward_duration_s})

    # RECIRCULATE REVERSE
    apm.add(NI_server, "gasvalve", {"gasvalve": "V1", "on": 1})
    apm.add(NI_server, "pump", {"pump": "direction", "on": 1})
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": reverse_duration_s})

    # RECIRCULATE FORWARD FINAL
    apm.add(NI_server, "gasvalve", {"gasvalve": "V1", "on": 1})
    apm.add(NI_server, "pump", {"pump": "direction", "on": 0})
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": final_duration_s})

    return apm.planned_actions


def CLAD_sub_load_sample(
    experiment: Experiment,
    experiment_version: int = 1,
    load_position: str = "cell1_we",
    clear_position: bool = True,
    solid_plate_id: Optional[int] = None,
    solid_sample_no: Optional[int] = None,
    liquid_sample_no: Optional[int] = None,
    liquid_volume_ul: Optional[float] = None,
    gas_sample_no: Optional[int] = None,
    gas_volume_ml: Optional[float] = None,
    bubbler_gas: Optional[str] = None,
):
    apm = ActionPlanMaker()

    if clear_position:
        apm.add(
            PAL_server,
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
            PAL_server,
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
            PAL_server,
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
            PAL_server,
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


def CLAD_sub_fill_cell(
    experiment: Experiment,
    experiment_version: int = 1,
    fill_volume_ul: float = 3000,
    fill_rate_ul_s: float = 300,
    load_sample: bool = False,
):
    apm = ActionPlanMaker()

    if load_sample:
        apm.add(
            PAL_server,
            "archive_custom_query_sample",
            {
                "custom": "cell1_we",
            },
            to_global_params={"_fast_samples_in": "_fast_samples_in"},
            # save new liquid_sample_no of eche cell to globals,
            start_condition=ActionStartCondition.no_wait,
        )

    apm.add(
        NI_server,
        "gasvalve",
        {"gasvalve": "V1", "on": 0},
        start_condition=ActionStartCondition.wait_for_orch,
    )
    apm.add(
        SOLUTIONPUMP_server,
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


# 1. CLEAN CELL
def CLAD_sub_setup_cell(
    experiment: Experiment,
    experiment_version: int = 1,
    rinse_recirc_duration_s: float = 30.0,
    rinse_volume_ul: float = 3000.0,
    fill_rate_ul_s: float = 300.0,
    drain_wait_duration_s: float = 30.0,
):
    apm = ActionPlanMaker()

    # MOVE TO CELL RINSE POSITION
    apm.add(MOTOR_server, "z_move", {"z_position": "load"})
    apm.add(
        MOTOR_server,
        "solid_get_builtin_specref",
        {"ref_name": "builtin_ref_motorxy"},
        to_global_params={"_refxy": "_refxy"},
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

    # FILL CELL WITHOUT SAMPLE LOAD
    apm.add_actions(
        CLAD_sub_fill_cell(
            experiment=experiment,
            fill_volume_ul=rinse_volume_ul,
            fill_rate_ul_s=fill_rate_ul_s,
            load_sample=False,
        )
    )

    # RECIRCULATE RINSE SOLUTION FORWARD DIRECTION
    apm.add(NI_server, "gasvalve", {"gasvalve": "V1", "on": 1})
    apm.add(NI_server, "pump", {"pump": "direction", "on": 0})
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": rinse_recirc_duration_s})

    # DRAIN CELL
    apm.add_actions(
        ADSS_sub_drain_cell(
            experiment=experiment,
            DrainWait_s=drain_wait_duration_s,
            ReturnLineReverseWait_s=5.0,
        )
    )

    # REFILL SYRINGE
    apm.add(NI_server, "gasvalve", {"gasvalve": "V3", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": 0.25})
    apm.add(
        SOLUTIONPUMP_server,
        "withdraw",
        {
            "rate_uL_sec": fill_rate_ul_s,
            "volume_uL": rinse_volume_ul,
        },
    )
    apm.add(ORCH_server, "wait", {"waittime": 10})
    apm.add(NI_server, "gasvalve", {"gasvalve": "V3", "on": 0})

    return apm.planned_actions


# 2. REFERENCE MEASUREMENT
def CLAD_sub_reference_setup(
    experiment: Experiment,
    experiment_version: int = 1,
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
):
    apm = ActionPlanMaker()

    # MOVE TO REFERENCE POSITION
    apm.add(MOTOR_server, "z_move", {"z_position": "load"})
    apm.add(
        MOTOR_server,
        "solid_get_builtin_specref",
        {"ref_position_name": reference_position_name},
        to_global_params={"_refxy": "_refxy"},
    )
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

    # LOAD REFERENCE SAMPLE
    apm.add(
        PAL_server,
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
        PAL_server,
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
        PAL_server,
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
            experiment=experiment,
            fill_volume_ul=fill_volume_ul,
            fill_rate_ul_s=fill_rate_ul_s,
            load_sample=True,
        )
    )

    # FLOW O2
    apm.add(NI_server, "gasvalve", {"gasvalve": "O2N2toggle", "on": False})

    # RECIRCULATE
    apm.add_actions(
        CLAD_sub_recirculate_alternating(
            experiment=experiment,
            forward_duration_s=fill_recirc_fwd_duration_s,
            reverse_duration_s=fill_recirc_rev_duration_s,
            final_duration_s=5.0,
        )
    )

    # REFILL SYRINGE
    apm.add_actions(
        ADSS_sub_refill_syringe(
            experiment=experiment,
            syringe="electrolyte",
            fill_volume_ul=fill_volume_ul,
            Syringe_rate_ulsec=300.0,
        )
    )

    return apm.planned_actions


def CLAD_sub_OCV_bubble_check(
    experiment: Experiment,
    experiment_version: int = 1,
    ocv_duration_s: float = 30.0,
    ocv_sample_rate_s: float = 0.1,
    electrolyte_ph: float = 1.0,
    reference_offset_V: float = 0.0,
    gamry_i_range: str = "auto",
    bubble_check: bool = True,
    aliquot_post_ocv: bool = True,
    run_use: RunUse = RunUse.data,
):
    apm = ActionPlanMaker()

    if bubble_check:
        # RUN BUBBLE-CHECK OCV
        apm.add_actions(
            ADSS_sub_OCV(
                experiment=experiment,
                experiment_version=experiment_version,
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
            experiment=experiment,
            experiment_version=experiment_version,
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
def CLAD_sub_load_assembly(
    experiment: Experiment,
    experiment_version: int = 1,
    load_position: str = "cell1_we",
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
    liquid_sample_no: int = 1053,
    fill_volume_ul: float = 7000.0,
    fill_rate_ul_s: float = 300.0,
    gas_sample_no: int = 2,
    gas_volume_ml: float = 1.0,
    bubbler_gas: str = "O2",
):
    """Registers solid, liquid, and gas into load_position, then moves to solid, seals, and fills liquid.

    Args:
        experiment (Experiment): _description_
        experiment_version (int, optional): _description_. Defaults to 1.
        load_position (str, optional): _description_. Defaults to "cell1_we".
        solid_plate_id (int, optional): _description_. Defaults to 4534.
        solid_sample_no (int, optional): _description_. Defaults to 1.
        liquid_sample_no (int, optional): _description_. Defaults to 1053.
        fill_volume_ul (float, optional): _description_. Defaults to 7000.0.
        fill_rate_ul_s (float, optional): _description_. Defaults to 300.0.
        gas_sample_no (int, optional): _description_. Defaults to 2.
        gas_volume_ml (float, optional): _description_. Defaults to 1.0.
        bubbler_gas (str, optional): _description_. Defaults to "O2".

    Returns:
        _type_: _description_
    """
    apm = ActionPlanMaker()

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
        to_global_params={"_platexy": "_platexy"},
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

    apm.add_actions(
        CLAD_sub_load_sample(
            experiment=experiment,
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
            experiment=experiment,
            fill_volume_ul=fill_volume_ul,
            fill_rate_ul_s=fill_rate_ul_s,
            load_sample=False,  # load whatever sample is in _fast_samples_in
        )
    )

    return apm.planned_actions


# 4. OCV MEASUREMENT
# 5. CA MEASUREMENT
