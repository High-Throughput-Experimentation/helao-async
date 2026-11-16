"""MicroOrch state the /group runner feed reads (spec: Runner side)."""

import asyncio
import json
import shutil
import tempfile

import pytest
import pytest_asyncio

from helao.core.models.group_snapshot import build_runner_snapshot
from helao.core.models.machine import MachineModel
from helao.core.rpc import RPCClient, derive_rpc_port
from helao.core.tests.unit_test_micro_orch import (
    _FakeDataActionServer,
    _demo_exp_func,
    _free_port,
    _make_orch,
)
from helao.helpers.premodels import Action, Experiment, ExperimentPlanMaker


@pytest_asyncio.fixture  # the repo runs pytest-asyncio in strict mode
async def rig():
    root = tempfile.mkdtemp(prefix="micro_group_")
    port = _free_port()
    fake = _FakeDataActionServer("FAKE", "ping", root)
    await fake.dispatcher.serve("127.0.0.1", derive_rpc_port(port))
    orch = _make_orch(root, {"FAKE": {"host": "127.0.0.1", "port": port}})
    orch.group_urls = []  # no feed in these tests
    await orch.start()
    try:
        yield orch
    finally:
        await orch.stop()
        await fake.dispatcher.close()
        shutil.rmtree(root, ignore_errors=True)


@pytest.mark.asyncio
async def test_run_experiment_records_and_clears_active_state(rig):
    orch = rig
    await orch.run_experiment(
        _demo_exp_func, experiment=Experiment(experiment_name="e1")
    )
    assert orch.active_experiment is None
    assert orch.last_experiment.experiment_name == "e1"
    assert [e.experiment_name for e in orch.finished_experiments] == ["e1"]
    assert len(orch.planned_actions) == 2
    assert all(a.action_uuid is not None for a in orch.planned_actions)
    events = orch.drain_events()
    kinds = [e["kind"] for e in events]
    assert kinds.count("dispatch") == 2 and kinds.count("finish") == 2
    assert all(e["server"] == "FAKE" and e["action_name"] == "ping" for e in events)
    assert orch.drain_events() == []
    u = orch.planned_actions[0].action_uuid
    assert orch.t_dispatch[u] <= orch.t_finish[u]


@pytest.mark.asyncio
async def test_runner_snapshot_follows_a_real_experiment_and_serialises(rig):
    orch = rig
    snaps = []

    def take():
        snaps.append(build_runner_snapshot(orch, seq_no=0, now=0.0, events=[]))

    async def sampler():
        while True:
            take()
            await asyncio.sleep(0.005)

    take()  # before
    task = asyncio.create_task(sampler())
    try:
        await orch.run_experiment(
            _demo_exp_func, experiment=Experiment(experiment_name="e1")
        )
    finally:
        task.cancel()
    take()  # after
    json.dumps(snaps)  # the runner POSTs this
    assert not snaps[0]["experiments"]
    assert any(
        [r["state"] for r in s["experiments"]] == ["active"] for s in snaps[1:-1]
    )
    last = snaps[-1]
    assert [r["state"] for r in last["experiments"]] == ["done"]
    assert [r["state"] for r in last["actions"]] == ["done", "done"]


@pytest.mark.asyncio
async def test_dispatch_rpc_failure_emits_errored_finish(rig):
    orch = rig
    act = Action(action_name="nope", action_server=MachineModel(server_name="FAKE"))
    with pytest.raises(Exception):
        await orch.dispatch_action(act, timeout=1.0)
    events = orch.drain_events()
    assert [e["kind"] for e in events] == ["dispatch", "finish"]
    assert events[1]["status"] == "errored"
    assert orch.finish_errors["FAKE"] == "errored"
    assert orch.active_actions() == {}


@pytest.mark.asyncio
async def test_get_object_by_kind_and_uuid_over_rpc(rig):
    orch = rig
    await orch.run_experiment(
        _demo_exp_func, experiment=Experiment(experiment_name="e2")
    )
    exp_uuid = str(orch.last_experiment.experiment_uuid)
    act_uuid = str(orch.planned_actions[1].action_uuid)
    client = RPCClient(
        endpoint=f"tcp://127.0.0.1:{derive_rpc_port(orch.port)}", default_timeout=2.0
    )
    try:
        exp = await client.call("get_object", kind="experiment", uuid=exp_uuid)
        act = await client.call("get_object", kind="action", uuid=act_uuid)
        none = await client.call("get_object", kind="action", uuid="not-a-uuid")
    finally:
        await client.close()
    assert exp["experiment_name"] == "e2"
    assert act["action_name"] == "ping"
    assert none is None


def test_feed_urls_from_reflex_entries_and_override(tmp_path):
    orch = _make_orch(
        str(tmp_path),
        {
            "UI": {"host": "10.0.0.5", "port": 8100, "reflex": "helao_ui"},
            "FAKE": {"host": "h", "port": 1},
        },
    )
    assert orch.feed_urls() == ["http://10.0.0.5:8101"]
    orch.group_urls = ["http://x:1"]
    assert orch.feed_urls() == ["http://x:1"]
    orch.group_urls = []
    assert orch.feed_urls() == []


def test_feed_config_fields(tmp_path):
    orch = _make_orch(str(tmp_path), {"FAKE": {"host": "h", "port": 1}})
    cfg = orch.feed_config()
    assert cfg["server_key"] == "micro"
    assert cfg["rpc_port"] == derive_rpc_port(orch.port)
    assert cfg["world_servers"] == ["FAKE"]
    assert cfg["prefinish_experiment_hooks"] == []


@pytest.mark.asyncio
async def test_run_sequence_accepts_a_generator_seq_func(rig):
    def gen_seq(cycles: int = 2):
        epm = ExperimentPlanMaker()
        for _ in range(cycles):
            epm.add("demo_exp", {"wait_time": 0.0})
        yield from epm.planned_experiments

    await rig.run_sequence(gen_seq, {"demo_exp": _demo_exp_func}, cycles=2)
    assert len(rig.finished_experiments) == 2


@pytest.mark.asyncio
async def test_a_second_start_does_not_leak_a_feed_task(tmp_path):
    orch = _make_orch(str(tmp_path), {"FAKE": {"host": "h", "port": 1}})
    orch.group_urls = ["http://127.0.0.1:1"]

    async def serve(*a, **k):
        return None

    orch.dispatcher.serve = serve
    await orch.start()
    first = orch._feed_task
    await orch.start()
    try:
        assert first is not None and orch._feed_task is first
    finally:
        await orch.stop()
