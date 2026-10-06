"""The /retire page: retire a mis-identified sequence.

Deletes metadata-API rows and moves run dirs, so it is off unless the Reflex
server's params set ``retire: true``, and every handler re-checks that. All the
logic lives in ``helao/ui/shared/retire.py`` (Reflex-free, tested offline); this
module is the thin state and layout over it. Design:
docs/superpowers/specs/2026-10-06-sequence-retire-page-design.md
"""

import asyncio
import uuid
from datetime import datetime, timezone

import reflex as rx

from helao.helpers import helao_logging as logging
from helao.ui.shared import retire as retire_logic
from helao.ui.shared.composition import api
from helao.ui.shared.palette import reflex_muted_text_class
from helao.ui.shared.retire import ENTITY_TYPES, Inventory

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

_CONFIG: dict = {"enabled": False, "root": "", "sources_root": ""}


def configure_retire(world_cfg: dict, server_key: str) -> None:
    """Bind the page to one Reflex server's ``retire`` params.

    Guarded at every level, never raising: this runs from ``build_app`` at
    import time (see ``control.configure_control``). Enabled only by the
    literal ``retire: true`` *and* a non-empty world ``root``.

    Args:
        world_cfg: The loaded HELAO world config.
        server_key: Config key of the Reflex server entry.
    """
    servers = world_cfg.get("servers")
    server_cfg = servers.get(server_key) if isinstance(servers, dict) else None
    if not isinstance(server_cfg, dict):
        server_cfg = {}
    params = server_cfg.get("params")
    if not isinstance(params, dict):
        params = {}
    root = world_cfg.get("root")
    root = root if isinstance(root, str) else ""
    sources = params.get("retire_sources_root")
    _CONFIG["root"] = root
    _CONFIG["sources_root"] = sources if isinstance(sources, str) and sources else ""
    _CONFIG["enabled"] = params.get("retire") is True and bool(root)


def retire_enabled() -> bool:
    return bool(_CONFIG.get("enabled"))


# ponytail: one process-wide lock, so two tabs cannot retire at once; the
# lock is per Reflex process, not per sequence. Per-uuid locks if two
# sequences ever need retiring concurrently.
_RETIRE_LOCK = asyncio.Lock()


def _progress(state):
    """Build the progress callback for *state*: ``(phase, done, total)``."""

    async def _cb(phase: str, done: int, total: int) -> None:
        async with state:
            state.status = f"{phase}: {done}/{total}"
            state.progress = round(100 * done / total) if total else 0

    return _cb


_UNSYNCED_WARNING = (
    "not synced — may still be running or uploading; "
    "retiring it can race the orchestrator/syncer"
)
_OVERRIDE = "UNSYNCED"


def _is_armed(
    inv: Inventory | None, confirm: str, label: str, synced: bool, override: str
) -> bool:
    """Label (or uuid) typed, and either synced or the override typed."""
    return (
        inv is not None
        and confirm == (label or inv.sequence_uuid)
        and (synced or override == _OVERRIDE)
    )


def _rearm(state) -> None:
    """Recompute ``armed`` and move ``phase`` between gathered and armed."""
    state.armed = _is_armed(
        state._inv,
        state.confirm_text,
        state.label,
        state.synced,
        state.override_text,
    )
    if state.phase in ("gathered", "armed"):
        state.phase = "armed" if state.armed else "gathered"


class RetireState(rx.State):
    """Gather, confirm and retire one sequence. Handlers re-check the gate."""

    uuid_text: str = ""
    status: str = ""
    error: str = ""
    counts: list[list[str]] = []
    label: str = ""
    campaign: str = ""
    confirm_text: str = ""
    armed: bool = False
    synced: bool = False
    override_text: str = ""
    busy: bool = False
    progress: int = 0
    ledger: str = ""
    warnings: list[str] = []
    moved: list[str] = []
    phase: str = "idle"
    run_dirs: list[str] = []
    analysis_dirs: list[str] = []
    _inv: Inventory | None = None

    @rx.event
    def set_uuid(self, v: str):
        if self.busy:
            return
        self.uuid_text = v
        self.status, self.error = "", ""
        self.counts, self.label, self.campaign = [], "", ""
        self.confirm_text, self.armed, self.progress = "", False, 0
        self.override_text, self.synced = "", False
        self.ledger, self.warnings, self.moved = "", [], []
        self.run_dirs, self.analysis_dirs = [], []
        self._inv = None
        if retire_enabled():
            self.phase = "idle"

    @rx.event
    def set_confirm(self, v: str):
        if self.busy:
            return
        self.confirm_text = v
        _rearm(self)

    @rx.event
    def set_override(self, v: str):
        if self.busy:
            return
        self.override_text = v
        _rearm(self)

    @rx.event(background=True)
    async def gather(self):
        async with self:
            if not retire_enabled() or self.busy:
                return
            self.status, self.error = "", ""
            self.counts, self.label, self.campaign = [], "", ""
            self.confirm_text, self.armed, self.progress = "", False, 0
            self.override_text, self.synced = "", False
            self.ledger, self.warnings, self.moved = "", [], []
            self.run_dirs, self.analysis_dirs = [], []
            self._inv = None
            try:
                u = str(uuid.UUID(self.uuid_text.strip()))
            except ValueError:
                self.error, self.phase = "not a uuid", "idle"
                return
            self.busy, self.phase, self.uuid_text = True, "gathering", u
            root, sources_root = _CONFIG["root"], _CONFIG["sources_root"]
        _cb = _progress(self)
        err, inv = "", None
        try:
            locs = await asyncio.to_thread(retire_logic.locate, root, u)
            hit = None
            if sources_root:
                hit = await asyncio.to_thread(
                    retire_logic.in_flight,
                    sources_root,
                    u,
                    [loc.rel_dir for loc in locs],
                )
            if hit:
                err = f"batch conversion in flight: {hit}"
            else:
                client = api.get_client()
                inv = await retire_logic.inventory(client, root, u, _cb)
        except asyncio.CancelledError:
            async with self:
                self.busy, self.phase = False, "idle"
            raise
        except Exception as exc:
            LOGGER.warning(f"retire gather failed: {exc!r}")
            err = str(exc)
        # busy drops in the same block as the terminal write, so set_uuid cannot
        # run in the gap between them and be overwritten by the results.
        async with self:
            self.busy = False
            if inv is None:
                self.error, self.phase = err, "idle"
                return
            if inv.nothing_to_retire:
                self.status, self.phase = "nothing to retire", "idle"
                return
            rows = [
                [t, str(len(inv.local[t])), str(len(inv.in_api[t]))]
                for t in ENTITY_TYPES
            ]
            rows.append(
                [
                    "SEQUENCE",
                    str(len(inv.locations)),
                    "present" if inv.sequence_in_api else "absent",
                ]
            )
            self.counts = rows
            self.label = inv.sequence_label
            self.campaign = inv.campaign_name
            self.run_dirs = [f"{loc.run_tree}/{loc.rel_dir}" for loc in inv.locations]
            self.analysis_dirs = list(inv.analysis_dirs)
            self.synced = inv.synced
            self.warnings = [
                *(
                    [
                        "experiments/actions unknowable from API alone; "
                        "processes may already be gone"
                    ]
                    if inv.api_only
                    else []
                ),
                *([] if inv.synced else [_UNSYNCED_WARNING]),
            ]
            self._inv = inv
            self.status, self.phase = "", "gathered"

    @rx.event(background=True)
    async def do_retire(self):
        held = False
        try:
            async with self:
                if not retire_enabled() or self.busy:
                    return  # a running gather/retire owns the state: write nothing
                inv = self._inv
                if self.phase != "armed" or inv is None:
                    self.error = "gather and confirm first"
                    return
                # No await between locked() and acquire(): another handler cannot
                # slip in, so a second click reports busy, not a second retire.
                if _RETIRE_LOCK.locked():
                    self.error = "a retire is already running"
                    return
                await _RETIRE_LOCK.acquire()
                held = True
                # busy is set in this block, so nothing can interleave after it.
                self.busy, self.phase, self.progress = True, "retiring", 0
                root = _CONFIG["root"]
                allow = not inv.synced and self.override_text == _OVERRIDE
            result = None
            error = ""
            try:
                client = api.get_client()
            except Exception as exc:
                LOGGER.warning(f"retire could not get a client: {exc!r}")
                error = f"{exc}; no files were moved"
            else:
                ledger = retire_logic.ledger_path_for(
                    root, inv.sequence_uuid, datetime.now(timezone.utc)
                )
                async with self:
                    self.ledger = ledger
                try:
                    result = await retire_logic.retire(
                        client,
                        root,
                        inv,
                        _progress(self),
                        ledger,
                        allow_unsynced=allow,
                    )
                except asyncio.CancelledError:
                    async with self:
                        self.busy, self.phase = False, "failed"
                        self._inv, self.armed = None, False
                        self.error = "retire cancelled; API rows may be deleted"
                    raise
            async with self:
                if result is not None:
                    self.warnings = [
                        *self.warnings,
                        *(
                            f"{t}: {len(u)} acknowledged-but-persists, "
                            f"e.g. {', '.join(u[:3])}"
                            for t, u in result.persisting.items()
                        ),
                    ]
                if result is not None and result.ok:
                    self.phase, self.status, self.error = "done", "retired", ""
                    self.moved = [f"{s} -> {d}" for s, d in result.moved]
                else:
                    self.phase = "failed"
                    self.error = result.error if result is not None else error
                self._inv, self.armed, self.busy = None, False, False
        finally:
            if held:
                _RETIRE_LOCK.release()


def _count_row(row: list[str]) -> rx.Component:
    return rx.table.row(
        rx.table.cell(row[0]), rx.table.cell(row[1]), rx.table.cell(row[2])
    )


def _line(text: str) -> rx.Component:
    return rx.text(text, size="2")


def retire_page() -> rx.Component:
    """The page body; a one-line note when the station has not enabled it."""
    if not retire_enabled():
        return rx.text("Retire is disabled on this station.", padding_x="1em")
    return rx.vstack(
        rx.hstack(
            rx.input(
                placeholder="sequence uuid",
                value=RetireState.uuid_text,
                on_change=RetireState.set_uuid,
                disabled=RetireState.busy,
                width="28em",
            ),
            rx.button("Gather", on_click=RetireState.gather, disabled=RetireState.busy),
        ),
        rx.text(RetireState.status, class_name=reflex_muted_text_class()),
        rx.text(RetireState.error, class_name="text-red-600"),
        rx.cond(
            RetireState.counts.length() > 0,  # type: ignore[attr-defined]
            rx.vstack(
                rx.table.root(
                    rx.table.header(
                        rx.table.row(
                            rx.table.column_header_cell("entity"),
                            rx.table.column_header_cell("local"),
                            rx.table.column_header_cell("in API"),
                        )
                    ),
                    rx.table.body(rx.foreach(RetireState.counts, _count_row)),
                ),
                rx.text("run dirs", weight="bold", size="2"),
                rx.foreach(RetireState.run_dirs, _line),
                rx.text("analysis dirs", weight="bold", size="2"),
                rx.foreach(RetireState.analysis_dirs, _line),
                rx.text(
                    "label: ", RetireState.label, "  campaign: ", RetireState.campaign
                ),
                rx.hstack(
                    rx.input(
                        placeholder="type the label (or the uuid if there is none)",
                        value=RetireState.confirm_text,
                        on_change=RetireState.set_confirm,
                        width="28em",
                    ),
                    rx.cond(
                        ~RetireState.synced,  # type: ignore[operator]
                        rx.input(
                            placeholder=f"type {_OVERRIDE} to override",
                            value=RetireState.override_text,
                            on_change=RetireState.set_override,
                            width="20em",
                        ),
                    ),
                    rx.button(
                        "Retire",
                        on_click=RetireState.do_retire,
                        disabled=~RetireState.armed | RetireState.busy,  # type: ignore[operator]
                    ),
                ),
            ),
        ),
        rx.cond(
            (RetireState.phase == "retiring") | (RetireState.phase == "done"),
            rx.progress(value=RetireState.progress),
        ),
        rx.foreach(
            RetireState.warnings,
            lambda w: rx.text(w, size="2", class_name="text-amber-700"),
        ),
        rx.cond(
            RetireState.ledger != "",
            rx.vstack(
                rx.text("ledger: ", RetireState.ledger, size="2"),
                rx.foreach(RetireState.moved, _line),
            ),
        ),
        padding="1em",
        spacing="3",
    )
