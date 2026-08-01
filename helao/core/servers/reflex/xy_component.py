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

import os
import pathlib
import shutil
import threading

import reflex as rx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

import xy.channel
import xy.widget

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


class BufferStore:
    """Process-wide ``panel_id -> (version, buffers)`` map behind the HTTP route.

    Only the newest version of a panel is retained: the browser refetches when
    its version token changes, so an older frame can never be usefully served.
    A stale or unknown request yields ``None`` (404 at the route), and the
    component keeps its last good frame rather than blanking — a refetch racing
    a panel teardown must not clear a live chart.
    """

    def __init__(self):
        """Create an empty store."""
        self._lock = threading.Lock()
        self._frames: dict = {}

    def put(self, panel_id: str, version: int, buffers) -> None:
        """Store the newest frame for ``panel_id``, replacing any previous one."""
        with self._lock:
            self._frames[panel_id] = (int(version), encode_buffers(buffers))

    def get(self, panel_id: str, version: int):
        """Return the encoded frame, or ``None`` if unknown or stale."""
        with self._lock:
            entry = self._frames.get(panel_id)
        if entry is None or entry[0] != int(version):
            return None
        return entry[1]

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
            raise HTTPException(
                status_code=404,
                detail=f"no buffers for panel '{panel_id}' at version {v}",
            )
        return Response(content=payload, media_type="application/octet-stream")

    return router


#: The React shim. The bundle's ``render({model, el})`` expects an
#: anywidget-style model, so this supplies a stub with exactly the six members
#: it touches — no anywidget dependency, just the same shape.
_SHIM_JS = """
import { useEffect, useRef } from "react";

export function XYChart({ spec, bufferUrl, height, onSelect }) {
  const hostRef = useRef(null);
  const stateRef = useRef({ spec: spec, buffers: null, handlers: {}, cleanup: null });

  useEffect(() => {
    let disposed = false;
    const st = stateRef.current;

    // Minimal anywidget-shaped model: the bundle only ever touches these.
    const model = {
      get: (name) => (name === "spec" ? st.spec : st.buffers),
      send: (msg) => {
        if (msg && msg.type === "select" && onSelect) onSelect(msg);
      },
      on: (event, cb) => {
        (st.handlers[event] = st.handlers[event] || []).push(cb);
      },
      off: (event, cb) => {
        st.handlers[event] = (st.handlers[event] || []).filter((h) => h !== cb);
      },
    };
    st.emit = (event) => (st.handlers[event] || []).forEach((cb) => cb());

    import(/* webpackIgnore: true */ "/xy-client.js").then((mod) => {
      if (disposed || !hostRef.current) return;
      st.decodeFrame = mod.decodeFrame;
      st.cleanup = mod.render({ model, el: hostRef.current });
      st.ready = true;
      if (st.pending) { st.pending = false; st.refetch(); }
    });

    st.refetch = async () => {
      if (!st.ready) { st.pending = true; return; }
      if (!bufferUrl) return;
      try {
        const resp = await fetch(bufferUrl);
        if (!resp.ok) return;  // keep the last good frame
        const raw = await resp.arrayBuffer();
        st.buffers = st.decodeFrame ? st.decodeFrame(raw) : raw;
        st.emit("change:spec");
        st.emit("change:buffers");
      } catch (e) {
        // Network hiccup: keep the last good frame rather than blanking.
      }
    };

    return () => {
      disposed = true;
      if (st.cleanup) st.cleanup();
      st.ready = false;
    };
  }, []);

  // Data updates take the bundle's in-place append path, not a re-render.
  useEffect(() => {
    const st = stateRef.current;
    st.spec = spec;
    if (st.refetch) st.refetch();
  }, [spec, bufferUrl]);

  return <div ref={hostRef} style={{ width: "100%", height: height }} />;
}
"""


class XYChart(rx.NoSSRComponent):
    """A live xy chart driven by Reflex state.

    Client-only: the bundle renders to a WebGL2 canvas, which cannot be
    server-side rendered.

    Attributes:
        spec: Data-less chart spec from ``Figure.build_payload_split``,
            carrying an ``append.seq`` version token.
        buffer_url: Route the browser fetches column buffers from.
        height: CSS height for the chart host element.
    """

    tag = "XYChart"
    library = None  # emitted inline by _get_custom_code, not an npm package

    spec: rx.Var[dict]
    buffer_url: rx.Var[str]
    height: rx.Var[str]

    on_select: rx.EventHandler[lambda payload: [payload]]

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
