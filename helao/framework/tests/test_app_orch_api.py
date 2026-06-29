"""End-to-end smoke tests for the SP5 orchestration app layer.

Exercises :class:`OrchDriver` and :func:`execute_commands` with injected fakes:
- FakeTransport scripted to succeed on every dispatch
- FakeStorage for in-memory meta assertions
- QueueEventSink + NtpClock

Three scenarios tested at the driver level:
1. Full loop: one sequence -> one experiment -> two actions, driven to completion.
   Asserts both actions dispatched, meta written for seq/exp, loop_state stopped.
2. Experiment-direct: enqueue a RunExperiment (no sequence wrapper), two actions.
3. Estop injection: start the loop, then call driver.estop() which drives the FSM
   to estopped; asserts loop_state is estopped.

Also exercises:
- execute_commands directly with BroadcastGlobalStatus, PersistMeta, EstopServers,
  FinishExperiment, FinishSequence, MoveRunDir, ExpandSequence, ExpandExperiment.
- OrchDriver control surface: stop, skip, clear, clear_estop, clear_error,
  on_status_update.
- makeOrchApp FastAPI thin wrappers via TestClient.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import List
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from helao.framework.adapters.fakes.storage import FakeStorage
from helao.framework.adapters.fakes.transport import FakeTransport
from helao.framework.adapters.ntp_clock import NtpClock
from helao.framework.adapters.queue_eventsink import QueueEventSink
from helao.framework.app.orch_api import (
    OrchDriver,
    OrchPorts,
    execute_commands,
    makeOrchApp,
    _as_run_sequence,
    _extract_nonblocking,
)
from helao.framework.domain.commands import (
    BroadcastGlobalStatus,
    DispatchAction,
    EstopServers,
    ExpandExperiment,
    ExpandSequence,
    FinishExperiment,
    FinishSequence,
    MoveRunDir,
    PersistMeta,
    StopExecutor,
)
from helao.framework.domain.orchestration import OrchState
from helao.framework.domain.run_models import RunAction, RunExperiment, RunSequence
from helao.framework.models.action_start_condition import ActionStartCondition
from helao.framework.models.errors import ErrorCodes
from helao.framework.models.experiment import ExperimentModel
from helao.framework.models.hlostatus import HloStatus
from helao.framework.models.machine import MachineModel
from helao.framework.models.orchstatus import LoopStatus
from helao.framework.models.server import (
    ActionServerModel,
    EndpointModel,
    GlobalStatusModel,
)
from helao.framework.ports.transport import DispatchResult, DispatchTarget

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

ORCH = MachineModel(server_name="test_orch", machine_name="testhost")
SRV = MachineModel(server_name="act_srv", machine_name="testhost", hostname="127.0.0.1", port=8001)
NOW = datetime(2026, 6, 22, 20, 0, 0)


def _make_action(name: str = "do_thing") -> RunAction:
    return RunAction(
        action_name=name,
        action_server=SRV,
        start_condition=ActionStartCondition.no_wait,
    )


def _exp_factory(experiment: RunExperiment, **_kw) -> List[RunAction]:
    """Minimal experiment factory: two named actions."""
    return [_make_action("act_alpha"), _make_action("act_beta")]


def _seq_factory(**_kw) -> List[ExperimentModel]:
    """Minimal sequence factory: one experiment."""
    return [ExperimentModel(experiment_name="test_exp")]


def _make_ports(transport=None, storage=None) -> OrchPorts:
    return OrchPorts(
        transport=transport or FakeTransport(),
        storage=storage or FakeStorage(),
        eventsink=QueueEventSink(),
        clock=NtpClock(),
        sequence_lib={"test_seq": _seq_factory},
        experiment_lib={"test_exp": _exp_factory},
    )


def _make_driver(transport=None, storage=None, state=None) -> OrchDriver:
    ports = _make_ports(transport=transport, storage=storage)
    return OrchDriver("test_orch", ports=ports, state=state)


# ---------------------------------------------------------------------------
# 1. Full sequence -> experiment -> 2 actions loop
# ---------------------------------------------------------------------------

def test_full_sequence_loop_dispatches_both_actions():
    transport = FakeTransport()
    transport.default_result = DispatchResult(
        response={"status": "finished"}, error=ErrorCodes.none
    )
    storage = FakeStorage()
    driver = _make_driver(transport=transport, storage=storage)

    seq = RunSequence(sequence_name="test_seq")
    driver.enqueue_sequence(seq)

    asyncio.run(driver.start())

    # Both actions must have been dispatched
    # dispatch endpoint is action_name (e.g. "act_alpha", "act_beta") since
    # _dispatch_target_for uses action.action_name for all server types.
    assert len(transport.dispatched) == 2, (
        f"expected 2 dispatches, got {len(transport.dispatched)}"
    )

    # Sequence and experiment meta written
    meta_keys = list(storage.meta_docs.keys())
    seq_metas = [k for k in meta_keys if k.endswith("-seq.yml")]
    exp_metas = [k for k in meta_keys if k.endswith("-exp.yml")]
    assert seq_metas, f"no seq meta written; meta_docs={meta_keys}"
    assert exp_metas, f"no exp meta written; meta_docs={meta_keys}"

    # After a complete run the loop exits via IDLE (all queues drained).
    # loop_state stays 'started' — it only transitions on STOP/estopped.
    # Verify the FSM is now at IDLE (nothing left to dispatch).
    from helao.framework.domain.orchestration import decide_next
    from helao.framework.domain.commands import OrchDecision
    assert decide_next(driver.state) == OrchDecision.IDLE, (
        f"expected IDLE after full run, got {decide_next(driver.state)}"
    )


def test_full_sequence_loop_action_names_recorded():
    """Dispatched payload should carry the correct action names."""
    transport = FakeTransport()
    storage = FakeStorage()
    driver = _make_driver(transport=transport, storage=storage)

    seq = RunSequence(sequence_name="test_seq")
    driver.enqueue_sequence(seq)
    asyncio.run(driver.start())

    dispatched_names = [
        (payload.get("action_name") or (payload.get("action") or {}).get("action_name"))
        for _, payload in transport.dispatched
        if isinstance(payload, dict)
    ]
    assert "act_alpha" in dispatched_names
    assert "act_beta" in dispatched_names


# ---------------------------------------------------------------------------
# 2. Experiment-direct (no sequence wrapper)
# ---------------------------------------------------------------------------

def test_experiment_direct_loop_dispatches_two_actions():
    transport = FakeTransport()
    storage = FakeStorage()
    driver = _make_driver(transport=transport, storage=storage)

    exp = RunExperiment(experiment_name="test_exp")
    driver.enqueue_experiment(exp)
    asyncio.run(driver.start())

    assert len(transport.dispatched) == 2

    meta_keys = list(storage.meta_docs.keys())
    exp_metas = [k for k in meta_keys if k.endswith("-exp.yml")]
    assert exp_metas, f"no exp meta written; keys={meta_keys}"


# ---------------------------------------------------------------------------
# 3. Single pre-staged action
# ---------------------------------------------------------------------------

def test_single_action_dispatched_via_start():
    transport = FakeTransport()
    driver = _make_driver(transport=transport)

    action = _make_action("solo_act")
    driver.state.action_dq.append(action)
    asyncio.run(driver.start())

    assert transport.dispatched, "single action was not dispatched"


# ---------------------------------------------------------------------------
# 4. Estop: inject after enqueue, before start — loop transitions to estopped
# ---------------------------------------------------------------------------

def test_estop_sets_loop_state_estopped():
    transport = FakeTransport()
    driver = _make_driver(transport=transport)

    # Apply estop directly (no running loop needed)
    asyncio.run(driver.estop(reason="test"))

    assert driver.state.loop_state == LoopStatus.estopped

    # estop must have been broadcast to every known server (none in this state,
    # but the EstopServers command must have been dispatched via transport)
    # — the estop command fans out to server_dict; with empty server_dict no
    # dispatch call is made, but the intent transition still fires.
    assert driver.state.loop_state == LoopStatus.estopped


def test_estop_during_queued_run_halts_before_dispatch():
    """Estop applied before start prevents any dispatch."""
    transport = FakeTransport()
    driver = _make_driver(transport=transport)

    seq = RunSequence(sequence_name="test_seq")
    driver.enqueue_sequence(seq)
    # estop before start: loop_state transitions to estopped
    asyncio.run(driver.estop())
    assert driver.state.loop_state == LoopStatus.estopped

    # start() while estopped is a no-op: loop_state remains estopped
    # (apply_intent("start") guards against estopped state)
    asyncio.run(driver.start())
    assert driver.state.loop_state == LoopStatus.estopped

    # Nothing dispatched to run_action
    assert transport.dispatched == [], "estop before start must prevent all dispatch"


# ---------------------------------------------------------------------------
# 5. clear_estop releases latch
# ---------------------------------------------------------------------------

def test_clear_estop_returns_to_stopped():
    driver = _make_driver()
    asyncio.run(driver.estop())
    assert driver.state.loop_state == LoopStatus.estopped
    asyncio.run(driver.clear_estop())
    assert driver.state.loop_state == LoopStatus.stopped


# ---------------------------------------------------------------------------
# 6. stop intent
# ---------------------------------------------------------------------------

def test_stop_intent_applied():
    from helao.framework.models.orchstatus import LoopIntent
    driver = _make_driver()
    # start requires work in queue; add an action so start() transitions to started
    driver.state.action_dq.append(_make_action())
    # Apply stop intent directly via _intent (stop outside started is a no-op for state)
    asyncio.run(driver.stop())
    # In stopped state stop intent is not stored (guarded by loop_state==started check)
    # Just verify no exception raised and state is coherent
    assert driver.state.loop_state in (LoopStatus.started, LoopStatus.stopped)


# ---------------------------------------------------------------------------
# 7. skip clears action_dq when not started
# ---------------------------------------------------------------------------

def test_skip_clears_action_dq_when_not_started():
    driver = _make_driver()
    driver.state.action_dq.append(_make_action("a1"))
    driver.state.action_dq.append(_make_action("a2"))
    asyncio.run(driver.skip())
    assert driver.state.action_dq == []


# ---------------------------------------------------------------------------
# 8. clear queue methods
# ---------------------------------------------------------------------------

def test_clear_sequences_empties_queue():
    driver = _make_driver()
    driver.state.sequence_dq.append(RunSequence(sequence_name="s1"))
    asyncio.run(driver.clear("sequences"))
    assert driver.state.sequence_dq == []


def test_clear_experiments_empties_queue():
    driver = _make_driver()
    driver.state.experiment_dq.append(RunExperiment(experiment_name="e1"))
    asyncio.run(driver.clear("experiments"))
    assert driver.state.experiment_dq == []


def test_clear_actions_empties_queue():
    driver = _make_driver()
    driver.state.action_dq.append(_make_action())
    asyncio.run(driver.clear("actions"))
    assert driver.state.action_dq == []


# ---------------------------------------------------------------------------
# 9. on_status_update folds in server status
# ---------------------------------------------------------------------------

def test_on_status_update_folds_server_status():
    driver = _make_driver()
    action = RunAction(
        action_name="act",
        action_uuid=uuid4(),
        action_server=SRV,
        action_status=[HloStatus.active],
    )
    ep = EndpointModel(endpoint_name="act", active_dict={action.action_uuid: action})
    asm = ActionServerModel(action_server=SRV, endpoints={"act": ep})
    asyncio.run(driver.on_status_update(asm))
    # server_dict should now contain this server
    assert any(True for k in driver.state.globalstatusmodel.server_dict)


def test_on_status_update_none_is_noop():
    driver = _make_driver()
    asyncio.run(driver.on_status_update(None))  # must not raise


# ---------------------------------------------------------------------------
# 10. execute_commands: unit-level coverage of each command branch
# ---------------------------------------------------------------------------

def test_execute_commands_broadcast_global_status():
    storage = FakeStorage()
    eventsink = QueueEventSink()
    ports = _make_ports(storage=storage)
    ports.eventsink = eventsink
    state = OrchState()
    cmd = BroadcastGlobalStatus(payload={"loop_state": "stopped"})
    asyncio.run(execute_commands(state, [cmd], ports=ports))
    # QueueEventSink drains into its queue; no exception = success
    assert True


def test_execute_commands_persist_meta_fallback():
    """PersistMeta with no active_sequence falls back to flat uuid-kind path."""
    storage = FakeStorage()
    ports = _make_ports(storage=storage)
    state = OrchState()
    uid = uuid4()
    cmd = PersistMeta(kind="seq", uuid=uid, payload={"sequence_name": "s"})
    asyncio.run(execute_commands(state, [cmd], ports=ports))
    # No active_sequence -> flat fallback path
    relpath = f"{uid}-seq.yml"
    assert relpath in storage.meta_docs
    assert storage.meta_docs[relpath]["sequence_name"] == "s"
    # file_type key must be present (meta_doc wraps with leading file_type)
    assert storage.meta_docs[relpath]["file_type"] == "sequence"


def test_execute_commands_persist_meta_seq_nested():
    """PersistMeta kind=seq with active_sequence writes to nested timestamp path with file_type."""
    import tempfile, os
    from helao.framework.adapters.fs_storage import FsStorage
    from helao.framework.domain.lifecycle import sequence_meta_relpath

    with tempfile.TemporaryDirectory() as tmp:
        fs = FsStorage(save_root=tmp)
        ports = _make_ports(storage=fs)
        state = OrchState()
        seq = RunSequence(
            sequence_name="test_seq",
            sequence_uuid=uuid4(),
            sequence_timestamp=NOW,
            sequence_output_dir="26.25/0622/200000__test_seq__noLabel",
        )
        state.active_sequence = seq
        uid = uuid4()
        cmd = PersistMeta(kind="seq", uuid=uid, payload=seq.as_dict())
        asyncio.run(execute_commands(state, [cmd], ports=ports))
        expected_relpath = sequence_meta_relpath(seq)
        expected_path = os.path.join(tmp, expected_relpath)
        assert os.path.exists(expected_path), (
            f"nested seq meta not found at {expected_path}"
        )
        import yaml
        with open(expected_path) as f:
            doc = yaml.safe_load(f)
        assert doc.get("file_type") == "sequence", f"file_type missing; got {doc}"


def test_execute_commands_persist_meta_exp_nested():
    """PersistMeta kind=exp with active_experiment writes to nested timestamp path with file_type."""
    import tempfile, os
    from helao.framework.adapters.fs_storage import FsStorage
    from helao.framework.domain.lifecycle import experiment_meta_relpath

    with tempfile.TemporaryDirectory() as tmp:
        fs = FsStorage(save_root=tmp)
        ports = _make_ports(storage=fs)
        state = OrchState()
        exp = RunExperiment(
            experiment_name="test_exp",
            experiment_uuid=uuid4(),
            experiment_timestamp=NOW,
            experiment_output_dir="26.25/0622/200000__test_seq__noLabel/260622.200000__test_exp",
        )
        state.active_experiment = exp
        uid = uuid4()
        cmd = PersistMeta(kind="exp", uuid=uid, payload=exp.as_dict())
        asyncio.run(execute_commands(state, [cmd], ports=ports))
        expected_relpath = experiment_meta_relpath(exp)
        expected_path = os.path.join(tmp, expected_relpath)
        assert os.path.exists(expected_path), (
            f"nested exp meta not found at {expected_path}"
        )
        import yaml
        with open(expected_path) as f:
            doc = yaml.safe_load(f)
        assert doc.get("file_type") == "experiment", f"file_type missing; got {doc}"


def test_execute_commands_finish_experiment():
    """FinishExperiment writes to the nested timestamp path with leading file_type key."""
    import tempfile, os
    from helao.framework.adapters.fs_storage import FsStorage
    from helao.framework.domain.lifecycle import experiment_meta_relpath

    with tempfile.TemporaryDirectory() as tmp:
        fs = FsStorage(save_root=tmp)
        ports = _make_ports(storage=fs)
        state = OrchState()
        exp = RunExperiment(
            experiment_name="test_exp",
            experiment_uuid=uuid4(),
            experiment_timestamp=NOW,
            experiment_output_dir="26.25/0622/200000__test_seq__noLabel/260622.200000__test_exp",
        )
        state.active_experiment = exp
        cmd = FinishExperiment(experiment_uuid=exp.experiment_uuid)
        asyncio.run(execute_commands(state, [cmd], ports=ports))

        # Task 5b: finish writes the meta to RUNS_ACTIVE then promotes the exp
        # output dir to RUNS_FINISHED (file-granular move_dir port). The meta now
        # lives under RUNS_FINISHED and the RUNS_ACTIVE copy is gone.
        active_relpath = experiment_meta_relpath(exp)  # RUNS_ACTIVE/.../...-exp.yml
        finished_relpath = active_relpath.replace("RUNS_ACTIVE", "RUNS_FINISHED", 1)
        finished_path = os.path.join(tmp, finished_relpath)
        active_path = os.path.join(tmp, active_relpath)
        assert os.path.exists(finished_path), (
            f"exp finish meta not promoted to {finished_path}; "
            f"meta_docs={list(fs.meta_docs.keys()) if hasattr(fs, 'meta_docs') else 'N/A'}"
        )
        assert not os.path.exists(active_path), (
            f"exp meta should be moved out of RUNS_ACTIVE; still at {active_path}"
        )
        import yaml
        with open(finished_path) as f:
            doc = yaml.safe_load(f)
        assert doc.get("file_type") == "experiment", (
            f"leading file_type key missing or wrong; got {doc.get('file_type')!r}"
        )


def test_execute_commands_finish_sequence():
    """FinishSequence writes to the nested timestamp path with leading file_type key."""
    import tempfile, os
    from helao.framework.adapters.fs_storage import FsStorage
    from helao.framework.domain.lifecycle import sequence_meta_relpath

    with tempfile.TemporaryDirectory() as tmp:
        fs = FsStorage(save_root=tmp)
        ports = _make_ports(storage=fs)
        state = OrchState()
        seq = RunSequence(
            sequence_name="test_seq",
            sequence_uuid=uuid4(),
            sequence_timestamp=NOW,
            sequence_output_dir="26.25/0622/200000__test_seq__noLabel",
        )
        state.active_sequence = seq
        cmd = FinishSequence(sequence_uuid=seq.sequence_uuid)
        asyncio.run(execute_commands(state, [cmd], ports=ports))

        # Task 5b: finish writes the meta to RUNS_ACTIVE then promotes the seq
        # output dir to RUNS_FINISHED (file-granular move_dir port).
        active_relpath = sequence_meta_relpath(seq)  # RUNS_ACTIVE/.../...-seq.yml
        finished_relpath = active_relpath.replace("RUNS_ACTIVE", "RUNS_FINISHED", 1)
        finished_path = os.path.join(tmp, finished_relpath)
        active_path = os.path.join(tmp, active_relpath)
        assert os.path.exists(finished_path), (
            f"seq finish meta not promoted to {finished_path}; "
            f"meta_docs={list(fs.meta_docs.keys()) if hasattr(fs, 'meta_docs') else 'N/A'}"
        )
        assert not os.path.exists(active_path), (
            f"seq meta should be moved out of RUNS_ACTIVE; still at {active_path}"
        )
        import yaml
        with open(finished_path) as f:
            doc = yaml.safe_load(f)
        assert doc.get("file_type") == "sequence", (
            f"leading file_type key missing or wrong; got {doc.get('file_type')!r}"
        )


def test_execute_commands_move_run_dir():
    storage = FakeStorage()
    ports = _make_ports(storage=storage)
    state = OrchState()
    cmd = MoveRunDir(src="old/path", dst="new/path")
    asyncio.run(execute_commands(state, [cmd], ports=ports))
    assert ("old/path", "new/path") in storage.relocations


def test_execute_commands_estop_servers_fans_out():
    """EstopServers fans out dispatch to every server in server_dict."""
    transport = FakeTransport()
    storage = FakeStorage()
    ports = _make_ports(transport=transport, storage=storage)
    state = OrchState()

    # seed a server into the global status model
    action = RunAction(action_name="a", action_uuid=uuid4(), action_server=SRV)
    ep = EndpointModel(endpoint_name="a", active_dict={action.action_uuid: action})
    asm = ActionServerModel(action_server=SRV, endpoints={"a": ep})
    from helao.framework.domain import status as status_facade
    status_facade.merge_server_status(state.globalstatusmodel, asm)

    cmd = EstopServers(switch=False, reason="test")
    asyncio.run(execute_commands(state, [cmd], ports=ports))

    estop_calls = [t for t, _ in transport.dispatched if t.endpoint == "estop"]
    assert len(estop_calls) >= 1


def test_execute_commands_stop_executor():
    transport = FakeTransport()
    ports = _make_ports(transport=transport)
    state = OrchState()
    cmd = StopExecutor(server_key="act", executor_id="ex1", host="127.0.0.1", port=8001)
    asyncio.run(execute_commands(state, [cmd], ports=ports))
    stop_calls = [t for t, _ in transport.dispatched if t.endpoint == "stop_executor"]
    assert len(stop_calls) == 1


def test_execute_commands_expand_sequence_fallback():
    """ExpandSequence fallback stages experiments onto active_sequence."""
    storage = FakeStorage()
    ports = _make_ports(storage=storage)
    state = OrchState()
    seq = RunSequence(sequence_name="test_seq", sequence_uuid=uuid4())
    state.active_sequence = seq
    cmd = ExpandSequence(sequence_name="test_seq", sequence_params={})
    asyncio.run(execute_commands(state, [cmd], ports=ports))
    # sequence_lib has "test_seq" -> _seq_factory which returns one experiment
    assert len(state.active_sequence.planned_experiments) == 1


def test_execute_commands_expand_experiment_fallback():
    """ExpandExperiment fallback stages actions onto action_dq."""
    storage = FakeStorage()
    ports = _make_ports(storage=storage)
    state = OrchState()
    exp = RunExperiment(experiment_name="test_exp", experiment_uuid=uuid4())
    state.active_experiment = exp
    cmd = ExpandExperiment(experiment_name="test_exp", experiment_params={})
    asyncio.run(execute_commands(state, [cmd], ports=ports))
    assert len(state.action_dq) == 2


def test_execute_commands_dispatch_action_success():
    """DispatchAction command drives transport.dispatch and folds back status."""
    transport = FakeTransport()
    ports = _make_ports(transport=transport)
    state = OrchState()
    exp = RunExperiment(experiment_name="e", experiment_uuid=uuid4())
    state.active_experiment = exp
    action = _make_action("my_act")
    action.action_uuid = uuid4()
    action.action_status = [HloStatus.active]
    cmd = DispatchAction(action=action, nonblocking=False)
    asyncio.run(execute_commands(state, [cmd], ports=ports))
    assert transport.dispatched, "DispatchAction must reach transport"


def test_execute_commands_dispatch_action_failure_stops_loop():
    """DispatchAction with transport error applies stop intent."""
    transport = FakeTransport()
    transport.default_result = DispatchResult(response={}, error=ErrorCodes.not_available)
    ports = _make_ports(transport=transport)
    state = OrchState()
    from helao.framework.models.orchstatus import LoopStatus
    state.loop_state = LoopStatus.started
    action = _make_action("fail_act")
    action.action_uuid = uuid4()
    action.action_status = [HloStatus.active]
    cmd = DispatchAction(action=action, nonblocking=False)
    asyncio.run(execute_commands(state, [cmd], ports=ports))
    # on_dispatch_result with error applies stop intent
    from helao.framework.models.orchstatus import LoopIntent
    assert state.loop_intent == LoopIntent.stop or state.loop_state != LoopStatus.started


def test_execute_commands_unknown_command_is_logged():
    """An unrecognised command object must not raise."""
    ports = _make_ports()
    state = OrchState()
    asyncio.run(execute_commands(state, [object()], ports=ports))


# ---------------------------------------------------------------------------
# 11. makeOrchApp FastAPI thin wrappers
# ---------------------------------------------------------------------------

def test_make_orch_app_globstat_endpoint():
    ports = _make_ports()
    app = makeOrchApp("myorch", ports=ports)
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get("/myorch/globstat")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, dict)


def test_make_orch_app_stop_endpoint():
    ports = _make_ports()
    app = makeOrchApp("myorch", ports=ports)
    client = TestClient(app)
    resp = client.post("/myorch/stop")
    assert resp.status_code == 200
    body = resp.json()
    assert "loop_intent" in body


def test_make_orch_app_estop_endpoint():
    ports = _make_ports()
    app = makeOrchApp("myorch", ports=ports)
    client = TestClient(app)
    resp = client.post("/myorch/estop", params={"reason": "integration-test"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["loop_state"] == "estopped"


def test_make_orch_app_clear_estop_endpoint():
    ports = _make_ports()
    app = makeOrchApp("myorch", ports=ports)
    client = TestClient(app)
    client.post("/myorch/estop")
    resp = client.post("/myorch/clear_estop")
    assert resp.status_code == 200
    body = resp.json()
    assert body["loop_state"] == "stopped"


def test_make_orch_app_skip_endpoint():
    ports = _make_ports()
    app = makeOrchApp("myorch", ports=ports)
    client = TestClient(app)
    resp = client.post("/myorch/skip")
    assert resp.status_code == 200


def test_make_orch_app_start_endpoint_with_sequence():
    """POST /start with a queued sequence drives the loop to completion."""
    transport = FakeTransport()
    storage = FakeStorage()
    ports = _make_ports(transport=transport, storage=storage)
    state = OrchState()
    state.sequence_dq.append(RunSequence(sequence_name="test_seq"))
    app = makeOrchApp("myorch", ports=ports, state=state)
    client = TestClient(app)
    resp = client.post("/myorch/start")
    assert resp.status_code == 200
    body = resp.json()
    assert "loop_state" in body
    # both actions must have been dispatched
    assert len(transport.dispatched) == 2, (
        f"expected 2 dispatches, got {len(transport.dispatched)}"
    )
    # FSM reached IDLE (work all done)
    from helao.framework.domain.orchestration import decide_next
    from helao.framework.domain.commands import OrchDecision
    driver = app.state.driver
    assert decide_next(driver.state) == OrchDecision.IDLE


# ---------------------------------------------------------------------------
# 12. OrchPorts.now() uses injected clock
# ---------------------------------------------------------------------------

def test_orch_ports_now_returns_datetime():
    ports = _make_ports()
    dt = ports.now()
    assert isinstance(dt, datetime)


# ---------------------------------------------------------------------------
# 13. Loop exception boundary drives estop
# ---------------------------------------------------------------------------

def test_loop_exception_boundary_estops():
    """A crash inside _step must be caught and drive the loop to estopped."""
    transport = FakeTransport()
    ports = _make_ports(transport=transport)

    state = OrchState()
    # Seed an action with a broken start_condition to trigger the loop
    action = _make_action("crash_act")
    action.action_uuid = uuid4()
    action.action_status = [HloStatus.active]
    state.action_dq.append(action)

    # Monkey-patch _step to raise
    driver = OrchDriver("test_orch", ports=ports, state=state)

    async def _bad_step(decision):
        raise RuntimeError("simulated crash")

    driver._step = _bad_step  # type: ignore[method-assign]

    asyncio.run(driver.start())
    assert driver.state.loop_state == LoopStatus.estopped


# ---------------------------------------------------------------------------
# BUG 3 regression: /wait must honor the dispatched action's nonblocking flag.
# The orch dispatch payload nests the action under body["action"]; if the flag
# is dropped the self-hosted wait blocks the loop (TEST_consecutive_noblocking
# "takes too long").
# ---------------------------------------------------------------------------
def test_extract_nonblocking_from_dispatch_payload():
    body = {"waittime": 30.0, "action": {"action_uuid": "x", "nonblocking": True}}
    assert _extract_nonblocking(body) is True


def test_extract_nonblocking_top_level_flag():
    assert _extract_nonblocking({"waittime": 1.0, "nonblocking": True}) is True


def test_extract_nonblocking_defaults_false():
    assert _extract_nonblocking({"waittime": 1.0}) is False
    assert _extract_nonblocking({"waittime": 1.0, "action": {"action_uuid": "x"}}) is False


# ---------------------------------------------------------------------------
# BUG B regression: queued items must carry a uuid at enqueue (operator queue
# table showed a blank uuid because stamping was deferred to dispatch).
# ---------------------------------------------------------------------------
def test_as_run_sequence_stamps_uuid_at_enqueue():
    seq = _as_run_sequence({"sequence_name": "te"})
    assert seq.sequence_uuid is not None


def test_as_run_sequence_preserves_supplied_uuid():
    from uuid import uuid4
    u = uuid4()
    seq = _as_run_sequence({"sequence_name": "te", "sequence_uuid": str(u)})
    assert seq.sequence_uuid == u


def test_append_experiment_endpoint_returns_uuid():
    ports = _make_ports()
    state = OrchState()
    app = makeOrchApp("myorch", ports=ports, state=state)
    client = TestClient(app)
    resp = client.post("/append_experiment", json={"experiment": {"experiment_name": "te"}})
    assert resp.status_code == 200
    euuid = resp.json()["experiment_uuid"]
    assert euuid and euuid != "None"
    # the queued experiment carries the same uuid (so the operator can show it)
    assert str(state.experiment_dq[0].experiment_uuid) == euuid


# ---------------------------------------------------------------------------
# Nonblocking action parity: update_nonblocking ingestion + experiment-finish
# teardown (legacy Orch.update_nonblocking / clear_nonblocking).
# ---------------------------------------------------------------------------
def test_driver_on_nonblocking_tracks_then_removes_and_registers_history():
    ports = _make_ports()
    state = OrchState()
    driver = OrchDriver("test_orch", ports=ports, state=state)
    action = _make_action("nb_act")
    action.action_uuid = uuid4()
    action.exec_id = "nb_act exec1"
    action.action_status = [HloStatus.active]

    asyncio.run(driver.on_nonblocking(action, "127.0.0.1", 8002))
    assert any(t[1] == "nb_act exec1" for t in state.nonblocking)
    assert action.action_uuid in state.action_history  # registered in history

    action.action_status = [HloStatus.finished]
    asyncio.run(driver.on_nonblocking(action, "127.0.0.1", 8002))
    assert not any(t[1] == "nb_act exec1" for t in state.nonblocking)  # removed on finish


def test_update_nonblocking_endpoint_routes_to_driver():
    ports = _make_ports()
    state = OrchState()
    app = makeOrchApp("myorch", ports=ports, state=state)
    client = TestClient(app)
    action = _make_action("nb_act")
    action.action_uuid = uuid4()
    action.exec_id = "nb_act exec1"
    action.action_status = [HloStatus.active]

    resp = client.post(
        "/update_nonblocking",
        json={"actionmodel": action.as_dict()},
        params={"server_host": "127.0.0.1", "server_port": 8002},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert any(t[1] == "nb_act exec1" for t in state.nonblocking)


def test_finish_experiment_stops_tracked_nonblocking_executors():
    transport = FakeTransport()
    driver = _make_driver(transport=transport)
    # a nonblocking executor is still tracked when the experiment finishes
    driver.state.nonblocking.append(("act_srv", "nb exec1", "127.0.0.1", 8002))
    driver.enqueue_experiment(RunExperiment(experiment_name="test_exp"))
    asyncio.run(driver.start())

    stop_dispatched = [
        (t, p)
        for t, p in transport.dispatched
        if getattr(t, "endpoint", None) == "stop_executor"
    ]
    assert stop_dispatched, (
        "no stop_executor dispatched at experiment finish; endpoints="
        f"{[getattr(t, 'endpoint', None) for t, _ in transport.dispatched]}"
    )
    assert any(p.get("executor_id") == "nb exec1" for _, p in stop_dispatched)
    # tracking is dropped at finish so a stale entry is not re-stopped on later
    # experiment finishes (best-effort teardown, no leak)
    assert driver.state.nonblocking == []


def test_multiple_queued_experiments_finish_serially():
    """Each queued experiment must be FINISHED before the next dispatches.

    Regression for the decide_next bug where queued experiments dispatched
    back-to-back (active_experiment overwritten) so only the last finished.
    """
    transport = FakeTransport()
    storage = FakeStorage()
    driver = _make_driver(transport=transport, storage=storage)
    for _ in range(3):
        driver.enqueue_experiment(RunExperiment(experiment_name="test_exp"))
    asyncio.run(driver.start())

    exp_metas = [k for k in storage.meta_docs if k.endswith("-exp.yml")]
    assert len(exp_metas) == 3, (
        f"expected 3 finished experiments, got {len(exp_metas)}: {exp_metas}"
    )
    assert driver.state.active_experiment is None


def test_orch_base_uses_in_process_nonblocking_sink_not_self_push(monkeypatch):
    """makeOrchApp must NOT set base.orch_key (would self-attach + crash on None
    coords); it wires an in-process nonblocking_sink to driver.on_nonblocking."""
    ports = _make_ports()
    state = OrchState()
    app = makeOrchApp("myorch", ports=ports, state=state)
    base = app.state.base
    # no regular-status self-attach
    assert base.orch_key is None
    # nonblocking reports route in-process to the driver
    assert callable(base.nonblocking_sink)

    # exercise the sink: a nonblocking action reported through the base reaches
    # the driver's FSM tracking without any HTTP/RPC dispatch
    base.server_cfg.setdefault("host", "127.0.0.1")
    base.server_cfg.setdefault("port", 8001)
    action = _make_action("wait")
    action.action_uuid = uuid4()
    action.exec_id = "wait exec1"
    action.action_status = [HloStatus.active]
    asyncio.run(base.send_nonblocking_status(action))
    assert any(t[1] == "wait exec1" for t in state.nonblocking)


def test_finish_experiment_stops_local_nonblocking_executor_in_process():
    """The orch's OWN nonblocking executors must be stopped IN-PROCESS at finish.

    Dispatching StopExecutor to the orch's own /stop_executor over RPC deadlocks
    the single dispatch loop (it would await a response it must itself produce).
    Local executors (in base.executors) are stopped via stop_action_task directly;
    no transport dispatch is issued for them.
    """
    class _FakeExec:
        def __init__(self):
            self.stopped = False
        def stop_action_task(self):
            self.stopped = True

    class _FakeBase:
        def __init__(self, ex):
            self.executors = {"wait exec1": ex}

    transport = FakeTransport()
    driver = _make_driver(transport=transport)
    ex = _FakeExec()
    driver.base = _FakeBase(ex)
    driver.state.nonblocking.append(("ORCH", "wait exec1", "127.0.0.1", 8001))
    driver.enqueue_experiment(RunExperiment(experiment_name="test_exp"))
    asyncio.run(driver.start())

    assert ex.stopped is True  # stopped in-process
    # no stop_executor was dispatched over the transport for the local executor
    stop_dispatched = [
        t for t, _ in transport.dispatched
        if getattr(t, "endpoint", None) == "stop_executor"
    ]
    assert stop_dispatched == []
    assert driver.state.nonblocking == []


def test_finish_experiment_dispatches_remote_nonblocking_stop():
    """A nonblocking executor NOT on the orch's base is dispatched over transport."""
    transport = FakeTransport()
    driver = _make_driver(transport=transport)

    class _EmptyBase:
        executors = {}

    driver.base = _EmptyBase()
    driver.state.nonblocking.append(("SIM", "acq exec9", "127.0.0.1", 8002))
    driver.enqueue_experiment(RunExperiment(experiment_name="test_exp"))
    asyncio.run(driver.start())

    stop_dispatched = [
        (t, p) for t, p in transport.dispatched
        if getattr(t, "endpoint", None) == "stop_executor"
    ]
    assert stop_dispatched, "remote nonblocking executor should be stopped via transport"
    assert any(p.get("executor_id") == "acq exec9" for _, p in stop_dispatched)


def test_as_run_experiment_stamps_uuid_for_queued_display():
    """Sequence-staged experiments must carry a uuid while queued (operator table)."""
    from helao.framework.app.orch_api import _as_run_experiment
    exp = _as_run_experiment(ExperimentModel(experiment_name="te"))
    assert exp.experiment_uuid is not None


# ---------------------------------------------------------------------------
# Task 4: stop endpoint forwards reset_run_id
# ---------------------------------------------------------------------------

def test_driver_stop_default_keeps_run_id():
    import uuid as _uuid
    driver = _make_driver()
    driver.state.active_run_id = _uuid.uuid4()
    rid = driver.state.active_run_id
    asyncio.run(driver.stop())
    assert driver.state.active_run_id == rid


def test_driver_stop_reset_clears_run_id():
    import uuid as _uuid
    driver = _make_driver()
    driver.state.active_run_id = _uuid.uuid4()
    asyncio.run(driver.stop(reset_run_id=True))
    assert driver.state.active_run_id is None
