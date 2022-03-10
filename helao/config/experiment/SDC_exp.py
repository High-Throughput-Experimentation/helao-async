"""
Experiment library for SDC
server_key must be a FastAPI action server defined in config
"""

__all__ = [
           "SDC_slave_unloadall_customs",
           "SDC_slave_load_solid",
           "SDC_slave_startup",
           "SDC_slave_shutdown",
           "SDC_slave_CA_toggle",
           "SDC_slave_CA",
          ]


from typing import Optional, List, Union
from socket import gethostname

from helaocore.schema import Action, Experiment, ActionPlanMaker
from helaocore.model.action_start_condition import ActionStartCondition
from helaocore.model.sample import (
                                    SolidSample,
                                    LiquidSample
                                   )
from helaocore.model.machine import MachineModel

from helao.library.driver.galil_motion_driver import MoveModes, TransformationModes
from helao.library.driver.pal_driver import Spacingmethod, PALtools


EXPERIMENTS = __all__

PSTAT_server = MachineModel(
                server_name = "PSTAT",
                machine_name = gethostname()
             ).json_dict()

MOTOR_server = MachineModel(
                server_name = "MOTOR",
                machine_name = gethostname()
             ).json_dict()
IO_server = MachineModel(
                server_name = "IO",
                machine_name = gethostname()
             ).json_dict()


ORCH_server = MachineModel(
                server_name = "ORCH",
                machine_name = gethostname()
             ).json_dict()
PAL_server = MachineModel(
                server_name = "PAL",
                machine_name = gethostname()
             ).json_dict()


def SDC_slave_unloadall_customs(experiment: Experiment):
    """last functionality test: -"""

    apm = ActionPlanMaker() # exposes function parameters via apm.pars

    apm.add_action({
        "action_server": PAL_server,
        "action_name": "archive_custom_unloadall",
        "action_params": {
                        },
        "start_condition": ActionStartCondition.wait_for_all, # orch is waiting for all action_dq to finish
        })

    return apm.action_list # returns complete action list to orch


def SDC_slave_load_solid(
                          experiment: Experiment, 
                          solid_custom_position: Optional[str] = "cell1_we",
                          solid_plate_id: Optional[int] = 4534,
                          solid_sample_no: Optional[int] = 1
                         ):
    """last functionality test: -"""
    
    apm = ActionPlanMaker() # exposes function parameters via apm.pars

    apm.add_action({
        "action_server": PAL_server,
        "action_name": "archive_custom_load",
        "action_params": {
                        "custom": apm.pars.solid_custom_position,
                        "load_sample_in": SolidSample(**{"sample_no":apm.pars.solid_sample_no,
                                                         "plate_id":apm.pars.solid_plate_id,
                                                         "machine_name":"legacy"
                                                        }).dict(),
                        },
        "start_condition": ActionStartCondition.wait_for_all, # orch is waiting for all action_dq to finish
        })

    return apm.action_list # returns complete action list to orch


def SDC_slave_startup(experiment: Experiment,
              solid_custom_position: Optional[str] = "cell1_we",
              solid_plate_id: Optional[int] = 4534,
              solid_sample_no: Optional[int] = 1,
              reservoir_liquid_sample_no: Optional[int] = 1,
              liquid_volume_ml: Optional[float] = 1.0
              ):
    """Slave experiment
       last functionality test: -"""

    
    apm = ActionPlanMaker() # exposes function parameters via apm.pars


    # unload all samples from custom positions
    apm.add_action_list(SDC_slave_unloadall_customs(experiment=experiment))


    # load new requested samples 
    apm.add_action_list(SDC_slave_load_solid(
        experiment=experiment,
        solid_custom_position = apm.pars.solid_custom_position,
        solid_plate_id = apm.pars.solid_plate_id, 
        solid_sample_no =apm.pars.solid_sample_no
        ))


    apm.add_action({
        "action_server": PAL_server,
        "action_name": "archive_custom_add_liquid",
        "action_params": {
                        "custom": apm.pars.solid_custom_position,
                        "source_liquid_in": LiquidSample(**{"sample_no":apm.pars.reservoir_liquid_sample_no,
                                                            "machine_name":gethostname()
                                                        }).dict(),
                        "volume_ml":apm.pars.liquid_volume_ml,
                        "combine_liquids":True,
                        "dilute_liquids":True
                        },
        "start_condition": ActionStartCondition.wait_for_all, # orch is waiting for all action_dq to finish
        })


    # move to position
    apm.add_action({
        "action_server": MOTOR_server,
        "action_name": "solid_get_sample_xy",
        "action_params": {
                        "plate_id":apm.pars.solid_plate_id,
                        "sample_no":apm.pars.solid_sample_no,
                        },
        "to_global_params":["_platexy"], # save new liquid_sample_no of eche cell to globals
        "start_condition": ActionStartCondition.wait_for_all,
        })


    # move to position
    apm.add_action({
        "action_server": MOTOR_server,
        "action_name": "move",
        "action_params": {
                        # "d_mm": [apm.pars.x_mm, apm.pars.y_mm],
                        "axis": ["x", "y"],
                        "mode": MoveModes.absolute,
                        "transformation": TransformationModes.platexy,
                        },
        "from_global_params":{
                    "_platexy":"d_mm"
                    },
        "start_condition": ActionStartCondition.wait_for_all,
        })



    return apm.action_list # returns complete action list to orch


def SDC_slave_shutdown(experiment: Experiment):
    """Slave experiment
    
    last functionality test: -"""

    apm = ActionPlanMaker() # exposes function parameters via apm.pars


    return apm.action_list # returns complete action list to orch


def SDC_slave_CA_toggle(experiment: Experiment,
              CA_potential_vsRHE: Optional[float] = 0.0,
              ph: float = 9.53,
              ref_vs_nhe: float = 0.21,
              samplerate_sec: Optional[float] = 0.1, 
              CA_duration_sec: Optional[float] = 60, 
              t_on: Optional[float] = 1000,
              t_off: Optional[float] = 1000,
              ):
    """last functionality test: -"""
    
    apm = ActionPlanMaker() # exposes function parameters via apm.pars

    # get sample for gamry
    apm.add_action({
        "action_server": PAL_server,
        "action_name": "archive_custom_query_sample",
        "action_params": {
                        "custom": "cell1_we",
                        },
        "to_global_params":["_fast_samples_in"], # save new liquid_sample_no of eche cell to globals
        "start_condition": ActionStartCondition.wait_for_all, # orch is waiting for all action_dq to finish
        })



    # setup toggle on galil_io
    apm.add_action({
        "action_server": IO_server,
        "action_name": "set_digital_cycle",
        "action_params": {
                          "trigger_item":"gamry_ttl0",
                          "triggertype":"risingedge",
                          "out_item":"doric_led3",
                          "out_item_gamry":"gamry_aux",
                          "t_on":apm.pars.t_on,
                          "t_off":apm.pars.t_off,
                          "mainthread":0,
                          "subthread":1,
                        },
        "start_condition": ActionStartCondition.wait_for_all, # orch is waiting for all action_dq to finish
        })

    
    # apply potential
    potential = apm.pars.CA_potential_vsRHE-1.0*apm.pars.ref_vs_nhe-0.059*apm.pars.ph
    print(f"ADSS_slave_CA potential: {potential}")
    apm.add_action({
        "action_server": PSTAT_server,
        "action_name": "run_CA",
        "action_params": {
                        "Vval": potential,
                        "Tval": apm.pars.CA_duration_sec,
                        "SampleRate": apm.pars.samplerate_sec,
                        "TTLwait": -1,  # -1 disables, else select TTL 0-3
                        "TTLsend": 0,  # -1 disables, else select TTL 0-3
                        "IErange": "auto",
                        },
        "from_global_params":{
                    "_fast_samples_in":"fast_samples_in"
                    },
        "start_condition": ActionStartCondition.wait_for_all, # orch is waiting for all action_dq to finish
        })


    return apm.action_list # returns complete action list to orch


def SDC_slave_CA(experiment: Experiment,
              CA_potential_vsRHE: Optional[float] = 0.0,
              ph: float = 9.53,
              ref_vs_nhe: float = 0.21,
              samplerate_sec: Optional[float] = 0.1, 
              CA_duration_sec: Optional[float] = 60, 
              ):
    """last functionality test: -"""
    
    apm = ActionPlanMaker() # exposes function parameters via apm.pars

    # get sample for gamry
    apm.add_action({
        "action_server": PAL_server,
        "action_name": "archive_custom_query_sample",
        "action_params": {
                        "custom": "cell1_we",
                        },
        "to_global_params":["_fast_samples_in"], # save new liquid_sample_no of eche cell to globals
        "start_condition": ActionStartCondition.wait_for_all, # orch is waiting for all action_dq to finish
        })

    
    # apply potential
    potential = apm.pars.CA_potential_vsRHE-1.0*apm.pars.ref_vs_nhe-0.059*apm.pars.ph
    print(f"ADSS_slave_CA potential: {potential}")
    apm.add_action({
        "action_server": PSTAT_server,
        "action_name": "run_CA",
        "action_params": {
                        "Vval": potential,
                        "Tval": apm.pars.CA_duration_sec,
                        "SampleRate": apm.pars.samplerate_sec,
                        "TTLwait": -1,  # -1 disables, else select TTL 0-3
                        "TTLsend": 0,  # -1 disables, else select TTL 0-3
                        "IErange": "auto",
                        },
        "from_global_params":{
                    "_fast_samples_in":"fast_samples_in"
                    },
        "start_condition": ActionStartCondition.wait_for_all, # orch is waiting for all action_dq to finish
        })


    return apm.action_list # returns complete action list to orch


def SDC_slave_CV_toggle(experiment: Experiment,
                        Vinit_vsRHE: Optional[float] = 0.0,  # Initial value in volts or amps.
                        Vapex1_vsRHE: Optional[float] = 1.0,  # Apex 1 value in volts or amps.
                        Vapex2_vsRHE: Optional[float] = -1.0,  # Apex 2 value in volts or amps.
                        Vfinal_vsRHE: Optional[float] = 0.0,  # Final value in volts or amps.
                        scanrate_voltsec: Optional[float] = 1.0,  # scan rate in volts/second or amps/second.
                        samplerate_sec: Optional[float] = 0.1, 
                        cycles: Optional[int] = 1,
                        ph: float = 9.53,
                        ref_vs_nhe: float = 0.21,
                        t_on: Optional[float] = 1000,
                        t_off: Optional[float] = 1000,
                       ):
    """last functionality test: -"""
    
    apm = ActionPlanMaker() # exposes function parameters via apm.pars

    # get sample for gamry
    apm.add_action({
        "action_server": PAL_server,
        "action_name": "archive_custom_query_sample",
        "action_params": {
                        "custom": "cell1_we",
                        },
        "to_global_params":["_fast_samples_in"], # save new liquid_sample_no of eche cell to globals
        "start_condition": ActionStartCondition.wait_for_all, # orch is waiting for all action_dq to finish
        })



    # setup toggle on galil_io
    apm.add_action({
        "action_server": IO_server,
        "action_name": "set_digital_cycle",
        "action_params": {
                          "trigger_item":"gamry_ttl0",
                          "triggertype":"risingedge",
                          "out_item":"doric_led3",
                          "out_item_gamry":"gamry_aux",
                          "t_on":apm.pars.t_on,
                          "t_off":apm.pars.t_off,
                          "mainthread":0,
                          "subthread":1,
                        },
        "start_condition": ActionStartCondition.wait_for_all, # orch is waiting for all action_dq to finish
        })

    
    # apply potential
    apm.add_action({
        "action_server": PSTAT_server,
        "action_name": "run_CV",
        "action_params": {
                         "Vinit":apm.pars.Vinit_vsRHE-1.0*apm.pars.ref_vs_nhe-0.059*apm.pars.ph,
                         "Vapex1":apm.pars.Vapex1_vsRHE-1.0*apm.pars.ref_vs_nhe-0.059*apm.pars.ph,
                         "Vapex2":apm.pars.Vapex2_vsRHE-1.0*apm.pars.ref_vs_nhe-0.059*apm.pars.ph,
                         "Vfinal":apm.pars.Vfinal_vsRHE-1.0*apm.pars.ref_vs_nhe-0.059*apm.pars.ph,
                         "ScanRate":apm.pars.scanrate_voltsec,
                         "SampleRate":apm.pars.samplerate_sec,
                         "Cycles":apm.pars.cycles,
                         "TTLwait": -1,  # -1 disables, else select TTL 0-3
                         "TTLsend": 0,  # -1 disables, else select TTL 0-3
                         "IErange": "auto",
                        },
        "from_global_params":{
                    "_fast_samples_in":"fast_samples_in"
                    },
        "start_condition": ActionStartCondition.wait_for_all, # orch is waiting for all action_dq to finish
        })


    return apm.action_list # returns complete action list to orch


def SDC_slave_CV(experiment: Experiment,
                 Vinit_vsRHE: Optional[float] = 0.0,  # Initial value in volts or amps.
                 Vapex1_vsRHE: Optional[float] = 1.0,  # Apex 1 value in volts or amps.
                 Vapex2_vsRHE: Optional[float] = -1.0,  # Apex 2 value in volts or amps.
                 Vfinal_vsRHE: Optional[float] = 0.0,  # Final value in volts or amps.
                 scanrate_voltsec: Optional[float] = 1.0,  # scan rate in volts/second or amps/second.
                 samplerate_sec: Optional[float] = 0.1, 
                 cycles: Optional[int] = 1,
                 ph: float = 9.53,
                 ref_vs_nhe: float = 0.21,
                ):
    """last functionality test: -"""
    
    apm = ActionPlanMaker() # exposes function parameters via apm.pars

    # get sample for gamry
    apm.add_action({
        "action_server": PAL_server,
        "action_name": "archive_custom_query_sample",
        "action_params": {
                        "custom": "cell1_we",
                        },
        "to_global_params":["_fast_samples_in"], # save new liquid_sample_no of eche cell to globals
        "start_condition": ActionStartCondition.wait_for_all, # orch is waiting for all action_dq to finish
        })



    # setup toggle on galil_io
    apm.add_action({
        "action_server": IO_server,
        "action_name": "set_digital_cycle",
        "action_params": {
                          "trigger_item":"gamry_ttl0",
                          "triggertype":"risingedge",
                          "out_item":"doric_led3",
                          "out_item_gamry":"gamry_aux",
                          "t_on":apm.pars.t_on,
                          "t_off":apm.pars.t_off,
                          "mainthread":0,
                          "subthread":1,
                        },
        "start_condition": ActionStartCondition.wait_for_all, # orch is waiting for all action_dq to finish
        })

    
    # apply potential
    apm.add_action({
        "action_server": PSTAT_server,
        "action_name": "run_CV",
        "action_params": {
                         "Vinit":apm.pars.Vinit_vsRHE-1.0*apm.pars.ref_vs_nhe-0.059*apm.pars.ph,
                         "Vapex1":apm.pars.Vapex1_vsRHE-1.0*apm.pars.ref_vs_nhe-0.059*apm.pars.ph,
                         "Vapex2":apm.pars.Vapex2_vsRHE-1.0*apm.pars.ref_vs_nhe-0.059*apm.pars.ph,
                         "Vfinal":apm.pars.Vfinal_vsRHE-1.0*apm.pars.ref_vs_nhe-0.059*apm.pars.ph,
                         "ScanRate":apm.pars.scanrate_voltsec,
                         "SampleRate":apm.pars.samplerate_sec,
                         "Cycles":apm.pars.cycles,
                         "TTLwait": -1,  # -1 disables, else select TTL 0-3
                         "TTLsend": 0,  # -1 disables, else select TTL 0-3
                         "IErange": "auto",
                        },
        "from_global_params":{
                    "_fast_samples_in":"fast_samples_in"
                    },
        "start_condition": ActionStartCondition.wait_for_all, # orch is waiting for all action_dq to finish
        })


    return apm.action_list # returns complete action list to orch
