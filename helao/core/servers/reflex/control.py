"""The Reflex half of the engineering control panel, on ``/control``.

The Bokeh half is ``io_control_vis.DigitalOutPanel``. Both render the same items
and drive the same private endpoints through
:mod:`helao.core.servers.io_control`, which is where the behaviour lives — this
module is a page and a state class, nothing more. Adding a rule to one UI and
not the other is the failure mode that layer exists to prevent.

Like the operator and the data browser, this page is built directly rather than
through the ``PanelTarget`` machinery: that is for WebSocket-fed panels with a
render tick, and a control panel has neither. It reads once when it mounts and
otherwise only when a control is clicked.
"""

__all__ = ["ControlState", "configure_control", "control_page", "control_targets"]

from dataclasses import dataclass

import reflex as rx

from helao.core.servers.reflex.discovery import resolve_panel_module
from helao.core.servers.io_control import (
    discover_do_items,
    group_do_items,
    group_heading,
    read_digital_outs,
    set_digital_out,
    state_label,
)
from helao.core.servers.palette import (
    REFLEX_CONTROL_READ_CLASS,
    reflex_control_button_class,
    reflex_muted_text_class,
)
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: The config key that puts a control panel on this page, matching the Bokeh
#: host's. One key, so a station declares its panels once for both stacks.
CONTROL_VIS_KEY = "control_vis"

#: Filled by :func:`configure_control` at build time. The page is compiled by a
#: separate ``reflex export`` process that has no orchestration group, so the
#: config cannot be read at import.
_CONFIG: dict = {"targets": [], "servers": {}}


@dataclass(frozen=True)
class ControlTarget:
    """One server's worth of controls.

    Attributes:
        server_key: The action server to drive.
        host: Its host.
        port: Its HTTP port.
        title: Heading for its block of controls.
        items: The :class:`~helao.core.servers.io_control.DoItem` list.
    """

    server_key: str
    host: str
    port: int
    title: str
    items: tuple


def control_targets(world_cfg: dict, limit_vis=None) -> list:
    """Discover every server declaring ``control_vis`` and enumerate its lines.

    The panel module is resolved only for its ``DO_GROUPS`` — which ``dev_*``
    blocks that server keeps its outputs in. Everything else about rendering is
    here, so a deployment's Reflex control module is three lines and carries no
    UI code at all.

    Args:
        world_cfg: The loaded HELAO world config.
        limit_vis: Optional allow-list of server keys.

    Returns:
        list[ControlTarget]: In config order. A server whose module will not
        resolve is skipped with a log line rather than taking down the page.
    """
    # A bare string `limit_vis` would degrade membership to a substring test,
    # the same trap `app.as_list` exists for.
    if isinstance(limit_vis, str):
        allowed = [limit_vis]
    else:
        allowed = list(limit_vis or [])
    targets = []
    servers = world_cfg.get("servers")
    if not isinstance(servers, dict):
        return targets
    for server_key, server_cfg in servers.items():
        if not isinstance(server_cfg, dict):
            continue
        module_names = server_cfg.get(CONTROL_VIS_KEY)
        if not module_names:
            continue
        if allowed and server_key not in allowed:
            continue
        if isinstance(module_names, str):
            module_names = [module_names]
        for module_name in module_names:
            try:
                module = resolve_panel_module(module_name)
                groups = module.DO_GROUPS
                title = getattr(module, "TITLE", "Digital output controls")
            except Exception as exc:
                LOGGER.warning(
                    f"control panel '{module_name}' for '{server_key}' did not "
                    f"resolve: {type(exc).__name__}: {exc}"
                )
                continue
            targets.append(
                ControlTarget(
                    server_key=server_key,
                    host=server_cfg.get("host"),
                    port=server_cfg.get("port"),
                    title=title,
                    items=tuple(discover_do_items(server_cfg, groups)),
                )
            )
    return targets


def configure_control(world_cfg: dict, server_key: str) -> None:
    """Bind the page to one orchestration group's config.

    Args:
        world_cfg: The loaded HELAO world config.
        server_key: Config key of the Reflex server entry, for its
            ``limit_vis`` param.
    """
    # Guarded, not `.get` straight through: this runs from ``build_app``, which
    # runs at *import* time, so an ``AttributeError`` on a malformed block does
    # not merely skip the control page — it kills the module and with it the
    # Reflex entrypoint. ``app.as_dict`` does the same job for the same reason;
    # it is reimplemented here rather than imported because ``app`` imports this
    # module.
    servers = world_cfg.get("servers")
    server_cfg = servers.get(server_key) if isinstance(servers, dict) else None
    if not isinstance(server_cfg, dict):
        server_cfg = {}
    params = server_cfg.get("params")
    if not isinstance(params, dict):
        params = {}
    targets = control_targets(world_cfg, limit_vis=params.get("limit_vis"))
    _CONFIG["targets"] = targets
    _CONFIG["servers"] = {t.server_key: t for t in targets}


def _row(target: ControlTarget, item, state) -> list:
    """Flatten one control into the string row the page iterates.

    ``list[list[str]]``, and every element a ``str``: a bare ``list`` fails the
    *frontend build* with ``ForeachVarError`` rather than at import, and a
    non-string element would have to be coerced in the template. The state is
    carried as its own key rather than as a colour so the styling decision stays
    in ``palette``.
    """
    return [
        target.server_key,
        item.name,
        item.group,
        f"{item.name}: {state_label(state)}",
        "unknown" if state is None else ("on" if state else "off"),
    ]


class ControlState(rx.State):
    """Every control on the page, and the last state each one reported.

    A single page-level state rather than one per server: these are a handful
    of buttons with no data stream behind them, so the per-panel mixin
    machinery ``make_panel_state`` exists for would buy nothing here.
    """

    #: ``[server_key, do_name, group, label, state_key]`` per control.
    rows: list[list[str]] = []

    #: What the page says under the controls.
    status: str = ""

    #: Guards the mount read, which Reflex may fire more than once.
    loaded: bool = False

    @rx.event(background=True)
    async def load(self):
        """Read every server's outputs once, when the page mounts.

        Once, not on a timer: these are engineering controls, not a data
        stream. The page therefore shows truth at open plus whatever it has
        commanded since — the same contract the Bokeh panel keeps.
        """
        async with self:
            if self.loaded:
                return
            self.loaded = True
            self.rows = [
                _row(target, item, None)
                for target in _CONFIG["targets"]
                for item in target.items
            ]
            self.status = "reading current state..."
        # The same read the button runs, so the two cannot report differently.
        await self._read_into_rows()

    @rx.event(background=True)
    async def reread(self):
        """Re-read every line on demand.

        Separate from :meth:`load` rather than clearing its guard: ``load``
        must stay idempotent for ``on_mount``, which Reflex can fire more than
        once, while this is the one path that is *supposed* to overwrite what
        the page currently shows. The panel otherwise only learns what it has
        commanded itself, so after a sequence has driven a line this is how an
        engineer gets the truth back without reloading.
        """
        async with self:
            self.status = "reading current state..."
        await self._read_into_rows()

    async def _read_into_rows(self):
        """Read every server once and rebuild ``rows`` from what came back."""
        states: dict = {}
        for target in _CONFIG["targets"]:
            if not target.items:
                continue
            states[target.server_key] = await read_digital_outs(
                server_key=target.server_key, host=target.host, port=target.port
            )
        async with self:
            self.rows = [
                _row(target, item, states.get(target.server_key, {}).get(item.name))
                for target in _CONFIG["targets"]
                for item in target.items
            ]
            # Three outcomes, not two, and they are worth telling apart: a
            # server that did not answer, a server that answered but knows
            # nothing about a line, and a clean read. The middle one is what a
            # write-mirror-only server reports on a fresh start, and calling it
            # "read current state" — as this did — hides the one fact the
            # engineer needs.
            unread = [key for key, got in states.items() if not got]
            unknown = [row[1] for row in self.rows if row[4] == "unknown"]
            parts = []
            if unread:
                parts.append(f"could not read: {', '.join(unread)}")
            if unknown:
                parts.append(f"unknown: {', '.join(unknown)}")
            self.status = "; ".join(parts) if parts else "read current state"

    @rx.event(background=True)
    async def toggle(self, server_key: str, do_name: str):
        """Drive one line to the opposite of the state it last reported.

        An unknown line is driven *off*: the safe direction for a control whose
        current state nobody knows, and it makes the line definite from then on.
        """
        target = _CONFIG["servers"].get(server_key)
        if target is None:
            return

        async with self:
            current = self._state_of(server_key, do_name)
            self.status = f"setting {do_name}..."
        want = False if current is None else (not current)

        reported = await set_digital_out(
            server_key=target.server_key,
            host=target.host,
            port=target.port,
            do_name=do_name,
            on=want,
        )

        async with self:
            if not reported:
                # The write may or may not have landed, so the honest state is
                # unknown — not the value that was asked for.
                self._apply(server_key, do_name, None)
                self.status = f"{do_name}: set failed, state unknown"
            else:
                new_state = reported.get(do_name)
                self._apply(server_key, do_name, new_state)
                self.status = f"{do_name}: {state_label(new_state)}"

    def _state_of(self, server_key: str, do_name: str):
        """Return the state currently rendered for one control."""
        for row in self.rows:
            if row[0] == server_key and row[1] == do_name:
                return {"on": True, "off": False}.get(row[4])
        return None

    def _apply(self, server_key: str, do_name: str, state) -> None:
        """Rewrite one control's row in place, leaving the rest untouched."""
        self.rows = [
            (
                [
                    row[0],
                    row[1],
                    row[2],
                    f"{row[1]}: {state_label(state)}",
                    "unknown" if state is None else ("on" if state else "off"),
                ]
                if row[0] == server_key and row[1] == do_name
                else row
            )
            for row in self.rows
        ]


def _control_button(row):
    """Render one control, coloured by the state it reports."""
    return rx.button(
        row[3],
        on_click=lambda: ControlState.toggle(row[0], row[1]),
        class_name=rx.match(
            row[4],
            ("on", reflex_control_button_class("on")),
            ("off", reflex_control_button_class("off")),
            reflex_control_button_class("unknown"),
        ),
        width="12em",
        size="2",
    )


def _group_block(target: ControlTarget, group: str, with_heading: bool):
    """Render one ``dev_*`` group's controls, under its heading.

    One flat ``rows`` var filtered per group, rather than a var per group:
    ``rows`` is what the event handlers rewrite, so a control repaints wherever
    it is rendered, and a per-group copy would be a second place for the same
    state to live. The filter is on both the server key and the group, since
    ``rows`` is page-wide.
    """
    controls = rx.flex(
        rx.foreach(
            ControlState.rows,
            lambda row: rx.cond(
                (row[0] == target.server_key) & (row[2] == group),
                _control_button(row),
                rx.fragment(),
            ),
        ),
        wrap="wrap",
        spacing="2",
    )
    if not with_heading:
        return controls
    return rx.vstack(
        rx.heading(f"{group_heading(group)}:", size="2"),
        controls,
        align="start",
        spacing="2",
        width="100%",
    )


def _server_block(target: ControlTarget):
    """Render one server's heading and its controls, grouped as configured."""
    if not target.items:
        body = rx.text(
            "no digital outputs configured",
            size="1",
            class_name=reflex_muted_text_class(),
        )
    else:
        # Grouped through the shared layer, so the sections here are the same
        # sections the Bokeh panel shows for the same config. A heading only
        # where there is more than one populated group: on a single-block server
        # it would just repeat "do".
        grouped = group_do_items(target.items)
        body = rx.vstack(
            *[
                _group_block(target, group, with_heading=len(grouped) > 1)
                for group, _ in grouped
            ],
            align="start",
            spacing="3",
            width="100%",
        )
    return rx.card(
        rx.vstack(
            rx.heading(f"{target.title} — {target.server_key}", size="3"),
            body,
            align="start",
            spacing="3",
            width="100%",
        ),
        width="100%",
    )


def control_page():
    """Render the ``/control`` page body."""
    targets = _CONFIG["targets"]
    if not targets:
        return rx.text(
            "No server in this config declares a `control_vis` panel.",
            padding_x="1em",
        )
    return rx.vstack(
        *[_server_block(target) for target in targets],
        rx.hstack(
            rx.button(
                "Read state",
                on_click=ControlState.reread,
                class_name=REFLEX_CONTROL_READ_CLASS,
                size="2",
            ),
            rx.text(
                ControlState.status, size="1", class_name=reflex_muted_text_class()
            ),
            align="center",
            spacing="3",
        ),
        width="100%",
        spacing="4",
        padding_x="1em",
        on_mount=ControlState.load,
    )
