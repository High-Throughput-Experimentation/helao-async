"""Experiment library exercising the websocket simulator action server.

Builds experiments that alternate orchestrator waits with ``acquire_data``
calls against the ``SIM`` server to validate end-to-end live-data
visualization through websockets.
"""

__all__ = ["SIM_websocket_data"]

from socket import gethostname

from helao.core.models.machine import MachineModel
from helao.core.models.process_contrib import ProcessContrib

from helao.helpers.premodels import ActionPlanMaker
from helao.helpers.lib_decorators import experiment

# list valid experiment functions
EXPERIMENTS = __all__

ORCH_HOST = gethostname().lower()
ORCH_server = MachineModel(server_name="ORCH", machine_name=ORCH_HOST).as_dict()
SIM_server = MachineModel(server_name="SIM", machine_name=ORCH_HOST).as_dict()


@experiment(version=1)
def SIM_websocket_data(
    wait_time: float = 3.0,
    data_duration: float = 5.0,
) -> list:
    """Build two wait-then-acquire process pairs against the websocket simulator.

    Each ``acquire_data`` action is marked as a process boundary, producing
    two complete processes per experiment.

    Args:
        wait_time: Orchestrator wait duration before each acquisition.
        data_duration: Duration of each simulated acquisition.

    Returns:
        Planned actions: wait, acquire, wait, acquire.
    """
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

    return apm.planned_actions
