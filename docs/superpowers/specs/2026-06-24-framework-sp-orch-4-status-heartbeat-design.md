# Framework SP-ORCH-4 — Orchestrator Status Heartbeat (design)

**Date:** 2026-06-24
**Branch:** `feat/framework-orch-heartbeat`
**Cycle:** Framework-orch endpoint completion — deferred follow-up (status_summary population).

## 1. Context

SP-ORCH-1 added an empty `status_summary` field on `OrchState` + a pure
`status_summary_payload` serializer; the `/get_status_summary` endpoint (SP-ORCH-2)
serves it. Population was deferred because the legacy source is a **network ping
heartbeat**. This sub-project adds that heartbeat so the operator's
status-summary panel shows live per-server status.

Legacy (`helao/core/servers/orch.py`):
- `ping_action_servers()` — for each `world_cfg["servers"]` entry, skipping `DB`/`ANA`,
  entries with `params.ignore_heartbeats`, and `bokeh`/`demovis` (UI) servers,
  dispatch `get_status` via `async_private_dispatcher`; parse the response into
  `(status_str, driver_status)` where `status_str` is `"idle"`, `"busy [<eps>]"`, or
  `"unreachable"`, and `driver_status` is `response["_driver_status"]` (default
  `"unknown"`). Busy endpoints are those whose `endpoints[name]["active_dict"]` is truthy.
- `action_server_monitor()` — `while True: status_summary = await ping_action_servers(); await asyncio.sleep(heartbeat_interval)`.

**Framework gap:** `OrchPorts` has no action-server list/config — the framework orch
dispatches per-action (each action carries its target) and never holds a global
server list. The heartbeat must be given the list of pingable servers. The framework
`Transport` port already provides `dispatch(target, payload) -> DispatchResult` (full
response + classified error), which is exactly what `get_status` needs.

## 2. Goal & non-goals

**Goal:** Populate `OrchState.status_summary` from a background heartbeat that
dispatches `get_status` to each configured action server via the transport port,
parsing responses into `(status_str, driver_status)`. Pure parse/filter logic in
`domain/`; the dispatch + loop + startup wiring in `app/`.

**Non-goals:**
- Changing the dispatch FSM, the HTTP endpoints (SP-ORCH-2), or the status WS (SP-ORCH-3).
- A new transport technology — reuse the existing `Transport.dispatch`.
- Deployment cut-over (passing the real server list from a deployment config is the
  deployment-migration cycle; SP-ORCH-4 plumbs the list through and ships it empty by
  default so the heartbeat is a no-op until a deployment supplies servers).
- Legacy `core/**` changes.

## 3. Boundary contract

- `domain/orchestration.py` stays pure: the two new helpers (`pingable_servers`,
  `parse_status_response`) take plain dicts and return plain values — no I/O.
- `app/orch_api.py` (app layer) owns the transport dispatch, the async loop, and the
  FastAPI startup/shutdown wiring.
- AST boundary check stays green.

## 4. Components

### 4.1 Pure domain helpers (`domain/orchestration.py`)

- `pingable_servers(servers_cfg: dict) -> list[tuple[str, str, int]]`
  Given a `world_cfg["servers"]`-shaped mapping (`server_key -> {host, port, params, bokeh?, demovis?}`),
  return `(server_key, host, port)` for each pingable server, applying the legacy
  skip rules: skip keys `DB`/`ANA`; skip entries with `params.ignore_heartbeats`;
  skip entries carrying a `bokeh` or `demovis` key (UI servers, no `get_status`).
- `parse_status_response(response: dict | None, error_ok: bool) -> tuple[str, str]`
  Parse a `get_status` response into `(status_str, driver_status)`:
  - `error_ok` False or `response` None → `("unreachable", "unknown")`.
  - else `driver_status = response.get("_driver_status", "unknown")`; collect
    endpoint names whose `endpoints[name]["active_dict"]` is truthy; `status_str =
    "busy [<comma-joined>]"` if any, else `"idle"`. Returns `(status_str, driver_status)`.
  Byte-parity with the legacy parsing block.

Add both to `__all__`.

### 4.2 `OrchPorts.action_servers` (`app/orch_api.py`)

Add an optional constructor field `action_servers: Optional[Mapping[str, dict]] = None`
to `OrchPorts` — a `world_cfg["servers"]`-shaped mapping the heartbeat pings. Stored
as `dict(action_servers or {})`. Empty by default (heartbeat no-op). Thread it through
`factory.makeOrchestratorApp` via a new `action_servers=None` kwarg.

### 4.3 `OrchDriver` heartbeat (`app/orch_api.py`)

- `__init__`: read `self.action_servers = dict(ports.action_servers or {})` (via the
  ports bundle) and `self.heartbeat_interval = 5.0` (constant; configurable later).
- `async def _heartbeat_once(self) -> None` — one ping pass:
  for each `(server_key, host, port)` in `pingable_servers(self.action_servers)`,
  `result = await self.ports.transport.dispatch(DispatchTarget(server_key, host, port, "get_status"), {"client_servkey": self.server_key})`,
  then `self.state.status_summary[server_key] = parse_status_response(result.response, result.error == ErrorCodes.none)`.
- `async def _heartbeat_loop(self) -> None` — `while True: await self._heartbeat_once(); await asyncio.sleep(self.heartbeat_interval)`. Wrap the body in a try/except that logs and continues (a transient ping failure must not kill the loop).
- `start_heartbeat()` / `stop_heartbeat()` — create/cancel the `asyncio.Task`; idempotent. No-op when `action_servers` is empty.

### 4.4 App startup/shutdown wiring (`makeOrchApp`)

Register `@app.on_event("startup")` to call `driver.start_heartbeat()` and
`@app.on_event("shutdown")` to call `driver.stop_heartbeat()` (matching the
`on_event` pattern base_api already uses). Startup must not block: `start_heartbeat`
only schedules a task (or no-ops on empty `action_servers`).

## 5. Data flow

```
app startup → driver.start_heartbeat() → _heartbeat_loop:
  pingable_servers(action_servers) → for each: transport.dispatch(get_status) → DispatchResult
    → parse_status_response → state.status_summary[server_key] = (status_str, driver_status)
  sleep(heartbeat_interval)
operator → POST /get_status_summary → status_summary_payload(state) → {server: [status, driver]}
```

## 6. Error handling (parity)

- Unreachable / non-`none` error / `None` response → `("unreachable", "unknown")`
  (parity with legacy's connect-error + non-success branches).
- A ping pass exception is caught in `_heartbeat_loop` so the loop survives; the
  affected server keeps its prior summary (or absent until first success).
- Empty `action_servers` → heartbeat never starts (no task, no dispatch).

## 7. Test strategy

Unit tests under `helao/framework/tests/`:

- `test_domain_orch_heartbeat.py` — `pingable_servers` skip rules (DB/ANA,
  ignore_heartbeats, bokeh/demovis dropped; normal kept with host/port);
  `parse_status_response` for idle / busy-with-endpoints / unreachable
  (None/error) / missing `_driver_status` → `"unknown"`. Reuse the legacy
  `test_endpoint_helpers_shapes`-style parity assertions.
- `test_app_orch_heartbeat.py` — build an `OrchDriver`/app via
  `makeApp("ORCH", group="orchestrator")` with a `FakeTransport` whose
  `script_by_endpoint["get_status"]` (or `queue_dispatch`) returns a canned
  `DispatchResult` with an `endpoints`/`_driver_status` body, and an
  `action_servers` map of one-or-two servers; call `await driver._heartbeat_once()`
  and assert `driver.state.status_summary` is populated with the parsed tuples;
  assert an error `DispatchResult` → `("unreachable", "unknown")`. Assert
  `start_heartbeat()` is a no-op when `action_servers` is empty (no task created).
- End-to-end-ish: after `_heartbeat_once`, `POST /get_status_summary` returns the
  populated summary (the SP-ORCH-2 endpoint over the heartbeat-populated field).

Full framework suite + AST boundary check stay green.

## 8. API parity

`status_summary` values are `(status_str, driver_status)` tuples exactly as legacy,
so `status_summary_payload` (SP-ORCH-1) and the operator's `get_status_summary`
consumer see the same `{server: [status_str, driver_status]}` shape. The skip rules
and `"idle"`/`"busy [<eps>]"`/`"unreachable"` strings match legacy.

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| `OrchPorts` has no server list | Add `action_servers` field + factory kwarg; empty default = no-op |
| Heartbeat loop dies on a transient error | try/except around the pass body; loop continues |
| `get_status` response shape differs from legacy | `parse_status_response` mirrors the legacy parse; tested with a canned legacy-shaped body |
| Startup task blocks app boot | `start_heartbeat` only schedules a task / no-ops on empty config |
| Heartbeat task leak on shutdown | `@app.on_event("shutdown")` cancels it; `stop_heartbeat` idempotent |

## 10. Done criteria

- `pingable_servers` + `parse_status_response` pure helpers in
  `domain/orchestration.py`; `OrchPorts.action_servers` + `OrchDriver` heartbeat
  (`_heartbeat_once`/`_heartbeat_loop`/`start_heartbeat`/`stop_heartbeat`) + startup
  wiring in `app/orch_api.py`; factory `action_servers` kwarg.
- Unit + app tests pass under the `helao` env; full framework suite green; AST
  boundary check green; domain stays pure.
- No legacy `core/**` or `deploy/**` modified.
- `status_summary` is now populated when a server list is supplied; the operator's
  status panel works. (Remaining: deployment supplies the real `action_servers` list
  at cut-over.)
