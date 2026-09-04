# Andor driver split: spectrograph-controlled and lamp-calibrated variants

**Date:** 2026-09-04
**Branch:** `feat/andor-driver-split`
**Status:** design approved, no code written

## Problem

`helao/deploy/hte/drivers/spec/andor/driver.py` couples two things that only some
stations need together: an Andor Zyla camera (`pyAndorSDK3`) and an Andor
ATSpectrograph (`pyAndorSpectrograph`). The spectrograph supplies the wavelength
array via `GetCalibration` and hosts the ND filter wheel.

A new station will not have a software-controlled spectrograph. Its optics —
grating, central wavelength, slit width, ND filter — are set manually at the
instrument and never written by HELAO. Its wavelength array comes instead from
fitting a measurement of a calibration light source.

Both paths must coexist. The legacy path stays exactly as it is for the stations
that use it; the new path must run on a station where `pyAndorSpectrograph` is
not installed at all.

### Why the package cannot simply be left uninstalled today

`driver.py:32-35` welds both vendor packages into one lazy loader:

```python
def _load_andor():
    global AndorSDK3, CameraException, ATSpectrograph
    from pyAndorSDK3 import AndorSDK3, CameraException
    from pyAndorSpectrograph.spectrograph import ATSpectrograph
```

`connect()` calls it unconditionally at `driver.py:109` before touching the camera. Every station therefore needs `pyAndorSpectrograph` installed merely to
open the camera. Splitting that loader — not the class hierarchy — is what buys
the install-free station. The class split is a separate decision, made below on
its own merits.

## Constraints

The hexagon framework migration is mid-flight, and three of its gates bear on
this work.

**The frozen route checklist.** `helao/hexagon/tests/checklists/hte/andor_server.json`
is a verbatim AST extraction of the pre-migration legacy source.
`test_hte_route_checklist.py` diffs every hte action module against its frozen
record and pins the tree-wide totals at `(168, 79)` action/private routes. Its
docstring is explicit: never regenerate the checklists, because re-freezing after
a change makes the gate pass by construction and proves nothing.

**The hte canaries no longer compare against legacy.**
`test_hte_canary_reference_is_gone.py` records that since B5, `andor.yml`
(`deployment: hte`) and `andorhex.yml` (`deployment: hexagon`) both resolve to the
same `helao/deploy/hte/servers/action/andor_server.py` — the hexagon shim's
`LEGACY_MODULE` names that module and `makeActionApp` calls the same `makeApp`.
`andor_diff.bat` is a self-comparison and cannot fail. No legacy-versus-hexagon
divergence is possible from this work, and none needs accounting for. The real
reference is now a git revision: `unstable` run tree versus branch run tree, per
`docs/superpowers/notes/2026-08-15-B5-station-gate-runbook.md`.

**Every station config must keep building.** `test_hte_builds_on_linux.py:63-71`
loads each station config and calls `makeApp`. `hispec.yml` is the only config
declaring an ANDOR server, and it must continue to build with no edit.

## Structure

```
helao/deploy/hte/drivers/spec/andor/
  driver.py           AndorDriver                          camera only
  spectrograph.py     AndorSpectrographDriver(AndorDriver)
  calibrated.py       AndorCalibratedDriver(AndorDriver)
  wl_calibration.py   pure numerics; no vendor and no server imports
```

`_load_andor()` splits into `_load_camera()` on the base, importing `pyAndorSDK3`,
and `_load_spectrograph()` in `spectrograph.py`, importing `pyAndorSpectrograph`.
`spectrograph.py` becomes the only module in the tree that names the spectrograph
package. `test_hardware_import_sweep.py` already guards against module-scope
vendor imports; a new test pins the sole-importer property.

The base keeps everything invariant between the two stations: the SDK handle, the
camera, `setup_image`, `get_meta_data`, the acquire loop, cooling, `get_data`, and
buffer handling. `connect()` keeps its present shape and calls `self._wavelengths()`
where it currently calls `self.setup_spectroscope(self.pixel_width)` at
`driver.py:114`. `_wavelengths()` is the one abstract method on the base — both
subclasses must supply it, and a subclass that forgets fails at construction
rather than at a station.

`setup_spectroscope` and `adjust_ND` move to `spectrograph.py`. The base does not
declare them, not even as abstract methods — a calibrated station has no ND wheel
and no grating to set, so an inherited stub would be a method that exists only to
refuse.

`setup_spectroscope` and `adjust_ND` each construct and `Close()` their own
`ATSpectrograph()` instance today (`driver.py:355` and `driver.py:457`), so the
move carries no shared-session bookkeeping.

### Accepted divergence

`base_api.py:682` builds the driver namedtuple field name from
`driver_class.__name__`:

```python
Drivers = namedtuple("Drivers", [d.__name__ for d in driver_classes])
```

So `app.drivers.AndorSpectrographDriver` at one station and
`app.drivers.AndorCalibratedDriver` at another. Nothing reads that field for
andor — `andor_server.py` uses `app.driver` throughout — so this is documented
rather than worked around. Anything that later introspects `drivers._fields`
must not assume a fixed name.

## Wavelength calibration

`wl_calibration.py` is pure: no vendor imports, no HELAO server dependencies, so
it is fully testable on Linux with no hardware. The fitting function is not yet
written; this is the contract it will satisfy.

```python
MODEL_POLY: Final = "poly"      # nm = sum(coeffs[i] * pixel**i)

@dataclass(frozen=True)
class WavelengthCalibration:
    model: str                   # "poly"; the loader refuses an unknown value
    coeffs: list[float]          # ascending power
    n_pixels: int
    fit_rms_nm: float
    n_lines: int
    lamp: str                    # e.g. "Hg-Ar"
    created: str                 # ISO-8601 UTC
    source_action_uuid: str | None

def fit_wavelength(
    counts: Sequence[float],         # measured lamp spectrum, length n_pixels
    lamp_lines_nm: Sequence[float],  # known reference lines
    *,
    degree: int = 3,
) -> WavelengthCalibration: ...

def evaluate(calib: WavelengthCalibration) -> np.ndarray: ...  # length n_pixels
```

Coefficients are persisted, not a materialized array. The record is smaller,
human-diagnosable in the JSON, and `fit_rms_nm` gives a station gate a number to
assert on. The cost is that a change in functional form orphans existing records;
`model` mitigates it, and the loader refuses an unrecognized value rather than
mis-evaluating a record it does not understand.

Peak-finding lives inside `fit_wavelength`. The driver hands it raw counts and
receives a calibration back.

### Persistence

`<STATES>/<host>_<server_key>_andor_wl_calib.json`, following the convention
`JsonFileCalibrationStore` already uses for the Galil plate calibration
(`<states_root>/<host>_last_plate_calib.json`), with `server_key` added because a
host can run more than one andor server.

### Who may calibrate

`run_wl_calibration()` lives on the **base**, so both subclasses can measure a
lamp. A spectrograph station can therefore fit against a lamp and compare the
result to `GetCalibration` — the only way to build confidence in the new path
before switching a station onto it. Only `AndorCalibratedDriver._wavelengths()`
reads the file back as the live axis; on a spectrograph station the action writes
the JSON and reports residuals without changing what `acquire` uses.

The action drives its own acquisition, averaging `n_frames` (default 1) captures,
rather than reading a prior `acquire`'s output, which HELAO actions cannot do
cleanly. `lamp_lines_nm` is a parameter with a bundled default table, so a routine
recalibration is a bare POST.

### Cold start

On a calibrated station with no calibration file, `connect()` logs a loud WARNING
and **succeeds**. It has to: the calibration action runs on this same server, so a
`connect()` that refused would make the station uncalibratable forever.

`acquire` fails the action with an explicit message when `wl_arr` is `None`. It
cannot fall back to a bare pixel index: `andor_server.py:269` derives channel names
from `wl_arr.shape[0]` and `:277` emits `optional={"wl": list(...)}`, so an
uncalibrated fallback would record a run against a fabricated wavelength axis that
looks entirely healthy afterwards. A refused action is visible; a wrong axis is not.

## Server surface

`makeApp` reads `config_loader.CONFIG["servers"][server_key]["params"]["wl_source"]`
— `spectrograph` or `calibration` — and selects the driver class.

**An absent key yields `AndorSpectrographDriver`**, so `hispec.yml` needs no edit
and `test_hte_builds_on_linux.py` stays green against an unmodified config.

Reading the config inside `makeApp` is sound: `fast_launcher.py:80-83` populates
`config_loader.CONFIG` before `:172-174` imports the module and calls `makeApp`, and
the launcher's own comment at `:165-166` documents that ordering. `_driver_class`
must also tolerate `CONFIG` being `None` and fall through to the default, so a
direct `makeApp` call outside the launcher does not crash.

Two routes, both registered **unconditionally** in source:

- `/ANDOR/adjust_nd` — unchanged. Its executor (`andor_server.py:109-118`) narrows
  its `driver` annotation to `AndorSpectrographDriver`, and the handler fails the
  action cleanly when the configured driver is the calibrated subclass.
- `/ANDOR/calibrate_wl` — new. It works on both subclasses, so it needs no
  isinstance guard at all.

Registration must not be made conditional. The checklist extractor reads source,
so a decorator wrapped in a config test still presents a uniform source surface
while the live OpenAPI silently differs per station — a divergence no existing
gate can observe.

Importing `AndorSpectrographDriver` into `andor_server.py` at module scope is safe:
the module is pure Python, and only `_load_spectrograph()`, called inside its
methods, touches the vendor package.

## Parity accounting

The net effect on the frozen record is **one added route**. `adjust_nd` survives
the change, so `andor_server.json` continues to match verbatim.

The mechanism is an additions allowlist, not a re-freeze. The risk is asymmetric,
and `diff_route_sets` (`harness/endpoints.py:206-209`) already reports it that way,
emitting typed `missing`, `extra`, and `changed` kinds. A `missing` or `changed`
route breaks a client that relied on it. An `extra` route cannot.

- Add `helao/hexagon/tests/checklists/hte/_additions.json`: one
  `{module, path, method, date, why}` entry per deliberately added route.
- `test_module_matches_its_frozen_checklist` drops `extra` diffs named in that
  file. Every `missing` and `changed` diff still fails unconditionally, and any
  **unlisted** `extra` still fails.
- Staleness guard: an entry naming a route that is not currently present fails, so
  the file cannot accumulate dead records.
- `test_the_gate_covers_the_whole_measured_surface` computes
  `168 + len(additions)` rather than carrying the literal.

The pre-port record stays byte-identical, removing a route remains impossible
without an explicit argument, and every addition is a named, dated line in the
diff.

The B5 station-gate runbook's `unstable`-versus-branch run-tree diff will show
`calibrate_wl` as a delta. That expected difference is recorded in the runbook
note rather than discovered at a station.

## Testing

Linux, no hardware:

- `test_andor_disconnected_construct.py` splits per subclass. It currently stubs
  `setup_spectroscope` at `:61`, which the base no longer declares. Add a case
  proving that constructing `AndorCalibratedDriver` never calls
  `_load_spectrograph`.
- `wl_calibration.py` unit tests: round-trip a known polynomial through
  `fit_wavelength`/`evaluate`, refuse an unknown `model`, and assert `fit_rms_nm`
  against synthetic lines.
- A test pinning `spectrograph.py` as the sole module naming `pyAndorSpectrograph`.
- The existing route-checklist and Linux-build gates, unmodified except for the
  additions mechanism above.

At a station:

- `hispec.yml`, unedited, still acquires with the spectrograph path.
- A calibrated station refuses `acquire` before calibration and succeeds after it.
- On the spectrograph station, a lamp fit cross-checked against `GetCalibration`.

## Out of scope

`setup_spectroscope`'s optical parameters (`centralWL`, `NumHorizPixels`,
`ND_filter_num`, `slit_width_um`) are hardcoded defaults today and are never read
from config. Promoting them to config params is a real improvement but is not
required by this work, and moving them would change the legacy path this design
exists to leave untouched.

No hexagon port is introduced. The spectrometer has no hexagon port yet, and
`andor_server` is still consumed through the hexagon shim's `LEGACY_MODULE`, so a
port would be consumed from deployment code. The strategy boundary here is drawn
so it could be lifted into one later without changing call sites.
