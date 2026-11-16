"""/group with several orchestrators and runners (spec: Page side)."""

import asyncio
from types import SimpleNamespace

import pytest

from helao.ui.reflex import group
from helao.ui.reflex.netgraph import group_layout
from helao.ui.reflex.runner_registry import RunnerRegistry

CFG = {
    "servers": {
        "SIM": {"host": "h", "port": 1, "group": "action"},
        "ORCH": {"host": "h", "port": 2, "group": "orchestrator"},
        "ORCH2": {"host": "h", "port": 3, "group": "orchestrator"},
    }
}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    reg = RunnerRegistry(clock=lambda: 1000.0)
    monkeypatch.setattr(group, "REGISTRY", reg)
    group.configure_group(CFG)
    group.ESTOP_LATCH.clear()
    yield reg
    group.configure_group({"servers": {}})


def runner_frame(**kw):
    return {
        "kind": "runner",
        "instance": "i",
        "seq_no": 1,
        "t": 1000.0,
        "orch_state": "busy",
        "loop_state": "started",
        "servers": [
            {
                "key": "SIM",
                "status": "busy",
                "active_action": "a",
                "host": "h",
                "port": 1,
            }
        ],
        "experiments": [],
        "actions": [],
        "events": [],
        **kw,
    }


def test_all_orchestrators_and_runners_are_feeds(fresh):
    fresh.post("R1", runner_frame())
    assert group.feed_keys() == ["ORCH", "ORCH2", "R1"]
    assert group.feed_kind("ORCH2") == "orchestrator"
    assert group.feed_kind("R1") == "runner"
    assert group.default_key() == "ORCH"


def test_reserved_keys_come_from_config(fresh):
    assert fresh.post("SIM", runner_frame()) == 409


def test_runner_only_config_defaults_to_runner(fresh):
    group.configure_group({"servers": {"SIM": CFG["servers"]["SIM"]}})
    fresh.post("R1", runner_frame())
    assert group.default_key() == "R1"


def test_selection_falls_back_when_runner_removed(fresh):
    fresh.post("R1", runner_frame())
    assert group.resolve_key("R1") == "R1"
    fresh.sweep(10_000.0)
    assert group.resolve_key("R1") == "ORCH"
    assert group.resolve_key("") == "ORCH"


def test_peer_layout_on_centre_row():
    pos = group_layout("ORCH", ["SIM"], ["R1", "ORCH2"])
    assert pos["ORCH2"] == (-0.55, 0.0) and pos["R1"] == (0.55, 0.0)
    assert pos["ORCH"] == (0.0, 0.0)


def test_build_graph_adds_peer_nodes_without_edges():
    g = group.build_graph(runner_frame(), "R1", False, peers=[("ORCH", "idle")])
    assert "ORCH" in g.nodes and "SIM" in g.nodes
    assert all("ORCH" not in (e.src, e.dst) for e in g.edges.values())


def test_peer_rows_status(fresh):
    fresh.post("R1", runner_frame())
    rows = dict(group.peer_rows("ORCH", 1000.5))
    assert rows["R1"] == "busy"
    assert rows["ORCH2"] == "unreachable"  # no stream in a unit test
    assert "ORCH" not in rows


def test_runner_estop_calls_every_server_and_latches(monkeypatch, fresh):
    calls = []

    async def fake(server, host, port, path, params_dict=None, json_dict=None):
        calls.append((server, path, params_dict))
        return {}, group.ErrorCodes.none

    monkeypatch.setattr(group, "async_private_dispatcher", fake)
    errs = asyncio.run(group._runner_estop(runner_frame(), True))
    assert errs == [] and calls == [("SIM", "SIM/estop", {"switch": True})]


def test_runner_buttons_hide_start_stop():
    flags = group.button_flags(runner_frame(), False, kind="runner")
    assert flags["can_start"] is False and flags["can_stop"] is False
    flags = group.button_flags(runner_frame(), False, kind="runner", latched=True)
    assert flags["estopped"] is True and flags["can_clear_estop"] is True


def test_replaced_runner_feed_resets_the_page_cursor(fresh):
    fresh.post("R1", runner_frame())
    old = fresh.get("R1")
    s = SimpleNamespace(
        _feed_id=0,
        _cursor=-1,
        _pulses=(),
        _old_orch=False,
        _first_at=0.0,
        _full_at=0.0,
        _hover_col=(-1, -1),
        _pulse_seq=0,
        graph_pulses={},
    )
    group.follow_feed(s, old)
    s._cursor = 57  # ahead of any fresh ingest's n_batches
    group.follow_feed(s, old)
    assert s._cursor == 57  # same object: untouched
    group.follow_feed(s, SimpleNamespace())  # a new object took the key
    assert s._cursor == -1


# ---- fix round 1: view changes, runner pending, latch -----------------------

from helao.core.tests.test_reflex_group import (  # noqa: E402
    Feed,
    _control_state,
    _FakeState,
    frame,
    state,
)
from helao.core.error import ErrorCodes  # noqa: E402


def _two_runner_frame(**kw):
    f = runner_frame(**kw)
    f["servers"] = [
        *f["servers"],
        {
            "key": "SIM2",
            "status": "idle",
            "active_action": None,
            "host": "h",
            "port": 4,
        },
    ]
    return f


def _tick_state():
    return _FakeState(
        **vars(state()),
        _feed_id=0,
        _running=False,
        selected_feed="",
        selected_kind="orchestrator",
        feed_options=[],
        router=SimpleNamespace(session=SimpleNamespace(client_token="t")),
        estopped=False,
        can_clear_estop=False,
    )


def test_view_change_drops_the_previous_feeds_snapshot(monkeypatch):
    orch, orch2 = Feed(), Feed()
    orch.push(frame(1, orch_state="estopped", loop_state="estopped"), now=time_now())
    monkeypatch.setattr(group, "_FEEDS", {"ORCH": orch, "ORCH2": orch2})
    s = _tick_state()
    asyncio.run(group.GroupState.tick.fn(s))
    assert s.estopped is True and s._snap
    s.selected_feed = "ORCH2"  # as set_feed / a dropdown change leaves it
    asyncio.run(group.GroupState.tick.fn(s))
    assert s._snap == () and s.estopped is False and s.can_clear_estop is False


def time_now():
    import time

    return time.time()


def test_runner_pending_is_not_retired_by_a_frame(fresh):
    fresh.post("R1", runner_frame())
    s = state()
    s.pending, s._pending_at = "clear_estop", 0.0
    group.apply_tick(s, fresh.get("R1"), 1000.5, "t", "R1")
    assert s.pending == "clear_estop" and s.action_error == ""


def test_latch_reads_as_estopped_when_the_frame_does_not(fresh):
    fresh.post("R1", runner_frame())
    s = state()
    group.apply_tick(s, fresh.get("R1"), 1000.5, "t", "R1")
    assert s.estopped is False and s.can_estop is True
    group.ESTOP_LATCH["R1"] = True
    s = state()
    group.apply_tick(s, fresh.get("R1"), 1000.5, "t", "R1")
    assert s.estopped is True and s.can_clear_estop is True


def _runner_control(monkeypatch, fresh, name, fail=(), frame_=None):
    fresh.post("R1", frame_ or _two_runner_frame())
    calls = []

    async def fake(server, host, port, path, params_dict=None, json_dict=None):
        calls.append(server)
        return {}, (ErrorCodes.http if server in fail else ErrorCodes.none)

    monkeypatch.setattr(group, "async_private_dispatcher", fake)
    s = _control_state()
    s.selected_feed = "R1"
    asyncio.run(group.GroupState.control.fn(s, name))
    return s, calls


def test_runner_estop_ok_sets_latch(monkeypatch, fresh):
    s, calls = _runner_control(monkeypatch, fresh, "estop")
    assert group.ESTOP_LATCH["R1"] is True and s.action_error == ""
    assert s.pending == "" and sorted(calls) == ["SIM", "SIM2"]


def test_runner_estop_failure_leaves_latch_and_names_server(monkeypatch, fresh):
    s, _ = _runner_control(monkeypatch, fresh, "estop", fail=("SIM2",))
    assert "R1" not in group.ESTOP_LATCH
    assert "SIM2" in s.action_error and "SIM:" not in s.action_error
    assert s.pending == ""


def test_runner_clear_ok_resets_latch(monkeypatch, fresh):
    group.ESTOP_LATCH["R1"] = True
    _runner_control(monkeypatch, fresh, "clear_estop")
    assert group.ESTOP_LATCH["R1"] is False


def test_runner_start_is_refused(monkeypatch, fresh):
    s, calls = _runner_control(monkeypatch, fresh, "start")
    assert s.action_error == "start is not available for a runner" and calls == []


def test_runner_estop_skips_rows_without_host_and_port(monkeypatch, fresh):
    f = _two_runner_frame()
    del f["servers"][1]["host"]
    s, calls = _runner_control(monkeypatch, fresh, "estop", frame_=f)
    assert calls == ["SIM"]
    # a filter-less call would KeyError inside one() and surface here
    assert s.action_error == "" and group.ESTOP_LATCH["R1"] is True


def test_a_pending_press_does_not_follow_a_switch_to_a_runner(monkeypatch, fresh):
    fresh.clock = time_now  # tick sweeps with the wall clock
    fresh.post("R1", runner_frame())
    orch = Feed()
    orch.push(frame(1), now=time_now())
    monkeypatch.setattr(group, "_FEEDS", {"ORCH": orch, "ORCH2": Feed()})
    s = _tick_state()
    asyncio.run(group.GroupState.tick.fn(s))
    s.pending, s._pending_at = "stop", time_now()
    s.selected_feed = "R1"
    asyncio.run(group.GroupState.tick.fn(s))
    assert s.pending == "" and s.selected_kind == "runner"
    assert s.can_clear_estop is False  # not estopped; the gate is pending only


# ---- Task 7: info box for every feed, node clicks ---------------------------

from functools import partial  # noqa: E402


def _bound(**kw):
    """A fake state whose plain helper methods are the real GroupState's."""
    s = _tick_state()
    s._info_node, s._info_sig, s._info_due = "", (), False
    for k, v in kw.items():
        setattr(s, k, v)
    s._select = partial(group.GroupState._select, s)
    s._show_node = partial(group.GroupState._show_node, s)
    return s


def test_backend_picks_a_backend_per_orchestrator(monkeypatch):
    seen = []

    def fake(token, orch_key=None):
        seen.append(orch_key)
        return SimpleNamespace(orch_key=orch_key or "ORCH")

    monkeypatch.setattr(group, "session_backend", fake)
    assert group._backend("t", "ORCH").orch_key == "ORCH"
    assert group._backend("t", "ORCH2").orch_key == "ORCH2"
    assert seen == [None, "ORCH2"]  # the first keeps the operator's own backend


def _runner_strip_state(fresh, rpc_cfg=True):
    f = runner_frame(
        experiments=[{"name": "e", "state": "active", "uuid": "u-exp", "qidx": None}],
        config={"host": "rh", "rpc_port": 9} if rpc_cfg else {},
    )
    fresh.post("R1", f)
    s = _bound(
        selected_feed="R1",
        _info_node="SIM",  # a node was showing; a strip click replaces it
        _exp_slots=(f["experiments"][0],),
        _exp_edges=(0.0, 100.0),
        _exp_ords=(0,),
        _scopes=("seq", "exp"),
    )
    return s


def test_runner_strip_click_fetches_through_the_entry_rpc(fresh):
    calls = []

    class FakeRPC:
        async def call(self, method, **kw):
            calls.append((method, kw))
            return {"experiment_name": "e", "experiment_uuid": "u-exp"}

    s = _runner_strip_state(fresh)
    fresh.get("R1").rpc = lambda host, port: (calls.append((host, port)), FakeRPC())[1]
    asyncio.run(group.GroupState.select_exp.fn(s, {"x": 10}))
    assert calls[0] == ("rh", 9)
    assert calls[1] == ("get_object", {"kind": "experiment", "uuid": "u-exp"})
    assert "u-exp"[:5] in s.tree_header or s.tree_header.startswith("e")
    assert s._info_node == ""


def test_runner_strip_click_without_rpc_config_is_not_found(fresh):
    s = _runner_strip_state(fresh, rpc_cfg=False)
    asyncio.run(group.GroupState.select_exp.fn(s, {"x": 10}))
    assert s.info_note == group.NOT_FOUND


def _node_state(monkeypatch, fresh, selected):
    fresh.clock = time_now
    f = runner_frame(
        config={"host": "rh", "rpc_port": 9, "password": "hunter2"},
    )
    fresh.post("R1", f)
    s = _bound(selected_feed=selected, _snap=(f,))
    g = group.build_graph(f, "R1", False, [("ORCH", "idle"), ("ORCH2", "idle")])
    group._GRAPHS["t"] = g
    return s, g, f


def _click(s, g, key):
    n = g.nodes[key]
    asyncio.run(group.GroupState.select_node.fn(s, {"x": n.x, "y": n.y}))


def test_action_server_node_click_shows_config_and_endpoints(monkeypatch, fresh):
    s, g, f = _node_state(monkeypatch, fresh, "R1")
    status = {
        "estop": False,
        "_driver_status": "ok",
        "endpoints": {"go": {"active_dict": {}, "nonactive_dict": {}}},
    }
    calls = []

    async def fake(server, host, port, path, params_dict=None, json_dict=None):
        calls.append(path)
        if path == "get_config":
            return {
                "servers": {
                    "SIM": {"host": "h", "port": 1, "params": {"api_key": "sekrit-9"}}
                }
            }, ErrorCodes.none
        return status, ErrorCodes.none

    monkeypatch.setattr(group, "async_private_dispatcher", fake)
    group._SERVER_CFG.clear()
    monkeypatch.setitem(
        group._WORLD, "servers", {}
    )  # a runner's server is unknown here
    _click(s, g, "SIM")
    assert calls == ["get_config", "get_status"]
    assert s.tree_header == "SIM" and s._info_node == "SIM"
    assert "go — idle, 0 non-idle" in s.tree_html
    assert "api_key: ***" in s.tree_html and "sekrit-9" not in s.tree_html
    assert s._info_sig == ("busy", "a")


def test_orch_and_runner_node_clicks_show_masked_config(monkeypatch, fresh):
    s, g, f = _node_state(monkeypatch, fresh, "R1")
    _click(s, g, "R1")
    assert s.tree_header == "R1" and "hunter2" not in s.tree_html
    assert "***" in s.tree_html and s.selected_feed == "R1"
    monkeypatch.setitem(group._WORLD, "servers", {"ORCH": {"port": 2, "token": "t0k"}})
    _click(s, g, "ORCH")  # a peer orchestrator
    assert s.tree_header == "ORCH" and "t0k" not in s.tree_html
    assert "***" in s.tree_html


def test_peer_click_switches_view_and_the_next_tick_keeps_it(monkeypatch, fresh):
    s, g, f = _node_state(monkeypatch, fresh, "R1")
    orch = Feed()
    orch.push(frame(1), now=time_now())
    monkeypatch.setattr(group, "_FEEDS", {"ORCH": orch, "ORCH2": Feed()})
    asyncio.run(group.GroupState.tick.fn(s))
    s._selected = ("experiment", 1, "x")
    _click(s, g, "ORCH")
    assert s.selected_feed == "ORCH" and s._feed_id == id(orch)
    assert s._snap == () and s._selected == ()
    assert s._info_node == "ORCH" and s.tree_header == "ORCH"
    cursor = 5
    s._cursor = cursor
    asyncio.run(group.GroupState.tick.fn(s))
    assert s._cursor != -1  # follow_feed did not reset a second time
    assert s._info_node == "ORCH"


def test_view_change_clears_the_node_selection(fresh):
    s = _bound(_info_node="SIM", _info_sig=("busy", "a"))
    group.switch_view(s)
    assert s._info_node == "" and s._info_sig == ()


def test_a_state_change_of_the_shown_node_marks_info_due(fresh):
    f = runner_frame()
    s = _bound(_info_node="SIM", _info_sig=("idle", None), selected_feed="R1")
    s._snap = (f,)
    fresh.post("R1", f)
    group.apply_tick(s, fresh.get("R1"), time_now(), "t", "R1", ())
    assert s._info_due is True


def test_backend_registry_drop_prefix_closes_only_that_session():
    from helao.ui.reflex.operator import BackendRegistry

    closed = []
    reg = BackendRegistry()
    for k in ("t", "t|A", "t|B", "u|A"):
        reg.put(k, SimpleNamespace(close=lambda k=k: closed.append(k)))
    reg.drop_prefix("t|")
    assert sorted(closed) == ["t|A", "t|B"]
    assert reg.get("t") is not None and reg.get("u|A") is not None
    assert reg.get("t|A") is None
