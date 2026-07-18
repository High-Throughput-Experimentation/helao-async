"""Non-default-identity experiment library for §10.3 item 2 (P1b2b).

Verbatim copy of helao/deploy/test/experiments/simulatews_exp.py's
SIM_websocket_data with the orchestrator MachineModel renamed to HEXORC:
test libraries hardcode server_name="ORCH", so exercising a non-default
orch identity (MINOR-8) requires a library that targets the renamed key.
Referenced by path from goldenhexid.yml; zero legacy edits."""

__all__ = ["SIM_websocket_data_hexid"]

from socket import gethostname

from helao.core.models.machine import MachineModel
from helao.core.models.process_contrib import ProcessContrib

from helao.helpers.premodels import ActionPlanMaker
from helao.helpers.lib_decorators import experiment

# list valid experiment functions
EXPERIMENTS = __all__

ORCH_HOST = gethostname().lower()
HEXORC_server = MachineModel(server_name="HEXORC", machine_name=ORCH_HOST).as_dict()
SIM_server = MachineModel(server_name="SIM", machine_name=ORCH_HOST).as_dict()


@experiment(version=1)
def SIM_websocket_data_hexid(
    wait_time: float = 3.0,
    data_duration: float = 5.0,
) -> list:
    """Two wait-then-acquire pairs against the websocket simulator, with the
    orchestrator's self-hosted waits addressed to the RENAMED orch identity."""
    apm = ActionPlanMaker()

    apm.add(
        HEXORC_server,
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
        HEXORC_server,
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
