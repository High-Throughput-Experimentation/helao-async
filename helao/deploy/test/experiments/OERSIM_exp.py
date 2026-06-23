"""Experiment library for the OER active-learning simulator.

Builds action plans that drive the ``CPSIM`` (chronopotentiometry simulator)
and ``GPSIM`` (Gaussian-process surrogate) servers together to load a plate,
measure CPs, decide on the next acquisition, and conditionally requeue
themselves.
"""

__all__ = [
    "OERSIM_sub_load_plate",
    "OERSIM_sub_measure_CP",
    "OERSIM_sub_decision",
    "OERSIM_sub_activelearn",
]


from typing import Optional, Union
from socket import gethostname

from helao.framework.domain.run_models import RunExperiment as Experiment
from helao.framework.domain.plan_makers import ActionPlanMaker
from helao.framework.models.machine import MachineModel as MM
from helao.framework.support.lib_decorators import experiment


EXPERIMENTS = __all__

ORCH_server = MM(server_name="ORCH", machine_name=gethostname().lower()).as_dict()
CPSIM_server = MM(server_name="CPSIM", machine_name=gethostname().lower()).as_dict()
GPSIM_server = MM(server_name="GPSIM", machine_name=gethostname().lower()).as_dict()


@experiment(version=1)
def OERSIM_sub_load_plate(
    plate_id: int = 0,
    init_random_points: int = 5,
):
    """Switch CPSIM to ``plate_id`` and seed GPSIM priors for that plate.

    Args:
        plate_id: Plate to load on CPSIM.
        init_random_points: Number of random initial compositions for GPSIM
            to acquire when initializing priors.
    """
    apm = ActionPlanMaker()
    apm.add(CPSIM_server, "change_plate", {"plate_id": plate_id})
    apm.add(CPSIM_server, "get_loaded_plate", {}, to_global_params=["_loaded_plate_id"])
    apm.add(
        GPSIM_server,
        "initialize_plate",
        {
            "num_random_points": init_random_points,
            "reinitialize": False,
        },
        from_global_act_params={"_loaded_plate_id": "plate_id"},
    )


@experiment(version=1)
def OERSIM_sub_measure_CP(
    init_random_points: int = 5,
) -> list:
    """Acquire the GPSIM-selected composition with a simulated CP and refit.

    Args:
        init_random_points: Forwarded through the plan for downstream
            initialization steps.

    Returns:
        Planned actions: get loaded plate, pick next feature, run simulated
        CP, then update the GPSIM model.
    """
    apm = ActionPlanMaker()
    apm.add(CPSIM_server, "get_loaded_plate", {}, to_global_params=["_loaded_plate_id"])
    apm.add(
        GPSIM_server,
        "acquire_point",
        {},
        from_global_act_params={"_loaded_plate_id": "plate_id"},
        to_global_params=["_feature"],
    )
    apm.add(
        CPSIM_server, "measure_cp", {}, from_global_act_params={"_feature": "comp_vec"}
    )
    apm.add(
        GPSIM_server,
        "update_model",
        {},
        from_global_act_params={"_loaded_plate_id": "plate_id"},
    )
    return apm.planned_actions


@experiment(version=1)
def OERSIM_sub_decision(
    stop_condition: str = "max_iters",  # {"none", "max_iters", "max_stdev", "max_ei"}
    thresh_value: Union[float, int] = 10,
    repeat_experiment_name: str = "OERSIM_sub_activelearn",
    repeat_experiment_params: dict = {},
    repeat_experiment_kwargs: dict = {},
) -> list:
    """Evaluate the active-learning stop condition and optionally requeue.

    Args:
        stop_condition: One of ``"none"``, ``"max_iters"``, ``"max_stdev"``,
            ``"max_ei"``.
        thresh_value: Threshold compared against the chosen stop condition.
        repeat_experiment_name: Name of the experiment to insert when the
            condition is not yet met.
        repeat_experiment_params: Parameters for the inserted experiment.
        repeat_experiment_kwargs: Additional kwargs forwarded to the
            inserted experiment.

    Returns:
        Planned actions: get loaded plate (and orchestrator coords) then
        ask GPSIM to evaluate the stop condition.
    """
    apm = ActionPlanMaker()
    apm.add(
        CPSIM_server,
        "get_loaded_plate",
        {},
        to_global_params=[
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
            "stop_condtion": stop_condition,
            "thresh_value": thresh_value,
            "repeat_experiment_name": repeat_experiment_name,
            "repeat_experiment_params": repeat_experiment_params,
            "repeat_experiment_kwargs": repeat_experiment_kwargs,
        },
        from_global_act_params={
            "_loaded_plate_id": "plate_id",
            "_orch_key": "orch_key",
            "_orch_host": "orch_host",
            "_orch_port": "orch_port",
        },
    )
    return apm.planned_actions


@experiment(version=1)
def OERSIM_sub_activelearn(
    init_random_points: int = 5,
    stop_condition: str = "max_iters",  # {"none", "max_iters", "max_stdev", "max_ei"}
    thresh_value: Union[float, int] = 10,
    repeat_experiment_kwargs: dict = {},
) -> list:
    """One full measure-and-decide iteration of the active-learning loop.

    Concatenates :func:`OERSIM_sub_measure_CP` and :func:`OERSIM_sub_decision`
    so the decision step requeues this same experiment until the stop
    condition is met.

    Args:
        init_random_points: Number of random initial compositions if the GP
            has not yet been initialized for the loaded plate.
        stop_condition: One of ``"none"``, ``"max_iters"``, ``"max_stdev"``,
            ``"max_ei"``.
        thresh_value: Threshold compared against the chosen stop condition.
        repeat_experiment_kwargs: Additional kwargs forwarded to the
            requeued experiment.

    Returns:
        Combined planned actions for measuring the next composition and
        evaluating the stop condition.
    """
    apm = ActionPlanMaker()
    apm.add_actions(
        OERSIM_sub_measure_CP(
            init_random_points=init_random_points,
        )
    )
    apm.add_actions(
        OERSIM_sub_decision(
            stop_condition=stop_condition,
            thresh_value=thresh_value,
            repeat_experiment_name="OERSIM_sub_activelearn",
            repeat_experiment_params={
                k: v
                for k, v in vars(apm.pars).items()
                if not k.startswith("experiment")
            },
            repeat_experiment_kwargs=repeat_experiment_kwargs,
        )
    )
    return apm.planned_actions
