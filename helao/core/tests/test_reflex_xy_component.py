"""Tests for the hand-written xy Reflex binding.

xy 0.0.5 ships no `xy.reflex`, so HELAO supplies the binding. These tests cover
the Python half — buffer storage, xy-native frame encoding, the HTTP route, and
asset copying — plus the JavaScript controller, executed under Node.

Nothing here can exercise WebGL; rendering is proven by the browser check at
the end of the plan. But the controller holds the shim logic that can actually
be wrong, so it is run rather than string-matched.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from helao.core.servers.reflex import xy_component as xc


def _bufs():
    return [
        memoryview(np.arange(4, dtype=np.float64).tobytes()),
        memoryview(np.arange(4, dtype=np.float32).tobytes()),
    ]


def test_encode_buffers_roundtrips_through_xy_channel():
    import xy.channel

    payload = xc.encode_buffers(_bufs())
    assert isinstance(payload, (bytes, bytearray))
    assert len(payload) > 0
    # Frames carry xy's own magic, so the browser decodes them with the
    # bundle's exported decodeFrame rather than anything HELAO invented.
    assert payload[: len(xy.channel.FRAME_MAGIC)] == bytes(xy.channel.FRAME_MAGIC)


def test_encode_buffers_handles_an_empty_list():
    assert isinstance(xc.encode_buffers([]), (bytes, bytearray))


def test_store_returns_what_was_put():
    store = xc.BufferStore()
    bufs = _bufs()
    store.put("panel-a", 3, bufs)
    assert store.get("panel-a", 3) is not None


def test_store_returns_none_for_a_stale_version():
    store = xc.BufferStore()
    store.put("panel-a", 3, _bufs())
    assert store.get("panel-a", 2) is None


def test_store_returns_none_for_an_unknown_panel():
    assert xc.BufferStore().get("nope", 1) is None


def test_store_put_replaces_the_previous_version():
    store = xc.BufferStore()
    store.put("panel-a", 1, _bufs())
    store.put("panel-a", 2, _bufs())
    assert store.get("panel-a", 1) is None
    assert store.get("panel-a", 2) is not None


def test_store_drop_removes_the_panel():
    store = xc.BufferStore()
    store.put("panel-a", 1, _bufs())
    store.drop("panel-a")
    assert store.get("panel-a", 1) is None


def _client(store):
    api = FastAPI()
    api.include_router(xc.make_buffer_router(store))
    return TestClient(api)


def test_route_serves_octet_stream_for_a_live_panel():
    store = xc.BufferStore()
    store.put("panel-a", 7, _bufs())
    resp = _client(store).get("/xy/buffers/panel-a?v=7")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/octet-stream"
    assert len(resp.content) > 0


def test_route_404s_on_an_unknown_panel():
    assert _client(xc.BufferStore()).get("/xy/buffers/ghost?v=1").status_code == 404


def test_route_404s_on_a_stale_version():
    store = xc.BufferStore()
    store.put("panel-a", 7, _bufs())
    assert _client(store).get("/xy/buffers/panel-a?v=6").status_code == 404


def test_route_requires_the_version_query_param():
    store = xc.BufferStore()
    store.put("panel-a", 7, _bufs())
    assert _client(store).get("/xy/buffers/panel-a").status_code == 422


def test_copy_client_asset_places_the_esm(tmp_path):
    dest = xc.copy_client_asset(str(tmp_path))
    assert dest.endswith(xc.CLIENT_ASSET_NAME)
    written = tmp_path / xc.CLIENT_ASSET_NAME
    assert written.exists()
    # The real bundle is ~400 KB; a truncated copy is a silent disaster.
    assert written.stat().st_size > 100_000


def test_copy_client_asset_is_idempotent(tmp_path):
    first = xc.copy_client_asset(str(tmp_path))
    second = xc.copy_client_asset(str(tmp_path))
    assert first == second


def test_xy_chart_builds_a_component():
    comp = xc.xy_chart(spec={}, buffer_url="/xy/buffers/x?v=0", height="320px")
    assert comp is not None


def test_xy_chart_is_client_only():
    """A WebGL canvas cannot server-side render."""
    import reflex as rx

    assert issubclass(xc.XYChart, rx.NoSSRComponent)


def test_shim_declares_the_six_model_members_the_bundle_requires():
    """The bundle's render({model, el}) drives everything through these.

    A substring check only proves the tokens are present, so it is a smoke test,
    not a guarantee -- the behavioral tests below are what actually constrain the
    controller.
    """
    code = xc.XYChart()._get_custom_code()  # type: ignore[reportCallIssue]
    for member in ("get", "send", "on", "off", "change:spec", "change:buffers"):
        assert member in code, f"shim is missing '{member}'"


def test_shim_references_the_bundles_exported_entry_points():
    code = xc.XYChart()._get_custom_code()  # type: ignore[reportCallIssue]
    assert "render" in code
    assert "decodeFrame" in code


# --- Behavioral tests for the shim controller -------------------------------
#
# The controller holds every piece of shim logic that can be wrong, with no JSX
# and no React, precisely so a JS runtime can execute it here. Substring
# assertions previously let a stale-closure bug ship: `refetch` captured the
# mount-time URL, so a chart painted once and then silently froze. These run the
# real code instead.

_JS_RUNTIME = shutil.which("node")

_HARNESS = """
%(controller)s

const calls = [];
globalThis.fetch = async (url) => {
  calls.push(url);
  if (url === "/fail") return { ok: false };
  return { ok: true, arrayBuffer: async () => new ArrayBuffer(8) };
};

const events = [];
const st = createController({ spec: {v: 1}, onSelect: null });
st.model.on("change:spec", () => events.push("spec"));
st.model.on("change:buffers", () => events.push("buffers"));

const out = {};
(async () => {
  // Queued before the bundle is ready, then flushed on markReady.
  await st.refetch("/xy/buffers/p?v=1");
  out.queuedWhileNotReady = calls.length === 0 && st.pending === true;
  st.markReady();
  await new Promise((r) => setTimeout(r, 0));
  out.flushedPendingUrl = calls[0];

  // The bug this guards: a later call must use the URL it is given.
  await st.refetch("/xy/buffers/p?v=2");
  await st.refetch("/xy/buffers/p?v=3");
  out.lastFetched = calls[calls.length - 1];
  out.allUrls = calls.slice();

  // Both change events fire per successful refetch (the in-place append path).
  out.events = events.slice();

  // A failed fetch keeps the previous frame rather than blanking it.
  const before = st.buffers;
  await st.refetch("/fail");
  out.keptFrameOnFailure = st.buffers === before;

  // Selection travels back to Reflex through model.send.
  let received = null;
  st.onSelect = (msg) => { received = msg; };
  st.model.send({ type: "select", rows: [1, 2] });
  out.selectPayload = received;
  received = null;
  st.model.send({ type: "hover" });
  out.nonSelectIgnored = received === null;

  console.log(JSON.stringify(out));
})();
"""


def _run_controller_harness():
    """Execute the shim controller under Node and return its result dict."""
    # Only called from tests gated by skipif(_JS_RUNTIME is None), but that
    # guard is invisible to pyright across the function boundary.
    assert _JS_RUNTIME is not None
    controller = xc._SHIM_CONTROLLER_JS
    script = _HARNESS % {"controller": controller}
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "harness.mjs")
        with open(path, "w") as fh:
            fh.write(script)
        proc = subprocess.run(
            [_JS_RUNTIME, path], capture_output=True, text=True, timeout=60
        )
    assert proc.returncode == 0, f"harness failed:\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(_JS_RUNTIME is None, reason="no node runtime available")
def test_controller_refetch_uses_the_url_it_is_given_not_a_captured_one():
    """The regression guard: a captured URL freezes the chart after one paint.

    `version` changes every render tick and BufferStore keeps only the newest
    version, so a stale URL 404s, the !ok guard holds the previous frame, and
    updates stop silently.
    """
    out = _run_controller_harness()
    assert out["lastFetched"] == "/xy/buffers/p?v=3"
    assert "/xy/buffers/p?v=2" in out["allUrls"]


@pytest.mark.skipif(_JS_RUNTIME is None, reason="no node runtime available")
def test_controller_queues_a_refetch_until_the_bundle_is_ready():
    out = _run_controller_harness()
    assert out["queuedWhileNotReady"] is True
    assert out["flushedPendingUrl"] == "/xy/buffers/p?v=1"


@pytest.mark.skipif(_JS_RUNTIME is None, reason="no node runtime available")
def test_controller_fires_both_change_events_per_successful_refetch():
    """The bundle's in-place append path listens for each event separately."""
    out = _run_controller_harness()
    assert out["events"].count("spec") == 3
    assert out["events"].count("buffers") == 3


@pytest.mark.skipif(_JS_RUNTIME is None, reason="no node runtime available")
def test_controller_keeps_the_last_good_frame_when_a_fetch_fails():
    out = _run_controller_harness()
    assert out["keptFrameOnFailure"] is True


@pytest.mark.skipif(_JS_RUNTIME is None, reason="no node runtime available")
def test_controller_dispatches_a_select_message_to_on_select():
    """model.send is how the bundle reports selection back to Reflex."""
    out = _run_controller_harness()
    assert out["selectPayload"] == {"type": "select", "rows": [1, 2]}
    assert out["nonSelectIgnored"] is True


def test_component_passes_the_current_url_into_refetch():
    """Guards the wiring the controller tests cannot reach.

    The four Node tests exercise ``createController`` only. The bug that shipped
    lived in the React wrapper, which called ``st.refetch()`` with no argument —
    and the controller's own ``if (!url) return;`` would swallow that silently
    while every controller test still passed. No JSX runtime is available here,
    so this asserts the wiring textually rather than by execution.
    """
    component = xc._SHIM_COMPONENT_JS
    assert "st.refetch(bufferUrl)" in component, "wrapper must pass the live URL"
    assert re.search(r"st\.refetch\(\s*\)", component) is None, (
        "wrapper calls refetch with no argument; the controller would no-op "
        "silently and the chart would freeze after one paint"
    )
