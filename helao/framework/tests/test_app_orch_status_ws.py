"""Orchestrator /ws_status WebSocket relay.

Wire format is JSON (framework standard, matching BaseAPI._ws_relay). The
operator's WsSubscriber decodes frames with json.loads — the relay's earlier
zstd+pickle bytes made every delivered frame fail to decode and flap the
operator's status subscription during running sequences.
"""
import json

from fastapi.testclient import TestClient

from helao.framework.app.factory import makeApp
from helao.framework.ports.eventsink import STATUS_CHANNEL


def _recv(ws):
    """Decode a JSON frame the way the operator's WsSubscriber (json.loads) does."""
    return json.loads(ws.receive_text())


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


def test_broadcast_payload_json_cleans_for_the_wire():
    """The relay's _json_clean makes a POPULATED broadcast payload send_json-safe.

    The domain payload (as_json) carries raw MachineModel / Dict[UUID,
    ActionModel] / enums for in-process consumers; json.dumps on it raises
    TypeError, which silently killed the relay (except-Exception-return) on
    every frame -- the operator's reconnect flap during running sequences. The
    relay must clean it at the wire boundary.
    """
    from uuid import uuid4

    from helao.framework.app.orch_api import _json_clean
    from helao.framework.domain.orchestration import OrchState, _broadcast
    from helao.framework.models.action import ActionModel
    from helao.framework.models.machine import MachineModel

    state = OrchState()
    gsm = state.globalstatusmodel
    gsm.orchestrator = MachineModel(server_name="ORCH", machine_name="uvis4")
    gsm.active_dict[uuid4()] = ActionModel(
        action_name="archive_custom_unloadall",
        action_server=MachineModel(server_name="PAL", machine_name="uvis4"),
    )
    payload = _broadcast(state).payload
    cleaned = _json_clean(payload)
    out = json.dumps(cleaned)  # must not raise
    assert "archive_custom_unloadall" in out


def test_ws_status_wire_format_matches_consumer(tmp_path):
    """Prove a forwarded frame decodes exactly as the real consumer does.

    The operator's RemoteBackend subscribes with WsSubscriber(decode=json.loads),
    so the relay must send JSON text frames. Receive the raw text and decode it
    with the identical json.loads path.
    """
    app = makeApp("ORCH", save_root=str(tmp_path), group="orchestrator")
    with TestClient(app) as client:
        with client.websocket_connect("/ws_status") as ws:
            eventsink = app.state.driver.ports.eventsink
            client.portal.call(eventsink.emit_global_status, {"loop_state": "started"})
            raw = ws.receive_text()
            decoded = json.loads(raw)
            assert decoded == {"loop_state": "started"}
