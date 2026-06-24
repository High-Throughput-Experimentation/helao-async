# Framework SP-ORCH-3 Status WebSocket Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/ws_status` WebSocket to the framework orchestrator app (`makeOrchApp`) that relays the eventsink's `GLOBAL_STATUS_CHANNEL` emissions to the connected client as JSON, so the operator's `RemoteBackend.subscribe` gets a liveness tick on every orch state change. Closes the framework-orch endpoint completion cycle.

**Architecture:** A standalone `_orch_ws_relay(websocket, eventsink, channel)` coroutine (mirroring SP8 `BaseAPI._ws_relay`) + a `@app.websocket("/ws_status")` route inside `makeOrchApp`. The orch already emits `BroadcastGlobalStatus` → `eventsink.emit_global_status` on transitions, so no emission wiring is needed — the relay just forwards.

**Tech Stack:** Python 3.12 (conda env `helao`), FastAPI/Starlette WebSocket + `fastapi.testclient.TestClient`, `pytest`.

## Global Constraints

- Run pytest via the `helao` conda env: `conda run -n helao python -m pytest <path> -v`.
- Pure addition: do NOT modify `domain/**`, `helao/core/**`, or `helao/deploy/**`. Only `app/orch_api.py` + new tests + docs.
- WS path is root `/ws_status` (matches `Wss(host, port, "ws_status")` the operator opens). Reuse the SP8 relay semantics (accept → subscribe → forward matching channel as JSON → clean disconnect).
- The orchestrator app is a plain FastAPI (not `BaseAPI`), so implement a standalone relay coroutine in `app/orch_api.py` — do NOT import `BaseAPI`.
- `app/orch_api.py` is the app layer; AST boundary check must stay green.

---

### Task 1: `/ws_status` relay endpoint

**Files:**
- Modify: `helao/framework/app/orch_api.py` (module-level `_orch_ws_relay`; `@app.websocket("/ws_status")` inside `makeOrchApp`; import `GLOBAL_STATUS_CHANNEL`/`STATUS_CHANNEL`)
- Test: `helao/framework/tests/test_app_orch_status_ws.py`

**Interfaces:**
- Consumes: `ports.eventsink` (a `QueueEventSink` with `subscribe() -> asyncio.Queue` and `emit_global_status`); `helao.framework.ports.eventsink.GLOBAL_STATUS_CHANNEL`.
- Produces: WebSocket route `/ws_status`; module-level `async def _orch_ws_relay(websocket, eventsink, channel) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# helao/framework/tests/test_app_orch_status_ws.py
"""Orchestrator /ws_status WebSocket relay."""
import asyncio

from fastapi.testclient import TestClient

from helao.framework.app.factory import makeApp
from helao.framework.ports.eventsink import STATUS_CHANNEL


def _app(tmp_path):
    return makeApp("ORCH", save_root=str(tmp_path), group="orchestrator")


def test_ws_status_forwards_global_status(tmp_path):
    app = _app(tmp_path)
    client = TestClient(app)
    with client.websocket_connect("/ws_status") as ws:
        # emit a global-status payload through the orchestrator's eventsink
        eventsink = app.state.driver.ports.eventsink
        client.portal.call(eventsink.emit_global_status, {"loop_state": "started"})
        msg = ws.receive_json()
        assert msg == {"loop_state": "started"}


def test_ws_status_real_transition_emits(tmp_path):
    app = _app(tmp_path)
    client = TestClient(app)
    with client.websocket_connect("/ws_status") as ws:
        # a real control transition emits BroadcastGlobalStatus -> emit_global_status
        client.post("/estop_orch")
        msg = ws.receive_json()
        assert "loop_state" in msg


def test_ws_status_ignores_non_global_channel(tmp_path):
    app = _app(tmp_path)
    client = TestClient(app)
    with client.websocket_connect("/ws_status") as ws:
        eventsink = app.state.driver.ports.eventsink
        # emit on the plain status channel (not global) then a global one
        client.portal.call(eventsink.emit_status, {"ignored": True})
        client.portal.call(eventsink.emit_global_status, {"loop_state": "stopped"})
        msg = ws.receive_json()
        assert msg == {"loop_state": "stopped"}  # status-channel msg was filtered out


def test_ws_status_clean_disconnect(tmp_path):
    app = _app(tmp_path)
    client = TestClient(app)
    with client.websocket_connect("/ws_status") as ws:
        pass  # immediate close
    # reaching here without exception = clean teardown
    assert True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_orch_status_ws.py -v`
Expected: FAIL — websocket connect to `/ws_status` rejected (no such route).

> If `client.portal.call(...)` is unavailable in this Starlette/TestClient version,
> use the real-transition path (`client.post("/estop_orch")`) to drive the emission
> instead, and for the channel-filtering test post a transition after a manual
> status emit via a tiny helper route — but FIRST try `client.portal`; recent
> Starlette `TestClient` exposes `.portal` (an `anyio` blocking portal) for calling
> app coroutines from sync tests.

- [ ] **Step 3: Write minimal implementation**

In `helao/framework/app/orch_api.py`:

(a) At module top, import the channel constant:

```python
from helao.framework.ports.eventsink import GLOBAL_STATUS_CHANNEL
```

(b) Add the standalone relay coroutine at module level (near the other module-level helpers):

```python
async def _orch_ws_relay(websocket, eventsink, channel: str) -> None:
    """Accept a websocket and forward eventsink items on ``channel`` as JSON.

    Subscribes a fresh per-client queue from the (multisubscriber) eventsink and
    forwards the payload of every ``(channel, payload)`` tuple whose channel
    matches. Mirrors ``BaseAPI._ws_relay`` (SP8); JSON wire format. Ends cleanly
    on client disconnect or any send/recv error.
    """
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
        return
```

(c) Inside `makeOrchApp`, after the existing routes, register the WebSocket
(reference `ports` and `GLOBAL_STATUS_CHANNEL` from scope):

```python
    @app.websocket("/ws_status")
    async def ws_status(websocket) -> None:
        await _orch_ws_relay(websocket, ports.eventsink, GLOBAL_STATUS_CHANNEL)
```

> `makeOrchApp` receives `ports: OrchPorts` (it builds `OrchDriver(..., ports=ports)`),
> so `ports.eventsink` is in scope. If for any reason `ports` is not directly
> referenceable in the route closure, use `app.state.driver.ports.eventsink`.

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_orch_status_ws.py -v`
Expected: PASS (4 passed)

> If `test_ws_status_real_transition_emits` flakes because the emit races the
> subscribe, note that `_orch_ws_relay` subscribes *during* `websocket.accept()`
> which completes before `websocket_connect()` returns, so the subscriber queue
> exists before the subsequent `client.post(...)`. If a race is still observed, add
> a tiny `ws.receive`-readiness step or assert via `client.portal.call` emission
> (deterministic) as in `test_ws_status_forwards_global_status`.

- [ ] **Step 5: Commit**

```bash
git add helao/framework/app/orch_api.py helao/framework/tests/test_app_orch_status_ws.py
git commit -m "feat(framework): SP-ORCH-3 — /ws_status WebSocket relay on the orchestrator app"
```

---

### Task 2: RemoteBackend liveness contract test + verification

**Files:**
- Test: `helao/framework/tests/test_app_orch_status_ws.py` (add one test)
- (verification only otherwise)

**Interfaces:**
- Consumes: `helao.framework.adapters.operator_backend.RemoteBackend` (its `_ws_loop` fires `on_change()` on any message).

- [ ] **Step 1: Add the consumer-liveness unit test**

Append to `helao/framework/tests/test_app_orch_status_ws.py`:

```python
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
```

> If `_ws_loop`'s signature differs (e.g. it reads `self._wss` and takes only
> `on_change`), match the actual signature in
> `helao/core/servers/operator/orch_backend.py` — the body sets `be._wss` and runs
> one iteration. Do not modify `RemoteBackend`; adapt the test to its real API.

- [ ] **Step 2: Run the new test**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_orch_status_ws.py::test_remote_backend_ws_loop_fires_on_change -v`
Expected: PASS

- [ ] **Step 3: Run the full framework suite**

Run: `conda run -n helao python -m pytest helao/framework/tests/ -p no:cacheprovider -q 2>&1 | tail -1`
Expected: all pass, no regressions.

- [ ] **Step 4: Confirm boundary + pure-addition**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_boundaries.py -q 2>&1 | tail -1`
Expected: PASS.

Run: `git diff --name-only feat/framework-scaffold...HEAD | grep -E "helao/(core|deploy)/|domain/" || echo "NONE (clean)"`
Expected: `NONE (clean)` — only `app/orch_api.py`, new test, docs.

- [ ] **Step 5: Commit**

```bash
git add helao/framework/tests/test_app_orch_status_ws.py
git commit -m "test(framework): SP-ORCH-3 — RemoteBackend ws-loop liveness contract + suite verify"
```

---

## Self-Review

**Spec coverage:**
- §4.1 `/ws_status` endpoint → Task 1. ✓
- §4.2 `_orch_ws_relay` helper → Task 1. ✓
- §4.3 no emission change (relay only) → honored (Task 1 adds no emission wiring). ✓
- §6 error handling (no-subscribe close, disconnect/except clean return) → relay code + `test_ws_status_clean_disconnect`. ✓
- §7 test strategy (forwards, real transition, channel filter, disconnect, RemoteBackend liveness) → Tasks 1-2. ✓
- §2 non-goals (no status_summary ping, no ws_data/ws_live, no domain/FSM change) → respected; Task 2 Step 4 guards pure-addition. ✓

**Placeholder scan:** No TBD/TODO. Full relay + endpoint + test code given. Guarded notes (`client.portal` availability, `_ws_loop` signature, emit/subscribe race) are concrete fallbacks, not placeholders.

**Type consistency:** `_orch_ws_relay(websocket, eventsink, channel)` defined + called in Task 1 with `ports.eventsink` + `GLOBAL_STATUS_CHANNEL`. `QueueEventSink.subscribe()`/`emit_global_status`/`emit_status` match the adapter API. `RemoteBackend._ws_loop(on_change)` + `_wss` match the consumer (Task 2 adapts to the real signature).
