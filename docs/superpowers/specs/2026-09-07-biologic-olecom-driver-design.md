# A second BioLogic backend over the EC-Lab OLE COM interface

*2026-09-07. Adds `BiologicOleDriver`, a drop-in alternative to the
easy-biologic/EClib driver, selected per-station by a `pstat_backend` config
key. The existing driver, its endpoints, and every station running it are
unchanged.*

## The problem

`helao/deploy/hte/drivers/pstat/biologic/driver.py` drives BioLogic
potentiostats through [easy-biologic](https://github.com/bicarlsen/easy-biologic),
which wraps BioLogic's `EClib` firmware DLL. That path is bounded in two ways
that matter at the stations:

* **Instrument and firmware support.** A unit whose firmware EClib will not
  negotiate is unreachable, and there is nothing to be done about it from this
  side. The ceiling is not moving, either: BioLogic's EClib2 SDK (v2.0.2) is
  not back-compatible -- it drops `blfind`, `BL_GetData` and `.ecc` files --
  so easy-biologic cannot import against it and vendors its own EClib1
  regardless.
* **Technique coverage.** easy-biologic exposes a handful of
  `base_programs`; the seven HELAO endpoints (`run_OCV`, `run_CA`, `run_CP`,
  `run_CV`, `run_PEIS`, `run_GEIS`, `run_CAOCV`) are close to all of it.
  EC-Lab itself has 147 techniques.

EC-Lab's OLE COM interface reaches the instrument through EC-Lab rather than
around it, so both limits go away: any instrument EC-Lab supports, and any
technique EC-Lab can express. The cost is that EC-Lab must be installed,
registered, and running on the same Windows host as the action server.

The requirement is a **drop-in replacement at the action-server level**. Five
experiment libraries — `ANEC_exp`, `ECHEUVIS_exp`, `PSTAT_exp`, `ECMS_exp`,
`HISPEC_exp` — dispatch these endpoints by name, and both `biologic_vis`
panels read the emitted column names. Route signatures, parameter names,
defaults, and emitted columns must all match, or the switch is not a switch.

## What the OLE COM API actually is

Read from *EC-Lab OLE COM User Manual*, EC-Lab v11.72, May 2026 (43 pp). Three
properties of the API shape the whole design, and two of them contradict what
you would guess from the easy-biologic model.

**There is no programmatic technique construction.** The API has 32 functions
(each also available with a `_TS` suffix, which only duplicates the return
value into a trailing out-argument for TestStand and is not used here) and not
one of them builds a technique from parameters. The only route from
parameters to a channel is:

```
LoadSettings(DeviceNumber, ChannelNumber, FileName) -> 0|1
```

where `FileName` is an absolute path to an `.mps` (settings) or `.mpr` (data)
file on disk. `ModifyOnTheFly(dev, ch, techNo, seqNo, ParamID, ParamValue)`
exists, but it mutates a **running** experiment, addresses the parameter by its
EC-Lab GUI caption string, and needs a second call to set the unit:

```
ModifyOnTheFly(6, 1, 2, 1, 'Is', '30.000');
ModifyOnTheFly(6, 1, 2, 1, 'unit Is', 'mA');
```

So `.mps` files are not an optional convenience for reusing GUI-authored
protocols — they are the transport for everything. Every parameterised
endpoint has to produce one.

**Data is polled out of the MPR file, one value per call.** There is no
streaming callback and no buffer drain. The available reads are:

| Function | Returns |
|---|---|
| `MeasureNumberOfPoints(mpr)` | point count — the cursor |
| `MeasureDcValue(mpr, idx)` | `<t_s, Ewe_V, I_A>` (I is always 0 for OCV) |
| `MeasureEisValue(mpr, idx)` | `<t_s, f_Hz, Re(Z), -Im(Z)>` |
| `MeasureValueByCode(mpr, varCode, idx)` | one variable, one point |
| `MeasureValueByID(mpr, 'Pwe/W', idx)` | same, by GUI display name |

**Channel status is a 32-element array of reals** from `MeasureStatus(dev, ch)`.
The indices this design uses:

| Idx | Meaning |
|---|---|
| 0 | `Stop=0`, `Run=1`, `Pause=2`, `Sync=3`, `Stop_rec1=4`, `Stop_rec2=5`, `Pause_rec=6` |
| 4 | current technique index in the channel's technique list (0–19) |
| 5 | technique code (appendix 7.1) |
| 6 | sequence index within the technique |
| 10 | cycle number (CV, EIS, VASP, CASP) |
| 15–19 | time, Ewe, Ece, Eoc, I |
| 23 | IRange |
| 25–26 | frequency, \|Z\| |
| 27–28 | current point index, total point index |
| 30 | safety limit: `Ok=0`, `Emax=1`, `Emin=2`, `I=3`, `Q-Q0=4`, stack limits 7–10 |
| 31 | connection: `Ok=0`, `Disconnected=1` |

The existing driver's `State > 0 ⇒ busy` mapping survives unchanged, because
`Stop` is 0 here too.

## Decisions

Each of these was settled during design; the reasoning is recorded because in
several cases the obvious choice is wrong.

### 1. A sibling driver package, selected by a config key

New package `helao/deploy/hte/drivers/pstat/biologic_ole/`. The existing
`biologic/` package is untouched. `biologic_server.py` selects between them,
mirroring the `wl_source` mechanism in `andor_server.py` exactly:

```python
BACKENDS: dict[str, type] = {
    "eclib": BiologicDriver,
    "olecom": BiologicOleDriver,
}
DEFAULT_BACKEND = "eclib"
```

with a `_driver_class(server_key)` that reads `params.pstat_backend` from the
global `CONFIG` and **raises on an unrecognized value rather than falling back
to the default**. A typo must not hand an EC-Lab station the EClib driver, to
fail much later at `connect()` with a vendor import error.

An absent key yields `eclib`, so all six live configs (`hispec`, `odspechw`,
`clad`, `adss3`, `htereflex`, `htehexreflex`) keep working with no edit.

There is deliberately **no shared base class**. The two backends have almost no
implementation in common — one is a TCP/DLL program model, the other is
GUI automation over files — so a base would be an empty shell. What they share
is the *contract* the action server already calls: `connect`, `get_status`,
`setup`, `start_channel`, `get_data`, `stop`, `cleanup`, `disconnect`, `reset`,
`shutdown`. That is made explicit as a `typing.Protocol` named
`BiologicBackend`, in a new `helao/deploy/hte/drivers/pstat/biologic_backend.py`
— a file with no implementation and no vendor import, which both packages
type-check against and neither depends on at runtime.

`BiologicExec` needs no change: it already binds `self.driver = self.active.driver`
rather than a named `app.drivers.<Name>` field, which is the form that survives
the class-name difference (`base_api` derives the namedtuple field from the
class name, so `app.drivers.BiologicOleDriver` and `app.drivers.BiologicDriver`
are different attributes — use `app.driver`).

### 2. `.mps` templates, patched per action

One checked-in template per technique, plus a Trigger In and Trigger Out
template:

```
biologic_ole/templates/
    OCV.mps  CA.mps  CP.mps  CV.mps  PEIS.mps  GEIS.mps  CAOCV.mps
    TI.mps   TO.mps
```

`.mps` is plain text in **latin-1**, not ASCII or UTF-8: the parameter table
lists parameter names in a fixed order with one column per sequence, which is
how [eclabfiles](https://github.com/vetschn/eclabfiles) parses them, and EC-Lab
writes the micro prefix as the single byte 0xB5 (`unit Is  µA`). Reading such
a file as UTF-8 raises. `mps_template.py`
loads a template, substitutes the action's parameter values, and writes a
patched copy; `technique.py` holds the per-technique mapping from HELAO
parameter key to `.mps` parameter caption and unit.

The alternative — emitting `.mps` from scratch — was rejected because it
requires reverse-engineering the full format and makes every EC-Lab version
bump a risk. Loading a fixed template and then pushing values with
`ModifyOnTheFly` was rejected because the experiment would start on the
template's values before the real ones arrive, which on a real cell is not an
acceptable transient.

The caption tables and value encodings were checked twice. First against
[`jdhuang-csm/biologic-com`](https://github.com/jdhuang-csm/biologic-com), a
working third-party `.mps` writer for the same OLE COM interface, which covers
OCV, CA, CP, PEIS and GEIS but not CV. That repository carries no license, so
nothing is copied from it — only facts about the vendor's file format, which
are not anyone's to license. It also corroborates the motivation for this
design from a different angle: its author reports that the EC-Lab Development
Package easy-biologic uses "loads different firmware to the instrument, which
in my experience results in a lower signal-to-noise ratio for certain
experiments compared to the standard firmware."

Then against **two real GUI-authored files** — a single-technique `CV.mps` and
a three-technique `TI_CV_TO.mps`, EC-Lab v11.72 on an SP-200, both now
committed as fixtures (and `CV.mps` doubling as the CV template). Running a
parser over them found five properties of the format, every one of which
breaks a reasonable implementation without saying so:

- **latin-1 with CRLF terminators.** The files carry 0xB2 and 0xB3 — the
  superscripts in `0.001 cm²` and `0.001 cm³` — and genuinely fail to decode
  as UTF-8. Reading without disabling universal-newline translation rewrites
  CRLF to LF and breaks byte-identity.
- **Fixed-width columns**, label in 0-19 and each sequence value in the 20
  after it, *trailing padding included*. Stripping it breaks the round-trip.
- **A value may contain a space.** `Trigger  Rising Edge` is one value;
  splitting on whitespace makes it two sequence columns.
- **Header lines can look exactly like parameter rows.**
  `Reference electrode : SCE ...` and `Characteristic mass : 0.001 g` were
  both mis-parsed as rows, which made an unscoped sequence count return 7 for
  a single-sequence file. Parsing is scoped to technique blocks.
- **Captions are not unique.** `vs.` appears **four times** in one Cyclic
  Voltammetry block, once per vertex; `Trigger` appears in both trigger blocks
  of the three-technique file; GEIS has a caption with two consecutive spaces
  (`unit  Ia`). Every accessor therefore takes a technique scope and an
  occurrence index, and a first-match lookup is never safe.

Two substantive findings beyond formatting. **EC-Lab's CV has no `dE (mV)`
row** — `Step percent` and `N` govern recording — so `AcqInterval__V` is left
unmapped rather than guessed, and settling it is an at-station question.
**Trigger In carries `Trigger` and `Channel` and no duration; Trigger Out
carries `Trigger` and a delay `td (h:m:s)` and no channel**, so `TTLwait` and
`TTLduration` map cleanly but `TTLsend`'s channel has nowhere to go and is
reported rather than dropped.

**The templates cannot be produced on Linux, and all nine now exist.** They
were authored in the EC-Lab GUI (v11.72, SP-200) and committed: OCV, CA, CP,
CV, PEIS, GEIS and CAOCV, plus TI and TO extracted from a real `TI_CV_TO.mps`.
Every caption in the technique registry is checked against them by a test that
runs on Linux, so this stopped being an at-station gate and became a
regression guard. One template-side question survives — see CV's
`AcqInterval__V` below.

### 3. `run_protocol`: an additive endpoint for GUI-authored protocols

Because `.mps` is already the transport, running a station-authored protocol
as-is costs almost nothing: `LoadSettings` with no patching. A new endpoint

```python
run_protocol(
    ctx, fast_samples_in=Body([], embed=True),
    mps_path: str = "", channel: int = 0,
    TTLwait: int = -1, TTLsend: int = -1, TTLduration: float = 1.0,
)
```

registers **only** on the OLE backend. `mps_path` is resolved against a
`protocol_dir` server param rather than taken as an arbitrary absolute path, so
a station's protocol library is a declared location instead of whatever the
caller passes. It is additive — no existing experiment code calls it, and the
drop-in contract is unaffected.

Its data columns cannot be known in advance, because the `.mps` decides the
techniques. The driver reads status index 5 after `LoadSettings`, looks the
technique code up in the appendix 7.1 table, and emits that technique's column
plan; an unrecognized code emits the `MeasureDcValue` triple alone rather than
guessing.

### 4. Derived `P_W` and `cycle`: one COM call per DC point

`MeasureDcValue` returns three of the five columns a DC technique emits. The
other two are derived rather than fetched:

* `P_W` = `|Ewe * I|`, which is precisely how EC-Lab defines variable code 70.
* `cycle` from `MeasureStatus[10]`, stamped across the points read in that poll.

Fetching them by code instead would be byte-exact to EC-Lab's own arithmetic
but would triple the COM traffic — at 100 Hz on a CA that is ~500 calls per
second against a GUI application. The derived values are identical by
definition for `P_W`, and `cycle` only changes at technique-level boundaries
that a poll cannot fall inside without the status also changing.

EIS is cheaper: `MeasureEisValue` returns `t_s`, `f_Hz`, `Re(Z)` and — per the
manual's own note — the imaginary part *already negated*. So the existing
derived pair falls out directly:

```
R_ohm = Re(Z)              # today: modulus * cos(phase)
X_ohm = <4th value>        # today: -modulus * sin(phase), i.e. -Im(Z)
```

and `modulus`/`phase` come from variable codes 36 and 35. The remaining PEIS/GEIS
columns all have codes: `Ece` 9, `|Ewe|` 33, `|I|` 34, `|Ece|` 96, `|Ice|` 97,
`Phase(Zce)` 98, `|Zce|` 99.

The manual describes `MeasureDcValue`'s output as an array "extracted from the
MPR file, **starting from** the selected index", then lists three values. If it
in fact returns every point from the index onward, the poll cost collapses by
orders of magnitude. **This is a one-line station probe.** The design exploits
it if true and does not depend on it if false: `mpr_cursor.py` reads a length
from whatever comes back and advances by that, so a bulk return needs no code
change.

### 5. TTL becomes TI/TO techniques inside the `.mps`

There are no trigger functions in the API. Trigger In and Trigger Out are
*techniques* (codes 38/39 and 88/89). So a non-default `TTLwait`, `TTLsend`, or
`TTLduration` causes the generated `.mps` to gain a prepended TI and/or an
appended TO technique around the main one.

Nothing in the tracked experiments or sequences currently passes a non-default
value: `helao/deploy/hte/sequences/` mentions these keys nowhere, and all 88
occurrences in `helao/deploy/hte/experiments/` are `-1` plumbing. But private
deployments are not visible from here, and a silently dropped hardware trigger
is the kind of failure that is discovered months later in the data.

### 6. Enum coercion moves out of the endpoint layer

Today each endpoint overwrites its own action params before the executor runs:

```python
active.action.action_params["IRange"] = EC_IRange_map[
    active.action.action_params["IRange"]
]
```

`EC_IRange_map` yields `easy_biologic.lib.ec_lib.IRange` members — EClib-specific
objects sitting in the shared endpoint layer, where the OLE backend needs the
plain string for `.mps` patching.

The coercion moves into each backend's `setup()`. Endpoints leave the
`EC_IRange` / `EC_ERange` / `EC_Bandwidth` `StrEnum` value in `action_params`;
`BiologicDriver.setup` maps it to the vendor enum, `BiologicOleDriver.setup`
reads the string.

**This changes what is recorded.** The action `.yml` will carry `"AUTO"`,
`"m1"`, `"BW4"` instead of the vendor enum's serialized integer. Nothing in
tracked code reads the value back, callers already pass these as strings
(`IRange: str = "m1"` in `HISPEC_exp`), and the string is the more legible
record — but it is a visible metadata change from the first action after this
lands.

### 7. `enum.py` becomes hermetic

`biologic/enum.py` imports `easy_biologic.lib.ec_lib` at module scope, and
`biologic_server.py` imports `enum.py`. A Windows station running EC-Lab but
*not* easy-biologic therefore cannot import the BIOLOGIC server at all — the
OLE-only station is unreachable until this is fixed.

`driver.py` and `technique.py` were made hermetic in P3a-2 (see
`test_biologic_disconnected_construct.py`); `enum.py` was missed because
nothing then needed it. The maps become lazily-resolved, and the existing
disconnected-construct test grows an assertion covering `enum.py`.

### 8. MPR and MPS ship with the action, moved after the run

`RunChannel(dev, ch, FileName)` writes EC-Lab's own `.mpr` data files.
`HelaoYml.misc_files` rglobs the action directory and uploads everything that
is not `.yml`/`.hlo`/`.lock`/`.tmp` and not a dotfile, so a file placed in the
action directory reaches `raw_data/` automatically. Both the patched `.mps` and
the resulting `.mpr` are worth having: the exact settings and the exact vendor
data, reopenable in EC-Lab.

But EC-Lab writes the `.mpr` **continuously while the technique runs**, and
SYNC globs live directories. So the run writes to
`<root>/STATES/olecom/<server_key>/ch<N>/<action_uuid>/` and `_post_exec` moves
the finished files into the action directory once status index 0 reaches
`Stop`. Provenance without a torn upload.

## Layout

```
helao/deploy/hte/drivers/pstat/
    biologic_backend.py   the BiologicBackend Protocol. No implementation,
                          no vendor import; both packages satisfy it

helao/deploy/hte/drivers/pstat/biologic_ole/
    __init__.py
    driver.py         BiologicOleDriver(HelaoDriver) — the 10-method surface
    olecom_client.py  typed wrapper over the 32 OLE functions;
                      the ONLY module that imports comtypes
    sim.py            fake COM server over synthetic MPR value tables
    status.py         MeasureStatus 32-float decoder -> named fields + ChannelState
    mps_template.py   load / patch / write .mps text. Pure; no COM, no vendor import
    technique.py      per technique: template file, param -> (ParamID, unit),
                      var-code column plan
    mpr_cursor.py     point cursor + column assembly over the three Measure* reads
    templates/        the nine .mps files, authored in EC-Lab at the station
```

The split is drawn so the risky part is the testable part. A wrong parameter
mapping is what silences a cell, and `mps_template.py` + `technique.py` are
pure text transforms with no vendor dependency — fully exercisable on Linux.

`comtypes` is already pinned in `helao_dev_win-64.yml` (Gamry uses it), so this
adds no environment dependency. The ProgID EC-Lab registers is not stated in
the manual and is a station probe.

## Lifecycle

| HELAO method | OLE COM |
|---|---|
| `connect()` | `EnableMessagesWindows(0)` → `GetSoftwareVersion` (refuse below 11.11) → `ConnectDeviceByIP(config['address'])` → cache device number → `GetDeviceChannelList`, `GetDeviceType`, `GetDeviceSN` to the log |
| `get_status(ch)` | `MeasureStatus` → decode index 0; `None` queries every channel in the device's channel list |
| `setup(tech, params)` | patch template → write scratch `.mps` → `IsChannelReady` → `LoadSettings` |
| `start_channel(ch)` | `RunChannel(dev, ch, out_base)`, then `GetDataFileName(dev, ch, techNo)` per technique |
| `get_data(ch)` | `MeasureStatus`; `MeasureNumberOfPoints(mpr)`; read `[cursor, n)`; advance |
| `stop(ch)` | `StopChannel` |
| `cleanup(ch)` | clear cursor, MPR paths, technique; move artifacts into the action dir |
| `disconnect()` | `DisconnectDevice(dev)` |
| `reset()` | `disconnect()` then `connect()`, as today |
| `shutdown()` | stop + cleanup every running channel, then disconnect, as today |

`ConnectDeviceByIP` maps the configs' existing `address:` key straight through,
and adds the device to EC-Lab's list if it is not already there.

Three behaviours follow from the status array rather than from choice:

* **`Stop_rec1` and `Stop_rec2` (4, 5) mean "the last points are being
  recorded", not "stopped".** The technique finishes only at state 0, and one
  further `MeasureNumberOfPoints` pass runs after reaching it — the same drain
  the current driver performs with its "retrieve last segment" loop.
* **Index 30 and index 31 are fault detection the EClib path never had.** A
  non-zero safety limit (`Emax`, `Emin`, `I`, `Q-Q0`, stack limits) routes to
  `LOGGER.alert` alongside the existing Ewe/I threshold alerts; index 31 equal
  to `Disconnected` is a hard error.
* **CAOCV is a two-technique `.mps` and therefore has two MPR files.** Cursors
  are per technique, switching when status index 4 increments. `t_s` restarts
  at each technique boundary and is offset to stay monotonic. Whether
  easy-biologic's `CAOCV` emits continuous or restarting time is not knowable
  from this side and is settled by the side-by-side station run.

`StopChannel` returning 0 means the channel was already stopped. That is not an
error and must not be reported as one.

## Error handling

Every OLE function returns a bare `1`/`0` (the newer ones an HRESULT) and
carries no reason for a failure. Section 2 of the manual states plainly that
the interface performs **no validation of the commands sent** and that
correctness is entirely the caller's responsibility. So the same rule
OceanDirect's `_trigger_write_hint` earned applies here: where the vendor
supplies no reading, the driver supplies it.

* Each call site attaches a named hint to a `0`. `LoadSettings` → the settings
  are incompatible with this hardware (bandwidth, IRange) or the file is
  unreadable; `RunChannel` → the channel is not ready or no settings are
  loaded; `ConnectDeviceByIP` → unreachable or held by another client. A failed
  action carries the patched `.mps` path so the settings can be opened directly
  in EC-Lab.
* `LoadSettings` returning 0 on hardware-incompatible settings is the **one
  real pre-run validation gate** the API offers, and setup fails there rather
  than at `RunChannel`.
* What can be checked before sending, is: the channel is present in
  `GetDeviceChannelList`, and parameters are within the technique registry's
  declared ranges.
* **A modal Windows message box hangs a COM call forever.**
  `EnableMessagesWindows(0)` at connect is mandatory. COM calls still run in a
  thread executor under `asyncio.wait_for`, which frees the coroutine but
  leaves the worker thread blocked — the same trade `OceanDirectExtrigExec`
  makes, and for the same reason.
* **`ConnectDevice` and `ConnectDeviceByIP` auto-answer "Yes" to EC-Lab's
  "Do you want to upgrade the firmware?" prompt.** The manual states this
  outright and the API offers no way to suppress it, so a connect can silently
  flash a production instrument. The driver warns at connect and this is
  documented in `CLAUDE.md`; nothing more can honestly be done from here.
* **EC-Lab is a GUI a human can touch mid-run.** `SelectDevice` and
  `SelectChannel` mutate a global selection, so no call may depend on it —
  every call passes an explicit device and channel. The manual's own §6.1
  worked example is internally inconsistent on this point (the prose says
  device 6, the code says `OLE_ConnectDevice(1)`), which is worth knowing
  before treating that example as normative.
* If EC-Lab was never registered as a COM server (`ECLab /regserver`, run as
  administrator, from the install directory), object creation fails
  distinguishably. `connect()` reports that with the exact remediation command.
* Technique codes are duplicated across two families — CA is both 24 and 54,
  OCV both 11 and 55, CV 6 and 57, PEIS 29 and 60, GEIS 30 and 61, CP 25 and
  56. Which one a template yields depends on the template. Status index 5
  reports it back, and each technique's expected code is asserted after
  `LoadSettings`.

## Testing

Everything below runs on Linux and must be green before anything reaches a
station.

* **`mps_template` and `technique`** — golden patched-output fixtures per
  technique, asserting the exact text written for a known parameter set. This
  is where a wrong mapping silences a cell, and it is pure text, so it is the
  most heavily covered unit in the design.
* **`status.py`** — decoder table tests, including the `Stop_rec1`/`Stop_rec2`
  boundary and the safety-limit and connection codes.
* **`mpr_cursor.py`** — cursor advance, drain-on-done, DC versus EIS reads,
  the multi-technique switch, and a bulk-return `MeasureDcValue` (so the probe
  result needs no code change either way).
* **`sim.py`** — a fake COM server implementing the OLE functions over
  synthetic MPR value tables, selected by `simulate: true` as
  `oceandirect_sim.py` is. It drives the whole path: driver → `BiologicExec` →
  endpoints. A `biologicole` config makes it launchable with
  `python launch.py biologicole` on Linux.
* **Vendor isolation** — only `olecom_client.py` may import `comtypes`,
  enforced by parsing imports rather than grepping source, as
  `test_andor_vendor_isolation.py` does.
* **Frozen route/param checklist** — the OLE backend must produce
  `/BIOLOGIC/*` routes, parameter names, annotations and defaults identical to
  the EClib backend's, via the existing checklist mechanism
  (`helao/hexagon/tests/checklists/hte/biologic_server.json`).
* **Emitted-column contract test** — both backends, driven against their
  simulators with the same action parameters, emit the same column key set per
  technique: `t_s`, `Ewe_V`, `I_A`, `P_W`, `cycle` for DC; plus `phase`,
  `modulus`, `f_Hz`, `X_ohm`, `R_ohm`, `Ece_V`, `AbsEwe_V`, `AbsI_A`,
  `AbsEce_V`, `AbsIce_A`, `phase_ce`, `modulus_ce` for EIS. This guards what
  the visualizers and processors actually read.
* **Disconnected construct** — `BiologicOleDriver` imports and constructs on
  Linux without `comtypes`, extending the existing
  `test_biologic_disconnected_construct.py`, which also gains coverage of the
  now-hermetic `enum.py`.

## At-station gates

None of these can be discharged from here.

1. **Settle CV's `AcqInterval__V`.** EC-Lab's Cyclic Voltammetry has no
   `dE (mV)` row; `Step percent` and `N` govern recording, and the real
   template holds `50` and `10`. Left unmapped rather than guessed, so those
   template values stand on every CV. The station owner's call. All nine
   templates are otherwise present and every caption is verified on Linux.
2. **The ProgID** EC-Lab registers for `comtypes.client.CreateObject`.
3. **The `MeasureDcValue` bulk-return probe** — does it return one point or
   every point from the index?
4. **Side-by-side run.** Same cell, same parameters, both backends back to
   back, comparing traces. This is the only check that catches a wrong `.mps`
   parameter mapping, and the only one that needs hardware.
5. **TTL verification** with a scope, if any private deployment passes a
   non-default trigger parameter.

## What this does not do

* It does not change the EClib backend's behaviour, beyond moving the range
  enum coercion into its `setup()` and making `enum.py` hermetic.
* It does not migrate any station. Every config keeps `eclib` until someone
  adds `pstat_backend: olecom`.
* It does not expose EC-Lab's other 140 techniques as endpoints. `run_protocol`
  reaches them through a station-authored `.mps`; first-class endpoints for
  specific techniques are a later, separate piece of work.
* It does not add a golden-capture canary variant. The frozen checklist and the
  column-contract test cover the same ground on Linux, and the canary's
  reference — a live EClib server — is exactly what an OLE-only station will
  not have.
