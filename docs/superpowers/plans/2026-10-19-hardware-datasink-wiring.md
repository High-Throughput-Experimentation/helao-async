# Hardware / DataSink port wiring: host-owned driver lifecycle, trimmed ports, typed host surface

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development` or
> `superpowers:executing-plans` to carry this out task by task. Steps use checkbox (`- [ ]`) syntax.

**Branch:** `feat/hexagon-completion`, in the parent repo, on top of the hexagon-completion plan's C1–C4
(`docs/superpowers/plans/2026-10-19-hexagon-completion.md`). **Task 4b of that plan must be committed before Task 0
here starts.**

**Implements:** `docs/superpowers/specs/2026-10-19-hardware-datasink-wiring-design.md` (the spec), approved as written.
Every open question in the spec's §8 is at its recommended default (user, 2026-10-19):

1. keep the attribute name `_base_hook`;
2. ship the `enqueue_data_nowait` thread-safety fix with the NI-DAQmx increment (I6e), behind a falsifiable
   foreign-thread test;
3. delete `UiHostPort.build_ui_app` now, together with the never-read `ui_host` slot;
4. power_supply keeps per-action connect (`connect_on_startup = False`);
5. lazy-connect drivers do not opt in;
6. SprintIR at `ccsi2` is the I1 canary; CM0134 rides on Linux gates only;
7. master-spec changes go in a short amendment file.

User decisions on this plan's own questions (final, 2026-10-19): Q1 Andor takes its key from `_base_hook` at the top of
`connect()`; **Q4 a raising host-managed connect is caught, logged at ERROR with traceback, alerted, and the server
starts with the driver disconnected**, for every host-managed connect; Q6 the host sets `_base_hook` on every
`HelaoDriver`; Q7 seven server-side log lines become one host line, which the plan and the station checklist call out;
Q9 station checks run at the branch head and bisect only on a failure.

**Revision 2 (2026-10-19):** applies the plan review's 12 required fixes and the user's final decisions on Q1, Q4,
Q6, Q7 and Q9 (§8). The biggest changes:
- a host-managed `connect()` that raises no longer stops startup; the host logs it and starts with the driver
  disconnected (D3, A3);
- the cross-thread put keeps FIFO order and is flushed before the drain marker (D10);
- the construct ratchet imports first, then records tripwire hits, and checks the pending set by AST (D4, D8);
- A4 is withdrawn: the time until the server first answers a request is unchanged.

**Revision 3 (2026-10-19):** applies the Revision 2 re-review (approve-with-fixes; Q10, Q11 and Q12 accepted).
- Task 7e test 3 asserts on the put record. Test 4b is added, and `drain`'s flush is now its unconditional first
  statement.
- The closed-loop branch no longer grows the deque.
- The construct test allowlists the leancat subtree and never patches vendor exception classes.
- The disconnected-poll check pre-settles the TEC poller and names where the guards live.
- The galil_io/NI-DAQmx startup-line claim is reworded as conditional.
- A TEC host start-and-shutdown test is added.
- Follow-ups F1 and F2 are recorded in §8.

**Sequencing.** Task 0 runs only after the completion branch's pending fix commit (the `NativeDataStreamer.drain`
rework: per-call waiters and a skip-when-never-streamed guard) has landed on top of `9f032f82`. Task 0 re-baselines
there.

**Inputs:**
- the spec (all of it);
- `helao/hexagon/app/CLAUDE.md` (host traps), `helao/helpers/CLAUDE.md` (launcher/child lifetime);
- `helao/deploy/hte/drivers/pstat/CLAUDE.md` (BioLogic OLE path), `helao/deploy/hte/drivers/spec/andor/CLAUDE.md`;
- the master spec, `docs/superpowers/specs/2026-07-16-framework-hexagonal-rewrite-design.md` §4.3.1, §4.3.2, §4.5, §10.4;
- the amendment precedent, `docs/superpowers/specs/2026-08-08-hexagonal-rewrite-amendment-2.md`.

**Goal.** `HelaoDriver` stays the hardware contract and the host owns its lifecycle: it sets `_base_hook`, then calls
`connect()` for drivers that declare `connect_on_startup = True`, before it builds the poller and runs
`dyn_endpoints`. Constructor connects and `dyn_endpoints` connects are removed one increment at a time, canary first.
The four never-wired `PortWiring` slots and their adapters are deleted. `DataSinkPort` shrinks to what executors call,
and `ActionSession` satisfies it with no adapter. The host surface that hardware-side code reads becomes a typed
`DriverHostPort` behind an AST gate.

All increments I0..I7 land on this branch with Linux gates. The user runs the Windows station checks (§7) before
merge.

---

## 0. Global constraints (every task, every delegation prompt carries these)

- **No outward-facing actions.** Implementers never run `git add`, `commit`, `push` or `stash`.
  - The main session commits at the marked **COMMIT BOUNDARY** lines, after the gate passes and the user approves.
  - Implementers write only inside `$REPO`'s working tree (and, where a step says so, inside a nested repo's tree)
    and inside `$SCR`.
- **Every git call is `git -C <repo>`.** The nested deployment repos under `helao/deploy/` are separate git repos with
  their own branches. A subagent's cwd resets between calls, so use absolute paths.
- **Never touch the production network mounts (`/mnt/wd4` and its siblings).** Nothing here needs them. Export
  `HELAO_SOURCES_ROOT=$SCR/sources` for every test run (some code falls back to a production root without it).
- **Privacy.** The parent repo is public.
  - Never write a private deployment's directory name in any tracked parent file: code, comments, tests, docs, commit
    messages. Use the aliases below, or "a private deployment".
  - Aliases used in this plan (locate each by content, never by name):
    - **Deployment-A**: the nested repo with `servers/action/potentiostat_server.py`;
    - **Deployment-B**: the nested repo with `drivers/robotarm/robotarm_driver.py`;
    - **Deployment-C**: the nested repo with `scripts/ecms_ms/convert_backlog.py`;
    - **Deployment-E**: the nested repo with `servers/action/oceandirect_server.py`.
    ```
    bash -c 'for f in servers/action/potentiostat_server.py drivers/robotarm/robotarm_driver.py scripts/ecms_ms/convert_backlog.py servers/action/oceandirect_server.py; do for d in '"$REPO"'/helao/deploy/*/; do [ -e "$d$f" ] && echo "$f -> $d"; done; done'
    ```
    Keep that output in `$SCR` only.
  - `nested_heads.txt` and every grep over nested repos stay in `$SCR`. Never paste their raw lines into a tracked
    file: they carry private names.
- **Escalate, don't choose.** Anything visible on the wire or on disk that this plan does not settle (route sets,
  parameters, response bodies, file names, log lines a test pins, the order of writes) is a stop-and-report. §8 lists
  the ones already found, each with the default the tasks implement.
- **Environment.**
  ```
  REPO=<the parent repo checkout>                  # the main session fills this in
  PY=$HELAO_ENV/bin/python                         # the helao conda env
  SCR=/tmp/claude-1000/hwplan                      # scratch; mkdir -p "$SCR"
  export HELAO_SOURCES_ROOT=$SCR/sources
  export PYTHONPATH=$REPO
  ```
  - Run one pytest file per process: `$PY -m pytest -q -p no:cacheprovider <file>`. Or
    `$PY run_tests.py --filter <substr>`; the filter is a plain path substring, so anchor it (`--filter /test_driver_`).
  - **Never `conda run ... <<EOF`.** It drops stdin and runs nothing. Put scratch Python in a file under `$SCR` and run
    `$PY $SCR/<file>.py`.
  - **The tool shell is zsh.** `grep` there is a snapshot shell function and `ls` is aliased to `exa`. Run every grep
    sweep, `ls` and glob loop inside `bash -c '...'`. Use `grep -rn` through Bash, not the Grep tool: the Grep tool
    honours `.gitignore` and cannot see the nested repos.
  - The repo root holds a stray runtime directory `C:/INST_hlo/` (a Windows `root:` used on Linux). Exclude it from
    every sweep; it is not source.
- **The whole-tree grep recipe.** Every deletion is re-verified with it, nested repos and configs included:
  ```
  bash -c 'grep -rnE "<pattern>" '"$REPO"' \
      --include="*.py" --include="*.yml" --include="*.yaml" --include="*.json" --include="*.md" --include="*.toml" \
    | grep -v "/\.ua/\|/\.omc/\|/\.claude/\|/\.git/\|/\.superpowers/\|__pycache__\|/docs/\|/C:/INST_hlo/"'
  ```
  Zero hits outside the files the step names is the pass condition. Hits under `docs/` are history and stay.
- **Launches (main session only).** A subagent's background launch is reaped when it goes idle.
  - `/mnt/STORAGE` is mounted `noexec`: launch with `bash ./helao.sh <prefix>`, never `./helao.sh`.
  - `export PYTHONPATH=$REPO` first; the launcher refuses to start without it.
  - Run under a pty and keep the wrapper's PID:
    `tail -f /dev/null | script -qfec "bash ./helao.sh goldenhex --no-hot-reload" $SCR/<name>.log & SPID=$!`
  - **Stop by PID, never by pattern.** Do not use `pkill -f` / `pgrep -f`: the calling shell's own command line contains
    the pattern. Task 0 writes `$SCR/stop_launch.sh <SPID>`: it walks the descendants of `SPID` through
    `/proc/<pid>/task/*/children`, picks the one whose `/proc/<pid>/cmdline` contains `launch.py`, sends it SIGTERM
    (a graceful CTRL-x), and waits until `<root>/STATES/pids_<prefix>_*.pck` is gone.
- **Background sweeps.** An implementer is not woken by its own background job. When it starts a `run_tests.py` sweep
  in the background, it reports the log path to the main session **immediately**, then continues or ends its turn. The
  main session polls the log.
- **Formatting.** The main session runs `black` on the changed files immediately before each commit, in the repo that
  owns them. The `force-exclude` for the native `sync_driver.py` stays as the completion plan left it.
- **Pyright.** `$REPO/pyrightconfig.json` is authoritative. For each changed `.py` file run
  `$HELAO_ENV/bin/pyright --outputjson <files>` **on the real path** (never under `.claude/worktrees/`, where it
  analyses zero files and reports zero errors). Report `summary.filesAnalyzed` next to `summary.errorCount`.
  `filesAnalyzed` must be > 0, and neither count may be worse than its Task 0 value for the same files.
- **Every new test has a mutation check.** Mutate, watch it go red; restore, watch it go green. Both outcomes go in the
  task report. Never mutate by executing code that defaults to a production path; nothing here does.
- **Anchor on symbols and text, never on line numbers.** Line numbers below are as measured at Task 0's predecessor
  state and are hints only. `finalizer.py`, `data_stream.py`, `action_session.py` and `ports/action_session.py` were
  being edited by Task 4b while this plan was written; Task 0 re-measures every symbol this plan names in them.

---

## 1. Measured facts this plan rests on (2026-10-19, branch head `65faced6` with Task 4b in the working tree; 4b has since landed as `9f032f82`)

The spec was measured at `ba910c4c`. Everything below was re-measured on the current tree, tests excluded unless a fact
is about tests. Task 0 re-runs the measurements at the post-4b head and stops on any drift.

**M1. The slots.** `build_wiring` (`app/factory.py`) assigns `data_sink=NativeDataSinkAdapter()` and nothing reads
`wiring.data_sink`. `hardware`, `sample_state` and `ui_host` are never assigned and never read. `"data_sink"` is in
`ACTION_REQUIRED` (`app/wiring.py`).

**M2. The deletion targets have no production caller.** Whole-tree grep, nested repos included:
- `HardwarePort`, `ExclusiveAccess`, `driver_response_to_error_code` (`ports/hardware.py`): only `wiring.py`,
  `test_ports_import.py`, `test_adapters_misc.py`, `test_hardware_import_sweep.py`, `test_galil_hardware_adapter.py`,
  and docstrings in `adapters/native/galil_motion.py`.
- `LegacyDriverHardwareAdapter` (`adapters/shared/hardware.py`, the module's only class): `test_adapters_misc.py`,
  `test_hardware_import_sweep.py`.
- `GalilMotionHardwareAdapter` (`adapters/native/galil_motion.py`, the module's only class): its test file, plus a
  docstring mention in `adapters/native/galil_motion_native.py`.
- `NativeDataSinkAdapter` (`adapters/native/data_sink.py`): `adapters/native/__init__.py`, `app/factory.py`,
  `test_factory.py`, `test_native_data_sink.py`. `.for_action(` has no other caller (`adapters/native/artifact_store.py` has its own live `for_action`, which stays).
- `ActiveDataSinkAdapter` (`adapters/shared/data_sink.py`): only `test_adapters_data.py`, which tests nothing else.
- `build_ui_app`: `ports/ui_host.py`, `app/ui_host.py` (raises `HexagonDeferred`), `test_app_ui_host.py`,
  `test_ui_host_port.py`.
- `enqueue_data_dflt` is called by endpoint code everywhere (hte, test and every nested repo), always on the session.
  Only its **port** declaration goes.
- `put_lbuf_nowait` has real callers on the **host** (`orch_dispatch.py`, `ActionHost.put_lbuf_nowait`, both member
  checklists). Only its port declaration and its two adapter bodies go.

**M3. Eight drivers connect in `__init__` — and a ninth the spec missed.** AST scan of `helao/deploy/hte/drivers` for a
`connect` call inside `__init__`:
- the spec's eight: `AliCatMFC`, `KinesisMotor`, `GamryDriver`, `KDS100`, `SIMDOS`, `CM0134`, `SprintIR`,
  `MeerstetterTEC`;
- **`LeancatDriver`** (`drivers/test_station/leancat/driver.py`): `__init__` imports the vendor `leancat_helao`,
  reads a JSON file, builds `Station(...)` and calls `self.station.connect()`. The spec's Q5 lists leancat as lazy;
  that is wrong (A1).

**M4. Seven servers call `app.driver.connect()` in `dyn_endpoints`:** `spec_server`, `andor_server`, `biologic_server`,
`nidaqmx_server`, `galil_motion`, `galil_io`, `gamry_server2`. `power_supply_server` connects per action, in 3
executors.

**M4b. An eighth startup connect: `xafs_server`.** Its `dyn_endpoints` does
`connect_resp = await asyncio.to_thread(app.driver.connect)`: connecting may spawn the sidecar and wait for it, so it
runs off the loop on purpose. `XafsSidecarDriver` is on the lazy list (user decision 5) and **is not flipped**: a host
connect is synchronous on the loop and would block it for the sidecar's start-up.

**M5. `dyn_endpoints` runs as a task, after the startup event returns.** `EndpointManager.dyn_endpoints_init` does
`asyncio.ensure_future(self.init_endpoint_status(self.host._dyn_endpoints))` and logs a failure through
`_log_init_failure`. So today:
- the 7 `dyn_endpoints` connects run after `startup_event` has returned, i.e. after uvicorn's lifespan startup;
- an exception from one of them is logged at ERROR ("endpoint status init failed") and the server **stays up**,
  without the routes registered after the connect line and without endpoint-status registration;
- a constructor connect, by contrast, runs inside `startup_event`, and its exception aborts startup;
- the time until the server first answers a request is the same either way (review measurement). The `dyn_endpoints`
  task runs at the first yield after lifespan startup, while uvicorn is still creating its server, and its synchronous
  connect blocks the loop before any request is served;
- the galil_io and nidaqmx pollers are built in `startup_event`, so today their first `get_data()` runs **before** the
  `dyn_endpoints` connect. If that first call raises, PRE logs a "`get_data()` raised" line at startup. After I6c/I6e
  the host connects before it builds the poller, so a line PRE logged disappears. This is unmeasured:
  `cNIMAXPoller` short-circuits while `task_monitors is None`, so NI-DAQmx may never have logged it.

**M6. Which `connect()` bodies can raise** (AST: statements not inside a `try` with a broad handler):
`GamryDriver` (`import comtypes.client`), `GamryComAdapter` (thread construct + factory call), io `Galil`
(`import gclib`), `cNIMAX` (`_load_nidaqmx()`), `NativeGalilMotion` (a `try` with a narrow handler), `SM303`
(a path check before its `try`), `BiologicDriver` (statements around its `try`), `MeerstetterTEC` (a retry loop).
On a station the vendor packages exist, so these raise only on genuinely unexpected errors. On Linux they raise on the
missing import.

**M7. Andor needs its `server_key` before `connect()`.** `andor_server`'s `dyn_endpoints` sets
`app.driver.server_key = server_key` and `app.driver._base_hook = app`, *then* connects. The calibrated variant's
`connect()` reads `calibration_file()`, which builds `<STATES>/<host>_<server_key>_andor_wl_calib.json`. A host connect
that runs before `dyn_endpoints` would read the class default `"ANDOR"`. `ActionHost.server_key` equals
`app.server.server_name` (`MachineModel(server_name=server_key, ...)` in `action_host.py`).

**M8. Gamry connects twice only in Deployment-A.** hte's `gamry_server2` hosts `GamryComAdapter`, which is
disconnected-construct; its `connect()` builds `GamryDriver` on the COM thread, and `GamryDriver.__init__` connects.
That is one connect. Deployment-A's `potentiostat_server` hosts `GamryDriver` directly **and** reuses hte's
`gamry_dyn_endpoints`, so there the constructor connects and then `dyn_endpoints` connects again.

**M9. `estop`/`stop` shapes hold.** hte: 12 `estop` methods, all `async`; 28 `stop` methods, 4 `async`
(`cNIMAX`, motion `Galil`, `GamryDriver`, `ReadZ`).

**M10. The host surface read from hardware-side classes.** AST scan of every class deriving transitively from
`HelaoDriver`, `DriverPoller` or `Executor` in hte, `hexagon/adapters/native` and `core/drivers`, counting `.base.X`,
`._base_hook.X` and `getattr(<…_base_hook…>, "X")`:
- 30 reads in 15 files, plus `DriverPoller`'s own `await self._base_hook.put_lbuf(...)`: **31 reads, 16 files**;
- the same **9 members** the spec lists: `get_lbuf` 12, `helaodirs` 6, `actionservermodel` 4, `server_params` 3,
  `put_lbuf` 2, `dflt_file_conn_key` 1, `world_cfg` 1, `executors` 1, `poller` 1;
- apart from the first argument of `getattr`/`hasattr` (5 sites today: nidaqmx, motion `Galil` ×2,
  `NativeGalilMotion` ×2; after I6b, also D9's line in Andor's `connect`), no in-scope class hands
  `.base` or `._base_hook` whole to a call; `kinesis_server`'s `KinesisMotorExec` aliases
  `self.base = self.active.base`, and its reads go through `self.base.X`, which the scan counts;
- every member exists on `ActionHost` (`server_params` through its config mixin; `poller` and `server_key` are plain
  instance attributes).

**M11. Class counts.** In-scope classes: 28 `HelaoDriver` subclasses (26 hte + `NativeGalilMotion`, `GamryComAdapter`),
10 `DriverPoller` subclasses, 32 hte `Executor` subclasses: 70, not the spec's 64. Not load-bearing: the gate's allowed
set is a member set, not a class count.

**M12. Station configs** (`helao/deploy/hte/configs/*.yml`, `fast:` module → config:key):
- `co2sensor_server` (SprintIR): `ccsi2:CO2SENSOR`. `o2sensor_server` (CM0134): none. **`tec_server`
  (MeerstetterTEC): none, in any repo.** `diapump_server` (SIMDOS): `ccsi2`. `syringe_server` (KDS100): `ccsi2`,
  `clad`, `adss3`. `mfc_server` (AliCat): `ccsi2`, `ecms3`. `kinesis_server`: `eche10`, `hispec`.
- `spec_server` (SM303): `eche10:SPEC_T`. `andor_server`: `hispec`. `galil_io`: `anec`, `eche10`, `hispec`.
  `biologic_server`: `biologiceclib2` (eclib2), `biologicole` (olecom), `hispec:PSTAT` (default eclib). **`clad` has no
  BioLogic.** `nidaqmx_server`: `adss3`, `anec`, `ccsi2`, `clad`, `ecms3`. `galil_motion`: `adss3`, `anec`, `clad`,
  `eche10`, `hispec`. `gamry_server2`: `adss3`, `anec`, `clad`, `eche10`, `ecms3`. `power_supply_server`: none.

**M13. Nested repos (rule R4).** No nested server calls `connect()` on an hte driver class itself. What they do:
- Deployment-A: `potentiostat_server` hosts `GamryDriver` and reuses `gamry_dyn_endpoints` (M8);
  `io_server` is a thin wrapper over hte's `nidaqmx_server.makeApp`; a test stubs `gamry_dyn_endpoints`' driver with a
  `connect=lambda: None`.
- Deployment-B: 2 configs name `gamry_server2` with no local module, so they resolve to hte's.
- Deployment-C: 1 config each names `galil_io`, `galil_motion`, `spec_server` with no local module (resolve to hte).
- Deployment-E: 1 config pins `deployment: hte` for `andor_server`, `biologic_server`, `galil_io`, `galil_motion`,
  `kinesis_server`; a test imports `AndorCalibratedDriver` and `andor_server._driver_class`.
- So no nested-repo code change is expected. Each increment still runs the nested tests that reference its classes.

**M14. Private `HelaoDriver` subclasses are hosted by `ActionHost` too.** About a dozen classes across Deployment-A/B/E.
After I0 the host sets `_base_hook` on them as well (spec: "HelaoDriver instances only"). Measured:
- all their `_base_hook` reads are in **pollers**, which are already hooked;
- one Deployment-B test asserts a driver has no `_base_hook`, but it constructs the driver directly, not through a
  host, so it is unaffected.

**M15. Tests that depend on today's connect placement.**
- Constructor connect pinned or relied on: `hte/tests/test_poller_drivers_connect_in_init.py` (CM0134, TEC),
  `test_simdos_connect_in_init.py`, `test_low_w3_hte_fixes.py` (KinesisMotor, SIMDOS), `test_kinesis_counts.py`,
  `test_kinesis_estop.py`, `test_motion_private_endpoints.py`, and the `xfail` in
  `hexagon/tests/test_hardware_import_sweep.py`.
- `dyn_endpoints` called by tests, possibly relying on its connect side effect: `test_andor_server_composition.py`
  (`_started_app`, pins `app.driver.server_key` and `app.driver._base_hook is app`),
  `test_andor_disconnected_construct.py`, `test_biologic_backend_select.py`, `test_biologic_new_endpoints.py`,
  `test_digital_out_private_endpoints.py`, `test_motion_private_endpoints.py`, `test_kinesis_estop.py`,
  `test_med_servers_fixes.py`, `test_xafs_server.py`, the smoke `golden_capture_galil*.py`, and Deployment-A's
  `test_p4b_gamry_overlay.py`.

**M16. 13 test files, plus `app/factory.py`, pass `data_sink=` to `PortWiring`.** One of them,
`helao/core/tests/unit_test_config_seam.py`, is in `run_unit_tests.py`'s gate. Find them with the recipe and pattern
`\bdata_sink=`. Removing the field turns each into a `TypeError`.

**M16b. Tests that drive a `dyn_endpoints` with a fake app relied on the server-side `_base_hook` assignment** that I0
deletes: `test_motion_private_endpoints.py`, `test_andor_acquire_guard.py` and the smoke `test_golden_capture_galil*.py`
(review finding). The host sets `_base_hook` now; a fake app that bypasses the host does not.

**M17. No test pins the server-side `"... connect() returned status=..."` log lines.** Whole-tree grep for
`connect\(\) returned` hits only the 7 server modules.

**M18. The action golden master.** `helao/core/tests/test_active_golden_master.py`:
- 13 scenarios in `SCENARIOS`; references in `helao/core/tests/golden/action/`;
- `--freeze` refuses a non-empty reference directory; `--check` reports a scenario with no reference as `MISSING`;
- `_make_host` sets `host.aloop = asyncio.get_running_loop()`; `_RecordingMSQ` subclasses `MultisubscriberQueue` and
  overrides `put` and `put_nowait`.

**M19. `NativeDataStreamer.enqueue_data_nowait`** builds the package on the calling thread (`_build_data_package`
reads `self.active.action` when `action is None`), then calls `self.active.base.data_q.put_nowait(msg)` and bumps
`num_data_queued`, all on the calling thread.

**M19b. Nothing yields between the end of an executor and the drain marker** (review finding). `executor_runner.py`
(the block after the poll loop): `await executor._post_exec()` (where NI-DAQmx stops its task), then an on-loop
`enqueue_data_nowait` of the cleanup data, then `executors.pop`, then `await self.active.finish()`, which reaches
`NativeDataStreamer.drain`'s marker put. A cross-thread put scheduled with `call_soon_threadsafe` while `_post_exec`
was stopping the NI task can therefore still be waiting in the loop's ready queue when the marker is put, and the
logger drops it (late data after the marker). The on-loop cleanup row would also jump ahead of it. Task 4b's
`9f032f82` and the pending fix rework `drain` (per-call waiters, a skip-when-never-streamed guard): anchor on the
symbol and on "the first marker put", not on its body.

**M20. Boundaries.** `test_boundaries.py` lets `ports/` import stdlib, `helao.hexagon.domain.*`,
`helao.hexagon.ports.*` and `helao.core.drivers.helao_driver`. `DriverPoller._base_hook` is typed `Any` today to avoid
a core→hexagon import cycle.

**M21. The Reflex bundle stamp hashes imported `helao/` modules**, including `ports/hardware.py` and
`ports/data_sink.py`. A changed module rebuilds the bundle on the next launch; nothing refuses.

**M22. Disconnected-construct probe (review scratch `probe2.py`).**
- `LeancatDriver`'s module cannot be imported on Linux, so a runtime tripwire can never classify it.
- `MeerstetterTEC` raises `KeyError: 'channel'` on its minimal config, and `XafsSidecarDriver` raises `InvalidURL`.
  Both need a config override.
- The vendor objects that matter are **module-level bound names** (`Thorlabs` from pylablib in `kinesis_driver`,
  `MeCom` in `mecom_driver`, `serial`, `nidaqmx`). A `sys.modules` sentinel installed after import cannot reach them.
- Most `connect()` bodies swallow exceptions, so a tripwire that only raises is invisible. The test has to record
  each hit.
- Two hte classes are named `Galil` (`io.galil_io_driver`, `motion.galil_motion_driver`), so class names are not
  unique keys.

---

## 2. Spec amendments (corrections this plan applies; recorded in the amendment file in Task 1)

**A1. A ninth constructor connect: `LeancatDriver`** (M3). It has no hte station config and is used by a private
deployment. Under user decision 5 it does not opt in, so this plan does not flip it. It stays in
`CONSTRUCTOR_CONNECT_PENDING` with a comment naming why. **The ratchet ends at `{LeancatDriver}`, not empty.** See Q3.

**A2. Gamry's double connect is a Deployment-A effect** (M8). I7 still removes it. In hte, I7 must also make
`GamryComAdapter.connect()` call the wrapped driver's `connect()` on the COM thread, because `GamryDriver.__init__` no
longer does.

**A3. Replaced by user decision Q4: a host-managed `connect()` that raises does not stop startup.** The spec says the
exception propagates and that this "matches both connect sites it replaces". That holds for the constructor sites
only (M5). The host instead catches any `Exception` from a host-managed `connect()`, logs it at ERROR with the
traceback, raises an alert through the existing `LOGGER.alert` path, and continues startup with the driver
disconnected. The poller and `dyn_endpoints` still run (D3). What changes, per kind of driver:
- **Formerly constructor-connect drivers (I1–I5, `GamryDriver` in I7).** Today a `connect()` that raises inside
  `__init__` aborts startup, and the server process never serves. After the flip the server starts, logs ERROR and
  alerts. Its poller polls a disconnected driver, and its action routes behave the way they do today when the device
  is absent and `connect()` returned a failed response. Raise-capable bodies among these (M6): `GamryDriver` (a
  missing `comtypes`) and `MeerstetterTEC` (its retry loop). Other constructor code that raises still aborts startup;
  only the `connect()` call is caught.
- **Formerly `dyn_endpoints`-connect servers (I6a–f, `GamryComAdapter` in I7).** Today a raising connect aborts the
  `dyn_endpoints` task: the error is logged, and the late routes and endpoint status are never registered. After the
  flip `dyn_endpoints` runs in full against a disconnected driver. The route set is the one a failed-but-not-raising
  connect produces today (`galil_enabled` gates still apply). Gamry and BioLogic wait on `ready` forever, logging
  "waiting for ... init" each second, exactly as they do today after a failed connect that returns normally.
- The host-order test pins this behaviour (Task 1b test 3), and station check 7 compares it against a PRE run with
  the device unplugged.

**A4. Withdrawn.** It claimed the I6/I7 servers bind later. They do not: the `dyn_endpoints` task's synchronous connect
already blocks the loop before the first request is served (M5). The time until the server first answers a request is
unchanged, so the old Q5 is moot.

**A5. `DriverHostPort` gains a tenth member, `server_key: str`** (M7). It is how the Andor driver learns its key before
the host's connect (D9, user decision Q1).

**A6. Stations.** I2 (MeerstetterTEC) has no config in any repo: it is Linux-only, like CM0134. I6d's BioLogic
stations are `hispec` (eclib), `biologiceclib2` and `biologicole`; `clad` has none (M12).

**A7. Counts.** 31 host reads in 16 files once `DriverPoller` itself is counted; `helaodirs` is read 6 times, not 7;
70 in-scope classes, not 64 (M10, M11). The member set, which is what the gate uses, is unchanged.

**A8. `test_hardware_import_sweep.py` is deleted in I0**, because it imports `LegacyDriverHardwareAdapter` and its
module lists are superseded by the new construct test. Its kinesis `xfail` goes with it. The spec's I5 "the `xfail`
becomes a pass" is realised as removing `KinesisMotor` from `CONSTRUCTOR_CONNECT_PENDING`.

**A9. The marshalling fix marshals the put, not the whole call, keeps FIFO order, and is flushed before the drain
marker** (M19, M19b).
- The package is still built on the calling thread, so a row keeps the action that was current when the hardware
  produced it.
- A foreign thread appends `(msg, has_data)` to a thread-safe pending deque and schedules a flush on `host.aloop`
  with `call_soon_threadsafe`.
- Every on-loop `enqueue_data_nowait` and `enqueue_data` flushes the deque before its own put, so rows reach the queue
  in the order they were produced.
- `NativeDataStreamer.drain` flushes the deque as its unconditional first statement, ahead of any guard and of the
  first marker put, so no cross-thread row can land behind the marker or be skipped by the guard.
- The condition is "the running loop on this thread is not `host.aloop`", not "there is no running loop", which also
  covers a foreign thread that runs its own loop.
- If the loop is closed (`call_soon_threadsafe` raises `RuntimeError`), the row is dropped and a WARNING is logged
  once per streamer.
- Q2.

**A10. `put_lbuf_nowait` is a live host member** (M2). Only the port declaration and the adapter bodies are deleted.

**A11. The AST gate also forbids handing the host off whole.** An in-scope class passing a bare `<x>.base` or
`<x>._base_hook` as a call argument fails the gate. The first argument of `getattr`/`hasattr` is exempt, because the
member rule already judges the literal name there. Measured zero violations today (M10), so the gate is green on day 1
and closes the one hole the member rule leaves.

**A12. Eight startup connects, not seven.** `xafs_server` connects off-loop in its `dyn_endpoints` (M4b) and stays as
it is.

**A13. Log lines (user decision Q7).** Seven server-side `"<X> connect() returned status=..."` INFO lines become one
host line per host-managed connect, `"<Class>.connect() at startup: response=... status=..."`. Constructor-connect
drivers gain that line. A raising connect logs `"<Class>.connect() at startup raised; continuing with the driver
disconnected"` at ERROR, plus an alert. No test pins any of these texts (M17).

---

## 3. Decisions this plan makes

**D1. Commits.** I0 lands as two code commits plus one docs commit (Task 1). Each later increment is one parent commit
(R1). A nested-repo commit happens only if a nested test needs a fix, and then in that repo, separately.

**D2. The host sets `_base_hook` on every `HelaoDriver` instance**, as the spec says, immediately after construction.
The three server-side assignments (`andor_server`, `galil_motion`, `nidaqmx_server`) are deleted in I0: they become
redundant, because the host has already set the same object before `dyn_endpoints` runs. The alternative (only
classes that declare `_base_hook`) is Q6.

**D3. The host's connect step and its log line.** Inside the `issubclass(driver_class, HelaoDriver)` branch of
`ActionHost._register_lifecycle_hooks.startup_event`:
```python
inst = driver_class(config=self.server_params)
inst._base_hook = self
if driver_class.connect_on_startup:
    name = driver_class.__name__
    try:
        resp = inst.connect()
    except Exception as exc:  # user decision Q4: start with the driver disconnected
        LOGGER.error(
            f"{name}.connect() at startup raised; continuing with the driver disconnected",
            exc_info=True,
        )
        LOGGER.alert(f"{self.server_key}: {name}.connect() at startup raised {exc!r}")
    else:
        LOGGER.info(
            f"{name}.connect() at startup: "
            f"response={getattr(resp, 'response', None)} status={getattr(resp, 'status', None)}"
        )
```
- Then the existing poller block, unchanged; it runs whether or not the connect succeeded.
- Only `Exception` is caught. `KeyboardInterrupt`/`SystemExit` still propagate.
- `LOGGER.alert` is the existing alert path (`helao_logging.alert`; the host's `/test_alert` route uses it).
- The server-side `LOGGER.info(f"... connect() returned status=...")` lines go with the connect calls they report
  (A13).

**D4. Two exact sets in the construct test, keyed by `"<module>.<qualname>"`** (M22: two classes are named `Galil`),
with the module relative to `helao.deploy.hte.drivers` or `helao.hexagon.adapters.native`, e.g.
`"sensor.sprintir_driver.SprintIR"`.
- `CONSTRUCTOR_CONNECT_PENDING`: the classes whose `__init__` still connects. It is checked **by AST**, the M3 scan:
  every in-scope `HelaoDriver` subclass whose `__init__` calls `connect` on `self` or on an attribute of `self`. That
  set must equal the constant exactly. The AST check is what lets `LeancatDriver` stay listed, since its module cannot
  be imported on Linux (M22). It starts with the spec's 8 plus `LeancatDriver` (A1).
- **The runtime tripwire judges only the other direction:** every importable class not in the pending set constructs
  with zero recorded hits and no exception.
- `CONNECT_ON_STARTUP`: the classes whose `connect_on_startup` is `True`, found by scanning every importable
  in-scope `HelaoDriver` subclass. The scan must equal the constant exactly. It starts empty.
- Each increment moves its classes out of the first set and into the second. Forgetting either half goes red.

**D5. Scenario 14 is added, never re-frozen.** The existing 13 references are not touched. Scenario 14's two reference
files are written once, at I0, from the code *before* the marshalling fix, by a scratch script that calls the module's
own `_capture_scenario` for that one scenario. `--check` then covers 14 scenarios.

**D6. Tests that relied on the old connect placement, or on the old `_base_hook` placement, are retargeted, not
weakened.** Each one makes the call the host now makes, at the point where the host makes it. Assertions stay as they
are.
- A test that constructed a driver and relied on the constructor connect calls `drv.connect()` after construction.
- A test that drove `dyn_endpoints` and relied on its connect calls `app.driver.connect()` before `dyn_endpoints`.
- A test that drives the galil_motion, nidaqmx or andor `dyn_endpoints` with a fake app and relied on the server-side
  `_base_hook` assignment (M16b) sets `app.driver._base_hook = app` itself, before calling `dyn_endpoints`.
- The implementer names every retargeted test in the task report, with the one line it added.

**D7. Typing `_base_hook` without an import cycle.** `DriverHostPort` lives in `ports/hardware.py`, which after I0
contains nothing else. In `helao/core/drivers/helao_driver.py`, import it under `typing.TYPE_CHECKING` only and annotate
`_base_hook: "Optional[DriverHostPort]"`. `ports/hardware.py` may import `helao.core.drivers.helao_driver` for
`DriverPoller` (allowed by M20); with the guard there is no runtime cycle.

**D8. How the construct test runs, and it never writes outside `tmp_path`.**
- **Order:** import every in-scope module first, with no tripwire, and record the modules that fail to import (with
  their exception). Then install the tripwire.
- **The tripwire records; it does not just raise.** Each patched callable appends `(what, class_under_test)` to a hit
  list and then raises `TripwireHit`. A class is judged by the hit list, never by whether an exception escaped, since
  most `connect()` bodies swallow exceptions (M22). Patch:
  - `socket.socket.connect`, `subprocess.Popen`, `ctypes.CDLL` and `ctypes.WinDLL` (when present);
  - `serial.Serial` **and** every in-scope module's own bound vendor names, replaced in that module's namespace:
    `serial`, `Serial`, `Thorlabs` (`kinesis_driver`), `MeCom` (`mecom_driver`), `nidaqmx`, `minimalmodbus`,
    `gclib`, `comtypes`, and `pylablib`. Find them by scanning each module's globals for objects whose `__module__`
    or `__name__` starts with one of those package names. **Patch only modules and callables that are not
    `BaseException` subclasses.** Vendor exception classes, such as mecom's `ResponseException`, `WrongChecksum` and
    `ResponseTimeout`, appear in `except` clauses; replacing them would break those clauses rather than detect I/O;
  - `sys.modules` sentinels for the same packages, for imports done lazily inside a method.
- **The classifier is a function**, `classify(cls, config) -> (hits, exc)`, so mutation checks can feed it a scratch
  class.
- **Configs.** Minimal configs come from the first hte config whose `servers.<k>.fast` hosts the class, else `{}`. Any
  string value that looks like a path (contains `:\` or starts with `/`) is replaced by a subdirectory of `tmp_path`.
  The config's `root:` is never used. Two overrides are settled in advance (M22), each with a one-line comment:
  `MeerstetterTEC` gets `channel` (and a `port`), and `XafsSidecarDriver` gets a well-formed local URL that is never
  contacted. Any further override needs the main session's agreement (Task 0 Step 6).
- **Writes.** The test snapshots `$REPO`'s top-level entries before and after, and fails on any new one. That is how
  `C:/INST_hlo/` got there.

**D9. Andor's key comes from the host (user decision Q1, review fix 7).** The first statement of `AndorDriver.connect()`,
before its `try`, is:
```python
self.server_key = getattr(self._base_hook, "server_key", None) or self.server_key
```
- `calibration_file()` keeps reading `self.server_key`.
- The server-side `app.driver.server_key = server_key` stays. It runs after the host connect now and assigns the same
  value; `test_andor_server_composition.py` reads it.
- The calibration file name is unchanged on every station, because `host.server_key` equals the value the server
  assigns (M7).

**D10. The marshalling fix** (I6e, A9), in `NativeDataStreamer`:
```python
# __init__: self._xthread = collections.deque(); self._closed_warned = False

def _put_queued(self, msg, has_data) -> None:  # loop thread only: today's two statements
    self.active.base.data_q.put_nowait(msg)
    if has_data:
        self.active.num_data_queued += 1

def _flush_xthread(self) -> None:  # loop thread only: FIFO by production order
    while self._xthread:
        self._put_queued(*self._xthread.popleft())

def enqueue_data_nowait(self, datamodel, action=None):
    msg, has_data = self.active._build_data_package(datamodel, action)  # calling thread, as today
    aloop = getattr(self.active.base, "aloop", None)
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if aloop is not None and running is not aloop:  # foreign thread
        if aloop.is_closed():  # nothing will ever flush: drop, do not grow the deque
            self._warn_closed()
            return
        self._xthread.append((msg, has_data))  # deque.append is thread-safe
        try:
            aloop.call_soon_threadsafe(self._flush_xthread)
        except RuntimeError:  # closed between the check and the call
            self._xthread.clear()
            self._warn_closed()
        return
    self._flush_xthread()
    self._put_queued(msg, has_data)

def _warn_closed(self) -> None:
    if not self._closed_warned:
        self._closed_warned = True
        LOGGER.warning("enqueue_data_nowait after the loop closed; rows dropped")
```
- `enqueue_data` (async, on the loop) calls `self._flush_xthread()` before its own put.
- **`drain`'s first statement, unconditionally, is `self._flush_xthread()`.** It comes before the skip-when-never-streamed
  guard of the completion branch's pending fix and before the first marker put (M19b). The guard reads
  `num_data_queued`, which stays 0 until the flush runs, so a flush placed after the guard would skip the drain and
  lose every cross-thread row. This is review fix 1 in deterministic form (Q10, accepted); see Task 7e.
- A host with no loop yet (`aloop is None`, unit tests) keeps today's direct path, plus the no-op flush.

---

## 4. File map

**Task 0:** scratch only (`$SCR/H0/*`, `$SCR/stop_launch.sh`, `$SCR/probe_construct.py`).

**Task 1 / I0a (deletions and the DataSinkPort trim)**
- Delete: `helao/hexagon/adapters/shared/hardware.py`, `helao/hexagon/adapters/shared/data_sink.py`,
  `helao/hexagon/adapters/native/data_sink.py`, `helao/hexagon/adapters/native/galil_motion.py`.
- Delete tests: `helao/hexagon/tests/{test_galil_hardware_adapter,test_native_data_sink,test_adapters_data,test_hardware_import_sweep}.py`.
- Edit: `helao/hexagon/ports/{hardware,data_sink,ui_host}.py`, `helao/hexagon/app/{wiring,factory,ui_host}.py`,
  `helao/hexagon/adapters/native/{__init__,galil_motion_native}.py`, `helao/hexagon/adapters/fakes/__init__.py`,
  `helao/deploy/hte/drivers/robot/pal_driver.py` (`_PALActiveContext` only).
- Edit tests: `test_adapters_misc.py`, `test_factory.py`, `test_wiring.py`, `test_ports_import.py`, `test_fakes.py`,
  `test_app_ui_host.py`, `test_ui_host_port.py`, and the 13 `data_sink=` test files (M16).
- New: `helao/hexagon/tests/test_data_sink_port_surface.py`.

**Task 1 / I0b (host lifecycle and gates)**
- `helao/core/drivers/helao_driver.py`, `helao/hexagon/ports/hardware.py` (`DriverHostPort`),
  `helao/hexagon/app/action_host.py`, `helao/hexagon/app/action_session.py` (annotation only),
  `helao/deploy/hte/drivers/{io/nidaqmx_driver,motion/galil_motion_driver,spec/andor/driver,pump/simdos_driver}.py`
  and `helao/hexagon/adapters/native/galil_motion_native.py` (annotations only),
  `helao/deploy/hte/servers/action/{andor_server,galil_motion,nidaqmx_server}.py` (delete the `_base_hook` line only).
- `helao/core/tests/test_active_golden_master.py` (scenario 14, `_RecordingMSQ.put_threads`) and two new files in
  `helao/core/tests/golden/action/`.
- New: `helao/hexagon/tests/{test_driver_host_surface,test_driver_disconnected_construct,test_host_driver_lifecycle}.py`.

**Task 1 / docs:** new `docs/superpowers/specs/2026-10-19-hexagonal-rewrite-amendment-3.md`; the root `CLAUDE.md`
"Conventions worth knowing" driver bullet.

**Tasks 2–8 (I1..I7):** the driver and server files named in each task, the construct test's two sets, and the tests
M15 names for that family.

---

## Task 0 — Baselines (no code change, no commit)

**Precondition:** Task 4b (`9f032f82`) **and** the completion branch's pending `drain` fix are committed. The only
tracked modification allowed is `docs/superpowers/plans/2026-10-19-hexagon-completion.md` (a docs edit the main session
commits separately); this plan's own file may be untracked.

- [ ] **Step 1: Record the state.**
  ```
  mkdir -p $SCR/H0
  git -C $REPO status --short --branch          # "## feat/hexagon-completion"; at most the two docs files above
  git -C $REPO rev-parse HEAD                   # record as BASE
  bash -c 'for d in '"$REPO"'/helao/deploy/*/; do [ -d "$d/.git" ] && echo "$d $(git -C $d rev-parse --short HEAD) $(git -C $d status --short | wc -l)"; done' > $SCR/H0/nested_heads.txt
  ```
  Every nested repo must be clean. If one is not, stop and report.
- [ ] **Step 2: Write `$SCR/stop_launch.sh`** as §0 describes. Test it once on a `goldenhex` launch: the launcher exits
  and the pid file clears.
- [ ] **Step 3: Full sweep H0** (background; report the log path to the main session at once):
  ```
  cd $REPO && $PY run_tests.py > $SCR/H0/run_tests.log 2>&1
  bash -c "grep -E '^  (PASS|FAIL|ENV|TIMEOUT|NOTESTS|NOTATEST) ' $SCR/H0/run_tests.log | awk '{print \$2, \$1}' | sort > $SCR/H0/verdicts.txt"
  bash -c "awk '\$2==\"FAIL\"||\$2==\"TIMEOUT\"{print \$1}' $SCR/H0/verdicts.txt > $SCR/H0/failset.txt"
  bash -c "comm -3 /tmp/claude-1000/hexplan/F0/failset.txt $SCR/H0/failset.txt" > $SCR/H0/failset_vs_F0.txt
  ```
  Also `cd $REPO && $PY run_unit_tests.py > $SCR/H0/unit.log 2>&1; echo rc=$?`.
  Report `failset_vs_F0.txt` (the completion plan's F0 set had 21 files). Every later gate compares against
  `$SCR/H0/failset.txt`, not F0.
- [ ] **Step 4: Golden masters.** Both must PASS; save to `$SCR/H0/gm_action.txt`, `$SCR/H0/gm_dispatch.txt`:
  ```
  cd $REPO && $PY helao/core/tests/test_active_golden_master.py --check
  cd $REPO && $PY helao/core/tests/test_orch_dispatch_golden_master.py --check
  ```
- [ ] **Step 5: Re-measure §1.** Write each scan as a script under `$SCR` and save its output in `$SCR/H0/`:
  - M2's deletion greps (recipe, one pattern per symbol): no production hit beyond the files listed;
  - M3: the constructor-connect AST scan → exactly the 9 classes;
  - M4: `app\.driver\.connect\(` in hte servers → exactly the 7 sites, plus power_supply's 3 `self.driver.connect()`;
  - M10: the host-read AST scan → the 9-member set, and zero bare `.base` / `._base_hook` call arguments in in-scope
    classes;
  - M15/M16: the test lists;
  - the Task-4b symbols this plan touches exist: `NativeDataStreamer.enqueue_data_nowait`,
    `NativeDataStreamer.enqueue_data`, `NativeDataStreamer._build_data_package`, `NativeDataStreamer.drain` (and where
    its first marker put is, after the pending fix), `ActionSession.finish_hlo_header`, `ActionSession.drain_data`,
    `ActionSessionPort.drain_data`;
  - M4b (xafs's off-loop connect) and M19b (no yield between `_post_exec` and the marker put) still hold.
  - **Any difference from §1 is a stop-and-report**, with the measured value.
- [ ] **Step 6: Probe disconnected construction (read-only, scratch).** Write `$SCR/probe_construct.py`; the review's
  `/tmp/claude-1000/hwplanreview/probe2.py` is a starting point. It does what the I0 construct test will do (D8:
  import first, then the recording tripwire, sanitised configs and the two settled overrides), but only prints, per
  in-scope `HelaoDriver` subclass keyed `module.qualname`: `importfail:<exc>`, `clean`, `hits:<list>`, or
  `error:<exception type>: <message>`. Run it from `$SCR` as cwd.
  - Expected: `LeancatDriver`'s module is `importfail`; the other 8 of M3 record hits; everything else is `clean`.
  - Any `error:` (a constructor that rejects its minimal config) or any unexpected `trip:` is reported with the class
    and the message. The main session decides per class before Task 1 Step 3 (a per-class config override in the test,
    or a new spec amendment).
- [ ] **Step 7: Pyright baseline** over every existing `.py` in §4. Save `$SCR/H0/pyright.json`; record
  `filesAnalyzed` and `errorCount`.
- [ ] **Step 8: Launch smoke baseline (main session).** GM-1 on `goldenhex`, twice (tags `b1`, `b2`):
  ```
  rm -rf /tmp/helao-hexsmoke
  tail -f /dev/null | script -qfec "bash ./helao.sh goldenhex --no-hot-reload" $SCR/H0/launch_<tag>.log & SPID=$!
  # wait: curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' --data '{}' http://127.0.0.1:8001/get_orch_state -> 200
  cd $REPO && $PY -m harness.capture --scenario GM-1 --root /tmp/helao-hexsmoke --out $SCR/H0/GM-1/<tag> --config-prefix goldenhex
  bash $SCR/stop_launch.sh $SPID
  ```
  `$PY -m harness.parity --golden $SCR/H0/GM-1/b1 --candidate $SCR/H0/GM-1/b2` must report 0 diffs. If not, stop.

**Gate 0:** Steps 1–8 complete; `failset.txt` recorded; both golden masters PASS; §1 re-measured with no unexplained
drift; the probe's classification agreed by the main session; GM-1 noise floor 0.

---

## Task 1 — I0: framework, no driver behaviour change

### Task 1a — Deletions and the `DataSinkPort` trim (I0a)

- [ ] **Step 1: Write the failing test `helao/hexagon/tests/test_data_sink_port_surface.py`.**
  1. `test_port_members_are_the_trimmed_set`: the public members of `DataSinkPort`
     (`{m for m in dir(DataSinkPort) if not m.startswith("_")}`) equal exactly
     `{"enqueue_data_nowait", "get_realtime_nowait", "finish_hlo_header", "enqueue_data", "write_file",
     "write_file_nowait", "track_file", "append_sample", "split", "set_estop"}`.
     *Mutation:* re-add `get_lbuf` to the Protocol → red.
  2. `test_finish_hlo_header_is_sync_on_the_port`: `inspect.iscoroutinefunction(DataSinkPort.finish_hlo_header)` is
     `False`, and so is `ActionSession.finish_hlo_header`. *Mutation:* make the port's declaration `async` → red.
  3. `test_action_session_satisfies_the_port`: build a session the way the action golden master does (reuse
     `_make_host`, `_mk_action`, `_active_params` from `helao.core.tests.test_active_golden_master`), and assert
     `isinstance(session, DataSinkPort)`. Also assert, for every port member, that the session's attribute is a
     coroutine function exactly when the port's is. *Mutation:* in a subclass of `ActionSession` used only by the
     test, set `split = None` → red.
  4. `test_wiring_has_no_hardware_side_slots`: `{f.name for f in dataclasses.fields(PortWiring)}` contains none of
     `hardware`, `data_sink`, `sample_state`, `ui_host`, and `"data_sink" not in ACTION_REQUIRED`.
     *Mutation:* re-add `data_sink: Optional[object] = None` → red.

  Tests 1, 2 and 4 are red before Step 2. Test 3 is green before and after; its mutation is what makes it falsifiable.
- [ ] **Step 2: Delete and trim.** Re-run the recipe for each symbol first.
  - `ports/hardware.py`: delete `HardwarePort`, `ExclusiveAccess`, `driver_response_to_error_code` and their imports.
    Leave a docstring stub; Task 1b adds `DriverHostPort`. The 33 inline `resp.response == success` compares stay.
  - Delete `adapters/shared/hardware.py` and `adapters/native/galil_motion.py`. In `galil_motion_native.py`, rewrite
    the module-docstring sentence that contrasts it with "the slice-3 `GalilMotionHardwareAdapter`" so it no longer
    names a deleted class.
  - Delete `adapters/native/data_sink.py` and `adapters/shared/data_sink.py`. Remove `NativeDataSinkAdapter` from
    `adapters/native/__init__.py` (import and `__all__`). Remove its import and `data_sink=` from `app/factory.py`. Fix
    the docstring mention in `adapters/native/artifact_store.py` (`native/data_sink.py`).
  - `app/wiring.py`: remove the `hardware`, `data_sink`, `sample_state`, `ui_host` fields and their imports; remove
    `"data_sink"` and its comment from `ACTION_REQUIRED`; remove the P7d `ui_host` comment block.
  - `ports/data_sink.py`: keep exactly the ten members of Step 1 test 1, with the spec §3.2 signatures;
    `finish_hlo_header` becomes `def` (sync). Rewrite the module docstring: thread-safe members are
    `enqueue_data_nowait`, `get_realtime_nowait`, `finish_hlo_header`; everything else is loop-affine; the
    `_nowait` suffix on `write_file_nowait` is historical. Drop the "`realtime_ns`" and lbuf sentences. Add one sentence:
    `ActionSession` satisfies this port structurally; there is no adapter.
    *Note:* the docstring states the thread-safety contract that I6e makes true. Until I6e lands it says
    "`enqueue_data_nowait`: thread-safe (made true in I6e; until then the put runs on the calling thread)". I6e
    removes the parenthesis.
  - `ports/ui_host.py`: delete `build_ui_app` and its docstring bullet. `app/ui_host.py`: delete
    `BokehServerUiHost.build_ui_app`.
  - `adapters/fakes/__init__.py`: `FakeDataSink` keeps only the ten port members, and its `finish_hlo_header` is sync.
  - `pal_driver.py` `_PALActiveContext`: delete the `finish_hlo_header` override (the port is sync now). Rewrite its
    docstring's "pre-existing port/adapter signature gap" sentence: the residual surface is `.action` and the async
    `get_realtime()`.
- [ ] **Step 3: Tests.**
  - Delete `test_galil_hardware_adapter.py`, `test_native_data_sink.py`, `test_adapters_data.py`,
    `test_hardware_import_sweep.py` (A8).
  - `test_adapters_misc.py`: delete the `LegacyDriverHardwareAdapter` test and `_SimDriver` if nothing else uses it;
    keep the queue-pck and `SampleShimAdapter` tests.
  - `test_factory.py`: drop the `data_sink` assertions; keep `w.require(*ACTION_REQUIRED)`.
  - `test_wiring.py`: drop `"data_sink"` from the expected set.
  - `test_ports_import.py`: `helao.hexagon.ports.hardware` exports nothing until Task 1b; set its entry to `[]` here and
    to `["DriverHostPort"]` in Task 1b.
  - `test_fakes.py`: `test_fake_data_sink_records_enqueues_thread_safely` still passes against the trimmed fake.
  - `test_app_ui_host.py`: delete `test_build_ui_app_is_deferred_to_p7f`. `test_ui_host_port.py`: delete the fake's
    `build_ui_app`, `test_build_ui_app_returns_an_opaque_object`, and `"build_ui_app"` from the name loop.
  - The 13 `data_sink=` test files (M16), including `helao/core/tests/unit_test_config_seam.py`: delete the `data_sink=` argument, nothing else.
- [ ] **Step 4: Re-verify every deletion** with the recipe: `HardwarePort`, `ExclusiveAccess`,
  `driver_response_to_error_code`, `LegacyDriverHardwareAdapter`, `GalilMotionHardwareAdapter`,
  `NativeDataSinkAdapter`, `ActiveDataSinkAdapter`, `\.for_action\(` (whitelist `adapters/native/artifact_store.py`), `build_ui_app`, `\bdata_sink=`, `wiring\.(hardware|data_sink|sample_state|ui_host)`,
  `adapters\.(shared|native)\.(hardware|data_sink|galil_motion)\b`. Zero hits outside `docs/`.
- [ ] **Step 5: Run Step 1's tests, then each mutation.** Record red then green.

**Gate 1a:**
- A full `run_tests.py` sweep: failing set equals `$SCR/H0/failset.txt` minus the 4 deleted files; every new file
  passes; `ENV` only for vendor imports.
- Both golden masters PASS (13/13; scenario 14 is Task 1b).
- `run_unit_tests.py` rc 0; pyright no worse than Task 0; `test_boundaries.py`, `test_ports_import.py`,
  `test_fakes.py`, `test_pal_driver_api.py` and every `test_*surface*.py` pass.
- The route checklist (`test_hte_route_checklist.py`) passes with no `_additions` / `_param_additions` change:
  `git -C $REPO diff --stat -- helao/hexagon/tests/checklists` is empty.

**COMMIT BOUNDARY (I0a):** `refactor(hexagon): delete the never-wired hardware/data-sink ports, adapters and slots`.

### Task 1b — `DriverHostPort`, host-owned lifecycle, the construct ratchet, scenario 14 (I0b)

- [ ] **Step 1: Write the failing tests.**
  1. **`helao/hexagon/tests/test_driver_host_surface.py`** (spec §3.3, A11).
     - Walk `helao/deploy/hte` and `helao/hexagon/adapters/native` (tests excluded) and `helao/core/drivers`. Collect
       classes deriving transitively from `Executor`, `HelaoDriver` or `DriverPoller` (resolve bases by name across
       the scanned files, as the M10 scan does).
     - Inside each such class, a violation is:
       - `<expr>.base.X` or `<expr>._base_hook.X` where `X` is not a member of `DriverHostPort`;
       - `getattr(<expr containing _base_hook>, "X", ...)` / `hasattr(...)` with such an `X`;
       - a bare `<expr>.base` or `<expr>._base_hook` passed as a positional or keyword call argument, **except the first
         argument of `getattr`/`hasattr`** (A11), which the previous rule judges.
     - The allowed set is computed from `DriverHostPort` itself (its properties plus its public methods), not
       hard-coded, so the Protocol is the single source.
     - Endpoint closures inside `makeApp` / `*_dyn_endpoints` functions are not classes and are not scanned (spec).
     - `test_no_forbidden_host_read` asserts zero violations. `test_the_scan_sees_every_measured_read` asserts the
       scan finds at least 31 reads in at least 16 files (M10), so a scan that silently matches nothing goes red.
     - *Mutations:* (a) in a scratch copy fed to the scanner function, add `self._base_hook.aloop` inside a
       `DriverPoller` subclass → red; (b) add `helper(self.active.base)` inside an `Executor` subclass → red; (c) add
       `getattr(self._base_hook, "aloop", None)` → red; (d) `getattr(self._base_hook, "helaodirs", None)` stays green
       (the exemption). Implement the scanner as a function taking a list of paths, so the mutations run on files under
       `tmp_path` and never edit a tracked driver.
  2. **`helao/hexagon/tests/test_driver_disconnected_construct.py`** (spec §4, D4, D8). It supersedes the deleted
     sweep's module lists.
     - **Phase 1, import:** import every module under `helao/deploy/hte/drivers` and `helao/hexagon/adapters/native`
       with no tripwire installed. An import failure fails the test, except a third-party `ImportError` that
       `run_tests.py` would classify `ENV`. Record those by name.
       - **Allowlist: the whole `helao/deploy/hte/drivers/test_station/leancat/` subtree** is skipped from import,
         with a comment giving the reason (review measurement). `logger/__init__.py` imports a `main_log` that
         `logger.py` does not define: an in-tree `ImportError` that cascades to `script`, `commands`, `database` and
         `station`. The subtree also needs `tenacity` and `opcua`, which are not installed.
       - `test_station/leancat/driver.py` stays in the **AST** pending scan, which reads source and never imports.
       - Fixing the leancat package is out of scope; it is follow-up F2 (§8).
     - **Phase 2, tripwire:** install the recording tripwire of D8, including the module-level bound vendor names.
       Classify each importable concrete `HelaoDriver` subclass with `classify(cls, config)` (D8), which returns its
       recorded hits and any escaped exception. Keys are `module.qualname` (D4).
     - `test_pending_set_matches_the_constructor_scan`: the AST scan (M3: a `connect` call on `self` or on an
       attribute of `self` inside `__init__`) over in-scope classes equals `CONSTRUCTOR_CONNECT_PENDING` exactly.
       Message on a class that dropped out: "`<key>` no longer connects in `__init__`: remove it from
       `CONSTRUCTOR_CONNECT_PENDING`".
     - `test_construct_is_disconnected`: every importable class **not** in the pending set has zero hits and no
       exception.
     - `test_pending_importable_drivers_do_hit`: every importable class in the pending set records at least one hit.
       This proves the tripwire sees the vendor objects that today's constructors really touch (M22).
     - `test_connect_on_startup_set_is_exact`: `{key for each importable class if cls.connect_on_startup}` equals
       `CONNECT_ON_STARTUP` (empty at I0).
     - `test_nothing_written_outside_tmp`: the `$REPO` top-level snapshot is unchanged (D8).
     - Initial `CONSTRUCTOR_CONNECT_PENDING`, as `module.qualname` keys: `mfc.alicat_driver.AliCatMFC`,
       `motion.kinesis_driver.KinesisMotor`, `pstat.gamry.driver.GamryDriver`, `pump.legato_driver.KDS100`,
       `pump.simdos_driver.SIMDOS`, `sensor.cm0134_driver.CM0134`, `sensor.sprintir_driver.SprintIR`,
       `temperature_control.mecom_driver.MeerstetterTEC`, `test_station.leancat.driver.LeancatDriver`. Each carries a
       one-line comment naming its increment; `LeancatDriver`'s says "no hte station; not flipped by this plan, see
       amendment 3".
     - Config overrides: the two settled in D8, plus any the main session agreed at Task 0 Step 6, each with a comment
       saying why.
     - *Mutations:* (a) remove `SprintIR` from the pending set → `test_pending_set_matches_the_constructor_scan` red,
       and its recorded serial hit turns `test_construct_is_disconnected` red; (b) pass `classify` a scratch subclass
       of `SM303` whose `__init__` calls `self.connect()` → hits non-empty; (c) add the `SM303` key to
       `CONNECT_ON_STARTUP` → red; (d) disable the module-level name patching → `test_pending_importable_drivers_do_hit`
       red for `KinesisMotor` and `MeerstetterTEC`.
  3. **`helao/hexagon/tests/test_host_driver_lifecycle.py`** (spec §6 "Host order").
     - Build an `ActionHost` with the `_host()` pattern from `test_get_status_survives_a_down_driver.py` (injected
       config, stub ports, a tmp `root`), with `driver_classes=[_FakeDriver]`, `poller_class=_FakePoller` and an async
       `dyn_endpoints` that records `"dyn_endpoints"`.
     - `_FakeDriver(HelaoDriver)` records `"__init__"` in its constructor, records `"_base_hook"` from a property
       setter on `_base_hook`, and records `"connect"` in `connect()`. `_FakePoller(DriverPoller)` records `"poller"`
       in `__init__` (after `super().__init__`) and returns an empty `DriverResponse()` from `get_data`. All records go
       to one list.
     - Drive startup with `with TestClient(host):` and wait (bounded, ≤ 2 s) until `"dyn_endpoints"` is recorded.
     - `test_flag_true_orders_connect_before_poller_and_dyn_endpoints`: with `connect_on_startup = True`, the list is
       exactly `["__init__", "_base_hook", "connect", "poller", "dyn_endpoints"]`.
     - `test_flag_false_never_connects`: with it `False`, `"connect"` is absent and the rest keep their order.
     - `test_connect_exception_is_logged_and_startup_continues` (user decision Q4, A3): a `_FakeDriver` whose
       `connect()` raises `RuntimeError("no device")`.
       - Startup completes; `TestClient` does not raise.
       - The list is `["__init__", "_base_hook", "connect", "poller", "dyn_endpoints"]`: the poller and
         `dyn_endpoints` still run.
       - Exactly one ERROR record containing `connect() at startup raised` carries `exc_info`, and one record at the
         alert level carries the exception's repr. `make_logger` sets `propagate=False`, so attach `caplog.handler`
         to `action_host`'s `LOGGER` and remove it in `finally` (pattern: `test_driver_poller_survives_error.py`).
       - `POST /get_status` still answers 200.
     - `test_constructor_exception_still_propagates`: a driver whose `__init__` raises still makes startup fail. Only
       `connect()` is caught.
     - *Mutations:* delete the host connect step → test 1 red; move it after the poller block → test 1 red; remove the
       `try/except` → test 3 red; drop the `LOGGER.alert` call → test 3 red; widen the `try` to cover construction →
       test 4 red.
  4. **Golden scenario 14, `14_nowait_from_foreign_thread`**, in `helao/core/tests/test_active_golden_master.py`.
     - `_RecordingMSQ.put_nowait` also appends `threading.get_ident()` to a `put_threads` list on the queue (not to the
       trace, so the 13 traces are unchanged).
     - The scenario opens a session the way scenario 1 does. A `threading.Thread` calls, in order,
       `session.get_realtime_nowait()`, `session.finish_hlo_header(realtime=<that value>)`, then
       `session.enqueue_data_nowait(DataModel(data={<key>: {"t": [i], "v": [i * 10]}}, errors=[]))` for `i` in 1..20,
       using the session's default file-conn key (follow scenario 1's data shape exactly).
     - The coroutine starts the thread, `join()`s it, then runs the module's existing `_drain_data` /`_ticks` helpers
       and `finish()`, as scenario 13 does. It records nothing about thread ids in the trace.
     - Register it in `SCENARIOS` after scenario 13.
- [ ] **Step 2: Implement.**
  - `helao/core/drivers/helao_driver.py`:
    - `HelaoDriver` gains `connect_on_startup: ClassVar[bool] = False`, with a docstring line: "`True` means the host
      calls `connect()` once at startup, after setting `_base_hook` and before building the poller. A driver must not
      do device I/O in `__init__`."
    - `DriverPoller._base_hook` becomes `"Optional[DriverHostPort]"` under a `TYPE_CHECKING` import (D7); update the
      comment that says `Any` avoids the cycle.
  - `helao/hexagon/ports/hardware.py`: module docstring (the hardware contract is the `HelaoDriver` ABC; this module
    holds what hardware-side code may read from its host) and `DriverHostPort(Protocol)`, `@runtime_checkable`, with
    the spec's nine §3.3 members plus `server_key` (A5): ten in all.
    - Methods: `get_lbuf(self, live_key) -> tuple`, `async put_lbuf(self, live_dict: dict) -> None`,
      `dflt_file_conn_key(self)`.
    - **Data members are read-only `@property` declarations** (review fix 9), not plain annotations: `helaodirs`,
      `actionservermodel`, `executors -> dict`, `server_params -> dict`, `world_cfg -> dict`,
      `poller -> Optional[DriverPoller]`, `server_key -> str`. A plain `poller: Optional[DriverPoller]` attribute is
      invariant, and pyright would reject `ActionHost` against it. A read-only property is covariant and accepts the
      host's attribute. No `# type: ignore` is allowed anywhere in this change.
    - Use the types the boundary rule allows (M20). Fall back to `Any`, with a comment, where a model type is not
      importable from `ports/`.
    - Each member carries its thread class from spec §3.3 in a trailing comment.
  - `test_ports_import.py`: `helao.hexagon.ports.hardware` exports `["DriverHostPort"]`. Add a check in the new
    surface test (or `test_action_host_member_coverage.py` if that is where host-member checks live) that a real
    `ActionHost` from the `_host()` pattern satisfies `isinstance(host, DriverHostPort)`.
  - Annotations only: each driver's `_base_hook` (`cNIMAX`, motion `Galil`, `NativeGalilMotion`) and
    `ActionSession.base` become `Optional[DriverHostPort]` / `DriverHostPort`. Andor reads `_base_hook` through
    `getattr`, so it needs no annotation now (I6b adds the `server_key` read). Do not add `# type: ignore`; if pyright
    objects to an `ActionHost` assignment, report the error.
  - `action_host.py`: D3, exactly. Nothing else in `startup_event` moves.
  - Delete the three server-side assignments (D2): `app.driver._base_hook = app.base` in `galil_motion` and
    `nidaqmx_server`, `app.driver._base_hook = app` in `andor_server`. Leave their comments accurate (the andor comment
    explaining why the key is wired there keeps the `server_key` half).
  - D6 for the tests of M16b: `test_motion_private_endpoints.py`, `test_andor_acquire_guard.py` and the smoke
    `test_golden_capture_galil*.py` set `app.driver._base_hook = app` on their fake app before calling
    `dyn_endpoints`. Find any others by running the galil_motion, nidaqmx and andor tests after the deletion. Name every
    test touched in the report.
  - Root `CLAUDE.md`, "Conventions worth knowing", the `HelaoDriver` bullet: add "No device I/O in `__init__`; set
    `connect_on_startup = True` to have the host connect at startup (after `_base_hook`, before the poller)."
- [ ] **Step 3: Scenario 14 reference (D5).**
  - Run the default mode (the determinism self-test) and confirm scenario 14 is stable twice.
  - Write `$SCR/I0/freeze14.py`: it imports the module, calls its `_capture_scenario("14_nowait_from_foreign_thread", <tmp>)`
    and writes the two reference files into `helao/core/tests/golden/action/` with the same names and encoding
    `_write_baseline` uses. It refuses if either file already exists.
  - `--check` must then print `PASS` for all 14 and `CHECK PASSED: all 14 scenarios`.
  - `git -C $REPO status --short -- helao/core/tests/golden/action` shows exactly the two new files.
- [ ] **Step 4: Run Step 1's tests, then each mutation.** Record red then green.

**Gate 1b:**
- Full sweep: failing set equals Gate 1a's; new files pass.
- Action golden master `--check`: 14/14, the 13 old references byte-unchanged
  (`git -C $REPO diff --stat HEAD -- helao/core/tests/golden` lists only the 2 additions). Dispatch golden master PASS.
- Route checklist unchanged, no additions entries.
- `test_hte_builds_on_linux.py`, `test_andor_server_composition.py`, `test_get_status_survives_a_down_driver.py`,
  `test_estop_fixes.py`, `test_action_host_member_coverage.py` pass.
- `run_unit_tests.py` rc 0; pyright no worse than Task 0.
- Nested repos: every nested `tests/` file that references `_base_hook`, `HelaoDriver` or an hte driver/server
  module keeps its H0 verdict (the full sweep covers them; list them in the report).
- **Launch smoke (main session):** one GM-1 capture on `goldenhex`; parity against `$SCR/H0/GM-1/b1` reports 0 diffs.

**COMMIT BOUNDARY (I0b):** `feat(action-host): host-owned driver lifecycle, DriverHostPort gate and construct ratchet`.

### Task 1c — The amendment file (docs)

- [ ] Write `docs/superpowers/specs/2026-10-19-hexagonal-rewrite-amendment-3.md` in the shape of amendment 2 (Date;
  Amends the master spec as amended by amendments 1 and 2; Status: Adopted; Baseline: BASE; privacy rule inherited).
  Body, short:
  - §4.3.1: the hardware contract is the `HelaoDriver` ABC plus `connect_on_startup`; `HardwarePort` and
    `ExclusiveAccess` are dropped; bus exclusivity stays inside each driver.
  - §4.3.2: `DataSinkPort` is the trimmed ten-member surface, `ActionSession` satisfies it with no adapter; `_base_hook`
    does not collapse into DataSink but is typed as the host-scoped `DriverHostPort`.
  - §4.5: `PortWiring` has no `hardware`, `data_sink`, `sample_state` or `ui_host` slot.
  - §4.5 (lifecycle): the host sets `_base_hook`, then connects drivers with `connect_on_startup`, before the poller
    and `dyn_endpoints`. A raising connect is logged at ERROR, alerted, and the server starts with the driver
    disconnected (user decision; replaces the spec's propagate rule, A3).
  - §10.4: the disconnected-construct ratchet (`CONSTRUCTOR_CONNECT_PENDING`, `CONNECT_ON_STARTUP`), ending at
    `{LeancatDriver}`.
  - Point to the spec for the design and to this plan's §2 (A1–A11) for the measured corrections. Use only the
    Deployment-A/B/C/E aliases.

**COMMIT BOUNDARY (docs):** `docs(spec): amendment 3 — host-owned driver lifecycle and trimmed hardware/data-sink ports`.

---

## The driver-flip recipe (used by every increment I1–I7)

For each class `D` the increment flips:

- [ ] **R4 check.** Recipe grep for `\bD\b` and for `D`'s server module name across the whole tree. Confirm M13 still
  holds: no nested server calls `connect()` on `D` itself. If one does, stop: that repo needs its own edit in the same
  window.
- [ ] **Red first.** In `test_driver_disconnected_construct.py`, remove `D` from `CONSTRUCTOR_CONNECT_PENDING` and add
  it to `CONNECT_ON_STARTUP`, using `module.qualname` keys (D4). Three tests go red:
  `test_pending_set_matches_the_constructor_scan`, `test_construct_is_disconnected` (D records hits) and
  `test_connect_on_startup_set_is_exact`.
- [ ] **Edit the driver.** Delete the `self.connect()` call in `__init__` and the comment that justifies it (each says
  "ActionHost never calls connect()", which is no longer true). Add, at class level,
  `connect_on_startup = True  # the host connects after _base_hook, before the poller`. Change nothing else.
- [ ] **Retarget the tests that pinned the old placement** (D6), from M15's list for this family. A test named
  `*_opens_at_construction` becomes `*_opens_on_connect`: construct, assert closed, call `connect()`, assert open.
- [ ] **Disconnected-poll check (A3, user decision Q4).** After the flip, a failed connect leaves this driver
  disconnected under a running poller, where before the server never started. Add one test per poller-backed class
  `D`, in the family's test file: construct `D` with the vendor faked so that `connect()` fails (or do not call
  `connect()` at all). Then call `get_data()` on its poller class directly, three times, and assert each call returns
  a `DriverResponse` without raising.
  - **Pre-settled exception: `MeerstetterTECPoller`** (review measurement). Its `get_data()` raises on every call while
    disconnected, because it re-attempts the MeCom open. That is today's behaviour, and `DriverPoller` already
    rate-limits the log: once, then every 100th. The I2 test asserts exactly that: it raises, and the poller loop
    survives three cycles with one logged line. It does not assert "no raise".
  - **Where the guard lives:** for `KinesisMotor`, `CM0134` and `SprintIR` the disconnected short-circuit is in the
    driver method the poller calls (`get_status` / `read_o2_ppm` / the SprintIR read), not in `get_data` itself. Name
    that driver method as the mutation target.
  - Any other `D` whose `get_data()` raises when disconnected: stop and report (Q11).
  - *Mutation:* remove the disconnected short-circuit (in `get_data` or in the named driver method) → red.
- [ ] **Green.** The construct test, the host lifecycle test, the family's tests.

**Per-increment gate (every one of I1–I7):**
1. Full `run_tests.py`: failing set equals the previous gate's; `ENV` only for vendor imports.
2. Action golden master 14/14 unchanged; dispatch golden master unchanged.
3. Route checklist unchanged; `git -C $REPO diff --stat HEAD -- helao/hexagon/tests/checklists` empty.
4. `test_driver_disconnected_construct.py` and `test_driver_host_surface.py` pass, and
   `CONSTRUCTOR_CONNECT_PENDING` shrank by exactly this increment's classes (show the diff of the two sets).
5. Pyright on the changed files, on the real path, no worse than Task 0.
6. The nested tests that reference this increment's classes or server modules keep their H0 verdicts (name them).
7. Black by the main session before the commit.

---

## Task 2 — I1: canary, SprintIR and CM0134

- [ ] Recipe for `SprintIR` (`drivers/sensor/sprintir_driver.py`) and `CM0134` (`drivers/sensor/cm0134_driver.py`).
- [ ] `git mv helao/deploy/hte/tests/test_poller_drivers_connect_in_init.py helao/deploy/hte/tests/test_poller_drivers_connect_on_startup.py`.
  Rewrite its module docstring: poller-backed drivers open their device in `connect()`, which the host calls at
  startup before the poller exists (`connect_on_startup`). Retarget the CM0134 tests:
  `test_cm0134_opens_at_construction` → construct (`drv.inst is None`), `connect()`, then `drv.inst.device == "COM7"`;
  the no-device test keeps its assertions after an explicit `connect()`. Add `assert CM0134.connect_on_startup is True`
  and the same for `SprintIR`. Leave the TEC tests for Task 3.
  *Mutation:* restore the constructor `self.connect()` in `CM0134` → the construct test and the retargeted
  "assert closed after construct" go red.

**Gate:** the per-increment gate. **Station check:** §7, I1 (SprintIR at `ccsi2`); CM0134 is Linux-only.

**COMMIT BOUNDARY:** `feat(sensor): SprintIR and CM0134 connect at host startup (I1, canary)`.

## Task 3 — I2: MeerstetterTEC

- [ ] Recipe for `MeerstetterTEC` (`drivers/temperature_control/mecom_driver.py`). Its `connect()` retries and returns
  a failed response; the session-open helper `_connect` is unchanged.
- [ ] In `test_poller_drivers_connect_on_startup.py`, retarget `test_tec_opens_at_construction` and
  `test_tec_with_a_missing_port_fails_once_without_raising` (the "fails once" count is taken after an explicit
  `connect()`).
- [ ] **`test_tec_host_starts_and_shuts_down_after_a_raising_connect`** (adopted from the re-review; the one host-level
  proof that disconnect and shutdown are safe on a formerly constructor-connect driver). `tec_server` has no
  station, so this is its only end-to-end check.
  - Build `tec_server.makeApp` against an injected config with a `TEC` server. Monkeypatch `MeerstetterTEC.connect`
    to raise `OSError`.
  - Under `with TestClient(app):`, assert:
    - startup completes, with one ERROR record `MeerstetterTEC.connect() at startup raised`;
    - `/get_status` answers 200;
    - the poller has run at least two cycles, and its `get_data()` raise is logged once (D-poll exception above).
  - Leaving the `with` block runs shutdown. Assert:
    - no exception escapes;
    - `ActionHost.shutdown()`'s `retvals` show the driver's `shutdown`/`async_shutdown` hooks ran, or were absent,
      on a never-connected driver;
    - the poller tasks are done.
  - *Mutation:* make the TEC `shutdown` hook (or `disconnect`, whichever teardown calls) dereference the session
    unguarded → red. If it already does that and the test is red on day 1, stop and report: that is a real teardown
    defect that the user's Q4 decision exposes.

**Gate:** the per-increment gate. **Station check:** none; no config hosts `tec_server` (A6). Linux-only.

**COMMIT BOUNDARY:** `feat(tec): MeerstetterTEC connects at host startup (I2)`.

## Task 4 — I3: SIMDOS and KDS100

- [ ] Recipe for `SIMDOS` (`drivers/pump/simdos_driver.py`) and `KDS100` (`drivers/pump/legato_driver.py`).
- [ ] `test_simdos_connect_in_init.py`: `git mv` it to `test_simdos_connect_on_startup.py` and retarget both tests
  (construct, assert `drv.com is None`, `connect()`, assert open). `test_low_w3_hte_fixes.py`'s SIMDOS construct gains
  `drv.connect()` where it relied on the open port.
- [ ] The SIMDOS poller's fault sweep reads `self._base_hook.executors`, a `DriverHostPort` member, and its code does
  not change. No Linux test covers it today: `test_low_w3_hte_fixes.py` only builds an empty `executors` dict. Add
  `test_simdos_fault_stops_host_executors`:
  - build a `SIMDOSPoller` over a constructed, unconnected `SIMDOS`;
  - stub the driver read so the status dict carries one `fault_*` entry with a non-zero value;
  - set `poller._base_hook` to a stub whose `executors` holds two stub executors that record `stop_action_task()`;
  - call `get_data()` once and assert both recorded a stop.

  *Mutation:* change the `fv != 0` filter to `fv == 0` → red. This replaces the station fault trigger, which is
  optional in §7.

**Gate:** the per-increment gate. **Station check:** §7, I3.

**COMMIT BOUNDARY:** `feat(pump): SIMDOS and KDS100 connect at host startup (I3)`.

## Task 5 — I4: AliCat MFC

- [ ] Recipe for `AliCatMFC` (`drivers/mfc/alicat_driver.py`). The 12 `stop_polling`/`start_polling` brackets and the
  co2 peer lookup through `world_cfg` stay as they are.
- [ ] Grep hte and nested tests for `AliCatMFC(`; retarget any that relied on the constructor connect.

**Gate:** the per-increment gate. **Station check:** §7, I4.

**COMMIT BOUNDARY:** `feat(mfc): AliCat MFC connects at host startup (I4)`.

## Task 6 — I5: Kinesis

- [ ] Recipe for `KinesisMotor` (`drivers/motion/kinesis_driver.py`).
- [ ] Retarget `test_kinesis_counts.py`, `test_motion_private_endpoints.py`, `test_low_w3_hte_fixes.py` and
  `test_kinesis_estop.py` where they build `KinesisMotor(config=...)` and then use its connections: add
  `driver.connect()` immediately after construction, inside the same monkeypatch scope that fakes `pylablib`.
- [ ] Confirm that the `xfail` the spec mentions no longer exists anywhere (A8):
  `bash -c 'grep -rn "xfail" '"$REPO"'/helao --include=*.py | grep -i kinesis'` is empty.

**Gate:** the per-increment gate. **Station check:** §7, I5.

**COMMIT BOUNDARY:** `feat(motion): Kinesis connects at host startup (I5)`.

---

## Task 7 — I6: servers whose `dyn_endpoints` connect is deleted (one commit each)

**The server recipe** (replaces "Edit the driver" in the driver-flip recipe, for drivers that are already
disconnected-construct):
- [ ] The driver class (and every class sharing the server) gets `connect_on_startup = True`; add it to
  `CONNECT_ON_STARTUP` first (red), then to the class (green). There is nothing to remove from the pending set.
- [ ] In the server's `*_dyn_endpoints`, delete `connect_resp = app.driver.connect()` (or the bare call) and the
  `LOGGER.info(f"... connect() returned status=...")` line under it. Rewrite the comment above it to say the host
  connects at startup. **Everything after it stays**: the `galil_enabled` gates, the `ready` waits,
  `UnifiedSampleDataAPI`, every route.
- [ ] Tests that drive this server's `dyn_endpoints` with a real or fake driver and relied on its connect (M15): call
  `app.driver.connect()` first (D6). Name each in the report.
- [ ] Extra gate for every I6 sub-task: `test_hte_builds_on_linux.py` and every test that runs this server's startup
  pass. A `connect()` that raises on Linux (M6) is now caught by the host (A3), so such a test sees an ERROR record
  instead of a failed startup. If a test pinned the old failure (no late routes after a raising connect), **stop and
  report** it with the assertion. Do not change it on your own.
- [ ] **Disconnected-server check (A3, user decision Q4).** For this server, add one host-level test, beside its
  existing server tests. Build the app with `makeApp` under its station config, as `test_hte_builds_on_linux.py`
  does, and make the driver's `connect()` raise (monkeypatch it on the class). Run startup with `TestClient` and
  assert:
  - startup completes;
  - an ERROR record containing `connect() at startup raised` is logged;
  - `POST /get_status` answers 200.
  - For Gamry and BioLogic, `dyn_endpoints` is still parked on `ready`, so their action routes are absent: assert
    that, and that the endpoint-status init task is still pending. That is today's behaviour after a failed connect.
  - *Mutation:* remove the host `try/except` → red.

### Task 7a — I6a: SM303 (`spec_server`)
- [ ] `SM303.connect_on_startup = True`; delete the connect in `spec_server`'s `dyn_endpoints`.
- Station: §7, I6a (`eche10:SPEC_T`).
- **COMMIT BOUNDARY:** `feat(spec): SM303 connects at host startup (I6a)`.

### Task 7b — I6b: Andor (`andor_server`)
- [ ] **Red first:** add `test_connect_takes_the_key_from_the_host` to `test_andor_server_composition.py`:
  - construct `AndorCalibratedDriver(config={...})` with no `server_key` argument;
  - set `_base_hook` to a stub with `server_key = "ANDOR_ALT"` and `helaodirs.states_root = tmp_path`;
  - call `connect()`, which fails harmlessly on Linux: its body catches broadly;
  - assert `drv.server_key == "ANDOR_ALT"` and that `calibration_file().name` contains `ANDOR_ALT`.

  The test is red before the edit, because the driver keeps the class default `"ANDOR"`. *Mutation:* drop the D9
  line → red. A second test: with `_base_hook = None`, `connect()` keeps the constructor's key.
- [ ] `AndorDriver.connect()`: D9's line as its first statement, before the `try`. Then
  `AndorDriver.connect_on_startup = True`, inherited by both variants.
  Delete the connect in `andor_server`'s `dyn_endpoints`; keep `app.driver.server_key = server_key` and rewrite its
  comment (it no longer has to run before connect; the host's key covers that).
- [ ] `test_andor_server_composition.py`'s existing pins (`server_key`, `_base_hook is app`, calibration under the
  configured `states_root`) keep passing unchanged. The Deployment-E test that imports `AndorCalibratedDriver` keeps its verdict.
- Station: §7, I6b (`hispec:ANDOR`; also the Deployment-E bench that pins `andor_server`).
- **COMMIT BOUNDARY:** `feat(andor): Andor connects at host startup; calibration key from the host (I6b)`.

### Task 7c — I6c: galil_io
- [ ] io `Galil.connect_on_startup = True` (`drivers/io/galil_io_driver.py`); delete the connect in `galil_io`'s
  `dyn_endpoints` and rewrite the comment above it (it explains why the connect had to precede route registration;
  the host order now guarantees that).
- [ ] `test_digital_out_private_endpoints.py` and the smoke `golden_capture_galil_io.py`: D6.
- Station: §7, I6c (`anec`, `eche10`, `hispec`; also the Deployment-C and Deployment-E configs that resolve to hte's
  `galil_io`).
- **COMMIT BOUNDARY:** `feat(galil-io): galil_io connects at host startup (I6c)`.

### Task 7d — I6d: BioLogic, all three backends
- [ ] `BiologicDriver`, `BiologicEclib2Driver`, `BiologicOleDriver`: `connect_on_startup = True`. Read
  `helao/deploy/hte/drivers/pstat/CLAUDE.md` first; the OLE connect still runs on the loop thread, as it did from the
  `dyn_endpoints` task.
- [ ] Delete the connect in `biologic_server`'s `dyn_endpoints`; keep the `while not app.driver.ready` wait.
- [ ] `test_biologic_backend_select.py`, `test_biologic_new_endpoints.py`, `test_biologic_eclib2_plan.py`,
  `test_biologic_disconnected_construct.py`, `test_biologic_estop.py`: D6 where they relied on the connect.
- Station: §7, I6d (`hispec:PSTAT` eclib, `biologiceclib2`, `biologicole`; also the Deployment-E bench).
- **COMMIT BOUNDARY:** `feat(biologic): BioLogic backends connect at host startup (I6d)`.

### Task 7e — I6e: NI-DAQmx, plus the `enqueue_data_nowait` marshalling fix (high risk: foreign thread)
- [ ] **Red first: `helao/hexagon/tests/test_enqueue_nowait_marshals_to_loop.py`.** Reuse the golden master's
  `_make_host` / `_mk_action` / `_active_params` and open a session as scenario 1 does.
  1. `test_foreign_thread_puts_run_on_the_loop_thread`: with the loop **running** (the coroutine awaits
     `asyncio.to_thread(worker)`), the worker calls `enqueue_data_nowait` ×20. After `finish()`, every entry of the
     data queue's `put_threads` equals the loop thread's id, and the `.hlo` holds all 20 rows in order `t = 1..20`.
     Red before the fix (the ids are the worker's).
  2. `test_foreign_thread_row_is_delivered_promptly` (review fix 8):
     - Wrap the session's `write_live_data` so it sets an `asyncio.Event` after writing.
     - Start a worker thread that enqueues one row and returns. Do not join it from the coroutine.
     - Await exactly one `asyncio.wait_for(event.wait(), 1.0)`, with no other timer or task in the test. Measure the
       elapsed time with `loop.time()` and assert < 0.2 s.
     - Before the fix the selector is not woken, so the row waits for the 1.0 s timeout and the test is red.
     - Report the measured pre-fix and post-fix times.
  3. `test_row_keeps_the_action_current_when_produced` (A9):
     - A worker thread calls `enqueue_data_nowait` once while the loop is blocked in a synchronous `t.join()`, so the
       marshalled put has not run yet.
     - The coroutine then calls `await session.split()` before yielding anywhere else, then drains and finishes.
     - **Assert on the put record, not on the `.hlo`.** The data queue's `_RecordingMSQ` records each package actually
       put; capture the package itself if the trace record lacks its uuid. That package's `action_uuid` must equal the
       **pre-split** action's uuid, the action current when the hardware produced it.
     - Why not the `.hlo`: `split()` removes the old action's uuid from `listen_uuids` without yielding. An unconsumed
       pre-split row is then skipped by the logger whichever way it was built (review measurement). **That loss is
       pre-existing, not fixed here,** and is recorded as a follow-up in §8 (F1).
  4. `test_no_tail_row_is_lost_before_the_marker` (review fix 1, M19b):
     - A worker thread enqueues rows `t = 1..N` (N = 20) while the loop is blocked in a synchronous `t.join()`.
     - The coroutine then makes one on-loop `enqueue_data_nowait` (`t = N+1`), the executor runner's cleanup row, and
       immediately `await session.finish()`, with no `_ticks`/`_drain_data` and no sleep in between.
     - Assert the `.hlo` holds all N+1 rows **in order** `t = 1..N+1`.
  4b. `test_no_tail_row_is_lost_without_an_on_loop_row` (review re-check):
     - Same setup as test 4, but **no** on-loop row: after `t.join()` the coroutine immediately runs
       `await session.finish()`.
     - Assert the `.hlo` holds all N rows in order. This is the case where only `drain`'s flush can save them.
  5. `test_closed_loop_drops_and_warns_once`: close a scratch loop and set it as `base.aloop`. Two foreign-thread
     `enqueue_data_nowait` calls neither raise nor put. They log exactly one WARNING, and the streamer's `_xthread`
     deque is empty afterwards.

  *Mutations:*
  - restore the direct `put_nowait` (the I0 body) → tests 1 and 2 red; record what 3–5 do;
  - marshal the whole call, including `_build_data_package` → test 3 red;
  - drop the flush in `drain` → **test 4b** red, tail rows missing. Test 4 stays green under this mutation, because
    its on-loop row's flush puts `1..N` first; that is expected;
  - move the `drain` flush after the never-streamed guard → test 4b red: `num_data_queued` is still 0 there, so the
    drain is skipped;
  - drop the flush at the top of the on-loop path → test 4 red, `N+1` out of order;
  - remove the `is_closed()` check and the `clear()` → test 5 red: the deque grows, or the call raises.
- [ ] **Implement D10** in `adapters/native/data_stream.py`. Add `import asyncio` and `import collections` if missing.
  - `self._flush_xthread()` is the **unconditional first statement** of `NativeDataStreamer.drain`. It goes before the
    completion branch's skip-when-never-streamed guard and before the first marker put. Anchor on the symbol;
    Task 0 Step 5 records the guard's shape.
  - Update the `ports/data_sink.py` docstring parenthesis (Task 1a) to state plainly that `enqueue_data_nowait` is
    thread-safe.
  - *Note on review fix 1:* the review asked for `await asyncio.sleep(0)` before the marker. The flush does the same
    job without relying on loop scheduling, and it also covers the on-loop cleanup row that would otherwise jump ahead
    (test 4's on-loop-flush mutation). A `sleep(0)` would still let that row overtake. The re-review accepted the
    flush (Q10).
- [ ] **Scenario 14 must still PASS unchanged** (`--check`), proving the rows did not change, only the thread. If it
  reports DELTA, stop and escalate with the diff; do not re-freeze.
- [ ] **The connect move:** `cNIMAX.connect_on_startup = True`; delete the connect in `nidaqmx_dyn_endpoints`. Its
  `_base_hook` line already went in I0. Rewrite the function docstring (it opens nothing now; it builds the shared
  `UnifiedSampleDataAPI`).
- [ ] Check the 4b interaction: `test_finish_drain_marker.py` and the pending fix's tests pass. Test 4 above, not loop
  scheduling, is what proves no cross-thread row lands behind the marker.
- [ ] Deployment-A's `io_server` wraps hte's `makeApp`; run its tests that reference `nidaqmx_server`.
- Station: §7, I6e.
- **COMMIT BOUNDARY:** `fix(data-stream): enqueue_data_nowait marshals its put onto the host loop; NI-DAQmx connects at host startup (I6e)`.

### Task 7f — I6f: galil_motion / `NativeGalilMotion` (high risk: motion, aligner)
- [ ] `NativeGalilMotion.connect_on_startup = True`. The legacy motion `Galil` class is not hosted by any server
  (M13 `driver_classes` scan): leave it `False`.
- [ ] Delete the connect in `galil_motion`'s `dyn_endpoints` and its log line. The `_base_hook` line went in I0; the
  `UnifiedSampleDataAPI` line and the whole `if app.driver.galil_enabled is True:` block stay. Rewrite the function
  docstring's ordering paragraph: the host sets `_base_hook` (so `connect()` can read `helaodirs`) and connects before
  this callback runs, so `galil_enabled` is final when it is read.
- [ ] `test_motion_private_endpoints.py`, the smoke `golden_capture_galil.py`, and any aligner test that runs this
  `dyn_endpoints`: D6.
- Station: §7, I6f.
- **COMMIT BOUNDARY:** `feat(galil-motion): NativeGalilMotion connects at host startup (I6f)`.

---

## Task 8 — I7: Gamry (highest risk: COM apartment; shared with private deployments)

- [ ] Recipe R4 for `GamryDriver`, `GamryComAdapter` and `gamry_dyn_endpoints`. Expected users (M13): hte's
  `gamry_server2`, Deployment-A's `potentiostat_server` (direct `GamryDriver` plus `gamry_dyn_endpoints`) and its
  overlay test, Deployment-B's 2 configs resolving to hte's `gamry_server2`.
- [ ] **Red first:**
  - construct test: move `GamryDriver` from pending to `CONNECT_ON_STARTUP`, and add `GamryComAdapter` to
    `CONNECT_ON_STARTUP`;
  - a new test in an existing gamry adapter test file (find it with `grep -rln GamryComAdapter $REPO/helao/hexagon/tests`):
    with a fake thread factory and a fake driver factory whose product records `connect()` calls,
    `adapter.connect()` constructs the driver **and calls its `connect()` exactly once, on the COM thread**. Red
    before the edit (the adapter relies on the constructor). *Mutation:* call `connect()` twice → red; call it off
    the fake thread → red.
- [ ] `GamryDriver`: delete the constructor `self.connect()`; `connect_on_startup = True` (this is what Deployment-A's
  host now uses, so it connects once instead of twice).
- [ ] `GamryComAdapter.connect()`: after `self._driver = self._thread.call(self._driver_factory, self._config)`, call
  `self._thread.call(self._driver.connect)`, then return the status as today. Fix the comment that says
  `GamryDriver.__init__` already connects. `connect_on_startup = True`.
- [ ] `gamry_dyn_endpoints`: delete `app.driver.connect()` and its comment; keep the `ready` wait and everything after.
- [ ] `helao/deploy/hte/drivers/pstat/gamry/tests/run_ocv.py` (a manual script, not collected): add an explicit
  `connect()` after it constructs `GamryDriver`.
- [ ] Deployment-A's `test_p4b_gamry_overlay.py` stub driver keeps `connect=lambda: None`; it is now unused. Do not
  edit the nested repo for that; report it as a nested follow-up only if its verdict changes.

- [ ] **Disconnected-server checks (A3, user decision Q4).** Run the I6 disconnected-server check for `gamry_server2`.
  Add one more test, `test_gamry_driver_host_starts_without_comtypes`: build an `ActionHost` with
  `driver_classes=[GamryDriver]` (Deployment-A's shape) and `gamry_dyn_endpoints`, on Linux where `comtypes` is
  absent. Assert that startup completes, that an ERROR record `GamryDriver.connect() at startup raised` is logged, and
  that `/get_status` answers. Before I7, this host failed at construction. *Mutation:* remove the host `try/except` →
  red.

**Gate:** the per-increment gate, plus every test with `gamry` in its path (`--filter gamry`) and Deployment-A's
`potentiostat` tests keep their H0 verdicts. The ratchet now reads `CONSTRUCTOR_CONNECT_PENDING == {"test_station.leancat.driver.LeancatDriver"}`.

**Station check:** §7, I7 (`eche10` first).

**COMMIT BOUNDARY:** `feat(gamry): Gamry connects once, at host startup (I7)`.

---

## 7. Station verification checklist (the user runs this before merge, canary first)

**How to run it.** Check out the branch head on the station (and each nested repo at its H0 head from
`$SCR/H0/nested_heads.txt`). Run the increments in the order below. If one fails, check out the commit just before
that increment (`git -C <repo> log --oneline` names them) and repeat that increment's checks to confirm attribution.
Every increment's rollback is reverting its commit (R1).

**PRE captures.** For each station, before touching the branch, run its smoke sequence on the merge base
(`git -C <repo> merge-base unstable feat/hexagon-completion`) and capture it with the family's
`helao\hexagon\tests\smoke\golden_capture_<family>.py` where one exists (co2, mfc, syringe, tec, spec, andor,
galil_io, galil, biologic), else `station_golden_capture.py`. Also, on PRE:
- **For I6e:** keep the `.hlo` of a ≥60 s cellIV.
- **Unplugged-device run.** For every increment's server, and always for the I6/I7 servers: launch PRE with the device
  unplugged (or powered off). Record whether the server came up, what `/get_status` answers, which action routes
  exist (save `curl.exe -s http://<host>:<port>/openapi.json`), and what one action request returns. Save the log
  excerpt. Check 7 compares against this run.

**Log lines changed by this branch (A13, user decision Q7):** the seven server-side
`"<X> connect() returned status=..."` lines are gone. Each host-managed connect logs one line instead:
`"<Class>.connect() at startup: response=... status=..."`. A raising connect logs
`"<Class>.connect() at startup raised; continuing with the driver disconnected"` at ERROR and sends an alert.
Anyone who greps station logs for the old text must switch to the new one.

**The eight checks** (spec §6), run for every increment at its station(s):
1. Launch with `helao.bat <config>`. The first launch rebuilds the Reflex bundle (M21); that is expected.
2. `curl.exe -s -X POST http://<host>:<port>/get_status`: `_driver_status` is not `unknown`.
3. Poller drivers: `curl.exe -s -X POST http://<host>:<port>/get_lbuf` is non-empty and its epoch advances over 30 s.
4. Run one action of the family; then E-STOP latch and release.
5. `CTRL-r` that server: for the restart, the log shows exactly one `<Class>.connect() at startup:` line and no
   server-side `connect() returned` line.
6. `CTRL-x`: clean teardown, with no `get_data` spam after disconnect. **For galil_io (I6c) and NI-DAQmx (I6e):**
   *if* PRE logged a startup "`get_data()` raised" line before its connect (M5; unmeasured, and NI-DAQmx's poller may
   short-circuit), that line is gone on POST. Record whether PRE had it, and report it if POST still does.
7. **Device unplugged at launch (user decision Q4).** POST must show:
   - the server **comes up**, and the log has the ERROR line above with its traceback (plus the alert email, if this
     station configures alerting);
   - `/get_status` answers;
   - action routes behave as they did in PRE's unplugged run when the driver is down: same route set in
     `openapi.json`, same response to the same action request.

   Two differences from PRE are expected:
   - formerly constructor-connect drivers (I1–I5, and `GamryDriver` hosts) used to fail at launch when `connect()`
     raised; now they come up disconnected;
   - an I6/I7 server whose PRE connect *raised* came up without its late routes; POST has them, except where a
     gate or a wait applies:
     - `galil_io` and `galil_motion` register their routes only when `galil_enabled` is true, so after a raising or
       failed connect they have none;
     - BioLogic waits on `ready`, which a failed connect never sets, so it keeps logging "waiting for ... init" as PRE
       did after a failed connect and has no action routes;
     - Gamry (hte's `gamry_server2`): after a failed *non-raising* connect, `GamryDriver.__init__` has already set
       `ready = True`, so `dyn_endpoints` does **not** park. It raises `AttributeError` on `app.driver.model` (`None`),
       the log shows "endpoint status init failed", and no routes register. That is identical to PRE. After a
       *raising* connect the adapter never builds a driver, `ready` stays false, and it waits.

   Record every difference, with the log excerpt.
8. On-station golden diff of the smoke sequence against PRE, with no control panel operated. Filter `body.ch_*`,
   `epoch_s` and `hlo_version` first; every remaining non-data diff must be explained.

**Order and stations:**

| # | increment | station(s) | extra |
|---|---|---|---|
| 1 | **I1 SprintIR (canary)** | `ccsi2` CO2SENSOR | CM0134 has no station |
| 2 | I2 MeerstetterTEC | none | Linux-only (A6) |
| 3 | I3 SIMDOS, KDS100 | `ccsi2` DOSEPUMP + syringes; syringes also on `clad`, `adss3` | optional: only if the station has a safe, documented way to raise a SIMDOS fault, trigger it during a run and see the running executors stop. Otherwise skip; `test_simdos_fault_stops_host_executors` covers it on Linux |
| 4 | I4 AliCat MFC | `ccsi2` MFC/N2MFC, `ecms3` MFCs | one constant-concentration action (co2 peer through `world_cfg`) |
| 5 | I5 Kinesis | `eche10` KMOTOR, `hispec` KMOTOR | also the Deployment-E bench config that pins `kinesis_server` |
| 6 | I6a SM303 | `eche10` SPEC_T | also the Deployment-C config resolving to hte's `spec_server` |
| 7 | I6b Andor | `hispec` ANDOR | the calibration file name is unchanged (`<host>_<server_key>_andor_wl_calib.json`); also the Deployment-E bench |
| 8 | I6c galil_io | `anec`, `eche10`, `hispec` IO | the same route set appears (compare `/docs` or the openapi snapshot to PRE); also Deployment-C/E configs |
| 9 | I6d BioLogic | `hispec` PSTAT (eclib), `biologiceclib2`, `biologicole` | `ready` reached; one CV per backend; also the Deployment-E bench |
| 10 | I6f galil_motion | `anec`, `eche10` MOTOR | aligner opens (if `enable_aligner`), plate calibration loads from `STATES`; also Deployment-C/E configs |
| 11 | I6e NI-DAQmx — **cellIV check waived 2026-10-22 (user):** cellIV was never deployed and cannot run on the current adss3/anec hardware; the NI host connect and digital IO were verified on ecms3 (2026-10-21) | `adss3` or `anec` NI; also the Deployment-A `io_server`, which wraps `nidaqmx_server.makeApp` | ≥60 s cellIV: row count equal or higher than PRE; `t_s` strictly monotonic in the `.hlo`; the last row's `t_s` is within one buffer-callback period of the action's end (no lost tail, M19b); no `finish drain timed out` |
| 12 | I7 Gamry | `eche10` PSTAT first, then `adss3`, `anec`, `clad`, `ecms3` | one connect line per launch, naming `GamryDriver` on the hosts that use it directly; one CV; also the Deployment-A potentiostat server and the Deployment-B configs that resolve to hte's `gamry_server2` (rule R4). The Deployment-A potentiostat server opened the pstat **twice** PRE (constructor, then `dyn_endpoints`) and opens it **once** POST: record any open or "in use" difference |
| 13 | Gamry IErange fix (follow-up on this branch) | `eche10` PSTAT, then each Gamry model on hand (an IFC1010 station if one exists) | on a resistor: `run_CV` with `IErange=auto`, then the same CV with a fixed `IErange` below the peak current — POST clips |I| at the range limit (PRE did not), and the log line `IE range requested … instrument reports auto-range False, range <index>` shows the requested index; the auto run reports auto-range True (IFC1010: whatever the instrument reports — the driver makes no mode call). Repeat one fixed-range `run_LSV`, `run_CA` and `run_RCA`. Note any change in noise or sense speed: every non-IFC1010 model now enables sense-speed auto-set |

---

## 8. Open questions (each has a default; the tasks implement the default; the executor stops on anything else)

**Decided by the user (2026-10-19), kept here for the record:**
- **Q1 (decided).** Andor's key comes from the host: the first statement of `AndorDriver.connect()` is
  `self.server_key = getattr(self._base_hook, "server_key", None) or self.server_key` (D9). The server-side assignment
  stays.
- **Q4 (decided).** A raising host-managed `connect()` is caught, logged at ERROR with the traceback, alerted, and the
  server starts with the driver disconnected. This applies to every host-managed connect, constructor drivers included
  (A3, D3, Task 1b test 3, the I6 and I7 disconnected-server checks, station check 7).
- **Q5 (withdrawn).** The bind timing does not change (A4).
- **Q6 (decided).** The host sets `_base_hook` on every `HelaoDriver` instance (D2).
- **Q7 (decided).** Seven server-side log lines become one host line (A13). §7 calls this out.
- **Q9 (decided).** Station checks run at the branch head, in §7's order, and bisect to an increment only on a failure.
- **Q10, Q11, Q12 (accepted at the Revision 2 re-review).** Their defaults below stand.

**Pre-existing defects found while planning (recorded, not fixed by this plan):**
- **F1.** `ActionSession.split()` removes the old action's uuid from `listen_uuids` without yielding. Any row of the
  old action not yet consumed by the logger is then skipped and never written. This happens with or without D10
  (Task 7e test 3).
- **F2.** `helao/deploy/hte/drivers/test_station/leancat/` does not import on Linux. Its `logger/__init__.py` imports a
  `main_log` that `logger.py` does not define, and the subtree needs `tenacity` and `opcua`. The construct test
  allowlists the subtree.

**Still open (defaults implemented):**

**Q2. Marshal the put, or the whole call?** (A9, D10) *Default:* build the package on the calling thread, queue it
FIFO, flush on the loop (including before the drain marker), and marshal whenever the running loop is not
`host.aloop`. *Alternative:* the spec's literal "re-dispatch the whole call when no loop is running", which re-reads
`active.action` on the loop and can file a row under a later action after a `split()` (Task 7e test 3).

**Q3. `LeancatDriver` connects in `__init__`,** and the spec classed it as lazy (A1). *Default:* it stays in
`CONSTRUCTOR_CONNECT_PENDING`, checked by AST because its module does not import on Linux, with a named comment. The
ratchet ends at `{LeancatDriver}`, and a follow-up flips it when a station needs it. *Alternative:* flip it in this plan
with Linux gates only.

**Q8. Construct-test config overrides.** Two are settled (D8: `MeerstetterTEC`'s `channel`, `XafsSidecarDriver`'s URL).
*Default:* no others. If Task 0 Step 6 finds more, the main session decides each before Task 1b and the test records it
with a reason.

**Q10. Drain-marker guarantee: a flush, or `sleep(0)`?** (Task 7e note) *Default:* flush the cross-thread deque before
the first marker put. That is deterministic, and it also keeps the on-loop cleanup row behind the rows produced before
it. *Alternative:* the review's `await asyncio.sleep(0)` before the marker, in addition to the flush or instead of it.
Instead of it, the cleanup row could overtake.

**Q11. A disconnected poller after a failed connect** (A3). For formerly constructor-connect drivers, a failed connect
used to mean no server; now the poller polls a disconnected driver. *Default:* rely on each driver's existing
disconnected short-circuit in `get_data()`, proven per class by the recipe's disconnected-poll check. If a driver's
`get_data()` raises when disconnected, stop and report it; do not add a guard unasked.

**Q12. The route set after a raising connect, for the I6 servers** (A3). Today such a connect aborts `dyn_endpoints`
before its routes register. Now the routes register against a disconnected driver, where `galil_enabled`-style gates
allow it. *Default:* accept. It is the same route set a failed-but-not-raising connect produces today, and the user's
Q4 decision asks for "as today when the driver is down". Station check 7 records any difference.

---

## 9. Final done-criteria

- Every COMMIT BOUNDARY passed with its gate evidence in the task report. `git -C $REPO log --oneline BASE..HEAD` shows,
  in order: I0a, I0b, docs (amendment 3), I1, I2, I3, I4, I5, I6a, I6b, I6c, I6d, I6e, I6f, I7.
- No nested-repo commit was needed, or each one is listed with its repo alias and reason.
- `CONSTRUCTOR_CONNECT_PENDING == {"test_station.leancat.driver.LeancatDriver"}`; `CONNECT_ON_STARTUP` holds every class flipped above and no other.
- No `test.skip`, `.only`, stub test or unimplemented branch was added:
  ```
  git -C $REPO diff BASE..HEAD | bash -c "grep -nE '^\+.*(pytest\.mark\.skip|pytest\.mark\.xfail|\.only\(|NotImplementedError|TODO)'"
  ```
  Zero hits.
- The final full sweep's failing set equals `$SCR/H0/failset.txt` minus the four files deleted in I0a.
- The user has completed §7 before merge.
