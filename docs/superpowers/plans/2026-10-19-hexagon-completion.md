# Hexagon completion: dead-code sweep, sync cutover, restore through the port, two deferred behaviours

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development` or
> `superpowers:executing-plans` to carry this out task by task. Steps use checkbox (`- [ ]`) syntax.

**Branch:** `feat/hexagon-completion`, off `unstable` @ `ba910c4c`, in the parent repo.

**Inputs:**
- `helao/hexagon/app/CLAUDE.md`
- `helao/helpers/CLAUDE.md`
- `helao/core/drivers/data/CLAUDE.md`
- the master spec, `docs/superpowers/specs/2026-07-16-framework-hexagonal-rewrite-design.md` (§4.3.3, §4.3.4, §4.3.12,
  §4.5, §5.4)
- `docs/superpowers/plans/2026-07-18-P2c-native-sync.md`
- the B7b spec, §6.4–6.5
- the legacy-separation program spec

**Revision 2 (2026-10-19):** applies the plan review's 22 required fixes and the optional items, and the user's decision
on two drain bounds (D12).

**Goal.** This plan finishes the hexagon migration in four parts, done in this order:

- **C3:** delete code that already has a live replacement.
- **C1:** production runs `NativeSyncer` through the wired `SyncPort`, and the core twin is deleted.
- **C2:** queue export and `--restore` go through `StatePersistencePort` / `QueuePckStore`, with the same bytes and
  behaviour.
- **C4:** the two deferred behaviours change: the 0.3 s blocking sleep and the finish-drain window. Their gates run on
  Linux, and the user verifies them on a station before merge.

The user's decisions C1–C4 are final. This plan does not revisit them. The decisions it adds are listed in §2, each with
its evidence.

---

## 0. Global constraints (every task, every delegation prompt carries these)

- **No outward-facing actions.** Implementers never run `git add`, `commit`, `push` or `stash`.
  - Commits are made by the main session at the marked **COMMIT BOUNDARY** lines, after the gate passes.
  - Implementers write only inside the repo's working tree and `/tmp/claude-1000/hexplan/`.
- **Every git call is `git -C <repo>`.**
  - The parent repo is `/mnt/STORAGE/repos/helao/helao-async`.
  - The private deployments are separate nested git repos under `helao/deploy/`.
  - A subagent's cwd resets between calls, so use absolute paths.
- **Never touch the production network mounts (`/mnt/wd4` and its siblings).** Nothing here needs them.
  - Some tests would fall back to a production root. For example, `sources_root()` defaults to `/mnt/wd4/SOURCES` when
    `HELAO_SOURCES_ROOT` is unset.
  - Run them with `HELAO_SOURCES_ROOT=/tmp/claude-1000/hexplan/sources` exported. The environment block below sets it.
- **Privacy.** The parent repo is public.
  - Do not write a private deployment's name in any tracked parent file. That covers code, comments, tests and commit
    messages. Write "a private deployment", or Deployment-A/B/C.
  - The one nested-repo edit (Task 2a) is in **Deployment-C**: the nested repo that contains
    `scripts/ecms_ms/convert_backlog.py`. Locate it with:
    ```
    bash -c 'for d in /mnt/STORAGE/repos/helao/helao-async/helao/deploy/*/scripts/ecms_ms; do echo "${d%/scripts/ecms_ms}"; done'
    ```
- **Escalate, don't choose.** If something comes up that this plan does not settle, stop and report it. This matters most
  for anything visible on the wire or on disk: route sets, response bodies, file names, file contents, or the order of
  writes.
- **Environment.**
  ```
  REPO=/mnt/STORAGE/repos/helao/helao-async
  PY=$HELAO_ENV/bin/python        # the helao env; do NOT use `conda run ... <<EOF` (drops stdin)
  SCR=/tmp/claude-1000/hexplan                          # scratch; mkdir -p "$SCR"
  export HELAO_SOURCES_ROOT=$SCR/sources
  ```
  - Run commands from `$REPO` with `PYTHONPATH=$REPO`.
  - Run one pytest file per process: `PYTHONPATH=$REPO $PY -m pytest -q -p no:cacheprovider <file>`.
  - Or use `$PY run_tests.py --filter <substr>`. The filter is a plain substring of the path. **`--filter sync` matches
    every file**, because `helao-async` is in every path. Use a path-anchored filter such as `--filter /test_sync`, or
    run a full sweep.
  - **The tool shell is zsh.** There, `grep` is a snapshot shell function and `ls` is aliased to `exa`. Run every grep
    sweep and every `ls`/glob loop inside `bash -c '...'`. Use `grep -rn` through Bash, not the Grep tool: the Grep tool
    honours `.gitignore` and does not see the nested repos.
  - Launch groups with `./helao.sh <prefix>`, which activates the env. Run it under a pty:
    `tail -f /dev/null | script -qfec "./helao.sh goldenhex --no-hot-reload" $SCR/<name>.log &`.
  - SIGTERM to the `launch.py` process is a graceful CTRL-x.
  - Only the main session runs launches. A subagent's background launch gets reaped when it goes idle.
- **Formatting.** The main session runs `black` on the changed files immediately before each commit. The black
  `force-exclude` keeps the native sync re-body unformatted for this whole branch (decision D8).
- **Pyright.** `$REPO/pyrightconfig.json` is authoritative.
  - For each changed `.py` file, run `$HELAO_ENV/bin/pyright --outputjson <files>`.
  - Report `summary.filesAnalyzed` next to `summary.errorCount`. `filesAnalyzed` must be greater than 0: a run that
    analyzed 0 files is not a pass.
  - Neither count may get worse than its Task 0 value.
- **Every new test in this plan has a mutation check.**
  - Mutate the code and watch the test go red. Restore it and watch it go green. Put both outcomes in the task report.
  - Never mutate by executing pre-fix code that defaults to a production path. Nothing in this plan does that.

---

## 1. Measured facts this plan rests on (2026-10-19, branch head `ba910c4c`)

**M1. The native sync body is byte-identical to the core twin.**
- `test_native_sync_pins.py`: 10 passed.
- `test_native_sync_parity.py`: 3 skipped.

**M2. The GM-1 golden set is absent locally, so `test_native_sync_parity.py` cannot run here.**
- `~/helao_goldens` does not exist, and `HELAO_GOLDENS` is unset.

**M3. Production constructs the core syncer at 4 parent sites plus 1 nested script.**
- `orch_host.py:29` and `:1464`.
- `hte/servers/action/sync_server.py:20`.
- `test/servers/action/sim_db_server.py:36`.
- `core/drivers/data/analysis_driver.py:88`, as `AnalysisSyncer(HelaoSyncer)`.
- Deployment-C `scripts/ecms_ms/convert_backlog.py:104`, plus its test at `:18` and `:782`.

**M4. The orchestrator uses its syncer for exactly one thing: `to_s3`, twice.**
- `orch_dispatch.py:1289` uploads the experiment meta; `:1449` uploads the sequence meta.
- Both call sites wrap the upload in `try/except Exception` and log the error.
- Nothing else in production reads `orch.syncer`.

**M5. The SYNC server's routes read 11 members from the driver.**
- `enqueue_yml`, `release_quarantine`, `list_pending`, `finish_pending(actions_first=)`, `reset_sync`, `write_off`,
  `quarantined`, `running_tasks`, `task_queue.qsize()`, `has_pending_work`, and `progress`.
- `progress` does not exist on the driver. `/current_progress` therefore raises `AttributeError`, and
  `test_db_endpoint_surface.py` pins that on purpose.

**M6. Nothing reads `.base` on a syncer instance, and `AnalysisSyncer` uses one inherited method.**
- `AnalysisSyncer.__init__` assigns `self.base` at `analysis_driver.py:517` and never calls `super().__init__`.
- An AST scan finds no `.base` read, in the class or anywhere else.
- The only inherited method it uses is `to_s3`, at `:1303`.

**M7. 15 orchestrator configs have no SYNC/DB server, so `use_sync` is False for them.**
- 3 in `hte`, 8 in `test`, 4 private.
- If `sync` were in `ORCH_REQUIRED`, these orchestrators would abort at startup.

**M8. The orchestrator's member contract freezes `syncer` and `use_sync`.**
- `checklists/orch_member_contract.json` holds 137 members. It "shrinks only when a member is retired on purpose".
- `test_orch_host_member_coverage.py:202` asserts `len(contract) > 130`. That leaves a margin of 6, and retiring
  `syncer` uses 1 of it.

**M9. Production dispatches through the reducer, but the dispatch golden master drives the dead `DispatchRunner.run`.**
- `OrchHost.dispatch_loop_task` calls `dispatch_runner.run()`.
- Its only caller is `_drain` at `test_orch_dispatch_golden_master.py:853`.

**M10. Driving the golden master through the reducer gives the same final state in every scenario.**
- Scratch harness `$SCR/gm_delta.py`: `StartRequested` plus `_hex_loop._run_started_phase()`, with a health stub that
  reports every endpoint available.
- All 9 `final` blocks are identical.
- Every trace delta is a **removal** of one of three spy events, 13 blocks in total:
  - `intent_call:intend_none`
  - `phase_enter:loop_task_dispatch_action` / `phase_exit:loop_task_dispatch_action`
  - `stop_call`
- Blocks removed per scenario: s1 1, s2 0, s3 1, s4 0, s5 3, s6 2, s7 0, s8 1, s9 5.
- The semantic checks in `_run_and_check` return `[]`.
- With the stock `LegacyHealthAdapter`, the reducer stops at once with "endpoints are unavailable": its HEAD probes reach
  no real servers.

**M10b. GM-5 cannot be captured on the current build.**
- `run_gm5` (`harness/capture.py:449-457`) needs `RUNS_SYNCED/**/*.zip`.
- The single-RUNS-tree syncer no longer zips or moves records, so GM-5 has nothing to reset.
- This plan does not change `capture.py`.

**M11. Lines 128–489 of `orch_dispatch.py` are an AST-identical copy of `domain/dispatch_policy.py`.**
- An AST-dump comparison finds 0 names that differ.

**M12. `_exec_pre_dispatch_intent` is live, so it is dropped from the C3 list.**
- `_launch_action` calls it (`orch_dispatch.py:765`), and `_launch_action` is kept.

**M13. `QueuePersister` writes the pickle itself. `QueuePckStore` is constructed, but nothing calls it.**
- `factory.py:35` builds the store, and `ORCH_REQUIRED` requires it.
- The store's `import_queues` archives **before** the schema check. It has no `_unreadable_` quarantine and no `pck_path`.
  Both differ from the live path in `orch_persist.py:315-444`.

**M14. `QueuePersister` returns `os.path.join(root, "STATES", name)`, but `QueuePckStore` returns a `Path`.**
- On Windows, `str(Path("C:/INST_hlo/STATES/queues.pck"))` rewrites `/` as `\`.
- `/export_queues` and `/import_queues` return that string, so the difference is visible on the wire.

**M15. `time.sleep(0.3)` blocks the event loop once per status, per client.**
- `action_host.py:790`, in `log_status_task`.

**M16. The finish drain is two loops, each capped at 5 × 0.1 s.**
- They run from the line `LOGGER.info("finish active: sending finish data_stream_status package")` through the
  `await asyncio.sleep(0.1)` that closes the `write_iter` loop: about `finalizer.py:326-382`.
- The next line to keep is `# self.action_list[-1] is the very first action`, about :384.
- **Edit by these text anchors, not by line numbers.**
- Scenario 13 cannot see housekeeping packets: its trace recorder drops data-less packets
  (`test_active_golden_master.py:_data_record`).
- The late row is in `13_finish_late_data_drain.runs.norm`.
- `data_stream_status` is not on `ActionModel`. It is not in `-act.yml`, and not in status payloads, which use
  `get_act()`.

**M17. The remaining C3 deletions have no callers outside their own tests.**
- Verified by a grep of the whole tree, nested repos included.
- The symbols:
  - `start_wait`, `get_sequence_codehash`, `Mplatewarp`
  - `RunQueues.replace_action`, `supplement_error_action`, `append_action`
  - `ArtifactStorePort.write_data_line`, `write_one_shot`, `close_streams`
  - `StatusPort.send_status`
  - `ServerMonitor.active_action_monitor`
  - `StatusIngester.update_status`, `update_nonblocking`
  - `domain/{status_fold,queue_policy,assembly}.py`
  - `LegacyArtifactStoreAdapter`
  - `adapters/vis/{ws_consumer,param_store,spec_parser,browser_source}.py`
  - `ports/{param_store,spec_parser,browser_source,operator_backend}.py`
  - `StatusStreamPort`, `ChannelNormalizerPort`, and `CHANNELS` / `CONSUMER_FACES` in `ports/status.py:53,57`
  - `PlateInfoPort`, `LibraryPort`, `NotifyPort`, `UuidFactoryPort`
- There is no `adapters/vis/operator_backend.py`. That mirror never existed.

**M18. `S3FacePort` in `ports/sync.py` has no implementation either.**
- Its only reference is `test_ports_import.py:84`.

**M19. Every E-STOP path marks its actions estopped before calling finish.**
- `/estop` reaches finish through `estop_actives` (`action_host.py:862-870`). For each session, in series, it calls
  `session.set_estop(action=a)` on every action that is not yet estopped, then `await session.finish()`.
- The other E-STOP sites also call `set_estop` before finishing: `action_host.py:1009`, and a `hte` PAL driver
  (`pal_driver.py:1691`).
- `ActionSession.set_estop` (`action_session.py:269-273`) appends `HloStatus.estopped` to the action's status.
- The orchestrator bounds each per-server E-STOP RPC at `ESTOP_SEND_TIMEOUT_S = 10.0` (`orch_estop.py:50`). A server
  with several active sessions finishes them one after another inside that one RPC.

---

## 2. Decisions this plan makes (with the evidence)

**D1. The `SyncPort` surface has exactly the members real callers use** (M4, M5), plus one member for the two routes that
read task state.
- The members: `enqueue_yml`, `release_quarantine`, `list_pending`,
  `finish_pending(omit_manual_exps=True, actions_first=False)`, `reset_sync` (synchronous), `write_off`, `quarantined`,
  `running_tasks()`, `n_queue()`, `has_pending_work`, `to_s3`.
- `sync_yml` is dropped: nothing calls it through the port.
- `reset_sync` and `list_pending` stay synchronous, so their `def` routes keep running in FastAPI's threadpool. An `async`
  wrapper would put a blocking unzip on the event loop.
- `/current_progress` keeps reading `app.driver.progress`, which preserves the pinned `AttributeError`.
- `S3FacePort` is deleted (M18). See open question Q2.

**D2. `sync` does not join `ORCH_REQUIRED` or `ACTION_REQUIRED`** (M7).
- The port is bound **at startup**, because `SyncDriver.__init__` calls `asyncio.create_task`.
- The orchestrator binds it when `use_sync` is set.
- The SYNC server and the sim DB server bind it **when `app.driver is not None`**. Driver construction can fail, and
  `test_sync_server_recovery.py:139-153` pins that the server still comes up when it does.
- `build_wiring` leaves `sync=None`, as it does today.
- No `require("sync")` call is added after the bind, because it could never fail.

**D2b. Routes read `app.hexagon_wiring.sync` at call time and never capture it inside `makeApp`.**
- The bind happens at startup, after `makeApp` has returned, so a value captured in `makeApp` would always be `None`.
- A route reached while the port is unbound keeps today's no-driver behaviour: an attribute error on `None`.
- `/hotreload_busy` keeps the semantics of `action_host.py:1104-1110`: the hook answers "not busy" when no port is bound.

**D3. The orchestrator retires `syncer` from its member contract.**
- `orch.hexagon_wiring.sync` replaces it. `use_sync` stays.
- Test fixtures that set `orch.syncer` set `orch.hexagon_wiring.sync` instead.

**D4. `AnalysisSyncer` subclasses `NativeSyncer` and sets `self.host` instead of `self.base`** (M6).
- It still never calls `super().__init__`, so nothing changes at runtime: `to_s3` is the same verbatim body.

**D5. `SimHelaoSyncer` is renamed `SimNativeSyncer(NativeSyncer)`.** Its recorder injection is unchanged.

**D6. The dispatch golden master moves to the reducer, and its references are re-frozen in a commit of their own.**
- That commit carries the measured delta from M10. A checker with hard-coded expectations verifies it (Task 1a).
- Only after that commit is `DispatchRunner.run`, `_loop` and the rest deleted.

**D7. The C1 parity gate substitutes for the absent GM-1 goldens (M2).**
- Byte-identity (M1) is proved at Task 0, while both twins still exist.
- The live gate is **GM-1 only**.
  - Capture GM-1 with `harness.capture` on `goldenhex`, once before the change (Task 0) and once after.
  - Compare the two captures with `harness.parity`, the golden gate's own comparator.
  - GM-5 is dropped (M10b).
- The reset_sync / finish_pending leg is gated offline instead. These tests must keep their F0 verdicts:
  - `helao/core/tests/test_sync_quarantine.py`
  - `helao/core/tests/test_prc_colocation.py`
  - `helao/core/tests/test_set_plate_id_resync.py`
  - `helao/hexagon/tests/test_native_sync_adapter.py`
  - `helao/deploy/hte/tests/test_sync_server_recovery.py`
- Task 0 captures GM-1 twice, to show the comparison is quiet: 0 diffs between the two baseline runs.
- A one-file mutation of the candidate proves the comparator can fail.
- GM-1 parity checks the tree, the metadata and the S3 records. It does **not** prove `.hlo` row-for-row identity: its
  manifest masks the WsSim `.hlo` value columns and tolerates ±3 rows.
- `test_native_sync_parity.py` keeps only its native-versus-committed-golden test. That test stays skipped here and runs
  wherever the goldens exist.

**D8. Black.**
- The core path comes out of the `force-exclude` regex.
- The native `sync_driver.py` stays excluded for this branch.
  - Reason: the cutover's safety argument is "these are the exact bytes the stations ran". Reformatting 3000 lines in the
    same branch would destroy the cheap `diff` audit that proves it.
- Follow-up (Q4): after the user's station verification and the merge, a formatting-only commit drops the exclusion.

**D9. `helao/core/drivers/data/CLAUDE.md` moves to `helao/hexagon/adapters/native/CLAUDE.md`, with `git mv`.**
- Its rules cover the syncer and the native writers, and those now live only in the native directory.
- The pointers in the root `CLAUDE.md` are updated to match.

**D10. The C2 port surface follows what `QueuePersister` actually does.**
- `export_queues(payload, timestamp_pck=False) -> str` writes the file and prunes the timestamped series.
- `load_queues(pck_path=None) -> tuple[str, Optional[dict]]` returns `None` for the payload when the file is missing. It
  also returns `None` when the file is unreadable, after first moving the file to `_unreadable_<ts>`.
- `archive_consumed(path) -> Optional[str]` renames the file to `_imported_<ts>`.
- These stay in `QueuePersister`: building the payload, the schema check, the "queues not empty" refusal, applying the
  payload, the #224 loop-flag reset, and the re-run under a fresh uuid.
- All paths are `os.path` strings (M14). The old `import_queues()` port member is removed.

**D11. C4a keeps the 0.3 s pacing but stops blocking:** `await asyncio.sleep(0.3)`.

**D12. C4b turns the drain into a marker round-trip, with two bounds** (the user's decision).
- **The call path.**
  - The finalizer calls `ActionSession.drain_data(timeout_s)`, which delegates to `NativeDataStreamer.drain`.
  - `drain_data` is declared in `ActionSessionPort`. `test_action_session_port.py:56-70` requires every `active.<x>` the
    finalizer reads to be a port member.
- **The marker round-trip.**
  - The drain puts one data-less `finished` package, the **marker**, on `data_q` for the current action.
  - The data logger sets an event when it consumes that exact object.
  - Each subscriber queue is FIFO, so by then every package queued before the marker has been written.
- **Re-sending the marker.**
  - If the event has not fired within 0.1 s, the drain puts the same marker again.
  - It re-puts only if the logger has consumed nothing since the previous put. The logger keeps a consumed-message
    counter; see Task 4b. This covers a logger that has not subscribed yet, without piling markers behind a busy one.
- **The logger-alive check.** The drain re-checks it on every iteration, not just once. If the logger task is gone, there
  is nothing to wait for and the drain returns. The logger can be gone because:
  - it never started;
  - `save_data=False`;
  - it exited through the `except` at `data_stream.py:282`;
  - `data_q.close()` ran in `_shutdown_once`.
- **Two bounds, each a single module constant in `adapters/native/finalizer.py`, referenced from one place:**
  - `FINISH_DRAIN_TIMEOUT_S = 10.0` for a normal finish;
  - `ESTOP_FINISH_DRAIN_TIMEOUT_S = 1.0` for a finish on an E-STOP path.
- **How the E-STOP path selects the short bound: the finalizer reads the session's own estop state.**
  - The test is `any(HloStatus.estopped in a.action_status for a in self.active.action_list)`.
  - This is the smaller diff. Threading an explicit argument would change `ActionSession.finish`,
    `NativeActionFinalizer.finish` / `finish_all`, the `ActionSessionPort.finish` signature, and `estop_actives`.
  - It also covers every E-STOP path, because each one calls `set_estop` before finish (M19): `/estop`, the
    `action_host.py:1009` path, and the PAL driver's own E-STOP.
  - Worst case on `/estop`: `n_sessions × 1 s` of drain wait. That stays inside the orchestrator's 10 s
    `ESTOP_SEND_TIMEOUT_S` for up to about 8 hung loggers on one server. Today it is up to 1.0 s per session.
- **Timeout and late data.**
  - A timeout logs a WARNING with the queued and written counts.
  - Data that arrives after the marker is still dropped, exactly as §5.4 says.
- **Overlapping drains (final review).** Marker and event are per call, registered in `NativeDataStreamer._drain_waiters`
  by `id(marker)`; the logger sets only the matching event and each call removes only its own entry. Two finishes of one
  session can overlap (`/estop` finishing it while the stopped executor finishes it too), and shared state made one of
  them raise.
- **Close-out always runs (final review).** `finalizer` wraps `drain_data` in `try/except Exception` with an `error` log,
  so the file close, logger cancel, `write_act` and the last status run whatever the drain did.
- **Non-streaming sessions publish nothing (final review).** `drain` returns at once, without a marker, when no action
  in the session has `data_stream_status == active` and nothing is queued unwritten. That keeps the old behaviour: a
  non-streaming action puts no data-less `finished` packet on `data_q`, so `/ws_data` subscribers see none.
- **The one remaining wire-visible change.** A streaming action whose logger is stuck re-sends the marker every 0.1 s
  while it consumes nothing, up to the bound (10 s, or 1 s on an E-STOP path). Each marker is a data-less `finished`
  package on `data_q`/`/ws_data`. Before, the retry loops sent at most about 10 such packets. A healthy logger consumes
  the first marker and nothing is re-sent.
- **Effect.**
  - A slow logger no longer loses anything queued before finish, up to 10 s, or 1 s on E-STOP.
  - With a fast logger, the drain takes ≤0.1 s instead of up to 1.0 s.

---

## 3. File map

**Task 0**
- Scratch only: `$SCR/F0/*`.
- Also creates `helao/hexagon/tests/smoke/restore_smoke.py`, which stays untracked until Task 3.

**Task 1a**
- `helao/core/tests/test_orch_dispatch_golden_master.py`
- `helao/core/tests/golden/dispatch/*.jsonl` (re-frozen)

**Task 1b**
- `helao/hexagon/app/orch_dispatch.py`
- `helao/hexagon/app/orch_host.py`
- `helao/hexagon/domain/orchestration.py` (docstring)
- `helao/hexagon/app/CLAUDE.md`
- `helao/core/tests/unit_test_orch_dispatch_policy.py` (import retarget only)
- `helao/hexagon/tests/test_estop_fixes.py`

**Task 1c**
- `helao/hexagon/app/{orch_status_sync,orch_monitor,orch_host,orch_queues,orch_lifecycle,orch_unpack,ingestion}.py`
- `helao/hexagon/domain/{status_fold,queue_policy,assembly,motion_transform}.py`
- `helao/hexagon/ports/auxiliary.py` (docstring at :56)
- `helao/deploy/test/configs/goldenhexconc.yml` (comment at :3)
- Tests: `unit_test_orch_{monitor,queues,status_sync}.py`, `test_{status_fold,queue_policy,assembly}.py`

**Task 1d**
- Ports: `helao/hexagon/ports/{artifact_store,status,auxiliary,param_store,spec_parser,browser_source,operator_backend,catalog,calibration_store}.py`
- Adapters: `helao/hexagon/adapters/{native/artifact_store,shared/artifact_store,shared/status,fakes/__init__,vis/__init__,vis/ws_consumer,vis/param_store,vis/spec_parser,vis/browser_source}.py`
- Tests: `test_{adapters_data,native_artifact_store,status_consumer_faces,param_store_port,spec_parser_port,browser_source_port,operator_backend_port,ports_import,fakes}.py`
- Possibly `mirror_pin.py`

**Task 2a (Deployment-C)**
- `scripts/ecms_ms/convert_backlog.py`
- `scripts/ecms_ms/tests/test_convert_backlog.py`
- Two config comments

**Task 2b**
- `helao/hexagon/ports/sync.py`
- `helao/hexagon/adapters/native/sync_adapter.py`
- **Delete** `helao/hexagon/adapters/shared/sync.py`
- `helao/hexagon/tests/test_adapters_misc.py` (the LegacySyncAdapter tests)
- `helao/hexagon/tests/test_native_sync_adapter.py`
- `helao/hexagon/app/{orch_host,orch_dispatch}.py`
- `helao/deploy/hte/servers/action/sync_server.py`
- `helao/deploy/test/servers/action/sim_db_server.py`
- `helao/core/drivers/data/analysis_driver.py`
- `helao/hexagon/tests/checklists/orch_member_contract.json`
- Fixtures: `test_orch_dispatch_golden_master.py`, `test_estop_clear_race.py`, `test_restore_loop_flags.py`
- `harness/tests/test_sim_db_server.py`
- `test_db_endpoint_surface.py`
- New: `helao/hexagon/tests/test_sync_port_wiring.py`

**Task 2c**
- Delete `helao/core/drivers/data/sync_driver.py` and `helao/hexagon/tests/test_native_sync_pins.py`.
- Retarget about 26 `helao/core/tests/*` files and 4 `helao/hexagon/tests/*` files.
- `sync_fixtures.py`
- `pyproject.toml`
- Docs (Task 2c, Step 3)

**Task 3**
- `helao/hexagon/ports/auxiliary.py`
- `helao/hexagon/adapters/shared/state_persistence.py`
- `helao/hexagon/adapters/fakes/__init__.py`
- `helao/hexagon/app/orch_persist.py`
- Fixtures
- New: `helao/hexagon/tests/test_queue_persistence_port.py`
- `helao/hexagon/tests/smoke/restore_smoke.py`

**Task 4a**
- `helao/hexagon/app/action_host.py`
- New: `helao/hexagon/tests/test_status_pacing_nonblocking.py`

**Task 4b**
- `helao/hexagon/adapters/native/{finalizer,data_stream}.py`
- `helao/hexagon/app/action_session.py` (`drain_data`)
- `helao/hexagon/ports/action_session.py` (declare `drain_data`)
- `helao/core/tests/test_active_golden_master.py` (docstring only)
- New: `helao/hexagon/tests/test_finish_drain_marker.py`
- The gate also runs `helao/hexagon/tests/test_action_session_port.py`.

---

## Task 0 — Baselines (no code change, no commit)

**Files:** scratch `$SCR/F0/` only, plus the new untracked smoke driver (Step 7).

- [ ] **Step 1: Record the state.**
  ```
  git -C $REPO status --short --branch      # expect "## feat/hexagon-completion"; only untracked doc files
  git -C $REPO rev-parse HEAD               # record as BASE
  bash -c 'for d in '"$REPO"'/helao/deploy/*/; do [ -d "$d/.git" ] && echo "$(basename $d) $(git -C $d rev-parse --short HEAD)"; done' > $SCR/F0/nested_heads.txt
  ```
  `nested_heads.txt` is scratch only. Never copy its contents into a tracked file: it holds private deployment names.
- [ ] **Step 2: Run the full sweep F0.** Run it in the background; it takes tens of minutes.
  ```
  cd $REPO && $PY run_tests.py > $SCR/F0/run_tests.log 2>&1
  bash -c "grep -E '^  (PASS|FAIL|ENV|TIMEOUT|NOTESTS|NOTATEST) ' $SCR/F0/run_tests.log | awk '{print \$2, \$1}' | sort > $SCR/F0/verdicts.txt"
  bash -c "awk '\$2==\"FAIL\"||\$2==\"TIMEOUT\"{print \$1}' $SCR/F0/verdicts.txt > $SCR/F0/failset.txt"
  ```
  Also run `cd $REPO && PYTHONPATH=$REPO $PY run_unit_tests.py > $SCR/F0/unit.log 2>&1; echo rc=$?`.
- [ ] **Step 3: Golden masters.** Both must PASS:
  ```
  cd $REPO && PYTHONPATH=$REPO $PY helao/core/tests/test_orch_dispatch_golden_master.py --check  > $SCR/F0/gm_dispatch.txt 2>&1
  cd $REPO && PYTHONPATH=$REPO $PY helao/core/tests/test_active_golden_master.py --check         > $SCR/F0/gm_action.txt 2>&1
  ```
- [ ] **Step 4: Byte-identity proof (M1).**
  - Run `PYTHONPATH=$REPO $PY -m pytest -q -p no:cacheprovider helao/hexagon/tests/test_native_sync_pins.py`.
  - Expect 10 passed. Save the output to `$SCR/F0/pins.txt`.
  - Task 2c cites this output as the parity-by-construction evidence when it deletes the core twin.
- [ ] **Step 5: Pyright baseline.**
  - Run pyright once over every `.py` file named in the §3 file map that exists today.
  - Save the output to `$SCR/F0/pyright.json`, and record `filesAnalyzed` and `errorCount`.
- [ ] **Step 6: Live sync baseline (D7, GM-1 only).** Run this twice, with run tags `b1` and `b2`:
  ```
  rm -rf /tmp/helao-hexsmoke
  tail -f /dev/null | script -qfec "./helao.sh goldenhex --no-hot-reload" $SCR/F0/launch_GM-1_<tag>.log &
  # wait for ORCH: curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' --data '{}' http://127.0.0.1:8001/get_orch_state  -> 200
  cd $REPO && PYTHONPATH=$REPO $PY -m harness.capture --scenario GM-1 --root /tmp/helao-hexsmoke \
      --out $SCR/F0/GM-1/<tag> --config-prefix goldenhex
  pkill -TERM -f 'launch.py goldenhex'      # graceful; wait until STATES/pids_goldenhex_*.pck is gone
  ```
  - The noise floor must be zero: `$PY -m harness.parity --golden $SCR/F0/GM-1/b1 --candidate $SCR/F0/GM-1/b2` must
    report 0 diffs.
  - If it does not, **stop and escalate**. The comparator is noisy, and D7 needs a different substitute.
  - Do not use `parity_run.sh`. Its port probe is `conda run ... python - <<PY`, which drops stdin and passes without
    checking anything.
  - Also save `$SCR/F0/offline_sync.txt`: the F0 verdict lines of the five offline tests listed in D7.
- [ ] **Step 7: Restore smoke baseline (the C2 gate).**
  - Create `helao/hexagon/tests/smoke/restore_smoke.py`. It is a smoke driver, not a test, so `run_tests.py` reports it
    as NOTESTS.
  - It imports `orch_post`, `get_orch_state`, `orch_parked`, `wait_until` and `build_ws_sequence` from
    `helao.hexagon.tests.smoke.conc_items`.
  - It has three phases, selected with `--phase`.
  - **`--phase export --root R`:**
    - Append `build_ws_sequence(n_exps=3, wait_time=2.0, data_duration=4.0)` and POST `start`.
    - Wait, for at most 120 s, until both of these hold:
      - `get_orch_state()["active_experiment"]` is truthy;
      - the second experiment has started, meaning there are 2 experiment directories under the sequence. Poll with
        `glob` on `R/RUNS/**/*-exp.yml`; the layout is `helao/core/models/run_dir.py`.
    - Print `READY-TO-KILL` and exit 0.
  - **`--phase verify-export --root R --out F`:**
    - Assert that `R/STATES/queues.pck` exists, then `pickle.load` it.
    - Write a JSON summary to F with these fields:
      - `schema`, `len(seq)`, `len(exp)`, `len(act)`;
      - the active experiment's `experiment_name`;
      - whether `globalstatusmodel.active_dict` is non-empty;
      - the sorted names of the actions that were in flight.
  - **`--phase restore --root R --out F`:**
    - Assert that `queues.pck` is gone and exactly one `queues_imported_*.pck` exists.
    - Assert that `get_orch_state()["loop_state"]` ends with `stopped`.
    - POST `start`, then `wait_until(orch_parked, 300)`.
    - Write a JSON summary to F. Include only fields that are stable from run to run:
      - the number of `-exp.yml` files under the sequence;
      - each experiment's final `experiment_status`;
      - per action name, the multiset of `action_status` lists and `action_retry` values;
      - the number of actions whose status list is `["skipped", "finished"]`, i.e. the retired in-flight uuid;
      - the file-name *patterns* in `STATES`, with timestamps replaced by `<TS>`.
  - **Baseline run** (main session):
    ```
    rm -rf /tmp/helao-hexsmoke
    tail -f /dev/null | script -qfec "./helao.sh goldenhex --no-hot-reload" $SCR/F0/rA.log &
    #   wait for ORCH 200 (as Step 6)
    PYTHONPATH=$REPO $PY helao/hexagon/tests/smoke/restore_smoke.py --phase export --root /tmp/helao-hexsmoke
    pkill -TERM -f 'launch.py goldenhex'      # wait for pid file to clear
    PYTHONPATH=$REPO $PY helao/hexagon/tests/smoke/restore_smoke.py --phase verify-export --root /tmp/helao-hexsmoke --out $SCR/F0/restore_export_<tag>.json
    tail -f /dev/null | script -qfec "./helao.sh goldenhex --restore --no-hot-reload" $SCR/F0/rB.log &
    #   wait for ORCH 200
    PYTHONPATH=$REPO $PY helao/hexagon/tests/smoke/restore_smoke.py --phase restore --root /tmp/helao-hexsmoke --out $SCR/F0/restore_final_<tag>.json
    pkill -TERM -f 'launch.py goldenhex'
    ```
  - Run the baseline twice, with tags `b1` and `b2`. The two summaries must be equal.
  - If they are not, tighten the summary to fields that do not vary, and report what was dropped and why.

**Gate 0:**
- Steps 2–7 have completed.
- `failset.txt` is recorded.
- Both golden masters PASS.
- The pins test reports 10 passed.
- The GM-1 noise floor is 0.
- The restore summaries for `b1` and `b2` are equal.

---

## Task 1 — C3: delete superseded code

**The grep recipe.** Every sub-task first re-runs its grep over **the whole tree, nested repos included**.
- Use word-bounded, qualified patterns. Some examples:
  - `\.(replace_action|append_action|supplement_error_action)\(`
  - `status_ingester\.update_`
  - `server_monitor\.active_action_monitor`
  - `-w start_wait`
  - `-w Mplatewarp`
- The command:
  ```
  bash -c 'grep -rnwE "<pattern>" /mnt/STORAGE/repos/helao/helao-async \
      --include="*.py" --include="*.yml" --include="*.json" --include="*.md" \
    | grep -v "/\.ua/\|/\.omc/\|/\.claude/\|/\.git/\|/\.superpowers/\|__pycache__\|/docs/\|docs/config-schema\.md"'
  ```
  Drop `-w` for patterns that already carry `\.` or `\(` anchors.
- If a hit appears outside the files this plan names, that symbol is **live**. Do not delete it: stop and report the hit.

### Task 1a — Move the dispatch golden master to the reducer, and re-freeze its references (D6)

- [ ] **Step 1: Edit `helao/core/tests/test_orch_dispatch_golden_master.py`.**
  - **Add an `_OkHealth` class**, the same shape as `helao/hexagon/tests/test_restore_loop_flags.py:35-41`:
    - `endpoints_available` returns all True;
    - `ping_action_servers` returns `{}`;
    - `status_summary` returns `{}`.
  - **In `_make_orch`** (about line 283), wire `health=_OkHealth()` in place of `LegacyHealthAdapter()`.
  - **Replace `_drain`** (about line 851) with:
    ```python
    async def _drain(orch: OrchHost) -> None:
        """Run one reducer started-phase inline, which is what production runs."""
        await orch._hex_runtime.handle(StartRequested())
        await orch._hex_loop._run_started_phase()
        await _run_all_ticks(5)
    ```
    Import `StartRequested` from `helao.hexagon.domain.orchestration`.
  - **Rewrite the docstrings that still name `dispatch_loop_task`:**
    - the module docstring's "What is REAL" list (lines 11–13, 32, 36): name the reducer runtime instead, that is
      `HexRuntime.handle`, `HexDispatchLoop._run_started_phase` and `OrchCommandRunner`, and explain the health stub;
    - the comments at about lines 636, 1143 and 1230;
    - line 40 (`HelaoSyncer.to_s3`): Task 2b rewrites this line, so leave it for now.
- [ ] **Step 2: Capture the new traces.**
  - Run `cd $REPO && PYTHONPATH=$REPO $PY helao/core/tests/test_orch_dispatch_golden_master.py`.
  - Default mode writes `.omc/artifacts/p5/baseline/*.jsonl`.
  - It must print "ALL 9 SCENARIO CHECKS PASSED" and "DETERMINISM CHECK PASSED".
- [ ] **Step 3: Check the delta mechanically, against hard-coded expectations.** Write `$SCR/gm_delta_check.py`:
  ```python
  import json, subprocess, sys
  from collections import Counter
  from pathlib import Path
  REPO = Path("/mnt/STORAGE/repos/helao/helao-async")
  NEW = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / ".omc/artifacts/p5/baseline"
  PE, PX = "phase_enter:loop_task_dispatch_action", "phase_exit:loop_task_dispatch_action"
  IN, ST = "intent_call:intend_none", "stop_call:"
  EXPECTED = {  # measured 2026-10-19 (plan M10); 13 blocks in total
      "1_": {IN: 1}, "2_": {}, "3_": {IN: 1}, "4_": {},
      "5_": {PE: 1, PX: 1, IN: 1}, "6_": {PE: 1, PX: 1}, "7_": {},
      "8_": {IN: 1}, "9_": {PE: 2, PX: 2, ST: 1},
  }
  def key(b):
      return f'{b.get("event")}:{b.get("method") or b.get("phase") or ""}'
  def removed_blocks(old, new):
      i, removed = 0, []
      for b in old:
          if i < len(new) and new[i] == b:
              i += 1
          else:
              removed.append(key(b))
      if i != len(new):
          return None, f"new has a block not in old: {json.dumps(new[i])[:200]}"
      return removed, None
  ok, total = True, 0
  files = sorted(NEW.glob("*.jsonl"))
  for p in files:
      old = json.loads(subprocess.check_output(
          ["git", "-C", str(REPO), "show", f"HEAD:helao/core/tests/golden/dispatch/{p.name}"]))
      new = json.loads(p.read_text())
      removed, err = removed_blocks(old["trace"], new["trace"])
      exp = EXPECTED[p.name[:2]]
      got = Counter(removed) if removed is not None else None
      good = (err is None and got == Counter(exp)
              and old["final"] == new["final"] and old["scenario"] == new["scenario"])
      total += sum(got.values()) if got else 0
      ok &= good
      print(p.name, "OK" if good else "FAIL", dict(got) if got is not None else err, "expected", exp)
  ok &= len(files) == 9 and total == 13
  print("TOTAL removed", total, "-> PASS" if ok else "-> FAIL")
  sys.exit(0 if ok else 1)
  ```
  - Expected result: every file reports OK, the removed total is 13, and the script exits 0.
  - **Any other result: stop and escalate.**
- [ ] **Step 4: Mutation-check the checker.** Record all three runs in the report.
  1. Copy the 9 new files to `$SCR/mut/`. In one of them, delete one `dispatch_call` block from `trace`. Run
     `$PY $SCR/gm_delta_check.py $SCR/mut`. It must exit 1, with the extra removal visible in the counter.
  2. Restore that file. In s9's copy, delete one more `phase_exit:loop_task_dispatch_action` block, one that the new trace
     still contains. The removed-count for s9 becomes 6 instead of 5, and the checker must exit 1 on the count mismatch.
  3. Run against the real directory. The checker exits 0.
- [ ] **Step 5: Re-freeze.**
  - Run `cp $REPO/.omc/artifacts/p5/baseline/*.jsonl $REPO/helao/core/tests/golden/dispatch/`.
  - Then run `--check`. It must print "CHECK PASSED".
- [ ] **Step 6:** Run `PYTHONPATH=$REPO $PY -m pytest -q -p no:cacheprovider helao/hexagon/tests/test_restore_loop_flags.py`.
  It imports this fixture, and it must pass.

**COMMIT BOUNDARY (main session):** `test(dispatch-gm): drive the reducer, re-freeze references`.
- The commit message includes the Step 3 output.
- The argument the commit message makes:
  - Every `final` block is identical.
  - The only removals are spy events the reducer makes unnecessary:
    - it clears the intent through a state delta, not by calling `intend_none()`;
    - it handles the pre-dispatch intent without entering `loop_task_dispatch_action`;
    - it stops step-thru through `StopRequested`, not through `OrchHost.stop()`.
  - Precedent: the old scenario-7 `intend_none` delta.

### Task 1b — Delete the legacy dispatch loop and the policy copy

- [ ] **Step 1: Delete from `helao/hexagon/app/orch_dispatch.py`.**
  - **The policy copy** (about lines 128–489): the classes from `DispatchSnapshot` to `DispatchPolicy`, plus
    `should_close_out_*`, `should_set_stopped` and `should_export`.
    - Replace them with `from helao.hexagon.domain.dispatch_policy import (...)`, naming **only** the names the
      remaining code still uses.
    - Find those names with `grep -n` after the deletion. Expect at least `DispatchPolicy`, `ProceedDispatch`, and the
      start-condition and intent step classes.
  - **From `DispatchRunner`**, delete `_snapshot`, `_finalization_snapshot`, `run`, `_loop`, `_log_deques`,
    `_exec_driver_health`, `_execute`, `_exec_pause`, `_finalize` and `_execute_finalization`.
  - **Keep:**
    - `__init__`, with `self.policy`;
    - `_launch_action`;
    - `_exec_pre_dispatch_intent` (M12);
    - everything below them.
  - **Remove imports left unused.** Check each `from`/`import` name with
    `grep -c '<name>' helao/hexagon/app/orch_dispatch.py`.
  - **Update the module docstring** (lines 1–40). It describes the "original dispatch_loop_task while-body".
- [ ] **Step 2: Remove `dispatch_loop_task`, and fix the docstrings that describe it.**
  - Delete `dispatch_loop_task` from `orch_host.py` (about lines 980–987).
  - `helao/hexagon/domain/orchestration.py:225`: the `start_loop` docstring says "create dispatch_loop_task (T1)".
    Change it to: "wake the HexDispatchLoop (T1): `CreateDispatchLoopTask` sets `loop_wake`; the long-lived task is the
    loop".
  - Check `OrchHost.start_loop`'s docstring for the same stale wording.
- [ ] **Step 3: Tests.**
  - `helao/core/tests/unit_test_orch_dispatch_policy.py:26`: retarget the import to `helao.hexagon.domain.dispatch_policy`.
    Change nothing else in that file. It is registered at `run_unit_tests.py:39`.
  - `helao/hexagon/tests/test_estop_fixes.py`:
    - **Delete** `test_runner_race_estop_lands_during_finish_active_experiment` and `..._sequence` (lines 157–194). They
      drive the deleted `_execute`. No port is needed, because both cases are already covered:
      - the experiment race, by `test_effect_race_estop_lands_during_finish_active_experiment` (lines 197–229, on
        `OrchCommandRunner`);
      - the sequence race, by the loop-state guard in `dispatch_sequence`, which `test_dispatch_sequence_refuses_under_estop`
        (line 147) pins.
    - Optional mutation, to show the coverage is real: make `dispatch_sequence`'s loop-state guard pass. Line 147 goes
      red.
    - Retarget any other import of policy names from `orch_dispatch` to the domain module.
- [ ] **Step 4: `helao/hexagon/app/CLAUDE.md`.** Paragraph 1 says the history poll is "twinned in `orch_dispatch.py`".
  Change it to say the poll lives only in `orch_effects.py`'s `DispatchHeadAction`.

**Gate 1b:**
- `run_tests.py --filter orch`, `--filter dispatch` and `--filter estop`: no file fails outside F0's failing set.
- Both golden masters pass `--check`.
- `run_unit_tests.py` returns rc 0.
- `test_orch_host_member_coverage.py` passes. `dispatch_loop_task` is not in the frozen contract (verified).

**COMMIT BOUNDARY:** `refactor(orch): delete the pre-reducer dispatch loop and its policy copy`.

### Task 1c — Delete dead orchestrator members and domain modules

Delete each item below, together with any tests it orphans. After each deletion, re-run its grep and show 0 remaining
hits.

- [ ] **`StatusIngester.update_nonblocking` and `update_status`** (`orch_status_sync.py:62` and `:152`).
  - Keep `__init__` and `clear_nonblocking`.
  - Remove any helpers that only those two methods used.
  - Fix the docstrings that call these methods twins or name them:
    - `helao/hexagon/app/CLAUDE.md`, paragraph 1: "Both ingestion twins (`orch_status_sync.py`, `ingestion.py`)" becomes
      "`ingestion.py`";
    - `helao/hexagon/app/ingestion.py`, lines 2, 24 and 106;
    - `helao/core/tests/unit_test_orch_status_sync.py`, line 4.
- [ ] **`ServerMonitor.active_action_monitor`** (`orch_monitor.py:107`), and its wrapper `OrchHost.active_action_monitor`
  (`orch_host.py:995`).
  - In `unit_test_orch_monitor.py`, delete the checks that exercise it. Keep the registered entry `orch_monitor_unit_test`
    (`run_unit_tests.py:43`), returning its reporter with the surviving checks.
  - Fix the docstrings that mention it: `orch_host.py:1457`, `helao/hexagon/ports/auxiliary.py:56`, and the comment at
    `helao/deploy/test/configs/goldenhexconc.yml:3`. Name the HexHealthMonitor instead.
- [ ] **`helao/hexagon/domain/status_fold.py`, `queue_policy.py` and `assembly.py`.**
  - Delete them with their tests: `helao/hexagon/tests/test_status_fold.py`, `test_queue_policy.py` and
    `test_assembly.py`.
  - Remove the `helao/hexagon/app/CLAUDE.md` sentence saying `status_fold.py` "is unwired but still encodes the
    terminal-only rule".
- [ ] **`RunQueues.replace_action`, `supplement_error_action` and `append_action`** (`orch_queues.py`).
  - In `unit_test_orch_queues.py`, delete the checks for these three. Keep the entry `orch_queues_unit_test`.
- [ ] **`RunLifecycle.start_wait`** (`orch_lifecycle.py:289`), and its mention in the docstring at line 5.
- [ ] **`get_sequence_codehash`** (`orch_unpack.py:66`), and its mentions in the docstring at lines 4 and 26.
- [ ] **`TransformXY.Mplatewarp`** (`domain/motion_transform.py:250`).

**Gate 1c:**
- `run_tests.py` with `--filter orch`, `--filter domain`, `--filter motion`, `--filter galil` and `--filter queue`.
- `run_unit_tests.py`.
- Nothing may newly fail against F0.
- The dispatch golden master passes `--check`.

### Task 1d — Delete dead ports and adapters

**Keep:**
- `HardwarePort`, `ExclusiveAccess` and `DataSinkPort`, and all their adapters.
- The `sample_state` and `ui_host` slots.

These are the user's decision.

- [ ] **`LegacyArtifactStoreAdapter`.** Delete `helao/hexagon/adapters/shared/artifact_store.py`, and its tests in
  `test_adapters_data.py`.
- [ ] **`ArtifactStorePort.write_data_line`, `close_streams` and `write_one_shot`.**
  - Remove them from:
    - the Protocol (`ports/artifact_store.py:53-74`);
    - `NativeArtifactStoreAdapter` (`adapters/native/artifact_store.py`);
    - the fake (`adapters/fakes/__init__.py`).
  - Remove the tests that exercise only these members, in `test_native_artifact_store.py` and `test_adapters_data.py`.
  - Any `isinstance(..., ArtifactStorePort)` assertion must still pass.
- [ ] **`StatusPort.send_status`.** Remove it from the Protocol (`ports/status.py:78`), from `DispatcherStatusAdapter`
  (`adapters/shared/status.py`), and from the fake.
- [ ] **The consumer side of `ports/status.py`.**
  - Delete `adapters/vis/ws_consumer.py`.
  - In `ports/status.py`, delete the following, and remove them from `__all__`:
    - `StatusStreamPort` and `ChannelNormalizerPort`;
    - `CHANNELS` (`:53`) and `CONSUMER_FACES` (`:57`).
  - Rewrite the module docstring to describe the publish side only. Drop the sentence at `:34`.
  - Drop the `WsConsumer` and `CHANNEL_NORMALIZERS` exports from `adapters/vis/__init__.py`.
  - In `helao/hexagon/tests/test_status_consumer_faces.py`:
    - Delete the Protocol and `WsConsumer` tests:
      - `test_three_faces_enumerated`
      - `test_port_channel_vocabulary_matches_the_frame_substrate`
      - `test_port_module_names_no_vendor_type`
      - `test_ws_consumer_*`
      - `test_isinstance_alone_is_vacuous_for_a_callback_protocol`
      - `test_hexagon_normalizer_declaration_mirrors_the_reflex_map`
    - Retarget the tests that cover Reflex behaviour to `helao.ui.reflex.ingest.NORMALIZERS` (`ingest.py:261`), so that
      they keep checking:
      - normalizer behaviour over real frames (`test_normalizer_face_is_behavioral_over_real_frames`);
      - the ws_path override edge (`test_ws_path_override_edge`);
      - the absence of a ws_status consumer (`test_registry_has_no_ws_status_consumer`).
    - **Mutation check for the retargeted file:** drop the `ws_data` key from a monkeypatched copy of `NORMALIZERS`. The
      normalizer-behaviour test must go red.
- [ ] **The four operator/browser ports and the vis mirrors.**
  - Delete `ports/{param_store,spec_parser,browser_source,operator_backend}.py`.
  - Delete `adapters/vis/{param_store,spec_parser,browser_source}.py`.
  - Delete `test_{param_store,spec_parser,browser_source,operator_backend}_port.py`.
  - Then run `bash -c 'grep -rn mirror_pin /mnt/STORAGE/repos/helao/helao-async/helao'`. If no importer is left, delete
    `helao/hexagon/tests/mirror_pin.py`.
- [ ] **`PlateInfoPort`, `LibraryPort`, `NotifyPort` and `UuidFactoryPort`.**
  - Delete them from `ports/auxiliary.py` and from its `__all__`. Update `test_ports_import.py` to match.
  - The docstrings of `ports/catalog.py:28` and `ports/calibration_store.py:20` cite "the `PlateInfoPort` precedent".
    Restate the rule without the name: numpy and vendor third parties are allowed in the ports and adapters that declare
    them.
- [ ] **Boundary and import tests.** Run:
  - `test_ports_import.py`
  - `test_boundaries.py`
  - `test_fakes.py`
  - every `test_*surface*.py` that exists

**Gate 1d:**
- A **full** `$PY run_tests.py` sweep.
  - Its failing set must equal F0, minus the files Task 1 deleted.
  - Every new or renamed file must pass.
  - An `ENV` verdict does not count as a failure.
- Both golden masters pass.
- `run_unit_tests.py` returns rc 0.
- Pyright is no worse than its Task 0 value.

**COMMIT BOUNDARY:** `refactor(hexagon): delete superseded members, domain modules, ports and mirrors (C3)`. This is a
single commit covering both 1c and 1d.

---

## Task 2 — C1: production sync on `NativeSyncer`, wired through `SyncPort`

### Task 2a — Deployment-C retarget (nested repo, separate commit)

This edit works against the current parent as well, because the native module already exists. It may land before
Task 2c, and should.

- [ ] **Locate Deployment-C and check it is clean:**
  ```
  DC=$(bash -c 'for d in /mnt/STORAGE/repos/helao/helao-async/helao/deploy/*/scripts/ecms_ms; do echo "${d%/scripts/ecms_ms}"; done')
  git -C $DC status --short --branch
  ```
  The tree must be clean. Note the branch.
- [ ] **Retarget the imports.** Change `helao.core.drivers.data.sync_driver` to `helao.hexagon.adapters.native.sync_driver`
  at:
  - `$DC/scripts/ecms_ms/convert_backlog.py:104`;
  - `$DC/scripts/ecms_ms/tests/test_convert_backlog.py:18` and `:782`;
  - the two `:func:` docstring references at `convert_backlog.py:21` and `:53`.
- [ ] **(Mandatory) Fix the two config comments.** In Deployment-C's `configs/`, two comments say "HelaoSyncer reads
  config_dict[...]". Find them with `bash -c "grep -rn HelaoSyncer $DC/configs"`. Change each to "the syncer reads ...".
- [ ] **Gate:** run `PYTHONPATH=$REPO $PY -m pytest -q -p no:cacheprovider $DC/scripts/ecms_ms/tests/test_convert_backlog.py`.
  Its pass/fail counts must equal its line in F0.

**COMMIT BOUNDARY (main session, in `$DC` with `git -C $DC`):** `refactor(ecms_ms): import SyncDriver from the hexagon
native module`. Run black on the two `.py` files first.

### Task 2b — Port surface, adapter, cutover, and `LegacySyncAdapter` deletion (core twin still present)

- [ ] **Step 1: Write the failing test `helao/hexagon/tests/test_sync_port_wiring.py`.** Each assertion below can fail.
  1. **`test_port_surface_is_the_measured_one`.**
     - The port's public members, `set(m for m in dir(SyncPort) if not m.startswith("_"))`, equal the D1 set exactly.
     - `isinstance(NativeSyncAdapter(drv), SyncPort)` holds.
       - `drv` comes from the `_native_syncer` helper pattern at `test_db_endpoint_surface.py:38-56`.
       - Tear it down with `teardown_driver`.
     - **Mutation:** delete `running_tasks` from the adapter. `isinstance` goes False.
  2. **`test_adapter_delegates_every_member`.**
     - Wrap a `SimpleNamespace` fake driver that records its calls.
     - Call each port member once, with **non-default** arguments, for example `finish_pending(actions_first=True)` and
       `enqueue_yml("x-act.yml", 2)`. Assert the fake received exactly those arguments.
     - Assert that `reset_sync`, `list_pending`, `release_quarantine` and `quarantined` are not coroutine functions.
     - **Mutation:** make the adapter's `finish_pending` drop `actions_first`. The test goes red.
  3. **`test_orch_to_s3_goes_through_the_port`.** This is the **only** C1 gate on the orchestrator. The dispatch golden
     master's `to_s3` stub is a no-op, and both call sites catch every exception (M4), so nothing else would notice a
     broken route.
     - Build an orch with the golden master's `_make_orch(tmp_path)`.
     - Set `orch.hexagon_wiring.sync` to a recorder with an async `to_s3`.
     - Set `orch.active_experiment` from a minimal experiment, as `_scenario_1` does.
     - Await `orch.dispatch_runner._upload_exp_meta_s3()`. That path calls `orch.write_exp`, which
       `_install_recording_stubs` stubs.
     - Assert the recorder got one call with the key `experiment/<uuid>.json`.
     - **Mutation:** point `orch_dispatch.py`'s call back at `orch.syncer`. The recorder stays empty: the AttributeError
       is caught and logged, and the test goes red.
  4. **`test_sync_server_routes_use_the_port`.**
     - Build the hte `sync_server.makeApp("SYNC")` app with an installed CONFIG. Follow the pattern of
       `test_db_endpoint_surface._action_host_driver` and `helao/deploy/hte/tests/test_sync_server_recovery.py`.
     - Run only its startup handlers. Follow the existing helper; do not bind the RPC socket.
     - Assert `isinstance(app.hexagon_wiring.sync, NativeSyncAdapter)` and `app.hexagon_wiring.sync._syncer is app.driver`.
     - Then replace `app.hexagon_wiring.sync` with a recorder **after** startup. Call the `/finish_yml` route function
       with `"a-act.yml"`. Assert that `enqueue_yml("a-act.yml", 0)` was recorded.
     - That replacement only reaches the route because the route reads the port at call time (D2b).
     - **Mutations:**
       - make the route call `app.driver.enqueue_yml` → red;
       - make `makeApp` capture `sync = app.hexagon_wiring.sync` before startup → red: `None`.
  5. **`test_sync_server_no_driver_stays_unbound`.**
     - Make driver construction fail, as `test_sync_server_recovery.py:139-153` does.
     - After startup, `app.hexagon_wiring.sync is None`.
     - `POST /hotreload_busy` returns `{"busy": False}`.
     - **Mutation:** drop the `app.driver is not None` guard. The adapter wraps `None`, and the hook call raises, so
       `busy` becomes `True` → red.
  6. **Repeat checks 4 and 5 for the test deployment's `sim_db_server`,** using `/finish_yml` and `/finish_pending`.

  Run `PYTHONPATH=$REPO $PY -m pytest -q -p no:cacheprovider helao/hexagon/tests/test_sync_port_wiring.py`. Expect FAIL.
- [ ] **Step 2: `helao/hexagon/ports/sync.py`.**
  - Rewrite `SyncPort` to the D1 members, with these signatures:

    | member | signature | sync/async |
    |---|---|---|
    | `enqueue_yml` | `(upath, rank=0, rank_limit=-5)` | async |
    | `release_quarantine` | `(yml_path) -> bool` | sync |
    | `list_pending` | `(omit_manual_exps=True) -> list` | sync |
    | `finish_pending` | `(omit_manual_exps=True, actions_first=False) -> list` | async |
    | `reset_sync` | `(sync_path) -> bool` | sync |
    | `write_off` | `(yml_path, reason, operator) -> dict` | async |
    | `quarantined` | `() -> list` | sync |
    | `running_tasks` | `() -> dict` | sync |
    | `n_queue` | `() -> int` | sync |
    | `has_pending_work` | `() -> bool` | sync |
    | `to_s3` | `(msg, target, retries=5, compress=False) -> bool` | async |

  - Delete `S3FacePort` (M18), and its entry at `test_ports_import.py:84`.
  - Rewrite the module docstring, line 1 included. It should say that the port is bound at startup (D2), and which callers
    use which members.
- [ ] **Step 3: `helao/hexagon/adapters/native/sync_adapter.py`.**
  - Implement exactly those members, delegating straight to `self._syncer`:
    - `running_tasks()` returns `self._syncer.running_tasks`;
    - `n_queue()` returns `self._syncer.task_queue.qsize()`.
  - Drop `sync_yml` and its `type: ignore`.
  - Update the docstring, which still says "NOT constructed by build_wiring" and "replaces shared/sync.py at P2e".
- [ ] **Step 4: Delete `LegacySyncAdapter` now.** It no longer satisfies the rewritten Protocol, so leaving it would turn
  the tree red.
  - Delete `helao/hexagon/adapters/shared/sync.py`.
  - In `test_adapters_misc.py`, delete its tests (about lines 60–75: the `isinstance` check, `await sync_yml`, and the
    import at line 14).
  - Update `helao/hexagon/tests/test_native_sync_adapter.py` to the D1 surface:
    - the module docstring at lines 1 and 39;
    - `:95`, which awaits `reset_sync`, which now returns a plain `bool`;
    - drop any `sync_yml` use;
    - keep the negative test that `sync` stays out of the REQUIRED sets and `build_wiring` leaves it `None`.
- [ ] **Step 5: The orchestrator.**
  - **`orch_host.py`:**
    - Replace `from helao.core.drivers.data.sync_driver import HelaoSyncer` (line 29) with two imports:
      `from helao.hexagon.adapters.native.native_syncer import NativeSyncer` and
      `from helao.hexagon.adapters.native.sync_adapter import NativeSyncAdapter`.
    - Delete `self.syncer = None` (line 165).
    - Rewrite the stale comment at lines 149–162: the syncer is native now, and the port is bound at startup.
    - In `_orch_startup` (about line 1463), construct the syncer and bind the port:
      ```python
      if self.use_sync and self.hexagon_wiring.sync is None:
          self.hexagon_wiring.sync = NativeSyncAdapter(
              NativeSyncer(self, sync_server_name=self._sync_server_key)
          )
      ```
  - **`orch_dispatch.py`**, lines 1289 and 1449: change `orch.syncer.to_s3(` to `orch.hexagon_wiring.sync.to_s3(`. Leave
    the arguments as they are.
  - **`helao/hexagon/tests/checklists/orch_member_contract.json`:** remove `"syncer"` (D3; retired on purpose). Update the
    count or description if the file has one.
    - The contract drops from 137 to 136, still above the `> 130` floor at `test_orch_host_member_coverage.py:202`. The
      remaining margin is 5. Do not lower the floor.
- [ ] **Step 6: The SYNC server, `helao/deploy/hte/servers/action/sync_server.py`.**
  - Set `driver_classes=[NativeSyncer]` and replace the import.
  - **Bind the port.** Add a startup handler, registered before `_wire_hotreload_busy` and `_arm_startup_sweep`.
    `ActionHost`'s own startup handler builds `app.driver` and runs first; this is the same ordering argument the module
    already makes for `_wire_hotreload_busy`.
    ```python
    @app.on_event("startup")
    def _bind_sync_port():
        if app.driver is not None:
            app.hexagon_wiring.sync = NativeSyncAdapter(app.driver)
    ```
  - **Route every endpoint through `app.hexagon_wiring.sync`, read inside each route body at call time.** Never bind it to
    a local variable in `makeApp` (D2b).

    | route | reads |
    |---|---|
    | `/finish_yml` | `.release_quarantine` (still via `asyncio.to_thread`), then `.enqueue_yml` |
    | `/list_pending`, `/finish_pending`, `/reset_sync`, `/write_off` | the port member of the same name |
    | `/tasks` | `.running_tasks().keys()`, `.n_queue()`, and `.quarantined()` via `to_thread` |
    | `/list_exceptions` | `.running_tasks()` |
    | `/n_queue` | `.n_queue()` |
    | `/current_progress` | stays `app.driver.progress` (D1, pinned) |

  - **Hot-reload hook:** `app.hexagon_wiring.sync is not None and app.hexagon_wiring.sync.has_pending_work()`. This
    preserves `/hotreload_busy`'s "no driver → not busy" behaviour (`action_host.py:1104-1110`).
  - **`_startup_sweep`:** pass `app.hexagon_wiring.sync` to `sweep_pending`. When the port is unbound that is `None`, and
    `sweep_pending` treats `None` as "skipped, no syncer driver". `test_sync_server_recovery.py:139-153` pins this, so
    keep it.
  - **Leave each route as it is:** signature, decorator, `def` versus `async def`, and return expression. The frozen
    checklist `helao/hexagon/tests/checklists/hte/sync_server.json` pins them.
  - **Docstrings:**
    - the module docstring;
    - the `makeApp` docstring;
    - in `sweep_pending`, the "Why this lives in the server" paragraph: the pins test is going away, and the sweep stays
      in the server because it is server lifecycle;
    - `helao/deploy/hte/tests/test_sync_server_recovery.py:6` and `:25`.
- [ ] **Step 7: The sim DB server, `helao/deploy/test/servers/action/sim_db_server.py`.**
  - Replace `SimHelaoSyncer(HelaoSyncer)` with `SimNativeSyncer(NativeSyncer)` (D5). The body stays the same.
  - Set `driver_classes=[SimNativeSyncer]`.
  - Apply Step 6's guarded bind and call-time routing to the routes this server has.
  - Update the module docstring. It still says "REAL HelaoSyncer" and "RUNS_FINISHED -> RUNS_SYNCED".
  - `harness/tests/test_sim_db_server.py:54` becomes `issubclass(mod.SimNativeSyncer, NativeSyncer)`.
  - Rename the class in `test_db_endpoint_surface.py`. Keep its pin that `progress` is absent.
- [ ] **Step 8: `helao/core/drivers/data/analysis_driver.py`** (D4).
  - Change the class to `class AnalysisSyncer(NativeSyncer)`, importing `NativeSyncer` from
    `helao.hexagon.adapters.native.native_syncer`.
  - In `__init__`, change `self.base = action_serv` to `self.host = action_serv`.
  - Change the class attribute annotation `base: "ActionHost"` to `host: "ActionHost"`.
  - Update the docstrings at lines 3, 487 and 1094.
  - Add `test_analysis_syncer_rides_native_to_s3` to `test_sync_port_wiring.py`:
    - `AnalysisSyncer.to_s3 is helao.hexagon.adapters.native.sync_driver.SyncDriver.to_s3`;
    - `issubclass(AnalysisSyncer, NativeSyncer)`.
  - **Mutation:** temporarily revert the base class to the core `HelaoSyncer`. The test goes red.
- [ ] **Step 9: Test fixtures that set `orch.syncer`.**
  - **`helao/core/tests/test_orch_dispatch_golden_master.py`:**
    - Delete `orch.syncer = SimpleNamespace(to_s3=_make_fake_to_s3())` (line 232).
    - Pass `sync=SimpleNamespace(to_s3=_make_fake_to_s3())` to the `PortWiring` built in `_make_orch` (about line 283).
    - Keep `orch.use_sync = True`.
    - Rewrite docstring line 40: "the `SyncPort.to_s3` stub (`orch.hexagon_wiring.sync.to_s3`)".
  - **`helao/hexagon/tests/test_estop_clear_race.py`.** Its orchestrator comes from
    `test_estop_finish_race.py:32` (`_make_orch`), with its own `PortWiring`.
    - In `_dispatch_ready` (line 63), set `orch.hexagon_wiring.sync = SimpleNamespace(to_s3=_to_s3)` in place of
      `orch.syncer`.
    - The parametrize ids at lines 134 and 162 that name the park target change from `syncer.to_s3` to
      `hexagon_wiring.sync.to_s3`.
    - `_park` (lines 97–112) resolves only one level of owner (`owner, _, attr = name.rpartition(".")`, then
      `getattr(orch, owner)`). Make it walk the dotted path:
      ```python
      owner = functools.reduce(getattr, owner.split("."), orch) if owner else orch
      ```
  - **`test_restore_loop_flags._orch`** (line 45): pass `sync=SimpleNamespace(to_s3=...)` into its `PortWiring`, reusing
    the golden master's `_make_fake_to_s3`.
  - **Then sweep for anything left:** `bash -c "grep -rn 'orch\.syncer\|\.syncer = ' $REPO/helao $REPO/harness"`.
- [ ] **Step 10: Run `test_sync_port_wiring.py`, then the mutations.** Expect PASS. Then do each mutation from Steps 1
  and 8 by hand, and record red followed by green.

**Gate 2b:**
- **Dispatch golden master:** `--check` passes, unchanged. This shows only that the fixture still runs: the `to_s3` stub
  is a no-op. The orchestrator's C1 gate is test 3.
- **Action golden master:** `--check` passes.
- **No new failures against F0**, from `run_tests.py` with each of these filters:
  - `/test_sync`
  - `/test_native_sync`
  - `orch`
  - `db_endpoint`
  - `analysis`
  - `hte/tests`
  - `adapters_misc`
- **The D7 offline tests** keep their F0 verdicts.
- **The checklist tests pass:**
  - `test_action_host_surface`
  - `test_orch_host_surface`
  - `test_orch_host_member_coverage`
  - the hte checklist test
- **Live parity (D7, main session):**
  - Repeat Task 0 Step 6 once.
  - Then `$PY -m harness.parity --golden $SCR/F0/GM-1/b1 --candidate $SCR/post2b/GM-1` must report **0 diffs**.
- **Comparator mutation:**
  - Copy the candidate to `$SCR/mut_cand`.
  - Delete one file under `root/S3_SIM/<bucket>/`.
  - Re-run parity. It must report a diff.
  - Record both runs.
- **The SYNC process loaded the native module.** While the group is up:
  ```
  curl -s -X POST http://127.0.0.1:8010/loaded_modules | grep -c hexagon/adapters/native/sync_driver   # >=1
  curl -s -X POST http://127.0.0.1:8010/loaded_modules | grep -c core/drivers/data/sync_driver         # 0
  ```

**COMMIT BOUNDARY:** `feat(sync): production runs NativeSyncer through the wired SyncPort (C1)`.

### Task 2c — Delete the core twin and retarget everything

- [ ] **Step 1: Delete the core twin and its pins.**
  - Delete `helao/core/drivers/data/sync_driver.py` and `helao/hexagon/tests/test_native_sync_pins.py`.
  - In `helao/hexagon/tests/sync_fixtures.py`, remove every helper and constant nothing references any more:
    - `LEGACY_SYNC_PATH` (`:23`);
    - `HELAO_SYNCER_SENTINEL` (`:49`);
    - the docstring and region text at `:23-49` and `:94`;
    - `assert_source_parity`;
    - `assert_verbatim_region`;
    - `assert_region_holds_no_imports`;
    - anything else left orphaned. Check each name with `bash -c "grep -rn <name> $REPO/helao"`.
- [ ] **Step 2: Retarget the tests.** Change both forms of the old import to the native module:
  - `helao.core.drivers.data.sync_driver` becomes `helao.hexagon.adapters.native.sync_driver`;
  - `from helao.core.drivers.data import sync_driver` becomes `from helao.hexagon.adapters.native import sync_driver`.

  The second form appears at `test_set_plate_id_resync.py:19` and `test_run_state_wiring.py:216`.
  - **Core test files** (`helao/core/tests/`):
    - `test_scan_prg_ghosts`
    - `test_sync_quarantine`
    - `unit_test_sync_relative_paths`
    - `test_run_state_wiring` (×2)
    - `unit_test_sync_process_recovery` (×4)
    - `test_sync_staging_files`
    - `test_upload_set`
    - `unit_test_estop_sync`
    - `test_orphan_record_defer`
    - `test_sync_postfinish_golden`
    - `test_to_s3_retry_body`
    - `unit_test_sync_to_thread`
    - `test_runs_layout`
    - `test_s3_upload_parquet_failure`
    - `test_hooks_postfinish`
    - `test_sync_write_off`
    - `test_sync_incomplete_process`
    - `test_prc_colocation` (×8)
    - `test_sync_postfinish_chain`
    - `test_set_plate_id_resync`
    - `test_sync_hlo_rename_warning`
    - `test_sync_loop_starvation`
    - `test_sync_parent_requeue`
  - **Parametrized twins.**
    - Where a file parametrizes over `[legacy_mod, native_mod]`, or defines `MODS = (legacy_mod, native_mod)`, collapse it
      to the native module only. Delete the legacy import.
    - Treat `test_sync_staging_files.py:199` (`[Progress, native_mod.Progress]`) the same way.
  - **`test_sequence_path_alias.py:62`** lists the core file among the files it scans. Remove that entry. Add the native
    path if it is not listed already.
  - **Hexagon test files:**
    - `test_native_sync_process_recovery.py`, lines 14 and 318: drop the legacy import and the legacy parametrize id.
    - `test_sync_secrets_not_in_config.py`, lines 16 and 56: native only.
    - `test_reconcile_interrupted.py:29`: retarget the import.
    - `test_native_sync_parity.py`:
      - delete the legacy-versus-native test;
      - replace the legacy `reset_sync` prep with the native `reset_sync`;
      - keep the F1a test (native against the committed GOLDEN) and the `skipif`;
      - rewrite the docstring.
- [ ] **Step 3: Docs and comments.**
  - **The root `CLAUDE.md`:**
    - line 69: move "the data syncer (`drivers/data/sync_driver.py`)" out of the `helao/core/` bullet. Under hexagon, add
      "the data syncer (`adapters/native/sync_driver.py`, `NativeSyncer`, wired as `SyncPort`)";
    - line 93: `HelaoSyncer` becomes `NativeSyncer`;
    - line 95: point the CLAUDE.md reference at `helao/hexagon/adapters/native/CLAUDE.md`.
  - **Move the syncer's CLAUDE.md (D9):**
    `git mv helao/core/drivers/data/CLAUDE.md helao/hexagon/adapters/native/CLAUDE.md`. Then, in the moved file:
    - change the title to "helao/hexagon/adapters/native — what the syncer uploads";
    - delete "Both sync twins carry the same edit, always — the verbatim-region pin … says so";
    - delete "Both `sync_driver.py` twins take every edit byte-identically".
  - **`docs/config-schema.md:608`:** `HelaoSyncer` becomes `NativeSyncer`.
  - **Rewrite these to describe the present state:**
    - `helao/helpers/server_keys.py:11`
    - `helao/hexagon/app/action_host.py:221`
    - `helao/hexagon/adapters/native/native_syncer.py`: the header docstring that cites the core file
    - `helao/hexagon/adapters/native/sync_driver.py`: same. Its docstring and comment lines sit outside the verbatim
      region, so the black exclusion is unaffected.
    - `helao/hexagon/tests/smoke/configs/sync.yml:2,10`
    - `helao/hexagon/tests/test_native_sync_to_thread.py:3`
    - `helao/core/tests/test_analysis_recovery.py:353`
    - the `HelaoSyncer` mentions in the docstrings of `unit_test_sync_to_thread.py` and `test_prc_colocation.py`
  - **`pyproject.toml`:**
    - change `force-exclude` (`:52`) to `'helao/hexagon/adapters/native/sync_driver\.py'` (D8);
    - rewrite the comment block at `:30-51`: it cites `sync_fixtures`' `assert_region_holds_no_imports` and the twin
      pins. Say instead why the exclusion stays: these are the exact bytes the stations ran, and a formatting-only
      follow-up will drop it.
- [ ] **Step 4: Single-implementation ratchet.** Add `test_sync_single_implementation` to `test_sync_port_wiring.py`.
  - It asserts `importlib.util.find_spec("helao.core.drivers.data.sync_driver") is None`.
  - It runs an AST walk of every `.py` under `helao/` and `harness/`, and flags each of these forms:
    - `Import` of `helao.core.drivers.data.sync_driver`;
    - `ImportFrom(module="helao.core.drivers.data.sync_driver")`;
    - `ImportFrom(module="helao.core.drivers.data")` with an alias whose name is `sync_driver`.
  - **Mutation 1 (the file).** This restores the file by writing it, not by stashing.
    1. Run `git -C $REPO show HEAD:helao/core/drivers/data/sync_driver.py > $REPO/helao/core/drivers/data/sync_driver.py`.
    2. The test goes red on `find_spec`.
    3. `rm` the file. The test goes green.
  - **Mutation 2 (the from-package form).**
    1. Create the temporary file `helao/core/tests/_tmp_ratchet_probe.py`. Its only content is a function whose body is
       `from helao.core.drivers.data import sync_driver`. The file must sit under `helao/`, because that is where the
       walk looks.
    2. The AST walk goes red.
    3. Delete the file. The test goes green.
- [ ] **Step 5: The "nothing left" check.** Run this after Step 3:
  ```
  bash -c "grep -rnE 'HelaoSyncer|core/drivers/data/sync_driver|core\.drivers\.data\.sync_driver|drivers\.data import sync_driver|LegacySyncDriver|LegacySyncAdapter|LEGACY_SYNC_PATH|HELAO_SYNCER_SENTINEL' $REPO \
     --include='*.py' --include='*.md' --include='*.yml' --include='*.toml' \
   | grep -v '/docs/superpowers/\|/\.ua/\|/\.omc/\|/\.claude/\|/\.superpowers/'"
  ```
  - The only lines allowed to remain:
    - `docs/cards-refactor/*`: historical refactor records;
    - `harness/docs/q3-local-only-sync.md` and `harness/docs/p0-gate-record.md`: dated gate records;
    - Deployment-C's own `docs/` tree and `scripts/batch_conversion.md:19`: its history, left alone.
  - Any other line: fix it, or escalate.
  - Report the allowlisted lines that remain. Write Deployment-C's paths as `<Deployment-C>/...`.

**Gate 2c:**
- A full `$PY run_tests.py` sweep. Its failing set must equal F0 minus the deleted files.
- Both golden masters pass.
- `run_unit_tests.py` returns rc 0.
- Pyright is no worse than Task 0, with `filesAnalyzed > 0`.
- One more live GM-1 parity run against `$SCR/F0/GM-1/b1` reports 0 diffs.
- `git -C $REPO status --short` shows only the intended paths.

**COMMIT BOUNDARY:** `refactor(sync): delete the core sync twin and HelaoSyncer (C1)`.

---

## Task 3 — C2: `--restore` and queue export through `StatePersistencePort`

- [ ] **Step 1: Write the failing test `helao/hexagon/tests/test_queue_persistence_port.py`.** Use `tmp_path`; no test
  root ever touches a mount.
  1. **`test_export_path_is_the_os_path_string`.**
     - Use the root `root = str(tmp_path) + "//x"`. `os.path.join` keeps the doubled slash, while `str(Path(...))`
       collapses it.
     - `QueuePckStore(root).export_queues({"schema": 1})` must return a `str` equal to
       `os.path.join(root, "STATES", "queues.pck")`.
     - The file must unpickle to the payload.
     - **Mutation:** return `str(Path(...))`. The equality check goes red.
  2. **`test_timestamped_export_prunes_to_retention`.**
     - Seed 7 files, `queues_2601{01..07}.120000.pck`. Seed one `queues_imported_x.pck` and one
       `queues_unreadable_x.pck`.
     - Export with `timestamp_pck=True`. That makes 8 timestamped files, with the new one newest. Exactly 5 must remain.
     - Seeds at index 0, 1 and 2 are gone; **assert specifically that index 1 is gone.** Index 3 **remains**.
     - Both archives remain.
     - **Mutations:**
       - skip the prune → red;
       - keep 6 → red, because index 2 survives.
  3. **`test_load_quarantines_an_unreadable_pickle`.**
     - Write garbage bytes to `queues.pck`.
     - `load_queues()` returns `(path, None)`.
     - `queues.pck` is gone, and exactly one `queues_unreadable_*.pck` exists.
     - **Mutation:** remove the rename → red.
  4. **`test_load_missing_returns_none_and_touches_nothing`.**
     - With no `queues.pck`, `load_queues()` returns `(os.path.join(root, "STATES", "queues.pck"), None)`.
     - The `STATES` listing is unchanged.
     - **Mutation:** make the missing branch create an empty file, or move anything → red.
  5. **Persister tests.** Build each orch with the golden master's `_make_orch`, and wire
     `state_persistence=QueuePckStore(orch.world_cfg["root"])`. The store root must be exactly that orch's
     `world_cfg["root"]`.
     - **`test_schema_mismatch_is_not_archived`.**
       - Export a payload with `schema: 0` by hand, then `import_queues()`.
       - The file is still `queues.pck`, and no `_imported_` file exists.
       - **Mutation:** archive inside `load_queues` → red.
     - **`test_successful_default_import_archives_once`.**
       - Export from orch A, then import into a fresh orch B.
       - Afterwards: no `queues.pck`, and exactly one `queues_imported_*.pck`.
       - B's deques equal A's, and `loop_state` is `stopped`.
       - **Mutation:** skip the `archive_consumed` call → red.
     - **`test_explicit_path_import_is_not_archived`.** After the import, the explicit file still exists.
     - **`test_persister_routes_through_the_port`.** Wire a recording `StatePersistencePort` stub instead of the store.
       - `orch.export_queues()` calls `stub.export_queues` once, with a payload whose `schema == QUEUE_PCK_SCHEMA`.
       - The orch returns exactly the string the stub returned.
       - `orch.import_queues()` calls `stub.load_queues(None)`.
       - It calls `stub.archive_consumed` only on success.
       - **Mutation:** make `QueuePersister.export_queues` call `pickle.dump` directly again → red.

  Run the file. Expect FAIL: `load_queues` and `archive_consumed` do not exist yet.
- [ ] **Step 2: Port and adapter.**
  - **`ports/auxiliary.py`:** change `StatePersistencePort` to the D10 members and update its docstring.
  - **`adapters/shared/state_persistence.py`:** `QueuePckStore(root: str)` keeps `self._root = root`. Move the file
    contract out of `orch_persist.py` into it:
    - **`export_queues(payload, timestamp_pck=False) -> str`.** Build the name and the `os.path.join` exactly as
      `orch_persist.py:160-170` does. When `timestamp_pck` is set, call `prune_timestamped_exports`.
    - **Move these verbatim:** `prune_timestamped_exports`, `TIMESTAMPED_EXPORT_RETENTION` and `_TIMESTAMPED_EXPORT_RE`.
    - **`orch_persist.py` must re-export** `_TIMESTAMPED_EXPORT_RE`, `TIMESTAMPED_EXPORT_RETENTION` and
      `QUEUE_PCK_SCHEMA`. This is **required**: `helao/core/tests/check_queue_pcks.py:38` imports all three from there.
    - **`load_queues(pck_path=None) -> tuple[str, Optional[dict]]`.** Copy these verbatim from `orch_persist.py:326-361`:
      - the logic that strips quotes from the path;
      - the exists/missing log line;
      - the try-unpickle, with its `_unreadable_` quarantine and error log.
    - **`archive_consumed(path) -> Optional[str]`.** Copy the `_imported_` rename and its OSError warning verbatim from
      `:429-439`.
    - Every LOGGER message keeps its exact text.
  - **Delete the old `import_queues()` from the adapter.**
  - **Update `FakeStatePersistence`** (`adapters/fakes/__init__.py:265`) to the new surface. Fix `test_fakes.py` and
    `test_adapters_misc.py:81-99` to match.
- [ ] **Step 3: `orch_persist.QueuePersister`.**
  - It resolves `store = self.orch.hexagon_wiring.state_persistence` **at call time**. That is its cache-nothing rule.
  - **`export_queues`:** build `queue_dict` exactly as today, then `return store.export_queues(queue_dict, timestamp_pck)`.
  - **`import_queues(pck_path)`:**
    1. Call `save_path, queue_dict = store.load_queues(pck_path)`. If `queue_dict is None`, return `save_path`.
    2. Keep the schema check and the "Existing queues are not empty" refusal as they are.
    3. Keep the apply step as it is: applying the payload, `_requeue_inflight_actions`, and the loop-flag reset.
    4. Then, still inside the same `try`, call `store.archive_consumed(save_path)` if `pck_path is None`.
  - Update the module docstring. It still says the module owns the file.
- [ ] **Step 4: Fixtures.** Fix each place below only by wiring the store. Never change an assertion.
  - **`test_orch_dispatch_golden_master._make_orch`**, which also feeds `capture_queues_pck_fixture`: add
    `state_persistence=QueuePckStore(str(tmp_root))`.
  - **`test_restore_loop_flags._orch`** (line 45): add `state_persistence=QueuePckStore(orch.world_cfg["root"])`. Each
    orch, `src` and `dst`, gets its own store, rooted at its own `world_cfg["root"]`.
  - **`test_orch_stops_polling_on_shutdown.py:128`:** the `SimpleNamespace` orch it passes to `QueuePersister` gets
    `hexagon_wiring=PortWiring(state_persistence=QueuePckStore(str(tmp_path)))`.
  - **Any other place the sweep exposes.**
- [ ] **Step 5: Run the new test file and its mutations, then the neighbours.**
  - Run the new file. Record each mutation, red then green.
  - Run `test_restore_loop_flags.py`, which pins the #224 behaviour.
  - Run `PYTHONPATH=$REPO $PY helao/core/tests/check_queue_pcks.py --help`. It must still import.

**Gate 3:**
- **Dispatch golden master:** `--check` passes, and its queues.pck round-trip fixture still passes.
- **No new failures:** `run_tests.py` with `--filter orch`, `--filter persist`, `--filter restore` and `--filter fakes`.
- **`run_unit_tests.py`** returns rc 0.
- **The checklist entries for `/export_queues` and `/import_queues`** in `checklists/orch_openapi.json` are unchanged.
- **Restore smoke (main session):**
  - Repeat Task 0 Step 7 exactly.
  - The new `restore_export_post.json` must equal `$SCR/F0/restore_export_b1.json`, and the new `restore_final_post.json`
    must equal `$SCR/F0/restore_final_b1.json`.
  - In `$SCR/post3/rB.log`, the ORCH log contains both "restore_queues_on_startup is set" and
    "Archived restored queue pck to".
- **`restore_smoke.py`** is committed in this commit.

**COMMIT BOUNDARY:** `refactor(orch): queue export and --restore go through StatePersistencePort (C2)`.

---

## Task 4 — C4: two deferred behaviours (Linux gates; the user verifies on a station before merge)

### Task 4a — The 0.3 s pacing sleep no longer blocks

- [ ] **Step 1: Write the failing test `helao/hexagon/tests/test_status_pacing_nonblocking.py`.**
  - **Setup:**
    - Build an `ActionHost` with the `_host()` pattern from `test_get_status_survives_a_down_driver.py:56-90`: injected
      config, stub ports, and no lifespan.
    - Stub `host.send_statuspackage` with an async function that records `loop.time()` and returns
      `({"ok": 1}, ErrorCodes.none)`.
    - Start `host.log_status_task()` as a task.
    - In teardown, cancel every task the test started.
  1. **`test_pacing_does_not_block_the_loop`.**
     - Set `host.status_clients = {("ORCH", "127.0.0.1", 1)}`.
     - **Before** putting the status, start a ticker coroutine. It loops `await asyncio.sleep(0.01)`, recording the
       largest gap between consecutive wakeups.
     - Put one status onto `host.status_q`. Use an `Action(...).get_act()` with `action_name`, `action_uuid` and
       `action_server` set.
     - Wait 0.5 s, which covers the whole 0.3 s pacing window. Then stop the ticker.
     - Assert the largest gap is `< 0.15` s. A blocking sleep produces a gap of at least 0.29 s.
     - **Mutation:** restore `time.sleep(0.3)` → red.
  2. **`test_pacing_is_preserved_between_clients`.**
     - Use two clients.
     - The two recorded send times are at least 0.29 s apart.
     - **Mutation:** delete the sleep → red.
- [ ] **Step 2: Make the sleep non-blocking.**
  - In `action_host.py`, replace the comment block and `time.sleep(0.3)` that close the per-client loop in
    `log_status_task` with `await asyncio.sleep(0.3)`.
  - The new comment says why: this is per-client pacing, now non-blocking (C4a).
  - Remove `import time` if nothing else in the file uses it. Check with `grep -n 'time\.' action_host.py`.
- [ ] **Step 3: Run the new test, then both mutations.** Record each red and the green that follows.

**Gate 4a:**
- The new test passes.
- These live tests pass, each in its own process:
  - `test_no_wait_overlap_live.py`
  - `test_concurrency_live.py`
  - `test_stop_requeues_pending_action_live.py`

  They cover the dispatch-loop traps in `helao/hexagon/app/CLAUDE.md`. Status timing feeds the history poll that those
  traps depend on.
- Both golden masters pass.
- **Launch smoke (main session):** one `goldenhex` GM-1 capture. Parity against `$SCR/F0/GM-1/b1` must report 0 diffs.

**COMMIT BOUNDARY:** `fix(action-host): status pacing sleep no longer blocks the event loop (C4a)`.

### Task 4b — The finish drain becomes a marker round-trip, with two bounds (D12)

- [ ] **Step 1: Write the failing test `helao/hexagon/tests/test_finish_drain_marker.py`.**
  - **Fixtures:**
    - Reuse the action golden master's host fixture:
      `from helao.core.tests.test_active_golden_master import _make_host, _mk_action, _active_params, _PatchedBaseGlobals, _drain_data, _ticks`.
    - Use `ActionSession` the way scenario 13 does.
    - There is no pytest-timeout plugin in the env, so every finish call is bounded with
      `await asyncio.wait_for(active.finish(), <bound>)`.
    - To capture the WARNING:
      - `make_logger` sets `propagate=False` (`helao_logging.py:611`), so caplog cannot see the record by default;
      - the WARNING comes from `data_stream.LOGGER`;
      - attach `caplog.handler` to that logger and remove it in `finally`. The pattern is
        `test_driver_poller_survives_error.py:31`.
  1. **`test_slow_logger_loses_nothing_queued_before_finish`.**
     - Monkeypatch the session's `write_live_data` with a wrapper that does `await asyncio.sleep(0.15)` before writing.
     - Enqueue 1 packet, then `_drain_data`.
     - Enqueue 10 more with `enqueue_data_nowait`, `t` = 1..10, and immediately
       `await asyncio.wait_for(active.finish(), 5.0)`.
     - Read the `.hlo`: all 11 data rows are present.
       - Under the old 2 × 5 × 0.1 s window, only about 6 of the 10 late rows fit: 10 × 0.15 s = 1.5 s, more than 1.0 s.
     - **Mutation:**
       - run `git -C $REPO show HEAD:helao/hexagon/adapters/native/finalizer.py > $REPO/helao/hexagon/adapters/native/finalizer.py`,
         which restores the old loops;
       - run **this test alone** (`-k slow_logger`). It sees fewer than 11 rows and goes red. Tests 2–4 monkeypatch the
         new constants with `raising=True`, so they error under the old file; that is expected and is not part of the
         check;
       - restore the file. The test only writes inside `tmp`.
  2. **`test_dead_logger_skips_the_wait`.**
     - Set `save_data=False`, so the logger returns at once.
     - Monkeypatch `finalizer.FINISH_DRAIN_TIMEOUT_S` to 2.0.
     - Time **`await active.drain_data(2.0)` alone**, with `loop.time()`. It must take less than 0.1 s.
     - `finish()` must also complete, inside `wait_for(..., 2.0)`.
     - **Mutation:** remove **both** logger-alive checks in `drain`, the one before the loop and the one inside it.
       `drain_data` then waits the whole 2 s → red.
  3. **`test_hung_logger_is_bounded_and_warns`.**
     - Monkeypatch `finalizer.FINISH_DRAIN_TIMEOUT_S` to 0.4.
     - Make `write_live_data` hang on an `asyncio.Event` that is never set.
     - Enqueue 1 packet. Then `await asyncio.wait_for(active.finish(), 2.0)`. It must return, with no `TimeoutError`, in
       less than 0.4 + 0.3 s.
     - Exactly one WARNING containing `finish drain timed out` is captured.
     - **Mutation:** remove the deadline. `wait_for` raises `TimeoutError` → red.
  4. **`test_estop_finish_uses_the_short_bound`.**
     - Leave `finalizer.FINISH_DRAIN_TIMEOUT_S` at 10.0. Monkeypatch `ESTOP_FINISH_DRAIN_TIMEOUT_S` to 1.0, which is its
       real value; the patch only makes the dependency explicit.
     - Hang the logger as in test 3. Enqueue 1 packet. Then call `active.set_estop()`, which is what `estop_actives` does
       (M19).
     - `await asyncio.wait_for(active.finish(), 1.5)` must return.
     - The WARNING text says `after 1.0s`.
     - **Mutation:** make the selector always pick `FINISH_DRAIN_TIMEOUT_S`. The finish then waits 10 s, and `wait_for`
       raises → red.
- [ ] **Step 2: Implement.**
  - **`adapters/native/data_stream.py` (`NativeDataStreamer`):**
    - Add the instance fields `_drain_marker = None`, `_drain_event = None` and `_consumed = 0`.
    - In `log_data_task`:
      - increment `self._consumed` for every message pulled from the subscription, as the first statement in the
        `async for` body;
      - directly after `self.active.action.data_stream_status = data_status`, add
        `if data_msg is self._drain_marker and self._drain_event is not None: self._drain_event.set()`.
    - Add `async def drain(self, timeout_s: float) -> bool`:
      ```python
      async def drain(self, timeout_s: float) -> bool:
          """Return once everything queued before this call is written (FIFO marker)."""
          logger = self.active.data_logger
          if logger is None or logger.done():
              return True
          loop = asyncio.get_running_loop()
          deadline = loop.time() + timeout_s
          self._drain_marker = self.active.assemble_data_msg(
              DataModel(data={}, errors=[], status=HloStatus.finished)
          )
          self._drain_event = asyncio.Event()
          try:
              await self.active.base.data_q.put(self._drain_marker)
              seen = self._consumed
              while True:
                  if logger.done():
                      return True  # the logger exited mid-drain; nothing is left to wait for
                  try:
                      await asyncio.wait_for(self._drain_event.wait(), 0.1)
                      return True
                  except asyncio.TimeoutError:
                      if loop.time() >= deadline:
                          LOGGER.warning(
                              f"finish drain timed out after {timeout_s}s: num_queued "
                              f"{self.active.num_data_queued} > num_written "
                              f"{self.active.num_data_written}; rows queued after this are dropped"
                          )
                          return False
                      if self._consumed == seen:  # nothing moved: the marker may have been missed
                          await self.active.base.data_q.put(self._drain_marker)
                      seen = self._consumed
          finally:
              self._drain_marker = None
              self._drain_event = None
      ```
      How the re-put works:
      - The marker is put once up front.
      - After each 0.1 s wait it is put again, but only if `_consumed` has not changed since the last check. That
        catches a logger that subscribed after the first put.
      - A logger that is busy working through a backlog keeps `_consumed` moving, so no marker is queued behind it.
  - **`app/action_session.py`:** add a delegation method next to `log_data_task`:
    `async def drain_data(self, timeout_s: float) -> bool: return await self.data_stream.drain(timeout_s)`.
  - **`ports/action_session.py`:** declare `drain_data(self, timeout_s: float) -> bool` (async) in `ActionSessionPort`.
  - **`adapters/native/finalizer.py`:**
    - Add these module constants, each defined in exactly one place:
      ```python
      FINISH_DRAIN_TIMEOUT_S = 10.0  # normal finish: wait for a genuinely slow logger
      ESTOP_FINISH_DRAIN_TIMEOUT_S = 1.0  # E-STOP finish: /estop finishes sessions serially
      ```
    - Replace the two loops (M16's text anchors: from `LOGGER.info("finish active: sending finish data_stream_status
      package")` through the `await asyncio.sleep(0.1)` that ends the `write_iter` loop) with:
      ```python
      estopped = any(
          HloStatus.estopped in a.action_status for a in self.active.action_list
      )
      timeout_s = ESTOP_FINISH_DRAIN_TIMEOUT_S if estopped else FINISH_DRAIN_TIMEOUT_S
      LOGGER.info(f"finish active: draining the data logger (bound {timeout_s}s)")
      await self.active.drain_data(timeout_s)
      ```
    - Keep everything from `# self.action_list[-1] is the very first action` onward unchanged.
    - Rewrite the module docstring's description of the drain: the marker drain and the two bounds.
  - **`helao/core/tests/test_active_golden_master.py`:** rewrite only the `_scenario_finish_late_data_drain` docstring,
    which still describes "the two capped retry+sleep(0.1) loops". The scenario code and the references stay as they are.
- [ ] **Step 3: The scenario-13 re-baseline argument.** The expected result is **no re-freeze**:
  - The trace recorder drops data-less packets (M16), so a different number of housekeeping `finished` packets cannot
    show up in the trace.
  - The order `status_packet: finished` → `move_dir` → `post_finish` is unchanged.
  - `runs.norm` already holds the late row `{"t":1,"v":111}`, and the marker drain preserves it, because the marker sits
    behind it in the same FIFO.

  Run `--check`, then the default-mode determinism self-test.
  - **If scenario 13, or any scenario, reports DELTA, stop and escalate with the diff.** Do not re-freeze.
  - The tests from Step 1 are the new, stronger pin. Scenario 13 stays the ordering pin.
- [ ] **Step 4: Run the new tests, then each mutation.** Record red then green for each mutation.

**Gate 4b:**
- The new tests pass.
- `test_action_session_port.py` passes. It checks that `drain_data` is declared and that every `active.<x>` the finalizer
  reads is a port member.
- Both golden masters pass, unchanged.
- No new failures from `run_tests.py` with `--filter action`, `--filter finaliz`, `--filter data_stream` and
  `--filter session`.
- **E-STOP timing.**
  - Test 4 passes. A finish on the E-STOP path with a hung logger returns within 1.5 s.
  - `test_estop_fixes.py` passes.
  - Every test with `estop` in its name passes under `--filter estop`.
  - The `/estop` route tests that finalize sessions complete well inside `ESTOP_SEND_TIMEOUT_S`. Name them in the report.
- **Launch smoke:** a GM-1 parity run against `$SCR/F0/GM-1/b1` reports 0 diffs. This checks the tree, the metadata and
  S3; it does not prove `.hlo` row identity (D7). Rows are proved by test 1.
- **A full final `run_tests.py`:**
  - The failing set equals F0 minus the deleted files.
  - Run `bash -c "grep -c 'finish drain timed out' $SCR/final/run_tests.log"`. The count must be 0, apart from lines
    attributable to `test_finish_drain_marker.py`'s tests 3 and 4.
    - The sweep prints test output only for failing files. To be sure, also run each of the following and grep their
      output:
      - `--filter action`
      - `--filter session`
      - `--filter estop`
      - `--filter golden`
    - Any timeout outside tests 3 and 4 means a logger is slower than its bound somewhere. Escalate it.
- **`run_unit_tests.py`** returns rc 0.
- **Pyright** is no worse than Task 0.

**COMMIT BOUNDARY:** `fix(finalizer): drain by marker round-trip with normal and E-STOP bounds (C4b)`.

### Station verification checklist

**Scope:** both C4 changes. The user runs this, and **the branch is not merged before it passes.**

**Station:** one hexagon station with a streaming data action, for example `eche10` (Windows).

1. **PRE.**
   - In the parent repo, check out `unstable` at the merge base: `git -C <repo> merge-base unstable feat/hexagon-completion`.
   - Check out each nested repo at its Task 0 head. Deployment-C is on `main` at `435e137`. The others stay as they
     are: this branch changes nothing in them.
   - Launch, and run the station smoke sequence: one CV or other streaming action, plus one non-blocking action if the
     station has one.
   - Let it drain, and let SYNC go idle.
   - Run `helao\hexagon\tests\smoke\eche10_golden_diff.bat capture pre <SEQNAME>`.
2. **POST.**
   - Check out the branch, and Deployment-C on its `feat/hexagon-completion` branch at `fb79839` (plus any later commit
     on that branch). The parent branch and the Deployment-C branch merge together.
   - Launch, and run the same sequence on the same hardware. Drain and sync.
   - Run `... capture post <SEQNAME>`.
3. **DIFF.**
   - Run `... diff`. Both trees use the unified layout, so no remap flag is needed.
   - Classify the report the way the 2026-09-30 eche10 diff was classified: first filter out `body.ch_*`, `epoch_s` and
     `hlo_version`.
   - Every remaining non-data diff must be explained. None are expected.
   - The `.hlo` row counts of the data actions must be **equal or higher** in POST. Never lower.
4. **Logs: the POST action server.**
   - The "Pushed status message to ORCH" lines for one action are still ≥ 0.3 s apart, so the pacing is kept.
   - There are no `num_queued … > num_written` lines.
   - There is no `finish drain timed out` WARNING.
   - From an action's last data row to its `finished` status takes ≤ 0.2 s. Before the change it was up to ~1.0 s.
5. **Responsiveness (C4a).**
   - During a running action, `curl -X POST http://<host>:<port>/get_status` on the action server answers in under 0.3 s,
     on each of 10 consecutive calls. Before, it could stall behind the blocking sleep.
   - On a server configured with `allow_concurrent_actions: false`:
     - queue a second action while the first runs;
     - when the first finishes, the queued one starts within 0.5 s;
     - a fresh POST to the server during the first action is answered at once. It is queued, not stalled.
6. **E-STOP timing (C4b).**
   - During a streaming action, press E-STOP from the operator UI.
   - The action server's log shows its sessions finalized, with any drain warning reading `after 1.0s`, never `10.0s`.
   - The orchestrator log shows no `estop for <server> timed out after 10.0s` line.
   - The whole E-STOP fan-out completes in under 3 s, measured from the orchestrator log timestamps.
   - Press E-STOP again while a streaming action is still finishing. `estopped_actions` lists every live action uuid.
     The action server log shows no `error finalizing an active action during estop` and no `AttributeError`.
   - After a non-streaming action on a server that also streams, the Bokeh or Reflex visualizer keeps its last trace:
     no data-less `finished` packet reaches `/ws_data` for a non-streaming action.
7. **SYNC.**
   - The sequence reaches synced.
   - The SYNC server's `/loaded_modules` lists `hexagon/adapters/native/sync_driver.py`, and does not list
     `core/drivers/data/sync_driver.py`.
   - `/tasks` answers with `quarantined: []`, or with the same list as PRE, and `last_startup_sweep` is non-null.
   - `POST /n_queue`, `/list_pending` and `/list_exceptions` all answer (no `AttributeError` on a `None` port).
   - `POST /hotreload_busy` answers `{"busy": false}` when SYNC is idle, and `{"busy": true}` while a sync is running.
   - The ORCH log shows `initializing SyncDriver` once, the initial active experiment and sequence S3 upload lines, and
     no `Error uploading initial active`.
   - Optional: run one analysis that uploads through `AnalysisSyncer`, and check that the upload lands.
8. **Restore (optional, recommended; required on Windows).**
   - Queue a 2-experiment sequence and start it. Press CTRL-x mid-run. `STATES\queues.pck` exists.
   - **On Windows this step is required, not optional** (the C2 path change). `/export_queues` must return a backslash
     path, `C:\...\STATES\queues.pck`.
   - Relaunch with `--restore`. Check that:
     - `queues_imported_<ts>.pck` exists;
     - the in-flight action re-runs under a new uuid;
     - the old uuid shows `[skipped, finished]`.
9. **Teardown.** `CTRL-x` tears the group down cleanly.

---

## 5. Final done-criteria

- Every COMMIT BOUNDARY above has been passed, with its gate evidence in the task report.
- `git -C $REPO log --oneline ba910c4c..HEAD` shows these commits, in this order:
  1. 1a
  2. 1b
  3. 1c+1d
  4. 2b
  5. 2c
  6. 3
  7. 4a
  8. 4b

  The Deployment-C commit is separate.
- No `test.skip`, `.only`, stub test, or unimplemented branch has been added. Check with:
  ```
  git -C $REPO diff ba910c4c..HEAD | grep -nE '^\+.*(pytest\.mark\.skip|\.only\(|NotImplementedError|TODO)'
  ```
  The one allowed hit is the existing GM-1 `skipif`.
- The user has completed the station checklist before merge.

---

## 6. Open questions

Each question has a default, and the tasks above implement the default.

**Q1. Where does the Deployment-C commit go?**
- Default: on its current branch (`main`), before Task 2c. It works against both the old parent and the new one.
- Alternative: a matching feature branch, merged together with the parent.

**Q2. Should `S3FacePort` be deleted?** (M18)
- It has no implementation, and it was not on the C3 list.
- Default: delete it in Task 2b, since `ports/sync.py` is being rewritten anyway.
- If the user wants to keep it, drop that bullet.

**Q3. Should the orchestrator stop building a full `SyncDriver`?**
- Today it builds one, with its workers and a SYNC-journal replay, only to call `to_s3`. Parity holds by construction.
- A dedicated S3-only face for the orchestrator would remove a second `RunStateJournal(..., "SYNC")` reader and writer
  from the ORCH process.
- That is a behaviour change, though not one visible on the wire.
- Default: leave it as it is, and record it as a follow-up.

**Q4. When does black run on the native `sync_driver.py`?** (D8)
- Default: a formatting-only commit after the merge and the station check, which also drops the `force-exclude`.
- Alternative: keep the file excluded permanently.

**Q5. Drain bounds. DECIDED by the user (2026-10-19).**
- Two bounds: `FINISH_DRAIN_TIMEOUT_S = 10.0` for a normal finish, and `ESTOP_FINISH_DRAIN_TIMEOUT_S = 1.0` for a finish
  on an E-STOP path.
- The finalizer selects the bound from the session's own estop state. D12 gives the selector and why.
- Both are module constants, not config. A config knob is a one-line follow-up if a station needs one.

**Q6. Two passages of the master spec now describe superseded behaviour.**
- §5.4 invariant 4 says "≤5 × 0.1 s … late data … silently dropped".
- §4.3.6 says "blocking 0.3 s … preserved until post-parity".
- Default: leave the dated spec untouched, and record the change in the C4 commit messages.
- Alternative: add a dated amendment note to the spec.

**Q7. `/current_progress` keeps raising `AttributeError`, which is pinned.**
- Default: leave it. Fixing it is wire-visible and out of scope.

**Q8. The dispatch golden master drives a private method, `HexDispatchLoop._run_started_phase`.**
- It does so to stay deterministic, with no background task.
- Default: accept it, because it is test code.
- Alternative: add a public `run_once()` to `HexDispatchLoop`. That would be a new public member that exists only for
  tests.
