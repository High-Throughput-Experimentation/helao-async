"""The Bokeh half of the digital-output control panel.

One class, :class:`DigitalOutPanel`, which a deployment's panel module
subclasses with nothing but the ``dev_*`` group names its server uses. The
contents are built from the station config at mount time, so a station gains or
loses a control by editing that server's config block and restarting — no panel
module changes.

The Reflex half renders the same items from the same
:mod:`helao.core.servers.io_control` layer; behaviour belongs there, not here.
"""

__all__ = ["DigitalOutPanel"]

from functools import partial

from bokeh.events import ButtonClick
from bokeh.layouts import Spacer, layout, row
from bokeh.models import Button, Div

from helao.core.servers.bokeh_theme import (
    SECTION_MARGIN,
    semantic_button_stylesheet,
    stretch_section,
)
from helao.core.servers.io_control import (
    discover_do_items,
    read_digital_outs,
    set_digital_out,
    state_label,
)
from helao.core.servers.palette import BODY_TEXT, HEADING_TEXT, PANEL_BG, panel_styles
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: Width of one toggle. Fixed, not stretched: these are buttons, and a row of
#: page-wide buttons reads as a menu rather than as a bank of controls.
TOGGLE_WIDTH = 150

#: Controls per row before wrapping. A station with twenty lines (ccsi1) needs
#: to wrap; four across keeps a group's controls in view together.
TOGGLES_PER_ROW = 4


class DigitalOutPanel:
    """A bank of toggle buttons, one per configured digital output.

    Subclasses set :attr:`DO_GROUPS` and, optionally, :attr:`TITLE`. The
    constructor signature is the one ``mount_visualizers`` calls, so a panel is
    declared in a config exactly like a visualizer is.

    Attributes:
        DO_GROUPS: ``dev_*`` config blocks to read, in display order.
        TITLE: Heading shown above the controls.
    """

    #: Overridden per server. ``("dev_do",)`` for a single-block server.
    DO_GROUPS: tuple = ("dev_do",)

    #: Overridden per server.
    TITLE: str = "Digital outputs"

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
        self.items = discover_do_items(self.serv_config, self.DO_GROUPS)
        #: Last known state per line; every control starts unknown and the
        #: open-time read fills in what it can.
        self.states = {item.name: None for item in self.items}
        self.buttons = {}

        self.status_div = Div(
            text="reading current state...",
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
                        text="<i>no digital outputs configured</i>",
                        sizing_mode="stretch_width",
                        height=15,
                        styles={"color": BODY_TEXT},
                    ),
                ]
            )
        else:
            rows.extend(self._build_group_rows())
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
        self.vis.doc.add_next_tick_callback(self._refresh_states)

    def _build_group_rows(self) -> list:
        """Return the layout rows for the controls, grouped and wrapped."""
        rows = []
        for group in self.DO_GROUPS:
            in_group = [item for item in self.items if item.group == group]
            if not in_group:
                continue
            if len(self.DO_GROUPS) > 1:
                # Only worth a heading when a server has more than one group;
                # on a single-block server it would just repeat "dev_do".
                rows.append(
                    [
                        Spacer(width=20),
                        Div(
                            text=f"<b>{group.removeprefix('dev_')}:</b>",
                            sizing_mode="stretch_width",
                            height=15,
                            styles={"color": HEADING_TEXT},
                        ),
                    ]
                )
            for start in range(0, len(in_group), TOGGLES_PER_ROW):
                chunk = in_group[start : start + TOGGLES_PER_ROW]
                rows.append(
                    [
                        Spacer(width=20),
                        row(
                            *[self._make_toggle(item) for item in chunk],
                            spacing=4,
                            sizing_mode="stretch_width",
                        ),
                    ]
                )
        return rows

    def _make_toggle(self, item) -> Button:
        """Build one line's button and wire its click.

        A ``Button`` rather than a ``Toggle``: a Toggle's pressed-ness is its
        own state, which would show the *click* rather than the instrument, and
        it has no third position for unknown. This carries the state in its
        label and colour instead, and always reports what the server last said.

        Args:
            item: The :class:`~helao.core.servers.io_control.DoItem` to render.

        Returns:
            Button: The control, already registered in ``self.buttons``.
        """
        button = Button(
            label=self._button_label(item.name),
            button_type="default",
            width=TOGGLE_WIDTH,
            stylesheets=[semantic_button_stylesheet()],
        )
        button.on_event(ButtonClick, partial(self._callback_toggle, do_name=item.name))
        self.buttons[item.name] = button
        self._restyle(item.name)
        return button

    def _button_label(self, do_name: str) -> str:
        """Return ``"<name>: ON|OFF|?"``."""
        return f"{do_name}: {state_label(self.states.get(do_name))}"

    def _restyle(self, do_name: str) -> None:
        """Set a button's label and semantic colour from its state."""
        button = self.buttons.get(do_name)
        if button is None:
            return
        state = self.states.get(do_name)
        button.label = self._button_label(do_name)
        # success for on, default for off, warning for unknown: unknown must
        # not look like either settled state, or the panel misreports the
        # instrument by omission.
        button.button_type = (
            "warning" if state is None else ("success" if state else "default")
        )

    def _callback_toggle(self, event, do_name: str) -> None:
        """Drive a line to the opposite of its known state.

        An unknown line is driven *off* first. That is the safe direction for a
        control whose current state nobody knows, and it makes the line's state
        definite from then on.

        Args:
            event: Bokeh ``ButtonClick`` (unused).
            do_name: The line to drive.
        """
        current = self.states.get(do_name)
        target = False if current is None else (not current)
        self.vis.doc.add_next_tick_callback(
            partial(self._apply_toggle, do_name=do_name, on=target)
        )

    async def _apply_toggle(self, do_name: str, on: bool) -> None:
        """Send one toggle and fold the server's readback into the panel."""
        self.status_div.text = f"setting {do_name} {'on' if on else 'off'}..."
        states = await set_digital_out(
            server_key=self.serv_key,
            host=self.host,
            port=self.port,
            do_name=do_name,
            on=on,
        )
        if not states:
            # The write may or may not have landed, so the honest state is
            # unknown rather than either settled value.
            self.states[do_name] = None
            self.status_div.text = f"{do_name}: set failed, state unknown"
        else:
            self.states.update({k: v for k, v in states.items() if k in self.states})
            self.status_div.text = f"{do_name}: {state_label(self.states[do_name])}"
        self._restyle(do_name)

    async def _refresh_states(self) -> None:
        """Read every line once and restyle the whole bank."""
        if not self.items:
            self.status_div.text = ""
            return
        states = await read_digital_outs(
            server_key=self.serv_key, host=self.host, port=self.port
        )
        if not states:
            self.status_div.text = (
                "could not read current state; controls show unknown until used"
            )
            return
        self.states.update({k: v for k, v in states.items() if k in self.states})
        for do_name in self.states:
            self._restyle(do_name)
        unknown = [n for n, s in self.states.items() if s is None]
        self.status_div.text = (
            f"read {len(self.states) - len(unknown)} of {len(self.states)} lines"
            + (f"; unknown: {', '.join(unknown)}" if unknown else "")
        )
