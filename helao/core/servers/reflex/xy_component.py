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
    "CLIENT_ASSET_NAME",
    "BUFFER_ROUTE_PREFIX",
]

import collections
import os
import pathlib
import shutil
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
    source = pathlib.Path(xy.widget.__file__).parent / "static" / "index.js"
    if not source.is_file():
        raise FileNotFoundError(
            f"xy's bundled ESM client is missing at '{source}'. A published "
            "wheel ships it prebuilt; a source checkout must build it once "
            "with `npm ci && node js/build.mjs`."
        )
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, CLIENT_ASSET_NAME)
    shutil.copyfile(source, dest)
    return dest


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
FRAME_HISTORY = 4


class BufferStore:
    """Process-wide ``panel_id -> recent (version, buffers)`` map behind the route.

    A few recent versions are retained per panel, newest last; see
    :data:`FRAME_HISTORY`. An unknown panel or a version older than the
    retained window yields ``None`` (404 at the route), and the component keeps
    its last good frame rather than blanking — a refetch racing a panel
    teardown must not clear a live chart.
    """

    def __init__(self, history: int = FRAME_HISTORY):
        """Create an empty store retaining ``history`` frames per panel."""
        self._lock = threading.Lock()
        self._history = max(1, int(history))
        self._frames: dict = {}

    def put(self, panel_id: str, version: int, buffers) -> None:
        """Store a frame for ``panel_id``, dropping the oldest beyond the window."""
        encoded = encode_buffers(buffers)
        with self._lock:
            frames = self._frames.setdefault(panel_id, collections.deque())
            frames.append((int(version), encoded))
            while len(frames) > self._history:
                frames.popleft()

    def get(self, panel_id: str, version: int):
        """Return the encoded frame, or ``None`` if unknown or evicted."""
        wanted = int(version)
        with self._lock:
            frames = self._frames.get(panel_id)
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
export function createController(options) {
  const st = {
    spec: options.spec,
    buffers: null,
    // The spec that describes `buffers`. See model.get.
    pairedSpec: null,
    layout: null,
    handlers: {},
    module: null,
    el: null,
    mounted: false,
    disposed: false,
    pendingUrl: null,
    cleanup: null,
    onSelect: options.onSelect,
    lastUrl: null,
    tag: "?",
  };

  // TEMPORARY DIAGNOSTIC. Every silent path in this controller and in xy's
  // append handler produces the same blank chart, so each decision point
  // announces itself. Filter the console on "[xy]". Remove once the
  // this-action/previous-action asymmetry is understood.
  st.log = (...args) => {
    try {
      console.log("[xy]", st.tag, ...args);
    } catch (e) {}
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
    if (!st.module || !st.el || !st.buffers) {
      st.log("mount deferred", {
        module: !!st.module,
        el: !!st.el,
        buffers: st.buffers ? st.buffers.length : null,
      });
      return;
    }
    st.log("mounting", {
      traces: (st.spec && st.spec.traces || []).length,
      columns: (st.spec && st.spec.columns || []).length,
      buffers: st.buffers.length,
      seq: st.spec && st.spec.append && st.spec.append.seq,
    });
    try {
      st.cleanup = st.module.render({ model: st.model, el: st.el });
    } catch (e) {
      // Logged, then rethrown: behaviour is unchanged, but a render that
      // throws is otherwise swallowed whole by refetch's catch.
      st.log("RENDER THREW", e && e.message, e);
      throw e;
    }
    st.mounted = true;
    // The browser's own "WebGL context was lost" names no chart, and a lost
    // context is indistinguishable from a working one in every other log
    // line: xy keeps delivering appends to a live listener and _applyAppend
    // returns before drawing. Tag the event with the panel id, and count the
    // live canvases, since exceeding the browser's context cap is what
    // provokes the eviction in the first place.
    // Wrapped: this is diagnostics, and the controller is also executed by the
    // test suite in a runtime with a stub element and no document. A throw
    // here would surface as a bogus REFETCH THREW, or an unhandled rejection
    // on the attach path.
    try {
      const canvas = st.el.querySelector("canvas");
      if (canvas && !canvas.__xyLossHooked) {
        canvas.__xyLossHooked = true;
        canvas.addEventListener("webglcontextlost", () =>
          st.log("WEBGL CONTEXT LOST", {
            canvases: document.querySelectorAll("canvas").length,
          })
        );
        canvas.addEventListener("webglcontextrestored", () =>
          st.log("WEBGL CONTEXT RESTORED")
        );
      }
      st.log("mounted", {
        canvas: !!canvas,
        canvases: document.querySelectorAll("canvas").length,
      });
    } catch (e) {}
  };

  st.teardown = () => {
    if (st.cleanup) st.cleanup();
    st.cleanup = null;
    st.mounted = false;
    st.handlers = {};
  };

  st.attach = (mod, el) => {
    st.module = mod;
    st.el = el;
    const url = st.pendingUrl;
    st.pendingUrl = null;
    st.log("bundle attached", { pendingUrl: url });
    if (url) st.refetch(url);
    else st.maybeMount();
  };

  // The URL is a parameter, never a closure capture. Capturing it would bind
  // the mount-time value forever: `version` changes every tick, BufferStore
  // keeps only the newest version, so a stale URL 404s, the !ok guard holds the
  // first frame, and the chart silently freezes after one paint.
  st.refetch = async (url) => {
    if (!url || st.disposed) return;
    // The panel id is the last path segment; it is the only thing that tells
    // one chart of a pair from the other in the console.
    if (url) st.tag = String(url).split("/").pop().split("?")[0];
    if (!st.module) {
      // decodeFrame lives in the bundle; hold the URL until it lands.
      st.pendingUrl = url;
      st.log("refetch queued (no bundle yet)", url);
      return;
    }
    st.lastUrl = url;
    // The spec describing THIS url's frame, captured before the await. The
    // panel republishes a larger spec every tick, so by the time the response
    // lands st.spec may already describe more points than these buffers hold.
    const specForUrl = st.spec;
    try {
      const resp = await fetch(url);
      // Superseded while in flight: a newer refetch has been issued, and its
      // response is the one that should win. Applying this one would pair old
      // buffers with a newer spec -- and out-of-order completions mean "last
      // to resolve" is not "newest".
      if (st.disposed || st.lastUrl !== url) return;
      if (!resp.ok) {
        st.log("FETCH NOT OK", resp.status, url);
        return;  // keep the last good frame
      }
      const raw = await resp.arrayBuffer();
      if (st.disposed || st.lastUrl !== url) return;
      // decodeFrame returns {message, buffers, version, byteLength}; the
      // renderer wants the buffer LIST, because a split-layout spec indexes
      // columns into it. Handing it the wrapper object fails the split check.
      const frame = st.module.decodeFrame(raw);
      // Assigned together: these two must never be read apart.
      st.buffers = frame.buffers;
      st.pairedSpec = specForUrl;
      const spec = specForUrl || {};
      const cols = spec.columns || [];
      st.log("frame", {
        bytes: raw.byteLength,
        buffers: frame.buffers ? frame.buffers.length : null,
        bufferBytes: (frame.buffers || []).map((b) => b && b.byteLength),
        traces: (spec.traces || []).length,
        columns: cols.length,
        colLens: cols.map((c) => c && c.len),
        layout: spec.buffer_layout,
        seq: spec.append && spec.append.seq,
        affected: spec.append && spec.append.affected,
        mounted: st.mounted,
      });
      if (!st.mounted) {
        st.maybeMount();
        return;
      }
      // Both events: the bundle's in-place append path listens for each.
      st.emit("change:spec");
      st.emit("change:buffers");
      st.log("append emitted", {
        listeners: (st.handlers["change:spec"] || []).length,
      });
    } catch (e) {
      // Network hiccup: keep the last good frame rather than blanking.
      st.log("REFETCH THREW", e && e.message, e);
    }
  };

  // A trace added or removed cannot be applied in place -- the update path
  // only swaps columns for traces the view already has. Rebuild instead.
  st.applyLayout = (layout) => {
    if (st.layout === null) {
      st.layout = layout;
      st.log("layout first seen", JSON.stringify(layout));
      return;
    }
    if (st.layout === layout) return;
    st.log("LAYOUT CHANGED, rebuilding", {
      from: JSON.stringify(st.layout),
      to: JSON.stringify(layout),
      wasMounted: st.mounted,
    });
    st.layout = layout;
    st.teardown();
    // Cleared together with the buffers they describe.
    st.buffers = null;
    st.pairedSpec = null;
  };

  st.dispose = () => {
    st.disposed = true;
    st.teardown();
  };

  return st;
}
"""

#: The React wrapper. Deliberately thin — it wires props and lifecycle to the
#: controller above and holds no logic of its own.
_SHIM_COMPONENT_JS = """
export function XYChart({ spec, bufferUrl, layout, height, onSelect }) {
  const hostRef = useRef(null);
  const ctrlRef = useRef(null);
  if (ctrlRef.current === null) {
    ctrlRef.current = createController({ spec: spec, onSelect: onSelect });
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

  // Data updates take the bundle's in-place append path, not a remount. The
  // URL is passed as an argument so this always fetches the current version.
  useEffect(() => {
    const st = ctrlRef.current;
    st.spec = spec;
    st.onSelect = onSelect;
    st.applyLayout(layout);
    st.refetch(bufferUrl);
  }, [spec, bufferUrl, layout, onSelect]);

  return <div ref={hostRef} style={{ width: "100%", height: height }} />;
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

    on_select: rx.EventHandler[lambda payload: [payload]]

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
        **props: ``spec``, ``buffer_url``, ``height``, ``on_select``.

    Returns:
        XYChart: The component.
    """
    return XYChart.create(**props)
