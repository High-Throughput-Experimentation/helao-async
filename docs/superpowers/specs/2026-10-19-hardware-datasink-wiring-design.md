# Hardware / DataSink port wiring: design

**Date:** 2026-10-19 · **Branch:** `feat/hexagon-completion` (measured at `ba910c4c`) · **Amends:** master spec `2026-07-16-framework-hexagonal-rewrite-design.md` §4.3.1, §4.3.2, §4.5, §10.4
**Scope:** `helao/hexagon/{ports,adapters,app}`, `helao/core/drivers/helao_driver.py`, `helao/deploy/hte/{drivers,servers}`. Private deployments are touched only where they import an hte driver class (§5, rule R4).

## 1. Problem: what the code does today

The ports were declared in P1a. The host never routed through them. Every number below was measured on the current tree with tests excluded.

### 1.1 PortWiring slots

| slot | assigned by `build_wiring` | read anywhere | evidence |
|---|---|---|---|
| `hardware` | no | no | `HardwarePort`'s only implementors are `LegacyDriverHardwareAdapter` and `GalilMotionHardwareAdapter`, and only tests construct them. Stations run `NativeGalilMotion`, which is a `HelaoDriver`, not a `HardwarePort` (`servers/action/galil_motion.py:954`). |
| `data_sink` | yes (`NativeDataSinkAdapter()`) | **no** | It is in `ACTION_REQUIRED`, so the fail-loud gate requires a slot nobody consumes, which makes that gate vacuous. `for_action()` has zero production callers. |
| `sample_state` | no | no | The Protocol does have a real consumer, `PalReconciliation`. PAL composes that consumer itself: `SampleShimAdapter(SampleArchiveShim(world_config))` at `pal_driver.py:223-228`. |
| `ui_host` | no | no | Nothing calls `require("ui_host")`. The one real consumer builds its host directly: `GalilAlignerHost(ui_host=BokehServerUiHost())` at `galil_motion.py:218`. Nothing calls `build_ui_app`, and it raises `HexagonDeferred`. |

### 1.2 What `ActionHost` actually calls on a driver (`action_host.py:1534-1555`, `:1117-1121`, `:1253`, `:1638-1642`)

- Construct with `cls(config=server_params)`, or with `cls(host)` for the bare test sims.
- Set `poller._base_hook = self`.
- Call `get_status()` synchronously inside a sync route, so it runs in the threadpool.
- `await estop(switch=)`, but only if the driver has `estop`.
- Call `shutdown()` synchronously, then `await async_shutdown()`, each only if present.
- **It never calls `connect()` and never calls `disconnect()`.**

Consequences of the missing `connect()`:
- **8 drivers connect inside `__init__`:** gamry, alicat, legato, sprintir, mecom, kinesis, cm0134 and simdos. Seven of them have a poller, and the poller starts at construction and needs an open device. `test_poller_drivers_connect_in_init.py` pins this workaround. The kinesis disconnected-construct test is `xfail`.
- **7 servers call `app.driver.connect()` in `dyn_endpoints`:** spec, andor, biologic, nidaqmx, galil_motion, galil_io and gamry_server2. Gamry therefore connects twice. power_supply connects per action inside its executors.

### 1.3 Defects in the never-wired members

- `LegacyDriverHardwareAdapter` runs every member through `asyncio.to_thread`. All 12 hte `estop` methods and 4 of the 28 `stop` methods are `async`. Through the adapter, estop/abort would return a coroutine that is never awaited: **a silent no-op E-STOP.**
- `DataSinkPort.finish_hlo_header` is declared `async` and loop-affine. Its two real callers, the NI-DAQmx buffer callback (`nidaqmx_driver.py:469`, foreign thread) and PAL, both call it **synchronously**. The real body (`data_file.py:161`) is sync and does no I/O.
- The "THREAD-SAFE" claim on `enqueue_data_nowait` is false for the implementation. `data_stream.py:135` calls `asyncio.Queue.put_nowait` on every subscriber queue straight from the NI thread. asyncio queues are not thread-safe, and the waiter is woken without waking the selector. Rows are not lost, but each one is delivered whenever the loop next wakes for some other reason. This is not a legacy-only problem: the native body is what runs today.

### 1.4 Reach-ins into the host (hte)

| category | master spec | today | notes |
|---|---|---|---|
| `active.action` in `drivers/` | 72 | **57** (11 files) | 31 are `action_params`. Each is an executor reading its own action, which is its input contract, not a host reach-in. |
| `active.action` in `servers/` | n/a | 400 | 285 `action_params`, 45 `error_code`. Same reasoning. |
| full-host `active.base` in `drivers/` | 18 | **18** (2 of them commented out) | `get_lbuf`, `server_params`, `world_cfg`, `helaodirs`, `put_lbuf`, `dflt_file_conn_key` |
| `_base_hook` | n/a | 33 lines / 7 files, plus `NativeGalilMotion` (4) and `DriverPoller` (1) | Three servers assign it to the driver (andor, galil_motion, nidaqmx). |
| **host reads from hardware-side classes** (AST scan of the 64 `Executor`/`HelaoDriver`/`DriverPoller` subclasses, plus `getattr(_base_hook, "…")` reads) | n/a | **30 reads, 15 files, 9 distinct members** | `get_lbuf` 12, `helaodirs` 7, `actionservermodel` 4, `server_params` 3, `put_lbuf` 2, `dflt_file_conn_key`, `world_cfg`, `executors`, `poller` 1 each |
| `active.driver` (executor reaching its own driver) | n/a | 47 | Legitimate. Out of scope. |
| polling-flag handshakes | AliCat, legato, Advantech | AliCat: 12 `stop_polling`/`start_polling` brackets. SIMDOS: 5. Legato: `com_lock` plus a sync `_send_sync` fork for the poller. NI-DAQmx: one pause pair. Four private `/start_polling` and `/stop_polling` routes (mfc, kinesis, diapump, syringe). | The Advantech handshake is in a private deployment and out of scope. `ExclusiveAccess` has zero implementors. |
| foreign-thread callback | NI-DAQmx | 1 (`streamIV_callback`) | It already receives 3 injected callables (`arm_cell_iv`). It also reads `_base_hook.get_lbuf` and the estop flag. |
| PAL per-job Active | `Active` injected | Already typed as `_PALActiveContext(DataSinkPort, Protocol)` | Residual surface: `.action` (14 writes), async `get_realtime` (1), sync `finish_hlo_header` (1) |

**Reading.** B7b deleted the legacy engine, so `active.base` is now `ActionHost` itself (`host.base is host`). What remains is untyped coupling to roughly 70 host members, not a legacy dependency. Hardware-side code uses 9 of those members. Every reach-in therefore needs typing and a gate. None of them needs a rewrite.

## 2. Options

| | A. Wire as declared | **B. Host-owned lifecycle, trimmed ports (chosen)** |
|---|---|---|
| Hardware | Put `PortWiring.hardware = LegacyDriverHardwareAdapter(driver)` and route the host through it. | `HelaoDriver` stays the hardware contract, and the host calls `connect()`. |
| DataSink | Have `ActionSession` hand `data_sink.for_action(self)` to executors. | `ActionSession` already satisfies the trimmed `DataSinkPort` structurally. Delete both adapters and the slot. |
| `_base_hook` | Collapse it into the per-action DataSink (master spec §4.3.1). | Type it as a new host-scoped `DriverHostPort` (§3.3) and gate it with an AST test. |
| Why A fails | 1. The `to_thread` E-STOP no-op (§1.3). 2. The 318 `app.driver.<verb>` and 47 `active.driver.<verb>` calls are driver-specific verbs that no lifecycle Protocol carries. 3. `arm`/`start`/`drain`/`cleanup` have zero host callers. 4. A poller outlives every action, so a per-action sink cannot replace `_base_hook`. 5. `NativeDataSinkAdapter` rebuilds collaborators that `ActionSession` already owns, giving a second write path that could drift. | |

A third option was rejected: keeping `HardwarePort` trimmed to `{connect, get_status}`. That is a second definition of a subset of the `HelaoDriver` ABC, and the two would drift.

## 3. Port surfaces

### 3.1 Hardware: `HelaoDriver` (`helao/core/drivers/helao_driver.py`)

- The ABC is unchanged: `connect`, `get_status`, `stop`, `reset` and `disconnect`, all returning `DriverResponse`.
- Add one class attribute: `connect_on_startup: ClassVar[bool] = False`. This is a real per-driver declaration, not migration scaffolding. power_supply connects per action and the lazy drivers stay `False`.
- `estop`, `shutdown` and `async_shutdown` stay optional hooks that the host looks up with `getattr`, exactly as today.
- **Delete:** `HardwarePort`, `ExclusiveAccess`, `driver_response_to_error_code` (zero callers; the 33 inline `resp.response == success` compares stay), `LegacyDriverHardwareAdapter`, `GalilMotionHardwareAdapter` (superseded by `NativeGalilMotion`), and their tests.

Bus exclusivity is a concern inside each driver. Pollers call `get_data()` synchronously on the loop, so the existing flag and lock handshakes cannot interleave with a sync command. Legato's `com_lock` already covers its one awaiting `send`. Add a lock only when a driver moves poll I/O off the loop.

### 3.2 `DataSinkPort` (per action; `ActionSession` satisfies it, no adapter)

| member | class | real callers (hte) |
|---|---|---|
| `enqueue_data_nowait(datamodel, action=None) -> None` | **thread-safe** | xafs executor; NI callback via `arm_cell_iv` |
| `get_realtime_nowait(epoch_ns=None, offset=None) -> int` | **thread-safe** | NI callback; PAL ×2 |
| `finish_hlo_header(file_conn_keys=None, realtime=None) -> None` | **thread-safe, now sync** (signature corrected) | NI callback; PAL |
| `async enqueue_data(datamodel, action=None)` | loop | PAL |
| `async write_file(...)` / `write_file_nowait(...)` | loop. The `_nowait` name is historical; the THREAD-SAFE claim is dropped because there is no off-loop caller. | xafs / PAL |
| `async track_file(file_type, file_path, samples, action=None)` | loop | xafs, axiscam |
| `async append_sample(samples, IO, action=None)` | loop | NI ×2, PAL ×2 |
| `async split(uuid_list=None, new_fileconnparams=None) -> list[UUID]` | loop | NI, PAL |
| `set_estop(action=None)` | loop (claim dropped) | PAL |

**Delete from the port:**
- `enqueue_data_dflt`: only endpoint code calls it, and it holds the session anyway. The method stays on `ActionSession`.
- `put_lbuf`, `put_lbuf_nowait` (zero callers) and `get_lbuf`: these are host-scoped and move to §3.3.
- `NativeDataSinkAdapter`, `ActiveDataSinkAdapter`, `PortWiring.data_sink`, and the `"data_sink"` entry in `ACTION_REQUIRED`. `FakeDataSink` shrinks to the trimmed surface.

**Thread-safety fix (made true, not just claimed):**
- `NativeDataStreamer.enqueue_data_nowait`: when there is no running loop on the calling thread, re-dispatch the whole call with `host.aloop.call_soon_threadsafe(...)`. All callers route through this one place. Rows and their order are unchanged; only the thread that performs the put changes.
- `get_realtime_nowait` is pure arithmetic, and `finish_hlo_header` does a GIL-atomic field assignment that happens-before the marshalled enqueue. Both stay direct.

### 3.3 `DriverHostPort` (host-scoped; `ports/hardware.py`; `ActionHost` satisfies it, no adapter)

What a driver, poller or executor may read from its host. The members are the names `ActionHost` already uses, so there is no rename churn.

| member | thread | callers |
|---|---|---|
| `get_lbuf(key) -> tuple` | **safe** (dict read) | 6 monitor executors; galil_io; NI callback; kinesis |
| `async put_lbuf(live_dict) -> None` | loop | `DriverPoller`; legato |
| `helaodirs` (`.save_root`/`.states_root`/`.db_root`) | read-only | andor, galil ×2, axiscam, biologic, xafs |
| `actionservermodel` (`.estop` read only) | **safe** (bool read) | NI callback; galil ×2; gamry |
| `executors` | loop | SIMDOS fault sweep |
| `server_params`, `world_cfg` | read-only | alicat (co2 peer lookup), legato, kinesis |
| `dflt_file_conn_key()` | loop | NI `CellIVExec` |
| `poller` | read-only | kinesis executor (`live_dict`) |

- Annotate `DriverPoller._base_hook`, each driver's `_base_hook`, and `ActionSession.base` as `Optional[DriverHostPort]`.
- **Gate:** add `helao/hexagon/tests/test_driver_host_surface.py`. It walks hte and `hexagon/adapters/native` for classes deriving (transitively) from `Executor`, `HelaoDriver` or `DriverPoller`. Any `.base.X`, `._base_hook.X` or `getattr(…_base_hook…, "X")` where `X` is not a member of `DriverHostPort` fails the test.
- The allowed set equals the measured set, so the gate is green on day 1 and stops further growth.
- Endpoint closures inside `makeApp` are the inbound-adapter layer and are exempt.

### 3.4 `sample_state` and `ui_host`: delete the slots, keep the Protocols

- **`sample_state`:** PAL is the only consumer and builds its own I/O-free shim from `world_config`. Wiring would mean injecting a collaborator into a `config=`-only constructor, for one caller. The Protocol stays because `PalReconciliation` needs it.
- **`ui_host`:** the aligner already takes `ui_host` as a parameter and stays injectable. A slot adds nothing. Keep `UiHostPort.start_document_host`/`stop` and `BokehServerUiHost`. Delete `build_ui_app` (open question Q3).

`PortWiring` loses `hardware`, `data_sink`, `sample_state` and `ui_host`.

## 4. Host-owned lifecycle (the actual wiring)

`ActionHost` startup, per driver:

```text
construct cls(config=server_params)
→ inst._base_hook = self                       # HelaoDriver instances only; replaces the 3 server-side assignments
→ if cls.connect_on_startup: inst.connect()    # sync, same timing as today's ctor/dyn_endpoints connect
→ poller (already gets _base_hook = self)
→ dyn_endpoints_init()                          # galil/nidaqmx endpoint gating still sees a connected driver
```

- An exception raised by `connect()` propagates. That matches both connect sites it replaces: drivers that tolerate a missing device already handle it inside `connect()`.
- The returned `DriverResponse` is logged.
- Teardown is unchanged: stop the poller, then `shutdown`/`async_shutdown`.

**Disconnected-construct guarantee (Linux CI):** add `helao/hexagon/tests/test_driver_disconnected_construct.py`.
- It imports every module under `helao/deploy/hte/drivers` plus `hexagon/adapters/native`, which supersedes the partial lists in `test_hardware_import_sweep.py`.
- It constructs every `HelaoDriver` subclass from a per-class minimal config (taken from the first hte config's `params:` block, or `{}`) under an I/O tripwire. The tripwire patches `socket.socket.connect`, `serial.Serial`, `ctypes.CDLL`/`WinDLL` and `subprocess.Popen`, and installs `sys.modules` sentinels for `gclib`, `nidaqmx`, `comtypes`, `pylablib`, `minimalmodbus` and `mecom`. Any trip fails the test.
- **Ratchet:** a `CONSTRUCTOR_CONNECT_PENDING` set starts with the 8 drivers from §1.2, and the test asserts each listed driver *does* trip. A driver that stops tripping fails the test until it is removed from the list.
- Each increment shrinks the list, and it ends empty.

## 5. Increments (canary first, ordered by risk)

**Rules for every increment:**
- **R1.** Lands alone. Rollback is reverting that commit.
- **R2.** Zero route or param changes.
- **R3.** Driver behaviour changes only in where `connect()` is called from.
- **R4.** Before flipping a driver class, grep each nested private deployment for imports of that class. Any server there that calls `connect()` itself is updated in that repo in the same window.

| # | scope | risk | station (hte config) |
|---|---|---|---|
| I0 | **Framework, no driver behaviour change.** Every deletion in §3. `DataSinkPort` trim plus the sync `finish_hlo_header` (PAL's `_PALActiveContext` residual shrinks). `DriverHostPort` plus its AST gate. Host-assigned `_base_hook`. `connect_on_startup` flag and host connect step (all drivers `False`). Disconnected-construct test with ratchet. Golden scenario 14 captured on the *current* code before the marshalling fix lands. | low | none (Linux only) |
| I1 | **Canary:** SprintIR, CM0134. Read-only gas sensors with pollers. Drop the constructor `connect()` and set `connect_on_startup = True`. | lowest hardware | `ccsi2` (co2sensor). CM0134 is in no hte config, so it is Linux-only. |
| I2 | MeerstetterTEC (temperature actuation) | low-med | `anec` |
| I3 | SIMDOS, KDS100 legato (fluid actuation; SIMDOS fault sweep via host `executors`) | med | `ccsi2` (diapump, syringe); syringe also in `clad`, `adss3` |
| I4 | AliCat MFC (gas flow; co2 peer via `world_cfg`; 12 handshake brackets left as is) | med | `ccsi2`, `ecms3` |
| I5 | Kinesis (motion). The `xfail` becomes a pass and is removed. | med | `eche10`, `hispec` |
| I6a-d | Servers whose `dyn_endpoints` connect is deleted, one per commit: SM303 (spec), Andor, galil_io, BioLogic (all 3 backends) | med | `eche10` / `hispec` / every galil_io config / `biologiceclib2`, `biologicole`, `clad` |
| I6e | NI-DAQmx: `dyn_endpoints` connect deleted, **plus the `enqueue_data_nowait` marshalling fix** | high (foreign thread) | `adss3` or `anec` (cellIV) |
| I6f | galil_motion / `NativeGalilMotion`. The host connects after setting `_base_hook`, which preserves the `helaodirs`-before-connect order. | high (motion, aligner) | `anec` / `eche10` |
| I7 | Gamry. Removes the double connect. COM apartment. Rule R4 applies: the driver is shared with private deployments. | highest | `eche10` first |

PAL needs no increment: it is type-only and covered by I0. power_supply stays `connect_on_startup = False`.

## 6. Gates

**Every increment, on Linux:**
1. `python run_tests.py`: all green, with `ENV` allowed only for vendor imports.
2. `python helao/core/tests/test_active_golden_master.py --check`: 13/13 unchanged, plus scenario 14 after I0.
3. `python helao/core/tests/test_orch_dispatch_golden_master.py --check`: unchanged.
4. Endpoint checklist (`helao/hexagon/tests/test_hte_route_checklist.py` and its frozen JSONs): unchanged, with no `_additions` / `_param_additions` entries. This includes the `/start_polling` and `/stop_polling` routes.
5. `test_driver_disconnected_construct.py` and `test_driver_host_surface.py` pass, with the pending list shrunk by exactly the increment's drivers.
6. `pyright` on the changed files, run on the real path and not under `.claude/worktrees/`.
7. `black` on the changed files.

**New tests: each must be shown failing against a mutation before it is accepted:**
- **Host order** (I0, `ActionHost` with a fake driver and poller). With the flag `True`, the recorded order is `__init__ → _base_hook → connect → poller → dyn_endpoints`; with it `False`, `connect` is never called. *Mutation:* delete the host connect step.
- **Golden scenario 14, `nowait_from_foreign_thread`.** A `threading.Thread` calls `get_realtime_nowait`, `finish_hlo_header` and `enqueue_data_nowait` ×N, is joined, and then `finish()` runs. The `.norm` must be byte-identical to the I0 capture. `_RecordingMSQ.put_nowait` records `threading.get_ident()`, and the test asserts it equals the loop thread. *Mutation:* reverting the marshalling must fail on the thread-id assertion; the rows would still match. Capture into a tmp root only.
- **Ratchet and AST gate:** add one forbidden `_base_hook.X` read and one constructor `connect()`, and both must go red.

**Per increment I1-I7, user-run on the Windows station:**
1. Launch with `helao.bat <config>`.
2. `/get_status`: `_driver_status` is not `unknown`.
3. For poller drivers: `/get_lbuf` is non-empty and its epoch advances over 30 s.
4. Run one action of the family, then an E-STOP latch and release.
5. `CTRL-r` restart of that server: it reconnects once and the log shows no second connect.
6. `CTRL-x`: teardown is clean, with no `get_data` spam after disconnect.
7. Device unplugged at launch: the server starts, or fails, exactly as it did before the increment.
8. On-station golden diff (master §6.6) of the station's smoke sequence, with no control panel operated.

- **I6e also:** run a cellIV for at least 60 s, then compare the row count and the `t_s` monotonicity of the `.hlo` against a pre-increment capture.
- **I7 also:** run the private-deployment Gamry server(s) under rule R4.

## 7. Not doing

- Rewriting the 457 `active.action` reads or the 47 `active.driver` reads. They are the executor's own inputs.
- Changing executor error mapping (the 33 inline compares).
- Giving drivers async-first lifecycles or `to_thread` offload.
- Replacing the polling handshakes, or migrating the Advantech one (private deployment).
- Moving PAL's `.action`/`get_realtime` residual into the port.
- Migrating `Archive` (constructed with the host; master §4.3.11).
- Changing `NotifyPort` or `HealthPort`.
- Deleting the legacy `galil_motion_driver.Galil` class. It is still imported for enums and by 3 experiment libraries; that is a follow-up.
- Fixing SIMDOS's poller `time.sleep` on the loop. That is a separate defect.
- Any WS, route or config-key change.

## 8. Open questions (each has a recommended default)

1. **Keep the attribute name `_base_hook`, or rename it to `host`?** Renaming touches about 40 lines and the tests, with no behaviour gain. *Default: keep `_base_hook`; the type carries the meaning.*
2. **Ship the `enqueue_data_nowait` marshalling fix in I6e, or defer it?** Rows are delivered today, only late. *Default: ship it in I6e. The port claims thread safety and the fix is a single branch behind a falsifiable test.*
3. **Delete `UiHostPort.build_ui_app` now?** Its P7f consumer has not landed and Reflex is hosted outside the hexagon. *Default: delete it now, and re-add it alongside its consumer.*
4. **Should power_supply connect at startup?** No hte config launches it, so it cannot be verified at a station. *Default: no. It keeps per-action connect and `connect_on_startup = False`.*
5. **Should drivers that connect lazily today (PAL, xafs, calc, HTEdata, axiscam, Netbooter, leancat) opt in?** *Default: no. Each one opts in only when a station issue calls for it.*
6. **Should the canary (I1) wait until CM0134 has a station?** *Default: no. SprintIR at `ccsi2` is the station canary; CM0134 rides on its Linux gates.*
7. **Amend the master spec in-line, or with an amendment file?** This spec changes §4.3.1 (Protocol to ABC, `ExclusiveAccess` dropped), §4.3.2 (surface trimmed, `_base_hook` no longer collapses into DataSink) and §10.4 (the ratchet). *Default: write a short amendment file pointing here, following the `2026-08-08-hexagonal-rewrite-amendment-2.md` precedent.*
