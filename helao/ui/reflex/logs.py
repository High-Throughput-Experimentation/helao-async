"""The /logs page: live tail of this group's JSONL logs.

The logic lives in ``helao/ui/shared/log_tail.py`` (Reflex-free). Design:
docs/superpowers/specs/2026-10-26-jsonl-unified-logging-design.md (section 4).
"""

import asyncio
import os
from typing import cast

import reflex as rx
from reflex.vars import ArrayVar

from helao.ui.shared import log_tail

_CONFIG: dict = {"log_dir": None}

MAX_ROWS = 2000
TICK_MS = 1000
LEVEL_CHOICES = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "ALERT"]


def configure_logs(world_cfg: dict, server_key: str) -> None:
    """Point the page at ``<root>/LOGS`` as an absolute path.

    Never raises: runs from ``build_app`` at import time. Absolute because the
    Reflex process runs from ``_app/``, not the repo root.
    """
    root = world_cfg.get("root") if isinstance(world_cfg, dict) else None
    _CONFIG["log_dir"] = os.path.realpath(os.path.join(root, "LOGS")) if root else None


def _log_dir():
    d = _CONFIG.get("log_dir")
    return d if d and os.path.isdir(d) else None


def _refresh(state) -> None:
    # while paused the view is the frozen snapshot, so filter changes still apply
    source = state._frozen if state.paused else state._all
    servers = set(state.selected) or None
    state.rows = log_tail.to_rows(
        log_tail.filter_records(source, servers, state.min_level, state.text)
    )


def _set_servers(state) -> None:
    # a selected server stays listed even after it ages out of the buffer
    found = sorted({r.get("server", "") for r in state._all} | set(state.selected))
    if found != state.servers:
        state.servers = found


def _apply_init(state, recs, cursors) -> None:
    state._cursors = tuple(cursors)
    # tuple: Reflex wraps a list var in a proxy that costs ~30 ms per busy tick
    state._all = tuple(recs)
    _set_servers(state)
    _refresh(state)


def _apply_poll(state, new, cursors) -> None:
    state._cursors = tuple(cursors)
    if new:
        state._all = tuple(log_tail.merge(list(state._all), new, MAX_ROWS))
        _set_servers(state)
        _refresh(state)


async def _load_bg(state, tick: bool) -> None:
    """One init (``start``) or poll (``tick``) of the log files.

    ``state`` is the Reflex ``StateProxy`` of a background event: it may be read
    or written only inside ``async with state``, and the file I/O runs on a
    worker thread between the two blocks so the event loop never waits on disk.
    Never log here: the page reads the logs, so a log line would feed itself.
    """
    async with state:
        if state._busy:  # a slow poll must not be overtaken by the next tick
            return
        d = _log_dir()
        if d is None:
            if not tick:
                state.rows = []
            return
        # a tick before start would otherwise read from offset 0 and show the oldest rows
        cursors = list(state._cursors) if tick else []
        state._busy = True
    try:
        if cursors:
            result = await asyncio.to_thread(log_tail.tail_poll, d, cursors)
        else:
            result = await asyncio.to_thread(log_tail.tail_init, d, MAX_ROWS)
    except BaseException:
        async with state:
            state._busy = False
        raise
    async with state:
        state._busy = False
        (_apply_poll if cursors else _apply_init)(state, *result)


def _set_min_level(state, value: str) -> None:
    state.min_level = value
    _refresh(state)


def _set_text(state, value: str) -> None:
    state.text = value
    _refresh(state)


def _toggle_server(state, server: str, on: bool) -> None:
    chosen = [s for s in state.selected if s != server]
    state.selected = chosen + [server] if on else chosen
    _refresh(state)


def _toggle_pause(state) -> None:
    state.paused = not state.paused
    if state.paused:
        state._frozen = tuple(state._all)
    _refresh(state)


class LogsState(rx.State):
    """Per-tab tail state. ``_all``/``_cursors`` are backend-only."""

    _all: tuple = ()
    _frozen: tuple = ()
    _cursors: tuple = ()
    _busy: bool = False
    rows: list[list[str]] = []
    servers: list[str] = []
    selected: list[str] = []
    min_level: str = "INFO"
    text: str = ""
    paused: bool = False

    @rx.event(background=True)
    async def start(self):
        await _load_bg(self, tick=False)

    @rx.event(background=True)
    async def tick(self, _value=None):
        # polls even while paused (only the display is frozen), so a rotated
        # file's plain copy is read inside its grace window
        await _load_bg(self, tick=True)

    @rx.event
    def set_min_level(self, value: str):
        _set_min_level(self, value)

    @rx.event
    def set_text(self, value: str):
        _set_text(self, value)

    @rx.event
    def toggle_server(self, server: str, on: bool):
        _toggle_server(self, server, on)

    @rx.event
    def toggle_pause(self):
        _toggle_pause(self)


def _server_box(server: rx.Var) -> rx.Component:
    return rx.checkbox(
        server,
        # class access yields a Var at runtime; pyright sees the list annotation
        checked=cast(ArrayVar, LogsState.selected).contains(server),
        on_change=lambda on: LogsState.toggle_server(server, on),
    )


# A message is one line cut with an ellipsis until clicked; a native <details>
# keeps the open/closed state in the browser, not in LogsState.
_SUMMARY = {
    "cursor": "pointer",
    "list_style": "none",
    "white_space": "nowrap",
    "overflow": "hidden",
    "text_overflow": "ellipsis",
    "&::-webkit-details-marker": {"display": "none"},
}
_OPEN = {"&[open] > summary": {"white_space": "pre-wrap", "overflow_wrap": "anywhere"}}


def _row(row: ArrayVar) -> rx.Component:
    return rx.table.row(
        rx.table.cell(row[0], white_space="nowrap"),
        rx.table.cell(row[1]),
        rx.table.cell(row[2]),
        rx.table.cell(
            rx.el.details(rx.el.summary(row[3], style=_SUMMARY), style=_OPEN),
            font_family="monospace",
            # max-width 0 lets the cell take the remaining width instead of
            # growing to fit the unwrapped line, so the ellipsis can show
            max_width="0",
            width="100%",
        ),
        style={"color": row[4]},
        key=row[5],
    )


def logs_page() -> rx.Component:
    return rx.vstack(
        rx.moment(interval=TICK_MS, on_change=LogsState.tick, display="none"),
        rx.hstack(
            rx.select(
                LEVEL_CHOICES,
                value=LogsState.min_level,
                on_change=LogsState.set_min_level,
            ),
            rx.input(
                placeholder="search", value=LogsState.text, on_change=LogsState.set_text
            ),
            rx.button(
                rx.cond(LogsState.paused, "Resume", "Pause"),
                on_click=LogsState.toggle_pause,
            ),
            spacing="3",
        ),
        rx.flex(rx.foreach(LogsState.servers, _server_box), wrap="wrap", spacing="3"),
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("time (UTC)"),
                    rx.table.column_header_cell("level"),
                    rx.table.column_header_cell("server"),
                    rx.table.column_header_cell("message"),
                )
            ),
            rx.table.body(rx.foreach(LogsState.rows, _row)),
            width="100%",
            # table bodies stay white (palette.REFLEX_TABLE_HUES); the page
            # tint would otherwise show through the transparent Radix rows
            class_name="bg-white",
        ),
        on_mount=LogsState.start,
        width="100%",
    )
