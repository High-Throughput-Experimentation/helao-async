# Framework SP-ORCH-3 — Orchestrator Status WebSocket (design)

**Date:** 2026-06-23
**Branch:** `feat/framework-orch-status-ws`
**Cycle:** Framework-orch endpoint completion (third and final sub-project).

## 1. Context

SP-ORCH-1 added the pure orchestrator domain ops; SP-ORCH-2 wired them to root-path
HTTP endpoints the operator's `RemoteBackend`/`HelaoOperator` call. The last gap is
the **status WebSocket** the operator's `RemoteBackend.subscribe` opens for live
updates.

`RemoteBackend.subscribe(on_change)` (`helao/core/servers/operator/orch_backend.py`):
- opens `Wss(host, port, "ws_status")` — a WebSocket at root path `/ws_status`,
- `_ws_loop` calls `on_change()` on **any** received message (the operator then
  re-fetches state via the SP-ORCH-2 HTTP endpoints — the WS is a *liveness tick*,
  not a data channel),
- also runs a `_poll_loop` fallback every `poll_interval` and a one-shot `_prime`.

So the operator already functions without the WS (poll fallback); the WS just makes
it responsive. The framework orchestrator already emits global-status changes:
`execute_commands` handles `BroadcastGlobalStatus` →
`ports.eventsink.emit_global_status(payload)` (`app/orch_api.py:175-176`) on the
`GLOBAL_STATUS_CHANNEL` (`ports/eventsink.py:8`). `QueueEventSink` is
multi-subscriber (`subscribe()` → a fresh per-client `asyncio.Queue` receiving
every emission). SP8's `BaseAPI._ws_relay` is the established accept→subscribe→
forward-JSON→handle-disconnect pattern (`app/base_api.py:1210`).

## 2. Goal & non-goals

**Goal:** Add a `/ws_status` WebSocket endpoint to the framework orchestrator app
(`makeOrchApp`) that relays the eventsink's `GLOBAL_STATUS_CHANNEL` emissions to the
connected client as JSON, so `RemoteBackend.subscribe`'s `_ws_loop` fires
`on_change()` whenever orch state changes. Plus an end-to-end-style integration
test. This closes the framework-orch endpoint completion cycle.

**Non-goals:**
- `status_summary` *population* (the legacy network **ping heartbeat**
  `ping_action_servers`). It remains a documented follow-up; `get_status_summary`
  returns the (empty until populated) field. The operator's status-summary panel is
  secondary; queue management, control, and global-status monitoring all work
  without it.
- `ws_data` / `ws_live` channels (visualizer data streams — out of scope; the
  operator only opens `ws_status`).
- zstd-pickle wire parity with legacy (SP8 already chose JSON for framework WS;
  `RemoteBackend._ws_loop` only checks *that* a message arrived, not its content).
- Changing the dispatch FSM, the domain ops, or the HTTP endpoints.
- Deployment rewiring; operator/legacy `core/**` changes.

## 3. Boundary contract

`app/orch_api.py` is the app layer (FastAPI/WebSocket lives here). The relay reads
from the injected `ports.eventsink` (a port) — no domain change. AST boundary check
stays green.

## 4. Components

All changes are in `helao/framework/app/orch_api.py`, inside `makeOrchApp`.

### 4.1 `/ws_status` WebSocket endpoint

Register at root path (matching `Wss(host, port, "ws_status")` → `/ws_status`):

```python
@app.websocket("/ws_status")
async def ws_status(websocket):
    await _orch_ws_relay(websocket, ports.eventsink, GLOBAL_STATUS_CHANNEL)
```

The handler accepts the socket, subscribes a fresh queue from the eventsink, and
forwards every `(channel, payload)` whose channel is `GLOBAL_STATUS_CHANNEL` as JSON
until the client disconnects.

### 4.2 `_orch_ws_relay` helper

A standalone module-level coroutine in `app/orch_api.py` (the orchestrator app is a
plain FastAPI, not a `BaseAPI`, so it cannot reuse `BaseAPI._ws_relay` directly).
Mirror the SP8 `_ws_relay` semantics:

```python
async def _orch_ws_relay(websocket, eventsink, channel: str) -> None:
    from starlette.websockets import WebSocketDisconnect
    await websocket.accept()
    subscribe = getattr(eventsink, "subscribe", None)
    if not callable(subscribe):
        await websocket.close()
        return
    queue = subscribe()
    try:
        while True:
            item = await queue.get()
            if isinstance(item, tuple) and len(item) == 2:
                item_channel, payload = item
            else:
                item_channel, payload = channel, item
            if item_channel != channel:
                continue
            await websocket.send_json(payload)
    except WebSocketDisconnect:
        return
    except Exception:
        # any send/recv error ends the relay cleanly
        return
```

Import `GLOBAL_STATUS_CHANNEL` from `helao.framework.ports.eventsink` at module top.

### 4.3 No change needed to global-status emission

The orch already emits on `BroadcastGlobalStatus` via `execute_commands`
(`emit_global_status`), and `apply_intent`/`on_status_update`/dispatch all produce a
`BroadcastGlobalStatus` on transitions (SP5). So a `start`/`stop`/`estop`/dispatch/
status-update naturally pushes a `/ws_status` message. No new emission wiring.

## 5. Data flow

```
orch transition → BroadcastGlobalStatus → execute_commands → eventsink.emit_global_status
   → every subscriber queue gets ("global_status", payload)
/ws_status client (RemoteBackend.subscribe → Wss) ← _orch_ws_relay forwards payload as JSON
   → RemoteBackend._ws_loop sees a message → on_change() → operator re-fetches via HTTP
```

## 6. Error handling

- No eventsink `subscribe` (e.g. a non-queue sink) → relay closes the socket cleanly.
- Client disconnect (`WebSocketDisconnect`) or any send error → relay returns,
  ending the per-client task (no leak; the subscriber queue is GC'd).
- A slow/blocked client only fills its own queue (per-subscriber), not others'.

## 7. Test strategy

Tests under `helao/framework/tests/` (e.g. `test_app_orch_status_ws.py`) using
`fastapi.testclient.TestClient`'s `websocket_connect` against an app from
`makeApp("ORCH", group="orchestrator")` (its `ports.eventsink` is a
`QueueEventSink`):

- **Relay forwards a global-status emission:** connect to `/ws_status`; from the
  test, `await app.state.driver.ports.eventsink.emit_global_status({"loop_state": "started"})`
  (or trigger a real transition via the HTTP `/estop_orch` endpoint, which emits a
  `BroadcastGlobalStatus`); assert the websocket receives the JSON payload.
- **Trigger via a real transition:** `POST /estop_orch` (or `/start` with no work)
  then assert a `/ws_status` message arrives carrying a `loop_state` key — proving
  the FSM→eventsink→WS path end-to-end.
- **Channel filtering:** emit on `STATUS_CHANNEL` (not global) and assert it is NOT
  forwarded to `/ws_status` (only global-status passes).
- **Clean disconnect:** exiting the `websocket_connect` context does not raise / the
  server-side relay task ends without error (best-effort: assert no exception).
- **RemoteBackend liveness shape (unit):** construct `RemoteBackend.__new__`, set a
  fake `_wss` whose `read_messages` returns a message once, run one `_ws_loop`
  iteration, assert `on_change` was called — confirming the consumer reacts to any
  message (documents the contract; no live server).

Full framework suite + AST boundary check stay green.

## 8. API parity

The endpoint path is exactly `/ws_status` (root) — what `RemoteBackend.subscribe`
opens via `Wss(host, port, "ws_status")`. JSON wire format (SP8 precedent); the
consumer only requires message *arrival*, so content shape is non-critical (the
`globalstatusmodel.as_json()` payload is sent).

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| WS path mismatch vs consumer | Root `/ws_status` matches `Wss(..., "ws_status")`; test connects to that exact path |
| Relay leaks tasks/queues on disconnect | `WebSocketDisconnect`/except returns; per-subscriber queue GC'd; test covers disconnect |
| Operator status panel empty (no status_summary) | Documented follow-up (ping heartbeat); operator otherwise fully functional via poll + WS tick |
| Slow client blocks others | `QueueEventSink` is per-subscriber; back-pressure is isolated |
| No emission on transition | Verified: SP5 emits `BroadcastGlobalStatus` on transitions → `emit_global_status`; integration test triggers a real transition |

## 10. Done criteria

- `/ws_status` WebSocket registered in `makeOrchApp`, relaying
  `GLOBAL_STATUS_CHANNEL` to the client as JSON via `_orch_ws_relay`.
- TestClient websocket tests pass under the `helao` env (relay forwards, real
  transition triggers, channel filtering, clean disconnect, consumer liveness);
  full framework suite still green; AST boundary check still green.
- No legacy `core/**` or `deploy/**` modified.
- **Cycle close:** the framework orchestrator now exposes the HTTP query/mutation/
  control endpoints (SP-ORCH-2) **and** the `/ws_status` WebSocket (SP-ORCH-3) the
  framework operator needs. Remaining follow-ups (separate, documented):
  `status_summary` ping heartbeat; deployment cut-over.
