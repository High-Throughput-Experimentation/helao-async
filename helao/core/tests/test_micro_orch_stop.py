"""MicroOrch cooperative stop (spec: Launcher step 6)."""

import asyncio
import json
import shutil
import tempfile
from copy import deepcopy

import pytest
import pytest_asyncio

from helao.core.models.machine import MachineModel
from helao.core.models.action_start_condition import ActionStartCondition
from helao.core.models.hlostatus import HloStatus
from helao.core.rpc import derive_rpc_port
from helao.core.runners.micro_orch import RunnerStopped
from helao.core.tests.unit_test_micro_orch import (
    _FakeDataActionServer,
    _free_port,
    _make_orch,
)
from helao.helpers.premodels import (
    Action,
    ActionPlanMaker,
    Experiment,
    ExperimentPlanMaker,
)


@pytest_asyncio.fixture
async def rig():
    root = tempfile.mkdtemp(prefix="micro_stop_")
    port = _free_port()
    fake = _FakeDataActionServer("FAKE", "ping", root)
    await fake.dispatcher.serve("127.0.0.1", derive_rpc_port(port))
    orch = _make_orch(root, {"FAKE": {"host": "127.0.0.1", "port": port}})
    orch.group_urls = []
    await orch.start()
    try:
        yield orch, fake
    finally:
        await orch.stop()
        await fake.dispatcher.close()
        shutil.rmtree(root, ignore_errors=True)


def _three_pings(experiment):
    apm = ActionPlanMaker()
    for _ in range(3):
        apm.add("FAKE", "ping", {})
    return apm.planned_actions


@pytest.mark.asyncio
async def test_request_stop_before_dispatch_raises_and_dispatches_nothing(rig):
    orch, fake = rig
    orch.request_stop()
    act = Action(action_name="ping", action_server=MachineModel(server_name="FAKE"))
    with pytest.raises(RunnerStopped):
        await orch.run_action(act)
    assert fake.action_calls == []


@pytest.mark.asyncio
async def test_request_stop_mid_experiment_finishes_record_aborted(rig, monkeypatch):
    orch, fake = rig
    real = orch.dispatch_action
    calls = {"n": 0}

    async def stop_after_first(action, *a, **k):
        if calls["n"] == 1:
            orch.request_stop()
        calls["n"] += 1
        return await real(action, *a, **k)

    monkeypatch.setattr(orch, "dispatch_action", stop_after_first)
    with pytest.raises(RunnerStopped):
        await orch.run_experiment(
            _three_pings, experiment=Experiment(experiment_name="e")
        )
    assert len(fake.action_calls) == 1
    exp = orch.last_experiment
    assert "aborted" in [str(getattr(s, "value", s)) for s in exp.experiment_status]
    assert any(r["type"] == "experiment" for r in orch.runs)


class _ActiveServer(_FakeDataActionServer):
    """``ping`` replies ``active``; the test finishes it later, like update_status."""

    async def _run_action(self, action: dict = None, **kwargs):
        action_dict = action or {}
        self.action_calls.append(deepcopy(action_dict))
        action_dict["action_status"] = ["active"]
        return action_dict


@pytest_asyncio.fixture
async def active_rig():
    root = tempfile.mkdtemp(prefix="micro_stop_")
    port = _free_port()
    fake = _ActiveServer("FAKE", "ping", root)
    await fake.dispatcher.serve("127.0.0.1", derive_rpc_port(port))
    orch = _make_orch(root, {"FAKE": {"host": "127.0.0.1", "port": port}})
    orch.group_urls = []
    await orch.start()
    try:
        yield orch, fake
    finally:
        await orch.stop()
        await fake.dispatcher.close()
        shutil.rmtree(root, ignore_errors=True)


async def _stop_while_first_active_then_finish(orch, fake, task):
    """Stop during the first action, assert the run waits, then finish the action."""
    for _ in range(200):
        if fake.action_calls:
            break
        await asyncio.sleep(0.01)
    assert len(fake.action_calls) == 1
    orch.request_stop()
    await asyncio.sleep(0.2)
    assert not task.done(), "stopped run must wait for the active action"
    dump = deepcopy(fake.action_calls[0])
    dump["action_status"] = [HloStatus.finished.value]
    uuid = orch.pending_uuids()[0]
    async with orch._cond:
        orch._latest[uuid] = dump
        orch._retire_locked(uuid, dump)
        orch._cond.notify_all()
    with pytest.raises(RunnerStopped):
        await asyncio.wait_for(task, 10)


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _two_no_wait(experiment):
    apm = ActionPlanMaker()
    for _ in range(2):
        apm.add("FAKE", "ping", {}, start_condition=ActionStartCondition.no_wait)
    return apm.planned_actions


@pytest.mark.asyncio
async def test_stop_waits_for_active_action_before_writing_aborted_record(
    active_rig, monkeypatch
):
    orch, fake = active_rig
    real = orch.dispatch_action
    calls = {"n": 0}

    async def stop_after_first(action, *a, **k):
        if calls["n"] == 1:
            orch.request_stop()
        calls["n"] += 1
        return await real(action, *a, **k)

    monkeypatch.setattr(orch, "dispatch_action", stop_after_first)
    task = asyncio.create_task(
        orch.run_experiment(_two_no_wait, experiment=Experiment(experiment_name="e"))
    )
    for _ in range(200):
        if calls["n"] == 2:
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.2)
    # action 2's dispatch raised; only the stop branch can still be waiting
    assert len(fake.action_calls) == 1
    assert not task.done(), "stop branch must wait for the active action"
    dump = deepcopy(fake.action_calls[0])
    dump["action_status"] = [HloStatus.finished.value]
    uuid = orch.pending_uuids()[0]
    async with orch._cond:
        orch._latest[uuid] = dump
        orch._retire_locked(uuid, dump)
        orch._cond.notify_all()
    with pytest.raises(RunnerStopped):
        await asyncio.wait_for(task, 10)
    rec = _load(orch.runs[-1]["yml_path"])
    assert "aborted" in [str(s) for s in rec["experiment_status"]]
    assert len(orch.last_experiment.dispatched_actions) == 1
    assert len(rec["dispatched_actions_abbr"]) == 1
    done = orch.last_experiment.dispatched_actions[0]
    assert "finished" in [str(getattr(s, "value", s)) for s in done.action_status]


@pytest.mark.asyncio
async def test_stop_during_sequence_aborts_sequence_and_keeps_the_experiment(
    active_rig,
):
    orch, fake = active_rig

    def seq():
        epm = ExperimentPlanMaker()
        epm.add("demo", {})
        epm.add("demo", {})
        return epm.planned_experiments

    task = asyncio.create_task(orch.run_sequence(seq, {"demo": _three_pings}))
    await _stop_while_first_active_then_finish(orch, fake, task)
    assert len(fake.action_calls) == 1
    assert len(orch.finished_experiments) == 1  # the second never started
    rec = _load(orch.runs[-1]["yml_path"])
    assert orch.runs[-1]["type"] == "sequence"
    assert "aborted" in [str(s) for s in rec["sequence_status"]]
    uuids = [str(e["experiment_uuid"]) for e in rec["dispatched_experiments_abbr"]]
    assert uuids == [str(orch.last_experiment.experiment_uuid)]


@pytest.mark.asyncio
async def test_run_experiment_after_stop_writes_nothing(rig):
    orch, fake = rig
    orch.request_stop()
    with pytest.raises(RunnerStopped):
        await orch.run_experiment(_three_pings, experiment=Experiment())
    assert orch.runs == []
    assert fake.action_calls == []


@pytest.mark.asyncio
async def test_stop_between_experiments_does_not_duplicate_the_finished_one(rig):
    orch, fake = rig
    real = orch._finish_experiment

    async def finish_then_stop(experiment, *a, **k):
        out = await real(experiment, *a, **k)
        orch.request_stop()
        return out

    orch._finish_experiment = finish_then_stop

    def seq():
        epm = ExperimentPlanMaker()
        epm.add("demo", {})
        epm.add("demo", {})
        return epm.planned_experiments

    with pytest.raises(RunnerStopped):
        await orch.run_sequence(seq, {"demo": _three_pings})
    assert len(orch.finished_experiments) == 1
    rec = _load(orch.runs[-1]["yml_path"])
    assert orch.runs[-1]["type"] == "sequence"
    assert "aborted" in [str(s) for s in rec["sequence_status"]]
    uuids = [str(e["experiment_uuid"]) for e in rec["dispatched_experiments_abbr"]]
    assert uuids == [str(orch.last_experiment.experiment_uuid)]


class _SubscriberServer(_FakeDataActionServer):
    """Keeps a subscriber list like ActionHost.status_clients."""

    def __init__(self, *a):
        super().__init__(*a)
        self.subscribers = set()
        self.dispatcher.register("attach_client", self._attach)
        self.dispatcher.register("detach_client", self._detach)

    async def _attach(self, client_servkey, client_host, client_port, **kw):
        self.subscribers.add((client_servkey, client_host, client_port))
        return True

    async def _detach(self, client_servkey, client_host, client_port, **kw):
        self.subscribers.discard((client_servkey, client_host, client_port))
        return True


@pytest.mark.asyncio
async def test_stop_detaches_from_servers():
    """A stopped runner must leave the server's subscriber list: the server's
    serial status push otherwise stalls 5 x 30 s on the dead address and every
    later runner's wait_for_action never sees its status (the /runners hang)."""
    root = tempfile.mkdtemp(prefix="micro_stop_")
    port = _free_port()
    fake = _SubscriberServer("FAKE", "ping", root)
    await fake.dispatcher.serve("127.0.0.1", derive_rpc_port(port))
    orch = _make_orch(root, {"FAKE": {"host": "127.0.0.1", "port": port}})
    orch.group_urls = []
    await orch.start()
    try:
        await orch.run_action(
            Action(action_name="ping", action_server=MachineModel(server_name="FAKE")),
            await_completion=False,
        )
        assert len(fake.subscribers) == 1
        await orch.stop()
        assert fake.subscribers == set()
    finally:
        await fake.dispatcher.close()
        shutil.rmtree(root, ignore_errors=True)


class _SlowRegisteringServer(_SubscriberServer):
    """Registers the subscriber, then answers after the client gave up."""

    async def _attach(self, client_servkey, client_host, client_port, **kw):
        self.subscribers.add((client_servkey, client_host, client_port))
        await asyncio.sleep(0.8)
        return True


@pytest.mark.asyncio
async def test_stop_detaches_server_whose_attach_timed_out_but_registered():
    root = tempfile.mkdtemp(prefix="micro_stop_")
    port = _free_port()
    fake = _SlowRegisteringServer("FAKE", "ping", root)
    await fake.dispatcher.serve("127.0.0.1", derive_rpc_port(port))
    orch = _make_orch(root, {"FAKE": {"host": "127.0.0.1", "port": port}})
    orch.default_timeout = 0.3
    orch.group_urls = []
    await orch.start()
    try:
        assert await orch.attach_to("FAKE") is False  # timed out client-side
        assert len(fake.subscribers) == 1  # ... yet registered server-side
        await orch.stop()
        assert fake.subscribers == set()
    finally:
        await fake.dispatcher.close()
        shutil.rmtree(root, ignore_errors=True)


@pytest.mark.asyncio
async def test_runner_except_exception_loop_cannot_swallow_a_stop(rig):
    """A runner's retry loop around run_action must not turn a stop into a retry."""
    orch, fake = rig
    orch.request_stop()
    attempts = 0
    act = Action(action_name="ping", action_server=MachineModel(server_name="FAKE"))
    with pytest.raises(RunnerStopped):
        for _ in range(3):
            attempts += 1
            try:
                await orch.run_action(act)
            except Exception:
                continue
    assert attempts == 1 and fake.action_calls == []
