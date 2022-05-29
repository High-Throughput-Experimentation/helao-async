"""
Experiment library for ECHE
server_key must be a FastAPI action server defined in config
"""

__all__ = [
    "ECHE_slave_unloadall_customs",
    "ECHE_slave_load_solid",
    "ECHE_slave_add_liquid",
    "ECHE_slave_startup",
    "ECHE_slave_shutdown",
    "ECHE_slave_CA_led",
    "ECHE_slave_CA",
    "ECHE_slave_CV_led",
    "ECHE_slave_CV",
    "ECHE_slave_background",
    "ECHE_slave_CP_led",
    "ECHE_slave_CP",
    "ECHE_slave_movetosample",
    "ECHE_slave_move",
    "ECHE_slave_CV_led_secondtrigger",
    "ECHE_slave_CA_led_secondtrigger",
    "ECHE_slave_CP_led_secondtrigger",

]


from typing import Optional, List, Union
from socket import gethostname

from helaocore.schema import Action, Experiment, ActionPlanMaker
from helaocore.model.action_start_condition import ActionStartCondition
from helaocore.model.sample import SolidSample, LiquidSample
from helaocore.model.machine import MachineModel
from helaocore.model.process_contrib import ProcessContrib
from helaocore.model.electrolyte import Electrolyte

from helao.driver.motion.enum import MoveModes, TransformationModes
from helao.driver.robot.enum import PALtools, Spacingmethod


EXPERIMENTS = __all__

PSTAT_server = MachineModel(server_name="PSTAT", machine_name=gethostname()).json_dict()

MOTOR_server = MachineModel(server_name="MOTOR", machine_name=gethostname()).json_dict()
IO_server = MachineModel(server_name="IO", machine_name=gethostname()).json_dict()


ORCH_server = MachineModel(server_name="ORCH", machine_name=gethostname()).json_dict()
PAL_server = MachineModel(server_name="PAL", machine_name=gethostname()).json_dict()

toggle_triggertype = "fallingedge"


def ECHE_slave_unloadall_customs(experiment: Experiment):
    """last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    apm.add_action(
        {
            "action_server": PAL_server,
            "action_name": "archive_custom_unloadall",
            "action_params": {
                "destroy_liquid": True,
            },
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        }
    )

    return apm.action_list  # returns complete action list to orch


def ECHE_slave_add_liquid(
    experiment: Experiment,
    experiment_version: int = 1,
    solid_custom_position: Optional[str] = "cell1_we",
    reservoir_liquid_sample_no: Optional[int] = 1,
    reservoir_bubbler_gas: Optional[str] = "O2",
    liquid_volume_ml: Optional[float] = 1.0,
):
    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    apm.add_action(
        {
            "action_server": PAL_server,
            "action_name": "archive_custom_add_liquid",
            "action_params": {
                "custom": apm.pars.solid_custom_position,
                "source_liquid_in": LiquidSample(
                    **{
                        "sample_no": apm.pars.reservoir_liquid_sample_no,
                        "machine_name": gethostname(),
                    }
                ).dict(),
                "volume_ml": apm.pars.liquid_volume_ml,
                "reservoir_bubbler_gas" : apm.pars.reservoir_bubbler_gas,
                
                "combine_liquids": True,
                "dilute_liquids": True,
            },
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        }
    )

    return apm.action_list  # returns complete action list to orch


def ECHE_slave_load_solid(
    experiment: Experiment,
    experiment_version: int = 1,
    solid_custom_position: Optional[str] = "cell1_we",
    solid_plate_id: Optional[int] = 4534,
    solid_sample_no: Optional[int] = 1,
):
    """last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    apm.add_action(
        {
            "action_server": PAL_server,
            "action_name": "archive_custom_load",
            "action_params": {
                "custom": apm.pars.solid_custom_position,
                "load_sample_in": SolidSample(
                    **{
                        "sample_no": apm.pars.solid_sample_no,
                        "plate_id": apm.pars.solid_plate_id,
                        "machine_name": "legacy",
                    }
                ).dict(),
            },
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
        }
    )

    return apm.action_list  # returns complete action list to orch


def ECHE_slave_startup(
    experiment: Experiment,
    experiment_version: int = 1,
    solid_custom_position: Optional[str] = "cell1_we",
    solid_plate_id: Optional[int] = 4534,
    solid_sample_no: Optional[int] = 1,
    reservoir_liquid_sample_no: Optional[int] = 1,
    reservoir_bubbler_gas: Optional[str] = "N2",
    liquid_volume_ml: Optional[float] = 1.0,
):
    """Slave experiment
    last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # unload all samples from custom positions
    apm.add_action_list(ECHE_slave_unloadall_customs(experiment=experiment))

    # load new requested solid samples
    apm.add_action_list(
        ECHE_slave_load_solid(
            experiment=experiment,
            solid_custom_position=apm.pars.solid_custom_position,
            solid_plate_id=apm.pars.solid_plate_id,
            solid_sample_no=apm.pars.solid_sample_no,
        )
    )

    # add liquid to solid
    apm.add_action_list(
        ECHE_slave_add_liquid(
            experiment=experiment,
            solid_custom_position=apm.pars.solid_custom_position,
            reservoir_liquid_sample_no=apm.pars.reservoir_liquid_sample_no,
            reservoir_bubbler_gas=apm.pars.reservoir_bubbler_gas,
            liquid_volume_ml=apm.pars.liquid_volume_ml,
        )
    )

    # get sample plate coordinates
    apm.add_action(
        {
            "action_server": MOTOR_server,
            "action_name": "solid_get_samples_xy",
            "action_params": {
                "plate_id": apm.pars.solid_plate_id,
                "sample_no": apm.pars.solid_sample_no,
            },
            "to_global_params": [
                "_platexy"
            ],  # save new liquid_sample_no of eche cell to globals
            "start_condition": ActionStartCondition.wait_for_all,
        }
    )

    # move to position
    apm.add_action(
        {
            "action_server": MOTOR_server,
            "action_name": "move",
            "action_params": {
                # "d_mm": [apm.pars.x_mm, apm.pars.y_mm],
                "axis": ["x", "y"],
                "mode": MoveModes.absolute,
                "transformation": TransformationModes.platexy,
            },
            "from_global_params": {"_platexy": "d_mm"},
            "start_condition": ActionStartCondition.wait_for_all,
        }
    )

    return apm.action_list  # returns complete action list to orch


def ECHE_slave_shutdown(experiment: Experiment):
    """Slave experiment

    last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

    # unload all samples from custom positions
    apm.add_action_list(ECHE_slave_unloadall_customs(experiment=experiment))

    return apm.action_list  # returns complete action list to orch


def ECHE_slave_CA_led(
    experiment: Experiment,
    experiment_version: int = 1,
    CA_potential_vsRHE: Optional[float] = 0.0,
    ph: float = 9.53,
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1, #currently liquid sample database number
    reservoir_bubbler_gas: str = "O2",
    droplet_size_cm2: float = .071,  #3mm diameter droplet
    reference_electrode_type: str = "NHE",
    ref_vs_nhe: float = 0.21,
    samplerate_sec: Optional[float] = 0.1,
    CA_duration_sec: Optional[float] = 60,
    IErange: Optional[str] = "auto",
    led: Optional[str] = "doric_led1",
    wavelength_nm: Optional[float] = 0.0,
    wavelength_intensity_mw: Optional[float] = 0.0,
    wavelength_intensity_date: Optional[str] = "n/a",
    led_side_illumination: Optional[str] = "front",
    toggle_on_ms: Optional[float] = 1000,
    toggle_off_ms: Optional[float] = 1000,
    toggle_offset_ms: Optional[int] = 0,
    toggle_duration_ms: Optional[int] = -1,
    comment: Optional[str] = "",
):
    """last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

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

    # setup toggle on galil_io
    apm.add_action(
        {
            "action_server": IO_server,
            "action_name": "set_digital_cycle",
            "action_params": {
                "trigger_item": "gamry_ttl0",
                "triggertype": toggle_triggertype,
                "out_item": apm.pars.led,
                "out_item_gamry": "gamry_aux",
                "t_on": apm.pars.toggle_on_ms,
                "t_off": apm.pars.toggle_off_ms,
                "t_offset": apm.pars.toggle_offset_ms,
                "t_duration": apm.pars.toggle_duration_ms,
                "t_on2": apm.pars.toggle_on_ms,
                "t_off2": apm.pars.toggle_off_ms,
                "t_offset2": apm.pars.toggle_offset_ms,
                "t_duration2": apm.pars.toggle_duration_ms,
#                "mainthread": 0,
#                "subthread": 1,
            },
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "process_finish": False,
            "process_contrib": [
                ProcessContrib.action_params,
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        },

    )

    # apply potential
    potential = (
        apm.pars.CA_potential_vsRHE - 1.0 * apm.pars.ref_vs_nhe - 0.059 * apm.pars.ph
    )
    print(f"ADSS_slave_CA potential: {potential}")
    apm.add_action(
        {
            "action_server": PSTAT_server,
            "action_name": "run_CA",
            "action_params": {
                "Vval__V": potential,
                "Tval__s": apm.pars.CA_duration_sec,
                "AcqInterval__s": apm.pars.samplerate_sec,
                "TTLwait": -1,  # -1 disables, else select TTL 0-3
                "TTLsend": 0,  # -1 disables, else select TTL 0-3
                "IErange": apm.pars.IErange,
            },
            "from_global_params": {"_fast_samples_in": "fast_samples_in"},
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "process_finish": True,
            "process_contrib": [
                ProcessContrib.action_params,
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        },

    )

    return apm.action_list  # returns complete action list to orch


def ECHE_slave_CA(
    experiment: Experiment,
    experiment_version: int = 1,
    CA_potential_vsRHE: Optional[float] = 0.0,
    ph: float = 9.53,
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1, #currently liquid sample database number
    reservoir_bubbler_gas: str = "O2",
    droplet_size_cm2: float = .071,  #3mm diameter droplet
    reference_electrode_type: str = "NHE",
    ref_vs_nhe: float = 0.21,
    samplerate_sec: Optional[float] = 0.1,
    CA_duration_sec: Optional[float] = 60,
    IErange: Optional[str] = "auto",
    comment: Optional[str] = "",
):
    """last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

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
    potential = (
        apm.pars.CA_potential_vsRHE - 1.0 * apm.pars.ref_vs_nhe - 0.059 * apm.pars.ph
    )
    print(f"ADSS_slave_CA potential: {potential}")
    apm.add_action(
        {
            "action_server": PSTAT_server,
            "action_name": "run_CA",
            "action_params": {
                "Vval__V": potential,
                "Tval__s": apm.pars.CA_duration_sec,
                "AcqInterval__s": apm.pars.samplerate_sec,
                "TTLwait": -1,  # -1 disables, else select TTL 0-3
                "TTLsend": -1,  # -1 disables, else select TTL 0-3
                "IErange": apm.pars.IErange,
            },
            "from_global_params": {"_fast_samples_in": "fast_samples_in"},
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "process_finish": True,
            "process_contrib": [
                ProcessContrib.action_params,
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        },
    )

    return apm.action_list  # returns complete action list to orch


def ECHE_slave_CV_led(
    experiment: Experiment,
    experiment_version: int = 1,
    Vinit_vsRHE: Optional[float] = 0.0,  # Initial value in volts or amps.
    Vapex1_vsRHE: Optional[float] = 1.0,  # Apex 1 value in volts or amps.
    Vapex2_vsRHE: Optional[float] = -1.0,  # Apex 2 value in volts or amps.
    Vfinal_vsRHE: Optional[float] = 0.0,  # Final value in volts or amps.
    scanrate_voltsec: Optional[
        float
    ] = 0.02,  # scan rate in volts/second or amps/second.
    samplerate_sec: Optional[float] = 0.1,
    cycles: Optional[int] = 1,
    IErange: Optional[str] = "auto",
    ph: float = 0,
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1, #currently liquid sample database number
    reservoir_bubbler_gas: str = "O2",
    droplet_size_cm2: float = .071,  #3mm diameter droplet
    reference_electrode_type: str = "NHE",
    ref_vs_nhe: float = 0.21,
    led: Optional[str] = "doric_led1",
    wavelength_nm: Optional[float] = 0.0,
    wavelength_intensity_mw: Optional[float] = 0.0,
    wavelength_intensity_date: Optional[str] = "n/a",
    led_side_illumination: Optional[str] = "front",
    toggle_on_ms: Optional[float] = 1000,
    toggle_off_ms: Optional[float] = 1000,
    toggle_offset_ms: Optional[int] = 0,
    toggle_duration_ms: Optional[int] = -1,
    comment: Optional[str] = "",
):
    """last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

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

    # setup toggle on galil_io
    apm.add_action(
        {
            "action_server": IO_server,
            "action_name": "set_digital_cycle",
            "action_params": {
                "trigger_item": "gamry_ttl0",
                "triggertype": toggle_triggertype,
                "out_item": apm.pars.led,
                "out_item_gamry": "gamry_aux",
                "t_on": apm.pars.toggle_on_ms,
                "t_off": apm.pars.toggle_off_ms,
                "t_offset": apm.pars.toggle_offset_ms,
                "t_duration": apm.pars.toggle_duration_ms,
                "t_on2": apm.pars.toggle_on_ms,
                "t_off2": apm.pars.toggle_off_ms,
                "t_offset2": apm.pars.toggle_offset_ms,
                "t_duration2": apm.pars.toggle_duration_ms,
#                "mainthread": 0,
#                "subthread": 1,
            },
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "process_finish": False,
            "process_contrib": [
                ProcessContrib.action_params,
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        },
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
                "IErange": apm.pars.IErange,
            },
            "from_global_params": {"_fast_samples_in": "fast_samples_in"},
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "process_finish": True,
            "process_contrib": [
                ProcessContrib.action_params,
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        },
    )

    return apm.action_list  # returns complete action list to orch


def ECHE_slave_CV(
    experiment: Experiment,
    experiment_version: int = 1,
    Vinit_vsRHE: Optional[float] = 0.0,  # Initial value in volts or amps.
    Vapex1_vsRHE: Optional[float] = 1.0,  # Apex 1 value in volts or amps.
    Vapex2_vsRHE: Optional[float] = -1.0,  # Apex 2 value in volts or amps.
    Vfinal_vsRHE: Optional[float] = 0.0,  # Final value in volts or amps.
    scanrate_voltsec: Optional[
        float
    ] = 0.020,  # scan rate in volts/second or amps/second.
    samplerate_sec: Optional[float] = 0.1,
    cycles: Optional[int] = 1,
    IErange: Optional[str] = "auto",
    ph: float = 0,
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1, #currently liquid sample database number
    reservoir_bubbler_gas: str = "O2",
    droplet_size_cm2: float = .071,  #3mm diameter droplet
    reference_electrode_type: str = "NHE",
    ref_vs_nhe: float = 0.21,
    comment: Optional[str] = "",
):
    """last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

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
                "TTLsend": -1,  # -1 disables, else select TTL 0-3
                "IErange": apm.pars.IErange,
            },
            "from_global_params": {"_fast_samples_in": "fast_samples_in"},
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "process_finish": True,
            "process_contrib": [
                ProcessContrib.action_params,
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        },
    )

    return apm.action_list  # returns complete action list to orch


def ECHE_slave_CP(
    experiment: Experiment,
    experiment_version: int = 1,
    CP_current: Optional[float] = 0.0,
    ph: float = 9.53,
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1, #currently liquid sample database number
    reservoir_bubbler_gas: str = "O2",
    droplet_size_cm2: float = .071,  #3mm diameter droplet
    reference_electrode_type: str = "NHE",
    ref_vs_nhe: float = 0.21,
    samplerate_sec: Optional[float] = 0.1,
    CP_duration_sec: Optional[float] = 60,
    IErange: Optional[str] = "auto",
    comment: Optional[str] = "",
):
    """last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

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

#    # apply potential
 #   potential = (
#        apm.pars.CA_potential_vsRHE - 1.0 * apm.pars.ref_vs_nhe - 0.059 * apm.pars.ph
#    )
#    print(f"ADSS_slave_CA potential: {potential}")
    apm.add_action(
        {
            "action_server": PSTAT_server,
            "action_name": "run_CP",
            "action_params": {
                "Ival__A": CP_current,
                "Tval__s": apm.pars.CP_duration_sec,
                "AcqInterval__s": apm.pars.samplerate_sec,
                "TTLwait": -1,  # -1 disables, else select TTL 0-3
                "TTLsend": -1,  # -1 disables, else select TTL 0-3
                "IErange": apm.pars.IErange,
            },
            "from_global_params": {"_fast_samples_in": "fast_samples_in"},
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "process_finish": True,
            "process_contrib": [
                ProcessContrib.action_params,
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        },
    )

    return apm.action_list  # returns complete action list to orch

def ECHE_slave_CP_led(
    experiment: Experiment,
    experiment_version: int = 1,
    CP_current: Optional[float] = 0.0,
    ph: float = 9.53,
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1, #currently liquid sample database number
    reservoir_bubbler_gas: str = "O2",
    droplet_size_cm2: float = .071,  #3mm diameter droplet
    reference_electrode_type: str = "NHE",
    ref_vs_nhe: float = 0.21,
    samplerate_sec: Optional[float] = 0.1,
    CP_duration_sec: Optional[float] = 60,
    IErange: Optional[str] = "auto",
    led: Optional[str] = "doric_led1",
    wavelength_nm: Optional[float] = 0.0,
    wavelength_intensity_mw: Optional[float] = 0.0,
    wavelength_intensity_date: Optional[str] = "n/a",
    led_side_illumination: Optional[str] = "front",
    toggle_on_ms: Optional[float] = 1000,
    toggle_off_ms: Optional[float] = 1000,
    toggle_offset_ms: Optional[int] = 0,
    toggle_duration_ms: Optional[int] = -1,
    comment: Optional[str] = "",
):
    """last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

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

    # setup toggle on galil_io
    apm.add_action(
        {
            "action_server": IO_server,
            "action_name": "set_digital_cycle",
            "action_params": {
                "trigger_item": "gamry_ttl0",
                "triggertype": toggle_triggertype,
                "out_item": apm.pars.led,
                "out_item_gamry": "gamry_aux",
                "t_on": apm.pars.toggle_on_ms,
                "t_off": apm.pars.toggle_off_ms,
                "t_offset": apm.pars.toggle_offset_ms,
                "t_duration": apm.pars.toggle_duration_ms,
                "t_on2": apm.pars.toggle_on_ms,
                "t_off2": apm.pars.toggle_off_ms,
                "t_offset2": apm.pars.toggle_offset_ms,
                "t_duration2": apm.pars.toggle_duration_ms,
#                "mainthread": 0,
#                "subthread": 1,
            },
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "process_finish": False,
            "process_contrib": [
                ProcessContrib.action_params,
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        },

    )

    apm.add_action(
        {
            "action_server": PSTAT_server,
            "action_name": "run_CP",
            "action_params": {
                "Ival__A": CP_current,
                "Tval__s": apm.pars.CP_duration_sec,
                "AcqInterval__s": apm.pars.samplerate_sec,
                "TTLwait": -1,  # -1 disables, else select TTL 0-3
                "TTLsend": 0,  # -1 disables, else select TTL 0-3
                "IErange": apm.pars.IErange,
            },
            "from_global_params": {"_fast_samples_in": "fast_samples_in"},
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "process_finish": True,
            "process_contrib": [
                ProcessContrib.action_params,
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        },

    )

    return apm.action_list  # returns complete action list to orch

def ECHE_slave_background(
    experiment: Experiment,
    experiment_version: int = 1,
    CP_current: [float] = 0.0,
    ph: float = 9.53,
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1, #currently liquid sample database number
    reservoir_bubbler_gas: str = "O2",
    droplet_size_cm2: float = .071,  #3mm diameter droplet
    reference_electrode_type: str = "NHE",
    ref_vs_nhe: float = 0.21,
    samplerate_sec: Optional[float] = 0.1,
    background_duration_sec: Optional[float] = 60,
    IErange: Optional[str] = "auto",
    toggle_on_ms: Optional[float] = 1000,
    toggle_off_ms: Optional[float] = 0,
    toggle_offset_ms: Optional[int] = 0,
    toggle_duration_ms: Optional[int] = -1,
    comment: Optional[str] = "",
):
    """last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

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

    # setup toggle on galil_io
    apm.add_action(
        {
            "action_server": IO_server,
            "action_name": "set_digital_cycle",
            "action_params": {
                "trigger_item": "gamry_ttl0",
                "triggertype": toggle_triggertype,
                "out_item": "gamry_aux",
                "out_item_gamry": "gamry_aux",
                "t_on": apm.pars.toggle_on_ms,
                "t_off": apm.pars.toggle_off_ms,
                "t_offset": apm.pars.toggle_offset_ms,
                "t_duration": apm.pars.toggle_duration_ms,
                "t_on2": apm.pars.toggle_on_ms,
                "t_off2": apm.pars.toggle_off_ms,
                "t_offset2": apm.pars.toggle_offset_ms,
                "t_duration2": apm.pars.toggle_duration_ms,
#                "mainthread": 0,
#                "subthread": 1,
            },
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "process_finish": False,
            "process_contrib": [
                ProcessContrib.action_params,
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        },

    )

    apm.add_action(
        {
            "action_server": PSTAT_server,
            "action_name": "run_CP",
            "action_params": {
                "Ival__A": CP_current,
                "Tval__s": apm.pars.background_duration_sec,
                "AcqInterval__s": apm.pars.samplerate_sec,
                "TTLwait": -1,  # -1 disables, else select TTL 0-3
                "TTLsend": 0,  # -1 disables, else select TTL 0-3
                "IErange": apm.pars.IErange,
            },
            "from_global_params": {"_fast_samples_in": "fast_samples_in"},
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "process_finish": True,
            "process_contrib": [
                ProcessContrib.action_params,
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        },

    )

    return apm.action_list  # returns complete action list to orch


def ECHE_slave_movetosample(
    experiment: Experiment,
    experiment_version: int = 1,
    solid_plate_id: Optional[int] = 4534,
    solid_sample_no: Optional[int] = 1,
):
    """Slave experiment
    last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars


    # get sample plate coordinates
    apm.add_action(
        {
            "action_server": MOTOR_server,
            "action_name": "solid_get_samples_xy",
            "action_params": {
                "plate_id": apm.pars.solid_plate_id,
                "sample_no": apm.pars.solid_sample_no,
            },
            "to_global_params": [
                "_platexy"
            ],  # save new liquid_sample_no of eche cell to globals
            "start_condition": ActionStartCondition.wait_for_all,
        }
    )

    # move to position
    apm.add_action(
        {
            "action_server": MOTOR_server,
            "action_name": "move",
            "action_params": {
                # "d_mm": [apm.pars.x_mm, apm.pars.y_mm],
                "axis": ["x", "y"],
                "mode": MoveModes.absolute,
                "transformation": TransformationModes.platexy,
            },
            "from_global_params": {"_platexy": "d_mm"},
            "start_condition": ActionStartCondition.wait_for_all,
        }
    )

    return apm.action_list  # returns complete action list to orch

def ECHE_slave_move(
    experiment: Experiment,
    experiment_version: int = 1,
    x_mm: float = 1.0,
    y_mm: float = 1.0,
):
    """Slave experiment
    last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars


    # move to position
    apm.add_action(
        {
            "action_server": MOTOR_server,
            "action_name": "move",
            "action_params": {
                "d_mm": [apm.pars.x_mm, apm.pars.y_mm],
                "axis": ["x", "y"],
                "mode": MoveModes.relative,
                "transformation": TransformationModes.platexy,
            },
#            "from_global_params": {"_platexy": "d_mm"},
            "start_condition": ActionStartCondition.wait_for_all,
        }
    )

    return apm.action_list  # returns complete action list to orch

def ECHE_slave_CV_led_secondtrigger(
    experiment: Experiment,
    experiment_version: int = 1,
    Vinit_vsRHE: Optional[float] = 0.0,  # Initial value in volts or amps.
    Vapex1_vsRHE: Optional[float] = 1.0,  # Apex 1 value in volts or amps.
    Vapex2_vsRHE: Optional[float] = -1.0,  # Apex 2 value in volts or amps.
    Vfinal_vsRHE: Optional[float] = 0.0,  # Final value in volts or amps.
    scanrate_voltsec: Optional[
        float
    ] = 0.02,  # scan rate in volts/second or amps/second.
    samplerate_sec: Optional[float] = 0.1,
    cycles: Optional[int] = 1,
    IErange: Optional[str] = "auto",
    ph: float = 0,
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1, #currently liquid sample database number
    reservoir_bubbler_gas: str = "O2",
    droplet_size_cm2: float = .071,  #3mm diameter droplet
    reference_electrode_type: str = "NHE",
    ref_vs_nhe: float = 0.21,
    led: Optional[str] = "doric_led1",
    wavelength_nm: Optional[float] = 0.0,
    wavelength_intensity_mw: Optional[float] = 0.0,
    wavelength_intensity_date: Optional[str] = "n/a",
    led_side_illumination: Optional[str] = "front",
    toggle_on_ms: Optional[float] = 1000,
    toggle_off_ms: Optional[float] = 1000,
    toggle_offset_ms: Optional[int] = 0,
    toggle_duration_ms: Optional[int] = -1,
    toggle_two_on_ms: Optional[float] = 100,
    toggle_two_off_ms: Optional[float] = 100,
    toggle_two_offset_ms: Optional[int] = 0,
    toggle_two_duration_ms: Optional[int] = -1,
    comment: Optional[str] = "",
):
    """last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

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

    #setup toggle on galil_io
    apm.add_action(
        {
            "action_server": IO_server,
            "action_name": "set_digital_cycle",
            "action_params": {
                "trigger_item": "gamry_ttl0",
                "triggertype": toggle_triggertype,
                "out_item": apm.pars.led,
                "out_item_gamry": "gamry_aux",
                "t_on": apm.pars.toggle_on_ms,
                "t_off": apm.pars.toggle_off_ms,
                "t_offset": apm.pars.toggle_offset_ms,
                "t_duration": apm.pars.toggle_duration_ms,
                "t_on2": apm.pars.toggle_two_on_ms,
                "t_off2": apm.pars.toggle_two_off_ms,
                "t_offset2": apm.pars.toggle_two_offset_ms,
                "t_duration2": apm.pars.toggle_two_duration_ms,
                # "mainthread": 0,
                # "subthread": 1,
                # "subthread2": 2,
            },
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "process_finish": False,
            "process_contrib": [
                ProcessContrib.action_params,
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        },
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
                "IErange": apm.pars.IErange,
            },
            "from_global_params": {"_fast_samples_in": "fast_samples_in"},
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "process_finish": True,
            "process_contrib": [
                ProcessContrib.action_params,
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        },
    )

    return apm.action_list  # returns complete action list to orch

def ECHE_slave_CA_led_secondtrigger(
    experiment: Experiment,
    experiment_version: int = 1,
    CA_potential_vsRHE: Optional[float] = 0.0,
    ph: float = 9.53,
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1, #currently liquid sample database number
    reservoir_bubbler_gas: str = "O2",
    droplet_size_cm2: float = .071,  #3mm diameter droplet
    reference_electrode_type: str = "NHE",
    ref_vs_nhe: float = 0.21,
    samplerate_sec: Optional[float] = 0.1,
    CA_duration_sec: Optional[float] = 60,
    IErange: Optional[str] = "auto",
    led: Optional[str] = "doric_led1",
    wavelength_nm: Optional[float] = 0.0,
    wavelength_intensity_mw: Optional[float] = 0.0,
    wavelength_intensity_date: Optional[str] = "n/a",
    led_side_illumination: Optional[str] = "front",
    toggle_on_ms: Optional[float] = 1000,
    toggle_off_ms: Optional[float] = 1000,
    toggle_offset_ms: Optional[int] = 0,
    toggle_duration_ms: Optional[int] = -1,
    toggle_two_on_ms: Optional[float] = 100,
    toggle_two_off_ms: Optional[float] = 100,
    toggle_two_offset_ms: Optional[int] = 0,
    toggle_two_duration_ms: Optional[int] = -1,
    comment: Optional[str] = "",
):
    """last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

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

    # setup toggle on galil_io
    apm.add_action(
        {
            "action_server": IO_server,
            "action_name": "set_digital_cycle",
            "action_params": {
                "trigger_item": "gamry_ttl0",
                "triggertype": toggle_triggertype,
                "out_item": apm.pars.led,
                "out_item_gamry": "gamry_aux",
                "t_on": apm.pars.toggle_on_ms,
                "t_off": apm.pars.toggle_off_ms,
                "t_offset": apm.pars.toggle_offset_ms,
                "t_duration": apm.pars.toggle_duration_ms,
                "t_on2": apm.pars.toggle_two_on_ms,
                "t_off2": apm.pars.toggle_two_off_ms,
                "t_offset2": apm.pars.toggle_two_offset_ms,
                "t_duration2": apm.pars.toggle_two_duration_ms,
#                "mainthread": 0,
#                "subthread": 1,
            },
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "process_finish": False,
            "process_contrib": [
                ProcessContrib.action_params,
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        },

    )

    # apply potential
    potential = (
        apm.pars.CA_potential_vsRHE - 1.0 * apm.pars.ref_vs_nhe - 0.059 * apm.pars.ph
    )
    print(f"ADSS_slave_CA potential: {potential}")
    apm.add_action(
        {
            "action_server": PSTAT_server,
            "action_name": "run_CA",
            "action_params": {
                "Vval__V": potential,
                "Tval__s": apm.pars.CA_duration_sec,
                "AcqInterval__s": apm.pars.samplerate_sec,
                "TTLwait": -1,  # -1 disables, else select TTL 0-3
                "TTLsend": 0,  # -1 disables, else select TTL 0-3
                "IErange": apm.pars.IErange,
            },
            "from_global_params": {"_fast_samples_in": "fast_samples_in"},
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "process_finish": True,
            "process_contrib": [
                ProcessContrib.action_params,
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        },

    )

    return apm.action_list  # returns complete action list to orch

def ECHE_slave_CP_led_secondtrigger(
    experiment: Experiment,
    experiment_version: int = 1,
    CP_current: Optional[float] = 0.0,
    ph: float = 9.53,
    reservoir_electrolyte: Electrolyte = "SLF10",
    reservoir_liquid_sample_no: int = 1, #currently liquid sample database number
    reservoir_bubbler_gas: str = "O2",
    droplet_size_cm2: float = .071,  #3mm diameter droplet
    reference_electrode_type: str = "NHE",
    ref_vs_nhe: float = 0.21,
    samplerate_sec: Optional[float] = 0.1,
    CP_duration_sec: Optional[float] = 60,
    IErange: Optional[str] = "auto",
    led: Optional[str] = "doric_led1",
    wavelength_nm: Optional[float] = 0.0,
    wavelength_intensity_mw: Optional[float] = 0.0,
    wavelength_intensity_date: Optional[str] = "n/a",
    led_side_illumination: Optional[str] = "front",
    toggle_on_ms: Optional[float] = 1000,
    toggle_off_ms: Optional[float] = 1000,
    toggle_offset_ms: Optional[int] = 0,
    toggle_duration_ms: Optional[int] = -1,
    toggle_two_on_ms: Optional[float] = 100,
    toggle_two_off_ms: Optional[float] = 100,
    toggle_two_offset_ms: Optional[int] = 0,
    toggle_two_duration_ms: Optional[int] = -1,
    comment: Optional[str] = "",
):
    """last functionality test: -"""

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars

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

    # setup toggle on galil_io
    apm.add_action(
        {
            "action_server": IO_server,
            "action_name": "set_digital_cycle",
            "action_params": {
                "trigger_item": "gamry_ttl0",
                "triggertype": toggle_triggertype,
                "out_item": apm.pars.led,
                "out_item_gamry": "gamry_aux",
                "t_on": apm.pars.toggle_on_ms,
                "t_off": apm.pars.toggle_off_ms,
                "t_offset": apm.pars.toggle_offset_ms,
                "t_duration": apm.pars.toggle_duration_ms,
                "t_on2": apm.pars.toggle_two_on_ms,
                "t_off2": apm.pars.toggle_two_off_ms,
                "t_offset2": apm.pars.toggle_two_offset_ms,
                "t_duration2": apm.pars.toggle_two_duration_ms,
#                "mainthread": 0,
#                "subthread": 1,
            },
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "process_finish": False,
            "process_contrib": [
                ProcessContrib.action_params,
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        },

    )

    apm.add_action(
        {
            "action_server": PSTAT_server,
            "action_name": "run_CP",
            "action_params": {
                "Ival__A": CP_current,
                "Tval__s": apm.pars.CP_duration_sec,
                "AcqInterval__s": apm.pars.samplerate_sec,
                "TTLwait": -1,  # -1 disables, else select TTL 0-3
                "TTLsend": 0,  # -1 disables, else select TTL 0-3
                "IErange": apm.pars.IErange,
            },
            "from_global_params": {"_fast_samples_in": "fast_samples_in"},
            "start_condition": ActionStartCondition.wait_for_all,  # orch is waiting for all action_dq to finish
            "process_finish": True,
            "process_contrib": [
                ProcessContrib.action_params,
                ProcessContrib.files,
                ProcessContrib.samples_in,
                ProcessContrib.samples_out,
            ],
        },

    )

    return apm.action_list  # returns complete action list to orch
