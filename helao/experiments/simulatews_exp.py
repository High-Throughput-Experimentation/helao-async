"""
Action library for websocket simulator

server_key must be a FastAPI action server defined in config
"""

__all__ = ["SIM_websocket_data"]

from socket import gethostname

from helaocore.models.machine import MachineModel
from helaocore.models.process_contrib import ProcessContrib

from helao.helpers.premodels import Experiment, ActionPlanMaker


# list valid experiment functions
EXPERIMENTS = __all__

ORCH_HOST = gethostname().lower()
ORCH_server = MachineModel(server_name="ORCH", machine_name=ORCH_HOST).as_dict()
SIM_server = MachineModel(server_name="SIM", machine_name=ORCH_HOST).as_dict()


def SIM_websocket_data(
    experiment: Experiment,
    experiment_version: int = 1,
    wait_time: float = 3.0,
    data_duration: float = 5.0,
):
    """Produces two data acquisition processes."""
    apm = ActionPlanMaker()

    apm.add(
        ORCH_server,
        "wait",
        {"waittime": wait_time},
        process_contrib=[ProcessContrib.action_params],
    )
    apm.add(
        SIM_server,
        "acquire_data",
        {"duration": data_duration},
        process_contrib=[ProcessContrib.files, ProcessContrib.run_use],
        process_finish=True,
    )
    apm.add(
        ORCH_server,
        "wait",
        {"waittime": wait_time},
        process_contrib=[ProcessContrib.action_params],
    )
    apm.add(
        SIM_server,
        "acquire_data",
        {"duration": data_duration},
        process_contrib=[ProcessContrib.files, ProcessContrib.run_use],
        process_finish=True,
    )

    return apm.action_list
