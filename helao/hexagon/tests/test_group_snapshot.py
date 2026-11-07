"""GroupSnapshot builder: pure, read-only, plain-dict output."""

from datetime import timedelta
from types import SimpleNamespace

from helao.core.models.hlostatus import HloStatus
from helao.core.models.orchstatus import LoopStatus
from helao.hexagon.tests.group_fakes import (
    T0,
    NoScan,
    fake_act,
    fake_exp,
    fake_orch,
    fake_seq,
)


def _snap(orch, **kw):
    from helao.core.models.group_snapshot import build_snapshot

    args = dict(seq_no=1, now=100.0, events=[], finish_errors={}, first_seen={})
    args.update(kw)
    return build_snapshot(orch, **args)


def test_fakes_use_real_model_field_names():
    from helao.core.models.machine import MachineModel
    from helao.core.models.server import ActionServerModel, GlobalStatusModel
    from helao.helpers.premodels import Action, Experiment, Sequence

    assert vars(fake_act()).keys() <= set(Action.model_fields)
    assert vars(fake_exp()).keys() <= set(Experiment.model_fields)
    assert vars(fake_seq()).keys() <= set(Sequence.model_fields)

    for name in (
        "action_uuid",
        "action_name",
        "action_server",
        "experiment_uuid",
        "action_timestamp",
        "action_finished_timestamp",
        "action_status",
    ):
        assert name in Action.model_fields, name
    for name in (
        "experiment_uuid",
        "experiment_name",
        "experiment_timestamp",
        "experiment_finished_timestamp",
        "experiment_status",
        "dispatched_actions",
    ):
        assert name in Experiment.model_fields, name
    for name in (
        "sequence_uuid",
        "sequence_name",
        "sequence_label",
        "sequence_timestamp",
        "dispatched_experiments",
    ):
        assert name in Sequence.model_fields, name
    assert "estop" in ActionServerModel.model_fields
    assert "server_name" in MachineModel.model_fields
    for name in (
        "loop_state",
        "loop_intent",
        "orch_state",
        "server_dict",
        "active_dict",
        "nonactive_dict",
        "counter_dispatched_actions",
    ):
        assert name in GlobalStatusModel.model_fields, name


def test_snapshot_is_plain_data_that_wire_dumps_round_trips():
    from helao.helpers.ws_utils import wire_dumps, wire_loads

    orch = fake_orch()
    orch.active_sequence = fake_seq()
    snap = _snap(orch)
    assert wire_loads(wire_dumps(snap)) == snap
    assert snap["seq"]["t_start"] == T0.timestamp()
    assert snap["loop_state"] == "stopped"


def test_server_status_precedence_and_config_filter():
    from helao.core.models.group_snapshot import server_rows

    orch = fake_orch(servers=("A", "B", "C", "D", "E"))
    gsm = orch.globalstatusmodel
    a = fake_act(server="A")
    b = fake_act(server="B")
    gsm.active_dict = {a.action_uuid: a, b.action_uuid: b}
    orch.status_summary = {"A": ("unreachable", "unknown")}
    gsm.server_dict = {
        ("B", "m"): SimpleNamespace(estop=True),
        ("X", "m"): SimpleNamespace(estop=False),
    }
    rows = {
        r["key"]: r
        for r in server_rows(orch, finish_errors={"D": "errored", "E": "finished"})
    }
    assert rows["A"]["status"] == "unreachable"  # beats busy
    assert rows["B"]["status"] == "estop"  # beats busy
    assert rows["C"]["status"] == "idle"
    assert rows["D"]["status"] == "error"
    assert rows["E"]["status"] == "idle"
    assert rows["X"]["status"] == "idle"  # known to the orch, not in config
    assert "ORCH" not in rows and "UI" not in rows
    busy = fake_act(server="C", name="move")
    gsm.active_dict = {busy.action_uuid: busy}
    rows = {r["key"]: r for r in server_rows(orch, finish_errors={})}
    assert rows["C"] == {"key": "C", "status": "busy", "active_action": "move"}


def test_experiment_window_bounds_and_totals():
    from helao.core.models.group_snapshot import experiment_rows

    orch = fake_orch()
    seq = fake_seq()
    seq.dispatched_experiments = [
        fake_exp(
            f"d{i}", ts=T0, fin=T0 + timedelta(seconds=1), status=(HloStatus.finished,)
        )
        for i in range(25)
    ]
    seq.dispatched_experiments[-1].experiment_status = [HloStatus.errored]
    orch.active_sequence = seq
    orch.active_experiment = fake_exp("act", ts=T0)
    orch.experiment_dq.extend(fake_exp(f"q{i}", with_uuid=False) for i in range(60))
    rows, n_done, n_queued = experiment_rows(orch)
    states = [r["state"] for r in rows]
    assert states == ["done"] * 19 + ["error"] + ["active"] + ["queued"] * 50
    assert rows[0]["name"] == "d5"
    assert (n_done, n_queued) == (5, 10)
    assert rows[21]["uuid"] is None and rows[21]["qidx"] == 0
    assert rows[20]["t_start"] == T0.timestamp() and rows[20]["t_end"] is None


def test_active_experiment_already_in_done_is_not_listed_twice():
    from helao.core.models.group_snapshot import experiment_rows

    orch = fake_orch()
    seq = fake_seq()
    exp = fake_exp("e", ts=T0, fin=T0, status=(HloStatus.finished,))
    seq.dispatched_experiments = [exp]
    orch.active_sequence = seq
    orch.active_experiment = exp
    rows, _, _ = experiment_rows(orch)
    assert [r["state"] for r in rows] == ["done"]


def test_action_rows_states_times_and_fallback():
    from helao.core.models.group_snapshot import action_rows

    orch = fake_orch()
    exp = fake_exp("e", ts=T0)
    orch.active_experiment = exp
    gsm = orch.globalstatusmodel
    done = fake_act(
        name="a1", exp_uuid=exp.experiment_uuid, fin=T0 + timedelta(seconds=5)
    )
    running = fake_act(name="a2", exp_uuid=exp.experiment_uuid, ts=None)
    failed = fake_act(name="a3", exp_uuid=exp.experiment_uuid, fin=T0)
    queued = fake_act(name="a4", exp_uuid=exp.experiment_uuid, ts=None)
    exp.dispatched_actions = [done, running, failed]
    gsm.active_dict = {running.action_uuid: running}
    gsm.nonactive_dict = {
        HloStatus.finished: {done.action_uuid: done},
        HloStatus.errored: {failed.action_uuid: failed},
    }
    orch.action_dq.append(queued)
    rows = action_rows(orch, first_seen={str(running.action_uuid): 42.0})
    assert [(r["name"], r["state"]) for r in rows] == [
        ("a1", "done"),
        ("a2", "active"),
        ("a3", "error"),
        ("a4", "queued"),
    ]
    assert rows[0]["t_end"] == (T0 + timedelta(seconds=5)).timestamp()
    assert rows[1]["t_start"] == 42.0  # action_timestamp None -> first observation
    assert rows[3]["t_start"] is None and rows[3]["uuid"] == str(queued.action_uuid)


def test_active_action_not_yet_in_dispatched_actions_is_listed():
    from helao.core.models.group_snapshot import action_rows

    orch = fake_orch()
    exp = fake_exp("e", ts=T0)
    orch.active_experiment = exp
    early = fake_act(name="early", exp_uuid=exp.experiment_uuid)
    orch.globalstatusmodel.active_dict = {early.action_uuid: early}
    assert [r["state"] for r in action_rows(orch, first_seen={})] == ["active"]


def test_closing_out_only_while_stopped_with_an_active_experiment():
    orch = fake_orch()
    orch.active_experiment = fake_exp("e", ts=T0)
    assert _snap(orch)["closing_out"] is True
    orch.globalstatusmodel.loop_state = LoopStatus.started
    assert _snap(orch)["closing_out"] is False
    orch.globalstatusmodel.loop_state = LoopStatus.stopped
    orch.active_experiment = None
    assert _snap(orch)["closing_out"] is False


def test_orch_own_action_is_reported_on_the_orch_not_as_a_server():
    orch = fake_orch()
    wait = fake_act(server="ORCH", name="wait")
    orch.globalstatusmodel.active_dict = {wait.action_uuid: wait}
    snap = _snap(orch)
    assert snap["orch_action"] == "wait"
    assert "ORCH" not in {s["key"] for s in snap["servers"]}


def test_experiment_rows_reads_only_the_queued_window():
    from collections import deque

    from helao.core.models.group_snapshot import EXP_QUEUED_WINDOW, experiment_rows

    class CountingDeque(deque):
        pulled = 0

        def __iter__(self):
            for item in super().__iter__():
                type(self).pulled += 1
                yield item

    orch = fake_orch()
    orch.experiment_dq = CountingDeque(
        fake_exp(f"q{i}", with_uuid=False) for i in range(5000)
    )
    rows, _, n_queued = experiment_rows(orch)
    assert CountingDeque.pulled <= EXP_QUEUED_WINDOW
    assert n_queued == 5000 - EXP_QUEUED_WINDOW


def test_error_wins_when_finished_and_errored_buckets_both_hold_the_action():
    from helao.core.models.group_snapshot import action_rows

    for order in (
        (HloStatus.finished, HloStatus.errored),
        (HloStatus.errored, HloStatus.finished),
    ):
        orch = fake_orch()
        exp = fake_exp("e", ts=T0)
        orch.active_experiment = exp
        failed = fake_act(name="bad", exp_uuid=exp.experiment_uuid, fin=T0)
        exp.dispatched_actions = [failed]
        orch.globalstatusmodel.nonactive_dict = {
            s: {failed.action_uuid: failed} for s in order
        }
        assert [r["state"] for r in action_rows(orch, first_seen={})] == [
            "error"
        ], order


def test_parked_head_action_is_listed_as_queued_before_action_dq():
    from helao.core.models.group_snapshot import action_rows

    orch = fake_orch()
    exp = fake_exp("e", ts=T0)
    orch.active_experiment = exp
    parked = fake_act(name="parked", ts=None)
    nxt = fake_act(name="next", ts=None)
    orch.parked_head_action = parked
    orch.action_dq.append(nxt)
    rows = action_rows(orch, first_seen={})
    assert [(r["name"], r["state"]) for r in rows] == [
        ("parked", "queued"),
        ("next", "queued"),
    ]


def test_action_rows_caps_queue_and_ignores_other_experiments_history():
    from helao.core.models.group_snapshot import ACT_QUEUED_WINDOW, action_rows

    orch = fake_orch()
    exp = fake_exp("e", ts=T0)
    orch.active_experiment = exp
    stale = fake_act(name="stale", exp_uuid=None, fin=T0)
    orch.globalstatusmodel.nonactive_dict = {
        HloStatus.finished: {stale.action_uuid: stale}
    }
    orch.action_dq.extend(
        fake_act(name=f"q{i}", ts=None) for i in range(ACT_QUEUED_WINDOW + 100)
    )
    rows = action_rows(orch, first_seen={})
    assert len(rows) == ACT_QUEUED_WINDOW
    assert all(r["state"] == "queued" for r in rows)
    assert "stale" not in {r["name"] for r in rows}


def test_action_rows_never_scans_the_finished_history():
    from helao.core.models.group_snapshot import action_rows

    orch = fake_orch()
    exp = fake_exp("e", ts=T0)
    orch.active_experiment = exp
    mine = fake_act(name="mine", exp_uuid=exp.experiment_uuid, fin=T0)
    exp.dispatched_actions = [mine]
    history = NoScan(
        {fake_act(fin=T0).action_uuid: fake_act(fin=T0) for _ in range(50)}
    )
    history[mine.action_uuid] = mine
    orch.globalstatusmodel.nonactive_dict = {HloStatus.finished: history}
    rows = action_rows(orch, first_seen={})
    assert [(r["name"], r["state"]) for r in rows] == [("mine", "done")]


def test_finished_sequence_is_framed_from_last_sequence_with_its_last_experiment():
    from helao.core.models.group_snapshot import experiment_rows

    orch = fake_orch()
    seq = fake_seq()
    last = fake_exp("last", ts=T0, fin=T0, status=(HloStatus.finished,))
    seq.dispatched_experiments = [last]
    orch.last_sequence = seq  # close-out emptied active_sequence
    orch.experiment_dq.append(fake_exp("stray", with_uuid=False))
    snap = _snap(orch)
    assert snap["seq"]["finished"] is True and snap["seq"]["name"] == "seq"
    assert [(r["name"], r["state"]) for r in snap["experiments"]] == [("last", "done")]
    assert snap["n_queued"] == 0
    orch.active_sequence = seq
    snap = _snap(orch)
    assert snap["seq"]["finished"] is False
    assert [r["state"] for r in snap["experiments"]] == ["done", "queued"]
    rows, _, _ = experiment_rows(orch)
    assert len(rows) == 2


def test_finished_sequence_says_how_it_ended():
    orch = fake_orch()
    seq = fake_seq()
    orch.last_sequence = seq
    cases = [
        ((HloStatus.finished,), "finished"),
        ((HloStatus.finished, HloStatus.estopped), "estopped"),
        ((HloStatus.estopped, HloStatus.finished), "estopped"),
        ((HloStatus.finished, HloStatus.errored), "error"),
    ]
    for statuses, want in cases:
        seq.sequence_status = list(statuses)
        assert _snap(orch)["seq"]["ended"] == want, statuses
    orch.active_sequence = seq  # still running: nothing has ended
    assert _snap(orch)["seq"]["ended"] is None


def test_idle_orch_with_no_sequence_at_all_has_no_seq():
    assert _snap(fake_orch())["seq"] is None


def test_queued_rows_are_rebuilt_only_when_length_or_head_changes():
    from collections import deque

    from helao.core.models.group_snapshot import experiment_rows

    class Counting(deque):
        pulled = 0

        def __iter__(self):
            for item in super().__iter__():
                type(self).pulled += 1
                yield item

    orch = fake_orch()
    orch.active_sequence = fake_seq()
    orch.experiment_dq = Counting(fake_exp(f"q{i}", with_uuid=False) for i in range(5))
    cache: dict = {}
    experiment_rows(orch, cache)
    first = Counting.pulled
    assert first == 5
    rows, _, _ = experiment_rows(orch, cache)
    assert Counting.pulled == first  # unchanged: served from the cache
    assert [r["name"] for r in rows] == [f"q{i}" for i in range(5)]
    orch.experiment_dq.popleft()  # head and length both change
    rows, _, _ = experiment_rows(orch, cache)
    assert Counting.pulled == first + 4
    assert [r["name"] for r in rows] == [f"q{i}" for i in range(1, 5)]
    assert [r["qidx"] for r in rows] == [0, 1, 2, 3]
    orch.experiment_dq.append(fake_exp("new", with_uuid=False))  # length only
    rows, _, _ = experiment_rows(orch, cache)
    assert rows[-1]["name"] == "new"
    orch.experiment_dq.popleft()  # pop + push: same length, new head
    orch.experiment_dq.append(fake_exp("newer", with_uuid=False))
    rows, _, _ = experiment_rows(orch, cache)
    assert [r["name"] for r in rows] == ["q2", "q3", "q4", "new", "newer"]


def test_a_zdeque_head_identity_is_o1_and_changes_with_the_head():
    from helao.core.models.group_snapshot import _head
    from helao.helpers.zdeque import zdeque

    dq = zdeque([fake_exp("a"), fake_exp("b")])
    h = _head(dq)
    assert isinstance(h, bytes) and _head(dq) is h
    dq.popleft()
    assert _head(dq) is not h and _head(zdeque()) is None
