"""
Action library for ANEC

server_key must be a FastAPI action server defined in config
"""

__all__ = ["debug", 
           "CA",
           "OCV_sqtest",
           "CA_sqtest"]


from typing import Optional, List, Union

from helaocore.schema import Action, Process, Sequencer
from helaocore.server import action_start_condition
from helao.library.driver.pal_driver import PALmethods, Spacingmethod, PALtools
import helaocore.model.sample as hcms

# list valid process functions 
SEQUENCES = __all__

PSTAT_name = "PSTAT"
MOTOR_name = "MOTOR"
NI_name = "NI"
ORCH_name = "ORCH"
PAL_name = "PAL"

# z positions for ADSS cell
z_home = 0.0
# touches the bottom of cell
z_engage = 2.5
# moves it up to put pressure on seal
z_seal = 4.5



def debug(pg_Obj: Process, 
             d_mm: Optional[str] = "1.0", 
             x_mm: Optional[float] = 0.0, 
             y_mm: Optional[float] = 0.0
             ):
    """Test action for ORCH debugging
    simple plate is e.g. 4534"""
    
     # additional process params should be stored in process.process_params
     # these are duplicates of the function parameters (currently the op uses functions 
     # parameters to display them in the webUI)
     
     
    # start_condition: 
    # 0: orch is dispatching an unconditional action
    # 1: orch is waiting for endpoint to become available
    # 2: orch is waiting for server to become available
    # 3: (or other): orch is waiting for all action_dq to finish
    
    # holds all actions for this process  
    action_list = []



    action_dict = pg_Obj.as_dict()
    action_dict.update({
        "action_server": f"{NI_name}",
        "action_name": "run_cell_IV",
        "action_params": {
                        "Tval": 10,
                        "SampleRate": 1.0,
                        "TTLwait": -1,  # -1 disables, else select TTL 0-3
                        "fast_samples_in":hcms.SampleList(samples=[
                            hcms.LiquidSample(**{"sample_no":1}),
                            hcms.LiquidSample(**{"sample_no":2}),
                            hcms.LiquidSample(**{"sample_no":3}),
                            hcms.LiquidSample(**{"sample_no":4}),
                            hcms.LiquidSample(**{"sample_no":5}),
                            hcms.LiquidSample(**{"sample_no":6}),
                            hcms.LiquidSample(**{"sample_no":7}),
                            hcms.LiquidSample(**{"sample_no":8}),
                            hcms.LiquidSample(**{"sample_no":9}),
                            ]).dict()
                        },
        # "save_prc": False,
        # "save_data": False,
        "start_condition": action_start_condition.wait_for_all, # orch is waiting for all action_dq to finish
        })
    action_list.append(Action(inputdict=action_dict))

    return action_list


def CA(pg_Obj: Process,
       CA_potential_V: Optional[float] = 0.0,
       CA_duration_sec: Optional[float] = 10.0,
       samplerate_sec: Optional[float] = 1.0,
       
       ):
    """Perform a CA measurement."""
    
    # todo, I will try to write a function which will do this later
    # I assume we need a base process class for this
    CA_potential_V = pg_Obj.process_params.get("CA_potential_V", CA_potential_V)
    CA_duration_sec = pg_Obj.process_params.get("CA_duration_sec", CA_duration_sec)
    samplerate_sec = pg_Obj.process_params.get("samplerate_sec", samplerate_sec)



    # list to hold all actions
    action_list = []
    
    
    # apply potential
    action_dict = pg_Obj.as_dict()
    action_dict.update({
        "action_server": f"{PSTAT_name}",
        "action_name": "run_CA",
        "action_params": {
                        "Vval": CA_potential_V,
                        "Tval": CA_duration_sec,
                        "SampleRate": samplerate_sec,
                        "TTLwait": -1,  # -1 disables, else select TTL 0-3
                        "TTLsend": -1,  # -1 disables, else select TTL 0-3
                        "IErange": "auto",
                        },
        "save_prc": True,
        "save_data": True,
        "start_condition": action_start_condition.wait_for_all, # orch is waiting for all action_dq to finish
        # "plate_id": None,
        })
    action_list.append(Action(inputdict=action_dict))

    return action_list


def OCV_sqtest(pg_Obj: Process,
               OCV_duration_sec: Optional[float] = 10.0,
               samplerate_sec: Optional[float] = 1.0,
              ):

    """This is the description of the process which will be displayed
       in the operator webgui. For all function parameters (except pg_Obj)
       a input field will be (dynamically) presented in the OP webgui.""" 
    
    
    sq = Sequencer(pg_Obj) # exposes function parameters via sq.pars

    sq.add_action(
        {
        "action_server": f"{PSTAT_name}",
        "action_name": "run_OCV",
        "action_params": {
                        "Tval": sq.pars.OCV_duration_sec,
                        "SampleRate": sq.pars.samplerate_sec,
                        "TTLwait": -1,  # -1 disables, else select TTL 0-3
                        "TTLsend": -1,  # -1 disables, else select TTL 0-3
                        "IErange": "auto",
                        },
        "save_prc": True,
        "save_data": True,
        "start_condition": action_start_condition.wait_for_all, # orch is waiting for all action_dq to finish
        }
    )

    return sq.action_list # returns complete action list to orch


def CA_sqtest(pg_Obj: Process,
              Ewe_vs_RHE: Optional[float] = 0.0,
              Eref: Optional[float] = 0.2,
              pH: Optional[float] = 10.0,
              duration_sec: Optional[float] = 10.0,
              samplerate_sec: Optional[float] = 1.0,
              ):

    """This is the description of the process which will be displayed
       in the operator webgui. For all function parameters (except pg_Obj)
       a input field will be (dynamically) presented in the OP webgui.""" 
    
    
    sq = Sequencer(pg_Obj) # exposes function parameters via sq.pars

    sq.add_action(
        {
        "action_server": f"{PSTAT_name}",
        "action_name": "run_CA",
        "action_params": {
                        "Vval": sq.pars.Ewe_vs_RHE-1.0*sq.pars.Eref-0.059*sq.pars.pH,
                        "Tval": sq.pars.duration_sec,
                        "SampleRate": sq.pars.samplerate_sec,
                        "TTLwait": -1,  # -1 disables, else select TTL 0-3
                        "TTLsend": -1,  # -1 disables, else select TTL 0-3
                        "IErange": "auto",
                        },
        "save_prc": True,
        "save_data": True,
        "start_condition": action_start_condition.wait_for_all, # orch is waiting for all action_dq to finish
        }
    )

    return sq.action_list # returns complete action list to orch
