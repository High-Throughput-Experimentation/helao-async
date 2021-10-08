"""
Process library for ADSS (RSHS and ANEC2)

process tuples take the form:
(process_group__id, server_key, process, param_dict, preemptive, blocking)

server_key must be a FastAPI process server defined in config
"""

__all__ = ["debug", 
           "ADSS_master_CA", 
           "ADSS_slave_startup", 
           "ADSS_slave_shutdown",
           "ADSS_slave_engage", 
           "ADSS_slave_disengage",
           "ADSS_slave_drain",
           "ADSS_slave_clean_PALtool",
           "ADSS_slave_single_CA",
           "OCV_sqtest"]


from typing import Optional, List, Union

from helao.core.schema import cProcess, cProcess_group, Sequencer

from helao.core.server import process_start_condition
from helao.library.driver.galil_driver import move_modes, transformation_mode

from helao.library.driver.pal_driver import PALmethods, Spacingmethod, PALtools
import helao.core.model.sample as hcms


# list valid sequence functions 
# SEQUENCES = [
#               "debug", 
#               "ADSS_master_CA", 
#               "ADSS_slave_startup", 
#               "ADSS_slave_shutdown",
#               "ADSS_slave_engage", 
#               "ADSS_slave_disengage",
#               "ADSS_slave_drain",
#               "ADSS_slave_clean_PALtool",
#               "ADSS_slave_single_CA",
#               ]

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



def debug(pg_Obj: cProcess_group, 
             d_mm: Optional[str] = "1.0", 
             x_mm: Optional[float] = 0.0, 
             y_mm: Optional[float] = 0.0
             ):
    """Test process for ORCH debugging
    simple plate is e.g. 4534"""
    
     # additional sequence params should be stored in process_group.sequence_pars
     # these are duplicates of the function parameters (currently the op uses functions 
     # parameters to display them in the webUI)
     
     
    # start_condition: 
    # 0: orch is dispatching an unconditional process
    # 1: orch is waiting for endpoint to become available
    # 2: orch is waiting for server to become available
    # 3: (or other): orch is waiting for all process_dq to finish
    
    # holds all processes for this sequence  
    process_list = []



    process_dict = pg_Obj.as_dict()
    process_dict.update({
        "process_server": f"{NI_name}",
        "process_name": "run_cell_IV",
        "process_params": {
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
        "start_condition": process_start_condition.wait_for_all, # orch is waiting for all process_dq to finish
        })
    process_list.append(cProcess(inputdict=process_dict))

    return process_list


def ADSS_slave_startup(pg_Obj: cProcess_group,
              x_mm: Optional[float] = 0.0, 
              y_mm: Optional[float] = 0.0,
              ):
    """Slave sequence
    (1) Move to position
    (2) Engages cell"""

    
    
    x_mm = pg_Obj.sequence_pars.get("x_mm", x_mm)
    y_mm = pg_Obj.sequence_pars.get("y_mm", y_mm)
    
    
    process_list = []

    # move z to home
    process_list.append(ADSS_slave_disengage(pg_Obj))

    # move to position
    process_dict = pg_Obj.as_dict()
    process_dict.update({
        "process_server": f"{MOTOR_name}",
        "process_name": "move",
        "process_params": {
                        "d_mm": [x_mm, y_mm],
                        "axis": ["x", "y"],
                        "mode": move_modes.absolute,
                        "transformation": transformation_mode.platexy,
                        },
        # "save_prc": True,
        "start_condition": process_start_condition.wait_for_all,
        # "plate_id": None,
        })
    process_list.append(cProcess(inputdict=process_dict))

    # seal cell
    process_list.append(ADSS_slave_engage(pg_Obj))

    return process_list


def ADSS_slave_shutdown(pg_Obj: cProcess_group):
    """Slave sequence
    (1) Deep clean PAL tool
    (2) pump liquid out off cell
    (3) Drain cell
    (4) Disengages cell (TBD)"""

    process_list = []

    # deep clean
    process_list.append(ADSS_slave_clean_PALtool(pg_Obj, clean_PAL_tool = PALtools.LS3, clean_PAL_volume_uL = 500))
    # process_dict = pg_Obj.as_dict()
    # process_dict.update({
    #     "process_server": f"{PAL_name}",
    #     "process_name": "PAL_run_method",
    #     "process_params": {
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
    #     # "save_prc": True,
    #     # "save_data": True,
    #     "start_condition": process_start_condition.wait_for_all,
    #     # "plate_id": None,
    #     })
    # process_list.append(cProcess(inputdict=process_dict))

    # set pump flow backward
    process_dict = pg_Obj.as_dict()
    process_dict.update({
        "process_server": f"{NI_name}",
        "process_name": "run_task_pump",
        "process_params": {
                         "pump":"Direction",
                         "on": 1,
                         },
        # "save_prc": True,
        "start_condition": process_start_condition.wait_for_all,
        # "plate_id": None,
        })
    process_list.append(cProcess(inputdict=process_dict))

    # wait some time to pump out the liquid
    process_dict = pg_Obj.as_dict()
    process_dict.update({
        "process_server": f"{ORCH_name}",
        "process_name": "wait",
        "process_params": {
                         "waittime":120,
                         },
        # "save_prc": True,
        "start_condition": process_start_condition.wait_for_all,
        # "plate_id": None,
        })
    process_list.append(cProcess(inputdict=process_dict))


    # drain, TODO
    # process_list.append(ADSS_slave_drain(pg_Obj))


    # turn pump off
    process_dict = pg_Obj.as_dict()
    process_dict.update({
        "process_server": f"{NI_name}",
        "process_name": "run_task_pump",
        "process_params": {
                         "pump":"PeriPump",
                         "on": 0,
                         },
        # "save_prc": True,
        "start_condition": process_start_condition.wait_for_all,
        # "plate_id": None,
        })
    process_list.append(cProcess(inputdict=process_dict))

    # set pump flow forward
    process_dict = pg_Obj.as_dict()
    process_dict.update({
        "process_server": f"{NI_name}",
        "process_name": "run_task_pump",
        "process_params": {
                         "pump":"Direction",
                         "on": 0,
                         },
        "save_prc": True,
        "start_condition": process_start_condition.wait_for_all,
        "plate_id": None,
        })
    process_list.append(cProcess(inputdict=process_dict))



    # move z to home
    # cannot do this without proper drain for now
    # process_list.append(ADSS_slave_disengage(pg_Obj))


    return process_list


def ADSS_slave_drain(pg_Obj: cProcess_group):
    """DUMMY Slave sequence
    Drains electrochemical cell."""

    process_list = []
    # TODO
    return process_list


def ADSS_slave_engage(pg_Obj: cProcess_group):
    """Slave sequence
    Engages and seals electrochemical cell."""
    
    process_list = []

    # engage
    process_dict = pg_Obj.as_dict()
    process_dict.update({
        "process_server": f"{MOTOR_name}",
        "process_name": "move",
        "process_params": {
                        "d_mm": [z_engage],
                        "axis": ["z"],
                        "mode": move_modes.absolute,
                        "transformation": transformation_mode.instrxy,
                        },
        # "save_prc": True,
        "start_condition": process_start_condition.wait_for_all,
        # "plate_id": None,
        })
    process_list.append(cProcess(inputdict=process_dict))

    # seal
    process_dict = pg_Obj.as_dict()
    process_dict.update({
        "process_server": f"{MOTOR_name}",
        "process_name": "move",
        "process_params": {
                        "d_mm": [z_seal],
                        "axis": ["z"],
                        "mode": move_modes.absolute,
                        "transformation": transformation_mode.instrxy,
                        },
        # "save_prc": True,
        "start_condition": process_start_condition.wait_for_all,
        # "plate_id": None,
        })
    process_list.append(cProcess(inputdict=process_dict))

    return process_list


def ADSS_slave_disengage(pg_Obj: cProcess_group):
    """Slave sequence
    Disengages and seals electrochemical cell."""

    process_list = []

    process_dict = pg_Obj.as_dict()
    process_dict.update({
        "process_server": f"{MOTOR_name}",
        "process_name": "move",
        "process_params": {
                        "d_mm": [z_home],
                        "axis": ["z"],
                        "mode": move_modes.absolute,
                        "transformation": transformation_mode.instrxy,
                        },
        # "save_prc": True,
        "start_condition": process_start_condition.wait_for_all,
        # "plate_id": None,
        })
    process_list.append(cProcess(inputdict=process_dict))

    return process_list


def ADSS_slave_clean_PALtool(pg_Obj: cProcess_group, 
                             clean_PAL_tool: Optional[str] = PALtools.LS3, 
                             clean_PAL_volume_uL: Optional[int] = 500
                             ):
    """Slave sequence
    Performs deep clean of selected PAL tool."""


    process_list = []

    clean_PAL_volume_uL = pg_Obj.sequence_pars.get("clean_PAL_volume_uL", clean_PAL_volume_uL)
    clean_PAL_tool = pg_Obj.sequence_pars.get("clean_PAL_tool", clean_PAL_tool)
    
    # deep clean
    process_dict = pg_Obj.as_dict()
    process_dict.update({
        "process_server": f"{PAL_name}",
        "process_name": "PAL_deepclean",
        "process_params": {
                          # "liquid_sample_no_in": 0,
                          # "PAL_method": PALmethods.deepclean,
                          "PAL_tool": clean_PAL_tool,
                          # "PAL_source": "elec_res1",
                          "PAL_volume_uL": clean_PAL_volume_uL,
                          # "PAL_totalvials": 1,
                          # "PAL_sampleperiod": [0.0],
                          # "PAL_spacingmethod": Spacingmethod.linear,
                          # "PAL_spacingfactor": 1.0,
                          # "PAL_wash1": 1, # dont use True or False but 0 AND 1
                          # "PAL_wash2": 1,
                          # "PAL_wash3": 1,
                          # "PAL_wash4": 1,
                          },
        # "save_prc": True,
        # "save_data": True,
        "start_condition": process_start_condition.wait_for_all,
        # "plate_id": None,
        })
    process_list.append(cProcess(inputdict=process_dict))

    return process_list


def ADSS_master_CA(pg_Obj: cProcess_group,
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
           
    """Chronoamperometry (current response on amplied potential):
        x_mm / y_mm: plate coordinates of sample;
        potential (Volt): applied potential;
        CA_duration_sec (sec): how long the potential is applied;
        samplerate_sec (sec): sampleperiod of Gamry;
        filltime_sec (sec): how long it takes to fill the cell with liquid or empty it."""



    x_mm = pg_Obj.sequence_pars.get("x_mm", x_mm)
    y_mm = pg_Obj.sequence_pars.get("y_mm", y_mm)
    liquid_sample_no = pg_Obj.sequence_pars.get("liquid_sample_no", liquid_sample_no)
    CA_potentials_vsRHE = pg_Obj.sequence_pars.get("CA_potentials_vsRHE", CA_potentials_vsRHE)
    ref_vs_nhe = pg_Obj.sequence_pars.get("ref_vs_nhe", ref_vs_nhe)
    pH = pg_Obj.sequence_pars.get("pH", pH)
    CA_duration_sec = pg_Obj.sequence_pars.get("CA_duration_sec", CA_duration_sec)
    aliquot_times_sec = pg_Obj.sequence_pars.get("aliquot_times_sec", aliquot_times_sec)
    OCV_duration_sec = pg_Obj.sequence_pars.get("OCV_duration_sec", OCV_duration_sec)
    samplerate_sec = pg_Obj.sequence_pars.get("samplerate_sec", samplerate_sec)
    filltime_sec = pg_Obj.sequence_pars.get("filltime_sec", filltime_sec)
    
    toNHE = -1.0*ref_vs_nhe-0.059*pH
    cycles = len(CA_potentials_vsRHE)


    # list to hold all processes
    process_list = []


    # add startup processes to list
    process_list.append(ADSS_slave_startup(pg_Obj, x_mm, y_mm))


    for cycle in range(cycles):
        potential = CA_potentials_vsRHE(cycle)+toNHE
        print(f" ... cycle {cycle} potential:", potential)
        if cycle == 0:
        
            # fill liquid, no wash (assume it was cleaned before)
            process_dict = pg_Obj.as_dict()
            process_dict.update({
                "process_server": f"{PAL_name}",
                "process_name": "PAL_run_method",
                "process_params": {
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
                "save_prc": True,
                "save_data": True,
                "start_condition": process_start_condition.wait_for_all, # orch is waiting for all process_dq to finish
                # "plate_id": None,
                })
            process_list.append(cProcess(inputdict=process_dict))

        
            # set pump flow forward
            process_dict = pg_Obj.as_dict()
            process_dict.update({
                "process_server": f"{NI_name}",
                "process_name": "run_task_pump",
                "process_params": {
                                 "pump":"Direction",
                                 "on": 0,
                                 },
                "save_prc": True,
                "start_condition": process_start_condition.wait_for_all,
                "plate_id": None,
                })
            process_list.append(cProcess(inputdict=process_dict))
        
            # turn on pump
            process_dict = pg_Obj.as_dict()
            process_dict.update({
                "process_server": f"{NI_name}",
                "process_name": "run_task_pump",
                "process_params": {
                                 "pump":"PeriPump",
                                 "on": 1,
                                 },
                "save_prc": True,
                "start_condition": process_start_condition.wait_for_all,
                "plate_id": None,
                })
            process_list.append(cProcess(inputdict=process_dict))

        
            # wait some time to pump in the liquid
            process_dict = pg_Obj.as_dict()
            process_dict.update({
                "process_server": f"{ORCH_name}",
                "process_name": "wait",
                "process_params": {
                                 "waittime":filltime_sec,
                                 },
                "save_prc": True,
                "start_condition": process_start_condition.wait_for_all,
                "plate_id": None,
                })
            process_list.append(cProcess(inputdict=process_dict))
            
        else:    
            # fill liquid, no wash (assume it was cleaned before)
            process_dict = pg_Obj.as_dict()
            process_dict.update({
                "process_server": f"{PAL_name}",
                "process_name": "PAL_run_method",
                "process_params": {
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
                "save_prc": True,
                "save_data": True,
                "start_condition": process_start_condition.wait_for_all, # orch is waiting for all process_dq to finish
                # "plate_id": None,
                })
            process_list.append(cProcess(inputdict=process_dict))


    
        process_list.append(ADSS_slave_single_CA(pg_Obj,
                                                x_mm = x_mm,
                                                y_mm = y_mm,
                                                CA_single_potential = potential,
                                                samplerate_sec = samplerate_sec,
                                                OCV_duration_sec = OCV_duration_sec,
                                                CA_duration_sec = CA_duration_sec,
                                                aliquot_times_sec = aliquot_times_sec
                                                ))

    process_list.append(ADSS_slave_shutdown(pg_Obj))

    return process_list


def ADSS_slave_single_CA(pg_Obj: cProcess_group,
              x_mm: Optional[float] = 0.0, 
              y_mm: Optional[float] = 0.0,
              CA_single_potential: Optional[float] = 0.0,
              samplerate_sec: Optional[float] = 1, 
              OCV_duration_sec: Optional[float] = 60, 
              CA_duration_sec: Optional[float] = 1320, 
              aliquot_times_sec: Optional[List[float]] = [60,600,1140],
              ):


    x_mm = pg_Obj.sequence_pars.get("x_mm", x_mm)
    y_mm = pg_Obj.sequence_pars.get("y_mm", y_mm)
    samplerate_sec = pg_Obj.sequence_pars.get("samplerate_sec", samplerate_sec)
    CA_single_potential = pg_Obj.sequence_pars.get("CA_single_potential", CA_single_potential)
    OCV_duration_sec = pg_Obj.sequence_pars.get("OCV_duration_sec", OCV_duration_sec)
    CA_duration_sec = pg_Obj.sequence_pars.get("CA_duration_sec", CA_duration_sec)
    
    
    process_list = []
    
    # OCV
    process_dict = pg_Obj.as_dict()
    process_dict.update({
        "process_server": f"{PSTAT_name}",
        "process_name": "run_OCV",
        "process_params": {
                        "Tval": OCV_duration_sec,
                        "SampleRate": samplerate_sec,
                        "TTLwait": -1,  # -1 disables, else select TTL 0-3
                        "TTLsend": -1,  # -1 disables, else select TTL 0-3
                        "IErange": "auto",
                        },
        "save_prc": True,
        "save_data": True,
        "start_condition": process_start_condition.wait_for_all, # orch is waiting for all process_dq to finish
        # "plate_id": None,

        })
    process_list.append(cProcess(inputdict=process_dict))


    # take liquid sample
    process_dict = pg_Obj.as_dict()
    process_dict.update({
        "process_server": f"{PAL_name}",
        "process_name": "PAL_run_method",
        "process_params": {
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
        "save_prc": True,
        "save_data": True,
        "start_condition": process_start_condition.wait_for_all, # orch is waiting for all process_dq to finish
        # "plate_id": None,
        })
    process_list.append(cProcess(inputdict=process_dict))


    # apply potential
    process_dict = pg_Obj.as_dict()
    process_dict.update({
        "process_server": f"{PSTAT_name}",
        "process_name": "run_CA",
        "process_params": {
                        "Vval": CA_single_potential,
                        "Tval": CA_duration_sec,
                        "SampleRate": samplerate_sec,
                        "TTLwait": -1,  # -1 disables, else select TTL 0-3
                        "TTLsend": -1,  # -1 disables, else select TTL 0-3
                        "IErange": "auto",
                        },
        "save_prc": True,
        "save_data": True,
        "start_condition": process_start_condition.wait_for_all, # orch is waiting for all process_dq to finish
        # "plate_id": None,
        })
    process_list.append(cProcess(inputdict=process_dict))


    # take multiple scheduled liquid samples
    process_dict = pg_Obj.as_dict()
    process_dict.update({
        "process_server": f"{PAL_name}",
        "process_name": "PAL_run_method",
        "process_params": {
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
        "save_prc": True,
        "save_data": True,
        "start_condition": process_start_condition.wait_for_endpoint, # orch is waiting for all process_dq to finish
        # "plate_id": None,
        })
    process_list.append(cProcess(inputdict=process_dict))


    # take last liquid sample and clean
    process_dict = pg_Obj.as_dict()
    process_dict.update({
        "process_server": f"{PAL_name}",
        "process_name": "PAL_run_method",
        "process_params": {
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
        "save_prc": True,
        "save_data": True,
        "start_condition": process_start_condition.wait_for_all, # orch is waiting for all process_dq to finish
        # "plate_id": None,
        })
    process_list.append(cProcess(inputdict=process_dict))

    return process_list


def OCV_sqtest(pg_Obj: cProcess_group,
               OCV_duration_sec: Optional[float] = 10.0,
               samplerate_sec: Optional[float] = 1.0,
              ):

    """This is the description of the sequence which will be displayed
       in the operator webgui. For all function parameters (except pg_Obj)
       a input field will be (dynamically) presented in the OP webgui.""" 
    
    additional_local_var = 12
    sq = Sequencer(pg_Obj) # exposes function parameters via sq.pars

    sq.add_process(
        {
        "process_server": f"{PSTAT_name}",
        "process_name": "run_OCV",
        "process_params": {
                        "Tval": sq.pars.OCV_duration_sec,
                        "SampleRate": sq.pars.samplerate_sec,
                        "TTLwait": -1,  # -1 disables, else select TTL 0-3
                        "TTLsend": -1,  # -1 disables, else select TTL 0-3
                        "IErange": "auto",
                        },
        "save_prc": True,
        "save_data": True,
        "start_condition": process_start_condition.wait_for_all, # orch is waiting for all process_dq to finish
        }
    )

    return sq.process_list # returns complete process list to orch
