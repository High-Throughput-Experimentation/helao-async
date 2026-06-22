"""Targeted tests for ``helao.framework.models.server`` status aggregation.

Exercises the status-sorting branches on `EndpointModel`, `ActionServerModel`,
and `GlobalStatusModel` that the construction-only leaf tests do not reach:
the ``errored`` finished bucket, `find_hlostatus_in_finished` /
`clear_in_finished` substatus paths, and the experiment lifecycle helpers.
"""
from uuid import uuid4

import pytest

from helao.framework.models.action import ActionModel
from helao.framework.models.hlostatus import HloStatus
from helao.framework.models.machine import MachineModel
from helao.framework.models.orchstatus import OrchStatus, LoopStatus, LoopIntent
from helao.framework.models.server import (
    ActionServerModel,
    EndpointModel,
    GlobalStatusModel,
)


ORCH = MachineModel(server_name="orch", machine_name="host")
SRV = MachineModel(server_name="act", machine_name="host")


def _action(statuses, exp_uuid=None, action_uuid=None):
    return ActionModel(
        action_uuid=action_uuid or uuid4(),
        experiment_uuid=exp_uuid,
        orchestrator=ORCH,
        action_status=list(statuses),
    )


# --------------------------------------------------------------------------- #
# EndpointModel.sort_status
# --------------------------------------------------------------------------- #
def test_endpoint_sort_status_moves_finished_to_finished_bucket():
    a = _action([HloStatus.finished])
    ep = EndpointModel(endpoint_name="ep", active_dict={a.action_uuid: a})
    ep.sort_status()
    assert a.action_uuid not in ep.active_dict
    assert a.action_uuid in ep.nonactive_dict[HloStatus.finished]


def test_endpoint_sort_status_buckets_errored_then_updates_existing():
    # First errored action creates the bucket (break branch); the second
    # finds the existing bucket and updates it (line 87 path).
    a1 = _action([HloStatus.finished, HloStatus.errored])
    a2 = _action([HloStatus.finished, HloStatus.errored])
    ep = EndpointModel(
        endpoint_name="ep",
        active_dict={a1.action_uuid: a1, a2.action_uuid: a2},
    )
    ep.sort_status()
    errored = ep.nonactive_dict[HloStatus.errored]
    # exactly one of the two lands in the errored bucket (the bucket-creation
    # iteration breaks before updating; the second updates the existing bucket)
    assert len(errored) == 1
    # both still recorded under finished
    assert a1.action_uuid in ep.nonactive_dict[HloStatus.finished]
    assert a2.action_uuid in ep.nonactive_dict[HloStatus.finished]


def test_endpoint_clear_finished_resets_bucket():
    a = _action([HloStatus.finished])
    ep = EndpointModel(endpoint_name="ep", active_dict={a.action_uuid: a})
    ep.sort_status()
    ep.clear_finished()
    assert ep.nonactive_dict == {HloStatus.finished: {}}


def test_endpoint_str_and_repr():
    a = _action([HloStatus.active])
    ep = EndpointModel(endpoint_name="ep", active_dict={a.action_uuid: a})
    assert "active:" in str(ep)
    assert repr(ep).startswith("<")


# --------------------------------------------------------------------------- #
# ActionServerModel
# --------------------------------------------------------------------------- #
def test_action_server_get_fastapi_json_all_and_single_endpoint():
    ep = EndpointModel(endpoint_name="ep")
    asm = ActionServerModel(action_server=SRV, endpoints={"ep": ep})
    all_json = asm.get_fastapi_json()
    assert "endpoints" in all_json
    one_json = asm.get_fastapi_json(action_name="ep")
    assert list(one_json["endpoints"].keys()) == ["ep"]
    # unknown endpoint returns empty payload
    assert asm.get_fastapi_json(action_name="missing") == {}


def test_action_server_init_endpoints_clears_finished():
    a = _action([HloStatus.finished])
    ep = EndpointModel(endpoint_name="ep", active_dict={a.action_uuid: a})
    ep.sort_status()
    asm = ActionServerModel(action_server=SRV, endpoints={"ep": ep})
    asm.init_endpoints()
    assert ep.nonactive_dict == {HloStatus.finished: {}}


# --------------------------------------------------------------------------- #
# GlobalStatusModel
# --------------------------------------------------------------------------- #
def _global_with_finished(action):
    gsm = GlobalStatusModel(orchestrator=ORCH)
    ep = EndpointModel(
        endpoint_name="ep", active_dict={action.action_uuid: action}
    )
    asm = ActionServerModel(action_server=SRV, endpoints={"ep": ep})
    gsm.update_global_with_acts(asm)
    return gsm


def test_global_actions_idle_and_server_endpoint_free():
    gsm = GlobalStatusModel(orchestrator=ORCH)
    assert gsm.actions_idle() is True
    assert gsm.server_free(SRV) is True
    assert gsm.endpoint_free(SRV, "ep") is True

    active = _action([HloStatus.active])
    ep = EndpointModel(endpoint_name="ep", active_dict={active.action_uuid: active})
    asm = ActionServerModel(action_server=SRV, endpoints={"ep": ep})
    gsm.update_global_with_acts(asm)
    assert gsm.actions_idle() is False
    assert gsm.server_free(SRV) is False
    assert gsm.endpoint_free(SRV, "ep") is False


def test_global_update_sorts_finished_into_nonactive():
    a = _action([HloStatus.finished])
    gsm = _global_with_finished(a)
    assert a.action_uuid in gsm.nonactive_dict[HloStatus.finished]
    assert a.action_uuid not in gsm.active_dict


def test_global_update_existing_server_merges_endpoints():
    a1 = _action([HloStatus.finished])
    gsm = _global_with_finished(a1)
    # second snapshot from the same server with a new endpoint -> merge branch
    a2 = _action([HloStatus.finished])
    ep2 = EndpointModel(endpoint_name="ep2", active_dict={a2.action_uuid: a2})
    asm2 = ActionServerModel(action_server=SRV, endpoints={"ep2": ep2})
    gsm.update_global_with_acts(asm2)
    assert {"ep", "ep2"}.issubset(set(gsm.server_dict[SRV.as_key()].endpoints))


def _global_with_errored_bucket():
    """Build a GlobalStatusModel that actually has a populated `errored` bucket.

    A single errored action only lands in `finished` (the bucket-creation
    iteration in `EndpointModel.sort_status` breaks before updating); the
    errored bucket is only populated from the second errored action onward.
    """
    a1 = _action([HloStatus.finished, HloStatus.errored])
    a2 = _action([HloStatus.finished, HloStatus.errored])
    ep = EndpointModel(
        endpoint_name="ep",
        active_dict={a1.action_uuid: a1, a2.action_uuid: a2},
    )
    asm = ActionServerModel(action_server=SRV, endpoints={"ep": ep})
    gsm = GlobalStatusModel(orchestrator=ORCH)
    gsm.update_global_with_acts(asm)
    return gsm


def test_find_hlostatus_in_finished_direct_bucket():
    gsm = _global_with_errored_bucket()
    # errored bucket exists directly and is non-empty
    found = gsm.find_hlostatus_in_finished(HloStatus.errored)
    assert len(found) == 1
    assert set(found).issubset(set(gsm.nonactive_dict[HloStatus.errored]))


def test_find_hlostatus_in_finished_substatus_path():
    # action carries 'estopped' in its status set but only the 'finished'
    # bucket exists -> the elif/substatus scan branch.
    a = _action([HloStatus.finished, HloStatus.estopped])
    gsm = GlobalStatusModel(orchestrator=ORCH)
    ep = EndpointModel(endpoint_name="ep", active_dict={a.action_uuid: a})
    asm = ActionServerModel(action_server=SRV, endpoints={"ep": ep})
    gsm.update_global_with_acts(asm)
    # estopped is not in main_finished_status, so no estopped bucket is created
    assert HloStatus.estopped not in gsm.nonactive_dict
    found = gsm.find_hlostatus_in_finished(HloStatus.estopped)
    assert a.action_uuid in found


def test_clear_in_finished_direct_bucket():
    gsm = _global_with_errored_bucket()
    gsm.clear_in_finished(HloStatus.errored)
    assert gsm.nonactive_dict[HloStatus.errored] == {}


def test_clear_in_finished_substatus_path_raises_on_nonempty_finished():
    # KNOWN PRE-EXISTING BUG (faithfully ported from helao/core/models/server.py):
    # the substatus branch deletes keys while iterating the same dict's .keys(),
    # which raises RuntimeError whenever the finished bucket is non-empty. This
    # test pins the *current* behavior; it must NOT be changed silently.
    a = _action([HloStatus.finished, HloStatus.estopped])
    gsm = GlobalStatusModel(orchestrator=ORCH)
    ep = EndpointModel(endpoint_name="ep", active_dict={a.action_uuid: a})
    asm = ActionServerModel(action_server=SRV, endpoints={"ep": ep})
    gsm.update_global_with_acts(asm)
    assert HloStatus.estopped not in gsm.nonactive_dict
    with pytest.raises(RuntimeError):
        gsm.clear_in_finished(HloStatus.estopped)


def test_clear_in_finished_substatus_path_noop_on_empty_finished():
    # When the finished bucket is empty, the buggy loop has nothing to iterate
    # so the substatus branch is exercised without raising.
    gsm = GlobalStatusModel(orchestrator=ORCH)
    gsm.nonactive_dict[HloStatus.finished] = {}
    gsm.clear_in_finished(HloStatus.estopped)
    assert gsm.nonactive_dict[HloStatus.finished] == {}


def test_experiment_lifecycle_counter_and_finish():
    exp_uuid = uuid4()
    a = _action([HloStatus.finished], exp_uuid=exp_uuid)
    gsm = _global_with_finished(a)
    gsm.new_experiment(exp_uuid)
    assert gsm.counter_dispatched_actions[exp_uuid] == 0
    finished = gsm.finish_experiment(exp_uuid)
    assert a.action_uuid in [act.action_uuid for act in finished]
    assert exp_uuid not in gsm.counter_dispatched_actions
    assert gsm.nonactive_dict == {}


def test_global_as_json_flattens_server_keys():
    a = _action([HloStatus.active])
    ep = EndpointModel(endpoint_name="ep", active_dict={a.action_uuid: a})
    asm = ActionServerModel(action_server=SRV, endpoints={"ep": ep})
    gsm = GlobalStatusModel(orchestrator=ORCH)
    gsm.update_global_with_acts(asm)
    j = gsm.as_json()
    assert any("@" in k for k in j["server_dict"].keys())
    assert j["loop_state"] is LoopStatus.stopped
    assert j["orch_state"] is OrchStatus.idle
    assert j["loop_intent"] is LoopIntent.none
