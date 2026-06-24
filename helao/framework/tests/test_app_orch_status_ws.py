"""Orchestrator /ws_status WebSocket relay."""
from fastapi.testclient import TestClient

from helao.framework.app.factory import makeApp
from helao.framework.ports.eventsink import STATUS_CHANNEL


def _app(tmp_path):
    return makeApp("ORCH", save_root=str(tmp_path), group="orchestrator")


def test_ws_status_forwards_global_status(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect("/ws_status") as ws:
            # emit a global-status payload through the orchestrator's eventsink
            eventsink = app.state.driver.ports.eventsink
            client.portal.call(eventsink.emit_global_status, {"loop_state": "started"})
            msg = ws.receive_json()
            assert msg == {"loop_state": "started"}


def test_ws_status_real_transition_emits(tmp_path):
    """Verify that a real FSM transition (estop) causes a global-status emission.

    We verify the emission by:
    1. Running estop() through portal.call (no WS open, so no relay deadlock).
    2. Checking the eventsink's history to confirm a global_status item was emitted.
    3. Separately confirming the relay forwards it when a subscriber is open.

    The reason for not combining the estop + ws.receive_json() in one block is
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
            msg = ws.receive_json()
            assert "loop_state" in msg


def test_ws_status_ignores_non_global_channel(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect("/ws_status") as ws:
            eventsink = app.state.driver.ports.eventsink
            # emit on the plain status channel (not global) then a global one
            client.portal.call(eventsink.emit_status, {"ignored": True})
            client.portal.call(eventsink.emit_global_status, {"loop_state": "stopped"})
            msg = ws.receive_json()
            assert msg == {"loop_state": "stopped"}  # status-channel msg was filtered out


def test_ws_status_clean_disconnect(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect("/ws_status") as ws:
            pass  # immediate close
    # reaching here without exception = clean teardown
    assert True
