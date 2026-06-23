# SP7: Pilot Migration — `test` Deployment Design Spec

**Date:** 2026-06-22
**Status:** Approved
**Branch:** `feat/framework-migrate-test`
**Scope:** Migrate the `test` deployment (action servers, orchestrator, experiments, sequences, runners, drivers) from `helao.core.*`/`helao.helpers.*` to `helao.framework.*`. Visualizers (`vis`, `data_browser`, operator Bokeh) remain on old core (§9 deferred scope from master spec).

---

## 1. Goal & context

SP0–SP6 produced a complete `helao/framework/` package: domain, models, ports, adapters, app layers, and 98.9% test coverage. SP7 proves the framework works against real (simulated) deployment code by migrating the `test` deployment — the simplest in-tree deployment — onto `helao.framework.*` imports. Any framework gaps discovered here are bugs to fix before production (`hte`) migration in a later cycle.

The `test` deployment lives in `helao/deploy/test/` and is the only deployment suitable for this pilot: it has no hardware dependencies, runs entirely in-process, and is fully tracked in the parent repo.

---

## 2. Locked decisions

| Decision | Choice |
|---|---|
| Migration strategy | Import-swap in-place (Approach A) |
| Visualizers | Out of scope — retain `helao.core.*` imports; §9 of master spec |
| Golden-master approach | Extend existing committed byte-format fixtures (in-process httpx drive) |
| `lib_decorators` | Port to `helao/framework/support/lib_decorators.py` using `RunExperiment` |
| `dispatcher` | Port to `helao/framework/support/dispatcher.py`; internally keeps `from helao.core.rpc import ...` as transitional dep until RPC layer is ported |
| `file_utils` | Port to `helao/framework/support/file_utils.py` (trivial, no new deps) |
| Runners | Migrate in SP7 (import-swap) |
| Branch | `feat/framework-migrate-test` off `unstable`; merge via PR |

---

## 3. What changes

### 3a. New framework support files

| File | Description |
|---|---|
| `helao/framework/support/lib_decorators.py` | `@experiment` / `@sequence` decorators ported from `helao.helpers.lib_decorators`; rewired to `RunExperiment` from `domain.run_models` and `EXPERIMENT_CTX` from `domain.plan_makers` |
| `helao/framework/support/file_utils.py` | Port of `helao.helpers.file_utils` (146 LOC, no new deps) |
| `helao/framework/support/dispatcher.py` | Port of `helao.helpers.dispatcher`; imports `RPCClient`/`RPCSyncClient`/`RPCError`/`derive_rpc_port` from `helao.core.rpc` as transitional dep |

### 3b. Test deployment files (import-swap only — no logic changes)

**Action servers** (`helao/deploy/test/servers/action/`):
- `ws_simulator.py`
- `cpsim_server.py`
- `gpsim_server.py`
- `motion_simulator.py`
- `pstat_simulator.py`
- `analysis_simulator.py`
- `archive_simulator.py`

**Experiments** (`helao/deploy/test/experiments/`):
- `TEST_exp.py`
- `OERSIM_exp.py`
- `simulatews_exp.py`

**Sequences** (`helao/deploy/test/sequences/`):
- `TEST_seq.py`
- `OERSIM_seq.py`

**Runners** (`helao/deploy/test/runners/`):
- `test_runner.py`
- `oersim_runner.py`
- `simulatews_runner.py`

**Drivers** (`helao/deploy/test/drivers/`):
- `drivers/data/gpsim_driver.py`
- `drivers/pstat/cpsim_driver.py`

**Not changed:** visualizer servers, `test.yml` config, `demo/` scripts (demos are opt-in standalone scripts, not part of the launch group).

---

## 4. Full import map

| Old import | New import |
|---|---|
| `helao.core.servers.base_api.BaseAPI` | `helao.framework.app.base_api.BaseAPI` |
| `helao.core.servers.base.Base` | `helao.framework.app.base_api.Base` |
| `helao.core.servers.base.Executor` | `helao.framework.domain.executor.Executor` |
| `helao.helpers.premodels.Action` | `helao.framework.models.action.ActionModel` (alias `Action = ActionModel` where needed) |
| `helao.helpers.premodels.Experiment` | `helao.framework.domain.run_models.RunExperiment` |
| `helao.helpers.premodels.ActionPlanMaker` | `helao.framework.domain.plan_makers.ActionPlanMaker` |
| `helao.helpers.premodels.ExperimentPlanMaker` | `helao.framework.domain.plan_makers.ExperimentPlanMaker` |
| `helao.helpers.lib_decorators.experiment` | `helao.framework.support.lib_decorators.experiment` |
| `helao.helpers.lib_decorators.sequence` | `helao.framework.support.lib_decorators.sequence` |
| `helao.core.models.machine.MachineModel` | `helao.framework.models.machine.MachineModel` |
| `helao.core.models.hlostatus.HloStatus` | `helao.framework.models.hlostatus.HloStatus` |
| `helao.core.models.sample.*` | `helao.framework.models.sample.*` |
| `helao.core.models.process_contrib.ProcessContrib` | `helao.framework.models.process_contrib.ProcessContrib` |
| `helao.core.error.ErrorCodes` | `helao.framework.models.errors.ErrorCodes` |
| `helao.helpers.helao_logging` | `helao.framework.support.helao_logging` |
| `helao.helpers.dispatcher` | `helao.framework.support.dispatcher` |
| `helao.helpers.file_utils` | `helao.framework.support.file_utils` |
| `helao.helpers.executor` | `helao.framework.domain.executor` |
| `helao.helpers.time_utils` | `helao.framework.support.time_utils` |
| `helao.helpers.config_loader` | `helao.framework.support.config_loader` |
| `helao.core.runners.micro_orch` | `helao.framework.runners.micro_orch` |

Already present in `helao/framework/support/`: `config_loader`, `time_utils`, `helao_logging`. No change needed for those.

---

## 5. `lib_decorators` port design

`helao/framework/support/lib_decorators.py` exports `experiment` and `sequence`.

**`@experiment(version: str)`**
- Tags `fn.experiment_version = version`
- Detects if wrapped function's first param is `RunExperiment` (by annotation or name `experiment`)
- On call: extracts `RunExperiment` from positional args, kwargs, or `EXPERIMENT_CTX.get(None)`
- Sets `EXPERIMENT_CTX` token around the wrapped call; resets token after return
- Legacy positional-arg form still works (first param named `experiment` receives `RunExperiment`)

**`@sequence(version: str)`**
- Tags `fn.sequence_version = version`
- No context-var logic

Uses `EXPERIMENT_CTX` from `helao.framework.domain.plan_makers` and `RunExperiment` from `helao.framework.domain.run_models`. No new contextvar introduced.

---

## 6. `dispatcher` port design

`helao/framework/support/dispatcher.py` is a direct copy of `helao.helpers.dispatcher` with one change:

```python
# old
from helao.core.rpc import RPCClient, RPCSyncClient, RPCError, derive_rpc_port
# new (transitional — helao.core.rpc has no domain/server coupling)
from helao.core.rpc import RPCClient, RPCSyncClient, RPCError, derive_rpc_port
```

The internal `helao.core.rpc` dep is retained as a transitional measure. `helao.core.rpc` is a pure ZMQ utility package with no `helao.core.servers.*` or model coupling — porting it is a separate task (future SP or cleanup PR). The user-facing import path becomes `helao.framework.support.dispatcher`, satisfying the deployment-layer migration goal.

---

## 7. Test strategy

One new test file: `helao/framework/tests/test_migrate_test_deploy.py`

**Test 1 — `lib_decorators` unit tests**
- `@experiment` sets `.experiment_version`, injects `RunExperiment` into `EXPERIMENT_CTX`, resets token after call
- `@sequence` sets `.sequence_version`
- Legacy positional-arg form: first param named `experiment` receives `RunExperiment`

**Test 2 — Golden-master integration (WsSim action server)**
Drive `ws_simulator.makeApp("SIM")` via `httpx.AsyncClient` against a tmp-dir `FsStorage`:
1. `POST /SIM/acquire_data` with minimal `ActionModel` payload
2. Await action completion
3. Assert `.hlo` bytes on disk match committed golden format (header + `%%\n` + JSON rows, as specified in `test_golden_master_action.py`)
4. Assert `.act` meta file exists with correct `action_name`

**Test 3 — Orchestrator smoke (TEST_exp → WsSim)**
Drive `orch_api.makeApp("ORCH")` + `ws_simulator.makeApp("SIM")` together in-process via `FakeTransport`:
1. Submit a `TEST_exp` experiment (from migrated `TEST_exp.py`)
2. Step FSM until `finished`
3. Assert all actions dispatched and returned `HloStatus.finished`

**Test 4 — Runner smoke**
Call `test_runner.py`'s runner entry-point directly (imports now resolve to `helao.framework.*`); assert no `ImportError` and runner reaches `idle` state.

Coverage gate unchanged (≥90% on `domain/`+`models/`); new tests count toward total.

---

## 8. Boundary enforcement

The existing AST boundary check (`test_boundaries.py`) enforces purity on `helao/framework/domain/`. Deployment files under `helao/deploy/` are **not** subject to the domain purity gate — they may freely import `helao.framework.*` as consumers. The new `framework.support.*` files may import I/O libs (ZMQ, httpx, aiofiles) per the existing support-layer contract.

---

## 9. Implementation sequencing

Decomposed into three waves:

| Wave | Tasks | Rationale |
|---|---|---|
| 1 | Port `lib_decorators`, `file_utils`, `dispatcher` to `framework.support` | Unblocks all deployment file import-swaps |
| 2 | Import-swap all `test` deployment files (action servers, experiments, sequences, runners, drivers) | Bulk mechanical change; verifiable by import resolution |
| 3 | Add `test_migrate_test_deploy.py` test suite; verify framework gate passes | Proves the migration end-to-end |

---

## 10. Out of scope

- Visualizer servers (`vis.py`, `data_browser.py`, `gpsim_live_vis.py`, etc.) — §9 of master spec
- Demo scripts (`demos/multi_orch_demo_helper.py`) — standalone, not part of launch group
- Porting `helao.core.rpc` itself — deferred; `dispatcher` keeps internal dep
- `hte` production deployment migration — separate future spec
- Private deployment migrations — their own repos and cycles
- Deleting `helao/core/` + `helao/helpers/` — only after last deployment migrates
