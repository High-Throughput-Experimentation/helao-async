"""The /group page: server-group graph, sequence timelines, controls, info box.

One process-wide ``WsIngest`` on the orchestrator's ``/ws_orch``; frames are
whole snapshots, read from ``ingest.raw``. ``GroupState`` is a plain
``rx.State`` (one page per orchestrator) ticked by ``rx.moment``: 60 Hz while
a pulse is alive, 2 Hz otherwise. Never a server-side loop. Buttons and the
info box go over HTTP through the operator's ``RemoteBackend``, which is bound
to the same orchestrator this page streams from (see :func:`_backend`).

Frames are followed by LOCAL arrival order (``WsIngest.n_batches``), never by
the orchestrator's own ``seq_no``: ``raw`` keeps old batches across an
orchestrator restart, and a page that has just opened must not replay what was
buffered before it. Backend vars touched every tick are tuples, not lists or
dicts, because Reflex wraps those in a ``MutableProxy`` (~30 ms per busy tick).
"""

import time
from datetime import datetime
from typing import Optional

import reflex as rx

from helao.core.models.group_snapshot import ERROR_STATUSES
from helao.helpers import helao_logging as logging
from helao.ui.reflex import plots
from helao.ui.reflex.ingest import WsIngest
from helao.ui.reflex.netgraph import NetGraph, group_layout
from helao.ui.reflex.operator import session_backend, tree_for
from helao.ui.reflex.timeline_strip import click_item, item_key, strip_marks
from helao.ui.reflex.tree_pane import tree_pane
from helao.ui.shared.operator.object_tree import truncate_uuid
from helao.ui.shared.palette import (
    GROUP_BADGE_CLASSES,
    GROUP_ERROR_TEXT_CLASS,
    GROUP_LABEL_COLORS,
    GROUP_PULSE_DISPATCH,
    GROUP_STATE_COLORS,
    REFLEX_MOTION_STOP_CLASS,
)

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

GRAPH_H, GRAPH_W = 360, 720
#: At least 70 px: below that the progress bar (y=0.08) and the second label
#: line (y=0.32) overlap in pixels once the chart padding is taken off.
STRIP_H, STRIP_W = 70, 720
FAST_MS, SLOW_MS = 16, 500
STALE_S = 5.0
PULSE_S = 0.6
PENDING_TIMEOUT_S = 10.0
NO_ORCH_NOTE = "This config has no orchestrator, so there is no server group to show."
LOST_BANNER = "orchestrator unreachable"
OLD_ORCH_BANNER = "orchestrator lacks /ws_orch — update the orchestrator"
SELECTION_GONE = "selection no longer in view"
NOT_FOUND = "not found on the orchestrator"
LOOP_TO_GROUP = {
    "started": "busy",
    "stopped": "idle",
    "estopped": "estop",
    "error": "error",
}
ORCH_TO_GROUP = {"idle": "idle", "busy": "busy", "error": "error", "estopped": "estop"}

_CFG: dict = {}
_FEED: Optional[WsIngest] = None


def configure_group(world_cfg: dict) -> None:
    """Record the group's orchestrator (the first ``group: orchestrator``).

    This is the same pick ``RemoteBackend._detect_orch_key`` makes, which is
    what lets the page reuse the operator's backend for its buttons.
    """
    servers = (world_cfg or {}).get("servers") or {}
    keys = [
        k
        for k, v in servers.items()
        if isinstance(v, dict) and v.get("group") == "orchestrator"
    ]
    _CFG.clear()
    if keys:
        key = keys[0]
        _CFG.update(orch_key=key, host=servers[key]["host"], port=servers[key]["port"])
        if len(keys) > 1:
            LOGGER.warning(
                f"/group shows the first of {len(keys)} orchestrators: {key} (others: {keys[1:]})"
            )


def start_feed() -> None:
    """Subscribe to /ws_orch once per process. Called from the app lifespan."""
    global _FEED
    if _CFG and _FEED is None:
        _FEED = WsIngest(_CFG["host"], _CFG["port"], "ws_orch", raw_maxlen=200)
        _FEED.start()


async def stop_feed() -> None:
    global _FEED
    if _FEED is not None:
        await _FEED.stop()
        _FEED = None


def _snapshots(batches) -> list:
    return [m for batch in batches for m in batch if isinstance(m, dict)]


def new_frames(feed, cursor: int) -> tuple:
    """``(frames, cursor)``: snapshots that arrived after ``cursor``.

    ``cursor`` counts batches in LOCAL arrival order (``feed.n_batches``), so it
    is immune to the orchestrator's ``seq_no`` going backwards on a restart. A
    cursor ahead of the feed (the feed was recreated) yields nothing.
    """
    if feed is None:
        return [], cursor
    total = feed.n_batches
    raw = list(feed.raw)
    fresh = raw[max(0, len(raw) - (total - cursor)) :] if total > cursor else []
    return _snapshots(fresh), total


def latest_frame(feed):
    """The newest buffered snapshot, or None."""
    frames = _snapshots(list(feed.raw)) if feed is not None else []
    return frames[-1] if frames else None


def stream_lost(feed, now: float) -> bool:
    """Lost while disconnected, never connected, or silent for over 5 s."""
    if feed is None or feed.status.message_count == 0:
        return True
    return now - feed.status.last_epoch > STALE_S


def pulse_for(ev: dict, now: float, orch_key: str):
    """``[edge_id, direction, t0, duration, colour]``; None for the orch's own actions.

    ``t0`` is when the page saw the event, not the event's own time: a 2 Hz
    page would otherwise start a 0.6 s pulse already half done.
    """
    server = ev.get("server")
    if not server or server == orch_key:
        return None
    if ev.get("kind") == "dispatch":
        return [server, "fwd", now, PULSE_S, GROUP_PULSE_DISPATCH]
    state = "error" if ev.get("status") in ERROR_STATUSES else "done"
    return [server, "rev", now, PULSE_S, GROUP_STATE_COLORS[state]]


def _estopped(snap: dict) -> bool:
    return snap.get("loop_state") == "estopped" or snap.get("orch_state") == "estopped"


def button_flags(snap: dict, lost: bool) -> dict:
    estopped = _estopped(snap)
    started = snap.get("loop_state") == "started"
    has_work = snap.get("n_sequences_queued", 0) > 0 or (
        snap.get("seq") is not None
        and any(e.get("state") == "queued" for e in snap.get("experiments", []))
    )
    return {
        "can_start": not lost and not started and not estopped and has_work,
        "can_stop": not lost and started,
        "estopped": estopped,
        "can_estop": not lost,
    }


def pending_done(name: str, snap: dict) -> bool:
    """True once a snapshot reflects the button's effect."""
    if name == "start":
        return snap.get("loop_state") == "started"
    if name == "stop":
        return snap.get("loop_state") != "started"
    if name == "estop":
        return _estopped(snap)
    return not _estopped(snap)


def object_request(kind: str, item: dict):
    """How to fetch a clicked item: by uuid, else by queue index, else nothing."""
    if item.get("uuid"):
        return ("get_object", kind, item["uuid"])
    if item.get("qidx") is not None:
        return ("get_queue_object", kind, item["qidx"])
    return None


def selection_in_view(selected: tuple, slots) -> bool:
    """Is the selected ``(kind, key, name)`` still the same item in ``slots``?

    A queued item is keyed ``q{qidx}`` and qidx shifts when the queue head pops,
    so the same key can name a different experiment. Items without a uuid must
    match by name too.
    """
    _, key, name = selected
    for it in slots:
        if it is not None and item_key(it) == key:
            return bool(it.get("uuid")) or it.get("name") == name
    return False


def _color_key(status: str) -> str:
    return status if status in GROUP_STATE_COLORS else "idle"


def graph_marks(snap: dict, pulses, now: float, orch_key: str, lost: bool):
    """``(marks, live pulses)`` for the network graph."""
    servers = snap.get("servers", [])
    pos = group_layout(orch_key, [s["key"] for s in servers])
    g = NetGraph(height_px=GRAPH_H, width_px=GRAPH_W)
    orch_status = (
        "unreachable"
        if lost
        else ORCH_TO_GROUP.get(snap.get("orch_state") or "", "idle")
    )
    g.add_node(
        orch_key,
        *pos[orch_key],
        color=GROUP_STATE_COLORS[orch_status],
        label_color=GROUP_LABEL_COLORS[orch_status],
        text=orch_key,
        subtext=snap.get("orch_action") or "",
    )
    for s in servers:
        status = "unreachable" if lost else s.get("status", "idle")
        key = _color_key(status)
        text = s["key"] if status in GROUP_STATE_COLORS else f"{s['key']} ({status})"
        g.add_node(
            s["key"],
            *pos[s["key"]],
            color=GROUP_STATE_COLORS[key],
            label_color=GROUP_LABEL_COLORS[key],
            text=text,
            subtext=s.get("active_action") or "",
        )
        g.add_edge(
            s["key"],
            orch_key,
            s["key"],
            color=GROUP_STATE_COLORS[key],
            width=4.0 if status == "busy" else 2.0,
        )
        g.add_arrowhead(s["key"], at="dst")
    for edge_id, direction, t0, duration, color in pulses:
        if edge_id in g.edges:
            g.pulse(edge_id, t0=t0, color=color, direction=direction, duration=duration)
    marks = g.marks(now)
    return marks, [
        [p.edge_id, p.direction, p.t0, p.duration, p.color] for p in g.pulses
    ]


def header_fields(snap: dict) -> dict:
    seq = snap.get("seq") or {}
    t = seq.get("t_start")
    loop_state = snap.get("loop_state", "")
    orch_state = snap.get("orch_state", "")
    return {
        "seq_name": seq.get("name") or "",
        "seq_started": (
            datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S") if t else ""
        ),
        "seq_uuid": seq.get("uuid") or "",
        "seq_uuid_short": truncate_uuid(seq.get("uuid")),
        "loop_state": loop_state,
        "orch_state": orch_state,
        "loop_group": LOOP_TO_GROUP.get(loop_state, "idle"),
        "orch_group": ORCH_TO_GROUP.get(orch_state, "idle"),
        "closing_out": bool(snap.get("closing_out")),
    }


CONTROL_CALLS = {
    "start": lambda b: b.start(strict=True),
    "stop": lambda b: b.stop(reset_run_id=False, strict=True),
    "estop": lambda b: b.estop(strict=True),
    "clear_estop": lambda b: b.clear_estop(strict=True),
}


def _backend(token: str):
    """The operator's session backend, if it targets the orchestrator this page streams.

    ``configure_operator`` is called without an ``orch_key``, so its backend
    takes ``RemoteBackend._detect_orch_key``: the first ``group: orchestrator``
    server, the very pick :func:`configure_group` makes. The check keeps that
    true if either side ever changes; on a mismatch buttons fail loudly rather
    than steer a different orchestrator.
    """
    backend = session_backend(token)
    if backend is not None and getattr(backend, "orch_key", None) != _CFG.get(
        "orch_key"
    ):
        LOGGER.warning(
            f"/group: operator backend targets {getattr(backend, 'orch_key', None)}, "
            f"page streams {_CFG.get('orch_key')}; refusing to use it"
        )
        return None
    return backend


def _render_graph(s, snap: dict, now: float, lost: bool, token: str) -> None:
    s._version += 1
    marks, live = graph_marks(snap, s._pulses, now, _CFG["orch_key"], lost)
    s._pulses = tuple(tuple(p) for p in live)
    p = plots.marks_chart(
        marks,
        x_domain=(-1.0, 1.0),
        y_domain=(-1.0, 1.0),
        panel_id=f"group-graph-{token}",
        version=s._version,
    )
    s.graph_spec, s.graph_url, s.graph_layout = p.spec, p.buffer_url, p.layout


def _render_strips(s, snap: dict, now: float, token: str) -> None:
    v = s._version
    sel_kind, sel_key, _ = s._selected if s._selected else (None, None, None)
    em, exp_slots = strip_marks(
        snap.get("experiments", []),
        n_before=snap.get("n_done", 0),
        n_after=snap.get("n_queued", 0),
        now=now,
        width_px=STRIP_W,
        selected=sel_key if sel_kind == "experiment" else None,
    )
    s._exp_slots = tuple(exp_slots)
    p = plots.marks_chart(
        em,
        x_domain=(0.0, float(max(len(exp_slots), 1))),
        y_domain=(0.0, 1.0),
        panel_id=f"group-exp-{token}",
        version=v,
        click=True,
    )
    s.exp_spec, s.exp_url, s.exp_layout = p.spec, p.buffer_url, p.layout
    am, act_slots = strip_marks(
        snap.get("actions", []),
        n_before=0,
        n_after=0,
        now=now,
        width_px=STRIP_W,
        selected=sel_key if sel_kind == "action" else None,
    )
    s._act_slots = tuple(act_slots)
    p = plots.marks_chart(
        am,
        x_domain=(0.0, float(max(len(act_slots), 1))),
        y_domain=(0.0, 1.0),
        panel_id=f"group-act-{token}",
        version=v,
        click=True,
    )
    s.act_spec, s.act_url, s.act_layout = p.spec, p.buffer_url, p.layout
    if s._selected:
        slots = s._exp_slots if sel_kind == "experiment" else s._act_slots
        if not selection_in_view(s._selected, slots):
            s._selected = ()
            s.info_note = SELECTION_GONE


def apply_tick(s, feed, now: float, token: str) -> bool:
    """One render of state-like ``s``. Returns True when an old-orch probe is due.

    The graph is rebuilt every tick; the header, buttons and both strips only
    when a frame arrived or ``SLOW_MS`` has passed, so the 60 Hz pulse ticks
    cost one chart.
    """
    if s._cursor < 0:
        # First tick after the page opened: show the latest buffered snapshot as
        # the current state, but replay none of its events as pulses.
        if feed is not None:
            latest = latest_frame(feed)
            frames = [latest] if latest else []
            s._cursor = feed.n_batches
            replay = False
        else:
            frames, replay = [], False
    else:
        frames, s._cursor = new_frames(feed, s._cursor)
        replay = True
    pulses = list(s._pulses)
    for f in frames:
        if replay:
            for ev in f.get("events", []):
                p = pulse_for(ev, now, _CFG["orch_key"])
                if p is not None:
                    pulses.append(tuple(p))
    s._pulses = tuple(pulses)
    if frames:
        s._snap = (frames[-1],)
        s._old_orch = False
    snap = s._snap[0] if s._snap else {}
    lost = stream_lost(feed, now)
    _render_graph(s, snap, now, lost, token)
    if frames or now - s._full_at >= SLOW_MS / 1000.0:
        s._full_at = now
        for name, value in header_fields(snap).items():
            setattr(s, name, value)
        for name, value in button_flags(snap, lost).items():
            setattr(s, name, value)
        s.lost = lost
        s.banner = (OLD_ORCH_BANNER if s._old_orch else LOST_BANNER) if lost else ""
        if s.pending and (
            pending_done(s.pending, snap) or now - s._pending_at > PENDING_TIMEOUT_S
        ):
            s.pending = ""
        _render_strips(s, snap, now, token)
    s.tick_ms = FAST_MS if s._pulses else SLOW_MS
    never_live = feed is not None and feed.status.message_count == 0
    return lost and never_live and now - s._probe_at > STALE_S


class GroupState(rx.State):
    """One /group page session. Created at import, before ``add_page``."""

    seq_name: str = ""
    seq_started: str = ""
    seq_uuid: str = ""
    seq_uuid_short: str = ""
    loop_state: str = ""
    orch_state: str = ""
    loop_group: str = "idle"
    orch_group: str = "idle"
    closing_out: bool = False
    can_start: bool = False
    can_stop: bool = False
    can_estop: bool = False
    estopped: bool = False
    lost: bool = True
    pending: str = ""
    action_error: str = ""
    banner: str = ""
    graph_spec: dict = {}
    graph_url: str = ""
    graph_layout: str = ""
    exp_spec: dict = {}
    exp_url: str = ""
    exp_layout: str = ""
    act_spec: dict = {}
    act_url: str = ""
    act_layout: str = ""
    tree_header: str = "select a row"
    tree_html: str = ""
    info_note: str = ""
    tick_ms: int = SLOW_MS
    # Backend vars: tuples only (a list or dict would be MutableProxy-wrapped).
    # _cursor < 0 means "not yet seeded from the feed".
    _cursor: int = -1
    _snap: tuple = ()  # (snapshot,) or ()
    _pulses: tuple = ()  # tuples of (edge, direction, t0, duration, colour)
    _version: int = 0
    _exp_slots: tuple = ()
    _act_slots: tuple = ()
    _selected: tuple = ()  # (kind, key, name) or ()
    _running: bool = False
    _full_at: float = 0.0
    _pending_at: float = 0.0
    _probe_at: float = 0.0
    _old_orch: bool = False

    @rx.event(background=True)
    async def tick(self, _tick: str = ""):
        """One render, driven by the page's ``rx.moment``."""
        if not _CFG:
            return
        async with self:
            if self._running:
                return
            self._running = True
            token = self.router.session.client_token
        try:
            async with self:
                probe = apply_tick(self, _FEED, time.time(), token)
            if probe:
                backend = _backend(token)
                state = await backend.get_orch_state() if backend is not None else {}
                async with self:
                    self._probe_at = time.time()
                    self._old_orch = bool(state)
        finally:
            async with self:
                self._running = False

    @rx.event(background=True)
    async def control(self, name: str):
        """Start / Stop / E-stop / Clear E-stop through RemoteBackend."""
        async with self:
            token = self.router.session.client_token
            self.pending = name
            self.action_error = ""
            self._pending_at = time.time()
        backend = _backend(token)
        err = ""
        if backend is None:
            err = "cannot reach the orchestrator"
        else:
            try:
                await CONTROL_CALLS[name](backend)
            except Exception as exc:
                err = str(exc)
        async with self:
            self.action_error = err
            if err:
                self.pending = ""

    async def _select(self, kind: str, payload: dict):
        async with self:
            token = self.router.session.client_token
            slots = self._exp_slots if kind == "experiment" else self._act_slots
            item = click_item(slots, (payload or {}).get("x"))
            if item is None:
                return
            self._selected = (kind, item_key(item), item.get("name"))
            self.info_note = ""
        request = object_request(kind, item)
        backend = _backend(token)
        obj = None
        if request is not None and backend is not None:
            method, k, ident = request
            try:
                obj = await getattr(backend, method)(k, ident)
            except Exception as exc:
                LOGGER.warning(f"/group could not fetch {kind} {ident}: {exc}")
        async with self:
            self.tree_header, self.tree_html = tree_for(kind, obj)
            if not obj:
                self.info_note = NOT_FOUND

    @rx.event(background=True)
    async def select_exp(self, payload: dict):
        await self._select("experiment", payload)

    @rx.event(background=True)
    async def select_act(self, payload: dict):
        await self._select("action", payload)


def _badge(prefix: str, label_var, group_var):
    """A state badge whose classes are all literal, so Tailwind emits them."""
    return rx.match(
        group_var,
        *[
            (state, rx.badge(prefix, label_var, class_name=cls))
            for state, cls in GROUP_BADGE_CLASSES.items()
        ],
        rx.badge(prefix, label_var, class_name=GROUP_BADGE_CLASSES["idle"]),
    )


def _button(label: str, name: str, enabled_var, class_name: str = ""):
    return rx.button(
        rx.cond(GroupState.pending == name, rx.spinner(size="1"), label),
        on_click=GroupState.control(name),
        disabled=~enabled_var,
        class_name=class_name,
    )


def group_page() -> rx.Component:
    if not _CFG:
        return rx.text(NO_ORCH_NOTE, padding_x="1em")
    S = GroupState
    seq_row = rx.cond(
        S.seq_name == "",
        rx.text("idle — no active sequence"),
        rx.hstack(
            rx.text("SEQ", weight="bold"),
            rx.text(S.seq_name),
            rx.text("started ", S.seq_started),
            rx.text("uuid"),
            rx.tooltip(
                rx.text(S.seq_uuid_short, "…", font_family="monospace"),
                content=S.seq_uuid,
            ),
            rx.button(
                "copy", size="1", variant="soft", on_click=rx.set_clipboard(S.seq_uuid)
            ),
            align="center",
            spacing="2",
        ),
    )
    controls = rx.hstack(
        _badge("loop: ", S.loop_state, S.loop_group),
        _badge("orch: ", S.orch_state, S.orch_group),
        rx.cond(
            S.closing_out,
            rx.badge("closing out", class_name=GROUP_BADGE_CLASSES["unreachable"]),
        ),
        rx.spacer(),
        _button("Start", "start", S.can_start),
        _button("Stop", "stop", S.can_stop),
        rx.cond(
            S.estopped,
            _button("Clear E-stop", "clear_estop", S.can_estop),
            _button("E-stop", "estop", S.can_estop, REFLEX_MOTION_STOP_CLASS),
        ),
        width="100%",
        align="center",
    )
    header = rx.vstack(
        seq_row,
        controls,
        rx.cond(
            S.action_error != "",
            rx.text(S.action_error, class_name=GROUP_ERROR_TEXT_CLASS),
        ),
        rx.cond(S.banner != "", rx.callout(S.banner, icon="triangle_alert")),
        width="100%",
    )
    charts = rx.vstack(
        plots.chart(
            S.graph_spec, S.graph_url, S.graph_layout, height=GRAPH_H, width=GRAPH_W
        ),
        rx.text("EXP", size="1", weight="bold"),
        plots.chart(
            S.exp_spec,
            S.exp_url,
            S.exp_layout,
            height=STRIP_H,
            width=STRIP_W,
            on_select=S.select_exp,
        ),
        rx.text("ACT", size="1", weight="bold"),
        plots.chart(
            S.act_spec,
            S.act_url,
            S.act_layout,
            height=STRIP_H,
            width=STRIP_W,
            on_select=S.select_act,
        ),
    )
    info = rx.vstack(
        rx.text("INFO", weight="bold"),
        rx.cond(S.info_note != "", rx.text(S.info_note, size="1")),
        tree_pane(S.tree_header, S.tree_html),
        width="100%",
    )
    return rx.vstack(
        header,
        rx.hstack(charts, info, width="100%", align="start", spacing="4"),
        rx.moment(interval=S.tick_ms, on_change=S.tick, display="none"),
        on_mount=S.tick(""),
        padding_x="1em",
        width="100%",
    )
