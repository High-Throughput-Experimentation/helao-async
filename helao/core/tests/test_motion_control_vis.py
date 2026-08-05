"""The Bokeh motion-axis control panel.

Built against a fake ``Vis`` and a stubbed transport, so no hardware and no
running action server. What matters here is what an engineer sees and what the
stage does: that a coordinate nobody has read renders as ``"?"`` rather than as
the origin, that a confirmation granted for one value cannot execute another,
and that a command refused because a sequence is running does not look like a
broken panel.

Fixtures are inline dicts. The letter-keyed and reciprocal blocks carry values
copied from tracked ``helao/deploy/hte`` configs; the name-keyed schema has no
tracked config, so its numbers are stated as bare literals with a provenance
comment. Nothing here reads a config path.
"""

import asyncio

import pytest
from bokeh.document import Document
from bokeh.models import Button, Div, NumericInput, Select

from helao.core.error import ErrorCodes
from helao.core.servers import motion_control_vis as mod
from helao.core.servers.motion_control import (
    ARM_TIMEOUT_S,
    FAILED_STATUS,
    REFUSED_STATUS,
)
from helao.core.servers.motion_control_vis import MotionPanel

SERVERS = {
    # Letter-keyed: `axis_id` maps a name to a controller letter and
    # `count_to_mm` is keyed by that letter. Values from a tracked hte MOTOR
    # block (adss).
    "MOTOR": {
        "host": "127.0.0.1",
        "port": 8003,
        "params": {
            "axis_id": {"x": "C", "y": "B", "z": "A", "Rz": "D"},
            "count_to_mm": {
                "A": 6.314999998973812e-05,
                "B": 0.00015627999999717445,
                "C": 0.00015634000000352077,
                "D": 0.0003169786106003353,
            },
        },
    },
    # Reciprocal: `pos_scale` is counts per millimetre. Values from a tracked
    # hte KMOTOR block (eche10), including its own move limit.
    "KMOTOR": {
        "host": "127.0.0.1",
        "port": 8015,
        "params": {
            "axes": {
                "z": {
                    "serial_no": "49370234",
                    "pos_scale": 1228800.0,
                    "move_limit_mm": 3.0,
                }
            }
        },
    },
    # Name-keyed: `axis_id` maps a name to a serial number and `count_to_mm`
    # is keyed by the axis name. No tracked config has this shape, so the
    # scale is a bare literal: 2.44140625e-06, a 150 mm linear stage.
    "NAMED": {
        "host": "127.0.0.1",
        "port": 8004,
        "params": {
            "axis_id": {"x": "45470574", "y": "45470575"},
            "count_to_mm": {"x": 2.44140625e-06, "y": 2.44140625e-06},
        },
    },
    # DELIBERATELY SYNTHETIC. No shipped config declares an axis with no
    # scale; this exists only to exercise the disabled-control path, which a
    # real-config fixture would pass without ever reaching.
    "SPARSE": {
        "host": "127.0.0.1",
        "port": 8009,
        "params": {"axis_id": {"x": "C"}, "count_to_mm": {}},
    },
    "BARE": {"host": "127.0.0.1", "port": 8010, "params": {}},
}


class _FakeVis:
    def __init__(self, doc):
        self.doc = doc
        self.world_cfg = {"servers": SERVERS}


def _drain(doc):
    """Run whatever the panel queued on the document, including coroutines."""
    for _ in range(8):
        callbacks = list(doc.session_callbacks)
        if not callbacks:
            break
        for cb in callbacks:
            result = cb.callback()
            if asyncio.iscoroutine(result):
                asyncio.run(result)


class _LetterPanel(MotionPanel):
    AXIS_SOURCE = "letter_scale"
    TITLE = "Test motion"


class _InversePanel(MotionPanel):
    AXIS_SOURCE = "inverse_scale"
    TITLE = "Test motion"


class _NamePanel(MotionPanel):
    AXIS_SOURCE = "name_scale"
    TITLE = "Test motion"


@pytest.fixture
def transport(monkeypatch):
    """Script what the private endpoints reply, and record what was sent."""
    sent = []
    script = {
        "read": {},
        "move": (ErrorCodes.none, {}),
        "stop": (ErrorCodes.none, {"stopped": []}),
    }

    async def _read(server_key, host, port):
        return {k: dict(v) for k, v in script["read"].items()}

    async def _move(
        server_key, host, port, axis, value, mode=None, units=None, speed=None
    ):
        sent.append(("move", axis, value, mode, getattr(units, "value", units)))
        return script["move"]

    async def _stop(server_key, host, port):
        sent.append(("stop",))
        return script["stop"]

    # The panel imported the names directly, so patch them there.
    monkeypatch.setattr(mod, "read_axis_positions", _read)
    monkeypatch.setattr(mod, "move_axis", _move)
    monkeypatch.setattr(mod, "stop_motion", _stop)
    return sent, script


@pytest.fixture
def clock(monkeypatch):
    """A settable monotonic clock, so arm expiry needs no sleeping."""
    now = {"t": 1000.0}
    monkeypatch.setattr(mod, "_now", lambda: now["t"])
    return now


def _build(cls, serv_key, doc=None):
    doc = doc or Document()
    panel = cls(_FakeVis(doc), serv_key)
    _drain(doc)
    return panel


def _divs(panel) -> str:
    return " ".join(
        d.text for d in panel.layout.select({"type": Div})  # type: ignore[arg-type]
    )


def _click_move(panel, axis):
    panel._callback_move(None, axis=axis)
    _drain(panel.vis.doc)


# --------------------------------------------------------------------------
# Discovery: one row per configured axis, for each of the three schemas.


def test_one_control_per_configured_axis(transport):
    panel = _build(_LetterPanel, "MOTOR")
    assert set(panel.inputs) == {"x", "y", "z", "Rz"}
    assert set(panel.move_buttons) == {"x", "y", "z", "Rz"}
    assert all(isinstance(w, NumericInput) for w in panel.inputs.values())
    assert all(isinstance(w, Select) for w in panel.mode_selects.values())
    assert all(isinstance(w, Select) for w in panel.unit_selects.values())
    print("test_one_control_per_configured_axis PASS")


def test_the_reciprocal_schema_yields_its_axes(transport):
    panel = _build(_InversePanel, "KMOTOR")
    assert set(panel.inputs) == {"z"}
    # The station states its own move limit, so the panel confirms against it
    # rather than against the generic default.
    assert panel.items_by_axis["z"].warn_above_mm == 3.0
    print("test_the_reciprocal_schema_yields_its_axes PASS")


def test_the_name_keyed_schema_yields_its_axes(transport):
    panel = _build(_NamePanel, "NAMED")
    assert set(panel.inputs) == {"x", "y"}
    assert panel.items_by_axis["x"].mm_per_count == pytest.approx(2.44140625e-06)
    print("test_the_name_keyed_schema_yields_its_axes PASS")


def test_a_server_absent_from_the_config_mounts_nothing():
    doc = Document()
    panel = _LetterPanel(_FakeVis(doc), "NOT_IN_CONFIG")
    assert panel.connected is False
    assert not doc.roots, "an absent server must not put anything on the page"
    print("test_a_server_absent_from_the_config_mounts_nothing PASS")


def test_a_server_with_no_axes_says_so(transport):
    panel = _build(_LetterPanel, "BARE")
    assert panel.inputs == {}
    assert "no motion axes configured" in _divs(panel), _divs(panel)
    # No axes, so nothing to read or stop.
    assert [b.label for b in panel.layout.select({"type": Button})] == []
    print("test_a_server_with_no_axes_says_so PASS")


# --------------------------------------------------------------------------
# The open-time read.


def test_the_open_time_read_is_queued_not_called_inline(transport):
    _, script = transport
    script["read"] = {"x": {"mm": 12.345, "counts": 78963, "moving": False}}

    doc = Document()
    panel = _LetterPanel(_FakeVis(doc), "MOTOR")
    # The document is not servable until the constructor returns, so the read
    # must still be pending here rather than already done.
    assert panel.positions["x"]["mm"] is None
    assert doc.session_callbacks, "the open-time read was not queued"

    _drain(doc)
    assert panel.positions["x"]["mm"] == 12.345
    print("test_the_open_time_read_is_queued_not_called_inline PASS")


def test_the_open_time_read_renders_both_units(transport):
    _, script = transport
    script["read"] = {"x": {"mm": 12.345, "counts": 78963, "moving": False}}

    panel = _build(_LetterPanel, "MOTOR")
    assert panel.readouts["x"].text == "12.345 mm / 78963 counts"
    # Unread axes stay unknown rather than borrowing x's coordinate.
    assert panel.readouts["y"].text == "? mm / ? counts"
    print("test_the_open_time_read_renders_both_units PASS")


def test_a_moving_axis_says_its_coordinate_is_stale(transport):
    _, script = transport
    script["read"] = {"x": {"mm": 1.0, "counts": 6396, "moving": True}}

    panel = _build(_LetterPanel, "MOTOR")
    assert "moving" in panel.readouts["x"].text, panel.readouts["x"].text
    print("test_a_moving_axis_says_its_coordinate_is_stale PASS")


def test_a_failed_read_leaves_every_readout_unknown_never_zero(transport):
    _, script = transport
    script["read"] = {}  # the transport reports an unreachable server this way

    panel = _build(_LetterPanel, "MOTOR")

    for axis, readout in panel.readouts.items():
        assert readout.text == "? mm / ? counts", (axis, readout.text)
        # Zero is a real motor coordinate. A failed read shown as zero is
        # indistinguishable from an axis sitting at its origin.
        assert "0.000" not in readout.text
    assert all(p["mm"] is None for p in panel.positions.values())
    assert "could not read position" in panel.status_div.text
    print("test_a_failed_read_leaves_every_readout_unknown_never_zero PASS")


def test_zero_renders_as_zero_and_not_as_unknown(transport):
    _, script = transport
    script["read"] = {"x": {"mm": 0.0, "counts": 0, "moving": False}}

    panel = _build(_LetterPanel, "MOTOR")
    assert panel.readouts["x"].text == "0.000 mm / 0 counts"
    print("test_zero_renders_as_zero_and_not_as_unknown PASS")


def test_the_read_button_refetches_every_axis(transport):
    _, script = transport
    script["read"] = {"x": {"mm": 1.0, "counts": 6396, "moving": False}}
    panel = _build(_LetterPanel, "MOTOR")
    assert panel.positions["x"]["mm"] == 1.0

    # A sequence drives the stage while the panel is open; the panel cannot
    # know, because it only learns what it commands itself.
    script["read"] = {"x": {"mm": 40.0, "counts": 255853, "moving": False}}
    assert panel.positions["x"]["mm"] == 1.0, "still showing the stale value"

    panel._callback_read(None)
    _drain(panel.vis.doc)
    assert panel.positions["x"]["mm"] == 40.0
    assert panel.readouts["x"].text == "40.000 mm / 255853 counts"
    print("test_the_read_button_refetches_every_axis PASS")


# --------------------------------------------------------------------------
# Button roles.


def test_read_is_primary_and_stop_is_danger(transport):
    panel = _build(_LetterPanel, "MOTOR")
    assert panel.read_button.button_type == "primary"
    assert panel.stop_button.button_type == "danger"
    print("test_read_is_primary_and_stop_is_danger PASS")


def test_no_button_is_default_typed_under_a_custom_stylesheet(transport):
    # `semantic_button_stylesheet()` deliberately never emits a
    # `.bk-btn-default` rule -- the marker chips elsewhere are default buttons
    # with their own override, and a blanket rule would collide with them. A
    # default-typed button here would therefore ship stock-coloured.
    panel = _build(_LetterPanel, "MOTOR")
    buttons = panel.layout.select({"type": Button})
    assert buttons, "expected the panel to mount buttons"
    for button in buttons:
        assert button.button_type != "default", button.label
        assert button.stylesheets, button.label
    print("test_no_button_is_default_typed_under_a_custom_stylesheet PASS")


# --------------------------------------------------------------------------
# The confirmation, and what invalidates it.


def test_a_small_move_needs_no_confirmation(transport):
    sent, script = transport
    script["read"] = {"x": {"mm": 1.0, "counts": 6396, "moving": False}}
    panel = _build(_LetterPanel, "MOTOR")

    panel.inputs["x"].value = 1.0
    _click_move(panel, "x")

    assert sent == [("move", "x", 1.0, "relative", "mm")], sent
    print("test_a_small_move_needs_no_confirmation PASS")


def test_a_large_move_arms_on_the_first_click_and_sends_nothing(transport):
    sent, _ = transport
    panel = _build(_LetterPanel, "MOTOR")

    panel.inputs["x"].value = 100.0
    _click_move(panel, "x")

    assert sent == [], "the first click must not reach the stage"
    assert panel.arms["x"] is not None
    assert panel.move_buttons["x"].button_type == "warning"
    assert panel.move_buttons["x"].label == "Confirm x"
    print("test_a_large_move_arms_on_the_first_click_and_sends_nothing PASS")


def test_the_second_click_sends_the_move_and_consumes_the_arm(transport):
    sent, _ = transport
    panel = _build(_LetterPanel, "MOTOR")

    panel.inputs["x"].value = 100.0
    _click_move(panel, "x")
    _click_move(panel, "x")

    assert sent == [("move", "x", 100.0, "relative", "mm")], sent
    # Consumed on use: a confirmation authorises one move, not a session.
    assert panel.arms["x"] is None
    assert panel.move_buttons["x"].button_type == "success"
    print("test_the_second_click_sends_the_move_and_consumes_the_arm PASS")


def test_editing_the_value_after_arming_revokes_the_confirmation(transport):
    # The sequence this whole mechanism exists for: arm at 100, edit to 200,
    # click. Without the binding, a 200 mm move executes under a confirmation
    # granted for 100.
    sent, _ = transport
    panel = _build(_LetterPanel, "MOTOR")

    panel.inputs["x"].value = 100.0
    _click_move(panel, "x")
    assert panel.arms["x"] is not None

    panel.inputs["x"].value = 200.0
    assert panel.arms["x"] is None, "editing the value must revoke the arm"

    _click_move(panel, "x")
    assert sent == [], "the click after an edit must re-arm, not move"
    assert panel.arms["x"] is not None

    _click_move(panel, "x")
    assert sent == [("move", "x", 200.0, "relative", "mm")], sent
    print("test_editing_the_value_after_arming_revokes_the_confirmation PASS")


def test_changing_the_mode_after_arming_revokes_the_confirmation(transport):
    sent, script = transport
    script["read"] = {"x": {"mm": 0.0, "counts": 0, "moving": False}}
    panel = _build(_LetterPanel, "MOTOR")

    panel.inputs["x"].value = 100.0
    _click_move(panel, "x")
    assert panel.arms["x"] is not None

    panel.mode_selects["x"].value = "absolute"
    assert panel.arms["x"] is None

    _click_move(panel, "x")
    assert sent == [], "the click after a mode change must re-arm, not move"
    print("test_changing_the_mode_after_arming_revokes_the_confirmation PASS")


def test_changing_the_units_after_arming_revokes_the_confirmation(transport):
    sent, _ = transport
    panel = _build(_LetterPanel, "MOTOR")

    panel.inputs["x"].value = 100.0
    _click_move(panel, "x")
    assert panel.arms["x"] is not None

    panel.unit_selects["x"].value = "counts"
    assert panel.arms["x"] is None

    _click_move(panel, "x")
    # 100 counts is 0.0156 mm on this axis -- far below the threshold, so the
    # re-evaluated request needs no confirmation at all and goes straight out.
    assert sent == [("move", "x", 100.0, "relative", "counts")], sent
    print("test_changing_the_units_after_arming_revokes_the_confirmation PASS")


def test_an_arm_expires_after_the_timeout(transport, clock):
    sent, _ = transport
    panel = _build(_LetterPanel, "MOTOR")

    panel.inputs["x"].value = 100.0
    _click_move(panel, "x")
    assert panel.arms["x"] is not None

    clock["t"] += ARM_TIMEOUT_S + 1
    _click_move(panel, "x")
    assert sent == [], "an expired confirmation must not authorise a move"

    # It re-armed, and that fresh arm is honoured.
    clock["t"] += 1
    _click_move(panel, "x")
    assert sent == [("move", "x", 100.0, "relative", "mm")], sent
    print("test_an_arm_expires_after_the_timeout PASS")


def test_an_arm_inside_the_timeout_is_honoured(transport, clock):
    sent, _ = transport
    panel = _build(_LetterPanel, "MOTOR")

    panel.inputs["x"].value = 100.0
    _click_move(panel, "x")
    clock["t"] += ARM_TIMEOUT_S - 1
    _click_move(panel, "x")

    assert sent == [("move", "x", 100.0, "relative", "mm")], sent
    print("test_an_arm_inside_the_timeout_is_honoured PASS")


def test_an_absolute_move_is_judged_by_its_displacement(transport):
    # Absolute 25.0 from a current 24.9 is a 0.1 mm move. Comparing the typed
    # coordinate instead would confirm nearly every absolute move.
    sent, script = transport
    script["read"] = {"x": {"mm": 24.9, "counts": 159274, "moving": False}}
    panel = _build(_LetterPanel, "MOTOR")

    panel.mode_selects["x"].value = "absolute"
    panel.inputs["x"].value = 25.0
    _click_move(panel, "x")

    assert sent == [("move", "x", 25.0, "absolute", "mm")], sent
    print("test_an_absolute_move_is_judged_by_its_displacement PASS")


def test_stopping_revokes_every_pending_confirmation(transport):
    sent, _ = transport
    panel = _build(_LetterPanel, "MOTOR")

    panel.inputs["x"].value = 100.0
    _click_move(panel, "x")
    assert panel.arms["x"] is not None

    panel._callback_stop(None)
    _drain(panel.vis.doc)

    assert ("stop",) in sent
    assert all(arm is None for arm in panel.arms.values())
    assert "energized" in panel.status_div.text, panel.status_div.text
    print("test_stopping_revokes_every_pending_confirmation PASS")


# --------------------------------------------------------------------------
# Command outcomes: sent, failed, and refused.


def test_a_failed_move_returns_the_readout_to_unknown(transport):
    _, script = transport
    script["read"] = {"x": {"mm": 1.0, "counts": 6396, "moving": False}}
    panel = _build(_LetterPanel, "MOTOR")
    assert panel.positions["x"]["mm"] == 1.0

    script["move"] = (ErrorCodes.unspecified, {})
    panel.inputs["x"].value = 1.0
    _click_move(panel, "x")

    # Not still 1.0: the move may or may not have started, so the only honest
    # coordinate is unknown.
    assert panel.positions["x"]["mm"] is None
    assert panel.readouts["x"].text == "? mm / ? counts"
    assert FAILED_STATUS in panel.status_div.text, panel.status_div.text
    print("test_a_failed_move_returns_the_readout_to_unknown PASS")


def test_a_refused_move_is_not_reported_as_a_failure(transport):
    # Refused is a fourth outcome, not a flavour of failed. A generic red
    # failure on a panel whose purpose is reporting what the instrument is
    # doing leads an engineer to conclude the panel itself is broken.
    _, script = transport
    script["read"] = {"x": {"mm": 1.0, "counts": 6396, "moving": False}}
    panel = _build(_LetterPanel, "MOTOR")

    script["move"] = (ErrorCodes.in_progress, {})
    panel.inputs["x"].value = 1.0
    _click_move(panel, "x")

    assert REFUSED_STATUS in panel.status_div.text, panel.status_div.text
    assert FAILED_STATUS not in panel.status_div.text
    # The status names the remedy, not just the cause.
    assert "Stop" in panel.status_div.text
    # No device call was made, so the coordinate the server last reported is
    # still true; blanking it would report a fault the instrument does not have.
    assert panel.positions["x"]["mm"] == 1.0
    assert panel.readouts["x"].text == "1.000 mm / 6396 counts"
    print("test_a_refused_move_is_not_reported_as_a_failure PASS")


def test_a_successful_move_rereads_the_position(transport):
    _, script = transport
    script["read"] = {"x": {"mm": 1.0, "counts": 6396, "moving": False}}
    panel = _build(_LetterPanel, "MOTOR")

    script["read"] = {"x": {"mm": 2.0, "counts": 12793, "moving": False}}
    panel.inputs["x"].value = 1.0
    _click_move(panel, "x")

    assert panel.positions["x"]["mm"] == 2.0
    assert "move sent" in panel.status_div.text, panel.status_div.text
    print("test_a_successful_move_rereads_the_position PASS")


def test_a_move_with_no_value_typed_sends_nothing(transport):
    sent, _ = transport
    panel = _build(_LetterPanel, "MOTOR")

    panel.inputs["x"].value = None
    _click_move(panel, "x")

    assert sent == []
    assert "enter a value" in panel.status_div.text, panel.status_div.text
    print("test_a_move_with_no_value_typed_sends_nothing PASS")


# --------------------------------------------------------------------------
# The scale-less axis (synthetic; no shipped config reaches this).


def test_a_scaleless_axis_is_counts_only_and_cannot_be_moved(transport):
    _, script = transport
    script["read"] = {"x": {"mm": None, "counts": 6396, "moving": False}}
    panel = _build(_LetterPanel, "SPARSE")

    assert panel.items_by_axis["x"].mm_per_count is None
    assert panel.unit_selects["x"].options == ["counts"]
    assert panel.unit_selects["x"].value == "counts"
    # There is no millimetre relation to evaluate a threshold against, so the
    # control says so once rather than confirming every move forever.
    assert panel.move_buttons["x"].disabled is True
    assert panel.inputs["x"].disabled is True
    assert "no scale configured" in _divs(panel), _divs(panel)
    # The readout still works, counts-side only.
    assert panel.readouts["x"].text == "? mm / 6396 counts"
    print("test_a_scaleless_axis_is_counts_only_and_cannot_be_moved PASS")


def test_a_scaleless_axis_sends_nothing_even_if_clicked(transport):
    sent, _ = transport
    panel = _build(_LetterPanel, "SPARSE")

    panel.inputs["x"].value = 100.0
    _click_move(panel, "x")

    assert sent == [], "a disabled control must not reach the stage"
    print("test_a_scaleless_axis_sends_nothing_even_if_clicked PASS")


# --------------------------------------------------------------------------
# T-E5: why the parent repository commits before a deployment names a module.
# Static and non-mutating -- no repository is checked out or modified.


def test_an_absent_panel_module_raises_rather_than_degrading():
    from helao.core.servers.vis_subscriber import import_vis_class

    # Mandatory: the resolution cache is process-wide and never cleared, so a
    # module resolved earlier in this session would make the assertion below
    # pass for the wrong reason.
    import_vis_class.cache_clear()
    with pytest.raises(ModuleNotFoundError):
        import_vis_class("motion_control_module_that_does_not_exist")
    import_vis_class.cache_clear()
    print("test_an_absent_panel_module_raises_rather_than_degrading PASS")


def test_mount_visualizers_does_not_catch_that_import_error():
    # This is what makes the commit order a safety property rather than a
    # preference: a config naming a panel module the parent has not shipped
    # takes down the whole control document, digital outputs included. If a
    # try/except is ever added here, the ordering rule needs restating.
    import inspect

    from helao.core.servers import vis_subscriber

    source = inspect.getsource(vis_subscriber.mount_visualizers)
    assert "import_vis_class(module_name)" in source
    assert "try:" not in source, "the uncaught import path was softened"
    print("test_mount_visualizers_does_not_catch_that_import_error PASS")
