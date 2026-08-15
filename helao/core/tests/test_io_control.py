"""The shared logic under both digital-output control panels.

Backend-agnostic, so these tests need neither Bokeh nor Reflex. What they pin
is the part that would fail silently: the tri-state, and the fact that
*unknown* never collapses to *off*. A panel that renders an unread line as off
is a confident lie about an instrument that may be energised.
"""

import asyncio

import pytest

from helao.core.error import ErrorCodes
from helao.ui.shared import io_control
from helao.ui.shared.io_control import (
    DoItem,
    discover_do_items,
    group_do_items,
    group_heading,
    read_digital_outs,
    set_digital_out,
    state_label,
)

GALIL_CFG = {
    "host": "127.0.0.1",
    "port": 8005,
    "params": {"dev_do": {"gamry_aux": 1, "Thorlab_led": 7}, "dev_di": {"ttl0": 1}},
}

NI_CFG = {
    "host": "127.0.0.1",
    "port": 8006,
    "params": {
        "dev_pump": {"PeriPump1": "line9"},
        "dev_gasvalve": {"CO2": "line0", "Ar": "line2"},
        "dev_led": {"led": "line11"},
    },
}


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------


def test_discovery_reads_one_block():
    items = discover_do_items(GALIL_CFG, ("dev_do",))
    assert items == [
        DoItem("gamry_aux", "dev_do"),
        DoItem("Thorlab_led", "dev_do"),
    ]
    print("test_discovery_reads_one_block PASS")


def test_discovery_keeps_group_order_then_config_order():
    # Group order is display order, so the panel's sections follow the list the
    # caller passed rather than dict iteration over the config.
    items = discover_do_items(NI_CFG, ("dev_gasvalve", "dev_pump", "dev_led"))
    assert [i.name for i in items] == ["CO2", "Ar", "PeriPump1", "led"]
    assert [i.group for i in items] == [
        "dev_gasvalve",
        "dev_gasvalve",
        "dev_pump",
        "dev_led",
    ]
    print("test_discovery_keeps_group_order_then_config_order PASS")


def test_discovery_ignores_groups_the_server_does_not_have():
    items = discover_do_items(NI_CFG, ("dev_pump", "dev_multivalve", "dev_fswbcd"))
    assert [i.name for i in items] == ["PeriPump1"]
    print("test_discovery_ignores_groups_the_server_does_not_have PASS")


def test_discovery_is_empty_when_nothing_is_configured():
    # A panel renders this as an explicit "none configured", not a blank box.
    assert discover_do_items({"params": {}}, ("dev_do",)) == []
    assert discover_do_items({}, ("dev_do",)) == []
    print("test_discovery_is_empty_when_nothing_is_configured PASS")


def test_discovery_gives_a_duplicated_name_only_one_control():
    # The servers refuse an ambiguous name, so a second button for it would be
    # one that cannot work.
    cfg = {
        "params": {"dev_gasvalve": {"shared": "a"}, "dev_liquidvalve": {"shared": "b"}}
    }
    items = discover_do_items(cfg, ("dev_gasvalve", "dev_liquidvalve"))
    assert items == [DoItem("shared", "dev_gasvalve")]
    print("test_discovery_gives_a_duplicated_name_only_one_control PASS")


# --------------------------------------------------------------------------
# state_label
# --------------------------------------------------------------------------


def test_state_label_has_three_states():
    assert state_label(True) == "ON"
    assert state_label(False) == "OFF"
    assert state_label(None) == "?"
    # The load-bearing one: unknown must not read as off.
    assert state_label(None) != state_label(False)
    print("test_state_label_has_three_states PASS")


# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------


@pytest.fixture
def dispatched(monkeypatch):
    """Capture private-dispatcher calls and script their replies."""
    calls = []
    reply = {"value": ({"gamry_aux": 1}, ErrorCodes.none)}

    async def _fake(**kwargs):
        calls.append(kwargs)
        result = reply["value"]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(io_control, "async_private_dispatcher", _fake)
    return calls, reply


def test_read_normalises_the_rpc_tuple_shape(dispatched):
    calls, reply = dispatched
    reply["value"] = ((ErrorCodes.none, {"gamry_aux": 1, "led": 0}), ErrorCodes.none)

    states = asyncio.run(read_digital_outs("IO", "127.0.0.1", 8005))

    assert states == {"gamry_aux": True, "led": False}
    assert calls[0]["private_action"] == "get_digital_outs"
    print("test_read_normalises_the_rpc_tuple_shape PASS")


def test_read_normalises_the_http_list_shape(dispatched):
    # The HTTP fallback JSON-decodes the endpoint's tuple to a two-element
    # list, so both shapes reach this layer and both must unwrap.
    _, reply = dispatched
    reply["value"] = ([0, {"gamry_aux": True, "led": None}], ErrorCodes.none)

    states = asyncio.run(read_digital_outs("IO", "127.0.0.1", 8005))

    assert states == {"gamry_aux": True, "led": None}
    print("test_read_normalises_the_http_list_shape PASS")


def test_read_preserves_unknown_rather_than_coercing_it(dispatched):
    _, reply = dispatched
    reply["value"] = ((ErrorCodes.none, {"a": None, "b": 0}), ErrorCodes.none)

    states = asyncio.run(read_digital_outs("NI", "127.0.0.1", 8006))

    assert states["a"] is None, "None must survive as unknown"
    assert states["b"] is False
    print("test_read_preserves_unknown_rather_than_coercing_it PASS")


def test_read_returns_empty_when_the_server_is_unreachable(dispatched):
    _, reply = dispatched
    reply["value"] = RuntimeError("connection refused")

    # Empty, not a dict of Falses: every control stays unknown rather than the
    # panel inventing states for an instrument it could not reach.
    assert asyncio.run(read_digital_outs("IO", "127.0.0.1", 8005)) == {}
    print("test_read_returns_empty_when_the_server_is_unreachable PASS")


def test_set_sends_the_name_and_state_and_returns_the_readback(dispatched):
    calls, reply = dispatched
    reply["value"] = ((ErrorCodes.none, {"gamry_aux": True}), ErrorCodes.none)

    states = asyncio.run(
        set_digital_out("IO", "127.0.0.1", 8005, do_name="gamry_aux", on=True)
    )

    assert states == {"gamry_aux": True}
    assert calls[0]["private_action"] == "set_digital_out"
    assert calls[0]["params_dict"] == {"do_name": "gamry_aux", "on": True}
    print("test_set_sends_the_name_and_state_and_returns_the_readback PASS")


def test_set_returns_empty_on_a_refused_name(dispatched):
    _, reply = dispatched
    reply["value"] = ((ErrorCodes.not_available, {}), ErrorCodes.not_available)

    # The write did not land, so the caller must not be told a state.
    assert (
        asyncio.run(set_digital_out("IO", "127.0.0.1", 8005, do_name="nope", on=True))
        == {}
    )
    print("test_set_returns_empty_on_a_refused_name PASS")


def test_set_returns_empty_when_the_call_raises(dispatched):
    _, reply = dispatched
    reply["value"] = RuntimeError("connection refused")

    assert (
        asyncio.run(set_digital_out("IO", "127.0.0.1", 8005, do_name="a", on=False))
        == {}
    )
    print("test_set_returns_empty_when_the_call_raises PASS")


# --------------------------------------------------------------------------
# grouping
# --------------------------------------------------------------------------


def test_grouping_keeps_config_order_within_and_across_groups():
    items = discover_do_items(NI_CFG, ("dev_pump", "dev_gasvalve", "dev_led"))
    grouped = group_do_items(items)

    assert [group for group, _ in grouped] == ["dev_pump", "dev_gasvalve", "dev_led"]
    assert [i.name for i in grouped[1][1]] == ["CO2", "Ar"]
    print("test_grouping_keeps_config_order_within_and_across_groups PASS")


def test_a_declared_but_unconfigured_group_gets_no_section():
    # Both panels render a heading per returned group, so an empty group here
    # would be a heading over nothing.
    items = discover_do_items(NI_CFG, ("dev_pump", "dev_liquidvalve"))
    assert [group for group, _ in group_do_items(items)] == ["dev_pump"]
    print("test_a_declared_but_unconfigured_group_gets_no_section PASS")


def test_every_line_appears_in_exactly_one_group():
    items = discover_do_items(NI_CFG, ("dev_pump", "dev_gasvalve", "dev_led"))
    grouped = group_do_items(items)

    flattened = [item.name for _, in_group in grouped for item in in_group]
    assert flattened == [i.name for i in items]
    assert len(set(flattened)) == len(flattened)
    print("test_every_line_appears_in_exactly_one_group PASS")


def test_the_heading_drops_the_config_prefix():
    assert group_heading("dev_gasvalve") == "gasvalve"
    # Not a `dev_` block at all: passed through rather than mangled.
    assert group_heading("outputs") == "outputs"
    print("test_the_heading_drops_the_config_prefix PASS")
