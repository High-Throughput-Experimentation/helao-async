"""
Experiment library for Orchestrator testing
server_key must be a FastAPI action server defined in config
"""

__all__ = ["OERSIM_sub_load_plate", "OERSIM_sub_measure_CP", "OERSIM_sub_decision"]


from typing import Optional, Union
from socket import gethostname

from helao.helpers.premodels import Experiment, ActionPlanMaker
from helaocore.models.action_start_condition import ActionStartCondition
from helaocore.models.machine import MachineModel as MM
from helaocore.models.process_contrib import ProcessContrib

from helao.drivers.io.enum import TriggerType


EXPERIMENTS = __all__

ORCH_server = MM(server_name="ORCH", machine_name=gethostname().lower()).as_dict()
CPSIM_server = MM(server_name="CPSIM", machine_name=gethostname().lower()).as_dict()
GPSIM_server = MM(server_name="GPSIM", machine_name=gethostname().lower()).as_dict()


def OERSIM_sub_load_plate(
    experiment: Experiment,
    experiment_version: int = 1,
    plate_id: int = 0,
):
    apm = ActionPlanMaker()
    apm.add(CPSIM_server, "change_plate", {"plate_id": apm.pars.plate_id})
    apm.add(
        CPSIM_server, "get_loaded_plate", {}, to_global_exp_params=["_loaded_plate_id"]
    )


def OERSIM_sub_measure_CP(
    experiment: Experiment,
    experiment_version: int = 1,
    init_random_points: int = 5,
):
    apm = ActionPlanMaker()
    apm.add(
        CPSIM_server, "get_loaded_plate", {}, to_global_exp_params=["_loaded_plate_id"]
    )
    apm.add(
        GPSIM_server,
        "initialize_plate",
        {
            "num_random_points": apm.pars.init_random_points,
            "reinitialize": False,
        },
        from_globalexp_params={"_loaded_plate_id": "plate_id"},
    )
    apm.add(
        GPSIM_server,
        "get_progress",
        {},
        from_globalexp_params={"_loaded_plate_id": "plate_id"},
        to_global_exp_params=[
            "_expected_improvement",
            "_feature",
            "_plate_step",
            "_global_step",
        ],
    )
    apm.add(
        CPSIM_server, "measure_cp", {}, from_globalexp_params={"_feature": "comp_vec"}
    )
    apm.add(
        GPSIM_server,
        "update_model",
        {},
        from_globalexp_params={"_loaded_plate_id": "plate_id", "_feature": "comp_vec"},
    )
    return apm.action_list


def OERSIM_sub_decision(
    experiment: Experiment,
    experiment_version: int = 1,
    stop_condition: str = "max_iters",  # {"none", "max_iters", "min_stdev", "min_ei"}
    thresh_value: Union[float, int] = 10,
):
    apm = ActionPlanMaker()
    apm.add(
        CPSIM_server, "get_loaded_plate", {}, to_global_exp_params=["_loaded_plate_id"]
    )
    # call progress action to force model fit if nothing has been measured
    apm.add(
        GPSIM_server,
        "get_progress",
        {},
        from_globalexp_params={"_loaded_plate_id": "plate_id"},
    )
    apm.add(
        GPSIM_server,
        "check_condition",
        {
            "stop_condtion": apm.pars.stop_condition,
            "thresh_value": apm.pars.thresh_value,
        },
        from_globalexp_params={"_loaded_plate_id": "plate_id"},
    )
    return apm.action_list


def OERSIM_sub_activelearn(
    experiment: Experiment,
    experiment_version: int = 1,
    init_random_points: int = 5,
    stop_condition: str = "max_iters",  # {"none", "max_iters", "min_stdev", "min_ei"}
    thresh_value: Union[float, int] = 10,
):
    apm = ActionPlanMaker()
    apm.add_action_list(
        OERSIM_sub_measure_CP(
            experiment=experiment,
            init_random_points=apm.pars.init_random_points,
        )
    )
    apm.add_action_list(
        OERSIM_sub_decision(
            experiment=experiment,
            stop_condition=apm.pars.stop_condition,
            thresh_value=apm.pars.thresh_value,
        )
    )
    return apm.action_list
