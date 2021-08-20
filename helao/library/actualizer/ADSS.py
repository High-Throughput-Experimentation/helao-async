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
ACTUALIZERS = [
              "debug", 
              "ADSS_master_CA", 
              "ADSS_slave_startup", 
              "ADSS_slave_shutdown",
              "ADSS_slave_engage", 
              "ADSS_slave_disengage",
              "ADSS_slave_drain",
              "ADSS_slave_clean_PALtool",
              ]

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

from typing import Optional, List, Union


def debug(decisionObj: Decision, 
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
    action_dict.update({
        "action_server": f"{PAL_name}",
        "action_name": "PAL_run_method",
        "action_params": {
                        "liquid_sample_no_in": 1,
                        "PAL_method": PALmethods.fillfixed,
                        "PAL_tool": PALtools.LS3,
                        "PAL_source": "elec_res1",
                        "PAL_volume_uL": 10000,
                        "PAL_totalvials": 1,
                        "PAL_sampleperiod": [0.0],
                        "PAL_spacingmethod": Spacingmethod.linear,
                        "PAL_spacingfactor": 1.0,
                          },
        "to_global_params":["_eche_sample_no"], # save new liquid_sample_no of eche cell to globals
        "from_global_params":{
                    "_eche_sample_no":"liquid_sample_no_in"
                    },
        # "save_rcp": True,
        # "save_data": True,
        "start_condition": action_start_condition.wait_for_all,
        # "plate_id": None,
        })
    action_list.append(Action(inputdict=action_dict))



    action_dict = decisionObj.as_dict()
    action_dict.update({
        "action_server": f"{PAL_name}",
        "action_name": "PAL_run_method",
        "action_params": {
                             "liquid_sample_no_in": None,
                             "PAL_method": PALmethods.archive,
                             "PAL_tool": PALtools.LS3,
                             "PAL_source": "lcfc_res",
                             "PAL_volume_uL": 200,
                             "PAL_totalvials": 1,
                             "PAL_sampleperiod": [0.0],
                             "PAL_spacingmethod": Spacingmethod.linear,
                             "PAL_spacingfactor": 1.0,
                          },
        # "to_global_params":["_eche_sample_no"], # save new liquid_sample_no of eche cell to globals
        "from_global_params":{
                    "_eche_sample_no":"liquid_sample_no_in"
                    },
        # "save_rcp": True,
        # "save_data": True,
        "start_condition": action_start_condition.wait_for_all,
        # "plate_id": None,
        })
    action_list.append(Action(inputdict=action_dict))



    # # # move z to home
    # action_dict = decisionObj.as_dict()
    # action_dict.update({
    #     "action_server": f"{MOTOR_name}",
    #     "action_name": "move",
    #     "action_params": {
    #                     "d_mm": [z_home],
    #                     "axis": ["z"],
    #                     "speed": None,
    #                     "mode": move_modes.absolute,
    #                     "transformation": transformation_mode.instrxy,
    #                     },
    #     # "save_rcp": True,
    #     "start_condition": action_start_condition.wait_for_all,
    #     # "plate_id": None,
    #     })
    # action_list.append(Action(inputdict=action_dict))
    
    



    # action_dict = decisionObj.as_dict()
    # action_dict.update({
    #     "action_server": f"{PSTAT_name}",
    #     "action_name": "run_OCV",
    #     "action_params": {
    #                     "Tval": 10.0,
    #                     "SampleRate": 0.01,
    #                     "TTLwait": -1,  # -1 disables, else select TTL 0-3
    #                     "TTLsend": -1,  # -1 disables, else select TTL 0-3
    #                     "IErange": "auto",
    #                     },
    #     # "action_enum": None,
    #     # "action_abbr": None,
    #     "save_rcp": True,
    #     # "save_data": None,
    #     "start_condition": action_start_condition.no_wait, # orch is waiting for all action_dq to finish
    #     "plate_id": None,
    #     "samples_in": {},
    #     })
    # action_list.append(Action(inputdict=action_dict))

    return action_list


def ADSS_slave_startup(decisionObj: Decision,
              x_mm: Optional[float] = 0.0, 
              y_mm: Optional[float] = 0.0,
              ):
    
    
    action_list = []

    # move z to home
    action_list.append(ADSS_slave_disengage(decisionObj))

    # move to position
    action_dict = decisionObj.as_dict()
    action_dict.update({
        "action_server": f"{MOTOR_name}",
        "action_name": "move",
        "action_params": {
                        "d_mm": [x_mm, y_mm],
                        "axis": ["x", "y"],
                        "mode": move_modes.absolute,
                        "transformation": transformation_mode.platexy,
                        },
        # "save_rcp": True,
        "start_condition": action_start_condition.wait_for_all,
        # "plate_id": None,
        })
    action_list.append(Action(inputdict=action_dict))

    # seal cell
    action_list.append(ADSS_slave_engage(decisionObj))

    return action_list


def ADSS_slave_shutdown(decisionObj: Decision):
    
    action_list = []

    # deep clean
    action_list.append(ADSS_slave_clean_PALtool(decisionObj, clean_PAL_tool = PALtools.LS3, clean_PAL_volume_uL = 500))
    # action_dict = decisionObj.as_dict()
    # action_dict.update({
    #     "action_server": f"{PAL_name}",
    #     "action_name": "PAL_run_method",
    #     "action_params": {
    #                       "liquid_sample_no_in": 0,
    #                       "PAL_method": PALmethods.deepclean,
    #                       "PAL_tool": PALtools.LS3,
    #                       "PAL_source": "elec_res1",
    #                       "PAL_volume_uL": 500,
    #                       "PAL_totalvials": 1,
    #                       "PAL_sampleperiod": [0.0],
    #                       "PAL_spacingmethod": Spacingmethod.linear,
    #                       "PAL_spacingfactor": 1.0,
    #                       "PAL_wash1": 1, # dont use True or False but 0 AND 1
    #                       "PAL_wash2": 1,
    #                       "PAL_wash3": 1,
    #                       "PAL_wash4": 1,
    #                       },
    #     # "save_rcp": True,
    #     # "save_data": True,
    #     "start_condition": action_start_condition.wait_for_all,
    #     # "plate_id": None,
    #     })
    # action_list.append(Action(inputdict=action_dict))

    # set pump flow backward
    action_dict = decisionObj.as_dict()
    action_dict.update({
        "action_server": f"{NI_name}",
        "action_name": "run_task_Pump",
        "action_params": {
                         "pump":"Direction",
                         "on": 1,
                         },
        # "save_rcp": True,
        "start_condition": action_start_condition.wait_for_all,
        # "plate_id": None,
        })
    action_list.append(Action(inputdict=action_dict))

    # wait some time to pump out the liquid
    action_dict = decisionObj.as_dict()
    action_dict.update({
        "action_server": f"{ORCH_name}",
        "action_name": "wait",
        "action_params": {
                         "waittime":120,
                         },
        # "save_rcp": True,
        "start_condition": action_start_condition.wait_for_all,
        # "plate_id": None,
        })
    action_list.append(Action(inputdict=action_dict))


    # drain, TODO
    # action_list.append(ADSS_slave_drain(decisionObj))


    # turn pump off
    action_dict = decisionObj.as_dict()
    action_dict.update({
        "action_server": f"{NI_name}",
        "action_name": "run_task_Pump",
        "action_params": {
                         "pump":"PeriPump",
                         "on": 0,
                         },
        # "save_rcp": True,
        "start_condition": action_start_condition.wait_for_all,
        # "plate_id": None,
        })
    action_list.append(Action(inputdict=action_dict))

    # set pump flow forward
    action_dict = decisionObj.as_dict()
    action_dict.update({
        "action_server": f"{NI_name}",
        "action_name": "run_task_Pump",
        "action_params": {
                         "pump":"Direction",
                         "on": 0,
                         },
        "save_rcp": True,
        "start_condition": action_start_condition.wait_for_all,
        "plate_id": None,
        })
    action_list.append(Action(inputdict=action_dict))



    # move z to home
    # cannot do this without proper drain for now
    # action_list.append(ADSS_slave_disengage(decisionObj))


    return action_list


def ADSS_slave_drain(decisionObj: Decision):
    action_list = []
    # TODO
    return action_list


def ADSS_slave_engage(decisionObj: Decision):
    action_list = []

    # engage
    action_dict = decisionObj.as_dict()
    action_dict.update({
        "action_server": f"{MOTOR_name}",
        "action_name": "move",
        "action_params": {
                        "d_mm": [z_engage],
                        "axis": ["z"],
                        "mode": move_modes.absolute,
                        "transformation": transformation_mode.instrxy,
                        },
        # "save_rcp": True,
        "start_condition": action_start_condition.wait_for_all,
        # "plate_id": None,
        })
    action_list.append(Action(inputdict=action_dict))

    # seal
    action_dict = decisionObj.as_dict()
    action_dict.update({
        "action_server": f"{MOTOR_name}",
        "action_name": "move",
        "action_params": {
                        "d_mm": [z_seal],
                        "axis": ["z"],
                        "mode": move_modes.absolute,
                        "transformation": transformation_mode.instrxy,
                        },
        # "save_rcp": True,
        "start_condition": action_start_condition.wait_for_all,
        # "plate_id": None,
        })
    action_list.append(Action(inputdict=action_dict))

    return action_list


def ADSS_slave_disengage(decisionObj: Decision):
    action_list = []

    action_dict = decisionObj.as_dict()
    action_dict.update({
        "action_server": f"{MOTOR_name}",
        "action_name": "move",
        "action_params": {
                        "d_mm": [z_home],
                        "axis": ["z"],
                        "mode": move_modes.absolute,
                        "transformation": transformation_mode.instrxy,
                        },
        # "save_rcp": True,
        "start_condition": action_start_condition.wait_for_all,
        # "plate_id": None,
        })
    action_list.append(Action(inputdict=action_dict))

    return action_list


def ADSS_slave_clean_PALtool(decisionObj: Decision, 
                             clean_PAL_tool: Optional[str] = PALtools.LS3, 
                             clean_PAL_volume_uL: Optional[int] = 500
                             ):
    action_list = []

    clean_PAL_volume_uL = decisionObj.actualizer_pars.get("clean_PAL_volume_uL", clean_PAL_volume_uL)
    clean_PAL_tool = decisionObj.actualizer_pars.get("clean_PAL_tool", clean_PAL_tool)
    
    # deep clean
    action_dict = decisionObj.as_dict()
    action_dict.update({
        "action_server": f"{PAL_name}",
        "action_name": "PAL_run_method",
        "action_params": {
                          "liquid_sample_no_in": 0,
                          "PAL_method": PALmethods.deepclean,
                          "PAL_tool": clean_PAL_tool,
                          "PAL_source": "elec_res1",
                          "PAL_volume_uL": clean_PAL_volume_uL,
                          "PAL_totalvials": 1,
                          "PAL_sampleperiod": [0.0],
                          "PAL_spacingmethod": Spacingmethod.linear,
                          "PAL_spacingfactor": 1.0,
                          "PAL_wash1": 1, # dont use True or False but 0 AND 1
                          "PAL_wash2": 1,
                          "PAL_wash3": 1,
                          "PAL_wash4": 1,
                          },
        # "save_rcp": True,
        # "save_data": True,
        "start_condition": action_start_condition.wait_for_all,
        # "plate_id": None,
        })
    action_list.append(Action(inputdict=action_dict))

    return action_list


def ADSS_master_CA(decisionObj: Decision,
              x_mm: Optional[float] = 0.0, 
              y_mm: Optional[float] = 0.0,
              liquid_sample_no: Optional[int] = 3,
              pH: Optional[float] = 9.53,
              CA_potentials_vsRHE: Optional[List[float]] = [0.2, 0.4, 0.6, 0.8, 1.0],
              CA_duration_sec: Optional[float] = 1320, 
              aliquot_times_sec: Optional[List[float]] = [60,600,1140],
              OCV_duration_sec: Optional[float] = 60, 
              samplerate_sec: Optional[float] = 1, 
              ref_vs_nhe: Optional[float] = 0.21,
              filltime_sec: Optional[float] = 10.0
              ):
           
    """Chronoamperometry (current response on amplied potential):\n
        x_mm / y_mm: plate coordinates of sample;\n
        potential (Volt): applied potential;\n
        CA_duration_sec (sec): how long the potential is applied;\n
        samplerate_sec (sec): sampleperiod of Gamry;\n
        filltime_sec (sec): how long it takes to fill the cell with liquid or empty it."""



    x_mm = decisionObj.actualizer_pars.get("x_mm", x_mm)
    y_mm = decisionObj.actualizer_pars.get("y_mm", y_mm)
    liquid_sample_no = decisionObj.actualizer_pars.get("liquid_sample_no", liquid_sample_no)
    CA_potentials_vsRHE = decisionObj.actualizer_pars.get("CA_potentials_vsRHE", CA_potentials_vsRHE)
    ref_vs_nhe = decisionObj.actualizer_pars.get("ref_vs_nhe", ref_vs_nhe)
    pH = decisionObj.actualizer_pars.get("pH", pH)
    CA_duration_sec = decisionObj.actualizer_pars.get("CA_duration_sec", CA_duration_sec)
    aliquot_times_sec = decisionObj.actualizer_pars.get("aliquot_times_sec", aliquot_times_sec)
    OCV_duration_sec = decisionObj.actualizer_pars.get("OCV_duration_sec", OCV_duration_sec)
    samplerate_sec = decisionObj.actualizer_pars.get("samplerate_sec", samplerate_sec)
    filltime_sec = decisionObj.actualizer_pars.get("filltime_sec", filltime_sec)
    
    toNHE = -1.0*ref_vs_nhe-0.059*pH
    cycles = len(CA_potentials_vsRHE)


    # list to hold all actions
    action_list = []


    # add startup actions to list
    action_list.append(ADSS_slave_startup(decisionObj, x_mm, y_mm))


    for cycle in range(cycles):
        potential = CA_potentials_vsRHE(cycle)+toNHE;
        print(f" ... cycle {cycle} potential:", potential)
        if cycle == 0:
        
            # fill liquid, no wash (assume it was cleaned before)
            action_dict = decisionObj.as_dict()
            action_dict.update({
                "action_server": f"{PAL_name}",
                "action_name": "PAL_run_method",
                "action_params": {
                                 "liquid_sample_no_in": liquid_sample_no,
                                 "PAL_method": PALmethods.fillfixed,
                                 "PAL_tool": PALtools.LS3,
                                 "PAL_source": "elec_res1",
                                 "PAL_volume_uL": 10000,
                                 "PAL_totalvials": 1,
                                 "PAL_sampleperiod": [0.0],
                                 "PAL_spacingmethod": Spacingmethod.linear,
                                 "PAL_spacingfactor": 1.0,
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
                "action_server": f"{NI_name}",
                "action_name": "run_task_Pump",
                "action_params": {
                                 "pump":"Direction",
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
                "action_server": f"{NI_name}",
                "action_name": "run_task_Pump",
                "action_params": {
                                 "pump":"PeriPump",
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
                "action_server": f"{ORCH_name}",
                "action_name": "wait",
                "action_params": {
                                 "waittime":filltime_sec,
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
                "action_server": f"{PAL_name}",
                "action_name": "PAL_run_method",
                "action_params": {
                                 "liquid_sample_no_in": liquid_sample_no,
                                 "PAL_method": PALmethods.fill,
                                 "PAL_tool": PALtools.LS3,
                                 "PAL_source": "elec_res1",
                                 "PAL_volume_uL": 1000,
                                 "PAL_totalvials": 1,
                                 "PAL_sampleperiod": [0.0],
                                 "PAL_spacingmethod": Spacingmethod.linear,
                                 "PAL_spacingfactor": 1.0,
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
            "action_server": f"{PSTAT_name}",
            "action_name": "run_OCV",
            "action_params": {
                            "Tval": OCV_duration_sec,
                            "SampleRate": samplerate_sec,
                            "TTLwait": -1,  # -1 disables, else select TTL 0-3
                            "TTLsend": -1,  # -1 disables, else select TTL 0-3
                            "IErange": "auto",
                            },
            "save_rcp": True,
            "save_data": None,
            "start_condition": action_start_condition.wait_for_all, # orch is waiting for all action_dq to finish
            # "plate_id": None,
            "samples_in": {},
    
            })
        action_list.append(Action(inputdict=action_dict))


        # take liquid sample
        action_dict = decisionObj.as_dict()
        action_dict.update({
            "action_server": f"{PAL_name}",
            "action_name": "PAL_run_method",
            "action_params": {
                             "liquid_sample_no_in": -1,
                             "PAL_method": PALmethods.archive,
                             "PAL_tool": PALtools.LS3,
                             "PAL_source": "lcfc_res",
                             "PAL_volume_uL": 200,
                             "PAL_totalvials": 1,
                             "PAL_sampleperiod": [0.0],
                             "PAL_spacingmethod": Spacingmethod.linear,
                             "PAL_spacingfactor": 1.0,
                             },
            # "to_global_params":["_eche_sample_no"],
            "from_global_params":{
                        "_eche_sample_no":"liquid_sample_no_in"
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
            "action_server": f"{PSTAT_name}",
            "action_name": "run_CA",
            "action_params": {
                            "Vval": potential,
                            "Tval": CA_duration_sec,
                            "SampleRate": samplerate_sec,
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
            "action_server": f"{PAL_name}",
            "action_name": "PAL_run_method",
            "action_params": {
                             "liquid_sample_no_in": -2, # signals to use second last item in liquid sample DB
                             "PAL_method": PALmethods.archive,
                             "PAL_tool": PALtools.LS3,
                             "PAL_source": "lcfc_res",
                             "PAL_volume_uL": 200,
                             "PAL_totalvials": len(aliquot_times_sec),
                             "PAL_sampleperiod": aliquot_times_sec, #1min, 10min, 10min
                             "PAL_spacingmethod": Spacingmethod.custom,
                             "PAL_spacingfactor": 1.0,
                             "PAL_timeoffset": 60.0,
                             },
            # "to_global_params":["_eche_sample_no"],
            "from_global_params":{
                        "_eche_sample_no":"liquid_sample_no_in"
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
            "action_server": f"{PAL_name}",
            "action_name": "PAL_run_method",
            "action_params": {
                             "liquid_sample_no_in": -5, # signals to use fifth last item in liquid sample DB
                             "PAL_method": PALmethods.archive,
                             "PAL_tool": PALtools.LS3,
                             "PAL_source": "lcfc_res",
                             "PAL_volume_uL": 200,
                             "PAL_totalvials": 1,
                             "PAL_sampleperiod": [0.0],
                             "PAL_spacingmethod": Spacingmethod.custom,
                             "PAL_spacingfactor": 1.0,
                             "PAL_timeoffset": 60.0,
                             "PAL_wash1": 1, # dont use True or False but 0 AND 1
                             "PAL_wash2": 1,
                             "PAL_wash3": 1,
                             "PAL_wash4": 1,
                             },
            # "to_global_params":["_eche_sample_no"],
            "from_global_params":{
                        "_eche_sample_no":"liquid_sample_no_in"
                        },
            "save_rcp": True,
            "save_data": True,
            "start_condition": action_start_condition.wait_for_all, # orch is waiting for all action_dq to finish
            # "plate_id": None,
            })
        action_list.append(Action(inputdict=action_dict))

    action_list.append(ADSS_slave_shutdown(decisionObj))

    return action_list
