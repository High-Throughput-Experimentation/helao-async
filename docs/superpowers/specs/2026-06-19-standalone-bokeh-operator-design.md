# Standalone Bokeh Operator — Design Spec

**Date:** 2026-06-19
**Status:** Approved (design)
**Branch (planned):** `feat/standalone-operator`

## 1. Problem

`BokehOperator` (`helao/core/servers/operator/bokeh_operator.py`, ~2280 lines) is the
human-facing UI for driving an orchestrator: it renders the sequence/experiment/action
queues and histories, lets a user pick library sequences/experiments and edit their
parameters, and exposes start/stop/skip/clear/estop and step-through controls.

Today it runs **in-process inside the orchestrator**. `Orch.start_operator()`
(`orch.py:273`) spawns a Bokeh `Server` on `bokeh_port` and hands the `BokehOperator` a
live reference to the `Orch` object. Every UI action is a direct Python call
(`self.orch.add_sequence(...)`, `self.orch.action_history`, `self.orch.step_thru_actions`,
`self.orch.unpack_sequence(...)`). This couples the operator to the orchestrator process:
it cannot be launched, restarted, or scaled independently, and there is exactly one
operator per orchestrator, hosted by that orchestrator.

## 2. Goal

Provide an **alternative operator that is launched like a visualizer** — a standalone
Bokeh app declared in the config and started by `bokeh_launcher.py` — that controls an
orchestrator **over OrchAPI HTTP/RPC endpoints** instead of an in-process object
reference. It must implement all existing `BokehOperator` functionality.

Non-goal: removing or changing the existing in-orch operator's behavior. The in-orch
operator continues to work exactly as before.

## 3. Decisions (locked during brainstorming)

| Topic | Decision |
|-------|----------|
| HTE plate-map / sample-picker | Keep, but as a **pluggable, hte-only hook** — core operator stays deployment-agnostic; plate-map widgets activate only when config points at `HTEPlateAPI`/PAL. |
| Library metadata + sequence unpacking | Operator **loads libs locally** via the same `import_autolibs` helper the orch uses; mutations go over HTTP. |
| Code sharing with existing operator | **Orch-access abstraction layer**: one `BokehOperator` UI class, two backends (`LocalBackend`, `RemoteBackend`). |
| Live sync | Subscribe to orch's existing **`ws_status`** WebSocket + a **slow poll** safety net; manual "Update tables" button stays. |
| Param-input UX | **Keep per-param widgets** (1:1 port of current TextInput/Select layout, red-on-change highlight, plate-map/file-upload hooks). No table input. |
| Target orch selection | Auto-detect the lone `group: orchestrator` server in `world_cfg`; override with `params.orch_key`. |
| Server group / launch | `group: operator`, `bokeh: <module>`; launched by `bokeh_launcher.py` via a deployment `makeBokehApp` shim. |

## 4. Architecture

### 4.1 Module layout

```
helao/core/servers/operator/
  orch_backend.py     NEW       OrchBackend ABC + LocalBackend + RemoteBackend
  bokeh_operator.py   REFACTOR  BokehOperator UI talks only to self.backend
deploy/<dep>/servers/operator/
  <name>.py           NEW shim  makeBokehApp(doc, confPrefix, server_key, helao_repo_root)
```

### 4.2 `OrchBackend` (ABC)

The single seam between UI and orchestrator. Every place `BokehOperator` currently
touches `self.orch.*` is replaced by a backend method. Methods (grouped):

**Reads (queues / state):**
- `list_sequences() -> list[Sequence]`
- `list_experiments() -> list[Experiment]`
- `list_actions() -> list[Action]`
- `get_histories() -> dict` — `{"action": [...], "experiment": [...], "sequence": [...]}`,
  each a list of `(uuid, dict)` items (mirrors `orch.*_history.items()`).
- `get_status_summary() -> dict[str, tuple[str, str]]` — `{server: (server_status, driver_status)}`.
- `get_orch_state() -> dict` — loop_state + active/last sequence/experiment (already an endpoint).
- `loop_state -> LoopStatus`, `current_stop_message -> str`,
  `active_sequence`, `active_experiment` (derived from `get_orch_state`).
- `get_global_params() -> dict`.
- `get_step_flags() -> dict` — `{"actions": bool, "experiments": bool, "sequences": bool}`.

**Library (local in both backends):**
- `sequence_lib`, `experiment_lib` — name→callable dicts.
- `unpack_sequence(sequence_name, sequence_params) -> list[Experiment]`.

**Mutations (control):**
- `add_sequence(sequence)`, `add_split_sequences(sequence)`
- `start()`, `stop()`, `skip()`, `estop()`
- `clear_sequences()`, `clear_experiments()`, `clear_actions()`
- `set_step_flag(kind: str, value: bool)`

**Live sync:**
- `subscribe(on_change: Callable)` — register a callback invoked whenever orch state
  may have changed. UI passes a handler that schedules `update_tables` on the Bokeh doc.
- `close()` — tear down subscriptions/tasks on session destroy.

All read/mutation methods are **async** (the UI already wraps every orch call in
`doc.add_next_tick_callback`, so async is compatible). `sequence_lib`/`experiment_lib`
and `unpack_sequence` are sync (pure local Python), matching current usage.

### 4.3 `LocalBackend(orch)`

Thin pass-through to the live `Orch`. Each method delegates to the existing
`orch.*` call/attribute. `subscribe(on_change)` wires the existing in-process push:
sets `orch.orch_op` to a small shim whose `update_q.put(...)` triggers `on_change`
(preserving the current `orch.update_operator` → `update_q` → `IOloop` flow).
Behavior is byte-for-byte the current in-orch operator.

### 4.4 `RemoteBackend(vis, orch_key)`

- Resolves `orch_key` → `(host, port)` from `vis.world_cfg["servers"]`.
- **Libs:** loads `experiment_lib`/`sequence_lib` via `import_autolibs(world_config_dict=vis.world_cfg, lib_dir=None, user_lib_dir=vis.helaodirs.user_exp|user_seq, lib_type=...)`. codehash/codepath libs are discarded — orch re-stamps on receipt. `unpack_sequence` copies orch's one-liner: `self.sequence_lib[name](**params)`.
- **Reads/mutations:** `async_private_dispatcher(orch_key, host, port, "<endpoint>", params_dict=..., json_dict=...)`. List/state endpoints already exist; new endpoints in §5.
- **Sequence serialization:** `add_sequence`/`add_split_sequences` send the locally-built `Sequence` as the JSON body (`{"sequence": seq.model_dump()}` to match `Body(..., embed=True)`).
- **Live sync:** `subscribe` opens a `WsSubscriber` on the orch's `ws_status` URL (same util visualizers use) in a background task; each received message calls `on_change`. A parallel slow poll (default 5 s, `params.poll_interval`) calls `on_change` as a safety net. `close()` cancels both.

### 4.5 `BokehOperator` refactor

- Constructor signature `__init__(self, vis_serv, backend)` (was `(vis_serv, orch)`).
- Replace every `self.orch.X` with `self.backend.X`. Specific touch points to migrate
  (from current code): `sequence_lib`/`experiment_lib`, `list_sequences/experiments/actions`,
  `action_history`/`experiment_history`/`sequence_history` → `get_histories`,
  `status_summary` → `get_status_summary`, `globalstatusmodel.loop_state` →
  `loop_state`/`get_orch_state`, `active_sequence`/`active_experiment`,
  `add_sequence`/`add_split_sequences`, `start`/`stop`/`skip`/`estop_loop`,
  `clear_sequences/experiments/actions`, `unpack_sequence`, step flags
  (`step_thru_actions` etc. + `flip_stepwise_flag`) → `get_step_flags`/`set_step_flag`,
  `global_params`, `current_stop_message`, `world_cfg["root"]` for `previous_params.json`.
- `world_cfg["root"]` for `previous_params.json` read/write uses `vis.world_cfg["root"]`
  (available on both backends; operator is co-located with orch), not an orch attribute.
- Live-update wiring (`IOloop`/`update_q`) replaced by `backend.subscribe(on_change)`
  where `on_change` schedules `update_tables`. `cleanup_session` calls `backend.close()`.
- **Plate-map hook:** the `HTEPlateAPI`-dependent methods (`get_pm`, `get_samples`,
  `get_sample_infos`, `get_elements_plateid`, `callback_clicked_pmplot`,
  `callback_changed_plateid`, plate-map widget creation in `add_dynamic_inputs`) move
  behind a `plate_api` attribute that is `None` unless configured. A config param
  (`params.plate_api: "HTEPlateAPI"` or similar) enables it; when absent, the special
  `solid_plate_id`/`solid_sample_no`/`x_mm`/`y_mm` widgets degrade to plain inputs.
  This makes the core operator importable without hte deps.

### 4.6 In-orch operator wiring

`Orch.makeBokehApp` (`orch.py:296`) constructs `BokehOperator(app.vis, LocalBackend(orch))`
instead of `BokehOperator(app.vis, orch)`. No other orch changes for the local path.

## 5. New OrchAPI endpoints

Added to `helao/core/servers/orch_api.py` (all `tags=["private"]`, POST):

| Endpoint | Body / params | Returns | Backing |
|----------|---------------|---------|---------|
| `/get_histories` | — | `{"action":[...],"experiment":[...],"sequence":[...]}` (uuid,dict items) | `orch.*_history.items()` |
| `/get_status_summary` | — | `{server: [server_status, driver_status]}` | `orch.status_summary` |
| `/get_step_flags` | — | `{"actions":bool,"experiments":bool,"sequences":bool}` | `orch.step_thru_*` |
| `/set_step_flag` | `kind: str, value: bool` | `{kind: value}` | sets `orch.step_thru_<kind>` |
| `/clear_sequences` | — | `{}` | `orch.clear_sequences()` (no endpoint exists today) |
| `/append_split_sequences` | `sequence: Sequence` (embed) | `{"sequence_uuids":[...]}` | `orch.add_split_sequences()` |

Already-present endpoints reused: `/list_sequences`, `/list_experiments`,
`/list_actions`, `/get_orch_state`, `/global_status`, `/get_global_params`,
`/append_sequence`, `/start`, `/stop`, `/skip_experiment`, `/estop_orch`,
`/clear_experiments`, `/clear_actions`, `ws_status`.

Endpoint handlers delegate to existing `orch` methods/attributes; serialization mirrors
the patterns already in `orch_api.py` (`clean_dict()` / `as_json()` where models are
returned). History/status payloads are plain dicts of primitives (already the case for
`action_history` entries and `status_summary`).

## 6. Config wiring

Operator server entry (example):

```yaml
  OP:
    group: operator
    bokeh: standalone_operator      # module under deploy/<dep>/servers/operator/
    host: 127.0.0.1
    port: 5004
    params:
      orch_key: ORCH                # optional; default = lone group:orchestrator server
      plate_api: HTEPlateAPI        # optional; enables plate-map hook
      poll_interval: 5              # optional; live-sync safety-net seconds
      doc_name: "Standalone Operator"
      # plus existing operator params: seqspec_parser_path, seqspec_folder_path,
      # skip_default_highlights, parser_kwargs
```

Deployment shim `deploy/<dep>/servers/operator/standalone_operator.py` mirrors the
visualizer shim (`live_visualizer.py`): build a `HelaoVis`, construct
`RemoteBackend(app.vis, orch_key)`, then `BokehOperator(app.vis, backend)`, add a header
banner, return `doc`.

`bokeh_launcher.py` already imports `deploy.<dep>.servers.<group>.<bokeh>` and calls
`makeBokehApp`; `group: operator` + `bokeh:` is launched in the `operator` phase of
`LAUNCH_ORDER`. (Verify launcher handles `bokeh:` for the operator group during
implementation; if it special-cases visualizers, extend it.)

## 7. Error handling

- **Orch unreachable:** `async_private_dispatcher` already retries then returns
  `(None, error_code)`. RemoteBackend treats a non-`none` error code as "no update":
  logs once, leaves last-known table data, and flips the orch-status banner to a
  `danger` "orchestrator unreachable" state. It does not crash the Bokeh session.
- **ws_status drop:** the slow poll keeps tables fresh; the WS task auto-reconnects
  (WsSubscriber behavior) — on permanent failure the poll is the sole path.
- **Lib mismatch:** if a selected sequence/experiment name is missing from the locally
  loaded lib (operator/orch config drift), `unpack_sequence` raises `KeyError`; caught
  and surfaced in the existing `error_txt` banner rather than propagating.
- **Mutation failures** (e.g. `start` while estopped): rely on orch-side guards (the
  endpoints already no-op/log); RemoteBackend refreshes state after each mutation so the
  UI reflects the true orch state.

## 8. Testing

No pytest harness in-repo; follow the data-browser precedent — standalone scripts under
`helao/core/tests/` plus mock-backed unit tests.

- **`OrchBackend` contract test:** a `FakeOrch` exercised through `LocalBackend` and a
  `FakeDispatcher` through `RemoteBackend`, asserting both satisfy the same method set
  and return equivalently-shaped data.
- **RemoteBackend serialization:** `add_sequence`/`add_split_sequences` produce a body
  that round-trips through `Sequence(**body["sequence"])`; `unpack_sequence` returns the
  same `planned_experiments` as a direct lib call.
- **Lib loading parity:** `import_autolibs` on a test config yields the same
  `sequence_lib`/`experiment_lib` keys the orch would load.
- **Endpoint smoke:** new orch_api endpoints return expected shapes against a `FakeOrch`.
- **BokehOperator wiring smoke:** construct `BokehOperator` with a mock backend; assert
  layout builds, tables populate, `subscribe` callback triggers `update_tables`, and
  `close()` is called on session destroy. (Mirrors data-browser's bokeh smoke test.)
- **Manual:** launch a `test`-deployment config with a `group: operator` standalone
  operator against a running orch; exercise add → start → stop → skip → clear → estop
  and confirm live table refresh.

## 9. Out of scope

- Removing the in-orch operator.
- Table-based parameter entry (explicitly deferred; keep per-param widgets).
- Running the operator on a different machine than the orch (libs are loaded locally, so
  co-location is assumed; cross-host would require the thin-client/endpoint-fed variant).
- Auth/permissions on the new endpoints (consistent with current `private` endpoints,
  which are unauthenticated within a deployment).
