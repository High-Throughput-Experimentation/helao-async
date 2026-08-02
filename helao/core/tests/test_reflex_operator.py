"""Tests for the Reflex operator page.

Driven against a fake OrchBackend: the real one is an ABC, so a stub is small,
and no orchestrator runs here. The page's logic lives in module-level functions
for the same reason the browser's does -- rx.State cannot be instantiated
outside a running app.
"""

import asyncio

import pytest

from helao.core.servers.operator import app_reflex as opx


class FakeBackend:
    """Only the OrchBackend methods the page calls."""

    def __init__(
        self,
        sequences=None,
        experiments=None,
        actions=None,
        state="idle",
        summary=None,
        fail=False,
    ):
        self._sequences = sequences or []
        self._experiments = experiments or []
        self._actions = actions or []
        self._state = state
        self._summary = summary or {}
        self._fail = fail
        self.calls = []

    def _boom(self):
        if self._fail:
            raise RuntimeError("orchestrator unreachable")

    async def get_orch_state(self):
        self._boom()
        return {"orch_state": self._state, "loop_state": "started"}

    async def list_sequences(self):
        self._boom()
        return self._sequences

    async def list_experiments(self):
        self._boom()
        return self._experiments

    async def list_actions(self):
        self._boom()
        return self._actions

    async def get_status_summary(self):
        self._boom()
        return self._summary

    async def start(self):
        self._boom()
        self.calls.append("start")

    async def stop(self, reset_run_id=False):
        self._boom()
        self.calls.append(("stop", reset_run_id))

    async def estop(self):
        self._boom()
        self.calls.append("estop")

    async def skip(self):
        self._boom()
        self.calls.append("skip")

    async def clear_sequences(self):
        self._boom()
        self.calls.append("clear_sequences")

    async def clear_experiments(self):
        self._boom()
        self.calls.append("clear_experiments")

    async def clear_actions(self):
        self._boom()
        self.calls.append("clear_actions")

    async def move_sequence(self, from_idx, to_idx):
        self._boom()
        self.calls.append(("move_sequence", from_idx, to_idx))

    async def move_experiment(self, from_idx, to_idx):
        self._boom()
        self.calls.append(("move_experiment", from_idx, to_idx))

    async def move_action(self, from_idx, to_idx):
        self._boom()
        self.calls.append(("move_action", from_idx, to_idx))

    async def remove_sequence(self, idx):
        self._boom()
        self.calls.append(("remove_sequence", idx))

    async def remove_experiment(self, idx):
        self._boom()
        self.calls.append(("remove_experiment", idx))

    async def remove_action(self, idx):
        self._boom()
        self.calls.append(("remove_action", idx))

    def close(self):
        self.calls.append("close")


def test_queue_rows_renders_requested_columns_as_strings():
    """Reflex serialises state to JSON; a UUID or None in a cell breaks the
    encoder or renders as garbage."""
    items = [{"a": 1, "b": None, "c": "x"}]
    assert opx.queue_rows(items, ["a", "b"]) == [["1", ""]]


def test_queue_rows_tolerates_a_missing_column():
    assert opx.queue_rows([{"a": 1}], ["a", "nope"]) == [["1", ""]]


def test_queue_rows_on_nothing_is_empty():
    assert opx.queue_rows([], ["a"]) == []


def test_queue_rows_stringifies_a_nested_value():
    rows = opx.queue_rows([{"a": {"k": 1}}], ["a"])
    assert rows == [["{'k': 1}"]]


def test_status_line_reports_the_orchestrator_state():
    assert "idle" in opx.status_line({"orch_state": "idle"}, reachable=True)


def test_status_line_includes_the_loop_state_when_present():
    line = opx.status_line({"orch_state": "busy", "loop_state": "started"}, True)
    assert "busy" in line and "started" in line


def test_status_line_distinguishes_unreachable_from_idle():
    """A station's orchestrator restarting mid-session is routine, and 'idle'
    would be a lie about it."""
    line = opx.status_line(None, reachable=False)
    assert "idle" not in line
    assert "reach" in line.lower()


def test_status_line_on_a_reachable_orchestrator_with_no_state():
    assert "unknown" in opx.status_line(None, reachable=True)


# -- backend registry --------------------------------------------------------


def test_backend_registry_is_per_session():
    reg = opx.BackendRegistry()
    a, b = FakeBackend(), FakeBackend()
    reg.put("tok-a", a)
    reg.put("tok-b", b)
    assert reg.get("tok-a") is a
    assert reg.get("tok-b") is b


def test_backend_registry_returns_none_for_an_unknown_session():
    assert opx.BackendRegistry().get("nobody") is None


def test_backend_registry_drop_closes_the_backend():
    """The backend holds sockets; dropping the reference without closing leaks
    an HTTP session per operator tab."""

    class Closable(FakeBackend):
        def __init__(self):
            super().__init__()
            self.closed = False

        def close(self):
            self.closed = True

    reg = opx.BackendRegistry()
    backend = Closable()
    reg.put("tok", backend)
    reg.drop("tok")
    assert backend.closed is True
    assert reg.get("tok") is None


def test_backend_registry_drop_survives_a_backend_that_cannot_close():
    """Teardown must not raise: it runs on page unmount, where an exception
    would leave the entry in the registry forever."""

    class Angry(FakeBackend):
        def close(self):
            raise RuntimeError("nope")

    reg = opx.BackendRegistry()
    reg.put("tok", Angry())
    reg.drop("tok")
    assert reg.get("tok") is None


# -- queue control gating ----------------------------------------------------


@pytest.mark.parametrize(
    "state,expected",
    [("idle", True), ("stopped", True), ("busy", False), ("estopped", False)],
)
def test_queue_edits_are_allowed_only_when_the_orchestrator_is_not_running(
    state, expected
):
    """Mirrors the Bokeh operator's enable gate: reordering a queue the
    orchestrator is actively dispatching from races it."""
    assert opx.may_edit_queue(state) is expected


def test_moved_index_refuses_to_move_the_first_item_up():
    assert opx.moved_index(0, "up", 5) is None


def test_moved_index_refuses_to_move_the_last_item_down():
    assert opx.moved_index(4, "down", 5) is None


def test_moved_index_returns_the_target_for_a_valid_move():
    assert opx.moved_index(2, "up", 5) == 1
    assert opx.moved_index(2, "down", 5) == 3


def test_moved_index_refuses_an_out_of_range_position():
    assert opx.moved_index(9, "up", 5) is None
    assert opx.moved_index(-1, "down", 5) is None


# -- column contract ---------------------------------------------------------


def test_queue_columns_are_keys_the_backend_actually_returns():
    """The column lists are a contract with ``RemoteBackend``'s normalizers.

    ``queue_rows`` renders a missing column as an empty cell, so a drifted
    column name does not raise -- it silently produces a blank column that
    looks like missing data from the orchestrator.
    """
    from helao.core.servers.operator import orch_backend as ob

    assert set(opx.SEQ_COLS) <= set(ob._SEQ_KEYS)
    assert set(opx.EXP_COLS) <= set(ob._EXP_KEYS)
    # list_actions builds its dicts inline rather than from a key constant.
    assert set(opx.ACT_COLS) <= {"action_name", "action_server", "action_uuid"}


# -- action-server status table ----------------------------------------------


def test_server_rows_sorts_by_server_name():
    """Fixed row order regardless of the unordered dict the backend returns."""
    rows = opx.server_rows({"b": ("idle", "ok"), "a": ("busy", "ok")})
    assert [r[0] for r in rows] == ["a", "b"]


def test_server_rows_stringifies_every_cell():
    rows = opx.server_rows({"a": ("idle", None)})
    assert rows == [["a", "idle", ""]]


def test_server_rows_tolerates_a_malformed_entry():
    """A server whose summary is not a (status, driver) pair still gets a row:
    dropping it would hide a server that is misbehaving."""
    rows = opx.server_rows({"a": "just a string"})
    assert rows[0][0] == "a"
    assert len(rows[0]) == 3


def test_server_rows_on_nothing_is_empty():
    assert opx.server_rows({}) == []
    assert opx.server_rows(None) == []


# -- poll interval -----------------------------------------------------------


def test_poll_interval_comes_from_the_server_params():
    cfg = {"servers": {"ui": {"params": {"poll_interval": 2.5}}}}
    assert opx.poll_interval_for(cfg, "ui") == 2.5


def test_poll_interval_defaults_when_absent():
    assert opx.poll_interval_for({"servers": {"ui": {}}}, "ui") == (
        opx.DEFAULT_POLL_INTERVAL
    )


def test_poll_interval_rejects_a_nonsense_value():
    """A typo'd YAML value must not turn into a zero-delay busy loop against
    the orchestrator."""
    cfg = {"servers": {"ui": {"params": {"poll_interval": "soon"}}}}
    assert opx.poll_interval_for(cfg, "ui") == opx.DEFAULT_POLL_INTERVAL
    cfg = {"servers": {"ui": {"params": {"poll_interval": 0}}}}
    assert opx.poll_interval_for(cfg, "ui") == opx.DEFAULT_POLL_INTERVAL


# -- refresh -----------------------------------------------------------------


def test_refresh_tables_reads_every_queue_and_the_state():
    backend = FakeBackend(
        sequences=[{"sequence_name": "s1"}],
        experiments=[{"experiment_name": "e1"}],
        actions=[{"action_name": "a1"}],
        summary={"srv": ("idle", "ok")},
    )
    out = asyncio.run(opx.refresh_tables(backend))
    assert out["reachable"] is True
    assert out["orch_state"] == "idle"
    assert out["seq_rows"][0][0] == "s1"
    assert out["exp_rows"][0][0] == "e1"
    assert out["act_rows"][0][0] == "a1"
    assert out["server_rows"] == [["srv", "idle", "ok"]]
    assert "idle" in out["status"]


def test_refresh_tables_keeps_the_last_rows_when_the_orchestrator_goes_away():
    """The returned dict carries no row keys on failure, so the caller's last
    known queues stay on screen while the status line says it cannot reach the
    orchestrator. Blanking the tables would read as 'the queue is empty'."""
    out = asyncio.run(opx.refresh_tables(FakeBackend(fail=True)))
    assert out["reachable"] is False
    assert "seq_rows" not in out
    assert "exp_rows" not in out
    assert "act_rows" not in out
    assert "server_rows" not in out
    assert "reach" in out["status"].lower()


def test_refresh_tables_reports_the_failure_in_error():
    out = asyncio.run(opx.refresh_tables(FakeBackend(fail=True)))
    assert "unreachable" in out["error"]


def test_refresh_tables_without_a_backend_is_unreachable():
    out = asyncio.run(opx.refresh_tables(None))
    assert out["reachable"] is False
    assert "seq_rows" not in out


def test_refresh_tables_clears_a_stale_error_on_success():
    out = asyncio.run(opx.refresh_tables(FakeBackend()))
    assert out["error"] == ""


# -- controls ----------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["start", "stop", "estop", "skip", "clear_sequences", "clear_experiments"],
)
def test_dispatch_control_calls_the_backend(name):
    backend = FakeBackend()
    assert asyncio.run(opx.dispatch_control(backend, name)) == ""
    assert len(backend.calls) == 1


def test_dispatch_control_refuses_a_method_that_is_not_a_control():
    """Event names arrive from the client. Without the allow-list, a crafted
    event would reach any coroutine on the backend, ``close`` included."""
    backend = FakeBackend()
    err = asyncio.run(opx.dispatch_control(backend, "close"))
    assert "unknown control" in err
    assert backend.calls == []


def test_dispatch_control_reports_a_backend_failure():
    err = asyncio.run(opx.dispatch_control(FakeBackend(fail=True), "start"))
    assert "start failed" in err


def test_dispatch_control_without_a_backend():
    err = asyncio.run(opx.dispatch_control(None, "start"))
    assert "no orchestrator" in err


# -- queue edits -------------------------------------------------------------


def test_dispatch_move_routes_to_the_right_backend_method():
    for kind, method in [
        ("sequence", "move_sequence"),
        ("experiment", "move_experiment"),
        ("action", "move_action"),
    ]:
        backend = FakeBackend()
        assert asyncio.run(opx.dispatch_move(backend, kind, 1, "up", 3)) == ""
        assert backend.calls == [(method, 1, 0)]


def test_dispatch_move_at_the_end_of_the_queue_does_not_call_the_backend():
    """An impossible move must not become a backend round trip that reorders
    nothing while the UI implies it worked."""
    backend = FakeBackend()
    assert asyncio.run(opx.dispatch_move(backend, "sequence", 0, "up", 3)) == ""
    assert backend.calls == []


def test_dispatch_move_refuses_an_unknown_kind():
    backend = FakeBackend()
    err = asyncio.run(opx.dispatch_move(backend, "nonsense", 0, "down", 3))
    assert "unknown queue" in err
    assert backend.calls == []


def test_dispatch_remove_routes_to_the_right_backend_method():
    for kind, method in [
        ("sequence", "remove_sequence"),
        ("experiment", "remove_experiment"),
        ("action", "remove_action"),
    ]:
        backend = FakeBackend()
        assert asyncio.run(opx.dispatch_remove(backend, kind, 2, 3)) == ""
        assert backend.calls == [(method, 2)]


def test_dispatch_remove_refuses_a_position_outside_the_queue():
    """Positions come from a rendered row index, which can outlive the row: a
    poll can shorten the queue between render and click."""
    backend = FakeBackend()
    err = asyncio.run(opx.dispatch_remove(backend, "sequence", 7, 3))
    assert "no longer" in err
    assert backend.calls == []


def test_dispatch_remove_reports_a_backend_failure():
    err = asyncio.run(opx.dispatch_remove(FakeBackend(fail=True), "sequence", 0, 3))
    assert "failed" in err


# -- backend construction ----------------------------------------------------


def test_vis_shim_exposes_what_the_backend_reads_off_a_bokeh_vis():
    """RemoteBackend was written against a Bokeh ``Vis``; it reads exactly two
    attributes off it, so the Reflex page supplies them rather than importing
    Bokeh."""
    shim = opx._VisShim({"servers": {}}, "ui")
    assert shim.world_cfg == {"servers": {}}
    assert hasattr(shim.helaodirs, "user_exp")
    assert hasattr(shim.helaodirs, "user_seq")


def test_session_backend_without_configuration_is_none():
    """Import-time safety: the state class exists before any config is loaded,
    and a poll that fires first must degrade to 'cannot reach', not raise."""
    opx.reset_settings()
    assert opx.session_backend("tok") is None
