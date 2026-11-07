"""The /group page: server-group graph, sequence timelines, controls, info box.

One process-wide ``WsIngest`` on the orchestrator's ``/ws_orch``; frames are
whole snapshots, read from ``ingest.raw``. ``GroupState`` is a plain
``rx.State`` (one page per orchestrator) ticked by ``rx.moment`` at 2 Hz. Never
a server-side loop. Pulses are not animated here: each is sent ONCE as a
descriptor (:func:`pulse_items`) and the chart shim moves it at display
refresh. Buttons and the
info box go over HTTP: the four control buttons straight through
``async_private_dispatcher`` (building a ``RemoteBackend`` runs ``import_autolibs``
on the Reflex loop, which would stall the first click), the info box through the
operator's ``RemoteBackend``, bound to the same orchestrator this page streams
from (see :func:`_backend`).

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

from helao.core.error import ErrorCodes
from helao.core.models.group_snapshot import ERROR_STATUSES
from helao.helpers import helao_logging as logging
from helao.helpers.dispatcher import async_private_dispatcher
from helao.ui.reflex import plots
from helao.ui.reflex.ingest import WsIngest
from helao.ui.reflex.netgraph import NetGraph, group_layout
from helao.ui.reflex.operator import TREE_EMPTY_HEADER, session_backend, tree_for
from helao.ui.reflex.timeline_strip import (
    HIT_TRACE,
    click_item,
    hit_slot,
    item_key,
    item_tooltip,
    strip_marks,
)
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
#: A strip is a fixed-height chart (``marks_chart(height_px=...)``): xy floors a
#: fixed height at 48 px, but a fluid (``"100%"``) one at 120 px, which would
#: spill out of a shorter card.
STRIP_H, STRIP_W = 60, 720
#: What a strip's segments divide: the host width less xy's padding both sides.
PLOT_W = STRIP_W - 2 * plots.CHART_PADDING_PX
#: Wide enough that a short server key (5-6 characters) sits inside its node.
NODE_PX = 44.0
#: The browser draws the node under the pointer this large, in its own colour.
HOVER_PX = round(NODE_PX * 1.3)
#: Every (colour, width) a server edge can take; a busy edge is thicker. Each
#: is a fixed trace of the graph, so a status change is column data, not a
#: chart rebuild.
#: A node's colour is its status; the strips' done/queued colours never reach it.
NODE_STATUSES = ("idle", "busy", "error", "estop", "unreachable")
NODE_COLORS = tuple(sorted({GROUP_STATE_COLORS[k] for k in NODE_STATUSES}))
EDGE_STYLES = tuple(
    sorted({(c, 4.0 if k == "busy" else 2.0) for k, c in GROUP_STATE_COLORS.items()})
)
SLOW_MS = 500
#: The graph's fixed view, for the shim's pulse overlay: data domain and padding.
PULSE_VIEW = {"x": [-1.0, 1.0], "y": [-1.0, 1.0], "pad": plots.CHART_PADDING_PX}
STALE_S = 5.0
#: Long enough that the one remaining chart rebuild (a strip whose slot count
#: changed, ~150 ms of frozen main thread) cannot swallow a pulse.
PULSE_S = 1.2
#: Frames that arrive in one tick pulse only their last second of events.
CATCH_UP_S = 1.0
PENDING_TIMEOUT_S = 10.0
NO_ORCH_NOTE = "This config has no orchestrator, so there is no server group to show."
LOST_BANNER = "orchestrator unreachable"
OLD_ORCH_BANNER = "orchestrator lacks /ws_orch — update the orchestrator"
SELECTION_GONE = "selection no longer in view"
NOT_FOUND = "not found on the orchestrator"
QUEUE_MOVED = "the queue moved since this was drawn; click again"
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
    page would otherwise start a pulse already half done.
    """
    server = ev.get("server")
    if not server or server == orch_key:
        return None
    if ev.get("kind") == "dispatch":
        return [server, "fwd", now, PULSE_S, GROUP_PULSE_DISPATCH]
    state = "error" if ev.get("status") in ERROR_STATUSES else "done"
    return [server, "rev", now, PULSE_S, GROUP_STATE_COLORS[state]]


def queue_pulse(pulses, p) -> list:
    """``pulses`` plus ``p``, bounded per edge.

    A dispatch and a finish seen in one frame (a short action) share an edge;
    both start at once and cross mid-edge, so the return leg is lost in the
    crossing. So ``p`` starts once the edge's last pulse has ended, but never
    more than one pulse-length ahead, and an edge holds at most one not-yet-
    started pulse per direction: a burst (a run of short actions, or a tab
    catching up) merges into that one instead of queueing for minutes.
    """
    edge, direction, now, duration = p[0], p[1], p[2], p[3]
    same = [q for q in pulses if q[0] == edge]
    if any(q[1] == direction and q[2] > now for q in same):
        return list(pulses)
    end = max((q[2] + q[3] for q in same), default=now)
    return [*pulses, (edge, direction, min(max(now, end), now + duration), *p[3:])]


def recent_events(frames, window: float = CATCH_UP_S) -> list:
    """Events of ``frames`` from the last ``window`` s of event time.

    A page that was backgrounded returns to many frames at once; pulsing every
    event in them would animate minutes of history. Events without a time stay.
    """
    events = [ev for f in frames for ev in f.get("events", [])]
    times = [ev["t"] for ev in events if isinstance(ev.get("t"), (int, float))]
    if not times:
        return events
    cut = max(times) - window
    return [
        ev
        for ev in events
        if not isinstance(ev.get("t"), (int, float)) or ev["t"] >= cut
    ]


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
        # A lost stream must not stop the operator from e-stopping.
        "can_estop": not estopped,
        "can_clear_estop": not lost and estopped,
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


def fetched_info(kind: str, item: dict, obj) -> tuple:
    """``(obj to show, note)`` for a clicked item's fetch result.

    Queued experiments and actions carry uuids (from enqueue / unpack) and are
    fetched by uuid; only a row without one falls back to a queue-index fetch,
    which is what the rest of this applies to. ``qidx`` is absolute and comes
    from the last drawn snapshot; a head pop before the click shifts every
    index, so such a fetch can return the neighbour. The name is then the only
    identity the row has, so a name mismatch is never shown; a same-named
    neighbour cannot be told apart. An empty result (out of range,
    unreachable, failed) stays "not found".
    """
    if not obj:
        return None, NOT_FOUND
    if item.get("uuid") or item.get("qidx") is None:
        return obj, ""
    if obj.get(f"{kind}_name") != item.get("name"):
        return None, QUEUE_MOVED
    return obj, ""


def exp_row_ordinals(snap: dict) -> list:
    """Stable sequence ordinal of each windowed experiment row.

    Done rows run ``n_done ...``; the active row is ``done_total``; a queued row
    is ``done_total + (1 if an active row exists) + qidx``. The ordinal does not
    move when the queue head pops or when a queued item becomes active, unlike
    ``q{qidx}`` (which also cannot tell same-named experiments apart).
    """
    rows = snap.get("experiments", [])
    n_finished = sum(1 for r in rows if r.get("state") in ("done", "error"))
    done_total = snap.get("n_done", 0) + n_finished
    has_active = any(r.get("state") == "active" for r in rows)
    ords, seen_done = [], 0
    for r in rows:
        state = r.get("state")
        if state in ("done", "error"):
            ords.append(snap.get("n_done", 0) + seen_done)
            seen_done += 1
        elif state == "active":
            ords.append(done_total)
        else:
            ords.append(done_total + (1 if has_active else 0) + (r.get("qidx") or 0))
    return ords


def selection_scope(snap: dict, kind: str):
    """What an ordinal is relative to: the sequence, and for actions the experiment.

    Both follow the strip: EXP clears when the sequence changes, ACT when the
    experiment it shows does (``act_exp``: the active one, else the last
    finished). Frames from an older orchestrator carry no ``act_exp`` and fall
    back to the active experiment's ordinal.
    """
    seq = (snap.get("seq") or {}).get("uuid")
    if kind == "experiment":
        return (seq,)
    if "act_exp" in snap:  # the experiment whose actions the ACT strip shows
        return (seq, snap["act_exp"])
    rows, ords = snap.get("experiments", []), exp_row_ordinals(snap)
    active = next((o for r, o in zip(rows, ords) if r.get("state") == "active"), None)
    return (seq, active)


def _slot_ordinals(snap: dict, kind: str) -> tuple:
    """Ordinals aligned with ``strip_marks``' slots (None for an ellipsis)."""
    if kind == "action":
        return tuple(range(len(snap.get("actions", []))))
    return (
        ((None,) if snap.get("n_done", 0) else ())
        + tuple(exp_row_ordinals(snap))
        + ((None,) if snap.get("n_queued", 0) else ())
    )


def selected_key(selected: tuple, snap: dict, kind: str):
    """``item_key`` of the selected row if it is still in view, else None."""
    if (
        not selected
        or selected[0] != kind
        or selected[2] != selection_scope(snap, kind)
    ):
        return None
    rows = snap.get("experiments" if kind == "experiment" else "actions", [])
    ords = exp_row_ordinals(snap) if kind == "experiment" else list(range(len(rows)))
    for row, o in zip(rows, ords):
        if o == selected[1]:
            return item_key(row)
    return None


def _color_key(status: str) -> str:
    return status if status in GROUP_STATE_COLORS else "idle"


def build_graph(snap: dict, orch_key: str, lost: bool) -> NetGraph:
    """The network graph for one snapshot: nodes and edges."""
    servers = snap.get("servers", [])
    pos = group_layout(orch_key, [s["key"] for s in servers])
    g = NetGraph(
        height_px=GRAPH_H,
        width_px=GRAPH_W,
        edge_styles=EDGE_STYLES,
        node_colors=NODE_COLORS,
        hover_px=HOVER_PX,
    )
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
        size_px=NODE_PX,
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
            size_px=NODE_PX,
        )
        g.add_edge(
            s["key"],
            orch_key,
            s["key"],
            color=GROUP_STATE_COLORS[key],
            width=4.0 if status == "busy" else 2.0,
        )
    return g


def graph_marks(snap: dict, orch_key: str, lost: bool):
    """Marks for the network graph: a pure function of the snapshot."""
    return build_graph(snap, orch_key, lost).marks()


def node_batch(g: NetGraph) -> dict:
    """The graph's node descriptors for the shim's hover overlay (``nodes`` prop).

    ``hover_r`` is the radius, in px, of the enlarged circle the browser draws.
    """
    return {"view": PULSE_VIEW, "hover_r": HOVER_PX / 2, "items": g.node_descriptors()}


def pulse_items(snap: dict, fresh, now: float, orch_key: str, lost: bool) -> list:
    """Descriptors for newly queued pulses, each sent to the browser once.

    ``fresh`` holds ``(edge, direction, t0, duration, colour)``. ``start_in`` is
    seconds from now, so the browser schedules from its own receipt time and a
    page/server clock difference cannot skip or delay a pulse. ``path`` is the
    edge's sampled curve in data units in TRAVEL order (reversed for ``rev``);
    the shim offsets it to one side, so the two directions take opposite lanes.
    """
    g = build_graph(snap, orch_key, lost)
    items = []
    for edge, direction, t0, duration, color in fresh:
        if edge not in g.edges:
            continue
        path = g.edge_path(edge)
        if direction != "fwd":
            path = path[::-1]
        items.append(
            {
                "id": f"{edge}|{direction}|{t0:.3f}",
                "dir": direction,
                "start_in": round(t0 - now, 3),
                "dur": duration,
                "color": color,
                "path": [[round(x, 5), round(y, 5)] for x, y in path],
            }
        )
    return items


def current_experiment(snap: dict):
    """The EXP strip's current row: the active one, else the last finished."""
    rows = snap.get("experiments", [])
    active = [r for r in rows if r.get("state") == "active"]
    done = [r for r in rows if r.get("state") in ("done", "error")]
    return (active or done or [None])[-1]


def current_action(snap: dict):
    """The ACT strip's current row: the most recently STARTED active action,
    else the last finished one (rows are in dispatch order)."""
    rows = snap.get("actions", [])
    active = [r for r in rows if r.get("state") == "active"]
    if active:
        return max(active, key=lambda r: r.get("t_start") or 0.0)
    done = [r for r in rows if r.get("state") in ("done", "error")]
    return done[-1] if done else None


def _current_fields(prefix: str, row) -> dict:
    t = (row or {}).get("t_start")
    uuid = (row or {}).get("uuid") or ""
    return {
        f"{prefix}_name": (row or {}).get("name") or "",
        f"{prefix}_started": (
            datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S") if t else ""
        ),
        f"{prefix}_uuid": uuid,
        f"{prefix}_uuid_short": truncate_uuid(uuid) if uuid else "",
        f"{prefix}_state": (row or {}).get("state") or "",
    }


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
        "seq_finished": bool(seq.get("finished")),
        # frames from an older orchestrator carry no `ended`
        "seq_ended": (seq.get("ended") or "finished") if seq.get("finished") else "",
        "loop_state": loop_state,
        "orch_state": orch_state,
        "loop_group": LOOP_TO_GROUP.get(loop_state, "idle"),
        "orch_group": ORCH_TO_GROUP.get(orch_state, "idle"),
        "closing_out": bool(snap.get("closing_out")),
        **_current_fields("exp", current_experiment(snap)),
        **_current_fields("act", current_action(snap)),
    }


#: button name -> (orchestrator endpoint, params)
CONTROL_CALLS = {
    "start": ("start", {}),
    "stop": ("stop", {"reset_run_id": False}),
    "estop": ("estop_orch", {}),
    "clear_estop": ("clear_estop", {}),
}


async def _control_call(name: str) -> None:
    """Raise unless the orchestrator took the call. No ``RemoteBackend`` involved."""
    endpoint, params = CONTROL_CALLS[name]
    _, err = await async_private_dispatcher(
        _CFG["orch_key"],
        _CFG["host"],
        _CFG["port"],
        endpoint,
        params_dict=params,
        json_dict={},
    )
    if err != ErrorCodes.none:
        raise RuntimeError(f"{endpoint} failed: {err}")


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


def _render_graph(s, snap: dict, lost: bool, token: str) -> None:
    s._version += 1
    g = build_graph(snap, _CFG["orch_key"], lost)
    # Sent only on a real change (topology or a status colour), never per hover.
    batch = node_batch(g)
    if batch != s.graph_nodes:
        s.graph_nodes = batch
    p = plots.marks_chart(
        g.marks(),
        x_domain=(-1.0, 1.0),
        y_domain=(-1.0, 1.0),
        panel_id=f"group-graph-{token}",
        version=s._version,
    )
    s.graph_spec, s.graph_url, s.graph_layout = p.spec, p.buffer_url, p.layout


def _hover_line(slots, slot: int, now: float) -> str:
    return item_tooltip(slots[slot], now) if 0 <= slot < len(slots) else ""


def _render_strips(s, snap: dict, now: float, token: str) -> None:
    v = s._version
    exp_key = selected_key(s._selected, snap, "experiment")
    act_key = selected_key(s._selected, snap, "action")
    em, exp_slots, exp_edges = strip_marks(
        snap.get("experiments", []),
        n_before=snap.get("n_done", 0),
        n_after=snap.get("n_queued", 0),
        now=now,
        width_px=PLOT_W,
        selected=exp_key,
    )
    s._exp_slots = tuple(exp_slots)
    s._exp_edges = exp_edges
    s._exp_ords = _slot_ordinals(snap, "experiment")
    s._scopes = (selection_scope(snap, "experiment"), selection_scope(snap, "action"))
    p = plots.marks_chart(
        em,
        x_domain=(0.0, float(PLOT_W)),
        y_domain=(0.0, 1.0),
        panel_id=f"group-exp-{token}",
        version=v,
        click=True,
        hover_events=True,
        height_px=STRIP_H,
    )
    s.exp_spec, s.exp_url, s.exp_layout = p.spec, p.buffer_url, p.layout
    am, act_slots, act_edges = strip_marks(
        snap.get("actions", []),
        n_before=0,
        n_after=0,
        now=now,
        width_px=PLOT_W,
        selected=act_key,
    )
    s._act_slots = tuple(act_slots)
    s._act_edges = act_edges
    s._act_ords = _slot_ordinals(snap, "action")
    p = plots.marks_chart(
        am,
        x_domain=(0.0, float(PLOT_W)),
        y_domain=(0.0, 1.0),
        panel_id=f"group-act-{token}",
        version=v,
        click=True,
        hover_events=True,
        height_px=STRIP_H,
    )
    s.act_spec, s.act_url, s.act_layout = p.spec, p.buffer_url, p.layout
    # the hover line keeps following its slot: the elapsed time ticks
    s.exp_hover = _hover_line(s._exp_slots, s._hover_slot[0], now)
    s.act_hover = _hover_line(s._act_slots, s._hover_slot[1], now)
    if s._selected and (exp_key if s._selected[0] == "experiment" else act_key) is None:
        s._selected = ()
        s.info_note = SELECTION_GONE
        s.tree_header, s.tree_html = TREE_EMPTY_HEADER, ""


def reset_for_mount(s) -> None:
    """A page (re)entering: state outlives navigation, so forget the old watermark.

    Without this a return to /group would replay every buffered event as pulses.
    """
    s._cursor = -1
    s._pulses = ()
    s._old_orch = False
    s._first_at = 0.0
    s._full_at = 0.0
    s._hover_slot = (-1, -1)
    s.graph_pulses = {"view": PULSE_VIEW, "seq": s._pulse_seq, "items": []}


def apply_tick(s, feed, now: float, token: str) -> bool:
    """One render of state-like ``s``. Returns True when an old-orch probe is due.

    The graph, header, buttons and strips are redrawn only when a frame arrived
    or ``SLOW_MS`` has passed: nothing in them moves with time, because pulses
    travel in the browser. A pulse queued this tick is published once, in
    ``graph_pulses``, and left alone until the next one.
    """
    if s._first_at <= 0:
        s._first_at = now
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
    # Only bounding needs the pulses the browser is still animating.
    pulses = [p for p in s._pulses if p[2] + p[3] > now]
    kept = list(pulses)
    if replay:
        for ev in recent_events(frames):
            p = pulse_for(ev, now, _CFG["orch_key"])
            if p is not None:
                pulses = queue_pulse(pulses, tuple(p))
    s._pulses = tuple(pulses)
    fresh = [p for p in pulses if p not in kept]
    if frames:
        s._snap = (frames[-1],)
        s._old_orch = False
    snap = s._snap[0] if s._snap else {}
    lost = stream_lost(feed, now)
    if fresh:
        s._pulse_seq += 1
        s.graph_pulses = {
            "view": PULSE_VIEW,
            "seq": s._pulse_seq,
            "items": pulse_items(snap, fresh, now, _CFG["orch_key"], lost),
        }
    if frames or now - s._full_at >= SLOW_MS / 1000.0:
        _render_graph(s, snap, lost, token)
        s._full_at = now
        for name, value in header_fields(snap).items():
            setattr(s, name, value)
        for name, value in button_flags(snap, lost).items():
            setattr(s, name, value)
        s.lost = lost
        s.banner = (OLD_ORCH_BANNER if s._old_orch else LOST_BANNER) if lost else ""
        if s.pending and pending_done(s.pending, snap):
            s.pending = ""
        elif s.pending and now - s._pending_at > PENDING_TIMEOUT_S:
            s.action_error = f"{s.pending} not confirmed by the orchestrator"
            s._unconfirmed = s.pending
            s.pending = ""
        # a late snapshot that does show the effect retires that message only
        if (
            s._unconfirmed
            and s.action_error.startswith(f"{s._unconfirmed} not confirmed")
            and pending_done(s._unconfirmed, snap)
        ):
            s.action_error = ""
            s._unconfirmed = ""
        _render_strips(s, snap, now, token)
    s.tick_ms = SLOW_MS
    never_live = feed is not None and feed.status.message_count == 0
    # The heartbeat is 2 s: a page that has only just opened has not waited
    # long enough to call the orchestrator old.
    waited = s._first_at > 0 and now - s._first_at > STALE_S
    return lost and never_live and waited and now - s._probe_at > STALE_S


class GroupState(rx.State):
    """One /group page session. Created at import, before ``add_page``."""

    seq_name: str = ""
    seq_started: str = ""
    seq_uuid: str = ""
    seq_uuid_short: str = ""
    seq_finished: bool = False
    seq_ended: str = ""
    loop_state: str = ""
    orch_state: str = ""
    loop_group: str = "idle"
    orch_group: str = "idle"
    closing_out: bool = False
    exp_name: str = ""
    exp_started: str = ""
    exp_uuid: str = ""
    exp_uuid_short: str = ""
    exp_state: str = ""
    act_name: str = ""
    act_started: str = ""
    act_uuid: str = ""
    act_uuid_short: str = ""
    act_state: str = ""
    exp_hover: str = ""
    act_hover: str = ""
    can_start: bool = False
    can_stop: bool = False
    # on before the first frame: the operator can always E-STOP (HTTP, no stream)
    can_estop: bool = True
    can_clear_estop: bool = False
    estopped: bool = False
    lost: bool = True
    pending: str = ""
    action_error: str = ""
    banner: str = ""
    graph_pulses: dict = {"view": PULSE_VIEW, "seq": 0, "items": []}
    graph_nodes: dict = {"view": PULSE_VIEW, "hover_r": HOVER_PX / 2, "items": []}
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
    _exp_edges: tuple = (0.0, float(PLOT_W))
    _act_edges: tuple = (0.0, float(PLOT_W))
    _exp_ords: tuple = ()
    _act_ords: tuple = ()
    _scopes: tuple = ()  # (experiment scope, action scope)
    _selected: tuple = ()  # (kind, key, name) or ()
    _running: bool = False
    _full_at: float = 0.0
    _pending_at: float = 0.0
    _unconfirmed: str = ""  # button whose "not confirmed" message is showing
    _probe_at: float = 0.0
    _first_at: float = 0.0
    _pulse_seq: int = 0
    _hover_slot: tuple = (-1, -1)  # hovered (EXP, ACT) slot, -1 for none
    _old_orch: bool = False

    @rx.event
    def mount(self):
        """Page mount: reset the watermark, then take the first tick."""
        reset_for_mount(self)
        return GroupState.tick("")

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
        """Start / Stop / E-stop / Clear E-stop straight to the orchestrator."""
        async with self:
            self.pending = name
            self.action_error = ""
            self._unconfirmed = ""
            self._pending_at = time.time()
        err = ""
        if not _CFG:
            err = "cannot reach the orchestrator"
        else:
            try:
                await _control_call(name)
            except Exception as exc:
                err = str(exc)
        async with self:
            self.action_error = err
            if err:
                self.pending = ""

    def _hover_strip(self, which: int, payload: dict) -> None:
        """Pointer over (or off) a strip segment: set only the hover line.

        No chart redraw: the line is plain text, so hovering never rebuilds or
        re-uploads a strip.
        """
        slots = self._exp_slots if which == 0 else self._act_slots
        edges = self._exp_edges if which == 0 else self._act_edges
        trace = (payload or {}).get("trace")
        slot = (
            hit_slot((payload or {}).get("index", -1), edges)
            if trace == HIT_TRACE
            else -1  # the pointer left the strip's points
        )
        if slot is None:
            slot = -1
        cur = list(self._hover_slot)
        if cur[which] == slot:
            return
        cur[which] = slot
        self._hover_slot = tuple(cur)
        line = _hover_line(slots, slot, time.time())
        if which == 0:
            self.exp_hover = line
        else:
            self.act_hover = line

    @rx.event
    def hover_exp(self, payload: dict):
        self._hover_strip(0, payload)

    @rx.event
    def hover_act(self, payload: dict):
        self._hover_strip(1, payload)

    async def _select(self, kind: str, payload: dict):
        async with self:
            token = self.router.session.client_token
            exp = kind == "experiment"
            slots = self._exp_slots if exp else self._act_slots
            edges = self._exp_edges if exp else self._act_edges
            ords = self._exp_ords if exp else self._act_ords
            item = click_item(slots, edges, (payload or {}).get("x"))
            if item is None or len(self._scopes) != 2:
                return
            at = next(i for i, it in enumerate(slots) if it is item)
            self._selected = (kind, ords[at], self._scopes[0 if exp else 1])
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
        obj, note = fetched_info(kind, item, obj)
        async with self:
            self.tree_header, self.tree_html = tree_for(kind, obj)
            if note:
                self.info_note = note

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


def _seq_ended_badge(ended_var) -> rx.Component:
    """How the finished sequence ended; classes literal for Tailwind."""
    return rx.match(  # type: ignore[return-value]
        ended_var,
        ("estopped", rx.badge("E-stopped", class_name=GROUP_BADGE_CLASSES["estop"])),
        ("error", rx.badge("error", class_name=GROUP_BADGE_CLASSES["error"])),
        rx.badge("finished", class_name=GROUP_BADGE_CLASSES["idle"]),
    )


def _button(
    label: str, name: str, enabled_var, class_name: str = "", gate_pending: bool = True
):
    """A control button. ``gate_pending=False`` (E-stop) never waits on another call."""
    disabled = ~enabled_var
    if gate_pending:
        disabled = disabled | (GroupState.pending != "")
    return rx.button(
        rx.cond(GroupState.pending == name, rx.spinner(size="1"), label),
        on_click=GroupState.control(name),
        disabled=disabled,
        class_name=class_name,
    )


def _uuid_row(label: str, name, state, started, uuid, short) -> rx.Component:
    """One header row under the sequence line; "—" while there is none."""
    return rx.cond(
        name == "",
        rx.hstack(
            rx.text(label, weight="bold", size="2"), rx.text("—", size="2"), spacing="2"
        ),
        rx.hstack(
            rx.text(label, weight="bold", size="2"),
            rx.text(name, size="2"),
            rx.text("(", state, ")", size="1"),
            rx.cond(started != "", rx.text("started ", started, size="2")),
            rx.text("uuid", size="2"),
            rx.tooltip(
                rx.text(short, "…", font_family="monospace", size="2"), content=uuid
            ),
            rx.button(
                "copy", size="1", variant="soft", on_click=rx.set_clipboard(uuid)
            ),
            align="center",
            spacing="2",
        ),
    )


def _strip_card(label: str, hover_var, chart) -> rx.Component:
    """A strip's card: the ``EXP``/``ACT`` header line, hover text beside it, the chart."""
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.text(label, size="1", weight="bold"),
                rx.text(hover_var, size="1"),
                align="center",
                spacing="2",
            ),
            chart,
            spacing="1",
        ),
        size="1",
    )


def group_page() -> rx.Component:
    if not _CFG:
        return rx.text(NO_ORCH_NOTE, padding_x="1em")
    S = GroupState
    seq_row = rx.cond(
        S.seq_name == "",
        rx.text("idle — no active sequence", size="2"),
        rx.hstack(
            rx.text("SEQ", weight="bold", size="2"),
            rx.text(S.seq_name, size="2"),
            rx.cond(
                S.seq_finished,
                _seq_ended_badge(S.seq_ended),
            ),
            rx.text("started ", S.seq_started, size="2"),
            rx.text("uuid", size="2"),
            rx.tooltip(
                rx.text(S.seq_uuid_short, "…", font_family="monospace", size="2"),
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
            _button("Clear E-stop", "clear_estop", S.can_clear_estop),
            _button(
                "E-stop",
                "estop",
                S.can_estop,
                REFLEX_MOTION_STOP_CLASS,
                gate_pending=False,
            ),
        ),
        width="100%",
        align="center",
    )
    header = rx.vstack(
        seq_row,
        _uuid_row(
            "EXP", S.exp_name, S.exp_state, S.exp_started, S.exp_uuid, S.exp_uuid_short
        ),
        _uuid_row(
            "ACT", S.act_name, S.act_state, S.act_started, S.act_uuid, S.act_uuid_short
        ),
        controls,
        rx.cond(
            S.action_error != "",
            rx.text(S.action_error, class_name=GROUP_ERROR_TEXT_CLASS),
        ),
        rx.cond(S.banner != "", rx.callout(S.banner, icon="triangle_alert")),
        width="100%",
    )
    # One card per chart, the same Radix card as INFO; a strip's header line
    # (with its hover text) is inside its card. The card paints the surface and
    # border, so the charts draw on a transparent background.
    charts = rx.vstack(
        rx.card(
            plots.chart(
                S.graph_spec,
                S.graph_url,
                S.graph_layout,
                height=GRAPH_H,
                width=GRAPH_W,
                pulses=S.graph_pulses,
                nodes=S.graph_nodes,
            ),
            size="1",
        ),
        _strip_card(
            "EXP",
            S.exp_hover,
            plots.chart(
                S.exp_spec,
                S.exp_url,
                S.exp_layout,
                height=STRIP_H,
                width=STRIP_W,
                on_select=S.select_exp,
                on_hover=S.hover_exp,
            ),
        ),
        _strip_card(
            "ACT",
            S.act_hover,
            plots.chart(
                S.act_spec,
                S.act_url,
                S.act_layout,
                height=STRIP_H,
                width=STRIP_W,
                on_select=S.select_act,
                on_hover=S.hover_act,
            ),
        ),
    )
    # Stretches to the chart column's height (graph + both strips), so the
    # box ends at the ACT card's bottom edge. Its content is absolutely
    # positioned: a tall tree must scroll inside the box, not stretch the row.
    info = rx.card(
        rx.vstack(
            rx.text("INFO", weight="bold"),
            rx.cond(S.info_note != "", rx.text(S.info_note, size="1")),
            tree_pane(S.tree_header, S.tree_html, fill=True),
            position="absolute",
            inset="0",
            padding="0.75em",
        ),
        position="relative",
        flex="1",
        min_width="0",
    )
    return rx.vstack(
        header,
        rx.hstack(charts, info, width="100%", align="stretch", spacing="4"),
        rx.moment(interval=S.tick_ms, on_change=S.tick, display="none"),
        on_mount=S.mount,
        padding_x="1em",
        width="100%",
    )
