# Framework SP-ORCH-4 Status Heartbeat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate `OrchState.status_summary` from a background heartbeat that dispatches `get_status` to each configured action server via the transport port. Pure parse/filter helpers in `domain/orchestration.py`; the dispatch loop + `OrchPorts.action_servers` + FastAPI startup wiring in `app/orch_api.py`.

**Architecture:** Two pure domain helpers (`pingable_servers`, `parse_status_response`) + an `OrchDriver` heartbeat (`_heartbeat_once`/`_heartbeat_loop`/`start_heartbeat`/`stop_heartbeat`) reading an optional `OrchPorts.action_servers` map, wired to FastAPI `startup`/`shutdown`. Empty `action_servers` ⇒ heartbeat no-op (so existing tests/in-process runners are unaffected).

**Tech Stack:** Python 3.12 (conda env `helao`), FastAPI + `TestClient`, the framework `Transport` port (`FakeTransport` for tests), `pytest`.

## Global Constraints

- Run pytest via the `helao` conda env: `conda run -n helao python -m pytest <path> -v`.
- Pure addition: do NOT modify `helao/core/**` or `helao/deploy/**`.
- `domain/orchestration.py` stays pure (the two helpers take plain dicts; no I/O). AST boundary check must stay green.
- `app/orch_api.py` already imports `DispatchTarget`, `Transport` (line 60) and `ErrorCodes` (line 35). Ensure `import asyncio` is present at module top (add if missing).
- Heartbeat is a no-op when `action_servers` is empty (default) — must not start a task or change behavior for the existing orch tests.
- Add new public domain helpers to the module `__all__`.

---

### Task 1: pure domain helpers (`pingable_servers`, `parse_status_response`)

**Files:**
- Modify: `helao/framework/domain/orchestration.py`
- Test: `helao/framework/tests/test_domain_orch_heartbeat.py`

**Interfaces:**
- Produces (module-level, in `__all__`): `pingable_servers(servers_cfg: dict) -> list[tuple[str, str, int]]`; `parse_status_response(response, error_ok: bool) -> tuple[str, str]`.

- [ ] **Step 1: Write the failing test**

```python
# helao/framework/tests/test_domain_orch_heartbeat.py
"""Pure orchestrator status-heartbeat helpers."""
from helao.framework.domain import orchestration as orch


def test_pingable_servers_skip_rules():
    cfg = {
        "MOTOR": {"host": "h1", "port": 1},
        "PSTAT": {"host": "h2", "port": 2, "params": {}},
        "DB": {"host": "h", "port": 3},                       # skip DB
        "ANA": {"host": "h", "port": 4},                      # skip ANA
        "VIS": {"host": "h", "port": 5, "bokeh": "x"},        # skip bokeh UI
        "LIVE": {"host": "h", "port": 6, "demovis": "y"},     # skip demovis UI
        "QUIET": {"host": "h", "port": 7, "params": {"ignore_heartbeats": True}},
    }
    out = orch.pingable_servers(cfg)
    assert sorted(out) == [("MOTOR", "h1", 1), ("PSTAT", "h2", 2)]


def test_parse_status_response_idle():
    resp = {"_driver_status": "ok", "endpoints": {"run": {"active_dict": {}}}}
    assert orch.parse_status_response(resp, True) == ("idle", "ok")


def test_parse_status_response_busy():
    resp = {"_driver_status": "ok",
            "endpoints": {"run": {"active_dict": {"a": 1}}, "idleep": {"active_dict": {}}}}
    status, driver = orch.parse_status_response(resp, True)
    assert status == "busy [run]"
    assert driver == "ok"


def test_parse_status_response_missing_driver_status():
    resp = {"endpoints": {}}
    assert orch.parse_status_response(resp, True) == ("idle", "unknown")


def test_parse_status_response_unreachable():
    assert orch.parse_status_response(None, True) == ("unreachable", "unknown")
    assert orch.parse_status_response({"_driver_status": "ok"}, False) == ("unreachable", "unknown")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_domain_orch_heartbeat.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'pingable_servers'`

- [ ] **Step 3: Write minimal implementation**

Add to `helao/framework/domain/orchestration.py` (with the other status helpers):

```python
def pingable_servers(servers_cfg: dict) -> list:
    """Return (server_key, host, port) for each pingable action server.

    Mirrors the legacy ping_action_servers filter: skip DB/ANA, skip entries with
    ``params.ignore_heartbeats``, and skip UI servers (a ``bokeh``/``demovis`` key).
    """
    out = []
    for server_key, cfg in (servers_cfg or {}).items():
        if server_key in ("DB", "ANA"):
            continue
        if not isinstance(cfg, dict):
            continue
        if (cfg.get("params") or {}).get("ignore_heartbeats"):
            continue
        if "bokeh" in cfg or "demovis" in cfg:
            continue
        host = cfg.get("host")
        port = cfg.get("port")
        if host is None or port is None:
            continue
        out.append((server_key, host, port))
    return out


def parse_status_response(response, error_ok: bool) -> tuple:
    """Parse a get_status response into (status_str, driver_status).

    ``("unreachable", "unknown")`` when ``error_ok`` is False or ``response`` is
    None. Otherwise ``driver_status = response["_driver_status"]`` (default
    ``"unknown"``) and ``status_str`` is ``"busy [<eps>]"`` for endpoints whose
    ``active_dict`` is truthy, else ``"idle"``. Mirrors legacy ping parsing.
    """
    if not error_ok or response is None:
        return ("unreachable", "unknown")
    driver_status = response.get("_driver_status", "unknown")
    busy = [
        name
        for name, ep in (response.get("endpoints") or {}).items()
        if ep.get("active_dict")
    ]
    status_str = f"busy [{', '.join(busy)}]" if busy else "idle"
    return (status_str, driver_status)
```

Add `pingable_servers` and `parse_status_response` to the module `__all__`.

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_domain_orch_heartbeat.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add helao/framework/domain/orchestration.py helao/framework/tests/test_domain_orch_heartbeat.py
git commit -m "feat(framework): SP-ORCH-4 — pure status-heartbeat helpers (pingable_servers/parse_status_response)"
```

---

### Task 2: `OrchPorts.action_servers` + `OrchDriver` heartbeat + wiring

**Files:**
- Modify: `helao/framework/app/orch_api.py` (`OrchPorts.__init__`; `OrchDriver`; `makeOrchApp` startup/shutdown)
- Modify: `helao/framework/app/factory.py` (`makeOrchestratorApp` `action_servers` kwarg)
- Test: `helao/framework/tests/test_app_orch_heartbeat.py`

**Interfaces:**
- Consumes: `orch.pingable_servers`/`orch.parse_status_response` (Task 1); `DispatchTarget`, `Transport.dispatch -> DispatchResult(response, error)`, `ErrorCodes` (already imported in `orch_api.py`).
- Produces: `OrchPorts(..., action_servers=None)` (stored as `self.action_servers: dict`); `OrchDriver._heartbeat_once()`, `OrchDriver._heartbeat_loop()`, `OrchDriver.start_heartbeat()`, `OrchDriver.stop_heartbeat()`, `OrchDriver.heartbeat_interval`; `makeOrchestratorApp(..., action_servers=None)`.

- [ ] **Step 1: Write the failing test**

```python
# helao/framework/tests/test_app_orch_heartbeat.py
"""Orchestrator status heartbeat (transport dispatch -> status_summary)."""
import asyncio

from helao.framework.adapters.fakes.transport import FakeTransport
from helao.framework.app.factory import makeApp
from helao.framework.models.errors import ErrorCodes
from helao.framework.ports.transport import DispatchResult


def _app(tmp_path, transport, action_servers):
    return makeApp("ORCH", save_root=str(tmp_path), group="orchestrator",
                   transport=transport, action_servers=action_servers)


def test_heartbeat_once_populates_status_summary(tmp_path):
    transport = FakeTransport()
    transport.script_by_endpoint["get_status"] = DispatchResult(
        response={"_driver_status": "ok",
                  "endpoints": {"run": {"active_dict": {"a": 1}}}},
        error=ErrorCodes.none,
    )
    app = _app(tmp_path, transport, {"MOTOR": {"host": "h", "port": 1}})
    driver = app.state.driver
    asyncio.run(driver._heartbeat_once())
    assert driver.state.status_summary["MOTOR"] == ("busy [run]", "ok")


def test_heartbeat_once_unreachable(tmp_path):
    transport = FakeTransport()
    transport.script_by_endpoint["get_status"] = DispatchResult(
        response=None, error=ErrorCodes.http,
    )
    app = _app(tmp_path, transport, {"MOTOR": {"host": "h", "port": 1}})
    driver = app.state.driver
    asyncio.run(driver._heartbeat_once())
    assert driver.state.status_summary["MOTOR"] == ("unreachable", "unknown")


def test_start_heartbeat_noop_when_no_servers(tmp_path):
    app = _app(tmp_path, FakeTransport(), {})
    driver = app.state.driver
    driver.start_heartbeat()
    assert getattr(driver, "_heartbeat_task", None) is None
    driver.stop_heartbeat()  # idempotent, no error


def test_get_status_summary_endpoint_reflects_heartbeat(tmp_path):
    from fastapi.testclient import TestClient
    transport = FakeTransport()
    transport.script_by_endpoint["get_status"] = DispatchResult(
        response={"_driver_status": "ok", "endpoints": {}}, error=ErrorCodes.none,
    )
    app = _app(tmp_path, transport, {"MOTOR": {"host": "h", "port": 1}})
    driver = app.state.driver
    asyncio.run(driver._heartbeat_once())
    client = TestClient(app)
    assert client.post("/get_status_summary").json() == {"MOTOR": ["idle", "ok"]}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_orch_heartbeat.py -v`
Expected: FAIL — `makeApp(... action_servers=...)` unexpected kwarg, or `driver._heartbeat_once` missing.

- [ ] **Step 3: Write minimal implementation**

(a) `helao/framework/app/orch_api.py` — ensure `import asyncio` at module top. In `OrchPorts.__init__`, add the param + storage:

```python
        action_servers: Optional[Mapping[str, dict]] = None,
```
and in the body:
```python
        self.action_servers: dict = dict(action_servers or {})
```
(Update the `OrchPorts` docstring's attribute list to mention `action_servers`.)

In `OrchDriver.__init__`, after `self.state = ...`, add:

```python
        self.action_servers = dict(getattr(ports, "action_servers", {}) or {})
        self.heartbeat_interval = 5.0
        self._heartbeat_task = None
```

Add these methods to `OrchDriver` (near the control surface):

```python
    async def _heartbeat_once(self) -> None:
        """One ping pass: dispatch get_status to each pingable server, fold into status_summary."""
        for server_key, host, port in orch.pingable_servers(self.action_servers):
            target = DispatchTarget(
                server_key=server_key, host=host, port=port, endpoint="get_status"
            )
            result = await self.ports.transport.dispatch(
                target, {"client_servkey": self.server_key}
            )
            self.state.status_summary[server_key] = orch.parse_status_response(
                result.response, result.error == ErrorCodes.none
            )

    async def _heartbeat_loop(self) -> None:
        """Refresh status_summary every heartbeat_interval until cancelled."""
        while True:
            try:
                await self._heartbeat_once()
            except Exception as exc:  # a transient ping failure must not kill the loop
                LOGGER.warning(f"heartbeat pass failed: {exc!r}")
            await asyncio.sleep(self.heartbeat_interval)

    def start_heartbeat(self) -> None:
        """Start the background heartbeat task (no-op if no servers / already running)."""
        if not self.action_servers:
            return
        if self._heartbeat_task is not None and not self._heartbeat_task.done():
            return
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    def stop_heartbeat(self) -> None:
        """Cancel the heartbeat task if running (idempotent)."""
        task = self._heartbeat_task
        if task is not None and not task.done():
            task.cancel()
        self._heartbeat_task = None
```

In `makeOrchApp`, after building `driver`, register startup/shutdown:

```python
    @app.on_event("startup")
    async def _start_heartbeat() -> None:
        driver.start_heartbeat()

    @app.on_event("shutdown")
    async def _stop_heartbeat() -> None:
        driver.stop_heartbeat()
```

(b) `helao/framework/app/factory.py` — add `action_servers=None` to `makeOrchestratorApp`'s signature and pass it into the `OrchPorts(...)` constructor. Also thread it through `makeApp`'s orchestrator branch (the `group == "orchestrator"` path) so `makeApp("ORCH", group="orchestrator", action_servers=...)` works. Add the kwarg with a default of `None` to both functions and forward it.

> Use `DispatchTarget(server_key=..., host=..., port=..., endpoint="get_status")` —
> the existing `_dispatch_target_for` shows the same constructor. The heartbeat sends
> a minimal payload; the action server's `get_status` ignores unknown kwargs. `LOGGER`
> is already defined in `orch_api.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_orch_heartbeat.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add helao/framework/app/orch_api.py helao/framework/app/factory.py helao/framework/tests/test_app_orch_heartbeat.py
git commit -m "feat(framework): SP-ORCH-4 — OrchDriver status heartbeat + action_servers wiring"
```

---

### Task 3: Full-suite + boundary verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full framework test suite**

Run: `conda run -n helao python -m pytest helao/framework/tests/ -p no:cacheprovider -q 2>&1 | tail -1`
Expected: all pass (new + pre-existing), no regressions. (Existing orch tests build apps with no `action_servers` → heartbeat no-op, unaffected.)

- [ ] **Step 2: Confirm the AST boundary check is green**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_boundaries.py -v`
Expected: PASS. `domain/orchestration.py` helpers are pure (plain dict in / tuple out); the dispatch loop lives in `app/`.

- [ ] **Step 3: Confirm pure-addition (no legacy/deploy edits)**

Run: `git diff --name-only feat/framework-scaffold...HEAD | grep -E "helao/(core|deploy)/" || echo "NONE (clean)"`
Expected: `NONE (clean)`.

- [ ] **Step 4: Commit (only if verification fixups were needed)**

```bash
git add -A
git commit -m "test(framework): SP-ORCH-4 — verify full suite + boundary green"
```

---

## Self-Review

**Spec coverage:**
- §4.1 pure helpers `pingable_servers`/`parse_status_response` → Task 1. ✓
- §4.2 `OrchPorts.action_servers` + factory kwarg → Task 2 (a)/(b). ✓
- §4.3 `OrchDriver` heartbeat (`_heartbeat_once`/`_loop`/`start`/`stop`) → Task 2. ✓
- §4.4 startup/shutdown wiring → Task 2. ✓
- §6 error handling (unreachable parse, loop survives exception, empty=no-op) → tests in Tasks 1/2. ✓
- §7 test strategy (filter/parse units, heartbeat-once via FakeTransport, no-op-on-empty, endpoint reflects heartbeat) → Tasks 1-2. ✓
- §3 boundary purity → Task 3 Steps 2-3. ✓

**Placeholder scan:** No TBD/TODO. Full helper + driver + test code. Guarded notes (DispatchTarget ctor, LOGGER availability) are concrete instructions.

**Type consistency:** `pingable_servers(dict) -> list[tuple[str,str,int]]` and `parse_status_response(response, error_ok) -> tuple[str,str]` defined Task 1, consumed by `_heartbeat_once` Task 2. `OrchPorts.action_servers` set Task 2(a), read by `OrchDriver.__init__` Task 2, threaded by factory Task 2(b). `result.error == ErrorCodes.none` matches `DispatchResult.error`. `status_summary[key]` tuple feeds SP-ORCH-1 `status_summary_payload` (list-coerced) — the endpoint test asserts the `[idle, ok]` JSON shape.
