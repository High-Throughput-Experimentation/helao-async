"""The Bokeh digital-output control panel.

Built against a fake ``Vis`` and a stubbed transport, so no hardware and no
running action server. What matters here is what an engineer sees: that a line
whose state nobody knows does not render like a line that is off, that a failed
write does not leave a control claiming success, and that a click sends the
*opposite* of the state the server last reported rather than of whatever the
button happens to look like.
"""

import asyncio

import pytest
from bokeh.document import Document
from bokeh.models import Button, Div

from helao.core.servers import io_control
from helao.core.servers.io_control_vis import DigitalOutPanel

SERVERS = {
    "IO": {
        "host": "127.0.0.1",
        "port": 8005,
        "params": {"dev_do": {"gamry_aux": 1, "Thorlab_led": 7}},
    },
    "NI": {
        "host": "127.0.0.1",
        "port": 8006,
        "params": {
            "dev_pump": {"PeriPump1": "line9"},
            "dev_gasvalve": {"CO2": "line0", "Ar": "line2"},
        },
    },
    "BARE": {"host": "127.0.0.1", "port": 8007, "params": {}},
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


class _Panel(DigitalOutPanel):
    DO_GROUPS = ("dev_do",)
    TITLE = "Test controls"


class _GroupedPanel(DigitalOutPanel):
    DO_GROUPS = ("dev_pump", "dev_gasvalve")
    TITLE = "Test controls"


@pytest.fixture
def transport(monkeypatch):
    """Script what the private endpoints reply, and record what was sent."""
    sent = []
    script = {"read": {}, "write": {}}

    async def _read(server_key, host, port):
        return dict(script["read"])

    async def _write(server_key, host, port, do_name, on):
        sent.append((do_name, on))
        return dict(script["write"])

    monkeypatch.setattr(io_control, "read_digital_outs", _read)
    monkeypatch.setattr(io_control, "set_digital_out", _write)
    # The panel imported the names directly, so patch them there too.
    import helao.core.servers.io_control_vis as mod

    monkeypatch.setattr(mod, "read_digital_outs", _read)
    monkeypatch.setattr(mod, "set_digital_out", _write)
    return sent, script


def _build(cls, serv_key, doc=None):
    doc = doc or Document()
    panel = cls(_FakeVis(doc), serv_key)
    _drain(doc)
    return panel


def _buttons(panel):
    return {name: btn for name, btn in panel.buttons.items()}


# --------------------------------------------------------------------------


def test_one_control_per_configured_line(transport):
    panel = _build(_Panel, "IO")
    assert set(panel.buttons) == {"gamry_aux", "Thorlab_led"}
    assert all(isinstance(b, Button) for b in panel.buttons.values())
    print("test_one_control_per_configured_line PASS")


def test_a_server_absent_from_the_config_mounts_nothing():
    doc = Document()
    panel = _Panel(_FakeVis(doc), "NOT_IN_CONFIG")
    assert panel.connected is False
    assert not doc.roots, "an absent server must not put anything on the page"
    print("test_a_server_absent_from_the_config_mounts_nothing PASS")


def test_a_server_with_no_outputs_says_so(transport):
    panel = _build(_Panel, "BARE")
    assert panel.buttons == {}
    text = " ".join(
        d.text for d in panel.layout.select({"type": Div})  # type: ignore[arg-type]
    )
    assert "no digital outputs configured" in text, text
    print("test_a_server_with_no_outputs_says_so PASS")


def test_controls_start_unknown_and_look_different_from_off(transport):
    # Nothing scripted for the read, so the panel learns nothing.
    panel = _build(_Panel, "IO")
    button = panel.buttons["gamry_aux"]

    assert panel.states["gamry_aux"] is None
    assert button.label.endswith(": ?"), button.label
    unknown_type = button.button_type

    # Now drive it off and compare: the two must not render the same.
    transport[1]["write"] = {"gamry_aux": False}
    panel._callback_toggle(None, do_name="gamry_aux")
    _drain(panel.vis.doc)

    assert panel.states["gamry_aux"] is False
    assert button.label.endswith(": OFF"), button.label
    assert (
        button.button_type != unknown_type
    ), "unknown and off must be visually distinct"
    print("test_controls_start_unknown_and_look_different_from_off PASS")


def test_open_time_read_populates_every_control(transport):
    _, script = transport
    script["read"] = {"gamry_aux": True, "Thorlab_led": False}

    panel = _build(_Panel, "IO")

    assert panel.states == {"gamry_aux": True, "Thorlab_led": False}
    assert panel.buttons["gamry_aux"].label.endswith(": ON")
    assert panel.buttons["Thorlab_led"].label.endswith(": OFF")
    print("test_open_time_read_populates_every_control PASS")


def test_a_partial_read_leaves_the_rest_unknown(transport):
    _, script = transport
    script["read"] = {"gamry_aux": True, "Thorlab_led": None}

    panel = _build(_Panel, "IO")

    assert panel.states["gamry_aux"] is True
    assert panel.states["Thorlab_led"] is None
    assert "unknown: Thorlab_led" in panel.status_div.text, panel.status_div.text
    print("test_a_partial_read_leaves_the_rest_unknown PASS")


def test_click_sends_the_opposite_of_the_reported_state(transport):
    sent, script = transport
    script["read"] = {"gamry_aux": True, "Thorlab_led": False}
    panel = _build(_Panel, "IO")

    script["write"] = {"gamry_aux": False}
    panel._callback_toggle(None, do_name="gamry_aux")
    _drain(panel.vis.doc)
    assert sent[-1] == ("gamry_aux", False), sent

    script["write"] = {"Thorlab_led": True}
    panel._callback_toggle(None, do_name="Thorlab_led")
    _drain(panel.vis.doc)
    assert sent[-1] == ("Thorlab_led", True), sent
    print("test_click_sends_the_opposite_of_the_reported_state PASS")


def test_clicking_an_unknown_line_drives_it_off(transport):
    # Safe direction for a control whose state nobody knows, and it makes the
    # line definite from then on.
    sent, script = transport
    script["write"] = {"gamry_aux": False}

    panel = _build(_Panel, "IO")
    assert panel.states["gamry_aux"] is None
    panel._callback_toggle(None, do_name="gamry_aux")
    _drain(panel.vis.doc)

    assert sent == [("gamry_aux", False)]
    assert panel.states["gamry_aux"] is False
    print("test_clicking_an_unknown_line_drives_it_off PASS")


def test_a_failed_write_returns_the_control_to_unknown(transport):
    _, script = transport
    script["read"] = {"gamry_aux": True, "Thorlab_led": False}
    panel = _build(_Panel, "IO")
    assert panel.states["gamry_aux"] is True

    script["write"] = {}  # the transport reports failure as an empty dict
    panel._callback_toggle(None, do_name="gamry_aux")
    _drain(panel.vis.doc)

    # NOT False, and not still True: the write may or may not have landed, so
    # the only honest state is unknown.
    assert panel.states["gamry_aux"] is None
    assert panel.buttons["gamry_aux"].label.endswith(": ?")
    assert "unknown" in panel.status_div.text, panel.status_div.text
    print("test_a_failed_write_returns_the_control_to_unknown PASS")


def test_an_unreachable_server_leaves_every_control_unknown(transport):
    _, script = transport
    script["read"] = {}  # transport reports an unreachable server this way

    panel = _build(_Panel, "IO")

    assert all(v is None for v in panel.states.values())
    assert "could not read current state" in panel.status_div.text
    print("test_an_unreachable_server_leaves_every_control_unknown PASS")


def test_a_grouped_server_renders_a_heading_per_group(transport):
    panel = _build(_GroupedPanel, "NI")

    assert set(panel.buttons) == {"PeriPump1", "CO2", "Ar"}
    text = " ".join(
        d.text for d in panel.layout.select({"type": Div})  # type: ignore[arg-type]
    )
    # Headings are the group name without the dev_ prefix; a single-group panel
    # gets none, since it would just repeat "dev_do".
    assert "pump:" in text and "gasvalve:" in text, text

    single = _build(_Panel, "IO", doc=Document())
    single_text = " ".join(
        d.text for d in single.layout.select({"type": Div})  # type: ignore[arg-type]
    )
    assert "do:" not in single_text, single_text
    print("test_a_grouped_server_renders_a_heading_per_group PASS")


def test_a_reply_about_other_lines_does_not_invent_controls(transport):
    # A server that reports more names than this panel was built for must not
    # grow the panel's state behind its back.
    _, script = transport
    script["read"] = {"gamry_aux": True, "surprise": True}

    panel = _build(_Panel, "IO")

    assert set(panel.states) == {"gamry_aux", "Thorlab_led"}
    print("test_a_reply_about_other_lines_does_not_invent_controls PASS")


def test_the_read_button_refetches_every_line(transport):
    _, script = transport
    script["read"] = {"gamry_aux": True, "Thorlab_led": True}
    panel = _build(_Panel, "IO")
    assert panel.states["gamry_aux"] is True

    # A sequence drives the line while the panel is open; the panel cannot
    # know, because it only learns what it commands itself.
    script["read"] = {"gamry_aux": False, "Thorlab_led": True}
    assert panel.states["gamry_aux"] is True, "still showing the stale value"

    panel._callback_read(None)
    _drain(panel.vis.doc)

    assert panel.states["gamry_aux"] is False
    assert panel.buttons["gamry_aux"].label.endswith(": OFF")
    print("test_the_read_button_refetches_every_line PASS")


def test_the_read_button_is_not_a_line_state_colour(transport):
    panel = _build(_Panel, "IO")
    # `primary`, so it cannot be mistaken for a fourth state beside the
    # success/default/warning the controls themselves use.
    assert panel.read_button.button_type == "primary"
    assert panel.read_button.button_type not in {
        b.button_type for b in panel.buttons.values()
    }
    print("test_the_read_button_is_not_a_line_state_colour PASS")


def test_a_server_with_no_outputs_gets_no_read_button(transport):
    panel = _build(_Panel, "BARE")
    labels = [b.label for b in panel.layout.select({"type": Button})]
    assert labels == [], labels
    print("test_a_server_with_no_outputs_gets_no_read_button PASS")
