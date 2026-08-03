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
  };

  st.model = {
    get: (name) => (name === "spec" ? st.spec : st.buffers),
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

  st.attach = (mod, el) => {
    st.module = mod;
    st.el = el;
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
    st.lastUrl = url;
    try {
      const resp = await fetch(url);
      if (!resp.ok) return;  // keep the last good frame
      const raw = await resp.arrayBuffer();
      // decodeFrame returns {message, buffers, version, byteLength}; the
      // renderer wants the buffer LIST, because a split-layout spec indexes
      // columns into it. Handing it the wrapper object fails the split check.
      const frame = st.module.decodeFrame(raw);
      st.buffers = frame.buffers;
      if (!st.mounted) {
        st.maybeMount();
        return;
      }
      // Both events: the bundle's in-place append path listens for each.
      st.emit("change:spec");
      st.emit("change:buffers");
    } catch (e) {
      // Network hiccup: keep the last good frame rather than blanking.
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
    st.teardown();
    st.buffers = null;
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
