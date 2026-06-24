# Framework SP-ORCH-1 — Orchestrator Domain Ops (design)

**Date:** 2026-06-23
**Branch:** `feat/framework-orch-domain-ops`
**Cycle:** Framework-orch endpoint completion (first of three sub-projects).

## 1. Context

The framework orchestrator (`app/orch_api.py` + `domain/orchestration.py`, built in
SP5) exposes only `start`/`stop`/`skip`/`estop`/`clear_estop`/`globstat`. The
operator's `RemoteBackend` (and the `HelaoOperator` client) call ~25 additional
orchestrator endpoints — queue queries, queue mutations, step-flags, histories,
status summary. This cycle completes those endpoints so a framework orchestrator
can drive the framework operator.

The cycle is decomposed into three sub-projects (each spec→plan→branch, merged into
`feat/framework-scaffold`):

1. **SP-ORCH-1 Domain ops** — this spec. Pure operations on `OrchState`.
2. **SP-ORCH-2 App endpoints** — route handlers in `app/orch_api.py` wiring the
   domain ops to the legacy endpoint contracts; concurrency-safe vs the dispatch loop.
3. **SP-ORCH-3 Status WS + integration** — orch status-push WebSocket for the
   operator's `subscribe`; end-to-end RemoteBackend↔framework orch.

The framework `OrchState` (`domain/orchestration.py`) already holds the backing
data: `sequence_dq`/`experiment_dq`/`action_dq` (lists used as deques, index 0 =
front), `active_*`/`last_*` sequence+experiment, `action_history`/
`experiment_history`/`sequence_history`, `step_thru_actions`/`_experiments`/
`_sequences`, `last_action_uuid`. The legacy contracts to mirror live in
`helao/core/servers/orch_api.py` (payload helpers `_histories_payload`,
`_status_summary_payload`, `_step_flags_payload`, `_set_step_flag`,
`_queue_counts`, `_queue_object_payload`) and `helao/core/servers/orch.py`
(`list_sequences`/`list_experiments`/`list_actions`, `move_sequence`,
`remove_sequence`, `prepend_sequences`, `add_split_sequences`,
`clear_sequences`/`_experiments`/`_actions`).

## 2. Goal & non-goals

**Goal:** Add the pure queue-mutation, query/serialization, step-flag, and
status-summary operations to `domain/orchestration.py`, unit-tested against the
legacy contracts. No FastAPI, no I/O. This is the testable foundation the SP-ORCH-2
route handlers call.

**Non-goals:**
- Route handlers / FastAPI wiring (SP-ORCH-2).
- Status WebSocket (SP-ORCH-3).
- Concurrency safety vs the running dispatch loop (SP-ORCH-2 owns the
  endpoint-vs-loop interaction; the domain ops are synchronous pure functions).
- Any change to legacy `core/**` or to the operator modules.
- The dispatch FSM (`decide_next`/`apply_intent`) — unchanged; this only adds
  queue/query/mutation helpers around the existing state.

## 3. Boundary contract

`domain/orchestration.py` stays pure: imports only `models/` + stdlib; never
FastAPI/httpx/filesystem/Bokeh/adapters. The AST boundary check
(`helao/framework/tests/test_boundaries.py`) must stay green.

## 4. Components

All additions are module-level pure functions in
`helao/framework/domain/orchestration.py`, taking `OrchState` as the first
argument (matching the existing `decide_next`/`apply_intent`/`register_obj_uuid`
convention). Mutations mutate `state` in place and return it (same convention as
the SP5 FSM and SP4 ActionSession).

### 4.1 OrchState additions

- Add field `status_summary: dict = field(default_factory=dict)` — maps
  `server_name -> (server_status, driver_status)`.
- **Population is out of scope for SP-ORCH-1.** In legacy, `status_summary` is
  built by a *network ping heartbeat* (`Orch.ping_action_servers` /
  `live_status_summary`, `orch.py` ~2297-2342) — that is I/O and belongs to the
  app layer (SP-ORCH-2/3). SP-ORCH-1 only adds the **field** and the pure
  `status_summary_payload(state)` serializer that reads it. The field stays empty
  until a later sub-project's heartbeat populates it. Do NOT add a ping or touch
  `on_status_update` for this.

### 4.2 Query / serialization functions

- `histories_payload(state) -> dict` — `{"action": list(state.action_history.items()), "experiment": ..., "sequence": ...}`. Byte-parity with legacy `_histories_payload`.
- `status_summary_payload(state) -> dict` — `{k: list(v) for k, v in state.status_summary.items()}`.
- `step_flags_payload(state) -> dict` — `{"actions": state.step_thru_actions, "experiments": state.step_thru_experiments, "sequences": state.step_thru_sequences}`.
- `set_step_flag(state, kind, value) -> dict` — kind ∈ {actions, experiments, sequences}; sets the flag; returns `{kind: bool(value)}`. Unknown kind raises `KeyError` (parity).
- `queue_counts(state) -> dict` — `{"n_sequences": len(state.sequence_dq), "n_experiments": ..., "n_actions": ...}`.
- `queue_object_payload(state, kind, idx) -> dict` — kind ∈ {sequence, experiment, action}; returns `dq[idx].as_dict()` or `{}` on out-of-range / unknown kind / missing serializer (snapshot-safe; mirror legacy `_queue_object_payload`).
- `list_sequences(state, limit=10) -> list`, `list_experiments(state, limit=10) -> list`, `list_actions(state, limit=10) -> list` — at most `limit` summaries from the front of each dq via `get_seq()`/`get_exp()`/`get_act()`.
- `orch_state_payload(state) -> dict` — `{loop_state, n_sequences, n_experiments, n_actions, current_stop_message}` from the global status + counts (the shape `RemoteBackend.get_orch_state` consumes).
- `get_active_sequence(state)`, `get_active_experiment(state)`, `get_last_sequence(state)`, `get_last_experiment(state)` — serialize the active/last objects (or `{}`).
- `latest_sequence_uuids(state)`, `latest_experiment_uuids(state)`, `latest_action_uuids(state)` — recent dispatched UUIDs (from the history maps / `last_action_uuid`).

### 4.3 Mutation functions

Each mutates `state` in place and returns it.

- `move_sequence(state, from_idx, to_idx)` — reorder `sequence_dq`; out-of-range is a no-op (parity with legacy `move_sequence`).
- `remove_sequence(state, idx)` — drop the sequence at `idx`; out-of-range no-op.
- `prepend_sequences(state, sequences)` — insert the given sequences at the front of `sequence_dq` preserving their order; returns the list of their `sequence_uuid`s. **Pure insert only** — the legacy run_id/codehash/`_prep_sequence_meta` *stamping* is config/library/driver-coupled and stays in the app layer (SP-ORCH-2 stamps before calling this). Empty list → `[]` no-op.
- `append_sequence(state, sequence)` / `insert_sequence(state, sequence, idx)` — add to back / at index.
- `append_experiment(state, experiment)` / `insert_experiment(state, experiment, idx)`.
- `clear_sequences(state)`, `clear_experiments(state)`, `clear_actions(state)` — empty the corresponding dq.

> **`add_split_sequences` is NOT in SP-ORCH-1.** Legacy `add_split_sequences`
> (`orch.py` ~1726) depends on `server_params` (`split_by_seq_params` /
> `group_by_seq_params` config), the codehash libraries, and run_id minting —
> all app/driver concerns, not pure `OrchState`. It is deferred to **SP-ORCH-2**,
> where the route handler resolves config/codehash/run_id and performs the split
> (it may factor a pure `split_sequence(...)` helper taking explicit args + an
> injected uuid factory, but that is SP-ORCH-2's call).

### 4.4 run_models serialization parity

`list_*`/`queue_object_payload` rely on `get_seq()`/`get_exp()`/`get_act()` and
`as_dict()` on the queued `RunSequence`/`RunExperiment`/`RunAction`. `RunAction`
already has `get_act` (SP4 redo). Add `get_seq` to `RunSequence` and `get_exp` to
`RunExperiment` if absent (parity with the legacy `Sequence.get_seq` /
`Experiment.get_exp` summary shape), and ensure `as_dict` exists (or use the
available dict serializer). Keep additions minimal and on the run_models in
`domain/run_models.py`.

## 5. Data flow

```
SP-ORCH-2 route handler → domain op(state, ...) → reads/mutates OrchState → JSON-safe dict/list
                                                  ↑ status_summary populated by on_status_update
```

## 6. Error handling (parity)

- `set_step_flag` raises `KeyError` on unknown kind (legacy dict-index parity).
- `queue_object_payload` returns `{}` on out-of-range / unknown kind / missing
  serializer (snapshot semantics).
- `move_sequence`/`remove_sequence` are no-ops on out-of-range indices.

## 7. Test strategy

Unit tests under `helao/framework/tests/` (e.g. `test_domain_orch_queue_ops.py`,
`test_domain_orch_payloads.py`) against hand-built `OrchState` fixtures:

- Serialization shapes match the legacy `orch_api._*_payload` contracts — reuse
  the exact assertions from `test_endpoint_helpers_shapes`
  (`helao/core/tests/test_standalone_operator.py` lines 80-103) repointed at the
  domain functions and a fake-or-real `OrchState`.
- Queue mutations: `move_sequence` ordering + out-of-range no-op; `remove_sequence`
  + bounds; `prepend_sequences` order + returned UUIDs; append/insert positioning;
  `clear_*` empties.
- `set_step_flag`/`step_flags_payload` round-trip; unknown-kind `KeyError`.
- `status_summary_payload` serializes a hand-set `state.status_summary` field to
  `{server: [s, d]}` (population is out of scope — see §4.1).
- `list_*` honor `limit` and front-of-deque order; `queue_object_payload` bounds.

The AST boundary check must stay green (domain remains pure).

## 8. API parity

Pure-function names chosen to mirror the legacy helpers (drop the leading
underscore: `histories_payload`, `status_summary_payload`, `step_flags_payload`,
`set_step_flag`, `queue_counts`, `queue_object_payload`) and the legacy Orch
methods (`list_sequences`, `move_sequence`, `remove_sequence`,
`prepend_sequences`, `clear_sequences`/`_experiments`/`_actions`; `add_split_sequences` deferred to SP-ORCH-2). Add each new name to the module `__all__`.

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Serialization shape drifts from legacy (operator de-serializes by key) | Reuse the exact `test_endpoint_helpers_shapes` assertions as parity tests |
| `get_seq`/`get_exp` missing on run_models → list_* break | §4.4 adds them if absent; list_* tests cover the shape |
| Mutation index semantics differ from legacy (off-by-one, no-op vs raise) | Parity tests for bounds; mirror legacy no-op behavior |

## 10. Done criteria

- The query/mutation/step-flag/status-summary pure functions exist in
  `domain/orchestration.py` (+ `status_summary` on `OrchState`, + `get_seq`/
  `get_exp` on run_models if needed), all in `__all__`.
- Unit tests pass under the `helao` env; full framework suite still green; AST
  boundary check still green; domain stays pure.
- No legacy `core/**` or `deploy/**` modified (pure addition).
- Foundation ready for SP-ORCH-2 (route handlers).
