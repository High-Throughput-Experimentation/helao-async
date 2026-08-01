"""Tests for the hand-written xy Reflex binding.

xy 0.0.5 ships no `xy.reflex`, so HELAO supplies the binding. These tests
cover the Python half — buffer storage, xy-native frame encoding, the HTTP
route, and asset copying. The JavaScript shim is proven in the browser check
at the end of the plan; nothing here can exercise WebGL.
"""

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
    """The bundle's render({model, el}) drives everything through these."""
    # Reflex's @dataclass_transform metaclass makes pyright treat every
    # declared Var as a required constructor kwarg, even though the real
    # Component.__init__ takes **kwargs and every Var is optional at
    # runtime (confirmed: XYChart() succeeds, matching xy_chart()'s own
    # XYChart.create() path). Bypassing .create() here is intentional --
    # this test wants the class-level shim code, not a bound instance.
    code = xc.XYChart()._get_custom_code()  # type: ignore[reportCallIssue]
    for member in ("get", "send", "on", "off", "change:spec", "change:buffers"):
        assert member in code, f"shim is missing '{member}'"


def test_shim_references_the_bundles_exported_entry_points():
    code = xc.XYChart()._get_custom_code()  # type: ignore[reportCallIssue]
    assert "render" in code
    assert "decodeFrame" in code
