# B7b — Delete the legacy engine

**Date:** 2026-09-30
**Program:** Legacy separation (`2026-08-14-legacy-separation-program-design.md`), sub-project B7, second of three parts
**Branch:** `feat/b7b-delete-engine` off `unstable` `e60d800a`, one PR, ordered commits
**Recovery point:** `freeze/pre-engine-delete_2609` = `e60d800a` (pushed; protected by the `freeze/*` ruleset)
**Status:** design approved; this spec records the measurements and the decisions the approval left open

## 1. What B7b is, and the measurement that shapes it

B7a moved every symbol that native code borrowed from `helao/core/servers/` to a home outside it.
What is left is the engine itself, plus the code that exists only because the engine exists: the
graft machinery, the harness encoder that reproduces the legacy `OrchAPI` WS bytes, the tests that
drive engine classes, and the parity pins whose reference is the engine source. B7b deletes all of
it. It also dispositions the post-parity backlog, one item at a time.

The program spec (§5) says B7 changes nothing visible on disk or on the wire. B7b keeps to that,
with two exceptions it names. One is a log line: every `deployment: hexagon` action server stops
logging `"<key>: native ActionHost, skipping the active write graft"` at startup
(`factory.py:144–146`), because the branch it reports is deleted. The `makeOrchApp` twin at
lines 107–109 never logged, since that function has no production caller. The other is removing
the `/ws_globstat` sender, which has never had a route (§6.1).

The measurement that governs B7b is that **every live runtime path is already native**. The
engine is loaded today only through three files and the tests:

- `harness/ws_frames.py:88` imports `base_status.StatusBroadcaster`.
- `helao/hexagon/app/active_graft.py:26` imports `base.Active`.
- `helao/hexagon/app/factory.py` reaches the engine twice: `makeOrchApp` at line 79, and
  `makeActionApp` at line 122. `makeActionApp` imports `active_graft` unconditionally, which loads
  12 engine modules into every launched `deployment: hexagon` action server, even though every
  target is now an `ActionHost` and the graft branch is skipped (§2.3).

So the deletion is safe only if the tests are ported first. Deleting in the other order would
lose the golden masters, the only byte-level references the program has, at the moment they are
most needed. That ordering is the whole design (§4).

## 2. Measured surface

All figures were measured on `e60d800a`, in this worktree unless the text says otherwise.
Private-deployment figures come from the main checkout, where those repositories live.

### 2.1 The engine

`helao/core/servers/` holds 18 tracked files: 16 modules, an empty `__init__.py`, and
`CLAUDE.md`. The 17 `.py` files total 6,578 lines, and `CLAUDE.md` adds 13 more. The largest
modules are `base.py` (1,502 lines), `base_api.py` (912), `orch.py` (894) and `orch_api.py` (868).
`orch_unpack.py` (16 lines) and `orch_global_params.py` (6 lines) are B7a's re-export shims.

`CLAUDE.md` does not document the engine. It documents native traps in `orch_effects`,
`orch_dispatch`, `orch_status_sync`/`ingestion`, `ActionHost._loop_exception_handler`, and the
stop-requeue in `DispatchRunner._launch_action`. It moves (D-B7b.8). Root `CLAUDE.md:85` points
at it, and lines 69, 80 and 81 describe `base_api`/`Base`/`Orch` as the running hosts. Line 69
also still lists `servers/vis.py`, which B0 moved.

**The directory survives a `git pull`, and it imports when it does.** `helao/core/` has no
`__init__.py`, and `__pycache__` is gitignored. Git therefore leaves
`helao/core/servers/__pycache__/` behind on every checkout that had run the engine. The main
checkout holds 58 such `.pyc` files. While that directory exists,
`import helao.core.servers` succeeds as a namespace package; this was measured with a replica
under the scratch directory. Submodule imports fail, but the package import does not. This
worktree had no `__pycache__` at checkout, but the measurement runs for this spec created one.

### 2.2 Who imports the engine

An AST sweep of the 1,025 tracked `.py` files found the following. It covered `Import`,
`ImportFrom`, and string constants that name `helao.core.servers`.

| kind | files |
|---|---|
| production, outside the engine | 3: `harness/ws_frames.py`, `helao/hexagon/app/active_graft.py`, `helao/hexagon/app/factory.py` (the three B7a allowlist entries) |
| `helao/core/tests/` | 21: `test_active_golden_master`, `test_orch_dispatch_golden_master`, `test_analysis_recovery` (l.968), `test_orch_queue_paging` (l.18, l.66), `test_run_state_wiring` (l.319–320), `test_standalone_operator` (l.46, 111, 523, 550), `test_upload_set` (l.6), and 14 `unit_test_*` (§5.2) |
| `helao/hexagon/tests/` | 12: `native_fixtures`, `test_action_session_port` (l.86), `test_active_graft`, `test_estop_finish_race` (l.26), `test_estop_fixes` (five function-local `seq_unpacker` imports, l.385/402/419/546/569), `test_factory` (l.93, 129), and `test_native_{artifact_store,data_file,data_sink,data_stream,finalizer,meta_writer}` |
| runtime probe | `test_engine_import_ratchet._PROBE`, whose `legacy` mode builds `BaseAPI`/`OrchAPI` |
| strings that ban the prefix | `test_boundaries` (l.141–142, 258, 314–315; mutation victims written to disk and never imported), `test_control_surface_port:114`, `test_external_composition_contract:32`, `test_hte_is_native:29`, `test_test_deployment_is_native:32`, `test_ui_boundary:1, 26, 68`. These are unaffected and stay |
| the ratchet itself | `test_engine_import_ratchet.py` (l.1, 41 `ENGINE`, 121–131 detector fixtures, 153, 238), and the commit-4 `find_spec` probe |
| provenance docstrings and comments (string constants, never imported) | `helao/core/drivers/data/analysis_layout.py:1`; `helao/hexagon/adapters/native/{__init__,native_syncer,sync_driver}.py:1`; `helao/hexagon/adapters/vis/{browser_source,control_surface,param_store,spec_parser,ws_consumer}.py:1`; `helao/hexagon/ports/{browser_source,control_surface,param_store,spec_parser}.py:1`; `helao/hexagon/domain/pal_reconciliation.py:1`; `helao/hexagon/app/endpoint_overlay.py:58`; `helao/deploy/hte/drivers/robot/pal_driver.py:108, 144`; `helao/deploy/hte/tests/test_kinesis_counts.py:142`; `helao/hexagon/tests/test_galil_motion_counts.py:206`; and the docstrings of `test_active_golden_master.py:1` and `unit_test_base_api.py:1`, which commit 1 rewrites or deletes. Left as they are (D-B7b.10) |

**Source-path readers.** Six tests read engine files by path:

- `test_action_host_member_coverage.py:34` (`BASE_PY`);
- `test_orch_host_member_coverage.py:44` (`SEARCH_DIRS`);
- `test_ws_consumer_parity.py:37–38` (`BASE_API_PATH`, `ORCH_API_PATH`);
- `test_orch_host_surface.py:66` (`_legacy_orch_api_routes`);
- `test_bokeh_theme.py:555` and `test_palette.py:1785`, which include the engine directory in a
  glob.

**Other mentions.** `pyproject.toml:32,58` (the `force-exclude` alternation); the frozen sweeper
calibration fixtures `helao/core/tests/fixtures/sweeper_calibration/*.py.txt` (frozen by
`helao/ui/shared/CLAUDE.md`, and left alone); `helao/core/drivers/helao_driver.drawio/.svg`
(a diagram, left alone). There are also 63 non-test `.py` files whose docstrings, comments or
messages name `makeOrchApp`, `graft_hexagon_loop`, `active_graft`, `sync_graft`, `OrchAPI`,
`BaseAPI`, `StatusBroadcaster`, `base_api`, `orch_api` or `globstat`. Most of these are
provenance notes; D-B7b.10 (§3) gives the rule for which ones change.

**Private deployments.** No module imports the engine, apart from two archival files under an
excluded `notes/` tree in one private deployment. `run_tests.py`'s `SKIP_PARTS` never sweeps
those. Exactly one test file in one private deployment imports `harness.ws_frames`. It uses `build_data_payload`, `roundtrip("ws_data", "base_api", ...)`,
`STRING_COLUMN` and `STRING_VALUES`, and only the `base_api` family. No other private file uses
`ws_frames`. Configs, launchers and `importlib` strings contain no engine path.

### 2.3 The runtime paths

- **`makeActionApp`** (`factory.py:121–166`) imports `graft_active_write_path` at line 122. It
  grafts at line 148 unless `_is_native_host(app)` is true, and binds a `WsPublishBridge` over
  `app.base.status_q/data_q/live_q` at line 157. All 34 `fast: graft` server entries were checked
  by source. (The unit is server entries with `fast: graft` in every `.yml` anywhere under each
  private deployment's tree, smoke configs included: 13 in the private deployment whose remote is
  disabled, 11 and 10 in two others. `*_hex.py` variants were loaded separately; counting distinct
  `legacy_module` targets gives smaller numbers.) Every
  one constructs an `ActionHost`, either directly or through an hte module it delegates to, and
  none names `BaseAPI` or `helao.core.servers`. Tracked `deployment: hexagon` action servers go
  through named shims that call `makeActionApp` with a test or hte module, and all of those are
  native: `test_hte_is_native` and `test_test_deployment_is_native` pin it.
- **`makeOrchApp`** (`factory.py:78–118`) builds an `OrchAPI` and has no production caller.
  Both orchestrator shims, `helao/deploy/hexagon/servers/orchestrator/async_orch2.py` and
  hte's, build an `OrchHost` directly. Its remaining users are `test_factory` (l.92, 114),
  `test_vis_hexagon_producer_parity:576` and `test_orch_host_surface:276`.
- **`dispatch_loop.HexagonGraft` / `graft_hexagon_loop`** (lines 157–268) have one user outside
  tests, `makeOrchApp`. Four tests in `test_dispatch_loop.py` exercise them (l.143, 191, 210,
  249), and the brief did not list that file. `HexRuntime` and `HexDispatchLoop` stay, because
  `OrchHost._build_reducer` (`orch_host.py:1404`) uses them. `OrchHost` binds the health
  adapter itself at line 1414, which is why the docstring at `adapters/legacy/health.py:11` and
  the message at line 35 are stale.
- **`sync_graft.py`** (88 lines) has one production caller: the hexagon shim
  `helao/deploy/hexagon/servers/action/sim_db_server.py`. **No config routes to that shim.**
  Every tracked config's `SYNC` entry is `fast: sim_db_server` with no `deployment:` key; the
  eight configs are `golden`, `goldenhex`, `goldenhexconc`, `goldenhexgraft`, `goldenhexid`,
  `goldenhexvis`, `goldenlocal` and `goldenvis`. `test_db_gate_config.py:40–53` asserts that
  the key is absent. No private config names it either. The test deployment's `sim_db_server`
  already builds an `ActionHost`, and `live_group.py:152` uses it directly. The graft's only
  other callers are its own tests, `test_sync_graft` and `test_db_shim`. **Decision: delete it**
  (D-B7b.3). The case is clear-cut, so it is not an open question.
- **`run_unit_tests.py`** imports 37 test functions, not the 44 the recon counted: 36 from
  `helao/core/tests/`, plus `unit_test_oersim_params`. Fourteen of them import the engine.
  `launch.py:1831–1834` runs the script for the 12 tracked configs that set
  `run_unit_tests: true`: `controlneg`, `golden`, `goldenhex`, `goldenhexgraft`,
  `goldenhexreflex`, `goldenhexvis`, `goldenlocal`, `goldenreflex`, `goldenreflexspec`,
  `goldenvis`, `test-hookalias` and `test`. `test_hex.py` derives from `test.yml`. No private
  config sets it.
- **The launch smoke does not reach `makeActionApp`.** `goldenhex` sends only `ORCH` through
  the hexagon shim, and that shim builds an `OrchHost` without going through the factory. `SIM`
  and `SYNC` are plain test-deployment modules. The changed factory path is exercised live on
  Linux only by `live_group.py:155`, whose users are `test_live_group`, `test_concurrency_live`,
  `test_no_wait_overlap_live`, `test_stop_requeues_pending_action_live`,
  `test_estop_reaches_drivers_live` and `test_orch_legacy_parity_live`. On hardware, only the
  station gate exercises it.

### 2.4 The golden masters

Both golden masters are standalone scripts; `run_tests.py` reports them as `NOTESTS`. Both read
their frozen references from `.omc/`, which is gitignored and exists only in the main checkout.
To measure them, the scripts and the references were copied into the scratch directory, and
imports were forced to this worktree.

- **The dispatch golden master** (`test_orch_dispatch_golden_master.py`, 9 scenarios) gave 7
  PASS and 2 DELTA against `.omc/artifacts/p5/baseline_S0/`. The deltas are deterministic, and
  both come from intended fixes:
  - S2 `has_pending: false → true` is the stop-requeue fix, now that `pending_action` is passed.
  - S7 `switch: false → true` is the change that makes E-STOP reach the drivers (`79a5a41d`).

  The baseline is stale, as the brief said.
- **The action golden master** (`test_active_golden_master.py`, 13 scenarios) gave 13 PASS
  against `.omc/artifacts/p6/baseline_S0a/`. **It is not stale.** It does have a trap: run from
  a current directory that is not a git checkout, all 13 come back DELTA. `hlo_version` resolves
  through `git rev-parse` in the current directory (`helao/core/version.py`), so it becomes
  empty and drops out of every `-act.yml` and `.hlo` header.
- **A native dispatch capture was prototyped** with the engine present. The fixture was swapped
  for `OrchHost.__new__`, then `_init_orch_collaborators()`, then a `PortWiring` carrying
  `LegacyLoggingAdapter` and `LegacyHealthAdapter`, then `_build_reducer()`. The capture was
  compared against a fresh legacy capture of the same script. S1–S6, S8 and S9 are
  **byte-identical**. S7 differs by one block: the native trace has no
  `{"event": "intent_call", "method": "intend_none"}`. That difference is the documented
  behaviour of `OrchHost.estop_loop` (`orch_host.py:1086–1098`, DD-5 item 6). The reducer
  applies the none→none intent delta without calling `intend_none()`, and wakes `interrupt_q`
  with `"estop"` directly. Both captures are deterministic over two runs each.
- **`set_error` has one caller outside the engine:** the action golden master's scenario 5
  (`_scenario_error_estop`, lines 918–948). It has no native caller in the parent or in any
  private deployment. `ActionSession` has no `set_error`, `substitute` or `finish_all`; the
  last two exist on `NativeActionFinalizer` (`finalizer.py:74, 82, 204`).

### 2.5 The tests that build on legacy fixtures

`native_fixtures.py` (115 lines) builds a **legacy** `Base.__new__` and a legacy `Active`, at
lines 19, 27 and 84. Six native test files depend on it: `test_native_*` for artifact_store,
data_file, data_sink, data_stream, finalizer and meta_writer. That makes 6, not 8:
`test_endpoint_overlay` names it only in a docstring, and `test_active_graft` dies. So deleting
the four `test_source_parity_with_legacy` pins does not free those files. The fixture has to be
rebuilt on `ActionHost` and `ActionSession`. `sync_fixtures.py` has its own `assert_source_parity`
over `helao/core/drivers/data/sync_driver.py`, which is not engine code, and it stays.

The member-coverage ratchets measure their contract from engine source. The Base public members
number 89. The orchestrator contract is 138 members; the docstring says 136. Take
`helao/core/servers` out of `SEARCH_DIRS` and `orch_api` out of `CONSUMERS`, and the contract
falls to 103: 35 members silently leave it, and the test's own `> 130` floor fails.

### 2.6 WS frames

The native orchestrator relay is `orch_host.py:1324–1383` (`_register_orch_ws_routes`). It uses
`WsPublisher(self.status_q, lambda m: m.as_dict())` for status and data, and
`WsPublisher(self.live_q)` for live. `WsPublisher.broadcast` sends
`pyzstd.compress(pickle.dumps(xform(msg)))` (`ws_utils.py:76–80`), which is the same expression
as `StatusBroadcaster._ws_relay` (`base_status.py:252–253`), so equal payloads encode to equal
bytes. `encode_base_api` (`ws_frames.py:251`) is already engine-free. The consumers of the
`orch_api` family are:

- `test_ws_frames` (via `FAMILIES`);
- `test_ws_consumer_parity:130, 219, 253`;
- `test_status_consumer_faces:149–173`;
- `test_vis_hexagon_producer_parity:317–318, 610, 620`.

The hte and test deployments' `test_vis_ws_parity`, and the private test, use only `base_api`.

### 2.7 Checklists

- `helao/hexagon/tests/checklists/orch_openapi_legacy.json` holds 74 routes and was captured
  from a launched legacy orchestrator. A live `OrchHost` serves 77. The three it adds are
  `/get_config`, `/hotreload_busy` and `/resend_active`, all POST; the frozen capture misses
  none, and neither params nor tags have drifted. The gate compares params only, and has two
  blind spots:
  - 20 routes carry a `requestBody` that is never compared;
  - 3 parameters are `$ref` enums, which the capture records as `type: null`
    (`openapi_capture._params`, lines 53–80).

  `test_the_route_surface_matches_the_live_legacy_orchestrator` checks only that no frozen
  route is missing. It never checks for extras.
- `checklists/hte/_baseapi_system_surface.json` was captured live from a legacy `BaseAPI`.
  `test_action_host_surface` compares `ActionHost`'s path set against it. Nothing in that test
  reads the engine.
- **The deployment checklists are not captured from legacy hosts.** That covers
  `checklists/hte/*.json` (28 files) and each private deployment's `tests/checklists/`.
  `harness/freeze.py` and `harness/hte_freeze.py` write them from `harness.endpoints.extract_routes`,
  an AST read of each deployment's own server modules. B7b edits no deployment server module,
  so **no deployment checklist is re-frozen**, and the private deployment whose remote is
  disabled needs no change at all.
- Known checklist drift, re-measured on `e60d800a`: exactly the five IDs B7a recorded.
  - `harness/tests/test_hte_checklist.py::test_frozen_matches_regenerated[andor_server.py-ANDOR]`
  - `harness/tests/test_hte_checklist.py::test_frozen_matches_regenerated[biologic_server.py-BIOLOGIC]`
  - `harness/tests/test_hte_checklist.py::test_frozen_matches_regenerated[nidaqmx_server.py-NI]`
  - `helao/hexagon/tests/test_hte_route_checklist.py::test_module_matches_its_frozen_checklist[andor_server.py]`
  - `harness/tests/test_freeze.py::test_hte_freeze_is_clean_and_skips_nothing`

### 2.8 The backlog, measured

- **`/ws_globstat` has never had a route**, on legacy or native (`orch_host.py:960–965`
  docstring; `test_ws_consumer_parity.py:180–199`). What exists is dead plumbing:
  - on `OrchHost`: the attributes `globstat_broadcaster`, `globstat_q` and `globstat_clients`
    (`orch_host.py:173, 179, 180`); the methods `globstat_broadcast_task` and `ws_globstat`
    (956–965); the feed `await self.globstat_q.put(interrupt.as_json())` inside
    `wait_for_interrupt` (1002); the task start (1439–1441); and the shutdown cancel (1491);
  - on `StatusIngester`: `ws_globstat` and `globstat_broadcast_task`
    (`orch_status_sync.py:298–319`), and a commented-out put at line 294;
  - a port member with no implementer and no caller: `NotifyPort.publish_globstat`
    (`ports/auxiliary.py:74`);
  - tests: `unit_test_orch_status_sync`'s two globstat checks, the dispatch golden master's
    fixture lines 242/250–251, and `test_orch_stops_polling_on_shutdown.py:38`.

  The orchestrator member contract includes `globstat_q`.
- **`params.limit_vis` is live. The brief said it was dead, and that is wrong.** One private
  deployment's station config sets it on a Bokeh `action_visualizer`, to keep a device with no
  Bokeh visualizer module off that page. It was added 2026-09-22, after the 2026-08-05
  measurement of "zero configs". It is read at `ui/bokeh/vis_subscriber.py:126`,
  `ui/reflex/control.py:287` and `ui/reflex/app.py:446`. Three tests pin it:
  `test_reflex_control.py:69`, and two in `test_reflex_config.py` (l.192, 272).
- **`set_error`**: §2.4.
- **The 0.3 s pacing sleep** is `time.sleep(0.3)` at `action_host.py:763`. It blocks, and the
  comment above it (759–762) says it stays "until parity is signed off". The legacy twin is at
  `base_status.py:356`.
- **The finish-drain window** is two loops in `adapters/native/finalizer.py`. The first
  (318–343) re-enqueues a finished data-stream package while any stream is active. The second
  (346–371) waits while `num_data_queued > num_data_written`. Each is capped at 5 iterations of
  `asyncio.sleep(0.1)`. The legacy twin, `active_finalizer.py`, dies with the engine.

### 2.9 Environment facts every gate depends on

- The `helao` conda env exports `PYTHONPATH=<main-checkout>`. Without an override, `python <script>` run from this worktree imports the main
  checkout's `helao`. This was measured: `helao.__file__` resolved into the main checkout.
- `run_tests.py --list` finds **306** files in this worktree, which has no private deployments,
  and **415** in the main checkout.

## 3. Decisions

**D-S1, amended.** The recovery point for everything B7b ships is `freeze/pre-engine-delete_2609`
(`e60d800a`), not `freeze/pre-legacy-removal_2608`. A station that breaks after B7b resets its
parent checkout to that branch. B7b changes no private deployment repository, so those stay at
their current heads, all of which already run against `e60d800a`. The 2608 branch remains the
recovery point for the program as a whole.

**D-B7b.1 — Port before delete, one PR, ordered commits.** Section 4 lists the commits. Each has
its own check, and a commit that fails its check is fixed in place, never carried forward. The
engine stays importable until commit 3, so every port can be compared against legacy output.

**D-B7b.2 — `makeActionApp` accepts only native hosts.** It no longer imports `active_graft`. It
checks what `makeApp` returned **at build time**, before the startup event, where uvicorn would
otherwise report a failure only as `SystemExit(3)`:

```python
if not _is_native_host(app):
    raise TypeError(f"{legacy_module}.makeApp returned {type(app).__name__}, not an ActionHost")
```

The startup hook is renamed `_hexagon_ws_bridge_startup`. It keeps the `DispatcherStatusAdapter`
check and the `WsPublishBridge` bind (`factory.py:152–159`), and loses the graft branch.
`_hexagon_active_graft_shutdown` and the `hexagon_active_graft` attribute are deleted. The
`legacy_module` parameter name stays; renames are B7c's. `fast: graft` configs keep working
unchanged.

**D-B7b.3 — The graft machinery is deleted, not left dormant.** That covers:

- `makeOrchApp`, and its `__all__` entry;
- `dispatch_loop.HexagonGraft` and `graft_hexagon_loop`, lines 157–268, plus the imports only
  they use;
- `helao/hexagon/app/active_graft.py`;
- `helao/hexagon/app/sync_graft.py`.

The hexagon `sim_db_server` shim becomes the same three-line `makeActionApp` delegate as its 24
siblings. That is the one shim edit step 2 forces. Deleting the shim is B7c's.

**D-B7b.4 — `harness/ws_frames.py` keeps its public surface.** `FAMILIES` stays
`("base_api", "orch_api")`, and so do `roundtrip`, `frame`, the `build_*_payload` builders and
the sentinel constants. The private test and the parent tests listed in §2.6 name them, and program §5
freezes the two encoding families independently. Only the `orch_api` encoder changes, so that it
drives native code rather than a copy:

- `orch_host.py` gains a module-level
  `orch_ws_publishers(status_q, data_q, live_q) -> tuple[WsPublisher, WsPublisher, WsPublisher]`.
- `_register_orch_ws_routes` builds its three publishers with that function.
- `encode_orch_api` imports it inside the function, so importing the harness stays light for
  the private test, and drives `publisher.broadcast` through `_drain_one`.

`_FakeBase` and the `StatusBroadcaster` import are deleted.
`test_the_ws_routes_use_the_ORCH_family_encoding_not_the_action_one` keeps working, because the
`as_dict` lambda still lives in the publisher's `xform_func`.

**Commit 2's scratch byte comparison is the last legacy anchor for the `orch_api` family.**
After it, `test_vis_hexagon_producer_parity`'s orch-versus-hexagon checks compare native with
native. `test_ws_frames` and `test_status_consumer_faces` pin the decoded shape of the frame
(`dict` for status and data), not its bytes. Frozen frame bytes are not committed, because
`ws_frames.ACTION_UUID` is `uuid4()` at import, so the canonical payload's bytes differ in every
process.

**D-B7b.5 — The golden masters survive as native self-regressions with tracked baselines.**
Q3 covers where the baselines live and Q1/Q2 cover the two deltas; §4.1 gives the port. The
dispatch golden master drives `OrchHost`, and the action golden master drives `ActionSession`
over an `ActionHost`. Their frozen references are **native captures**. Each is accepted only
after it has been compared, byte for byte, against a legacy capture of the same script, taken
on the same commit while the engine is still present.

**D-B7b.6 — Tests are classified, never silently dropped.** Every test that touches the engine
falls into one of three classes:

- **port**: re-point it at native code;
- **move-and-delete**: move its uncovered checks into the named native twin, then delete the
  file;
- **delete**: its subject is engine-only.

A check is deleted only if one of two things is written into the plan: the native test that
covers it, or a reason it is engine-internal (wiring, delegation or source parity). The
per-file dispositions are in §5.

**D-B7b.7 — Frozen snapshots replace source-derived contracts.** The member-coverage ratchets
lose their reference when the engine goes. Before deletion, commit 1 freezes what they derive:

- `helao/hexagon/tests/checklists/base_member_surface.json`, the 89 Base public members;
- `helao/hexagon/tests/checklists/orch_member_contract.json`, the 138-member orchestrator
  contract.

Afterwards, the action test reads the JSON, and the orchestrator test checks the JSON's members
together with a live extraction over `helao/hexagon/app` consumers. Both floors stay. The JSON
can only shrink when a member is retired on purpose, as commit 5 does for `globstat_q`.

**D-B7b.8 — `helao/core/servers/CLAUDE.md` moves to `helao/hexagon/app/CLAUDE.md`, content
intact.** Only the title changes, to "dispatch loop and host traps". Root `CLAUDE.md` changes as
follows:

- line 85 points at the new path, and its "read it before editing `orch.py`" becomes "before
  editing `orch_host.py`, `orch_effects.py` or `orch_dispatch.py`";
- lines 80–81 describe `ActionHost` (`helao/hexagon/app/action_host.py`) and `OrchHost`
  (`orch_host.py`);
- line 69 lists `helao/core/` as models, drivers, rpc, runners, error and `hooks/` (the
  finish-hook extension point), and drops `servers/*`.

**D-B7b.9 — The directory is removed with `rm -rf`, and the ratchet can tell.** Commit 3 runs
`rm -rf helao/core/servers`, which takes `__pycache__` with it. Commit 4 adds a runtime
assertion to the ratchet, in a fresh subprocess with `PYTHONPATH` set to the repo root:

- `importlib.util.find_spec("helao.core.servers") is None`;
- `import helao.core.servers.base` raises `ModuleNotFoundError`.

The first half fails on any checkout that still holds a stale `__pycache__`, which is correct:
a namespace package importing silently is the hazard. Its failure message must say
`rm -rf helao/core/servers` (Linux) or `rmdir /s /q helao\core\servers` (Windows `cmd`),
naming the cause as untracked `__pycache__` that git leaves behind. The PR description gives
both forms, and says every checkout that pulls B7b needs the command once, the main checkout
included. At runtime the
stale directory is harmless, because no code imports it.

**D-B7b.10 — What a stale reference is.** A docstring, comment or runtime message is fixed if it
describes current behaviour through a deleted symbol, as in "legacy BaseAPI keeps hosting", "the
graft binds it at startup" or "orch compositions stay on legacy WS". Provenance is left alone, as
in "ported verbatim from `orch_dispatch.py:128`" or "moved from `orch_api.py` by B7a". Commit 3
classifies every hit this grep finds in those 63 files, and fixes only those that describe current
behaviour:

```
git ls-files '*.py' | grep -v -E '/tests/' \
  | xargs grep -n -E 'makeOrchApp|graft_hexagon_loop|HexagonGraft|active_graft|graft_active_write_path|sync_graft|graft_native_sync|\bOrchAPI\b|\bBaseAPI\b|StatusBroadcaster|\bbase_api\b|\borch_api\b|globstat|\bgraft\b|assert_source_parity|native_fixtures'
```

Known to change:

- `hexconfig.py:31–33`, which says the orchestrator shim calls `makeOrchApp`;
- `adapters/legacy/health.py:11` and its message at 35;
- `adapters/legacy/status.py:68–71`, and the three `UnwiredPortError` messages at 145–163;
- `ingestion.py:1–6, 23–25`;
- `dispatch_loop.py`'s module docstring;
- `factory.py`'s module docstring and `_is_native_host` docstring;
- the orchestrator shims' docstrings: `deploy/hexagon/.../async_orch2.py:4–14` and
  `deploy/hte/.../async_orch2.py:10`;
- `harness/ws_frames.py:1–43`;
- `adapters/native/data_file.py:67`, which points at `native_fixtures`/`assert_source_parity`,
  whose pins die.

The `\bgraft\b` hits in the 24 `helao/deploy/hexagon/servers/action/*` shim docstrings ("native
write/WS graft via makeActionApp") and in `graft.py` are classified and left. Those files are
B7c's to delete, and B7b edits a shim only where step 2 forces it. The sleep comment at
`action_host.py:759–762` belongs to commit 5 (§6.4), not this list.

None of those messages appears in a golden trace or an asserted string; both were checked by
grep. The pyright suppressions in `orch.py`, and the `type: ignore[attr-defined]` lines in
`makeOrchApp`, leave with the code they annotate.

## 4. Commit sequence

Every command runs with the working directory at the worktree root, and with
`conda run -n helao env PYTHONPATH=<worktree> python <scriptfile>` (§2.9). Each commit's check
also records `python -c "import helao; print(helao.__file__)"` and requires the path to fall
under the worktree. `black` runs on the changed files immediately before each `git add`.

### 4.0 Task 0 — baselines (no commit)

On `e60d800a`, before any edit:

1. Run the private-repo copy procedure (§7, gate 5) and record the failing set: **F0p**.
2. Remove the copies. Run `run_tests.py` in the bare worktree and record its failing set: **F0**.
   B7a measured 3 files in its worktree; the plan re-measures rather than assuming it.
3. Record the five checklist IDs (§2.7).
4. Record pyright errors on every file the plan will touch.
5. Record `run_unit_tests.py` PASS.
6. Record the ports 8000–8003 and 8010 as free.

### 4.1 Commit 1 — port, while the engine is still present

1. **Legacy references.** With the engine present and the golden masters unmodified, except for
   scenario 5's edit (Q2), capture:
   - all 9 dispatch scenarios, into scratch `legacy_dispatch/`;
   - all 13 action scenarios, into scratch `legacy_action/`.

   Take each capture twice and require the two runs to be byte-identical.
2. **Freeze the member snapshots** (D-B7b.7), from the extraction functions as they stand.
3. **Re-point the dispatch golden master.** In `_make_orch`, replace `Orch` with
   `OrchHost.__new__(OrchHost)` and keep the same attribute block. Then call
   `_init_orch_collaborators()`, set
   `hexagon_wiring = PortWiring(logging=LegacyLoggingAdapter(), health=LegacyHealthAdapter())`,
   and call `_build_reducer()`. Patches stay on the modules that own the seams, as B7a
   established. Add `assert type(orch) is OrchHost`.
4. **Re-point the action golden master.** Replace `_make_base`/`Active` with an `ActionHost`
   host fixture (either real construction with `helao_cfg` and a `PortWiring`, as
   `test_action_session_port.py:192–248` does, or `ActionHost.__new__` with the same attribute
   block) and `ActionSession(host, activeparams)`. Make the scenario calls go through
   `session.action_finalizer.substitute()`/`.finish_all()` where `ActionSession` lacks the
   method. `_PatchedBaseGlobals` patches `move_dir`, `async_private_dispatcher` and `set_time`
   on every native module that binds them at import. On `e60d800a` those binders are:
   `adapters/native/finalizer.py:44–47` (`async_private_dispatcher`, `set_time`, `move_dir`);
   `adapters/native/artifact_store.py:32` (`move_dir`; unpatched, it moves real files if the
   fixture wires `NativeArtifactStoreAdapter`); `app/action_host.py:53`
   (`async_private_dispatcher`); and `premodels.set_time`. The plan re-greps before writing the
   patch list. `async_copy` is dropped: `base.py:69` imports it but never uses it, and it appears in
   no trace.
5. **Red-check, action golden master**, following B7a §5. With the native port in place, patch
   the legacy module globals only (`helao.core.servers.base`, `active_finalizer`). `--check`
   against `legacy_action/` **must fail**, because the recorded `move_dir` events vanish. Then
   patch the native modules: it must pass.
6. **Compare native against legacy.**
   - Dispatch: S1–S6, S8 and S9 must be byte-identical to `legacy_dispatch/`. S7 may differ
     only by the single `intend_none` intent-call block (Q1), confirmed with a line diff of
     exactly that block.
   - Action: all 13 must match `legacy_action/` under the golden master's own comparison rules
     (exact trace bytes, exact normalized text, `.hlo` header plus value multisets).
   - Any other delta stops the commit and is escalated. It is not re-baselined.
7. **Freeze the native captures** as the tracked references (Q3), after re-grepping them for
   `/home/`, `/mnt/`, `/tmp/`, the host name and the user name (0 hits required). Point `BASELINE_S0_DIR` and
   `BASELINE_S0A_DIR` at them, and keep the refuse-to-overwrite guards. The golden master
   docstrings state what was compared, and against what.
8. **Port the shared-logic tests and unit tests** per §5, including the rebuilt `native_fixtures`
   and the commit-1 ports listed in §5.4. Edit `run_unit_tests.py` in this same commit, removing
   the entries of any `unit_test_*` it deletes.
9. **Compare the orchestrator surface against legacy, including bodies and enums.** Land the
   `harness/openapi_capture` change of §8 in this commit. While the engine is present, normalize
   `OrchAPI("ORCH", "ORCH", "b7b", 3.0).openapi()` (built in-process, as the ratchet's legacy
   probe does) and `test_orch_host_surface._host().openapi()`. Require equal `params` and `body`
   on every route both serve (74 today). Keep the normalized legacy capture in scratch as
   evidence. Any delta stops the commit and is escalated, as in step 6. Two divergences outside
   the normalize are recorded here, not fixed:
   - `/prepend_sequences` answers `{"sequence_uuids": [...]}` on legacy (`orch_api.py:383–384`)
     and a bare list on `OrchHost` (`orch_host.py:473`). No in-tree caller reads the response
     (`orch_backend.py:324–327` and both operators discard it), and it has been live on every
     hexagon station since B3b (Q10);
   - the three routes `OrchHost` adds (§2.7).

**Check:**

- both golden masters pass `--check` and their default double-capture mode;
- the red-check is recorded as failed first;
- `run_unit_tests.py` passes;
- every touched pytest file passes;
- the full `run_tests.py` failing set is a subset of F0 (gate 4's command), so a collateral break
  in an untouched file cannot ride forward;
- the AST sweep shows the only test files still importing the engine are the ones commit 2 or
  commit 3 deletes or trims (§5.3, §5.4);
- step 9's legacy/native surface comparison holds;
- a subprocess check of each golden master module shows no `helao.core.servers` in
  `sys.modules` after a native run.

### 4.2 Commit 2 — cut the runtime paths

- `factory.py`, per D-B7b.2 and D-B7b.3; `dispatch_loop.py`, per D-B7b.3.
- Delete `active_graft.py` and `sync_graft.py`.
- Reduce the hexagon `sim_db_server` shim.
- `harness/ws_frames.py` and `orch_host.orch_ws_publishers`, per D-B7b.4.
- Test changes, per §5.3:
  - delete `test_active_graft.py` and `test_sync_graft.py`;
  - trim `test_db_shim.py`, `test_dispatch_loop.py` and `test_factory.py`;
  - port `test_vis_hexagon_producer_parity::test_no_hexagon_orch_ws_producer_exists`;
  - delete `test_orch_host_surface::test_a_native_orch_host_is_not_grafted`.
- **Empty the ratchet allowlist in this commit, not in commit 4.** The brief put it in step 4,
  but `test_every_allowlisted_file_still_imports_the_engine` is shrink-only, so it fails the
  moment these three files stop importing the engine. Delete `ALLOWLIST` and that test; the
  offender assertion becomes `offenders() == {}`.
- Extend the ratchet's native runtime probe. It already builds hosts directly; add a third case
  that builds `makeActionApp("SIM", "helao.deploy.test.servers.action.ws_simulator")` under the
  goldenhex config, and assert `engine_modules == []`. That makes B7a Amendment 2's second item
  falsifiable.

**Check:**

- ratchet green: static 0, and a native probe that includes the factory case;
- one scratch script (not committed), run while the engine is still present, compares the new
  `encode_orch_api` output against the old `StatusBroadcaster._ws_relay` output for all three
  channels, and requires byte equality;
- every file in §5.3 passes;
- `live_group`'s six users pass;
- the full `run_tests.py` failing set is a subset of F0, less deleted files.

### 4.3 Commit 3 — delete

- `rm -rf helao/core/servers`.
- Move `CLAUDE.md` and fix root `CLAUDE.md` (D-B7b.8).
- Delete the engine self-tests, the parity pins and the ratchet's `legacy` probe (§5.4).
- Adjust the six source-path readers (§5.5).
- `pyproject.toml` (Q6).
- Stale references (D-B7b.10).

**Check:**

- the full `run_tests.py`, compared against F0 (gate 4);
- `run_unit_tests.py` passes;
- both golden masters pass `--check`, byte-identical to their commit-1 references;
- an AST sweep over **all** tracked `.py`, tests included, finds zero *executable* references to
  the engine:
  - no `Import`/`ImportFrom` of `helao.core.servers` or any submodule;
  - no call to `importlib.import_module`, `__import__` or `importlib.util.find_spec` whose
    first argument is a string constant starting with `helao.core.servers`, except the ratchet's
    own commit-4 probe;
  - no `mock.patch`/`monkeypatch.setattr`/`monkeypatch.delattr` whose target string starts with
    `helao.core.servers`.

  Other string constants that name the module are allowed only in the files of §2.2's last
  three rows: the ban lists, the ratchet, and the enumerated provenance docstrings. The check
  prints any file outside that list and fails on it. A raw grep for the module name is not the
  check, because provenance docstrings are kept by design (D-B7b.10);
- `git ls-files helao/core/servers` is empty.

### 4.4 Commit 4 — ratchet and checklists

- The package-is-gone assertion (D-B7b.9).
- Re-freeze and rename the orchestrator checklist (§8). The `openapi_capture` change already
  landed in commit 1 (step 9), where its new fields were compared against legacy.
- The drift record: the five IDs are listed in the PR and in §2.7; nothing re-freezes the hte
  checklists to hide them.

**Check:**

- the ratchet passes;
- `test_orch_host_surface` passes against the re-frozen file;
- two mutation probes fail the parameter gate and are reverted. The first renames one member of
  an enum that a route parameter references. The second renames one property of one route's
  request body;
- the full `run_tests.py` failing set is a subset of F0, less deleted files.

### 4.5 Commit 5 — backlog

The dispositions in §6. **Check:** `test_ws_consumer_parity`, `unit_test_orch_status_sync`,
`test_orch_stops_polling_on_shutdown` and both member-coverage tests pass; the dispatch golden
master passes `--check`, because the globstat feed writes to a queue with no subscriber and no
trace records it; and the full sweep is re-run as the final gate (§7).

## 5. Test dispositions

### 5.1 `helao/core/tests/` shared-logic tests

| file | engine use | disposition |
|---|---|---|
| `test_orch_queue_paging.py` | l.18 `_histories_payload`/`_history_page_payload` from `orch_api`; l.61 `test_the_ten_row_default_is_gone_from_every_layer` checks `Orch` signatures | **port**: import from `helao.hexagon.app.orch_payloads`; the signature check covers `(OrchHost, RunQueues)` |
| `test_run_state_wiring.py` | l.301 manual-action eviction via legacy `Active` and `unit_test_active_finalizer._make_active_for_journal` | **port** onto `NativeActionFinalizer` over the rebuilt native fixture; the helper moves to `native_fixtures` |
| `test_standalone_operator.py` | l.46 `Orch.__new__` in `_make_orch`; l.109 and l.522 `orch_api` payload helpers; l.549 `_prepend_sequences` | **port** `_make_orch` to `OrchHost.__new__` and the two payload tests to `orch_payloads`; **delete** `test_prepend_sequences_helper`, because `_prepend_sequences` exists only in `orch_api` and `OrchHost`'s route takes a typed `list[Sequence]` body, whose coercion is FastAPI's |
| `test_analysis_recovery.py` | l.959 baseline route set from `BaseAPI(...)` | **port**: the baseline is a bare `ActionHost` with the same arguments; the assertion `{"/list_queued_tasks", "/list_running_tasks"}` is unchanged |
| `test_upload_set.py` | l.6 `_relative_file_name` via `active_data_file` | **port**: import from `helao.helpers.file_utils` (its real home, line 33) |

### 5.2 The 14 `unit_test_*` engine importers

The "native twin" column names the pytest file that already covers the subject. The plan writes
a check-to-test mapping for each file before it deletes any check (D-B7b.6).

| file | subject | native twin | disposition |
|---|---|---|---|
| `active_data_file` | `DataFileWriter` | `test_native_data_file` | **move-and-delete**: move `explicit_filename_aux`, `resolve_output_path_save_data_false` and `track_file`; `collaborator_wired` is engine wiring |
| `active_data_stream` | `DataStreamer` | `test_native_data_stream` | **move-and-delete**: move `realtime_forwarding`, `add_new_listen_uuid_mutates_active`, `assemble_and_build_package` and `enqueue_nowait_counts` |
| `active_executor` | legacy `ExecutorRunner` | `test_executor_runner` | **move-and-delete**: move `oneoff_executor` and `start_executor_to_completion`; `delegators_forward` is engine delegation |
| `active_finalizer` | `ActionFinalizer` | `test_native_finalizer` | **move-and-delete**: move `split_keep_active_then_finish_all` and `empty_global_params_skips_dispatch`; `_make_active_for_journal` moves to `native_fixtures` |
| `base_api` | `base_api` helpers | `test_action_context`, `test_action_route` | **delete**: the helpers are engine-only; the native replacements (D-B1.1) have their own 24 tests |
| `base_endpoints` | `EndpointManager`, `ActionQueueDispatcher` | `test_endpoint_manager` | **move-and-delete**: move `dyn_endpoints_init`, `init_endpoint_status_dyn_endpoints_called`, `process_endpoint_queue_success` and `process_unified_queue` onto `app/endpoint_manager.py`'s same-named classes |
| `base_live_buffer` | `LiveBuffer` | none | **port in place** onto `ActionHost`'s `_stamp_lbuf_dict`, `put_lbuf`, `put_lbuf_nowait`, `get_lbuf` and `get_realtime*` |
| `base_meta_writer` | `MetaFileWriter` | `test_native_meta_writer` | **move-and-delete**: move `write_act_save_act_false` |
| `base_status` | `StatusBroadcaster` | none that is dedicated | **port in place** onto `ActionHost`: `send_statuspackage`, `send_nbstatuspackage`, attach/detach, `replace_status`. Drop `ws_relay`, which is the engine relay; native WS encoding is covered by `test_ws_frames` and D-B7b.4 |
| `config_seam` | `Base(helao_cfg=)` | none | **port in place** onto `ActionHost(helao_cfg=...)` |
| `dispatcher` | only l.43 imports the engine: `ACTION_CTX` and `wrap_action_endpoint` in the RPC fast-path check | — | **port in place**: that one check goes through native `action_route.wrap_action_endpoint(fn, host)`, with the handler taking `ctx`; the rest of the file is unchanged |
| `estop_sync` | `Base.estop_actives` | — | **port in place** onto `ActionHost.estop_actives` |
| `orch_lifecycle` | native `RunLifecycle`, legacy `Orch` fixture | — | **port in place**: the fixture becomes `OrchHost.__new__` |
| `orch_queues` | native `RunQueues`, legacy `Orch` fixture | — | **port in place**: the fixture becomes `OrchHost.__new__`; `base_collaborator_seam` is re-pointed at `OrchHost._init_orch_collaborators` |

After this table, `run_unit_tests.py` imports 30 functions: the 37 of §2.3, minus the 7 deleted
files (`active_data_file`, `active_data_stream`, `active_executor`, `active_finalizer`,
`base_api`, `base_endpoints` and `base_meta_writer`). The plan re-counts after editing.

### 5.3 Graft and factory tests (commit 2)

| file | disposition |
|---|---|
| `test_active_graft.py` (179 lines) | **delete**: the whole subject is the graft |
| `test_sync_graft.py` (168 lines) | **move-and-delete**. `test_native_driver_exposes_db_endpoint_surface` (l.108–138) is the only test that pins the DB endpoint surface: `enqueue_yml`, `list_pending`, `finish_pending` (with its `actions_first` kwarg), `reset_sync`, `running_tasks`, `task_queue`, and the deliberate *absence* of `progress`. Move it to `helao/hexagon/tests/test_native_sync_parity.py`, parametrized over two drivers: a `NativeSyncer` built against that file's existing host fixture, and the test deployment's `sim_db_server` `ActionHost` `app.driver` (`SimHelaoSyncer`) after its startup event. Once the graft is gone, the latter is what the DB endpoints actually resolve. The other five tests cover graft rebinding only: engine-internal, deleted |
| `test_db_shim.py` | **trim** to one test: the shim's `makeApp` returns an `ActionHost` built by `makeActionApp`, and registers no startup hook of its own |
| `test_dispatch_loop.py` | Keep the four `HexRuntime`/`HexDispatchLoop` tests (l.76, 88, 112, 257). **Delete** `test_graft_rebinds_control_methods` (l.143) and `test_graft_rebinds_status_ingestion_endpoints` (l.191): instance rebinding is engine-internal, and `test_orch_host_surface::test_the_host_owns_the_reducer_rather_than_being_grafted` covers the native control methods. **Move-and-delete** the two health tests. `test_graft_swaps_heartbeat_task_when_health_wired` (l.210) becomes a new `test_orch_host_surface::test_the_host_binds_its_health_adapter_and_starts_no_legacy_heartbeat`: after `_host()`, `host.hexagon_wiring.health._orch is host` (`orch_host.py:1414–1416`), `host._hex_health` is built, and `host.heartbeat_monitor is None`. `test_graft_without_health_skips_monitor` (l.249) is covered by `test_adapter_health::test_orch_required_includes_health_and_wiring_has_slot` (l.16): an orch composition without health cannot be built, so there is no native case to test |
| `test_factory.py` | **delete** `test_make_orch_app_constructs_with_graft_hooks` (l.92). **Port** `test_orchestrator_exposes_loaded_modules` (l.114) to the orchestrator shim's `makeApp`, keeping the count-is-1 and payload assertions and dropping the `BaseAPI.__init__` source check. **Invert** `test_launcher_shims_delegate` l.304 to `not hasattr(factory, "makeOrchApp")`. **Rewrite** l.375 and l.391 for the renamed hook (D-B7b.2), removing l.391's `active_graft` monkeypatch. **Add** a test that `makeActionApp` raises `TypeError` for a module whose `makeApp` returns a plain FastAPI app |
| `test_vis_hexagon_producer_parity.py` | **port** `test_no_hexagon_orch_ws_producer_exists` (l.529) to the orchestrator shim's `makeApp`. The source twin becomes "`bind_publish_bridge` not in `orch_host` source". The other tests are unchanged |
| `test_orch_host_surface.py` | **delete** `test_a_native_orch_host_is_not_grafted` (l.269) |

### 5.4 Deleted in commit 3 (and two commit-1 ports that sit beside them)

- **The engine self-tests:** `test_action_session_port::test_the_legacy_active_satisfies_the_port`
  (l.80); `test_estop_finish_race`'s `legacy` parametrization, whose `FLAVOURS` shrinks to the
  `hexagon` entry; and the ratchet's `legacy` fixture and
  `test_every_legacy_route_is_built_by_action_api_route`.
- **The parity pins:** the four `test_source_parity_with_legacy` tests, in `test_native_data_file`,
  `_data_stream`, `_finalizer` and `_meta_writer`, and `native_fixtures.assert_source_parity`.
- **The legacy halves of two tests:** `test_native_artifact_store` and `test_native_data_sink`,
  which each have a `test_port_conformance_and_no_base_inheritance` that asserts against `Base`.
  The conformance half stays.
- **`test_estop_fixes`:** the five `seq_unpacker` imports are **ported** in commit 1 to
  `helao.hexagon.app.orch_unpack`.
- **`test_native_data_sink::test_q2_members_delegate_to_legacy_active`:** **ported** in commit 1
  onto `ActionSession`.

### 5.5 Source-path readers (commit 3)

| reader | treatment |
|---|---|
| `test_action_host_member_coverage.py:34` | reads `base_member_surface.json` (D-B7b.7) |
| `test_orch_host_member_coverage.py:44, CONSUMERS` | drops `helao/core/servers` and `orch_api`; the contract is `orch_member_contract.json` ∪ live extraction; the floor stays `> 130` |
| `test_ws_consumer_parity.py:37–38` | the paths become `helao/hexagon/app/orch_host.py` and `action_host.py`; `extract_routes` finds `/ws_status`, `/ws_data` and `/ws_live` in both (measured) |
| `test_orch_host_surface.py:53–100` | **delete** `_legacy_orch_api_routes` and `test_every_orch_api_route_exists_on_the_host`: the frozen openapi checklist, which is exact after §8, is the gate that function's own docstring defers to |
| `test_bokeh_theme.py:555`, `test_palette.py:1785` | delete the engine-glob line; neither test has a floor that depended on it |

## 6. Backlog dispositions

### 6.1 `/ws_globstat`: deleted (commit 5)

Delete everything listed in §2.8: the `OrchHost` attributes, methods, feed, task and cancel;
`StatusIngester.ws_globstat` and `globstat_broadcast_task`; the commented-out put at line 294;
`NotifyPort.publish_globstat`. Fix the docstrings in `orch_status_sync.py` (lines 5–9, 16,
30–31, 38–39, 46), `orch_dispatch.py:41–42, 51–53` and `ingestion.py:23–25`.

In the tests:

- the dispatch golden master's fixture loses lines 242/250–251;
- `test_orch_stops_polling_on_shutdown._Probe` loses `globstat_broadcaster`;
- `unit_test_orch_status_sync` loses its two globstat checks and keeps `clear_nonblocking`;
- `globstat_q` is retired from `orch_member_contract.json`.

`test_ws_globstat_is_dead` flips to `test_ws_globstat_channel_is_gone`. It keeps its current
route assertions, now on the native files (§5.5), and adds five more:

- `OrchHost` has no `ws_globstat`;
- `OrchHost` has no `globstat_broadcast_task`;
- `StatusIngester` has no `ws_globstat`;
- `StatusIngester` has no `globstat_broadcast_task`;
- a constructed `OrchHost` has no `globstat_q`.

Nothing on the wire changes, because no route ever served it.

### 6.2 `params.limit_vis`: kept (Q4)

It is live (§2.8). Deleting the three reads would change what one private deployment's
visualizer mounts. B7b changes no code here. This spec records that the "dead key" finding of
2026-08-05 was overtaken on 2026-09-22.

### 6.3 `set_error`: gone with the engine (commit 3)

No native or deployment caller exists (§2.4). The action golden master's scenario 5 loses the
step in commit 1 (Q2).

### 6.4 Deferred: the 0.3 s blocking sleep

`action_host.py:763` stays. Replacing it with `asyncio.sleep` reorders `log_status_task`
against every other coroutine on an action server, which is exactly the class of change
program §5 keeps out of a deletion, and it needs its own station verification. Commit 5
rewrites the comment at 759–762 to say that it is deferred past B7 and why. It no longer says
"until parity is signed off", because parity sign-off is what B7b is. The comment change is the
one log-invisible edit this item gets.

### 6.5 Deferred: the finish-drain window

`finalizer.py` 318–343 and 346–371 stay as they are, with at most 5 × 0.1 s each. Shortening or
restructuring them changes when the last data package lands relative to the final `write_act`.
The action golden master's scenario 13 (`13_finish_late_data_drain`) pins that ordering, and
the station data diff is the program's comparison of record. It needs its own change, with a
scenario-13 re-baseline that is argued for rather than inherited.

## 7. Gates

These are in addition to each commit's check, and all run on the branch head.

1. **Ratchet**, `pytest helao/hexagon/tests/test_engine_import_ratchet.py`:
   - static offenders `{}`, with no allowlist;
   - the native probe, factory case included, finds no engine module;
   - `find_spec("helao.core.servers") is None`.
2. **Golden masters**: both pass `--check` against their tracked native references, and both
   pass their default double-capture mode. Commit 1's record shows legacy-versus-native
   identity, with only the S7 block allowed, and the action red-check failing first.
3. **Checklists**: the failing checklist IDs equal the five in §2.7 exactly.
   `test_orch_host_surface` and `test_action_host_surface` pass.
4. **Full `run_tests.py` in the bare worktree.** The failing set must equal F0, less any file B7b
   deletes. Any new or renamed test file must pass. `ENV` is not a failure.
5. **Private deployments against the branch.** Copy each private deployment into the worktree at
   its committed `HEAD`, because symlinks and `PYTHONPATH` both give false results:
   ```
   MAIN=<main-checkout>; WT=<worktree>
   for src in "$MAIN"/helao/deploy/*/; do
     d=$(basename "$src")
     case "$d" in hte|test|hexagon|__pycache__) continue ;; esac
     [ -d "$src/.git" ] || continue
     rm -rf "$WT/helao/deploy/$d" && mkdir "$WT/helao/deploy/$d"
     git -C "$src" archive HEAD | tar -x -C "$WT/helao/deploy/$d"
   done
   ```
   Then run `run_tests.py` in the worktree. Its discovery is structural, so it finds them. The
   failing set must equal F0p (Task 0), measured with the identical procedure on `e60d800a`,
   less deleted files. Afterwards, `rm -rf` the copies and require `git -C "$WT" status --short`
   to be empty. The copies are gitignored by `helao/deploy/*` (`.gitignore:23`), but the check
   is still required.

   Why a copy:
   - A symlink makes `Path(__file__).resolve()` land in the main checkout. Private tests resolve
     repo-relative paths through `parents[N]`/`REPO_ROOT` at 30 sites, so they would read the
     main checkout's `harness/` and `helao/`.
   - Running the private tests in place, with `PYTHONPATH` set to the worktree, puts pytest's
     rootdir at the main checkout first on `sys.path`, so `helao` resolves to main again.
   - `git archive` copies exactly the committed tree, with no `.git`, `.omc` or `__pycache__`.
     The code hash of every file resolves to `""` in the copy, and it did so identically in F0p.
6. **`run_unit_tests.py` passes; `pyright` shows no new errors** on any changed file compared
   with Task 0. The run uses `pyright --outputjson` on the explicit list of changed files, with
   `PYTHONPATH` set to the worktree. `summary.filesAnalyzed` must equal the number of changed
   `.py` files that still exist, and must be greater than 0. Under worktree paths pyright has
   reported a clean run while analyzing no files at all, so an error count alone proves nothing.
   Task 0 records the same fields.
7. **Launch smoke**, from the worktree root with `PYTHONPATH` set to the worktree:
   - `python launch.py goldenhex`, which has `run_unit_tests: true`, so `run_unit_tests.py` runs
     first and must pass;
   - every server binds, and `supervise_early_exits` reports no child exit within 90 s;
   - one `goldenhex` sequence reaches `RUNS_FINISHED` or `RUNS_SYNCED`;
   - SIGTERM tears the group down (B7a Amendment 1), and `STATES/pids_goldenhex_.pck` is
     cleared.

   This covers `launch.py`, `run_unit_tests` and the orchestrator shim. It does not cover
   `makeActionApp` (§2.3). Gate 4's `live_group` tests cover that on Linux, and gate 8 covers it
   on hardware (Q7).
8. **One hexagon station launch before merge**: `eche10_hex`, user-run, on a Windows station.
   - Before launching, run `rmdir /s /q helao\core\servers` in `cmd` from the repo root
     (D-B7b.9), then confirm
     `python -c "import importlib.util as u; print(u.find_spec('helao.core.servers'))"` prints
     `None`.
   - Every server binds, which is the proof that no launched server imports the engine: the
     directory no longer exists, so any engine import is a startup `ModuleNotFoundError`.
   - One short sequence reaches `RUNS_FINISHED` or `RUNS_SYNCED`.
   - `CTRL-x` tears the group down cleanly.

   `/loaded_modules` is **not** used as evidence. It lists only files it can hash, so once the
   directory is removed it could never name an engine file, whatever was imported.
9. **`black`** on every changed file immediately before each `git add`.

## 8. The orchestrator surface checklist

- **`harness/openapi_capture`** (lands in commit 1, step 9, so its new fields are compared
  against legacy before the engine goes). `normalize(doc)` passes `doc["components"]["schemas"]` to
  `_params(op, schemas)` and to a new `_body(op, schemas)`.
  - A parameter whose schema, or one of whose `anyOf` variants, is a `$ref` gains
    `"ref": <component name>`. It also takes the component's `type`, where the capture records
    `null` today, and gains `"enum": sorted(component["enum"])` when the component has one.
  - A route with a `requestBody` gains `"body"`:
    `{"required": bool, "properties": sorted [[name, type or ref name (with its enum, if any)]], "required_props": sorted [...]}`.
    This is resolved one level into the body component. The body component's own name is
    **not** recorded: FastAPI derives it from the handler's function name, and the module
    docstring's rule against generated titles covers it for the same reason.
  - Routes without a body keep their current shape, so `test_action_host_surface` and
    `test_ws_simulator_port` are unaffected; they compare only paths and tags.
- **The re-freeze and rename.** `orch_openapi_legacy.json` is re-frozen from a live `OrchHost`,
  built by `test_orch_host_surface._host()`, as `helao/hexagon/tests/checklists/orch_openapi.json`
  (77 routes) and the old file is deleted. The capture writes it once, and its
  refuse-to-overwrite behaviour matches `harness/freeze.py`'s. It is only a native snapshot in
  form: commit 1 step 9 has already shown its `params` and `body` equal legacy's on the 74
  shared routes, and it records the one known divergence outside the normalize
  (`/prepend_sequences`' response shape, Q10).
- **The tests become exact.** They are renamed `..._matches_the_frozen_orchestrator_surface`.
  The route test asserts both "missing" and "extra" are `[]`. The parameter test compares
  `params` and `body`.
- **`checklists/hte/_baseapi_system_surface.json` is unchanged** (Q8).

## 9. Risks

- **A gate that ran the main checkout's code.** The env's baked-in `PYTHONPATH` (§2.9) makes
  this the easiest false pass available. It is guarded by the `helao.__file__` assertion in
  every check and gate (§4 preamble).
- **The golden masters' `hlo_version` depends on the current directory.** Always run them from
  the worktree root, which is a git checkout. A run from elsewhere reads as 13 DELTAs, not as a
  pass.
- **A port that intercepts nothing.** The action golden master's patches move to native
  modules; the red-check (§4.1 step 5) makes a missed module a failure. The dispatch golden
  master's seams already live on their owner modules (B7a), and `assert type(orch) is OrchHost`
  pins the fixture.
- **A stale `__pycache__` resurrecting the package.** D-B7b.9 makes it a loud test failure, and
  the PR and gate 8 carry the `rm -rf`.
- **Hot reload on stations.** A pulled B7b changes `factory.py`, so the watcher restarts every
  idle `deployment: hexagon` action server, and orchestrators restart with `--restore`. That is
  expected behaviour. Gate 8 is where it is first seen live.
- **A private module that still returns a legacy app.** None does, measured by source across
  all 34 `fast: graft` server entries (§2.3 gives the counting unit). If one appears, D-B7b.2 fails it at build, naming the module,
  instead of in the startup event.
- **Private-copy residue.** The copies are gitignored. Gate 5 requires `git status --short` to
  be empty afterwards, and the copies are removed before any commit. They must never be present
  while a `git add` runs.
- **`ws_frames` import weight for the private test.** The `orch_host` import stays inside
  `encode_orch_api`, so importing `harness.ws_frames` does not load the orchestrator.
- **The member snapshots freezing the wrong thing.** They are captured in commit 1 from the
  existing extraction functions, whose floors (`> 60`, `> 130`) and known-name assertions still
  run against the snapshot.

## 10. What B7b does not do

- **No B7c work:** no `_hex` → bare-prefix renames, no deleting `helao/deploy/hexagon/` shims,
  no `adapters/legacy` → `adapters/shared`, no renaming `legacy_module` or `fast: graft`. The
  hexagon `sim_db_server` shim is reduced, not deleted, and only because its import of
  `sync_graft` dies.
- **No change to** any private deployment repository, any deployment server module, or any
  deployment checklist. The private deployment whose remote is disabled needs nothing.
- **No change to `params.limit_vis`** (§6.2), the 0.3 s sleep (§6.4) or the finish-drain window
  (§6.5).
- **No edits to** provenance docstrings, the frozen sweeper calibration fixtures, or the driver
  diagram.
- **Does not rename** `checklists/hte/_baseapi_system_surface.json`.
- **Does not remove** the main checkout's `.omc/artifacts/p5` and `p6` baselines. They are
  untracked, and the golden masters stop reading them.
- **Does not change** `NotifyPort`'s other members, or any port besides the one globstat
  member.

## 11. Done

B7b is done when:

- `helao/core/servers/` is gone from the tree and cannot be imported. Its traps doc lives at
  `helao/hexagon/app/CLAUDE.md`, and root `CLAUDE.md` describes the native hosts.
- Nothing imports the engine, tests included. The ratchet proves that with no allowlist, and
  with a probe that builds a real `makeActionApp` composition.
- Both golden masters run natively against tracked references. Each reference was accepted
  only after a byte comparison with a legacy capture of the same commit, and the one named S7
  delta was recorded.
- The graft machinery, `makeOrchApp` and `sync_graft` are gone. `makeActionApp` accepts native
  hosts only, and `fast: graft` configs still launch.
- `harness/ws_frames` encodes the `orch_api` family through `OrchHost`'s own publishers, with
  its public names intact.
- The orchestrator surface checklist is native, exact, and sees enum members and request
  bodies. The five known drift IDs are recorded, not hidden.
- Each backlog item is dispositioned as §6 records.
- Gates 1–9 hold. Gate 8 (the eche10 station launch) is recorded in the PR before merge.

## 12. Open questions

Each question has a recommended default, which the plan adopts unless the user overrides it.
Q1, Q2 and Q4 depart from the approved design, and Q10 records a pre-existing divergence it
did not mention. They are listed here rather than quietly
changed.

- **Q1: the dispatch golden master's S7 cannot be byte-identical.** The approved design requires
  native traces byte-identical to the legacy capture. Measured (§2.4), 8 of 9 scenarios are
  identical. S7 lacks one `intend_none` intent-call block, because `OrchHost.estop_loop` goes
  through the reducer (DD-5 item 6). That is a documented, deliberate difference, not a
  regression. **Default:** accept exactly that one block as the only allowed delta, and adopt
  the native capture as S7's reference. The alternative, making the spy record something the
  native host never calls, would make the golden master describe a system that no longer
  exists.
- **Q2: action scenario 5 calls `set_error`, which dies.** **Default:** remove the `set_error`
  step, with its `post_set_error` trace event, from `_scenario_error_estop` *before* the legacy
  capture in §4.1 step 1, so the legacy and native runs execute the same script. The
  alternative, adding `set_error` to `ActionSession`, would resurrect the quirk (it appends to
  `experiment_status`) that the backlog exists to retire.
- **Q3: where the golden-master references live.** Today they sit in the gitignored `.omc/`, in
  one checkout only, so `--check` cannot run in any worktree. After B7b, legacy can never
  regenerate them. **Default:** track them in `helao/core/tests/golden/dispatch/` (9 `.jsonl`)
  and `helao/core/tests/golden/action/` (13 `.trace.jsonl` and 13 `.runs.norm`). They are small
  and synthetic; a grep found no local path, user name or host name.
- **Q4: `params.limit_vis` is live, not dead.** The approved design says to delete the three
  reads. **Default:** keep them (§6.2). Deleting them changes one private station's visualizer,
  and needs that deployment's config and a UI check. That is a UI change, not an engine
  deletion.
- **Q5: `NotifyPort.publish_globstat`.** It has no implementer and no caller. **Default:**
  delete it with the rest of the globstat channel (§6.1). `test_ports_import` checks only that
  the `NotifyPort` name is exported, which stays true.
- **Q6: `pyproject.toml`'s `force-exclude`.** It excludes four native collaborators because they
  were pinned byte-for-byte to engine files. The pins die in commit 3. **Default:** remove the
  `core/servers/(...)` alternation *and* the four `hexagon/adapters/native/(meta_writer|data_file|data_stream|finalizer)`
  entries; run `black` on those four files in commit 3. Black's default safe mode already
  refuses any reformat whose AST differs from the input, and that is the proof the change is
  layout only. The action golden master `--check` is re-run as well, but as a
  behaviour check, not as that proof. Keep
  `sync_driver` on both sides, because its pins, against a non-engine file, stay. Rewrite the
  comment at lines 28–57 to cover `sync_driver` only.
- **Q7: the launch smoke does not reach the changed factory path.** **Default:** keep the
  approved `goldenhex` smoke, and name `live_group`'s six users (gate 4) and eche10 (gate 8) as
  the coverage of `makeActionApp`. Launching `test_hex`, which does route `SIM` through
  `makeActionApp`, is not recommended: its base config's `root: C:/INST_hlo` creates a relative
  `C:` directory on Linux, the same kind of untracked `C:\INST_hlo...` directory the main
  checkout already holds.
- **Q8: `checklists/hte/_baseapi_system_surface.json`** is also a legacy capture, but nothing
  about it depends on the engine. **Default:** leave the name and content alone. Renaming it is
  cosmetic, and it is read by a native-only test.
- **Q9: renaming the `makeActionApp` startup hook** (D-B7b.2). **Default:** rename it to
  `_hexagon_ws_bridge_startup`. The only readers of the name are tests, which were checked in
  the parent and in every private deployment.
- **Q10: `/prepend_sequences` answers differently on the native orchestrator.** Legacy returns
  `{"sequence_uuids": [...]}` (`orch_api.py:383–384`); `OrchHost` returns the bare list
  (`orch_host.py:473`). It has been live since B3b. No in-tree caller reads the response: the
  operator backend (`orch_backend.py:324–327`) and both operator UIs discard it. No private
  deployment calls the route. **Default:** record it here and in the PR; B7b does not change it.
  Restoring the legacy shape is a wire change in its own right, and there is no reader for whom
  it would fix anything.
