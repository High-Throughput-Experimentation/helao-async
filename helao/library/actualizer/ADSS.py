"""
Action library for ADSS (RSHS and ANEC2)

action tuples take the form:
(decision_id, server_key, action, param_dict, preemptive, blocking)

server_key must be a FastAPI action server defined in config
"""
from helao.core.schema import Action, Decision
from helao.core.model import return_dec, return_declist, return_act, return_actlist

# list valid actualizer functions 
ACTUALIZERS = ['orchtest']


# z positions for ADSS cell
z_home = 0.0
# touches the bottom of cell
z_engage = 2.5
# moves it up to put pressure on seal
z_seal = 4.5

from typing import Optional, List, Union


def orchtest(decisionObj: Decision, 
             d_mm: Optional[str] = '1.0', 
             x_mm: Optional[float] = 0.0, 
             y_mm: Optional[float] = 0.0
             ):
    """Test action for ORCH debugging
    simple plate is e.g. 4534"""
    
     # additional actualizer params should be stored in decision.actualizer_pars
     # these are duplicates of the function parameters (currently the op uses functions 
     # parameters to display them in the webUI)
     
     
    # start_condition: 
    # 0: orch is dispatching an unconditional action
    # 1: orch is waiting for endpoint to become available
    # 2: orch is waiting for server to become available
    # 3: (or other): orch is waiting for all action_dq to finish
    
    # holds all actions for this actualizer  
    action_list = []


    action_dict = decisionObj.as_dict()
    # action_dict = dict()
    action_dict.update({
        # "action_uuid": None,
        # "action_queue_time": None,
        "action_server": "potentiostat",
        "action_name": "run_OCV",
        "action_params": {
                        "Tval": 10.0,
                        "SampleRate": 0.01,
                        "TTLwait": -1,  # -1 disables, else select TTL 0-3
                        "TTLsend": -1,  # -1 disables, else select TTL 0-3
                        "IErange": "auto",
                        },
        # "action_enum": None,
        # "action_abbr": None,
        "save_rcp": True,
        # "save_data": None,
        "start_condition": 0, # orch is waiting for all action_dq to finish
        "plate_id": None,
        "samples_in": {},
        # # the following attributes are set during Action dispatch but can be imported
        # "samples_out": {},
        # "data": [],
        # "output_dir": None,
        # "column_names": None,
        # "header": None,
        # "file_type": None,
        # "filename": None,
        # "file_group": None,
        # "error_code": "0",
        })
    action_list.append(Action(inputdict=action_dict))

    return action_list

