"""The Reflex binding for xy that xy itself does not yet ship.

``xy`` 0.0.5 has no ``xy.reflex`` module — its own source calls the Reflex
adapter planned work. What it does ship is everything that adapter would have
wrapped: a versioned ESM render client inside the wheel (no CDN, which is what
airgapped lab stations need), a split payload of small JSON spec plus raw
column buffers, and a defined binary frame protocol. This module is the ~100
lines of glue between those and Reflex.

Two design points are load-bearing:

* **Bulk data never enters Reflex state.** Reflex syncs state as JSON over its
  WebSocket; pushing megabyte float arrays through it would forfeit exactly the
  performance xy exists to provide. The small spec rides a state var carrying a
  version token; the browser fetches column buffers from :func:`make_buffer_router`
  and decodes them with the bundle's own ``decodeFrame``.
* **Updates append, they do not re-render.** The bundle exposes an explicit
  append path — bump ``spec.append.seq``, swap buffers, fire the change events —
  and updates the view in place. The shim fires both events and never tears the
  view down on data change.

Delete this module when xy ships its own adapter: :mod:`plots` is the only
consumer.
"""

__all__ = [
    "XYChart",
    "xy_chart",
    "BufferStore",
    "encode_buffers",
    "make_buffer_router",
    "copy_client_asset",
    "client_asset_source",
    "CLIENT_ASSET_NAME",
    "BUFFER_ROUTE_PREFIX",
]

import collections
import os
import pathlib
import threading

import reflex as rx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

import xy.channel
import xy.widget

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: Filename the xy ESM client is published under in the Reflex assets dir.
#: Reflex serves ``assets/`` from the site root, so the browser sees "/<name>".
CLIENT_ASSET_NAME = "xy-client.js"

#: URL prefix for the column-buffer route.
BUFFER_ROUTE_PREFIX = "/xy/buffers"


def client_asset_source() -> pathlib.Path:
    """Path of xy's bundled ESM client inside the installed package.

    Exposed because the bundle stamp hashes this source rather than the copy
    under ``assets/`` (the copy is made by the build, so hashing it would
    record nothing before the first one). Callers outside this module must ask
    for the path instead of importing ``xy`` themselves: only this module and
    the plot facade may touch that alpha API, and a test enforces it.
    """
    return pathlib.Path(xy.widget.__file__).parent / "static" / "index.js"


def copy_client_asset(dest_dir: str) -> str:
    """Copy xy's bundled ESM client into the Reflex assets directory.

    The bundle is a generated artifact that ships inside published wheels. A
    source-checkout install lacks it, and xy's own error names the fix
    (``npm ci && node js/build.mjs``).

    Args:
        dest_dir: Reflex ``assets/`` directory.

    Returns:
        str: Path of the written asset.

    Raises:
        FileNotFoundError: If the wheel carries no bundled client.
    """
    source = client_asset_source()
    if not source.is_file():
        raise FileNotFoundError(
            f"xy's bundled ESM client is missing at '{source}'. A published "
            "wheel ships it prebuilt; a source checkout must build it once "
            "with `npm ci && node js/build.mjs`."
        )
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, CLIENT_ASSET_NAME)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(patch_client_nan(source.read_text(encoding="utf-8")))
    return dest


#: xy's shaders build NaN as ``uintBitsToFloat(0x7fc00000u)``. Firefox on
#: Linux/NVIDIA translates ESSL 3.00 to desktop GLSL below 330 without
#: ``GL_ARB_shader_bit_encoding``, so every shader fails to compile ("error
#: C7532: global function uintBitsToFloat requires #version 330"). Measured on
#: that stack: ``0.0/0.0`` is folded back into the same call by ANGLE, and a
#: local ``z/z`` survives compilation but NVIDIA's fast math makes it 1.0. Only
#: a uniform divided by itself is opaque to both; uniforms default to 0.0 and
#: xy never sets this one, so it evaluates 0/0 = NaN at runtime.
_NAN_EXPR = "uintBitsToFloat(0x7fc00000u)"
_NAN_ANCHOR = "float xyDecode(float encoded, vec2 meta)"
_NAN_UNIFORM = "xyNanZero"


def patch_client_nan(js: str) -> str:
    """Rewrite xy's bit-cast NaN constant to a form every driver compiles.

    The uniform is declared ahead of ``xyDecode``, the head of the GLSL
    snippet every shader using the constant includes. ``highp`` is explicit
    because a uniform shared by both stages must match precision.

    Args:
        js: Source of xy's bundled ESM client.

    Returns:
        str: The patched source; unchanged if xy stops using the constant.

    Raises:
        RuntimeError: If the constant is present but the anchor is not, i.e.
            xy's shader layout changed under us.
    """
    if _NAN_EXPR not in js:
        return js
    if js.count(_NAN_ANCHOR) != 1:
        raise RuntimeError(
            f"xy client uses {_NAN_EXPR} but '{_NAN_ANCHOR}' no longer appears "
            "exactly once; update patch_client_nan for this xy version."
        )
    js = js.replace(_NAN_ANCHOR, f"uniform highp float {_NAN_UNIFORM};\n{_NAN_ANCHOR}")
    return js.replace(_NAN_EXPR, f"({_NAN_UNIFORM} / {_NAN_UNIFORM})")


def encode_buffers(buffers) -> bytes:
    """Encode column buffers using xy's own frame protocol.

    Using ``xy.channel`` rather than an ad-hoc format means the browser decodes
    with the bundle's exported ``decodeFrame`` and the two halves cannot drift.

    ``encode_frame_parts`` takes a JSON-able metadata mapping plus the buffer
    sequence and returns scatter/gather parts (header, metadata, then each
    buffer with its length prefix and alignment padding) without copying the
    buffer payloads; an HTTP response body needs one contiguous blob, so the
    parts are joined here. No column metadata belongs in the frame — the
    figure spec (parked separately, in the Reflex state var) already carries
    everything the browser needs to interpret each column.

    Args:
        buffers: The ``list[memoryview]`` from ``Figure.build_payload_split``.

    Returns:
        bytes: One encoded frame carrying every column.
    """
    parts = xy.channel.encode_frame_parts({}, list(buffers))
    return b"".join(bytes(part) for part in parts)


#: Frames retained per panel. One is not enough: the browser is told a new
#: version in the same state delta that replaces the buffers, so a fetch of
#: version N is in flight exactly while the panel is publishing N+1. Keeping
#: only the newest meant that fetch 404'd whenever the round trip outlasted
#: one tick -- which, with the frontend proxying the route through to the
#: backend, it reliably did while data was streaming. The chart then held its
#: last good frame with nothing logged, and the whole trace appeared at once
#: when the action ended and publishing stopped.
#:
#: The count has to cover the round trip measured in *ticks*, so it is a
#: function of the render cadence. Four sufficed at the 2-4 Hz panels used to
#: run at. At the 60 Hz of ``DEFAULT_UPDATE_RATE`` a version is published every
#: ~16 ms, so four frames is ~64 ms of history and an ordinary proxied fetch
#: outlives it: a station logged "buffer miss ... at version 168; retained:
#: [169, 170, 171, 172]", missing by one, and the chart went blank because even
#: the first mount could not land a frame. 64 frames covers about a second of
#: publishing at 60 Hz.
#:
#: What has to be covered is how far a client may fall behind, and at the 60 Hz
#: of ``state.DEFAULT_UPDATE_RATE`` 64 frames is barely one second: a station
#: logged a chart asking for version 118 while 152-215 were retained, 34
#: versions past the window, and a client that far behind misses *every* fetch
#: and holds its last frame -- a chart whose axes scroll with no line on it.
#: 512 frames is ~8.5 s at 60 Hz, generous for a hiccup. Not derived from
#: DEFAULT_UPDATE_RATE, which lives in state -- state imports plots imports
#: this module, so reading it back would close an import cycle.
#:
#: This is a count cap only. Memory is bounded by :data:`FRAME_BUDGET_BYTES`:
#: xy downsamples to roughly pixel resolution before publishing, so a live
#: frame is tens of KB and 512 of them are a few MB, but a plate map with a
#: photo underlay publishes about 4 MiB per redraw, and 512 of those per panel
#: per browser tab is 2 GiB.
FRAME_HISTORY = 512

#: Encoded bytes retained per panel. After each put the oldest frames go while
#: the panel is over budget, so a live stream (tens of KB a frame) still keeps
#: all :data:`FRAME_HISTORY` frames, and a photo-underlay map (about 4 MiB a
#: frame) keeps about 7. Its redraws follow clicks, not a 60 Hz tick, so a
#: client is never that many versions behind.
FRAME_BUDGET_BYTES = 32 * 1024 * 1024

#: Frames kept whatever their size: a fetch of version N is in flight while
#: N+1 is published, so a panel whose single frame tops the budget must still
#: serve the frame the browser is asking for.
FRAME_MIN_KEEP = 4

#: Panels retained store-wide, least recently *used* (put or get) first out. A
#: closed tab never fires ``on_unmount``, so nothing else would ever forget its
#: panels' frames. An evicted panel loses its whole frame history, so a live one
#: starts 404ing in-flight versions again and a static one (a plate map, which
#: publishes only on a click) stays blank on remount: size this well above the
#: panels live at once (tabs x charts). 256 costs nothing extra in practice:
#: live frames are tens of KB, and only the few photo-underlay maps approach
#: :data:`FRAME_BUDGET_BYTES` each.
FRAME_MAX_PANELS = 256


class BufferStore:
    """Process-wide ``panel_id -> recent (version, buffers)`` map behind the route.

    A few recent versions are retained per panel, newest last: at most
    :data:`FRAME_HISTORY` of them, within :data:`FRAME_BUDGET_BYTES`, and never
    fewer than :data:`FRAME_MIN_KEEP`. An unknown panel or a version older than the
    retained window yields ``None`` (404 at the route), and the component keeps
    its last good frame rather than blanking — a refetch racing a panel
    teardown must not clear a live chart.
    """

    def __init__(
        self,
        history: int = FRAME_HISTORY,
        budget_bytes: int = FRAME_BUDGET_BYTES,
        min_keep: int = FRAME_MIN_KEEP,
        max_panels: int = FRAME_MAX_PANELS,
    ):
        """Create an empty store retaining at most ``history`` frames per panel,
        within ``budget_bytes``, and never fewer than ``min_keep``."""
        self._lock = threading.Lock()
        self._history = max(1, int(history))
        self._budget = int(budget_bytes)
        self._min_keep = max(1, int(min_keep))
        self._max_panels = max(1, int(max_panels))
        self._frames: dict = {}

    def put(self, panel_id: str, version: int, buffers) -> None:
        """Store a frame for ``panel_id``, dropping the oldest beyond the window."""
        encoded = encode_buffers(buffers)
        with self._lock:
            frames = self._frames.pop(panel_id, None) or collections.deque()
            self._frames[panel_id] = frames  # re-insert: dict order is recency
            while len(self._frames) > self._max_panels:
                evicted = next(iter(self._frames))
                del self._frames[evicted]
                LOGGER.debug(f"xy BufferStore evicted idle panel {evicted}")
            frames.append((int(version), encoded))
            while len(frames) > self._history:
                frames.popleft()
            # ponytail: O(frames) per put, at most FRAME_HISTORY; keep a running
            # total per panel if put ever shows up in a profile.
            size = sum(len(payload) for _, payload in frames)
            while len(frames) > self._min_keep and size > self._budget:
                size -= len(frames.popleft()[1])

    def get(self, panel_id: str, version: int):
        """Return the encoded frame, or ``None`` if unknown or evicted."""
        wanted = int(version)
        with self._lock:
            frames = self._frames.pop(panel_id, None)
            if frames is None:
                return None
            self._frames[panel_id] = frames  # a read is a use: bump recency
            if not frames:
                return None
            for stored, payload in frames:
                if stored == wanted:
                    return payload
        return None

    def versions(self, panel_id: str) -> list:
        """Versions currently retained for ``panel_id``, oldest first."""
        with self._lock:
            return [v for v, _ in self._frames.get(panel_id, ())]

    def drop(self, panel_id: str) -> None:
        """Forget a panel, e.g. when its session ends."""
        with self._lock:
            self._frames.pop(panel_id, None)


def make_buffer_router(store: BufferStore) -> APIRouter:
    """Build the router serving column buffers for ``store``.

    Mounted on the Reflex backend through ``rx.App(api_transformer=...)``;
    Reflex 0.9.7 exposes no public ``app.api`` before build.

    Args:
        store: The :class:`BufferStore` to serve from.

    Returns:
        APIRouter: Router exposing ``GET /xy/buffers/{panel_id}?v=<version>``.
    """
    router = APIRouter()

    @router.get(f"{BUFFER_ROUTE_PREFIX}/{{panel_id}}")
    async def get_buffers(panel_id: str, v: int = Query(...)):
        """Serve one encoded frame as an opaque byte stream."""
        payload = store.get(panel_id, v)
        if payload is None:
            # Logged, not just 404'd. A miss means a chart silently keeps a
            # stale frame -- the component cannot blank on a failed refetch
            # without clearing live charts during teardown -- so without a line
            # here a chart that stops updating leaves no trace anywhere.
            retained = store.versions(panel_id)
            LOGGER.warning(
                f"buffer miss for panel '{panel_id}' at version {v}; "
                f"retained: {retained or 'none'}. The chart will hold its "
                f"previous frame."
            )
            raise HTTPException(
                status_code=404,
                detail=f"no buffers for panel '{panel_id}' at version {v}",
            )
        return Response(content=payload, media_type="application/octet-stream")

    return router


#: The React shim. The bundle's ``render({model, el})`` expects an
#: anywidget-style model, so this supplies a stub with exactly the six members
#: it touches — no anywidget dependency, just the same shape.
#: The controller: every piece of shim logic that can be wrong, with no JSX and
#: no React, so it can be evaluated directly by a JS runtime in the test suite.
#: The bundle's ``render({model, el})`` only ever touches the six members
#: assembled here, so this is a plain stub — not an anywidget dependency.
_SHIM_CONTROLLER_JS = """
// ---- pulse overlay: pure geometry, shared by the controller and the tests ----
// A pulse is a short segment that follows an edge's curve and rides a lane a few
// px to the LEFT of its travel direction (screen coordinates, y down). Outbound
// and return pulses travel opposite ways along the same curve, so their lefts
// are opposite sides and the two directions never overdraw each other.
export const PULSE_LANE_PX = 3.5;
export const PULSE_SEG_PX = 22;
export const PULSE_WIDTH_PX = 4;

// Data units -> host pixels. The graph has a fixed domain and a fixed inset
// (tick labels off, so the plot rect is the padding), so a resize only changes w/h.
export function pulsePixelPath(path, view, w, h) {
  const pad = view.pad;
  const pw = w - 2 * pad;
  const ph = h - 2 * pad;
  const x0 = view.x[0], x1 = view.x[1], y0 = view.y[0], y1 = view.y[1];
  return path.map((p) => [pad + ((p[0] - x0) / (x1 - x0)) * pw, pad + ((y1 - p[1]) / (y1 - y0)) * ph]);
}

// The node under host-pixel point (x, y): distance to its centre <= its radius
// in px, nearest wins. Items carry data x/y and r in px; null when none. The
// node already hovered (`stickyKey`) is held out to `stickyR`, the radius its
// enlarged circle is drawn at, so moving outward over the circle does not clear it.
export function hitNode(items, view, w, h, x, y, stickyKey, stickyR) {
  let best = null, bestD = Infinity;
  for (const it of items || []) {
    const c = pulsePixelPath([[it.x, it.y]], view, w, h)[0];
    const d = Math.hypot(x - c[0], y - c[1]);
    const r = it.key === stickyKey ? Math.max(it.r, stickyR) : it.r;
    if (d <= r && d < bestD) { best = it; bestD = d; }
  }
  return best;
}

function pulseCumulative(px) {
  const cum = [0];
  for (let i = 1; i < px.length; i++) {
    cum.push(cum[i - 1] + Math.hypot(px[i][0] - px[i - 1][0], px[i][1] - px[i - 1][1]));
  }
  return cum;
}

// Point at arc length a (clamped), and the unit tangent of the segment it is on.
export function pulsePointAt(px, cum, a) {
  const total = cum[cum.length - 1];
  const t = Math.min(Math.max(a, 0), total);
  let i = 1;
  while (i < cum.length - 1 && cum[i] < t) i++;
  const seg = cum[i] - cum[i - 1];
  const f = seg === 0 ? 0 : (t - cum[i - 1]) / seg;
  const dx = px[i][0] - px[i - 1][0], dy = px[i][1] - px[i - 1][1];
  const len = Math.hypot(dx, dy) || 1;
  return {
    x: px[i - 1][0] + f * dx,
    y: px[i - 1][1] + f * dy,
    tx: dx / len,
    ty: dy / len,
  };
}

// The moving segment at progress s in [0, 1]: its head runs from the start of the
// path to one segment length past the end, so it grows out of one node and
// vanishes into the other. Returns offset vertices (lane = px to the left).
export function pulseSegment(px, s, segPx, lanePx) {
  if (px.length < 2) return [];
  const cum = pulseCumulative(px);
  const total = cum[cum.length - 1];
  const head = Math.min(Math.max(s * (total + segPx), 0), total);
  const tail = Math.min(Math.max(s * (total + segPx) - segPx, 0), total);
  if (head <= tail) return [];
  const arcs = [tail];
  for (let i = 1; i < cum.length - 1; i++) if (cum[i] > tail && cum[i] < head) arcs.push(cum[i]);
  arcs.push(head);
  return arcs.map((a) => {
    const p = pulsePointAt(px, cum, a);
    // left of travel on a y-down screen: (dy, -dx)
    return [p.x + p.ty * lanePx, p.y - p.tx * lanePx];
  });
}

export function createController(options) {
  const st = {
    spec: options.spec,
    buffers: null,
    // The spec that describes `buffers`. See model.get.
    pairedSpec: null,
    // Version of the newest frame applied, so a late response cannot regress.
    appliedSeq: null,
    layout: null,
    // Bumped on every layout change. A response issued under an older layout
    // describes the torn-down view and must never mount the new one.
    layoutGen: 0,
    handlers: {},
    module: null,
    el: null,
    mounted: false,
    disposed: false,
    pendingUrl: null,
    cleanup: null,
    onSelect: options.onSelect,
    onHover: options.onHover,
    hovered: false,
    observer: null,
    lastUrl: null,
    // One fetch outstanding per chart; the newest URL to arrive meanwhile waits
    // here and everything between it and the one in flight is dropped.
    inFlight: false,
    queuedUrl: null,
    // Pulse overlay. Opt-in: a chart that never gets a `pulses` prop never calls
    // setPulses with a batch, and then nothing below runs or is created.
    pulsesOn: false,
    pulses: [],
    pulseSeen: new Map(),
    pulseView: null,
    pulseCanvas: null,
    // Node hover overlay. Opt-in like the pulses: no `nodes` prop, no listener.
    nodesOn: false,
    nodes: null,
    nodeListening: false,
    pointer: null,
    hoverNode: null,
    raf: null,
    visHandler: null,
  };

  st.model = {
    // The PAIRED spec, not the newest one. st.spec advances on every tick
    // while a fetch is in flight, so handing the renderer the newest spec
    // alongside buffers that arrived for an earlier version describes more
    // points than the buffers hold. xy then either throws "column extends
    // past chart payload" from _columnView at mount -- which has no
    // validator -- or, on the append path, fails c(spec, buffers) and drops
    // the frame without a word. Either way the chart never draws.
    get: (name) => (name === "spec" ? st.pairedSpec || st.spec : st.buffers),
    send: (msg) => {
      if (msg && msg.type === "select" && st.onSelect) st.onSelect(msg);
    },
    on: (event, cb) => {
      (st.handlers[event] = st.handlers[event] || []).push(cb);
    },
    off: (event, cb) => {
      st.handlers[event] = (st.handlers[event] || []).filter((h) => h !== cb);
    },
  };

  st.emit = (event) => (st.handlers[event] || []).forEach((cb) => cb());

  // render() decodes model.get("buffers") synchronously and throws
  // TypeError("chart payload must be an ArrayBuffer or ArrayBuffer view") on
  // null, so the first frame has to be in hand BEFORE the view is built --
  // not fetched after it. Mounting is therefore deferred until the bundle,
  // the host element, and a payload are all present.
  st.maybeMount = () => {
    if (st.mounted || st.disposed) return;
    if (!st.module || !st.el || !st.buffers) return;
    st.cleanup = st.module.render({ model: st.model, el: st.el });
    st.mounted = true;
  };

  st.teardown = () => {
    if (st.cleanup) st.cleanup();
    st.cleanup = null;
    st.mounted = false;
    st.handlers = {};
  };

  // A click reaches the page only as xy's bubbling `xy:click` DOM event, whose
  // detail carries the data-space x/y. The comm `select` message above is a
  // shift-drag box (x0..y1, no x/y), so a click used to go nowhere and the
  // page's details panel never filled.
  st.onClick = (event) => {
    const d = (event && event.detail) || {};
    if (!st.onSelect || !Number.isFinite(d.x) || !Number.isFinite(d.y)) return;
    st.onSelect({ type: "click", x: d.x, y: d.y, trace: d.trace, index: d.index });
  };

  // Hover reaches the page the same way: `xy:hover` (only when the point under
  // the pointer changes) carries `points[0] = {trace: <name>, index}`. xy has no
  // event for moving from a point onto empty plot, so that is read off the
  // tooltip element: xy hides it (display:none) in exactly that case, and the
  // chart styles it invisible, so it is a free "left every point" signal.
  // `xy:leave` is the pointer leaving the chart.
  st.onHoverEvent = (event) => {
    const p = (((event && event.detail) || {}).points || [])[0];
    if (!st.onHover || !p) return;
    st.hovered = true;
    st.onHover({ trace: String(p.trace), index: p.index });
  };
  st.onLeave = () => {
    if (!st.hovered) return;
    st.hovered = false;
    if (st.onHover) st.onHover({ trace: "", index: -1 });
  };
  st.onTooltipMutation = (records) => {
    for (const r of records) {
      const t = r.target;
      if (t && t.dataset && t.dataset.xySlot === "tooltip" && t.style.display === "none") {
        st.onLeave();
      }
    }
  };

  // ---- pulse overlay ----
  // Times are performance.now() milliseconds throughout, the same clock
  // requestAnimationFrame hands its callback. A descriptor carries `start_in`
  // (seconds from when the server built it), converted to a local start at
  // RECEIPT, so a page/server clock difference cannot skip or delay a pulse.
  st.setPulses = (batch, nowMs) => {
    // A hidden tab never runs rAF, so nothing else prunes while batches arrive.
    st.pulses = st.pulses.filter((p) => p.end > nowMs);
    st.pulsesOn = batch !== undefined && batch !== null;
    if (!st.pulsesOn) {
      st.pulses = [];
      return;
    }
    if (batch.view) st.pulseView = batch.view;
    if (!st.visHandler && typeof document !== "undefined" && document.addEventListener) {
      st.visHandler = st.onVisible;
      document.addEventListener("visibilitychange", st.visHandler);
    }
    for (const it of batch.items || []) {
      if (st.pulseSeen.has(it.id)) continue;  // each descriptor is applied once
      const start = nowMs + it.start_in * 1000;
      const end = start + it.dur * 1000;
      st.pulseSeen.set(it.id, end);
      if (end <= nowMs) continue;  // already over on arrival: never replayed
      st.pulses.push({ id: it.id, dir: it.dir, hue: it.color, path: it.path, start, end });
    }
    for (const [id, end] of st.pulseSeen) if (end < nowMs - 10000) st.pulseSeen.delete(id);
    st.kickPulses();
  };

  // Drops what has ended (a tab that was hidden comes back to nothing to replay)
  // and returns what is moving now, with its progress.
  st.activePulses = (nowMs) => {
    st.pulses = st.pulses.filter((p) => p.end > nowMs);
    return st.pulses
      .filter((p) => p.start <= nowMs)
      .map((p) => ({ ...p, s: (nowMs - p.start) / (p.end - p.start) }));
  };

  // ---- node hover overlay ----
  // Descriptors arrive once per real change. The pointer is hit-tested here, in
  // the browser, and the circle is drawn on the pulses' canvas: no server event.
  st.setNodes = (batch) => {
    st.nodesOn = batch !== undefined && batch !== null;
    st.nodes = st.nodesOn ? batch : null;
    if (st.nodesOn && batch.view) st.pulseView = batch.view;
    if (st.nodesOn) st.listenNodes();
    else st.unlistenNodes();
    st.rehover();
  };

  st.listenNodes = () => {
    if (st.nodeListening || !st.el || !st.nodesOn) return;
    st.nodeListening = true;
    st.el.addEventListener("pointermove", st.onPointerMove);
    st.el.addEventListener("pointerleave", st.onPointerLeave);
  };

  st.unlistenNodes = () => {
    if (!st.nodeListening) return;
    st.nodeListening = false;
    st.el.removeEventListener("pointermove", st.onPointerMove);
    st.el.removeEventListener("pointerleave", st.onPointerLeave);
    st.pointer = null;
  };

  // Hit-test the stored pointer; one redraw frame only when the node changes
  // (or its fill did while the pointer stayed).
  st.rehover = () => {
    const el = st.el;
    let hit = null;
    if (st.nodesOn && st.pointer && el && st.pulseView) {
      hit = hitNode(st.nodes.items, st.pulseView, el.clientWidth, el.clientHeight, st.pointer[0], st.pointer[1],
        st.hoverNode && st.hoverNode.key, st.nodes.hover_r);
    }
    const id = (n) => n && n.key + n.color;  // a new fill redraws too
    if (id(hit) === id(st.hoverNode)) return;
    st.hoverNode = hit;
    st.requestDraw();
  };

  st.onPointerMove = (e) => {
    if (!st.el) return;
    const r = st.el.getBoundingClientRect();
    st.pointer = [e.clientX - r.left, e.clientY - r.top];
    st.rehover();
  };

  st.onPointerLeave = () => {
    st.pointer = null;
    st.rehover();
  };

  // One frame now, whether or not a pulse is moving.
  st.requestDraw = () => {
    if (st.raf !== null || st.disposed || !st.el || typeof requestAnimationFrame !== "function") return;
    st.raf = requestAnimationFrame(st.pulseFrame);
  };

  st.drawPulses = (nowMs) => {
    const el = st.el;
    const active = st.activePulses(nowMs);
    if (!el || !st.pulseView || typeof document === "undefined") return;
    if (!st.pulseCanvas) {
      if (!active.length && !st.hoverNode) return;
      const c = document.createElement("canvas");
      c.dataset.helaoSlot = "pulses";
      c.style.cssText = "position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none";
      st.pulseCanvas = c;
    }
    const c = st.pulseCanvas;
    // Sit directly under xy's label layer, so a node's name stays on top of the
    // enlarged hover circle (measured: appended after xy's root, the circle
    // covered the label). xy may rebuild its DOM on a layout change, so this is
    // re-checked on every draw; with no label layer yet it is appended to the host.
    const labels = typeof el.querySelector === "function" ? el.querySelector('[data-xy-slot="labels"]') : null;
    if (labels && labels.parentElement) {
      if (c.nextSibling !== labels || c.parentElement !== labels.parentElement) labels.parentElement.insertBefore(c, labels);
    } else if (!c.isConnected) {
      el.appendChild(c);
    }
    const w = el.clientWidth, h = el.clientHeight;
    const dpr = (typeof window !== "undefined" && window.devicePixelRatio) || 1;
    if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) {
      c.width = Math.round(w * dpr);
      c.height = Math.round(h * dpr);
    }
    const g = c.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    // hover circle first, so a pulse crossing it stays on top
    const hn = st.hoverNode;
    if (hn && st.nodes) {
      const c0 = pulsePixelPath([[hn.x, hn.y]], st.pulseView, w, h)[0];
      g.fillStyle = hn.color;
      g.beginPath();
      g.arc(c0[0], c0[1], st.nodes.hover_r, 0, 2 * Math.PI);
      g.fill();
    }
    g.lineCap = "round";
    g.lineJoin = "round";
    g.lineWidth = PULSE_WIDTH_PX;
    for (const p of active) {
      const pts = pulseSegment(pulsePixelPath(p.path, st.pulseView, w, h), p.s, PULSE_SEG_PX, PULSE_LANE_PX);
      if (pts.length < 2) continue;
      g.strokeStyle = p.hue;
      g.beginPath();
      g.moveTo(pts[0][0], pts[0][1]);
      for (let i = 1; i < pts.length; i++) g.lineTo(pts[i][0], pts[i][1]);
      g.stroke();
    }
  };

  st.pulseFrame = (t) => {
    st.raf = null;
    if (st.disposed || (!st.pulsesOn && !st.nodesOn)) return;
    st.drawPulses(t);
    st.kickPulses();
  };

  // One rAF loop, alive only while a pulse is pending.
  st.kickPulses = () => {
    if (st.raf !== null || st.disposed || !st.pulsesOn || !st.pulses.length) return;
    if (!st.el || typeof requestAnimationFrame !== "function") return;
    st.raf = requestAnimationFrame(st.pulseFrame);
  };

  st.onVisible = () => {
    if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
    st.activePulses(typeof performance !== "undefined" ? performance.now() : 0);
    if (st.pulseCanvas && !st.pulses.length) st.drawPulses(0);  // clear the last frame
    st.kickPulses();
  };

  st.attach = (mod, el) => {
    st.module = mod;
    st.el = el;
    st.kickPulses();
    st.listenNodes();
    el.addEventListener("xy:click", st.onClick);
    el.addEventListener("xy:hover", st.onHoverEvent);
    el.addEventListener("xy:leave", st.onLeave);
    // Only a chart that asked for hover pays for the observer.
    if (st.onHover && typeof MutationObserver === "function" && typeof el.nodeType === "number") {
      st.observer = new MutationObserver(st.onTooltipMutation);
      st.observer.observe(el, { subtree: true, attributes: true, attributeFilter: ["style"] });
    }
    const url = st.pendingUrl;
    st.pendingUrl = null;
    if (url) st.refetch(url);
    else st.maybeMount();
  };

  // The URL is a parameter, never a closure capture. Capturing it would bind
  // the mount-time value forever: `version` changes every tick, BufferStore
  // keeps only the newest version, so a stale URL 404s, the !ok guard holds the
  // first frame, and the chart silently freezes after one paint.
  st.refetch = async (url) => {
    if (!url || st.disposed) return;
    if (!st.module) {
      // decodeFrame lives in the bundle; hold the URL until it lands.
      st.pendingUrl = url;
      return;
    }
    // One request at a time, and only the newest is worth making. A fetch per
    // tick outruns the browser's ~6 connections per origin once the round trip
    // exceeds the tick -- which it does through the frontend's proxy -- so
    // requests queue, each carrying the version that was current when it was
    // queued, and the version asked for falls further behind without bound. A
    // station showed it plainly: the requested version sat ~35 below the
    // retained window whether the window held 64 frames or 512, so every fetch
    // missed and the charts scrolled with no line. Superseded URLs are simply
    // dropped: catching up matters, the intermediate frames do not.
    if (st.inFlight) {
      st.queuedUrl = url;
      return;
    }
    st.inFlight = true;
    st.lastUrl = url;
    // The spec describing THIS url's frame, captured before the await. The
    // panel republishes a larger spec every tick, so by the time the response
    // lands st.spec may already describe more points than these buffers hold.
    const specForUrl = st.spec;
    // Version of this request, used to reject only genuinely older frames.
    const seqForUrl =
      specForUrl && specForUrl.append ? specForUrl.append.seq : null;
    const genForUrl = st.layoutGen;
    try {
      const resp = await fetch(url);
      if (st.disposed) return;
      if (!resp.ok) return;  // keep the last good frame
      const raw = await resp.arrayBuffer();
      if (st.disposed) return;
      // Reject only frames OLDER than what is already drawn. "Is my request
      // still the newest?" was the wrong question: a new refetch is issued
      // every tick, so once a fetch outlasts one tick -- which it does through
      // the frontend's proxy to the backend -- every response finds itself
      // superseded and the chart starves, advancing a version every few
      // seconds instead of every tick. Out-of-order completions still cannot
      // regress the view, because the test is monotonic on the version rather
      // than on request order.
      if (
        seqForUrl !== null &&
        st.appliedSeq !== null &&
        seqForUrl <= st.appliedSeq
      ) {
        return;
      }
      // Issued before a layout change and landed after it. appliedSeq was
      // reset for the rebuild, so the test above lets it through; mounted, it
      // rebuilds the view from the OLD spec (a composition map's previous
      // unit, colorbar and all), the new frame then lands on the in-place path
      // that swaps columns only, and every later update stays in place on
      // that stale view. The queued newest URL still drains in `finally`.
      if (genForUrl !== st.layoutGen) return;
      // decodeFrame returns {message, buffers, version, byteLength}; the
      // renderer wants the buffer LIST, because a split-layout spec indexes
      // columns into it. Handing it the wrapper object fails the split check.
      const frame = st.module.decodeFrame(raw);
      // Assigned together: these three must never be read apart.
      st.buffers = frame.buffers;
      st.pairedSpec = specForUrl;
      st.appliedSeq = seqForUrl;
      if (!st.mounted) {
        st.maybeMount();
        return;
      }
      // Both events: the bundle's in-place append path listens for each.
      st.emit("change:spec");
      st.emit("change:buffers");
    } catch (e) {
      // Network hiccup: keep the last good frame rather than blanking.
    } finally {
      // Drains whichever URL arrived while this one was outstanding, so the
      // chart converges on the newest frame instead of walking a backlog.
      st.inFlight = false;
      const next = st.queuedUrl;
      st.queuedUrl = null;
      if (next && next !== url && !st.disposed) st.refetch(next);
    }
  };

  // A trace added or removed cannot be applied in place -- the update path
  // only swaps columns for traces the view already has. Rebuild instead.
  st.applyLayout = (layout) => {
    if (st.layout === null) {
      st.layout = layout;
      return;
    }
    if (st.layout === layout) return;
    st.layout = layout;
    st.layoutGen += 1;
    st.teardown();
    // Cleared together with the buffers they describe. appliedSeq too, so the
    // rebuild can accept the next frame whatever its version.
    st.buffers = null;
    st.pairedSpec = null;
    st.appliedSeq = null;
  };

  st.dispose = () => {
    st.disposed = true;
    if (st.raf !== null && typeof cancelAnimationFrame === "function") cancelAnimationFrame(st.raf);
    st.raf = null;
    if (st.visHandler) document.removeEventListener("visibilitychange", st.visHandler);
    st.unlistenNodes();
    if (st.pulseCanvas && st.pulseCanvas.remove) st.pulseCanvas.remove();
    if (st.observer) st.observer.disconnect();
    st.teardown();
  };

  return st;
}
"""

#: The React wrapper. Deliberately thin — it wires props and lifecycle to the
#: controller above and holds no logic of its own.
_SHIM_COMPONENT_JS = """
export function XYChart({ spec, bufferUrl, layout, height, width, onSelect, onHover, pulses, nodes }) {
  const hostRef = useRef(null);
  const ctrlRef = useRef(null);
  if (ctrlRef.current === null) {
    ctrlRef.current = createController({ spec: spec, onSelect: onSelect, onHover: onHover });
  }

  useEffect(() => {
    const st = ctrlRef.current;

    // Built at runtime and marked ignore for both bundlers: the asset is served
    // from the site root at request time and is not a module the build can
    // resolve. A bare literal fails the export with UNRESOLVED_IMPORT.
    const clientUrl = "/" + "xy-client" + ".js";
    import(/* webpackIgnore: true */ /* @vite-ignore */ clientUrl).then((mod) => {
      if (st.disposed || !hostRef.current) return;
      st.attach(mod, hostRef.current);
    });

    return () => st.dispose();
  }, []);

  // Pulse descriptors arrive once each; the controller animates them itself.
  useEffect(() => {
    ctrlRef.current.setPulses(pulses, performance.now());
  }, [pulses]);

  // Node descriptors arrive once per real change; hover is hit-tested in the browser.
  useEffect(() => {
    ctrlRef.current.setNodes(nodes);
  }, [nodes]);

  // Data updates take the bundle's in-place append path, not a remount. The
  // URL is passed as an argument so this always fetches the current version.
  useEffect(() => {
    const st = ctrlRef.current;
    st.spec = spec;
    st.onSelect = onSelect;
    st.onHover = onHover;
    st.applyLayout(layout);
    st.refetch(bufferUrl);
  }, [spec, bufferUrl, layout, onSelect, onHover]);

  // minHeight and flexShrink belong here, on the element xy observes and
  // draws into -- not on a wrapper. `height` alone collapses to nothing when
  // this div is a flex item, because flex-shrink applies to it, and the next
  // chart in a wrapping row is then drawn over it. A wrapper box reserving the
  // height fixed the overlap but cost the y axis: the gutter xy draws its
  // ticks, labels and title in ended up outside the box.
  return (
    <div
      ref={hostRef}
      style={{
        width: width || "100%",
        height: height,
        minHeight: height,
        flexShrink: 0,
        // the overlay canvas is absolutely positioned inside this element
        ...(pulses !== undefined || nodes !== undefined ? { position: "relative" } : {}),
      }}
    />
  );
}
"""

#: What the component emits: the controller first, then the wrapper that uses it.
_SHIM_JS = _SHIM_CONTROLLER_JS + _SHIM_COMPONENT_JS


class XYChart(rx.Component):
    """A live xy chart driven by Reflex state.

    A plain ``Component``, not ``NoSSRComponent``: NoSSR exists to emit
    ``import('<library>')`` for a package that cannot be server-rendered, and
    raises ``Undefined library for NoSSRComponent`` without one. This component
    has no npm package -- the shim below is emitted as custom code and performs
    its own dynamic ``import("/xy-client.js")`` inside a ``useEffect``, which is
    client-only by construction. Server rendering emits an empty ``div``; the
    WebGL canvas is attached on mount.

    Attributes:
        spec: Data-less chart spec from ``Figure.build_payload_split``,
            carrying an ``append.seq`` version token.
        buffer_url: Route the browser fetches column buffers from.
        layout: Trace-set token; a change rebuilds the chart rather than
            updating it in place.
        height: CSS height for the chart host element.
    """

    tag = "XYChart"
    library = None  # no npm package; the shim is emitted by _get_custom_code

    spec: rx.Var[dict]
    buffer_url: rx.Var[str]
    layout: rx.Var[str]
    height: rx.Var[str]
    width: rx.Var[str]

    on_select: rx.EventHandler[lambda payload: [payload]]
    on_hover: rx.EventHandler[lambda payload: [payload]]
    pulses: rx.Var[dict]
    nodes: rx.Var[dict]

    def add_imports(self):
        """Declare the React hooks the shim uses.

        The shim must not emit its own ``import ... from "react"``: Reflex's
        generated page already imports these, and a duplicate literal import in
        custom code fails the frontend build with "Identifier `useEffect` has
        already been declared". Declaring them here lets Reflex dedupe.
        """
        return {"react": ["useEffect", "useRef"]}

    def _get_custom_code(self) -> str:
        """Emit the React shim that bridges Reflex to xy's ESM bundle."""
        return _SHIM_JS


def xy_chart(**props) -> XYChart:
    """Create an :class:`XYChart`.

    Args:
        **props: ``spec``, ``buffer_url``, ``height``, ``width``, ``on_select``, ``on_hover``.

    Returns:
        XYChart: The component.
    """
    return XYChart.create(**props)
