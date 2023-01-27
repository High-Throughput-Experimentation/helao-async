"""
Experiment library for Orchestrator testing
server_key must be a FastAPI action server defined in config
"""

__all__ = []


from typing import Optional
from socket import gethostname

from helao.helpers.premodels import Experiment, ActionPlanMaker
from helaocore.models.action_start_condition import ActionStartCondition
from helaocore.models.machine import MachineModel as MM
from helaocore.models.process_contrib import ProcessContrib

from helao.drivers.io.enum import TriggerType


EXPERIMENTS = __all__

ORCH_server = MM(server_name="ORCH", machine_name=gethostname()).json_dict()
PAL_server = MM(server_name="PAL", machine_name=gethostname()).json_dict()
CALC_server = MM(server_name="CALC", machine_name=gethostname()).json_dict()


def TEST_sub_noblocking(
    experiment: Experiment,
    experiment_version: int = 1,
    wait_time: float = 10.0,
    reason: str = "wait",
):
    apm = ActionPlanMaker()
    apm.add(ORCH_server, "interrupt", {"reason": apm.pars.reason})
    return apm.action_list
