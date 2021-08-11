"""
Action library for ADSS (RSHS and ANEC2)

action tuples take the form:
(decision_id, server_key, action, param_dict, preemptive, blocking)

server_key must be a FastAPI action server defined in config
"""
from helao.core.schema import Action, Decision

from helao.core.server import action_start_condition
from helao.library.driver.galil_driver import move_modes, transformation_mode

from helao.library.driver.PAL_driver import PALmethods, Spacingmethod, PALtools



# list valid actualizer functions 
ACTUALIZERS = ["orchtest", "ADSS_CA"]


# z positions for ADSS cell
z_home = 0.0
# touches the bottom of cell
z_engage = 2.5
# moves it up to put pressure on seal
z_seal = 4.5

from typing import Optional, List, Union


def orchtest(decisionObj: Decision, 
             d_mm: Optional[str] = "1.0", 
             x_mm: Optional[float] = 0.0, 
             y_mm: Optional[float] = 0.0
             ):
    """Test action for ORCH debugging \n
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
        "start_condition": action_start_condition.no_wait, # orch is waiting for all action_dq to finish
        "plate_id": None,
        "samples_in": {},

        })
    action_list.append(Action(inputdict=action_dict))

    return action_list




def ADSS_startup(decisionObj: Decision,
              x_mm: Optional[float] = 0.0, 
              y_mm: Optional[float] = 0.0,
              ):
    
    
    action_list = []

    # move z to home
    action_dict = decisionObj.as_dict()
    action_dict.update({
        "action_server": "motor",
        "action_name": "move",
        "action_params": {
                        "d_mm": [z_home],
                        "axis": ["z"],
                        "mode": move_modes.absolute,
                        "transformation": transformation_mode.instrxy,
                        },
        "save_rcp": True,
        "start_condition": action_start_condition.wait_for_all,
        "plate_id": None,
        })
    action_list.append(Action(inputdict=action_dict))



    # move to position
    action_dict = decisionObj.as_dict()
    action_dict.update({
        "action_server": "motor",
        "action_name": "move",
        "action_params": {
                        "d_mm": [x_mm, y_mm],
                        "axis": ["x", "y"],
                        "mode": move_modes.absolute,
                        "transformation": transformation_mode.platexy,
                        },
        "save_rcp": True,
        "start_condition": action_start_condition.wait_for_all,
        "plate_id": None,
        })
    action_list.append(Action(inputdict=action_dict))

    # engage
    action_dict = decisionObj.as_dict()
    action_dict.update({
        "action_server": "motor",
        "action_name": "move",
        "action_params": {
                        "d_mm": [z_engage],
                        "axis": ["z"],
                        "mode": move_modes.absolute,
                        "transformation": transformation_mode.instrxy,
                        },
        "save_rcp": True,
        "start_condition": action_start_condition.wait_for_all,
        "plate_id": None,
        })
    action_list.append(Action(inputdict=action_dict))


    # seal
    action_dict = decisionObj.as_dict()
    action_dict.update({
        "action_server": "motor",
        "action_name": "move",
        "action_params": {
                        "d_mm": [z_seal],
                        "axis": ["z"],
                        "mode": move_modes.absolute,
                        "transformation": transformation_mode.instrxy,
                        },
        "save_rcp": True,
        "start_condition": action_start_condition.wait_for_all,
        "plate_id": None,
        })
    action_list.append(Action(inputdict=action_dict))


    return action_list


def ADSS_shutdown(decisionObj: Decision):
    
    action_list = []
    # # deep clean
    action_dict = decisionObj.as_dict()
    action_dict.update({
        "action_server": "PAL",
        "action_name": "run_method",
        "action_params": {
                         "liquid_sample_no": "0",
                         "method": PALmethods.deepclean,
                         "tool": PALtools.LS3,
                         "source": "elec_res1",
                         "volume_uL": 500,
                         "totalvials": 1,
                         "sampleperiod": 0.0,
                         "spacingmethod": Spacingmethod.linear,
                         "spacingfactor": 1.0,
                         },
        "save_rcp": True,
        "save_data": True,
        "start_condition": action_start_condition.wait_for_all,
        "plate_id": None,
        })
    action_list.append(Action(inputdict=action_dict))


    # set pump flow backward
    action_dict = decisionObj.as_dict()
    action_dict.update({
        "action_server": "nimax",
        "action_name": "run_task_Pumps",
        "action_params": {
                         "pumps":"Direction",
                         "on": 1,
                         },
        "save_rcp": True,
        "start_condition": action_start_condition.wait_for_all,
        "plate_id": None,
        })
    action_list.append(Action(inputdict=action_dict))

    # wait some time to pump out the liquid
    action_dict = decisionObj.as_dict()
    action_dict.update({
        "action_server": "orchestrator",
        "action_name": "wait",
        "action_params": {
                         "waittime":120,
                         },
        "save_rcp": True,
        "start_condition": action_start_condition.wait_for_all,
        "plate_id": None,
        })
    action_list.append(Action(inputdict=action_dict))

    # turn pump off
    action_dict = decisionObj.as_dict()
    action_dict.update({
        "action_server": "nimax",
        "action_name": "run_task_Pumps",
        "action_params": {
                         "pumps":"PeriPump",
                         "on": 0,
                         },
        "save_rcp": True,
        "start_condition": action_start_condition.wait_for_all,
        "plate_id": None,
        })
    action_list.append(Action(inputdict=action_dict))


    # set pump flow forward
    action_dict = decisionObj.as_dict()
    action_dict.update({
        "action_server": "nimax",
        "action_name": "run_task_Pumps",
        "action_params": {
                         "pumps":"Direction",
                         "on": 0,
                         },
        "save_rcp": True,
        "start_condition": action_start_condition.wait_for_all,
        "plate_id": None,
        })
    action_list.append(Action(inputdict=action_dict))


    # TODO DRAIN
    
    # # move z to home
    # action_dict = decisionObj.as_dict()
    # action_dict.update({
    #     "action_server": "motor",
    #     "action_name": "move",
    #     "action_params": {
    #                     "d_mm": [z_home],
    #                     "axis": ["z"],
    #                     "mode": move_modes.absolute,
    #                     "transformation": transformation_mode.instrxy,
    #                     },
    #     "save_rcp": True,
    #     "start_condition": action_start_condition.wait_for_all,
    #     "plate_id": None,
    #     })
    # action_list.append(Action(inputdict=action_dict))


    return action_list



def ADSS_CA(decisionObj: Decision,
              x_mm: Optional[float] = 0.0, 
              y_mm: Optional[float] = 0.0,
              liquid_sample_no: Optional[int] = 3,
              potentials: Optional[List[float]] = [],
              erhe: Optional[float] = -0.21-0.059*9.53,
              duration: Optional[float] = 1320, 
              OCV_duration: Optional[float] = 60, 
              samplerate: Optional[float] = 1, 
              filltime: Optional[float] = 10.0
              ):
           
    """Chronoamperometry (current response on amplied potential):\n
        x_mm / y_mm: plate coordinates of sample;\n
        potential (Volt): applied potential;\n
        duration (sec): how long the potential is applied;\n
        samplerate (sec): sampleperiod of Gamry;\n
        filltime (sec): how long it takes to fill the cell with liquid or empty it."""



    cycles = len(potentials)

    # action_list = []
    action_list = ADSS_startup(decisionObj, x_mm, y_mm)


    for cycle in range(cycles):
        potential = potentials(cycle)+erhe;
        print(f" ... cycle {cycle} potential:", potential)
        if cycle == 0:
        
            # fill liquid, no wash (assume it was cleaned before)
            action_dict = decisionObj.as_dict()
            action_dict.update({
                "action_server": "PAL",
                "action_name": "run_method",
                "action_params": {
                                 "liquid_sample_no": liquid_sample_no,
                                 "method": PALmethods.fillfixed,
                                 "tool": PALtools.LS3,
                                 "source": "elec_res1",
                                 "volume_uL": 10000,
                                 "totalvials": 1,
                                 "sampleperiod": [0.0],
                                 "spacingmethod": Spacingmethod.linear,
                                 "spacingfactor": 1.0,
                                 },
                "to_global_params":["_eche_sample_no"], # save new liquid_sample_no of eche cell to globals
                "save_rcp": True,
                "save_data": True,
                "start_condition": action_start_condition.wait_for_all, # orch is waiting for all action_dq to finish
                # "plate_id": None,
                })
            action_list.append(Action(inputdict=action_dict))

        
            # set pump flow forward
            action_dict = decisionObj.as_dict()
            action_dict.update({
                "action_server": "nimax",
                "action_name": "run_task_Pumps",
                "action_params": {
                                 "pumps":"Direction",
                                 "on": 0,
                                 },
                "save_rcp": True,
                "start_condition": action_start_condition.wait_for_all,
                "plate_id": None,
                })
            action_list.append(Action(inputdict=action_dict))
        
            # turn on pump
            action_dict = decisionObj.as_dict()
            action_dict.update({
                "action_server": "nimax",
                "action_name": "run_task_Pumps",
                "action_params": {
                                 "pumps":"PeriPump",
                                 "on": 1,
                                 },
                "save_rcp": True,
                "start_condition": action_start_condition.wait_for_all,
                "plate_id": None,
                })
            action_list.append(Action(inputdict=action_dict))

        
            # wait some time to pump in the liquid
            action_dict = decisionObj.as_dict()
            action_dict.update({
                "action_server": "orchestrator",
                "action_name": "wait",
                "action_params": {
                                 "waittime":filltime,
                                 },
                "save_rcp": True,
                "start_condition": action_start_condition.wait_for_all,
                "plate_id": None,
                })
            action_list.append(Action(inputdict=action_dict))
            
        else:    
            # fill liquid, no wash (assume it was cleaned before)
            action_dict = decisionObj.as_dict()
            action_dict.update({
                "action_server": "PAL",
                "action_name": "run_method",
                "action_params": {
                                 "liquid_sample_no": liquid_sample_no,
                                 "method": PALmethods.fill,
                                 "tool": PALtools.LS3,
                                 "source": "elec_res1",
                                 "volume_uL": 1000,
                                 "totalvials": 1,
                                 "sampleperiod": [0.0],
                                 "spacingmethod": Spacingmethod.linear,
                                 "spacingfactor": 1.0,
                                 },
                "to_global_params":["_eche_sample_no"],
                "save_rcp": True,
                "save_data": True,
                "start_condition": action_start_condition.wait_for_all, # orch is waiting for all action_dq to finish
                # "plate_id": None,
                })
            action_list.append(Action(inputdict=action_dict))
    
    
        # OCV
        action_dict = decisionObj.as_dict()
        action_dict.update({
            "action_server": "potentiostat",
            "action_name": "run_OCV",
            "action_params": {
                            "Tval": OCV_duration,
                            "SampleRate": samplerate,
                            "TTLwait": -1,  # -1 disables, else select TTL 0-3
                            "TTLsend": -1,  # -1 disables, else select TTL 0-3
                            "IErange": "auto",
                            },
            "save_rcp": True,
            "save_data": None,
            "start_condition": action_start_condition.wait_for_all, # orch is waiting for all action_dq to finish
            "plate_id": None,
            "samples_in": {},
    
            })
        action_list.append(Action(inputdict=action_dict))


        # take liquid sample
        action_dict = decisionObj.as_dict()
        action_dict.update({
            "action_server": "PAL",
            "action_name": "run_method",
            "action_params": {
                             "liquid_sample_no": -1,
                             "method": PALmethods.archive,
                             "tool": PALtools.LS3,
                             "source": "lcfc_res",
                             "volume_uL": 200,
                             "totalvials": 1,
                             "sampleperiod": [0.0],
                             "spacingmethod": Spacingmethod.linear,
                             "spacingfactor": 1.0,
                             },
            # "to_global_params":["_eche_sample_no"],
            "from_global_params":{
                        "_eche_sample_no":"liquid_sample_no"
                        },
            "save_rcp": True,
            "save_data": True,
            "start_condition": action_start_condition.wait_for_all, # orch is waiting for all action_dq to finish
            # "plate_id": None,
            })
        action_list.append(Action(inputdict=action_dict))


        # apply potential
        action_dict = decisionObj.as_dict()
        action_dict.update({
            "action_server": "potentiostat",
            "action_name": "run_CA",
            "action_params": {
                            "Vval": potential,
                            "Tval": duration,
                            "SampleRate": samplerate,
                            "TTLwait": -1,  # -1 disables, else select TTL 0-3
                            "TTLsend": -1,  # -1 disables, else select TTL 0-3
                            "IErange": "auto",
                            },
            "save_rcp": True,
            "save_data": True,
            "start_condition": action_start_condition.wait_for_all, # orch is waiting for all action_dq to finish
            # "plate_id": None,
            })
        action_list.append(Action(inputdict=action_dict))

    
        # take multiple scheduled liquid samples
        action_dict = decisionObj.as_dict()
        action_dict.update({
            "action_server": "PAL",
            "action_name": "run_method",
            "action_params": {
                             "liquid_sample_no": -2, # signals to use second last item in liquid sample DB
                             "method": PALmethods.archive,
                             "tool": PALtools.LS3,
                             "source": "lcfc_res",
                             "volume_uL": 200,
                             "totalvials": 3,
                             "sampleperiod": [60,600,1140], #1min, 10min, 10min
                             "spacingmethod": Spacingmethod.custom,
                             "spacingfactor": 1.0,
                             "timeoffset": 60.0,
                             },
            # "to_global_params":["_eche_sample_no"],
            "from_global_params":{
                        "_eche_sample_no":"liquid_sample_no"
                        },
            "save_rcp": True,
            "save_data": True,
            "start_condition": action_start_condition.wait_for_endpoint, # orch is waiting for all action_dq to finish
            # "plate_id": None,
            })
        action_list.append(Action(inputdict=action_dict))


   
        # take last liquid sample and clean
        action_dict = decisionObj.as_dict()
        action_dict.update({
            "action_server": "PAL",
            "action_name": "run_method",
            "action_params": {
                             "liquid_sample_no": -5, # signals to use fifth last item in liquid sample DB
                             "method": PALmethods.archive,
                             "tool": PALtools.LS3,
                             "source": "lcfc_res",
                             "volume_uL": 200,
                             "totalvials": 1,
                             "sampleperiod": 0.0,
                             "spacingmethod": Spacingmethod.custom,
                             "spacingfactor": 1.0,
                             "timeoffset": 60.0,
                             "wash1": 1, # dont use True or False but 0 AND 1
                             "wash2": 1,
                             "wash3": 1,
                             "wash4": 1,
                             },
            # "to_global_params":["_eche_sample_no"],
            "from_global_params":{
                        "_eche_sample_no":"liquid_sample_no"
                        },
            "save_rcp": True,
            "save_data": True,
            "start_condition": action_start_condition.wait_for_all, # orch is waiting for all action_dq to finish
            # "plate_id": None,
            })
        action_list.append(Action(inputdict=action_dict))

    action_list.append(ADSS_shutdown(decisionObj))


    return action_list