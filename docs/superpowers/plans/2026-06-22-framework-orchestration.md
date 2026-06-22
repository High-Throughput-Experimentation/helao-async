# Framework Orchestration — Implementation Plan (Sub-project 5)

**Spec:** `docs/superpowers/specs/2026-06-22-framework-orchestration-design.md`
**Branch:** stacked on `feat/framework-scaffold` (PR #176).
**Execution:** parallel subagents per wave (standing authorization); continue across waves without checkpointing; conda env `helao`; gate via `python run_framework_tests.py`.

Baseline at start: 425 tests pass, gate 98.5%.

---

## Wave 1 — Pure foundations (parallelizable)

Three independent files, no cross-deps; dispatch concurrently.

- **1a. `domain/plan_makers.py`** — port `ActionPlanMaker`/`ExperimentPlanMaker` (premodels.py:389–584) near-verbatim onto framework `RunAction`/`ShortExperimentModel`. Bring `EXPERIMENT_CTX`/`ACTION_CTX` context-var plumbing. Tests: `add`/`add_actions` build correct objects; frame + context-var capture path; bool-string coercion. Pure (no I/O). ≥90%.
- **1b. `domain/expansion.py`** — pure `unpack_sequence(name, params, *, sequence_lib)` and experiment unpack consuming injected lib maps → `[ExperimentModel]`/`[RunAction]`; global-param fold helpers (`fold_in_global`, `fold_out_global`) ported from the dispatch loops; `verify_plate_in_params(paramd, *, resolver)` pure. Tests with fake lib maps + resolver. ≥90%.
- **1c. `domain/status.py` + clear_in_finished fix** — pure aggregation glue (`actions_idle`/`server_free`/`endpoint_free`/`newly_finished` thin wrappers if needed) AND fix `GlobalStatusModel.clear_in_finished` in `models/server.py` (replace delete-during-iteration with `self.nonactive_dict[HloStatus.finished] = {}`). Flip the pinning test → assert no RuntimeError + bucket cleared. Add a regression test reproducing the old crash on the fixed path.

Gate after wave: all green, new files ≥90%.

## Wave 2 — The FSM core (depends on Wave 1)

- **2a. `domain/commands.py` extension** — add orchestration command/result value objects: `DispatchAction`, `ExpandSequence`, `ExpandExperiment`, `PersistMeta`, `EstopServers`, `BroadcastGlobalStatus`, `FinishExperiment`, `FinishSequence`, `MoveRunDir`, `StopExecutor`, `OrchDecision` (enum-ish), `DispatchResult`-consumption types. Frozen dataclasses, domain-pure.
- **2b. `domain/orchestration.py`** — `OrchState` dataclass + pure transition functions: `decide_next`, `apply_intent` (all intents incl. estop/clear), `on_status_update`, `on_nonblocking`/`clear_nonblocking`, `start_condition_met` (six conditions), dispatch-step functions consuming injected expansion results + `now`/`uuid`, history register/track. Returns `(OrchState, [Command])`, never raises for expected conditions. Imports only models/ports-types/support/domain + stdlib (NO asyncio/httpx/fastapi).

Tests: exhaustive `decide_next` queue-combination matrix; every intent transition; status reactions (idle/busy/error/estop); all six start conditions; global-param fold; dispatch transitions. ≥90% on `orchestration.py`.

Gate after wave.

## Wave 3 — Transport port + real HTTP adapter (depends on Wave 2 for command shapes)

- **3a. `ports/transport.py` extension** — add `DispatchTarget`, `DispatchResult` (`response`/`error: ErrorCodes`), `ProbeResult`; add `dispatch`/`probe` to the `Transport` Protocol. Keep `publish`/`subscribe`. Extend `ports/eventsink.py` with `emit_global_status` (or channel constant). Update `tests/test_ports_transport.py`/`test_ports_eventsink.py`.
- **3b. `adapters/fakes/transport.py` extension** — scriptable `dispatch`/`probe` returning canned results; records calls. Update fake eventsink for `emit_global_status`.
- **3c. `adapters/http_transport.py` (NEW)** — port `dispatcher.py` (`async_action_dispatcher`/`async_private_dispatcher`, RPC fast-path → HTTP fallback, retry/backoff, `_RPC_CLIENTS` cache) + `endpoints_available` → `probe`. httpx/zmq stay inside. Tests against in-process ASGI stub server: RPC→HTTP fallback, retry, error-code mapping, probe classification. (Adapter coverage not gated to 90%, but test the contract.)

Gate after wave (boundary test must stay green — fake used by domain tests).

## Wave 4 — App driver + runners + golden master (depends on Waves 1–3)

- **4a. `app/orch_api.py` (NEW)** — async driver loop wiring `OrchState` + injected adapters + libs; background tasks (subscribe/heartbeat/globstat); FastAPI endpoints (start/stop/skip/estop/clear/append/list/ws_globstat); single exception→`ErrorCodes.critical`+estop boundary. FastAPI only here.
- **4b. `app/factory.py` extension** — `makeApp(server_key)` assembles an orchestrator app for `group: orchestrator`.
- **4c. `runners/micro_orch.py`** — short-lived in-process driver reusing `domain/orchestration.step`; realises the runner stubs.
- **4d. Tests** — app wiring smoke (two-action sequence end-to-end via fake transport: add→dispatch→status→finish→meta); runner smoke (same sequence in-process); golden-master fixture (cited `orch.py` line mapping for `decide_next`/`apply_intent` traces + emitted meta).

Final gate: ≥90% on domain+models+support, every new domain file ≥90%, AST boundary green, all tests pass.

## Wrap-up

- Run full gate; fix any regressions.
- Commit per wave (`feat(framework): ...`), push to `feat/framework-scaffold` (PR #176 grows).
- Update standing-authorization memory with SP5-done cold-resume state.
- Tell user to `/clear` before SP6 (data sync).
