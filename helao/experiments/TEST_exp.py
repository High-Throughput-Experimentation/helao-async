"""
Experiment library for Orchestrator testing
server_key must be a FastAPI action server defined in config
"""

__all__ = ["TEST_sub_noblocking", "TEST_sub_conditional_stop"]


from socket import gethostname

# from typing import Optional

from helao.helpers.premodels import Experiment, ActionPlanMaker
from helao.core.models.machine import MachineModel as MM

# from helao.core.models.action_start_condition import ActionStartCondition
# from helao.core.models.process_contrib import ProcessContrib


EXPERIMENTS = __all__

ORCH_server = MM(server_name="ORCH", machine_name=gethostname().lower()).as_dict()
PAL_server = MM(server_name="PAL", machine_name=gethostname().lower()).as_dict()
CALC_server = MM(server_name="CALC", machine_name=gethostname().lower()).as_dict()


def TEST_sub_noblocking(
    experiment: Experiment,
    experiment_version: int = 1,
    wait_time: float = 3.0,
    dummy_param: float = 0.0,
):
    apm = ActionPlanMaker()
    apm.add(
        ORCH_server, "wait", {"waittime": wait_time * 10}, nonblocking=True, to_global_params={"waittime": "test_wait"}
    )
    apm.add(ORCH_server, "wait", {"waittime": wait_time})
    exp = apm.experiment
    exp.experiment_params["test_additional_param"] = "test_additional_param_value"
    return exp


def TEST_sub_conditional_stop(
    experiment: Experiment,
    experiment_version: int = 1,
):
    apm = ActionPlanMaker()
    apm.add(
        ORCH_server,
        "add_globalexp_param",
        {"param_name": "globalexp_test", "param_value": True},
    )
    apm.add(
        ORCH_server,
        "conditional_stop",
        {"stop_parameter": "globalexp_test", "stop_value": True},
        from_global_params={"globalexp_test": "globalexp_test"},
    )
    apm.add(ORCH_server, "wait", {"waittime": 1})
    apm.add(ORCH_server, "wait", {"waittime": 1})
    apm.add(ORCH_server, "wait", {"waittime": 1})
    apm.add(ORCH_server, "wait", {"waittime": 1})
    apm.add(ORCH_server, "wait", {"waittime": 1})
    return apm.experiment
