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
        _exp_ords=(),
        _act_ords=(),
        _scopes=(),
        _first_at=0.0,
        _hovered="",
        tree_header="select a row",
        tree_html="",
        _full_at=0.0,
        _pending_at=0.0,
        _unconfirmed="",
        _probe_at=0.0,
        _old_orch=False,
        pending="",
        action_error="",
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
FINISH = {"kind": "finish", "server": "SIM", "status": "finished"}


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


def _exp(tag, state, qidx=None, uuid=None, name="scan"):
    return {"uuid": uuid, "qidx": qidx, "name": name, "state": state, "tag": tag}


def _click(group, s, kind, slot, snap):
    """Select slot ``slot`` the way ``_select`` does."""
    exp = kind == "experiment"
    ords = s._exp_ords if exp else s._act_ords
    s._selected = (kind, ords[slot], s._scopes[0 if exp else 1])


def _selected_row(group, s, snap, kind="experiment"):
    key = group.selected_key(s._selected, snap, kind)
    rows = snap["experiments" if kind == "experiment" else "actions"]
    row = next((r for r in rows if group.item_key(r) == key), None)
    assert row is not None, "selection not in view"
    return row


def _queue(tags, start, active=None, n_done=0):
    rows = [active] if active else []
    rows += [_exp(t, "queued", qidx=i) for i, t in enumerate(tags[start:])]
    return frame(1, experiments=rows, n_done=n_done)


def test_same_named_queued_selection_follows_the_item_when_the_head_pops(group):
    s = state()
    tags = ["a", "b", "c", "d", "e"]
    before = _queue(tags, 0)
    group._render_strips(s, before, 100.0, "t")
    _click(group, s, "experiment", 3, before)  # queued item "d"
    assert _selected_row(group, s, before)["tag"] == "d"
    # head pops and starts running; every name is still "scan"
    after = _queue(tags, 1, active=_exp("a", "active", uuid="ua"))
    group._render_strips(s, after, 101.0, "t")
    assert s.info_note == "" and _selected_row(group, s, after)["tag"] == "d"


def test_queued_selection_keeps_when_it_becomes_active(group):
    s = state()
    before = _queue(["a", "b", "c"], 0)
    group._render_strips(s, before, 100.0, "t")
    _click(group, s, "experiment", 0, before)  # head "a"
    after = _queue(["a", "b", "c"], 1, active=_exp("a", "active", uuid="ua"))
    group._render_strips(s, after, 101.0, "t")
    assert _selected_row(group, s, after)["tag"] == "a" and s.info_note == ""
    # and when it finishes: still "a", now a done row
    done = frame(
        3,
        experiments=[_exp("a", "done", uuid="ua"), _exp("b", "active", uuid="ub")]
        + [_exp("c", "queued", qidx=0)],
    )
    group._render_strips(s, done, 102.0, "t")
    assert _selected_row(group, s, done)["tag"] == "a"


def test_selection_clears_when_the_item_leaves_the_window_or_sequence(group):
    s = state()
    snap = _queue(["a", "b"], 0)
    group._render_strips(s, snap, 100.0, "t")
    _click(group, s, "experiment", 1, snap)
    s.tree_header, s.tree_html = "old", "<b>x</b>"
    group._render_strips(s, _queue(["a"], 0), 101.0, "t")  # "b" is gone
    assert s._selected == () and s.info_note == group.SELECTION_GONE
    assert (s.tree_header, s.tree_html) == ("select a row", "")
    # a new sequence restarts the ordinals: an old selection must not carry over
    s2 = state()
    one = {**_queue(["a", "b"], 0), "seq": {"uuid": "S1"}}
    group._render_strips(s2, one, 100.0, "t")
    _click(group, s2, "experiment", 1, one)
    two = {**_queue(["x", "y"], 0), "seq": {"uuid": "S2"}}
    group._render_strips(s2, two, 101.0, "t")
    assert s2._selected == ()


def test_action_selection_clears_when_the_experiment_changes(group):
    s = state()
    acts = [{"uuid": f"a{i}", "name": "act", "state": "done"} for i in range(3)]
    snap = frame(1, experiments=[_exp("e1", "active", uuid="u1")], actions=acts)
    group._render_strips(s, snap, 100.0, "t")
    _click(group, s, "action", 1, snap)
    assert _selected_row(group, s, snap, "action")["uuid"] == "a1"
    group._render_strips(s, snap, 101.0, "t")
    assert s._selected != ()
    nxt = frame(
        2, experiments=[_exp("e2", "active", uuid="u2")], actions=acts[:2], n_done=1
    )
    group._render_strips(s, nxt, 102.0, "t")
    assert s._selected == () and s.info_note == group.SELECTION_GONE


def test_selection_by_uuid_survives_and_vanishes_with_the_item(group):
    s = state()
    snap = frame(1, experiments=[_exp("u", "active", uuid="u1", name="renamed")])
    group._render_strips(s, snap, 100.0, "t")
    _click(group, s, "experiment", 0, snap)
    group._render_strips(s, snap, 100.5, "t")
    assert s._selected != ()
    group._render_strips(s, frame(2), 101.0, "t")
    assert s._selected == () and s.info_note == group.SELECTION_GONE


def test_exp_row_ordinals_are_sequence_positions():
    from helao.ui.reflex.group import exp_row_ordinals

    snap = {
        "n_done": 4,
        "experiments": [
            _exp("d", "done"),
            _exp("e", "error"),
            _exp("r", "active"),
            _exp("q0", "queued", qidx=0),
            _exp("q1", "queued", qidx=1),
        ],
    }
    assert exp_row_ordinals(snap) == [4, 5, 6, 7, 8]
    assert exp_row_ordinals({"experiments": [_exp("q", "queued", qidx=2)]}) == [2]


def test_strip_height_keeps_progress_bar_and_labels_apart():
    from helao.ui.reflex import group

    assert group.STRIP_H == 120  # xy's minimum chart height, and a bar + 2 labels fit


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
    from helao.ui.reflex.group import PULSE_S, pulse_for

    d = pulse_for(
        {"kind": "dispatch", "server": "SIM", "status": "active"}, 5.0, "ORCH"
    )
    assert d is not None and d == ["SIM", "fwd", 5.0, PULSE_S, GROUP_PULSE_DISPATCH]
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
        "can_clear_estop": False,
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
    # a lost stream disables everything except E-stop
    assert button_flags(running, True) == {
        "can_start": False,
        "can_stop": False,
        "estopped": False,
        "can_estop": True,
        "can_clear_estop": False,
    }
    # E-stop is disabled only while estopped; then Clear E-stop is offered
    assert button_flags(stopped, False)["can_estop"] is False
    assert button_flags(stopped, False)["can_clear_estop"] is True
    assert button_flags(stopped, True)["can_clear_estop"] is False


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
    by_colour = {
        m["colors"][0]: len(m["x"])
        for m in marks
        if m.get("name", "").startswith("nodes:") and m["x"]
    }
    assert by_colour == {GROUP_STATE_COLORS["busy"]: 2, GROUP_STATE_COLORS["idle"]: 1}
    assert "X (weird)" in [m["value"] for m in marks if m["kind"] == "text"]
    assert len(pulses) == 1
    lost, _ = graph_marks(snap, [], 0.1, "ORCH", True)
    drawn = [m for m in lost if m.get("name", "").startswith("nodes:") and m["x"]]
    assert {c for m in drawn for c in m["colors"]} == {
        GROUP_STATE_COLORS["unreachable"]
    }


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
    assert h["seq_finished"] is False
    done = header_fields({"seq": {"name": "S", "finished": True}})
    assert done["seq_finished"] is True and done["seq_name"] == "S"
    assert header_fields({})["seq_finished"] is False


def test_header_names_how_the_sequence_ended():
    from helao.ui.reflex.group import header_fields

    for ended, want in (
        ("estopped", "estopped"),
        ("error", "error"),
        ("finished", "finished"),
    ):
        h = header_fields({"seq": {"name": "S", "finished": True, "ended": ended}})
        assert h["seq_ended"] == want
    # an older orchestrator sends no `ended`; a running sequence has none
    assert (
        header_fields({"seq": {"name": "S", "finished": True}})["seq_ended"]
        == "finished"
    )
    assert header_fields({"seq": {"name": "S", "finished": False}})["seq_ended"] == ""
    assert header_fields({})["seq_ended"] == ""


def test_estopped_sequence_badge_uses_the_estop_colour_not_finished(group):
    from helao.ui.shared.palette import GROUP_BADGE_CLASSES

    node = group._seq_ended_badge(group.GroupState.seq_ended).render()["children"][0]
    cases = {c[0][0]: c[1] for c in node["match_cases"]}
    est = cases['"estopped"']
    assert est["children"][0]["contents"] == '"E-stopped"'
    assert f'className:"{GROUP_BADGE_CLASSES["estop"]}"' in est["props"]
    assert f'className:"{GROUP_BADGE_CLASSES["error"]}"' in cases['"error"']["props"]
    assert node["default"]["children"][0]["contents"] == '"finished"'
    assert f'className:"{GROUP_BADGE_CLASSES["idle"]}"' in node["default"]["props"]
    group.configure_group(CFG)
    assert "seq_ended" in str(group.group_page().render())


def test_finished_badge_shows_beside_the_name_and_idle_only_without_a_sequence(group):
    group.configure_group(CFG)
    rendered = str(group.group_page().render())
    assert "seq_finished" in rendered and "finished" in rendered
    assert "no active sequence" in rendered
    assert rendered.index("seq_name") < rendered.index("seq_finished")


def test_ws_orch_frames_are_not_numeric_normalized():
    from helao.ui.reflex.ingest import NORMALIZERS

    assert NORMALIZERS["ws_orch"](
        [{"seq_no": 1, "servers": [], "n_done": [1.0, 2.0], "orch_state": ("busy", 1)}]
    ) == ({}, [])


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


# ---- mount reset, probe delay, buttons, control, minors -----------------------


def test_reentering_the_page_does_not_replay_buffered_events(group):
    feed = Feed()
    feed.push(frame(1))
    s = state()
    group.apply_tick(s, feed, 100.0, "t")
    feed.push(frame(2, [DISPATCH]))
    group.apply_tick(s, feed, 100.1, "t")
    assert len(s._pulses) == 1
    s._old_orch = True
    group.GroupState.mount.fn(s)  # leave and come back: state persists, mount fires
    assert s._cursor == -1 and s._pulses == () and s._old_orch is False
    group.apply_tick(s, feed, 200.0, "t")
    assert s._pulses == () and s._snap[0]["seq_no"] == 2


def test_mount_chains_a_first_tick(group):
    result = group.GroupState.mount.fn(state())
    assert "GroupState.tick" in str(result)
    assert "GroupState.mount" in str(group.group_page().event_triggers["on_mount"])


def test_probe_waits_five_seconds_after_the_first_empty_tick(group):
    feed = Feed()  # never connected: message_count == 0
    s = state()
    assert group.apply_tick(s, feed, 100.0, "t") is False
    assert group.apply_tick(s, feed, 103.0, "t") is False
    assert group.apply_tick(s, feed, 105.5, "t") is True


def test_buttons_are_disabled_while_a_call_is_pending(group):
    rendered = str(group._button("Start", "start", group.GroupState.can_start).render())
    assert "pyOr(" in rendered and "pending_rx_state_" in rendered


def _disabled_expr(component):
    import re

    found = re.search(r"disabled:[^']*", str(component.render()))
    assert found is not None
    return found.group(0)


def test_estop_is_never_gated_by_another_calls_pending_state(group):
    S = group.GroupState
    assert "pending_rx_state_" not in _disabled_expr(
        group._button("E-stop", "estop", S.can_estop, gate_pending=False)
    )
    for label, name, var in (
        ("Start", "start", S.can_start),
        ("Stop", "stop", S.can_stop),
        ("Clear E-stop", "clear_estop", S.can_clear_estop),
    ):
        assert "pending_rx_state_" in _disabled_expr(group._button(label, name, var))
    # and the page wires E-stop that way, beside gated Start/Stop/Clear buttons
    import re

    text = str(group.group_page().render())
    gated = {}
    for m in re.finditer(r"RadixThemesButton', 'props': \[([^\]]*)\]", text):
        props = m.group(1)
        d = re.search(r"disabled:[^']*", props)
        if d:
            is_estop = group.REFLEX_MOTION_STOP_CLASS in props
            gated[is_estop] = gated.get(is_estop, []) + [
                "pending_rx_state_" in d.group(0)
            ]
    assert gated[True] == [False]
    assert gated[False] == [True, True, True]


class _FakeState(SimpleNamespace):
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _control_state():
    return _FakeState(
        router=SimpleNamespace(session=SimpleNamespace(client_token="t")),
        pending="",
        action_error="",
        _pending_at=0.0,
        _unconfirmed="",
    )


def _no_backend(monkeypatch, group):
    """Fail loudly if a control press touches the operator's RemoteBackend."""
    from helao.ui.shared.operator.orch_backend import RemoteBackend

    def boom(*a, **k):
        raise AssertionError("control built a RemoteBackend")

    monkeypatch.setattr(RemoteBackend, "__init__", boom)
    monkeypatch.setattr(group, "session_backend", boom)
    monkeypatch.setattr(group, "_backend", boom)


def test_control_goes_straight_to_the_orchestrator_without_a_remote_backend(
    group, monkeypatch
):
    import asyncio

    from helao.core.error import ErrorCodes

    _no_backend(monkeypatch, group)
    calls = []

    async def dispatch(key, host, port, endpoint, params_dict=None, json_dict=None):
        calls.append((key, host, port, endpoint, params_dict))
        return {}, ErrorCodes.none

    monkeypatch.setattr(group, "async_private_dispatcher", dispatch)
    for name in ("start", "stop", "estop", "clear_estop"):
        s = _control_state()
        asyncio.run(group.GroupState.control.fn(s, name))
        assert s.action_error == "" and s.pending == name
    assert calls == [
        ("ORCH", "127.0.0.1", 8001, "start", {}),
        ("ORCH", "127.0.0.1", 8001, "stop", {"reset_run_id": False}),
        ("ORCH", "127.0.0.1", 8001, "estop_orch", {}),
        ("ORCH", "127.0.0.1", 8001, "clear_estop", {}),
    ]


def test_control_error_sets_action_error_and_clears_pending(group, monkeypatch):
    import asyncio

    from helao.core.error import ErrorCodes

    _no_backend(monkeypatch, group)

    async def refused(*a, **k):
        return None, ErrorCodes.http

    monkeypatch.setattr(group, "async_private_dispatcher", refused)
    s = _control_state()
    asyncio.run(group.GroupState.control.fn(s, "start"))
    assert s.action_error == f"start failed: {ErrorCodes.http}" and s.pending == ""

    async def raises(*a, **k):
        raise OSError("link down")

    monkeypatch.setattr(group, "async_private_dispatcher", raises)
    asyncio.run(group.GroupState.control.fn(s, "stop"))
    assert s.action_error == "link down" and s.pending == ""
    group._CFG.clear()
    asyncio.run(group.GroupState.control.fn(s, "stop"))
    assert s.action_error == "cannot reach the orchestrator" and s.pending == ""


def test_an_unconfirmed_button_names_itself_after_the_timeout(group):
    feed = Feed()
    feed.push(frame(1, loop_state="stopped"), now=100.0)
    s = state()
    group.apply_tick(s, feed, 100.1, "t")
    s.pending, s._pending_at = "estop", 100.0
    group.apply_tick(s, feed, 100.0 + group.PENDING_TIMEOUT_S - 1, "t")
    assert s.pending == "estop" and s.action_error == ""  # still waiting
    group.apply_tick(s, feed, 100.0 + group.PENDING_TIMEOUT_S + 1, "t")
    assert s.pending == ""
    assert s.action_error.startswith("estop not confirmed by the orchestrator")
    s.pending, s._pending_at, s.action_error = "start", 200.0, ""
    group.apply_tick(s, feed, 200.0 + group.PENDING_TIMEOUT_S + 1, "t")
    assert s.action_error == "start not confirmed by the orchestrator"


def test_a_late_confirmation_clears_only_the_not_confirmed_message(group):
    feed = Feed()
    feed.push(frame(1, loop_state="stopped"), now=100.0)
    s = state()
    group.apply_tick(s, feed, 100.1, "t")
    s.pending, s._pending_at = "estop", 100.0
    group.apply_tick(s, feed, 100.0 + group.PENDING_TIMEOUT_S + 1, "t")
    assert s.action_error.startswith("estop not confirmed")
    # the effect arrives late: the message goes
    feed.push(frame(2, loop_state="estopped", orch_state="estopped"), now=120.0)
    group.apply_tick(s, feed, 120.1, "t")
    assert s.action_error == ""
    # an unrelated error is never cleared by a snapshot
    s.action_error, s._unconfirmed = "start failed: boom", ""
    group.apply_tick(s, feed, 121.0, "t")
    assert s.action_error == "start failed: boom"
    # nor is one that replaced the message
    s.action_error, s._unconfirmed = "link down", "estop"
    feed.push(frame(3, loop_state="estopped", orch_state="estopped"), now=122.0)
    group.apply_tick(s, feed, 122.1, "t")
    assert s.action_error == "link down"


def test_an_unconfirmed_message_stays_while_the_snapshot_still_disagrees(group):
    feed = Feed()
    feed.push(frame(1, loop_state="stopped"), now=100.0)
    s = state()
    group.apply_tick(s, feed, 100.1, "t")
    s.pending, s._pending_at = "estop", 100.0
    group.apply_tick(s, feed, 100.0 + group.PENDING_TIMEOUT_S + 1, "t")
    feed.push(frame(2, loop_state="stopped"), now=130.0)
    group.apply_tick(s, feed, 130.1, "t")
    assert s.action_error.startswith("estop not confirmed")


def test_a_confirmed_button_clears_pending_without_an_error(group):
    feed = Feed()
    feed.push(frame(1, loop_state="started"), now=100.0)
    s = state()
    group.apply_tick(s, feed, 100.1, "t")
    s.pending, s._pending_at = "start", 100.0
    group.apply_tick(s, feed, 100.0 + group.PENDING_TIMEOUT_S + 1, "t")
    assert s.pending == "" and s.action_error == ""


def test_ingest_lifespan_always_stops_the_registry():
    import inspect

    from helao.ui.reflex import app

    src = inspect.getsource(app.build_app)
    assert "await stop_feed()" in src
    tail = src[src.index("await stop_feed()") :]
    assert tail.index("finally") < tail.index("await registry.stop()")


def test_a_fresh_group_state_has_estop_enabled(group):
    """The operator can E-STOP before any frame has arrived."""
    assert group.GroupState.__fields__["can_estop"].default is True


def test_estop_flag_is_available_in_every_state_but_estopped(group):
    flags = group.button_flags
    for snap in (
        {},
        {"loop_state": "stopped", "orch_state": "idle"},
        {"loop_state": "started", "orch_state": "busy"},
        {"loop_state": "error", "orch_state": "error"},
        {"loop_state": "stopped", "closing_out": True},
    ):
        assert flags(snap, lost=False)["can_estop"] is True, snap
        assert flags(snap, lost=True)["can_estop"] is True, snap  # stream lost
    est = {"loop_state": "estopped", "orch_state": "estopped"}
    assert flags(est, lost=False)["can_estop"] is False
    assert flags(est, lost=False)["can_clear_estop"] is True


# ---- return pulse: queued per edge ------------------------------------------


def _drawn(group, s, now):
    """Points drawn per pulse trace for edge SIM at ``now``, via the real render."""
    marks, _ = group.graph_marks(s._snap[0], s._pulses, now, "ORCH", False)
    return {
        m["name"]: len(m["x"]) for m in marks if m.get("name", "").startswith("pulse:")
    }


def test_finish_makes_a_reverse_pulse_drawn_over_many_frames(group):
    feed = Feed()
    feed.push(frame(1))
    s = state()
    group.apply_tick(s, feed, 100.0, "t")
    feed.push(frame(2, [FINISH]))
    group.apply_tick(s, feed, 100.0, "t")
    assert [p[1] for p in s._pulses] == ["rev"]
    t, seen = 100.0, 0
    while s._pulses:
        t += 1 / 60
        group.apply_tick(s, feed, t, "t")
        seen += (
            _drawn(group, s, t)["pulse:triangle"]
            + _drawn(group, s, t)["pulse:triangle_down"]
        )
    assert seen >= 60  # 1.2 s at 60 Hz, never a couple of frames


def test_dispatch_and_finish_in_one_frame_run_one_after_the_other(group):
    feed = Feed()
    feed.push(frame(1))
    s = state()
    group.apply_tick(s, feed, 100.0, "t")
    feed.push(frame(2, [DISPATCH, FINISH]))
    group.apply_tick(s, feed, 100.0, "t")
    (_, d1, t1, dur1, _), (_, d2, t2, _, _) = s._pulses
    assert (d1, d2) == ("fwd", "rev")
    assert t2 == pytest.approx(t1 + dur1)  # return leg starts as the outbound ends
    # first half of the window: only the outbound is drawn; second: only the return
    t, seen = 100.0, []
    while t < 100.0 + group.PULSE_S * 1.5:
        t += 1 / 60
        group.apply_tick(s, feed, t, "t")
        d = _drawn(group, s, t)
        seen.append((t, d["pulse:triangle"], d["pulse:triangle_down"]))
    assert all(rev == 0 for t, _, rev in seen if t < 100.0 + group.PULSE_S - 0.03)
    assert all(fwd == 0 for t, fwd, _ in seen if t > 100.0 + group.PULSE_S + 0.03)
    assert any(rev for _, _, rev in seen)


# ---- hover and rebuild-free status changes -----------------------------------


def _two_server_frame(seq, status):
    f = frame(seq)
    f["servers"] = [
        {"key": "SIM", "status": status, "active_action": None},
        {"key": "CPSIM", "status": "idle", "active_action": None},
    ]
    return f


def _hover(group, s, payload):
    s.router = SimpleNamespace(session=SimpleNamespace(client_token="t"))
    group.GroupState.hover_node.fn(s, payload)


def test_hovering_a_node_redraws_it_larger_in_its_own_colour_then_clears(
    group, monkeypatch
):
    monkeypatch.setattr(group, "stream_lost", lambda feed, now: False)
    feed = Feed()
    feed.push(_two_server_frame(1, "busy"))
    s = state()
    group.apply_tick(s, feed, 100.0, "t")
    layout, v = s.graph_layout, s._version
    busy = group.GROUP_STATE_COLORS["busy"]
    idle = group.GROUP_STATE_COLORS["idle"]
    _hover(group, s, {"trace": f"nodes:44:{busy}", "index": 0})  # SIM, busy
    assert s._hovered == "SIM"
    _hover(group, s, {"trace": f"nodes:44:{idle}", "index": 1})  # CPSIM (ORCH is 0)
    assert s._hovered == "CPSIM"
    _hover(group, s, {"trace": f"nodes:44:{busy}", "index": 0})
    assert s._hovered == "SIM" and s._version == v + 3  # one redraw per change
    assert s.graph_layout == layout  # point columns only: no chart rebuild
    marks, _ = group.graph_marks(s._snap[0], (), 100.0, "ORCH", False, "SIM")
    hov = next(m for m in marks if m.get("name") == f"hovered:{busy}")
    assert hov["colors"] == [busy]
    assert hov["size"] == group.HOVER_PX > group.NODE_PX
    _hover(group, s, {"trace": "", "index": -1})  # pointer left
    assert s._hovered == "" and s.graph_layout == layout
    _hover(group, s, {"trace": "pulse:triangle", "index": 0})  # not a node
    assert s._hovered == ""


def test_a_status_change_leaves_the_graph_layout_token_unchanged(group):
    feed = Feed()
    feed.push(_two_server_frame(1, "idle"))
    s = state()
    group.apply_tick(s, feed, 100.0, "t")
    idle = s.graph_layout
    for status in ("busy", "error", "estopped", "mystery"):
        feed.push(_two_server_frame(2, status))
        group.apply_tick(s, feed, 101.0, "t")
        assert s.graph_layout == idle, status
