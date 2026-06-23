# SP8 — Production Action-Server Wiring (design)

Date: 2026-06-23 · Branch: `feat/framework-scaffold` (continues PR #176) · Model for spec: Opus

## 1. Why

SP7 migrated the `test` deployment's import paths onto `helao.framework.*` and proved
`makeApp` + adapters + sim driver can run one action via an in-process ASGI test.
But running the migrated action servers under the **real (legacy) orchestrator** on
hardware exposed that the framework `FrameworkBase`/`BaseAPI` is a deliberate subset
of the legacy `Base`/`BaseAPI`. The pieces that production needs were stamped "added
in the full production wiring (a later SP)". SP8 is that SP.

Two grounding gap maps (this session, investigators) enumerate the full delta. This
spec scopes SP8 to **the minimum that makes the migrated `test` deployment run
end-to-end live under the existing orchestrator**, plus driver-contract conformance.
True nice-to-haves are explicitly deferred (§7).

## 2. The critical path (why a run hangs today)

1. Orch startup calls each action server's private `attach_client(client_servkey,
   client_host, client_port)` (orch.py:318) to subscribe as a status client.
2. On every action state change the action server **POSTs a status package to the
   orch's `/update_status`** (legacy `Base.send_statuspackage` base.py:479, driven by
   `log_status_task` base.py:737).
3. Orch `update_status` (orch.py:448) folds it into `globalstatusmodel`; the dispatch
   loop only advances when it sees the dispatched action reach a terminal status.

The framework `attach_client` is a stub returning `True` and never registers the
client; nothing emits status to the orch. So the orch dispatches an action, the
action runs and finishes, but the orch never learns → the sequence stalls forever.
**Restoring this attach→emit→update_status loop is SP8's core.**

Note: orch↔action-server status is **HTTP push** (attach_client + update_status), not
the websockets. The `/ws_*` websockets feed the **visualizer** Bokeh apps (live plots).

## 3. Scope (workstreams)

### WS-A — Status model + orch status integration (CRITICAL)
- Add `ActionServerModel`/`EndpointModel` registry to `FrameworkBase`
  (`init_endpoint_status` over the app's action routes; `last_action_uuid`;
  `clear_finished`/status sort — port from base.py:272–326, 750–799).
- `status_clients` set; real `attach_client`/`detach_client`.
- `send_statuspackage`/`send_nbstatuspackage`: POST the status package to each
  registered client's `update_status`/`update_nonblocking` via the dispatcher
  (port base.py:479–548).
- Status emission on action lifecycle: when `ActionSession` status changes
  (active→finished/errored) the hosting base pushes to clients. Replace the legacy
  `status_q`+`log_status_task` background drain with a direct emit driven through the
  `EventSink` port + a base-level status hook. Keep `update_status` payload
  byte-compatible with what the orch expects (`ActionModel`-shaped).

### WS-B — WebSocket publishers + admin endpoints
- `/ws_status`, `/ws_data`, `/ws_live` routes backed by `QueueEventSink.subscribe()`
  (port the `_ws_relay`/`WsPublisher` pattern base.py:622–664, base_api.py:665–696).
- Real `/get_status` (dump `actionservermodel` + driver/poller status), `/get_config`,
  `/endpoints` (route introspection → `fast_urls`), `/get_lbuf`, `/list_executors`,
  `/stop_executor`, `/resend_active`, `/shutdown`.
- `estop` + generic `stop` action endpoints (base_api.py:208, 811).
- HEAD mirror for every POST (endpoint-availability `session.head()` checks).

### WS-C — Server identity, config, lifecycle
- `server` `MachineModel` with host/port/machine_name from `server_cfg`; `server_params`
  (= `server_cfg["params"]`); orch attach coords; per-server logger root from config.
- Startup hook: build base after loop exists; `myinit` background tasks (live-buffer +
  status); driver instantiation parity — `HelaoDriver` subclasses get `config=server_params`,
  bare drivers get `base`; optional `poller_class`. Shutdown hook: driver
  `shutdown`/`async_shutdown`.

### WS-D — Driver contract conformance (user request)
- Audit + migrate every `test` deployment driver to the framework `HelaoDriver`
  contract where it is a real driver; leave bare base-helper classes as-is but ensure
  framework compatibility. (Driven by the driver-audit investigator's report.)

### WS-E — Concurrency middleware + exception handler
- `app_entry` action-collision queue (base_api.py:383–483) and the
  estop-all-on-unhandled-error HTTP exception handler (base_api.py:486–512).

### WS-F — Finish/sync parity
- Whole-run-directory relocation at finish (`move_dir` RUNS_ACTIVE→synced, base.py:2218)
  so `HelaoSyncer` picks runs up. Confirm inline data-to-disk write parity.

## 4. Architecture constraints (unchanged)
- Hexagonal boundary holds: `domain/` imports only `models/` + `ports/` (AST boundary
  test stays green). New IO (websocket relay, HTTP status push, dir move) lives in
  `app/` and `adapters/`, never `domain/`.
- The status push to the orch goes through the existing dispatcher
  (`helao.framework.support.dispatcher`) — message-shaped, no new transport tech.
- Author-facing surface (deployment endpoint files) must not need edits beyond the
  SP7 import swap. Method names/semantics preserved.

## 5. Testing
- Unit tests per workstream (status model, attach/detach, send_statuspackage with a
  mocked dispatcher, ws relay, admin endpoints, driver conformance per driver).
- Integration: extend the WsSim golden-master to assert a status package is emitted to
  a registered client on finish.
- Gate: `run_framework_tests` (≥90% support cov, boundary 6/6) stays green.

## 6. Sequencing (waves)
- Wave 1 (parallel): WS-A status model+integration; WS-D driver conformance (independent).
- Wave 2 (parallel, after A): WS-B websockets+admin; WS-C identity/lifecycle; WS-F finish/sync.
- Wave 3: WS-E concurrency middleware; cross-cutting review + live smoke.
Each task: implement → self-review → framework gate. Reviews between waves.

## 7. Out of scope (deferred)
- aiodebug hang inspection; `DummyBase`; `action_version` envelope param + decorator.
- Debug/utility endpoints (`_raise_exception`, `test_alert`, `test_receive`).
- Operator/data_browser Bokeh UIs; production `hte` migration; deletion of old core.
- Changing wire protocol/transport tech.
