# HELAO-async Hexagonal Rewrite — Master Design Spec

**Date:** 2026-07-16
**Status:** Draft for review (master spec; each phase P0–P7 gets its own implementation plan — see §13)
**Baseline:** branch `unstable` @ `982004a3` (post-CARDS P1–P6)
**Amendments:** *Amendment 1 — the second UI stack* (`2026-08-04-hexagonal-rewrite-ui-amendment.md`, adopted 2026-08-04 @ `8e18c0f9`): adds D9 and phase P7-UI, adds artifact row 15, corrects §9.2(3) and §9.4, extends §8.1's endpoint count to 241. Amendment sections are cited inline below as **[A1 §n]**.
**Inputs:** the grounded current-state research set under `.omc/research/framework-rewrite/` (core-01…core-06, postmortem-old-framework, deploy-test, deploy-hte-drivers-A/B, deploy-hte-servers, Deployment-A/B/C audits) — every contract number, line reference, and behavior cited below was verified against `unstable` on 2026-07-16 by that research pass.

**Privacy rule (binding for this document and every phase plan):** the three private deployments are referred to ONLY as **Deployment-A**, **Deployment-B**, **Deployment-C**. No real deployment names, directory names of private nested repos, hostnames, IPs, credentials, usernames, or campaign/plate identifiers from private configs may appear in tracked docs, code comments, or commit messages. Structure and behavior only.

---

## 1. Context, goals, and non-goals

### 1.1 Context

HELAO-async is a distributed instrument-control system: FastAPI action servers wrapping hardware drivers, an orchestrator owning sequence/experiment/action queues, Bokeh visualizers/operators, and a data syncer shipping run artifacts to S3/DB. The CARDS refactor (P1–P6) already decomposed the two god-classes (`Orch` 2622→864 facade + collaborators; `Base` 2557→1543 + 9 collaborators), migrated 23 drivers plus PAL onto the `HelaoDriver` ABC, and extracted a pure `DispatchPolicy` FSM. The codebase is therefore *already half-hexagonal*: pure policy objects exist, the driver config-seam exists, collaborators follow a strict no-cached-state rule.

A previous full rewrite (`feat/framework-scaffold`, 2026-06-22 → 2026-07-06, ~70k insertions, abandoned) proved the architecture (domain/ports/adapters/app + reducer FSM + AST boundary test held for its entire life) but died on **parity discipline**: on-disk artifacts and wire behavior were re-derived from reading code instead of being captured from real runs, and its 1700-test suite pinned the rewrite's own wrong behavior. This spec restarts the rewrite with parity as the load-bearing structure, not a table row.

### 1.2 Goals

1. **G1 — Hexagonal core.** A parallel tree with a pure domain (no I/O), ports as Protocols, adapters at the edges, and a thin app/composition layer; boundary enforced by an AST test that fails the suite on violation.
2. **G2 — Byte-level artifact parity**, defined as the four-part contract of §5/§6: (a) run output tree (directories + filenames), (b) YAML/meta content post-`clean_dict`, (c) HLO data payloads, (d) synced S3/DB payload shapes — all measured against **golden masters captured from real legacy runs**, never hand-built.
3. **G3 — Full scope.** Core + all deployments: `test`, `hte`, and private Deployment-A/B/C, phased P0–P6 with a hard parity gate per phase.
4. **G4 — Behavioral parity of the public surface**: every legacy endpoint, WS channel, RPC method, and status-push contract preserved per the endpoint-parity checklists of §8.
5. **G5 — Structural elimination of the three known failure modes** (artifact re-derivation, write-timing divergence, FSM/status races) plus the logging-singleton regression — see the countermeasure table in §2.

### 1.3 Non-goals (explicit)

- **No `action_params` typing.** The untyped params relay (`*_params` dicts, `to_global_params: Union[list, dict]`, `from_global_*_params`, underscore-prefixed blackboard keys like `_results`/`_coordinates`) is kept **bit-exact**. Typing it is a later Domain-Integrity pass, out of scope here.
- **No new pure-domain type system.** The domain layer **reuses** the existing post-CARDS pydantic run models (`ActionModel`/`ExperimentModel`/`SequenceModel`/`ProcessModel` + runtime `Action`/`Experiment`/`Sequence` from `helao/helpers/premodels.py`). They already emit artifacts via `HelaoDict.clean_dict()`; introducing parallel domain types is precisely what made the old attempt's artifacts drift.
- **No status-transition enforcement flip.** `status_transitions.py` guards stay **log-only** (CARDS "3a"); enforcement ("3e") remains gated on soak telemetry, independent of this rewrite.
- **No behavior "fixes" that change observable artifacts or wire bytes** during P0–P6. Known legacy bugs and quirks (e.g. `set_error` writing `errored` into `experiment_status`, the ≤~1 s finish-drain data-loss window, the blocking 0.3 s per-status-client sleep, sample-union accept-anything fallback) are **reproduced** and catalogued in a post-parity backlog. Internal defects invisible to disk/wire (e.g. power-supply driver's inverted response codes) may be fixed inside adapters.
- **No API-leg implementation.** `SyncDriver.to_api` is a stub returning `True` today; it stays a stub. The observable sync surface is S3 payloads + on-disk tree (§5.6).
- **No deletion of legacy core.** Legacy `helao/core` + `helao/helpers` remain untouched and runnable throughout; deletion is a separate post-P6 decision with its own gate.
- **No dead-code migration.** `dbpack_driver.py` (superseded by `sync_driver.py`), `ws_demo.yml`, the orphaned/broken hte `leancat` driver, `experiments/archive/`, and Deployment-B's empty `example_device` are not ported.
- **No UI migration in P0–P6.** Both UI stacks (Bokeh and the Reflex/`xy` stack added 2026-08-01) stay on legacy core through the deployment phases and migrate together in **P7-UI** (D9, [A1 §3]). They are *consumers* of the hexagon servers' wire surface during P0–P6, and keeping them working is a per-phase obligation, not a per-phase scope item.

---

## 2. Why the old attempt failed, and how each failure is structurally prevented

Full autopsy: `postmortem-old-framework.md`. The KEEP list (§2.3) is adopted wholesale; every AVOID item maps to a structural countermeasure below. "Structural" means: the countermeasure is a gate, a test class, or an architectural rule that makes the failure mechanically impossible or loudly visible — not a reminder.

### 2.1 The three failure modes → countermeasures

| # | Failure (root cause) | Structural prevention in this spec |
|---|---|---|
| F1 | **Artifact parity by re-derivation.** Golden masters were hand-constructed fixtures citing legacy line numbers; tests pinned the framework's own behavior; the real legacy-vs-new on-disk diff was deferred to "before deleting old core" and never ran. Ten distinct divergences (wrong root, wrong filenames, missing `file_type` header, `as_dict` vs `clean_dict` pruning, dropped output-dir stamping, missing `-prc.yml`, …) each surfaced live. | **P0 builds the parity harness before any rewrite code exists** (§6). Golden masters are captured from real legacy runs on Linux (`test` deployment) and at-station for hardware deployments; the harness refuses fixtures not produced by a recorded capture run (fixture provenance manifest, §6.5). The artifact inventory (§5) is the normative contract — every row has path template, filename grammar, content schema, writer, and timing. **Every phase gate P1–P6 includes the automated normalized diff**; a milestone cannot be declared done without a harness run ID. |
| F2a | **Artifact write-timing divergence.** Eager HLO open in `contain_action` vs legacy lazy-open-on-first-write changed filenames, FileInfo recording, and no-data semantics; fire-and-forget `enqueue_data_nowait` past `finish()` leaked handles (WinError 32, permanent promotion failure). | Timing is **part of the contract**: §5.4 specifies open-on-first-write, `%%`-before-first-row, no-data ⇒ no file, finish-joins-pending-writes, meta-write-then-move ordering, and the rewrite cadence of exp/seq ymls. The ArtifactStore port (§4.3.3) encodes these as its semantics, and the golden set includes a **no-data action** and a **write-after-finish** scenario so timing divergence shows up as a tree/content diff, not a station surprise. |
| F2b | **FSM/status races.** Production shipped with `FakeTransport` wired in (`_synthesize_finished_status` — the orch never really dispatched); spawn-per-event loops double-drained queues; identity-defaulted status folds matched everything; the register/history side-effect calls scattered through legacy `update_status` were omitted three separate times. | (a) **Fakes are opt-in and fail loud** (§10.2): app composition raises at startup if a port has no adapter — there is no silent default. (b) **Single long-lived Event-parked dispatch loop from day one** (KEEP, commit 7924342c pattern). (c) The **side-effect checklist** of legacy `update_status`/`finish_active_*` (history registration, uuid tracking, live-buffer puts, interrupt_q wake — enumerated §4.2.4) is a required conformance test, not tribal knowledge. (d) **Mandatory concurrency test class** (§10.3): lost-wakeup, double-drain, non-default orchestrator identity, estop-between-decision-and-effect. An orch milestone that has not run these on the **real transport** is not done, and "done" claims must name the transport used. |
| F3 | **Duplicated logging singleton.** Vendored second `helao_logging` module with its own `LOGGER=None` global; launchers initialized only the legacy one; `make_logger(log_dir=None)` silently fell back to `tempfile.mkdtemp()` → logs scattered to `/tmp`, then a parallel `LOGS_FW` dir post-fix. | **Exactly one logging module** for both stacks during coexistence (the legacy `helao.helpers.helao_logging`, wrapped by a Logging port — §9.1). The port **raises** when asked to create a file logger without a resolved log root; the `mkdtemp()` fallback is deleted behind the port. Log path is a contractual, tested string: `<root>/LOGS/<server_key>.log`. No parallel directories, ever. A P0 behavior test asserts the path. |

### 2.2 The spec-thinness list → where this spec is thick

| Old spec gap | This spec |
|---|---|
| "Byte-compatible on-disk formats" was one table row | §5: 14-artifact inventory with grammar, schema, writer, timing; §5.4 ordering invariants; §5.5 volatile-field normalizer contract |
| Golden-master procedure unspecified; capture never happened | §6: end-to-end capture rig, sequences, sim DB server, normalizer, per-milestone gate mechanics, at-station procedure |
| No wire/dispatch contract | §7: RPC port math, probe timeout, method/payload shapes, HTTP fallback, middleware-bypass semantics, WS frame encodings, status-fold identity rules, nonblocking lifecycle |
| No legacy public-surface audit | §8: per-deployment endpoint-parity checklists generated mechanically from the audited surface maps (241 static hte endpoints as of 2026-08-04, 237 at the audit + config-driven ones + the BaseAPI system surface) |
| No cross-cutting runtime-services plan | §9: logging, config-identity, clock/NTP as first-class ports with behavior tests |
| Test strategy trusted purity over fidelity | §10: fixture-fidelity rule (real route registration, real consumer decoders, capture-derived fixtures), concurrency suite, disconnected-driver construct |
| Import-swap migration underestimated (experiment libs, private configs, bokeh ports) | §8.3 dependent-surface inventory rule; §12 phases explicitly include experiment/sequence libraries and private-deployment configs |
| Windows out of the loop | §11: import isolation, COM apartment plan, file-lock semantics, event-loop policy |

### 2.3 KEEP ledger (adopted from the old attempt, verbatim requirements)

1. Layer discipline enforced by an **AST boundary test** (never eroded in the old branch's life).
2. **Reducer-style orch FSM** `step(state, events) -> (state, commands)` driven by an app-layer loop.
3. **Single long-lived Event-driven dispatch loop**; in-process routing for orch-self operations (`nonblocking_sink`, in-process `stop_executor`); **never self-RPC from inside the loop** (the FINISH_EXPERIMENT self-deadlock, c58f1314).
4. **Serialize at the wire adapter, keep domain payloads rich** (`_json_clean` at the relay; the domain-side serialization attempt broke 46 consumers).
5. Ports as Protocols + fakes-in-adapters for fast unit suites; command/result value-object error style (ErrorCodes-carrying results; exceptions only for faults).
6. Launcher **`deployment:` key + per-config atomic cut-over + offline preflight validator + canary-first, risk-ordered station rollout** (the preflight caught a real pre-existing config bug in 3 stations).
7. Shared-seam hardening worth porting regardless: WsSubscriber capped-backoff indefinite reconnect (7bfee1ed), busy-file retry on Windows promotion (bc9232db), await-nowait-writes-before-close (ce846da1), operator write-only-on-change poll (c0d4b12a).
8. Namespace-hash synthetic identities (never uuid.int±k arithmetic — it collided once, 3ee3c31b).
9. `inspect.get_annotations(eval_str=True)` in RPC arg coercion, tested in a `from __future__ import annotations` module (7d804523).
10. Log every exception swallow around wire sends — no bare `except Exception: pass` on send paths (f638207e).

---

## 3. Locked decisions (do not re-litigate in phase plans)

| # | Decision |
|---|---|
| D1 | Strategy: **parallel hexagonal tree** (strangler-fig beside untouched legacy), with **every step gated by the golden-artifact parity harness**. The old parallel tree failed on parity discipline, not architecture. |
| D2 | Parity contract = ALL of: run output tree (dirs + filenames), YAML/meta content (post-`clean_dict`), HLO data payloads, and synced S3/DB payload shape. |
| D3 | Scope = core + ALL deployments (test, hte, Deployment-A/B/C), phased P0–P6. |
| D4 | Golden masters are **captured from real legacy runs** — never hand-built from reading code. |
| D5 | Build a **simulated DB/sync server** so test configs exercise the full RUNS_FINISHED → RUNS_SYNCED → S3/DB leg on Linux and capture those goldens automatically (`HelaoSyncer` only instantiates when a `DB` server key exists — `helao/core/servers/orch.py:117-119`). |
| D6 | The embedded Bokeh plate-aligner UIs inside motion drivers (hte `galil_motion_driver`, Deployment-A `ThorlabsMotor`) are **extracted**: motion Hardware adapter + pure `TransformXY` domain service + a separate **aligner visualizer adapter**. A driver may never construct a Bokeh `Server` or hold an `Active`. |
| D7 | The `action_params` blackboard stays **bit-exact** for parity; typing is a later Domain-Integrity pass. |
| D8 | Domain layer **reuses the existing post-CARDS pydantic run models**; no new pure-domain type system. |
| D9 | **Both UI stacks (Bokeh and Reflex) stay on legacy core through P0–P6 and migrate together in P7-UI** [A1 §3]. The UI consumes the servers' wire surface; it produces no parity artifact (see row 15). **Corollary, binding on P0–P6:** no phase may change a WS payload shape, a private route, or a config key that either UI stack consumes without updating that stack in the same commit. |

---

## 4. Target architecture

### 4.1 Package layout and boundary rule

New parallel tree (name is Open Question Q1; working name `helao/hexagon/` to avoid collision/confusion with the abandoned `helao/framework/` branch):

```
helao/hexagon/
├── domain/      # pure logic; imports: stdlib, pydantic, numpy, helao.core.models,
│                #   helao.helpers.premodels, helao.core.helaodict ONLY
├── ports/       # typing.Protocol definitions; imports: domain + stdlib
├── adapters/    # implementations; imports: ports, domain, vendor libs, legacy helao.*
│   └── fakes/   # opt-in test doubles (never wired by default composition)
├── app/         # FastAPI/Bokeh hosting, factories, composition root, dispatch loop
└── tests/       # pytest suite incl. tests/test_boundaries.py (AST walk)
```

**Boundary test (mandatory from the first commit):** an AST walk over `helao/hexagon/` that fails if `domain/` imports anything outside its allow-list (in particular: no `fastapi`, `aiohttp`, `httpx`, `zmq`, `bokeh`, `boto3`, `aiofiles`, `asyncio`-I/O, vendor libs, or `helao.hexagon.adapters`/`app`), if `ports/` imports adapters/app, or if `adapters/` imports `app`. This held for the entire old branch — keep it identical in spirit and extend the allow-list explicitly rather than loosening the walk.

Note the deliberate exception: `domain/` **may import the legacy model modules** (`helao/core/models/*`, `helao/helpers/premodels.py`, `helao/core/helaodict.py`) per D8. Those modules are pure-ish (the known smell — `core/models/server.py` importing `premodels.Action` — is accepted; see Q4). Everything else in legacy `helao.*` is adapter territory.

### 4.2 Domain layer

Pure, deterministic, no I/O, no `await` on external resources. Contents:

#### 4.2.1 Run models (reused, D8)
`ActionModel`/`ExperimentModel`/`SequenceModel`/`ProcessModel` + runtime `Sequence`/`Experiment`/`Action` (premodels, with the cumulative-inheritance MI flattening), `HloStatus` lists with log-only guarded mutators, `SampleUnion` two-stage union **including** the bare-`SampleModel` accept-anything fallback (parity: schema drift must keep being silently absorbed exactly as today), `FileInfo`/`HloHeaderModel`/`FileConnParams`, `GlobalStatusModel` (with its tuple-keyed `server_dict` and bespoke `as_json()`), enums (`OrchStatus`/`LoopStatus`/`LoopIntent`/`ActionStartCondition`/`RunUse`/`ProcessContrib`/`RunDir`/…). Serialization for every artifact goes through `HelaoDict.clean_dict()` — the domain's artifact-content assembly is "model → clean_dict → dict", nothing else.

#### 4.2.2 Orchestration reducer FSM (KEEP)
`domain/orchestration.py`: `step(state, events) -> (state, commands)`, encoding exactly the legacy semantics mapped in core-01:

- The **decision ladder** (priority order): ExitLoop → DriverHealthWait (non-terminal; falls through in-iteration after retries, never `continue`-loops) → StopLoop (estop) → LaunchAction → FinishThenDispatchExperiment → FinishThenDispatchSequence → LogQueuesEmpty.
- The **loop-state transition table** T1–T13 (start/stop/skip/estop/clear_estop/clear_error/dispatch-failure/uncaught-exception), including: dispatch transport failure ⇒ graceful stop + head-requeue (NOT estop); action `error_code != none` in a result ⇒ **escalates to estop_loop**; skip clears only `action_dq`; plain stop with empty queues still runs CloseOutExperiment/Sequence.
- Start-condition predicates (`no_wait`/`wait_for_endpoint`/`wait_for_server`/`wait_for_orch`/`wait_for_previous`/`wait_for_all`+fallback), evaluated interrupt-driven (re-checked on `wait_for_interrupt` wake, not polled).
- Queue CRUD semantics (head-reinsert on failure/stop-intent; `supplement_error_action` retry bump; `add_experiment` field-fold; split/prepend sequence stamping; run-id policy `_ensure_run_id`/`_resolve_active_run_id` — empty `sequence_dq` mints, non-empty reuses).
- The **three live estop re-checks** that the CARDS code carries (inside the dispatch lock; at the top of FinishThenDispatch effects; in finalization close-out guards `loop_state != estopped` so `estop_finish_active` remains sole finalizer under estop). The reducer form must make these explicit: commands carry the guard, and the effect runner re-reads live state before executing them — or estop is serialized with the loop. A phase plan must pick one and test both races either way.
- Global-param folds: `apply_from_globals` / `collect_to_globals` (pure, already extracted).
- Process grouping at experiment expansion (`process_contrib`/`process_finish` → `process_uuid`s, `process_order_groups`, `process_list`), planned-experiment merge policy, sequence split/group logic.

#### 4.2.3 Naming & artifact assembly
Dir/filename grammar (§5.1) as pure functions (already in `premodels.py` + `base_meta_writer.py` name logic); file-conn key derivation (`md5`→UUID, `dflt_file_conn_key = md5(str(None))` — 34 call sites); manual-run `RUNS_ACTIVE→RUNS_DIAG` redirection **centralized in one domain function** (legacy copy-pastes it at 8+ write sites); HLO filename scheme; FileInfo construction (`init_datafile` logic incl. `nosync` for `sync_data=False`).

#### 4.2.4 Status ingestion fold + side-effect checklist
`GlobalStatusModel.update_global_with_acts`/`_sort_status` (pure fold) + the **enumerated side effects** legacy performs around it — this list is normative and each item gets a conformance test:
1. history registration on `last_action_uuid` match (this is what unblocks the dispatch loop's history poll);
2. `register_obj_uuid`/`register_action_uuid` calls on every enqueue/dispatch/finish path (the thrice-omitted class of bug);
3. newly-nonactive `(uuid, status)` tuples → live buffer;
4. orch_state derivation (estopped-in-finished ⇒ estop_loop; errored ⇒ error; empty active_dict ⇒ idle; else busy);
5. `interrupt_q.put(...)` wake of the dispatch loop;
6. status-fold identity rule: finished actions are removed only when `statusmodel.orchestrator == gsm.orchestrator` — and every self-hosted action (orch `/wait`, conditional_*) **must stamp the orch identity** (MINOR-8: default `MachineModel()` worked in tests and permanently stalled under a real config identity).

#### 4.2.5 Estop as a domain policy (new — replaces two hardcoded cascades)
Today: (a) the orch's `estop_loop` sequence (loop_state=estopped → clear run_id → fan `estop` action to every server in `server_dict` → `estop_finish_active` exp-then-seq with `[finished, estopped]` terminal status → deferred child-dir-aware promotion), and (b) Deployment-B's `execute_gamry_stop` — a driver-resident cascade firing raw HTTP at hardcoded server keys (`ORCH*` `/stop`, recorder keys `/stop_record`, PSTAT keys `/stop_private`), duplicated with drift in a Bokeh visualizer. This is the CARDS estop-extraction backlog item plus the Deployment-B port-boundary violation, resolved once:

- `domain/estop_policy.py`: pure `EstopPolicy` that, given a **declarative stop topology** (derived from config: which server keys are orchestrators, which host recorders, which need `stop_private`) and a trigger event (driver fault edge, UI button, status-ingested estopped uuid, `/estop_orch`), emits an ordered command list (`StopOrch(key)`, `StopRecorders(keys)`, `StopPrivate(keys)`, `EstopFanout(switch)`, `FinishActiveEstopped()`).
- Commands execute through the **Transport/OrchControl outbound port** — never raw `httpx` in a driver, never hardcoded keys in code.
- Adapters expose trigger sources: the Deployment-B OPC-UA fault monitor's rising-edge and the visualizer buttons both feed the same policy. The duplicate UI implementation is deleted in P5.
- Parity constraint: the estopped artifact shape is unchanged — `[finished, estopped]` status lists, no fabricated placeholder artifacts (post-bd8b83ab semantics), estop-promote waits ≤30 s for co-located child dirs then leaves the record in RUNS_ACTIVE for `finish_pending`.

#### 4.2.6 Other domain services
`TransformXY` (lifted whole from `galil_motion_driver` — already Base-free, ~370 lines; Deployment-A carries a near-copy to unify), plan makers (`ActionPlanMaker`/`ExperimentPlanMaker` minus caller-frame inspection — context passes explicitly), `calc`-style pure computations (UV-Vis FOM math, `calculate_cp_overpotential`), dispatch-policy snapshot dataclasses, `should_close_out_*`/`should_export` guards, `Timer` primitive, sequence-constructor/spec-parser plan logic.

### 4.3 Ports (Protocols)

Each port below states: purpose, the concrete legacy contract it abstracts, and its parity-critical semantics. Signatures are illustrative; exact Protocols are P1-plan material.

#### 4.3.1 Hardware
Abstacts `HelaoDriver` (`helao/core/drivers/helao_driver.py:85`). Contract:
- Construction from `config: dict` (the server's YAML `params:` block) — the existing conformant seam; **no I/O in `__init__`** (the port bans constructor-connect; adapters wrapping legacy constructor-connecting drivers defer construction to `connect()`).
- **Disconnected construct** is a first-class requirement: every adapter must be constructible (and schema-introspectable) without hardware or vendor runtime present — this is what the golden harness, preflight validator, and Linux CI import (§11).
- `DriverResponse` two-axis result (`response` = did this call work; `status` = driver state) kept verbatim, including `DriverStatus.retry` and the "empty `DriverResponse()` = skip this sample" poller sentinel (formalized, currently undocumented convention in the sensor pollers).
- Lifecycle promoted from convention to interface: `connect / get_status / arm(setup) / start(measure) / drain(get_data) / abort(stop) / cleanup / disconnect / estop / shutdown`, **async-first** (the ABC's sync declaration is violated today by Gamry `stop()`, Biologic `get_data()`; callers guess). Adapters wrap legacy sync drivers with explicit thread offload where needed.
- One `DriverResponse→ErrorCodes` mapping function in the port module (today duplicated in every executor phase).
- An explicit **exclusive-access primitive** (async context manager) for poller-vs-command contention on shared buses — replaces the ad-hoc `polling`-flag handshakes (AliCat, legato `_send_sync` fork, Advantech pause/resume) and the disabled Gamry poller.
- `DriverPoller` semantics preserved: poll cadence, `live_dict` merge + `last_updated`, and the **narrow `_base_hook` inversion collapses into the DataSink port** (a poller gets a sink, never a `Base`).
- **Readback fidelity is a declared axis, and "unknown" is a third value** [A1 §4.3]. A state read states whether it is measured from hardware or a mirror of the last write; an adapter may never present a mirror as a measurement (`galil_io` reads the controller per line; `nidaqmx` cannot read back a line held by a one-shot `Task` and returns its own write mirror). A value the process has not written reports `None`, and `None` must not render, serialize, or compare equal to `False` — the coercion belongs in one tested function, because a vendor readback of the *string* `" 0.0000"` is truthy.

#### 4.3.2 DataSink (thread-safe)
The formalization of what executors/drivers actually need from `Active` — precedent: `cNIMAX.arm_cell_iv(...)` receiving plain callables (`enqueue_data_nowait`, `get_realtime_nowait`, `finish_hlo_header`), the best-in-tree pattern. Surface: `enqueue(datamodel)` / `enqueue_nowait(...)`, `realtime_ns()`, `finish_hlo_header(...)`, `write_file(...)`/`write_file_nowait(...)`, `track_file(...)`, `append_sample(...)`, `split(...)`, `set_estop()`, `put_lbuf(...)`/`get_lbuf(key)`. **Thread-safety is contractual**: the NI-DAQmx hardware buffer callback runs on a foreign thread and must be able to call the `_nowait` members safely; the port spec states which members are loop-affine and which are thread-safe. This port replaces the `active.base.app.driver...` object-graph handouts (72 `active.action` reach-ins, 18 full-`Base` reach-ins in hte alone) and the PAL per-job injected `Active`.

#### 4.3.3 ArtifactStore
Abstracts `MetaFileWriter` + `DataFileWriter`/`DataStreamer` file side + `move_dir` + `yml_finisher`. Semantics (all parity-critical, from §5):
- Atomic yml writes (temp file + `os.replace`), trailing newline, `file_type:` first key.
- **Lazy HLO open on first data item** for a file_conn_key; header (`HloHeaderModel.clean_dict()`) at open; `%%\n` before first data row; one JSON object per line (`hlo_json_dumps`; non-serializable payload ⇒ `{"error": ...}` line); NaN/Infinity tokens legal; **no data ⇒ no file**; `w+` truncate on open; close at finish (or `substitute`).
- One-shot files: mode `a+`, `header + "%%\n" + payload`, FileInfo appended at write; gated by `save_data`.
- `finish()` **joins the write queue** before closing handles (drain protocol §5.4; late data beyond the bounded retries is dropped exactly as legacy drops it).
- `move_dir` promotion: recursive glob for actions / top-level for exp+seq; `.hlo` with `sync_data=False` diverted to RUNS_NOSYNC; manual → RUNS_DIAG; 60×/30× copy/remove retries; then DB-server `/finish_yml?yml_path=...` handoff; **fire-and-forget task semantics preserved** (transient ACTIVE/FINISHED splits are normal; the syncer's child-gating absorbs them).
- Zip (`zip_dir`: entries relative to seq dir, `.prg` included, `.lock` skipped, source dir deleted), parquet (≥1 GiB hlo), micro-orch `MANIFEST.txt` zips.
- Post-processor hooks (`hlo_postprocessors` replacing `action.files`; `MetaProcessor` seq/exp postprocessors) run at the same lifecycle points — including their non-standard outputs (file-type renames `helao__file`→`csv__file`, `.hlo` deletion by `spec_melt_wls`, multi-file parquet datasets), which the artifact model must allow.

#### 4.3.4 Sync
Abstracts `HelaoSyncer`/`SyncDriver`: `enqueue_yml`, the per-yml `sync_yml` pipeline (hierarchical seq-RW/exp-mutex locks, children gate with estopped-children-terminal rule, priority re-enqueue with rank floor −5, file push, process reconcile+flush writing `-prc.yml`, patched meta JSON, `.lock` cleanup, move-to-SYNCED, empty-dir pruning, destructive sequence zip, optional auto-analysis dispatch), `.prg` sidecar lifecycle, `reset_sync` reversal. S3 sub-port: key templates + payload shapes of §5.6; retries ≤5 × 30 s via `asyncio.to_thread`; unset S3 config ⇒ local-only success. The Sim DB server (§6.3) implements this port's S3 face with a recording sink.

#### 4.3.5 Transport (ZMQ-first + HTTP fallback)
Abstracts `helao/helpers/dispatcher.py` + `helao/core/rpc/zmq_rpc.py`. Full contract in §7. Non-negotiables: **co-located RPC server on `http_port + 10000` mirroring every POST route is mandatory for every hexagon server** (a plain FastAPI server makes each incoming private dispatch eat the 3 s probe timeout — the operator 5 s-blank-render incident, fixed 88256e0f); in-process self-ops (never self-RPC from the dispatch loop); RPC-bypasses-queuing-middleware semantics preserved.

#### 4.3.6 Status (WS pub/sub + push, dual stack — **three consumer faces** [A1 §8])
All parallel WS mechanisms survive (consumers exist for each): (1) `WsPublisher`-backed `/ws_status` `/ws_data` `/ws_live` routes consumed by Bokeh visualizers via `WsSubscriber`; (2) `_ws_relay` streams sending **zstd-compressed pickle** of `msg.as_dict()` (wire-format parity constraint for existing remote subscribers); (3) the Reflex stack's `reflex/ingest.py` normalizers, **keyed by `ws_path` rather than uniform across channels** — `ws_live` relays a `{datalab: (value, epoch)}` dict while `ws_data` carries a pickled `DataPackageModel` whose samples sit at `.datamodel.data[key][column]`, and a single normalizer silently drops the other endpoint's messages with no error on either side. Plus the push path: full/filtered `ActionServerModel` POSTed to each registered client's private `/update_status` (≤5 retries; the legacy blocking 0.3 s per-client sleep is preserved as pacing behavior until post-parity); nonblocking executors push `/update_nonblocking` directly. Serialization happens **only in this adapter** (KEEP #4; `_json_clean` for JSON channels).

#### 4.3.7 Clock
NTP offset arithmetic: offset file `<root>/LOGS/ntpLastSync.txt` written by launch (`get_ntp_time`), read by `read_saved_offset` at Base init and by the logging formatter; `set_time(offset)` for every `*_timestamp`; `epoch_ns` stamping (at lazy file open **or** header finish — two legal code paths, goldens must not diff header epoch). Port exposes `now()`, `now_ns()`, `offset()`; the golden harness may inject a deterministic clock **only in unit fixtures**, never in capture runs.

#### 4.3.8 Logging (FAIL LOUD)
§9.1. One module, injected log root, no tempdir fallback, `<root>/LOGS/<server_key>.log` flat-file contract, daily gz rotation keep-90, dedup handler, ALERT level 60 email/webhook queue listeners, `configure-before-app-import` ordering.

#### 4.3.9 Config (raw-dict identity)
§9.2. The raw config dict is the runtime source of truth; object identity of `CONFIG["servers"][key]` with each server's `server_cfg` must be preserved (the `--restore` in-place mutation gate rides on it); typed `HelaoConfig` remains a validation gate only — never installed as the runtime dict (it drops launcher-added keys: `loaded_config_path`, `helao_repo_root`, `deployment`, credentials/alert paths).

#### 4.3.10 AnalysisArtifact
Unifies Deployment-C's **three divergent analysis writers** — core `analysis_driver.sync_ana`, the XAFS converter's inline re-implementation (drifted copy: hardcoded `dummy=False`, scalar-only short outputs), and quantification's plain-HLO third way — into one "publish an AnalysisRecord" port with one adapter producing the §5 row-13 layout (`ANALYSES/<yy.ww>/<mmdd>/<HHMMSS>__<name>[__<suffix>]/<analysis_uuid>.yml` + per-output JSONs + `analysis/<uuid>.json` (+`_output_<group>.json`) S3 keys, content-hash UUIDs via pydasher). Converters *enqueue* analyses; they never write the layout themselves.

#### 4.3.11 SampleState
The Archive boundary, aligned with the approved archive-hoist-to-SAMPLE-server plan: the boundary is **SAMPLE-server-behind-RPC**, exactly what PAL already consumes via `sample_shim.SampleArchiveShim` (fail-loud RPC client, call-time address resolution, typed rehydration — adopt its conventions for all inter-server ports). `Archive` (2451 lines: pickled `Positions` store, custom-position policy, dilution/assembly chemistry) is **never ported as a driver**; it becomes the SampleState adapter behind the SAMPLE server. Its `Base` coupling is only `helaodirs` ×3 + `UnifiedSampleDataAPI(base)` — mechanical to inject. The `params.positions` single-owner launcher rule carries over.

#### 4.3.12 Auxiliary ports
- **StatePersistence**: `queues.pck` export/import (pickle shape per core-01 §2 incl. `globalstatusmodel` — note runtime FSM state persists across restore, a parity behavior), import-archives-consumed-pck rule.
- **PlateInfo**: `PLATE_API` / `HTEPlateAPI` queries + plate gate (`verify_plates`).
- **Library**: dynamic import of experiment/sequence/postprocessor libs + codehash/codepath provenance; flat name-keyed registries with a **load-time collision check** (the CCSI/CSIL and `ECHEUVIS_postseq` silent-shadowing hazard becomes a loud preflight error, config-overridable for intentional shadowing).
- **Health**: HEAD-probe `endpoints_available`, `ping_action_servers`, heartbeat monitors (`active_action_monitor` default 10 s + `ignore_heartbeats`; driver-health `status_summary` gate).
- **Notify**: live buffer, `globstat_q`/WS relay, `LOGGER.alert`.

### 4.4 Adapters

Grouped by difficulty; each item names its split. Per-driver detail lives in the deploy audits; phase plans own the fine-grained work.

**Hardest (multi-way splits):**
1. **PAL (hte, 3236 lines) — 4-way split**: (a) *transport adapter* — SSH/Cygwin + local-subprocess method submission and process kill; (b) *trigger adapter* — NI TTL start/continue/done edges (consuming the nidaqmx adapter or a Trigger port, not raw `nidaqmx` inside PAL); (c) *sample-reconciliation policy* (~1500 lines of tray/custom/next-empty resolution) — domain logic beside the SampleState port, already speaking through the shim; (d) *job-context port* — the per-job injected `Active` (`split`/`enqueue_data`/`append_sample`/`write_file_nowait`/`set_estop`) becomes a DataSink handle; `PALJob.done`-event + error is the completion contract. The 13 `build_palcam_*` recipes + `robot/enum.py` CAM catalog port as declarative data. Busy-check-before-contain (rejects create no artifact) is preserved behavior.
2. **galil_motion (hte, 1744 lines) — 3-way split (D6)**: gclib motion Hardware adapter; pure `TransformXY` + calibration persistence behind a small storage port (JSON under states/db roots); the embedded Bokeh **Aligner extracted to a visualizer adapter** (`layouts/aligner.py` UI driven via `run_aligner`/`stop_aligner` endpoints; the aligner session talks to the motion server, not to a driver-held `Active`). Legacy `{err_code: ErrorCodes}` dict returns preserved at the endpoint surface.
3. **ThorlabsMotor (Deployment-A, 1706 lines) — same 4-way split as galil_motion**: Kinesis adapter + shared `TransformXY` domain + calibration-store port (per-hostname JSONs) + aligner visualizer adapter (driver currently starts a Bokeh `Server` thread inside `connect()` — banned by D6).
4. **Archive → SampleState adapter** (§4.3.11).
5. **Gamry — COM apartment adapter** (§11.2): dedicated STA thread owned by the adapter; `sys.coinit_flags` out of module import; PumpEvents loop + event sinks on that thread; `kill_gamrycom`/reset as adapter-supervisor concern; DC/dtaq vs EIS/ReadZ vs idle-poller as strategies behind one adapter (today `stop()` must know which path is live). The declarative technique/signal/dtaq/range catalogs port as data.

**Standard:** the remaining ~30 conformant drivers (galil_io incl. DMC code-gen as declarative toggle-program value object, biologic with the easy-biologic private-API pinned shim, alicat with vendor fork extracted, nidaqmx→DataSink exemplar, kinesis/legato/simdos/sensors/mecom/synaccess/spec/andor per audit notes, Deployment-A stenner/advantech/elveflow/ml/calc, Deployment-B actuator/UR10e/OPC-UA). Contract drift and internal defects catalogued in deploy-hte-drivers-A/B §2–3 are fixed inside adapters **only where invisible to wire/disk**.
**Framework adapters:** artifact writers + syncer (wrapping today's `base_meta_writer`/`active_data_file`/`active_data_stream`/`active_finalizer`/`sync_driver` behaviors), dispatcher (ZMQ+HTTP), logging, config loader, NTP clock, state persistence, Bokeh vis subscribers (`vis_subscriber` stack), operator backends, sim DB server (§6.3), fakes (opt-in). **UI hosting for either stack is P7-UI, not P0–P6** (D9): during those phases the Bokeh visualizers/operator/browser and the Reflex app remain legacy-core consumers of the hexagon servers' wire surface. The one exception already in-tree is the D6 aligner visualizer adapter, which constructs its own Bokeh `Server` inside an action-server process — P7-UI folds it behind the UiHost port [A1 §6].
**Inbound adapters:** FastAPI action-route wrapper (ActionAPIRoute kwargs→Action envelope + `ACTION_CTX`; the `app_entry` queueing middleware with per-endpoint zdeques, `queued_on_actserv`, requeue-with-`no_wait`+`queued_launch` semantics), private routes, RPC dispatcher, dyn-endpoint registration (config-shaped signatures from driver device maps — `drv.dev_mfcs` etc. — are a load-bearing contract), `@action_version` stamping.

### 4.5 App / composition

- `app/factory.py`: `makeApp`/`makeActionApp`/`makeOrchApp`/`makeVisApp` — the **only** layer constructing FastAPI/Bokeh objects and wiring adapters into ports per config. Composition **raises at startup on any unwired port** (F2b countermeasure) — there are no default fakes.
- Launcher integration: reuse the existing per-server `deployment:` key mechanism (fast/bokeh launchers) with a reserved value routing to the hexagon factory; per-config atomic cut-over; **offline preflight validator** (config sanity + endpoint-parity checklist + library collision check + port-wiring completeness, runnable with disconnected adapters on Linux); canary-first risk-ordered station rollout (all KEEP #6).
- The dispatch loop lives here: single long-lived task parked on `asyncio.Event`, draining reducer commands; in-process routing for self-ops.
- Both launch paths preserved: launcher-managed groups AND `append.py` merge; hotkeys, PID pickles, graceful-kill timing (§9.4), hot-reload watcher compatibility (`/loaded_modules` + bokeh `STATES/loaded_modules_<key>.json` snapshots).

---

## 5. Artifact inventory — the parity contract

This section is normative. Source of truth: core-04 (verified against `sync_driver.py`, `yml_tools.py`, `hlo_data.py`, `base_meta_writer.py`, `active_data_file.py`, `active_data_stream.py`, `active_finalizer.py`, `orch_lifecycle.py`/`orch_estop.py`, `helaodict.py`, models). All roots/buckets are templates.

### 5.1 Directory-path grammar

Config `root:` → `helao_dirs()` creates `<root>/{RUNS_ACTIVE, LOGS, STATES, DATABASE, USER_CONFIG/{EXP,SEQ}, ANALYSES, PROCESSES}`. `save_root = <root>/RUNS_ACTIVE`. State dirs = `RunDir` enum `RUNS_ACTIVE | RUNS_FINISHED | RUNS_SYNCED | RUNS_DIAG | RUNS_NOSYNC`; sync progression ACTIVE→FINISHED→SYNCED; **state transitions are literal string substitution of the `RUNS_*` path segment** — everything below is invariant.

| Level | Template |
|---|---|
| sequence | `<YY.WW>/<MMDD>/<HHMMSS>__<sequence_name>__<sequence_label>[-<plateN><cksum>[-<sampleno>]]` — `YY.WW` = `%y.%U`; plate suffix only when `plate_id` in sequence_params and not already in the label; checksum = digit-sum mod 10 |
| experiment | `<seq_dir>/<YYMMDD.HHMMSS>__<experiment_name>` — `%y%m%d.%H%M%S`, no µs |
| action | `<exp_dir>/<orch_submit_order>__<action_split>__<server_name>__<action_name>` — forward slashes always |

Manual actions (no parent seq/exp): synthetic `seq--<action_name>` / `exp--<action_name>`, label `manual`, `access="manual"`, whole tree under **RUNS_DIAG** (terminal; never synced; `manual_orch_seq` filtered by the syncer's pending lists).

### 5.2 Artifact taxonomy (path • writer • when • content)

| # | Artifact | Path/filename template | Writer | When (timing is contractual) | Content schema |
|---|---|---|---|---|---|
| 1 | `-seq.yml` | `<state>/<seq_dir>/<%y%m%d.%H%M%S%f of sequence_timestamp>-seq.yml` | `MetaFileWriter.write_seq`, driven by Orch (`orch_lifecycle`/`orch_estop`) and `finish_manual_action` | S1 at sequence activation (dequeue, after planned_experiments resolution, BEFORE plate gate/unpacker); S2 rewritten inside `finish_active_experiment` after appending the exp snapshot, BEFORE the final exp write; S3 final at `finish_active_sequence` (after all actions idle; status→finished, finished ts, `finished_global_params`, seq postprocessors); S4 estop variant | `file_type: sequence` + `SequenceModel.get_seq().clean_dict()` — hlo_version, sequence_uuid/name/label/params/comment, access, dummy, simulation, run_type, sequence_timestamp, sequence_status[], sequence_output_dir, codehash/codepath/funcname, finished_timestamp, planned_experiments[], dispatched_experiments_abbr[], files[], aux_files[], data_request_id, orchestrator{}, campaign fields, run_id, sync_data, manual_action, initial/finished_global_params |
| 2 | `-exp.yml` | `<state>/<exp_dir>/<%y%m%d.%H%M%S%f of experiment_timestamp>-exp.yml` | `MetaFileWriter.write_exp` | E1 at experiment activation (after action expansion, BEFORE plate gate, before actions hit `action_dq`; snapshots `initial_global_params`); E2 final at `finish_active_experiment` (all actions idle + nonblocking executors stopped; seq updated FIRST per S2); E3 estop variant (idempotent mark, does not wait for actions inline) | `file_type: experiment` + `ExperimentModel` incl. uuid/name/params/output_dir, orch identity, experiment_status[], code provenance, finished_timestamp, dispatched_actions_abbr[] (ShortActionModel), samples_in/out[] (rebuilt from dispatched actions on every `get_exp()`), files[] (aggregated FileInfo), process_list[], process_order_groups{pidx:[orders]}, initial/finished_global_params |
| 3 | `-act.yml` | `<state>/<act_dir>/<%y%m%d.%H%M%S%f of action_timestamp>-act.yml` | `MetaFileWriter.write_act` (gated `save_act`), **action-server side** (Orch never writes it for remote actions; the orch writes its own for self-hosted wait/conditional actions) | First at `Active.myinit`; may be rewritten anytime via `update_act_file`; final rewrite (same filename, atomic tmp+`os.replace`, last-writer-wins) in `_finish` just before `move_dir` | `file_type: action` + `ActionModel.clean_dict()`: action_uuid/output_dir/actual_order, orch_submit_order, action_server{}, orchestrator{}, action_timestamp/status[]/order/retry/split, action_name/sub_name/abbr, **action_params (bit-exact, D7)**, action_output, code provenance, finished_timestamp, parent/child_action_uuid, samples_in/out[], files[] (FileInfo), exec_id, technique_name (str **or list** on disk), process_finish/contrib[]/uuid, error_code, run_use, sync_data, campaign/run ids, start_condition, save_act/save_data, aux_file_paths[], from_global_act_params, to_global_params — note the dispatch-control fields ARE serialized despite the in-code "not in ActionModel" comment |
| 4 | `.hlo` (streamed) | `<state>/<act_dir>/<action_abbr>-<orch_submit_order>.<action_order>.<action_retry>.<action_split>__<filenum>.hlo` (`filenum` = index of file_conn_key in `action.file_conn_keys`) | `DataFileWriter.log_data_set_output_file` + `DataStreamLogger` | **Lazily created on FIRST data item** for that file_conn_key (mode `w+`); header at open; `%%\n` before first data row; closed at `_finish` step 3 or `substitute()` | YAML header = `HloHeaderModel.clean_dict()` (hlo_version, action_name — abbr preferred, column_headings[] = json_data_keys, optional{} instrument dict, epoch_ns) then `%%` then one JSON object per line (columns → scalar-or-list); NaN/Infinity tokens legal in body; missing `json_data_keys` inferred from the first message's keys |
| 5 | one-shot files | same name template; `.hlo` for `HloFileGroup.helao_files`, `.csv` for aux; or caller-supplied name | `DataFileWriter.write_file(_nowait)` (gated `save_data`) | any time during the action; mode `a+`, `header + "%%\n" + output_str` | FileInfo appended to `action.files` at write |
| 6 | `FileInfo` (embedded) | inside `files[]` of act/exp/prc ymls | `init_datafile` / `track_file` | streamed: at lazy open; one-shot: at write; tracked: at `track_file` (`relocate_files` copies external files in — driver-invoked, not automatic) | `{action_uuid, run_use, sample[global labels], file_name, file_type (default helao__file), data_keys[], nosync}` — `nosync=True` for `.hlo` when `action.sync_data` false |
| 7 | `-prc.yml` | `<root>/PROCESSES/<YY.WW>/<MMDD>/<seq_dirname>/<exp_dirname>/<pidx>__<process_uuid>__<technique_name>-prc.yml` (dir = dirname of the exp-yml's RUNS-relative path) | `SyncDriver.sync_process` | during **experiment sync**, once a process group's contributing actions are all synced (or force) | `ProcessModel.clean_dict(strip_private=True)`: process_uuid, sequence/experiment_uuid, orchestrator, access, dummy, simulation, technique_name, run_type/use, process_timestamp (= first contributing action_timestamp), process_params (= experiment_params), process_group_index, data_request_id, dispatched_actions_abbr[], samples_in/out[] (deduped by global_label: in keeps earliest contributor, out keeps latest), files[], campaign/run ids. When an exp has no `process_list`: `process_uuid = uuid5("<experiment_uuid>__<pidx>")` (deterministic given experiment_uuid) |
| 8 | `.prg` sidecar | `<RUNS_SYNCED>/…/<yml stem>.prg` (suffix swap; **always under SYNCED even while the yml is still in FINISHED**) | `Progress` (syncer) | created on first sync attempt; updated every step; ends up **inside** the sequence zip | YAML: `yml` (abs path), `api: bool`, `s3: bool`; actions add `files_pending[]/files_s3{}`; experiments add `process_actions_done{}, process_groups{}, process_metas{}, process_s3[], process_api[], legacy_finisher_idxs[], legacy_experiment` |
| 9 | `.parquet` | sibling of `.hlo` (suffix swap) — only for hlo ≥ 1 GiB, during sync | `hlo_to_parquet` via syncer | during action file push | parquet with the hlo header's `optional` dict JSON-embedded under schema-metadata key `helao_metadata` |
| 10 | sequence `.zip` | `<RUNS_SYNCED>/<YY.WW>/<MMDD>/<seq_dirname>.zip` — the synced dir is **DELETED** after zipping | `zip_dir` via syncer | after the whole sequence tree is synced | entries relative to seq dir (`.prg` included, `.lock` skipped); `reset_sync` renames zip → `.orig` |
| 11 | `.lock` files | anywhere in act dirs | drivers/executors | during run | ignored everywhere: excluded from misc/hlo lists, deleted before move-to-synced, skipped by zip_dir |
| 12 | micro-orch archive | caller-chosen `<name>.zip` | `runners/micro_orch.zip_runs` | on demand (runner path only) | tree relative to RUNS_FINISHED/RUNS_DIAG + `MANIFEST.txt` (sorted arcnames) at root — the localfs loader keys on MANIFEST.txt presence |
| 13 | analysis yml + json | `<root>/ANALYSES/<YY.WW>/<MMDD>/<HHMMSS>__<analysis_name>[__<seq_label\|plate+cksum>]/<analysis_uuid>.yml` + one local `.json` per declared output group | `analysis_driver.sync_ana` (sole writer after P6 unification — §4.3.10) | on auto/manual analysis | `AnalysisModel` dict; outputs key-filtered dicts; scalar/array split by `isinstance(v, list)` |
| 14 | logs/state (non-parity) | `<root>/LOGS/<server_key>.log` (+ `.log.<date>.gz`), `<root>/LOGS/ntpLastSync.txt`, `<root>/STATES/*.pck`, `STATES/loaded_modules_<key>.json` | logging/launch/orch_persist | startup/shutdown | out of artifact-parity scope but **path-contractual** (§9.1); behavior-tested, not diffed |
| 15 | **none — direct hardware control** (negative row) [A1 §4.1] | *(no artifact)* | `io_control.set_digital_out` via a server's private `/set_digital_out` | on operator click, any time, including mid-run | **Nothing is written**: no action, no `-act.yml`, no HLO, no run record, no status push; the response carries the post-write readback. Normative as a negative: the harness asserts that driving a digital output through the control surface leaves the tree **unchanged**. A hexagon implementation that logged a control toggle as an action would pass every other check while writing rows no legacy run contains |

### 5.3 YAML formatting + clean_dict contract

`yml_dumps`: ruamel round-trip dumper, indents mapping=2/sequence=4/offset=2, duplicate keys allowed, `None` → literal `null`, trailing newline enforced by the meta writer. `clean_dict()` recursively **drops** None, empty strings, empty lists, empty dicts; Enum→`.name`/value per HelaoDict, UUID→str, datetime/Path→str, numpy scalars→python, NaN→None, float rounding; skips FunctionType values and `__`-prefixed string keys; `strip_private` (drops `_`-prefixed keys) applies to **S3/API payloads and `-prc.yml` only**, NOT to on-disk act/exp/seq ymls. Consequence: key presence is data-dependent — **the parity comparator must treat "absent" and "empty" as equal**. Byte-parity is measured post-clean_dict, never on `model_dump()` JSON.

### 5.4 Lifecycle timing + ordering invariants (contractual)

1. seq yml exists on disk **before** any of its experiments; exp yml exists **before** any of its actions dispatch (syncer/operator rely on the tree shape).
2. On exp finish: seq yml (with the new `dispatched_experiments` entry) is written **before** the final exp yml; exp `move_dir` runs as a background task after.
3. `-act.yml` is written at `myinit` and **rewritten (atomic replace, same filename)** at finish carrying files/statuses/finished-timestamp — the syncer depends on the final rewrite.
4. Action finish drain protocol: enqueue empty finished-status packets until every action's `data_stream_status != active` (≤5 × 0.1 s), then wait `num_data_queued <= num_data_written` (≤5 × 0.1 s) → close every open file handle → cancel data logger → hlo postprocessors (may rewrite `files[]`) → final `write_act` → final status broadcast → fire-and-forget `move_dir`. Late data beyond the window is silently dropped (legacy behavior, preserved).
5. `move_dir` of exp/seq copies top-level files then rmtree's — the clean path has already waited for actions idle; the estop path polls ≤30 s for child dirs to vacate, else leaves the record in RUNS_ACTIVE for `finish_pending`.
6. Estop terminal status is `[finished, estopped]` (never bare `[estopped]`); close-out guards ensure no double-finalization; **no fabricated placeholder artifacts**.
7. `finish_active_sequence` clears `counter_dispatched_actions` wholesale; `last_*` deepcopies precede nulling `active_*`.
8. Exp/seq ymls are rewritten multiple times; **only the final content is contractual** (atomic writer exists because torn writes were observed) — but write *events* S1/S2/E1 must still occur (invariants 1–2 depend on them).
9. Split (`action_split` bump): new uuid/timestamp/**new output dir**, parent/child uuid links, fresh FileConns (new md5(epoch_ns) keys), listen-uuid swap stops writes to the old hlo, counters reset — a golden scenario covers split if any migrated deployment uses it (PAL does).
10. `epoch_ns` stamped at lazy open **or** header finish (two legal paths) — normalizer ignores it.

### 5.5 Volatile fields — the normalizer contract (exhaustive)

The parity normalizer MUST normalize/ignore exactly this list and nothing more (an over-broad normalizer re-creates F1 by masking real diffs; additions require a spec change):

**Identity & time:** every `*_uuid` (action/experiment/sequence/process/campaign, `run_id`, `data_request_id`, parent/child_action_uuid, per-sample `action_uuid` lists, FileInfo `action_uuid`) — uuid7 time-seeded; **exception with structure**: process_uuid = uuid5(`"<experiment_uuid>__<pidx>"`) when no process_list — deterministic once experiment_uuid is mapped, so normalize by uuid-mapping, not blanket-ignoring (this checks the derivation). Every `*_timestamp`/`*_finished_timestamp` (µs datetimes, NTP-corrected), `epoch_ns`, `process_timestamp`. ALL path/filename components derived from timestamps (`YY.WW/MMDD/HHMMSS…` dir levels, `<ts>-{act,exp,seq}.yml` filenames, `*_output_dir` fields) — compare trees by **shape + timestamp-stripped names**. Time-of-run data columns inside `.hlo` bodies (tick times, epochs, `record_time_local`/`elapsed_time` recorder columns).

**Environment & code identity:** `*_codehash/codepath/funcname` (abs host path; hash changes per commit), `hlo_version`, `orch_key/host/port`, `MachineModel` contents (hostname-bearing), `aux_file_paths` (absolute), `.prg` `yml` field (absolute), `files_s3` values (embed action_uuid), `exec_id`, `action_etc`, `dummy`/`simulation` flags, `access`, log/STATES artifacts entirely.

**Ordering/presence hazards (normalize, don't just ignore):** clean_dict empty-pruning ⇒ absent == empty; `samples_in/out` dedupe order keyed by dispatch order; `files[]` follows write order; `dispatched_*_abbr` follows completion order (concurrency-variable — sort by a stable key before diffing); `technique_name` list→str split patch applied **only** in S3/API/prc copies, not the on-disk act yml; FileInfo `file_name`/`file_type` rewritten in the S3 meta copy (`x.hlo` → `x.hlo.json` basename; `helao__file` → `helao__<ext>_file`) — on-disk yml and S3 JSON **intentionally differ** and the harness asserts the difference, not sameness; `.prg` ranks/retry bookkeeping + `legacy_experiment` flag; unseeded sim data values (WsSim `np.random`) — diff structure/columns/counts with value masking.

### 5.6 S3 / DB payload shapes (templates)

No S3 config ⇒ `to_s3` returns True (sync completes locally). Uploads retried ≤5× / 30 s sleeps via `asyncio.to_thread`. **API leg is a stub** (`to_api` returns True unconditionally even with `api_host` set) — the `.prg` `api: true` flag carries no external guarantee; observable surface = S3 payloads + on-disk tree.

| Payload | S3 key template | Body |
|---|---|---|
| streamed hlo (<1 GiB) | `raw_data/<action_uuid>/<hlo_filename>.json` (+`.gz` if compressed) | `{"meta": <hlo header dict>, "data": {col: [values]}}` |
| hlo ≥1 GiB | `raw_data/<action_uuid>/<hlo_stem>.parquet` | parquet upload (`helao_metadata` schema key) |
| misc/aux file | `raw_data/<action_uuid>/<path relative to act dir, posix>` | raw file |
| action meta | `action/<action_uuid>.json` | `ActionModel.clean_dict(strip_private)` after `exid→exec_id` patch + technique split + FileInfo rename rule |
| experiment meta | `experiment/<experiment_uuid>.json` | ExperimentModel… + `process_list` injected from synced process_metas (sorted by pidx) |
| sequence meta | `sequence/<sequence_uuid>.json` | SequenceModel… |
| process meta | `process/<process_uuid>.json` | `ProcessModel.clean_dict(strip_private)` |
| analysis | `analysis/<analysis_uuid>.json` + `analysis/<uuid>_output_<scalar\|array>.json` | model dict / key-filtered outputs |

DB-server HTTP surface (all POST, query params): `/finish_yml`, `/list_pending`, `/finish_pending`, `/reset_sync`, `/tasks`, `/list_exceptions`, `/n_queue`, `/current_progress` + BaseAPI stock endpoints.

### 5.7 Parity definition (summary)

For a **quiesced** run (all fire-and-forget moves settled; the harness polls the DB server's `/n_queue`+`/tasks` to zero before snapshotting): identical RUNS_SYNCED zip *member set* (timestamp-normalized names); identical normalized YAML content for `-seq/-exp/-act/-prc.yml` (post-§5.5, absent==empty); byte-identical `.hlo` header-structure + `%%` + JSON-lines body modulo volatile columns; identical PROCESSES tree shape; identical S3 key *templates* + payload shapes against the recording sink. `.prg` files: compare only terminal `s3`/`api` booleans. RUNS_DIAG trees compared for the manual-action scenario. RUNS_NOSYNC placement asserted for the `sync_data=False` scenario.

---

## 6. Golden-master procedure

### 6.1 Principles

1. **Real runs only (D4).** A golden master is the artifact tree + recorded sync payloads of an actual legacy launch. Hand-authored fixtures are forbidden in the parity suite; the harness records a **provenance manifest** per golden set (config used, git SHA of legacy code, launch command, sequence submitted, capture timestamp, harness version) and refuses fixture directories without one.
2. **Per-milestone gate, not pre-deletion afterthought.** The normalized diff runs in CI-able form (single command) and is a named acceptance criterion of every phase gate.
3. **Determinism first.** P0's baseline gate is legacy-vs-legacy: two independent legacy capture runs must be normalized-identical. If they are not, the normalizer (or a determinism lever) is wrong — fix before any rewrite code is measured. Known levers: fixed `wait_time`/`data_duration`, seeded GPSIM (`random_seed`), value-masked WsSim columns, quiesce-before-snapshot.

### 6.2 Linux capture rig (test deployment)

All commands inside the `helao` conda env (`conda run -n helao …`), `PYTHONPATH` at repo root.

1. **`golden.yml`** — an uncommitted-then-committed capture config: copy `helao/deploy/test/configs/test.yml`, set `root:` to a Linux capture area (tracked configs use `C:/INST_hlo`), drop `launch_browser: true`, **add a `DB` server entry** hosting the sim DB server (§6.3). Keeping it in-tree preserves launcher deployment auto-detection. Launch with `--no-hot-reload` so a stray commit can't restart servers mid-capture. Note the cross-deployment resolution: test configs pull `async_orch2`, `standalone_operator`, `live_visualizer`, `action_visualizer` from `hte` by launcher glob — golden runs therefore exercise the production orchestrator/operator/visualizer code, by design.
2. **Scenario set** (each an independently captured golden):
   - **GM-1 (primary):** a Sequence wrapping `SIM_websocket_data` (simulatews_exp) — richest artifact mix: streamed hlo files, **two `-prc.yml` per experiment** (`process_contrib=[files, run_use]` + `process_finish=True` twice), `hlo_to_csv` postprocess csv + file-type rename, `append_params` seq/exp postprocessor effects, orch `wait` actions.
   - **GM-2 (scheduling):** `TEST_consecutive_noblocking` — nonblocking waits, `wait_for_*` start conditions, seq-level global-param handoff (`from_global_exp_params` across cycles).
   - **GM-3 (manual/diag):** one direct (non-orch) action POST to the SIM server — synthesized `seq--`/`exp--` parents, RUNS_DIAG tree, `finish_manual_action` ymls.
   - **GM-4 (lifecycle edges):** a run exercising stop-intent drain, skip, and a no-data action (executor that streams nothing → **no `.hlo`**), plus an estop mid-experiment (`/estop_orch`) → `[finished, estopped]` artifacts and deferred promotion.
   - **GM-5 (sync leg):** GM-1's tree carried through the sim DB server: `.prg` lifecycle, `-prc.yml` under PROCESSES, RUNS_SYNCED zip member set, recorded S3 key/payload set, `finish_pending`/`reset_sync` round-trip.
   - **GM-6 (tier 2, optional):** `OERSIM_activelearn` on demo0 (seeded) — self-requeue via `insert_experiment`, multi-server flow. Requires gpflow; structure-level diff only (GP timing varies).
   - **GM-7 (runner path, if runners are migrated):** `simulatews_runner` MicroOrch run + `zip_runs` MANIFEST zip.
3. **Submission** is programmatic (the `multi_orch_demo_helper.py` pattern): build the `Sequence`, `private_dispatcher(... "append_sequence", json_dict={"sequence": seq.as_dict()})`, then `"start"`. Poll `/global_status` until `loop_state == "stopped"` and queues drained; poll DB `/n_queue`+`/tasks` to zero; then snapshot `<root>` (RUNS_*, PROCESSES, recorded-S3 dir) into the golden store with the provenance manifest.
4. The same rig re-runs unchanged against a hexagon-composed group (same config, `deployment:` key flipped) — capture, normalize, diff.

### 6.3 Sim DB/sync server (D5) — P0 deliverable

A test-deployment action server (`sim_db_server`) whose server key is `DB` (the literal key gates `HelaoSyncer` instantiation in `orch.py:117-119`) that hosts the **real** `HelaoSyncer` with:
- `aws_bucket` param set (constructor hard-requires it, `sync_driver.py:728`) but **no** `aws_config_path` → S3 session None. Two modes: (a) *local-only* — verify the RUNS_SYNCED move completes with no S3 (deploy-test flags this as needing a verification run — P0 task); (b) *recording* — an injected S3-recorder object (same duck surface as the boto3 client the syncer uses) that writes every upload to `<root>/S3_SIM/<bucket>/<key>` and logs `(key, content-type, gzip?)` to a manifest. The recorder is an adapter of the Sync port's S3 face — the same object later serves the hexagon syncer, so both stacks are recorded identically.
- The stub API leg untouched (`to_api` → True).
- The full dbpack HTTP surface (`/finish_yml` … `/current_progress`) so `move_dir`'s `yml_finisher` handoff and harness quiescing work unmodified.
- Windows-tolerant so at-station captures (§6.6) can wire the same server.

If injecting the recorder requires a seam in legacy `sync_driver.py`, the allowed change is a constructor-level client override (default = current behavior) — a reviewed, minimal legacy patch; no behavior change when unset.

### 6.4 Normalizer

A pure library (`harness/normalize.py`) + CLI implementing §5.5 exactly:
- Tree pass: strip timestamp components from dir/file names per the §5.1 grammar; map uuids to stable ordinals **per capture** (uuid-mapping, so uuid5 process derivations and parent/child links are *checked*, not ignored); classify files by artifact row (1–13).
- YAML pass: load, apply volatile-field normalization, canonicalize (absent==empty; stable sort for the documented ordering hazards; everything else order-preserved), re-dump canonical.
- HLO pass: header dict normalized (epoch_ns dropped, hlo_version dropped); `%%` split verified; body compared line-by-line as parsed JSON with volatile columns masked per a per-scenario column list (the column list lives in the golden's provenance manifest, not in harness code).
- S3 pass: key-template match (uuid-mapped), payload normalization same as YAML pass, FileInfo rename rule asserted.
- Output: a machine-readable diff report (per-file, per-key) + exit code. **Any unnormalized diff fails.** The normalizer has its own unit tests pinned by the legacy-vs-legacy baseline captures.

### 6.5 Gate mechanics + fixture provenance

- `python -m harness.parity --golden <set> --candidate <root>` is the single gate command; phase gates cite its run ID.
- Golden sets are stored under a dedicated location (repo LFS or an untracked share — Open Question Q2) with their provenance manifests; the harness hard-fails on a manifest-less golden (F1 countermeasure).
- Unit-test fixtures throughout the hexagon suite that represent artifacts/wire frames must be **derived from capture** (extracted from a golden set by a documented script), not typed in. Code review enforces; the boundary test can grep for a `# fixture-source:` provenance comment convention.
- Golden refresh: when legacy `unstable` intentionally changes an artifact (it still evolves), re-capture and re-baseline; the manifest's legacy SHA makes staleness visible.

### 6.6 Hardware-only deployments (hte, Deployment-A, Deployment-B)

These cannot capture on Linux (gclib/comtypes/NI/BDaq/DLLs; Deployment-B has zero Linux-launchable configs). Procedure:
- **At-station capture, pre-migration:** before a station's cut-over window, run the station's designated smoke sequence(s) on legacy at the station, with the sim DB recorder wired (or the station's real DB config plus tree-only capture), snapshot the root, normalize, store as that station's golden with provenance.
- **At-station diff, post-migration:** run the identical sequence(s) on the hexagon composition in the same window; diff on the spot. This is a **gate for the station**, executed during the canary/rollout runbook (KEEP #6). The eche10 "data-vs-legacy diff" that the old attempt left forever-open becomes a mandatory checklist line with a stored report.
- Deployment-C is Linux-capturable via its batch/analysis path (P6 gate): golden = converted sequence trees + ANALYSES trees + recorded analysis S3 payloads from real drop-folder inputs (sanitized copies).
- Scenario choice per station comes from the phase plan's risk-ordered runbook; each must cover at least: one streamed-hlo action, one process-producing experiment, one estop, and that station's highest-traffic sequence.
- **No control panel is operated during either window** [A1 §4.2]. Row 15 changes hardware state without changing the tree, so a toggle mid-capture alters what the next sequence measures with nothing in the diff to show it — undetectable after the fact, which is why the provenance manifest (§6.5) carries a signed-off `control_surface_idle: true` field. Procedural gate, not a code gate.

---

## 7. Wire / dispatch contract

Normative; abstracted by the Transport and Status ports, implemented by the dispatcher adapter. Source: `helao/helpers/dispatcher.py`, `helao/core/rpc/zmq_rpc.py`, `helao/helpers/server_api.py:87-119`, core-01 §3–4.

### 7.1 RPC (ZMQ) fast path
- Port pairing: `derive_rpc_port(http_port) = http_port + 10000` (`RPC_PORT_OFFSET`). Endpoint `tcp://<host>:<port+10000>`.
- Clients: one cached `RPCClient` (DEALER, id-correlated futures, concurrency-safe) per `(host, port)` async; one `RPCSyncClient` (REQ) per peer sync; explicit teardown functions.
- `_RPC_PROBE_TIMEOUT = 3.0` s; call timeout `min(timeout, 3.0)`. A DEALER to a dead peer queues silently — **the timeout IS the down-detector**. Fallback triggers on `RPCError | asyncio.TimeoutError | zmq.ZMQError | OSError`.
- **Co-location requirement:** every hexagon FastAPI server constructs an RPC dispatcher at startup that mirrors **every registered POST route**, serves on `derive_rpc_port(port)`, closes at shutdown. Composition fails preflight if absent (memory: plain-FastAPI servers caused every peer dispatch to eat the 3 s probe — the operator blank-render incident).
- Arg coercion (`_coerce_args`): match by parameter name, rehydrate pydantic models, and resolve string annotations via `inspect.get_annotations(eval_str=True)` — with a test in a future-annotated module (KEEP #9).

### 7.2 Action dispatch
`async_action_dispatcher(world_cfg, A, params={}, timeout=60, retries=5)`:
- Destination from `world_cfg["servers"][A.action_server.server_name]` (host/port resolved at call time).
- RPC method = `"<server_name>/<action_name>"`; kwargs = `params ∪ {"action": A.as_dict()}`.
- HTTP fallback: `POST http://host:port/<server>/<action>`, query = params, json body = `{"action": A.as_dict()}`; up to 5 retries, backoff `retry_count * timeout / 2`, fresh force-close `TCPConnector` per attempt.
- Returns `(response_json | None, ErrorCodes)`.
- **Semantic difference preserved:** the HTTP path traverses BaseAPI's action-queuing middleware (colliding POSTs get queued, immediate queued-action response); **the RPC path bypasses it** (orch-side endpoint coordination via start conditions is assumed). The hexagon inbound adapter must reproduce both behaviors.
- Endpoint naming is `/{server_key}/{action_name}` with private endpoints at root — the old attempt's `run_action` default + flat payload were both wrong and masked by hand-rolled test fixtures (AVOID #5); §10.1's fixture rule applies.

### 7.3 Private dispatch
`async_private_dispatcher(server_key, host, port, private_action, params_dict, json_dict, timeout=60, retries=5)`: RPC method = endpoint path; params+json merged into one kwargs map; HTTP fallback `POST http://host:port/<private_action>`. Sync `private_dispatcher` variant: default timeout 180 s, `requests`, single attempt. `check_endpoint`/`endpoints_available` HEAD probes.

### 7.4 Status flow
- Startup: orch `ServerMonitor.subscribe_all` calls each non-Bokeh server's private `attach_client(orch_key, orch_host, orch_port)` (retry ≤15 × 2 s; failure ⇒ `init_success=False`). Direction matters on restart: the launcher re-subscribes by calling the **action server's** `/attach_client` with the orch as client (documented past bug).
- Push: each action server POSTs its full/filtered `ActionServerModel` to the orch's private `/update_status`; nonblocking executors → `/update_nonblocking` (with the legacy `list.remove` ValueError quirk on unknown exec_ids noted for the adapter to reproduce-or-guard without wire change).
- Ingestion runs **inside `orch.aiolock`** (exactly two lock owners: status ingestion and the dispatch critical section); side effects per §4.2.4; `interrupt_q` wakes the dispatch loop; drained models forward to `globstat_q` → `/ws_globstat`.
- Identity-correlated folds per §4.2.4(6). The dispatch loop's history-poll coupling (spin until the dispatched uuid appears in `action_history`, fed by ingestion) is preserved behavior; its known hang mode (server dies after replying, before first status push; heartbeat monitor is the only exit) is documented and covered by a concurrency test asserting the heartbeat path fires.

### 7.5 WS frame encodings (per channel)
- `Base.ws_status/ws_data/ws_live` relays: `pyzstd.compress(pickle.dumps(msg.as_dict()))` per message (`use_as_dict=False` for live) — byte-format parity for existing subscribers.
- `WsPublisher` channels consumed by `vis_subscriber` visualizers — preserved as-is.
- Orch `/ws_globstat` and any JSON channel: JSON-safe serialization performed **at the wire adapter** (`_json_clean`) — never in the domain broadcast; every send-path exception is logged, never silently swallowed (AVOID #7: a `json.dumps` TypeError once masqueraded as a connection flap for days).

### 7.6 Self-ops
Orch-hosted executors (`wait`, `add_global_param`, `conditional_stop`, interrupt) are stopped/finished **in-process**; the dispatch loop never issues an RPC to its own server (the c58f1314 deadlock). `nonblocking_sink`/`on_nonblocking` wiring is mandatory and covered by the endpoint-parity checklist (it was left dangling once, e7534fd3).

---

## 8. Legacy public-surface audit & endpoint-parity checklists

### 8.1 The audited surface (reference maps)

The deploy research files are the frozen legacy-surface maps this spec incorporates by reference:
- **hte** (`deploy-hte-servers.md`): 23 action-server modules, **241 statically-defined endpoints** as of 2026-08-04 (237 at the 2026-07-16 audit; +4 from the private digital-out pair on `galil_io` and `nidaqmx_server` — [A1 §5.1], re-frozen, zero removals), plus config-driven `analyze_<name>` endpoints, 242 experiment functions / 13 modules, 86 sequence functions / 14 modules, 13 config-selected `*_vis` modules **plus 13 config-selected Reflex panel modules (19 files, 6 of them shared helpers) and two control panels present in both stacks** (D9 subjects, P7-UI), operator scripts (incl. the external `data_request_client` dependency), specification parsers, meta/post processors.
- **test** (`deploy-test.md`): sim servers + endpoints, dual-convention bare-helper drivers, runners.
- **Deployment-A** (`deploy-A.md`): 9 server modules (incl. FastAPI route surgery on `run_CP` v3, cross-deployment Gamry/NI reuse, aligner, ML back-channel), 37 experiments, 20 sequences, import-time CSV dependency.
- **Deployment-B** (`deploy-B.md`): 3 action servers (actuator/UR10e/OPC-UA incl. top-level `/execute_gamry_stop`), 5 visualizers (incl. control buttons), 23 experiments, 6 sequences.
- **Deployment-C** (`deploy-C.md`): batch-convert server (private-tag endpoints + watchdog), thin analysis server, 3 BaseAnalysis classes, converter pipeline.

### 8.2 The BaseAPI system surface (every action server)

Beyond per-deployment endpoints, every server must provide: `/get_config`, `/get_status`, `/attach_client`, `/stop_executor`, `/{server_key}/estop`, `/shutdown`, `/get_lbuf`, `/list_executors`, `/loaded_modules`, WS `ws_status`/`ws_data`/`ws_live`, the action-lifecycle POST contract, the queuing middleware, the estop exception handler (HTTP exceptions on action routes trigger estop + stop-executors), and the co-located RPC mirror. The orchestrator additionally: `/update_status`, `/update_nonblocking`, `/update_global_params`, `/global_status`, `/ws_globstat`, `append_sequence`/`insert_experiment`/`start`/`stop`/`estop_orch`/`clear_estop`/`clear_error`/`skip_experiment`, queue-management endpoints, `/get_status` (which the old framework orch simply lacked — legacy inherits it from Base), export/import queues. The old attempt's per-station crash class was exactly gaps in this shared surface plus driver-facing Base members (`app.server_params`, async `dyn_endpoints`, `poller_class=`, `setup_and_contain_action(action_abbr=…)`, `get_main_error`, …) — the checklist includes the **member surface** consumed by each deployment's code (grep-derived import/attribute audit), not just routes.

### 8.3 Checklist mechanics (per-deployment, mandatory gate input)

1. **Generated, not written:** a harness script AST-extracts the route set (path, method, tags, param names/types/defaults) from legacy `makeApp` modules and from the hexagon composition, and diffs them. The committed checklist artifact per deployment is the frozen legacy extraction + sign-off boxes for: every route present, param-schema equal (incl. config-shaped dynamic enums — extraction runs with the target config so `drv.dev_*` signatures materialize), tags equal (action vs private changes lifecycle), dyn-endpoint sets equal, WS channels equal, RPC mirror complete.
2. **Runtime cross-check at preflight:** the offline validator hits `/openapi.json` (or route introspection) of each launched hexagon server and re-diffs against the frozen extraction — catching composition-time regressions the static pass can't.
3. **Dependent-surface inventory** (AVOID #8): per deployment, a grep-based audit of (a) experiment/sequence library imports, (b) `active.*`/`base.*` member usage, (c) private-deployment config references to shared modules — enumerating **three** vis keys (`live_vis`, `action_vis`, **`control_vis`**) and the per-config **`reflex:` server set** [A1 §5.3], (d) `bokeh_port`-style invisible port claims — attached to the phase plan before its wave starts. Experiments/sequences libraries are **in the wave plan from day one** (their omission forced the old Wave 3.5 emergency).
4. Flat-namespace collision check (§4.3.12 Library port) runs in the same preflight.
5. **A checklist diff is a route-set diff first** [A1 §5.2]. The extractor records annotations as source text, so a typing-modernization or formatting sweep produces diffs in servers with no surface change at all (the PEP 585 pass rewrote `List[...]`→`list[...]` in 11 hte servers). Evaluate (path, method) and parameter-name deltas first; annotation-spelling changes are reported separately and do not by themselves constitute surface drift. Without this rule a reviewer either re-freezes reflexively — letting a real removal ride along — or keeps trusting a stale freeze.
6. **Worst case of (3d):** a `reflex:` server claims `port` **and** `port + 1` with nothing in the config naming the second (§9.2). One collision has already shipped and been fixed (a control panel on 5003, which the Galil aligner binds), so this is a first-class preflight check, not a review habit.

---

## 9. Cross-cutting runtime services (first-class, behavior-tested)

### 9.1 Logging (fail loud — regression guard)

Contract (from core-05 §4, preserved exactly):
```
active:    <root>/LOGS/<server_key>.log          (flat file, one per server process)
rotated:   <root>/LOGS/<server_key>.log.<YYYY-MM-DD>.gz   (daily, keep 90, GZipRotator)
ntp:       <root>/LOGS/ntpLastSync.txt           (written by launch; read by every logger's NtpOffsetFormatter and by Base)
launcher:  <root>/LOGS/launch.log
legacy txt archives: <root>/LOGS/<server_name>/*.txt zipped at startup (first-`[`-line HHMMSS scheme)
```
Rules:
1. **One logging module** across both stacks during coexistence — the hexagon Logging port wraps `helao.helpers.helao_logging`; nothing is vendored (F3).
2. The port's file-logger factory **raises** if no log root is resolved. Both legacy tempdir traps (`log_dir=None → mkdtemp()`; `OSError → mkdtemp()` with a bare print) are unreachable through the port. No parallel `LOGS_FW`-style directory, ever.
3. **Ordering contract:** resolve config → create `<root>/LOGS` → install the named singleton logger (`logging.LOGGER = make_logger(server_key, log_dir=…)`) → **only then** import application modules (the module-level `LOGGER = make_logger(__file__) if logging.LOGGER is None else logging.LOGGER` idiom at ~every module top makes import order load-bearing). The hexagon launcher path reproduces this sequence; a P0 behavior test launches a server and asserts the log file lands at the contractual path and `/tmp` gains nothing.
4. Handler behavior preserved: dedup window 10 s (with the `getMessage()` try/except guard — the gpsim hang fix), level policy (logger at min(10, level), handlers gate; per-server > top-level > 20), `propagate=False`, ALERT=60 email throttling (one per `email_interval`, buffered subjects) + webhook queue listeners on background threads.
5. `print_message` shim retained for call-site compatibility.

### 9.2 Config (raw-dict identity)

1. `read_config` resolution rules preserved: explicit `.py` (top-level `config` dict) / `.yml`; bare prefix globs `helao/deploy/*/configs/<prefix>.*` with `.yml` over `.py`; augmentation keys (`loaded_config_path`, `helao_repo_root`, `helao_credentials_path`, `alert_config_path`).
2. `install_global_config` publishes the **raw dict as-is**; `HelaoConfig.model_validate` is a schema gate whose output is never installed (it drops undeclared keys and breaks `--restore`'s same-object aliasing: `CONFIG["servers"][key] is server.server_cfg`, mutated in place by `--restore`). The hexagon Config port hands out views of the same dict object; any typed convenience view is read-only and derived.
3. Cross-cutting validation (unique keys, unique host:port, **exactly one of `fast`/`bokeh`/`reflex`**, single `params.positions` owner) stays in the launcher/preflight validator, extended with the hexagon checks (§8.3, port wiring). **Uniqueness is no longer one address per server** [A1 §9.1]: a `reflex:` entry claims `host:port` **and** `host:port+1` (static frontend, then backend), resolved by `reflex.discovery.reserved_addresses`. The second half is the load-bearing one — nothing else may claim `port + 1`, and nothing in the config mentions it. `launch.py:583` is the authority on the code-key tuple; `launch.py:61` on the address reservation.
4. Deployment resolution: config-path autodetect, per-server `deployment:` override, module-glob fallback with same-deployment preference — the cross-deployment module reuse (test→hte orch/operator/vis; Deployment-A→hte Gamry/NI; Deployment-B→hte gamry_server2 etc.) is a supported, tested path, and those shared modules are treated as **shared legacy surface**, not deployment-private.

### 9.3 Clock / NTP

`get_ntp_time` writes the offset file at launch; `read_saved_offset` at server init; `set_time(offset=ntp_offset)` mints every timestamp; `epoch_ns` per §5.4(10); `Timer` wall/monotonic alignment; `get_realtime(_nowait)` surface on the DataSink port. Behavior test: timestamps in captured artifacts shift by an injected offset exactly as legacy's do (one paired capture with a manipulated offset file).

### 9.4 Launch / process lifecycle (compatibility constraints)

`LAUNCH_ORDER = ["action", "orchestrator", "operator", "visualizer"]` (note: **operator before visualizer** — CLAUDE.md's order is stale); `KILL_ORDER = ["operator", "visualizer", "action", "orchestrator"]`; graceful kill SIGTERM → 7.0 s (> uvicorn `timeout_graceful_shutdown=5` + Base detach sleep 1 s) → SIGKILL → 3.0 s, zombie-reaping on every branch; pid pickles `STATES/pids_<prefix>_<extraopt>.pck`; `--restore` semantics incl. consumed-pck archiving; hot-reload contract (`/loaded_modules` live for `fast` servers + a `STATES/loaded_modules_<key>.json` startup snapshot for **bokeh *and reflex*** servers, neither of which exposes that route — `server_loaded_files` branches on `"fast" in server_entry` [A1 §9.2]; idle definitions per server group); uvicorn stdout format `[%H:%M:%S_<server_key>]` (the log-zipper regex keys on it); Windows selector event-loop policy set **before any loop exists** in both launchers (zmq.asyncio needs `add_reader`).

**Process containment (added since the 2026-07-16 baseline; [A1 §9.3]).** A server dies with its launcher unless the launcher says otherwise, by two different mechanisms:
- **Linux:** each server arms `PR_SET_PDEATHSIG` at its entry point (`helao.helpers.parent_death`). The signal is scoped to the *spawning thread*, so the handler re-checks `getppid()` and re-arms rather than trusting the notification; arming must **not** move into a `preexec_fn` — `launch.py` is multi-threaded, where post-fork code is unsafe.
- **Windows:** there is no PDEATHSIG, so containment is a Job Object on **the launcher** with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (`helao/helpers/win_job.py`), inherited automatically by anything a job member spawns. **The job handle must stay referenced for the launcher's whole life — closing it is what kills the group**, so a garbage-collected handle terminates every running server.
- **Both:** CTRL-d writes `STATES/detached_<prefix>_<extraopt>.marker` and a server finding it stands down instead of shutting down; on Windows CTRL-d must *clear* the kill-on-close limit first, since a process cannot be removed from a job.
- `--reconnect` / `--force-relaunch` govern what happens when servers from an earlier launch still hold the ports; live members are confirmed by matching the process cmdline against `<fast|bokeh|reflex>_launcher.py <configPrefix> <server_key>`, never by `pid_exists` alone, so a recycled PID is never reported as a live server.

---

## 10. Testability & test requirements

### 10.1 Fixture fidelity (the anti-F1/anti-AVOID#5 rules)
1. Parity fixtures: capture-derived only (§6.5).
2. Endpoint/dispatch tests register routes through the **real** route-registration/wrapping code (ActionAPIRoute, middleware, RPC mirror) — never hand-rolled fake endpoints (they masked both the endpoint-naming and payload-shape bugs).
3. Wire-format tests decode with **every real consumer decoder registered for that channel** — plural since Amendment 1 [A1 §8]: the visualizer's `WsSubscriber` path, the zstd-pickle `_ws_relay` path, **and** the Reflex `ingest` normalizer for that `ws_path`. Never a copy of the producer's encoder (the dd31c36f trap). A WS adapter that satisfies `WsSubscriber` alone is not covered, and its failure mode is a blank panel with an otherwise healthy server.
4. Every regression fix lands with a pinning test whose fixture derives from the failing artifact/frame.
5. **Not every HELAO data column is numeric** [A1 §8(3)]. Datasets carry an orchestrator host or a status string beside the traces; handing one to a plotting facade raises `could not convert string to float` from inside the render and takes down the whole chart. Column filtering is consumer-side behavior a hexagon-hosted UI must keep, and it is pinned in the same tests.
6. **The palette sweep covers `helao/hexagon/`, effective immediately** [A1 §7]. `helao/core/servers/palette.py` is the single source of every colour in both UI stacks, enforced by an AST sweep in `helao/core/tests/test_palette.py` whose globs are `helao/core/servers/**` and `helao/deploy/*/servers/**` — the hexagon tree is currently outside it, so the D6 aligner adapter is unguarded and inherits theming only by luck (it constructs a `HelaoVis`, whose `__init__` calls `apply_theme`). Extending the glob must **not** extend the exemption list, which a test pins to exactly two entries by exact path; a hexagon module needing a colour literal is a design error, not an exemption. Do not reformat `helao/core/tests/fixtures/sweeper_calibration/` while doing it — its line numbers are pinned.

### 10.2 Fakes: opt-in, fail loud
`adapters/fakes/` exists for unit speed, but: (a) production composition **raises** on unwired ports — no fake defaults; (b) fakes self-identify (log a WARNING banner at construction) so a "green" run on fakes is visible in output; (c) any milestone claim states the transport/adapters used; (d) e2e milestone gates run on the **real** transport (ZMQ+HTTP, real WS) against sim hardware — "green suite ≠ working system" (AVOID #6) is countered by making the sim-live e2e gate part of every phase.

### 10.3 Mandatory concurrency suite (orch/FSM)
Blocking for any orch milestone; runs against the real dispatch loop + real transport with sim action servers:
1. **Lost wakeup / double drain:** status bursts while the loop is mid-effect; assert single-drainer semantics (no double-popped queue, no duplicated FinishExperiment).
2. **Non-default identity:** full run under a config with non-trivial orch `MachineModel`; assert status folds and self-hosted `/wait` finish (MINOR-8).
3. **Estop between decision and effect:** inject estop (a) while blocked on the dispatch lock, (b) between ladder decision and FinishThenDispatch effect, (c) during finalization close-out — assert single finalizer, `[finished, estopped]`, no duplicate `finished`.
4. **Serial multi-experiment sequence:** ≥3 experiments; assert every experiment finishes (FinishExperiment meta + clear_nonblocking) before the next dispatches (5c43a803).
5. **Nonblocking lifecycle:** nonblocking `/wait` end-to-end (`send_nbstatuspackage` → `update_nonblocking` → clear) — the flag must survive the endpoint (ac42e9bf/e7534fd3).
6. **History-poll hang exit:** kill a sim server after dispatch-reply, before first status push; assert the heartbeat monitor issues stop (the only exit).
7. **Idle drain:** natural queue drain flips loop_state via the complete-idle path (7533dbc5); history entries non-blank (2e828981, ac42e9bf, 6b8931ce).
8. **Data-path timing:** `enqueue_data_nowait` racing `finish()` (writes joined before close, no leaked handle — ce846da1); split mid-stream (listen-uuid swap, old hlo closed, new file名 correct); no-data action produces no file.
9. **seq_unpacker startup race** and **`_ensure_run_id`** adjacency (add_sequence interleaving final popleft).
10. **PEP 563 RPC coercion** in a future-annotated module.

### 10.4 Disconnected-driver construct
Every Hardware adapter constructs without hardware/vendor runtime (§4.3.1) — used by unit tests, the preflight validator, endpoint-signature extraction (dyn endpoints need a constructed driver's device maps: provide config-derived maps without I/O), and Linux CI import of Windows-only adapters (§11.1).

### 10.5 Coverage & suite shape
Pytest for the hexagon tree; ≥90% domain+ports coverage gate (KEEP — cheap given purity), but coverage is explicitly **not** an acceptance criterion for milestones; the parity harness + concurrency suite + endpoint checklist are. Legacy remains under its existing scripts, now swept by `run_tests.py` [A1 §9.5] — **one file per pytest process**, because collecting the tree as a single session hangs indefinitely and ignores SIGINT while the same files pass individually (the tests start event loops, bind sockets, and spawn Bokeh servers, so cross-file interference is expected). The hexagon suite inherits that: run it per-file. Third-party import failures report `ENV`, not `FAIL`; a missing `helao*` module stays a failure. `run_unit_tests.py` remains the fast pre-launch gate and stays deliberately separate.

---

## 11. Windows plan

### 11.1 Import isolation
Module-top vendor imports currently make ≥6 driver files un-importable on Linux: `gclib` ×2 (galil io/motion), `nidaqmx` ×2 (nidaqmx_driver, **pal_driver** — PAL is un-importable without NI runtime purely for trigger lines), `comtypes`/GamryCOM (gamry), `easy_biologic`→EC-Lib DLLs (biologic driver + technique module), plus SMdbUSBm/Andor SDK loads and Deployment-A's Advantech BDaq (`sys.path.append("C:\\Advantech\\…")` at import). Rule: **vendor imports are lazy and adapter-scoped** (inside `connect()`/factory functions), so every adapter imports everywhere for schema/introspection/preflight; CI includes a Linux import-sweep test over all adapters. Deployment-A's *library* import-time I/O (the experiment/sequence modules `pd.read_csv` a station-local absolute path at import) becomes an injected electrolyte-catalog port resolved at composition (P4).

### 11.2 COM apartment (Gamry)
`sys.coinit_flags = 0x0` currently set at module import — process-wide. The Gamry adapter owns a dedicated STA thread: COM init, dtaq event sinks, and the `PumpEvents` loop live on it; results marshal out via queue; blocking COM calls never run on the event loop thread. Apartment affinity is preserved when work moves off-thread (COM objects are not shared across threads). `reset()`'s GamryCOM process-kill (psutil) is adapter-supervisor logic. EIS (ReadZ) vs dtaq path selection stays inside the adapter.

### 11.3 Event loop & sockets
`WindowsSelectorEventLoopPolicy` set before loop creation in every launcher path (zmq.asyncio `add_reader` requirement); uvicorn driven via `asyncio.run(Server(cfg).serve())` so the policy is honored. Proactor-specific quirks are treated as station-test items in P3–P5 runbooks.

### 11.4 File semantics
Windows lock behavior is contractual where the syncer/mover encodes it: `move_to_synced` retries file-in-use every 1 s indefinitely; promotion busy-file retry (bc9232db); writes joined before close so no handle leaks past `finish()` (ce846da1 — the WinError 32 chain). Path normalization quirks in `_resolve_output_path` reproduced. Station runbooks include a Windows-only artifact diff (at-station golden, §6.6) precisely because none of this is exercised by Linux CI.

### 11.5 Verification placement
Linux CI: everything except vendor I/O (imports, domain, ports, parity vs test-deployment goldens, sim DB leg) **plus rendered-UI checks against sim configs** — headless-browser verification is available in this environment and was used throughout the UI work, so rendered UI is not inherently an at-station activity; only hardware-backed panels are [A1 §9.4]. Windows: at-station smoke + soak + on-station golden diff per the P3–P5 runbooks; the Deployment-B phase has **no Linux path at all** (its configs are Windows/live-LAN only) — its gate is entirely at-station, with simulated actuator/UR/OPC-UA adapters added for pre-station unit coverage.

**Station runbooks for any config carrying a `reflex:` server gain a bundle-rebuild step** [A1 §9.4]. The Reflex frontend is a prebuilt static bundle with the backend URL **baked in at export**, so a bundle built for one config's port serves a blank, silently disconnected page under a config on any other port. Rebuild (`build_reflex_bundle.py`) is required when a config's port changes **or** when any `class_name=` usage changes, because the compiled CSS contains only the utilities present at build time and a stale bundle renders new ones completely unstyled with no error on either side. Follow it with a rendered check that asserts computed styles, not a source grep. Bokeh needs only a restart — the asymmetry is the part to remember. Stations never need Node; the bundle is built on a development machine and shipped.

---

## 12. Phasing P0–P7 (gates, risks, rollback)

Common rules: every phase ends with its **parity gate** (harness run ID recorded); no phase starts before its predecessor's gate is green; legacy remains launchable for every config at all times (rollback = flip the `deployment:` key back); each phase gets its own implementation plan (§13); hardware phases follow the canary-first risk-ordered runbook. **D9 adds one more common rule:** no phase changes a WS payload shape, private route, or config key that either UI stack consumes without updating that stack in the same commit — the UI is legacy code the hexagon must keep working, exactly as legacy configs must stay launchable.

### P0 — Parity harness + capture rig (no rewrite code)
**Deliverables:** normalizer (§6.4) + diff CLI; capture rig + provenance manifests (§6.2, §6.5); `golden.yml` (Linux root, DB entry); **sim DB/sync server** (§6.3) incl. the local-only RUNS_SYNCED verification and the recording S3 sink (minimal reviewed legacy seam if required); golden sets GM-1…GM-5 captured from **legacy**; endpoint-extraction tooling (§8.3); logging/config/clock behavior tests written against legacy (they define the §9 contracts).
**Gate:** legacy reproduces its own goldens — two independent legacy runs of each scenario are normalized-identical, including the full FINISHED→SYNCED→S3-recorded leg; the harness fails when fed a deliberately perturbed tree (mutation self-test).
**Risks:** local-only sync may not complete the SYNCED move (verify first — fallback: recorder-mode always, or a minimal-credential no-op S3 session); WsSim nondeterminism (mask via manifest column lists); over-normalization (mutation self-test + the "exhaustive list only" rule).
**Rollback:** none needed — nothing ships; the harness is additive tooling.

### P1 — Domain core behind ports, legacy adapters
**Scope:** hexagon tree scaffold + AST boundary test; domain layer (§4.2) incl. reducer FSM, estop policy, naming/assembly, status fold + side-effect checklist; port Protocols (§4.3); **legacy adapters** that wrap the current writers/dispatcher/logging/clock/config (thin delegation — behavior identical by construction); app factory + single-drainer dispatch loop; fail-loud composition.
**Gate:** GM-1…GM-5 parity with a hexagon-composed orchestrator + hexagon-hosted SIM action server over legacy-wrapped adapters on `golden.yml`; concurrency suite items 1–7 green on real transport; boundary test green; §9 behavior tests green on the hexagon path.
**Risks:** the history-poll/ingestion coupling and the three live estop re-checks are the subtle-race hotspots — mitigated by the suite existing *before* the loop is written (test-first for §10.3); legacy-adapter wrapping tempting shortcuts that reach past ports (boundary test catches).
**Rollback:** delete/ignore the tree; legacy untouched.

### P2 — `test` deployment fully on hexagon
**Scope:** dual-convention sim adapters (test sims stay bare helpers per the standing decision — the adapter layer supports both `HelaoDriver(config=)` and bare-`Base`-style construction shims); hexagon-native artifact/sync adapters replacing the legacy-wrapped ones; visualizer/operator hosting via the hexagon vis adapters; launcher `deployment:` cut-over for test configs; optional GM-7 runner path.
**Gate:** GM-1…GM-6 parity on the hexagon-native adapters; full concurrency suite green; endpoint checklist for test+shared modules (orch/operator/vis surface) green; multi-orch demo (demo0+demo1 shared-GPSIM pattern) functional.
**Risks:** the sync pipeline is the largest native-adapter surface (locks, priorities, process reconcile) — GM-5 plus targeted syncer unit tests derived from `sync_driver` fixtures; dual-convention shim leaking `Base` into new code (boundary test + review).
**Rollback:** flip test configs back to legacy deployment key.

### P3 — hte
**Scope:** all 23 hte action servers as inbound adapters; drivers → Hardware adapters per deploy-hte-drivers-A/B porting notes (Gamry COM plan §11.2; PAL 4-way split §4.4; galil_motion 3-way split + aligner extraction D6; Archive → SampleState per the archive-hoist plan); experiments/sequences libraries (242+86 functions) imported through the Library port; 13 vis modules; operator scripts; hte configs cut over station-by-station.
**Gate (per station, HARDWARE):** endpoint-parity checklist green (static + runtime preflight); station smoke sequence; soak window per runbook; **on-station golden diff** (§6.6). Canary station first; risk-ordered rollout; a station rolls back individually.
**Risks:** the per-station BaseAPI-member-gap class (countered by §8.2/§8.3 member-surface audit before the wave); Windows file/COM semantics (§11); PAL split scope (largest single item — its plan may sub-phase: wrap-then-split, i.e. port PAL first as a single adapter behind the job-context port, split internals after parity).
**Rollback:** per-station `deployment:` flip; legacy code untouched in-tree.
**Amendment-1 delta:** reopened at the **checklist level, not the code level** [A1 §10]. Its frozen checklists are re-frozen (241 routes; the private digital-out pair on `galil_io` and `nidaqmx_server`); no station had yet diffed against the stale baseline, so nothing shipped against it. Its dependent-surface inventory gains `control_vis` (**15 of 21 configs** — it is a Bokeh feature Reflex also renders, not a Reflex-era key) and `reflex:` servers (3 station configs + 1 dev config); those three stations' runbooks gain the §11.5 bundle-rebuild step, while the other twelve control-panel stations need only a visualizer restart.

### P4 — Deployment-A
**Scope:** ThorlabsMotor 4-way split (motion god-file); aligner extraction; **import-time fs coupling fix** (electrolyte CSV → injected catalog port); Gamry route-surgery (`run_CP` v3 re-registration) reproduced as a first-class composition feature (endpoint override, not router mutation); the ML `insert_experiment` back-channel through the Transport port; latent-bug backlog carried (not silently fixed where wire-visible); its 2 sim/demo configs repaired or replaced as Linux preflight targets.
**Gate (HARDWARE):** endpoint checklist + station smoke + on-station golden diff at the deployment's station(s).
**Risks:** cross-deployment imports (hte Gamry/NI/motion enums) — P3 must land the shared adapters first; duplication mass in its 8.7k-line exp/seq libs is **not** refactored in this phase (parity first; dedup is post-parity backlog).
**Rollback:** per-station flip.
**Amendment-1 delta:** it has **no Reflex panels today**, and under D9 that is a choice rather than a gap — panels resolve by the same config keys in either stack, and a station opts in by adding a `reflex:` server and changing nothing else. **Recommended: Bokeh only for P4**, so its hardware gate is not entangled with a first-ever bundle build at that station. Its Advantech server already carries the private digital-out pair, so its checklist freeze must pick that up [A1 §10].

### P5 — Deployment-B
**Scope:** actuator/UR10e/OPC-UA adapters; **estop cascade extraction** — `execute_gamry_stop` (driver) + the visualizer's duplicate buttons both re-implemented as EstopPolicy triggers over the declarative stop topology (§4.2.5), deleting both hardcoded cascades; recorder-sandwich and unit-scaling smears noted but not refactored (post-parity); the ~1300 lines of commented-out dead exp/seq code dropped from the port (dead code is not surface); stale driver test rewritten; simulated actuator/UR/OPC-UA adapters for pre-station coverage.
**Gate (HARDWARE, no Linux path):** endpoint checklist (incl. the top-level `/execute_gamry_stop` route preserved, now delegating to the policy) + station smoke + on-station golden diff + an **estop drill** at-station (policy fires the same wire calls the legacy cascade fired — assert via recorded dispatch log).
**Risks:** safety-critical path — the estop drill is non-negotiable and rehearsed against sims first; parameter-key latent bugs in its sequences (documented in the audit) must not be silently "fixed" (they change dispatched params → artifact diffs); OPC-UA poller's self-started asyncio task needs the sanctioned poller lifecycle.
**Rollback:** flip; legacy cascade still present in legacy tree.
**Amendment-1 delta:** it gained 7 Reflex panels and its own palette-sweep test. Both are P7-UI subjects, not P5 subjects, and its dependent-surface inventory must list them. D9's corollary bites hardest here, because P5 is the phase that **deletes a duplicated estop cascade whose second copy lives in a visualizer** — a deletion that touches UI code during a non-UI phase. Scope is unchanged (§4.2.5 stands), but **the at-station estop drill must be run against both UI stacks** if that station carries a `reflex:` server: a stack whose buttons were not re-pointed at `EstopPolicy` is a safety-relevant regression that no artifact diff would catch [A1 §10].

### P6 — Deployment-C
**Scope:** **unify the three analysis writers** behind the AnalysisArtifact port (core `sync_ana` becomes the single adapter; XAFS inline copy deleted; quantification's plain-HLO output kept as an action artifact but its analysis records routed through the port); **helao_nbio split along the 7-slice plan** (session/credentials context — no import-time network, S3 transfer deduped into the sync adapter, metadata-API client, sample-graph, platemap service replacing the `PM57` import-time S3 download, parameterized SQL repository, notebook analytics evicted from the deployment); `offline_funcs` (the drifting fork of the artifact writers) replaced by the ArtifactStore adapter; batch_convert_server ported as the reference "job manager as app service"; standards registry kept as the model persistent-registry service.
**Gate (Linux-capturable):** analysis-output parity via batch — golden converted-sequence trees + ANALYSES trees + recorded `analysis/*` S3 payloads from sanitized real drop inputs, normalized diff green; converter round-trip through the real DB server `/finish_yml` leg; import-sweep proves no module performs network/credential I/O at import.
**Risks:** ICPMS conversion's mid-conversion live SQL (hidden runtime dependency) — becomes an explicit port with a recorded fixture; the uvis suffix-algebra is ported as-is (typing it is post-parity; only the noted `reconstruct_saturated_peaks` last-window bug is evaluated for fix since it is *output-changing* — decision recorded in the P6 plan, default: preserve for parity, fix behind a flag after).
**Rollback:** conversions are batch jobs — rerun on legacy converters; keep legacy scripts callable until gate + one real campaign cycle pass.
**Amendment-1 delta:** scope unchanged; one station config declares **both** `control_vis` and a `reflex:` server while the deployment ships **no Reflex panel modules of its own** — the panel resolves to the hte module by the launcher's cross-deployment fallback (§9.2(4)). Its inventory must record that cross-deployment edge rather than reporting "no panels", and its runbook needs the bundle step even though it ships no panel source [A1 §10].

### P7-UI — both UI stacks onto hexagon (added by Amendment 1; [A1 §6])
**Scope:** host the Bokeh visualizers/operator/browser and the Reflex app from the hexagon app layer; the shared layers (`operator/{orch_backend,param_forms,param_store,spec_parser}`, `data_browser/{readers,sources,state}`, `io_control`) move behind ports rather than being imported directly; `palette.py` becomes the hexagon tree's colour source too (§10.1(6)); the D6 aligner adapter is folded into the same hosting layer instead of standing alone. **New ports:** *UiHost* — the Bokeh `Server` / Reflex app construction seam, generalizing D6's ban from "no driver may construct a Bokeh `Server`" to "nothing outside the app layer may construct a UI host" (which the aligner adapter does today); *ControlSurface* — `io_control` behind a port so a panel in either stack drives hardware through one tested path with row-15 semantics and §4.3.1 fidelity reporting.
**Gate:** the first phase whose gate is **not** an artifact diff, because its subject writes no artifacts (row 15). Instead: (1) **wire-consumer parity** — for every WS channel and private route the UIs consume, the hexagon-hosted UI decodes byte-identical frames from a hexagon server, asserted with every real consumer decoder (§10.1(3)); (2) **rendered parity** — headless-browser checks over `/`, `/live`, `/action`, `/operator`, `/browser`, `/control` and the Bokeh visualizer/operator/aligner documents, asserting **computed styles and drawn content**, never source greps; (3) the palette sweep extended over `helao/hexagon/` and green; (4) the **row-15 negative assertion** — a control toggle against a hexagon-hosted server leaves the tree unchanged; (5) the bundle-rebuild step present in every affected station runbook.
**Risks:** the Reflex frontend is a build artifact with a baked backend URL, so this is the first phase where a gate can pass on a development machine and fail at a station purely from a stale bundle; and Chrome evicts past 16 live WebGL contexts — silently and permanently for the evicted chart, with nothing logged server-side — making "panels render" a per-page budget question, not a per-panel one.
**Rollback:** flip the config's `reflex:`/`bokeh:` entries back to the legacy launcher path; both stacks remain in legacy core in-tree.

---

## 13. Decomposition note

This is the **master** spec. Each phase P0–P7 receives its own implementation plan (task breakdown, file-level design, per-driver adapter specs, station runbooks, test lists) authored against this document; phase plans may refine tactics but may not weaken a gate, alter a locked decision (§3), shrink the artifact inventory (§5), or extend the normalizer's volatile list (§5.5) without a master-spec amendment. The deploy audit files are incorporated by reference as the per-deployment ground truth for phase planning.

## 14. Open questions & assumptions

**Open questions:**
- **Q1 — Package name.** Working name `helao/hexagon/`; the old branch used `helao/framework/` (unmerged, so the name is technically free) — final name to be confirmed before P1 scaffolding to avoid cherry-pick confusion when reusing KEEP code from `feat/framework-scaffold`.
- **Q2 — Golden storage.** Repo-adjacent LFS vs untracked share for golden sets (GM-1 tree with hlo bodies is MB-scale; at-station goldens may be larger and contain private context — at-station goldens for A/B/C must live outside the public repo regardless).
- **Q3 — Local-only sync completion.** Whether a no-S3 `HelaoSyncer` completes the RUNS_SYNCED move end-to-end is unverified (deploy-test caveat) — P0's first task; the recording-sink mode is the fallback either way.
- **Q4 — Model-layer smells under D8.** `core/models/server.py` imports `helpers/premodels.Action` (core→helpers inversion); premodels lives outside core/models; pydantic v1 remnants. Assumption: all accepted as-is for this rewrite (D8); consolidation is a post-parity cleanup. Confirm.
- **Q5 — Runners scope.** Micro-orch runners (GM-7, artifact row 12) migrate in P2 only if effort permits; otherwise they remain on legacy core indefinitely (legacy stays in-tree). Default: defer, keep goldens for the day they migrate.
- **Q6 — Old-branch code reuse.** The reducer FSM, boundary test, WsSubscriber backoff, and preflight validator from `feat/framework-scaffold` are candidates for cherry-pick-and-rework vs rewrite-with-reference. Default: rewrite-with-reference (the branch predates CARDS P5/P6 shapes), lifting tests where fixtures can be re-derived from captures.
- **Q7 — Deployment-B stop-topology config schema.** The declarative estop topology (§4.2.5) needs a config representation (per-server role tags vs an explicit `estop_topology:` block). Decide in the P1 plan (domain policy) with P5 (first real consumer) review.
- **Q8 — Does the shared-layer split survive porting?** [A1 §11] `operator/{param_forms,param_store,spec_parser}`, `data_browser/{readers,sources,state}` and `io_control` are backend-agnostic layers with two UIs over each; P7-UI must not fork them per stack. Ports vs plain shared modules the hexagon app layer calls directly is a P7 design question. Default: ports for anything reaching the network or filesystem (`orch_backend`, `param_store`, `spec_parser`, `io_control`), plain shared modules for pure logic (`param_forms`, `readers`).
- **Q9 — Where does `palette.py` live after P7?** [A1 §11] It is dependency-free and sits under `helao/core/servers/`. Moving it into the hexagon tree breaks the legacy stack that still consumes it during coexistence; leaving it makes the hexagon tree import legacy core for colours — legal under the boundary rule (colour is adapter territory, never domain), but it should be a stated choice, not an accident. Default: leave it and extend the sweep (§10.1(6)).
- **Q10 — Is a spec parser's absence a gate failure?** [A1 §11] A deployment's spec parser is code this repo never sees, loaded by path, and every function degrades to "nothing configured" rather than raising — a broken parser disables a tab instead of taking down a page. Right for an instrument; ambiguous for a gate, which cannot distinguish "none configured" from "broken". P7's rendered checks need an explicit answer.

**Assumptions:**
- A1: `unstable` remains the integration branch; hexagon work lands via feature branches per phase, gated as §12.
- A2: Station access windows for P3–P5 gates are schedulable per the existing runbook practice; a phase can hold at "Linux-green, awaiting station" without blocking later Linux-side work of the next phase (subject to dependency order: P3 shared adapters before P4/P5).
- A3: The sim DB recording seam (if legacy needs the constructor-level client override) is an acceptable, reviewed, no-behavior-change legacy patch.
- A4: `test` deployment sims stay bare helpers (standing decision); the dual-convention shim is permanent for sims, not a migration stopgap.
- A5: Analysis auto-dispatch (`auto_analyze_sequences`) and specification-parser re-run flows are covered by the P3/P6 endpoint checklists rather than dedicated golden scenarios, unless P0 capture shows they mutate artifacts beyond row 13.
