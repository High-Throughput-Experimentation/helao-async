# HELAO Framework Core Rewrite — Design Spec

**Date:** 2026-06-22
**Status:** Approved (design); awaiting per-sub-project implementation plans
**Scope:** Clean-room rewrite of the deployment-agnostic framework (`helao/core` + `helao/helpers`) into a new parallel package `helao/framework/`. Deployment refactors are out of scope (future cycles).

---

## 1. Goal & context

HELAO-async is a distributed instrument-control system (~183k LOC, 507 Python files, 9 architectural layers) built from cooperating FastAPI and Bokeh servers. The deployment-agnostic framework lives in `helao/core/` (~25k LOC) and `helao/helpers/` (~9k LOC). It runs live lab hardware across 5 deployments (`hte`, `test`, plus the nested separate repos `lila`, `lila_gl`, `mea`, `priv`).

The framework has accumulated three structural problems that this rewrite targets directly:

- **God classes / tangled modules.** `Base` (2496 LOC, 46 methods, ~40 init attrs), `Orch` (2428 LOC, 72 methods, ~53 init attrs), `Active` (41 methods), `HelaoSyncer` (1933 LOC). Each mixes 4–7 unrelated responsibilities.
- **Unclear interfaces / coupling.** I/O (FastAPI, httpx, Bokeh, filesystem, NTP) is threaded directly through business logic. The domain model itself is split — `Action`/`Experiment`/`Sequence` live in `helao/helpers/premodels.py` while their pydantic bases live in `helao/core/models/`.
- **No tests / untestable.** No pytest harness; a handful of standalone scripts. Tight coupling to hardware/HTTP makes unit testing impractical.

The rewrite produces a framework structured "the way a software architect would" — reusable, maintainable, readable, and testable — while keeping the live system running throughout via a strangler-fig migration.

## 2. Locked decisions

| Decision | Choice | Rationale |
|---|---|---|
| Strategy | **Clean-room core rewrite first**, deployment refactors in later cycles | Highest-leverage foundation; everything imports it |
| First scope | **`helao/core` + `helao/helpers` framework** | Deployment-agnostic foundation |
| Architecture | **Layered hexagonal (Approach A), C-compatible** | Domain/ports/adapters split; pure logic, mockable I/O. Designed so a future event-driven core (Approach C) is an adapter swap + reducer refactor, not a rewrite |
| Coexistence | **New parallel package `helao/framework/`; old `helao/core`+`helpers` untouched** | Strangler-fig. Each deployment migrates atomically in its own cycle; old deleted only after the last leaves |
| Deployment migration | **Atomic per config group** (all-old or all-new, never mixed) | No cross-version wire compat needed between new-core and old-core servers |
| On-disk formats | **Byte-compatible** (HLO, parquet, `RUNS_*` trees) | Historical data + downstream analysis/syncer consume them |
| Generic utilities | **Vendored into `helao/framework/support/`** | New package fully self-contained; clean strangler boundary |
| Operator/data_browser UI | **Out of scope** (own later cycle) | Presentation, not framework |
| Test bar | **pytest + high coverage, hardware mocked** | Directly addresses the "no tests" pain |
| Branch discipline | **Every sub-project on its own branch off `unstable`; merge via PR**; nothing commits to `unstable`/`main` directly | User constraint |

### Approach A → C runway (do now, stop there)

To keep a future event-driven rewrite cheap without paying for it now:
1. Model domain operations as explicit **command/result value objects** (return what happened), not void side-effecting methods. An event bus later just serializes these.
2. Keep the `transport` port **message-shaped** (publish/handle named messages), not RPC-call-shaped, so an event adapter fits the same interface.

Do **not** build now: an actual event bus, event store, or pub/sub indirection. No second consumer exists yet.

## 3. Target package layout

```
helao/framework/
  domain/        # pure, zero I/O, high-coverage unit-testable
    action_lifecycle.py     # ex-Active state machine: split/finish/substitute
    orchestration.py        # ex-Orch: dispatch FSM, queue state, estop/skip — reducer-style step()
    status.py               # status aggregation/projection rules
    commands.py             # command + result value objects (the C-runway)
    sync/                   # ex-HelaoSyncer: pure walk/decide-what-to-sync logic
  models/        # pydantic: action, experiment, sequence, sample, data,
                 #   hlostatus, orchstatus, machine, file, process, analysis, ...
                 #   merges in the premodels runtime classes (unified domain model)
  ports/         # Protocols (abstract seams)
    transport.py            # message-shaped publish/handle (NOT rpc-shaped)
    storage.py              # write act/exp/seq/hlo, RUNS_* layout, read loaders
    clock.py                # NTP time
    eventsink.py            # status/data egress
    driver.py               # HelaoDriver / DriverPoller / DriverResponse / DriverStatus (near-verbatim)
  adapters/      # concrete impls of ports; may import I/O libs
    http_transport.py  bokeh_ws.py  fs_storage.py  ntp_clock.py
    s3_sync.py  loaders/  zmq_rpc.py  vis_subscriber.py
  app/           # thin wiring only — the ONLY layer FastAPI/Bokeh live in
    base_api.py  orch_api.py  vis.py  factory.py   # makeApp/makeBokehApp
  support/       # vendored generic utils: logging, yaml, config_loader,
                 #   dispatcher, time, codehash
  tests/         # pytest, mirrors structure; conftest with fake adapters
```

### Boundaries (the contract each unit honors)

- `domain/` imports only `models/` and `ports/`. **Never** FastAPI, httpx, filesystem, Bokeh, or `adapters/`.
- `adapters/` implement `ports/`, may import I/O libs. **Never** imported by `domain/`.
- `app/` wires domain + adapters + models into servers. The only layer where FastAPI/Bokeh live.
- The import rule is **enforced by a test** (AST check; see §7).

## 4. Component decomposition

### 4.1 `Base` → domain + ports + app

| Current responsibility (methods) | New home |
|---|---|
| action setup/containment (`setup_action`, `setup_and_contain_action`, `contain_action`, `_get_action`) | `domain/action_lifecycle.py` (pure), wired in `app/base_api.py` |
| meta/act/exp/seq file writing (`write_act`, `write_exp`, `write_seq`, `_write_meta_atomic`, `new_file_conn_key`) | `ports/storage.py` + `adapters/fs_storage.py` |
| status broadcast + WS relay (`ws_status`, `ws_data`, `ws_live`, `send_statuspackage`, `_ws_relay`, attach/detach) | `ports/eventsink.py` + `adapters/bokeh_ws.py`; aggregation in `domain/status.py` |
| live buffer (`put_lbuf`, `get_lbuf`, `live_buffer_task`, `_stamp_lbuf_dict`) | `domain/` buffer logic + `adapters` async task |
| endpoint queues + dispatch (`endpoint_queues_init`, `process_unified_queue`, `process_endpoint_queue`, `_dispatch_queued_action`) | `domain/` queue state machine; async runner in `app/` |
| NTP clock (`Timer`, time sync) | `ports/clock.py` + `adapters/ntp_clock.py` |

### 4.2 `Active` → `domain/action_lifecycle.py` + ports

The per-action context object. Its state machine (`split`, `substitute`, `finish`, `_finish`, `finish_all`, `split_and_keep_active`, sample append) becomes **pure domain logic returning command/result objects**. Its I/O (`write_file`, `enqueue_data`, `log_data_task`, `relocate_files`, `_resolve_output_path`) goes through the `storage`/`eventsink` ports. **Highest-value split** — hottest path, currently least testable.

### 4.3 `BaseAPI` → `app/base_api.py`

FastAPI-facing composition: builds domain objects, injects concrete adapters, registers endpoints. Thin. Public `makeApp(server_key)` factory lives in `app/factory.py`.

### 4.4 `Orch` → domain + ports + app

| Current responsibility (methods) | New home |
|---|---|
| dispatch decision logic (`loop_task_dispatch_*`, `dispatch_loop_task`, `wait_for_interrupt`, `orch_wait_for_all_actions`) | `domain/orchestration.py` — pure reducer-style `step(state, events) -> (new_state, commands)` |
| queue state (3 deques + uuid register/track) | `domain/orchestration.py` state struct |
| estop/stop/skip/clear control (`stop`, `intend_*`, `skip`, `clear_*`, `estop_actions`, `estop_loop`) | `domain/orchestration.py` transitions; thin async wrappers in `app/orch_api.py` |
| remote status intake (`update_status`, `update_nonblocking`, `clear_nonblocking`, `subscribe_all`) | `ports/transport.py` feeding `domain/status.py` |
| globstat WS broadcast (`ws_globstat`, `globstat_broadcast_task`) | `ports/eventsink.py` + `adapters/bokeh_ws.py` |
| sequence unpack + codehash (`unpack_sequence`, `seq_unpacker`, `get_sequence_codehash`, `verify_plate_in_params`) | `domain/` (pure unpack) + `support/` (codehash hashing) |
| run-id/meta prep (`_prep_sequence_meta`, `_ensure_run_id`) | `domain/` + `storage` port |
| dispatch transport (HTTP to action servers) | `adapters/http_transport.py` |

**Dispatch loop:** `app/orch_api.py` runs an async driver loop — read incoming status (transport port) → `domain.orchestration.step(...)` → execute returned commands via ports. Pure FSM in the middle, I/O at the edges. C later swaps the transport adapter for an event bus; `step` barely changes.

### 4.5 Models

Port pydantic models into `models/`, **merging the `premodels` runtime classes** so the domain model is unified. Kill the `core/models` vs `helpers/premodels` split, tighten validation, drop dead fields. `unit_test_sample_models` / `unit_test_extra_models` port to pytest as the seed suite.

### 4.6 Driver contract

`helao_driver.py`'s `HelaoDriver`/`DriverPoller`/`DriverResponse`/`DriverStatus` is already a clean port — the one good abstraction. Move into `ports/driver.py` near-verbatim, preserving names/semantics. Concrete vendor drivers stay in deployments and import the contract from the new package.

### 4.7 Data sync

`HelaoSyncer` (1933 LOC) splits: walk/decide-what-to-sync → pure `domain/sync/` (testable against a fake tree); actual S3/fs/HTTP movement → `adapters` behind storage/transport ports. `RUNS_*` layout and HLO/parquet formats stay byte-compatible. Loaders (`loaders/localfs.py`, `helao_loader.py`) move under `adapters/` implementing a storage-read port.

### 4.8 Misc framework pieces

- `analysis_driver.py`, `rpc/zmq_rpc.py` → domain logic pure, transport adapter concrete.
- `vis_subscriber.py` → `adapters/` consumer of the `eventsink` message shape.
- **Runners** (`runners/micro_orch.py` et al) reuse `domain/orchestration.py` directly — same FSM drives both the long-lived `Orch` server and the short-lived runner, no duplication. Runner stubs get a real implementation for free.

## 5. Public contract (what deployments import)

Deployments migrate by changing import paths (`helao.core.*`/`helao.helpers.*` → `helao.framework.*`) plus minor signature cleanups — **not** a rewrite of every action server. The author-facing surface keeps the same names and semantics, delegating to domain+ports underneath.

Most-depended-on symbols to preserve (from import-frequency analysis across deployments): `Action`/`Experiment`/`Sequence` + `ActionPlanMaker`/`ExperimentPlanMaker` (premodels), `ErrorCodes`, `BaseAPI`, `Base`, `Active`, `HloStatus`, `Executor`, `MachineModel`, `Vis`/`HelaoVis`/`LiveVisualizer`/`ActionVisualizer`, `ProcessContrib`, `make_str_enum`, `SolidSample`/`LiquidSample`/`GasSample`/`NoneSample`, `ActionStartCondition`, `DataModel`, `gen_uuid`, `async_private_dispatcher`, `HelaoOperator`, the `HelaoDriver` contract, and `makeApp`/`makeBokehApp` factories.

## 6. Error handling & control flow

- **`ErrorCodes` stays** the canonical error vocabulary (ported into `models/`). Imported 70× — load-bearing. The design tightens *how* errors flow, not the codes.
- **Domain returns, never raises, for expected failures.** Action rejected, start-condition unmet, estop active, queue empty → `Result` value objects carrying an `ErrorCodes` value + payload. Trivially assertable; forces callers to handle.
- **Exceptions reserved for true faults** (adapter I/O failure, bugs). Caught at the `app/` boundary — today's scattered `exception_handler` becomes one place that maps an unexpected exception → `ErrorCodes.critical` + estop trigger + structured log.
- **Estop is a domain state, not a side effect.** Lives in `domain/orchestration.py`; an estop is a state transition making `step()` return halt commands that `app/` executes. Same path whether triggered by operator, error, or remote server.
- **Adapter failures degrade through ports.** Each port defines its failure contract (e.g. `transport.dispatch` returns a delivery result, not a raw httpx exception). No httpx/socket types leak inward.
- **Logging** via the ported `make_logger` in `support/`; structured fields (action_uuid, exp_uuid, server_key) attached at the `app/` boundary.

## 7. Test strategy & boundary enforcement

Purity is the test strategy — the architecture makes coverage cheap.

- **Harness:** real `pytest` (first in repo). `helao/framework/tests/` mirrors package structure. `conftest.py` provides fake adapters per port (`FakeTransport`, `FakeStorage`, `FakeClock`, `FakeEventSink`) — in-memory, deterministic, no hardware/network/disk.
- **Tier 1 — domain unit tests (bulk, coverage gate):** feed state+events to `action_lifecycle`, `orchestration` FSM, `status`, `sync` walk-logic; assert returned command/result objects. No mocks beyond plain data.
- **Tier 2 — adapter tests:** each adapter against its port contract (`fs_storage` vs tmp dir, `http_transport` vs stub server, `ntp_clock` with frozen time).
- **Tier 3 — wiring/integration smoke:** `app/` composition exercised through the migrated `test` sim deployment; proves `makeApp` + real adapters + sim driver launch and run an action end-to-end.
- **Coverage gate:** `--cov=helao/framework`, **≥90% on `domain/` and `models/`**, lower on `adapters/app`. Enforced by `run_framework_tests.py` so it can gate merges without CI infra.
- **Boundary enforcement as a test:** AST-walks `domain/`, fails on any import of FastAPI/httpx/bokeh/filesystem/`adapters`. Mechanical, not aspirational. (Custom AST check, zero new dep; import-linter optional.)
- **Migration safety net (golden master):** before deleting old `core`, run an action/sequence on old core, capture HLO/meta/`RUNS_*` output, assert new core produces byte-identical output.

## 8. Implementation sequencing

The core rewrite decomposes into ordered sub-projects, each its own brainstorm→spec→plan→implement cycle, each on its own branch off `unstable`, merged via PR after tests+review pass.

| # | Sub-project | Delivers | Branch |
|---|---|---|---|
| 0 | Scaffold + test harness | `helao/framework/` skeleton, `ports/` Protocols, fake adapters, pytest+coverage gate, AST boundary test, `run_framework_tests.py` | `feat/framework-scaffold` |
| 1 | Models | `models/` (pydantic + merged premodels), `ErrorCodes`; ported model unit tests | `feat/framework-models` |
| 2 | Support | vendored `support/` (logging, yaml, config_loader, dispatcher, time, codehash) | `feat/framework-support` |
| 3 | Driver contract | `ports/driver.py` (HelaoDriver et al, near-verbatim) | `feat/framework-driver-port` |
| 4 | Action lifecycle | `domain/action_lifecycle.py` (ex-Active), storage+eventsink adapters, `app/base_api.py`, `makeApp` | `feat/framework-action-base` |
| 5 | Orchestration | `domain/orchestration.py` FSM, `http_transport`, `app/orch_api.py`; runners reuse domain | `feat/framework-orch` |
| 6 | Data sync | `domain/sync/` + S3/fs adapters, loaders | `feat/framework-sync` |
| 7 | Pilot migration: `test` deployment | migrate sim deployment onto framework; golden-master vs old core; end-to-end smoke | `feat/framework-migrate-test` |

Sub-projects 0–3 are low-risk and partly parallelizable. 4–6 are the heart. 7 proves the whole thing on real (sim) servers and gates any production (`hte`) deployment migration in a later, separate spec.

## 9. Out of scope (future cycles)

- Operator and data_browser Bokeh UIs (`bokeh_operator.py` and friends).
- Production deployment migration (`hte`).
- Migration of the nested separate repos (`lila`, `lila_gl`, `mea`, `priv`) — each its own cycle in its own repo.
- Deletion of old `helao/core` + `helao/helpers` (only after the last deployment migrates).
- Per-sub-project implementation detail (each sub-project §8 gets its own spec).
- Changing the wire protocol / transport technology (an explicit C-later concern, not now).

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Rewrite drifts from current behavior | Golden-master byte-compatibility tests (§7) before any deletion |
| Scope creep into deployments/UI | Hard out-of-scope list (§9); atomic-migration boundary |
| Domain/adapter boundary erodes over time | AST boundary test fails the build (§7) |
| "Big rewrite never ships" | Strangler-fig: old system runs untouched; value delivered incrementally per sub-project; `test` pilot proves end-to-end before production |
| Premature C abstraction | Command/result objects + message-shaped transport port only; no bus/event-store built now |
