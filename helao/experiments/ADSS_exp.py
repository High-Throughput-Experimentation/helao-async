"""
Experiment library for ADSS
server_key must be a FastAPI action server defined in config
"""

__all__ = [
    "debug",
    "ADSS_sub_sample_start",
    "ADSS_sub_shutdown",
    "ADSS_sub_drain",
    "ADSS_sub_clean_PALtool",
    "ADSS_sub_CA",  # latest
    "ADSS_sub_CV",  # latest
    "ADSS_sub_OCV",  # at beginning of all sequences
    "ADSS_sub_unloadall_customs",
    "ADSS_sub_unload_liquid",
    "ADSS_sub_load",
    "ADSS_sub_load_solid",
    "ADSS_sub_load_liquid",
    "ADSS_sub_fillfixed",
    "ADSS_sub_fill",
    "ADSS_sub_tray_unload",
    "ADSS_sub_rel_move",
    "ADSS_sub_heat",
    "ADSS_sub_stopheat",
    "ADSS_sub_cellfill_prefilled",
    "ADSS_sub_cellfill_flush",
    "ADSS_sub_drain_cell",
    #    "ADSS_sub_empty_cell",
    "ADSS_sub_move_to_clean_cell",
    "ADSS_sub_clean_cell",
    "ADSS_sub_refill_syringes",
    "ADSS_sub_sample_aliquot",
    "ADSS_sub_recirculate",
    "ADSS_sub_abs_move",
    "ADSS_sub_cell_illumination",
    "ADSS_sub_CA_photo",
    "ADSS_sub_OCV_photo",
]


from typing import Optional, List
from socket import gethostname

from helao.helpers.premodels import Experiment, ActionPlanMaker
from helaocore.models.action_start_condition import ActionStartCondition
from helaocore.models.sample import SolidSample, LiquidSample
from helaocore.models.machine import MachineModel
from helaocore.models.process_contrib import ProcessContrib
from helao.helpers.ref_electrode import REF_TABLE

from helao.drivers.motion.galil_motion_driver import MoveModes, TransformationModes
from helao.drivers.robot.pal_driver import Spacingmethod, PALtools


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


def debug(
    experiment: Experiment,
    experiment_version: int = 1,
    d_mm: str = "1.0",
    x_mm: float = 0.0,
    y_mm: float = 0.0,
):
    """Test action for ORCH debugging
    simple plate is e.g. 4534"""

    # additional experiment params should be stored in action_group.experiment_params
    # these are duplicates of the function parameters (currently the op uses functions
    # parameters to display them in the webUI)

    # start_condition:
    # 0: orch is dispatching an unconditional action
    # 1: orch is waiting for endpoint to become available
    # 2: orch is waiting for server to become available
    # 3: (or other): orch is waiting for all action_dq to finish

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    apm.add(
        PAL_server,
        "archive_custom_unload",
        {"custom": "cell1_we"},
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
    )

    apm.add(
        PAL_server,
        "archive_custom_load",
        {
            "custom": "cell1_we",
            "load_sample_in": SolidSample(
                **{"sample_no": 1, "plate_id": 4534, "machine_name": "legacy"}
            ).dict(),
        },
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
    )

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
            "Tval": 10.0,
            "SampleRate": 1.0,
            "TTLwait": apm.pars.gamrychannelwait,  # -1 disables, else select TTL 0-3
            "TTLsend": apm.pars.gamrychannelsend,  # -1 disables, else select TTL 0-3
            "IErange": "auto",
        },
        from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
    )

    return apm.action_list  # returns complete action list to orch


def ADSS_sub_unloadall_customs(experiment: Experiment):
    """last functionality test: 11/29/2021"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    apm.add(
        PAL_server,
        "archive_custom_unloadall",
        {
            #                "destroy_liquid": False,
        },
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
    )

    return apm.action_list  # returns complete action list to orch


def ADSS_sub_unload_liquid(
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


def ADSS_sub_load_solid(
    experiment: Experiment,
    experiment_version: int = 1,
    solid_custom_position: str = "cell1_we",
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
):
    """last functionality test: 11/29/2021"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(
        PAL_server,
        "archive_custom_load",
        {
            "custom": apm.pars.solid_custom_position,
            "load_sample_in": SolidSample(
                **{
                    "sample_no": apm.pars.solid_sample_no,
                    "plate_id": apm.pars.solid_plate_id,
                    "machine_name": "legacy",
                }
            ).dict(),
        },
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
    )
    return apm.action_list  # returns complete action list to orch


def ADSS_sub_load_liquid(
    experiment: Experiment,
    experiment_version: int = 2,  # v2 changes from archive_custom_load
    liquid_custom_position: str = "cell1_we",
    liquid_sample_no: int = 1,
    volume_ul_cell_liquid: int = 1000,
):
    """last functionality test: 11/29/2021"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(
        PAL_server,
        "archive_custom_add_liquid",
        {
            "custom": apm.pars.liquid_custom_position,
            "source_liquid_in": LiquidSample(
                **{
                    "sample_no": apm.pars.liquid_sample_no,
                    "machine_name": gethostname(),
                }
            ).dict(),
            "volume_ml": apm.pars.volume_ul_cell_liquid / 1000,
            "combine_liquids": False,
            "dilute_liquids": False,
        },
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
    )
    return apm.action_list  # returns complete action list to orch


def ADSS_sub_load(
    experiment: Experiment,
    experiment_version: int = 2,
    solid_custom_position: str = "cell1_we",
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
    liquid_custom_position: str = "cell1_we",
    liquid_sample_no: int = 1,
    liquid_sample_volume_ul: float = 4000,
):
    apm = ActionPlanMaker()

    #    # unload all samples from custom positions
    apm.add_action_list(ADSS_sub_unloadall_customs(experiment=experiment))

    # load new requested samples
    apm.add_action_list(
        ADSS_sub_load_solid(
            experiment=experiment,
            solid_custom_position=apm.pars.solid_custom_position,
            solid_plate_id=apm.pars.solid_plate_id,
            solid_sample_no=apm.pars.solid_sample_no,
        )
    )

    apm.add_action_list(
        ADSS_sub_load_liquid(
            experiment=experiment,
            liquid_custom_position=apm.pars.liquid_custom_position,
            liquid_sample_no=apm.pars.liquid_sample_no,
            volume_ul_cell_liquid=apm.pars.liquid_sample_volume_ul,
        )
    )

    return apm.action_list


def ADSS_sub_sample_start(
    experiment: Experiment,
    experiment_version: int = 4,
    solid_custom_position: str = "cell1_we",
    solid_plate_id: int = 4534,
    solid_sample_no: int = 1,
    #    x_mm: float = 0.0,
    #    y_mm: float = 0.0,
    liquid_custom_position: str = "cell1_we",
    liquid_sample_no: int = 1,
    liquid_sample_volume_ul: float = 4000,
):
    """Sub experiment
    (1) Unload all custom position samples
    (2) Load solid sample to cell
    (3) Load liquid sample to reservoir
    (4) Move to position
    (5) Engages cell

    last functionality test: 11/29/2021"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    apm.add_action_list(
        ADSS_sub_load(
            experiment=experiment,
            solid_custom_position=apm.pars.solid_custom_position,
            solid_plate_id=apm.pars.solid_plate_id,
            solid_sample_no=apm.pars.solid_sample_no,
            liquid_custom_position=apm.pars.liquid_custom_position,
            liquid_sample_no=apm.pars.liquid_sample_no,
            liquid_sample_volume_ul=apm.pars.liquid_sample_volume_ul,
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
            "plate_id": apm.pars.solid_plate_id,
            "sample_no": apm.pars.solid_sample_no,
        },
        to_globalexp_params=[
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
        from_globalexp_params={"_platexy": "d_mm"},
        save_act=debug_save_act,
        save_data=debug_save_data,
        start_condition=ActionStartCondition.wait_for_all,
    )

    # seal cell
    apm.add(MOTOR_server, "z_move", {"z_position": "seal"})

    return apm.action_list  # returns complete action list to orch


def ADSS_sub_shutdown(experiment: Experiment):
    """Sub experiment
    (1) Deep clean PAL tool
    (2) pump liquid out off cell
    (3) Drain cell
    (4) Disengages cell (TBD)

    last functionality test: 11/29/2021"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # deep clean
    apm.add_action_list(
        ADSS_sub_clean_PALtool(experiment, clean_tool=PALtools.LS3, clean_volume_ul=500)
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
    # apm.add_action_list(ADSS_sub_drain(experiment))

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
    # apm.add_action_list(ADSS_sub_disengage(experiment))

    return apm.action_list  # returns complete action list to orch


def ADSS_sub_drain(experiment: Experiment):
    """DUMMY Sub experiment
    Drains electrochemical cell.
    last functionality test: 11/29/2021"""
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    # TODO
    return apm.action_list  # returns complete action list to orch


def ADSS_sub_clean_PALtool(
    experiment: Experiment,
    experiment_version: int = 1,
    clean_tool: str = PALtools.LS3,
    clean_volume_ul: int = 500,
):
    """Sub experiment
    Performs deep clean of selected PAL tool.

    last functionality test: 11/29/2021"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # deep clean
    apm.add(
        PAL_server,
        "PAL_deepclean",
        {
            "tool": apm.pars.clean_tool,
            "volume_ul": apm.pars.clean_volume_ul,
        },
        start_condition=ActionStartCondition.wait_for_all,
    )

    return apm.action_list  # returns complete action list to orch


def ADSS_sub_fillfixed(
    experiment: Experiment,
    experiment_version: int = 1,
    fill_vol_ul: int = 10000,
    filltime_sec: float = 10.0,
    PAL_Injector: str = "PALtools.LS3",
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # fill liquid, no wash (assume it was cleaned before)
    apm.add(
        PAL_server,
        "PAL_fillfixed",
        {
            "tool": apm.pars.PAL_Injector,
            "source": "elec_res1",
            "dest": "cell1_we",
            "volume_ul": apm.pars.fill_vol_ul,
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
            "waittime": apm.pars.filltime_sec,
        },
        start_condition=ActionStartCondition.wait_for_all,
    )

    return apm.action_list  # returns complete action list to orch


def ADSS_sub_fill(
    experiment: Experiment,
    experiment_version: int = 1,
    fill_vol_ul: int = 1000,
    PAL_Injector: str = "PALtools.LS3",
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # fill liquid, no wash (assume it was cleaned before)
    apm.add(
        PAL_server,
        "PAL_fill",
        {
            "tool": apm.pars.PAL_Injector,
            "source": "elec_res1",
            "dest": "cell1_we",
            "volume_ul": apm.pars.fill_vol_ul,
            "wash1": 0,
            "wash2": 0,
            "wash3": 0,
            "wash4": 0,
        },
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
    )

    return apm.action_list  # returns complete action list to orch


def ADSS_sub_CA(
    experiment: Experiment,
    experiment_version: int = 8,
    CA_potential: float = 0.0,
    ph: float = 9.53,
    potential_versus: str = "rhe",
    ref_type: str = "inhouse",
    ref_offset__V: float = 0.0,
    gamry_i_range: str = "auto",
    samplerate_sec: float = 0.05,
    CA_duration_sec: float = 1800,
    aliquot_volume_ul: int = 200,
    aliquot_times_sec: List[float] = [],
    aliquot_insitu: bool = True,
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "fill serial number here",
):
    """Primary CA experiment with optional PAL sampling.

    aliquot_intervals_sec is an optional list of intervals aftedf
    r which an aliquot
    is sampled from the cell, e.g. [600, 600, 600] will take 3 aliquots at 10-minute
    intervals; note due to PAL overhead, intervals must be longer than 4 minutes

    aliquot_insitu flags whether the sampling interval timer begins at the start of the
    PSTAT action (True) or after the PSTAT action (False)

    """

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

    # calculate potential
    versus = 0  # for vs rhe
    if apm.pars.potential_versus == "oer":
        versus = 1.23
    if apm.pars.ref_type == "rhe":
        potential = apm.pars.CA_potential - apm.pars.ref_offset__V + versus
    else:
        potential = (
            apm.pars.CA_potential
            - 1.0 * apm.pars.ref_offset__V
            + versus
            - 0.059 * apm.pars.ph
            - REF_TABLE[apm.pars.ref_type]
        )
    print(f"ADSS_sub_CA potential: {potential}")

    # apply potential
    apm.add(
        PSTAT_server,
        "run_CA",
        {
            "Vval__V": potential,
            "Tval__s": apm.pars.CA_duration_sec,
            "AcqInterval__s": apm.pars.samplerate_sec,
            "IErange": apm.pars.gamry_i_range,
        },
        from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
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
    atimes = apm.pars.aliquot_times_sec
    vwait = 0
    if atimes:
        intervals = [atimes[0]] + [x - y for x, y in zip(atimes[1:], atimes[:-1])]

        if apm.pars.aliquot_insitu:
            waitcond = ActionStartCondition.no_wait
        else:
            waitcond = ActionStartCondition.wait_for_all

        washmod = 0
        for interval in intervals:
            apm.add(ORCH_server, "wait", {"waittime": interval - vwait}, waitcond)
            apm.add(
                NI_server,
                "gasvalve",
                {"gasvalve": "V1", "on": 0},
                ActionStartCondition.wait_for_orch,
            )
            apm.add(
                PAL_server,
                "PAL_archive",
                {
                    "tool": apm.pars.PAL_Injector,
                    "source": "cell1_we",
                    "volume_ul": apm.pars.aliquot_volume_ul,
                    "sampleperiod": [0.0],
                    "spacingmethod": Spacingmethod.linear,
                    "spacingfactor": 1.0,
                    "timeoffset": 0.0,
                    "wash1": 0,
                    "wash2": washmod % 2,
                    "wash3": (washmod + 1) % 2,
                    "wash4": 0,
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
            vwait = 65
            washmod += 1
            apm.add(ORCH_server, "wait", {"waittime": vwait}, waitcond)
            apm.add(
                NI_server,
                "gasvalve",
                {"gasvalve": "V1", "on": 1},
                ActionStartCondition.wait_for_orch,
            )

    return apm.action_list  # returns complete action list to orch


def ADSS_sub_CA_photo(
    experiment: Experiment,
    experiment_version: int = 4,  # v4 add electrolyte add
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
    insert_electrolyte_yn: bool = False,
    insert_electrolyte_ul: int = 0,
    insert_electrolyte_time_sec: float = 1800,
    aliquot_volume_ul: int = 200,
    aliquot_times_sec: List[float] = [],
    aliquot_insitu: bool = True,
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "fill serial number here",
):
    """Primary CA experiment with optional PAL sampling.

    aliquot_intervals_sec is an optional list of intervals aftedf
    r which an aliquot
    is sampled from the cell, e.g. [600, 600, 600] will take 3 aliquots at 10-minute
    intervals; note due to PAL overhead, intervals must be longer than 4 minutes

    aliquot_insitu flags whether the sampling interval timer begins at the start of the
    PSTAT action (True) or after the PSTAT action (False)

    """

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

    apm.add(NI_server, "led", {"led": "led", "on": 1})

    # calculate potential
    versus = 0  # for vs rhe
    if apm.pars.potential_versus == "oer":
        versus = 1.23
    if apm.pars.ref_type == "rhe":
        potential = apm.pars.CA_potential - apm.pars.ref_offset__V + versus
    else:
        potential = (
            apm.pars.CA_potential
            - 1.0 * apm.pars.ref_offset__V
            + versus
            - 0.059 * apm.pars.ph
            - REF_TABLE[apm.pars.ref_type]
        )
    print(f"ADSS_sub_CA potential: {potential}")

    # apply potential
    apm.add(
        PSTAT_server,
        "run_CA",
        {
            "Vval__V": potential,
            "Tval__s": apm.pars.CA_duration_sec,
            "AcqInterval__s": apm.pars.samplerate_sec,
            "IErange": apm.pars.gamry_i_range,
        },
        from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
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
    atimes = apm.pars.aliquot_times_sec
    etime = apm.pars.insert_electrolyte_time_sec

    eidx = max([i for i, v in enumerate(atimes) if v < etime])
    mlist = [("aliquot", t) for t in atimes]
    mlist.insert(eidx + 1, ("electrolyte", etime))

    vwait = 0
    if mlist:
        intervals = [mlist[0][1]] + [
            x[1] - y[1] for x, y in zip(mlist[1:], mlist[:-1])
        ]

        if apm.pars.aliquot_insitu:
            waitcond = ActionStartCondition.no_wait
        else:
            waitcond = ActionStartCondition.wait_for_all

        washmod = 0
        for mtup, interval in zip(mlist, intervals):
            if mtup[0] == "aliquot":
                apm.add(ORCH_server, "wait", {"waittime": interval - vwait}, waitcond)
                apm.add(
                    NI_server,
                    "gasvalve",
                    {"gasvalve": "V1", "on": 0},
                    ActionStartCondition.wait_for_orch,
                )
                apm.add(
                    PAL_server,
                    "PAL_archive",
                    {
                        "tool": apm.pars.PAL_Injector,
                        "source": "cell1_we",
                        "volume_ul": apm.pars.aliquot_volume_ul,
                        "sampleperiod": [0.0],
                        "spacingmethod": Spacingmethod.linear,
                        "spacingfactor": 1.0,
                        "timeoffset": 0.0,
                        "wash1": 0,
                        "wash2": washmod % 2,
                        "wash3": (washmod + 1) % 2,
                        "wash4": 0,
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
                vwait = 65
                washmod += 1
                apm.add(ORCH_server, "wait", {"waittime": vwait}, waitcond)
                apm.add(
                    NI_server,
                    "gasvalve",
                    {"gasvalve": "V1", "on": 1},
                    ActionStartCondition.wait_for_orch,
                )
            elif mtup[0] == "electrolyte":
               if apm.pars.insert_electrolyte_yn:
                    apm.add_action_list(ADSS_sub_cellfill_prefilled(
                        experiment=experiment,
                        Solution_volume_ul=apm.pars.insert_electrolyte_ul,
                        Syringe_rate_ulsec=300))
                

    apm.add(NI_server, "led", {"led": "led", "on": 0})

    return apm.action_list  # returns complete action list to orch


def ADSS_sub_CV(
    experiment: Experiment,
    experiment_version: int = 5,
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
    potential_versus: str = "rhe",
    ref_type: str = "inhouse",
    ref_offset__V: float = 0.0,
    aliquot_volume_ul: int = 200,
    aliquot_times_sec: List[float] = [],
    aliquot_insitu: bool = True,
    PAL_Injector: str = "LS 4",
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    CV_duration_sec = (
        abs(apm.pars.Vapex1_vsRHE - apm.pars.Vinit_vsRHE) / apm.pars.scanrate_voltsec
    )
    CV_duration_sec += (
        abs(apm.pars.Vfinal_vsRHE - apm.pars.Vapex2_vsRHE) / apm.pars.scanrate_voltsec
    )
    CV_duration_sec += (
        abs(apm.pars.Vapex2_vsRHE - apm.pars.Vapex1_vsRHE)
        / apm.pars.scanrate_voltsec
        * apm.pars.cycles
    )
    CV_duration_sec += (
        abs(apm.pars.Vapex2_vsRHE - apm.pars.Vapex1_vsRHE)
        / apm.pars.scanrate_voltsec
        * 2.0
        * (apm.pars.cycles - 1)
    )

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

    # apply potential
    apm.add(
        PSTAT_server,
        "run_CV",
        {
            "Vinit__V": apm.pars.Vinit_vsRHE
            - 1.0 * apm.pars.ref_offset__V
            - REF_TABLE[apm.pars.ref_type]
            - 0.059 * apm.pars.ph,
            "Vapex1__V": apm.pars.Vapex1_vsRHE
            - 1.0 * apm.pars.ref_offset__V
            - REF_TABLE[apm.pars.ref_type]
            - 0.059 * apm.pars.ph,
            "Vapex2__V": apm.pars.Vapex2_vsRHE
            - 1.0 * apm.pars.ref_offset__V
            - REF_TABLE[apm.pars.ref_type]
            - 0.059 * apm.pars.ph,
            "Vfinal__V": apm.pars.Vfinal_vsRHE
            - 1.0 * apm.pars.ref_offset__V
            - REF_TABLE[apm.pars.ref_type]
            - 0.059 * apm.pars.ph,
            "ScanRate__V_s": apm.pars.scanrate_voltsec,
            "AcqInterval__s": apm.pars.samplerate_sec,
            "Cycles": apm.pars.cycles,
            "IErange": apm.pars.gamry_i_range,
        },
        from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
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

    atimes = apm.pars.aliquot_times_sec
    if atimes:
        intervals = [atimes[0]] + [x - y for x, y in zip(atimes[1:], atimes[:-1])]

        if apm.pars.aliquot_insitu:
            waitcond = ActionStartCondition.no_wait
        else:
            waitcond = ActionStartCondition.wait_for_all

        for interval in intervals:
            apm.add(ORCH_server, "wait", {"waittime": interval}, waitcond)
            apm.add(
                PAL_server,
                "PAL_archive",
                {
                    "tool": apm.pars.PAL_Injector,
                    "source": "cell1_we",
                    "volume_ul": apm.pars.aliquot_volume_ul,
                    "sampleperiod": [0.0],
                    "spacingmethod": Spacingmethod.custom,
                    "spacingfactor": 1.0,
                    "timeoffset": 0.0,
                    "wash1": 0,
                    "wash2": 0,
                    "wash3": 0,
                    "wash4": 0,
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

    return apm.action_list  # returns complete action list to orch


def ADSS_sub_OCV(
    experiment: Experiment,
    experiment_version: int = 5,
    Tval__s: float = 60.0,
    gamry_i_range: str = "auto",
    samplerate_sec: float = 0.05,
    ph: float = 9.53,
    ref_type: str = "inhouse",
    ref_offset__V: float = 0.0,
    aliquot_volume_ul: int = 200,
    aliquot_times_sec: List[float] = [],
    aliquot_insitu: bool = False,
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "fill serial number here",
    rinse_1: int = 1,
    rinse_4: int = 0,
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
            "SampleRate": apm.pars.samplerate_sec,
            "IErange": apm.pars.gamry_i_range,
        },
        from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
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

    atimes = apm.pars.aliquot_times_sec
    if atimes:
        intervals = [atimes[0]] + [x - y for x, y in zip(atimes[1:], atimes[:-1])]

        if apm.pars.aliquot_insitu:
            waitcond = ActionStartCondition.no_wait
        else:
            waitcond = ActionStartCondition.wait_for_all

        for interval in intervals:
            apm.add(ORCH_server, "wait", {"waittime": interval}, waitcond)
            apm.add(
                NI_server,
                "gasvalve",
                {"gasvalve": "V1", "on": 0},
                ActionStartCondition.wait_for_orch,
            )
            apm.add(
                PAL_server,
                "PAL_archive",
                {
                    "tool": apm.pars.PAL_Injector,
                    "source": "cell1_we",
                    "volume_ul": apm.pars.aliquot_volume_ul,
                    "sampleperiod": [0.0],
                    "spacingmethod": Spacingmethod.custom,
                    "spacingfactor": 1.0,
                    "timeoffset": 0.0,
                    "wash1": apm.pars.rinse_1,
                    "wash2": 0,
                    "wash3": 0,
                    "wash4": apm.pars.rinse_4,
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
            apm.add(ORCH_server, "wait", {"waittime": 65}, ActionStartCondition.no_wait)
            apm.add(
                NI_server,
                "gasvalve",
                {"gasvalve": "V1", "on": 1},
                ActionStartCondition.wait_for_orch,
            )

    return apm.action_list  # returns complete action list to orch


def ADSS_sub_OCV_photo(
    experiment: Experiment,
    experiment_version: int = 6,
    Tval__s: float = 60.0,
    gamry_i_range: str = "auto",
    samplerate_sec: float = 0.05,
    ph: float = 9.53,
    ref_type: str = "inhouse",
    ref_offset__V: float = 0.0,
    led_wavelength: str = "385",
    toggle_illum_duty: float = 1,
    aliquot_volume_ul: int = 200,
    aliquot_times_sec: List[float] = [],
    aliquot_insitu: bool = False,
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "fill serial number here",
    rinse_1: int = 1,
    rinse_4: int = 0,
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

    apm.add(NI_server, "led", {"led": "led", "on": 1})

    # OCV
    apm.add(
        PSTAT_server,
        "run_OCV",
        {
            "Tval__s": apm.pars.Tval__s,
            "SampleRate": apm.pars.samplerate_sec,
            "IErange": apm.pars.gamry_i_range,
        },
        from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
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

    atimes = apm.pars.aliquot_times_sec
    if atimes:
        intervals = [atimes[0]] + [x - y for x, y in zip(atimes[1:], atimes[:-1])]

        if apm.pars.aliquot_insitu:
            waitcond = ActionStartCondition.no_wait
        else:
            waitcond = ActionStartCondition.wait_for_all

        for interval in intervals:
            apm.add(ORCH_server, "wait", {"waittime": interval}, waitcond)
            apm.add(
                NI_server,
                "gasvalve",
                {"gasvalve": "V1", "on": 0},
                ActionStartCondition.wait_for_orch,
            )
            apm.add(
                PAL_server,
                "PAL_archive",
                {
                    "tool": apm.pars.PAL_Injector,
                    "source": "cell1_we",
                    "volume_ul": apm.pars.aliquot_volume_ul,
                    "sampleperiod": [0.0],
                    "spacingmethod": Spacingmethod.custom,
                    "spacingfactor": 1.0,
                    "timeoffset": 0.0,
                    "wash1": apm.pars.rinse_1,
                    "wash2": 0,
                    "wash3": 0,
                    "wash4": apm.pars.rinse_4,
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
            apm.add(ORCH_server, "wait", {"waittime": 65}, ActionStartCondition.no_wait)
            apm.add(
                NI_server,
                "gasvalve",
                {"gasvalve": "V1", "on": 1},
                ActionStartCondition.wait_for_orch,
            )

    apm.add(NI_server, "led", {"led": "led", "on": 0})

    return apm.action_list  # returns complete action list to orch


def ADSS_sub_tray_unload(
    experiment: Experiment,
    experiment_version: int = 1,
    tray: int = 2,
    slot: int = 1,
    survey_runs: int = 1,
    main_runs: int = 3,
    rack: int = 2,
):
    """Unloads a selected tray from PAL position tray-slot and creates
    (1) json
    (2) csv
    (3) icpms
    exports.

    Parameters for ICPMS export are
    survey_runs: rough sweep over the whole partial_molarity range
    main_runs: sweep channel centered on element partial_molarity
    rack: position of the tray in the icpms instrument, usually 2.
    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    apm.add(
        PAL_server,
        "archive_tray_export_json",
        {
            "tray": apm.pars.tray,
            "slot": apm.pars.slot,
        },
        start_condition=ActionStartCondition.wait_for_all,
    )

    apm.add(
        PAL_server,
        "archive_tray_export_csv",
        {
            "tray": apm.pars.tray,
            "slot": apm.pars.slot,
        },
        start_condition=ActionStartCondition.wait_for_all,
    )

    apm.add(
        PAL_server,
        "archive_tray_export_icpms",
        {
            "tray": apm.pars.tray,
            "slot": apm.pars.slot,
            "survey_runs": apm.pars.survey_runs,
            "main_runs": apm.pars.main_runs,
            "rack": apm.pars.rack,
        },
        start_condition=ActionStartCondition.wait_for_all,
    )

    apm.add(
        PAL_server,
        "archive_tray_unload",
        {
            "tray": apm.pars.tray,
            "slot": apm.pars.slot,
        },
        start_condition=ActionStartCondition.wait_for_all,
    )

    return apm.action_list  # returns complete action list to orch


def ADSS_sub_rel_move(
    experiment: Experiment,
    experiment_version: int = 1,
    offset_x_mm: float = 1.0,
    offset_y_mm: float = 1.0,
    offset_z_mm: float = 0.0,
):
    """Sub experiment
    last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # move to position
    apm.add(
        MOTOR_server,
        "move",
        {
            "d_mm": [apm.pars.offset_x_mm, apm.pars.offset_y_mm, apm.pars.offset_z_mm],
            "axis": ["x", "y", "z"],
            "mode": MoveModes.relative,
            "transformation": TransformationModes.platexy,
        },
        #            "from_globalexp_params": {"_platexy": "d_mm"},
        start_condition=ActionStartCondition.wait_for_all,
    )

    return apm.action_list  # returns complete action list to orch


def ADSS_sub_abs_move(
    experiment: Experiment,
    experiment_version: int = 1,
    x_mm: float = 80.0,
    y_mm: float = 50.0,
    #    offset_z_mm: float = 0.0,
):
    """Sub experiment
    last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    apm.add(MOTOR_server, "z_move", {"z_position": "load"})
    # move to position
    apm.add(
        MOTOR_server,
        "move",
        {
            "d_mm": [apm.pars.x_mm, apm.pars.y_mm],
            "axis": ["x", "y"],
            "mode": MoveModes.absolute,
            "transformation": TransformationModes.platexy,
        },
        #            "from_globalexp_params": {"_platexy": "d_mm"},
        start_condition=ActionStartCondition.wait_for_all,
    )

    return apm.action_list  # returns complete action list to orch


def ADSS_sub_heat(
    experiment: Experiment,
    experiment_version: int = 1,
    duration_hrs: float = 2.0,
    celltemp_min_C: float = 74.5,
    celltemp_max_C: float = 75.5,
    reservoir2_min_C: float = 84.5,
    reservoir2_max_C: float = 85.5,
):
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
            "duration_hrs": apm.pars.duration_hrs,
            "celltemp_min_C": apm.pars.celltemp_min_C,
            "celltemp_max_C": apm.pars.celltemp_max_C,
            "reservoir2_min_C": apm.pars.reservoir2_min_C,
            "reservoir2_max_C": apm.pars.reservoir2_max_C,
        },
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        process_finish=False,
        process_contrib=[
            ProcessContrib.files,
        ],
    )
    return apm.action_list  # returns complete action list to orch


def ADSS_sub_stopheat(
    experiment: Experiment,
    experiment_version: int = 1,
):
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
    return apm.action_list  # returns complete action list to orch


def ADSS_sub_cellfill_prefilled(
    experiment: Experiment,
    experiment_version: int = 1,
    Solution_volume_ul: float = 3000,
    Syringe_rate_ulsec: float = 300,
    #    deadvolume_ul: int = 0,
    #    PurgeWait_s: float = 2,
    ReturnLineWait_s: float = 0,
):
    apm = ActionPlanMaker()
    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {
            "custom": "cell1_we",
        },
        to_globalexp_params=[
            "_fast_samples_in"
        ],  # save new liquid_sample_no of eche cell to globals
    )
    apm.add(NI_server, "gasvalve", {"gasvalve": "V1", "on": 0})
    # apm.add(NI_server, "gasvalve", {"gasvalve": "V3", "on": 1})
    # apm.add(
    #     SOLUTIONPUMP_server,
    #     "withdraw",
    #     {
    #         "rate_uL_sec": apm.pars.Syringe_rate_ulsec,
    #         "volume_uL": apm.pars.Solution_volume_ul,
    #     },
    # )
    # apm.add(NI_server, "gasvalve", {"gasvalve": "V3", "on": 0})
    apm.add(
        SOLUTIONPUMP_server,
        "infuse",
        {
            "rate_uL_sec": apm.pars.Syringe_rate_ulsec,
            "volume_uL": apm.pars.Solution_volume_ul,
        },
        from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
        technique_name="cell_fill",
        process_finish=True,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.samples_in,
        ],
    )
    if apm.pars.ReturnLineWait_s != 0:
        apm.add(NI_server, "pump", {"pump": "direction", "on": 0})
        apm.add(NI_server, "pump", {"pump": "peripump", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": apm.pars.ReturnLineWait_s})
        apm.add(NI_server, "pump", {"pump": "peripump", "on": 0})

    #    apm.add(NI_server, "gasvalve", {"gasvalve": "V1", "on": 1})

    return apm.action_list


def ADSS_sub_cellfill_flush(
    experiment: Experiment,
    experiment_version: int = 1,
    Solution_volume_ul: float = 3000,
    Syringe_rate_ulsec: float = 300,
    #    deadvolume_ul: int = 0,
    #    PurgeWait_s: float = 2,
    ReturnLineWait_s: float = 0,
):
    apm = ActionPlanMaker()
    apm.add(NI_server, "gasvalve", {"gasvalve": "V1", "on": 0})
    # apm.add(NI_server, "gasvalve", {"gasvalve": "V3", "on": 1})
    # apm.add(
    #     SOLUTIONPUMP_server,
    #     "withdraw",
    #     {
    #         "rate_uL_sec": apm.pars.Syringe_rate_ulsec,
    #         "volume_uL": apm.pars.Solution_volume_ul,
    #     },
    # )
    # apm.add(NI_server, "gasvalve", {"gasvalve": "V3", "on": 0})
    apm.add(
        SOLUTIONPUMP_server,
        "infuse",
        {
            "rate_uL_sec": apm.pars.Syringe_rate_ulsec,
            "volume_uL": apm.pars.Solution_volume_ul,
        },
    )
    if apm.pars.ReturnLineWait_s != 0:
        apm.add(NI_server, "pump", {"pump": "direction", "on": 0})
        apm.add(NI_server, "pump", {"pump": "peripump", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": apm.pars.ReturnLineWait_s})
        apm.add(NI_server, "pump", {"pump": "peripump", "on": 0})

    #    apm.add(NI_server, "gasvalve", {"gasvalve": "V1", "on": 1})

    return apm.action_list


def ADSS_sub_drain_cell(
    experiment: Experiment,
    experiment_version: int = 2,  # v2 remove residual part
    DrainWait_s: float = 60,
    ReturnLineReverseWait_s: float = 5,
    ResidualWait_s: float = 15,
):
    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "V1", "on": 0})
    apm.add(NI_server, "pump", {"pump": "direction", "on": 1})
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 1})  # clearing return line
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.ReturnLineReverseWait_s})
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "V4", "on": 1})
    apm.add(NI_server, "pump", {"pump": "direction", "on": 0})
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 1})  # draining reservoir
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.DrainWait_s})
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 0})
    #    apm.add(NI_server, "gasvalve", {"gasvalve": "V5", "on": 1})
    #    apm.add(NI_server, "pump", {"pump": "peripump", "on": 1})  # draining cell
    #    apm.add(ORCH_server, "wait", {"waittime": apm.pars.ResidualWait_s})
    #    apm.add(NI_server, "pump", {"pump": "peripump", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "V4", "on": 0})
    #    apm.add(NI_server, "gasvalve", {"gasvalve": "V5", "on": 0})

    return apm.action_list


# def ADSS_sub_empty_cell(
#     experiment: Experiment,
#     experiment_version: int = 1,
#     ReversePurgeWait_s: float = 20,
# ):

#     apm = ActionPlanMaker()
#     apm.add(NI_server, "gasvalve", {"gasvalve": "V1", "on": 0})
#     apm.add(NI_server, "pump", {"pump": "peripump", "on": 0})
#     apm.add(NI_server, "pump", {"pump": "direction", "on": 1})
#     apm.add(NI_server, "pump", {"pump": "peripump", "on": 1})
#     apm.add(ORCH_server, "wait", {"waittime": apm.pars.ReversePurgeWait_s})
#     apm.add(NI_server, "pump", {"pump": "peripump", "on": 0})

#     return apm.action_list


# need to move to clean spot first before beginning clean
def ADSS_sub_clean_cell(
    experiment: Experiment,
    experiment_version: int = 2,
    Clean_volume_ul: float = 3000,
    Syringe_rate_ulsec: float = 300,
    PurgeWait_s: float = 3,
    ReturnLineWait_s: float = 30,
    DrainWait_s: float = 60,
    ReturnLineReverseWait_s: float = 5,
    ResidualWait_s: float = 15,
):
    apm = ActionPlanMaker()

    apm.add(
        WATERCLEANPUMP_server,
        "infuse",
        {
            "rate_uL_sec": apm.pars.Syringe_rate_ulsec,
            "volume_uL": apm.pars.Clean_volume_ul,
        },
    )
    apm.add(NI_server, "gasvalve", {"gasvalve": "V1", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.PurgeWait_s})

    apm.add(NI_server, "pump", {"pump": "direction", "on": 0})
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.ReturnLineWait_s})
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 0})

    apm.add_action_list(
        ADSS_sub_drain_cell(
            experiment=experiment,
            DrainWait_s=apm.pars.DrainWait_s,
            ReturnLineReverseWait_s=apm.pars.ReturnLineReverseWait_s,
            ResidualWait_s=apm.pars.ResidualWait_s,
        )
    )

    apm.add(MOTOR_server, "z_move", {"z_position": "load"})

    return apm.action_list


def ADSS_sub_move_to_clean_cell(
    experiment: Experiment,
    experiment_version: int = 1,
):
    apm = ActionPlanMaker()
    apm.add(MOTOR_server, "z_move", {"z_position": "load"})
    apm.add(
        MOTOR_server,
        "solid_get_builtin_specref",
        {},
        to_globalexp_params=["_refxy"],
    )
    apm.add(
        MOTOR_server,
        "move",
        {
            "axis": ["x", "y"],
            "mode": MoveModes.absolute,
            "transformation": TransformationModes.platexy,
        },
        from_globalexp_params={"_refxy": "d_mm"},
    )

    apm.add(MOTOR_server, "z_move", {"z_position": "seal"})

    return apm.action_list


def ADSS_sub_refill_syringes(
    experiment: Experiment,
    experiment_version: int = 1,
    Solution_volume_ul: float = 0,
    Waterclean_volume_ul: float = 5000,
    Syringe_rate_ulsec: float = 300,
):
    apm = ActionPlanMaker()
    if apm.pars.Solution_volume_ul != 0:
        apm.add(NI_server, "gasvalve", {"gasvalve": "V3", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": 0.25})
        apm.add(
            SOLUTIONPUMP_server,
            "withdraw",
            {
                "rate_uL_sec": apm.pars.Syringe_rate_ulsec,
                "volume_uL": apm.pars.Solution_volume_ul + 25,
            },
        )
        apm.add(
            SOLUTIONPUMP_server,
            "infuse",
            {"rate_uL_sec": apm.pars.Syringe_rate_ulsec, "volume_uL": 25},
        )
        apm.add(ORCH_server, "wait", {"waittime": 40})
        apm.add(NI_server, "gasvalve", {"gasvalve": "V3", "on": 0})

    if apm.pars.Waterclean_volume_ul != 0:
        apm.add(NI_server, "gasvalve", {"gasvalve": "V2", "on": 1})
        apm.add(ORCH_server, "wait", {"waittime": 0.25})
        apm.add(
            WATERCLEANPUMP_server,
            "withdraw",
            {
                "rate_uL_sec": apm.pars.Syringe_rate_ulsec,
                "volume_uL": apm.pars.Waterclean_volume_ul + 25,
            },
        )
        apm.add(
            WATERCLEANPUMP_server,
            "infuse",
            {"rate_uL_sec": apm.pars.Syringe_rate_ulsec, "volume_uL": 25},
        )
        apm.add(ORCH_server, "wait", {"waittime": 10})
        apm.add(NI_server, "gasvalve", {"gasvalve": "V2", "on": 0})

    return apm.action_list


def ADSS_sub_sample_aliquot(
    experiment: Experiment,
    experiment_version: int = 3,
    aliquot_volume_ul: int = 200,
    EquilibrationTime_s: float = 30,
    PAL_Injector: str = "LS 4",
    PAL_Injector_id: str = "fill serial number here",
    rinse_1: int = 1,
    rinse_4: int = 0,
):
    apm = ActionPlanMaker()
    apm.add(
        PAL_server,
        "archive_custom_query_sample",
        {
            "custom": "cell1_we",
        },
        to_globalexp_params=[
            "_fast_samples_in"
        ],  # save new liquid_sample_no of eche cell to globals
    )
    apm.add(NI_server, "gasvalve", {"gasvalve": "V1", "on": 0})
    apm.add(NI_server, "pump", {"pump": "direction", "on": 0})
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.EquilibrationTime_s})
    apm.add(
        PAL_server,
        "PAL_archive",
        {
            "tool": apm.pars.PAL_Injector,
            "source": "cell1_we",
            "volume_ul": apm.pars.aliquot_volume_ul,
            "sampleperiod": [0.0],
            "spacingmethod": Spacingmethod.custom,
            "spacingfactor": 1.0,
            "timeoffset": 0.0,
            "wash1": apm.pars.rinse_1,
            "wash2": 0,
            "wash3": 0,
            "wash4": apm.pars.rinse_4,
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
    apm.add(NI_server, "gasvalve", {"gasvalve": "V1", "on": 1})

    return apm.action_list  # returns complete action list to orch


def ADSS_sub_recirculate(
    experiment: Experiment,
    experiment_version: int = 1,
    direction_forward_or_reverse: str = "forward",
):
    apm = ActionPlanMaker()
    if apm.pars.direction_forward_or_reverse == "forward":
        dir = 0
    else:
        dir = 1
    apm.add(NI_server, "gasvalve", {"gasvalve": "V1", "on": 1})
    apm.add(NI_server, "pump", {"pump": "direction", "on": dir})
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 1})
    return apm.action_list  # returns complete action list to orch


def ADSS_sub_cell_illumination(
    experiment: Experiment,
    experiment_version: int = 1,
    led_wavelength: str = "385",
    illumination_on: bool = False,
):
    apm = ActionPlanMaker()
    if apm.pars.illumination_on:
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

    return apm.action_list  # returns complete action list to orch
