# Framework Action Lifecycle — Design Spec (Sub-project 4)

**Date:** 2026-06-22
**Status:** Approved (standing authorization)
**Parent spec:** `docs/superpowers/specs/2026-06-22-helao-framework-core-rewrite-design.md` (§4.1, §4.2, §4.3)
**Branch:** stacked on `feat/framework-scaffold` (PR #176).

---

## 1. Goal

Rebuild the action-execution machinery (`Active` 41 methods + `Base` action-containment + `Executor`) as a **pure domain state machine** driving I/O through ports, plus the thin `app/base_api.py` wiring and the `makeApp(server_key)` factory. This is the heart of the rewrite (parent spec §4.1–4.3). Depends on SP0–SP3.

## 2. The inheritance decision (deferred from SP1)

**Finding.** `Active` *composes* a runtime `Action` (`self.action = activeparams.action`), it does not subclass it. The runtime `Action(Experiment(Sequence))` triple-inheritance is load-bearing **only as a field carrier + behavior host**: it gives one object the union of sequence+experiment+action fields plus runtime-only fields (`file_conn_keys`, `data_stream_status`) and the methods `init_act`/`init_seq`/`init_exp`/`get_*_dir`/split linkage. The pure `ActionModel` (ported SP1) has action+experiment-uuid fields but lacks sequence provenance and the runtime fields.

**Decision: flatten the diamond to single inheritance + extract behavior to pure functions.**

- `domain/run_models.py`: runtime models by **single** inheritance, no MRO diamond:
  - `RunSequence(SequenceModel)` — adds `dispatched_experiments`.
  - `RunExperiment(ExperimentModel)` — adds `dispatched_actions`.
  - `RunAction(ActionModel)` — adds the runtime-only fields (`file_conn_keys`, `data_stream_status`) **and explicitly declares the sequence/experiment provenance fields the action server needs** (`sequence_uuid`, `sequence_name`, `sequence_timestamp`, `sequence_label`, `sequence_output_dir`, `experiment_name`, `experiment_output_dir`, etc.). These were previously inherited from the `Sequence`/`Experiment` bases; now they are an explicit, documented field list on `RunAction` — denormalized provenance, same serialized shape.
- `domain/lifecycle.py`: the behavior, as **pure functions** (no I/O), operating on run-models and returning **command/result value objects** (parent spec A→C runway):
  - `init_action(action, *, now, uuid, manual_names) -> ActionInit` (assigns timestamp/uuid/status/output_dir; auto-promotes manual actions by also initializing synthetic sequence/experiment identity). The wall-clock and uuid are **passed in** (from the `Clock` port + a uuid factory), never read inside.
  - `action_output_dir(action) -> str`, `experiment_output_dir(...)`, `sequence_output_dir(...)` — pure path computation (the `get_*_dir` logic).
  - `split_action(action, *, now, uuid) -> SplitResult` — produces the new/old action states + the file-connection open/close commands.

**Rationale.** No diamond MRO (the thing that made the model hierarchy hard to reason about); provenance is explicit and greppable; behavior is pure and unit-testable with injected clock/uuid; serialized output unchanged (byte-compat invariant). `RunExperiment`/`RunSequence` full orchestrator behavior (PlanMakers, dispatched-action rollup) is SP5 — SP4 defines them minimally (the fields the action path touches) and SP5 completes them.

## 3. Domain core: the action session (ex-`Active`)

`domain/action_session.py` — `ActionSession`: the state machine, **pure** (all I/O via injected ports).

- Holds a `RunAction`, an `action_list` of split siblings, counters (`num_data_queued`/`num_data_written`), and references to injected ports (`Storage`, `EventSink`, `Clock`) + an `Executor`.
- States: `init → active → finish`, with `split` / `substitute` / `manual` transitions (per the map).
- Methods return command/result objects describing effects; the **caller in `app/`** executes them via ports. Where a method is hot/awaited (data enqueue), the port call is made directly through the injected port interface (still mockable). No FastAPI/httpx/aiofiles imports in this module.
- Side-effect taxonomy from the map maps onto ports:
  - **STORAGE** (`write_file`, `write_act/exp/seq`, `_write_meta_atomic`, `track_file`, `relocate_files`, HLO header/data writes, post-processor run) → `ports/storage.py` (extended for streaming HLO writes — see §5).
  - **EVENTSINK** (`add_status`, `enqueue_data`, status/data broadcast) → `ports/eventsink.py`.
  - **CLOCK** (timestamps, poll sleeps) → `ports/clock.py`.
  - **TRANSPORT** (`_finish` exporting `to_global_params`, queued redispatch) → `ports/transport.py` (Protocol exists; concrete HTTP adapter is SP5 — SP4 uses the fake in tests).

## 4. Executor contract

`domain/executor.py` (or `ports/executor.py`) — port the `Executor` four-phase contract (`_pre_exec`/`_exec`/`_poll`/`_post_exec`/`_manual_stop`, `oneoff`/`poll_rate`/`concurrent`/`duration`) near-verbatim; it is already a clean abstraction. Driver-author subclasses implement the phases. `ActionSession.action_loop_task` drives it: pre → (exec | poll-loop until non-active status) → manual_stop? → post, enqueuing data from each phase. The loop is pure aside from the injected `Clock` (poll sleep) and `EventSink` (data enqueue).

## 5. Port extensions needed

The scaffold ports were minimal. SP4 extends them (and updates the fakes) to carry the action path:

- `ports/storage.py`: add streaming-HLO operations — open a file connection (header write), append a data row, close; write atomic meta (`.act`/`.exp`/`.seq` YAML); copy/relocate an aux file; run a post-processor. Keep the existing `write_json`/`read_json`. The fake records writes in memory; the fs adapter (real) is built here (`adapters/fs_storage.py`).
- `ports/eventsink.py`: already `emit(channel, payload)`. Add a typed `emit_status`/`emit_data` convenience or keep generic `emit` with channel constants. Fake already records.
- `ports/transport.py`: unchanged (used via fake here; real adapter SP5).
- `ports/clock.py`: unchanged.

All port changes must keep existing SP0 tests green (extend, don't break).

## 6. App wiring

- `app/base_api.py` — composition: builds the `RunAction` from the request context (the ex-`Base._get_action`/`setup_and_contain_action`), injects concrete adapters (`fs_storage`, a websocket/queue eventsink, `ntp_clock`), registers the `Active`-equivalent in an `actives` registry, drives the loop. FastAPI lives ONLY here.
- `app/factory.py` — `makeApp(server_key) -> HelaoFastAPI` (port of the existing factory; deployments call this). May be a thin stub in SP4 if full server assembly needs orchestrator pieces — minimum: it builds an app exposing an action endpoint that runs an injected dummy executor end-to-end (proves the wiring).
- Public author surface preserved: subclass/instantiate, `setup_and_contain_action`, `active.enqueue_data`, `active.finish`, same method names, delegating to domain + ports.

## 7. Testing

- **Domain (the bulk, ≥90% gate):** unit-test `lifecycle` (init/dir/split with injected clock+uuid → assert returned command objects + run-model state), `action_session` (drive through init→active→finish + split/substitute/manual with fake ports → assert STORAGE/EVENTSINK/CLOCK calls and final state), `executor` (phase ordering, poll-until-status, manual stop) with a dummy executor.
- **Adapters:** `fs_storage` against a tmp dir — assert HLO file bytes (header + `%%\n` + JSON rows) match the legacy format exactly (byte-compat); meta YAML atomic write.
- **Wiring smoke:** `app/base_api` runs a dummy-executor action end-to-end through the real fs adapter, producing an HLO file.
- **Golden master (critical):** run a representative action on the OLD `Base`/`Active` (sim/dummy driver) and assert the new path produces byte-identical `.hlo`/`.act` output for the same input.
- Coverage gate stays ≥90% on domain+models+support (now + new domain).

## 8. Out of scope

- Orchestrator, dispatch loops, `Orch` (SP5).
- The real HTTP transport adapter + dispatcher + zmq rpc (SP5).
- Full `RunExperiment`/`RunSequence` orchestrator behavior + PlanMakers (SP5).
- Visualizer/operator (later cycle).
- Deployment migration.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Active is huge; one pass too big | Decompose SP4 into waves: run_models+lifecycle → action_session core → executor+loop → storage adapter+HLO bytes → app wiring+golden master |
| HLO byte format drift | fs_storage adapter tested for byte-identical output; golden-master test vs old Base/Active |
| Flattening RunAction drops a field the server needs | Enumerate fields from the map (§4 PREMODELS USAGE); a test asserts RunAction has every field old Action exposed to Active |
| `_uptime` inherited bug (driver) surfaces here | Fix in this SP per memory note; flip its pinning test |
| Hidden orchestrator coupling in Active (`to_global_params` via dispatcher) | Use the transport port + fake in SP4; real adapter SP5 |
