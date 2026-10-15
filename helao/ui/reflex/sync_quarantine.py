"""The /quarantine page: release or write off records the syncer has parked.

Off unless the Reflex server's params set ``sync_quarantine: true`` and the
config names a syncer; every handler re-checks that. The logic lives in
``helao/ui/shared/sync_quarantine.py`` (Reflex-free); this module is the thin
state and layout over it. Design:
docs/superpowers/specs/2026-10-15-sync-write-off-design.md (section 4.7).
"""

import asyncio

import reflex as rx

from helao.ui.shared import sync_quarantine as sq
from helao.ui.shared.palette import reflex_muted_text_class

_CONFIG: dict = {"enabled": False, "target": None}

POLL_MS = 60_000
ACT_TIMEOUT = 30  # s, call + re-fetch together, held under the process lock
UNREACHABLE = "SYNC unreachable: quarantine state unknown"
NOTHING = "nothing quarantined"
BUSY = "busy: another release or write-off is running"
# Row columns, per sq.rows(): yml, dir name, cause, quarantined_at, strikes,
# last_error, incomplete flag.
YML, DIR, FLAG = 0, 1, 6


def configure_quarantine(world_cfg: dict, server_key: str) -> None:
    """Bind the page to one Reflex server's ``sync_quarantine`` param.

    Never raises: this runs from ``build_app`` at import time. Enabled only by
    the literal ``sync_quarantine: true`` and a resolvable syncer.

    Args:
        world_cfg: The loaded HELAO world config.
        server_key: Config key of the Reflex server entry.
    """
    servers = world_cfg.get("servers")
    server_cfg = servers.get(server_key) if isinstance(servers, dict) else None
    params = server_cfg.get("params") if isinstance(server_cfg, dict) else None
    flag = params.get("sync_quarantine") if isinstance(params, dict) else None
    target = sq.sync_target(world_cfg)
    _CONFIG["target"] = target
    _CONFIG["enabled"] = flag is True and target is not None


def quarantine_enabled() -> bool:
    return bool(_CONFIG.get("enabled"))


# ponytail: one process-wide lock serializes Release and Write off; per-yml
# locks if two records ever need acting on at once.
_LOCK = asyncio.Lock()


def _rearm(state) -> None:
    state.armed = sq.is_armed(
        state.selected_dir, state.confirm, state.reason, state.operator
    )


def _clear_selection(state) -> None:
    state.selected, state.selected_dir, state.confirm = "", "", ""
    state.armed = False


def _apply(state, entries) -> None:
    """Install fetched *entries*; drop a selection whose row is gone."""
    state.rows = sq.rows(entries) if entries is not None else []
    if entries is None:
        state.status = UNREACHABLE
    else:
        state.status = f"{len(entries)} quarantined" if entries else NOTHING
    if state.selected and not any(r[YML] == state.selected for r in state.rows):
        _clear_selection(state)


class QuarantineState(rx.State):
    """List parked records; release one or write one off, by yml path."""

    rows: list[list[str]] = []
    status: str = ""
    message: str = ""  # the last action's result; only an action rewrites it
    gen: int = 0  # bumped by every action; a refresh older than it is dropped
    selected: str = ""
    selected_dir: str = ""
    confirm: str = ""
    reason: str = ""
    operator: str = ""
    armed: bool = False
    busy: bool = False

    @rx.event
    def set_confirm(self, v: str):
        if self.busy or not quarantine_enabled():
            return
        self.confirm = v
        _rearm(self)

    @rx.event
    def set_reason(self, v: str):
        if self.busy or not quarantine_enabled():
            return
        self.reason = v
        _rearm(self)

    @rx.event
    def set_operator(self, v: str):
        if self.busy or not quarantine_enabled():
            return
        self.operator = v
        _rearm(self)

    @rx.event
    def select(self, yml: str, dir_name: str):
        if self.busy or not quarantine_enabled() or not yml:
            return
        self.selected, self.selected_dir, self.confirm = yml, dir_name, ""
        _rearm(self)

    @rx.event(background=True)
    async def refresh(self, _tick: str = ""):
        async with self:
            if not quarantine_enabled() or self.busy:
                return
            target, gen = _CONFIG["target"], self.gen
        entries = await sq.fetch(target)
        async with self:
            if self.busy or self.gen != gen:
                return  # an action ran meanwhile: these rows predate it
            _apply(self, entries)

    @rx.event(background=True)
    async def release_row(self, yml: str):
        async with self:
            if yml not in {r[YML] for r in self.rows}:
                return
        await _act(self, yml, lambda t: sq.release(t, yml))

    @rx.event(background=True)
    async def write_off(self):
        async with self:
            yml = self.selected
            reason, operator = self.reason, self.operator
            row = next((r for r in self.rows if r[YML] == yml), None)
            ok = (
                quarantine_enabled()
                and row is not None
                and row[FLAG] == "1"
                and sq.is_armed(row[DIR], self.confirm, reason, operator)
            )
        if not ok:
            return
        await _act(self, yml, lambda t: sq.write_off(t, yml, reason, operator))


async def _act(state, yml: str, call) -> None:
    """Run one release or write-off under the lock and show its message."""
    held = False
    try:
        async with state:
            if not quarantine_enabled() or not yml or state.busy:
                return
            if _LOCK.locked():
                state.message = BUSY
                return
            await _LOCK.acquire()
            held = True
            state.busy = True
            state.gen += 1
            target = _CONFIG["target"]

        async def go():
            return (await call(target))[1], await sq.fetch(target)

        try:
            msg, entries = await asyncio.wait_for(go(), ACT_TIMEOUT)
        except asyncio.TimeoutError:
            async with state:
                state.gen += 1
                state.message = sq.UNKNOWN
            return
        async with state:
            state.gen += 1
            state.message = msg
            _apply(state, entries)
            _clear_selection(state)
    finally:
        if held:
            try:
                async with state:
                    state.busy = False
            finally:
                _LOCK.release()


def _cell(text) -> rx.Component:
    return rx.table.cell(text)


def _row(row: list[str]) -> rx.Component:
    return rx.table.row(
        *(_cell(row[i]) for i in range(6)),
        rx.table.cell(
            rx.cond(
                row[YML] != "",
                rx.hstack(
                    rx.button(
                        "Release",
                        size="1",
                        on_click=QuarantineState.release_row(row[YML]),
                        disabled=QuarantineState.busy,
                    ),
                    rx.cond(
                        row[FLAG] == "1",
                        rx.button(
                            "Write off",
                            size="1",
                            on_click=QuarantineState.select(row[YML], row[DIR]),
                            disabled=QuarantineState.busy,
                        ),
                    ),
                ),
            )
        ),
    )


_HEADERS = ("record", "directory", "cause", "since", "strikes", "last error", "")


def sync_quarantine_page() -> rx.Component:
    """The page body; a one-line note when the station has not enabled it."""
    if not quarantine_enabled():
        return rx.text("Sync quarantine is disabled on this station.", padding_x="1em")
    return rx.vstack(
        rx.hstack(
            rx.button("Refresh", on_click=QuarantineState.refresh("")),
            rx.moment(
                interval=POLL_MS,
                on_change=QuarantineState.refresh,
                display="none",
            ),
        ),
        rx.text(QuarantineState.message, weight="bold", size="2"),
        rx.text(QuarantineState.status, class_name=reflex_muted_text_class()),
        rx.table.root(
            rx.table.header(
                rx.table.row(*(rx.table.column_header_cell(h) for h in _HEADERS))
            ),
            rx.table.body(rx.foreach(QuarantineState.rows, _row)),
        ),
        rx.cond(
            QuarantineState.selected != "",
            rx.vstack(
                rx.text("Write off: ", QuarantineState.selected, weight="bold"),
                rx.input(
                    placeholder="type the directory name to confirm",
                    value=QuarantineState.confirm,
                    on_change=QuarantineState.set_confirm,
                    width="32em",
                ),
                rx.input(
                    placeholder="reason",
                    value=QuarantineState.reason,
                    on_change=QuarantineState.set_reason,
                    width="32em",
                ),
                rx.input(
                    placeholder="operator",
                    value=QuarantineState.operator,
                    on_change=QuarantineState.set_operator,
                    width="20em",
                ),
                rx.button(
                    "Confirm write off",
                    on_click=QuarantineState.write_off,
                    disabled=~QuarantineState.armed | QuarantineState.busy,  # type: ignore[operator]
                ),
                spacing="2",
            ),
        ),
        on_mount=QuarantineState.refresh(""),
        padding="1em",
        spacing="3",
    )
