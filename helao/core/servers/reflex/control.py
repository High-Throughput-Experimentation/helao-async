"""The Reflex half of the engineering control panel, on ``/control``.

The Bokeh halves are ``io_control_vis.DigitalOutPanel`` and
``motion_control_vis.MotionPanel``. Both stacks render the same items and drive
the same private endpoints through :mod:`helao.core.servers.io_control` and
:mod:`helao.core.servers.motion_control`, which is where the behaviour lives —
this module is a page and a state class, nothing more. Adding a rule to one UI
and not the other is the failure mode those layers exist to prevent, so nothing
here decides when to confirm a move, what a scale is, or what an unread
coordinate looks like.

Two kinds of control share the page, and they share nothing else: digital
outputs are booleans in :attr:`ControlState.rows`, axes are coordinates and
typed input in :attr:`ControlState.motion_rows`. Two vars, two builders, one
read pass — a single row shape would have to carry a value, a mode and a unit
for a control that has none of them.

Like the operator and the data browser, this page is built directly rather than
through the ``PanelTarget`` machinery: that is for WebSocket-fed panels with a
render tick, and a control panel has neither. It reads once when it mounts,
after every command, and otherwise only when a control is clicked. Never on a
timer: ``on_unmount`` does not fire when a tab is closed, so a server-side
refresh loop would go on polling a station's motion servers forever after the
browser is gone.
"""

__all__ = ["ControlState", "configure_control", "control_page", "control_targets"]

import time
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
from helao.core.servers.motion_control import (
    ARM_TIMEOUT_S,
    FAILED_STATUS,
    Units,
    discover_axes,
    exceeds_warn_threshold,
    move_axis,
    outcome_status,
    position_label,
    read_axis_positions,
    stop_motion,
)
from helao.core.servers.palette import (
    REFLEX_CONTROL_READ_CLASS,
    REFLEX_MOTION_INPUT_CLASS,
    REFLEX_MOTION_READOUT_CLASS,
    REFLEX_MOTION_STOP_CLASS,
    reflex_control_button_class,
    reflex_motion_move_class,
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


#: The two move modes, in the order the dropdown offers them. Relative first
#: because it is the default and the smaller of the two mistakes: a relative
#: move of a wrongly-typed value goes somewhere near where the stage already is.
MOVE_MODES = ["relative", "absolute"]

#: The unit dropdown's options, from the shared enum so the page cannot offer a
#: unit the endpoint would 422 on.
UNIT_NAMES = [unit.value for unit in Units]

# Column indices into a motion row. Named, because the rows are flat lists of
# strings -- which is what ``rx.foreach`` can iterate -- and ``row[7]`` at a
# call site says nothing about which of eleven strings it is.
(
    MOTION_SERVER,
    MOTION_AXIS,
    MOTION_LABEL,
    MOTION_VALUE,
    MOTION_MODE,
    MOTION_UNITS,
    MOTION_ARM,
    MOTION_ENABLED,
    MOTION_MOVING,
    MOTION_ARM_UNTIL,
    MOTION_MM,
) = range(11)


@dataclass(frozen=True)
class ControlTarget:
    """One server's worth of controls.

    Attributes:
        server_key: The action server to drive.
        host: Its host.
        port: Its HTTP port.
        title: Heading for its block of controls.
        items: The :class:`~helao.core.servers.io_control.DoItem` list.
        axes: The :class:`~helao.core.servers.motion_control.AxisItem` list.
            Defaulted, so a deployment's existing three-line digital-output
            panel module keeps working with no edit.
        axis_source: The panel module's ``AXIS_SOURCE``, or ``""``. Kept
            alongside ``axes`` because an empty ``axes`` is ambiguous on its
            own -- a motion server whose config declares no axis and a digital
            server that has none are the same tuple, and they need different
            things said about them.
    """

    server_key: str
    host: str
    port: int
    title: str
    items: tuple
    axes: tuple = ()
    axis_source: str = ""


def control_targets(world_cfg: dict, limit_vis=None) -> list:
    """Discover every server declaring ``control_vis`` and enumerate its lines.

    The panel module is resolved only for its ``DO_GROUPS`` — which ``dev_*``
    blocks that server keeps its outputs in — and its ``AXIS_SOURCE``, which of
    the three shipped config schemas its axes are declared in. Everything else
    about rendering is here, so a deployment's Reflex control module is three
    lines and carries no UI code at all.

    Both selectors are read with ``getattr``: a module declares whichever of
    the two kinds of control its server has, and neither is mandatory.

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
                # ``getattr``, not a hard read. A motion panel module declares
                # no ``DO_GROUPS`` at all, and ``module.DO_GROUPS`` raised
                # straight into the handler below -- which does not take the
                # page down, it *drops the panel*. A station's motion controls
                # would simply never have appeared, indistinguishable from a
                # mistyped module name.
                groups = getattr(module, "DO_GROUPS", ())
                axis_source = getattr(module, "AXIS_SOURCE", None)
                # A default per kind, so a module that declares only its
                # selector still gets an honest heading. Panel modules name
                # themselves; this is for the ones that do not.
                title = getattr(
                    module,
                    "TITLE",
                    (
                        "Motion controls"
                        if axis_source and not groups
                        else "Digital output controls"
                    ),
                )
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
                    # Called only when the module names a schema. Handing
                    # ``None`` to ``discover_axes`` is an error there by
                    # design, and every digital-output panel in every
                    # deployment would log one on every page build.
                    axes=(
                        tuple(
                            discover_axes(
                                server_cfg, axis_source, server_key=server_key
                            )
                        )
                        if axis_source is not None
                        else ()
                    ),
                    axis_source="" if axis_source is None else str(axis_source),
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


def _now() -> float:
    """Return the clock the arm timeout counts in.

    Monotonic, not wall clock: a confirmation must not be extended or expired
    by an NTP step, and the panel only ever asks how long ago the click was.
    A function rather than a direct call so a test can hold time still.
    """
    return time.monotonic()


def _as_float(text: str):
    """Parse a coordinate the row carries as text, or ``None``.

    ``None`` rather than ``0.0`` on anything unparseable, because that value
    goes on to be an absolute move's current position -- and a zero there would
    turn "we have not read this axis" into "the axis is at its origin", which
    is the one substitution the shared layer exists to prevent.
    """
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _motion_row(target: ControlTarget, item, position, previous=None) -> list:
    """Flatten one axis into the string row the page iterates.

    ``list[list[str]]`` for the same reason ``_row`` is: a bare ``list`` fails
    the *frontend build* with ``ForeachVarError`` rather than at import, so it
    looks fine until ``reflex export`` runs at a station with no Node.

    The row carries both what the instrument reported and what the engineer has
    typed, and rebuilding one from a fresh read must not discard the other --
    hence ``previous``. Losing a half-typed value on every position read would
    make the panel unusable in exactly the way that is hardest to reproduce.

    Args:
        target: The server the axis belongs to.
        item: The :class:`~helao.core.servers.motion_control.AxisItem`.
        position: What the server reported for this axis, or ``{}``.
        previous: This axis's current row, when there is one.
    """
    position = position or {}
    mm = position.get("mm")
    counts = position.get("counts")
    moving = position.get("moving")
    if previous is None:
        value = ""
        mode = MOVE_MODES[0]
        # An axis with no configured scale has no millimetre relation, so
        # counts is the only unit it could honestly be driven in -- the same
        # conclusion that disables its control, said in the dropdown too.
        units = Units.mm.value if item.move_enabled else Units.counts.value
        arm = "ready"
        arm_until = ""
    else:
        value = previous[MOTION_VALUE]
        mode = previous[MOTION_MODE]
        units = previous[MOTION_UNITS]
        arm = previous[MOTION_ARM]
        arm_until = previous[MOTION_ARM_UNTIL]
    return [
        target.server_key,
        item.axis,
        # The readout is the shared renderer's, not this page's: unknown has to
        # look the same in both stacks, and it must never render as 0.
        position_label(mm, counts),
        value,
        mode,
        units,
        arm,
        "enabled" if item.move_enabled else "disabled",
        "unknown" if moving is None else ("moving" if moving else "stopped"),
        arm_until,
        # Kept as text beside the rendered label because an absolute move needs
        # the number, and parsing it back out of the label would make the
        # label's format load-bearing.
        "" if mm is None else repr(float(mm)),
    ]


class ControlState(rx.State):
    """Every control on the page, and the last state each one reported.

    A single page-level state rather than one per server: these are a handful
    of buttons with no data stream behind them, so the per-panel mixin
    machinery ``make_panel_state`` exists for would buy nothing here. That is a
    property of *this* page, not general advice -- a var on a concrete
    ``rx.State`` is shared by every substate under it, which is why panels fed
    by a WebSocket build theirs through ``make_panel_state`` instead.
    """

    #: ``[server_key, do_name, group, label, state_key]`` per control.
    rows: list[list[str]] = []

    #: ``[server_key, axis, readout, value, mode, units, arm, enabled, moving,
    #: arm_until, mm]`` per axis -- the indices named above.
    #:
    #: Deliberately **not** merged into :attr:`rows`. A digital output is one
    #: boolean and a name; an axis is a coordinate, a typed value, a mode, a
    #: unit and a confirmation state. One row shape would carry six empty
    #: strings for every digital output on the page and would make the two
    #: kinds of control repaint each other.
    motion_rows: list[list[str]] = []

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
            self.motion_rows = [
                _motion_row(target, item, {})
                for target in _CONFIG["targets"]
                for item in target.axes
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
        """Read every server once and rebuild both row sets from what came back.

        One read pass over both kinds of control, so the mount read and the
        "Read state" button each cover the whole page. A second mount handler
        for the axes would be a second thing to forget, and Reflex fires
        ``on_mount`` more than once, so it would need its own guard too.
        """
        states: dict = {}
        positions: dict = {}
        for target in _CONFIG["targets"]:
            if target.items:
                states[target.server_key] = await read_digital_outs(
                    server_key=target.server_key, host=target.host, port=target.port
                )
            if target.axes:
                positions[target.server_key] = await read_axis_positions(
                    server_key=target.server_key, host=target.host, port=target.port
                )
        async with self:
            self.rows = [
                _row(target, item, states.get(target.server_key, {}).get(item.name))
                for target in _CONFIG["targets"]
                for item in target.items
            ]
            # Guarded rather than assigned unconditionally: a config with no
            # motion server has no motion rows to rebuild, and this keeps the
            # digital-output path exactly what it was.
            unknown_axes: list = []
            if positions:
                self.motion_rows, unknown_axes = self._motion_from(positions)
            # Three outcomes, not two, and they are worth telling apart: a
            # server that did not answer, a server that answered but knows
            # nothing about a line, and a clean read. The middle one is what a
            # write-mirror-only server reports on a fresh start, and calling it
            # "read current state" — as this did — hides the one fact the
            # engineer needs.
            unread = [key for key, got in states.items() if not got]
            unread += [
                key for key, got in positions.items() if not got and key not in unread
            ]
            unknown = [row[1] for row in self.rows if row[4] == "unknown"]
            parts = []
            if unread:
                parts.append(f"could not read: {', '.join(unread)}")
            if unknown:
                parts.append(f"unknown: {', '.join(unknown)}")
            if unknown_axes:
                # Axis-level, and only for servers that answered: a server that
                # said nothing is already named above, and listing every one of
                # its axes again would bury the servers that did answer.
                parts.append(f"position unknown: {', '.join(unknown_axes)}")
            self.status = "; ".join(parts) if parts else "read current state"

    def _motion_from(self, positions: dict) -> tuple:
        """Rebuild every motion row from a read, keeping what has been typed.

        Args:
            positions: ``{server_key: {axis: {...}}}`` as read this pass.

        Returns:
            tuple: ``(rows, unknown)`` -- the rows, and ``"SERVER axis"`` for
            each axis a *reachable* server reported nothing usable for. The two
            are computed together because the second is only knowable from the
            reply, not from the row it produced.
        """
        previous = {
            (row[MOTION_SERVER], row[MOTION_AXIS]): row for row in self.motion_rows
        }
        rows: list = []
        unknown: list = []
        for target in _CONFIG["targets"]:
            if not target.axes:
                continue
            got = positions.get(target.server_key) or {}
            for item in target.axes:
                position = got.get(item.axis) or {}
                rows.append(
                    _motion_row(
                        target,
                        item,
                        position,
                        previous.get((target.server_key, item.axis)),
                    )
                )
                if (
                    got
                    and position.get("mm") is None
                    and position.get("counts") is None
                ):
                    unknown.append(f"{target.server_key} {item.axis}")
        return rows, unknown

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

    # -- motion ------------------------------------------------------------
    # Separate events on a separate var, sharing only the read pass above.

    @rx.event
    def set_move_value(self, server_key: str, axis: str, value: str):
        """Record what has been typed into one axis's move field.

        Not a background event: it does no I/O, and a keystroke that has to
        wait on the event loop's I/O lane feels broken. It **disarms**, which
        is the point of routing every widget through a handler at all -- see
        :meth:`move`.
        """
        self._rewrite_motion(server_key, axis, {MOTION_VALUE: str(value)})

    @rx.event
    def set_move_mode(self, server_key: str, axis: str, mode: str):
        """Record one axis's move mode, and disarm.

        The dropdown's value arrives as a string and is checked against the
        two legal ones rather than trusted: a value this page does not
        recognise must become the *safer* mode, not travel to the endpoint.
        """
        chosen = str(getattr(mode, "value", mode))
        self._rewrite_motion(
            server_key,
            axis,
            {MOTION_MODE: chosen if chosen in MOVE_MODES else MOVE_MODES[0]},
        )

    @rx.event
    def set_move_units(self, server_key: str, axis: str, units: str):
        """Record one axis's move units, and disarm.

        Coerced through the shared enum's own values. This is the widget where
        an unchecked assumption costs the most: ``"count"`` reaching an
        endpoint that compares against ``"counts"`` would execute a
        ten-thousand-*count* move as ten thousand *millimetres*.
        """
        chosen = str(getattr(units, "value", units))
        self._rewrite_motion(
            server_key,
            axis,
            {MOTION_UNITS: chosen if chosen in UNIT_NAMES else Units.mm.value},
        )

    @rx.event(background=True)
    async def move(self, server_key: str, axis: str):
        """Move one axis, asking first when the move is a large one.

        **The confirmation is bound to the value, mode and units it was granted
        for**, and every one of those widgets disarms on change. Without that
        binding: type 100, click (arms), change to 200, click -- and a 200 mm
        move executes under a confirmation granted for 100. It also expires
        after ``ARM_TIMEOUT_S``, because an arm that outlived the attention it
        was granted under is a confirmation for a move nobody is watching.

        Whether a move is large enough to ask about is
        :func:`~helao.core.servers.motion_control.exceeds_warn_threshold`'s
        decision, not this page's, so the two stacks cannot come to disagree --
        and a UI that quietly stopped asking would look identical to one that
        never needed to.
        """
        target = _CONFIG["servers"].get(server_key)
        if target is None:
            return
        item = next((a for a in target.axes if a.axis == axis), None)
        if item is None:
            return

        async with self:
            row = self._motion_row_of(server_key, axis)
            if row is None:
                return
            if not item.move_enabled:
                # The control is disabled, so arriving here means something
                # bypassed it. Say so rather than dispatching a move whose size
                # nothing on this page can judge.
                self.status = f"{axis}: no scale configured, so moves are disabled"
                return
            value = _as_float(row[MOTION_VALUE])
            if value is None:
                self.status = f"{axis}: type a move value first"
                return
            mode = row[MOTION_MODE]
            units = (
                Units(row[MOTION_UNITS])
                if row[MOTION_UNITS] in UNIT_NAMES
                else Units.mm
            )
            armed = row[MOTION_ARM] == "armed" and (
                (_as_float(row[MOTION_ARM_UNTIL]) or 0.0) > _now()
            )
            if not armed and exceeds_warn_threshold(
                item, value, units, _as_float(row[MOTION_MM]), mode
            ):
                self._rewrite_motion(
                    server_key,
                    axis,
                    {
                        MOTION_ARM: "armed",
                        MOTION_ARM_UNTIL: repr(_now() + ARM_TIMEOUT_S),
                    },
                    disarm=False,
                )
                self.status = (
                    f"{axis}: {row[MOTION_VALUE]} {units.value} {mode} is a large "
                    f"move — click Confirm move within {ARM_TIMEOUT_S}s to go ahead"
                )
                return
            self.status = f"moving {axis}..."

        error_code, _payload = await move_axis(
            server_key=target.server_key,
            host=target.host,
            port=target.port,
            axis=axis,
            value=value,
            mode=mode,
            units=units,
        )
        note = outcome_status(error_code)

        async with self:
            # The confirmation is spent either way: a refused move that stayed
            # armed would go the moment the sequence ended, with no second click.
            self._rewrite_motion(server_key, axis, {})
            if note == FAILED_STATUS:
                # The same contract a failed digital write keeps: the command
                # may or may not have landed, so the coordinate is unknown
                # rather than whatever it was before.
                self._blank_position(server_key, axis)
            if note:
                # Refused is not failed. The endpoint declining because a
                # sequence is running means the panel is working, and the
                # status says so and names the remedy.
                self.status = f"{axis}: {note}"
                return

        await self._refresh_positions(server_key)
        async with self:
            self.status = f"{axis}: move commanded"

    @rx.event(background=True)
    async def stop(self, server_key: str):
        """Halt every axis on one server, leaving its motors energized.

        Unconditional by design: an escape hatch for a stage heading somewhere
        it should not go must not depend on the orchestrator being responsive.
        The consequence is stated at the endpoint rather than hidden -- a
        sequence mid-move is not notified, so its run record can describe a
        move that did not finish where it says.

        Positions are re-read whatever the answer: a stop that landed leaves
        the stage at a coordinate the panel has never seen, and a stop that did
        not is exactly when an engineer most needs the readout refreshed.
        """
        target = _CONFIG["servers"].get(server_key)
        if target is None:
            return
        async with self:
            self.status = f"stopping {server_key}..."

        error_code, payload = await stop_motion(
            server_key=target.server_key, host=target.host, port=target.port
        )
        await self._refresh_positions(server_key)

        async with self:
            for item in target.axes:
                # A stop spends every arm on the server: whatever was about to
                # be confirmed is not what anyone wants to happen next.
                self._rewrite_motion(server_key, item.axis, {})
            note = outcome_status(error_code)
            if note:
                self.status = f"{server_key}: {note}"
                return
            stopped = payload.get("stopped")
            if not isinstance(stopped, (list, tuple)) or not stopped:
                stopped = [item.axis for item in target.axes]
            self.status = f"{server_key}: stopped {', '.join(str(a) for a in stopped)}"

    async def _refresh_positions(self, server_key: str) -> None:
        """Re-read one server's coordinates, leaving every other row alone.

        Targeted rather than a whole-page read: a move must not restate every
        digital output on the page, and a station's other servers have nothing
        to say about an axis that just moved.
        """
        target = _CONFIG["servers"].get(server_key)
        if target is None or not target.axes:
            return
        got = await read_axis_positions(
            server_key=target.server_key, host=target.host, port=target.port
        )
        async with self:
            axes = {item.axis: item for item in target.axes}
            self.motion_rows = [
                (
                    _motion_row(
                        target,
                        axes[row[MOTION_AXIS]],
                        got.get(row[MOTION_AXIS]) or {},
                        row,
                    )
                    if row[MOTION_SERVER] == server_key and row[MOTION_AXIS] in axes
                    else row
                )
                for row in self.motion_rows
            ]

    def _motion_row_of(self, server_key: str, axis: str):
        """Return the row currently rendered for one axis, or ``None``."""
        for row in self.motion_rows:
            if row[MOTION_SERVER] == server_key and row[MOTION_AXIS] == axis:
                return row
        return None

    def _rewrite_motion(
        self, server_key: str, axis: str, changes: dict, *, disarm: bool = True
    ) -> None:
        """Rewrite one axis's row in place, leaving the rest untouched.

        Args:
            server_key: The server owning the axis.
            axis: The axis name.
            changes: ``{column index: new value}``.
            disarm: Whether to spend any granted confirmation. **The default,
                deliberately**: every caller but the one that arms is a change
                to what was confirmed or to whether it still applies, so
                forgetting to disarm has to be the thing that takes an argument.
        """
        if disarm:
            changes = {**changes, MOTION_ARM: "ready", MOTION_ARM_UNTIL: ""}
        self.motion_rows = [
            (
                [changes.get(index, cell) for index, cell in enumerate(row)]
                if row[MOTION_SERVER] == server_key and row[MOTION_AXIS] == axis
                else row
            )
            for row in self.motion_rows
        ]

    def _blank_position(self, server_key: str, axis: str) -> None:
        """Return one axis's readout to unknown, through the shared renderer."""
        self._rewrite_motion(
            server_key,
            axis,
            {
                MOTION_LABEL: position_label(None, None),
                MOTION_MOVING: "unknown",
                MOTION_MM: "",
            },
        )


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


def _axis_block(target: ControlTarget, row):
    """Render one axis: its controls, then what it last reported.

    Every widget carries an ``on_change`` rather than being read at click time,
    because changing any of the three is what invalidates a confirmation --
    see :meth:`ControlState.move`.
    """
    disabled = row[MOTION_ENABLED] == "disabled"
    return rx.hstack(
        rx.text(row[MOTION_AXIS], size="2", width="4em"),
        rx.input(
            value=row[MOTION_VALUE],
            on_change=lambda value: ControlState.set_move_value(
                row[MOTION_SERVER], row[MOTION_AXIS], value
            ),
            disabled=disabled,
            class_name=REFLEX_MOTION_INPUT_CLASS,
            placeholder="value",
            width="8em",
            size="2",
        ),
        rx.select(
            MOVE_MODES,
            value=row[MOTION_MODE],
            on_change=lambda mode: ControlState.set_move_mode(
                row[MOTION_SERVER], row[MOTION_AXIS], mode
            ),
            disabled=disabled,
            size="2",
        ),
        rx.select(
            UNIT_NAMES,
            value=row[MOTION_UNITS],
            on_change=lambda units: ControlState.set_move_units(
                row[MOTION_SERVER], row[MOTION_AXIS], units
            ),
            disabled=disabled,
            size="2",
        ),
        rx.button(
            rx.match(row[MOTION_ARM], ("armed", "Confirm move"), "Move"),
            on_click=lambda: ControlState.move(row[MOTION_SERVER], row[MOTION_AXIS]),
            disabled=disabled,
            class_name=rx.match(
                row[MOTION_ARM],
                ("armed", reflex_motion_move_class("armed")),
                reflex_motion_move_class("ready"),
            ),
            width="9em",
            size="2",
        ),
        rx.text(row[MOTION_LABEL], size="2", class_name=REFLEX_MOTION_READOUT_CLASS),
        # Surfaced rather than inferred: a coordinate read while the axis is
        # still travelling is stale the instant it arrives, and the readout
        # gives no other sign of that.
        rx.cond(
            row[MOTION_MOVING] == "moving",
            rx.text("moving", size="1", class_name=reflex_muted_text_class()),
            rx.fragment(),
        ),
        rx.cond(
            row[MOTION_ENABLED] == "disabled",
            rx.text(
                "no scale configured",
                size="1",
                class_name=reflex_muted_text_class(),
            ),
            rx.fragment(),
        ),
        align="center",
        spacing="2",
        wrap="wrap",
    )


def _motion_block(target: ControlTarget):
    """Render one server's axes and its stop button.

    Stop is per server, not per axis, and sits under them: it halts everything
    that server drives, which is what an engineer reaching for it wants.
    """
    return rx.vstack(
        rx.foreach(
            ControlState.motion_rows,
            lambda row: rx.cond(
                row[MOTION_SERVER] == target.server_key,
                _axis_block(target, row),
                rx.fragment(),
            ),
        ),
        rx.button(
            "Stop",
            on_click=ControlState.stop(target.server_key),
            class_name=REFLEX_MOTION_STOP_CLASS,
            width="9em",
            size="2",
        ),
        align="start",
        spacing="3",
        width="100%",
    )


def _server_block(target: ControlTarget):
    """Render one server's heading and its controls, grouped as configured."""
    blocks = []
    if target.items:
        # Grouped through the shared layer, so the sections here are the same
        # sections the Bokeh panel shows for the same config. A heading only
        # where there is more than one populated group: on a single-block server
        # it would just repeat "do".
        grouped = group_do_items(target.items)
        blocks.append(
            rx.vstack(
                *[
                    _group_block(target, group, with_heading=len(grouped) > 1)
                    for group, _ in grouped
                ],
                align="start",
                spacing="3",
                width="100%",
            )
        )
    if target.axes:
        blocks.append(_motion_block(target))
    if not blocks:
        # Named for what the server declared, not for what this page happens to
        # render first: a motion server with no axes in its config is not
        # missing digital outputs.
        blocks.append(
            rx.text(
                (
                    "no axes configured"
                    if target.axis_source
                    else "no digital outputs configured"
                ),
                size="1",
                class_name=reflex_muted_text_class(),
            )
        )
    return rx.card(
        rx.vstack(
            rx.heading(f"{target.title} — {target.server_key}", size="3"),
            *blocks,
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
