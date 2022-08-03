"""
Experiment library for ADSS
server_key must be a FastAPI action server defined in config
"""

__all__ = [
    "debug",
    # "ADSS_duaribilty_CAv1",
    "ADSS_sub_startup",
    "ADSS_sub_shutdown",
    "ADSS_sub_engage",
    "ADSS_sub_disengage",
    "ADSS_sub_drain",
    "ADSS_sub_clean_PALtool",
    "ADSS_sub_CA",
    "ADSS_sub_unloadall_customs",
    "ADSS_sub_load_solid",
    "ADSS_sub_load_liquid",
    "ADSS_sub_fillfixed",
    "ADSS_sub_fill",
    "ADSS_sub_tray_unload",
    "ADSS_sub_CA_noaliquots", #only one with process contrib
    "ADSS_sub_CV_noaliquots", #only one with process contrib
    
]


from typing import Optional, List, Union
from socket import gethostname

from helao.helpers.premodels import Action, Experiment, ActionPlanMaker
from helaocore.models.action_start_condition import ActionStartCondition
from helaocore.models.sample import SolidSample, LiquidSample
from helaocore.models.machine import MachineModel
from helaocore.models.process_contrib import ProcessContrib
from helaocore.models.electrolyte import Electrolyte

from helao.drivers.motion.galil_motion_driver import MoveModes, TransformationModes
from helao.drivers.robot.pal_driver import Spacingmethod, PALtools


EXPERIMENTS = __all__

PSTAT_server = MachineModel(server_name="PSTAT", machine_name=gethostname()).json_dict()

MOTOR_server = MachineModel(server_name="MOTOR", machine_name=gethostname()).json_dict()

NI_server = MachineModel(server_name="NI", machine_name=gethostname()).json_dict()
ORCH_server = MachineModel(server_name="ORCH", machine_name=gethostname()).json_dict()
PAL_server = MachineModel(server_name="PAL", machine_name=gethostname()).json_dict()

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

    sq = ActionPlanMaker()  # exposes function parameters via sq.pars

    sq.add_action(
        {
            "action_server": PAL_server,
            "action_name": "archive_custom_unload",
            "action_params": {"custom": "cell1_we"},
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        }
    )

    sq.add_action(
        {
            "action_server": PAL_server,
            "action_name": "archive_custom_load",
            "action_params": {
                "custom": "cell1_we",
                "load_sample_in": SolidSample(
                    **{"sample_no": 1, "plate_id": 4534, "machine_name": "legacy"}
                ).dict(),
            },
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        }
    )

    sq.add_action(
        {
            "action_server": PAL_server,
            "action_name": "archive_custom_query_sample",
            "action_params": {
                "custom": "cell1_we",
            },
            "to_global_params": [
                "_fast_samples_in"
            ],  # save new liquid_sample_no of eche cell to globals
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        }
    )

    # OCV
    sq.add_action(
        {
            "action_server": PSTAT_server,
            "action_name": "run_OCV",
            "action_params": {
                "Tval": 10.0,
                "SampleRate": 1.0,
                "TTLwait": -1,  # -1 disables, else select TTL 0-3
                "TTLsend": -1,  # -1 disables, else select TTL 0-3
                "IErange": "auto",
            },
            "from_global_params": {"_fast_samples_in": "fast_samples_in"},
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        }
    )

    return sq.action_list  # returns complete action list to orch


def ADSS_sub_unloadall_customs(experiment: Experiment):
    """last functionality test: 11/29/2021"""

    sq = ActionPlanMaker()  # exposes function parameters via sq.pars

    sq.add_action(
        {
            "action_server": PAL_server,
            "action_name": "archive_custom_unloadall",
            "action_params": {},
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        }
    )

    return sq.action_list  # returns complete action list to orch


def ADSS_sub_load_solid(
    experiment: Experiment,
    experiment_version: int = 1,
    solid_custom_position: Optional[str] = "cell1_we",
    solid_plate_id: Optional[int] = 4534,
    solid_sample_no: Optional[int] = 1,
):
    """last functionality test: 11/29/2021"""

    sq = ActionPlanMaker()  # exposes function parameters via sq.pars
    sq.add_action(
        {
            "action_server": PAL_server,
            "action_name": "archive_custom_load",
            "action_params": {
                "custom": sq.pars.solid_custom_position,
                "load_sample_in": SolidSample(
                    **{
                        "sample_no": sq.pars.solid_sample_no,
                        "plate_id": sq.pars.solid_plate_id,
                        "machine_name": "legacy",
                    }
                ).dict(),
            },
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        }
    )
    return sq.action_list  # returns complete action list to orch


def ADSS_sub_load_liquid(
    experiment: Experiment,
    experiment_version: int = 1,
    liquid_custom_position: Optional[str] = "elec_res1",
    liquid_sample_no: Optional[int] = 1,
):
    """last functionality test: 11/29/2021"""

    sq = ActionPlanMaker()  # exposes function parameters via sq.pars
    sq.add_action(
        {
            "action_server": PAL_server,
            "action_name": "archive_custom_load",
            "action_params": {
                "custom": sq.pars.liquid_custom_position,
                "load_sample_in": LiquidSample(
                    **{
                        "sample_no": sq.pars.liquid_sample_no,
                        "machine_name": gethostname(),
                    }
                ).dict(),
            },
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        }
    )
    return sq.action_list  # returns complete action list to orch


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

    sq = ActionPlanMaker()  # exposes function parameters via sq.pars

    # unload all samples from custom positions
    sq.add_action_list(ADSS_sub_unloadall_customs(experiment=experiment))

    # load new requested samples
    sq.add_action_list(
        ADSS_sub_load_solid(
            experiment=experiment,
            solid_custom_position=sq.pars.solid_custom_position,
            solid_plate_id=sq.pars.solid_plate_id,
            solid_sample_no=sq.pars.solid_sample_no,
        )
    )

    sq.add_action_list(
        ADSS_sub_load_liquid(
            experiment=experiment,
            liquid_custom_position=sq.pars.liquid_custom_position,
            liquid_sample_no=sq.pars.liquid_sample_no,
        )
    )

    # turn pump off
    sq.add_action(
        {
            "action_server": NI_server,
            "action_name": "pump",
            "action_params": {
                "pump": "peripump",
                "on": 0,
            },
            "start_condition": ActionStartCondition.wait_for_all,
        }
    )

    # set pump flow forward
    sq.add_action(
        {
            "action_server": NI_server,
            "action_name": "pump",
            "action_params": {
                "pump": "direction",
                "on": 0,
            },
            "start_condition": ActionStartCondition.wait_for_all,
        }
    )

    # move z to home
    sq.add_action_list(ADSS_sub_disengage(experiment))

    # move to position
    sq.add_action(
        {
            "action_server": MOTOR_server,
            "action_name": "move",
            "action_params": {
                "d_mm": [sq.pars.x_mm, sq.pars.y_mm],
                "axis": ["x", "y"],
                "mode": MoveModes.absolute,
                "transformation": TransformationModes.platexy,
            },
            "save_act": debug_save_act,
            "save_data": debug_save_data,
            "start_condition": ActionStartCondition.wait_for_all,
        }
    )

    # seal cell
    sq.add_action_list(ADSS_sub_engage(experiment))

    return sq.action_list  # returns complete action list to orch


def ADSS_sub_shutdown(experiment: Experiment):
    """Sub experiment
    (1) Deep clean PAL tool
    (2) pump liquid out off cell
    (3) Drain cell
    (4) Disengages cell (TBD)

    last functionality test: 11/29/2021"""

    sq = ActionPlanMaker()  # exposes function parameters via sq.pars

    # deep clean
    sq.add_action_list(
        ADSS_sub_clean_PALtool(
            experiment, clean_tool=PALtools.LS3, clean_volume_ul=500
        )
    )
    # sq.add_action({
    #     "action_server": PAL_server,
    #     "action_name": "PAL_deepclean",
    #     "action_params": {
    #                       "tool": PALtools.LS3,
    #                       "volume_ul": 500,
    #                       },
    #     # "save_act": True,
    #     # "save_data": True,
    #     "start_condition": ActionStartCondition.wait_for_all,
    #     # "plate_id": None,
    #     })

    # set pump flow backward
    sq.add_action(
        {
            "action_server": NI_server,
            "action_name": "pump",
            "action_params": {
                "pump": "direction",
                "on": 1,
            },
            "start_condition": ActionStartCondition.wait_for_all,
        }
    )

    # wait some time to pump out the liquid
    sq.add_action(
        {
            "action_server": ORCH_server,
            "action_name": "wait",
            "action_params": {
                "waittime": 120,
            },
            "start_condition": ActionStartCondition.wait_for_all,
        }
    )

    # drain, TODO
    # sq.add_action_list(ADSS_sub_drain(experiment))

    # turn pump off
    sq.add_action(
        {
            "action_server": NI_server,
            "action_name": "pump",
            "action_params": {
                "pump": "peripump",
                "on": 0,
            },
            "start_condition": ActionStartCondition.wait_for_all,
        }
    )

    # set pump flow forward
    sq.add_action(
        {
            "action_server": NI_server,
            "action_name": "pump",
            "action_params": {
                "pump": "direction",
                "on": 0,
            },
            "start_condition": ActionStartCondition.wait_for_all,
        }
    )

    # move z to home
    # cannot do this without proper drain for now
    # sq.add_action_list(ADSS_sub_disengage(experiment))

    return sq.action_list  # returns complete action list to orch


def ADSS_sub_drain(experiment: Experiment):
    """DUMMY Sub experiment
    Drains electrochemical cell.

    last functionality test: 11/29/2021"""

    sq = ActionPlanMaker()  # exposes function parameters via sq.pars
    # TODO
    return sq.action_list  # returns complete action list to orch


def ADSS_sub_engage(experiment: Experiment):
    """Sub experiment
    Engages and seals electrochemical cell.

    last functionality test: 11/29/2021"""

    sq = ActionPlanMaker()  # exposes function parameters via sq.pars

    # engage
    sq.add_action(
        {
            "action_server": MOTOR_server,
            "action_name": "move",
            "action_params": {
                "d_mm": [z_engage],
                "axis": ["z"],
                "mode": MoveModes.absolute,
                "transformation": TransformationModes.instrxy,
            },
            "save_act": debug_save_act,
            "save_data": debug_save_data,
            "start_condition": ActionStartCondition.wait_for_all,
        }
    )

    # seal
    sq.add_action(
        {
            "action_server": MOTOR_server,
            "action_name": "move",
            "action_params": {
                "d_mm": [z_seal],
                "axis": ["z"],
                "mode": MoveModes.absolute,
                "transformation": TransformationModes.instrxy,
            },
            "save_act": debug_save_act,
            "save_data": debug_save_data,
            "start_condition": ActionStartCondition.wait_for_all,
        }
    )

    return sq.action_list  # returns complete action list to orch


def ADSS_sub_disengage(experiment: Experiment):
    """Sub experiment
    Disengages and seals electrochemical cell.

    last functionality test: 11/29/2021"""

    sq = ActionPlanMaker()  # exposes function parameters via sq.pars

    sq.add_action(
        {
            "action_server": MOTOR_server,
            "action_name": "move",
            "action_params": {
                "d_mm": [z_home],
                "axis": ["z"],
                "mode": MoveModes.absolute,
                "transformation": TransformationModes.instrxy,
            },
            "save_act": debug_save_act,
            "save_data": debug_save_data,
            "start_condition": ActionStartCondition.wait_for_all,
        }
    )

    return sq.action_list  # returns complete action list to orch


def ADSS_sub_clean_PALtool(
    experiment: Experiment,
    experiment_version: int = 1,
    clean_tool: Optional[str] = PALtools.LS3,
    clean_volume_ul: Optional[int] = 500,
):
    """Sub experiment
    Performs deep clean of selected PAL tool.

    last functionality test: 11/29/2021"""

    sq = ActionPlanMaker()  # exposes function parameters via sq.pars

    # deep clean
    sq.add_action(
        {
            "action_server": PAL_server,
            "action_name": "PAL_deepclean",
            "action_params": {
                "tool": sq.pars.clean_tool,
                "volume_ul": sq.pars.clean_volume_ul,
            },
            "start_condition": ActionStartCondition.wait_for_all,
        }
    )

    return sq.action_list  # returns complete action list to orch


def ADSS_sub_fillfixed(
    experiment: Experiment,
    experiment_version: int = 1,
    fill_vol_ul: Optional[int] = 10000,
    filltime_sec: Optional[float] = 10.0,
):
    sq = ActionPlanMaker()  # exposes function parameters via sq.pars

    # fill liquid, no wash (assume it was cleaned before)
    sq.add_action(
        {
            "action_server": PAL_server,
            "action_name": "PAL_fillfixed",
            "action_params": {
                "tool": PALtools.LS3,
                "source": "elec_res1",
                "dest": "cell1_we",
                "volume_ul": sq.pars.fill_vol_ul,
                "wash1": 0,
                "wash2": 0,
                "wash3": 0,
                "wash4": 0,
            },
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        }
    )

    # set pump flow forward
    sq.add_action(
        {
            "action_server": NI_server,
            "action_name": "pump",
            "action_params": {
                "pump": "direction",
                "on": 0,
            },
            "start_condition": ActionStartCondition.wait_for_all,
        }
    )

    # turn on pump
    sq.add_action(
        {
            "action_server": NI_server,
            "action_name": "pump",
            "action_params": {
                "pump": "peripump",
                "on": 1,
            },
            "start_condition": ActionStartCondition.wait_for_all,
        }
    )

    # wait some time to pump in the liquid
    sq.add_action(
        {
            "action_server": ORCH_server,
            "action_name": "wait",
            "action_params": {
                "waittime": sq.pars.filltime_sec,
            },
            "start_condition": ActionStartCondition.wait_for_all,
        }
    )

    return sq.action_list  # returns complete action list to orch


def ADSS_sub_fill(
    experiment: Experiment,
    experiment_version: int = 1,
    fill_vol_ul: Optional[int] = 1000,
):
    sq = ActionPlanMaker()  # exposes function parameters via sq.pars

    # fill liquid, no wash (assume it was cleaned before)
    sq.add_action(
        {
            "action_server": PAL_server,
            "action_name": "PAL_fill",
            "action_params": {
                "tool": PALtools.LS3,
                "source": "elec_res1",
                "dest": "cell1_we",
                "volume_ul": sq.pars.fill_vol_ul,
                "wash1": 0,
                "wash2": 0,
                "wash3": 0,
                "wash4": 0,
            },
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        }
    )

    return sq.action_list  # returns complete action list to orch


def ADSS_sub_CA(
    experiment: Experiment,
    experiment_version: int = 1,
    CA_potential: Optional[float] = 0.0,
    ph: float = 9.53,
    ref_vs_nhe: float = 0.21,
    samplerate_sec: Optional[float] = 1,
    OCV_duration_sec: Optional[float] = 60,
    CA_duration_sec: Optional[float] = 1320,
    aliquot_times_sec: Optional[List[float]] = [60, 600, 1140],
):
    """last functionality test: 11/29/2021"""

    sq = ActionPlanMaker()  # exposes function parameters via sq.pars

    # get sample for gamry
    sq.add_action(
        {
            "action_server": PAL_server,
            "action_name": "archive_custom_query_sample",
            "action_params": {
                "custom": "cell1_we",
            },
            "to_global_params": [
                "_fast_samples_in"
            ],  # save new liquid_sample_no of eche cell to globals
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        }
    )

    # OCV
    sq.add_action(
        {
            "action_server": PSTAT_server,
            "action_name": "run_OCV",
            "action_params": {
                "Tval": sq.pars.OCV_duration_sec,
                "SampleRate": sq.pars.samplerate_sec,
                "TTLwait": -1,  # -1 disables, else select TTL 0-3
                "TTLsend": -1,  # -1 disables, else select TTL 0-3
                "IErange": "auto",
            },
            "from_global_params": {"_fast_samples_in": "fast_samples_in"},
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        }
    )

    # take liquid sample
    sq.add_action(
        {
            "action_server": PAL_server,
            "action_name": "PAL_archive",
            "action_params": {
                "tool": PALtools.LS3,
                "source": "cell1_we",
                "volume_ul": 200,
                "sampleperiod": [0.0],
                "spacingmethod": Spacingmethod.linear,
                "spacingfactor": 1.0,
                "timeoffset": 0.0,
                "wash1": 0,
                "wash2": 0,
                "wash3": 0,
                "wash4": 0,
            },
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        }
    )

    sq.add_action(
        {
            "action_server": PAL_server,
            "action_name": "archive_custom_query_sample",
            "action_params": {
                "custom": "cell1_we",
            },
            "to_global_params": [
                "_fast_samples_in"
            ],  # save new liquid_sample_no of eche cell to globals
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        }
    )

    # apply potential
    potential = sq.pars.CA_potential - 1.0 * sq.pars.ref_vs_nhe - 0.059 * sq.pars.ph
    print(f"ADSS_sub_CA potential: {potential}")
    sq.add_action(
        {
            "action_server": PSTAT_server,
            "action_name": "run_CA",
            "action_params": {
                "Vval": potential,
                "Tval": sq.pars.CA_duration_sec,
                "SampleRate": sq.pars.samplerate_sec,
                "TTLwait": -1,  # -1 disables, else select TTL 0-3
                "TTLsend": -1,  # -1 disables, else select TTL 0-3
                "IErange": "auto",
            },
            "from_global_params": {"_fast_samples_in": "fast_samples_in"},
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        }
    )

    # take multiple scheduled liquid samples
    sq.add_action(
        {
            "action_server": PAL_server,
            "action_name": "PAL_archive",
            "action_params": {
                "tool": PALtools.LS3,
                "source": "cell1_we",
                "volume_ul": 200,
                "sampleperiod": sq.pars.aliquot_times_sec,  # 1min, 10min, 10min
                "spacingmethod": Spacingmethod.custom,
                "spacingfactor": 1.0,
                "timeoffset": 60.0,
                "wash1": 0,
                "wash2": 0,
                "wash3": 0,
                "wash4": 0,
            },
            "start_condition": ActionStartCondition.wait_for_endpoint,  # orch is waiting for all action_dq to finish
        }
    )

    # take last liquid sample and clean
    sq.add_action(
        {
            "action_server": PAL_server,
            "action_name": "PAL_archive",
            "action_params": {
                "tool": PALtools.LS3,
                "source": "cell1_we",
                "volume_ul": 200,
                "sampleperiod": [0.0],
                "spacingmethod": Spacingmethod.linear,
                "spacingfactor": 1.0,
                "timeoffset": 0.0,
                "wash1": 1,  # dont use True or False but 0 AND 1
                "wash2": 1,
                "wash3": 1,
                "wash4": 1,
            },
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        }
    )

    return sq.action_list  # returns complete action list to orch



def ADSS_sub_CA_noaliquots(
    experiment: Experiment,
    experiment_version: int = 1,
    CA_potential: Optional[float] = 0.0,
    ph: float = 9.53,
    ref_vs_nhe: float = 0.21,
    samplerate_sec: Optional[float] = .05,
    OCV_duration_sec: Optional[float] = 60,
    CA_duration_sec: Optional[float] = 1320,
    aliquot_times_sec: Optional[List[float]] = [60, 600, 1140],
):
    """last functionality test: 11/29/2021"""

    sq = ActionPlanMaker()  # exposes function parameters via sq.pars

    # get sample for gamry
    sq.add_action(
        {
            "action_server": PAL_server,
            "action_name": "archive_custom_query_sample",
            "action_params": {
                "custom": "cell1_we",
            },
            "to_global_params": [
                "_fast_samples_in"
            ],  # save new liquid_sample_no of eche cell to globals
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        }
    )

    # OCV
    sq.add_action(
        {
            "action_server": PSTAT_server,
            "action_name": "run_OCV",
            "action_params": {
                "Tval": sq.pars.OCV_duration_sec,
                "SampleRate": sq.pars.samplerate_sec,
                "TTLwait": -1,  # -1 disables, else select TTL 0-3
                "TTLsend": -1,  # -1 disables, else select TTL 0-3
                "IErange": "auto",
            },
            "from_global_params": {"_fast_samples_in": "fast_samples_in"},
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "process_finish": False,
            "process_contrib": [
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],

        }
    )


    sq.add_action(
        {
            "action_server": PAL_server,
            "action_name": "archive_custom_query_sample",
            "action_params": {
                "custom": "cell1_we",
            },
            "to_global_params": [
                "_fast_samples_in"
            ],  # save new liquid_sample_no of eche cell to globals
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        }
    )

    # apply potential
    potential = sq.pars.CA_potential - 1.0 * sq.pars.ref_vs_nhe - 0.059 * sq.pars.ph
    print(f"ADSS_sub_CA potential: {potential}")
    sq.add_action(
        {
            "action_server": PSTAT_server,
            "action_name": "run_CA",
            "action_params": {
                "Vval": potential,
                "Tval": sq.pars.CA_duration_sec,
                "SampleRate": sq.pars.samplerate_sec,
                "TTLwait": -1,  # -1 disables, else select TTL 0-3
                "TTLsend": -1,  # -1 disables, else select TTL 0-3
                "IErange": "auto",
            },
            "from_global_params": {"_fast_samples_in": "fast_samples_in"},
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "technique_name": "CA",
            "process_finish": True,
            "process_contrib": [
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        }
    )

    return sq.action_list  # returns complete action list to orch

def ADSS_sub_CV_noaliquots(
    experiment: Experiment,
    experiment_version: int = 1,
    Vinit_vsRHE: Optional[float] = 0.0,  # Initial value in volts or amps.
    Vapex1_vsRHE: Optional[float] = 1.0,  # Apex 1 value in volts or amps.
    Vapex2_vsRHE: Optional[float] = -1.0,  # Apex 2 value in volts or amps.
    Vfinal_vsRHE: Optional[float] = 0.0,  # Final value in volts or amps.
    scanrate_voltsec: Optional[float] = 0.02,  # scan rate in volts/second or amps/second.
    samplerate_sec: Optional[float] = 0.1,
    cycles: Optional[int] = 1,
    gamry_i_range: Optional[str] = "auto",
    ph: float = 9.53,
    ref_vs_nhe: float = 0.21,
    aliquot_times_sec: Optional[List[float]] = [60, 600, 1140],
):

    
    apm = ActionPlanMaker()  # exposes function parameters via sq.pars

    CV_duration_sec = (
        abs(apm.pars.Vapex1_vsRHE - apm.pars.Vinit_vsRHE) / apm.pars.scanrate_voltsec
    )
    CV_duration_sec += (
        abs(apm.pars.Vfinal_vsRHE - apm.pars.Vapex2_vsRHE) / apm.pars.scanrate_voltsec
    )
    CV_duration_sec += (
        abs(apm.pars.Vapex2_vsRHE - apm.pars.Vapex1_vsRHE) / apm.pars.scanrate_voltsec * apm.pars.cycles
    )
    CV_duration_sec += (
        abs(apm.pars.Vapex2_vsRHE - apm.pars.Vapex1_vsRHE) / apm.pars.scanrate_voltsec * 2.0 * (apm.pars.cycles - 1)
    )

    # get sample for gamry
    apm.add_action(
        {
            "action_server": PAL_server,
            "action_name": "archive_custom_query_sample",
            "action_params": {
                "custom": "cell1_we",
            },
            "to_global_params": [
                "_fast_samples_in"
            ],  # save new liquid_sample_no of eche cell to globals
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        }
    )

    # apply potential



    apm.add_action(
        {
            "action_server": PSTAT_server,
            "action_name": "run_CV",
            "action_params": {
                "Vinit__V": apm.pars.Vinit_vsRHE
                - 1.0 * apm.pars.ref_vs_nhe
                - 0.059 * apm.pars.ph,
                "Vapex1__V": apm.pars.Vapex1_vsRHE
                - 1.0 * apm.pars.ref_vs_nhe
                - 0.059 * apm.pars.ph,
                "Vapex2__V": apm.pars.Vapex2_vsRHE
                - 1.0 * apm.pars.ref_vs_nhe
                - 0.059 * apm.pars.ph,
                "Vfinal__V": apm.pars.Vfinal_vsRHE
                - 1.0 * apm.pars.ref_vs_nhe
                - 0.059 * apm.pars.ph,
                "ScanRate__V_s": apm.pars.scanrate_voltsec,
                "AcqInterval__s": apm.pars.samplerate_sec,
                "Cycles": apm.pars.cycles,
                "TTLwait": -1,  # -1 disables, else select TTL 0-3
                "TTLsend": 0,  # -1 disables, else select TTL 0-3
                "IErange": apm.pars.gamry_i_range,
            },
            "from_global_params": {"_fast_samples_in": "fast_samples_in"},
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "technique_name": "CV",
            "process_finish": True,
            "process_contrib": [
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        }
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

    sq = ActionPlanMaker()  # exposes function parameters via sq.pars

    sq.add_action(
        {
            "action_server": PAL_server,
            "action_name": "archive_tray_export_json",
            "action_params": {
                "tray": sq.pars.tray,
                "slot": sq.pars.slot,
            },
            "start_condition": ActionStartCondition.wait_for_all,
        }
    )

    sq.add_action(
        {
            "action_server": PAL_server,
            "action_name": "archive_tray_export_csv",
            "action_params": {
                "tray": sq.pars.tray,
                "slot": sq.pars.slot,
            },
            "start_condition": ActionStartCondition.wait_for_all,
        }
    )

    sq.add_action(
        {
            "action_server": PAL_server,
            "action_name": "archive_tray_export_icpms",
            "action_params": {
                "tray": sq.pars.tray,
                "slot": sq.pars.slot,
                "survey_runs": sq.pars.survey_runs,
                "main_runs": sq.pars.main_runs,
                "rack": sq.pars.rack,
            },
            "start_condition": ActionStartCondition.wait_for_all,
        }
    )

    sq.add_action(
        {
            "action_server": PAL_server,
            "action_name": "archive_tray_unload",
            "action_params": {
                "tray": sq.pars.tray,
                "slot": sq.pars.slot,
            },
            "start_condition": ActionStartCondition.wait_for_all,
        }
    )

    return sq.action_list  # returns complete action list to orch
