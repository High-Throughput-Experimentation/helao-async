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

from helao.helpers.premodels import Experiment, ActionPlanMaker
from helao.drivers.robot.pal_driver import PALtools
from helaocore.models.sample import SolidSample, LiquidSample
from helaocore.models.machine import MachineModel
from helaocore.models.action_start_condition import ActionStartCondition
from helaocore.models.process_contrib import ProcessContrib


# list valid experiment functions
EXPERIMENTS = __all__

ORCH_HOST = gethostname()
ORCH_server = MachineModel(server_name="ORCH", machine_name=ORCH_HOST).json_dict()
SPEC_server = MachineModel(server_name="SPEC", machine_name=ORCH_HOST).json_dict()


def SPEC_test_wait(
    experiment: Experiment,
    experiment_version: int = 1,
    wait_time1: Optional[int] = 5,
    wait_time2: Optional[int] = 10,
    wait_time3: Optional[int] = 15,
):
    """ORCH wait debugging

    Args:
        exp (Experiment): Active experiment object supplied by Orchestrator
        wait_time: seconds to wait before collecting spectra

    """

    apm = ActionPlanMaker()  # exposes function parameters via apm.pars
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.wait_time1})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.wait_time2})
    apm.add(ORCH_server, "wait", {"waittime": apm.pars.wait_time3})
    apm.add(SPEC_server, "measure_spec", {"int_time": 50})
    apm.add(SPEC_server, "measure_spec", {"int_time": 50})
    apm.add(SPEC_server, "measure_spec", {"int_time": 50})
    return apm.action_list
