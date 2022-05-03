"""
Action library for ANEC

server_key must be a FastAPI action server defined in config
"""

__all__ = [
    "SPEC_test_wait"
]

###
from socket import gethostname
from typing import Optional

from helaocore.schema import Experiment, ActionPlanMaker
from helao.driver.robot.pal_driver import PALtools
from helaocore.model.sample import SolidSample, LiquidSample
from helaocore.model.machine import MachineModel
from helaocore.model.action_start_condition import ActionStartCondition
from helaocore.model.process_contrib import ProcessContrib


# list valid experiment functions
EXPERIMENTS = __all__

ORCH_HOST = gethostname()
ORCH_server = MachineModel(server_name="ORCH", machine_name=ORCH_HOST).json_dict()
SPEC_server = MachineModel(server_name="SPEC", machine_name=ORCH_HOST).json_dict()


def SPEC_test_wait(
    experiment: Experiment,
    experiment_version: int = 1,
    wait_time: Optional[int] = 80,
):
    """ORCH wait debugging

    Args:
        exp (Experiment): Active experiment object supplied by Orchestrator
        wait_time: seconds to wait before collecting spectra

    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.wait_time})
    apm.add(SPEC_server, "measure", {"int_time": 50})
    apm.add(SPEC_server, "measure", {"int_time": 50})
    apm.add(SPEC_server, "measure", {"int_time": 50})
    return apm.action_list
