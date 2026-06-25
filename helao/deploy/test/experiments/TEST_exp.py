"""Experiment library for exercising orchestrator scheduling features.

Defines short experiments that combine ``wait``/``add_global_param``/
``conditional_stop`` actions on the orchestrator itself to verify
non-blocking dispatch and conditional sequence termination.
"""

__all__ = ["TEST_sub_noblocking", "TEST_sub_conditional_stop", "TEST_sub_wait_acquire"]


from socket import gethostname

# from typing import Optional

from helao.framework.domain.run_models import RunExperiment as Experiment
from helao.framework.domain.plan_makers import ActionPlanMaker
from helao.framework.models.machine import MachineModel as MM
from helao.framework.support.lib_decorators import experiment

# from helao.core.models.action_start_condition import ActionStartCondition
# from helao.core.models.process_contrib import ProcessContrib


EXPERIMENTS = __all__

ORCH_server = MM(server_name="ORCH", machine_name=gethostname().lower()).as_dict()
PAL_server = MM(server_name="PAL", machine_name=gethostname().lower()).as_dict()
CALC_server = MM(server_name="CALC", machine_name=gethostname().lower()).as_dict()
SIM_server = MM(server_name="SIM", machine_name=gethostname().lower()).as_dict()


@experiment(version=1)
def TEST_sub_noblocking(
    wait_time: float = 3.0,
    dummy_param: float = 0.0,
):
    """Build an experiment with a non-blocking wait followed by a blocking wait.

    Args:
        wait_time: Base wait duration; the non-blocking wait uses 10x this.
        dummy_param: Unused placeholder parameter exposed for sequence
            wiring tests.

    Returns:
        The configured ``Experiment`` with an added
        ``test_additional_param`` parameter.
    """
    apm = ActionPlanMaker()
    apm.add(
        ORCH_server,
        "wait",
        {"waittime": wait_time * 10},
        nonblocking=True,
        to_global_params={"waittime": "test_wait"},
    )
    apm.add(ORCH_server, "wait", {"waittime": wait_time})
    exp = apm.experiment
    exp.experiment_params["test_additional_param"] = "test_additional_param_value"
    return exp


@experiment(version=1)
def TEST_sub_conditional_stop(
):
    """Build an experiment that sets a global param and conditionally stops.

    Sets ``global_test`` then calls ``conditional_stop`` to halt the
    sequence before the trailing wait actions execute.

    Returns:
        The configured ``Experiment``.
    """
    apm = ActionPlanMaker()
    apm.add(
        ORCH_server,
        "add_global_param",
        {"param_name": "global_test", "param_value": True},
    )
    apm.add(
        ORCH_server,
        "conditional_stop",
        {"stop_parameter": "global_test", "stop_value": True},
        from_global_act_params={"global_test": "global_test"},
    )
    apm.add(ORCH_server, "wait", {"waittime": 1})
    apm.add(ORCH_server, "wait", {"waittime": 1})
    apm.add(ORCH_server, "wait", {"waittime": 1})
    apm.add(ORCH_server, "wait", {"waittime": 1})
    apm.add(ORCH_server, "wait", {"waittime": 1})
    return apm.experiment


@experiment(version=1)
def TEST_sub_wait_acquire(
    wait_time_s: float = 2.0,
    acq_duration_s: float = 3.0,
    acquisition_rate: float = 0.2,
):
    """Short SP-ORCH-5 smoke experiment: an ORCH ``wait`` then a SIM recording.

    Dispatches a blocking ``wait`` on the orchestrator itself, then an
    ``acquire_data`` recording action on the ``SIM`` (``ws_simulator``) action
    server. Exercises the framework orchestrator's real dispatch + status
    ingestion (the SIM action) and its built-in ``wait`` action.

    Args:
        wait_time_s: Seconds for the ORCH ``wait`` action.
        acq_duration_s: Seconds for the SIM ``acquire_data`` recording.
        acquisition_rate: SIM data acquisition period (seconds per sample).

    Returns:
        The configured ``Experiment``.
    """
    apm = ActionPlanMaker()
    apm.add(ORCH_server, "wait", {"waittime": wait_time_s})
    apm.add(
        SIM_server,
        "acquire_data",
        {"duration": acq_duration_s, "acquisition_rate": acquisition_rate},
    )
    return apm.experiment
