"""
Process library for ADSS
server_key must be a FastAPI process server defined in config
"""

__all__ = [
           "debug", 
           "ADSS_duaribilty_CAv1", 
           "ADSS_slave_startup", 
           "ADSS_slave_shutdown",
           "ADSS_slave_engage", 
           "ADSS_slave_disengage",
           "ADSS_slave_drain",
           "ADSS_slave_clean_PALtool",
           "ADSS_slave_single_CA",
           "ADSS_slave_unloadall_customs",
           "ADSS_slave_load_solid",
           "ADSS_slave_load_liquid",
          ]


from typing import Optional, List, Union
from socket import gethostname

from helaocore.schema import Process, Sequence, Sequencer
from helaocore.server import process_start_condition
import helaocore.model.sample as hcms

from helao.library.driver.galil_driver import move_modes, transformation_mode
from helao.library.driver.pal_driver import Spacingmethod, PALtools


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

    additional_local_var_added_to_sq = 12
    sq = Sequencer(pg_Obj) # exposes function parameters via sq.pars

    sq.add_process({
        "process_server": f"{PAL_name}",
        "process_name": "archive_custom_unload",
        "process_params": {
                        "custom": "cell1_we"
                        },
        "start_condition": process_start_condition.wait_for_all, # orch is waiting for all process_dq to finish
        })

    sq.add_process({
        "process_server": f"{PAL_name}",
        "process_name": "archive_custom_load",
        "process_params": {
                        "custom": "cell1_we",
                        "load_samples_in": hcms.SampleList(samples=[hcms.SolidSample(**{"sample_no":1,
                                                                                        "plate_id":4534,
                                                                                        "machine_name":"legacy"
                                                                                       })]).dict(),
                        },
        "start_condition": process_start_condition.wait_for_all, # orch is waiting for all process_dq to finish
        })

    sq.add_process({
        "process_server": f"{PAL_name}",
        "process_name": "archive_custom_query_sample",
        "process_params": {
                        "custom": "cell1_we",
                        },
        "to_global_params":["_fast_sample_in"], # save new liquid_sample_no of eche cell to globals
        "start_condition": process_start_condition.wait_for_all, # orch is waiting for all process_dq to finish
        })


    # OCV
    sq.add_process({
        "process_server": f"{PSTAT_name}",
        "process_name": "run_OCV",
        "process_params": {
                        "Tval": 10.0,
                        "SampleRate": 1.0,
                        "TTLwait": -1,  # -1 disables, else select TTL 0-3
                        "TTLsend": -1,  # -1 disables, else select TTL 0-3
                        "IErange": "auto",
                        },
        "from_global_params":{
                    "_fast_sample_in":"fast_samples_in"
                    },
        "start_condition": process_start_condition.wait_for_all, # orch is waiting for all process_dq to finish
        })


    return sq.process_list # returns complete process list to orch



def ADSS_slave_unloadall_customs(pg_Obj: Sequence):
    """last functionality test: 11/29/2021"""
    
    sq = Sequencer(pg_Obj) # exposes function parameters via sq.pars

    sq.add_process({
        "process_server": f"{PAL_name}",
        "process_name": "archive_custom_unloadall",
        "process_params": {
                        },
        "start_condition": process_start_condition.wait_for_all, # orch is waiting for all process_dq to finish
        })

    return sq.process_list # returns complete process list to orch


def ADSS_slave_load_solid(
                          pg_Obj: Sequence, 
                          solid_custom_position: Optional[str] = "cell1_we",
                          solid_plate_id: Optional[int] = 4534,
                          solid_sample_no: Optional[int] = 1
                         ):
    """last functionality test: 11/29/2021"""
    
    sq = Sequencer(pg_Obj) # exposes function parameters via sq.pars
    sq.add_process({
        "process_server": f"{PAL_name}",
        "process_name": "archive_custom_load",
        "process_params": {
                        "custom": sq.pars.solid_custom_position,
                        "load_samples_in": hcms.SampleList(samples=[hcms.SolidSample(**{"sample_no":sq.pars.solid_sample_no,
                                                                                        "plate_id":sq.pars.solid_plate_id,
                                                                                        "machine_name":"legacy"
                                                                                       })]).dict(),
                        },
        "start_condition": process_start_condition.wait_for_all, # orch is waiting for all process_dq to finish
        })
    return sq.process_list # returns complete process list to orch


def ADSS_slave_load_liquid(
                          pg_Obj: Sequence, 
                          liquid_custom_position: Optional[str] = "elec_res1",
                          liquid_sample_no: Optional[int] = 1
                         ):
    """last functionality test: 11/29/2021"""
    
    sq = Sequencer(pg_Obj) # exposes function parameters via sq.pars
    sq.add_process({
        "process_server": f"{PAL_name}",
        "process_name": "archive_custom_load",
        "process_params": {
                        "custom": sq.pars.liquid_custom_position,
                        "load_samples_in": hcms.SampleList(samples=[hcms.LiquidSample(**{"sample_no":sq.pars.liquid_sample_no,
                                                                                        "machine_name":gethostname()
                                                                                       })]).dict(),
                        },
        "start_condition": process_start_condition.wait_for_all, # orch is waiting for all process_dq to finish
        })
    return sq.process_list # returns complete process list to orch


def ADSS_slave_startup(pg_Obj: Sequence,
              solid_custom_position: Optional[str] = "cell1_we",
              solid_plate_id: Optional[int] = 4534,
              solid_sample_no: Optional[int] = 1,
              x_mm: Optional[float] = 0.0, 
              y_mm: Optional[float] = 0.0,
              liquid_custom_position: Optional[str] = "elec_res1",
              liquid_sample_no: Optional[int] = 1
              ):
    """Slave sequence
    (1) Unload all custom position samples
    (2) Load solid sample to cell
    (3) Load liquid sample to reservoir
    (4) Move to position
    (5) Engages cell
    
    last functionality test: 11/29/2021"""

    
    sq = Sequencer(pg_Obj) # exposes function parameters via sq.pars


    # unload all samples from custom positions
    sq.add_process_list(ADSS_slave_unloadall_customs(pg_Obj=pg_Obj))


    # load new requested samples 
    sq.add_process_list(ADSS_slave_load_solid(
        pg_Obj=pg_Obj,
        solid_custom_position = sq.pars.solid_custom_position,
        solid_plate_id = sq.pars.solid_plate_id, 
        solid_sample_no =sq.pars.solid_sample_no
        ))
    
    sq.add_process_list( ADSS_slave_load_liquid(
        pg_Obj=pg_Obj,
        liquid_custom_position = sq.pars.liquid_custom_position,
        liquid_sample_no =sq.pars.liquid_sample_no
        ))

    # turn pump off
    sq.add_process({
        "process_server": f"{NI_name}",
        "process_name": "pump",
        "process_params": {
                         "pump":"peripump",
                         "on": 0,
                         },
        "start_condition": process_start_condition.wait_for_all,
        })

    # set pump flow forward
    sq.add_process({
        "process_server": f"{NI_name}",
        "process_name": "pump",
        "process_params": {
                         "pump":"direction",
                         "on": 0,
                         },
        "start_condition": process_start_condition.wait_for_all,
        })



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
    (4) Disengages cell (TBD)
    
    last functionality test: 11/29/2021"""

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
        "process_name": "pump",
        "process_params": {
                         "pump":"direction",
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
        "process_name": "pump",
        "process_params": {
                         "pump":"peripump",
                         "on": 0,
                         },
        "start_condition": process_start_condition.wait_for_all,
        })

    # set pump flow forward
    sq.add_process({
        "process_server": f"{NI_name}",
        "process_name": "pump",
        "process_params": {
                         "pump":"direction",
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
    Drains electrochemical cell.
    
    last functionality test: 11/29/2021"""

    sq = Sequencer(pg_Obj) # exposes function parameters via sq.pars
    # TODO
    return sq.process_list # returns complete process list to orch


def ADSS_slave_engage(pg_Obj: Sequence):
    """Slave sequence
    Engages and seals electrochemical cell.
    
    last functionality test: 11/29/2021"""
    
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
    Disengages and seals electrochemical cell.
    
    last functionality test: 11/29/2021"""

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
    Performs deep clean of selected PAL tool.
    
    last functionality test: 11/29/2021"""


    sq = Sequencer(pg_Obj) # exposes function parameters via sq.pars
    
    # deep clean
    sq.add_process({
        "process_server": f"{PAL_name}",
        "process_name": "PAL_deepclean",
        "process_params": {
                          "PAL_tool": sq.pars.clean_PAL_tool,
                          "PAL_volume_ul": sq.pars.clean_PAL_volume_ul,
                          },
        "start_condition": process_start_condition.wait_for_all,
        })

    return sq.process_list # returns complete process list to orch


def ADSS_duaribilty_CAv1(pg_Obj: Sequence,
              solid_custom_position: Optional[str] = "cell1_we",
              solid_plate_id: Optional[int] = 4534,
              solid_sample_no: Optional[int] = 1,
              x_mm: Optional[float] = 0.0, 
              y_mm: Optional[float] = 0.0,
              liquid_custom_position: Optional[str] = "elec_res1",
              liquid_sample_no: Optional[int] = 3,
              pH: Optional[float] = 9.53,
              CA_potentials_vsRHE: Optional[List[float]] = [-0.2, 0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
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
        filltime_sec (sec): how long it takes to fill the cell with liquid or empty it.
        
        
        last functionality test: 11/30/2021"""



    sq = Sequencer(pg_Obj) # exposes function parameters via sq.pars

    potentials = [pot-1.0*sq.pars.ref_vs_nhe-0.059*sq.pars.pH  for pot in sq.pars.CA_potentials_vsRHE]

    # add startup processes to list
    sq.add_process_list(ADSS_slave_startup(
                                           pg_Obj=pg_Obj, 
                                           x_mm = sq.pars.x_mm, 
                                           y_mm = sq.pars.y_mm,
                                           solid_custom_position = sq.pars.solid_custom_position,
                                           solid_plate_id = sq.pars.solid_plate_id,
                                           solid_sample_no = sq.pars.solid_sample_no,
                                           liquid_custom_position = sq.pars.liquid_custom_position,
                                           liquid_sample_no = sq.pars.liquid_sample_no,
                                          ))


    for cycle, potential in enumerate(potentials):
        print(f" ... cycle {cycle} potential:", potential)
        if cycle == 0:
        
            # fill liquid, no wash (assume it was cleaned before)
            sq.add_process({
                "process_server": f"{PAL_name}",
                "process_name": "PAL_fillfixed",
                "process_params": {
                                 "PAL_tool": PALtools.LS3,
                                 "PAL_source": "elec_res1",
                                 "PAL_dest": "cell1_we",
                                 "PAL_volume_ul": 10000,
                                 "PAL_wash1": 0,
                                 "PAL_wash2": 0,
                                 "PAL_wash3": 0,
                                 "PAL_wash4": 0,
                                 },
                "start_condition": process_start_condition.wait_for_all, # orch is waiting for all process_dq to finish
                })

        
            # set pump flow forward
            sq.add_process({
                "process_server": f"{NI_name}",
                "process_name": "pump",
                "process_params": {
                                 "pump":"direction",
                                 "on": 0,
                                 },
                "start_condition": process_start_condition.wait_for_all,
                })
        
            # turn on pump
            sq.add_process({
                "process_server": f"{NI_name}",
                "process_name": "pump",
                "process_params": {
                                 "pump":"peripump",
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
                                 "PAL_dest": "cell1_we",
                                 "PAL_volume_ul": 1000,
                                 "PAL_wash1": 0,
                                 "PAL_wash2": 0,
                                 "PAL_wash3": 0,
                                 "PAL_wash4": 0,
                                 },
                "start_condition": process_start_condition.wait_for_all, # orch is waiting for all process_dq to finish
                })
    
        sq.add_process_list(ADSS_slave_single_CA(
                                                 pg_Obj,
                                                 CA_single_potential = potential,
                                                 samplerate_sec = sq.pars.samplerate_sec,
                                                 OCV_duration_sec = sq.pars.OCV_duration_sec,
                                                 CA_duration_sec = sq.pars.CA_duration_sec,
                                                 aliquot_times_sec = sq.pars.aliquot_times_sec
                                                ))


    sq.add_process_list(ADSS_slave_shutdown(pg_Obj = pg_Obj))

    return sq.process_list # returns complete process list to orch


def ADSS_slave_single_CA(pg_Obj: Sequence,
              CA_single_potential: Optional[float] = 0.0,
              samplerate_sec: Optional[float] = 1, 
              OCV_duration_sec: Optional[float] = 60, 
              CA_duration_sec: Optional[float] = 1320, 
              aliquot_times_sec: Optional[List[float]] = [60,600,1140],
              ):
    """last functionality test: 11/29/2021"""
    
    sq = Sequencer(pg_Obj) # exposes function parameters via sq.pars

    # get sample for gamry
    sq.add_process({
        "process_server": f"{PAL_name}",
        "process_name": "archive_custom_query_sample",
        "process_params": {
                        "custom": "cell1_we",
                        },
        "to_global_params":["_fast_sample_in"], # save new liquid_sample_no of eche cell to globals
        "start_condition": process_start_condition.wait_for_all, # orch is waiting for all process_dq to finish
        })
    
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
        "from_global_params":{
                    "_fast_sample_in":"fast_samples_in"
                    },
        "start_condition": process_start_condition.wait_for_all, # orch is waiting for all process_dq to finish
        })


    # take liquid sample
    sq.add_process({
        "process_server": f"{PAL_name}",
        "process_name": "PAL_archive",
        "process_params": {
                          "PAL_tool": PALtools.LS3,
                          "PAL_source": "cell1_we",
                          "PAL_volume_ul": 200,
                          "PAL_sampleperiod": [0.0],
                          "PAL_spacingmethod":  Spacingmethod.linear,
                          "PAL_spacingfactor": 1.0,
                          "PAL_timeoffset": 0.0,
                          "PAL_wash1": 0,
                          "PAL_wash2": 0,
                          "PAL_wash3": 0,
                          "PAL_wash4": 0,
                          },
        "start_condition": process_start_condition.wait_for_all, # orch is waiting for all process_dq to finish
        })


    sq.add_process({
        "process_server": f"{PAL_name}",
        "process_name": "archive_custom_query_sample",
        "process_params": {
                        "custom": "cell1_we",
                        },
        "to_global_params":["_fast_sample_in"], # save new liquid_sample_no of eche cell to globals
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
        "from_global_params":{
                    "_fast_sample_in":"fast_samples_in"
                    },
        "start_condition": process_start_condition.wait_for_all, # orch is waiting for all process_dq to finish
        })


    # take multiple scheduled liquid samples
    sq.add_process({
        "process_server": f"{PAL_name}",
        "process_name": "PAL_archive",
        "process_params": {
                          "PAL_tool": PALtools.LS3,
                          "PAL_source": "cell1_we",
                          "PAL_volume_ul": 200,
                          "PAL_sampleperiod": sq.pars.aliquot_times_sec, #1min, 10min, 10min
                          "PAL_spacingmethod": Spacingmethod.custom,
                          "PAL_spacingfactor": 1.0,
                          "PAL_timeoffset": 60.0,
                          "PAL_wash1": 0,
                          "PAL_wash2": 0,
                          "PAL_wash3": 0,
                          "PAL_wash4": 0,
                          },
        "start_condition": process_start_condition.wait_for_endpoint, # orch is waiting for all process_dq to finish
        })


    # take last liquid sample and clean
    sq.add_process({
        "process_server": f"{PAL_name}",
        "process_name": "PAL_archive",
        "process_params": {
                          "PAL_tool": PALtools.LS3,
                          "PAL_source": "cell1_we",
                          "PAL_volume_ul": 200,
                          "PAL_sampleperiod": [0.0],
                          "PAL_spacingmethod":  Spacingmethod.linear,
                          "PAL_spacingfactor": 1.0,
                          "PAL_timeoffset": 0.0,
                          "PAL_wash1": 1, # dont use True or False but 0 AND 1
                          "PAL_wash2": 1,
                          "PAL_wash3": 1,
                          "PAL_wash4": 1,
                          },
        "start_condition": process_start_condition.wait_for_all, # orch is waiting for all process_dq to finish
        })

    return sq.process_list # returns complete process list to orch
