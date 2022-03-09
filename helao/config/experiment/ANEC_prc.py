"""
Action library for ANEC

server_key must be a FastAPI action server defined in config
"""

__all__ = [
           "ANEC_GC_preparation",
           "ANEC_cleanup",
           "ANEC_run_CA",
         #   "OCV_sqtest",
         #   "CA_sqtest"
          ]

###
from socket import gethostname
from typing import Optional, List, Union

from helaocore.schema import Action, Experiment, ActionPlanMaker
from helaocore.model.action_start_condition import ActionStartCondition
from helao.library.driver.pal_driver import Spacingmethod, PALtools
from helaocore.model.sample import (
                                    SolidSample,
                                    LiquidSample
                                   )
from helaocore.model.machine import MachineModel

# list valid experiment functions 
EXPERIMENTS = __all__

PSTAT_name = MachineModel(
                server_name = "PSTAT",
                machine_name = gethostname()
             ).json_dict()

MOTOR_name = MachineModel(
                server_name = "MOTOR",
                machine_name = gethostname()
             ).json_dict()

NI_name = MachineModel(
                server_name = "NI",
                machine_name = gethostname()
             ).json_dict()
ORCH_name = MachineModel(
                server_name = "ORCH",
                machine_name = gethostname()
             ).json_dict()
PAL_name = MachineModel(
                server_name = "PAL",
                machine_name = gethostname()
             ).json_dict()

# z positions for ADSS cell
z_home = 0.0
# touches the bottom of cell
z_engage = 2.5
# moves it up to put pressure on seal
z_seal = 4.5


def ANEC_GC_preparation(experiment: Experiment,
                        toolGC: Optional[str] = "HS 2",
                        source: Optional[str] = "cell1_we",
                        volume_ul_GC: Optional[int] = 300
                        ):
    """Flush and purge ANEC cell
    
    (1) Drain cell and purge with CO2 for 10 seconds
    (2) Fill cell with liquid for 90 seconds
    (3) Equilibrate for 15 seconds
    (4) Drain cell and purge with CO2 for 60 seconds
    (5) Fill cell with liquid for 90 seconds

    Args:
        experiment (Experiment): Active experiment object supplied by Orchestrator
        toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
        volume_ul_GC: GC injection volume
        
    """

    sq = ActionPlanMaker(experiment) # exposes function parameters via sq.pars

    ###### Drain cell and flush with CO2

    # step 1
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "pump",
        "action_params": {
            "pump": "PeriPump1",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 2
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "pump",
        "action_params": {
            "pump": "Direction",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 3
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "liquidvalve",
        "action_params": {
            "liquidvalve": "down",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 4
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "gasvalve",
        "action_params": {
            "gas_valve": "CO2",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 5
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "pump",
        "action_params": {
            "pump": "PeriPump2",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 6
    sq.add_action({
        "action_server": f"{ORCH_name}",
        "action_name": "wait",
        "action_params": {
                        "waittime":10,
                        },
        "start_condition": ActionStartCondition.wait_for_all,
        })

    ###### Fill cell with liquid

    # step 7
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "liquidvalve",
        "action_params": {
            "liquidvalve": "down",
            "on": 0,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 8
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "liquidvalve",
        "action_params": {
            "liquidvalve": "up",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 9
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "pump",
        "action_params": {
            "pump": "Direction",
            "on": 0,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 10
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "gasvalve",
        "action_params": {
            "gasvalve": "CO2",
            "on": 0,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 11
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "liquidvalve",
        "action_params": {
            "liquidvalve": "liquid",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 12
    sq.add_action({
        "action_server": f"{ORCH_name}",
        "action_name": "wait",
        "action_params": {
                        "waittime":90,
                        },
        "start_condition": ActionStartCondition.wait_for_all,
        })

    ###### Equilibration

    # step 13
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "liquidvalve",
        "action_params": {
            "liquidvalve": "liquid",
            "on": 0,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 14
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "gasvalve",
        "action_params": {
            "gasvalve": "CO2",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 15
    sq.add_action({
        "action_server": f"{ORCH_name}",
        "action_name": "wait",
        "action_params": {
                        "waittime":15,
                        },
        "start_condition": ActionStartCondition.wait_for_all,
        })

    # step 16
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "gasvalve",
        "action_params": {
            "gasvalve": "atm",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 17
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "liquidvalve",
        "action_params": {
            "liquidvalve": "up",
            "on": 0,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 18
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "pump",
        "action_params": {
            "pump": "PeriPump2",
            "on": 0,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 19
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "gasvalve",
        "action_params": {
            "gasvalve": "CO2",
            "on": 0,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 20
    sq.add_action({
        "action_server": f"{ORCH_name}",
        "action_name": "wait",
        "action_params": {
                        "waittime":1,
                        },
        "start_condition": ActionStartCondition.wait_for_all,
        })

    # step 21
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "gasvalve",
        "action_params": {
            "gasvalve": "atm",
            "on": 0,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 22
    sq.add_action({
        "action_server": f"{ORCH_name}",
        "action_name": "wait",
        "action_params": {
                        "waittime":60,
                        },
        "start_condition": ActionStartCondition.wait_for_all,
        })

    ###### Drain cell and flush with CO2

    # step 23
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "pump",
        "action_params": {
            "pump": "PeriPump1",
            "on": 0,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 24
    sq.add_action({
        "action_server": f"{PAL_name}",
        "action_name": "PAL_ANEC_GC",
        "action_params": {
            "toolGC": PALtools(toolGC),
            "source": source,
            "volume_ul_GC": volume_ul_GC,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 25
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "pump",
        "action_params": {
            "pump": "PeriPump1",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 26
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "pump",
        "action_params": {
            "pump": "Direction",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 27
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "liquidvalve",
        "action_params": {
            "liquidvalve": "down",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 28
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "gasvalve",
        "action_params": {
            "gasvalve": "CO2",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 29
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "pump",
        "action_params": {
            "pump": "PeriPump2",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 30
    sq.add_action({
        "action_server": f"{ORCH_name}",
        "action_name": "wait",
        "action_params": {
                        "waittime":90,
                        },
        "start_condition": ActionStartCondition.wait_for_all,
        })

    return sq.action_list



def ANEC_run_CA(experiment: Experiment,
                        toolGC: Optional[str] = "HS 2",
                        toolarchive: Optional[str] = "LS 3",
                        source: Optional[str] = "cell1_we",
                        volume_ul_GC: Optional[int] = 300,
                        volume_ul_archive: Optional[int] = 500,
                        wash1: Optional[bool] = True,
                        wash2: Optional[bool] = True,
                        wash3: Optional[bool] = True,
                        wash4: Optional[bool] = False,
                        Vval: Optional[float] = 0.0,
                        Tval: Optional[float] = 10.0,
                        SampleRate: Optional[float] = 0.01,
                        TTLwait: Optional[int] = -1,
                        TTLsend: Optional[int] = -1,
                        IErange: Optional[str]= 'auto'
                        ):
    """Flush and purge ANEC cell
    
    (1) Fill cell with liquid for 90 seconds
    (2) Equilibrate for 15 seconds
    (3) run CA
    (4) mix product
    (5) Drain cell and purge with CO2 for 60 seconds

    Args:
        experiment (Experiment): Active experiment object supplied by Orchestrator
        toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
        volume_ul_GC: GC injection volume
        
    """

    sq = ActionPlanMaker(experiment) # exposes function parameters via sq.pars
    

    ###### Fill cell with liquid

    # step 1
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "liquidvalve",
        "action_params": {
            "liquidvalve": "down",
            "on": 0,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 2
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "liquidvalve",
        "action_params": {
            "liquidvalve": "up",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 3
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "pump",
        "action_params": {
            "pump": "Direction",
            "on": 0,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 4
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "gasvalve",
        "action_params": {
            "gasvalve": "CO2",
            "on": 0,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 5
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "liquidvalve",
        "action_params": {
            "liquidvalve": "liquid",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 6
    sq.add_action({
        "action_server": f"{ORCH_name}",
        "action_name": "wait",
        "action_params": {
                        "waittime":90,
                        },
        "start_condition": ActionStartCondition.wait_for_all,
        })

    ###### Equilibration

    # step 7
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "liquidvalve",
        "action_params": {
            "liquidvalve": "liquid",
            "on": 0,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 8
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "gasvalve",
        "action_params": {
            "gasvalve": "CO2",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 9
    sq.add_action({
        "action_server": f"{ORCH_name}",
        "action_name": "wait",
        "action_params": {
                        "waittime":15,
                        },
        "start_condition": ActionStartCondition.wait_for_all,
        })

    # step 10
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "gasvalve",
        "action_params": {
            "gasvalve": "atm",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 11
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "liquidvalve",
        "action_params": {
            "liquidvalve": "up",
            "on": 0,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 12
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "pump",
        "action_params": {
            "pump": "PeriPump2",
            "on": 0,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 13
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "gasvalve",
        "action_params": {
            "gasvalve": "CO2",
            "on": 0,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 14
    sq.add_action({
        "action_server": f"{ORCH_name}",
        "action_name": "wait",
        "action_params": {
                        "waittime":1,
                        },
        "start_condition": ActionStartCondition.wait_for_all,
        })

    # step 15
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "gasvalve",
        "action_params": {
            "gasvalve": "atm",
            "on": 0,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    #start echem
    # step 16
    sq.add_action({
        "action_server": f"{PSTAT_name}",
        "action_name": "run_CA",
        "action_params": {
                        "Vval": Vval,
                        "Tval": Tval,
                       " SampleRate": SampleRate,
                        "TTLwait": TTLwait,
                        "TTLsend": TTLsend,
                        "IErange": IErange
                        },
        "start_condition": ActionStartCondition.wait_for_all,
        })

    ###### mixing and taking aliquot
    # step 17
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "pump",
        "action_params": {
            "pump": "Direction",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })
    
    # step 18
    sq.add_action({
        "action_server": f"{PSTAT_name}",
        "action_name": "run_CA",
        "action_params": {
                        "waittime":60,
                        },
        "start_condition": ActionStartCondition.wait_for_all,
        })
    
    # step 19
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "pump",
        "action_params": {
            "pump": "Direction",
            "on": 0,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })
    
    # step 20
    sq.add_action({
        "action_server": f"{PSTAT_name}",
        "action_name": "run_CA",
        "action_params": {
                        "waittime":30,
                        },
        "start_condition": ActionStartCondition.wait_for_all,
        })
    
    # step 21
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "pump",
        "action_params": {
            "pump": "Direction",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })
    
    # step 22
    sq.add_action({
        "action_server": f"{PSTAT_name}",
        "action_name": "run_CA",
        "action_params": {
                        "waittime":60,
                        },
        "start_condition": ActionStartCondition.wait_for_all,
        })
    
    # step 23
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "pump",
        "action_params": {
            "pump": "Direction",
            "on": 0,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })
    
    # step 24
    sq.add_action({
        "action_server": f"{PSTAT_name}",
        "action_name": "run_CA",
        "action_params": {
                        "waittime":30,
                        },
        "start_condition": ActionStartCondition.wait_for_all,
        })
    # step 25
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "pump",
        "action_params": {
            "pump": "PeriPump1",
            "on": 0,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 26
    sq.add_action({
        "action_server": f"{PAL_name}",
        "action_name": "PAL_ANEC_aliquot",
        "action_params": {
            "toolGC": PALtools(toolGC),
            "toolarchive": PALtools(toolarchive),
            "source": source,
            "volume_ul_GC": volume_ul_GC,
            "volume_ul_archive": volume_ul_archive,
            "wash1": wash1,
            "wash2": wash2,
            "wash3": wash3,
            "wash4": wash4,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })
    
    # drain the cell and flush with CO2
    # step 27
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "pump",
        "action_params": {
            "pump": "PeriPump1",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 28
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "pump",
        "action_params": {
            "pump": "Direction",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 29
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "liquidvalve",
        "action_params": {
            "liquidvalve": "down",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 30
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "gasvalve",
        "action_params": {
            "gasvalve": "CO2",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 31
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "pump",
        "action_params": {
            "pump": "PeriPump2",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 32
    sq.add_action({
        "action_server": f"{ORCH_name}",
        "action_name": "wait",
        "action_params": {
                        "waittime":90,
                        },
        "start_condition": ActionStartCondition.wait_for_all,
        })

    return sq.action_list


def ANEC_cleanup(experiment: Experiment):
    """Flush and purge ANEC cell
    
    (1) Drain cell and purge with CO2 for 10 seconds
    (2) Fill cell with liquid for 90 seconds
    (3) Equilibrate for 15 seconds
    (4) Drain cell and purge with CO2 for 60 seconds
    (5) Fill cell with liquid for 90 seconds

    Args:
        experiment (Experiment): Active experiment object supplied by Orchestrator
        toolGC (str): PAL tool string enumeration (see pal_driver.PALTools)
        volume_ul_GC: GC injection volume
        
    """

    sq = ActionPlanMaker(experiment) # exposes function parameters via sq.pars


    ###### Fill cell with liquid

    # step 1
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "liquidvalve",
        "action_params": {
            "liquidvalve": "down",
            "on": 0,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 2
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "liquidvalve",
        "action_params": {
            "liquidvalve": "up",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 3
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "pump",
        "action_params": {
            "pump": "Direction",
            "on": 0,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 4
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "gasvalve",
        "action_params": {
            "gasvalve": "CO2",
            "on": 0,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 5
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "liquidvalve",
        "action_params": {
            "liquidvalve": "liquid",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 6
    sq.add_action({
        "action_server": f"{ORCH_name}",
        "action_name": "wait",
        "action_params": {
                        "waittime":90,
                        },
        "start_condition": ActionStartCondition.wait_for_all,
        })

    ###### Equilibration

    # step 7
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "liquidvalve",
        "action_params": {
            "liquidvalve": "liquid",
            "on": 0,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 8
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "gasvalve",
        "action_params": {
            "gasvalve": "CO2",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 9
    sq.add_action({
        "action_server": f"{ORCH_name}",
        "action_name": "wait",
        "action_params": {
                        "waittime":15,
                        },
        "start_condition": ActionStartCondition.wait_for_all,
        })

    # step 10
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "gasvalve",
        "action_params": {
            "gasvalve": "atm",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 11
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "liquidvalve",
        "action_params": {
            "liquidvalve": "up",
            "on": 0,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 12
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "pump",
        "action_params": {
            "pump": "PeriPump2",
            "on": 0,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 13
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "gasvalve",
        "action_params": {
            "gasvalve": "CO2",
            "on": 0,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 14
    sq.add_action({
        "action_server": f"{ORCH_name}",
        "action_name": "wait",
        "action_params": {
                        "waittime":1,
                        },
        "start_condition": ActionStartCondition.wait_for_all,
        })

    # step 15
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "gasvalve",
        "action_params": {
            "gasvalve": "atm",
            "on": 0,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 16
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "pump",
        "action_params": {
            "pump": "Direction",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 17
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "liquidvalve",
        "action_params": {
            "liquidvalve": "down",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 18
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "gasvalve",
        "action_params": {
            "gasvalve": "CO2",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 19
    sq.add_action({
        "action_server": f"{NI_name}",
        "action_name": "pump",
        "action_params": {
            "pump": "PeriPump2",
            "on": 1,
            },
        "start_condition": ActionStartCondition.wait_for_all
    })

    # step 20
    sq.add_action({
        "action_server": f"{ORCH_name}",
        "action_name": "wait",
        "action_params": {
                        "waittime":90,
                        },
        "start_condition": ActionStartCondition.wait_for_all,
        })

    return sq.action_list

# def CA(experiment: Experiment,
#        CA_potential_V: Optional[float] = 0.0,
#        CA_duration_sec: Optional[float] = 10.0,
#        samplerate_sec: Optional[float] = 1.0,
       
#        ):
#     """Perform a CA measurement."""
    
#     # todo, I will try to write a function which will do this later
#     # I assume we need a base experiment class for this
#     CA_potential_V = experiment.experiment_params.get("CA_potential_V", CA_potential_V)
#     CA_duration_sec = experiment.experiment_params.get("CA_duration_sec", CA_duration_sec)
#     samplerate_sec = experiment.experiment_params.get("samplerate_sec", samplerate_sec)



#     # list to hold all actions
#     action_list = []
    
    
#     # apply potential
#     action_dict = experiment.as_dict()
#     action_dict.update({
#         "action_server_name": f"{PSTAT_name}",
#         "action_name": "run_CA",
#         "action_params": {
#                         "Vval": CA_potential_V,
#                         "Tval": CA_duration_sec,
#                         "SampleRate": samplerate_sec,
#                         "TTLwait": -1,  # -1 disables, else select TTL 0-3
#                         "TTLsend": -1,  # -1 disables, else select TTL 0-3
#                         "IErange": "auto",
#                         },
#         "save_act": True,
#         "save_data": True,
#         "start_condition": ActionStartCondition.wait_for_all, # orch is waiting for all action_dq to finish
#         # "plate_id": None,
#         })
#     action_list.append(Action(inputdict=action_dict))

#     return action_list


# def OCV_sqtest(experiment: Experiment,
#                OCV_duration_sec: Optional[float] = 10.0,
#                samplerate_sec: Optional[float] = 1.0,
#               ):

#     """This is the description of the experiment which will be displayed
#        in the operator webgui. For all function parameters (except experiment)
#        a input field will be (dynamically) presented in the OP webgui.""" 
    
    
#     sq = ActionPlanMaker(experiment) # exposes function parameters via sq.pars

#     sq.add_action(
#         {
#         "action_server_name": f"{PSTAT_name}",
#         "action_name": "run_OCV",
#         "action_params": {
#                         "Tval": sq.pars.OCV_duration_sec,
#                         "SampleRate": sq.pars.samplerate_sec,
#                         "TTLwait": -1,  # -1 disables, else select TTL 0-3
#                         "TTLsend": -1,  # -1 disables, else select TTL 0-3
#                         "IErange": "auto",
#                         },
#         "save_act": True,
#         "save_data": True,
#         "start_condition": ActionStartCondition.wait_for_all, # orch is waiting for all action_dq to finish
#         }
#     )

#     return sq.action_list # returns complete action list to orch


# def CA_sqtest(experiment: Experiment,
#               Ewe_vs_RHE: Optional[float] = 0.0,
#               Eref: Optional[float] = 0.2,
#               pH: Optional[float] = 10.0,
#               duration_sec: Optional[float] = 10.0,
#               samplerate_sec: Optional[float] = 1.0,
#               ):

#     """This is the description of the experiment which will be displayed
#        in the operator webgui. For all function parameters (except experiment)
#        a input field will be (dynamically) presented in the OP webgui.""" 
    
    
#     sq = ActionPlanMaker(experiment) # exposes function parameters via sq.pars

#     sq.add_action(
#         {
#         "action_server_name": f"{PSTAT_name}",
#         "action_name": "run_CA",
#         "action_params": {
#                         "Vval": sq.pars.Ewe_vs_RHE-1.0*sq.pars.Eref-0.059*sq.pars.pH,
#                         "Tval": sq.pars.duration_sec,
#                         "SampleRate": sq.pars.samplerate_sec,
#                         "TTLwait": -1,  # -1 disables, else select TTL 0-3
#                         "TTLsend": -1,  # -1 disables, else select TTL 0-3
#                         "IErange": "auto",
#                         },
#         "save_act": True,
#         "save_data": True,
#         "start_condition": ActionStartCondition.wait_for_all, # orch is waiting for all action_dq to finish
#         }
#     )

#     return sq.action_list # returns complete action list to orch
