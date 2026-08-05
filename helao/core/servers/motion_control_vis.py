"""The Bokeh half of the motion-axis control panel.

One class, :class:`MotionPanel`, which a deployment's panel module subclasses
with nothing but the name of the config schema its server uses. The axes are
built from the station config at mount time, so a station gains or loses an
axis by editing that server's config block and restarting -- no panel module
changes.

Deliberately **not** a subclass of
:class:`~helao.core.servers.io_control_vis.DigitalOutPanel`. The two panels sit
side by side on the same document and answer to the same ``control_vis`` config
key, but they share no rendering: a digital output is a boolean with a single
button, an axis is a float with four widgets and a confirmation. Sharing a base
would put the 15 digital-output tests at risk on every motion change, and those
tests are the backward-compatibility gate. What the two *do* share is their
backend -- :mod:`helao.core.servers.motion_control`, which is also what the
Reflex half renders from. Behaviour belongs there, not here.
"""

__all__ = ["MotionPanel"]

import time
from functools import partial
from typing import Optional

from bokeh.events import ButtonClick
from bokeh.layouts import Spacer, layout, row
from bokeh.models import Button, Div, NumericInput, Select

from helao.core.servers.bokeh_theme import (
    SECTION_MARGIN,
    semantic_button_stylesheet,
    stretch_section,
)
from helao.core.servers.motion_control import (
    ARM_TIMEOUT_S,
    REFUSED_STATUS,
    Units,
    discover_axes,
    exceeds_warn_threshold,
    move_axis,
    outcome_status,
    position_label,
    read_axis_positions,
    stop_motion,
)
from helao.core.servers.palette import BODY_TEXT, HEADING_TEXT, PANEL_BG, panel_styles
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: Width of one command button. The same width the digital-output toggles use,
#: so the two panels' buttons line up when a server declares both.
BUTTON_WIDTH = 150

#: Width of the axis name, the typed value, and each dropdown. Fixed rather
#: than stretched: a page-wide numeric field reads as a search box.
AXIS_LABEL_WIDTH = 50
VALUE_WIDTH = 110
SELECT_WIDTH = 110

#: Height of one control row's widgets, so the static Divs sit on the same
#: baseline as the inputs beside them.
ROW_HEIGHT = 32

#: The two move modes, in the order they are offered. ``relative`` first and
#: default: it is the mode whose worst case is bounded by what was typed,
#: whereas an absolute coordinate typed into a relative habit is a full-travel
#: move. Plain strings, matching the ``MoveModes`` string-enum values the
#: endpoints take, so this module imports no deployment's enum.
MOVE_MODES = ["relative", "absolute"]


def _now() -> float:
    """Return a monotonic timestamp, for arm expiry.

    Wrapped in a function of its own so the expiry can be exercised without
    sleeping through :data:`~helao.core.servers.motion_control.ARM_TIMEOUT_S`.
    """
    return time.monotonic()


class MotionPanel:
    """A bank of per-axis move controls and a dual-unit position readout.

    Subclasses set :attr:`AXIS_SOURCE` and, optionally, :attr:`TITLE`. The
    constructor signature is the one ``mount_visualizers`` calls, so a panel is
    declared in a config exactly like a visualizer is.

    Attributes:
        AXIS_SOURCE: The config schema this server's axes are declared in, one
            of :data:`~helao.core.servers.motion_control.AXIS_SOURCES`.
        TITLE: Heading shown above the controls.
    """

    #: Overridden per server. **There is deliberately no working default.** The
    #: three schemas state their scale in two opposite orientations, so a panel
    #: that guessed would be wrong by the square of the scale and silent about
    #: it; an unset value is logged by ``discover_axes`` and renders an empty
    #: panel, which is loud in the log and harmless on the stage.
    AXIS_SOURCE: str = ""

    #: Overridden per server.
    TITLE: str = "Motion controls"

    def __init__(self, vis_serv, serv_key: str):
        """Build the panel for ``serv_key`` and mount it on the document.

        Args:
            vis_serv: Host :class:`Vis` server providing the Bokeh document.
            serv_key: Config key of the action server to control. A key absent
                from the config leaves ``connected`` ``False`` and mounts
                nothing, matching how the visualizers handle it.
        """
        self.vis = vis_serv
        self.serv_key = serv_key
        self.serv_config = self.vis.world_cfg["servers"].get(serv_key, None)
        self.connected = self.serv_config is not None
        if not self.connected:
            return

        self.host = self.serv_config.get("host", None)
        self.port = self.serv_config.get("port", None)
        self.items = discover_axes(
            self.serv_config, self.AXIS_SOURCE, server_key=serv_key
        )
        self.items_by_axis = {item.axis: item for item in self.items}
        #: Last known coordinate per axis; every axis starts unknown and the
        #: open-time read fills in what it can. Unknown is never ``0.0`` --
        #: zero is a real motor coordinate.
        self.positions = {
            item.axis: {"mm": None, "counts": None, "moving": None}
            for item in self.items
        }
        #: Per axis, the granted confirmation: ``((value, mode, units), when)``
        #: or ``None``. Bound to the triple it was granted for, so a value
        #: edited after arming cannot execute under the earlier confirmation.
        self.arms: dict[str, Optional[tuple]] = {item.axis: None for item in self.items}

        self.inputs = {}
        self.mode_selects = {}
        self.unit_selects = {}
        self.move_buttons = {}
        self.readouts = {}

        self.status_div = Div(
            text="reading current position...",
            sizing_mode="stretch_width",
            height=15,
            styles={"font-size": "100%", "color": BODY_TEXT},
        )

        docs_url = f"http://{self.host}:{self.port}/docs#/"
        server_link = f'<a href="{docs_url}" target="_blank">\'{self.serv_key}\'</a>'
        header = f"<b>{self.TITLE} for server {server_link}</b>"

        rows = [
            [Spacer(width=20), Div(text=header, sizing_mode="stretch_width", height=15)]
        ]
        if not self.items:
            rows.append(
                [
                    Spacer(width=20),
                    Div(
                        text="<i>no motion axes configured</i>",
                        sizing_mode="stretch_width",
                        height=15,
                        styles={"color": BODY_TEXT},
                    ),
                ]
            )
        else:
            rows.extend(self._build_axis_rows())

        # Re-read on demand. The panel reads once when it opens and otherwise
        # only learns what it has commanded itself, so after a sequence has
        # driven the stage — or after a panel has been left open a while — this
        # is how an engineer gets the truth back without reloading the page.
        # `primary`, so it does not read as one of the move/confirm states.
        self.read_button = Button(
            label="Read position",
            button_type="primary",
            width=BUTTON_WIDTH,
            stylesheets=[semantic_button_stylesheet()],
        )
        self.read_button.on_event(ButtonClick, self._callback_read)
        # `danger`, and it takes a single click: an escape hatch for a stage
        # heading somewhere it should not go must not ask a question first.
        self.stop_button = Button(
            label="Stop motion",
            button_type="danger",
            width=BUTTON_WIDTH,
            stylesheets=[semantic_button_stylesheet()],
        )
        self.stop_button.on_event(ButtonClick, self._callback_stop)
        if self.items:
            rows.append([Spacer(width=20), row(self.read_button, self.stop_button)])
        rows.append([Spacer(width=20), self.status_div])
        rows.append(Spacer(height=10))

        self.layout = stretch_section(
            layout(rows, styles=panel_styles(PANEL_BG), margin=SECTION_MARGIN)
        )
        self.vis.doc.add_root(self.layout)
        self.vis.doc.add_root(Spacer(height=10))

        # Read once, on the next tick rather than here: the document is not
        # servable until this constructor returns, and the read is a network
        # round trip to another server.
        self.vis.doc.add_next_tick_callback(self._refresh_positions)

    def _build_axis_rows(self) -> list:
        """Return the layout rows, one per configured axis."""
        rows = []
        for item in self.items:
            rows.append([Spacer(width=20), self._make_axis_row(item)])
        return rows

    def _make_axis_row(self, item):
        """Build one axis's widgets and wire their callbacks.

        Args:
            item: The :class:`~helao.core.servers.motion_control.AxisItem` to
                render.

        Returns:
            The Bokeh ``row`` holding that axis's controls and readout.
        """
        axis = item.axis
        name = Div(
            text=f"<b>{axis}</b>",
            width=AXIS_LABEL_WIDTH,
            height=ROW_HEIGHT,
            styles={"color": HEADING_TEXT},
        )
        value_input = NumericInput(
            value=0,
            mode="float",
            width=VALUE_WIDTH,
            height=ROW_HEIGHT,
            disabled=not item.move_enabled,
        )
        mode_select = Select(
            value=MOVE_MODES[0],
            options=list(MOVE_MODES),
            width=SELECT_WIDTH,
            height=ROW_HEIGHT,
            disabled=not item.move_enabled,
        )
        # An axis with no configured scale has no millimetre relation at all,
        # so millimetres is not an option it can honestly offer.
        unit_options: list[Optional[str]] = []
        if item.mm_per_count is not None:
            unit_options.append(Units.mm.value)
        if item.has_counts:
            unit_options.append(Units.counts.value)
        if not unit_options:
            unit_options.append(Units.mm.value)
        units_select = Select(
            value=unit_options[0],
            options=unit_options,
            width=SELECT_WIDTH,
            height=ROW_HEIGHT,
            # One option is not a choice; a dropdown offering it is an
            # invitation to look for the other one.
            disabled=not item.move_enabled or len(unit_options) < 2,
        )
        move_button = Button(
            label=f"Move {axis}",
            button_type="success",
            width=BUTTON_WIDTH,
            disabled=not item.move_enabled,
            stylesheets=[semantic_button_stylesheet()],
        )
        move_button.on_event(ButtonClick, partial(self._callback_move, axis=axis))
        # Any edit to the triple a confirmation was granted for revokes it.
        # Without this, arming at 100 and then typing 200 would execute a 200
        # mm move under a confirmation nobody granted for it.
        for widget in (value_input, mode_select, units_select):
            widget.on_change("value", partial(self._on_widget_change, axis=axis))

        readout = Div(
            text=position_label(None, None),
            sizing_mode="stretch_width",
            height=ROW_HEIGHT,
            styles={"color": BODY_TEXT},
        )

        self.inputs[axis] = value_input
        self.mode_selects[axis] = mode_select
        self.unit_selects[axis] = units_select
        self.move_buttons[axis] = move_button
        self.readouts[axis] = readout

        widgets = [name, value_input, mode_select, units_select, move_button]
        if not item.move_enabled:
            # Said once, statically, beside a disabled control. The alternative
            # — leaving the control live and confirming every move, because the
            # threshold is a millimetre quantity this axis cannot express —
            # trains an engineer to dismiss the dialog everywhere.
            widgets.append(
                Div(
                    text="<i>no scale configured; move disabled</i>",
                    width=VALUE_WIDTH * 2,
                    height=ROW_HEIGHT,
                    styles={"color": BODY_TEXT},
                )
            )
        widgets.append(readout)
        return row(*widgets, spacing=4, sizing_mode="stretch_width")

    def _restyle_readout(self, axis: str) -> None:
        """Set one axis's readout from its last known coordinate."""
        readout = self.readouts.get(axis)
        if readout is None:
            return
        known = self.positions.get(axis) or {}
        text = position_label(known.get("mm"), known.get("counts"))
        if known.get("moving"):
            # A coordinate read mid-move is stale the instant it arrives, and
            # a stale number that does not say so reads as a settled position.
            text = f"{text} (moving)"
        readout.text = text

    def _restyle_move(self, axis: str) -> None:
        """Set one axis's move button from whether it is armed."""
        button = self.move_buttons.get(axis)
        if button is None:
            return
        if self.arms.get(axis) is None:
            button.label = f"Move {axis}"
            button.button_type = "success"
        else:
            # Armed must not look like ready, or the second click is
            # indistinguishable from the first.
            button.label = f"Confirm {axis}"
            button.button_type = "warning"

    def _on_widget_change(self, attr, old, new, axis: str) -> None:
        """Revoke ``axis``'s confirmation when its request changes.

        Args:
            attr: Bokeh property name (unused).
            old: Previous value (unused).
            new: New value (unused).
            axis: The axis whose widget changed.
        """
        if self.arms.get(axis) is None:
            return
        self._disarm(axis)
        self.status_div.text = f"{axis}: value changed, confirmation cleared"

    def _disarm(self, axis: str) -> None:
        """Drop any confirmation granted for ``axis``."""
        self.arms[axis] = None
        self._restyle_move(axis)

    def _request(self, axis: str):
        """Return the ``(value, mode, units)`` the widgets currently describe.

        Returns:
            tuple | None: The request, or ``None`` when no value is typed or
            the typed value is not a number.
        """
        raw = self.inputs[axis].value
        if raw is None:
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        return (
            value,
            self.mode_selects[axis].value,
            Units(self.unit_selects[axis].value),
        )

    def _armed_for(self, axis: str, request) -> bool:
        """Whether a live, unexpired confirmation covers exactly ``request``."""
        arm = self.arms.get(axis)
        if arm is None:
            return False
        granted, when = arm
        if granted != request:
            return False
        if _now() - when > ARM_TIMEOUT_S:
            # A confirmation that outlived the attention it was granted under
            # is a confirmation for a move nobody is watching.
            return False
        return True

    def _callback_move(self, event, axis: str) -> None:
        """Arm, or execute, a move on ``axis``.

        Args:
            event: Bokeh ``ButtonClick`` (unused).
            axis: The axis to move.
        """
        self.vis.doc.add_next_tick_callback(partial(self._apply_move, axis=axis))

    async def _apply_move(self, axis: str) -> None:
        """Send one move, or ask for the second click that authorises it."""
        item = self.items_by_axis.get(axis)
        if item is None or not item.move_enabled:
            return
        request = self._request(axis)
        if request is None:
            self.status_div.text = f"{axis}: enter a value to move"
            return
        value, mode, units = request

        if exceeds_warn_threshold(
            item, value, units, self.positions[axis]["mm"], mode
        ) and not self._armed_for(axis, request):
            self.arms[axis] = (request, _now())
            self._restyle_move(axis)
            self.status_div.text = (
                f"{axis}: {value:g} {units.value} {mode} exceeds "
                f"{item.warn_above_mm:g} mm — click Confirm to send"
            )
            return

        # Consumed on use: a confirmation authorises one move, not a session.
        self._disarm(axis)
        self.status_div.text = f"{axis}: moving {value:g} {units.value} ({mode})..."
        error_code, _ = await move_axis(
            server_key=self.serv_key,
            host=self.host,
            port=self.port,
            axis=axis,
            value=value,
            mode=mode,
            units=units,
        )
        status = outcome_status(error_code)
        if not status:
            self.status_div.text = f"{axis}: move sent"
            await self._refresh_positions(clear_status=False)
            return
        self.status_div.text = f"{axis}: {status}"
        if status == REFUSED_STATUS:
            # Refused is not failed: the server made no device call, so the
            # coordinate the panel holds is still the one the server reported.
            # Blanking it would report a fault the instrument does not have.
            return
        # The move may or may not have started, so the only honest coordinate
        # is unknown.
        self.positions[axis] = {"mm": None, "counts": None, "moving": None}
        self._restyle_readout(axis)

    def _callback_stop(self, event) -> None:
        """Halt every axis on this server.

        Args:
            event: Bokeh ``ButtonClick`` (unused).
        """
        self.status_div.text = "stopping..."
        self.vis.doc.add_next_tick_callback(self._apply_stop)

    async def _apply_stop(self) -> None:
        """Send the stop and re-read where everything ended up."""
        # Every arm is dropped: whatever was about to be confirmed is not what
        # anyone wants immediately after hitting stop.
        for axis in self.arms:
            self._disarm(axis)
        error_code, _ = await stop_motion(
            server_key=self.serv_key, host=self.host, port=self.port
        )
        status = outcome_status(error_code)
        if status:
            self.status_div.text = status
            return
        self.status_div.text = "stopped; motors still energized"
        await self._refresh_positions(clear_status=False)

    def _callback_read(self, event) -> None:
        """Re-read every axis on demand.

        Args:
            event: Bokeh ``ButtonClick`` (unused).
        """
        self.status_div.text = "reading current position..."
        self.vis.doc.add_next_tick_callback(self._refresh_positions)

    async def _refresh_positions(self, clear_status: bool = True) -> None:
        """Read every axis once and re-render the whole readout.

        Args:
            clear_status: Whether to replace the status line with the read's
                own summary. ``False`` when the read follows a command, whose
                outcome is the more useful thing to leave on screen.
        """
        if not self.items:
            self.status_div.text = ""
            return
        positions = await read_axis_positions(
            server_key=self.serv_key, host=self.host, port=self.port
        )
        if not positions:
            # No answer at all. Every coordinate goes unknown rather than
            # staying at whatever it last was: a number nobody can confirm is
            # worse than an honest "?".
            for axis in self.positions:
                self.positions[axis] = {"mm": None, "counts": None, "moving": None}
                self._restyle_readout(axis)
            if clear_status:
                self.status_div.text = (
                    "could not read position; axes show unknown until read"
                )
            return
        for axis in self.positions:
            if axis in positions:
                self.positions[axis] = positions[axis]
            self._restyle_readout(axis)
        if not clear_status:
            return
        unknown = [a for a, p in self.positions.items() if p.get("mm") is None]
        self.status_div.text = f"read {len(self.positions) - len(unknown)} of " + (
            f"{len(self.positions)} axes"
            + (f"; unknown mm: {', '.join(unknown)}" if unknown else "")
        )
