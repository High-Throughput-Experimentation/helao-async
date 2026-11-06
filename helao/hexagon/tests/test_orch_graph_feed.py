# pyright: reportOptionalSubscript=false, reportAttributeAccessIssue=false, reportArgumentType=false, reportOptionalMemberAccess=false
"""OrchGraphFeed against a fake orch, plus the OrchHost wiring and /get_object."""

import asyncio

import pytest

from helao.core.models.hlostatus import HloStatus
from helao.hexagon.tests.group_fakes import T0, fake_act, fake_exp, fake_orch, fake_seq


class _Q:
    def __init__(self):
        self.items = []

    def put_nowait(self, item):
        self.items.append(item)


def _feed(orch):
    from helao.hexagon.app.orch_graph_feed import OrchGraphFeed

    return OrchGraphFeed(orch, _Q())


def test_unchanged_state_sends_nothing_but_the_heartbeat_still_arrives():
    feed = _feed(fake_orch())
    first = feed.step(0.0)
    assert first is not None and first["seq_no"] == 1
    assert feed.step(0.1) is None
    assert feed.step(1.9) is None
    beat = feed.step(2.0)
    assert beat is not None and beat["seq_no"] == 2 and beat["events"] == []
    assert beat is not first  # WsPublisher identity cache: a new object per publish


def test_first_frame_primes_without_replaying_old_finishes():
    orch = fake_orch()
    old = fake_act()
    orch.globalstatusmodel.nonactive_dict = {HloStatus.finished: {old.action_uuid: old}}
    assert _feed(orch).step(0.0)["events"] == []


def test_dispatch_then_finish_events():
    orch = fake_orch()
    feed = _feed(orch)
    feed.step(0.0)
    a = fake_act(server="SIM", name="acquire")
    orch.globalstatusmodel.active_dict = {a.action_uuid: a}
    frame = feed.step(0.1)
    assert [(e["kind"], e["server"], e["action_name"]) for e in frame["events"]] == [
        ("dispatch", "SIM", "acquire")
    ]
    orch.globalstatusmodel.active_dict = {}
    orch.globalstatusmodel.nonactive_dict = {HloStatus.finished: {a.action_uuid: a}}
    frame = feed.step(0.2)
    assert [(e["kind"], e["status"]) for e in frame["events"]] == [
        ("finish", "finished")
    ]
    assert {s["key"]: s["status"] for s in frame["servers"]}["SIM"] == "idle"


def test_errored_finish_marks_the_server_error():
    orch = fake_orch()
    feed = _feed(orch)
    feed.step(0.0)
    a = fake_act(server="SIM")
    orch.globalstatusmodel.active_dict = {a.action_uuid: a}
    feed.step(0.1)
    orch.globalstatusmodel.active_dict = {}
    orch.globalstatusmodel.nonactive_dict = {HloStatus.errored: {a.action_uuid: a}}
    frame = feed.step(0.2)
    assert frame["events"][0]["status"] == "errored"
    assert {s["key"]: s["status"] for s in frame["servers"]}["SIM"] == "error"


def test_an_action_seen_only_finished_still_yields_dispatch_then_finish():
    orch = fake_orch()
    feed = _feed(orch)
    feed.step(0.0)
    a = fake_act()
    orch.globalstatusmodel.nonactive_dict = {HloStatus.finished: {a.action_uuid: a}}
    frame = feed.step(0.1)
    assert [e["kind"] for e in frame["events"]] == ["dispatch", "finish"]


def test_an_action_that_vanishes_without_a_terminal_bucket_still_finishes():
    orch = fake_orch()
    feed = _feed(orch)
    feed.step(0.0)
    a = fake_act()
    orch.globalstatusmodel.active_dict = {a.action_uuid: a}
    feed.step(0.1)
    orch.globalstatusmodel.active_dict = {}
    frame = feed.step(0.2)
    assert [(e["kind"], e["status"]) for e in frame["events"]] == [
        ("finish", "finished")
    ]


def test_unhashable_driver_status_does_not_break_the_fingerprint():
    orch = fake_orch()
    orch.status_summary = {"SIM": ("idle", {"axis": [1, 2]})}
    feed = _feed(orch)
    assert feed.step(0.0) is not None
    orch.status_summary = {"SIM": ("idle", {"axis": [1, 3]})}
    assert feed.step(0.1) is not None  # a changed driver status is a change
    orch.status_summary = {"SIM": ("idle", {"axis": [1, 3]})}
    assert feed.step(0.2) is None  # unchanged again: nothing to send


def test_window_and_closing_out_reach_the_frame():
    orch = fake_orch()
    seq = fake_seq()
    seq.dispatched_experiments = [
        fake_exp(f"d{i}", ts=T0, fin=T0, status=(HloStatus.finished,))
        for i in range(22)
    ]
    orch.active_sequence = seq
    orch.active_experiment = fake_exp("a", ts=T0)
    frame = _feed(orch).step(0.0)
    assert frame["n_done"] == 2 and frame["closing_out"] is True


@pytest.mark.asyncio
async def test_an_exception_in_the_build_does_not_kill_the_task():
    from helao.hexagon.app.orch_graph_feed import OrchGraphFeed

    q = _Q()
    feed = OrchGraphFeed(fake_orch(), q, tick_s=0.01, heartbeat_s=0.02)
    real_step = feed.step
    calls = {"n": 0}

    def flaky(now):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return real_step(now)

    feed.step = flaky
    task = asyncio.create_task(feed.run())
    await asyncio.sleep(0.2)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert calls["n"] > 2 and len(q.items) >= 1


def test_last_experiment_finishing_alone_yields_a_new_frame():
    orch = fake_orch()
    seq = fake_seq()
    orch.active_sequence = seq
    feed = _feed(orch)
    assert feed.step(0.0) is not None
    assert feed.step(0.1) is None
    seq.dispatched_experiments.append(
        fake_exp("d", ts=T0, fin=T0, status=(HloStatus.finished,))
    )
    assert feed.step(0.2) is not None  # nothing else changed


def test_the_last_sequence_dispatched_count_is_fingerprinted_too():
    orch = fake_orch()
    seq = fake_seq()
    orch.last_sequence = seq
    feed = _feed(orch)
    feed.step(0.0)
    seq.dispatched_experiments.append(fake_exp("d"))
    assert feed.step(0.1) is not None


def _host():
    from helao.hexagon.tests.test_orch_host_surface import _host as surface_host

    return surface_host()


def test_host_serves_ws_orch_once_with_identity_encoding():
    host = _host()
    assert [
        r for r in host.routes if getattr(r, "path", "") == "/ws_orch"
    ].__len__() == 1
    assert "as_dict" not in host.orch_graph_publisher.xform_func.__code__.co_names
    assert host.graph_feed.orch is host


def test_get_object_finds_each_tier_and_misses_with_null():
    from uuid import uuid4

    from fastapi.testclient import TestClient

    from helao.core.models.machine import MachineModel
    from helao.helpers.premodels import Action, Experiment, Sequence

    host = _host()
    sim = MachineModel(server_name="SIM")
    act_active = Action(action_name="a_active", action_server=sim, action_uuid=uuid4())
    act_parked = Action(action_name="a_parked", action_server=sim, action_uuid=uuid4())
    act_live = Action(action_name="a_live", action_server=sim, action_uuid=uuid4())
    act_queued = Action(action_name="a_queued", action_server=sim, action_uuid=uuid4())
    exp_active = Experiment(experiment_name="e_active", experiment_uuid=uuid4())
    exp_active.dispatched_actions = [act_active]
    exp_queued = Experiment(experiment_name="e_queued", experiment_uuid=uuid4())
    exp_done = Experiment(experiment_name="e_done", experiment_uuid=uuid4())
    seq = Sequence(sequence_name="s", sequence_uuid=uuid4())
    seq.dispatched_experiments = [exp_done.get_exp()]
    host.active_sequence = seq
    host.active_experiment = exp_active
    host.parked_head_action = act_parked
    host.globalstatusmodel.active_dict[act_live.action_uuid] = act_live
    # queued items hold no uuid until activation and the zdeque unpickles every
    # item on iteration: the endpoint must never touch them
    host.experiment_dq.append(exp_queued)
    host.action_dq.append(act_queued)
    hist_uuid = uuid4()
    host.action_history[hist_uuid] = {"action_name": "a_hist"}
    ehist_uuid = uuid4()
    host.experiment_history[ehist_uuid] = {"experiment_name": "e_hist"}

    client = TestClient(host)

    def get(kind, uid):
        r = client.post("/get_object", params={"kind": kind, "uuid": str(uid)})
        assert r.status_code == 200
        return r.json()

    assert (
        get("experiment", exp_active.experiment_uuid)["experiment_name"] == "e_active"
    )
    assert get("experiment", exp_done.experiment_uuid)["experiment_name"] == "e_done"
    assert get("experiment", ehist_uuid)["experiment_name"] == "e_hist"
    assert get("action", act_active.action_uuid)["action_name"] == "a_active"
    assert get("action", act_parked.action_uuid)["action_name"] == "a_parked"
    assert get("action", act_live.action_uuid)["action_name"] == "a_live"
    assert get("action", hist_uuid)["action_name"] == "a_hist"
    assert get("action", uuid4()) is None
    assert get("experiment", exp_queued.experiment_uuid) is None
    assert get("action", act_queued.action_uuid) is None
    assert get("sequence", seq.sequence_uuid) is None


def test_get_object_never_iterates_a_queue():
    from uuid import uuid4

    from helao.hexagon.app.orch_payloads import _object_payload

    class Boom:
        def __iter__(self):
            raise AssertionError("queue iterated")

        def __len__(self):
            raise AssertionError("queue measured")

    orch = fake_orch()
    orch.experiment_dq = orch.action_dq = Boom()
    orch.action_history = {}
    orch.experiment_history = {}
    assert _object_payload(orch, "experiment", str(uuid4())) is None
    assert _object_payload(orch, "action", str(uuid4())) is None


@pytest.mark.asyncio
async def test_shutdown_cancels_the_feed_task_and_closes_its_queue():
    host = _host()
    host.graph_feed_task = asyncio.create_task(host.graph_feed.run())
    closed = []

    async def close():
        closed.append(True)

    host.orch_graph_q.close = close
    await asyncio.sleep(0)
    await host.orch_shutdown()
    await asyncio.sleep(0)
    assert host.graph_feed_task.cancelled()
    assert closed == [True]
