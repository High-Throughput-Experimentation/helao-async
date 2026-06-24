"""Orchestrator /ws_status WebSocket relay."""
import pickle

import pyzstd
from fastapi.testclient import TestClient

from helao.framework.app.factory import makeApp
from helao.framework.ports.eventsink import STATUS_CHANNEL


def _recv(ws):
    """Decode a zstd-pickle frame the way WsSubscriber.subscriber_loop does."""
    return pickle.loads(pyzstd.decompress(ws.receive_bytes()))


def _app(tmp_path):
    return makeApp("ORCH", save_root=str(tmp_path), group="orchestrator")


def test_ws_status_forwards_global_status(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect("/ws_status") as ws:
            # emit a global-status payload through the orchestrator's eventsink
            eventsink = app.state.driver.ports.eventsink
            client.portal.call(eventsink.emit_global_status, {"loop_state": "started"})
            msg = _recv(ws)
            assert msg == {"loop_state": "started"}


def test_ws_status_real_transition_emits(tmp_path):
    """Verify that a real FSM transition (estop) causes a global-status emission.

    We verify the emission by:
    1. Running estop() through portal.call (no WS open, so no relay deadlock).
    2. Checking the eventsink's history to confirm a global_status item was emitted.
    3. Separately confirming the relay forwards it when a subscriber is open.

    The reason for not combining the estop + _recv(ws) in one block is
    that Starlette's TestClient sync→async bridge deadlocks when the relay's
    send_json() runs within the portal.call() window (the test thread is blocked
    by portal.call while the relay tries to push to the WS send queue that the
    test thread owns). The deterministic portal.call path from the brief is used
    for the channel-filter test instead.
    """
    app = _app(tmp_path)
    with TestClient(app) as client:
        driver = app.state.driver
        eventsink = driver.ports.eventsink
        # Run estop with no WS subscriber; history captures the emission.
        client.portal.call(driver.estop)
        global_statuses = eventsink.global_statuses
        assert len(global_statuses) >= 1
        assert "loop_state" in global_statuses[-1]
        # Confirm the relay does forward global_status emissions to a subscriber.
        with client.websocket_connect("/ws_status") as ws:
            client.portal.call(eventsink.emit_global_status, {"loop_state": "estopped"})
            msg = _recv(ws)
            assert "loop_state" in msg


def test_ws_status_ignores_non_global_channel(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect("/ws_status") as ws:
            eventsink = app.state.driver.ports.eventsink
            # emit on the plain status channel (not global) then a global one
            client.portal.call(eventsink.emit_status, {"ignored": True})
            client.portal.call(eventsink.emit_global_status, {"loop_state": "stopped"})
            msg = _recv(ws)
            assert msg == {"loop_state": "stopped"}  # status-channel msg was filtered out


def test_ws_status_clean_disconnect(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect("/ws_status") as ws:
            pass  # immediate close
    # reaching here without exception = clean teardown
    assert True


def test_remote_backend_ws_loop_fires_on_change():
    """RemoteBackend._ws_loop calls on_change() when a ws message arrives."""
    import asyncio as _asyncio
    from helao.framework.adapters.operator_backend import RemoteBackend

    calls = []

    class _FakeWss:
        def __init__(self):
            self._sent = False

        async def read_messages(self):
            if not self._sent:
                self._sent = True
                return [{"loop_state": "started"}]
            return []

    be = RemoteBackend.__new__(RemoteBackend)
    be._wss = _FakeWss()

    async def _drive():
        task = _asyncio.create_task(be._ws_loop(lambda: calls.append(1)))
        await _asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except _asyncio.CancelledError:
            pass

    _asyncio.run(_drive())
    assert calls, "on_change was not fired on a ws message"


def test_ws_status_wire_format_matches_consumer(tmp_path):
    """Prove a forwarded frame decodes exactly as WsSubscriber.subscriber_loop would.

    This is the real-consumer-path round-trip: receive raw bytes from the relay
    and decode them with the identical pickle+zstd path used by WsSubscriber.
    """
    app = makeApp("ORCH", save_root=str(tmp_path), group="orchestrator")
    with TestClient(app) as client:
        with client.websocket_connect("/ws_status") as ws:
            eventsink = app.state.driver.ports.eventsink
            client.portal.call(eventsink.emit_global_status, {"loop_state": "started"})
            raw = ws.receive_bytes()
            decoded = pickle.loads(pyzstd.decompress(raw))
            assert decoded == {"loop_state": "started"}
