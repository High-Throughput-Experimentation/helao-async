# SP7 — Pilot Migration: `test` Deployment (design)

**Date:** 2026-06-23 · **Branch:** `feat/framework-scaffold` (continues PR #176) · **Model for spec:** Opus
**Supersedes:** the discarded Sonnet `2026-06-22-framework-migrate-test-design.md` (reachable at tag `sp6-sp8-sonnet-ref`).

---

## 1. Goal & context

SP0–SP6 produced `helao/framework/`: domain, models, ports, adapters, app + sync
layers, ~860 tests, gate 7/7, domain provably pure. SP7 proves the framework runs
real (simulated) deployment code by migrating the in-tree `test` deployment off
`helao.core.*`/`helao.helpers.*` onto `helao.framework.*`, and **proves one action
server runs one action end-to-end in-process** (golden-master ASGI drive).

The `test` deployment is the only one suitable for the pilot: no hardware, fully
in-tree, no private-repo coupling.

### Scope correction vs the Sonnet spec
The Sonnet SP7 spec assumed `helao.framework.app.base_api` already exported
legacy-compatible `Base`/`BaseAPI`/`Executor` and treated SP7 as a near-pure
import-swap. **It does not.** Current `app/base_api.py` exports only `FrameworkBase`
(a deliberate subset built in SP4) and `app/factory.py:makeActionApp` is a one-off
`/run_dummy` demo, not a real action-server host. So SP7 must additionally **port the
minimal action-server surface** the migrated deploy servers call:

```
BaseAPI(server_key=…, driver_classes=[…])  →  app.base.setup_and_contain_action()  (no-arg)
                                          →  active.start_executor(executor)
                                          →  base.put_lbuf / base.get_lbuf
                                          →  base.executors[…].stop_action_task()
```

This is exactly the "deliberate subset … added in the full production wiring (a later
SP)" the SP8 spec references. The SP7/SP8 line is drawn at **single-server, in-process,
no live orch** (§2).

---

## 2. SP7 / SP8 boundary (explicit)

| Concern | SP7 (this spec) | SP8 (next) |
|---|---|---|
| Import paths swapped on `test` deploy | ✅ | — |
| `Base`/`BaseAPI`/`Executor` legacy-compat exports | ✅ (subset) | extends |
| `ACTION_CTX` request wrapper → no-arg `setup_and_contain_action()` | ✅ | — |
| Live buffer (`put_lbuf`/`get_lbuf`) | ✅ | — |
| `executors` registry + `start_executor` + `stop_action_task` | ✅ | — |
| Driver instantiation (dual-convention: `HelaoDriver` vs bare helper) | ✅ (minimal) | conformance audit (WS-D) |
| One action runs in-process via ASGI (golden master) | ✅ | — |
| Orch `attach_client` → action-server status POST → `/update_status` | — | ✅ (WS-A, critical) |
| `/ws_status`/`/ws_data`/`/ws_live` publishers | — | ✅ (WS-B) |
| Admin endpoints (`/get_status`, `/endpoints`, `/stop_executor`, `/shutdown`, …) | — | ✅ (WS-B) |
| `app_entry` collision middleware + estop exception handler | — | ✅ (WS-E) |
| Whole-run-dir relocation at finish (RUNS_ACTIVE→synced) | — | ✅ (WS-F) |
| Live multi-server / orchestrated sequence run | — | ✅ |

**Rule:** if a behavior is only observable when a *second* server (orch or visualizer)
talks to the action server over the network, it is SP8. SP7 stops at one server
hosting one action driven by an in-process `httpx`/ASGI client.

---

## 3. Locked decisions

| Decision | Choice |
|---|---|
| Migration strategy | Import-swap in-place (Approach A) — no logic changes to deploy files |
| Action-server surface | Port the minimal subset to `helao.framework.app.base_api` (`BaseAPI`, `Base`) + `helao.framework.domain.executor` (`Executor`) |
| `setup_and_contain_action()` | No-arg form, driven by `ACTION_CTX` populated by the endpoint request-wrapper (port `base_api.py:89,302–358`) |
| Legacy names | `Base = FrameworkBase`-superset, `Action = ActionModel` alias where deploy code imports `Action` |
| Visualizers | Out of scope — retain `helao.core.*` imports (master §9) |
| `lib_decorators` | Port to `framework/support/lib_decorators.py` on `RunExperiment` + `EXPERIMENT_CTX` |
| `file_utils` | Port to `framework/support/file_utils.py` (no new deps) |
| `dispatcher` | Port to `framework/support/dispatcher.py`; keep `from helao.core.rpc import …` as transitional dep |
| Golden master | In-process `httpx.AsyncClient` (ASGITransport) over `ws_simulator.makeApp("SIM")` against a tmp `FsStorage`; assert `.hlo` + `.act` byte/shape parity with the SP4 committed format |
| Branch | `feat/framework-scaffold` (stack on PR #176) |
| Env | `conda run -n helao` for all python/pytest |

---

## 4. What changes

### 4a. New framework support files (Wave 1)

| File | Source | Notes |
|---|---|---|
| `framework/support/lib_decorators.py` | `helao.helpers.lib_decorators` | rewire to `RunExperiment` (`domain.run_models`) + `EXPERIMENT_CTX` (`domain.plan_makers`); legacy positional-`experiment` form preserved; `@experiment` must accept a legacy `Experiment`/`RunExperiment` instance |
| `framework/support/file_utils.py` | `helao.helpers.file_utils` | direct port, no new deps |
| `framework/support/dispatcher.py` | `helao.helpers.dispatcher` | direct port; internal `from helao.core.rpc import RPCClient, RPCSyncClient, RPCError, derive_rpc_port` retained (transitional; `helao.core.rpc` is pure ZMQ, no server/model coupling) |

### 4b. Framework action-server surface (Wave 2) — the new work

**`framework/domain/executor.py`** — extend the existing `Executor`:
- `stop_action_task()` (port `base.py:2461`) — sets a stop flag the poll loop honors.
- confirm `oneoff`/`poll_rate`/`exec_id`/`duration` parity (already present).

**`framework/domain/action_session.py`** — extend `ActionSession` (= legacy `Active`):
- `start_executor(executor) -> dict` (port `base.py:1202`): register in `base.executors`
  keyed by `exec_id`, spawn `action_loop_task` as a background task, return the active
  action dict.
- `.base` backref (set at construction) so `WsExec._poll` can call `self.active.base.get_lbuf`.
- `put_lbuf`/`get_lbuf` delegating to `base` (legacy `Active` mirrors these,
  `base.py:2487/2493`).

**`framework/app/base_api.py`** — grow `FrameworkBase` toward legacy `Base` (subset) and
add the legacy-named host class:
- `server_cfg` / `world_cfg` (a.k.a. `helao_cfg`) populated from `CONFIG`/passed config;
  `server_cfg["params"]` exposed; `helaodirs` (`helao_dirs`).
- `executors: dict` registry.
- live buffer: `put_lbuf`/`put_lbuf_nowait`/`get_lbuf` (port `base.py:677–700`).
- **no-arg** `setup_and_contain_action(...)` that recovers the `RunAction` from
  `ACTION_CTX` (port `base.py:328–445`), keeping the existing ctx-arg form working for
  the SP4 demo/tests (overload by optional arg).
- `myinit()` minimal (live-buffer task only; status/orch tasks are SP8).
- driver instantiation helper: `HelaoDriver` subclasses get `config=server_params`; bare
  helper classes get the base positional ([[sp8-drivers-bare-helpers]]).
- export alias `Base = FrameworkBase` (or rename + keep `FrameworkBase` alias).

**`framework/app/base_api.py` (or a sibling app module)** — `ACTION_CTX` + `BaseAPI`:
- `ACTION_CTX: ContextVar[Optional[ActionContext]]` (port `base_api.py:89`).
- action-endpoint request wrapper that, on each call, builds a `RunAction` from the
  request body/query + route and sets/resets `ACTION_CTX` (port `base_api.py:302–358`).
- `BaseAPI(HelaoFastAPI)` accepting `server_key`, `server_title`, `description`,
  `version`, `driver_classes`, `dyn_endpoints` (port `base_api.py:568–661` **subset** —
  NO ws routes, NO admin endpoints, NO app_entry middleware, NO estop handler; those
  are SP8). Exposes `.base`. Instantiates `driver_classes` against `.base`.

> The app-layer file is the only framework module besides `app/factory.py` allowed to
> import FastAPI (boundary contract unchanged).

### 4c. Test deployment import-swap (Wave 2) — no logic changes

Action servers (`servers/action/`): `ws_simulator`, `cpsim_server`, `gpsim_server`,
`motion_simulator`, `pstat_simulator`, `analysis_simulator`, `archive_simulator`.
Experiments (`experiments/`): `TEST_exp`, `OERSIM_exp`, `simulatews_exp`.
Sequences (`sequences/`): `TEST_seq`, `OERSIM_seq`.
Runners (`runners/`): `test_runner`, `oersim_runner`, `simulatews_runner`.
Drivers (`drivers/`): `data/gpsim_driver`, `pstat/cpsim_driver`.

**Not changed:** visualizer servers, `test.yml`, `demos/`.

### 4d. Import map

| Old | New |
|---|---|
| `helao.core.servers.base_api.BaseAPI` | `helao.framework.app.base_api.BaseAPI` |
| `helao.core.servers.base.Base` | `helao.framework.app.base_api.Base` |
| `helao.core.servers.base.Executor` | `helao.framework.domain.executor.Executor` |
| `helao.helpers.premodels.Action` | `helao.framework.models.action.ActionModel` (`Action = ActionModel`) |
| `helao.helpers.premodels.Experiment` | `helao.framework.domain.run_models.RunExperiment` |
| `helao.helpers.premodels.ActionPlanMaker` | `helao.framework.domain.plan_makers.ActionPlanMaker` |
| `helao.helpers.premodels.ExperimentPlanMaker` | `helao.framework.domain.plan_makers.ExperimentPlanMaker` |
| `helao.helpers.lib_decorators.{experiment,sequence}` | `helao.framework.support.lib_decorators.{experiment,sequence}` |
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

Already present in `framework/support/`: `config_loader`, `time_utils`,
`helao_logging`, `codehash`, `yml_tools`. Confirm each migrated file's model imports
resolve (machine/sample/process_contrib all exist under `framework/models/`).

---

## 5. Test strategy (Wave 3)

New file: `framework/tests/test_migrate_test_deploy.py` (+ split helpers if large).

- **T1 `lib_decorators` units:** `@experiment` sets `.experiment_version`, injects
  `RunExperiment` into `EXPERIMENT_CTX`, resets token after call, accepts a legacy
  `RunExperiment` instance; `@sequence` sets `.sequence_version`; legacy positional form.
- **T2 import-resolution:** every migrated module imports with no `ImportError` and no
  residual `helao.core.*`/`helao.helpers.*` import (assert via AST/`importlib`).
- **T3 golden-master (WsSim, in-process):** `httpx.AsyncClient` + `ASGITransport` over
  `ws_simulator.makeApp("SIM")` against a tmp `FsStorage`; `POST /SIM/acquire_data` with
  `duration` short; await finish (`cancel_acquire_data` or duration elapse); assert the
  `.hlo` bytes (header + `%%\n` + JSON rows) and `.act` meta match the SP4 committed
  golden format (reuse `test_golden_master_action.py` format helpers).
- **T4 runner import smoke:** importing `test_runner`/`oersim_runner`/`simulatews_runner`
  resolves to `helao.framework.*` with no `ImportError` (no live run — that's SP8).

Gate unchanged: `run_framework_tests` — ≥90% on `domain/`+`models/`, boundary test green
(now 7 categories), all suites pass. New tests count toward total.

---

## 6. Boundary enforcement

`domain/` purity gate unchanged: `domain/executor.py` and `domain/action_session.py`
additions must import only `models/` + `ports/` (no FastAPI, no I/O libs). `ACTION_CTX`
+ `BaseAPI` live in `app/` (FastAPI allowed there). Deploy files under `helao/deploy/`
are consumers — not subject to the domain gate. `framework/support/*` may import I/O
libs (ZMQ/httpx/aiofiles) per the support-layer contract.

---

## 7. Sequencing (waves)

| Wave | Tasks | Parallelism |
|---|---|---|
| 1 | Port `lib_decorators`, `file_utils`, `dispatcher` to `framework/support` | 3 parallel |
| 2 | (A) `Executor.stop_action_task`; (B) `ActionSession.start_executor`+`.base`+lbuf delegation; (C) `Base`/`FrameworkBase` lbuf+executors+server_cfg+no-arg setup+driver-inst; (D) `ACTION_CTX`+`BaseAPI`; then (E) import-swap all deploy files | A/B/C parallel → D depends on B+C → E depends on D |
| 3 | `test_migrate_test_deploy.py` (T1–T4); run gate; fix fallout | sequential after W2 |

Each task: implement → self-review → framework gate. Reviews between waves. Continue
across waves without user checkpoint (standing authorization).

---

## 8. Out of scope (→ SP8 or later)

- Everything in the SP8 column of §2 (live-orch wiring, ws publishers, admin endpoints,
  concurrency middleware, finish relocation, full driver-contract conformance audit).
- Visualizer servers, `data_browser`, operator Bokeh UIs.
- `demos/` scripts; `test.yml` changes.
- Porting `helao.core.rpc` itself (dispatcher keeps the transitional dep).
- `hte` / private-deployment migration; deletion of old `helao/core` + `helao/helpers`.
- Changing wire protocol / transport tech.
