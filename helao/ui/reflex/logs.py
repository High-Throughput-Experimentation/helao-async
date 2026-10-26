"""The /logs page: live tail of this group's JSONL logs.

The logic lives in ``helao/ui/shared/log_tail.py`` (Reflex-free). Design:
docs/superpowers/specs/2026-10-26-jsonl-unified-logging-design.md (section 4).
"""

import os

import reflex as rx

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
    if state.paused:
        return
    servers = set(state.selected) or None
    state.rows = log_tail.to_rows(
        log_tail.filter_records(state._all, servers, state.min_level, state.text)
    )


def _start(state) -> None:
    d = _log_dir()
    if d is None:
        state.rows = []
        return
    state._all, state._cursors = log_tail.tail_init(d, MAX_ROWS)
    state.servers = sorted({r.get("server", "") for r in state._all})
    _refresh(state)


def _tick(state) -> None:
    # Never log here: the page reads the logs, so a log line would feed itself.
    d = _log_dir()
    if d is None:
        return
    new, state._cursors = log_tail.tail_poll(d, state._cursors)
    if new:
        state._all = log_tail.merge(state._all, new, MAX_ROWS)
        state.servers = sorted({r.get("server", "") for r in state._all})
        _refresh(state)


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
    _refresh(state)


class LogsState(rx.State):
    """Per-tab tail state. ``_all``/``_cursors`` are backend-only."""

    _all: list = []
    _cursors: dict = {}
    rows: list[list[str]] = []
    servers: list[str] = []
    selected: list[str] = []
    min_level: str = "INFO"
    text: str = ""
    paused: bool = False

    @rx.event
    def start(self):
        _start(self)

    @rx.event
    def tick(self, _value=None):
        # polls even while paused (only the display is frozen), so a rotated
        # file's plain copy is read inside its grace window
        _tick(self)

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
        checked=LogsState.selected.contains(server),
        on_change=lambda on: LogsState.toggle_server(server, on),
    )


def _row(row: rx.Var) -> rx.Component:
    return rx.table.row(
        rx.table.cell(row[0], white_space="nowrap"),
        rx.table.cell(row[1]),
        rx.table.cell(row[2]),
        rx.table.cell(row[3], font_family="monospace", white_space="pre-wrap"),
        style={"color": row[4]},
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
        ),
        on_mount=LogsState.start,
        width="100%",
    )
