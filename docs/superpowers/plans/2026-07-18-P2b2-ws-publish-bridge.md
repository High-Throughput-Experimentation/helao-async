# P2b-2 WS Publish Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Discharge the DD-7 `HexagonDeferred` on `publish_status`/`publish_data`/`publish_live` in `helao/hexagon/adapters/legacy/status.py` by making them functional puts onto the legacy fan-out queues with correct wire types, and certify frame parity.

**Architecture:** A new hand-written native adapter `WsPublishBridge` (`helao/hexagon/adapters/native/ws_publish.py`) holds refs to the three legacy `MultisubscriberQueue`s (`base.status_q`/`data_q`/`live_q`) and converts each dict payload to its channel's wire type at put time (D1: `ActionModel` for status, `DataPackageModel` for data, dict as-is for live). `DispatcherStatusAdapter` gains a late-bind seam (`bind_publish_bridge`, D3 — mirror of the P2b-1 `bind_base` pattern) and delegates the three `publish_*` to the bound bridge, raising `UnwiredPortError` when unbound. `makeActionApp`'s existing `_hexagon_active_graft_startup` hook constructs and binds the bridge once `app.base` (hence its queues) is live. Frame bytes are then produced by the untouched legacy `WsPublisher` `pyzstd.compress(pickle.dumps(...))` path — wire parity by construction, certified by a real-encoder/real-decoder round-trip test.

**Tech Stack:** Python 3.12 (`helao` conda env), pydantic v2 (`model_validate`), FastAPI/uvicorn + `websockets` (test harness only), `pyzstd`+`pickle` via the REAL `helao.helpers.ws_utils.WsPublisher`/`WsSubscriber`, pytest + pytest-asyncio, pyright, black.

## Global Constraints

- ZERO LEGACY EDITS: only helao/hexagon/** + pyproject.toml. Nothing under helao/core, helao/helpers, helao/deploy.
- Port ports/status.py UNCHANGED (Protocol shared). Drift resolved adapter-local via model_validate (D1).
- Bind ACTION apps only (D3); do not touch makeOrchApp; orch WS stays legacy (Q1).
- Real WsSubscriber/WsPublisher in tests — never a copy of the encoder (§10.1(3) dd31c36f trap).
- `conda run -n helao` for all tooling.
- Branch: `feat/hexagon-p2b2-ws-bridge` off `unstable` (baseline: P0…P2b-1 merged).
- TDD: failing test first, then minimal implementation. Run `black` on every changed `.py` file immediately before each commit.
- No commits to `unstable`/`main`, no pushes — the controller handles integration.

**Binding decision docs (already resolved — do not re-litigate):** `.superpowers/sdd/p2b2-decisions.md` (D1–D6), `.superpowers/sdd/p2b-scope.md` §3.

**Verified anchors (transcribed from live code 2026-07-18):**
- Port `helao/hexagon/ports/status.py:51-55`: `async def publish_status(self, payload: dict) -> None: ...` (same shape for `publish_data`, `publish_live`). DO NOT MODIFY.
- `helao/hexagon/adapters/legacy/status.py:130-137`: the three `raise HexagonDeferred("WS publish bridge is P1b2 (DD-7)")`. `__init__(self, server_key, own_host="", own_port=0)` sets `_server_key`/`_own_host`/`_own_port`/`clients`. Module-top drift block at lines 1-41.
- `helao/core/servers/base.py:196-206` (READ-ONLY): `self.status_q = MultisubscriberQueue()`, `self.data_q`, `self.live_q`; wrapped by `status_publisher`/`data_publisher`/`live_publisher = WsPublisher(<q>)`.
- `helao/helpers/ws_utils.py` (READ-ONLY): `WsPublisher(source_queue, xform_func=lambda x: x)`; `broadcast` sends `pyzstd.compress(pickle.dumps(self.xform_func(source_msg)))`. `WsSubscriber(host, port, path)` decodes `pickle.loads(pyzstd.decompress(recv_bytes))` into `self.recv_queue`; its `__init__` starts `self.subscriber_task` on the running loop.
- `helao/helpers/multisubscriber_queue.py` (READ-ONLY): `MultisubscriberQueue` — `async put(data)`, `put_nowait(data)`, `queue() -> asyncio.Queue` (registers a direct subscriber), `subscribers` list; accepts any object.
- Wire types: status_q carries `helao.core.models.action.ActionModel`, data_q carries `helao.core.models.data.DataPackageModel`, live_q carries a plain dict. Both models restore via `.model_validate(dict)`. `ActionModel.model_validate({})` SUCCEEDS (all fields defaulted) — the unbound guard must fire before validation.
- `helao/hexagon/app/factory.py:85-107` `makeActionApp`: already registers `_hexagon_active_graft_startup` (runs with `app.base` live, installs the P2b-1 write graft) and `_hexagon_active_graft_shutdown`; sets `app.hexagon_wiring = wiring`. `wiring.status` is a `DispatcherStatusAdapter` (typed `Optional[StatusPort]` on `PortWiring`).
- `helao/hexagon/tests/test_adapters_misc.py:105-111` `test_status_conformance_and_deferred_publish` asserts `HexagonDeferred` on `await a.publish_status({})` — MUST be updated in Task 2.
- `helao/hexagon/adapters/errors.py`: `UnwiredPortError(RuntimeError)` already exists.
- `pyproject.toml` currently: `[tool.black]` with `force-exclude = 'helao/hexagon/adapters/native/'` — narrowed in Task 1 per D2.
- Boundary test `helao/hexagon/tests/test_boundaries.py`: `adapters/native/` bans `helao.core.servers.*`; `helao.helpers.*` and `helao.core.models.*` are allowed. `ws_publish.py` complies by construction.
- uvicorn-in-loop test precedent: `helao/hexagon/tests/test_adapter_transport.py` (`uvicorn.Config`/`uvicorn.Server` + `server.started` poll + `server.should_exit` teardown).

---

### Task 1: `WsPublishBridge` (native adapter) + real-encoder round-trip test + black-exclude narrowing (D2)

**Files:**
- Create: `helao/hexagon/adapters/native/ws_publish.py`
- Create: `helao/hexagon/tests/test_ws_publish_bridge.py`
- Modify: `pyproject.toml` (the `[tool.black]` block, currently lines 1-11)

**Interfaces:**
- Consumes: `MultisubscriberQueue` (`helao.helpers.multisubscriber_queue`), `ActionModel` (`helao.core.models.action`), `DataPackageModel`/`DataModel` (`helao.core.models.data`), `WsPublisher`/`WsSubscriber` (`helao.helpers.ws_utils`) — all pre-existing, untouched.
- Produces: `class WsPublishBridge` with `__init__(self, status_q: MultisubscriberQueue, data_q: MultisubscriberQueue, live_q: MultisubscriberQueue)` and `async def publish_status(self, payload: dict) -> None`, `async def publish_data(self, payload: dict) -> None`, `async def publish_live(self, payload: dict) -> None`. Instance attrs `_status_q`/`_data_q`/`_live_q`. Task 2 binds an instance into `DispatcherStatusAdapter`.

- [ ] **Step 1: Create the working branch**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
git checkout unstable
git checkout -b feat/hexagon-p2b2-ws-bridge
```

Expected: `Switched to a new branch 'feat/hexagon-p2b2-ws-bridge'`

- [ ] **Step 2: Write the failing round-trip test**

Create `helao/hexagon/tests/test_ws_publish_bridge.py` with exactly:

```python
"""P2b-2 WS publish bridge: REAL-encoder/REAL-decoder round-trip (§10.1(3)).

The bridge's puts must serialize through the real legacy wire path — the
WsPublisher ``pyzstd.compress(pickle.dumps(...))`` encode and the
WsSubscriber ``pickle.loads(pyzstd.decompress(...))`` decode
(helao/helpers/ws_utils.py) — never a test-local copy of either (the
dd31c36f trap). A minimal uvicorn app hosts the three WS routes with the
exact handler shape the legacy BaseAPI uses (base_api.py:677-708), and a
real WsSubscriber connects and decodes. Certifies D1: status frames decode
to ActionModel, data frames to DataPackageModel, live frames to the dict.
"""

import asyncio
import socket
from uuid import uuid4

import pydantic
import pytest
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from helao.core.models.action import ActionModel
from helao.core.models.data import DataModel, DataPackageModel
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.ws_utils import WsPublisher, WsSubscriber
from helao.hexagon.adapters.native.ws_publish import WsPublishBridge

HOST = "127.0.0.1"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def _ws_app(publishers: dict) -> FastAPI:
    """Host each REAL WsPublisher under its route, with the exact handler
    shape the legacy BaseAPI registers (base_api.py:677-708)."""
    app = FastAPI()
    for path, pub in publishers.items():

        def _make_route(pub: WsPublisher):
            async def _route(websocket: WebSocket):
                await pub.connect(websocket)
                try:
                    await pub.broadcast(websocket)
                except WebSocketDisconnect:
                    pub.disconnect(websocket)

            return _route

        app.websocket(path)(_make_route(pub))
    return app


@pytest.mark.asyncio
async def test_bridge_roundtrip_real_publisher_real_subscriber():
    status_q = MultisubscriberQueue()
    data_q = MultisubscriberQueue()
    live_q = MultisubscriberQueue()
    pubs = {
        "/ws_status": WsPublisher(status_q),
        "/ws_data": WsPublisher(data_q),
        "/ws_live": WsPublisher(live_q),
    }
    queues = {"/ws_status": status_q, "/ws_data": data_q, "/ws_live": live_q}
    port = _free_port()
    cfg = uvicorn.Config(_ws_app(pubs), host=HOST, port=port, log_level="warning")
    server = uvicorn.Server(cfg)
    serve_task = asyncio.create_task(server.serve())
    subs: dict = {}
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.1)
        assert server.started

        # real WsSubscriber per channel; its __init__ starts the task
        subs = {p: WsSubscriber(HOST, port, p.strip("/")) for p in pubs}
        # broadcast() registers its subscriber queue on first iteration —
        # wait until every fan-out queue has a live WS subscription before
        # putting, or the frames are lost.
        for _ in range(200):
            if all(len(q.subscribers) >= 1 for q in queues.values()):
                break
            await asyncio.sleep(0.05)
        assert all(len(q.subscribers) >= 1 for q in queues.values())

        bridge = WsPublishBridge(status_q, data_q, live_q)
        act_uuid = uuid4()
        status_payload = ActionModel(
            action_uuid=act_uuid, action_name="acquire_data"
        ).model_dump()
        data_payload = DataPackageModel(
            action_uuid=act_uuid,
            action_name="acquire_data",
            datamodel=DataModel(data={uuid4(): {"epoch_s": [1.0]}}),
        ).model_dump()
        live_payload = {"sim_temp": (25.0, 1234.5)}
        await bridge.publish_status(status_payload)
        await bridge.publish_data(data_payload)
        await bridge.publish_live(live_payload)

        decoded: dict = {}
        for path, sub in subs.items():
            for _ in range(200):
                msgs = await sub.read_messages()
                if msgs:
                    decoded[path] = msgs[0]
                    break
                await asyncio.sleep(0.05)
        assert set(decoded) == set(pubs), f"missing frames: {set(pubs) - set(decoded)}"

        # D1 wire types restored through the REAL pickle+pyzstd path
        assert isinstance(decoded["/ws_status"], ActionModel)
        assert decoded["/ws_status"].action_uuid == act_uuid
        assert isinstance(decoded["/ws_data"], DataPackageModel)
        assert decoded["/ws_data"].action_uuid == act_uuid
        assert decoded["/ws_data"].datamodel.data  # payload survived
        assert decoded["/ws_live"] == live_payload  # dict-native channel
    finally:
        for sub in subs.values():
            sub.subscriber_task.cancel()
        server.should_exit = True
        await asyncio.wait_for(serve_task, timeout=10)


@pytest.mark.asyncio
async def test_bridge_rejects_malformed_payload_loud():
    """D1 fail-loud: a payload that is not the channel's model in dict form
    raises pydantic.ValidationError and puts NOTHING on the queue."""
    q = MultisubscriberQueue()
    sub = q.queue()  # direct subscriber queue, no WS needed
    bridge = WsPublishBridge(q, q, q)
    with pytest.raises(pydantic.ValidationError):
        # DataPackageModel requires action_uuid/action_name/datamodel
        await bridge.publish_data({"nonsense": True})
    assert sub.empty()
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
conda run -n helao python -m pytest helao/hexagon/tests/test_ws_publish_bridge.py -v
```

Expected: collection ERROR — `ModuleNotFoundError: No module named 'helao.hexagon.adapters.native.ws_publish'`

- [ ] **Step 4: Write the minimal implementation**

Create `helao/hexagon/adapters/native/ws_publish.py` with exactly:

```python
"""Native WS publish bridge (P2b-2): functional publish_status/data/live.

Discharges the DD-7 HexagonDeferred on DispatcherStatusAdapter.publish_*
by putting each payload onto the composition's legacy fan-out queues
(base.status_q / data_q / live_q) — the queues the legacy-hosted
WsPublisher routes (/ws_status /ws_data /ws_live, base_api.py:677-708)
broadcast from. Frame bytes are then produced by the untouched legacy
``pyzstd.compress(pickle.dumps(...))`` path (helao/helpers/ws_utils.py) —
wire parity by construction, certified by the round-trip test.

Port-vs-wire drift resolved HERE, adapter-local (P2b-2 D1): the StatusPort
publish_* members are dict-typed (Protocol unchanged — fakes and other
adapters share it), but the legacy consumers expect typed objects on the
wire: status_q carries ActionModel (log_status_task does attribute access),
data_q carries DataPackageModel, live_q is dict-native. Each put
model_validates its payload back to the channel's wire type; a malformed
payload fails loud with pydantic.ValidationError, never a silent bad frame.

The queue refs live on the legacy Base, which only exists once the app has
started — the bridge is therefore constructed and bound in makeActionApp's
startup hook (D3: ACTION apps only; orch WS stays on legacy relays, Q1).

This module is HAND-WRITTEN (not a verbatim re-body copy) and is
black-enforced (pyproject force-exclude narrowed in P2b-2, D2).
"""

from helao.core.models.action import ActionModel
from helao.core.models.data import DataPackageModel
from helao.helpers.multisubscriber_queue import MultisubscriberQueue

__all__ = ["WsPublishBridge"]


class WsPublishBridge:
    """Holds the three legacy fan-out queue refs and converts each dict
    payload to its channel's wire type at put time (D1)."""

    def __init__(
        self,
        status_q: MultisubscriberQueue,
        data_q: MultisubscriberQueue,
        live_q: MultisubscriberQueue,
    ):
        self._status_q = status_q
        self._data_q = data_q
        self._live_q = live_q

    async def publish_status(self, payload: dict) -> None:
        await self._status_q.put(ActionModel.model_validate(payload))

    async def publish_data(self, payload: dict) -> None:
        await self._data_q.put(DataPackageModel.model_validate(payload))

    async def publish_live(self, payload: dict) -> None:
        await self._live_q.put(payload)
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
conda run -n helao python -m pytest helao/hexagon/tests/test_ws_publish_bridge.py -v
```

Expected: `2 passed` (both `test_bridge_roundtrip_real_publisher_real_subscriber` and `test_bridge_rejects_malformed_payload_loud` PASS)

- [ ] **Step 6: Run the boundary test (ws_publish.py must satisfy the adapters/native rules)**

```bash
conda run -n helao python -m pytest helao/hexagon/tests/test_boundaries.py -q
```

Expected: all pass, 0 failed (`ws_publish.py` imports only `helao.core.models.*` + `helao.helpers.*` — no `helao.core.servers.*`)

- [ ] **Step 7: Format and commit the bridge**

```bash
conda run -n helao black helao/hexagon/tests/test_ws_publish_bridge.py
# NOTE: ws_publish.py is still force-excluded until Step 8 — black is a
# no-op on it right now; it gets black-enforced by the next step.
git add helao/hexagon/adapters/native/ws_publish.py helao/hexagon/tests/test_ws_publish_bridge.py
git commit -m "feat(hexagon): WsPublishBridge native adapter + real-encoder round-trip test (P2b-2 T1)"
```

Expected: commit created on `feat/hexagon-p2b2-ws-bridge`.

- [ ] **Step 8: Narrow the black force-exclude (D2)**

Replace the entire content of `pyproject.toml` (it currently contains only the `[tool.black]` block) with exactly:

```toml
[tool.black]
# Four native re-body modules under helao/hexagon/adapters/native/ are
# VERBATIM, byte-identical copies of the legacy CARDS-P6 write collaborators
# (helao/core/servers/active_data_*.py, base_meta_writer.py), pinned per-method
# by inspect.getsource source-parity tests for byte-parity. Several legacy
# collaborator modules are NOT black-formatted at line-length 88, so running
# black on the copies would reformat them and break the source-parity
# byte-identity. force-exclude protects ONLY those four re-bodies; the
# hand-written native adapters (artifact_store, data_sink, ws_publish) are
# black-enforced like the rest of the repo (P2b-2 D2). (No other black
# config: line length stays the default 88.)
force-exclude = 'helao/hexagon/adapters/native/(meta_writer|data_file|data_stream|finalizer)\.py'
```

- [ ] **Step 9: Verify the un-excluded hand-written adapters are black-clean**

```bash
conda run -n helao black --check helao/hexagon/adapters/native/artifact_store.py helao/hexagon/adapters/native/data_sink.py helao/hexagon/adapters/native/ws_publish.py
```

Expected: `3 files would be left unchanged.` (exit 0). If `ws_publish.py` needs reformatting, run `conda run -n helao black helao/hexagon/adapters/native/ws_publish.py`, re-run the check, and re-run Step 5's pytest. If `artifact_store.py` or `data_sink.py` fail the check, STOP and report — they were verified black-clean at plan time; a failure means an intervening change, do not reformat them silently.

- [ ] **Step 10: Verify the four re-bodies are still excluded (byte-identity protection)**

```bash
conda run -n helao black --check helao/hexagon/adapters/native/meta_writer.py helao/hexagon/adapters/native/data_file.py helao/hexagon/adapters/native/data_stream.py helao/hexagon/adapters/native/finalizer.py
```

Expected: `No Python files are present to be formatted. Nothing to do` (or equivalent "0 files" output — force-exclude filters them even when passed explicitly). They must NOT be reported as "would be reformatted".

- [ ] **Step 11: Commit the pyproject narrowing**

```bash
git add pyproject.toml
git commit -m "chore(black): narrow native force-exclude to the 4 verbatim re-bodies (P2b-2 D2)"
```

Expected: commit created.

---

### Task 2: Wire the bridge into `DispatcherStatusAdapter` + bind at `makeActionApp` startup

**Files:**
- Modify: `helao/hexagon/adapters/legacy/status.py` (docstring lines 1-41, imports lines 43-49, `__init__` lines 55-59, publish methods lines 130-137)
- Modify: `helao/hexagon/app/factory.py` (imports lines 16-26, `makeActionApp` lines 85-107)
- Modify: `helao/hexagon/tests/test_adapters_misc.py` (imports lines 1-19, test at lines 105-111)
- Modify: `helao/hexagon/tests/test_factory.py` (append one test)

**Interfaces:**
- Consumes: `WsPublishBridge(status_q, data_q, live_q)` with `async publish_status/publish_data/publish_live(payload: dict) -> None` (Task 1); `UnwiredPortError` (`helao.hexagon.adapters.errors`); the existing `_hexagon_active_graft_startup` hook and `app.base.status_q/data_q/live_q`.
- Produces: `DispatcherStatusAdapter.bind_publish_bridge(bridge: WsPublishBridge) -> None`; instance attr `_publish_bridge: Optional[WsPublishBridge]` (None until bound); `app.hexagon_ws_bridge` on action apps (None at build, `WsPublishBridge` after startup). Task 3 verifies these; nothing else depends on new names.

- [ ] **Step 1: Update the existing deferred-publish test to the new contract (failing first)**

In `helao/hexagon/tests/test_adapters_misc.py`, make these exact edits:

Replace the import at line 9:

```python
from helao.hexagon.adapters.errors import HexagonDeferred
```

with:

```python
from helao.hexagon.adapters.errors import UnwiredPortError
```

(`HexagonDeferred` has no other use in this file after this step.)

Replace the whole test at lines 105-111:

```python
# --- Status: wire-level push (publish_* deferred loudly) ----------------------
@pytest.mark.asyncio
async def test_status_conformance_and_deferred_publish():
    a = DispatcherStatusAdapter(server_key="ORCH")
    assert isinstance(a, StatusPort)
    with pytest.raises(HexagonDeferred):
        await a.publish_status({})
```

with:

```python
# --- Status: wire-level push (publish_* fail loud until the bridge binds) -----
@pytest.mark.asyncio
async def test_status_conformance_and_unbound_publish():
    a = DispatcherStatusAdapter(server_key="ORCH")
    assert isinstance(a, StatusPort)
    with pytest.raises(UnwiredPortError):
        await a.publish_status({})
    with pytest.raises(UnwiredPortError):
        await a.publish_data({})
    with pytest.raises(UnwiredPortError):
        await a.publish_live({})


@pytest.mark.asyncio
async def test_status_bound_publish_puts_wire_types():
    """D1 through the adapter: a bound publish_status restores the
    channel's wire type (ActionModel) onto the fan-out queue."""
    from helao.core.models.action import ActionModel
    from helao.helpers.multisubscriber_queue import MultisubscriberQueue
    from helao.hexagon.adapters.native.ws_publish import WsPublishBridge

    status_q = MultisubscriberQueue()
    data_q = MultisubscriberQueue()
    live_q = MultisubscriberQueue()
    sub = status_q.queue()  # direct subscriber queue
    a = DispatcherStatusAdapter(server_key="SIM")
    a.bind_publish_bridge(WsPublishBridge(status_q, data_q, live_q))
    await a.publish_status(ActionModel(action_name="acquire_data").model_dump())
    item = sub.get_nowait()
    assert isinstance(item, ActionModel)
    assert item.action_name == "acquire_data"
```

- [ ] **Step 2: Add the factory startup-bind test (failing first)**

Append to `helao/hexagon/tests/test_factory.py`:

```python
@pytest.mark.asyncio
async def test_action_app_startup_binds_ws_publish_bridge(
    installed_config, monkeypatch
):
    """P2b-2 D3: the existing _hexagon_active_graft_startup hook constructs
    WsPublishBridge over the live base's queues and binds it into the status
    adapter (ACTION apps only; makeOrchApp is untouched, Q1)."""
    from types import SimpleNamespace

    from helao.helpers.multisubscriber_queue import MultisubscriberQueue
    from helao.hexagon.adapters.native.ws_publish import WsPublishBridge
    import helao.hexagon.app.active_graft as active_graft_mod
    from helao.hexagon.app.factory import makeActionApp

    class _StubGraft:
        def close(self):
            pass

    # isolate the bind from the P2b-1 write graft (its own tests cover it)
    monkeypatch.setattr(
        active_graft_mod,
        "graft_active_write_path",
        lambda base, wiring: _StubGraft(),
    )
    app = makeActionApp("SIM", "helao.deploy.test.servers.action.ws_simulator")
    assert app.hexagon_ws_bridge is None  # bound at startup, not at build
    app.base = SimpleNamespace(
        status_q=MultisubscriberQueue(),
        data_q=MultisubscriberQueue(),
        live_q=MultisubscriberQueue(),
    )
    hook = [
        h
        for h in app.router.on_startup
        if h.__name__ == "_hexagon_active_graft_startup"
    ][0]
    await hook()
    assert isinstance(app.hexagon_ws_bridge, WsPublishBridge)
    assert app.hexagon_wiring.status._publish_bridge is app.hexagon_ws_bridge
    assert app.hexagon_ws_bridge._status_q is app.base.status_q
    assert app.hexagon_ws_bridge._data_q is app.base.data_q
    assert app.hexagon_ws_bridge._live_q is app.base.live_q
```

- [ ] **Step 3: Run both test files to verify the new tests fail**

```bash
conda run -n helao python -m pytest helao/hexagon/tests/test_adapters_misc.py helao/hexagon/tests/test_factory.py -v
```

Expected: FAIL —
- `test_status_conformance_and_unbound_publish` fails with `HexagonDeferred` raised instead of `UnwiredPortError`
- `test_status_bound_publish_puts_wire_types` fails with `AttributeError: 'DispatcherStatusAdapter' object has no attribute 'bind_publish_bridge'`
- `test_action_app_startup_binds_ws_publish_bridge` fails with `AttributeError: ... object has no attribute 'hexagon_ws_bridge'`
- all pre-existing tests in both files still pass

- [ ] **Step 4: Implement the adapter seam in `helao/hexagon/adapters/legacy/status.py`**

Four exact edits:

(a) In the module docstring, replace the sentence at lines 5-9:

```
Keeps its own client registry (attach/detach). The WS publish_*
members (WsPublisher / _ws_relay zstd-pickle) are deliberately deferred
(DD-7) — they raise HexagonDeferred loudly; in the P1b1 wrapped-legacy
composition the live WS channels run on legacy Base relays.
```

with:

```
Keeps its own client registry (attach/detach). The WS publish_*
members are WIRED (P2b-2 — DD-7 discharged): they delegate to a
WsPublishBridge bound at makeActionApp startup, which model-validates each
payload back to its channel's wire type and puts it on the legacy fan-out
queues (adapter-local drift fix D1, like the three drifts below). Before
binding they raise UnwiredPortError loudly. Orch compositions never bind
the bridge — their live WS channels stay on legacy Base relays (Q1).
```

(b) Replace the import at line 48:

```python
from helao.hexagon.adapters.errors import HexagonDeferred
```

with:

```python
from helao.hexagon.adapters.errors import UnwiredPortError
from helao.hexagon.adapters.native.ws_publish import WsPublishBridge
```

(c) Replace `__init__` (lines 55-59):

```python
    def __init__(self, server_key: str, own_host: str = "", own_port: int = 0):
        self._server_key = server_key
        self._own_host = own_host
        self._own_port = own_port
        self.clients: List[Tuple[str, str, int]] = []
```

with:

```python
    def __init__(self, server_key: str, own_host: str = "", own_port: int = 0):
        self._server_key = server_key
        self._own_host = own_host
        self._own_port = own_port
        self.clients: List[Tuple[str, str, int]] = []
        self._publish_bridge: Optional[WsPublishBridge] = None

    def bind_publish_bridge(self, bridge: WsPublishBridge) -> None:
        """Late-bind the WS publish bridge (P2b-2 D3): the fan-out queues
        live on the legacy Base, which only exists once the app has started,
        so makeActionApp's startup hook constructs the bridge and binds it
        here (mirror of the P2b-1 NativeArtifactStoreAdapter.bind_base
        pattern)."""
        self._publish_bridge = bridge
```

(d) Replace the three deferred methods (lines 130-137):

```python
    async def publish_status(self, payload: dict) -> None:
        raise HexagonDeferred("WS publish bridge is P1b2 (DD-7)")

    async def publish_data(self, payload: dict) -> None:
        raise HexagonDeferred("WS publish bridge is P1b2 (DD-7)")

    async def publish_live(self, payload: dict) -> None:
        raise HexagonDeferred("WS publish bridge is P1b2 (DD-7)")
```

with:

```python
    async def publish_status(self, payload: dict) -> None:
        if self._publish_bridge is None:
            raise UnwiredPortError(
                "publish_status before bind_publish_bridge (bound at "
                "makeActionApp startup; orch compositions stay on legacy WS)"
            )
        await self._publish_bridge.publish_status(payload)

    async def publish_data(self, payload: dict) -> None:
        if self._publish_bridge is None:
            raise UnwiredPortError(
                "publish_data before bind_publish_bridge (bound at "
                "makeActionApp startup; orch compositions stay on legacy WS)"
            )
        await self._publish_bridge.publish_data(payload)

    async def publish_live(self, payload: dict) -> None:
        if self._publish_bridge is None:
            raise UnwiredPortError(
                "publish_live before bind_publish_bridge (bound at "
                "makeActionApp startup; orch compositions stay on legacy WS)"
            )
        await self._publish_bridge.publish_live(payload)
```

(`Optional` is already imported at line 44; do not touch the port file.)

- [ ] **Step 5: Implement the startup bind in `helao/hexagon/app/factory.py`**

Three exact edits (do NOT touch `makeOrchApp` — D3):

(a) Replace the import at line 16:

```python
from helao.hexagon.adapters.errors import HexagonDeferred
```

with:

```python
from helao.hexagon.adapters.errors import HexagonDeferred, UnwiredPortError
```

(b) After line 25 (`from helao.hexagon.adapters.native.data_sink import NativeDataSinkAdapter`), add:

```python
from helao.hexagon.adapters.native.ws_publish import WsPublishBridge
```

(c) In `makeActionApp`, replace:

```python
    app.hexagon_wiring = wiring
    app.hexagon_active_graft = None

    # Registered AFTER the legacy BaseAPI's own startup handler (which sets
    # self.base = Base(app=self, ...), base_api.py:646; Starlette preserves
    # registration order): the graft sees the live app.base and rebinds
    # contain_action + meta_writer before any action can be contained.
    @app.on_event("startup")
    async def _hexagon_active_graft_startup():
        app.hexagon_active_graft = graft_active_write_path(app.base, wiring)
```

with:

```python
    app.hexagon_wiring = wiring
    app.hexagon_active_graft = None
    app.hexagon_ws_bridge = None

    # Registered AFTER the legacy BaseAPI's own startup handler (which sets
    # self.base = Base(app=self, ...), base_api.py:646; Starlette preserves
    # registration order): the graft sees the live app.base and rebinds
    # contain_action + meta_writer before any action can be contained.
    @app.on_event("startup")
    async def _hexagon_active_graft_startup():
        app.hexagon_active_graft = graft_active_write_path(app.base, wiring)
        # P2b-2 (D3): the WS publish bridge needs the live Base's fan-out
        # queues — construct and bind it now, ACTION apps only (orch WS
        # stays on legacy relays, Q1: makeOrchApp never binds).
        if not isinstance(wiring.status, DispatcherStatusAdapter):
            raise UnwiredPortError(
                "WS publish bridge requires DispatcherStatusAdapter status wiring"
            )
        bridge = WsPublishBridge(
            app.base.status_q, app.base.data_q, app.base.live_q
        )
        wiring.status.bind_publish_bridge(bridge)
        app.hexagon_ws_bridge = bridge
```

(`DispatcherStatusAdapter` is already imported at line 22; the isinstance check is the fail-loud F2b guard AND narrows `Optional[StatusPort]` for pyright.)

- [ ] **Step 6: Run the Task 2 test files to verify they pass**

```bash
conda run -n helao python -m pytest helao/hexagon/tests/test_adapters_misc.py helao/hexagon/tests/test_factory.py helao/hexagon/tests/test_ws_publish_bridge.py -v
```

Expected: all PASS, 0 failed.

- [ ] **Step 7: Verify the HexagonDeferred discharge (honesty grep)**

```bash
! grep -q HexagonDeferred helao/hexagon/adapters/legacy/status.py && echo CLEAN
```

Expected output: `CLEAN`

- [ ] **Step 8: Run the full hexagon suite + pyright**

```bash
conda run -n helao python -m pytest helao/hexagon -q
conda run -n helao pyright helao/hexagon
```

Expected: pytest — all pass, 0 failed (the suite includes the boundary tests; `status.py` importing `adapters.native.ws_publish` is adapters-layer→adapters-layer, allowed). pyright — `0 errors, 0 warnings, 0 informations`.

- [ ] **Step 9: Format and commit**

```bash
conda run -n helao black helao/hexagon/adapters/legacy/status.py helao/hexagon/app/factory.py helao/hexagon/tests/test_adapters_misc.py helao/hexagon/tests/test_factory.py helao/hexagon/adapters/native/ws_publish.py
git add helao/hexagon/adapters/legacy/status.py helao/hexagon/app/factory.py helao/hexagon/tests/test_adapters_misc.py helao/hexagon/tests/test_factory.py
git commit -m "feat(hexagon): bind WsPublishBridge into DispatcherStatusAdapter at makeActionApp startup (P2b-2 T2, DD-7 discharged)"
```

Expected: commit created. If black reformatted anything, re-run Step 6 and Step 8 before committing.

---

### Task 3: Verification sweep + LAUNCHED gate evidence (controller-run)

**Files:**
- Modify: `docs/superpowers/plans/2026-07-18-P2b2-ws-publish-bridge.md` (this file — record gate evidence in the block below; NO code files)

**Interfaces:**
- Consumes: everything from Tasks 1-2; the P1b2a parity harness `helao/hexagon/tests/smoke/parity_run.sh` and the goldenhex config family (read its header for invocation — it is re-used verbatim, never modified).
- Produces: recorded gate evidence only.

> **IMPORTANT — execution routing:** Steps 1-4 are subagent-runnable checks. Steps 5-6 (the LAUNCHED gate) are **controller-run in the MAIN SESSION, foreground** — they launch a live server group; do NOT dispatch them to a subagent.

- [ ] **Step 1: Full hexagon suite**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
conda run -n helao python -m pytest helao/hexagon -q
```

Expected: all pass, 0 failed, 0 errors (record the pass count).

- [ ] **Step 2: pyright + black + boundary**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black --check helao/hexagon
conda run -n helao python -m pytest helao/hexagon/tests/test_boundaries.py -q
```

Expected: pyright `0 errors, 0 warnings, 0 informations`; black `All done! ... files would be left unchanged.` (the 4 re-bodies are force-excluded and never checked); boundary tests all pass.

- [ ] **Step 3: Zero-legacy proof**

```bash
git diff --stat unstable -- helao/core helao/helpers helao/deploy
```

Expected: EMPTY output (no legacy file touched). Also confirm the full branch surface:

```bash
git diff --stat unstable
```

Expected: only `helao/hexagon/**`, `pyproject.toml`, and this plan file appear.

- [ ] **Step 4: Discharge greps (honesty)**

```bash
! grep -q HexagonDeferred helao/hexagon/adapters/legacy/status.py && echo CLEAN
grep -rn "publish_status\|publish_data\|publish_live" helao/hexagon/adapters/legacy/status.py | grep -c "raise HexagonDeferred"
```

Expected: `CLEAN`, then `0` (the second grep exits 1 with count 0 — that is the pass condition).

- [ ] **Step 5 (CONTROLLER, MAIN SESSION, foreground): GM-1 parity re-run on the goldenhex composition**

Adapter changes must carry a parity-guard re-run (P1b2b-T6 precedent). Run the GM-1 scenario of `helao/hexagon/tests/smoke/parity_run.sh` (invocation per the script's own header — the harness is re-used verbatim) against the existing legacy goldens.

Expected: **0 diffs**. The WS bridge is a new producer surface (no hexagon code previously put onto status_q/data_q/live_q, so no double-publish) and does not touch on-disk artifacts — any diff is a regression; STOP and debug before proceeding.

- [ ] **Step 6 (CONTROLLER, MAIN SESSION, foreground, BEST-EFFORT per D5): launched WS frame check**

During a GM-1 run on the goldenhex group, attach a REAL `WsSubscriber` (`helao.helpers.ws_utils.WsSubscriber`) to the action server's `/ws_data` route and assert ≥1 decoded frame is a `DataPackageModel` with the expected `action_uuid`/`datamodel` shape (certifies the native write path's data_q traffic serializes wire-correctly end-to-end — on-disk GM parity does not exercise the WS encode path). Per D5: if a launched WS subscribe proves too flaky/heavy to script reliably, the Task 1 unit round-trip + GM-1 0-diff + the honesty grep already cover wire-encode + native traffic — mark this step best-effort and record exactly what ran.

- [ ] **Step 7: Record evidence and commit**

Fill in the evidence block below (suite pass count, pyright output, GM-1 run ID + diff count, launched-WS outcome or best-effort note), then:

```bash
git add docs/superpowers/plans/2026-07-18-P2b2-ws-publish-bridge.md
git commit -m "docs(hexagon): P2b-2 gate evidence (suite/pyright/black/boundary/GM-1/launched-WS)"
```

**Gate evidence (fill in at execution time):**

```
suite:        <N> passed, 0 failed (command + date)
pyright:      0 errors, 0 warnings
black:        clean (force-exclude narrowed, 4 re-bodies protected)
boundary:     pass
zero-legacy:  git diff --stat unstable -- helao/core helao/helpers helao/deploy -> empty
GM-1 parity:  run id <...>, 0 diffs
launched WS:  <DataPackageModel frame observed on /ws_data during run <...>>
              OR <best-effort skipped: unit round-trip + GM-1 + grep cover, per D5>
```

---

## Self-review record (plan author)

- **Spec coverage:** D1 → Task 1 Step 4 + both round-trip tests + Task 2 bound-path test. D2 → Task 1 Steps 8-11. D3 → Task 2 Steps 2/5 (action-only, makeOrchApp untouched). D4 → Global Constraints + Task 3 Step 3. D5 → Task 1 real-encoder test, Task 2 unbound/updated tests + grep, Task 3 Steps 1-6. D6 → nothing in this plan touches `_ws_relay`, route hosting, LiveBuffer, or `_json_clean`.
- **Placeholder scan:** no TBDs; every code step carries complete code; the only intentionally open item is the `parity_run.sh` invocation (harness re-used verbatim, controller-run — its own header is authoritative).
- **Type consistency:** `WsPublishBridge(status_q, data_q, live_q)` / `_status_q`/`_data_q`/`_live_q` / `bind_publish_bridge` / `_publish_bridge` / `app.hexagon_ws_bridge` used identically across Tasks 1-3.
