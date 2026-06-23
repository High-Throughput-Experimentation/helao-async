"""WebSocket publisher tests for ``app/base_api.py`` (SP8 WS-B).

The framework relays JSON-serializable payloads over the ``/ws_status`` /
``/ws_data`` / ``/ws_live`` sockets (NOT legacy zstd+pickle — visualizer parity
is deferred, see the route docstrings). These tests use Starlette's synchronous
``TestClient`` (httpx has no websocket client) in a bounded loop so a relay hang
fails fast rather than blocking the suite.

The ``TestClient`` runs the app in its own event loop in a background thread, so
the base's eventsink and status drain are live; emitting through the shared
eventsink in that loop must reach the subscribed websocket.
"""
import pytest
from starlette.testclient import TestClient

from helao.framework.app.base_api import BaseAPI
from helao.framework.ports.eventsink import STATUS_CHANNEL, DATA_CHANNEL


def _make_app(tmp_path):
    return BaseAPI(server_key="SIM", save_root=str(tmp_path))


def test_ws_status_forwards_status_emission(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect("/ws_status") as ws:
            # emit a status from the app's own loop via the portal
            client.portal.call(
                app.base.eventsink.emit, STATUS_CHANNEL, {"hello": "status"}
            )
            msg = ws.receive_json()
    assert msg == {"hello": "status"}


def test_ws_status_ignores_non_status_channel(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect("/ws_status") as ws:
            # a DATA emission must NOT come through the status socket; a STATUS
            # emission after it is what we should receive.
            client.portal.call(
                app.base.eventsink.emit, DATA_CHANNEL, {"skip": "me"}
            )
            client.portal.call(
                app.base.eventsink.emit, STATUS_CHANNEL, {"keep": "me"}
            )
            msg = ws.receive_json()
    assert msg == {"keep": "me"}


def test_ws_data_forwards_data_emission(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect("/ws_data") as ws:
            client.portal.call(
                app.base.eventsink.emit, DATA_CHANNEL, {"v": 1}
            )
            msg = ws.receive_json()
    assert msg == {"v": 1}


def test_ws_live_forwards_data_emission(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect("/ws_live") as ws:
            client.portal.call(
                app.base.eventsink.emit, DATA_CHANNEL, {"live": 9}
            )
            msg = ws.receive_json()
    assert msg == {"live": 9}
