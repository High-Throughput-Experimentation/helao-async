"""Smoke tests for :mod:`helao.framework.runners.micro_orch`.

Exercises :class:`MicroOrch` and the module-level convenience entry points
(:func:`run_sequence`, :func:`run_experiment`, :func:`run_action`) in-process,
using the same :class:`FakeTransport` and library maps as the orch_api smoke
tests. No HTTP server, no asyncio.run nesting — the synchronous entry points
handle the event loop.

Scenarios:
1. run_sequence: one sequence -> one experiment -> two actions dispatched.
2. run_experiment: direct experiment -> two actions.
3. run_action: single pre-built action dispatched.
4. MicroOrch.run_sequence async: same outcome through the async method.
5. MicroOrch.run_experiment async: direct experiment.
6. MicroOrch.run_action async: single action.
7. Custom transport injected into MicroOrch.
8. save_root plumbing: FsStorage receives meta writes under tmp_path.
9. Estop propagation via injected transport that fails.
10. sequence_lib / experiment_lib missing name -> graceful empty expansion.
"""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import List

from helao.framework.adapters.fakes.transport import FakeTransport
from helao.framework.adapters.fs_storage import FsStorage
from helao.framework.domain.run_models import RunAction, RunExperiment, RunSequence
from helao.framework.models.action_start_condition import ActionStartCondition
from helao.framework.models.errors import ErrorCodes
from helao.framework.models.experiment import ExperimentModel
from helao.framework.models.machine import MachineModel
from helao.framework.models.orchstatus import LoopStatus
from helao.framework.ports.transport import DispatchResult
from helao.framework.runners.micro_orch import (
    MicroOrch,
    run_action,
    run_experiment,
    run_sequence,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

SRV = MachineModel(
    server_name="act_srv", machine_name="testhost", hostname="127.0.0.1", port=8001
)


def _make_action(name: str = "do_thing") -> RunAction:
    return RunAction(
        action_name=name,
        action_server=SRV,
        start_condition=ActionStartCondition.no_wait,
    )


def _exp_factory(experiment: RunExperiment, **_kw) -> List[RunAction]:
    return [_make_action("act_one"), _make_action("act_two")]


def _seq_factory(**_kw) -> List[ExperimentModel]:
    return [ExperimentModel(experiment_name="micro_exp")]


SEQ_LIB = {"micro_seq": _seq_factory}
EXP_LIB = {"micro_exp": _exp_factory}


# ---------------------------------------------------------------------------
# 1. run_sequence convenience entry point
# ---------------------------------------------------------------------------

def test_run_sequence_dispatches_both_actions():
    transport = FakeTransport()
    seq = RunSequence(sequence_name="micro_seq")
    state = run_sequence(
        seq,
        sequence_lib=SEQ_LIB,
        experiment_lib=EXP_LIB,
        transport=transport,
    )
    run_calls = list(transport.dispatched)
    assert len(run_calls) == 2, f"expected 2 dispatches, got {len(run_calls)}"
    # After a complete run the loop exits via IDLE; loop_state stays 'started'
    # (only transitions on explicit stop/estop). Assert FSM is at IDLE instead.
    from helao.framework.domain.orchestration import decide_next
    from helao.framework.domain.commands import OrchDecision
    assert decide_next(state) == OrchDecision.IDLE


def test_run_sequence_action_names_in_dispatched_payloads():
    transport = FakeTransport()
    seq = RunSequence(sequence_name="micro_seq")
    run_sequence(seq, sequence_lib=SEQ_LIB, experiment_lib=EXP_LIB, transport=transport)
    names = [
        (p.get("action_name") or (p.get("action") or {}).get("action_name"))
        for _, p in transport.dispatched
        if isinstance(p, dict)
    ]
    assert "act_one" in names
    assert "act_two" in names


# ---------------------------------------------------------------------------
# 2. run_experiment convenience entry point
# ---------------------------------------------------------------------------

def test_run_experiment_dispatches_two_actions():
    transport = FakeTransport()
    exp = RunExperiment(experiment_name="micro_exp")
    state = run_experiment(exp, experiment_lib=EXP_LIB, transport=transport)
    run_calls = list(transport.dispatched)
    assert len(run_calls) == 2


def test_run_experiment_returns_final_state():
    transport = FakeTransport()
    exp = RunExperiment(experiment_name="micro_exp")
    state = run_experiment(exp, experiment_lib=EXP_LIB, transport=transport)
    # loop exits via IDLE after dispatching all actions; loop_state stays started
    from helao.framework.domain.orchestration import decide_next
    from helao.framework.domain.commands import OrchDecision
    assert decide_next(state) == OrchDecision.IDLE


# ---------------------------------------------------------------------------
# 3. run_action convenience entry point
# ---------------------------------------------------------------------------

def test_run_action_dispatches_single_action():
    transport = FakeTransport()
    action = _make_action("solo")
    state = run_action(action, transport=transport)
    run_calls = list(transport.dispatched)
    assert len(run_calls) == 1


def test_run_action_returns_state():
    transport = FakeTransport()
    action = _make_action("solo")
    state = run_action(action, transport=transport)
    assert state is not None


# ---------------------------------------------------------------------------
# 4. MicroOrch async: run_sequence
# ---------------------------------------------------------------------------

def test_micro_orch_async_run_sequence():
    transport = FakeTransport()
    micro = MicroOrch(sequence_lib=SEQ_LIB, experiment_lib=EXP_LIB, transport=transport)
    seq = RunSequence(sequence_name="micro_seq")
    state = asyncio.run(micro.run_sequence(seq))
    run_calls = list(transport.dispatched)
    assert len(run_calls) == 2
    from helao.framework.domain.orchestration import decide_next
    from helao.framework.domain.commands import OrchDecision
    assert decide_next(state) == OrchDecision.IDLE


# ---------------------------------------------------------------------------
# 5. MicroOrch async: run_experiment
# ---------------------------------------------------------------------------

def test_micro_orch_async_run_experiment():
    transport = FakeTransport()
    micro = MicroOrch(experiment_lib=EXP_LIB, transport=transport)
    exp = RunExperiment(experiment_name="micro_exp")
    state = asyncio.run(micro.run_experiment(exp))
    run_calls = list(transport.dispatched)
    assert len(run_calls) == 2


# ---------------------------------------------------------------------------
# 6. MicroOrch async: run_action
# ---------------------------------------------------------------------------

def test_micro_orch_async_run_action():
    transport = FakeTransport()
    micro = MicroOrch(transport=transport)
    action = _make_action("async_solo")
    state = asyncio.run(micro.run_action(action))
    run_calls = list(transport.dispatched)
    assert len(run_calls) == 1


# ---------------------------------------------------------------------------
# 7. MicroOrch exposes driver and state properties
# ---------------------------------------------------------------------------

def test_micro_orch_state_property():
    micro = MicroOrch()
    assert micro.state is micro.driver.state


def test_micro_orch_ports_property():
    micro = MicroOrch()
    assert micro.ports is micro.driver.ports


# ---------------------------------------------------------------------------
# 8. save_root plumbing: meta files written to disk via FsStorage
# ---------------------------------------------------------------------------

def test_run_sequence_writes_meta_to_disk(tmp_path):
    transport = FakeTransport()
    seq = RunSequence(sequence_name="micro_seq")
    run_sequence(
        seq,
        sequence_lib=SEQ_LIB,
        experiment_lib=EXP_LIB,
        transport=transport,
        save_root=str(tmp_path),
    )
    meta_files = list(tmp_path.rglob("*.yml"))
    assert meta_files, f"no .yml meta files written under {tmp_path}"


def test_run_experiment_writes_exp_meta_to_disk(tmp_path):
    transport = FakeTransport()
    exp = RunExperiment(experiment_name="micro_exp")
    run_experiment(
        exp,
        experiment_lib=EXP_LIB,
        transport=transport,
        save_root=str(tmp_path),
    )
    meta_files = list(tmp_path.rglob("*.yml"))
    assert meta_files, f"no .yml meta files written under {tmp_path}"


# ---------------------------------------------------------------------------
# 9. Default temp dir: MicroOrch creates a temp dir when save_root=None
# ---------------------------------------------------------------------------

def test_micro_orch_default_temp_dir():
    """MicroOrch with no save_root must not raise and must run to completion."""
    transport = FakeTransport()
    micro = MicroOrch(transport=transport)
    action = _make_action("temp_dir_act")
    state = asyncio.run(micro.run_action(action))
    run_calls = list(transport.dispatched)
    assert len(run_calls) == 1


# ---------------------------------------------------------------------------
# 10. Missing sequence/experiment name -> graceful empty expansion (no crash)
# ---------------------------------------------------------------------------

def test_run_sequence_unknown_name_completes_without_dispatch():
    """An unknown sequence name returns empty experiment list; loop idles cleanly."""
    transport = FakeTransport()
    seq = RunSequence(sequence_name="no_such_sequence")
    state = run_sequence(
        seq,
        sequence_lib=SEQ_LIB,
        experiment_lib=EXP_LIB,
        transport=transport,
    )
    run_calls = list(transport.dispatched)
    assert run_calls == []
    from helao.framework.domain.orchestration import decide_next
    from helao.framework.domain.commands import OrchDecision
    assert decide_next(state) == OrchDecision.IDLE


def test_run_experiment_unknown_name_no_actions():
    """An unknown experiment name stages zero actions; loop idles cleanly."""
    transport = FakeTransport()
    exp = RunExperiment(experiment_name="no_such_exp")
    state = run_experiment(
        exp,
        experiment_lib=EXP_LIB,
        transport=transport,
    )
    run_calls = list(transport.dispatched)
    assert run_calls == []


# ---------------------------------------------------------------------------
# 11. Multiple sequences queued
# ---------------------------------------------------------------------------

def test_two_sequences_dispatched_in_order():
    transport = FakeTransport()
    micro = MicroOrch(sequence_lib=SEQ_LIB, experiment_lib=EXP_LIB, transport=transport)
    micro.driver.enqueue_sequence(RunSequence(sequence_name="micro_seq"))
    micro.driver.enqueue_sequence(RunSequence(sequence_name="micro_seq"))
    state = asyncio.run(micro.driver.start())
    run_calls = list(transport.dispatched)
    # 2 sequences x 1 experiment x 2 actions = 4 dispatches
    assert len(run_calls) == 4


# ---------------------------------------------------------------------------
# 12. Scripted transport failure causes stop intent (no estop, graceful stop)
# ---------------------------------------------------------------------------

def test_transport_failure_applies_stop_intent():
    """A failing dispatch must apply stop intent, not crash."""
    from helao.framework.models.orchstatus import LoopIntent
    transport = FakeTransport()
    transport.default_result = DispatchResult(
        response={}, error=ErrorCodes.not_available
    )
    exp = RunExperiment(experiment_name="micro_exp")
    state = run_experiment(exp, experiment_lib=EXP_LIB, transport=transport)
    # on_dispatch_result with error -> apply_intent("stop") -> LoopIntent.stop
    # loop_state stays 'started' (intent != state); the loop then breaks because
    # decide_next returns STOP (due to loop_intent==stop)
    assert state.loop_intent == LoopIntent.stop or state.loop_state in (
        LoopStatus.stopped, LoopStatus.estopped
    )
