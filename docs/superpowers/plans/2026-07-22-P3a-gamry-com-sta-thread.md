# P3a Gamry COM STA-thread adapter — design plan

> Sub-slice of the galil/PAL/Gamry special splits (roadmap
> `2026-07-18-P3a-special-splits-roadmap.md` §"Gamry"). **Windows-only
> (comtypes); NOT Linux-runtime-verifiable** — the whole point is COM
> apartment/thread affinity, which only manifests on Windows against a live
> GamryCOM server + potentiostat. Construct-test on Linux; **runtime +
> apartment-affinity verify at-station** before any cut-over. This is the
> highest-risk item in the P3a program: it introduces *new* runtime threading
> semantics (unlike the galil slices, which were behavior-preserving
> delegation/relocation), so it must be built where it can be iterated against
> hardware.

## Status
- **DONE now (Linux-safe prep, this session):** `sys.coinit_flags` moved out of
  module import into `GamryDriver.connect()` (before the first
  `import comtypes.client`). Importing the driver — including on Linux in the
  hexagon import-sweep — no longer mutates a process-global. Value unchanged
  (`0x0` == `COINIT_MULTITHREADED`, also comtypes' own default); connect() is
  the driver's first comtypes user, so the Windows apartment model is
  unchanged. Verified: import sets nothing, pulls no comtypes; pyright delta 0.
- **PLANNED (this doc):** the STA-thread adapter + the §10.4 constructor-connect
  fold. Build + verify at-station.

## Current architecture (legacy `GamryDriver`, driver.py 803 LOC)

All COM work runs **on the caller's thread** in the **MTA** (`coinit_flags=0x0`).
Three distinct COM interaction "strategies" coexist behind one driver:

1. **DC / dtaq-sink** (CV/CA/CP/LSV/OCV/RCA): `setup()` builds a `GamryDtaq*`
   COM object + `GamryDtaqSink` (a `client.GetEvents(dtaq, sink)` event sink);
   `measure()` energizes the cell + `dtaq.Run(True)`; `get_data(pump_rate)`
   calls **`comtypes.client.PumpEvents(pump_rate)`** on the caller thread to
   drive the COM event loop, then drains `dtaqsink.acquired_points`.
2. **EIS / ReadZ** (PEIS/GEIS): `setup_eis()` builds a `GamryReadZ` + a `ReadZ`
   helper (readz.py, its own events); `close_eis()` tears it down. `stop()`
   must check `readz` first (EIS keeps `dtaqsink == DummySink`).
3. **Idle poller** (`GamryPoller.get_data`): samples `MeasureV/I/A` directly on
   the pstat — conflicts with 1/2, idle-only.

`stop()` today branches on *which strategy is live* (readz vs dtaqsink).
`reset()`/`kill_gamrycom()` force-terminate the out-of-process `GamryCOM.exe`
via psutil (supervisor concern). `__init__` calls `self.connect()` (§10.4
constructor-connect violation). `pstat.State()` string parsing in
`get_status`/`get_gamry_state`.

### Why an STA thread
- COM objects have **apartment affinity**. In an MTA, event sinks + `PumpEvents`
  are fragile: `PumpEvents` pumps the *calling thread's* message queue, but MTA
  threads have no STA message pump, so dtaq event delivery relies on COM's MTA
  marshalling and the ad-hoc `PumpEvents` poll. The robust pattern for
  event-sink COM (dtaq `_IGamryDtaqEvents`) is a dedicated **STA** thread that
  (a) `CoInitializeEx(COINIT_APARTMENTTHREADED)`, (b) creates the COM objects,
  (c) runs the message pump, (d) delivers sink callbacks on that same thread.
- Every COM call must then be **marshalled onto that thread** (the pstat/dtaq/
  readz objects live there); results marshalled back via a queue/future.

## Target design — `GamryComThread` owning all COM, behind a native adapter

New module (proposed): `helao/hexagon/adapters/native/gamry_com.py`.

### `GamryComThread`
A dedicated worker thread that OWNS the COM apartment and all GamryCOM objects.
- `start()`: spawn `threading.Thread(target=_run, daemon=True)`. `_run`:
  `sys.coinit_flags` set → `import comtypes` → `CoInitializeEx` (STA) → create a
  request queue consumer loop that **also pumps COM messages** (interleave
  `queue.get(timeout=short)` with `PumpEvents(short)` so dtaq sink callbacks and
  submitted calls both progress) → on shutdown `CoUninitialize`.
- `submit(fn, *args) -> Future`: enqueue a callable to run **on the COM thread**;
  the loop executes it and sets the `Future` result/exception. All pstat/dtaq/
  readz method calls (connect/setup/measure/get_data/stop/cleanup/disconnect/
  setup_eis/close_eis/poll) go through `submit`, so COM objects are only ever
  touched on their owning thread.
- The dtaq event sink stays the existing `GamryDtaqSink`; it is created and
  receives callbacks on the COM thread. `get_data` becomes "on the COM thread,
  the pump has already run; drain acquired_points" — the explicit
  `PumpEvents(pump_rate)` per call is replaced by the loop's continuous pump,
  and `get_data` just snapshots new points (marshalled out).

### `GamryComAdapter` (the HardwarePort-ish native adapter)
- Disconnected construct (§10.4): `__init__(config)` does **zero COM** — no
  thread start, no connect. `connect()` starts the `GamryComThread` and submits
  the open. Mirrors the andor/kinesis `_load_*`/relocate-connect pattern and the
  galil slice-3 adapter.
- Exposes the same verbs as `GamryDriver` (setup/measure/get_data/stop/cleanup/
  disconnect/reset/setup_eis/close_eis/get_status/get_gamry_state) but each is a
  thin `self._thread.submit(...)`; returns the legacy `DriverResponse` verbatim
  (behavior-preserving at the API boundary).
- **Three strategies unified:** the adapter tracks the live strategy
  (`_active: {"dc","eis","idle",None}`) so `stop()`/`cleanup()` dispatch to the
  right teardown without today's implicit readz-vs-dtaqsink branch. The idle
  poller (`GamryPoller`) also submits `MeasureV/I/A` onto the COM thread (fixes
  the current "poller conflicts with measurement" footgun via a single-owner
  thread + the `_active` guard).
- **Supervisor (reset/kill):** `kill_gamrycom()` (psutil, out-of-process kill)
  and the `recover_stale_gamrycom` self-heal stay adapter-level (they act on the
  OS process, not COM objects); `reset()` = tear down the thread → kill → new
  thread → connect.

## §10.4 constructor-connect fold (cross-deployment — coordinate)

Removing `self.connect()` from `GamryDriver.__init__` requires the hosting
server to call `connect()` explicitly (like `galil_dyn_endpoints`). But
`GamryDriver` is imported+constructed by **three** servers:
- `helao/deploy/hte/servers/action/gamry_server2.py` (`gamry_dyn_endpoints`
  waits on `app.driver.ready` then reads `app.driver.model` — set by connect()).
- **private** `Deployment-A/servers/action/potentiostat_server.py`
- **private** `Deployment-D/servers/potentiostat_server.py`
All three must add an explicit `app.driver.connect()` (in their dyn_endpoints /
startup) before touching `app.driver.model`. **Do NOT change the shared
`GamryDriver.__init__` contract without landing the matching server changes in
the two private repos in the same wave** — else those deployments construct a
never-connected driver. For the native adapter this is free (the adapter is
disconnected-construct from day one, connect() started by whoever wires it).

## Construct-test tier (Linux, buildable now if pursued)
- Adapter `__init__` touches no COM / starts no thread (assert, no comtypes in
  `sys.modules`).
- `GamryComThread.submit` executes callables on the worker thread and returns
  results/exceptions through the Future — testable with a **fake COM object**
  (no comtypes): prove marshalling + ordering + the interleaved-pump loop's
  liveness, and that a submitted exception propagates.
- `_active` strategy state machine transitions (dc/eis/idle/None) unit-tested.
- Import-sweep: module imports on Linux with comtypes absent (lazy import inside
  the thread `_run`).

## AT-STATION GATE (must pass before cut-over)
Windows + live GamryCOM + potentiostat: run OCV/CV (dtaq-sink), PEIS (ReadZ),
and the idle poller; confirm data parity vs legacy (golden diff — the existing
`golden_diff.bat` harness), that dtaq events deliver on the STA thread without
missed points, that stop/estop halt mid-measurement, that reset/kill recover a
hung `GamryCOM.exe`, and — critically — **apartment affinity**: no cross-thread
COM call escapes the owning thread (would raise `RPC_E_WRONG_THREAD` /
`CoInitialize`-not-called). Verify the golden OCV byte-parity still holds.

## Risks / open questions
- STA message-pump + `queue.get` interleaving cadence vs the current explicit
  `PumpEvents(pump_rate)` — event delivery latency/coalescing may shift the
  sampled-point cadence; validate against a golden CV.
- `ReadZ` (readz.py, 439 LOC) has its own events loop — must also move onto the
  COM thread; audit its `PumpEvents`/event usage during the build.
- Whether STA is even required vs staying MTA-with-a-dedicated-pump-thread: STA
  is the textbook fit for event-sink COM, but if legacy MTA+PumpEvents has been
  reliable at-station for years, a lower-risk variant is a dedicated **MTA**
  worker thread (single-owner, continuous pump) WITHOUT switching apartment —
  decide at-station based on observed event reliability.
