"""Experiment library for exercising orchestrator scheduling features.

Defines short experiments that combine ``wait``/``add_global_param``/
``conditional_stop`` actions on the orchestrator itself to verify
non-blocking dispatch and conditional sequence termination.
"""

EXPERIMENTS = [
    "TEST_sub_conditional_stop",
    "TEST_sub_noblocking",
    "TEST_sub_no_wait_overlap",
    "TEST_sub_stop_during_condition_wait",
]


from socket import gethostname

from helao.core.models.machine import MachineModel as MM
from helao.helpers.lib_decorators import experiment

# from typing import Optional
from helao.helpers.premodels import ActionPlanMaker

from helao.core.models.action_start_condition import ActionStartCondition

# from helao.core.models.process_contrib import ProcessContrib


ORCH_server = MM(server_name="ORCH", machine_name=gethostname().lower()).as_dict()
SIM_server = MM(server_name="SIM", machine_name=gethostname().lower()).as_dict()
PAL_server = MM(server_name="PAL", machine_name=gethostname().lower()).as_dict()
CALC_server = MM(server_name="CALC", machine_name=gethostname().lower()).as_dict()


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
def TEST_sub_conditional_stop():
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
def TEST_sub_no_wait_overlap(
    wait_time: float = 6.0,
    data_duration: float = 6.0,
):
    """Build a blocking ORCH wait with a ``no_wait`` SIM acquisition under it.

    The minimal shape of a SpEC-style experiment: something long is started,
    and the next action must run *while* it runs rather than after it. Two
    different servers, so nothing the action servers do can serialise the
    pair -- if the two are not simultaneously active, the orchestrator
    dispatched them serially and ``no_wait`` was not honoured.

    Args:
        wait_time: Duration of the blocking orchestrator wait.
        data_duration: Duration of the simulated acquisition that must
            overlap it.

    Returns:
        Planned actions: a blocking wait, then a ``no_wait`` acquisition.
    """
    apm = ActionPlanMaker()
    apm.add(ORCH_server, "wait", {"waittime": wait_time})
    apm.add(
        SIM_server,
        "acquire_data",
        {"duration": data_duration},
        start_condition=ActionStartCondition.no_wait,
    )
    return apm.planned_actions


@experiment(version=1)
def TEST_sub_stop_during_condition_wait(
    wait_time: float = 8.0,
    data_duration: float = 2.0,
):
    """Park a second action on a start condition long enough to stop the loop.

    The first action holds the orchestrator's own ``wait`` endpoint for
    ``wait_time``; the second asks for ``wait_for_orch``, so it is popped from
    ``action_dq`` and then blocks in the start-condition wait for that whole
    window. That window is the only place a graceful stop can be requested
    against an action that has already left the queue -- which is what decides
    whether the action is pushed back or runs anyway.

    Args:
        wait_time: How long the orchestrator ``wait`` action holds its
            endpoint, and so how long the second action stays parked.
        data_duration: Duration of the acquisition that must NOT run.

    Returns:
        Planned actions: a long ORCH wait, then a ``wait_for_orch`` acquisition.
    """
    apm = ActionPlanMaker()
    apm.add(ORCH_server, "wait", {"waittime": wait_time})
    apm.add(
        SIM_server,
        "acquire_data",
        {"duration": data_duration},
        start_condition=ActionStartCondition.wait_for_orch,
    )
    return apm.planned_actions
