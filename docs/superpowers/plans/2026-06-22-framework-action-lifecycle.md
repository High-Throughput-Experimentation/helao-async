# Framework Action Lifecycle Implementation Plan (Sub-project 4)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development / executing-plans. Checkbox steps.

**Goal:** Rebuild the action-execution machinery as a pure domain state machine driven through ports, plus `app/base_api.py` wiring and `makeApp`. See spec `docs/superpowers/specs/2026-06-22-framework-action-lifecycle-design.md` and the machinery map in that sub-project's notes.

**Architecture:** Hexagonal. Pure `domain/` (run-models, lifecycle functions, action-session state machine, executor contract) returning command/result objects; I/O via `ports/` (storage/eventsink/clock/transport) with `adapters/` impls; FastAPI only in `app/`.

**Tech Stack:** Python 3.12 (helao conda env), pydantic v2, asyncio, aiofiles, pytest.

---

## Conventions (read first)

- **helao conda env only:** prefix every command with `conda run -n helao`. Never OS python. Ignore cosmetic `ERROR conda.cli.main_run` on non-zero exit.
- **Branch:** `feat/framework-scaffold` (all sub-projects stack here). Confirm `git branch --show-current`. Never commit to `unstable`/`main`.
- **No private-deployment names.**
- **Sources of truth:** `helao/core/servers/base.py` (Base, Active), `helao/helpers/executor.py`, `helao/helpers/premodels.py`, `helao/helpers/active_params.py`, `helao/core/models/{file,data,sample}.py` (already ported to framework). Port behavior faithfully; restructure per spec.
- **Purity:** `domain/` imports only `models/`, `ports/`, `support/`. Never FastAPI/httpx/aiofiles/bokeh/`adapters`/`app`. The AST boundary test enforces this — run it each wave.
- **After every task:** `conda run -n helao python run_framework_tests.py` green; AST boundary test green.

---

## Wave 1 — Run models + pure lifecycle functions

### Task 1.1: RunAction / RunExperiment / RunSequence (single inheritance, explicit provenance)

**Files:** Create `helao/framework/domain/run_models.py`; Test `helao/framework/tests/test_domain_run_models.py`.

- [ ] **Step 1:** Read `helao/helpers/premodels.py` (the runtime wrapper field additions) and the ported `helao/framework/models/{action,experiment,sequence}.py`. Enumerate EVERY field the old runtime `Action` exposed to `Active` (from the machinery map §4): action+experiment+sequence provenance, `file_conn_keys`, `data_stream_status`, `dispatched_actions`, `dispatched_experiments`, split linkage.
- [ ] **Step 2:** Write failing tests: `RunAction` is constructible; assert it carries EVERY field in that enumerated list (a `test_runaction_has_all_legacy_action_fields` that checks `set(expected) <= set(RunAction.model_fields)`); `RunSequence`/`RunExperiment` carry their runtime tallies; `model_dump()` round-trips; NO multiple inheritance (assert `RunAction.__bases__ == (ActionModel,)`).
- [ ] **Step 3:** Implement `run_models.py`: `RunSequence(SequenceModel)` (+`dispatched_experiments`), `RunExperiment(ExperimentModel)` (+`dispatched_actions`), `RunAction(ActionModel)` (+`file_conn_keys`, `data_stream_status`, + explicit sequence/experiment provenance fields not already on ActionModel). Single inheritance only. Import only from framework models.
- [ ] **Step 4:** Run tests → PASS; full gate + boundary green.
- [ ] **Step 5:** Commit `feat(framework): add flat runtime run-models (no diamond inheritance)`

### Task 1.2: Pure lifecycle functions (init/dir/split) returning command objects

**Files:** Create `helao/framework/domain/lifecycle.py`, extend/create `helao/framework/domain/commands.py`; Test `helao/framework/tests/test_domain_lifecycle.py`.

- [ ] **Step 1:** Read the `init_act`/`init_seq`/`init_exp`/`get_action_dir`/`get_experiment_dir`/`get_sequence_dir`/`split` logic in `premodels.py`.
- [ ] **Step 2:** Write failing tests: `action_output_dir(run_action)` / `experiment_output_dir` / `sequence_output_dir` reproduce the legacy path strings byte-for-byte for fixed inputs; `init_action(action, now=<fixed datetime>, uuid=<fixed uuid>, manual_names=...)` assigns timestamp/uuid/status/output_dir and, when sequence/experiment timestamps are absent, auto-promotes to manual (sets `manual_action`, synthetic `seq--`/`exp--` names, `access="manual"`) — assert the returned `ActionInit`/run-model; `split_action(action, now=..., uuid=...)` returns the new+old states and the file-conn open/close command list. Clock/uuid are injected args (functions never read wall clock internally — assert by passing fixed values and getting deterministic output).
- [ ] **Step 3:** Implement `lifecycle.py` (pure functions) + the `ActionInit`/`SplitResult` command/result dataclasses in `commands.py`.
- [ ] **Step 4:** Run tests → PASS; gate + boundary green.
- [ ] **Step 5:** Commit `feat(framework): add pure action lifecycle functions`

---

## Wave 2 — Port extensions + storage adapter (HLO byte format)

### Task 2.1: Extend storage + eventsink ports and fakes

**Files:** Modify `helao/framework/ports/storage.py`, `ports/eventsink.py`, `adapters/fakes/storage.py`, `adapters/fakes/eventsink.py`; Test `helao/framework/tests/test_ports_storage.py` (extend), `test_ports_eventsink.py` (extend).

- [ ] **Step 1:** From the map §1/§5, list the storage operations the action path needs: open HLO file-connection (write header), append data row, close; write atomic meta YAML (`.act`/`.exp`/`.seq`); copy/relocate aux file; run HLO post-processor. List eventsink needs: emit status, emit data.
- [ ] **Step 2:** Write failing tests against the EXTENDED port Protocols using the fakes: open→append→close records an in-memory HLO buffer with header + `%%\n` + rows; meta write records the doc; relocate records src→dst; eventsink emit_status/emit_data record. Keep existing storage/eventsink tests passing.
- [ ] **Step 3:** Extend the Protocols (add methods) and the fakes (implement them in memory). Do NOT break existing `write_json`/`read_json`/`emit`.
- [ ] **Step 4:** Run tests → PASS; gate + boundary green (ports stay pure).
- [ ] **Step 5:** Commit `feat(framework): extend storage/eventsink ports for HLO streaming`

### Task 2.2: Real filesystem storage adapter (byte-identical HLO)

**Files:** Create `helao/framework/adapters/fs_storage.py`; Test `helao/framework/tests/test_adapters_fs_storage.py`.

- [ ] **Step 1:** Read the HLO write logic in `Active.log_data_set_output_file`/`write_live_data`/`write_file`/`_finish` and `Base._write_meta_atomic` (map §1/§2, §5) to capture exact byte format: `[HEADER]\n%%\n[JSON ROW]\n...`, meta YAML via temp-file + `os.replace`.
- [ ] **Step 2:** Write failing tests: `FsStorage` writing an HLO file to a tmp dir produces byte-identical content to the legacy format for a fixed header+rows; meta YAML write is atomic (temp then replace) and round-trips; relocate copies a file. Use `tmp_path`.
- [ ] **Step 3:** Implement `fs_storage.py` (aiofiles-based) realizing the extended `Storage` Protocol. Lives in `adapters/` (may import aiofiles).
- [ ] **Step 4:** Run tests → PASS; gate + boundary green.
- [ ] **Step 5:** Commit `feat(framework): add filesystem storage adapter with HLO byte-compat`

---

## Wave 3 — Executor contract + action-session core

### Task 3.1: Executor contract

**Files:** Create `helao/framework/domain/executor.py`; Test `helao/framework/tests/test_domain_executor.py`.

- [ ] **Step 1:** Read `helao/helpers/executor.py`.
- [ ] **Step 2:** Write failing tests: a dummy `Executor` subclass; assert phase methods exist with the documented signatures (`_pre_exec`/`_exec`/`_poll`/`_post_exec`/`_manual_stop` returning the documented dicts), `oneoff`/`poll_rate`/`concurrent`/`duration` attributes, and the `set_*` runtime binders work.
- [ ] **Step 3:** Port `Executor` near-verbatim into `domain/executor.py`, repointing imports to framework (`ErrorCodes`, `HloStatus`). No I/O.
- [ ] **Step 4:** Run tests → PASS; gate + boundary green.
- [ ] **Step 5:** Commit `feat(framework): port Executor contract into domain`

### Task 3.2: ActionSession core (init → active → finish happy path)

**Files:** Create `helao/framework/domain/action_session.py`; Test `helao/framework/tests/test_domain_action_session.py`.

- [ ] **Step 1:** Read `Active.__init__`/`myinit`/`start_executor`/`action_loop_task`/`add_status`/`enqueue_data`/`write_file`/`append_sample`/`log_data_task` (map §1).
- [ ] **Step 2:** Write failing tests: construct `ActionSession(run_action, storage=fake, eventsink=fake, clock=fake, executor=dummy)`; drive init→active→finish on a oneoff dummy executor; assert: output dir created (storage), initial status emitted (eventsink), each executor phase's data enqueued (eventsink), a written file recorded (storage), `append_sample` mutates samples + emits status, final status emitted, counters `num_data_queued==num_data_written`. All via fakes; no real I/O.
- [ ] **Step 3:** Implement `ActionSession` core methods, pure, calling injected ports. The `action_loop_task` drives the executor phases and enqueues data.
- [ ] **Step 4:** Run tests → PASS; gate + boundary green.
- [ ] **Step 5:** Commit `feat(framework): add ActionSession core state machine`

---

## Wave 4 — split / substitute / manual / finish

### Task 4.1: split, substitute, manual promotion

**Files:** Modify `helao/framework/domain/action_session.py`; Test `test_domain_action_session_split.py`.

- [ ] **Step 1:** Read `Active.split`/`split_and_keep_active`/`split_and_finish_prev_uuids`/`substitute`/`finish_manual_action` (map §1).
- [ ] **Step 2:** Write failing tests: split increments `action_split`, reinits uuid/timestamp (injected), opens new file connections + finishes old ones, links parent/child uuids; `substitute` closes open handles; manual action (no parent timestamps) promotes and writes synthetic exp/seq meta. Assert via fakes.
- [ ] **Step 3:** Implement these transitions using `lifecycle.split_action` + ports.
- [ ] **Step 4:** Run tests → PASS; gate + boundary green.
- [ ] **Step 5:** Commit `feat(framework): add split/substitute/manual transitions`

### Task 4.2: finish / _finish (drain, global params, meta, postproc, relocate)

**Files:** Modify `helao/framework/domain/action_session.py`; Test `test_domain_action_session_finish.py`.

- [ ] **Step 1:** Read `Active.finish`/`_finish`/`relocate_files`/`track_file` (map §1).
- [ ] **Step 2:** Write failing tests: finish waits for data drain (counters), exports `to_global_params` via the injected `transport` port (fake), writes `.act` meta (storage), runs post-processors (storage), schedules relocate of tracked aux files (storage), emits final `finished` status (eventsink); error/estop paths set the right statuses. Inject the transport FAKE.
- [ ] **Step 3:** Implement `finish`/`_finish` using storage+eventsink+transport+clock ports.
- [ ] **Step 4:** Run tests → PASS; gate + boundary green.
- [ ] **Step 5:** Commit `feat(framework): add ActionSession finish with drain/global-params/postproc`

---

## Wave 5 — app wiring + golden master + close-out

### Task 5.1: app/base_api + makeApp + wiring smoke

**Files:** Create `helao/framework/app/base_api.py`, `helao/framework/app/factory.py`; Test `helao/framework/tests/test_app_base_api_smoke.py`.

- [ ] **Step 1:** Read `Base._get_action`/`setup_action`/`setup_and_contain_action`/`contain_action`/`get_active_info` and the existing `makeApp` factory pattern (any deployment `servers/action/*.py` + `base_api.py`).
- [ ] **Step 2:** Write a failing smoke test: build an app/base object via `app/base_api.py`, wire the REAL `fs_storage` adapter + a queue/in-memory eventsink + `ntp_clock` (create `adapters/ntp_clock.py` if not present) + the transport fake, run a dummy-executor action end-to-end through `setup_and_contain_action` → `finish`, and assert an HLO file appears on disk (tmp root) with correct bytes.
- [ ] **Step 3:** Implement `app/base_api.py` (composition + the `_get_action`/contain logic, FastAPI-facing) and `app/factory.py` `makeApp(server_key)`. Preserve public method names (`setup_and_contain_action`, `active.enqueue_data`, `active.finish`).
- [ ] **Step 4:** Run tests → PASS; gate + boundary green (app may import FastAPI; domain must not).
- [ ] **Step 5:** Commit `feat(framework): add app/base_api wiring and makeApp factory`

### Task 5.2: golden-master vs old Base/Active + fix _uptime + close coverage

**Files:** Create `helao/framework/tests/test_golden_master_action.py`; Modify `helao/framework/ports/driver.py` (fix `_uptime`).

- [ ] **Step 1:** Write a golden-master test: run a representative action (fixed inputs, dummy/sim driver) through BOTH the old `helao.core.servers.base` Active path and the new framework path; assert byte-identical `.hlo` and `.act` output. If running old Base in-process is impractical, capture a committed golden fixture file from the old path and assert the new output matches it (document how the fixture was generated).
- [ ] **Step 2:** Fix the inherited `_uptime` bug in `helao/framework/ports/driver.py` (format `timedelta` via `total_seconds()`/`str`, not `strftime`) and FLIP `test_ports_driver.py::test_uptime_inherits_source_timedelta_bug` to assert correct behavior (per memory note known-bug-clear-in-finished).
- [ ] **Step 3:** Run the gate; for each new `domain/` file below 90%, add targeted tests until domain+models+support ≥90% and PASS.
- [ ] **Step 4:** Commit `test(framework): golden-master action parity; fix driver _uptime; close coverage`

### Task 5.3: Final verification

- [ ] **Step 1:** `conda run -n helao python run_framework_tests.py` → all pass, gate PASS.
- [ ] **Step 2:** Purity — `grep -rE "from helao\.(core|helpers)" helao/framework/domain/ helao/framework/ports/` empty; AST boundary test green (`domain/` imports no FastAPI/aiofiles/httpx/adapters/app).
- [ ] **Step 3:** No private-deployment names in the diff.
- [ ] **Step 4:** `git log --oneline unstable..HEAD` shows the SP4 commits stacked.

---

## Self-review notes

- Delivers spec §2 (flat run-models + pure lifecycle), §3 (ActionSession state machine, pure, port-driven), §4 (Executor contract), §5 (storage/eventsink extensions + fs adapter byte-compat), §6 (app/base_api + makeApp), §7 (domain unit tests, fs adapter byte tests, wiring smoke, golden master), and fixes the deferred `_uptime` bug.
- OUT of scope per spec §8: Orch, real HTTP transport/dispatcher/zmq (SP5), full RunExperiment/RunSequence orchestrator behavior + PlanMakers (SP5).
- All commands `conda run -n helao`. No private-deployment names.
