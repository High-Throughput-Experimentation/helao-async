"""
Process library for ANEC

server_key must be a FastAPI process server defined in config
"""

__all__ = ["debug", 
           "CA",
           "OCV_sqtest",
           "CA_sqtest"]


from typing import Optional, List, Union

from helaocore.schema import cProcess, cProcess_group, Sequencer
from helaocore.server import process_start_condition
from helao.library.driver.pal_driver import PALmethods, Spacingmethod, PALtools
import helaocore.model.sample as hcms

# list valid sequence functions 
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
    
     # additional sequence params should be stored in process_group.sequence_params
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


def CA(pg_Obj: cProcess_group,
       CA_potential_V: Optional[float] = 0.0,
       CA_duration_sec: Optional[float] = 10.0,
       samplerate_sec: Optional[float] = 1.0,
       
       ):
    """Perform a CA measurement."""
    
    # todo, I will try to write a function which will do this later
    # I assume we need a base sequence class for this
    CA_potential_V = pg_Obj.sequence_params.get("CA_potential_V", CA_potential_V)
    CA_duration_sec = pg_Obj.sequence_params.get("CA_duration_sec", CA_duration_sec)
    samplerate_sec = pg_Obj.sequence_params.get("samplerate_sec", samplerate_sec)



    # list to hold all processes
    process_list = []
    
    
    # apply potential
    process_dict = pg_Obj.as_dict()
    process_dict.update({
        "process_server": f"{PSTAT_name}",
        "process_name": "run_CA",
        "process_params": {
                        "Vval": CA_potential_V,
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

    return process_list


def OCV_sqtest(pg_Obj: cProcess_group,
               OCV_duration_sec: Optional[float] = 10.0,
               samplerate_sec: Optional[float] = 1.0,
              ):

    """This is the description of the sequence which will be displayed
       in the operator webgui. For all function parameters (except pg_Obj)
       a input field will be (dynamically) presented in the OP webgui.""" 
    
    
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


def CA_sqtest(pg_Obj: cProcess_group,
              Ewe_vs_RHE: Optional[float] = 0.0,
              Eref: Optional[float] = 0.2,
              pH: Optional[float] = 10.0,
              duration_sec: Optional[float] = 10.0,
              samplerate_sec: Optional[float] = 1.0,
              ):

    """This is the description of the sequence which will be displayed
       in the operator webgui. For all function parameters (except pg_Obj)
       a input field will be (dynamically) presented in the OP webgui.""" 
    
    
    sq = Sequencer(pg_Obj) # exposes function parameters via sq.pars

    sq.add_process(
        {
        "process_server": f"{PSTAT_name}",
        "process_name": "run_CA",
        "process_params": {
                        "Vval": sq.pars.Ewe_vs_RHE-1.0*sq.pars.Eref-0.059*sq.pars.pH,
                        "Tval": sq.pars.duration_sec,
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
