"""Tests for the Reflex operator page.

Driven against a fake OrchBackend: the real one is an ABC, so a stub is small,
and no orchestrator runs here. The page's logic lives in module-level functions
for the same reason the browser's does -- rx.State cannot be instantiated
outside a running app.
"""

import pytest

from helao.core.servers.operator import app_reflex as opx


class FakeBackend:
    """Only the OrchBackend methods the page calls."""

    def __init__(self, sequences=None, experiments=None, actions=None, state="idle"):
        self._sequences = sequences or []
        self._experiments = experiments or []
        self._actions = actions or []
        self._state = state
        self.calls = []

    async def get_orch_state(self):
        return {"orch_state": self._state, "loop_state": "started"}

    async def list_sequences(self):
        return self._sequences

    async def list_experiments(self):
        return self._experiments

    async def list_actions(self):
        return self._actions

    async def get_status_summary(self):
        return {}

    async def start(self):
        self.calls.append("start")

    async def stop(self, reset_run_id=False):
        self.calls.append(("stop", reset_run_id))

    async def estop(self):
        self.calls.append("estop")


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
