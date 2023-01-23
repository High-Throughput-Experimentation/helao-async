"""
Experiment library for ADSS
server_key must be a FastAPI action server defined in config
"""

__all__ = [
    "debug",
    "ADSS_sub_startup",
    "ADSS_sub_shutdown",
    "ADSS_sub_engage",
    "ADSS_sub_disengage",
    "ADSS_sub_drain",
    "ADSS_sub_clean_PALtool",
    "ADSS_sub_CA",  # latest
    "ADSS_sub_CV",  # latest
    "ADSS_sub_OCV",  # at beginning of all sequences
    "ADSS_sub_unloadall_customs",
    "ADSS_sub_load",
    "ADSS_sub_load_solid",
    "ADSS_sub_load_liquid",
    "ADSS_sub_fillfixed",
    "ADSS_sub_fill",
    "ADSS_sub_tray_unload",
    "ADSS_sub_rel_move",
    "ADSS_sub_heat",
    "ADSS_sub_stopheat",
    "ADSS_sub_cellfill",
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
PSTAT_server = MachineModel(server_name="PSTAT", machine_name=ORCH_HOST).json_dict()
MOTOR_server = MachineModel(server_name="MOTOR", machine_name=ORCH_HOST).json_dict()
NI_server = MachineModel(server_name="NI", machine_name=ORCH_HOST).json_dict()
ORCH_server = MachineModel(server_name="ORCH", machine_name=ORCH_HOST).json_dict()
PAL_server = MachineModel(server_name="PAL", machine_name=ORCH_HOST).json_dict()
SOLUTIONPUMP_server = MachineModel(server_name="SYRINGE0", machine_name=ORCH_HOST).json_dict()
WATERCLEANPUMP_server = MachineModel(server_name="SYRINGE1", machine_name=ORCH_HOST).json_dict()


# z positions for ADSS cell
z_home = 0.0
# touches the bottom of cell
z_engage = 2.5
# moves it up to put pressure on seal
z_seal = 4.5

# cannot save data without exp
debug_save_act = True
debug_save_data = True


def debug(
    experiment: Experiment,
    experiment_version: int = 1,
    d_mm: Optional[str] = "1.0",
    x_mm: Optional[float] = 0.0,
    y_mm: Optional[float] = 0.0,
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


def ADSS_sub_load_solid(
    experiment: Experiment,
    experiment_version: int = 1,
    solid_custom_position: Optional[str] = "cell1_we",
    solid_plate_id: Optional[int] = 4534,
    solid_sample_no: Optional[int] = 1,
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
    experiment_version: int = 1,
    liquid_custom_position: Optional[str] = "elec_res1",
    liquid_sample_no: Optional[int] = 1,
):
    """last functionality test: 11/29/2021"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(
        PAL_server,
        "archive_custom_load",
        {
            "custom": apm.pars.liquid_custom_position,
            "load_sample_in": LiquidSample(
                **{
                    "sample_no": apm.pars.liquid_sample_no,
                    "machine_name": gethostname(),
                }
            ).dict(),
        },
        start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
    )
    return apm.action_list  # returns complete action list to orch


def ADSS_sub_load(
    experiment: Experiment,
    experiment_version: int = 1,
    solid_custom_position: Optional[str] = "cell1_we",
    solid_plate_id: Optional[int] = 4534,
    solid_sample_no: Optional[int] = 1,
    liquid_custom_position: Optional[str] = "elec_res1",
    liquid_sample_no: Optional[int] = 1,
):
    apm = ActionPlanMaker()

    # unload all samples from custom positions
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
        )
    )

    return apm.action_list


def ADSS_sub_startup(
    experiment: Experiment,
    experiment_version: int = 1,
    solid_custom_position: Optional[str] = "cell1_we",
    solid_plate_id: Optional[int] = 4534,
    solid_sample_no: Optional[int] = 1,
    x_mm: Optional[float] = 0.0,
    y_mm: Optional[float] = 0.0,
    liquid_custom_position: Optional[str] = "elec_res1",
    liquid_sample_no: Optional[int] = 1,
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
    apm.add_action_list(ADSS_sub_disengage(experiment))

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
        save_act=debug_save_act,
        save_data=debug_save_data,
        start_condition=ActionStartCondition.wait_for_all,
    )

    # seal cell
    apm.add_action_list(ADSS_sub_engage(experiment))

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


def ADSS_sub_engage(experiment: Experiment):
    """Sub experiment
    Engages and seals electrochemical cell.

    last functionality test: 11/29/2021"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # engage
    apm.add(
        MOTOR_server,
        "move",
        {
            "d_mm": [z_engage],
            "axis": ["z"],
            "mode": MoveModes.absolute,
            "transformation": TransformationModes.instrxy,
        },
        save_act=debug_save_act,
        save_data=debug_save_data,
        start_condition=ActionStartCondition.wait_for_all,
    )

    # seal
    apm.add(
        MOTOR_server,
        "move",
        {
            "d_mm": [z_seal],
            "axis": ["z"],
            "mode": MoveModes.absolute,
            "transformation": TransformationModes.instrxy,
        },
        save_act=debug_save_act,
        save_data=debug_save_data,
        start_condition=ActionStartCondition.wait_for_all,
    )

    return apm.action_list  # returns complete action list to orch


def ADSS_sub_disengage(experiment: Experiment):
    """Sub experiment
    Disengages and seals electrochemical cell.

    last functionality test: 11/29/2021"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    apm.add(
        MOTOR_server,
        "move",
        {
            "d_mm": [z_home],
            "axis": ["z"],
            "mode": MoveModes.absolute,
            "transformation": TransformationModes.instrxy,
        },
        save_act=debug_save_act,
        save_data=debug_save_data,
        start_condition=ActionStartCondition.wait_for_all,
    )

    return apm.action_list  # returns complete action list to orch


def ADSS_sub_clean_PALtool(
    experiment: Experiment,
    experiment_version: int = 1,
    clean_tool: Optional[str] = PALtools.LS3,
    clean_volume_ul: Optional[int] = 500,
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
    fill_vol_ul: Optional[int] = 10000,
    filltime_sec: Optional[float] = 10.0,
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # fill liquid, no wash (assume it was cleaned before)
    apm.add(
        PAL_server,
        "PAL_fillfixed",
        {
            "tool": PALtools.LS3,
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
    fill_vol_ul: Optional[int] = 1000,
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # fill liquid, no wash (assume it was cleaned before)
    apm.add(
        PAL_server,
        "PAL_fill",
        {
            "tool": PALtools.LS3,
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
    experiment_version: int = 5,
    CA_potential: Optional[float] = 0.0,
    ph: Optional[float] = 9.53,
    potential_versus: Optional[str] = "rhe",
    ref_type: Optional[str] = "inhouse",
    ref_offset__V: Optional[float] = 0.0,
    gamry_i_range: Optional[str] = "auto",
    samplerate_sec: Optional[float] = 0.05,
    CA_duration_sec: Optional[float] = 1800,
    aliquot_volume_ul: Optional [int] = 200,
    aliquot_times_sec: Optional[List[float]] = [],
    aliquot_insitu: Optional[bool] = False,
):
    """Primary CA experiment with optional PAL sampling.

    aliquot_intervals_sec is an optional list of intervals after which an aliquot
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
    potential = (
        apm.pars.CA_potential
        - 1.0 * apm.pars.ref_offset__V
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

    # check if aliquot sample should happen in-situ or after PSTAT action
    if apm.pars.aliquot_insitu:
        startcond = ActionStartCondition.no_wait
    else:
        startcond = ActionStartCondition.wait_for_orch

    if apm.pars.aliquot_times_sec:
        for i, aliquot_time in enumerate(apm.pars.aliquot_times_sec):
            if i == 0 and not apm.pars.aliquot_insitu:
                apm.add(
                    ORCH_server,
                    "wait",
                    {"waittime": aliquot_time},
                    ActionStartCondition.wait_for_all,
                )
            else:
                apm.add(ORCH_server, "wait", {"waittime": aliquot_time}, startcond)
            apm.add(
                PAL_server,
                "PAL_archive",
                {
                    "tool": PALtools.LS3,
                    "source": "cell1_we",
                    "volume_ul": apm.pars.aliquot_volume_ul,
                    "sampleperiod": [0.0],
                    "spacingmethod": Spacingmethod.custom,
                    "spacingfactor": 1.0,
                    "timeoffset": 60.0,
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


def ADSS_sub_CV(
    experiment: Experiment,
    experiment_version: int = 4,
    Vinit_vsRHE: Optional[float] = 0.0,  # Initial value in volts or amps.
    Vapex1_vsRHE: Optional[float] = 1.0,  # Apex 1 value in volts or amps.
    Vapex2_vsRHE: Optional[float] = -1.0,  # Apex 2 value in volts or amps.
    Vfinal_vsRHE: Optional[float] = 0.0,  # Final value in volts or amps.
    scanrate_voltsec: Optional[
        float
    ] = 0.02,  # scan rate in volts/second or amps/second.
    samplerate_sec: Optional[float] = 0.1,
    cycles: Optional[int] = 1,
    gamry_i_range: Optional[str] = "auto",
    ph: float = 9.53,
    potential_versus: Optional[str] = "rhe",
    ref_type: Optional[str] = "inhouse",
    ref_offset__V: Optional[float] = 0.0,
    aliquot_volume_ul: Optional [int] = 200,
    aliquot_times_sec: Optional[List[float]] = [],
    aliquot_insitu: Optional[bool] = False,
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

    # check if aliquot sample should happen in-situ or after PSTAT action
    if apm.pars.aliquot_insitu:
        startcond = ActionStartCondition.no_wait
    else:
        startcond = ActionStartCondition.wait_for_orch

    if apm.pars.aliquot_times_sec:
        for i, aliquot_time in enumerate(apm.pars.aliquot_times_sec):
            if i == 0 and not apm.pars.aliquot_insitu:
                apm.add(
                    ORCH_server,
                    "wait",
                    {"waittime": aliquot_time},
                    ActionStartCondition.wait_for_all,
                )
            else:
                apm.add(ORCH_server, "wait", {"waittime": aliquot_time}, startcond)
            apm.add(
                PAL_server,
                "PAL_archive",
                {
                    "tool": PALtools.LS3,
                    "source": "cell1_we",
                    "volume_ul": apm.pars.aliquot_volume_ul,
                    "sampleperiod": [0.0],
                    "spacingmethod": Spacingmethod.custom,
                    "spacingfactor": 1.0,
                    "timeoffset": 60.0,
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
    experiment_version: int = 4,
    Tval__s: Optional[float] = 60.0,
    gamry_i_range: Optional[str] = "auto",
    aliquot_volume_ul: Optional [int] = 200,
    aliquot_intervals_sec: Optional[List[float]] = [],
    aliquot_insitu: Optional[bool] = False,
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

    # check if aliquot sample should happen in-situ or after PSTAT action
    if apm.pars.aliquot_insitu:
        startcond = ActionStartCondition.no_wait
    else:
        startcond = ActionStartCondition.wait_for_orch

    if apm.pars.aliquot_times_sec:
        for i, aliquot_time in enumerate(apm.pars.aliquot_times_sec):
            if i == 0 and not apm.pars.aliquot_insitu:
                apm.add(
                    ORCH_server,
                    "wait",
                    {"waittime": aliquot_time},
                    ActionStartCondition.wait_for_all,
                )
            else:
                apm.add(ORCH_server, "wait", {"waittime": aliquot_time}, startcond)
            apm.add(
                PAL_server,
                "PAL_archive",
                {
                    "tool": PALtools.LS3,
                    "source": "cell1_we",
                    "volume_ul": apm.pars.aliquot_volume_ul,
                    "sampleperiod": [0.0],
                    "spacingmethod": Spacingmethod.custom,
                    "spacingfactor": 1.0,
                    "timeoffset": 60.0,
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


def ADSS_sub_tray_unload(
    experiment: Experiment,
    experiment_version: int = 1,
    tray: Optional[int] = 2,
    slot: Optional[int] = 1,
    survey_runs: Optional[int] = 1,
    main_runs: Optional[int] = 3,
    rack: Optional[int] = 2,
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
        process_finish=True,
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
        process_finish=True,
        process_contrib=[
            ProcessContrib.files,
        ],
    )
    apm.add(
        NI_server,
        "monloopstop",
        {},
    )
    return apm.action_list  # returns complete action list to orch


# def ADSS_sub_CA_originalwithstuff(
#     experiment: Experiment,
#     experiment_version: int = 2,
#     CA_potential: Optional[float] = 0.0,
#     ph: float = 9.53,
#     potential_versus: Optional[str] = "rhe",
#     ref_type: Optional[str] = "inhouse",
#     ref_offset__V: Optional[float] = 0.0,
#     gamry_i_range: Optional[str] = "auto",
#     samplerate_sec: Optional[float] = 1,
#     OCV_duration_sec: Optional[float] = 60,
#     CA_duration_sec: Optional[float] = 1320,
#     aliquot_times_sec: Optional[List[float]] = [60, 600, 1140],
# ):
#     """last functionality test: 11/29/2021"""

#     apm = ActionPlanMaker()  # exposes function parameters via apm.pars

#     # get sample for gamry
#     apm.add(
#         PAL_server,
#         "archive_custom_query_sample",
#         {
#             "custom": "cell1_we",
#         },
#         to_globalexp_params=[
#             "_fast_samples_in"
#         ],  # save new liquid_sample_no of eche cell to globals
#         start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
#     )

#     # OCV
#     apm.add(
#         PSTAT_server,
#         "run_OCV",
#         {
#             "Tval": apm.pars.OCV_duration_sec,
#             "SampleRate": apm.pars.samplerate_sec,
#             "IErange": apm.pars.gamry_i_range,
#         },
#         from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
#         start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
#     )

#     # take liquid sample
#     apm.add(
#         PAL_server,
#         "PAL_archive",
#         {
#             "tool": PALtools.LS3,
#             "source": "cell1_we",
#             "volume_ul": 200,
#             "sampleperiod": [0.0],
#             "spacingmethod": Spacingmethod.linear,
#             "spacingfactor": 1.0,
#             "timeoffset": 0.0,
#             "wash1": 0,
#             "wash2": 0,
#             "wash3": 0,
#             "wash4": 0,
#         },
#         start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
#     )

#     apm.add(
#         PAL_server,
#         "archive_custom_query_sample",
#         {
#             "custom": "cell1_we",
#         },
#         to_globalexp_params=[
#             "_fast_samples_in"
#         ],  # save new liquid_sample_no of eche cell to globals
#         start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
#     )

#     # apply potential
#     potential = (
#         apm.pars.CA_potential
#         - 1.0 * apm.pars.ref_offset__V
#         - 0.059 * apm.pars.ph
#         - REF_TABLE[apm.pars.ref_type]
#     )
#     print(f"ADSS_sub_CA potential: {potential}")
#     apm.add(
#         PSTAT_server,
#         "run_CA",
#         {
#             "Vval__V": potential,
#             "Tval__s": apm.pars.CA_duration_sec,
#             "SampleRate": apm.pars.samplerate_sec,
#             "IErange": "auto",
#         },
#         from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
#         start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
#     )

#     # take multiple scheduled liquid samples
#     apm.add(
#         PAL_server,
#         "PAL_archive",
#         {
#             "tool": PALtools.LS3,
#             "source": "cell1_we",
#             "volume_ul": 200,
#             "sampleperiod": apm.pars.aliquot_times_sec,  # 1min, 10min, 10min
#             "spacingmethod": Spacingmethod.custom,
#             "spacingfactor": 1.0,
#             "timeoffset": 60.0,
#             "wash1": 0,
#             "wash2": 0,
#             "wash3": 0,
#             "wash4": 0,
#         },
#         start_condition=ActionStartCondition.wait_for_endpoint,  # orch is waiting for all action_dq to finish
#     )

#     # take last liquid sample and clean
#     apm.add(
#         PAL_server,
#         "PAL_archive",
#         {
#             "tool": PALtools.LS3,
#             "source": "cell1_we",
#             "volume_ul": 200,
#             "sampleperiod": [0.0],
#             "spacingmethod": Spacingmethod.linear,
#             "spacingfactor": 1.0,
#             "timeoffset": 0.0,
#             "wash1": 1,  # dont use True or False but 0 AND 1
#             "wash2": 1,
#             "wash3": 1,
#             "wash4": 1,
#         },
#         start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
#     )

#     return apm.action_list  # returns complete action list to orch


# def ADSS_sub_preCV(
#     experiment: Experiment,
#     experiment_version: int = 3,
#     CA_potential: Optional[float] = 0.0,  # need to get from CV initial
#     ph: Optional[float] = 9.53,
#     ref_type: Optional[str] = "inhouse",
#     ref_offset__V: Optional[float] = 0.0,
#     gamry_i_range: Optional[str] = "auto",
#     samplerate_sec: Optional[float] = 0.05,
#     CA_duration_sec: Optional[float] = 3,  # adjustable pre_CV time
# ):
#     """last functionality test: 11/29/2021"""

#     apm = ActionPlanMaker()  # exposes function parameters via apm.pars

#     # get sample for gamry
#     apm.add(
#         PAL_server,
#         "archive_custom_query_sample",
#         {
#             "custom": "cell1_we",
#         },
#         to_globalexp_params=[
#             "_fast_samples_in"
#         ],  # save new liquid_sample_no of eche cell to globals
#         start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
#     )
#     # apply potential
#     potential = (
#         apm.pars.CA_potential
#         - 1.0 * apm.pars.ref_offset__V
#         - 0.059 * apm.pars.ph
#         - REF_TABLE[apm.pars.ref_type]
#     )
#     apm.add(
#         PSTAT_server,
#         "run_CA",
#         {
#             "Vval__V": potential,
#             "Tval__s": apm.pars.CA_duration_sec,
#             "SampleRate": apm.pars.samplerate_sec,
#             "IErange": apm.pars.gamry_i_range,
#         },
#         from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
#         start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
#         technique_name="CA",
#         process_finish=True,
#         process_contrib=[
#             ProcessContrib.files,
#             ProcessContrib.samples_in,
#             ProcessContrib.samples_out,
#         ],
#     )

#     return apm.action_list  # returns complete action list to orch

# def ADSS_sub_CA_noaliquots(
#     experiment: Experiment,
#     experiment_version: int = 2,
#     CA_potential: Optional[float] = 0.0,
#     ph: float = 9.53,
#     potential_versus: Optional[str] = "rhe",
#     ref_type: Optional[str] = "inhouse",
#     ref_offset__V: Optional[float] = 0.0,
#     gamry_i_range: Optional[str] = "auto",
#     samplerate_sec: Optional[float] = 0.05,
#     OCV_duration_sec: Optional[float] = 60,
#     CA_duration_sec: Optional[float] = 1320,
#     aliquot_times_sec: Optional[List[float]] = [60, 600, 1140],
# ):
#     """last functionality test: 11/29/2021"""

#     apm = ActionPlanMaker()  # exposes function parameters via apm.pars

#     # get sample for gamry
#     apm.add(
#         PAL_server,
#         "archive_custom_query_sample",
#         {
#             "custom": "cell1_we",
#         },
#         to_globalexp_params=[
#             "_fast_samples_in"
#         ],  # save new liquid_sample_no of eche cell to globals
#         start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
#     )

#     # OCV
#     apm.add(
#         PSTAT_server,
#         "run_OCV",
#         {
#             "Tval": apm.pars.OCV_duration_sec,
#             "SampleRate": apm.pars.samplerate_sec,
#             "IErange": apm.pars.gamry_i_range,
#         },
#         from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
#         start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
#         process_finish=False,
#         process_contrib=[
#             ProcessContrib.files,
#             ProcessContrib.samples_in,
#             ProcessContrib.samples_out,
#         ],
#     )

#     apm.add(
#         PAL_server,
#         "archive_custom_query_sample",
#         {
#             "custom": "cell1_we",
#         },
#         to_globalexp_params=[
#             "_fast_samples_in"
#         ],  # save new liquid_sample_no of eche cell to globals
#         start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
#     )

#     # apply potential
#     potential = (
#         apm.pars.CA_potential
#         - 1.0 * apm.pars.ref_offset__V
#         - 0.059 * apm.pars.ph
#         - REF_TABLE[apm.pars.ref_type]
#     )
#     print(f"ADSS_sub_CA potential: {potential}")
#     apm.add(
#         PSTAT_server,
#         "run_CA",
#         {
#             "Vval__V": potential,
#             "Tval__s": apm.pars.CA_duration_sec,
#             "SampleRate": apm.pars.samplerate_sec,
#             "IErange": "auto",
#         },
#         from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
#         start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
#         technique_name="CA",
#         process_finish=True,
#         process_contrib=[
#             ProcessContrib.files,
#             ProcessContrib.samples_in,
#             ProcessContrib.samples_out,
#         ],
#     )

#     return apm.action_list  # returns complete action list to orch


# def ADSS_sub_CV_noaliquots(
#     experiment: Experiment,
#     experiment_version: int = 2,
#     Vinit_vsRHE: Optional[float] = 0.0,  # Initial value in volts or amps.
#     Vapex1_vsRHE: Optional[float] = 1.0,  # Apex 1 value in volts or amps.
#     Vapex2_vsRHE: Optional[float] = -1.0,  # Apex 2 value in volts or amps.
#     Vfinal_vsRHE: Optional[float] = 0.0,  # Final value in volts or amps.
#     scanrate_voltsec: Optional[
#         float
#     ] = 0.02,  # scan rate in volts/second or amps/second.
#     samplerate_sec: Optional[float] = 0.1,
#     cycles: Optional[int] = 1,
#     gamry_i_range: Optional[str] = "auto",
#     ph: float = 9.53,
#     potential_versus: Optional[str] = "rhe",
#     ref_type: Optional[str] = "inhouse",
#     ref_offset__V: Optional[float] = 0.0,
#     aliquot_times_sec: Optional[List[float]] = [60, 600, 1140],
# ):

#     apm = ActionPlanMaker()  # exposes function parameters via apm.pars

#     CV_duration_sec = (
#         abs(apm.pars.Vapex1_vsRHE - apm.pars.Vinit_vsRHE) / apm.pars.scanrate_voltsec
#     )
#     CV_duration_sec += (
#         abs(apm.pars.Vfinal_vsRHE - apm.pars.Vapex2_vsRHE) / apm.pars.scanrate_voltsec
#     )
#     CV_duration_sec += (
#         abs(apm.pars.Vapex2_vsRHE - apm.pars.Vapex1_vsRHE)
#         / apm.pars.scanrate_voltsec
#         * apm.pars.cycles
#     )
#     CV_duration_sec += (
#         abs(apm.pars.Vapex2_vsRHE - apm.pars.Vapex1_vsRHE)
#         / apm.pars.scanrate_voltsec
#         * 2.0
#         * (apm.pars.cycles - 1)
#     )

#     # get sample for gamry
#     apm.add(
#         PAL_server,
#         "archive_custom_query_sample",
#         {
#             "custom": "cell1_we",
#         },
#         to_globalexp_params=[
#             "_fast_samples_in"
#         ],  # save new liquid_sample_no of eche cell to globals
#         start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
#     )

#     # apply potential

#     apm.add(
#         PSTAT_server,
#         "run_CV",
#         {
#             "Vinit__V": apm.pars.Vinit_vsRHE
#             - 1.0 * apm.pars.ref_offset__V
#             - REF_TABLE[apm.pars.ref_type]
#             - 0.059 * apm.pars.ph,
#             "Vapex1__V": apm.pars.Vapex1_vsRHE
#             - 1.0 * apm.pars.ref_offset__V
#             - REF_TABLE[apm.pars.ref_type]
#             - 0.059 * apm.pars.ph,
#             "Vapex2__V": apm.pars.Vapex2_vsRHE
#             - 1.0 * apm.pars.ref_offset__V
#             - REF_TABLE[apm.pars.ref_type]
#             - 0.059 * apm.pars.ph,
#             "Vfinal__V": apm.pars.Vfinal_vsRHE
#             - 1.0 * apm.pars.ref_offset__V
#             - REF_TABLE[apm.pars.ref_type]
#             - 0.059 * apm.pars.ph,
#             "ScanRate__V_s": apm.pars.scanrate_voltsec,
#             "AcqInterval__s": apm.pars.samplerate_sec,
#             "Cycles": apm.pars.cycles,
#             "IErange": apm.pars.gamry_i_range,
#         },
#         from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
#         start_condition=ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
#         technique_name="CV",
#         process_finish=True,
#         process_contrib=[
#             ProcessContrib.files,
#             ProcessContrib.samples_in,
#             ProcessContrib.samples_out,
#         ],
#     )

#     return apm.action_list  # returns complete action list to orch

 #valves/pumps for adss
    # apm.add(NI_server, "pump", {"pump": "peripump", "on": 0})
    # apm.add(NI_server, "pump", {"pump": "direction", "on": 0})
    # apm.add(ORCH_server, "wait", {"waittime": 0.25})
    # apm.add(NI_server, "gasvalve", {"gasvalve": "V1", "on": 1})
    # apm.add(NI_server, "gasvalve", {"gasvalve": "V2", "on": 1},start_condition=ActionStartCondition.no_wait)
    # apm.add(NI_server, "gasvalve", {"gasvalve": "V3", "on": 1},start_condition=ActionStartCondition.no_wait)
    # apm.add(NI_server, "gasvalve", {"gasvalve": "V4", "on": 0},start_condition=ActionStartCondition.no_wait)

    # apm.add(SOLUTIONPUMP_server, "infuse", {"rate_uL_sec": apm.pars.Syringe_rate_ulsec , "volume_uL": apm.pars.Solution_volume_ul + apm.pars.Syringe_retraction_ul},start_condition=ActionStartCondition.no_wait)
    # apm.add(ORCH_server, "wait", {"waittime": 0.25})
    # apm.add(WATERCLEANPUMP_server, "infuse", {"rate_uL_sec": apm.pars.Syringe_rate_ulsec, "volume_uL": apm.pars.Waterclean_volume_ul + apm.pars.Syringe_retraction_ul},start_condition=ActionStartCondition.no_wait)    
    # apm.add(ORCH_server, "wait", {"waittime": 0.25})


def ADSS_sub_cellfill(
    experiment: Experiment,
    experiment_version: int = 1,
    Solution_volume_ul: float = 3000,
    Syringe_rate_ulsec: float = 300,
    deadvolume_ul: int = 50,
    SyringeFillWait_s: float = 15,
    PurgeWait_s: float = 5,
    PressureEquibWait_s: float = 2,
):

    apm = ActionPlanMaker()
    apm.add(PAL_server, "archive_custom_query_sample", {"custom": "cell1_we",},
        to_globalexp_params=[
            "_fast_samples_in"
        ],  # save new liquid_sample_no of eche cell to globals
    )
    apm.add(NI_server, "gasvalve", {"gasvalve": "V1", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.PressureEquibWait_s})
    apm.add(NI_server, "gasvalve", {"gasvalve": "V3", "on": 1})
    apm.add(SOLUTIONPUMP_server, "withdraw", {"rate_uL_sec": apm.pars.Syringe_rate_ulsec , "volume_uL": apm.pars.Solution_volume_ul + apm.pars.deadvolume_ul})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.SyringeFillWait_s})
    apm.add(NI_server, "gasvalve", {"gasvalve": "V1", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.PurgeWait_s})
    apm.add(NI_server, "gasvalve", {"gasvalve": "V1", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.PressureEquibWait_s})
    apm.add(NI_server, "gasvalve", {"gasvalve": "V3", "on": 0})
    apm.add(SOLUTIONPUMP_server, "infuse", {"rate_uL_sec": apm.pars.Syringe_rate_ulsec , "volume_uL": apm.pars.Solution_volume_ul + apm.pars.deadvolume_ul},
        from_globalexp_params={"_fast_samples_in": "fast_samples_in"},
        technique_name="cell_fill",
        process_finish=True,
        process_contrib=[
            ProcessContrib.action_params,
            ProcessContrib.files,
            ProcessContrib.samples_in,
            ProcessContrib.samples_out,
        ],
    )
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.PressureEquibWait_s})
    apm.add(NI_server, "gasvalve", {"gasvalve": "V1", "on": 1})
 
    return apm.action_list

def ADSS_sub_drain_cell(
    experiment: Experiment,
    experiment_version: int = 1,
    FillLinePurgeWait_s: float = 10,
    DrainWait_s: float = 60,
):

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "V1", "on": 1},start_condition=ActionStartCondition.no_wait)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.FillLinePurgeWait_s})
    apm.add(NI_server, "gasvalve", {"gasvalve": "V4", "on": 1})
    apm.add(NI_server, "pump", {"pump": "direction", "on": 0})
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.DrainWait_s})
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "V4", "on": 0})
    apm.add(NI_server, "gasvalve", {"gasvalve": "V1", "on": 0})
 
    return apm.action_list

def ADSS_sub_empty_cell(
    experiment: Experiment,
    experiment_version: int = 1,
    ReversePurgeWait_s: float = 20,
):

    apm = ActionPlanMaker()
    apm.add(NI_server, "pump", {"pump": "direction", "on": 1})
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 0})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.ReversePurgeWait_s})
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 0})

    return apm.action_list


#need to move to clean spot first before beginning clean
def ADSS_sub_clean_cell(
    experiment: Experiment,
    experiment_version: int = 1,
    Clean_volume_ul: float = 3000,
    Syringe_rate_ulsec: float = 300,
    deadvolume_ul: int = 50,
    PurgeWait_s: float = 5,
    PressureEquibWait_s: float = 2,
):

    apm = ActionPlanMaker()
    apm.add(CLEANPUMP_server, "infuse", {"rate_uL_sec": apm.pars.Syringe_rate_ulsec , "volume_uL": apm.pars.Clean_volume_ul + apm.pars.deadvolume_ul})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.PressureEquibWait_s})
    apm.add(NI_server, "gasvalve", {"gasvalve": "V1", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.PurgeWait_s})
    apm.add(CLEANPUMP_server, "withdraw", {"rate_uL_sec": apm.pars.Syringe_rate_ulsec , "volume_uL": apm.pars.deadvolume_ul})

    return apm.action_list


def ADSS_sub_sample_aliquot(
    experiment: Experiment,
    experiment_version: int = 1,
    aliquot_volume_ul: Optional [int] = 200,
    EquilibrationTime_s: float = 30,
):

    apm = ActionPlanMaker()
    apm.add(PAL_server, "archive_custom_query_sample", {"custom": "cell1_we",},
        to_globalexp_params=[
            "_fast_samples_in"
        ],  # save new liquid_sample_no of eche cell to globals
    )
    apm.add(NI_server, "pump", {"pump": "direction", "on": 0})
    apm.add(NI_server, "pump", {"pump": "peripump", "on": 1})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.EquilibrationTime_s})
    apm.add(
        PAL_server,
        "PAL_archive",
        {
            "tool": PALtools.LS3,
            "source": "cell1_we",
            "volume_ul": apm.pars.aliquot_volume_ul,
            "sampleperiod": [0.0],
            "spacingmethod": Spacingmethod.custom,
            "spacingfactor": 1.0,
            "timeoffset": 60.0,
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
