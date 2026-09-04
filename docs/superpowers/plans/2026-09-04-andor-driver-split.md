# Andor Driver Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `AndorDriver` into a camera-only base with two subclasses — one driving an ATSpectrograph as today, one deriving its wavelength axis from a calibration-lamp fit — so a station can run the camera without `pyAndorSpectrograph` installed.

**Architecture:** `driver.py` keeps everything invariant (SDK handle, camera, imaging, acquire loop, cooling, buffers) and declares one abstract `_wavelengths()`. `spectrograph.py` holds `AndorSpectrographDriver` and is the only module in the tree naming `pyAndorSpectrograph`. `calibrated.py` holds `AndorCalibratedDriver`. `wl_calibration.py` is pure numerics with no vendor or server imports. `makeApp` picks the class from a `wl_source` config key, defaulting to the spectrograph so no existing config needs editing.

**Tech Stack:** Python 3.14, pytest, numpy, pandas. Vendor SDKs `pyAndorSDK3` and `pyAndorSpectrograph` are Windows-only and lazily imported; everything in this plan is developed and tested on Linux without them.

**Spec:** `docs/superpowers/specs/2026-09-04-andor-driver-split-design.md`

**Depends on:** `docs/superpowers/plans/2026-09-04-frozen-checklist-additions-allowlist.md` must be complete. Task 7 below writes the first `_additions.json` entry and will fail the checklist gate without it.

## Global Constraints

- Run every Python command inside the `helao` conda env: `conda run -n helao python ...`. The OS python is not 3.14.
- **Neither vendor SDK is installed on this machine and neither can be.** `pyAndorSDK3` and `pyAndorSpectrograph` ship in Windows installers. Every test in this plan runs without them; anything needing a real camera is an at-station gate listed at the end and is not attempted here.
- **No module may import a vendor package at module scope.** `test_hardware_import_sweep.py` enforces this. Imports go inside a `_load_*()` function called at the point of first device use.
- **`helao/hexagon/tests/checklists/hte/andor_server.json` must stay byte-identical.** `git diff` it before every commit. `adjust_nd` survives this work; only `calibrate_wl` is added, and it is added via `_additions.json`, never by editing the frozen record.
- **Never run `harness/hte_freeze.py`.**
- `hispec.yml` must not be edited. `test_hte_builds_on_linux.py:63-71` loads it and calls `makeApp`; an absent `wl_source` key must yield the spectrograph driver.
- Run `black` on changed Python files immediately before `git add`. Line length 88, default settings.
- `pyright` (`pyrightconfig.json`, basic mode) is authoritative. Do not remove existing `# type: ignore` directives.
- Work on branch `feat/andor-driver-split`. Do not push. Do not merge.

## File Structure

| File | Responsibility |
|---|---|
| `helao/deploy/hte/drivers/spec/andor/driver.py` | `AndorDriver`: camera, imaging, acquire, cooling, buffers, `_load_camera()`, abstract `_wavelengths()`, `run_wl_calibration()` |
| `helao/deploy/hte/drivers/spec/andor/spectrograph.py` | `AndorSpectrographDriver`, `_load_spectrograph()`, `setup_spectroscope`, `adjust_ND`. Sole importer of `pyAndorSpectrograph` |
| `helao/deploy/hte/drivers/spec/andor/calibrated.py` | `AndorCalibratedDriver`: load/persist the calibration JSON, `_wavelengths()` from it |
| `helao/deploy/hte/drivers/spec/andor/wl_calibration.py` | `WavelengthCalibration`, `fit_wavelength`, `evaluate`, `load`, `save`. Pure; no vendor, no server imports |
| `helao/deploy/hte/servers/action/andor_server.py` | Class selection in `makeApp`, the `calibrate_wl` route, `adjust_nd` refusal on a calibrated station |

---

### Task 1: Split the vendor loader

The smallest safe step and the one that actually buys the install-free station. `connect()` calls the combined `_load_andor()` at `driver.py:109` before touching the camera, so today every station needs `pyAndorSpectrograph` merely to open a Zyla. Nothing else changes here; the tree stays green throughout.

**Files:**
- Modify: `helao/deploy/hte/drivers/spec/andor/driver.py:29-35` (the loader), `:109`, `:354`, `:456` (its three call sites)
- Test: `helao/hexagon/tests/test_andor_disconnected_construct.py` (modify)

**Interfaces:**
- Produces: `_load_camera()` and `_load_spectrograph()` module-level functions in `driver.py`. `_load_camera()` binds globals `AndorSDK3` and `CameraException`; `_load_spectrograph()` binds global `ATSpectrograph`. Task 3 moves `_load_spectrograph` out to `spectrograph.py`.

- [ ] **Step 1: Write the failing test**

Append to `helao/hexagon/tests/test_andor_disconnected_construct.py`:

```python
def test_connect_does_not_load_the_spectrograph_runtime(monkeypatch):
    """Opening the camera must not require pyAndorSpectrograph.

    Both vendor packages were welded into one `_load_andor()` that
    `connect()` called unconditionally, so a station with only a camera
    still needed the spectrograph package installed to get past line one
    of connect(). Splitting the loader is what fixes that; the class split
    alone would not have, because the subclass inherits this connect().
    """
    loaded = {"camera": 0, "spectrograph": 0}

    class _FakeCam:
        pass

    class _FakeSDK:
        def GetCamera(self, dev_id):
            return _FakeCam()

    monkeypatch.setattr(
        andor_driver, "_load_camera", lambda: loaded.__setitem__("camera", 1)
    )
    monkeypatch.setattr(
        andor_driver,
        "_load_spectrograph",
        lambda: loaded.__setitem__("spectrograph", 1),
    )
    monkeypatch.setattr(andor_driver, "AndorSDK3", _FakeSDK, raising=False)

    d = AndorDriver(config={})
    monkeypatch.setattr(d, "setup_image", lambda: 1024)
    monkeypatch.setattr(d, "setup_spectroscope", lambda pw: [0.0])
    monkeypatch.setattr(d, "get_meta_data", lambda: (1, 1, 1, 1))

    d.connect()
    assert loaded["camera"] == 1
    assert loaded["spectrograph"] == 0, "connect() must not load the spectrograph"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_andor_disconnected_construct.py -v`

Expected: the new test fails with `AttributeError: <module ...driver> has no attribute '_load_camera'`.

- [ ] **Step 3: Split the loader**

In `helao/deploy/hte/drivers/spec/andor/driver.py`, replace lines 29-35:

```python
# Andor SDKs (pyAndorSDK3 / pyAndorSpectrograph) are vendor runtimes; import
# them lazily so the module imports on a vendor-less Linux box (§11.1).
# Called before the camera/spectrograph is first touched.
def _load_andor():
    global AndorSDK3, CameraException, ATSpectrograph
    from pyAndorSDK3 import AndorSDK3, CameraException
    from pyAndorSpectrograph.spectrograph import ATSpectrograph
```

with:

```python
# The Andor SDKs are vendor runtimes; import them lazily so the module imports
# on a vendor-less Linux box (§11.1). Two loaders, not one: a station may have
# the camera without the spectrograph, and a combined loader made connect()
# demand both before it had touched anything.
def _load_camera():
    """Bind the camera SDK. Called before the camera is first touched."""
    global AndorSDK3, CameraException
    from pyAndorSDK3 import AndorSDK3, CameraException


def _load_spectrograph():
    """Bind the spectrograph SDK. Called before the spectrograph is touched."""
    global ATSpectrograph
    from pyAndorSpectrograph.spectrograph import ATSpectrograph
```

- [ ] **Step 4: Update the three call sites**

At `driver.py:109`, inside `connect()`, change `_load_andor()` to `_load_camera()`.

At `driver.py:354`, inside `setup_spectroscope`, change `_load_andor()` to `_load_spectrograph()`.

At `driver.py:456`, inside `adjust_ND`, change `_load_andor()` to `_load_spectrograph()`.

Verify none remain: `grep -n "_load_andor" helao/deploy/hte/drivers/spec/andor/driver.py` must print nothing.

- [ ] **Step 5: Update the existing test that patches the old name**

`test_construct_does_not_load_vendor_runtime` and `test_connect_creates_sdk_once_then_reuses` both patch `_load_andor`. Change both to `_load_camera`, and in `test_construct_does_not_load_vendor_runtime` patch **both** loaders so the assertion still means "no vendor runtime at construction":

```python
def test_construct_does_not_load_vendor_runtime(monkeypatch):
    called = {"load": 0}

    def _boom_load():
        called["load"] += 1
        raise AssertionError("no vendor loader may run at construction")

    monkeypatch.setattr(andor_driver, "_load_camera", _boom_load)
    monkeypatch.setattr(andor_driver, "_load_spectrograph", _boom_load)
    AndorDriver(config={})  # must not raise / must not call either loader
    assert called["load"] == 0
```

In `test_connect_creates_sdk_once_then_reuses`, change the `_load_andor` patch target to `_load_camera` and rename the counter key from `loads` to `camera_loads` for clarity. Its two assertions become `made["camera_loads"] == 1`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_andor_disconnected_construct.py -v`

Expected: 4 passed.

- [ ] **Step 7: Run the import sweep and build gates**

```bash
conda run -n helao python -m pytest helao/hexagon/tests/test_hardware_import_sweep.py -v
conda run -n helao python -m pytest helao/hexagon/tests/test_hte_builds_on_linux.py -v
```

Expected: both pass. The sweep is what guarantees the new loaders did not leak an import to module scope.

- [ ] **Step 8: Format and commit**

```bash
git diff --stat helao/hexagon/tests/checklists/   # must be empty
conda run -n helao black helao/deploy/hte/drivers/spec/andor/driver.py \
  helao/hexagon/tests/test_andor_disconnected_construct.py
git add helao/deploy/hte/drivers/spec/andor/driver.py \
        helao/hexagon/tests/test_andor_disconnected_construct.py
git commit -m "refactor(andor): load the camera and spectrograph SDKs separately

connect() called a combined _load_andor() before touching anything, so a
station with only a Zyla still needed pyAndorSpectrograph installed to
get past the first line. Two loaders, called at the point each device is
first used. This, not the class split that follows, is what makes a
spectrograph-free station possible -- a subclass would have inherited
the same connect()."
```

---

### Task 2: The pure wavelength-calibration module

Independent of the class split and testable on Linux with nothing installed. The fitting function is not yet written by the owner; this task builds the contract, the persistence, and a working polynomial fit that satisfies it.

**Files:**
- Create: `helao/deploy/hte/drivers/spec/andor/wl_calibration.py`
- Test: `helao/hexagon/tests/test_andor_wl_calibration.py` (create)

**Interfaces:**
- Produces, all imported by Tasks 4 and 5:
  - `MODEL_POLY: Final[str] = "poly"`
  - `WavelengthCalibration` frozen dataclass with fields `model: str`, `coeffs: list[float]`, `n_pixels: int`, `fit_rms_nm: float`, `n_lines: int`, `lamp: str`, `created: str`, `source_action_uuid: str | None`
  - `fit_wavelength(counts, lamp_lines_nm, *, degree=3, lamp="unknown", source_action_uuid=None) -> WavelengthCalibration`
  - `evaluate(calib: WavelengthCalibration) -> np.ndarray` of length `calib.n_pixels`
  - `save(calib: WavelengthCalibration, path: Path) -> None`
  - `load(path: Path) -> WavelengthCalibration`, raising `UnknownCalibrationModel` on an unrecognized `model`
  - `UnknownCalibrationModel(Exception)`
  - `calibration_path(states_root: str, host: str, server_key: str) -> Path`

- [ ] **Step 1: Write the failing tests**

Create `helao/hexagon/tests/test_andor_wl_calibration.py`:

```python
"""Pure wavelength-calibration numerics and persistence.

No vendor SDK and no HELAO server are involved, so this whole file runs on
Linux with nothing installed. That is the point of keeping the numerics in
their own module: the part most likely to need iteration is the part that
needs no hardware to iterate on.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from helao.deploy.hte.drivers.spec.andor import wl_calibration as wlc


def _synthetic_lamp(coeffs, n_pixels, line_pixels, width=2.0):
    """A spectrum with Gaussian peaks at `line_pixels`, flat elsewhere."""
    pixels = np.arange(n_pixels, dtype=float)
    counts = np.full(n_pixels, 100.0)
    for p in line_pixels:
        counts += 5000.0 * np.exp(-0.5 * ((pixels - p) / width) ** 2)
    return counts


TRUE_COEFFS = [400.0, 0.2, 1e-6, 0.0]
N_PIXELS = 2560
LINE_PIXELS = [200, 700, 1300, 1900, 2400]


def _true_nm(pixel):
    return sum(c * pixel**i for i, c in enumerate(TRUE_COEFFS))


def test_evaluate_reproduces_the_polynomial():
    calib = wlc.WavelengthCalibration(
        model=wlc.MODEL_POLY,
        coeffs=TRUE_COEFFS,
        n_pixels=8,
        fit_rms_nm=0.0,
        n_lines=0,
        lamp="none",
        created="2026-09-04T00:00:00Z",
        source_action_uuid=None,
    )
    wl = wlc.evaluate(calib)
    assert wl.shape == (8,)
    assert wl[0] == pytest.approx(_true_nm(0))
    assert wl[7] == pytest.approx(_true_nm(7))


def test_fit_recovers_a_known_polynomial():
    counts = _synthetic_lamp(TRUE_COEFFS, N_PIXELS, LINE_PIXELS)
    lines = [_true_nm(p) for p in LINE_PIXELS]
    calib = wlc.fit_wavelength(counts, lines, degree=3, lamp="synthetic")

    assert calib.model == wlc.MODEL_POLY
    assert calib.n_pixels == N_PIXELS
    assert calib.n_lines == len(LINE_PIXELS)
    assert calib.lamp == "synthetic"
    assert calib.fit_rms_nm < 0.5

    wl = wlc.evaluate(calib)
    for p in LINE_PIXELS:
        assert wl[p] == pytest.approx(_true_nm(p), abs=1.0)


def test_fit_refuses_when_peaks_and_lines_disagree_in_count():
    counts = _synthetic_lamp(TRUE_COEFFS, N_PIXELS, LINE_PIXELS)
    with pytest.raises(ValueError, match="line"):
        wlc.fit_wavelength(counts, [400.0, 500.0], degree=3)


def test_fit_refuses_a_degree_it_cannot_support():
    counts = _synthetic_lamp(TRUE_COEFFS, N_PIXELS, LINE_PIXELS)
    lines = [_true_nm(p) for p in LINE_PIXELS]
    with pytest.raises(ValueError, match="degree"):
        wlc.fit_wavelength(counts, lines, degree=9)


def test_round_trip_through_disk(tmp_path):
    calib = wlc.WavelengthCalibration(
        model=wlc.MODEL_POLY,
        coeffs=TRUE_COEFFS,
        n_pixels=N_PIXELS,
        fit_rms_nm=0.01,
        n_lines=5,
        lamp="Hg-Ar",
        created="2026-09-04T00:00:00Z",
        source_action_uuid="abc-123",
    )
    path = tmp_path / "calib.json"
    wlc.save(calib, path)
    assert wlc.load(path) == calib


def test_load_refuses_an_unknown_model(tmp_path):
    """A record this build cannot evaluate must not be silently mis-read."""
    path = tmp_path / "calib.json"
    path.write_text(
        json.dumps(
            {
                "model": "chebyshev",
                "coeffs": [1.0],
                "n_pixels": 4,
                "fit_rms_nm": 0.0,
                "n_lines": 0,
                "lamp": "x",
                "created": "2026-09-04T00:00:00Z",
                "source_action_uuid": None,
            }
        )
    )
    with pytest.raises(wlc.UnknownCalibrationModel, match="chebyshev"):
        wlc.load(path)


def test_save_writes_readable_json(tmp_path):
    """The record is meant to be diagnosed by eye in a station's STATES dir."""
    calib = wlc.WavelengthCalibration(
        model=wlc.MODEL_POLY,
        coeffs=[1.0, 2.0],
        n_pixels=2,
        fit_rms_nm=0.5,
        n_lines=2,
        lamp="Hg-Ar",
        created="2026-09-04T00:00:00Z",
        source_action_uuid=None,
    )
    path = tmp_path / "calib.json"
    wlc.save(calib, path)
    loaded = json.loads(path.read_text())
    assert loaded["lamp"] == "Hg-Ar"
    assert loaded["fit_rms_nm"] == 0.5
    assert "\n" in path.read_text(), "expected indented JSON, not one line"


def test_calibration_path_follows_the_station_convention():
    p = wlc.calibration_path("/root/STATES", "hte-eche-11", "ANDOR")
    assert p == Path("/root/STATES/hte-eche-11_ANDOR_andor_wl_calib.json")


def test_module_imports_no_vendor_or_server_package():
    """Keeping this module pure is what lets it be iterated on Linux."""
    src = Path(wlc.__file__).read_text()
    for banned in ("pyAndor", "helao.core", "helao.helpers", "fastapi"):
        assert banned not in src, f"{banned} must not appear in wl_calibration.py"
```

- [ ] **Step 2: Run to verify it fails**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_andor_wl_calibration.py -v`

Expected: collection error, `ModuleNotFoundError: No module named 'helao.deploy.hte.drivers.spec.andor.wl_calibration'`.

- [ ] **Step 3: Write the module**

Create `helao/deploy/hte/drivers/spec/andor/wl_calibration.py`:

```python
"""Wavelength calibration from a calibration-lamp measurement.

Pure numerics and persistence: no vendor SDK, no HELAO server imports. A
station that derives its wavelength axis from a lamp instead of from an
ATSpectrograph reads its axis from here.

Coefficients are persisted rather than a materialized array. The record is
small, diagnosable by eye in a station's STATES directory, and carries
``fit_rms_nm`` so a gate has a number to assert on. The cost is that a change
in functional form orphans existing records -- which is why ``model`` is
stored and why ``load`` refuses a value it does not recognize instead of
mis-evaluating a record it does not understand.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, Optional, Sequence

import numpy as np

MODEL_POLY: Final[str] = "poly"

#: Minimum reference lines required above the polynomial degree. A fit with
#: exactly degree+1 points interpolates and reports rms 0, which reads as a
#: perfect calibration and is no evidence at all.
MIN_EXCESS_LINES: Final[int] = 1


class UnknownCalibrationModel(Exception):
    """A persisted record names a functional form this build cannot evaluate."""


@dataclass(frozen=True)
class WavelengthCalibration:
    """A pixel-to-nanometre mapping and the provenance of its fit."""

    model: str
    coeffs: list[float]
    n_pixels: int
    fit_rms_nm: float
    n_lines: int
    lamp: str
    created: str
    source_action_uuid: Optional[str]


def evaluate(calib: WavelengthCalibration) -> np.ndarray:
    """The wavelength array this calibration describes, one entry per pixel."""
    if calib.model != MODEL_POLY:
        raise UnknownCalibrationModel(calib.model)
    pixels = np.arange(calib.n_pixels, dtype=float)
    return np.polyval(list(reversed(calib.coeffs)), pixels)


def find_peaks(counts: Sequence[float], n_expected: int) -> list[float]:
    """The ``n_expected`` strongest local maxima, as sub-pixel centroids.

    Deliberately simple: a parabolic refinement of the strongest well-separated
    local maxima. Replace this with the station's own peak finder by editing
    this function alone -- ``fit_wavelength`` is its only caller.
    """
    arr = np.asarray(counts, dtype=float)
    if arr.ndim != 1:
        raise ValueError("counts must be one-dimensional")
    interior = np.arange(1, arr.size - 1)
    is_max = (arr[interior] > arr[interior - 1]) & (arr[interior] >= arr[interior + 1])
    candidates = interior[is_max]
    candidates = candidates[np.argsort(arr[candidates])[::-1]]

    chosen: list[int] = []
    for c in candidates:
        if all(abs(c - k) > 5 for k in chosen):
            chosen.append(int(c))
        if len(chosen) == n_expected:
            break
    chosen.sort()

    refined: list[float] = []
    for c in chosen:
        y0, y1, y2 = arr[c - 1], arr[c], arr[c + 1]
        denom = y0 - 2.0 * y1 + y2
        offset = 0.0 if denom == 0 else 0.5 * (y0 - y2) / denom
        refined.append(c + float(offset))
    return refined


def fit_wavelength(
    counts: Sequence[float],
    lamp_lines_nm: Sequence[float],
    *,
    degree: int = 3,
    lamp: str = "unknown",
    source_action_uuid: Optional[str] = None,
) -> WavelengthCalibration:
    """Fit pixel-to-nm from a lamp spectrum and its known reference lines.

    Args:
        counts: The measured lamp spectrum, one value per detector pixel.
        lamp_lines_nm: Known wavelengths of the lamp's lines, ascending. One
            peak is located per entry.
        degree: Polynomial degree.
        lamp: Free-text lamp identifier, recorded in the calibration.
        source_action_uuid: The action that produced ``counts``, if any.

    Returns:
        A :class:`WavelengthCalibration` whose ``fit_rms_nm`` is the residual
        of the located peaks against ``lamp_lines_nm``.

    Raises:
        ValueError: If ``degree`` leaves too few lines to be evidence, or if
            the expected number of peaks could not be located.
    """
    lines = sorted(float(x) for x in lamp_lines_nm)
    if len(lines) < degree + 1 + MIN_EXCESS_LINES:
        raise ValueError(
            f"degree {degree} needs at least {degree + 1 + MIN_EXCESS_LINES} "
            f"reference lines; got {len(lines)}"
        )

    peaks = find_peaks(counts, len(lines))
    if len(peaks) != len(lines):
        raise ValueError(
            f"located {len(peaks)} peak(s) for {len(lines)} reference line(s)"
        )

    coeffs_desc = np.polyfit(np.array(peaks), np.array(lines), degree)
    residuals = np.polyval(coeffs_desc, np.array(peaks)) - np.array(lines)
    return WavelengthCalibration(
        model=MODEL_POLY,
        coeffs=[float(c) for c in reversed(coeffs_desc)],
        n_pixels=len(counts),
        fit_rms_nm=float(np.sqrt(np.mean(residuals**2))),
        n_lines=len(lines),
        lamp=lamp,
        created=_utc_now(),
        source_action_uuid=source_action_uuid,
    )


def save(calib: WavelengthCalibration, path: Path) -> None:
    """Write the calibration as indented JSON, atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(asdict(calib), indent=2) + "\n")
    tmp.replace(path)


def load(path: Path) -> WavelengthCalibration:
    """Read a calibration, refusing a model this build cannot evaluate."""
    raw = json.loads(path.read_text())
    if raw.get("model") != MODEL_POLY:
        raise UnknownCalibrationModel(
            f"{raw.get('model')!r} in {path}; this build evaluates {MODEL_POLY!r}"
        )
    return WavelengthCalibration(
        model=raw["model"],
        coeffs=[float(c) for c in raw["coeffs"]],
        n_pixels=int(raw["n_pixels"]),
        fit_rms_nm=float(raw["fit_rms_nm"]),
        n_lines=int(raw["n_lines"]),
        lamp=str(raw["lamp"]),
        created=str(raw["created"]),
        source_action_uuid=raw.get("source_action_uuid"),
    )


def calibration_path(states_root: str, host: str, server_key: str) -> Path:
    """``<STATES>/<host>_<server_key>_andor_wl_calib.json``.

    Follows the convention ``JsonFileCalibrationStore`` uses for the Galil
    plate calibration, with ``server_key`` added because one host can run more
    than one andor server.
    """
    return Path(states_root) / f"{host}_{server_key}_andor_wl_calib.json"


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
```

Note the atomic write in `save`: the staging name is `.<name>.tmp`, which carries **both** a leading dot and a `.tmp` suffix. `HelaoYml.misc_files` rglobs an action directory and uploads everything that is not one of those two shapes, so a staging file under a record directory would otherwise be shipped to `raw_data/`. This file is written to STATES, not a record directory, but the convention is kept so a later move does not reintroduce the hazard.

- [ ] **Step 4: Run to verify it passes**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_andor_wl_calibration.py -v`

Expected: 9 passed.

- [ ] **Step 5: Type-check and commit**

```bash
conda run -n helao pyright helao/deploy/hte/drivers/spec/andor/wl_calibration.py
git diff --stat helao/hexagon/tests/checklists/   # must be empty
conda run -n helao black helao/deploy/hte/drivers/spec/andor/wl_calibration.py \
  helao/hexagon/tests/test_andor_wl_calibration.py
git add helao/deploy/hte/drivers/spec/andor/wl_calibration.py \
        helao/hexagon/tests/test_andor_wl_calibration.py
git commit -m "feat(andor): pure pixel-to-nm calibration from a lamp measurement

Coefficients are persisted, not an array: the record is small, readable
in a station's STATES dir, and carries fit_rms_nm for a gate to assert
on. load() refuses an unrecognized model rather than mis-evaluating a
record written by a build with a different functional form.

No vendor or server imports, pinned by a test, so the part most likely
to need iteration needs no hardware to iterate on."
```

---

### Task 3: Extract `AndorSpectrographDriver`

The big move. `setup_spectroscope` and `adjust_ND` leave `driver.py`; the base gains an abstract `_wavelengths()`, which makes `AndorDriver` uninstantiable — `HelaoDriver` is an ABC (`helao/core/drivers/helao_driver.py:86`), so `@abstractmethod` bites. Every consumer must move to the subclass in this same task or the tree goes red.

**Files:**
- Create: `helao/deploy/hte/drivers/spec/andor/spectrograph.py`
- Modify: `helao/deploy/hte/drivers/spec/andor/driver.py` — delete `setup_spectroscope` (`:314-438`) and `adjust_ND` (`:440-576`), delete `_load_spectrograph` (added in Task 1), add abstract `_wavelengths`, change `:114`
- Modify: `helao/deploy/hte/servers/action/andor_server.py:22`, `:113`, `:340`
- Modify: `helao/hexagon/tests/test_andor_disconnected_construct.py` (all four tests)

**Interfaces:**
- Consumes: `_load_camera()` from Task 1.
- Produces: `AndorSpectrographDriver(AndorDriver)` in `spectrograph.py`, with `setup_spectroscope(self, PixelWidth, centralWL=697.26, NumHorizPixels=2560, ND_filter_num=1, slit_width_um=200) -> np.ndarray`, `adjust_ND(self) -> DriverResponse`, and `_wavelengths(self) -> np.ndarray`. Also `AndorDriver._wavelengths(self) -> np.ndarray` as an abstractmethod on the base.

- [ ] **Step 1: Write the failing tests**

Replace the whole body of `helao/hexagon/tests/test_andor_disconnected_construct.py` below its docstring. Update the docstring's last line to read `Real camera behavior remains an at-station gate; this is construct-tier only. Both subclasses are covered: the base is abstract and cannot be constructed.` Then:

```python
import pytest

from helao.deploy.hte.drivers.spec.andor import driver as andor_driver
from helao.deploy.hte.drivers.spec.andor import spectrograph as andor_spectrograph
from helao.deploy.hte.drivers.spec.andor.driver import AndorDriver
from helao.deploy.hte.drivers.spec.andor.spectrograph import AndorSpectrographDriver


def test_the_base_is_abstract():
    """A base that could be constructed would silently have no wavelengths."""
    with pytest.raises(TypeError, match="_wavelengths"):
        AndorDriver(config={})  # type: ignore[abstract]


def test_construct_without_sdk_or_hardware():
    d = AndorSpectrographDriver(config={"dev_id": 2})
    assert d.sdk3 is None  # no AndorSDK3() at construction
    assert d.cam is None  # camera not opened
    assert d.wl_arr is None
    assert d.device_id == 2
    assert d.ready is True


def test_construct_does_not_load_vendor_runtime(monkeypatch):
    called = {"load": 0}

    def _boom_load():
        called["load"] += 1
        raise AssertionError("no vendor loader may run at construction")

    monkeypatch.setattr(andor_driver, "_load_camera", _boom_load)
    monkeypatch.setattr(andor_spectrograph, "_load_spectrograph", _boom_load)
    AndorSpectrographDriver(config={})
    assert called["load"] == 0


def test_connect_creates_sdk_once_then_reuses(monkeypatch):
    made = {"camera_loads": 0, "sdks": 0}

    class _FakeCam:
        pass

    class _FakeSDK:
        def __init__(self):
            made["sdks"] += 1

        def GetCamera(self, dev_id):
            return _FakeCam()

    monkeypatch.setattr(
        andor_driver,
        "_load_camera",
        lambda: made.__setitem__("camera_loads", made["camera_loads"] + 1),
    )
    monkeypatch.setattr(andor_driver, "AndorSDK3", _FakeSDK, raising=False)

    d = AndorSpectrographDriver(config={})
    monkeypatch.setattr(d, "setup_image", lambda: 1024)
    monkeypatch.setattr(d, "_wavelengths", lambda: [0.0])
    monkeypatch.setattr(d, "get_meta_data", lambda: (1, 1, 1, 1))

    assert d.sdk3 is None
    d.connect()
    assert made["sdks"] == 1 and made["camera_loads"] == 1
    first_sdk = d.sdk3
    d.connect()
    assert made["sdks"] == 1
    assert d.sdk3 is first_sdk


def test_connect_does_not_load_the_spectrograph_runtime(monkeypatch):
    """Opening the camera must not require pyAndorSpectrograph."""
    loaded = {"camera": 0, "spectrograph": 0}

    class _FakeCam:
        pass

    class _FakeSDK:
        def GetCamera(self, dev_id):
            return _FakeCam()

    monkeypatch.setattr(
        andor_driver, "_load_camera", lambda: loaded.__setitem__("camera", 1)
    )
    monkeypatch.setattr(
        andor_spectrograph,
        "_load_spectrograph",
        lambda: loaded.__setitem__("spectrograph", 1),
    )
    monkeypatch.setattr(andor_driver, "AndorSDK3", _FakeSDK, raising=False)

    d = AndorSpectrographDriver(config={})
    monkeypatch.setattr(d, "setup_image", lambda: 1024)
    monkeypatch.setattr(d, "_wavelengths", lambda: [0.0])
    monkeypatch.setattr(d, "get_meta_data", lambda: (1, 1, 1, 1))

    d.connect()
    assert loaded["camera"] == 1
    assert loaded["spectrograph"] == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_andor_disconnected_construct.py -v`

Expected: collection error, `ModuleNotFoundError: ...andor.spectrograph`.

- [ ] **Step 3: Add the abstract hook to the base**

In `helao/deploy/hte/drivers/spec/andor/driver.py`, add `from abc import abstractmethod` to the imports, and insert this method immediately before `def connect` (currently `:98`):

```python
    @abstractmethod
    def _wavelengths(self) -> Optional[np.ndarray]:
        """The wavelength array for the configured AOI, one entry per pixel.

        ``Optional`` because the lamp-calibrated variant legitimately returns
        ``None`` before its first calibration; annotating this ``np.ndarray``
        would make that subclass an illegal narrowing and fail pyright.

        The one thing that differs between an ATSpectrograph station and a
        lamp-calibrated one. Abstract rather than a defaulted hook: a subclass
        that forgot it would otherwise acquire against a fabricated axis, and
        a wrong wavelength axis is invisible in the recorded data.
        """
```

Change `driver.py:114` from:

```python
            self.wl_arr = self.setup_spectroscope(self.pixel_width)
```

to:

```python
            self.wl_arr = self._wavelengths()
```

Delete `setup_spectroscope` (lines 314-438) and `adjust_ND` (lines 440-576) from `driver.py`. Delete the `_load_spectrograph` function added in Task 1. Leave `image_and_check_dynamic_range` (`:225`) and `generate_spectral_array` (`:608`) in place — neither touches `ATSpectrograph`; the first is called by `adjust_ND` from the subclass and the second takes its wavelength array as a parameter.

Update the module docstring's first line to `"""HelaoDriver wrapping the Andor Zyla camera."""` and drop the `pyAndorSpectrograph` sentence from it. Remove `ATSpectrograph` from the `cam: AndorSDK3` class-attribute block's docstring mention of the spectrograph.

- [ ] **Step 4: Write the subclass**

Create `helao/deploy/hte/drivers/spec/andor/spectrograph.py`:

```python
"""AndorDriver variant driving an Andor ATSpectrograph.

The only module in the tree that names ``pyAndorSpectrograph``. A station
whose optics are set by hand runs :class:`AndorCalibratedDriver` instead and
does not need the package installed at all.

``setup_spectroscope`` and ``adjust_ND`` are moved here verbatim from
``driver.py``; each opens and closes its own ``ATSpectrograph`` handle, so
there is no shared session between them.
"""

from __future__ import annotations

import numpy as np

from helao.core.drivers.helao_driver import DriverResponse
from helao.helpers import helao_logging as logging

from .driver import AndorDriver

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def _load_spectrograph():
    """Bind the spectrograph SDK. Called before the spectrograph is touched."""
    global ATSpectrograph
    from pyAndorSpectrograph.spectrograph import ATSpectrograph


class AndorSpectrographDriver(AndorDriver):
    """Andor Zyla coupled to an ATSpectrograph.

    The wavelength array comes from the spectrograph's own ``GetCalibration``
    after the grating, central wavelength, slit and ND filter are set.
    """

    def _wavelengths(self) -> np.ndarray:
        return self.setup_spectroscope(self.pixel_width)

    # setup_spectroscope and adjust_ND are moved verbatim from driver.py.
```

Then move the two method bodies. Copy `setup_spectroscope` (was `driver.py:314-438`) and `adjust_ND` (was `driver.py:440-576`) into the class **unchanged except** that each `_load_andor()` call — already `_load_spectrograph()` after Task 1 — now resolves to this module's function. Do not otherwise edit them; the whole point is that the legacy path is untouched.

- [ ] **Step 5: Point the server at the subclass**

In `helao/deploy/hte/servers/action/andor_server.py`:

At `:22`, change:

```python
from ...drivers.spec.andor.driver import AndorDriver, DriverStatus
```

to:

```python
from ...drivers.spec.andor.driver import AndorDriver, DriverStatus
from ...drivers.spec.andor.spectrograph import AndorSpectrographDriver
```

This import is safe at module scope: `spectrograph.py` is pure Python and only `_load_spectrograph()`, called inside its methods, touches the vendor package.

At `:113`, narrow the ND executor's annotation:

```python
class AndorAdjustND(Executor):
    ...
    driver: AndorSpectrographDriver
```

At `:340`, change `driver_classes=[AndorDriver]` to `driver_classes=[AndorSpectrographDriver]`. Task 6 replaces this with the config-driven selection; this keeps the tree green in between.

Leave `:36`, `:134` and `:343` annotated as `AndorDriver` — the cooling and acquire executors use only base-class methods, and `app.driver` is legitimately either subclass.

- [ ] **Step 6: Run to verify the tests pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_andor_disconnected_construct.py -v`

Expected: 5 passed, including `test_the_base_is_abstract`.

- [ ] **Step 7: Run the gates this move can break**

```bash
conda run -n helao python -m pytest helao/hexagon/tests/test_hte_builds_on_linux.py -v
conda run -n helao python -m pytest helao/hexagon/tests/test_hardware_import_sweep.py -v
conda run -n helao python -m pytest helao/hexagon/tests/test_hte_route_checklist.py -v
conda run -n helao python -m pytest helao/hexagon/tests/test_hte_action_shims.py -v
```

Expected: all pass. The route checklist must pass **unchanged** here — no route moved in this task, so a diff means the server edit went wrong.

- [ ] **Step 8: Type-check, format, commit**

```bash
conda run -n helao pyright helao/deploy/hte/drivers/spec/andor/ \
  helao/deploy/hte/servers/action/andor_server.py
git diff helao/hexagon/tests/checklists/hte/andor_server.json   # must be empty
conda run -n helao black helao/deploy/hte/drivers/spec/andor/driver.py \
  helao/deploy/hte/drivers/spec/andor/spectrograph.py \
  helao/deploy/hte/servers/action/andor_server.py \
  helao/hexagon/tests/test_andor_disconnected_construct.py
git add helao/deploy/hte/drivers/spec/andor/ \
        helao/deploy/hte/servers/action/andor_server.py \
        helao/hexagon/tests/test_andor_disconnected_construct.py
git commit -m "refactor(andor): move the spectrograph path into a subclass

AndorDriver keeps the camera and everything invariant and declares one
abstract _wavelengths(). AndorSpectrographDriver supplies it from
GetCalibration and carries setup_spectroscope and adjust_ND verbatim --
the legacy path is moved, not edited.

The base is abstract deliberately: a subclass that forgot _wavelengths
would acquire against a fabricated axis, and a wrong wavelength axis is
invisible in the recorded data afterwards."
```

---

### Task 4: `AndorCalibratedDriver`

**Files:**
- Create: `helao/deploy/hte/drivers/spec/andor/calibrated.py`
- Test: `helao/hexagon/tests/test_andor_calibrated_driver.py` (create)

**Interfaces:**
- Consumes: `AndorDriver` from Task 3, `wl_calibration.{load, evaluate, calibration_path, UnknownCalibrationModel}` from Task 2.
- Produces: `AndorCalibratedDriver(AndorDriver)` with `_wavelengths(self) -> Optional[np.ndarray]` and `calibration_file(self) -> Path`.

- [ ] **Step 1: Write the failing tests**

Create `helao/hexagon/tests/test_andor_calibrated_driver.py`:

```python
"""The lamp-calibrated Andor variant, construct- and load-tier only.

The cold-start rule is the load-bearing part: connect() must SUCCEED with no
calibration on disk, because the calibration action runs on this same server
and a refusing connect() would make the station uncalibratable forever. It is
`acquire` that must refuse, not `connect`.
"""

import json

import numpy as np
import pytest

from helao.deploy.hte.drivers.spec.andor import driver as andor_driver
from helao.deploy.hte.drivers.spec.andor import wl_calibration as wlc
from helao.deploy.hte.drivers.spec.andor.calibrated import AndorCalibratedDriver

CALIB = wlc.WavelengthCalibration(
    model=wlc.MODEL_POLY,
    coeffs=[400.0, 0.2],
    n_pixels=16,
    fit_rms_nm=0.02,
    n_lines=5,
    lamp="Hg-Ar",
    created="2026-09-04T00:00:00Z",
    source_action_uuid=None,
)


def _driver(tmp_path, **extra):
    config = {"dev_id": 0, "states_root": str(tmp_path), "host": "teststation"}
    config.update(extra)
    return AndorCalibratedDriver(config=config, server_key="ANDOR")


def test_construct_without_sdk_or_calibration(tmp_path):
    d = _driver(tmp_path)
    assert d.sdk3 is None
    assert d.cam is None
    assert d.wl_arr is None
    assert d.ready is True


def test_construct_does_not_import_the_spectrograph_module(tmp_path):
    """The whole point: this station has no pyAndorSpectrograph installed."""
    import sys

    sys.modules.pop("helao.deploy.hte.drivers.spec.andor.spectrograph", None)
    _driver(tmp_path)
    assert "helao.deploy.hte.drivers.spec.andor.spectrograph" not in sys.modules


def test_calibration_file_follows_the_convention(tmp_path):
    d = _driver(tmp_path)
    assert d.calibration_file().name == "teststation_ANDOR_andor_wl_calib.json"


def test_wavelengths_are_none_when_no_calibration_exists(tmp_path):
    d = _driver(tmp_path)
    assert d._wavelengths() is None


def test_wavelengths_come_from_the_persisted_calibration(tmp_path):
    d = _driver(tmp_path)
    wlc.save(CALIB, d.calibration_file())
    wl = d._wavelengths()
    assert wl is not None
    assert wl.shape == (16,)
    assert wl[0] == pytest.approx(400.0)
    assert wl[15] == pytest.approx(400.0 + 0.2 * 15)


def test_connect_succeeds_without_a_calibration(tmp_path, monkeypatch, caplog):
    """A refusing connect() would make the station uncalibratable forever."""

    class _FakeCam:
        pass

    class _FakeSDK:
        def GetCamera(self, dev_id):
            return _FakeCam()

    monkeypatch.setattr(andor_driver, "_load_camera", lambda: None)
    monkeypatch.setattr(andor_driver, "AndorSDK3", _FakeSDK, raising=False)

    d = _driver(tmp_path)
    monkeypatch.setattr(d, "setup_image", lambda: 1024)
    monkeypatch.setattr(d, "get_meta_data", lambda: (1, 1, 1, 1))

    resp = d.connect()
    assert resp.response == "success"
    assert d.wl_arr is None


def test_an_unreadable_model_is_refused_not_guessed(tmp_path):
    d = _driver(tmp_path)
    path = d.calibration_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "model": "chebyshev",
                "coeffs": [1.0],
                "n_pixels": 4,
                "fit_rms_nm": 0.0,
                "n_lines": 0,
                "lamp": "x",
                "created": "2026-09-04T00:00:00Z",
                "source_action_uuid": None,
            }
        )
    )
    with pytest.raises(wlc.UnknownCalibrationModel):
        d._wavelengths()
```

- [ ] **Step 2: Run to verify it fails**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_andor_calibrated_driver.py -v`

Expected: collection error, `ModuleNotFoundError: ...andor.calibrated`.

- [ ] **Step 3: Write the subclass**

Create `helao/deploy/hte/drivers/spec/andor/calibrated.py`:

```python
"""AndorDriver variant whose wavelength axis comes from a lamp calibration.

For a station whose grating, central wavelength, slit and ND filter are set by
hand at the instrument and never written by HELAO. Imports nothing from
``spectrograph.py``, so ``pyAndorSpectrograph`` need not be installed.
"""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Optional

import numpy as np

from helao.helpers import helao_logging as logging

from . import wl_calibration as wlc
from .driver import AndorDriver

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class AndorCalibratedDriver(AndorDriver):
    """Andor Zyla whose wavelength axis is read from a persisted lamp fit."""

    def __init__(self, config: dict = {}, server_key: str = "ANDOR"):
        """Construct without opening the camera or reading the calibration.

        Args:
            config: Driver configuration. ``states_root`` and ``host`` locate
                the calibration file; both fall back to sane values so a
                construct-test needs no station config.
            server_key: This server's key, part of the calibration filename
                because one host can run more than one andor server.
        """
        super().__init__(config=config)
        self.server_key = server_key

    def calibration_file(self) -> Path:
        """Where this server's persisted wavelength calibration lives."""
        states_root = self.config.get("states_root") or "STATES"
        host = self.config.get("host") or socket.gethostname()
        return wlc.calibration_path(states_root, host, self.server_key)

    def _wavelengths(self) -> Optional[np.ndarray]:
        """The calibrated axis, or ``None`` when none has been measured yet.

        ``None`` rather than a raise: ``connect()`` must succeed on an
        uncalibrated station, because the calibration action runs on this same
        server and a refusing connect() would make the station uncalibratable.
        ``acquire`` is where the refusal belongs, and it reads ``wl_arr``.

        An unreadable *model* is a different case and does raise -- a record
        this build cannot evaluate must not be silently guessed at.
        """
        path = self.calibration_file()
        if not path.exists():
            LOGGER.warning(
                "no wavelength calibration at %s; acquire will refuse until "
                "/ANDOR/calibrate_wl has been run on this station",
                path,
            )
            return None
        calib = wlc.load(path)
        LOGGER.info(
            "loaded wavelength calibration: %d px, %d lines, rms %.4f nm, lamp %s, "
            "created %s",
            calib.n_pixels,
            calib.n_lines,
            calib.fit_rms_nm,
            calib.lamp,
            calib.created,
        )
        return wlc.evaluate(calib)
```

- [ ] **Step 4: Run to verify it passes**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_andor_calibrated_driver.py -v`

Expected: 7 passed.

- [ ] **Step 5: Type-check, format, commit**

```bash
conda run -n helao pyright helao/deploy/hte/drivers/spec/andor/
git diff helao/hexagon/tests/checklists/hte/andor_server.json   # must be empty
conda run -n helao black helao/deploy/hte/drivers/spec/andor/calibrated.py \
  helao/hexagon/tests/test_andor_calibrated_driver.py
git add helao/deploy/hte/drivers/spec/andor/calibrated.py \
        helao/hexagon/tests/test_andor_calibrated_driver.py
git commit -m "feat(andor): wavelength axis from a persisted lamp calibration

connect() succeeds with no calibration on disk and logs a loud warning:
the calibration action runs on this same server, so a refusing connect()
would leave the station uncalibratable forever. acquire is where the
refusal belongs, and Task 5 puts it there.

An unrecognized model does raise -- that is a record this build cannot
evaluate, not an absent one."
```

---

### Task 5: `run_wl_calibration()` on the base, and the `acquire` refusal

The calibration lives on the base so a spectrograph station can measure a lamp and compare the fit against `GetCalibration` — the only way to build confidence in the new path before switching a station onto it.

**Files:**
- Modify: `helao/deploy/hte/drivers/spec/andor/driver.py` (add `run_wl_calibration`)
- Modify: `helao/deploy/hte/servers/action/andor_server.py:253-287` (the `acquire` handler)
- Test: `helao/hexagon/tests/test_andor_calibrated_driver.py` (append)

**Interfaces:**
- Consumes: `wl_calibration.{fit_wavelength, save}` from Task 2; `AndorCalibratedDriver.calibration_file` from Task 4.
- Produces: `AndorDriver.run_wl_calibration(self, lamp_lines_nm, *, lamp="Hg-Ar", n_frames=1, exp_time=0.0098, degree=3, source_action_uuid=None) -> DriverResponse`, whose `.data` carries `coeffs`, `fit_rms_nm`, `n_lines`, `lamp`, `path`, `applied`. Also `AndorDriver.calibration_file(self) -> Path` hoisted from Task 4's subclass, and `DEFAULT_LAMP_LINES_NM: list[float]`.

- [ ] **Step 1: Write the failing tests**

Append to `helao/hexagon/tests/test_andor_calibrated_driver.py`:

```python
from helao.deploy.hte.drivers.spec.andor.driver import DEFAULT_LAMP_LINES_NM


def _fake_lamp_frame(n_pixels, line_pixels):
    pixels = np.arange(n_pixels, dtype=float)
    counts = np.full(n_pixels, 100.0)
    for p in line_pixels:
        counts += 5000.0 * np.exp(-0.5 * ((pixels - p) / 2.0) ** 2)
    return counts


def test_the_default_lamp_line_table_is_usable(tmp_path):
    """A bare POST must be able to calibrate; the default must support the fit."""
    assert len(DEFAULT_LAMP_LINES_NM) >= 5
    assert DEFAULT_LAMP_LINES_NM == sorted(DEFAULT_LAMP_LINES_NM)


def test_run_wl_calibration_persists_and_reports(tmp_path, monkeypatch):
    d = _driver(tmp_path)
    line_pixels = [200, 700, 1300, 1900, 2400]
    true_nm = [400.0 + 0.2 * p for p in line_pixels]
    monkeypatch.setattr(
        d, "_capture_lamp_frame", lambda n_frames, exp_time: _fake_lamp_frame(2560, line_pixels)
    )

    resp = d.run_wl_calibration(true_nm, lamp="Hg-Ar", degree=1)
    assert resp.response == "success"
    assert resp.data["fit_rms_nm"] < 0.5
    assert resp.data["n_lines"] == 5
    assert resp.data["applied"] is True  # calibrated driver uses it live
    assert d.calibration_file().exists()


def test_run_wl_calibration_reports_failure_without_raising(tmp_path, monkeypatch):
    """An action handler must never see an exception out of the driver."""
    d = _driver(tmp_path)
    monkeypatch.setattr(
        d, "_capture_lamp_frame", lambda n_frames, exp_time: _fake_lamp_frame(2560, [200])
    )
    resp = d.run_wl_calibration([400.0, 500.0, 600.0, 700.0, 800.0], degree=3)
    assert resp.response == "failed"
    assert not d.calibration_file().exists()
```

Create `helao/hexagon/tests/test_andor_spectrograph_calibration.py`:

```python
"""A spectrograph station may measure a lamp; it just does not use it live.

This is the cross-check that validates the new path against the old one
before any station is switched over.
"""

import numpy as np

from helao.deploy.hte.drivers.spec.andor.spectrograph import AndorSpectrographDriver


def _fake_lamp_frame(n_pixels, line_pixels):
    pixels = np.arange(n_pixels, dtype=float)
    counts = np.full(n_pixels, 100.0)
    for p in line_pixels:
        counts += 5000.0 * np.exp(-0.5 * ((pixels - p) / 2.0) ** 2)
    return counts


def test_a_spectrograph_station_can_calibrate_but_does_not_apply_it(
    tmp_path, monkeypatch
):
    d = AndorSpectrographDriver(
        config={"states_root": str(tmp_path), "host": "teststation"},
        server_key="ANDOR",
    )
    line_pixels = [200, 700, 1300, 1900, 2400]
    true_nm = [400.0 + 0.2 * p for p in line_pixels]
    monkeypatch.setattr(
        d,
        "_capture_lamp_frame",
        lambda n_frames, exp_time: _fake_lamp_frame(2560, line_pixels),
    )

    resp = d.run_wl_calibration(true_nm, lamp="Hg-Ar", degree=1)
    assert resp.response == "success"
    assert resp.data["applied"] is False, "the spectrograph remains the live axis"
    assert d.calibration_file().exists()
```

- [ ] **Step 2: Run to verify they fail**

Run:
```bash
conda run -n helao python -m pytest \
  helao/hexagon/tests/test_andor_calibrated_driver.py \
  helao/hexagon/tests/test_andor_spectrograph_calibration.py -v
```

Expected: `ImportError: cannot import name 'DEFAULT_LAMP_LINES_NM'` and `AttributeError: ... has no attribute 'run_wl_calibration'`.

- [ ] **Step 3: Hoist `calibration_file` and add the calibration to the base**

Move `calibration_file` and the `server_key` constructor argument out of `calibrated.py` and onto `AndorDriver` in `driver.py`, so both subclasses have them. `AndorCalibratedDriver.__init__` and `AndorCalibratedDriver.calibration_file` are deleted; the base's `__init__` signature becomes:

```python
    def __init__(self, config: dict = {}, server_key: str = "ANDOR"):
```

with `self.server_key = server_key` set alongside `self.device_id`, and this method added to the base:

```python
    def calibration_file(self) -> Path:
        """Where this server's persisted wavelength calibration lives."""
        states_root = self.config.get("states_root") or "STATES"
        host = self.config.get("host") or socket.gethostname()
        return wl_calibration.calibration_path(states_root, host, self.server_key)
```

Add `import socket`, `from pathlib import Path`, and `from . import wl_calibration` to `driver.py`. `wl_calibration` is pure, so this adds no vendor import.

Add the default line table near the top of `driver.py`:

```python
#: Hg-Ar pen-lamp lines, nm, in air. The default reference set so a routine
#: recalibration is a bare POST. Override per-action with `lamp_lines_nm`.
DEFAULT_LAMP_LINES_NM: list[float] = [
    404.6565,
    435.8335,
    546.0750,
    576.9610,
    579.0670,
    696.5431,
    763.5106,
    811.5311,
    912.2967,
]
```

- [ ] **Step 4: Add the capture helper and the calibration routine**

Add both to `AndorDriver` in `driver.py`:

```python
    def _capture_lamp_frame(self, n_frames: int, exp_time: float) -> np.ndarray:
        """Average ``n_frames`` single captures into one spectrum.

        Separated from :meth:`run_wl_calibration` so the fit can be tested
        without a camera: the tests replace this method and leave the rest of
        the routine real.
        """
        frames = []
        for _ in range(n_frames):
            acq, _max, _in_range, _optimality = self.image_and_check_dynamic_range(
                exposure_time=exp_time
            )
            # acq.image is 2D: vertical (spatial) rows by horizontal
            # (wavelength) columns -- the same orientation the commented
            # imshow in image_and_check_dynamic_range assumes with
            # extent=[wl_arr[0], wl_arr[-1], 0, 2160]. Sum down the spatial
            # axis to get one spectrum per frame.
            image = np.asarray(acq.image, dtype=float)
            if image.ndim != 2:
                raise ValueError(f"expected a 2D detector image, got {image.shape}")
            frames.append(image.sum(axis=0))
        return np.mean(np.vstack(frames), axis=0)

    def run_wl_calibration(
        self,
        lamp_lines_nm: Optional[list] = None,
        *,
        lamp: str = "Hg-Ar",
        n_frames: int = 1,
        exp_time: float = 0.0098,
        degree: int = 3,
        source_action_uuid: Optional[str] = None,
    ) -> DriverResponse:
        """Measure a calibration lamp, fit pixel-to-nm, and persist the result.

        Available on both variants. On a lamp-calibrated station the result
        becomes the live wavelength axis at the next ``connect()``; on a
        spectrograph station it is recorded for comparison against
        ``GetCalibration`` and does not change what ``acquire`` uses.

        Returns:
            A :class:`DriverResponse` whose ``data`` carries ``coeffs``,
            ``fit_rms_nm``, ``n_lines``, ``lamp``, ``path`` and ``applied``.
            Never raises: an action handler must not see an exception.
        """
        try:
            lines = list(lamp_lines_nm) if lamp_lines_nm else DEFAULT_LAMP_LINES_NM
            counts = self._capture_lamp_frame(n_frames, exp_time)
            calib = wl_calibration.fit_wavelength(
                counts,
                lines,
                degree=degree,
                lamp=lamp,
                source_action_uuid=source_action_uuid,
            )
            path = self.calibration_file()
            wl_calibration.save(calib, path)
            LOGGER.info(
                "wavelength calibration written to %s (rms %.4f nm over %d lines)",
                path,
                calib.fit_rms_nm,
                calib.n_lines,
            )
            return DriverResponse(
                response=DriverResponseType.success,
                status=DriverStatus.ok,
                data={
                    "coeffs": calib.coeffs,
                    "fit_rms_nm": calib.fit_rms_nm,
                    "n_lines": calib.n_lines,
                    "lamp": calib.lamp,
                    "path": str(path),
                    "applied": self.uses_lamp_calibration,
                },
            )
        except Exception:
            LOGGER.error("run_wl_calibration failed", exc_info=True)
            return DriverResponse(
                response=DriverResponseType.failed, status=DriverStatus.error
            )
```

Add a class attribute to the base declaring which variant applies the result:

```python
    #: Whether this variant's live wavelength axis comes from the lamp fit.
    #: Reported back as `applied` so an operator can tell, from the action's
    #: own output, whether the calibration they just ran changed anything.
    uses_lamp_calibration: bool = False
```

and in `calibrated.py`, on `AndorCalibratedDriver`:

```python
    uses_lamp_calibration = True
```

- [ ] **Step 5: Make `acquire` refuse without a calibration**

In `helao/deploy/hte/servers/action/andor_server.py`, in the `acquire` handler (`:253`), insert immediately after the signature and before `active = await ctx.begin()`:

```python
        if app.driver.wl_arr is None:
            LOGGER.error(
                "acquire refused: no wavelength calibration on this station. "
                "Run POST /%s/calibrate_wl, then restart this server.",
                server_key,
            )
            active = await ctx.begin()
            active.action.error_code = ErrorCodes.critical_error
            finished_action = await active.finish()
            return finished_action.as_dict()
```

It cannot fall back to a bare pixel index: `:269` derives the channel names from `wl_arr.shape[0]` and `:277` emits `optional={"wl": list(app.driver.wl_arr)}`, so a fallback would record a run against a fabricated axis that looks entirely healthy afterwards.

- [ ] **Step 6: Run to verify the tests pass**

```bash
conda run -n helao python -m pytest \
  helao/hexagon/tests/test_andor_calibrated_driver.py \
  helao/hexagon/tests/test_andor_spectrograph_calibration.py \
  helao/hexagon/tests/test_andor_disconnected_construct.py -v
```

Expected: all pass. The construct tests still pass because the base's new `__init__` argument is defaulted.

- [ ] **Step 7: Confirm the route surface has not moved yet**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_hte_route_checklist.py -v`

Expected: pass. No route was added in this task — `acquire` only gained a guard. A diff here means the handler edit changed the signature, which it must not.

- [ ] **Step 8: Type-check, format, commit**

```bash
conda run -n helao pyright helao/deploy/hte/drivers/spec/andor/ \
  helao/deploy/hte/servers/action/andor_server.py
git diff helao/hexagon/tests/checklists/hte/andor_server.json   # must be empty
conda run -n helao black helao/deploy/hte/drivers/spec/andor/ \
  helao/deploy/hte/servers/action/andor_server.py \
  helao/hexagon/tests/test_andor_calibrated_driver.py \
  helao/hexagon/tests/test_andor_spectrograph_calibration.py
git add helao/deploy/hte/drivers/spec/andor/ \
        helao/deploy/hte/servers/action/andor_server.py \
        helao/hexagon/tests/test_andor_calibrated_driver.py \
        helao/hexagon/tests/test_andor_spectrograph_calibration.py
git commit -m "feat(andor): lamp calibration on both variants; acquire refuses without one

run_wl_calibration lives on the base so a spectrograph station can fit a
lamp and compare it against GetCalibration -- the cross-check that
validates the new path before a station is switched onto it. It reports
'applied' so the operator can tell from the action's own output whether
what they ran changed the live axis.

acquire refuses when wl_arr is None rather than falling back to a pixel
index: the channel names and optional.wl both come from wl_arr, so a
fallback records a run against a fabricated axis that looks healthy."
```

---

### Task 6: Config-driven class selection

**Files:**
- Modify: `helao/deploy/hte/servers/action/andor_server.py:321-350` (`makeApp`)
- Test: `helao/hexagon/tests/test_andor_server_composition.py` (create)

**Interfaces:**
- Consumes: both subclasses from Tasks 3 and 4.
- Produces: `andor_server._driver_class(server_key: str) -> type[AndorDriver]`.

- [ ] **Step 1: Write the failing tests**

Create `helao/hexagon/tests/test_andor_server_composition.py`:

```python
"""`wl_source` picks the driver class, and its default keeps hispec.yml valid.

The default matters more than the key does. `test_hte_builds_on_linux.py`
loads every station config and calls makeApp; hispec.yml declares no
`wl_source`, and it must not need editing for this change to land.
"""

import pytest

from helao.deploy.hte.servers.action import andor_server
from helao.deploy.hte.drivers.spec.andor.calibrated import AndorCalibratedDriver
from helao.deploy.hte.drivers.spec.andor.spectrograph import AndorSpectrographDriver
from helao.helpers import config_loader


@pytest.fixture
def with_config(monkeypatch):
    def _set(params):
        monkeypatch.setattr(
            config_loader,
            "CONFIG",
            {"servers": {"ANDOR": {"group": "action", "params": params}}},
        )

    return _set


def test_an_absent_key_yields_the_spectrograph_driver(with_config):
    """hispec.yml has no wl_source and must keep working untouched."""
    with_config({"dev_id": 0})
    assert andor_server._driver_class("ANDOR") is AndorSpectrographDriver


def test_spectrograph_is_selectable_explicitly(with_config):
    with_config({"dev_id": 0, "wl_source": "spectrograph"})
    assert andor_server._driver_class("ANDOR") is AndorSpectrographDriver


def test_calibration_selects_the_calibrated_driver(with_config):
    with_config({"dev_id": 0, "wl_source": "calibration"})
    assert andor_server._driver_class("ANDOR") is AndorCalibratedDriver


def test_an_unknown_value_is_refused_loudly(with_config):
    """A typo must not silently fall through to the default."""
    with_config({"dev_id": 0, "wl_source": "spectograph"})
    with pytest.raises(ValueError, match="spectograph"):
        andor_server._driver_class("ANDOR")


def test_no_config_at_all_still_yields_the_default(monkeypatch):
    """makeApp is called outside the launcher by tests and capture scripts."""
    monkeypatch.setattr(config_loader, "CONFIG", None)
    assert andor_server._driver_class("ANDOR") is AndorSpectrographDriver


def test_a_server_key_absent_from_config_yields_the_default(with_config):
    with_config({"dev_id": 0, "wl_source": "calibration"})
    assert andor_server._driver_class("SOME_OTHER_KEY") is AndorSpectrographDriver
```

- [ ] **Step 2: Run to verify it fails**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_andor_server_composition.py -v`

Expected: `AttributeError: module ... has no attribute '_driver_class'`.

- [ ] **Step 3: Implement the selector**

In `helao/deploy/hte/servers/action/andor_server.py`, add the import and the function above `makeApp`:

```python
from helao.helpers import config_loader

from ...drivers.spec.andor.calibrated import AndorCalibratedDriver

#: `wl_source` value -> driver class. An absent key yields the spectrograph
#: driver so every existing station config keeps working unedited; a station
#: opts into the lamp-calibrated path by adding the key.
WL_SOURCES: dict[str, type] = {
    "spectrograph": AndorSpectrographDriver,
    "calibration": AndorCalibratedDriver,
}
DEFAULT_WL_SOURCE = "spectrograph"


def _driver_class(server_key: str) -> type:
    """The driver class this server's config selects.

    Reads the global CONFIG, which ``fast_launcher.py`` populates before it
    imports this module and calls ``makeApp``. Tolerates a missing CONFIG or
    server entry, because capture scripts and build tests call ``makeApp``
    outside the launcher.

    Raises:
        ValueError: On an unrecognized ``wl_source``. A typo must not fall
            through to the default -- a station meaning to run the calibrated
            path would silently get the spectrograph one and fail at
            ``connect()`` with a vendor import error instead.
    """
    config = getattr(config_loader, "CONFIG", None) or {}
    params = (config.get("servers") or {}).get(server_key, {}).get("params", {}) or {}
    name = params.get("wl_source", DEFAULT_WL_SOURCE)
    if name not in WL_SOURCES:
        raise ValueError(
            f"unknown wl_source {name!r} for server {server_key!r}; "
            f"expected one of {sorted(WL_SOURCES)}"
        )
    return WL_SOURCES[name]
```

In `makeApp`, change `driver_classes=[AndorSpectrographDriver]` to:

```python
        driver_classes=[_driver_class(server_key)],
```

Add to `makeApp`'s docstring, after the existing `Constructs a ...` sentence:

```
    The driver class is selected by the server's ``wl_source`` param
    (``spectrograph`` or ``calibration``), defaulting to ``spectrograph`` so an
    existing station config needs no edit. Note that ``base_api`` names the
    driver namedtuple field from the class name, so ``app.drivers.<Name>``
    differs between the two -- use ``app.driver``.
```

- [ ] **Step 4: Run to verify it passes**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_andor_server_composition.py -v`

Expected: 6 passed.

- [ ] **Step 5: Verify hispec.yml still builds untouched**

```bash
git diff --stat helao/deploy/hte/configs/   # must be empty
conda run -n helao python -m pytest helao/hexagon/tests/test_hte_builds_on_linux.py -v
```

Expected: pass, with no config edited. This is the assertion the whole default exists to satisfy.

- [ ] **Step 6: Type-check, format, commit**

```bash
conda run -n helao pyright helao/deploy/hte/servers/action/andor_server.py
git diff helao/hexagon/tests/checklists/hte/andor_server.json   # must be empty
conda run -n helao black helao/deploy/hte/servers/action/andor_server.py \
  helao/hexagon/tests/test_andor_server_composition.py
git add helao/deploy/hte/servers/action/andor_server.py \
        helao/hexagon/tests/test_andor_server_composition.py
git commit -m "feat(andor): select the driver variant from a wl_source config key

An absent key yields the spectrograph driver, so hispec.yml needs no
edit and the Linux build gate passes against an unmodified config. An
unrecognized value raises rather than defaulting: a typo would otherwise
hand a lamp-calibrated station the spectrograph driver, which fails much
later at connect() with a vendor import error."
```

---

### Task 7: The `calibrate_wl` route, the `adjust_nd` refusal, and the allowlist entry

The only task that moves the route surface. It depends on the additions-allowlist plan being complete.

**Files:**
- Modify: `helao/deploy/hte/servers/action/andor_server.py` (new executor, new route, `adjust_nd` guard)
- Modify: `helao/hexagon/tests/checklists/hte/_additions.json`
- Test: `helao/hexagon/tests/test_andor_server_composition.py` (append)

**Interfaces:**
- Consumes: `_driver_class` from Task 6, `run_wl_calibration` from Task 5, `filter_allowed_additions` and `_additions.json` from the allowlist plan.
- Produces: `POST /{server_key}/calibrate_wl` with params `lamp_lines_nm: list = []`, `lamp: str = "Hg-Ar"`, `n_frames: int = 1`, `exp_time: float = 0.0098`, `degree: int = 3`.

- [ ] **Step 1: Confirm the prerequisite is in place**

```bash
cat helao/hexagon/tests/checklists/hte/_additions.json
conda run -n helao python -c \
  "from harness.endpoints import filter_allowed_additions; print('ok')"
```

Expected: `[]` and `ok`. If either fails, stop and complete `2026-09-04-frozen-checklist-additions-allowlist.md` first.

- [ ] **Step 2: Write the failing tests**

Append to `helao/hexagon/tests/test_andor_server_composition.py`:

```python
def test_adjust_nd_is_still_frozen_and_calibrate_wl_is_listed():
    """adjust_nd survives this work; only calibrate_wl is added."""
    import json
    from pathlib import Path

    frozen = json.loads(
        Path("helao/hexagon/tests/checklists/hte/andor_server.json").read_text()
    )
    paths = {r["path"] for r in frozen}
    assert "/ANDOR/adjust_nd" in paths, "the frozen record must not have been edited"
    assert "/ANDOR/calibrate_wl" not in paths, "additions go in _additions.json"

    additions = json.loads(
        Path("helao/hexagon/tests/checklists/hte/_additions.json").read_text()
    )
    entry = [a for a in additions if a["path"] == "/ANDOR/calibrate_wl"]
    assert len(entry) == 1, "calibrate_wl must be listed exactly once"
    assert entry[0]["module"] == "andor_server.py"
    assert entry[0]["method"] == "post"
```

- [ ] **Step 3: Run to verify it fails**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_andor_server_composition.py::test_adjust_nd_is_still_frozen_and_calibrate_wl_is_listed -v`

Expected: FAIL, `calibrate_wl must be listed exactly once`.

- [ ] **Step 4: Add the executor and the route**

In `helao/deploy/hte/servers/action/andor_server.py`, add the executor beside `AndorAdjustND`:

```python
class AndorCalibrateWavelength(Executor):
    """Executor that measures a calibration lamp and fits the wavelength axis.

    One-shot: ``_exec`` calls :meth:`AndorDriver.run_wl_calibration` and
    forwards its data payload, which reports whether the fit became the live
    axis on this station.
    """

    driver: AndorDriver

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            self.action_params = self.active.action.action_params
            self.lamp_lines_nm = self.action_params.get("lamp_lines_nm") or None
            self.lamp = self.action_params.get("lamp", "Hg-Ar")
            self.n_frames = self.action_params.get("n_frames", 1)
            self.exp_time = self.action_params.get("exp_time", 0.0098)
            self.degree = self.action_params.get("degree", 3)
        except Exception:
            LOGGER.error("AndorCalibrateWavelength init failed", exc_info=True)

    async def _exec(self) -> dict:
        """Call :meth:`AndorDriver.run_wl_calibration` and forward its data."""
        LOGGER.debug("Running driver.run_wl_calibration()")
        resp = self.driver.run_wl_calibration(
            self.lamp_lines_nm,
            lamp=self.lamp,
            n_frames=self.n_frames,
            exp_time=self.exp_time,
            degree=self.degree,
            source_action_uuid=str(self.active.action.action_uuid),
        )
        error = (
            ErrorCodes.none if resp.response == "success" else ErrorCodes.critical_error
        )
        return {"error": error, "data": resp.data}
```

Add the route inside `andor_dyn_endpoints`, immediately after `adjust_nd`:

```python
    @app.action()
    async def calibrate_wl(
        ctx: ActionContext,
        lamp_lines_nm: list = [],
        lamp: str = "Hg-Ar",
        n_frames: int = 1,
        exp_time: float = 0.0098,
        degree: int = 3,
    ):
        """Measure a calibration lamp and fit this detector's wavelength axis.

        Works on both driver variants. On a spectrograph station the fit is
        recorded for comparison against ``GetCalibration`` and the live axis is
        unchanged; the response's ``applied`` field says which happened.
        """
        active = await ctx.begin()
        executor = AndorCalibrateWavelength(active=active, oneoff=True)
        active_action_dict = active.start_executor(executor)
        return active_action_dict
```

Registration is unconditional and correct: the checklist extractor reads source, so wrapping a decorator in a config test would keep the source surface uniform while the live OpenAPI differed per station, which no gate can see.

- [ ] **Step 5: Guard `adjust_nd`**

Replace the `adjust_nd` handler body (`:313-319`) with:

```python
    @app.action()
    async def adjust_nd(ctx: ActionContext):
        """Run the ND-filter auto-selection routine via :class:`AndorAdjustND`."""
        if not isinstance(app.driver, AndorSpectrographDriver):
            LOGGER.error(
                "adjust_nd refused: this station has no software-controlled ND "
                "filter wheel (wl_source=calibration). Set the filter by hand."
            )
            active = await ctx.begin()
            active.action.error_code = ErrorCodes.critical_error
            finished_action = await active.finish()
            return finished_action.as_dict()
        active = await ctx.begin()
        executor = AndorAdjustND(active=active, oneoff=True)
        active_action_dict = active.start_executor(executor)
        return active_action_dict
```

The decorator and signature are untouched, so the frozen record still matches.

- [ ] **Step 6: Add the allowlist entry**

Replace `helao/hexagon/tests/checklists/hte/_additions.json` with:

```json
[
  {
    "module": "andor_server.py",
    "path": "/ANDOR/calibrate_wl",
    "method": "post",
    "date": "2026-09-04",
    "why": "lamp wavelength calibration for stations without a software-controlled spectrograph; see docs/superpowers/specs/2026-09-04-andor-driver-split-design.md"
  }
]
```

- [ ] **Step 7: Run every affected gate**

```bash
conda run -n helao python -m pytest helao/hexagon/tests/test_hte_route_checklist.py -v
conda run -n helao python -m pytest helao/hexagon/tests/test_andor_server_composition.py -v
conda run -n helao python -m pytest helao/hexagon/tests/test_hte_builds_on_linux.py -v
```

Expected: all pass. `test_module_matches_its_frozen_checklist[andor_server.py]` passes because the allowlist absorbs the one `extra` diff; `test_no_addition_entry_is_stale` passes because the route now exists in source.

- [ ] **Step 8: Type-check, format, commit**

Commit *before* the red-proof below, so the destructive edit it needs can be
undone with `git checkout --` without risking any uncommitted work. (Never
`git stash` in this repo — the stash stack carries other branches' work and
popping onto a clean tree restores it as conflicts.)

```bash
git diff helao/hexagon/tests/checklists/hte/andor_server.json   # MUST be empty
conda run -n helao pyright helao/deploy/hte/servers/action/andor_server.py
conda run -n helao black helao/deploy/hte/servers/action/andor_server.py \
  helao/hexagon/tests/test_andor_server_composition.py
git add helao/deploy/hte/servers/action/andor_server.py \
        helao/hexagon/tests/test_andor_server_composition.py \
        helao/hexagon/tests/checklists/hte/_additions.json
git commit -m "feat(andor): add the calibrate_wl route and refuse adjust_nd when unwired

Both routes are registered unconditionally in source. The extractor reads
source, so a config-wrapped decorator would present a uniform surface
while the live OpenAPI differed per station -- a divergence no gate can
observe. The handlers refuse instead.

adjust_nd's decorator and signature are untouched, so andor_server.json
stays byte-identical; calibrate_wl is recorded in _additions.json."
```

- [ ] **Step 9: Prove the allowlist is not laundering a removal**

The allowlist now absorbs one `extra` diff for this module. Confirm it did not
also weaken the gate against a deletion — that is the whole claim the mechanism
rests on, and a green gate is not evidence of it.

Comment out the `@app.action()` decorator on `adjust_nd` in
`helao/deploy/hte/servers/action/andor_server.py`, then:

```bash
conda run -n helao python -m pytest \
  "helao/hexagon/tests/test_hte_route_checklist.py::test_module_matches_its_frozen_checklist[andor_server.py]" -v
```

Expected: FAIL with a `missing` diff for `/ANDOR/adjust_nd`.

Restore and confirm green:

```bash
git checkout -- helao/deploy/hte/servers/action/andor_server.py
conda run -n helao python -m pytest helao/hexagon/tests/test_hte_route_checklist.py -v
git status --short   # must be clean
```

Expected: all pass, working tree clean. Nothing to commit — this step changes no
committed file.

---

### Task 8: Sole-importer guard, docs, and the station gate list

**Files:**
- Test: `helao/hexagon/tests/test_andor_vendor_isolation.py` (create)
- Modify: `CLAUDE.md` (append an Andor subsection)
- Modify: `docs/superpowers/notes/2026-08-15-B5-station-gate-runbook.md` (append the expected delta)

**Interfaces:** none produced.

- [ ] **Step 1: Write the failing test**

Create `helao/hexagon/tests/test_andor_vendor_isolation.py`:

```python
"""`spectrograph.py` is the only module that IMPORTS pyAndorSpectrograph.

This is the property the whole split exists for, and it is the one that
would rot silently: an import added to driver.py or calibrated.py breaks a
spectrograph-free station at connect() and nothing else would notice on
Linux, because the package is absent here either way.

Checked by parsing imports, not by grepping source text. A grep for the
bare package name also matches the docstrings that explain the rule --
calibrated.py says "pyAndorSpectrograph need not be installed", which is
documentation, not a dependency. Import statements are the actual hazard.
"""

import ast
from pathlib import Path

ANDOR = Path("helao/deploy/hte/drivers/spec/andor")
ALLOWED = {"spectrograph.py"}


def _imported_modules(path: Path) -> set[str]:
    """Every module name this file imports, however it spells the import."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            # level>0 is a relative import; node.module is None for `from . import x`
            prefix = "." * node.level + (node.module or "")
            names.add(prefix)
            names.update(f"{prefix}.{a.name}".lstrip(".") for a in node.names)
    return names


def test_only_spectrograph_py_imports_the_vendor_package():
    offenders = []
    for path in sorted(ANDOR.glob("*.py")):
        if path.name in ALLOWED:
            continue
        if any(n.startswith("pyAndorSpectrograph") for n in _imported_modules(path)):
            offenders.append(path.name)
    assert offenders == [], f"{offenders} must not import pyAndorSpectrograph"


def test_spectrograph_py_actually_imports_it():
    """A guard that passes because the target moved is not a guard."""
    names = _imported_modules(ANDOR / "spectrograph.py")
    assert any(n.startswith("pyAndorSpectrograph") for n in names), names


def test_the_calibrated_driver_does_not_import_the_spectrograph_module():
    names = _imported_modules(ANDOR / "calibrated.py")
    assert not any("spectrograph" in n for n in names), names


def test_the_base_does_not_import_either_subclass():
    """A base importing its subclasses would defeat the whole split."""
    names = _imported_modules(ANDOR / "driver.py")
    assert not any("spectrograph" in n or "calibrated" in n for n in names), names
```

- [ ] **Step 2: Run to verify it passes**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_andor_vendor_isolation.py -v`

Expected: 4 passed. If `test_only_spectrograph_py_imports_the_vendor_package` fails, an earlier task left a real import behind — fix that module, do not widen `ALLOWED`.

- [ ] **Step 3: Prove the guard goes red**

Temporarily add `from pyAndorSpectrograph.spectrograph import ATSpectrograph` inside a function in `calibrated.py` (module scope would trip the import sweep instead), re-run the test, confirm it fails naming `calibrated.py`, then remove the line and re-run to confirm green. A bare `# pyAndorSpectrograph` comment must NOT trip it — that is the false positive this guard was rewritten to avoid.

- [ ] **Step 4: Document it in CLAUDE.md**

Append this subsection to `CLAUDE.md`, immediately after the "Ocean Insight spectrometers (OceanDirect)" section:

```markdown
### Andor Zyla + spectrograph (two driver variants)

`helao/deploy/hte/drivers/spec/andor/` holds one camera base and two variants,
selected by the action server's `wl_source` param (`spectrograph` | `calibration`).

- **The base is abstract on `_wavelengths()` alone.** Everything else — SDK handle,
  camera, imaging, acquire loop, cooling, buffers — is shared. A subclass that
  forgot the hook would acquire against a fabricated wavelength axis, which is
  invisible in the recorded data, so it is `@abstractmethod` rather than a
  defaulted hook.
- **`spectrograph.py` is the only module that imports `pyAndorSpectrograph`**, pinned by
  `test_andor_vendor_isolation.py`, which parses imports rather than grepping source —
  a grep also matches the docstrings explaining the rule. What actually makes a spectrograph-free station
  possible is that `_load_andor()` was split into `_load_camera()` and
  `_load_spectrograph()`: the combined loader was called unconditionally from
  `connect()`, so the class split alone would have changed nothing — a subclass
  inherits that `connect()`.
- **An absent `wl_source` yields the spectrograph driver**, so every existing station
  config keeps working unedited. An *unrecognized* value raises: a typo would
  otherwise hand a lamp-calibrated station the spectrograph driver and fail much
  later at `connect()` with a vendor import error.
- **`connect()` succeeds on an uncalibrated station; `acquire` is what refuses.** The
  calibration action runs on the same server, so a refusing `connect()` would leave
  the station uncalibratable forever. `acquire` cannot fall back to a pixel index —
  both the channel names and `optional.wl` come from `wl_arr`.
- **`run_wl_calibration()` is on the base, so a spectrograph station can measure a
  lamp too** and compare the fit against `GetCalibration` without changing its live
  axis. The response's `applied` field says which happened.
- **`base_api` names the driver namedtuple field from the class name**, so
  `app.drivers.AndorSpectrographDriver` and `app.drivers.AndorCalibratedDriver`
  differ per station. Use `app.driver`.
- Persisted calibration: `<STATES>/<host>_<server_key>_andor_wl_calib.json`,
  coefficients not an array, with `model` refused on an unrecognized value rather
  than mis-evaluated.
```

- [ ] **Step 5: Record the expected station-gate delta**

Append to `docs/superpowers/notes/2026-08-15-B5-station-gate-runbook.md`:

```markdown
## Expected delta: `/ANDOR/calibrate_wl` (2026-09-04)

The `unstable`-versus-branch run-tree diff will show one added route on the ANDOR
server, `POST /ANDOR/calibrate_wl`. It is intentional and recorded in
`helao/hexagon/tests/checklists/hte/_additions.json`. `adjust_nd` is unchanged.
Any *other* ANDOR route delta is a regression, not this.
```

- [ ] **Step 6: Run the whole affected surface one last time**

```bash
conda run -n helao python run_unit_tests.py
for f in test_andor_disconnected_construct test_andor_wl_calibration \
         test_andor_calibrated_driver test_andor_spectrograph_calibration \
         test_andor_server_composition test_andor_vendor_isolation \
         test_hte_route_checklist test_hte_builds_on_linux \
         test_hardware_import_sweep test_checklist_additions; do
  echo "=== $f"
  timeout 300 conda run -n helao python -m pytest "helao/hexagon/tests/$f.py" -q
done
```

Expected: `run_unit_tests.py` exits 0 and every file passes. Run them per-file: the hexagon suite hangs when collected as a single pytest session.

- [ ] **Step 7: Commit**

```bash
git diff helao/hexagon/tests/checklists/hte/andor_server.json   # must be empty
conda run -n helao black helao/hexagon/tests/test_andor_vendor_isolation.py
git add helao/hexagon/tests/test_andor_vendor_isolation.py CLAUDE.md \
        docs/superpowers/notes/2026-08-15-B5-station-gate-runbook.md
git commit -m "test(andor): pin spectrograph.py as the sole vendor importer

The property the split exists for, and the one that would rot silently:
an import added to driver.py breaks a spectrograph-free station at
connect() and nothing else notices on Linux, where the package is absent
either way. Also records the expected calibrate_wl delta in the B5
station-gate runbook so it is not read as a regression."
```

---

## At-station gates (not attempted here)

None of these can run on Linux. They belong on a Windows station with the hardware attached.

1. **`hispec.yml` unedited still acquires.** Launch the hispec group, run one `ANDOR/acquire`, confirm the run tree matches what `unstable` produces. This is the regression that matters most: the legacy path was moved, not rewritten, and this is what says so.
2. **`adjust_nd` still works on the spectrograph station.** Run it, confirm the ND wheel moves and the chosen filter is reported.
3. **A calibrated station refuses `acquire` before calibration.** Set `wl_source: calibration`, launch with no calibration file, confirm `acquire` fails with the message rather than recording a run.
4. **The calibration round-trip.** Run `ANDOR/calibrate_wl` with the lamp lit, confirm the JSON appears in STATES with a plausible `fit_rms_nm`, restart the server, confirm `acquire` now succeeds and `optional.wl` spans the expected range.
5. **The cross-check.** On the spectrograph station, run `calibrate_wl` with the lamp lit and compare the fitted axis against the `GetCalibration` axis the same server is using live. `applied` must read `false`. A large disagreement is a finding about the fit, not a reason to switch a station over.
6. **A station without `pyAndorSpectrograph` installed.** The real proof of the loader split. Set `wl_source: calibration` on a machine with only the camera SDK and confirm `connect()` succeeds.

## Done when

- Every Linux test in Step 6 of Task 8 passes and `run_unit_tests.py` exits 0.
- `git diff unstable...HEAD -- helao/hexagon/tests/checklists/hte/` shows only `_additions.json`.
- `git diff unstable...HEAD -- helao/deploy/hte/configs/` is empty.
- `conda run -n helao python -m pytest helao/hexagon/tests/test_andor_vendor_isolation.py -v` passes: only `spectrograph.py` imports the vendor package.
- The six at-station gates above are listed for the station owner and none is claimed as passed.
