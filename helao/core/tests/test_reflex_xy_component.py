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


def test_store_keeps_the_frame_a_fetch_is_still_asking_for():
    """The browser is told version N+1 in the same delta that replaces the
    buffers, so a fetch of N is in flight exactly while N+1 is published.
    Retaining only the newest 404'd that fetch whenever the round trip
    outlasted a tick, and the chart silently held its last frame."""
    store = xc.BufferStore()
    store.put("panel-a", 1, _bufs())
    store.put("panel-a", 2, _bufs())
    assert store.get("panel-a", 1) is not None
    assert store.get("panel-a", 2) is not None


def test_store_evicts_beyond_the_retained_window():
    store = xc.BufferStore(history=2)
    for version in (1, 2, 3):
        store.put("panel-a", version, _bufs())
    assert store.get("panel-a", 1) is None
    assert store.versions("panel-a") == [2, 3]


def test_store_retains_several_frames_by_default():
    store = xc.BufferStore()
    for version in range(1, xc.FRAME_HISTORY + 1):
        store.put("panel-a", version, _bufs())
    assert store.get("panel-a", 1) is not None


def test_store_history_is_per_panel():
    store = xc.BufferStore(history=1)
    store.put("panel-a", 1, _bufs())
    store.put("panel-b", 1, _bufs())
    assert store.get("panel-a", 1) is not None
    assert store.get("panel-b", 1) is not None


def test_store_reports_no_versions_for_an_unknown_panel():
    assert xc.BufferStore().versions("nope") == []


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
    comp = xc.xy_chart(
        spec={}, buffer_url="/xy/buffers/x?v=0", layout="", height="320px"
    )
    assert comp is not None


def test_xy_chart_touches_the_bundle_only_on_the_client():
    """A WebGL canvas cannot be server-rendered.

    Asserts the property rather than the base class. NoSSRComponent was the
    original vehicle, but it exists to emit `import('<library>')` for an npm
    package and raises "Undefined library" without one -- which broke the
    frontend export the moment panels actually resolved and the component was
    first constructed. What guarantees client-only execution is that the shim
    imports the bundle and calls render() inside a useEffect; server rendering
    emits an empty div.
    """
    code = xc.XYChart()._get_custom_code()  # type: ignore[reportCallIssue]
    before_effect, _, after_effect = code.partition("useEffect")
    assert "import(" not in before_effect, "bundle imported outside useEffect"
    assert "import(" in after_effect and "clientUrl" in after_effect
    assert "xy-client" in after_effect
    assert "st.attach(mod" in after_effect


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

// Stand-in for the xy bundle. `render` records the buffers it was handed at
// mount time, which is what the null-payload crash was about.
const renders = [];
let destroyed = 0;
const fakeModule = {
  decodeFrame: (raw) => ({ message: {}, buffers: ["colX", "colY"], byteLength: 8 }),
  render: ({ model, el }) => {
    renders.push(model.get("buffers"));
    return () => { destroyed += 1; };
  },
};

const events = [];
const st = createController({ spec: {v: 1}, onSelect: null });
st.model.on("change:spec", () => events.push("spec"));
st.model.on("change:buffers", () => events.push("buffers"));

const out = {};
(async () => {
  // Queued before the bundle lands: decodeFrame lives in it, so nothing can
  // be fetched yet.
  await st.refetch("/xy/buffers/p?v=1");
  out.queuedBeforeAttach = calls.length === 0 && st.pendingUrl === "/xy/buffers/p?v=1";
  out.notMountedBeforeAttach = renders.length === 0;

  st.attach(fakeModule, {});
  await new Promise((r) => setTimeout(r, 0));
  out.flushedPendingUrl = calls[0];

  // render() must not have run until a payload existed: it decodes
  // model.get("buffers") synchronously and throws TypeError on null.
  out.renderCount = renders.length;
  out.mountedWithBuffers = renders[0];

  // The bug this guards: a later call must use the URL it is given.
  await st.refetch("/xy/buffers/p?v=2");
  await st.refetch("/xy/buffers/p?v=3");
  out.lastFetched = calls[calls.length - 1];
  out.allUrls = calls.slice();

  // Both change events fire per post-mount refetch (the in-place append path).
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

  // A trace added or removed cannot be applied in place; the view is rebuilt.
  st.applyLayout("0:line:a");
  out.sameLayoutKeepsView = destroyed === 0 && st.mounted === true;
  st.applyLayout("0:line:a|1:line:b");
  out.layoutChangeTearsDown = destroyed === 1 && st.mounted === false;
  await st.refetch("/xy/buffers/p?v=4");
  out.remountedAfterLayoutChange = renders.length === 2;

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
    assert out["queuedBeforeAttach"] is True
    assert out["flushedPendingUrl"] == "/xy/buffers/p?v=1"


@pytest.mark.skipif(_JS_RUNTIME is None, reason="no node runtime available")
def test_controller_does_not_render_before_a_payload_exists():
    """The crash this guards, reported from a live browser:

        TypeError: chart payload must be an ArrayBuffer or ArrayBuffer view

    xy's render() decodes model.get("buffers") synchronously, so mounting it
    with a null payload throws and the panel never appears. Mounting has to
    wait for the first frame rather than fetch after the fact.
    """
    out = _run_controller_harness()
    assert out["notMountedBeforeAttach"] is True
    assert out["renderCount"] == 1


@pytest.mark.skipif(_JS_RUNTIME is None, reason="no node runtime available")
def test_controller_hands_the_renderer_the_buffer_list_not_the_frame_wrapper():
    """decodeFrame returns {message, buffers, version, byteLength}.

    A split-layout spec indexes columns into a buffer LIST, so passing the
    wrapper object fails xy's split check outright.
    """
    out = _run_controller_harness()
    assert out["mountedWithBuffers"] == ["colX", "colY"]


@pytest.mark.skipif(_JS_RUNTIME is None, reason="no node runtime available")
def test_controller_rebuilds_the_view_when_the_trace_set_changes():
    """xy's update path swaps columns for traces the view already has; it
    cannot add or remove one. A live stream gaining a series must therefore
    rebuild, not update."""
    out = _run_controller_harness()
    assert out["sameLayoutKeepsView"] is True
    assert out["layoutChangeTearsDown"] is True
    assert out["remountedAfterLayoutChange"] is True


@pytest.mark.skipif(_JS_RUNTIME is None, reason="no node runtime available")
def test_controller_fires_both_change_events_per_successful_refetch():
    """The bundle's in-place append path listens for each event separately."""
    out = _run_controller_harness()
    # Three fetches follow the mount; the mounting fetch itself paints
    # through render() rather than through the change events.
    assert out["events"].count("spec") == 2
    assert out["events"].count("buffers") == 2


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
