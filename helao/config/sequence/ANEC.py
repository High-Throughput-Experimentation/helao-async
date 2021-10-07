"""
Process library for ADSS (RSHS and ANEC2)

process tuples take the form:
(process_group__id, server_key, process, param_dict, preemptive, blocking)

server_key must be a FastAPI process server defined in config
"""

__all__ = ["debug", 
           "CA"]


from typing import Optional, List, Union


from helao.core.schema import cProcess, cProcess_group, Sequencer
from helao.core.server import process_start_condition
from helao.library.driver.pal_driver import PALmethods, Spacingmethod, PALtools
import helao.core.model.sample as hcms

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



def debug(process_group_Obj: cProcess_group, 
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



    process_dict = process_group_Obj.as_dict()
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


def CA(process_group_Obj: cProcess_group,
       CA_potential_V: Optional[float] = 0.0,
       CA_duration_sec: Optional[float] = 10.0,
       samplerate_sec: Optional[float] = 1.0,
       
       ):
    """Perform a CA measurement."""
    
    # todo, I will try to write a function which will do this later
    # I assume we need a base sequence class for this
    CA_potential_V = process_group_Obj.sequence_pars.get("CA_potential_V", CA_potential_V)
    CA_duration_sec = process_group_Obj.sequence_pars.get("CA_duration_sec", CA_duration_sec)
    samplerate_sec = process_group_Obj.sequence_pars.get("samplerate_sec", samplerate_sec)



    # list to hold all processes
    process_list = []
    
    
    # apply potential
    process_dict = process_group_Obj.as_dict()
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


def CA_test(process_group_Obj: cProcess_group,
        CA_potential_V: Optional[float] = 0.0,
        CA_duration_sec: Optional[float] = 10.0,
        samplerate_sec: Optional[float] = 1.0,
       
        ):




    
    # todo, I will try to write a function which will do this later
    # I assume we need a base sequence class for this
    CA_potential_V = process_group_Obj.sequence_pars.get("CA_potential_V", CA_potential_V)
    CA_duration_sec = process_group_Obj.sequence_pars.get("CA_duration_sec", CA_duration_sec)
    samplerate_sec = process_group_Obj.sequence_pars.get("samplerate_sec", samplerate_sec)

    sequence = Sequencer(process_group_Obj, locals())
    
    
    sequence.add_process(
        {
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
            }
        )
    
    
    return sequence.process_list
