# P3a-2 — hte lazy-import completion (nidaqmx / pal / andor) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the §11.1 lazy-vendor-import work so `nidaqmx_driver`, `pal_driver`, and `andor/driver` import on a vendor-less Linux box, moving them from the import-sweep's `xfail` set to the asserted-import set. (biologic deferred — see below; the constructor-connect §10.4 fixes are deferred to the native-adapter splits.)

**Architecture:** Two lazy patterns, chosen by usage breadth:
- **Single-site use → per-method local import** (pal: `nidaqmx` in one method).
- **Pervasive use across many methods → a module-level `_load_<vendor>()` that imports into module globals via `global`, called at the top of `connect()`** (nidaqmx, andor). This avoids repeating a long constant list at every call site and keeps one edit point. It relies on the lifecycle guarantee that `connect()` runs before `setup`/`measure`/`get_data` — true for every HELAO driver.
- andor additionally needs `from __future__ import annotations` (its class body has `cam: AndorSDK3`, a bare annotation Python evaluates at class-definition/import time without the future import).

All changes are behavior-preserving: on a Windows/hardware box the same symbols are imported before first use; only the import *timing/location* moves.

**Tech Stack:** Python 3.12 (`conda run -n helao`), pytest under `helao/hexagon/tests/`, `black` line-length 88.

## Global Constraints

- **conda run -n helao** for every python/pytest. **black** (88) before every commit.
- **Behavior-preservation gate:** the `_load_*()` call must precede any use of the loaded names on every live code path. Since all uses are inside methods that run after `connect()`, calling `_load_*()` at the top of `connect()` suffices — VERIFY per file that no vendor symbol is referenced at module scope, class scope, or in a default-argument (those run at import/definition and would break). If any is, that symbol needs separate handling (record it, don't force).
- **Live-station instrument drivers** (parent repo, tracked). Import relocation only; NO logic/algorithm changes. The constructor-connect (`__init__` calls `connect()`/instantiates a device) is NOT touched here — deferred to the native-adapter splits.
- Branch: `feat/p3a2-lazy-imports` off `feat/p3a1-hardware-import-sweep` (stacked; needs the sweep test). Do NOT push / no PRs.

## Deferred (NOT in this plan)

- **biologic** (`pstat/biologic/driver.py` + `technique.py`): `technique.py` references `blp.OCV`/`blp.CA`/`blp.CV`/`blp.PEIS`/`blp.GEIS`/`blp.CP` at **module scope** (the technique registry is built at import) plus a `easy_class: BiologicProgram` class annotation — making it import-lazy is a registry restructure (store technique names/factories, resolve `getattr(blp, ...)` at use), not an import move. Folded into the biologic native-adapter work. Stays `xfail`.
- **Constructor-connect §10.4 cluster** (KinesisMotor / GamryDriver / AndorDriver `__init__` device work): deferred to the respective native splits (kinesis/galil motion, Gamry COM, andor). andor's `AndorSDK3()` in `__init__` remains here — the import-sweep tests *import*, not construct, so andor's module still imports after this plan.

## Verified inputs (2026-07-18 live grep)

- `io/nidaqmx_driver.py`: module-top L27 `import nidaqmx`, L28-37 `from nidaqmx.constants import (LineGrouping, Edge, AcquisitionType, TerminalConfiguration, VoltageUnits, TemperatureUnits, ThermocoupleType, CurrentShuntResistorLocation, UnitsPreScaled, TriggerType)`. All uses are in method bodies (`connect`/`setup`/`measure`-style around L194-393, DO/DI methods L651/L691). No `__init__` connect (server `nidaqmx_server.py:65` calls connect()).
- `robot/pal_driver.py`: module-top L67 `import nidaqmx`, L68 `from nidaqmx.constants import LineGrouping`. Only real use L547-564 (one method, the trigger block).
- `spec/andor/driver.py`: NO `from __future__ import annotations`; module-top L8 `from pyAndorSDK3 import AndorSDK3, CameraException`, L13 `from pyAndorSpectrograph.spectrograph import ATSpectrograph`; class annotation L47 `cam: AndorSDK3`; uses in `__init__` (L77 `AndorSDK3()`), spectrograph methods (L334/L435 `ATSpectrograph()`, L348/L448 `ATSpectrograph.ATSPECTROGRAPH_SUCCESS`), L790 `except CameraException`.

---

### Task 1: pal — per-method lazy `nidaqmx` import (single method)

**Files:** Modify `helao/deploy/hte/drivers/robot/pal_driver.py`; edit `helao/hexagon/tests/test_hardware_import_sweep.py` (move `robot.pal_driver` SLICE2→SLICE1).

- [ ] **Step 1: Confirm single-method use** — `grep -nE "nidaqmx|LineGrouping" helao/deploy/hte/drivers/robot/pal_driver.py`. Expect module-top L67-68 + uses only in the one method containing L547-564. Identify that method's `def` name.

- [ ] **Step 2: Edit** — delete module-top L67 (`import nidaqmx`) and L68 (`from nidaqmx.constants import LineGrouping`); add both as the first statements inside the identified method (before the `with nidaqmx.Task()` block).

- [ ] **Step 3: Move the test entry** — in `test_hardware_import_sweep.py`, move `"robot.pal_driver"` from `SLICE2_MODULES` to `SLICE1_MODULES`.

- [ ] **Step 4: Run** — `conda run -n helao python -m pytest helao/hexagon/tests/test_hardware_import_sweep.py -q -k "pal or slice"`. Expect `robot.pal_driver` import test PASS (it imports today since nidaqmx is installed; the edit makes it hermetic).

- [ ] **Step 5: black + commit**

```bash
conda run -n helao black helao/deploy/hte/drivers/robot/pal_driver.py helao/hexagon/tests/test_hardware_import_sweep.py
git add helao/deploy/hte/drivers/robot/pal_driver.py helao/hexagon/tests/test_hardware_import_sweep.py
git commit -m "refactor(hte): P3a-2 lazy nidaqmx import in pal trigger method (§11.1)"
```

---

### Task 2: nidaqmx — module-level `_load_nidaqmx()` globals loader

**Files:** Modify `helao/deploy/hte/drivers/io/nidaqmx_driver.py`; edit the sweep test (move `io.nidaqmx_driver` SLICE2→SLICE1).

- [ ] **Step 1: Verify no module/class/default-arg use** — confirm every `nidaqmx`/constant reference is inside a method body:

Run: `conda run -n helao python -c "import ast,sys; t=ast.parse(open('helao/deploy/hte/drivers/io/nidaqmx_driver.py').read()); names={'nidaqmx','LineGrouping','Edge','AcquisitionType','TerminalConfiguration','VoltageUnits','TemperatureUnits','ThermocoupleType','CurrentShuntResistorLocation','UnitsPreScaled','TriggerType'}; import_lines={n.lineno for node in ast.walk(t) if isinstance(node,(ast.Import,ast.ImportFrom)) for n in [node]};\nbad=[]\nfor node in ast.walk(t):\n  if isinstance(node,ast.Name) and node.id in names:\n    bad.append(node.lineno)\nprint('name-ref lines:', sorted(set(bad)))"`
Then eyeball: every listed line must be inside a `def` (not a class-body annotation / default arg / module statement). If any is at class/module scope, STOP and record it.

- [ ] **Step 2: Add the loader + remove module-top imports.** Delete module-top L27-37. Add near the top of the module (after the existing imports, before the class):

```python
# NI-DAQmx is a Windows-only runtime; import it lazily so the module imports on
# a vendor-less Linux box (§11.1). connect() calls this before any device use.
def _load_nidaqmx():
    global nidaqmx, LineGrouping, Edge, AcquisitionType, TerminalConfiguration
    global VoltageUnits, TemperatureUnits, ThermocoupleType
    global CurrentShuntResistorLocation, UnitsPreScaled, TriggerType
    import nidaqmx as _nidaqmx
    from nidaqmx.constants import (
        LineGrouping,
        Edge,
        AcquisitionType,
        TerminalConfiguration,
        VoltageUnits,
        TemperatureUnits,
        ThermocoupleType,
        CurrentShuntResistorLocation,
        UnitsPreScaled,
        TriggerType,
    )
    nidaqmx = _nidaqmx
```

- [ ] **Step 3: Call it in `connect()`** — add `_load_nidaqmx()` as the first statement of the driver's `def connect`. Also add it to the top of any method that references a vendor symbol AND can be called without a prior `connect()` in the same process — but for nidaqmx the DO/DI methods (`set_digital_out`/`get_digital_in`, L651/L691) are called after connect in the lifecycle, so a single `connect()` call suffices. If Step 1 flagged a method reachable pre-connect, add `_load_nidaqmx()` there too (idempotent).

- [ ] **Step 4: Move test entry** SLICE2→SLICE1 for `io.nidaqmx_driver`.

- [ ] **Step 5: Run** — `-k "nidaqmx or slice"` → PASS. Also import the module fresh to be sure the loader definition is valid: `conda run -n helao python -c "import helao.deploy.hte.drivers.io.nidaqmx_driver as m; m._load_nidaqmx; print('module ok, loader present')"`.

- [ ] **Step 6: black + commit**

```bash
conda run -n helao black helao/deploy/hte/drivers/io/nidaqmx_driver.py helao/hexagon/tests/test_hardware_import_sweep.py
git add helao/deploy/hte/drivers/io/nidaqmx_driver.py helao/hexagon/tests/test_hardware_import_sweep.py
git commit -m "refactor(hte): P3a-2 lazy NI-DAQmx via _load_nidaqmx() globals loader (§11.1)"
```

---

### Task 3: andor — `__future__` annotations + `_load_andor()` globals loader

**Files:** Modify `helao/deploy/hte/drivers/spec/andor/driver.py`; edit the sweep test (move `spec.andor.driver` SLICE2→SLICE1).

- [ ] **Step 1: Add `from __future__ import annotations`** as the FIRST line of the module (before the docstring is not valid — put it immediately after the module docstring, which is where `from __future__` must go: right after the docstring, before any other statement). Verify placement: `from __future__` imports must precede all other code except the docstring.

- [ ] **Step 2: Verify symbol sites** — `grep -nE "AndorSDK3|CameraException|ATSpectrograph" helao/deploy/hte/drivers/spec/andor/driver.py`. Confirm: class annotation L47 (`cam: AndorSDK3`) now stringized by the future import; real uses in `__init__` (L77) + spectrograph methods (L334/L435/L348/L448) + `except CameraException` (L790). No default-arg use.

- [ ] **Step 3: Add loader + remove module-top imports.** Delete module-top L8 + L13. Add after the imports/before the class:

```python
def _load_andor():
    global AndorSDK3, CameraException, ATSpectrograph
    from pyAndorSDK3 import AndorSDK3, CameraException
    from pyAndorSpectrograph.spectrograph import ATSpectrograph
```

- [ ] **Step 4: Call it where devices are first touched.** Add `_load_andor()` as the first statement of `__init__` (before `self.sdk3 = AndorSDK3()` at L77) AND at the top of any spectrograph method that constructs `ATSpectrograph()` without going through `__init__`/`connect()` first (L334/L435 methods). Adding it in `__init__` covers construction; add it to the spectrograph setup method(s) too for safety (idempotent). Do NOT change the `AndorSDK3()` construction location (constructor-connect deferred).

- [ ] **Step 5: Move test entry** SLICE2→SLICE1 for `spec.andor.driver`.

- [ ] **Step 6: Run** — `-k "andor or slice"`. `spec.andor.driver` import test now PASSES (imports without the Andor SDKs present — a genuine hermetic win, unlike nidaqmx/pal which were installed). Confirm: `conda run -n helao python -c "import helao.deploy.hte.drivers.spec.andor.driver as m; print('andor imports on linux, loader:', bool(m._load_andor))"`.

- [ ] **Step 7: black + commit**

```bash
conda run -n helao black helao/deploy/hte/drivers/spec/andor/driver.py helao/hexagon/tests/test_hardware_import_sweep.py
git add helao/deploy/hte/drivers/spec/andor/driver.py helao/hexagon/tests/test_hardware_import_sweep.py
git commit -m "refactor(hte): P3a-2 lazy Andor SDK via _load_andor() + __future__ annotations (§11.1)"
```

---

### Task 4: Full sweep green + regression + biologic-only xfail

- [ ] **Step 1: Confirm the sweep lists** — `SLICE1_MODULES` now contains gamry, spectral_products, galil_io, galil_motion, cm0134, sprintir, mecom, synaccess, kinesis, simdos, **pal, nidaqmx, andor**; `SLICE2_MODULES` = `["pstat.biologic.driver"]` only. Update the xfail reason on the biologic parametrization to point at the technique-registry restructure.

- [ ] **Step 2: Full sweep** — `conda run -n helao python -m pytest helao/hexagon/tests/test_hardware_import_sweep.py -q`. Expect: all SLICE1 import tests PASS; biologic `xfail`; kinesis-construct `xfail` (from P3a-1); 0 unexpected failures.

- [ ] **Step 3: Hexagon suite regression** — `conda run -n helao python -m pytest helao/hexagon/tests/ -q 2>&1 | tail -3`. Expect no new failures (332+ passed).

- [ ] **Step 4: Behavior-preservation static check** — every edited driver has its loader/local import present and no residual module-top vendor import:

Run: `grep -nE "^import nidaqmx|^from nidaqmx|^from pyAndor" helao/deploy/hte/drivers/io/nidaqmx_driver.py helao/deploy/hte/drivers/robot/pal_driver.py helao/deploy/hte/drivers/spec/andor/driver.py`
Expected: NO matches at column 0 (all vendor imports now inside loaders/methods).

- [ ] **Step 5: Commit any test-list/xfail-reason tidy**

```bash
conda run -n helao black helao/hexagon/tests/test_hardware_import_sweep.py
git add helao/hexagon/tests/test_hardware_import_sweep.py
git commit -m "test(hexagon): P3a-2 sweep — only biologic remains xfail (technique registry restructure pending)"
```

## Self-Review

**Spec coverage (§11.1):** nidaqmx/pal/andor now import hermetically → Tasks 1-3; sweep gate updated → Task 4. biologic explicitly deferred with reason. Constructor-connect deferred to native splits. ✔

**Placeholder scan:** none; exact line numbers + loader code given; each task verify-gates symbol scope before editing.

**Type consistency:** `_load_nidaqmx`/`_load_andor` defined and called within their own modules; sweep-test `SLICE1_MODULES`/`SLICE2_MODULES` are the P3a-1 lists, edited additively.

**Risk controls:** the `global`-loader pattern is gated on "no module/class/default-arg vendor use" (Step 1 of Tasks 2/3); andor future-annotations placement verified; construction-time behavior unchanged (loader called before first use on every live path; deferred constructor-connect untouched).

## Execution Handoff

Recommended: **Subagent-Driven** — fresh subagent per task, review between (live-station driver edits).
