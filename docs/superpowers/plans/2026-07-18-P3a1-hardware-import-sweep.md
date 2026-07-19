# P3a-1 — hte Hardware-adapter import sweep + generic bindings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the mechanically-safe hte driver modules import on a vendor-less Linux box (spec §11.1) and bind them to the hexagon `HardwarePort` via the existing generic `LegacyDriverHardwareAdapter`, gated by a new hermetic import-sweep test — the foundation of the P3a native Hardware-adapter track (which gates P4/P5).

**Architecture:** The lazy-import pattern is **per-method local import**: each method that references a vendor symbol gets `import <vendor>` as its first statement; the module-top import is deleted. This makes the module import without the vendor package present while leaving **Windows runtime behavior unchanged** (each method imports the same symbol before first use). The generic `LegacyDriverHardwareAdapter` (`helao/hexagon/adapters/legacy/hardware.py`) already covers the real driver surface — no adapter/port code change. One logic fix: `KinesisMotor.__init__` must stop calling `self.connect()` (disconnected-construct, §10.4).

**Tech Stack:** Python 3.12 (`conda run -n helao`), pytest under `helao/hexagon/tests/`, `black` line-length 88.

## Why per-method local import (NOT the two tempting shortcuts — both are WRONG here)

Verified against the actual source (2026-07-18):
- **"Move the import into `connect()`" is WRONG** for every file except galil_io: the vendor symbols are used across multiple methods (gamry: `connect`/`setup`/`measure`/`get_data`/`setup_eis`; galil_motion: `connect`/`run_aligner_precheck`/`shutdown`; cm0134: `connect`/`read_o2_ppm`). A single connect()-local import leaves the other methods with an unbound name at runtime.
- **A module-level `__getattr__` lazy proxy (PEP 562) is WRONG here** too: it fires only for `module.attr` access from an importer, NOT for bare-name global lookups inside a function body. `gclib.py()` inside a method resolves `gclib` via the module globals dict then builtins and raises `NameError` if absent — it never invokes the module `__getattr__`. So a proxy would not rescue in-method references.
- **Per-method local import** is the one correct, uniform, obviously-behavior-preserving pattern for symbols referenced in method bodies. It is verbose but each edit is trivial and local.

## Global Constraints

- **conda run -n helao** for every python/pytest (OS python is 3.14 — wrong).
- **black** (line length 88) on changed `.py` files immediately before every commit.
- **Behavior-preservation is a hard gate.** For each file, the set of methods getting a local import MUST equal the set of methods that reference the vendor symbol (verified by grep in each task's Step 1). Miss one → runtime `NameError` on a live station. Docstring/comment mentions do NOT count (verify the hit is real code, not a `"""docstring"""` or `#comment`).
- **These are live-station instrument drivers** (parent repo, tracked). Edits are import-relocation only, plus the one sanctioned `KinesisMotor.__init__` fix. No functional/algorithmic changes.
- **Legacy rollback preserved:** relocating imports into methods leaves the `deployment:`-flip rollback intact (legacy server runs identically on Windows).
- Branch: `feat/p3a1-hardware-import-sweep` off `unstable`. Do NOT push. Do NOT create PRs.

## Scope (verified per-file, risk-tiered)

**Slice-1 (THIS plan)** — files whose vendor symbols appear only in method bodies (no class-scope annotation eval, no `__init__` instantiation):
- `galil_io` — `gclib` in `connect` only (1 method).
- `cm0134` — `minimalmodbus` in `connect`, `read_o2_ppm` (2 methods).
- `galil_motion` — `gclib` in `connect`, `run_aligner_precheck`, `shutdown` (3 methods).
- `gamry` — `comtypes`/`comtypes.client as client` in `connect`, `setup`, `measure`, `get_data`, `setup_eis`; + `readz.py` in `init_pstat`, `get_data`.
- `KinesisMotor.__init__` constructor-connect fix.

**Slice-2 (DEFERRED — plan `P3a-2`)** — files needing more than import relocation:
- `spec/andor/driver.py` — `AndorSDK3()` instantiated in `__init__` (constructor-connect, §10.4 violation) + class-level annotation `cam: AndorSDK3` evaluated at import (no `from __future__ import annotations`) + used in `adjust_ND`/`get_data`/`setup_spectroscope`. Needs: add `from __future__ import annotations`, defer the `AndorSDK3()` construction out of `__init__`, then per-method imports.
- `pstat/biologic/driver.py` (+ `technique.py`) — `easy_biologic` (raises Windows-only `OSError` at its own import) used in technique bodies.
- `io/nidaqmx_driver.py` — 11 `nidaqmx.constants` symbols referenced throughout; needs per-method imports at ~a dozen sites (verify count).
- `robot/pal_driver.py` — `nidaqmx` used only around the trigger block (~L546); likely 1-2 methods — re-verify; may graduate to a fast follow.

## Verified inputs (2026-07-18, live grep)

Current Linux import state: **OK** = spectral_products(SM303), sprintir, mecom, synaccess, kinesis, simdos. **FAIL** = gamry(comtypes), andor(pyAndorSDK3), galil_io(gclib), galil_motion(gclib), cm0134(minimalmodbus). (biologic/nidaqmx/pal are slice-2.)

Per-file vendor-symbol method sites (real code, comments excluded):
- `pstat/gamry/driver.py`: module-top L20 `import comtypes`, L21 `import comtypes.client as client`. Real uses: `connect` (client.GetModule/CreateObject), `setup` (client.CreateObject ×2, `except comtypes.COMError`), `measure` (client.GetEvents, `except comtypes.COMError`), `get_data` (client.PumpEvents), `setup_eis` (client.CreateObject).
- `pstat/gamry/readz.py`: module-top L15 `import comtypes.client as client`. Real uses: `init_pstat` (client.GetEvents), `get_data` (client.PumpEvents).
- `io/galil_io_driver.py`: module-top L53 `import gclib`. Real use: `connect` (`self.g = gclib.py()`, `self.g.GVersion()`).
- `motion/galil_motion_driver.py`: module-top L61 `import gclib`. Real uses: `connect` (`gclib.py()`), `run_aligner_precheck` (`except gclib.GclibError`), `shutdown` (verify exact gclib ref).
- `sensor/cm0134_driver.py`: module-top L14 `import minimalmodbus`. Real uses: `connect` (`minimalmodbus.Instrument`), `read_o2_ppm` (`except minimalmodbus.NoResponseError`).
- `motion/kinesis_driver.py`: `__init__` last line `self.connect()` to remove.

The sweep test module set (14): `pstat.gamry.driver` · `pstat.biologic.driver` · `spec.spectral_products_driver` · `spec.andor.driver` · `io.galil_io_driver` · `motion.galil_motion_driver` · `io.nidaqmx_driver` · `robot.pal_driver` · `sensor.cm0134_driver` · `sensor.sprintir_driver` · `temperature_control.mecom_driver` · `io.synaccess.driver` · `motion.kinesis_driver` · `pump.simdos_driver` (under `helao.deploy.hte.drivers.`).

---

### Task 1: Import-sweep test (RED-first)

**Files:** Create `helao/hexagon/tests/test_hardware_import_sweep.py`

- [ ] **Step 1: Write the test** — slice-1 modules asserted to import; slice-2 modules `xfail`:

```python
import importlib
import pytest
from helao.hexagon.adapters.legacy.hardware import LegacyDriverHardwareAdapter
from helao.hexagon.ports.hardware import HardwarePort

BASE = "helao.deploy.hte.drivers."

SLICE1_MODULES = [
    "pstat.gamry.driver",
    "spec.spectral_products_driver",   # already lazy
    "io.galil_io_driver",
    "motion.galil_motion_driver",
    "sensor.cm0134_driver",
    "sensor.sprintir_driver",          # already imports (serial only)
    "temperature_control.mecom_driver",
    "io.synaccess.driver",
    "motion.kinesis_driver",
    "pump.simdos_driver",
]
SLICE2_MODULES = [
    "spec.andor.driver",
    "pstat.biologic.driver",
    "io.nidaqmx_driver",
    "robot.pal_driver",
]


@pytest.mark.parametrize("mod", SLICE1_MODULES)
def test_slice1_driver_imports_on_linux(mod):
    importlib.import_module(BASE + mod)


@pytest.mark.parametrize("mod", SLICE2_MODULES)
@pytest.mark.xfail(reason="P3a-2: deeper lazy-import/constructor refactor pending", strict=False)
def test_slice2_driver_imports_on_linux(mod):
    importlib.import_module(BASE + mod)
```

- [ ] **Step 2: Run — RED baseline**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_hardware_import_sweep.py -q`
Expected: slice-1 FAILs for gamry, galil_io, galil_motion, cm0134 (missing vendor libs); PASSes for spectral_products, sprintir, mecom, synaccess, kinesis, simdos; slice-2 all `xfail`.

- [ ] **Step 3: Commit**

```bash
conda run -n helao black helao/hexagon/tests/test_hardware_import_sweep.py
git add helao/hexagon/tests/test_hardware_import_sweep.py
git commit -m "test(hexagon): P3a-1 hte driver import-sweep (RED; andor/biologic/nidaqmx/pal xfail)"
```

---

### Task 2: galil_io — `gclib` local import in `connect` (single method)

**Files:** Modify `helao/deploy/hte/drivers/io/galil_io_driver.py`

- [ ] **Step 1: Confirm single-method use** (real code only):

Run: `conda run -n helao python -c "import re; ls=open('helao/deploy/hte/drivers/io/galil_io_driver.py').read().splitlines(); cur=None; [print(i+1,cur,l.strip()[:70]) for i,l in enumerate(ls) if (m:=re.match(r'\s*def (\w+)',l)) and (globals().__setitem__('cur',m.group(1)) or True)] " 2>/dev/null; grep -nE "gclib\.(py|[A-Z])" helao/deploy/hte/drivers/io/galil_io_driver.py`
Expected: the only real `gclib.` code references are in `connect`.

- [ ] **Step 2: Edit** — delete module-top `import gclib` (L53); add `import gclib` as the first statement inside `def connect`.

- [ ] **Step 3: Run sweep** — `conda run -n helao python -m pytest helao/hexagon/tests/test_hardware_import_sweep.py -q -k galil_io` → PASS.

- [ ] **Step 4: Commit**

```bash
conda run -n helao black helao/deploy/hte/drivers/io/galil_io_driver.py
git add helao/deploy/hte/drivers/io/galil_io_driver.py
git commit -m "refactor(hte): P3a-1 lazy gclib import in galil_io connect (§11.1)"
```

---

### Task 3: cm0134 — `minimalmodbus` local import in `connect` + `read_o2_ppm`

**Files:** Modify `helao/deploy/hte/drivers/sensor/cm0134_driver.py`

- [ ] **Step 1: Confirm the two methods** — `grep -nE "minimalmodbus" helao/deploy/hte/drivers/sensor/cm0134_driver.py` → real uses in `connect` (L70) and `read_o2_ppm` (L136). No others.

- [ ] **Step 2: Edit** — delete module-top `import minimalmodbus` (L14); add `import minimalmodbus` as the first statement of BOTH `def connect` and `def read_o2_ppm`.

- [ ] **Step 3: Run sweep** — `-k cm0134` → PASS.

- [ ] **Step 4: Commit**

```bash
conda run -n helao black helao/deploy/hte/drivers/sensor/cm0134_driver.py
git add helao/deploy/hte/drivers/sensor/cm0134_driver.py
git commit -m "refactor(hte): P3a-1 lazy minimalmodbus import in cm0134 connect+read_o2_ppm (§11.1)"
```

---

### Task 4: galil_motion — `gclib` local import in `connect` + `run_aligner_precheck` + `shutdown`

**Files:** Modify `helao/deploy/hte/drivers/motion/galil_motion_driver.py`

- [ ] **Step 1: Confirm exact methods** referencing `gclib` as real code:

Run: `grep -nE "gclib\.(py|Gclib|[A-Z])" helao/deploy/hte/drivers/motion/galil_motion_driver.py`
Expected: `connect` (`gclib.py()`), `run_aligner_precheck` (`except gclib.GclibError`), and confirm the `shutdown` reference is real code (not a docstring). Record the FINAL method set — every one gets a local import.

- [ ] **Step 2: Edit** — delete module-top `import gclib` (L61); add `import gclib` as the first statement of each method in the confirmed set (`connect`, `run_aligner_precheck`, `shutdown` if real).

- [ ] **Step 3: Run sweep** — `-k galil_motion` → PASS.

- [ ] **Step 4: Commit**

```bash
conda run -n helao black helao/deploy/hte/drivers/motion/galil_motion_driver.py
git add helao/deploy/hte/drivers/motion/galil_motion_driver.py
git commit -m "refactor(hte): P3a-1 lazy gclib import in galil_motion (connect/aligner/shutdown) (§11.1)"
```

---

### Task 5: gamry driver + readz — `comtypes`/`client` local imports across their real-use methods

**Files:** Modify `helao/deploy/hte/drivers/pstat/gamry/driver.py`, `helao/deploy/hte/drivers/pstat/gamry/readz.py`

- [ ] **Step 1: Confirm exact method sets** (real code):

Run: `grep -nE "comtypes|client\." helao/deploy/hte/drivers/pstat/gamry/driver.py; echo ---; grep -nE "comtypes|client\." helao/deploy/hte/drivers/pstat/gamry/readz.py`
Expected driver methods: `connect`, `setup`, `measure`, `get_data`, `setup_eis`. `except comtypes.COMError` appears in `setup`, `measure` — those methods need `import comtypes` too (not just `client`). readz methods: `init_pstat`, `get_data`. Record which methods need `client`, which also need `comtypes`.

- [ ] **Step 2: Edit driver.py** — delete module-top L20-21. In each method that uses `client`, add `import comtypes.client as client` as its first statement; in each method that also references `comtypes.COMError`, add `import comtypes` too (before the `try`). Methods: `connect` (`client`), `setup` (`client`+`comtypes`), `measure` (`client`+`comtypes`), `get_data` (`client`), `setup_eis` (`client`).

- [ ] **Step 3: Edit readz.py** — delete module-top L15; add `import comtypes.client as client` as the first statement of `init_pstat` and `get_data`.

- [ ] **Step 4: Run sweep** — `-k gamry` → PASS.

- [ ] **Step 5: Commit**

```bash
conda run -n helao black helao/deploy/hte/drivers/pstat/gamry/driver.py helao/deploy/hte/drivers/pstat/gamry/readz.py
git add helao/deploy/hte/drivers/pstat/gamry/driver.py helao/deploy/hte/drivers/pstat/gamry/readz.py
git commit -m "refactor(hte): P3a-1 lazy comtypes imports in gamry driver+readz (per-method, §11.1)"
```

---

### Task 6: `KinesisMotor.__init__` disconnected-construct fix (§10.4)

**Files:** Modify `helao/deploy/hte/drivers/motion/kinesis_driver.py`; extend `test_hardware_import_sweep.py`

- [ ] **Step 1: Write the failing test** — append:

```python
def test_kinesis_constructs_without_connecting(monkeypatch):
    """§10.4: KinesisMotor(config) must not open devices in __init__."""
    import pylablib.devices.Thorlabs as Thorlabs
    from helao.deploy.hte.drivers.motion import kinesis_driver

    calls = []
    monkeypatch.setattr(
        Thorlabs, "KinesisMotor",
        lambda *a, **k: calls.append((a, k)) or object(),
    )
    drv = kinesis_driver.KinesisMotor(config={"axes": {"x": {"serial": "0", "scale": 1}}})
    assert calls == [], "KinesisMotor.__init__ must not connect to hardware"
    assert isinstance(LegacyDriverHardwareAdapter(drv), HardwarePort)
```

- [ ] **Step 2: Run — expect FAIL** (`-k kinesis_constructs`): `calls` non-empty or connect error.

- [ ] **Step 3: Verify the server connects explicitly, then remove the `__init__` call.** Confirm the action server drives connection so removing `__init__`'s connect doesn't strand the driver:

Run: `grep -nE "\.connect\(|KinesisMotor\(|poller|setup_and_contain" helao/deploy/hte/servers/action/kinesis_server.py | head`
- If the server/poller calls `driver.connect()` (or the poller opens it), remove ONLY the `self.connect()` line at the end of `__init__` (keep all attribute setup).
- If NOTHING external calls `connect()` and the driver relied on `__init__`-time connect, DO NOT silently drop it — keep this task RED and record the finding (the connect must be relocated to the server startup, which is a documented deviation escalated for review, not done silently).

- [ ] **Step 4: Run — GREEN** (`-k kinesis`): both kinesis tests pass.

- [ ] **Step 5: Commit**

```bash
conda run -n helao black helao/deploy/hte/drivers/motion/kinesis_driver.py helao/hexagon/tests/test_hardware_import_sweep.py
git add helao/deploy/hte/drivers/motion/kinesis_driver.py helao/hexagon/tests/test_hardware_import_sweep.py
git commit -m "refactor(hte): P3a-1 KinesisMotor disconnected-construct — drop __init__ self.connect() (§10.4)"
```

---

### Task 7: Full sweep green + regression + adapter-conformance

**Files:** extend `test_hardware_import_sweep.py`

- [ ] **Step 1: Add an adapter-conformance assertion** for the slice-1 drivers that construct disconnected (append):

```python
DISCONNECTED_CONSTRUCT = [
    ("io.galil_io_driver", "Galil"),
    ("motion.galil_motion_driver", "Galil"),
    ("sensor.cm0134_driver", "CM0134"),
    ("sensor.sprintir_driver", "SprintIR"),
    ("temperature_control.mecom_driver", "MeerstetterTEC"),
    ("io.synaccess.driver", "NetbooterDriver"),
    ("pump.simdos_driver", "SIMDOS"),
    ("pstat.gamry.driver", "GamryDriver"),
]


@pytest.mark.parametrize("mod,cls", DISCONNECTED_CONSTRUCT)
def test_adapter_is_hardware_port(mod, cls):
    klass = getattr(importlib.import_module(BASE + mod), cls)
    drv = klass(config={})
    assert isinstance(LegacyDriverHardwareAdapter(drv), HardwarePort)
```

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_hardware_import_sweep.py -q -k adapter_is_hardware_port`
Expected: PASS. If any driver's `__init__` does I/O with `config={}` (raises), REMOVE it from this list and record it as a slice-2 constructor-connect item (do not weaken the assertion).

- [ ] **Step 2: Full sweep** — `conda run -n helao python -m pytest helao/hexagon/tests/test_hardware_import_sweep.py -q` → all slice-1 + adapter + kinesis pass; slice-2 xfail; 0 unexpected.

- [ ] **Step 3: Hexagon suite regression** — `conda run -n helao python -m pytest helao/hexagon/tests/ -q 2>&1 | tail -5` → no new failures.

- [ ] **Step 4: Behavior-preservation static check** — every edited method that lost the module-top import now has a local import before first vendor use:

Run: `grep -nE "import (comtypes|gclib|minimalmodbus)" helao/deploy/hte/drivers/io/galil_io_driver.py helao/deploy/hte/drivers/motion/galil_motion_driver.py helao/deploy/hte/drivers/sensor/cm0134_driver.py helao/deploy/hte/drivers/pstat/gamry/driver.py helao/deploy/hte/drivers/pstat/gamry/readz.py`
Expected: each import appears inside methods (indented), none at column 0. Cross-check the method set matches Step-1 findings of Tasks 2-5.

---

## Self-Review

**Spec coverage:** §11.1 lazy vendor imports → Tasks 2-5 (per-method) + slice-2 deferral (andor/biologic/nidaqmx/pal). Import-sweep CI test → Tasks 1, 7. §10.4 disconnected-construct → Task 6 + Task 7 Step 1. Generic `HardwarePort` binding → Task 7 (no adapter/port change). ✔

**Placeholder scan:** none; every edit names exact methods, each preceded by a grep confirming the real-code method set.

**Type consistency:** `SLICE1_MODULES`/`SLICE2_MODULES`/`DISCONNECTED_CONSTRUCT` defined in the test module; `LegacyDriverHardwareAdapter`/`HardwarePort` imported once.

**Risk controls:** per-method import set is grep-verified per file (miss = station `NameError`, called out explicitly); the two wrong shortcuts (connect-only move, `__getattr__` proxy) are documented as forbidden with reasons; andor/biologic/nidaqmx/pal deferred rather than force-fit; Task 6 has an explicit escalation branch if the kinesis server relied on `__init__`-time connect.

**Deferred-by-design:** andor (`__future__` annotations + constructor-connect), biologic, nidaqmx, pal (slice-2 `P3a-2`); all hardware runtime exercise (station gate); the 4 special-case splits (PAL 4-way, galil 3-way+aligner, Gamry COM STA-thread, Archive→SampleState — separate P3a sub-plans).

## Execution Handoff

Plan saved. Recommended: **Subagent-Driven** — fresh subagent per task, review between (these edit live-station driver code; between-task review is the behavior-preservation checkpoint). Each task is grep-verify → edit → sweep-green → commit.
