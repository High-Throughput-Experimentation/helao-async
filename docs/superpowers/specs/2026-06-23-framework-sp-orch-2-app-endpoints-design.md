# Framework SP-ORCH-2 — Orchestrator App Endpoints (design)

**Date:** 2026-06-23
**Branch:** `feat/framework-orch-endpoints`
**Cycle:** Framework-orch endpoint completion (second of three sub-projects).

## 1. Context

SP-ORCH-1 added the pure orchestrator domain ops (queue mutations, query/
serialization, step-flags, `status_summary` field) to `domain/orchestration.py`.
SP-ORCH-2 wires those ops to FastAPI route handlers in `app/orch_api.py` so the
operator's `RemoteBackend` (and the `HelaoOperator` client) can call them over the
wire. SP-ORCH-3 adds the status WebSocket.

**Path convention (decisive).** `async_private_dispatcher` (the transport
`RemoteBackend`/`HelaoOperator` use) hits the HTTP path
`http://{host}:{port}/{private_action}` — **root path, no `server_key` prefix**
(`support/dispatcher.py:277`). This matches the SP8 base_api decision to register
private endpoints at root. The existing framework orch endpoints
(`/{server_key}/start` etc., SP5) use the prefixed convention and are exercised by
SP5 tests with that prefix. SP-ORCH-2 therefore registers the operator-facing
endpoints at **root** (`/list_sequences`, `/get_histories`, `/start`, …), leaving
the existing prefixed endpoints in place.

**Two simplifications discovered in the framework driver:**
- The FSM stamps `active_run_id` at **dispatch** time (`orchestration.py:879-882`),
  not at enqueue. So the enqueue/prepend endpoints need **no** run_id/codehash
  stamping — they call the SP-ORCH-1 pure ops directly.
- The domain ops are **synchronous** (no `await` mid-op). Under the single-threaded
  async event loop, an endpoint handler mutating `driver.state` cannot interleave
  with the dispatch loop mid-op, so **no lock is required**. (Documented, not added.)

## 2. Goal & non-goals

**Goal:** Register the orchestrator private endpoints `RemoteBackend` +
`HelaoOperator` call, at the root path, as thin handlers over the SP-ORCH-1 domain
ops + the driver control surface, with dict→Run-model deserialization for posted
sequences/experiments. Tested via a FastAPI test client against `makeOrchApp`.

**Non-goals:**
- Status WebSocket / `subscribe` push (SP-ORCH-3).
- `status_summary` population (the network ping heartbeat — SP-ORCH-3 or later).
- Full `add_split_sequences` splitting (needs split-by-seq-param **config** not
  present in `OrchPorts`; SP-ORCH-2 ships a faithful **fallback to append_sequence**,
  matching the legacy no-split branch, and notes config plumbing as a follow-up).
- New domain logic (SP-ORCH-1 owns it) or changes to the dispatch FSM.
- Deployment rewiring; operator module changes; legacy `core/**` changes.

## 3. Boundary contract

`app/orch_api.py` is the app layer (FastAPI lives here). It composes domain ops +
ports + models. It must not put business logic in handlers beyond
serialization/deserialization + calling a domain op or driver method. The AST
boundary check stays green (domain untouched here).

## 4. Components

All changes are in `helao/framework/app/orch_api.py`, inside `makeOrchApp` (new
root-path routes) and possibly a few small `OrchDriver` methods.

### 4.1 Deserialization helpers

The wire payloads (from `RemoteBackend`/`HelaoOperator`) carry plain dicts:
- `add_sequence` posts `{"sequence": <seq dict>}`; `prepend_sequences` posts
  `{"sequences": [<seq dict>, …]}`; `add_experiment`/`append_experiment` post
  `{"experiment": <exp dict>}`.

Add a small handler-local helper to build run-models from dicts:
`_as_run_sequence(d) -> RunSequence` and `_as_run_experiment(d) -> RunExperiment`
(the latter already exists in this module — reuse it). Build via
`RunSequence(**d)` / `RunExperiment(**d)`, filtering to model fields if needed
(same pattern as SP-ORCH-1's `get_seq`/`get_exp`).

### 4.2 Query endpoints (root path) — call SP-ORCH-1 read ops

- `POST /get_histories` → `orchestration.histories_payload(state)`
- `POST /get_status_summary` → `orchestration.status_summary_payload(state)`
- `POST /get_step_flags` → `orchestration.step_flags_payload(state)`
- `POST /set_step_flag` (kind, value) → `orchestration.set_step_flag(state, kind, value)`
- `POST /get_orch_state` → `orchestration.orch_state_payload(state)` **plus** the
  `active_sequence`/`active_experiment` keys folded in (via
  `get_active_sequence`/`get_active_experiment`) — addresses the SP-ORCH-1
  carry-forward so the operator can label the running seq/exp.
- `POST /list_sequences` (limit) → `[s for s in orchestration.list_sequences(state, limit)]` serialized (each `.as_dict()`).
- `POST /list_experiments` (limit) → `orchestration.list_experiments(state, limit)` serialized.
- `POST /list_actions` (limit) → `orchestration.list_actions(state, limit)` serialized.
- `POST /get_queue_object` (kind, idx) → `orchestration.queue_object_payload(state, kind, idx)`
- `POST /get_active_sequence`, `POST /get_active_experiment` → the getter dicts.
- `POST /latest_sequence_uuids`, `/latest_experiment_uuids`, `/latest_action_uuids` → the uuid lists.

> `list_*` return summary models (`SequenceModel`/`ExperimentModel`/`ActionModel`);
> the handler serializes each to a dict (`.as_dict()` / `.clean_dict()`) so the
> response is JSON. `RemoteBackend` then trims to its `_SEQ_KEYS`/`_EXP_KEYS`.

### 4.3 Mutation endpoints (root path) — call SP-ORCH-1 mutation ops

- `POST /append_sequence` (`{"sequence": d}`) → `append_sequence(state, _as_run_sequence(d))`; return `{"sequence_uuid": str(seq.sequence_uuid)}`.
- `POST /insert_sequence` (`{"sequence": d}`, idx) → `insert_sequence(state, _as_run_sequence(d), idx)`.
- `POST /prepend_sequences` (`{"sequences": [d, …]}`) → `prepend_sequences(state, [_as_run_sequence(d) …])`; return the uuid list (stringified).
- `POST /move_sequence` (from_idx, to_idx) → `move_sequence(state, from_idx, to_idx)`.
- `POST /remove_sequence` (idx) → `remove_sequence(state, idx)`.
- `POST /append_experiment` (`{"experiment": d}`) → `append_experiment(state, _as_run_experiment(d))`; return `{"experiment_uuid": str(...)}`.
- `POST /insert_experiment` (`{"experiment": d}`, idx) → `insert_experiment(state, _as_run_experiment(d), idx)`.
- `POST /clear_sequences`, `/clear_experiments`, `/clear_actions` → the clear ops.
- `POST /add_split_sequences` (`{"sequence": d}`) → **fallback**: `append_sequence(state, _as_run_sequence(d))` and return `[str(seq.sequence_uuid)]`. (Faithful to the legacy no-split branch; real splitting needs split-config plumbing — follow-up.)

### 4.4 Control endpoints (root path) — alias the driver control surface

Register root-path aliases the operator/client call: `POST /start`, `/stop`,
`/skip`, `/estop`, `/clear_estop`, plus `/clear_sequences` etc. (already in §4.3).
These call the existing `driver.start()/stop()/skip()/estop()/clear_estop()` and
return the same `{loop_state|loop_intent}` dicts as the SP5 prefixed handlers. The
existing `/{server_key}/…` handlers stay (SP5 tests use them); the root aliases are
additional registrations sharing the driver methods.

> **`start` semantics:** the SP5 `driver.start()` awaits `run_dispatch_loop()` to a
> natural idle/stop, so the HTTP call blocks until the loop yields. That mirrors the
> existing prefixed `/start`. Preserve it (do not change loop semantics here).

### 4.5 Optional small driver helpers

If a handler needs a serialized list, add a thin `OrchDriver` convenience method
(e.g. `list_sequences(self, limit)` returning serialized dicts) only if it reduces
handler duplication; otherwise inline the domain-op call + serialization in the
route. Keep handlers thin.

## 5. Data flow

```
RemoteBackend._call("list_sequences") → async_private_dispatcher → POST /list_sequences
   → handler: orchestration.list_sequences(driver.state, limit) → [.as_dict()] → JSON
RemoteBackend.add_sequence(seq) → POST /append_sequence {"sequence": dump}
   → handler: append_sequence(driver.state, _as_run_sequence(dump)) → {"sequence_uuid": ...}
```

## 6. Error handling

- Unknown `set_step_flag` kind → the domain op raises `KeyError`; the handler lets
  it surface as a 500 (or maps to a 400) — match whatever the existing framework
  orch handlers do for bad input; keep minimal.
- `get_queue_object` / `move_sequence` / `remove_sequence` are snapshot-safe / no-op
  on bad indices (domain-op behavior) — handlers return the `{}`/state as-is.
- Deserialization failure (bad sequence dict) surfaces as a 422/500; not specially
  handled (parity with legacy which assumed well-formed payloads).

## 7. Test strategy

Tests under `helao/framework/tests/` (e.g. `test_app_orch_endpoints.py`) using a
FastAPI/Starlette `TestClient` against an app built by `makeOrchApp` (or
`makeApp(group="orchestrator")`) with fake ports (`FakeTransport`, fakes for
storage/eventsink/clock) and small `sequence_lib`/`experiment_lib`. Follow the
existing `test_app_base_api_*` client-test pattern.

- Query endpoints return the SP-ORCH-1 payload shapes (seed `driver.state` then
  `POST` and assert JSON): histories, status_summary, step_flags, queue_counts via
  get_orch_state, list_sequences/experiments/actions (limit honored), queue_object
  bounds, get_orch_state includes `active_sequence`/`active_experiment`, latest_uuids.
- Mutation endpoints change `driver.state`: append/insert/prepend (returns uuids,
  order), move/remove (+ bounds no-op), clear_*, set_step_flag round-trip.
- `append_sequence`/`append_experiment` deserialize a posted dict into a Run-model
  and enqueue it (assert `driver.state.sequence_dq` grew with the right name).
- `add_split_sequences` fallback enqueues one sequence and returns its uuid list.
- Root-path registration: assert the routes exist at `/list_sequences` etc. (no
  `server_key` prefix) — e.g. `POST /list_sequences` returns 200.
- A serialize round-trip mirroring `RemoteBackend`: post a seq, `list_sequences`,
  confirm the dict carries the keys `RemoteBackend` trims to.

Full framework suite + AST boundary check stay green.

## 8. API parity

Endpoint names match exactly what `RemoteBackend._call(...)` and `HelaoOperator`
request: `list_sequences`, `list_experiments`, `list_actions`, `get_queue_object`,
`get_histories`, `get_status_summary`, `get_step_flags`, `set_step_flag`,
`get_orch_state`, `get_active_sequence`, `get_active_experiment`, `append_sequence`,
`insert_sequence`, `prepend_sequences`, `move_sequence`, `remove_sequence`,
`add_split_sequences`, `append_experiment`, `insert_experiment`, `clear_sequences`,
`clear_experiments`, `clear_actions`, `start`, `stop`, `skip`, `estop`,
`clear_estop`, `latest_sequence_uuids`, `latest_experiment_uuids`,
`latest_action_uuids`.

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Endpoint path mismatch (prefix vs root) | Register at root to match `async_private_dispatcher`; test asserts root paths |
| Run-model deserialization from dict fails on extra keys | Field-filter like SP-ORCH-1 `get_seq`; test posts a realistic dump |
| Mutating queues during the running loop | Domain ops synchronous + single-thread async = no interleave; documented; no lock |
| `add_split_sequences` not truly splitting | Faithful fallback to append (legacy no-split branch); documented follow-up |
| `start` blocks until loop idle | Preserved from SP5; unchanged semantics |

## 10. Done criteria

- All §8 endpoints registered at root in `makeOrchApp`, each a thin wrapper over an
  SP-ORCH-1 domain op or driver control method, with dict→Run-model deserialization.
- TestClient tests pass under the `helao` env; full framework suite still green; AST
  boundary check still green.
- No legacy `core/**` or `deploy/**` modified.
- Ready for SP-ORCH-3 (status WS + end-to-end RemoteBackend↔framework orch).
