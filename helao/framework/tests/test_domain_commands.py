"""Tests for the domain command/result value objects ``helao.framework.domain.commands``.

These are frozen dataclasses / an enum returned by the pure domain functions.
The tests assert immutability, defaults, and construction (which is what gives
the module its coverage independent of the FSM tests).
"""
import dataclasses
from uuid import uuid4

import pytest

from helao.framework.domain.run_models import RunAction
from helao.framework.domain.commands import (
    ActionInit,
    BroadcastGlobalStatus,
    DispatchAction,
    EstopServers,
    ExpandExperiment,
    ExpandSequence,
    FinishExperiment,
    FinishSequence,
    MoveRunDir,
    OrchDecision,
    PersistMeta,
    SplitResult,
    StopExecutor,
)


def test_orch_decision_members():
    assert OrchDecision.DISPATCH_ACTION.value == "dispatch_action"
    assert {d.value for d in OrchDecision} == {
        "dispatch_action", "dispatch_experiment", "dispatch_sequence",
        "finish_experiment", "finish_sequence", "wait", "stop", "idle",
    }


def test_dispatch_action_defaults_and_frozen():
    a = RunAction(action_uuid=uuid4())
    cmd = DispatchAction(action=a)
    assert cmd.action is a
    assert cmd.nonblocking is False
    with pytest.raises(dataclasses.FrozenInstanceError):
        cmd.nonblocking = True


def test_expand_sequence_and_experiment_defaults():
    es = ExpandSequence(sequence_name="s")
    assert es.sequence_params == {}
    ee = ExpandExperiment(experiment_name="e", experiment_params={"k": 1})
    assert ee.experiment_params == {"k": 1}


def test_persist_meta():
    u = uuid4()
    pm = PersistMeta(kind="exp", uuid=u, payload={"a": 1})
    assert pm.kind == "exp" and pm.uuid == u and pm.payload == {"a": 1}
    assert PersistMeta(kind="seq", uuid=None).payload == {}


def test_estop_servers_defaults():
    e = EstopServers()
    assert e.switch is False and e.reason == ""
    e2 = EstopServers(switch=True, reason="why")
    assert e2.switch is True and e2.reason == "why"


def test_stop_executor():
    se = StopExecutor(server_key="act", executor_id="e1", host="h", port=9)
    assert (se.server_key, se.executor_id, se.host, se.port) == ("act", "e1", "h", 9)
    assert StopExecutor(server_key="x", executor_id=None).host is None


def test_broadcast_global_status_default():
    assert BroadcastGlobalStatus().payload == {}
    assert BroadcastGlobalStatus(payload={"x": 1}).payload == {"x": 1}


def test_finish_and_move_commands():
    u = uuid4()
    assert FinishExperiment(experiment_uuid=u).experiment_uuid == u
    assert FinishSequence(sequence_uuid=u).sequence_uuid == u
    assert FinishExperiment().experiment_uuid is None
    mv = MoveRunDir(src="a", dst="b")
    assert mv.src == "a" and mv.dst == "b"


def test_action_init_and_split_result_still_present():
    a = RunAction(action_uuid=uuid4())
    init = ActionInit(action=a)
    assert init.manual is False
    sr = SplitResult(new_action=a, prev_action=a)
    assert sr.open_file_conns == [] and sr.close_file_conns == []
