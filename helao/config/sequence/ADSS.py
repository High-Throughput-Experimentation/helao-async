"""
Process library for ADSS
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

from helaocore.schema import Process, Sequence, Sequencer

from helaocore.server import process_start_condition
from helao.library.driver.galil_driver import move_modes, transformation_mode

from helao.library.driver.pal_driver import Spacingmethod, PALtools
import helaocore.model.sample as hcms

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



def debug(pg_Obj: Sequence, 
             d_mm: Optional[str] = "1.0", 
             x_mm: Optional[float] = 0.0, 
             y_mm: Optional[float] = 0.0
             ):
    """Test process for ORCH debugging
    simple plate is e.g. 4534"""
    
     # additional sequence params should be stored in process_group.sequence_params
     # these are duplicates of the function parameters (currently the op uses functions 
     # parameters to display them in the webUI)
     
     
    # start_condition: 
    # 0: orch is dispatching an unconditional process
    # 1: orch is waiting for endpoint to become available
    # 2: orch is waiting for server to become available
    # 3: (or other): orch is waiting for all process_dq to finish
    
    sq = Sequencer(pg_Obj) # exposes function parameters via sq.pars

    sq.add_process({
        "process_server": f"{NI_name}",
        "process_name": "cellIV",
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
        "start_condition": process_start_condition.wait_for_all, # orch is waiting for all process_dq to finish
        })

    return sq.process_list # returns complete process list to orch


def ADSS_slave_startup(pg_Obj: Sequence,
              x_mm: Optional[float] = 0.0, 
              y_mm: Optional[float] = 0.0,
              ):
    """Slave sequence
    (1) Move to position
    (2) Engages cell"""

    
    sq = Sequencer(pg_Obj) # exposes function parameters via sq.pars

    # move z to home
    sq.add_process_list(ADSS_slave_disengage(pg_Obj))

    # move to position
    sq.add_process({
        "process_server": f"{MOTOR_name}",
        "process_name": "move",
        "process_params": {
                        "d_mm": [sq.pars.x_mm, sq.pars.y_mm],
                        "axis": ["x", "y"],
                        "mode": move_modes.absolute,
                        "transformation": transformation_mode.platexy,
                        },
        "start_condition": process_start_condition.wait_for_all,
        })

    # seal cell
    sq.add_process_list(ADSS_slave_engage(pg_Obj))

    return sq.process_list # returns complete process list to orch


def ADSS_slave_shutdown(pg_Obj: Sequence):
    """Slave sequence
    (1) Deep clean PAL tool
    (2) pump liquid out off cell
    (3) Drain cell
    (4) Disengages cell (TBD)"""

    sq = Sequencer(pg_Obj) # exposes function parameters via sq.pars

    # deep clean
    sq.add_process_list(ADSS_slave_clean_PALtool(pg_Obj, clean_PAL_tool = PALtools.LS3, clean_PAL_volume_ul = 500))
    # sq.add_process({
    #     "process_server": f"{PAL_name}",
    #     "process_name": "PAL_deepclean",
    #     "process_params": {
    #                       "PAL_tool": PALtools.LS3,
    #                       "PAL_volume_ul": 500,
    #                       },
    #     # "save_prc": True,
    #     # "save_data": True,
    #     "start_condition": process_start_condition.wait_for_all,
    #     # "plate_id": None,
    #     })

    # set pump flow backward
    sq.add_process({
        "process_server": f"{NI_name}",
        "process_name": "run_task_pump",
        "process_params": {
                         "pump":"Direction",
                         "on": 1,
                         },
        "start_condition": process_start_condition.wait_for_all,
        })

    # wait some time to pump out the liquid
    sq.add_process({
        "process_server": f"{ORCH_name}",
        "process_name": "wait",
        "process_params": {
                         "waittime":120,
                         },
        "start_condition": process_start_condition.wait_for_all,
        })


    # drain, TODO
    # sq.add_process_list(ADSS_slave_drain(pg_Obj))


    # turn pump off
    sq.add_process({
        "process_server": f"{NI_name}",
        "process_name": "run_task_pump",
        "process_params": {
                         "pump":"PeriPump",
                         "on": 0,
                         },
        "start_condition": process_start_condition.wait_for_all,
        })

    # set pump flow forward
    sq.add_process({
        "process_server": f"{NI_name}",
        "process_name": "run_task_pump",
        "process_params": {
                         "pump":"Direction",
                         "on": 0,
                         },
        "start_condition": process_start_condition.wait_for_all,
        })



    # move z to home
    # cannot do this without proper drain for now
    # sq.add_process_list(ADSS_slave_disengage(pg_Obj))


    return sq.process_list # returns complete process list to orch


def ADSS_slave_drain(pg_Obj: Sequence):
    """DUMMY Slave sequence
    Drains electrochemical cell."""

    sq = Sequencer(pg_Obj) # exposes function parameters via sq.pars
    # TODO
    return sq.process_list # returns complete process list to orch


def ADSS_slave_engage(pg_Obj: Sequence):
    """Slave sequence
    Engages and seals electrochemical cell."""
    
    sq = Sequencer(pg_Obj) # exposes function parameters via sq.pars

    # engage
    sq.add_process({
        "process_server": f"{MOTOR_name}",
        "process_name": "move",
        "process_params": {
                        "d_mm": [z_engage],
                        "axis": ["z"],
                        "mode": move_modes.absolute,
                        "transformation": transformation_mode.instrxy,
                        },
        "start_condition": process_start_condition.wait_for_all,
        })

    # seal
    sq.add_process({
        "process_server": f"{MOTOR_name}",
        "process_name": "move",
        "process_params": {
                        "d_mm": [z_seal],
                        "axis": ["z"],
                        "mode": move_modes.absolute,
                        "transformation": transformation_mode.instrxy,
                        },
        "start_condition": process_start_condition.wait_for_all,
        })

    return sq.process_list # returns complete process list to orch


def ADSS_slave_disengage(pg_Obj: Sequence):
    """Slave sequence
    Disengages and seals electrochemical cell."""

    sq = Sequencer(pg_Obj) # exposes function parameters via sq.pars

    sq.add_process({
        "process_server": f"{MOTOR_name}",
        "process_name": "move",
        "process_params": {
                        "d_mm": [z_home],
                        "axis": ["z"],
                        "mode": move_modes.absolute,
                        "transformation": transformation_mode.instrxy,
                        },
        "start_condition": process_start_condition.wait_for_all,
        })

    return sq.process_list # returns complete process list to orch


def ADSS_slave_clean_PALtool(pg_Obj: Sequence, 
                             clean_PAL_tool: Optional[str] = PALtools.LS3, 
                             clean_PAL_volume_ul: Optional[int] = 500
                             ):
    """Slave sequence
    Performs deep clean of selected PAL tool."""


    sq = Sequencer(pg_Obj) # exposes function parameters via sq.pars
    
    # deep clean
    sq.add_process({
        "process_server": f"{PAL_name}",
        "process_name": "PAL_deepclean",
        "process_params": {
                          # "liquid_sample_no_in": 0,
                          # "PAL_method": PALmethods.deepclean,
                          "PAL_tool": sq.pars.clean_PAL_tool,
                          # "PAL_source": "elec_res1",
                          "PAL_volume_ul": sq.pars.clean_PAL_volume_ul,
                          # "PAL_totalruns": 1,
                          # "PAL_sampleperiod": [0.0],
                          # "PAL_spacingmethod": Spacingmethod.linear,
                          # "PAL_spacingfactor": 1.0,
                          # "PAL_wash1": 1, # dont use True or False but 0 AND 1
                          # "PAL_wash2": 1,
                          # "PAL_wash3": 1,
                          # "PAL_wash4": 1,
                          },
        "start_condition": process_start_condition.wait_for_all,
        })

    return sq.process_list # returns complete process list to orch


def ADSS_master_CA(pg_Obj: Sequence,
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



    sq = Sequencer(pg_Obj) # exposes function parameters via sq.pars

    toNHE = -1.0*sq.pars.ref_vs_nhe-0.059*sq.pars.pH
    cycles = len(sq.pars.CA_potentials_vsRHE)

    # add startup processes to list
    sq.add_process_list(ADSS_slave_startup(
                                           pg_Obj=pg_Obj, 
                                           x_mm = sq.pars.x_mm, 
                                           y_mm = sq.pars.y_mm
                                          ))


    for cycle in range(cycles):
        potential = CA_potentials_vsRHE(cycle)+toNHE
        print(f" ... cycle {cycle} potential:", potential)
        if cycle == 0:
        
            # fill liquid, no wash (assume it was cleaned before)
            sq.add_process({
                "process_server": f"{PAL_name}",
                "process_name": "PAL_fillfixed",
                "process_params": {
                                 "PAL_tool": PALtools.LS3,
                                 "PAL_source": "elec_res1",
                                 "PAL_volume_ul": 10000,
                                 },
                "to_global_params":["_eche_sample_no"], # save new liquid_sample_no of eche cell to globals
                "start_condition": process_start_condition.wait_for_all, # orch is waiting for all process_dq to finish
                })

        
            # set pump flow forward
            sq.add_process({
                "process_server": f"{NI_name}",
                "process_name": "run_task_pump",
                "process_params": {
                                 "pump":"Direction",
                                 "on": 0,
                                 },
                "start_condition": process_start_condition.wait_for_all,
                })
        
            # turn on pump
            sq.add_process({
                "process_server": f"{NI_name}",
                "process_name": "run_task_pump",
                "process_params": {
                                 "pump":"PeriPump",
                                 "on": 1,
                                 },
                "start_condition": process_start_condition.wait_for_all,
                })

        
            # wait some time to pump in the liquid
            sq.add_process({
                "process_server": f"{ORCH_name}",
                "process_name": "wait",
                "process_params": {
                                 "waittime":sq.pars.filltime_sec,
                                 },
                "start_condition": process_start_condition.wait_for_all,
                })
            
        else:    
            # fill liquid, no wash (assume it was cleaned before)
            sq.add_process({
                "process_server": f"{PAL_name}",
                "process_name": "PAL_fill",
                "process_params": {
                                 "PAL_tool": PALtools.LS3,
                                 "PAL_source": "elec_res1",
                                 "PAL_volume_ul": 1000,
                                 },
                "to_global_params":["_eche_sample_no"],
                "start_condition": process_start_condition.wait_for_all, # orch is waiting for all process_dq to finish
                })


    
        sq.add_process_list(ADSS_slave_single_CA(
                                                 pg_Obj,
                                                 x_mm = sq.pars.x_mm,
                                                 y_mm = sq.pars.y_mm,
                                                 CA_single_potential = sq.pars.potential,
                                                 samplerate_sec = sq.pars.samplerate_sec,
                                                 OCV_duration_sec = sq.pars.OCV_duration_sec,
                                                 CA_duration_sec = sq.pars.CA_duration_sec,
                                                 aliquot_times_sec = sq.pars.aliquot_times_sec
                                                ))

    sq.add_process_list(ADSS_slave_shutdown(pg_Obj = pg_Obj))

    return sq.process_list # returns complete process list to orch


def ADSS_slave_single_CA(pg_Obj: Sequence,
              x_mm: Optional[float] = 0.0, 
              y_mm: Optional[float] = 0.0,
              CA_single_potential: Optional[float] = 0.0,
              samplerate_sec: Optional[float] = 1, 
              OCV_duration_sec: Optional[float] = 60, 
              CA_duration_sec: Optional[float] = 1320, 
              aliquot_times_sec: Optional[List[float]] = [60,600,1140],
              ):

    sq = Sequencer(pg_Obj) # exposes function parameters via sq.pars
    
    # OCV
    sq.add_process({
        "process_server": f"{PSTAT_name}",
        "process_name": "run_OCV",
        "process_params": {
                        "Tval": sq.pars.OCV_duration_sec,
                        "SampleRate": sq.pars.samplerate_sec,
                        "TTLwait": -1,  # -1 disables, else select TTL 0-3
                        "TTLsend": -1,  # -1 disables, else select TTL 0-3
                        "IErange": "auto",
                        },
        "start_condition": process_start_condition.wait_for_all, # orch is waiting for all process_dq to finish
        })


    # take liquid sample
    sq.add_process({
        "process_server": f"{PAL_name}",
        "process_name": "PAL_archive",
        "process_params": {
                          "PAL_tool": PALtools.LS3,
                          "PAL_source": "lcfc_res",
                          "PAL_volume_ul": 200,
                          },
        # "to_global_params":["_eche_sample_no"],
        "from_global_params":{
                    "_eche_sample_no":"liquid_sample_no_in"
                    },
        "start_condition": process_start_condition.wait_for_all, # orch is waiting for all process_dq to finish
        })


    # apply potential
    sq.add_process({
        "process_server": f"{PSTAT_name}",
        "process_name": "run_CA",
        "process_params": {
                        "Vval": sq.pars.CA_single_potential,
                        "Tval": sq.pars.CA_duration_sec,
                        "SampleRate": sq.pars.samplerate_sec,
                        "TTLwait": -1,  # -1 disables, else select TTL 0-3
                        "TTLsend": -1,  # -1 disables, else select TTL 0-3
                        "IErange": "auto",
                        },
        "start_condition": process_start_condition.wait_for_all, # orch is waiting for all process_dq to finish
        })


    # take multiple scheduled liquid samples
    sq.add_process({
        "process_server": f"{PAL_name}",
        "process_name": "PAL_archive",
        "process_params": {
                          "PAL_tool": PALtools.LS3,
                          "PAL_source": "lcfc_res",
                          "PAL_volume_ul": 200,
                          # "PAL_totalruns": len(aliquot_times_sec),
                          "PAL_sampleperiod": sq.pars.aliquot_times_sec, #1min, 10min, 10min
                          "PAL_spacingmethod": Spacingmethod.custom,
                          "PAL_spacingfactor": 1.0,
                          "PAL_timeoffset": 60.0,
                          },
        # "to_global_params":["_eche_sample_no"],
        "from_global_params":{
                    "_eche_sample_no":"liquid_sample_no_in"
                    },
        "start_condition": process_start_condition.wait_for_endpoint, # orch is waiting for all process_dq to finish
        })


    # take last liquid sample and clean
    sq.add_process({
        "process_server": f"{PAL_name}",
        "process_name": "PAL_archive",
        "process_params": {
                          "PAL_tool": PALtools.LS3,
                          "PAL_source": "lcfc_res",
                          "PAL_volume_ul": 200,
                          "PAL_wash1": 1, # dont use True or False but 0 AND 1
                          "PAL_wash2": 1,
                          "PAL_wash3": 1,
                          "PAL_wash4": 1,
                          },
        # "to_global_params":["_eche_sample_no"],
        "from_global_params":{
                    "_eche_sample_no":"liquid_sample_no_in"
                    },
        "start_condition": process_start_condition.wait_for_all, # orch is waiting for all process_dq to finish
        })

    return sq.process_list # returns complete process list to orch


def OCV_sqtest(pg_Obj: Sequence,
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
