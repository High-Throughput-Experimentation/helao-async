"""The /runners page: pick a runner, fill its params, check its servers, launch.

Backend logic is in ``runner_procs.py`` (no Reflex); the helpers here are plain
functions so the launch gating is testable without a Reflex state. Design:
docs/superpowers/specs/2026-11-17-runners-page-design.md (Page).
"""

import os
import re
import time

import reflex as rx

from helao.core.runners import requirements
from helao.core.runners.requirements import default_key
from helao.helpers import helao_logging as logging
from helao.ui.reflex import runner_procs
from helao.ui.reflex.group import GroupState
from helao.ui.reflex.operator import (
    coerce_params,
    fields_for_item,
    flatten_fields,
)
from helao.ui.shared.operator.param_store import form_values, read_params, write_params
from helao.ui.shared.palette import (
    GROUP_BADGE_CLASSES,
    GROUP_ERROR_TEXT_CLASS,
    reflex_muted_text_class,
)

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

_CONFIG: dict = {"world": {}, "repo_root": ""}

TICK_MS = 2000
_TYPES = {"int": int, "float": float, "str": str, "bool": bool}
#: requirement verdict -> /group state whose badge it borrows
_VERDICT_STATE = {"ok": "idle", "warn": "busy", "fail": "error"}
_KEY_RE = re.compile(r"[A-Za-z0-9_-]+")
INFERRED_NOTE = "inferred, may be incomplete"


def configure_runners(world_cfg: dict, repo_root: str = "") -> None:
    """Record the config and repo root; never raises (runs at import from build_app)."""
    _CONFIG["world"] = world_cfg if isinstance(world_cfg, dict) else {}
    # the Reflex process runs from _app/, so the root must be absolute
    _CONFIG["repo_root"] = repo_root or os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )


def item_from_entry(entry: dict) -> dict:
    """A ``--describe`` entry as the library item ``fields_for_item`` reads."""
    return {
        "doc": entry.get("doc") or "",
        "args": list(entry.get("args") or []),
        "defaults": list(entry.get("defaults") or []),
        "argtypes": [_TYPES.get(t, "unspecified") for t in entry.get("argtypes") or []],
    }


def stored_values(root: str, module: str, fields: list) -> dict:
    """Last-used values for the runner, as form strings, minus removed params."""
    names = {f["name"] for f in fields}
    saved = read_params(root, "runner", module)
    return {k: v for k, v in form_values(saved).items() if k in names}


def _detail(r: dict) -> str:
    if not r["in_config"]:
        return "not in config"
    if not r["reachable"]:
        return "unreachable"
    if not r["has_endpoint"]:
        return "no such endpoint"
    if r["estopped"]:
        return "e-stopped"
    return "busy" if r["busy"] else ""


async def check_requirements(world_cfg: dict, entry: dict) -> tuple:
    """``(rows, note, blocked)``; rows are ``[server, action, verdict, detail]``."""
    declared = entry.get("requires")
    reqs = declared if declared is not None else entry.get("inferred") or {}
    if not reqs:
        return [], "none", False
    endpoints, status = await runner_procs.probe(list(reqs), world_cfg)
    rows = requirements.check(
        reqs, world_cfg, endpoints, status, inferred_only=declared is None
    )
    out = [[r["server"], r["action"], r["verdict"], _detail(r)] for r in rows]
    return (
        out,
        "declared" if declared is not None else INFERRED_NOTE,
        any(r[2] == "fail" for r in out),
    )


async def try_launch(
    world_cfg: dict,
    entry: dict,
    values: dict,
    key: str,
    *,
    blocked: bool,
    override: bool,
) -> str:
    """Validate, gate, save the params and spawn. ``""`` on success, else the error."""
    if not _KEY_RE.fullmatch(key or ""):
        return "key may hold only letters, digits, _ and -"
    if entry.get("error"):
        return f"runner cannot be loaded: {entry['error']}"
    fields = fields_for_item(item_from_entry(entry))
    params, errors = coerce_params(fields, values)
    if errors:
        return "; ".join(errors)
    if blocked and not override:
        return "requirement check failed; tick launch anyway to override"
    write_params(world_cfg.get("root", ""), "runner", entry["module"], params)
    try:
        await runner_procs.launch(world_cfg, entry["module"], key, params)
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        LOGGER.exception("runner launch failed")
        return f"launch failed: {exc}"
    return ""


def _entry_rows() -> list:
    rows = []
    for e in runner_procs.CATALOG.values():
        doc = (e.get("doc") or "").strip().splitlines()
        rows.append(
            [
                e["module"],
                e["module"].rsplit(".", 1)[-1],
                doc[0] if doc else "",
                e.get("error") or "",
                (
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e["mtime"]))
                    if e.get("mtime")
                    else ""
                ),
            ]
        )
    return rows


def _proc_rows() -> list:
    return [
        [
            p.key,
            p.module,
            str(p.pid),
            time.strftime("%H:%M:%S", time.localtime(p.started)),
            p.state,
            f"exited {p.rc}" if p.state == "exited" else p.state,
            p.log_path,
        ]
        for p in runner_procs.PROCS.values()
    ]


def _overlap_rows() -> list:
    return [
        f"{server} is busy under {', '.join(keys)}"
        for server, keys in runner_procs.overlap().items()
    ]


def _sig(entry: dict) -> str:
    return repr((entry.get("doc"), item_from_entry(entry), entry.get("requires")))


def _load_form(state, entry: dict) -> None:
    """Build the form for *entry*; blocks launching until the check has run."""
    fields = fields_for_item(item_from_entry(entry))
    module = entry["module"]
    state.selected = module
    state.doc = entry.get("doc") or ""
    state.fields_rows = flatten_fields(fields)
    # every field is seeded, so a cleared text field reads "" and not its default
    state.values = {f["name"]: f["default"] for f in fields} | stored_values(
        _CONFIG["world"].get("root", ""), module, fields
    )
    state.key = default_key(module)
    state.error = ""
    state.override = False
    state.req_rows, state.req_note, state.blocked = [], "checking", True
    state._sig = _sig(entry)


def _apply_refresh(state) -> bool:
    """Reconcile the selection with the new catalog; True when it must be re-checked."""
    entry = runner_procs.CATALOG.get(state.selected)
    if entry is None or entry.get("error"):
        state.selected = ""
        state.fields_rows, state.req_rows = [], []
        state.blocked = False
        return False
    if _sig(entry) == state._sig:
        return False
    _load_form(state, entry)
    return True


class RunnersState(rx.State):
    """Per-tab page state. Backend vars (underscore) are tuples, never lists."""

    entries: list[list[str]] = []  # [module, name, summary, error, mtime]
    selected: str = ""
    doc: str = ""
    fields_rows: list[list[str]] = []  # [name, kind, default, help]
    values: dict[str, str] = {}
    req_rows: list[list[str]] = []  # [server, action, verdict, detail]
    req_note: str = ""
    blocked: bool = False
    override: bool = False
    key: str = ""
    error: str = ""
    procs: list[list[str]] = []  # [key, module, pid, started, state, shown, log]
    overlap_rows: list[str] = []
    _sig: str = ""  # what the form was built from, to spot a changed entry

    @rx.event
    def mount(self):
        return RunnersState.refresh

    @rx.event(background=True)
    async def refresh(self):
        try:
            await runner_procs.refresh_catalog(_CONFIG["world"], _CONFIG["repo_root"])
        except Exception as exc:
            LOGGER.exception("runner catalog refresh failed")
            async with self:
                self.error = f"refresh failed: {exc}"
            return
        async with self:
            self.entries = _entry_rows()
            changed = _apply_refresh(self)
            entry = runner_procs.CATALOG.get(self.selected)
        if changed and entry is not None:
            rows, note, blocked = await check_requirements(_CONFIG["world"], entry)
            async with self:
                if self.selected == entry["module"]:
                    self.req_rows, self.req_note, self.blocked = rows, note, blocked

    @rx.event
    def select(self, module: str):
        entry = runner_procs.CATALOG.get(module)
        if entry is None or entry.get("error"):
            return
        _load_form(self, entry)
        return RunnersState.recheck

    @rx.event(background=True)
    async def recheck(self):
        async with self:
            entry = runner_procs.CATALOG.get(self.selected)
        if entry is None:
            return
        rows, note, blocked = await check_requirements(_CONFIG["world"], entry)
        async with self:
            if self.selected == entry["module"]:  # not overtaken by another select
                self.req_rows, self.req_note, self.blocked = rows, note, blocked

    @rx.event
    def set_value(self, name: str, value: str):
        self.values = {**self.values, name: value}

    @rx.event
    def set_bool(self, name: str, value: bool):
        # a checkbox sends a JSON bool; str(value) is what coerce_params reads
        self.values = {**self.values, name: str(value)}

    @rx.event
    def set_key(self, value: str):
        self.key = value

    @rx.event
    def toggle_override(self):
        self.override = not self.override

    @rx.event(background=True)
    async def launch_selected(self):
        async with self:
            entry = runner_procs.CATALOG.get(self.selected)
            values, key = dict(self.values), self.key
            blocked, override = self.blocked, self.override
            stale = entry is not None and _sig(entry) != self._sig
        if entry is None:
            return
        if stale:
            async with self:
                self.error = "runner changed; re-check"
            return
        err = await try_launch(
            _CONFIG["world"], entry, values, key, blocked=blocked, override=override
        )
        async with self:
            self.error = err
            if not err:
                self.procs = _proc_rows()

    @rx.event
    def stop(self, key: str):
        runner_procs.stop(key)
        self.procs = _proc_rows()

    @rx.event
    def force_kill(self, key: str):
        runner_procs.force_kill(key)
        self.procs = _proc_rows()

    @rx.event
    def dismiss(self, key: str):
        runner_procs.dismiss(key)
        self.procs = _proc_rows()

    @rx.event
    def tick(self, _value: str = ""):
        procs, overlap = _proc_rows(), _overlap_rows()
        if procs != self.procs:
            self.procs = procs
        if overlap != self.overlap_rows:
            self.overlap_rows = overlap


S = RunnersState


def _entry_row(row) -> rx.Component:
    return rx.cond(
        row[3] != "",
        rx.box(
            rx.text(row[1], weight="bold", class_name=reflex_muted_text_class()),
            rx.text(row[3], class_name=GROUP_ERROR_TEXT_CLASS, size="1"),
        ),
        rx.box(
            rx.text(row[1], weight="bold"),
            rx.text(row[2], size="1"),
            rx.text(row[4], size="1", class_name=reflex_muted_text_class()),
            cursor="pointer",
            on_click=S.select(row[0]),
        ),
    )


def _field(row) -> rx.Component:
    return rx.hstack(
        rx.text(row[0], width="10em"),
        rx.cond(
            row[1] == "bool",
            rx.checkbox(
                checked=S.values[row[0]].lower() == "true",
                on_change=lambda on: S.set_bool(row[0], on),
            ),
            rx.input(
                value=S.values[row[0]],
                on_change=lambda v: S.set_value(row[0], v),
            ),
        ),
        rx.text(row[3], size="1"),
    )


def _verdict_badge(row) -> rx.Component:
    return rx.match(
        row[2],
        *[
            (v, rx.badge(v, class_name=GROUP_BADGE_CLASSES[s]))
            for v, s in _VERDICT_STATE.items()
        ],
        rx.badge(row[2]),
    )


def _req_row(row) -> rx.Component:
    return rx.hstack(
        _verdict_badge(row), rx.text(row[0], " / ", row[1]), rx.text(row[3])
    )


def _proc_row(row) -> rx.Component:
    return rx.table.row(
        rx.table.cell(row[0]),
        rx.table.cell(row[1]),
        rx.table.cell(row[2]),
        rx.table.cell(row[3]),
        rx.table.cell(row[5]),
        rx.table.cell(row[6], font_family="monospace", size="1"),
        rx.table.cell(
            rx.hstack(
                rx.button(
                    "Stop",
                    on_click=S.stop(row[0]),
                    disabled=row[4] != "running",
                ),
                rx.button(
                    "Force kill",
                    on_click=S.force_kill(row[0]),
                    disabled=row[4] != "stopping",
                ),
                rx.button(
                    "Dismiss",
                    on_click=S.dismiss(row[0]),
                    disabled=(row[4] == "running") | (row[4] == "stopping"),
                ),
                rx.button(
                    "group",
                    variant="ghost",
                    on_click=[GroupState.set_feed(row[0]), rx.redirect("/group")],
                ),
            )
        ),
        key=row[0],
    )


def runners_page() -> rx.Component:
    form = rx.cond(
        S.selected != "",
        rx.vstack(
            rx.text(S.selected, weight="bold"),
            rx.text(S.doc, white_space="pre-wrap", size="1"),
            rx.foreach(S.fields_rows, _field),
            rx.hstack(
                rx.text("Requirements (", S.req_note, ")"),
                rx.button("Re-check", on_click=S.recheck),
            ),
            rx.foreach(S.req_rows, _req_row),
            rx.cond(
                S.blocked,
                rx.checkbox(
                    "launch anyway", checked=S.override, on_change=S.toggle_override
                ),
            ),
            rx.hstack(
                rx.input(value=S.key, on_change=S.set_key, placeholder="key"),
                rx.button(
                    "Launch",
                    on_click=S.launch_selected,
                    disabled=S.blocked & ~S.override,
                ),
            ),
            rx.cond(S.error != "", rx.text(S.error, class_name=GROUP_ERROR_TEXT_CLASS)),
            align="start",
        ),
        rx.text("Select a runner."),
    )
    return rx.vstack(
        rx.moment(interval=TICK_MS, on_change=S.tick, display="none"),
        rx.hstack(
            rx.vstack(
                rx.button("Refresh", on_click=S.refresh),
                rx.foreach(S.entries, _entry_row),
                align="start",
                min_width="16em",
            ),
            form,
            spacing="6",
            align="start",
        ),
        rx.heading("Processes", size="4"),
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    *[
                        rx.table.column_header_cell(h)
                        for h in ("key", "runner", "pid", "started", "state", "log", "")
                    ]
                )
            ),
            rx.table.body(rx.foreach(S.procs, _proc_row)),
            class_name="bg-white",
        ),
        rx.foreach(S.overlap_rows, lambda t: rx.callout(t, icon="triangle_alert")),
        on_mount=S.mount,
        padding_x="1em",
        width="100%",
    )
