"""The Reflex control page: discovery, state transitions, and the tri-state.

The behaviour these assert is the same behaviour ``test_io_control_vis.py``
asserts for the Bokeh panel, deliberately — the two UIs share
``helao.core.servers.io_control`` precisely so a rule cannot hold in one and
not the other, and a pair of test files is what keeps that honest.

Reflex event handlers are exercised directly rather than through a browser: the
handlers are ``background=True`` coroutines whose only job is to fold a
transport result into ``rows``, and that is what can be wrong.
"""

import asyncio

import pytest

from helao.core.servers import io_control
from helao.core.servers.reflex import control as control_mod
from helao.core.servers.reflex.control import ControlState, control_targets

WORLD = {
    "servers": {
        "IO": {
            "host": "127.0.0.1",
            "port": 8005,
            "control_vis": "digital_out_control",
            "params": {"dev_do": {"gamry_aux": 1, "Thorlab_led": 7}},
        },
        "NI": {
            "host": "127.0.0.1",
            "port": 8006,
            "control_vis": "nidaqmx_control",
            "params": {
                "dev_pump": {"PeriPump1": "line9"},
                "dev_gasvalve": {"CO2": "line0"},
            },
        },
        "PLAIN": {"host": "127.0.0.1", "port": 8007, "params": {}},
    }
}


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------


def test_only_servers_declaring_control_vis_get_a_block():
    targets = control_targets(WORLD)
    assert [t.server_key for t in targets] == ["IO", "NI"]
    print("test_only_servers_declaring_control_vis_get_a_block PASS")


def test_groups_come_from_the_panel_module_not_the_page():
    # The page knows nothing about which dev_* blocks a server uses; that is
    # the panel module's whole contribution, and it differs per server.
    targets = {t.server_key: t for t in control_targets(WORLD)}

    assert [i.name for i in targets["IO"].items] == ["gamry_aux", "Thorlab_led"]
    assert all(i.group == "dev_do" for i in targets["IO"].items)

    ni_names = [i.name for i in targets["NI"].items]
    assert ni_names == ["PeriPump1", "CO2"], ni_names
    assert [i.group for i in targets["NI"].items] == ["dev_pump", "dev_gasvalve"]
    print("test_groups_come_from_the_panel_module_not_the_page PASS")


def test_limit_vis_narrows_the_page():
    targets = control_targets(WORLD, limit_vis=["NI"])
    assert [t.server_key for t in targets] == ["NI"]
    print("test_limit_vis_narrows_the_page PASS")


def test_an_unresolvable_panel_module_is_skipped_not_raised():
    # A deployment's module that will not import must not take down the page
    # for every other server on it.
    world = {
        "servers": {
            "IO": dict(WORLD["servers"]["IO"]),
            "BAD": {
                "host": "h",
                "port": 1,
                "control_vis": "no_such_control_module",
                "params": {"dev_do": {"x": 1}},
            },
        }
    }
    targets = control_targets(world)
    assert [t.server_key for t in targets] == ["IO"]
    print("test_an_unresolvable_panel_module_is_skipped_not_raised PASS")


# --------------------------------------------------------------------------
# state
# --------------------------------------------------------------------------


@pytest.fixture
def page(monkeypatch):
    """Configure the page and script what the endpoints reply."""
    sent = []
    script = {"read": {}, "write": {}}

    async def _read(server_key, host, port):
        return dict(script["read"].get(server_key, {}))

    async def _write(server_key, host, port, do_name, on):
        sent.append((server_key, do_name, on))
        return dict(script["write"])

    monkeypatch.setattr(io_control, "read_digital_outs", _read)
    monkeypatch.setattr(io_control, "set_digital_out", _write)
    monkeypatch.setattr(control_mod, "read_digital_outs", _read)
    monkeypatch.setattr(control_mod, "set_digital_out", _write)
    control_mod.configure_control(WORLD, "REFLEX")
    return sent, script


class _FakeState:
    """A stand-in carrying the three vars and two helpers the handlers touch.

    Deliberately *not* a ``ControlState`` subclass: Reflex intercepts attribute
    assignment on a real state and forwards it to a parent state that does not
    exist outside a session, so every write raises. Duck-typing keeps the
    handlers themselves under test — the transitions are the whole point — with
    none of the session machinery in the way.

    ``async with self`` is how a background handler takes the state lock; here
    it is a no-op.
    """

    def __init__(self):
        self.rows = []
        self.status = ""
        self.loaded = False

    # The real implementations, exercised rather than reimplemented. Every
    # non-event method the handlers reach through `self` has to be listed:
    # duck-typing buys isolation from Reflex's session machinery and costs this
    # line, which is why a missing one fails loudly on the next run rather than
    # quietly passing.
    _state_of = ControlState._state_of
    _apply = ControlState._apply
    _read_into_rows = ControlState._read_into_rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _load(state):
    asyncio.run(ControlState.load.fn(state))


def _toggle(state, server_key, do_name):
    asyncio.run(ControlState.toggle.fn(state, server_key, do_name))


def test_every_configured_line_gets_a_row(page):
    state = _FakeState()
    _load(state)

    assert [(r[0], r[1]) for r in state.rows] == [
        ("IO", "gamry_aux"),
        ("IO", "Thorlab_led"),
        ("NI", "PeriPump1"),
        ("NI", "CO2"),
    ]
    print("test_every_configured_line_gets_a_row PASS")


def test_unread_lines_render_unknown_not_off(page):
    _, script = page
    script["read"] = {"IO": {"gamry_aux": True, "Thorlab_led": False}}
    state = _FakeState()
    _load(state)

    by_name = {r[1]: r for r in state.rows}
    assert by_name["gamry_aux"][4] == "on"
    assert by_name["gamry_aux"][3] == "gamry_aux: ON"
    assert by_name["Thorlab_led"][4] == "off"
    # NI answered nothing, so its controls stay unknown rather than off.
    assert by_name["PeriPump1"][4] == "unknown"
    assert by_name["CO2"][3] == "CO2: ?"
    assert "could not read: NI" in state.status, state.status
    print("test_unread_lines_render_unknown_not_off PASS")


def test_toggle_sends_the_opposite_of_the_reported_state(page):
    sent, script = page
    script["read"] = {"IO": {"gamry_aux": True, "Thorlab_led": False}}
    state = _FakeState()
    _load(state)

    script["write"] = {"gamry_aux": False}
    _toggle(state, "IO", "gamry_aux")
    assert sent[-1] == ("IO", "gamry_aux", False), sent

    script["write"] = {"Thorlab_led": True}
    _toggle(state, "IO", "Thorlab_led")
    assert sent[-1] == ("IO", "Thorlab_led", True), sent
    print("test_toggle_sends_the_opposite_of_the_reported_state PASS")


def test_toggling_an_unknown_line_drives_it_off(page):
    sent, script = page
    script["write"] = {"CO2": False}
    state = _FakeState()
    _load(state)

    _toggle(state, "NI", "CO2")

    assert sent == [("NI", "CO2", False)]
    assert {r[1]: r[4] for r in state.rows}["CO2"] == "off"
    print("test_toggling_an_unknown_line_drives_it_off PASS")


def test_a_failed_write_returns_the_control_to_unknown(page):
    _, script = page
    script["read"] = {"IO": {"gamry_aux": True, "Thorlab_led": False}}
    state = _FakeState()
    _load(state)

    script["write"] = {}  # the transport reports failure as an empty dict
    _toggle(state, "IO", "gamry_aux")

    by_name = {r[1]: r for r in state.rows}
    assert by_name["gamry_aux"][4] == "unknown"
    assert "state unknown" in state.status, state.status
    # And only that control changed.
    assert by_name["Thorlab_led"][4] == "off"
    print("test_a_failed_write_returns_the_control_to_unknown PASS")


def test_a_toggle_leaves_every_other_row_alone(page):
    _, script = page
    script["read"] = {
        "IO": {"gamry_aux": True, "Thorlab_led": True},
        "NI": {"PeriPump1": True, "CO2": True},
    }
    state = _FakeState()
    _load(state)

    script["write"] = {"CO2": False}
    _toggle(state, "NI", "CO2")

    states = {r[1]: r[4] for r in state.rows}
    assert states == {
        "gamry_aux": "on",
        "Thorlab_led": "on",
        "PeriPump1": "on",
        "CO2": "off",
    }
    print("test_a_toggle_leaves_every_other_row_alone PASS")


def test_toggling_an_unknown_server_is_a_no_op(page):
    sent, _ = page
    state = _FakeState()
    _load(state)

    _toggle(state, "NOT_A_SERVER", "whatever")

    assert sent == [], "a server not on the page must not reach the transport"
    print("test_toggling_an_unknown_server_is_a_no_op PASS")


def test_load_is_guarded_against_firing_twice(page):
    _, script = page
    script["read"] = {"IO": {"gamry_aux": True}}
    state = _FakeState()
    _load(state)
    before = list(state.rows)

    script["read"] = {"IO": {"gamry_aux": False}}
    _load(state)

    # Reflex can fire on_mount more than once; a second read would stamp over
    # states the user has since commanded.
    assert state.rows == before
    print("test_load_is_guarded_against_firing_twice PASS")


def test_the_control_page_route_is_registered():
    from helao.core.servers.reflex.app import SHELL_ROUTES

    assert "/control" in SHELL_ROUTES
    print("test_the_control_page_route_is_registered PASS")


def test_every_state_key_has_a_button_class():
    from helao.core.servers.palette import reflex_control_button_class

    # The three the rows can carry, and nothing else -- an unmapped key would
    # render a control whose colour says nothing about the line it drives.
    for key in ("on", "off", "unknown"):
        assert reflex_control_button_class(key)
    with pytest.raises(KeyError):
        reflex_control_button_class("maybe")
    print("test_every_state_key_has_a_button_class PASS")


def _reread(state):
    asyncio.run(ControlState.reread.fn(state))


def test_reread_refetches_where_load_would_not(page):
    _, script = page
    script["read"] = {"IO": {"gamry_aux": True, "Thorlab_led": True}}
    state = _FakeState()
    _load(state)
    assert {r[1]: r[4] for r in state.rows}["gamry_aux"] == "on"

    # A sequence drives the line while the page is open. `load` is guarded and
    # would do nothing; `reread` is the path that is meant to overwrite.
    script["read"] = {"IO": {"gamry_aux": False, "Thorlab_led": True}}
    _load(state)
    assert {r[1]: r[4] for r in state.rows}[
        "gamry_aux"
    ] == "on", "load must not refetch"

    _reread(state)
    assert {r[1]: r[4] for r in state.rows}["gamry_aux"] == "off"
    print("test_reread_refetches_where_load_would_not PASS")


def test_reread_restores_unknown_for_a_server_that_stops_answering(page):
    _, script = page
    script["read"] = {"IO": {"gamry_aux": True, "Thorlab_led": False}}
    state = _FakeState()
    _load(state)

    script["read"] = {}  # both servers now unreachable
    _reread(state)

    assert all(r[4] == "unknown" for r in state.rows), state.rows
    assert "could not read" in state.status
    print("test_reread_restores_unknown_for_a_server_that_stops_answering PASS")


def test_the_read_button_colour_is_not_a_line_state_colour():
    from helao.core.servers.palette import (
        REFLEX_CONTROL_READ_CLASS,
        REFLEX_CONTROL_STATE_CLASSES,
    )

    # An action, not a fourth state a digital output could be in.
    assert REFLEX_CONTROL_READ_CLASS not in set(REFLEX_CONTROL_STATE_CLASSES.values())
    print("test_the_read_button_colour_is_not_a_line_state_colour PASS")
