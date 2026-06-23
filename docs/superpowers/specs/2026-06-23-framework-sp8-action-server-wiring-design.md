# SP8 — Production Action-Server Wiring (design, refreshed)

**Date:** 2026-06-23 · **Branch:** `feat/framework-scaffold` (continues PR #176) · **Model for spec:** Opus
**Supersedes:** the discarded Sonnet-era SP8 spec (reachable at tag `sp6-sp8-sonnet-ref`). Structure
preserved; refreshed against the **actual SP7 end-state** (SP6 + SP7 redone on Opus, see §1).

---

## 1. Why & current state

SP7 migrated the in-tree `test` deployment onto `helao.framework.*` and proved **one
action server runs one action end-to-end in-process** (ASGI golden master, real
`.hlo`/`.act`). SP8 makes the migrated servers run **end-to-end live under the existing
orchestrator**, plus driver-contract conformance.

### What SP7 already delivered (do NOT re-build in SP8)
On `feat/framework-scaffold` through `fa1467f0`:
- `helao.framework.app.base_api`: `FrameworkBase` + legacy-named `Base`; `BaseAPI(HelaoFastAPI)`
  with `server_key`/`driver_classes`/`dyn_endpoints`, dual-convention driver instantiation
  (`HelaoDriver` → `config=server_params`; bare helper → positional `base`).
- `ACTION_CTX` ContextVar + `wrap_action_endpoint` request wrapper + `_build_action_from_kwargs`
  (folds extra kwargs into `action_params`).
- No-arg `setup_and_contain_action()` → `contain_action` → `ActionSession`; **default
  file-connection auto-open** (`file_conn_keys[0]`, empty header) so streaming executors
  write `.hlo` without an explicit `open_file`.
- `executors` registry; `put_lbuf`/`put_lbuf_nowait`/`get_lbuf` + `_live_buffer_task` drain;
  `myinit()` starts ONLY the live-buffer drain.
- `ActionSession.start_executor`, `.base` backref, `action_loop_task` + poll/cancel,
  `Executor.stop_action_task`; `open_file` closes a prior handle before reopening.
- `framework/support/{lib_decorators,file_utils,dispatcher}` ported. **Dispatcher non-2xx
  infinite-loop bug fixed** (increment `retry_count` on non-2xx; legacy has the same latent bug).
- Orchestrator side: `framework/app/orch_api.py` already owns `globalstatusmodel`
  (`server_dict`, status fold) from SP6/7. **SP8's status work is the ACTION-SERVER side.**

### The delta SP8 closes
`FrameworkBase`/`BaseAPI` deliberately omit (per their own docstring, base_api.py:582-587):
the orch `attach_client` → `/update_status` status push, the `/ws_*` publishers, the admin
endpoints, the `app_entry` collision middleware, the estop exception handler, full server
identity (`MachineModel`), driver lifecycle (startup/shutdown), and finish-time dir relocation.

---

## 2. The critical path (why a live run hangs today)

1. Orch startup calls each action server's private `attach_client(client_servkey, client_host,
   client_port)` to subscribe as a status client (legacy `Base.attach_client` base.py:550).
2. On every action state change the action server **POSTs a status package to the orch's
   `/update_status`** (legacy `Base.send_statuspackage` base.py:479, driven by `log_status_task`
   base.py:737).
3. Orch `update_status` (orch.py:448) folds it into `globalstatusmodel`; the dispatch loop
   only advances when the dispatched action reaches a terminal status.

The framework action server has **no** `attach_client` and emits **no** status to the orch. So
the orch dispatches, the action runs and finishes, but the orch never learns → the sequence
stalls forever. **Restoring attach → emit → update_status is SP8's core.**

Note: orch↔action-server status is **HTTP push** (attach_client + update_status), NOT websockets.
The `/ws_*` websockets feed the **visualizer** Bokeh apps (live plots) only.

---

## 3. Scope (workstreams)

### WS-A — Action-server status model + orch push (CRITICAL)
- `ActionServerModel`/`EndpointModel` registry on `FrameworkBase`: `init_endpoint_status`
  over the app's action routes, `last_action_uuid`, `clear_finished` + status sort
  (port base.py:272-326, 750-799). NB the [[known-bug-clear-in-finished]] dict-mutation
  bug was fixed in SP5 — keep that fix.
- `status_clients` set; real `attach_client`/`detach_client` private endpoints.
- `send_statuspackage`/`send_nbstatuspackage`: POST the `ActionModel`-shaped package to each
  registered client's `update_status`/`update_nonblocking` via `framework.support.dispatcher`
  (port base.py:479-548). Keep the payload byte-compatible with what orch expects.
- **Status emission hook:** replace the legacy `status_q` + `log_status_task` background drain
  with a direct emit driven through the `EventSink` port + a base-level status hook, so when an
  `ActionSession` status changes (active → finished/errored) the hosting base pushes to clients.

### WS-B — WebSocket publishers + admin endpoints
- `/ws_status`, `/ws_data`, `/ws_live` backed by `QueueEventSink.subscribe()` (port the
  `_ws_relay`/`WsPublisher` pattern).
- Real `/get_status` (dump `actionservermodel` + driver/poller status), `/get_config`,
  `/endpoints` (route introspection → `fast_urls`), `/get_lbuf`, `/list_executors`,
  `/stop_executor`, `/resend_active`, `/shutdown`.
- `estop` + generic `stop` action endpoints.
- HEAD mirror for every POST (the dispatcher's `endpoints_available` HEAD checks — already
  ported in SP7 and unit-tested).

### WS-C — Server identity, config, lifecycle
- `server` `MachineModel` (host/port/machine_name from `server_cfg`); `server_params`
  (`= server_cfg["params"]`, already on FrameworkBase); orch attach coords; per-server logger
  root from config.
- **Driver background-task lifecycle (carryover, confirmed via SP7 probing):** sim drivers start
  their poll loop in `__init__` via `asyncio.get_event_loop().create_task(...)` (e.g. `WsSim`),
  which is orphaned on a dead loop under in-process ASGI and never feeds the live buffer. SP8
  must start driver background tasks from a **base startup hook after the loop exists** (FastAPI
  `startup` event → `base.myinit` + driver-poller start), not from driver `__init__`. Decide:
  either (a) a `poller_class`/`DriverPoller` start in the startup hook, or (b) a thin
  `base.start_driver_tasks()` the startup hook calls. Prefer not editing the deploy driver files.
- Shutdown hook: driver `shutdown`/`async_shutdown`.

### WS-D — Driver contract conformance (user request)
- Audit + migrate every `test` deployment driver to the framework `HelaoDriver` contract where
  it is a real driver; leave bare base-helper classes as-is but ensure framework compatibility
  ([[sp8-drivers-bare-helpers]] — do NOT force the ABC onto bare helpers; dual-convention wiring
  already handles them).

### WS-E — Concurrency middleware + exception handler
- `app_entry` action-collision queue and the estop-all-on-unhandled-error HTTP exception handler.
- **Caveat (carryover):** WS-E `BaseHTTPMiddleware` was the suspected cause of a pytest hang in
  the Sonnet attempt — scrutinize the request body re-read vs status-drain interaction. Mirrors
  the dispatcher hang already fixed in SP7; add an explicit timeout-guarded test.

### WS-F — Finish/sync parity
- Whole-run-directory relocation at finish (`move_dir` RUNS_ACTIVE → synced, base.py:2218) so
  `HelaoSyncer` picks runs up. Confirm inline data-to-disk write parity.
- **hloheader stamping (carryover):** SP7's default file-conn auto-open writes an **empty**
  header. SP8 stamps the full `HloHeaderModel` (epoch_ns, action_name, column_headings from
  `json_data_keys`) — port base.py:1347-1542. This is what makes `.hlo` headers byte-match legacy.

### Carryover punch-list (found via SP7 in-process probing — fold into the waves above)
- `enqueue_data_dflt` on `ActionSession`: referenced by `gpsim_server`/`cpsim_server` (gpflow-gated,
  so not import-verified in SP7). Add it (default-file-conn convenience over `enqueue_data`). → WS-A/B.
- Orch-driven full action body: in-process tests must POST `{"action": {...}}`; under the live orch
  the orchestrator supplies it. No framework change needed — note for integration tests. → WS-A.

---

## 4. Architecture constraints (unchanged)
- Hexagonal boundary holds: `domain/` imports only `models/` + `ports/`; the AST boundary test
  (now **7 categories**) stays green. New IO (ws relay, HTTP status push, dir move) lives in
  `app/` + `adapters/`, never `domain/`.
- The status push to the orch goes through `helao.framework.support.dispatcher` — message-shaped,
  no new transport tech.
- Author-facing surface (deployment endpoint files) must not need edits beyond the SP7 import
  swap. Method names/semantics preserved. (The driver-lifecycle fix in WS-C must avoid editing the
  deploy driver files — keep it in the base/startup hook.)

## 5. Testing
- Unit tests per workstream: status model + `clear_finished`; `attach_client`/`detach_client`;
  `send_statuspackage` with a mocked dispatcher (assert POST shape to `/update_status`); ws relay;
  each admin endpoint; per-driver conformance; hloheader stamping byte-parity.
- Integration: extend the WsSim golden-master (`test_migrate_test_deploy.py` T3) to register a fake
  orch client and assert a status package is POSTed to it on finish; assert the `.hlo` header now
  byte-matches the legacy `HloHeaderModel` layout (tighten beyond SP7's structural check).
- A timeout-guarded test around WS-E middleware (regression guard for the suspected hang).
- Gate: `run_framework_tests` (≥90% on `domain/`+`models/`, boundary 7/7, all suites) stays green.
  Run via `conda run -n helao` ([[use-helao-conda-env-python]]).

## 6. Sequencing (waves)
- **Wave 1 (parallel):** WS-A status model + orch push (CRITICAL); WS-D driver conformance audit
  (independent, read-mostly).
- **Wave 2 (parallel, after A):** WS-B ws + admin endpoints; WS-C identity + driver lifecycle;
  WS-F finish/sync + hloheader stamping.
- **Wave 3:** WS-E concurrency middleware (+ hang regression guard); cross-cutting review; live
  smoke under the real orchestrator on the `test` deployment.
- Each task: implement → self-review → framework gate. Reviews between waves. Continue across waves
  without user checkpoint ([[framework-rewrite-standing-authorization]]); parallel subagents.

## 7. Out of scope (deferred)
- aiodebug hang inspection; `DummyBase`; `action_version` envelope param + decorator.
- Debug/utility endpoints (`_raise_exception`, `test_alert`, `test_receive`).
- Operator/data_browser Bokeh UIs; production `hte`/private-deployment migration; deletion of old
  `helao/core` + `helao/helpers`.
- Changing wire protocol / transport tech.

## 8. Live-core caveat (carry from SP6-SP8 redo)
If the Bokeh operator is exercised, re-apply the discarded `field_validator` on
`helao/core/models/sequence.py` (`git show sp6-sp8-sonnet-ref:helao/core/models/sequence.py`) —
it fixes a Pydantic-V2 add-sequence `ValidationError`. Independent of the framework work.
