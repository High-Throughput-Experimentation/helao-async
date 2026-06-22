# Framework Orchestration — Design Spec (Sub-project 5)

**Date:** 2026-06-22
**Status:** Approved (standing authorization)
**Parent spec:** `docs/superpowers/specs/2026-06-22-helao-framework-core-rewrite-design.md` (§4.4, §4.8, §6)
**Branch:** stacked on `feat/framework-scaffold` (PR #176).

---

## 1. Goal

Rebuild the orchestrator (`Orch`, 72 methods, 2428 LOC) as a **pure domain FSM** driving I/O through ports, plus the real HTTP transport adapter and the thin `app/orch_api.py` wiring. This is the second of the two big sub-projects (parent spec §4.4). It completes the `RunExperiment`/`RunSequence` behavior SP4 left minimal, ports the plan-makers, fixes the `clear_in_finished` bug, and lets the runners (`micro_orch`) reuse the same FSM. Depends on SP0–SP4.

## 2. The decomposition decision

`Orch` mixes four concerns: (a) **decision logic** — which queue to pull from, when to dispatch, how intents/estop transition the loop; (b) **status aggregation** — folding remote `ActionServerModel` updates into the `GlobalStatusModel`; (c) **expansion** — sequences→experiments→actions via library callbacks + plan-makers; (d) **I/O** — HTTP dispatch, WS broadcast, meta persistence, heartbeat probes.

**Decision: a reducer-style pure core, async driver at the edge** (parent spec §4.4, §6).

- `domain/orchestration.py` holds an immutable-ish `OrchState` struct (the three deques, active/last seq+exp, `GlobalStatusModel`, `global_params`, histories, loop FSM enums) and **pure transition functions** returning `(new_state, [Command])`. No I/O, no asyncio, no FastAPI/httpx.
- `app/orch_api.py` runs the async driver loop: await an event from the transport/event ports → call `orchestration.step(state, event)` → realise the returned commands through the injected ports → repeat. The loop, the awaits, and the background tasks (subscribe, heartbeat, globstat broadcast) live here.
- **Expected failures are `ErrorCodes`-carrying result values, never exceptions** (parent spec §6). Estop is a domain *state*: `step` returns halt/estop commands that `app/` executes.

This is the same shape as SP4 (`ActionSession` pure, `app/base_api.py` drives). The runners reuse `domain/orchestration` directly — one FSM, two drivers.

## 3. Domain core

### 3.1 `domain/orchestration.py` — the FSM

- **`OrchState`** dataclass: `sequence_dq`/`experiment_dq`/`action_dq` (lists used as deques), `active_sequence`/`active_experiment`/`last_sequence`/`last_experiment` (`RunSequence`/`RunExperiment` or `None`), `active_seq_exp_counter`, `active_run_id`, `global_params`, `globalstatusmodel` (`GlobalStatusModel`), `action_history`/`experiment_history`/`sequence_history`, `loop_state`/`loop_intent`/`orch_state` (read through the model), `current_stop_message`, the three `step_thru_*` flags, `nonblocking`. Mutable runtime state; config (libs, postprocessor names, heartbeat interval) is **not** here — it is passed into the pure functions or held by `app/`.
- **Pure transition functions** (each returns `(OrchState, list[Command])`, never raises for expected conditions):
  - `decide_next(state) -> OrchDecision` — given non-empty queues + idle status, which of {dispatch_action, dispatch_experiment, dispatch_sequence, finish_experiment, finish_sequence, wait, stop} is next (ports `dispatch_loop_task` priority order: action → exp → seq, with wait-for-all gating exp/seq).
  - `apply_intent(state, intent) -> (state, [Command])` — `start`/`stop`/`skip`/`estop`/`clear_*`/`intend_*` transitions on `loop_state`/`loop_intent` (ports `start_loop`/`estop_loop`/`stop`/`skip`/`clear_estop`/`clear_error`/`intend_*`).
  - `on_status_update(state, actionservermodel) -> (state, [Command])` — fold a remote status into the global model (delegating aggregation to `domain/status.py`), react to estop/error/idle/busy, decide whether to wake the loop (ports `update_status`).
  - `on_nonblocking(state, actionmodel, host, port) -> (state, [Command])` / `clear_nonblocking(state) -> (state, [Command])` (ports `update_nonblocking`/`clear_nonblocking`).
  - `start_condition_met(state, action) -> bool` — pure check of `ActionStartCondition` (no_wait / wait_for_endpoint / wait_for_server / wait_for_previous / wait_for_orch / wait_for_all) against the global model (ports the wait logic inside `loop_task_dispatch_action`).
  - dispatch helpers that produce the next state + commands after a sequence/experiment/action is pulled and (for seq/exp) expanded — the **expansion callback result is passed in** (the library call is an `app/`-side effect; the pure function consumes its output), mirroring how SP4 injects `now`/`uuid`.
  - global-param fold in/out (`from_global_*_params` → action/exp params; `to_global_params` → `state.global_params`), pure dict ops ported from the dispatch loops.
- **`OrchState` history** keyed inserts (`register_action_uuid`/`track_action_uuid`/`register_obj_uuid`) are pure list/dict ops.

### 3.2 `domain/status.py` — global-status aggregation

Extract the `GlobalStatusModel` merge/sort logic exercised by `update_status` into pure helpers (`merge_server_status`, `sort_status`, `newly_finished`, `actions_idle`, `server_free`, `endpoint_free`). The model methods already live in `models/server.py`; this module is the thin pure orchestration-side glue if any decision logic is needed beyond the model methods. **Fix `GlobalStatusModel.clear_in_finished` here** (the in-tree model) — replace the delete-during-iteration loop (`models/server.py:332-333`) with a dict replacement (`self.nonactive_dict[HloStatus.finished] = {}`), and flip the test that currently pins the buggy behavior (see [[known-bug-clear-in-finished]]).

### 3.3 `domain/plan_makers.py` — expansion helpers

Port `ActionPlanMaker` / `ExperimentPlanMaker` (premodels.py:389–584) near-verbatim — they are pure (no I/O; they use `inspect`/`contextvars` to capture the calling experiment frame). They build `RunAction`/`ShortExperimentModel` lists from library-function locals. Preserve names + semantics (parent spec §5 — author-facing surface). The `@experiment`/`@action` context-var plumbing (`EXPERIMENT_CTX`) comes along.

### 3.4 Sequence/experiment unpack (pure)

`unpack_sequence(name, params, *, sequence_lib)` and the experiment unpack consume an injected library map and return `[ExperimentModel]` / `[RunAction]`. Codehash lookup is a `support/codehash` concern (already ported). `verify_plate_in_params` is pure given an injected platemap-resolver (or returns a "needs verification" command for `app/`).

## 4. Ports

- **`ports/transport.py` — extend with RPC-shaped dispatch.** The existing message-shaped `publish`/`subscribe` stays (the A→C event-bus runway). Add a request/response method the orchestrator dispatch path needs:
  - `dispatch(target: DispatchTarget, payload: Mapping) -> DispatchResult` where `DispatchResult` carries `response: dict | None` + `error: ErrorCodes` (never raises for expected failures — parent spec §6). This ports `async_action_dispatcher` / `async_private_dispatcher` (request → response + error code).
  - `probe(targets: list) -> ProbeResult` ports `endpoints_available` (reachability classification).
  - Keep it transport-technology-agnostic: `DispatchTarget` is `(server_key, host, port, endpoint)`, not a URL.
- `ports/eventsink.py` — already carries `emit_status`/`emit_data`; add `emit_global_status` (or reuse `emit` with a channel constant) for the `ws_globstat` broadcast. Fake records.
- `ports/clock.py` — unchanged (heartbeat/poll cadence is an `app/` concern, as in SP4).
- `ports/storage.py` — unchanged; meta persistence reuses the SP4 `write_meta`/`relocate`. `export_queues`/`import_queues` pickle round-trip goes through a storage call (or stays an `app/` concern — see §8).

## 5. Adapters

- **`adapters/http_transport.py` — the real transport (NEW, the headline adapter).** Implements `Transport`: `dispatch` = RPC fast-path (ZMQ DEALER → `derive_rpc_port`, 3s timeout) → HTTP fallback (POST with retry/backoff), porting `helao/helpers/dispatcher.py` (`async_action_dispatcher`, `async_private_dispatcher`) + `helao/core/rpc/zmq_rpc.py`. `probe` ports `endpoints_available`. `publish`/`subscribe` over the existing WS status mechanism. All httpx/zmq types stay inside this module; only `DispatchResult`/`ProbeResult`/`ErrorCodes` cross the port. The RPC-client caches (`_RPC_CLIENTS`) live here.
- `adapters/fakes/transport.py` — extend the existing fake with scriptable `dispatch`/`probe` returning canned `DispatchResult`s, so domain + app tests run with no network.
- `adapters/queue_eventsink.py` — extend for `emit_global_status` if added.

## 6. App wiring

- **`app/orch_api.py`** — the async driver. Builds `OrchState` from config, injects `http_transport` + `queue_eventsink` + `fs_storage` + `ntp_clock`, loads experiment/sequence libs + postprocessors, then runs the loop: `event = await transport/interrupt` → `state, cmds = orchestration.step(state, event)` → execute `cmds` via ports → broadcast. Hosts the background tasks (`subscribe_all`, heartbeat/`ping_action_servers`, `globstat_broadcast`) and the FastAPI/Bokeh-operator endpoints (estop/start/stop/skip/clear/append/queue-listing/ws_globstat). FastAPI lives ONLY here. The single `app/` exception boundary maps an unexpected exception → `ErrorCodes.critical` + estop (parent spec §6).
- **`app/factory.py`** — extend `makeApp(server_key)` to assemble an orchestrator app when the server group is `orchestrator` (today it builds action apps). Same public factory deployments call.
- **Runners:** `runners/micro_orch.py` (+ `sequence_runner`/`experiment_runner`/`action_runner` stubs) drive `domain/orchestration` directly — a short-lived in-process loop with the same `step`, no HTTP server. This realises the "runner stubs get a real implementation for free" promise (parent spec §4.8).

## 7. Testing

- **Domain (the bulk, ≥90% gate):** unit-test `orchestration` (`decide_next` priority across queue combinations; `apply_intent` for every intent incl. estop→estopped and clear→stopped; `on_status_update` idle/busy/error/estop reactions; `start_condition_met` for all six conditions; global-param fold; dispatch state transitions with injected expansion results, clock, uuid). Unit-test `status` (merge/sort/newly-finished; **`clear_in_finished` fixed-behavior test**). Unit-test `plan_makers` (add/add_actions build correct `RunAction`/`ShortExperimentModel`; frame/context capture). All with fakes + plain data — no network.
- **Adapters:** `http_transport` against a stub server (httpx ASGI transport or a localhost FastAPI fixture) — assert RPC→HTTP fallback, retry/backoff, `DispatchResult.error` mapping, `probe` classification. `fakes/transport` script-and-assert.
- **Wiring smoke:** `app/orch_api` runs a tiny two-action sequence end-to-end against a fake transport (no real servers) — queue add → dispatch → status update → finish → meta written. Runner smoke: `micro_orch` runs the same sequence in-process.
- **Golden master:** committed fixture asserting `decide_next`/`apply_intent` traces + emitted meta for a representative sequence match the old `Orch` semantics (cited `orch.py` line mapping, as SP4 did for `Active` — the old `Orch` is not run in-process; too much harness).
- Coverage gate stays ≥90% on `domain`+`models`+`support`; every new domain file ≥90%. AST boundary test stays green (no FastAPI/httpx/asyncio in `domain`).

## 8. Out of scope

- Visualizer / operator Bokeh UIs beyond the `ws_globstat` eventsink hook (later cycle).
- Data sync / `HelaoSyncer` (SP6).
- `test` deployment migration + end-to-end on real sim servers (SP7).
- `export_queues`/`import_queues` pickle persistence may stay an `app/`-level concern (pickle is an I/O + version-coupling concern, not domain logic) — port as an adapter call, not pure domain, if it lands in SP5 at all.
- Production (`hte`) migration; private deployments.
- Changing the wire protocol (RPC/HTTP stay; transport port is shaped so C-later can swap it).

## 9. Risks

| Risk | Mitigation |
|---|---|
| Orch is huge; one pass too big | Decompose into waves: state+run-models+plan-makers → FSM core+status+clear_in_finished fix → transport port+http adapter → app driver+runners+golden master |
| RPC-shaped dispatch vs message-shaped transport port | Extend the port with `dispatch`/`probe` returning value objects; keep `publish`/`subscribe` for the event-bus runway; both implemented by `http_transport` |
| Hidden asyncio coupling sneaks into domain | AST boundary test forbids `asyncio`/`httpx`/`fastapi` imports in `domain`; the loop/awaits live in `app/orch_api.py` |
| `clear_in_finished` fix changes a pinned test | Flip the pinning test to assert correct (no-RuntimeError) behavior; note in commit |
| Plan-makers' frame/context capture is fragile | Port near-verbatim (don't redesign); test the capture path explicitly |
| Golden-master infeasible against live old Orch | Committed fixture with cited `orch.py` line mapping, same approach as SP4 |
| Transport adapter needs network in tests | Test against in-process ASGI/stub; fake transport for domain+app tests |
