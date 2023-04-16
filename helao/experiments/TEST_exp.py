"""
Experiment library for Orchestrator testing
server_key must be a FastAPI action server defined in config
"""

__all__ = ["TEST_sub_noblocking"]


from typing import Optional
from socket import gethostname

from helao.helpers.premodels import Experiment, ActionPlanMaker
from helaocore.models.action_start_condition import ActionStartCondition
from helaocore.models.machine import MachineModel as MM
from helaocore.models.process_contrib import ProcessContrib

from helao.drivers.io.enum import TriggerType


EXPERIMENTS = __all__

ORCH_server = MM(server_name="ORCH", machine_name=gethostname().lower()).as_dict()
PAL_server = MM(server_name="PAL", machine_name=gethostname().lower()).as_dict()
CALC_server = MM(server_name="CALC", machine_name=gethostname().lower()).as_dict()


def TEST_sub_noblocking(
    experiment: Experiment,
    experiment_version: int = 1,
    wait_time: float = 3.0,
):
    apm = ActionPlanMaker()
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.wait_time*10}, nonblocking=True)
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.wait_time})
    return apm.action_list
