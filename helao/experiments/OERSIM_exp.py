"""
Experiment library for Orchestrator testing
server_key must be a FastAPI action server defined in config
"""

__all__ = [
    "OERSIM_sub_load_plate",
    "OERSIM_sub_measure_CP",
    "OERSIM_sub_decision",
    "OERSIM_sub_activelearn",
]


from typing import Optional, Union
from socket import gethostname

from helao.helpers.premodels import Experiment, ActionPlanMaker
from helaocore.models.machine import MachineModel as MM


EXPERIMENTS = __all__

ORCH_server = MM(server_name="ORCH", machine_name=gethostname().lower()).as_dict()
CPSIM_server = MM(server_name="CPSIM", machine_name=gethostname().lower()).as_dict()
GPSIM_server = MM(server_name="GPSIM", machine_name=gethostname().lower()).as_dict()


def OERSIM_sub_load_plate(
    experiment: Experiment,
    experiment_version: int = 1,
    plate_id: int = 0,
    init_random_points: int = 5,
):
    apm = ActionPlanMaker()
    apm.add(CPSIM_server, "change_plate", {"plate_id": apm.pars.plate_id})
    apm.add(
        CPSIM_server, "get_loaded_plate", {}, to_globalexp_params=["_loaded_plate_id"]
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


def OERSIM_sub_measure_CP(
    experiment: Experiment,
    experiment_version: int = 1,
    init_random_points: int = 5,
):
    apm = ActionPlanMaker()
    apm.add(
        CPSIM_server, "get_loaded_plate", {}, to_globalexp_params=["_loaded_plate_id"]
    )
    apm.add(
        GPSIM_server,
        "acquire_point",
        {},
        from_globalexp_params={"_loaded_plate_id": "plate_id"},
        to_globalexp_params=["_feature"]
    )
    apm.add(
        CPSIM_server, "measure_cp", {}, from_globalexp_params={"_feature": "comp_vec"}
    )
    apm.add(
        GPSIM_server,
        "update_model",
        {},
        from_globalexp_params={"_loaded_plate_id": "plate_id"},
    )
    return apm.action_list


def OERSIM_sub_decision(
    experiment: Experiment,
    experiment_version: int = 1,
    stop_condition: str = "max_iters",  # {"none", "max_iters", "max_stdev", "max_ei"}
    thresh_value: Union[float, int] = 10,
    repeat_experiment_name: str = "OERSIM_sub_activelearn",
    repeat_experiment_params: dict = {},
    repeat_experiment_kwargs: dict = {},
):
    apm = ActionPlanMaker()
    apm.add(
        CPSIM_server,
        "get_loaded_plate",
        {},
        to_globalexp_params=[
            "_loaded_plate_id",
            "_orch_key",
            "_orch_host",
            "_orch_port",
        ],
    )
    apm.add(
        GPSIM_server,
        "check_condition",
        {
            "stop_condtion": apm.pars.stop_condition,
            "thresh_value": apm.pars.thresh_value,
            "repeat_experiment_name": apm.pars.repeat_experiment_name,
            "repeat_experiment_params": apm.pars.repeat_experiment_params,
            "repeat_experiment_kwargs": apm.pars.repeat_experiment_kwargs,
        },
        from_globalexp_params={
            "_loaded_plate_id": "plate_id",
            "_orch_key": "orch_key",
            "_orch_host": "orch_host",
            "_orch_port": "orch_port",
        },
    )
    return apm.action_list


def OERSIM_sub_activelearn(
    experiment: Experiment,
    experiment_version: int = 1,
    init_random_points: int = 5,
    stop_condition: str = "max_iters",  # {"none", "max_iters", "max_stdev", "max_ei"}
    thresh_value: Union[float, int] = 10,
    repeat_experiment_kwargs: dict = {},
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
            repeat_experiment_name="OERSIM_sub_activelearn",
            repeat_experiment_params={
                k: v
                for k, v in vars(apm.pars).items()
                if not k.startswith("experiment")
            },
            repeat_experiment_kwargs=apm.pars.repeat_experiment_kwargs,
        )
    )
    return apm.action_list
