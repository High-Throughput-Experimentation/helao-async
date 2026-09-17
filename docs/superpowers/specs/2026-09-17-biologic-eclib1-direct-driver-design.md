# BioLogic `eclib` backend, rewritten directly against the EC-Lab Development Package

Date: 2026-09-17
Status: design approved, not implemented
Scope: `helao/deploy/hte/drivers/pstat/biologic/`, `helao/deploy/hte/servers/action/biologic_server.py`, `helao_dev_{win,linux}-64.yml`, `helao/hexagon/tests/`

## 1. Why

`helao/deploy/hte/drivers/pstat/biologic/` reaches a BioLogic potentiostat
through [easy-biologic](https://github.com/onepunchdan/easy-biologic), pinned in
both env files as a zip of a fork's `main`. This replaces that path with a
driver that calls the EC-Lab Development Package (EClib1) directly.

Four things drive it, all named by the station owner:

1. **Drop the third-party wrapper from the hardware path.** It is a pinned
   archive of a fork's moving branch, and every defect below has to be fixed in
   it rather than here.
2. **Four specific defects** (§6), each of which the wrapper's shape either
   causes or hides.
3. **Techniques EClib1 has and easy-biologic does not expose**: CALIMIT,
   CPLIMIT, SPEIS, SGEIS, and arbitrary linked-technique plans.
4. **Multi-channel is unused.** Every station runs one channel at a time
   (`hispec` declares `num_channels: 1`), and the per-channel dicts are
   complexity with no consumer.

This is a **replace-in-place** change, chosen deliberately over a fifth backend
entry: the package path, the class name `BiologicDriver` and the
`pstat_backend: eclib` key are all kept, the easy-biologic dependency is
deleted, and every BioLogic station moves on its next launch. The four station
configs that declare a BioLogic server — `hispec`, `odspechw`, `clad`, `adss3` —
need no edit and get no opt-out. Rollback is a revert of the merge, which is why
§8 requires a freeze branch and an at-station gate before it lands.

The SDK lives at `/mnt/k/experiments/eche/Installation packages/EC-Lab
Development Package/`: `lib/` (DLLs, 118 `.ecc`, `kernel*.bin`),
`Examples/Python/` (BioLogic's own `kbio` ctypes layer plus CP and OCV
examples), and `EC-Lab Development Package.pdf` (§7 documents every technique's
parameters, record layout and required conversions).

**EClib1 is not EClib2.** The `biologic_eclib2` backend targets EC-Lib 2.0,
which is not backwards compatible with these DLLs — no `blfind64.dll`, no
`BL_GetData`, no `.ecc` files, kernel6 firmware. The two are separate SDKs over
separate wire protocols and neither supersedes the other. This work does not
touch `biologic_eclib2` or `biologic_ole`.

## 2. Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Replace in place; keep path, class name and `eclib` key | No config edits; no migration period the station owner does not want |
| D2 | Mirror the `biologic_eclib2/` module split | Proven in-tree shape for a path-loaded vendor SDK |
| D3 | Write our own ctypes binding; do not vendor `kbio` | Every shipped file carries the BioLogic OEM Package licence header, and the parent repo is a public remote |
| D4 | Vendor assets load from a configured `sdk_path`; nothing committed | Licence, plus `.ecc` files are per-EC-Lab-release and a committed copy silently pins a technique encoding the firmware may not match |
| D5 | Single active channel; `channel` stays in every signature | Matches actual use; `BiologicExec` and the endpoints are untouched |
| D6 | Board family from `GetChannelBoardType`, driving both `.ecc` suffix and record layout | One source of truth; the channel board, not the chassis, is what holds the technique |
| D7 | Emitted columns frozen for the 7 existing techniques | Two `biologic_vis` panels and five experiment libraries key off these names; a rename renders nothing and logs nothing |
| D8 | CAOCV becomes a two-entry linked plan, keeping its endpoint keys | The plan machinery exists for `run_plan` anyway; a hardcoded pair is the special case |
| D9 | Parameter labels and record layouts taken from the PDF, asserted against the DLL | The wrapper's tables disagree with the PDF in at least two places (§6.5) |
| D10 | `loop_N_times = -1` refused | The PDF's "mandatory goto, unlimited" — an action that never terminates parks the orchestrator with no error anywhere |
| D11 | Fix the `SweepMode` coercion; endpoint default stays `"log"` | The parameter has never reached the instrument (§6.8). Default EIS sweeps become logarithmic, which is what every caller and every record already claimed |
| D12 | Honour CAOCV's `CA_ERange`; drop the derived override | Every other technique honours its `ERange` (§6.9) |

## 3. Architecture

Package contents replaced; package identity kept.

| module | responsibility |
|---|---|
| `vendor.py` | Locate and `WinDLL`-load `EClib64.dll` from `sdk_path`. ctypes signatures, structs (`TDeviceInfos_t`, `TChannelInfos_t`, `TCurrentValues_t`, `DataInfo`, `TEccParam_t`/`TEccParams_t`), error-code table, board-type → `.ecc`/`kernel*.bin`/`*.xlx` asset resolution. |
| `eclib_client.py` | Serialized gateway over `vendor`. `Connect`, `Disconnect`, `TestConnection`, `GetChannelInfo`, `GetChannelBoardType`, `LoadFirmware`, `LoadTechnique`, `Define{,Bool,Sgl,Int}Parameter`, `UpdateParameters`, `GetTechniqueInfos`, `GetParamInfos`, `StartChannel`, `StopChannel`, `GetData`, `GetCurrentValues`, `GetMessage`, `ConvertChannelNumericIntoSingle`, `ConvertTimeChannelNumericIntoSeconds`, `GetErrorMsg`. Raises `EclibError` carrying the vendor code's *name*. |
| `technique.py` | `BiologicTechnique`: `.ecc` stem, ECC parameter table, action-key mapping, column plan. 11 techniques, plan assembly, TTL bracketing. |
| `data.py` | Record unpacking: layout tables per `(technique, board_family, process_index)`, time reconstruction, derived columns, done-detection. |
| `sim.py` | Fake DLL at the `vendor` boundary. Selected by `simulate: true` on server params. |
| `driver.py` | `BiologicDriver(HelaoDriver)`, single channel. |
| `enum.py` | `EC_IRange` / `EC_ERange` / `EC_Bandwidth` `StrEnum`s resolving to our own int table. |

`BACKENDS` and `TECHNIQUE_REGISTRIES` in `biologic_server.py` keep their
`"eclib"` entries unchanged. `BACKENDS` stays annotated
`dict[str, type[BiologicBackend]]`, which is what makes the protocol's
conformance claim non-vacuous.

Three consequences:

**`enum.py` becomes hermetic.** It currently lazy-imports
`easy_biologic.lib.ec_lib` solely to map a string alias onto a vendor enum
member spelled identically. With our own int table the lazy-import indirection
and its `lru_cache` are deleted.

**`blfind64.dll` is never loaded.** Every station config names an explicit IP.
Device discovery is the module that makes `easy_biologic` unimportable
off-Windows; dropping it costs nothing.

**Nothing vendor-licensed enters the repo.** `sdk_path` defaults to
`C:\EC-Lab Development Package\lib`. `.ecc`, `kernel*.bin`, `*.xlx` and
`EClib64.dll` stay on the station.

Dependency removal: the easy-biologic archive URL drops from
`helao_dev_win-64.yml:14` and `helao_dev_linux-64.yml:14`. The only other repo
reference is a comment at `helao/deploy/hte/experiments/HISPEC_exp.py:507`.

## 4. Technique layer

```
BiologicTechnique:
    technique_name : str                  # "CA"; registry key, unchanged
    ecc_stem       : str                  # "ca" -> ca.ecc / ca4.ecc / ca5.ecc
    param_table    : dict[str, EccType]   # ECC label -> float|int|bool + arity
    parameter_map  : dict[str, str]       # action key -> ECC label, keys unchanged
    column_plan    : tuple[str, ...]      # canonical HELAO column names
```

`technique.py` owns what goes *down*; `data.py` owns what comes *back*. Record
layouts live in `data.py`.

**`.ecc` resolution by measured board type** (per the vendor CP example's own
`match`): `ESSENTIAL` → `ca.ecc`, `PREMIUM` → `ca4.ecc`, `DIGICORE` →
`ca5.ecc`. easy-biologic instead picks from its vendored `techniques-6.08` set
regardless of what the channel reports.

**11 techniques.** OCV, CA, CP, CV, PEIS, GEIS, CAOCV (existing), plus CALIMIT,
CPLIMIT, SPEIS, SGEIS. Plus `run_plan`.

**CAOCV is a two-entry plan.** Its endpoint keys (`CA_Vval__V_list`,
`CA_Tval__s_list`, `CA_AcqInterval__s`, `CA_IRange`, `CA_ERange`,
`CA_Bandwidth`, `OCV_Tval__s`, `OCV_AcqInterval__s`) and its recorded
`action_params` stay byte-identical.

**TTL is two real techniques.** TI (id 152) or TO (id 151) loaded at index 0
with `first=True`; the measurement at index 1. The
`{"ttl", "ttl_logic", "ttl_duration"}` dict `BiologicExec` builds is kept
verbatim, so the executor and every endpoint are untouched. After loading,
`GetTechniqueInfos` reads the channel's technique list back and `setup` fails if
the trigger is not at index 0.

**LOOP for plan repeats.** `loop_N_times` plus `protocol_number` (0-based index
of the technique to return to). Two traps:

- Loop bounds are given over **plan entries** while the channel holds a
  **flattened** technique list. A prepended TTL shifts every index; CAOCV
  occupies two slots; a future entry may expand further. Entry index → loaded
  index is mapped explicitly, the way the eclib2 plan does it. Getting this
  wrong repeats the wrong span and the instrument never complains.
- `loop_N_times = -1` is refused (D10).

**Off-by-one conventions are per-technique and pinned by tests.** CALIMIT's
`Step_number` is documented "number of steps minus 1"; the vendor CP example
passes `idx`, not `len(steps)`; PEIS/SPEIS pass `Step_number = 0`. Arrays are
fixed 20-wide for CA/CP/CALIMIT/CPLIMIT.

**`Test{1,2,3}_Config` gets an explicit encoder.** It is a packed 32-bit word
(variable / sign / logic / active fields) per PDF §7.37.2, transcribed into the
test rather than inferred. An incorrectly packed limit is a cell driven past the
threshold that was supposed to stop it — this is the one parameter in the set
whose misencoding is a hardware-safety matter, not a data matter.

## 5. Data layer

`BL_GetData` returns `(CurrentValues, DataInfo, buffer[1000 × int32])`.
Unpacking is a table lookup keyed `(technique, board_family, process_index)`
plus a conversion pass — no per-technique lambdas.

**Board family from `GetChannelBoardType`** (D6): `ESSENTIAL` → VMP3-series
layout; `PREMIUM`/`DIGICORE` → VMP-300-series layout. easy-biologic keys layouts
off `device.kind`, the chassis code, while the technique encoding follows the
channel board; in a mixed-board chassis those disagree and a record is decoded
against the wrong column count.

Layout differences, confirmed against PDF §7:

| technique | VMP3 series | VMP-300 series |
|---|---|---|
| OCV | `t_high t_low Ewe Ece` | `t_high t_low Ewe` |
| CV | `t_high t_low Ec <I> <Ewe> Cycle` | `t_high t_low <I> <Ewe> Cycle` |
| CA / CP / CALIMIT / CPLIMIT | `t_high t_low Ewe I Cycle` | same |
| PEIS / GEIS process 1 | 15 cols, trailing `Irange` | 14 cols |
| SPEIS / SGEIS | PEIS layout plus `step`, both processes | same plus `step` |

PEIS/GEIS process 0 is `t_high t_low Ewe I` on both families; process 1 is
`freq |Ewe| |I| PhaseZwe Ewe I - |Ece| |Ice| PhaseZce Ece - - t [Irange]`.

**Time uses the vendor conversion.**
`BL_ConvertTimeChannelNumericIntoSeconds` for process 0, as §7.x.4 prescribes.
easy-biologic hand-rolls `TimeBase * ((t_high << 32) + t_low)` instead.
Process-1 `time` is a float through `ConvertChannelNumericIntoSingle`.
`DataInfo.StartTime` offset retained, `NaN` treated as 0 as today.

**Derived columns stay bit-identical to what `eclib` records now**:
`P_W = Ewe * I` (signed), `modulus = |Ewe| / |I|`,
`X_ohm = -modulus·sin(phase)`, `R_ohm = modulus·cos(phase)`, with the existing
`NaN`-fill fallback when modulus or phase is unexpected. Noted and deliberately
not reconciled: the OLE backend derives `P_W` as `|Ewe·I|`, so the two backends
already disagree on sign. The column contract compares names, not values.

**Done-detection replaces the `State > 0` test.** `PROG_STATE` is
`STOP=0, RUN=1, PAUSE=2, SYNC=3`. Three parts:

- A channel polled between `StartChannel` and the firmware actually running
  reads `STOP`. One `RUN` must be observed before `STOP` is accepted as
  terminal, or the first `get_data` can end an action before it began.
- `PAUSE` and `SYNC` are busy, stated explicitly rather than by `> 0`.
- On terminal, drain until `NbRows == 0`, bounded by an iteration cap and by
  `TechniqueIndex` not advancing. This replaces the current
  `while len(latest_segment.data) > 0` loop and its stray
  `print("!!! retrieving last segment")`.

**`DataInfo.IRQskipped` is dropped points and is currently ignored.** Surfaced
as a `LOGGER.warning` and a driver counter, not as a new column — the emitted
set stays frozen (D7).

**Emitted columns do not change.** `field_map` → canonical name is replaced by
`column_plan`. `test_biologic_column_contract.py`'s frozen sets
(`{t_s, Ewe_V, I_A, P_W, cycle}` for DC; the 16-name EIS set) are the gate. The
`_`-prefixed `CurrentValues` columns keep today's membership exactly. New
techniques get new plans: CALIMIT/CPLIMIT reuse CP's, SPEIS/SGEIS add `step`.

## 6. Defects being fixed

**6.1 Data-tail truncation.** §5, done-detection and drain.

**6.2 TTL is wrapper-shaped and unverified.** easy-biologic prepends TI/TO
inside `program.py::_run` from a `ttl_params` dict and never confirms the
trigger technique loaded. §4 makes it explicit and reads the list back.

**6.3 stop/cleanup/reset raciness.**

- `self.stopping` guarded nothing and is deleted; the worker thread (§7) is what
  makes vendor calls non-reentrant.
- `connection_raised` is set *before* the attempt, so a `connect` that throws
  strands the driver permanently. Replaced by `TestConnection` against the held
  id.
- `reset()` builds a success response and then reconnects in a `finally`, so a
  failed reconnect reports success. Made sequential.
- The `"In use by another script" in exc.__str__()` string match becomes a
  vendor error-code check.

**6.4 No firmware or board-type handling.** §4 and §5 (D6), plus §7's
conditional firmware load.

**6.5 Wrapper tables disagree with the vendor docs.** Found while building the
layout tables: easy-biologic names OCV's 4th VMP3 column `control` where the PDF
says `Ece`, and spells CALIMIT's `Step_number` as `Step_nuber` — a label the DLL
has no parameter for. Neither is load-bearing today only because OCV drops that
column and HELAO has never run CALimit. This is the evidence behind D9.

**6.6 Blocking vendor calls run on the event loop.** easy-biologic's `*_async`
functions are `async def` wrappers around the blocking sync calls, generated in
a loop at `lib/ec_lib.py:660`. Every `BL_GetData` today blocks the action
server's event loop, at the executor's 10 ms poll rate, in a process also
serving HTTP and two WebSockets. §7 fixes it.

**6.7 Firmware messages are never read.** EClib1 exposes per-channel messages
via `BL_GetMessage`; easy-biologic never calls it, so a firmware complaint about
a rejected parameter is invisible. §7 drains them into the log.

**6.8 `SweepMode` has never reached the instrument.** Found while planning. The
ECC parameter `sweep` is boolean and documented "TRUE for linear points
spacing" (PDF §7.11.2); easy-biologic casts the action value with `bool(...)`
at `lib/ec_lib.py:777`, and `bool("log")` is `True`. Every PEIS and GEIS run on
all four stations has swept **linearly** while the recorded `SweepMode` said
`log`. Fixed: `"lin"` → `True`, `"log"` → `False`, with a bare bool refused so
the old shape cannot slip back in. The endpoint default stays `"log"`, so **the
default sweep becomes logarithmic and new spectra are not frequency-comparable
with the archive** (D11).

**6.9 CAOCV's `CA_ERange` has never reached the instrument.** `CAOCV.__init__`
did `ch_params["voltage_range"] = get_voltage_range(max(abs(voltages)))` — an
unconditional overwrite — so the recorded `CA_ERange` was ignored and the
hardware got `v2_5`/`v5`/`v10` derived from the voltage list. Fixed: the
parameter applies, and CAOCV stops being the one technique that ignores its own
range (D12). Behaviour change on CA steps, where a default of `AUTO` now
reaches the hardware.

CP's and GEIS's equivalents needed no decision: `set_current_range` only *warns*
when a range is supplied, and the endpoints always supply one, so that path was
already dead.

## 7. Driver lifecycle

**Single channel** (D5). `self.channel: Optional[int]` and its claim state
replace three `num_channels`-wide dicts. `setup` claims; a second claim returns
`DriverStatus.busy` naming the holder. `num_channels` still bounds-checks the
index. Every protocol signature keeps its `channel` argument, since
`BiologicExec` passes `action_params["channel"]` and stamps it into the data.

**One worker thread owns every DLL call**, reached from `get_data` through
`run_in_executor`. Motivated by 6.6; it also settles DLL re-entrancy without
needing the manual to answer it.

**`connect()`** loads the DLL from `sdk_path`, `BL_Connect(address, timeout)`,
`GetChannelInfo`, then loads firmware **only if `is_kernel_loaded` is false**,
with `force=False`. `force_load_firmware: true` in the server params is the
escape hatch. The vendor example uses `force=True`, which reflashes a production
instrument on every connect. Board type and firmware version are logged, because
they select the `.ecc` and the layout.

**`setup()`** coerces the range enums from their recorded strings (unchanged —
the recorded param stays `"AUTO"`/`"m1"`/`"BW4"`), builds the `TEccParams_t`
array, resolves the `.ecc` by board type, loads TI/TO at index 0 when requested,
loads the measurement, reads the technique list back, verifies.

**`start_channel()`** calls `StartChannel`, records `start_time`, arms the
done-detector.

**`stop()`** calls `StopChannel`. `stop(None)` stops the claimed channel if
there is one and is otherwise a successful no-op, which is what `stop_private`
and `shutdown` need.

**`cleanup(channel)`** releases the claim and refuses while the channel reads
`RUN`, as today. EClib1 has no unload call — a technique stays resident until
the next `LoadTechnique(first=True)` replaces it — so cleanup clears our state,
not the instrument's.

**`reset()`** disconnects then connects, in sequence (6.3).

**`shutdown()`** stops, cleans up, disconnects; bounded.

**`GetMessage` drained into the log** at setup, start and stop (6.7).

## 8. Testing and gates

**`sim.py` fakes the DLL, not the client** — a callable surface standing in for
`WinDLL` at the `vendor` boundary, so the real structs, the real `TEccParams_t`
packing, the real buffer decode and the whole client execute on Linux. Selected
by `simulate: true`, matching eclib2. Synthesizes per-board-family `int32`
buffers; simulates no electrochemistry.

New tests:

| file | asserts |
|---|---|
| `test_biologic_technique.py` | param tables, array arity, `Step_number` conventions, TTL bracketing, `Test*_Config` packing, plan-entry → loaded-index mapping, `loop_N_times = -1` refusal |
| `test_biologic_data.py` | layout tables per `(technique, family, process)`, vendor time conversion, derived columns, drain, done-detection including the start race, `IRQskipped` |
| `test_biologic_driver.py` | lifecycle against sim: claim and refusal, firmware conditionality, `reset` ordering, stop/cleanup, `GetMessage` drain |
| `test_biologic_vendor_real_sdk.py` | opt-in on `HELAO_ECLIB1_SDK_PATH`: every `.ecc` stem resolves per board suffix; every `param_table` label against `BL_GetParamInfos`; every struct field; every error-code name |

`test_biologic_column_contract.py` extended: the frozen sets for the 7 shared
techniques are unchanged, and its live half now runs the eclib sim as well as
the OLE one, so the DC and EIS column sets are proven by two drivers instead of
declared by one.

Changed because the dependency is gone:

- `test_biologic_disconnected_construct.py` — its four `easy_biologic`
  hermeticity assertions become "import loads no DLL and reads no `sdk_path`".
- `test_hte_builds_on_linux.py:108` — the test that fails if `easy_biologic`
  becomes importable on Linux is deleted. The `BUILDS` entry
  `("biologic_server", "hispec", "PSTAT")` stays.
- `test_hardware_import_sweep.py:43` — expectation updated.

**Route checklist.** Four new paths — `/BIOLOGIC/run_CALIMIT`,
`run_CPLIMIT`, `run_SPEIS`, `run_SGEIS` — need entries in
`helao/hexagon/tests/checklists/hte/_additions.json` or
`test_hte_route_checklist.py` fails. That is the trap the eclib2 work hit late.

`/BIOLOGIC/run_plan` is **already listed**, so it needs no new entry — but its
recorded `why` currently reads "eclib2 backend only, since neither sibling
backend can load a multi-technique experiment in one call", which this change
makes false. Amend that entry rather than adding a second one.
`biologic_server.py:655`'s `== "eclib2"` guard widens to
`in {"eclib", "eclib2"}` so `run_plan` registers on both.

### 8.1 Sequencing — the step that cannot be reordered

`helao/hexagon/tests/smoke/golden_capture_biologic.py` captures `run_OCV`
against a live instrument on a dummy cell or calibration resistor, driven by
`biologic_diff.bat`.

**The reference must be captured with the current driver, at the station, before
the rewrite reaches it.** Once easy-biologic is gone the reference is
unobtainable, and a rewrite with no reference has only its own assertions to
agree with. See `golden-diff-needs-real-hw-config` — a canary that does not
carry the station's real hardware params passes regardless and hides a wrong
address.

Then, in order:

1. Golden captured on the current driver at the station (above).
2. Freeze branch cut from `unstable` before the merge. Rollback is a revert of
   the merge; there is no config key to flip back (D1).
3. At station: `run_OCV` golden diff.
4. At station: `run_CA`, `run_CV`, `run_PEIS`, `run_GEIS` on the dummy cell,
   columns compared against pre-rewrite records.
5. Merge.

### 8.2 Gaps recorded rather than papered over

- **TTL's electrical leg.** Verifying that a trigger actually fires needs a
  second instrument or a scope. Without one, the gate is the technique-list
  read-back only, and the trigger itself is untested. Do not read a passing
  `setup` as a working trigger.
- **The four new techniques and `run_plan` have no station reference.** Nobody
  has run CALIMIT, CPLIMIT, SPEIS or SGEIS here. Acceptance is "runs,
  terminates, columns present, limits observed", not a diff.
- **Layouts are verified on whichever board family the gate station has.** The
  other family's tables are asserted against the PDF and the DLL's
  `GetParamInfos`, but not against a record. A station on the other family is a
  separate first-launch gate.

### 8.3 Conventions

`black` on changed files immediately before `git add`, in the `helao` conda env.
pyright baseline on `biologic_server.py` plus the driver files is **40 errors
today** (Optional-narrowing and dynamic `ActionHost` attributes, all
pre-existing); measure against that, not zero. Run the hexagon suite per-file
with `timeout`, not as one session.

## 9. Out of scope

- `biologic_ole` and `biologic_eclib2`: untouched.
- The `P_W` sign disagreement between `eclib` and `olecom` (§5).
- Adding `Ece_V` to OCV's emitted columns, though the column exists on VMP3
  hardware and is currently discarded (D7 freezes the set).
- The corrosion technique family — LP, GC, CPP, PDP, PSP, ZRA, EVT — and the
  pulse voltammetry family. `.ecc` files ship for all of them; none were
  requested.
- Multi-channel concurrency (D5). A second simultaneous channel is refused, not
  queued.
