"""/group page: pure helpers, tick logic, rendering and registration."""

import collections
from types import SimpleNamespace

import pytest

from helao.ui.shared.palette import GROUP_PULSE_DISPATCH, GROUP_STATE_COLORS

CFG = {
    "servers": {
        "ORCH": {"host": "127.0.0.1", "port": 8001, "group": "orchestrator"},
        "SIM": {"host": "127.0.0.1", "port": 8002, "group": "action"},
    }
}


class Feed:
    """Stand-in for WsIngest: ``raw`` batches plus the local arrival counter."""

    def __init__(self, maxlen=200):
        self.raw = collections.deque(maxlen=maxlen)
        self.n_batches = 0
        self.status = SimpleNamespace(message_count=0, last_epoch=0.0)

    def push(self, *frames, now=100.0):
        self.raw.append(list(frames))
        self.n_batches += 1
        self.status.message_count += len(frames)
        self.status.last_epoch = now


def seqs(frames):
    return [f["seq_no"] for f in frames]


@pytest.fixture
def group():
    from helao.ui.reflex import group as g

    g.configure_group(CFG)
    yield g
    g.configure_group(CFG)


def state():
    return SimpleNamespace(
        _cursor=-1,
        _snap=(),
        _pulses=(),
        _version=0,
        _exp_slots=(),
        _act_slots=(),
        _selected=(),
        _full_at=0.0,
        _pending_at=0.0,
        _probe_at=0.0,
        _old_orch=False,
        pending="",
        info_note="",
        tick_ms=500,
        lost=True,
        banner="",
    )


def frame(seq_no, events=(), **kw):
    return {
        "seq_no": seq_no,
        "servers": [{"key": "SIM", "status": "idle", "active_action": None}],
        "events": list(events),
        "experiments": [],
        "actions": [],
        **kw,
    }


DISPATCH = {"kind": "dispatch", "server": "SIM", "status": "active"}


# ---- new_frames: local arrival order, not the orchestrator's seq_no ----------


def test_new_frames_returns_each_frame_once():
    from helao.ui.reflex.group import new_frames

    feed = Feed()
    feed.push(frame(1))
    feed.push(frame(2), frame(3))
    got, cur = new_frames(feed, 1)
    assert seqs(got) == [2, 3] and cur == 2
    assert new_frames(feed, cur) == ([], 2)
    feed.push(frame(4))
    got, cur = new_frames(feed, cur)
    assert seqs(got) == [4] and cur == 3
    assert new_frames(None, 0) == ([], 0)


def test_new_frames_after_orch_restart_never_returns_old_frames_again():
    from helao.ui.reflex.group import new_frames

    feed = Feed()
    feed.push(frame(900))
    feed.push(frame(901))
    _, cur = new_frames(feed, 0)
    feed.push(frame(1))  # orchestrator restarted: seq_no went backwards
    got, cur = new_frames(feed, cur)
    assert seqs(got) == [1]
    for _ in range(3):
        got, cur = new_frames(feed, cur)
        assert got == []


def test_new_frames_clamps_a_cursor_ahead_of_a_recreated_feed():
    from helao.ui.reflex.group import new_frames

    feed = Feed()
    feed.push(frame(1))
    assert new_frames(feed, 50) == ([], 1)


def test_new_frames_when_the_deque_dropped_old_batches():
    from helao.ui.reflex.group import new_frames

    feed = Feed(maxlen=2)
    for i in range(1, 6):
        feed.push(frame(i))
    got, cur = new_frames(feed, 1)
    assert seqs(got) == [4, 5] and cur == 5


# ---- tick: seed, pulses, render cost ----------------------------------------


def test_fresh_page_renders_latest_snapshot_but_replays_no_pulses(group):
    feed = Feed()
    feed.push(frame(5, [DISPATCH]), now=100.0)
    feed.push(frame(6, [DISPATCH], loop_state="started"), now=100.0)
    s = state()
    group.apply_tick(s, feed, 100.5, "t")
    assert s._snap[0]["seq_no"] == 6 and s.loop_state == "started"
    assert s._pulses == () and s.tick_ms == group.SLOW_MS
    feed.push(frame(7, [DISPATCH]), now=100.6)
    group.apply_tick(s, feed, 100.7, "t")
    assert len(s._pulses) == 1 and s.tick_ms == group.FAST_MS
    assert s._cursor == feed.n_batches


def test_unfed_page_stays_unseeded_until_the_feed_exists(group):
    s = state()
    group.apply_tick(s, None, 100.0, "t")
    assert s._cursor == -1 and s.lost is True


def test_orch_restart_does_not_repulse_old_frames(group):
    feed = Feed()
    feed.push(frame(900, [DISPATCH]))
    s = state()
    group.apply_tick(s, feed, 100.0, "t")
    feed.push(frame(1, [DISPATCH]))
    group.apply_tick(s, feed, 100.1, "t")
    assert len(s._pulses) == 1
    group.apply_tick(s, feed, 100.2, "t")
    assert len(s._pulses) == 1  # the old frame was not returned a second time


def test_fast_tick_with_a_live_pulse_does_not_rebuild_the_strips(group, monkeypatch):
    feed = Feed()
    feed.push(frame(1))
    s = state()
    group.apply_tick(s, feed, 100.0, "t")
    feed.push(frame(2, [DISPATCH]))
    group.apply_tick(s, feed, 100.1, "t")
    assert s.tick_ms == group.FAST_MS
    built = []
    real = group.plots.marks_chart
    monkeypatch.setattr(
        group.plots,
        "marks_chart",
        lambda *a, **k: built.append(k["panel_id"]) or real(*a, **k),
    )
    group.apply_tick(s, feed, 100.116, "t")  # no frame, inside SLOW_MS
    assert built == ["group-graph-t"]
    group.apply_tick(s, feed, 100.7, "t")  # slow cadence due again
    assert sorted(built[1:]) == ["group-act-t", "group-exp-t", "group-graph-t"]


def test_new_frame_rebuilds_the_strips(group, monkeypatch):
    feed = Feed()
    feed.push(frame(1))
    s = state()
    group.apply_tick(s, feed, 100.0, "t")
    built = []
    real = group.plots.marks_chart
    monkeypatch.setattr(
        group.plots,
        "marks_chart",
        lambda *a, **k: built.append(k["panel_id"]) or real(*a, **k),
    )
    feed.push(frame(2))
    group.apply_tick(s, feed, 100.01, "t")
    assert "group-exp-t" in built and "group-act-t" in built


def test_backend_vars_touched_each_tick_are_tuples(group):
    s = state()
    feed = Feed()
    feed.push(frame(1))
    group.apply_tick(s, feed, 100.0, "t")
    for name in ("_snap", "_pulses", "_exp_slots", "_act_slots", "_selected"):
        assert isinstance(getattr(s, name), tuple), name
    for name in ("_snap", "_pulses", "_exp_slots", "_act_slots", "_selected"):
        assert vars(group.GroupState)[name].annotated_type is tuple, name


# ---- selection identity ------------------------------------------------------


def test_queued_selection_is_dropped_when_qidx_shifts_to_another_experiment(group):
    exp = lambda name, qidx: {
        "uuid": None,
        "qidx": qidx,
        "name": name,
        "state": "queued",
    }  # noqa: E731
    s = state()
    s._selected = ("experiment", "q3", "exp_c")
    snap = frame(1, experiments=[exp("exp_c", 3)])
    group._render_strips(s, snap, 100.0, "t")
    assert s._selected and s.info_note == ""
    # queue head popped: the same key now names a different experiment
    snap = frame(2, experiments=[exp("exp_d", 3)])
    group._render_strips(s, snap, 101.0, "t")
    assert s._selected == () and s.info_note == group.SELECTION_GONE


def test_selection_by_uuid_survives_and_vanishes_with_the_item(group):
    s = state()
    s._selected = ("experiment", "u1", "e")
    keep = frame(
        1,
        experiments=[
            {"uuid": "u1", "qidx": None, "name": "renamed", "state": "active"}
        ],
    )
    group._render_strips(s, keep, 100.0, "t")
    assert s._selected != ()
    group._render_strips(s, frame(2), 101.0, "t")
    assert s._selected == () and s.info_note == group.SELECTION_GONE


def test_strip_height_keeps_progress_bar_and_labels_apart():
    from helao.ui.reflex import group

    assert group.STRIP_H >= 70


# ---- S10: same orchestrator for stream and buttons ---------------------------


def test_backend_is_the_operators_only_when_it_targets_the_streamed_orch(
    group, monkeypatch
):
    monkeypatch.setattr(
        group, "session_backend", lambda token: SimpleNamespace(orch_key="ORCH")
    )
    assert group._backend("t").orch_key == "ORCH"
    monkeypatch.setattr(
        group, "session_backend", lambda token: SimpleNamespace(orch_key="OTHER")
    )
    assert group._backend("t") is None
    monkeypatch.setattr(group, "session_backend", lambda token: None)
    assert group._backend("t") is None


def test_group_picks_the_same_orchestrator_as_remote_backend(group):
    from helao.ui.shared.operator.orch_backend import RemoteBackend

    cfg = {
        "servers": {
            "A": {"host": "h", "port": 1, "group": "action"},
            "ORCH2": {"host": "h", "port": 2, "group": "orchestrator"},
            "ORCH1": {"host": "h", "port": 3, "group": "orchestrator"},
        }
    }
    group.configure_group(cfg)
    assert group._CFG["orch_key"] == RemoteBackend._detect_orch_key(cfg) == "ORCH2"


# ---- pure helpers (as specified) ---------------------------------------------


def test_stream_lost():
    from helao.ui.reflex.group import stream_lost

    f = Feed()
    assert stream_lost(None, 0.0)
    assert stream_lost(f, 100.0)
    f.push(frame(1), now=100.0)
    assert not stream_lost(f, 104.0)
    assert stream_lost(f, 105.5)


def test_pulse_for_direction_colour_and_self():
    from helao.ui.reflex.group import pulse_for

    d = pulse_for(
        {"kind": "dispatch", "server": "SIM", "status": "active"}, 5.0, "ORCH"
    )
    assert d is not None and d == ["SIM", "fwd", 5.0, 0.6, GROUP_PULSE_DISPATCH]
    f = pulse_for({"kind": "finish", "server": "SIM", "status": "errored"}, 5.0, "ORCH")
    assert f is not None and f[1] == "rev" and f[4] == GROUP_STATE_COLORS["error"]
    ok = pulse_for(
        {"kind": "finish", "server": "SIM", "status": "finished"}, 5.0, "ORCH"
    )
    assert ok is not None and ok[4] == GROUP_STATE_COLORS["done"]
    assert (
        pulse_for(
            {"kind": "dispatch", "server": "ORCH", "status": "active"}, 5.0, "ORCH"
        )
        is None
    )


def test_button_flags():
    from helao.ui.reflex.group import button_flags

    idle = {
        "loop_state": "stopped",
        "orch_state": "idle",
        "n_sequences_queued": 1,
        "seq": None,
        "experiments": [],
    }
    assert button_flags(idle, False) == {
        "can_start": True,
        "can_stop": False,
        "estopped": False,
        "can_estop": True,
    }
    assert button_flags({**idle, "n_sequences_queued": 0}, False)["can_start"] is False
    resumable = {
        **idle,
        "n_sequences_queued": 0,
        "seq": {"uuid": "s"},
        "experiments": [{"state": "queued"}],
    }
    assert button_flags(resumable, False)["can_start"] is True
    running = {**idle, "loop_state": "started"}
    assert button_flags(running, False)["can_stop"] is True
    stopped = {**idle, "loop_state": "estopped"}
    assert (
        button_flags(stopped, False)["estopped"] is True
        and button_flags(stopped, False)["can_start"] is False
    )
    assert button_flags(running, True) == {
        "can_start": False,
        "can_stop": False,
        "estopped": False,
        "can_estop": False,
    }


def test_pending_done():
    from helao.ui.reflex.group import pending_done

    assert pending_done("start", {"loop_state": "started"})
    assert not pending_done("start", {"loop_state": "stopped"})
    assert pending_done("stop", {"loop_state": "stopped"})
    assert pending_done("estop", {"loop_state": "estopped", "orch_state": "estopped"})
    assert pending_done("clear_estop", {"loop_state": "stopped", "orch_state": "idle"})


def test_object_request_falls_back_to_the_queue_index():
    from helao.ui.reflex.group import object_request

    assert object_request("experiment", {"uuid": "u", "qidx": None}) == (
        "get_object",
        "experiment",
        "u",
    )
    assert object_request("experiment", {"uuid": None, "qidx": 3}) == (
        "get_queue_object",
        "experiment",
        3,
    )
    assert object_request("action", {"uuid": None, "qidx": None}) is None


def test_graph_marks_unknown_status_and_lost_stream():
    from helao.ui.reflex.group import graph_marks

    snap = {
        "orch_state": "busy",
        "servers": [
            {"key": "SIM", "status": "busy", "active_action": "acquire"},
            {"key": "X", "status": "weird", "active_action": None},
        ],
    }
    marks, pulses = graph_marks(
        snap, [["SIM", "fwd", 0.0, 0.6, GROUP_PULSE_DISPATCH]], 0.1, "ORCH", False
    )
    nodes = next(m for m in marks if m.get("name", "").startswith("nodes:"))
    assert nodes["colors"] == [
        GROUP_STATE_COLORS["busy"],
        GROUP_STATE_COLORS["busy"],
        GROUP_STATE_COLORS["idle"],
    ]
    assert "X (weird)" in [m["value"] for m in marks if m["kind"] == "text"]
    assert len(pulses) == 1
    lost, _ = graph_marks(snap, [], 0.1, "ORCH", True)
    nodes = next(m for m in lost if m.get("name", "").startswith("nodes:"))
    assert set(nodes["colors"]) == {GROUP_STATE_COLORS["unreachable"]}


def test_header_fields_idle_and_running():
    from helao.ui.reflex.group import header_fields

    assert header_fields({})["seq_name"] == ""
    h = header_fields(
        {
            "seq": {"name": "S", "uuid": "0123456789abcdef", "t_start": None},
            "loop_state": "started",
            "orch_state": "busy",
            "closing_out": False,
        }
    )
    assert (h["seq_name"], h["seq_uuid_short"], h["loop_group"]) == (
        "S",
        "89abcdef",
        "busy",
    )


def test_ws_orch_frames_are_not_numeric_normalized():
    from helao.ui.reflex.ingest import NORMALIZERS

    assert NORMALIZERS["ws_orch"]([{"seq_no": 1, "servers": []}]) == ({}, [])


def test_page_renders_with_and_without_an_orchestrator(group):
    group.configure_group(CFG)
    rendered = str(group.group_page().render())
    assert "E-stop" in rendered and "Start" in rendered
    group.configure_group({"servers": {}})
    assert group.NO_ORCH_NOTE in str(group.group_page().render())


def test_group_route_nav_and_tint():
    from helao.ui.reflex import app
    from helao.ui.shared import palette

    assert "/group" in app.SHELL_ROUTES
    assert "/group" not in app.CREDENTIAL_ROUTES
    assert all(
        href != "/group"
        for _, items, gated in app.NAV_MENUS
        for _, href in items + gated
    )
    assert palette.REFLEX_PAGE_TINTS["/group"] == "pink-50"
    assert app.NAV_LINKS[0] == ("Group", "/group")
    assert app.NAV_ICONS["Group"] == "network"
    assert '"/group"' in str(app._nav())


def test_wsingest_counts_batches_in_local_arrival_order():
    import asyncio

    from helao.ui.reflex.ingest import WsIngest

    batches = [[{"seq_no": 900}], [], [{"seq_no": 1}, {"seq_no": 2}]]

    class Wss:
        async def read_messages(self):
            if not batches:
                raise asyncio.CancelledError
            return batches.pop(0)

    ing = WsIngest("h", 1, "ws_orch", drain_interval=0)
    ing._wss = Wss()  # type: ignore[assignment]
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(ing._drain_loop())
    assert ing.n_batches == 2 and len(ing.raw) == 2
    assert ing.status.message_count == 3
