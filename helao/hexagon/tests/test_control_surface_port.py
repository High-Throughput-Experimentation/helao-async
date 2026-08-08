"""The ControlSurface port and its face over the two shared control modules.

Two things are pinned here, and they are different in kind.

*Conformance* is cheap and nearly vacuous on its own: ``runtime_checkable``
compares method **names**, so ``isinstance`` passing proves only that nobody
renamed anything. Every conformance assertion below is therefore paired with a
behavioural one -- each of the five methods is driven against a scripted
dispatcher and its **wire call** is asserted, which is the thing a station
actually depends on.

*Delegation* is the real subject. The adapter must issue byte-identical calls
to the legacy wrappers, because those wrappers carry the short timeout, the
retry counts, and the error-body discard -- three behaviours that a
reimplementation would lose silently, each of which has already cost a
measured failure at a station or in review.
"""

import asyncio
import inspect

import pytest

from helao.core.error import ErrorCodes
from helao.core.servers import io_control, motion_control
from helao.core.servers.motion_control import Units
from helao.hexagon.adapters.vis.control_surface import ControlSurface
from helao.hexagon.ports.control_surface import CONTROL_ROUTES, ControlSurfacePort

SERVER = ("IO", "127.0.0.1", 8005)


@pytest.fixture
def dispatched(monkeypatch):
    """Capture private-dispatcher calls on *both* shared modules, one log.

    One log rather than two, because the port's whole claim is that the five
    routes are one surface: a test that had to know which module a method
    reaches through would have re-created the split the port removes.
    """
    calls: list[dict] = []
    reply: dict = {"value": ({}, ErrorCodes.none)}

    async def _fake(**kwargs):
        calls.append(kwargs)
        result = reply["value"]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(io_control, "async_private_dispatcher", _fake)
    monkeypatch.setattr(motion_control, "async_private_dispatcher", _fake)
    return calls, reply


# --------------------------------------------------------------------------
# conformance
# --------------------------------------------------------------------------


def test_the_adapter_satisfies_the_port():
    assert isinstance(ControlSurface(), ControlSurfacePort)
    print("test_the_adapter_satisfies_the_port PASS")


def test_the_port_covers_exactly_the_five_private_control_routes():
    # Both directions. A method added to the adapter without a route entry is
    # a surface nobody declared; a route entry without a method is a control
    # the panel can name but not reach.
    declared = set(CONTROL_ROUTES.values())
    implemented = {
        name
        for name in dir(ControlSurface)
        if not name.startswith("_") and callable(getattr(ControlSurface, name))
    }
    assert declared == implemented
    assert set(CONTROL_ROUTES) == {
        "get_digital_outs",
        "set_digital_out",
        "get_axis_positions",
        "move_axis",
        "stop_motion",
    }
    print("test_the_port_covers_exactly_the_five_private_control_routes PASS")


def test_every_port_method_is_a_coroutine_function():
    # A sync method would satisfy runtime_checkable just as well and then
    # return a coroutine object the panel awaits nowhere -- a control that
    # silently does nothing.
    for name in CONTROL_ROUTES.values():
        assert inspect.iscoroutinefunction(getattr(ControlSurface, name)), name
    print("test_every_port_method_is_a_coroutine_function PASS")


def test_the_port_imports_nothing_it_may_not():
    # test_boundaries enforces the allow-list repo-wide; this states the two
    # temptations specific to *this* port, because both are what a port author
    # reaches for first and both are banned: ErrorCodes (for the tuple's first
    # element) and motion_control.Units (for the ``units`` parameter).
    import ast

    from helao.hexagon.ports import control_surface as port_module

    tree = ast.parse(inspect.getsource(port_module))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")

    assert imported == {"typing"}
    assert not any(m.startswith("helao.core.servers") for m in imported)
    assert "helao.core.error" not in imported
    print("test_the_port_imports_nothing_it_may_not PASS")


# --------------------------------------------------------------------------
# delegation: each method issues exactly the legacy wrapper's wire call
# --------------------------------------------------------------------------


def test_read_digital_outs_issues_the_wrapper_call(dispatched):
    calls, reply = dispatched
    reply["value"] = ({"gamry_aux": 1, "led": 0}, ErrorCodes.none)

    states = asyncio.run(ControlSurface().read_digital_outs(*SERVER))

    assert states == {"gamry_aux": True, "led": False}
    assert calls == [
        {
            "server_key": "IO",
            "host": "127.0.0.1",
            "port": 8005,
            "private_action": "get_digital_outs",
            "timeout": io_control.CALL_TIMEOUT,
            "retries": io_control.READ_RETRIES,
        }
    ]
    print("test_read_digital_outs_issues_the_wrapper_call PASS")


def test_set_digital_out_issues_the_wrapper_call(dispatched):
    calls, reply = dispatched
    reply["value"] = ({"gamry_aux": True}, ErrorCodes.none)

    states = asyncio.run(
        ControlSurface().set_digital_out(*SERVER, do_name="gamry_aux", on=True)
    )

    assert states == {"gamry_aux": True}
    assert calls[0]["private_action"] == "set_digital_out"
    assert calls[0]["params_dict"] == {"do_name": "gamry_aux", "on": True}
    # A write is worth one more attempt than a read: a dropped write is worse
    # than a slow one. Pinned because the two counts differ by one and a
    # reimplementation would plausibly use whichever it saw first.
    assert calls[0]["retries"] == io_control.WRITE_RETRIES
    assert io_control.WRITE_RETRIES != io_control.READ_RETRIES
    print("test_set_digital_out_issues_the_wrapper_call PASS")


def test_read_axis_positions_issues_the_wrapper_call(dispatched):
    calls, reply = dispatched
    reply["value"] = (
        {"x": {"mm": 12.345, "counts": 78321, "moving": False}},
        ErrorCodes.none,
    )

    positions = asyncio.run(ControlSurface().read_axis_positions(*SERVER))

    assert positions == {"x": {"mm": 12.345, "counts": 78321, "moving": False}}
    assert calls[0]["private_action"] == "get_axis_positions"
    assert calls[0]["timeout"] == motion_control.CALL_TIMEOUT
    assert calls[0]["retries"] == motion_control.READ_RETRIES
    print("test_read_axis_positions_issues_the_wrapper_call PASS")


def test_move_axis_dispatches_the_value_exactly_as_typed(dispatched):
    calls, reply = dispatched
    reply["value"] = ({"axis": "x", "requested": 10000.0}, ErrorCodes.none)

    code, payload = asyncio.run(
        ControlSurface().move_axis(*SERVER, axis="x", value=10000.0, units="counts")
    )

    assert code == ErrorCodes.none
    assert payload == {"axis": "x", "requested": 10000.0}
    # No conversion, no scaling: 10000 counts leaves as 10000. The unit rides
    # alongside as a discriminator, which is the whole reason a mistaken unit
    # is dangerous rather than merely wrong.
    assert calls[0]["params_dict"] == {
        "axis": "x",
        "value": 10000.0,
        "units": "counts",
    }
    print("test_move_axis_dispatches_the_value_exactly_as_typed PASS")


def test_move_axis_omits_mode_and_speed_when_not_given(dispatched):
    calls, _ = dispatched

    asyncio.run(ControlSurface().move_axis(*SERVER, axis="x", value=1.0, units="mm"))

    # Omitted, not defaulted: the server keeps its configured default rather
    # than being told this layer's guess at it.
    assert "mode" not in calls[0]["params_dict"]
    assert "speed" not in calls[0]["params_dict"]
    print("test_move_axis_omits_mode_and_speed_when_not_given PASS")


def test_move_axis_passes_mode_and_speed_through_when_given(dispatched):
    calls, _ = dispatched

    asyncio.run(
        ControlSurface().move_axis(
            *SERVER, axis="x", value=1.0, units="mm", mode="absolute", speed=1000
        )
    )

    assert calls[0]["params_dict"] == {
        "axis": "x",
        "value": 1.0,
        "units": "mm",
        "mode": "absolute",
        "speed": 1000,
    }
    print("test_move_axis_passes_mode_and_speed_through_when_given PASS")


def test_an_enum_unit_and_its_value_string_produce_one_wire_call(dispatched):
    calls, _ = dispatched

    asyncio.run(
        ControlSurface().move_axis(*SERVER, axis="x", value=2.0, units=Units.mm)
    )
    asyncio.run(ControlSurface().move_axis(*SERVER, axis="x", value=2.0, units="mm"))

    # This is what lets the port type ``units`` as ``object``: it may not
    # import the enum, and a caller that has one must not get a different
    # move from a caller that has the string.
    assert calls[0]["params_dict"] == calls[1]["params_dict"]
    assert calls[0]["params_dict"]["units"] == "mm"
    print("test_an_enum_unit_and_its_value_string_produce_one_wire_call PASS")


def test_stop_motion_issues_the_wrapper_call(dispatched):
    calls, reply = dispatched
    reply["value"] = ({"stopped": ["x", "y"]}, ErrorCodes.none)

    code, payload = asyncio.run(ControlSurface().stop_motion(*SERVER))

    assert code == ErrorCodes.none
    assert payload == {"stopped": ["x", "y"]}
    assert calls[0]["private_action"] == "stop_motion"
    assert calls[0]["retries"] == motion_control.WRITE_RETRIES
    print("test_stop_motion_issues_the_wrapper_call PASS")


def test_every_control_call_uses_the_panel_timeout_not_the_dispatcher_default(
    dispatched,
):
    calls, _ = dispatched
    surface = ControlSurface()

    asyncio.run(surface.read_digital_outs(*SERVER))
    asyncio.run(surface.set_digital_out(*SERVER, do_name="d", on=False))
    asyncio.run(surface.read_axis_positions(*SERVER))
    asyncio.run(surface.move_axis(*SERVER, axis="x", value=0.0, units="mm"))
    asyncio.run(surface.stop_motion(*SERVER))

    assert len(calls) == len(CONTROL_ROUTES)
    assert [c["private_action"] for c in calls] == list(CONTROL_ROUTES)
    # 5 s, not the dispatcher's 60. These run on a UI callback: a slow retry
    # does not delay the read, it holds the page blank while it happens.
    assert {c["timeout"] for c in calls} == {5}
    print(
        "test_every_control_call_uses_the_panel_timeout_not_the_dispatcher_default PASS"
    )


# --------------------------------------------------------------------------
# the contract clauses: unknown is a third value; error bodies are discarded
# --------------------------------------------------------------------------


def test_an_error_body_never_becomes_a_phantom_control(dispatched):
    calls, reply = dispatched
    # A 404 from a server without the endpoint. It is still a JSON dict, and
    # parsing it renders a control named "detail" reading ON.
    reply["value"] = ({"detail": "Not Found"}, ErrorCodes.not_available)

    states = asyncio.run(ControlSurface().read_digital_outs(*SERVER))

    assert states == {}
    assert "detail" not in states
    assert calls  # the call was made -- this is a discard, not a short-circuit
    print("test_an_error_body_never_becomes_a_phantom_control PASS")


def test_an_error_body_never_becomes_a_phantom_axis(dispatched):
    _, reply = dispatched
    reply["value"] = ({"detail": "Not Found"}, ErrorCodes.not_available)

    positions = asyncio.run(ControlSurface().read_axis_positions(*SERVER))

    assert positions == {}
    print("test_an_error_body_never_becomes_a_phantom_axis PASS")


def test_a_failed_write_reports_unknown_not_off(dispatched):
    _, reply = dispatched
    reply["value"] = RuntimeError("connection refused")

    states = asyncio.run(
        ControlSurface().set_digital_out(*SERVER, do_name="gamry_aux", on=True)
    )

    # Empty, so the panel shows "?" -- the write may or may not have landed,
    # and either guess misreports the instrument.
    assert states == {}
    assert states.get("gamry_aux") is not False
    print("test_a_failed_write_reports_unknown_not_off PASS")


def test_none_survives_the_round_trip_as_none_never_false(dispatched):
    _, reply = dispatched
    reply["value"] = ({"gamry_aux": None, "led": 0}, ErrorCodes.none)

    states = asyncio.run(ControlSurface().read_digital_outs(*SERVER))

    assert states["gamry_aux"] is None
    assert states["gamry_aux"] is not False
    # And the third value is genuinely distinguishable from the second: a
    # panel that rendered both as "off" would pass a truthiness check.
    assert states["led"] is False
    print("test_none_survives_the_round_trip_as_none_never_false PASS")


def test_an_unread_coordinate_is_none_never_zero(dispatched):
    _, reply = dispatched
    reply["value"] = (
        {
            "x": {"mm": None, "counts": None, "moving": None},
            "y": {"mm": 0.0, "counts": 0, "moving": False},
        },
        ErrorCodes.none,
    )

    positions = asyncio.run(ControlSurface().read_axis_positions(*SERVER))

    assert positions["x"] == {"mm": None, "counts": None, "moving": None}
    # Zero is a legitimate motor coordinate, so the two must not collapse:
    # an axis at its origin and an axis that could not be read look identical
    # the moment unknown renders as 0.
    assert positions["y"] == {"mm": 0.0, "counts": 0, "moving": False}
    assert positions["x"]["mm"] is not positions["y"]["mm"]
    print("test_an_unread_coordinate_is_none_never_zero PASS")


def test_a_non_finite_coordinate_degrades_to_unknown(dispatched):
    _, reply = dispatched
    reply["value"] = ({"x": {"mm": float("nan"), "counts": "?"}}, ErrorCodes.none)

    positions = asyncio.run(ControlSurface().read_axis_positions(*SERVER))

    assert positions["x"] == {"mm": None, "counts": None, "moving": None}
    print("test_a_non_finite_coordinate_degrades_to_unknown PASS")


# --------------------------------------------------------------------------
# transport shapes: both unwraps reach one coercion
# --------------------------------------------------------------------------


def test_the_rpc_tuple_and_the_http_list_decode_identically(dispatched):
    _, reply = dispatched
    surface = ControlSurface()

    reply["value"] = ((ErrorCodes.none, {"led": 1}), ErrorCodes.none)
    rpc = asyncio.run(surface.read_digital_outs(*SERVER))
    # The HTTP fallback JSON-decodes the same reply to a two-element list, and
    # the enum arrives as its string value.
    reply["value"] = (["none", {"led": 1}], ErrorCodes.none)
    http = asyncio.run(surface.read_digital_outs(*SERVER))

    assert rpc == http == {"led": True}
    print("test_the_rpc_tuple_and_the_http_list_decode_identically PASS")


def test_the_two_transports_agree_on_axis_positions_too(dispatched):
    _, reply = dispatched
    surface = ControlSurface()
    axes = {"x": {"mm": 1.5, "counts": 3000, "moving": True}}

    reply["value"] = ((ErrorCodes.none, axes), ErrorCodes.none)
    rpc = asyncio.run(surface.read_axis_positions(*SERVER))
    reply["value"] = (["none", axes], ErrorCodes.none)
    http = asyncio.run(surface.read_axis_positions(*SERVER))

    assert rpc == http == axes
    print("test_the_two_transports_agree_on_axis_positions_too PASS")


def test_the_gclib_string_coercion_stays_on_the_server_side(dispatched):
    """The one coercion function is the server's, and must not be duplicated.

    ``MG @OUT[port]`` comes back from gclib as ``" 0.0000"`` -- a *non-empty
    string*, so ``bool()`` of it is ``True``. The single place that turns that
    into a state is ``galil_io.do_value_to_bool`` (``bool(float(...))``, tested
    beside it), which is why this side does a plain ``bool()`` and why that is
    correct: by the time a reply reaches the client the value is already a
    JSON bool or number.

    This test pins the boundary in the direction that fails silently. If a
    server is ever written that returns the raw device string, the panel reads
    a de-energised line as ON -- so the fix belongs in that server's coercion,
    never here: adding a ``float()`` on this side would make a legitimate
    ``"0"``-shaped payload and an error string differ by nothing visible.
    """
    _, reply = dispatched
    reply["value"] = ({"led": " 0.0000"}, ErrorCodes.none)

    states = asyncio.run(ControlSurface().read_digital_outs(*SERVER))

    assert states == {"led": True}, (
        "client-side coercion changed; if this now reads False, the gclib "
        "string rule was duplicated here instead of staying in "
        "galil_io.do_value_to_bool"
    )
    print("test_the_gclib_string_coercion_stays_on_the_server_side PASS")
