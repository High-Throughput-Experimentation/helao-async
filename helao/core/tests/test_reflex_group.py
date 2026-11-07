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
        _exp_edges=(),
        _act_edges=(),
        _selected=(),
        _exp_ords=(),
        _act_ords=(),
        _scopes=(),
        _first_at=0.0,
        _hover_slot=(-1, -1),
        _pulse_seq=0,
        graph_pulses={},
        graph_nodes={"items": []},
        exp_hover="",
        act_hover="",
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
    assert len(s._pulses) == 1 and s.tick_ms == group.SLOW_MS
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
    names = ("_snap", "_pulses", "_exp_slots", "_act_slots", "_selected")
    names += ("_exp_edges", "_act_edges")
    for name in names:
        assert isinstance(getattr(s, name), tuple), name
    for name in names:
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


def test_strips_are_60_px_tall_and_ask_xy_for_a_fixed_height(group, monkeypatch):
    assert group.STRIP_H == 60
    seen = []
    real = group.plots.marks_chart

    def spy(*a, **kw):
        seen.append((kw["panel_id"], kw.get("height_px")))
        return real(*a, **kw)

    monkeypatch.setattr(group.plots, "marks_chart", spy)
    s = state()
    group._render_strips(s, {}, 100.0, "tok")
    assert seen == [("group-exp-tok", 60), ("group-act-tok", 60)]
    html = str(group.group_page())
    assert html.count('height:"60px"') == 2 and 'height:"120px"' not in html


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
    marks = graph_marks(snap, "ORCH", False)
    by_colour: dict = {}
    for m in marks:
        if m.get("name", "").startswith("nodes:"):
            for c in m["colors"]:
                by_colour[c] = by_colour.get(c, 0) + 1
    assert by_colour == {GROUP_STATE_COLORS["busy"]: 2, GROUP_STATE_COLORS["idle"]: 1}
    assert "X (weird)" in [m["value"] for m in marks if m["kind"] == "text"]
    lost = graph_marks(snap, "ORCH", True)
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


def test_a_live_pulse_costs_no_extra_ticks_or_renders(group, monkeypatch):
    """The 60 Hz tick is gone: pulses move in the browser, so nothing here is timed."""
    assert not hasattr(group, "FAST_MS")
    feed = Feed()
    feed.push(frame(1))
    s = state()
    group.apply_tick(s, feed, 100.0, "t")
    feed.push(frame(2, [DISPATCH]))
    group.apply_tick(s, feed, 100.1, "t")
    assert s.tick_ms == group.SLOW_MS and s._pulses
    built = []
    real = group.plots.marks_chart
    monkeypatch.setattr(
        group.plots,
        "marks_chart",
        lambda *a, **k: built.append(k["panel_id"]) or real(*a, **k),
    )
    for t in (100.116, 100.2, 100.4):  # no frame, inside SLOW_MS: nothing redrawn
        group.apply_tick(s, feed, t, "t")
        assert s.tick_ms == group.SLOW_MS
    assert built == []
    group.apply_tick(s, feed, 100.7, "t")  # slow cadence due
    assert sorted(built) == ["group-act-t", "group-exp-t", "group-graph-t"]


def test_graph_marks_carry_no_pulse_traces_and_no_time(group):
    snap = frame(1, loop_state="started")
    marks = group.graph_marks(snap, "ORCH", False)
    assert not [m for m in marks if m.get("name", "").startswith("pulse")]
    assert marks == group.graph_marks(snap, "ORCH", False)  # a pure function


# ---- pulse descriptors: sent once, in travel order ---------------------------


def _tick_frames(group, *events_per_frame, t=100.0):
    feed = Feed()
    feed.push(frame(1))
    s = state()
    group.apply_tick(s, feed, t, "t")
    for i, evs in enumerate(events_per_frame, 2):
        feed.push(frame(i, evs))
        group.apply_tick(s, feed, t, "t")
    return feed, s


def test_each_event_is_one_descriptor_published_once(group):
    feed, s = _tick_frames(group, [FINISH])
    batch = s.graph_pulses
    assert [it["dir"] for it in batch["items"]] == ["rev"]
    it = batch["items"][0]
    assert set(it) == {"id", "dir", "start_in", "dur", "color", "path"}
    assert it["dur"] == group.PULSE_S and it["start_in"] == pytest.approx(0.0)
    assert it["color"] == group.GROUP_STATE_COLORS["done"]
    assert batch["view"] == group.PULSE_VIEW and batch["seq"] == 1
    # later ticks, with or without frames, never re-publish it
    for t in (100.016, 100.032, 100.6, 101.2):
        group.apply_tick(s, feed, t, "t")
        assert s.graph_pulses is batch
    feed.push(frame(3, [DISPATCH]))
    group.apply_tick(s, feed, 101.3, "t")
    assert [x["dir"] for x in s.graph_pulses["items"]] == ["fwd"]
    assert s.graph_pulses["seq"] == 2


def test_descriptor_path_is_the_edge_curve_in_travel_order(group):
    snap = frame(1)
    g = group.build_graph(snap, "ORCH", False)
    curve = g.edge_path("SIM")  # orch -> server, data units
    fwd = group.pulse_items(
        snap, [("SIM", "fwd", 100.0, 1.2, "#111")], 100.0, "ORCH", False
    )
    rev = group.pulse_items(
        snap, [("SIM", "rev", 100.0, 1.2, "#111")], 100.0, "ORCH", False
    )
    assert fwd[0]["path"][0] == pytest.approx(list(curve[0]), abs=1e-4)
    assert rev[0]["path"][0] == pytest.approx(list(curve[-1]), abs=1e-4)
    assert rev[0]["path"] == fwd[0]["path"][::-1]
    assert len(fwd[0]["path"]) == 24
    # an edge that left the graph yields nothing
    assert (
        group.pulse_items(
            snap, [("GONE", "fwd", 100.0, 1.2, "#111")], 100.0, "ORCH", False
        )
        == []
    )


def test_dispatch_and_finish_in_one_frame_start_one_after_the_other(group):
    _, s = _tick_frames(group, [DISPATCH, FINISH])
    out, back = s.graph_pulses["items"]
    assert (out["dir"], back["dir"]) == ("fwd", "rev")
    assert out["start_in"] == pytest.approx(0.0)
    # the return leg starts as the outbound ends (start times are honoured)
    assert back["start_in"] == pytest.approx(out["start_in"] + out["dur"])
    assert out["id"] != back["id"]


def test_pulse_bounding_is_unchanged_by_browser_animation(group):
    """A 100-event burst still yields a handful of descriptors, all soon."""
    _, s = _tick_frames(group, [DISPATCH, FINISH] * 50)
    items = s.graph_pulses["items"]
    assert 0 < len(items) <= 3
    assert max(it["start_in"] for it in items) <= 2 * group.PULSE_S
    assert len(s._pulses) == len(items)


def test_expired_pulses_leave_the_bounding_state(group):
    feed, s = _tick_frames(group, [FINISH])
    assert len(s._pulses) == 1
    group.apply_tick(s, feed, 100.0 + group.PULSE_S + 0.1, "t")
    assert s._pulses == ()


def test_a_pulse_leaves_the_graph_layout_token_and_payload_alone(group):
    feed = Feed()
    feed.push(frame(1))
    s = state()
    group.apply_tick(s, feed, 100.0, "t")
    layout, spec = s.graph_layout, s.graph_spec
    feed.push(frame(2, [DISPATCH]))
    group.apply_tick(s, feed, 100.1, "t")
    assert s.graph_layout == layout
    assert [t["name"] for t in s.graph_spec["traces"]] == [
        t["name"] for t in spec["traces"]
    ]


# ---- hover and rebuild-free status changes -----------------------------------


def _two_server_frame(seq, status):
    f = frame(seq)
    f["servers"] = [
        {"key": "SIM", "status": status, "active_action": None},
        {"key": "CPSIM", "status": "idle", "active_action": None},
    ]
    return f


def _items(s):
    return {it["key"]: it for it in s.graph_nodes["items"]}


def test_node_descriptors_carry_key_position_fill_and_radius(group, monkeypatch):
    monkeypatch.setattr(group, "stream_lost", lambda feed, now: False)
    feed = Feed()
    feed.push(_two_server_frame(1, "busy"))
    s = state()
    group.apply_tick(s, feed, 100.0, "t")
    got = _items(s)
    assert set(got) == {"ORCH", "SIM", "CPSIM"}
    pos = group.group_layout("ORCH", ["SIM", "CPSIM"])
    for key, it in got.items():
        assert (it["x"], it["y"]) == pytest.approx(pos[key], abs=1e-5)
        assert it["r"] == group.NODE_PX / 2
    assert got["SIM"]["color"] == group.GROUP_STATE_COLORS["busy"]
    assert got["CPSIM"]["color"] == group.GROUP_STATE_COLORS["idle"]
    assert s.graph_nodes["hover_r"] == group.HOVER_PX / 2 > group.NODE_PX / 2
    assert s.graph_nodes["view"] == group.PULSE_VIEW


def test_descriptors_change_with_a_status_colour_and_not_otherwise(group, monkeypatch):
    monkeypatch.setattr(group, "stream_lost", lambda feed, now: False)
    feed = Feed()
    feed.push(_two_server_frame(1, "idle"))
    s = state()
    group.apply_tick(s, feed, 100.0, "t")
    first = s.graph_nodes
    feed.push(_two_server_frame(2, "idle"))  # a new frame, nothing changed
    group.apply_tick(s, feed, 101.0, "t")
    assert s.graph_nodes is first  # the very same value: nothing is re-sent
    group.apply_tick(s, feed, 102.0, "t")  # a slow tick with no frame
    assert s.graph_nodes is first
    feed.push(_two_server_frame(3, "busy"))
    group.apply_tick(s, feed, 103.0, "t")
    assert s.graph_nodes is not first
    assert _items(s)["SIM"]["color"] == group.GROUP_STATE_COLORS["busy"]
    assert _items(s)["CPSIM"] == {it["key"]: it for it in first["items"]}["CPSIM"]


def test_the_graph_has_no_hovered_traces_and_no_server_hover_path(group):
    marks = group.graph_marks(_two_server_frame(1, "busy"), "ORCH", False)
    assert not any(m.get("name", "").startswith("hovered") for m in marks)
    assert not hasattr(group.GroupState, "hover_node")
    assert "_hovered" not in vars(group.GroupState)
    s = state()
    group._render_graph(s, _two_server_frame(1, "busy"), False, "t")
    assert "hover" not in s.graph_spec["interaction"]  # xy reports nothing on hover
    assert "mark_style" not in s.graph_spec


def test_the_graph_chart_is_opted_in_to_nodes_and_not_to_server_hover(group):
    import inspect

    src = inspect.getsource(group)
    assert "nodes=S.graph_nodes" in src and "on_hover=S.hover_node" not in src


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


# ---- bursts stay bounded -----------------------------------------------------


def test_a_burst_of_events_on_one_edge_stays_bounded(group):
    pulses = []
    for i in range(100):
        pulses = group.queue_pulse(
            pulses, ("SIM", "fwd" if i % 2 else "rev", 50.0, group.PULSE_S, "c")
        )
    assert len(pulses) <= 3  # the running one plus one pending per direction
    assert max(p[2] for p in pulses) <= 50.0 + 2 * group.PULSE_S


def test_a_catch_up_batch_pulses_only_the_last_second():
    from helao.ui.reflex.group import recent_events

    old = {"kind": "dispatch", "server": "SIM", "t": 10.0}
    new = {"kind": "finish", "server": "SIM", "t": 500.0}
    untimed = {"kind": "dispatch", "server": "SIM"}
    got = recent_events([{"events": [old]}, {"events": [new, untimed]}])
    assert got == [new, untimed]


def test_a_tick_with_many_old_frames_starts_a_bounded_number_of_pulses(group):
    feed = Feed()
    feed.push(frame(1))
    s = state()
    group.apply_tick(s, feed, 100.0, "t")
    for i in range(100):
        feed.push(frame(2 + i, [{**(DISPATCH if i % 2 else FINISH), "t": 1000.0 + i}]))
    group.apply_tick(s, feed, 100.0, "t")
    assert 1 <= len(s._pulses) <= 3
    assert max(p[2] for p in s._pulses) <= 100.0 + 2 * group.PULSE_S


# ---- node traces: every node is in exactly one trace, and xy repaints it ------

SERVER_STATUSES = ("idle", "busy", "error", "estop", "unreachable", "weird")
ORCH_STATES = ("idle", "busy", "error", "estopped", "closing out", "")


def _real_node_points(marks):
    """node key -> number of traces drawing it on-domain."""
    from helao.ui.reflex import plots

    n: dict = {}
    for m in marks:
        if m.get("name", "").startswith("nodes:"):
            key = m["name"].split(":")[1]
            n[key] = n.get(key, 0) + sum(1 for x in m["x"] if x != plots.PLACEHOLDER_XY)
    return n


def test_every_status_places_each_node_in_exactly_one_node_trace(group):
    import itertools

    for orch, a, b in itertools.product(ORCH_STATES, SERVER_STATUSES, SERVER_STATUSES):
        snap = {
            "orch_state": orch,
            "servers": [{"key": "SIM", "status": a}, {"key": "CPSIM", "status": b}],
        }
        for lost in (False, True):
            marks = group.graph_marks(snap, "ORCH", lost)
            assert _real_node_points(marks) == {"ORCH": 1, "SIM": 1, "CPSIM": 1}, (
                orch,
                a,
                b,
                lost,
            )


def _xy_gpu_after(prev, marks, spec):
    """What xy 0.0.8's in-place append leaves on the GPU after ``spec``.

    ``_appendTraceInPlace`` runs only when a scatter trace keeps or grows its
    length and its x/y column offset+scale; it then writes just the points past
    the old length. Anything else rebuilds the trace from the new columns.
    """
    cols, gpu = spec["columns"], {}
    scatters = [t for t in spec["traces"] if t["kind"] == "scatter"]
    for t, m in zip(scatters, [m for m in marks if m["kind"] == "scatter"]):
        new = {
            "x": list(m["x"]) or [-1e6],
            "y": list(m["y"]) or [-1e6],
            "c": list(m["colors"]) or ["pad"],
            "sig": tuple(
                (cols[t[a]]["offset"], cols[t[a]]["scale"]) for a in ("x", "y")
            ),
        }
        old = (prev or {}).get(m["name"])
        if old and len(new["x"]) >= len(old["x"]) and old["sig"] == new["sig"]:
            k = len(old["x"])
            gpu[m["name"]] = {
                **new,
                **{f: old[f][:k] + new[f][k:] for f in ("x", "y", "c")},
            }
        else:
            gpu[m["name"]] = new
    return gpu


def test_xy_repaints_every_node_after_any_status_change(group):
    """A node moving between colour traces must never leave a stale GPU copy.

    Regression: with one trace per colour holding several nodes, the orch going
    busy -> idle while every server was idle grew the idle trace at its FRONT;
    xy wrote only the tail, so the ORCH node vanished (its label stayed).
    """
    import itertools

    from helao.ui.reflex import plots

    def render(orch, sts):
        snap = {
            "orch_state": orch,
            "servers": [
                {"key": k, "status": s} for k, s in zip(("SIM", "CP", "GP"), sts)
            ],
        }
        marks = group.graph_marks(snap, "ORCH", False)
        p = plots.marks_chart(
            marks, x_domain=(-1, 1), y_domain=(-1, 1), panel_id="t", version=1
        )
        return marks, p.spec

    states = [
        (o, s)
        for o in ("idle", "busy", "error")
        for s in itertools.product(("idle", "busy", "error"), repeat=3)
    ]
    rendered = {st: render(*st) for st in states}
    for a, b in itertools.permutations(states, 2):
        gpu = _xy_gpu_after(_xy_gpu_after(None, *rendered[a]), *rendered[b])
        want = _xy_gpu_after(None, *rendered[b])
        for name in gpu:
            if name.startswith("nodes:"):
                assert gpu[name]["x"] == want[name]["x"], (a, b, name)
                assert gpu[name]["c"] == want[name]["c"], (a, b, name)


# ---- timeline rules in the page ---------------------------------------------


def test_action_scope_follows_the_experiment_the_act_strip_shows(group):
    base = {"seq": {"uuid": "S"}, "experiments": []}
    assert group.selection_scope({**base, "act_exp": "E1"}, "action") == ("S", "E1")
    assert group.selection_scope({**base, "act_exp": None}, "action") == ("S", None)
    # an orchestrator that predates act_exp: the active experiment's ordinal
    old = {**base, "experiments": [_exp("e", "active", uuid="u")]}
    assert group.selection_scope(old, "action") == ("S", 0)
    # the EXP scope is the sequence only
    assert group.selection_scope({**base, "act_exp": "E1"}, "experiment") == ("S",)


def test_act_selection_survives_idle_and_clears_when_a_new_experiment_starts(group):
    s = state()
    acts = [{"uuid": f"a{i}", "name": "act", "state": "done"} for i in range(3)]
    seq = {"uuid": "S"}
    done = [_exp("e1", "done", uuid="u1")]
    running = frame(1, seq=seq, experiments=done, actions=acts, act_exp="u1")
    group._render_strips(s, running, 100.0, "t")
    _click(group, s, "action", 1, running)
    # still the last experiment, nothing active: selection stays
    idle = frame(2, seq=seq, experiments=done, actions=acts, act_exp="u1")
    group._render_strips(s, idle, 101.0, "t")
    assert s._selected != () and s.info_note == ""
    # a new experiment starts: ACT shows it, the selection is gone
    new = frame(
        3,
        seq=seq,
        experiments=done + [_exp("e2", "active", uuid="u2")],
        actions=[],
        act_exp="u2",
    )
    group._render_strips(s, new, 102.0, "t")
    assert s._selected == () and s.info_note == group.SELECTION_GONE


def test_exp_selection_clears_only_when_the_sequence_changes(group):
    s = state()
    rows = [_exp("a", "done", uuid="ua"), _exp("b", "done", uuid="ub")]
    one = frame(1, seq={"uuid": "S1"}, experiments=rows, n_done=0)
    group._render_strips(s, one, 100.0, "t")
    _click(group, s, "experiment", 1, one)
    # the orchestrator goes idle on the same sequence: kept
    group._render_strips(s, {**one, "seq_no": 2}, 101.0, "t")
    assert s._selected != ()
    two = frame(3, seq={"uuid": "S2"}, experiments=[], n_done=0)
    group._render_strips(s, two, 102.0, "t")
    assert s._selected == ()


# ---- header rows: current experiment and action --------------------------------


def _act(name, state, t=None, uuid=None):
    return {"uuid": uuid or name, "name": name, "state": state, "t_start": t}


def test_current_experiment_is_the_active_one_else_the_last_finished(group):
    rows = [_exp("a", "done", uuid="ua"), _exp("b", "active", uuid="ub")]
    rows += [_exp("c", "queued", qidx=0)]
    assert group.current_experiment({"experiments": rows})["uuid"] == "ub"
    idle = [_exp("a", "done", uuid="ua"), _exp("b", "error", uuid="ub")]
    assert group.current_experiment({"experiments": idle})["uuid"] == "ub"
    assert group.current_experiment({"experiments": []}) is None
    only_queued = [_exp("c", "queued", qidx=0)]
    assert group.current_experiment({"experiments": only_queued}) is None


def test_current_action_is_the_most_recently_started_active_else_last_finished(group):
    acts = [
        _act("old", "active", 10.0),
        _act("new", "active", 30.0),
        _act("mid", "active", 20.0),
        _act("q", "queued"),
    ]
    assert group.current_action({"actions": acts})["name"] == "new"
    done = [_act("a", "done", 1.0), _act("b", "error", 2.0), _act("q", "queued")]
    assert group.current_action({"actions": done})["name"] == "b"
    assert group.current_action({"actions": [_act("q", "queued")]}) is None
    assert group.current_action({}) is None


def test_header_fields_carry_current_experiment_and_action_rows(group):
    snap = {
        "experiments": [
            {**_exp("e", "active", uuid="0123456789abcdef"), "t_start": None}
        ],
        "actions": [
            _act("acquire", "active", 1_700_000_000.0, uuid="fedcba9876543210")
        ],
    }
    h = group.header_fields(snap)
    assert (h["exp_name"], h["exp_uuid"], h["exp_uuid_short"]) == (
        "scan",
        "0123456789abcdef",
        "89abcdef",
    )
    assert h["exp_state"] == "active" and h["exp_started"] == ""
    assert (h["act_name"], h["act_uuid_short"], h["act_state"]) == (
        "acquire",
        "76543210",
        "active",
    )
    assert h["act_started"].startswith("2023-11-1")
    empty = group.header_fields({})
    assert empty["exp_name"] == "" and empty["act_name"] == ""
    assert empty["exp_uuid_short"] == "" and empty["act_uuid"] == ""


def test_header_rows_are_on_the_page_below_the_sequence_line(group):
    import re

    html = str(group.group_page())
    seq, exp, act = (html.find(f'"{t}"') for t in ("SEQ", "EXP", "ACT"))
    assert 0 <= seq < exp < act
    for var in ("exp_uuid", "act_uuid"):
        assert re.search(rf"set_clipboard.*{var}", html, re.S) or var in html


# ---- strip hover: a line under the strip, anywhere over a segment ------------


def _hover_state():
    s = state()
    s.exp_hover = s.act_hover = ""
    s.router = SimpleNamespace(session=SimpleNamespace(client_token="t"))
    return s


def test_hit_grid_answers_every_segment_and_maps_back_to_its_slot():
    from helao.ui.reflex.group import STRIP_H
    from helao.ui.reflex.timeline_strip import (
        HIT_COLS,
        HIT_PX,
        HIT_ROWS,
        hit_slot,
        strip_marks,
    )

    for n_items in (1, 3, 30, 72):
        items = [
            {"name": f"e{i}", "state": "done", "uuid": f"u{i}"} for i in range(n_items)
        ]
        marks, slots, edges = strip_marks(
            items, n_before=0, n_after=0, now=1.0, width_px=720
        )
        hit = next(m for m in marks if m.get("name") == "hit")
        assert len(hit["x"]) == HIT_COLS * HIT_ROWS == len(hit["y"])
        # each grid point sits in the slot hit_slot names for it
        for idx, x in enumerate(hit["x"]):
            assert hit_slot(idx, edges) == next(
                i for i in range(len(slots)) if edges[i] <= x < edges[i + 1]
            )
        # every slot has a point, and the points are never further apart than xy's
        # 12 px pick radius allows (720 px / HIT_COLS columns)
        reach = {hit_slot(i, edges) for i in range(HIT_COLS * HIT_ROWS)}
        wide = {
            i for i in range(len(slots)) if edges[i + 1] - edges[i] >= 720 / HIT_COLS
        }
        assert wide <= reach
        # xy picks pixel-exact on a drawn marker, so the squares must tile the plot
        assert hit["size"] == HIT_PX and hit["symbol"] == "square"
        assert HIT_PX >= 704 / HIT_COLS and HIT_PX >= (STRIP_H - 16) / HIT_ROWS
    assert hit_slot(-1, edges) is None
    assert hit_slot(HIT_COLS * HIT_ROWS, edges) is None


def test_item_tooltip_formats(group):
    from datetime import date, datetime

    from helao.ui.reflex.timeline_strip import item_tooltip

    today = date.today()
    t0 = datetime.combine(today, datetime.min.time()).timestamp() + 3600 * 10
    hms = lambda t: datetime.fromtimestamp(t).strftime("%H:%M:%S")
    done = {"name": "scan", "state": "done", "t_start": t0, "t_end": t0 + 65}
    assert item_tooltip(done, t0 + 99, today) == (
        f"scan: start {hms(t0)}, end {hms(t0 + 65)}"
    )
    run = {"name": "scan", "state": "active", "t_start": t0, "t_end": None}
    assert item_tooltip(run, t0 + 65, today) == (
        f"scan: start {hms(t0)}, running (1:05)"
    )
    assert item_tooltip({"name": "scan", "state": "queued"}, 0, today) == "scan: queued"
    no_end = {"name": "x", "state": "done", "t_start": t0, "t_end": None}
    assert item_tooltip(no_end, 0, today).endswith("end —")
    assert item_tooltip(None, 0, today) == ""


def test_hovering_a_strip_sets_only_its_line_and_never_redraws(group):
    s = state()
    exp = [
        {"name": "alpha", "state": "done", "uuid": "u0", "t_start": 1.0, "t_end": 2.0},
        {"name": "beta", "state": "queued", "uuid": None, "qidx": 0},
    ]
    snap = frame(1, seq={"uuid": "S"}, experiments=exp)
    group._render_strips(s, snap, 100.0, "t")
    layout, spec, url = s.exp_layout, s.exp_spec, s.exp_url
    hover = group.GroupState._hover_strip
    col = 40  # right half of the 52-column grid: slot 1
    hover(s, 0, {"trace": "hit", "index": col})
    assert s.exp_hover.startswith("beta: queued") and s.act_hover == ""
    hover(s, 0, {"trace": "hit", "index": 1})
    assert s.exp_hover.startswith("alpha: start")
    hover(s, 1, {"trace": "hit", "index": 3})  # ACT has no slots: nothing to say
    assert s.act_hover == ""
    hover(s, 0, {"trace": "", "index": -1})  # pointer left
    assert s.exp_hover == ""
    # no redraw: the chart payload is untouched by hovering
    assert (s.exp_layout, s.exp_spec, s.exp_url) == (layout, spec, url)
    # another trace (xy may report one) is not a hover on a segment
    hover(s, 0, {"trace": "hit", "index": 1})
    hover(s, 0, {"trace": "progress", "index": 0})
    assert s.exp_hover == ""


def test_the_hover_line_keeps_ticking_while_the_pointer_stays(group, monkeypatch):
    monkeypatch.setattr(group.time, "time", lambda: 105.0)
    s = state()
    run = [{"name": "alpha", "state": "active", "uuid": "u0", "t_start": 100.0}]
    snap = frame(1, seq={"uuid": "S"}, experiments=run)
    group._render_strips(s, snap, 105.0, "t")
    group.GroupState._hover_strip(s, 0, {"trace": "hit", "index": 0})
    assert "running (0:05)" in s.exp_hover
    group._render_strips(s, snap, 112.0, "t")
    assert "running (0:12)" in s.exp_hover


def test_strips_ask_for_hover_events_and_clicks(group):
    s = state()
    group._render_strips(s, frame(1, seq={"uuid": "S"}), 100.0, "t")
    for spec in (s.exp_spec, s.act_spec):
        assert spec["interaction"].get("hover") and spec["interaction"].get("click")
        # xy's invisible toolbar would swallow the pointer over a strip's corner
        assert spec.get("show_modebar") is False


def test_every_slot_of_the_largest_unsqueezed_exp_strip_is_reachable():
    from helao.ui.reflex.timeline_strip import HIT_COLS, HIT_ROWS, hit_slot

    for n in (5, 6):  # up to PLOT_W / MIN_KEY_PX equal slots
        edges = tuple(i * 704.0 / n for i in range(n)) + (704.0,)
        hit = {hit_slot(i, edges) for i in range(HIT_COLS * HIT_ROWS)}
        assert hit == set(range(n)), sorted(set(range(n)) - hit)


def test_strip_labels_are_boxed_for_the_plot_width_not_the_host_width(group):
    s = state()
    exp = [
        {"uuid": str(i), "name": "n", "state": "done", "t_start": 1.0, "t_end": 2.0}
        for i in range(4)
    ]
    marks = []
    real = group.plots.marks_chart
    group.plots.marks_chart = lambda m, **kw: marks.append(m) or real(m, **kw)
    try:
        group._render_strips(s, {"experiments": exp, "actions": exp}, 100.0, "tok")
    finally:
        group.plots.marks_chart = real
    for strip in marks:  # EXP and ACT both box for the plot width
        boxes = {m["max_px"] for m in strip if m["kind"] == "text"}
        assert boxes == {704 / 4 - 8}


def test_strip_hover_text_sits_beside_its_header_and_nothing_follows_the_act_strip(
    group,
):
    html = str(group.group_page())
    for tag, var in (("EXP", "exp"), ("ACT", "act")):
        head = html.index(f'size:"1",weight:"bold"}},"{tag}")')
        between = html[head : html.index("XYChart", head)]
        assert f"{var}_hover_rx_state_" in between
    tail = html[html.rindex("act_spec_rx_state_") :]
    assert "act_hover" not in tail[: tail.index("RadixThemesCard")]
    assert tail[: tail.index("RadixThemesCard")].count("RadixThemesText") == 0


def test_header_rows_are_one_size_smaller_and_buttons_stay_small(group):
    html = str(group.group_page())
    head = html[: html.index("XYChart")]
    for label in ('"SEQ"', '"EXP"', '"ACT"'):
        at = head.index(label)
        assert 'size:"2"' in head[head.rindex("RadixThemesText", 0, at) : at]
    assert 'size:"2"},"idle' in head or "idle — no active sequence" in head
    rows = head[head.index("no active sequence") - 300 : head.index("loop: ")]
    # 22 texts: 20 at size 2, plus the two "(state)" texts that stay at size 1
    assert rows.count("RadixThemesText") == 22 and rows.count('size:"2"') == 20


def test_graph_and_each_strip_sit_in_their_own_card_beside_info(group):
    import re

    html = str(group.group_page())
    cards = [m.start() for m in re.finditer(r"jsx\(RadixThemesCard", html)]
    assert len(cards) == 4  # graph, EXP, ACT, INFO
    at = lambda s, start=0: html.index(s, start)
    assert cards[0] < at("graph_spec_rx") < cards[1]
    # the strip's header line is inside its card, ahead of its chart
    assert cards[1] < at('"EXP")', cards[1]) < at("exp_spec_rx") < cards[2]
    assert cards[2] < at('"ACT")', cards[2]) < at("act_spec_rx") < cards[3]
    assert at('"INFO")') > cards[3]


def test_fetched_info_never_shows_a_shifted_queue_item(group):
    """A stale qidx returns the neighbour: never show it as the click."""
    clicked = {"uuid": None, "qidx": 3, "name": "exp_b"}
    moved = group.fetched_info("experiment", clicked, {"experiment_name": "exp_c"})
    assert moved == (None, group.QUEUE_MOVED)
    ok = {"experiment_name": "exp_b"}
    assert group.fetched_info("experiment", clicked, ok) == (ok, "")
    # empty (out of range, unreachable, raised) is "not found", never "moved"
    for empty in ({}, None):
        assert group.fetched_info("experiment", clicked, empty) == (
            None,
            group.NOT_FOUND,
        )
    # by-uuid fetches are exact
    act = {"action_name": "other"}
    assert group.fetched_info("action", {"uuid": "u1", "qidx": None}, act) == (
        act,
        "",
    )
