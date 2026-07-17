# P1a: hexagon domain + ports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pure domain layer and port Protocols of the HELAO-async hexagonal rewrite (`helao/hexagon/`), enforced by an AST boundary test from the first commit, with full unit-test coverage — no adapters, no app/composition, no dispatch loop, no legacy edits.

**Architecture:** P1a is the first slice of master-spec phase P1 (`docs/superpowers/specs/2026-07-16-framework-hexagonal-rewrite-design.md`, §12 P1). It creates `helao/hexagon/{domain,ports,tests}`: the domain reuses the existing post-CARDS pydantic run models (D8) and ports the already-pure `DispatchPolicy`/fold functions into a reducer FSM `step(state, event) -> (state, commands)`; ports are `typing.Protocol` definitions of every outbound/inbound seam from spec §4.3. Everything here is pure and unit-testable with in-memory fakes. Adapters, app factory, the single-drainer dispatch loop, and the GM-1..5 parity gate are P1b.

**Tech Stack:** Python 3.12 (conda env `helao`), pydantic v2, pytest (hexagon tree only), pyright (authoritative), black 88.

## Global Constraints

Copied verbatim from the master spec + project rules. Every task's requirements implicitly include this section.

- **Environment:** all commands run inside the `helao` conda env (`conda run -n helao …`), Python 3.12, `PYTHONPATH` at repo root. Never use the OS python.
- **Formatting:** run `black <changed_files>` (default settings, line length 88) as the final step before **every** commit.
- **Type checking:** `pyright` (`pyrightconfig.json`, basic mode) is the authoritative type checker; 0 errors on `helao/hexagon/` is a gate. Do not remove `# type: ignore` directives pyright needs.
- **Package name:** `helao/hexagon/` (locked, Q1 resolved). NOT `helao/framework/` — that is the abandoned tree.
- **Boundary rule (spec §4.1):** `domain/` imports ONLY: stdlib (minus an I/O/concurrency denylist), `pydantic`, `numpy`, `helao.core.models.*`, `helao.helpers.premodels`, `helao.core.helaodict`, `helao.core.error` (declared extension — pure `ErrorCodes` StrEnum needed by dispatch results), and `helao.hexagon.domain.*`. In particular NO `fastapi`, `aiohttp`, `httpx`, `zmq`, `bokeh`, `boto3`, `aiofiles`, `asyncio`, vendor libs, and NO `helao.hexagon.adapters`/`helao.hexagon.app`. `ports/` imports ONLY: stdlib(+typing), `helao.hexagon.domain.*`, `helao.hexagon.ports.*`, and `helao.core.drivers.helao_driver` (declared extension — the `DriverResponse`/`DriverStatus`/`DriverResponseType` value objects the Hardware port keeps verbatim, spec §4.3.1). Allow-list extensions are explicit, never a loosening of the walk.
- **D7:** `action_params` (and the whole `*_params` / `to_global_params` / `from_global_*_params` relay) stays untyped/bit-exact. Do not type it.
- **D8:** the domain REUSES the existing post-CARDS pydantic run models; NO new domain type system. Artifact-content assembly = model → `clean_dict()`.
- **No legacy edits:** nothing outside `helao/hexagon/` and this plan's doc file is created or modified. Legacy `helao/core` + `helao/helpers` remain untouched.
- **No adapters/app/loop/servers in P1a:** `adapters/__init__.py` and `app/__init__.py` exist only as empty packages so the boundary test can police them; they contain no logic. No server is ever launched by this plan.
- **Rewrite-with-reference (Q6):** the reducer FSM and boundary test are written fresh against the post-CARDS shapes in `helao/core/servers/orch_dispatch.py` etc.; nothing is cherry-picked from `feat/framework-scaffold`.
- **Branch:** work on a feature branch off `unstable` (suggested: `feat/hexagon-p1a`). Do not push without explicit authorization.
- **Privacy:** no private-deployment names anywhere (public repo). Use Deployment-A/B/C if a deployment must be referenced.
- **Tests:** pytest is introduced for the hexagon tree ONLY (`helao/hexagon/tests/`); the legacy no-pytest convention elsewhere is unchanged. Run with `conda run -n helao python -m pytest helao/hexagon/tests -q`.

**P1a gate (end of plan):** AST boundary test green; all port Protocols import cleanly on Linux; domain unit tests green (FSM transitions T1–T13, ladder precedence, naming, estop policy, folds, status fold); pyright 0 errors on `helao/hexagon/`; black clean. **Explicitly NOT in P1a:** the GM-1..5 golden parity gate and the §10.3 concurrency suite — both require adapters + real transport and belong to P1b.

## File Structure

```
helao/hexagon/
├── __init__.py                      # package marker + docstring
├── domain/
│   ├── __init__.py
│   ├── models.py                    # D8 re-export surface (the ONLY model import point for ports)
│   ├── naming.py                    # filename/dir grammar, file-conn keys, manual-dir redirect
│   ├── assembly.py                  # model → clean_dict artifact-content assembly
│   ├── dispatch_policy.py           # ported pure DispatchPolicy + snapshots + steps + guards
│   ├── global_params.py             # ported apply_from_globals / collect_to_globals
│   ├── status_fold.py               # status ingestion fold + §4.2.4 side-effect command set
│   ├── orchestration.py             # reducer FSM: step(state, event) -> (state, commands)
│   ├── queue_policy.py              # queue CRUD / run-id / process-grouping / plan-merge pure fns
│   └── estop_policy.py              # EstopPolicy + declarative stop topology (Q7)
├── ports/
│   ├── __init__.py
│   ├── hardware.py                  # HardwarePort + DriverResponse→ErrorCodes mapping
│   ├── data_sink.py                 # DataSinkPort (thread-safety contract)
│   ├── artifact_store.py            # ArtifactStorePort (timing semantics in docstrings)
│   ├── sync.py                      # SyncPort + S3FacePort
│   ├── transport.py                 # TransportPort (action + private dispatch)
│   ├── status.py                    # StatusPort (push + WS pub, dual stack)
│   ├── clock.py                     # ClockPort
│   ├── logging.py                   # LoggingPort (fail-loud)
│   ├── config.py                    # ConfigPort (raw-dict identity)
│   ├── analysis.py                  # AnalysisArtifactPort
│   ├── sample_state.py              # SampleStatePort (SampleArchiveShim conventions)
│   └── auxiliary.py                 # StatePersistence/PlateInfo/Library/Health/Notify
├── adapters/
│   └── __init__.py                  # EMPTY (P1b)
├── app/
│   └── __init__.py                  # EMPTY (P1b)
└── tests/
    ├── __init__.py
    ├── test_boundaries.py           # the AST walk (from commit 1)
    ├── fakes.py                     # in-memory port fakes (test-only)
    ├── test_ports_import.py
    ├── test_naming.py
    ├── test_assembly.py
    ├── test_dispatch_policy.py
    ├── test_global_params.py
    ├── test_status_fold.py
    ├── test_orchestration.py
    ├── test_queue_policy.py
    ├── test_estop_policy.py
    └── test_fakes.py
```

---

### Task 1: Package scaffold + AST boundary test

**Files:**
- Create: `helao/hexagon/__init__.py`
- Create: `helao/hexagon/domain/__init__.py`
- Create: `helao/hexagon/ports/__init__.py`
- Create: `helao/hexagon/adapters/__init__.py`
- Create: `helao/hexagon/app/__init__.py`
- Create: `helao/hexagon/tests/__init__.py`
- Test: `helao/hexagon/tests/test_boundaries.py`

**Interfaces:**
- Produces: `helao.hexagon.tests.test_boundaries.iter_violations(pyfile: Path) -> List[Tuple[int, str, str]]` — the reusable checker later tasks keep green. Layer rules constants: `DOMAIN_ALLOW_PREFIXES`, `PORTS_ALLOW_PREFIXES`, `STDLIB_DENY`, `VENDOR_BANNED`.

- [ ] **Step 1: Verify pytest availability in the helao env**

Run: `conda run -n helao python -c "import pytest; print(pytest.__version__)"`
Expected: a version string. If `ModuleNotFoundError`: run `conda run -n helao python -m pip install pytest` and re-check.

- [ ] **Step 2: Write the failing boundary test**

Create `helao/hexagon/tests/test_boundaries.py`:

```python
"""AST boundary test for helao/hexagon (master spec §4.1).

Walks every .py file under helao/hexagon and fails the suite if a layer
imports outside its allow-list. This test exists from the first commit and
must never be weakened; allow-list changes require a spec amendment.

Layer rules:
- domain/  : stdlib (minus I/O denylist), pydantic, numpy,
             helao.core.models.*, helao.helpers.premodels,
             helao.core.helaodict, helao.core.error, helao.hexagon.domain.*
- ports/   : stdlib (minus I/O denylist), helao.hexagon.domain.*,
             helao.hexagon.ports.*, helao.core.drivers.helao_driver
             (declared exception: DriverResponse value objects, spec §4.3.1)
- adapters/: anything EXCEPT helao.hexagon.app
- app/     : anything
- tests/   : anything (fakes live here in P1a)
"""

import ast
import sys
from pathlib import Path
from typing import List, Tuple

HEXAGON_ROOT = Path(__file__).resolve().parents[1]  # .../helao/hexagon
HEXAGON_PKG = "helao.hexagon"

# stdlib modules that smuggle I/O, event loops, or concurrency into "pure"
# layers.  asyncio is banned in domain/ports on purpose: the domain is sync
# and pure; async signatures in ports need no asyncio import.
STDLIB_DENY = frozenset(
    {
        "asyncio",
        "socket",
        "ssl",
        "selectors",
        "subprocess",
        "http",
        "urllib",
        "ftplib",
        "smtplib",
        "multiprocessing",
        "threading",
        "concurrent",
    }
)

# named explicitly so a violation message is unambiguous (spec §4.1 list)
VENDOR_BANNED = frozenset(
    {
        "fastapi",
        "aiohttp",
        "httpx",
        "zmq",
        "bokeh",
        "boto3",
        "aiofiles",
        "requests",
        "websockets",
        "uvicorn",
        "starlette",
        "pyzstd",
        "psutil",
    }
)

DOMAIN_THIRD_PARTY = frozenset({"pydantic", "numpy"})

DOMAIN_ALLOW_PREFIXES: Tuple[str, ...] = (
    "helao.core.models",
    "helao.helpers.premodels",
    "helao.core.helaodict",
    "helao.core.error",
    "helao.hexagon.domain",
)

PORTS_ALLOW_PREFIXES: Tuple[str, ...] = (
    "helao.hexagon.domain",
    "helao.hexagon.ports",
    "helao.core.drivers.helao_driver",
)

_STDLIB = frozenset(sys.stdlib_module_names)


def _layer_of(pyfile: Path) -> str:
    rel = pyfile.resolve().relative_to(HEXAGON_ROOT)
    return rel.parts[0] if len(rel.parts) > 1 else "root"


def _absolutize(pyfile: Path, node: ast.ImportFrom) -> str:
    """Resolve a relative import to its absolute module path."""
    if node.level == 0:
        return node.module or ""
    rel = pyfile.resolve().relative_to(HEXAGON_ROOT)
    # package parts of the importing module (drop the filename)
    pkg_parts = [HEXAGON_PKG.replace(".", "/")] + list(rel.parts[:-1])
    pkg = ".".join(HEXAGON_PKG.split(".") + list(rel.parts[:-1]))
    parts = pkg.split(".")
    parts = parts[: len(parts) - (node.level - 1)]
    if node.module:
        parts.append(node.module)
    return ".".join(parts)


def _imported_modules(pyfile: Path) -> List[Tuple[int, str]]:
    tree = ast.parse(pyfile.read_text(encoding="utf-8"))
    found: List[Tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            found.append((node.lineno, _absolutize(pyfile, node)))
    return found


def _allowed(module: str, layer: str) -> bool:
    top = module.split(".")[0]
    if layer in ("app", "tests", "root"):
        return True
    if layer == "adapters":
        return not (
            module == f"{HEXAGON_PKG}.app" or module.startswith(f"{HEXAGON_PKG}.app.")
        )
    # domain / ports
    if top in VENDOR_BANNED:
        return False
    if top in _STDLIB:
        return top not in STDLIB_DENY
    prefixes = DOMAIN_ALLOW_PREFIXES if layer == "domain" else PORTS_ALLOW_PREFIXES
    if layer == "domain" and top in DOMAIN_THIRD_PARTY:
        return True
    return any(module == p or module.startswith(p + ".") for p in prefixes)


def iter_violations(pyfile: Path) -> List[Tuple[int, str, str]]:
    """Return (lineno, module, layer) for every disallowed import in pyfile."""
    layer = _layer_of(pyfile)
    return [
        (lineno, module, layer)
        for lineno, module in _imported_modules(pyfile)
        if module and not _allowed(module, layer)
    ]


def _walk_layer(layer: str) -> List[Path]:
    d = HEXAGON_ROOT / layer
    return sorted(d.rglob("*.py")) if d.is_dir() else []


def test_hexagon_packages_exist():
    for layer in ("domain", "ports", "adapters", "app", "tests"):
        assert (HEXAGON_ROOT / layer / "__init__.py").is_file(), layer


def test_domain_imports_only_allowlist():
    bad = [v for f in _walk_layer("domain") for v in iter_violations(f)]
    assert not bad, f"domain boundary violations: {bad}"


def test_ports_import_only_domain_and_stdlib():
    bad = [v for f in _walk_layer("ports") for v in iter_violations(f)]
    assert not bad, f"ports boundary violations: {bad}"


def test_adapters_never_import_app():
    bad = [v for f in _walk_layer("adapters") for v in iter_violations(f)]
    assert not bad, f"adapters boundary violations: {bad}"


def test_checker_flags_banned_import(tmp_path):
    """Mutation self-test: the walker must actually catch violations."""
    victim = HEXAGON_ROOT / "domain" / "_boundary_selftest_tmp.py"
    victim.write_text("import httpx\nfrom helao.hexagon.app import x\n")
    try:
        hits = iter_violations(victim)
        assert {m for _, m, _ in hits} == {"httpx", "helao.hexagon.app"}
    finally:
        victim.unlink()


def test_checker_allows_domain_allowlist(tmp_path):
    victim = HEXAGON_ROOT / "domain" / "_boundary_selftest_ok_tmp.py"
    victim.write_text(
        "import math\nimport pydantic\nimport numpy\n"
        "from helao.core.models.hlostatus import HloStatus\n"
        "from helao.helpers.premodels import Action\n"
        "from helao.core.helaodict import HelaoDict\n"
        "from helao.core.error import ErrorCodes\n"
    )
    try:
        assert iter_violations(victim) == []
    finally:
        victim.unlink()
```

- [ ] **Step 3: Run the test to verify it fails (packages missing)**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_boundaries.py -q`
Expected: collection error or `test_hexagon_packages_exist` FAILS (no `__init__.py` yet).

- [ ] **Step 4: Create the package markers**

Create `helao/hexagon/__init__.py`:

```python
"""helao.hexagon: the hexagonal rewrite tree (master spec 2026-07-16).

Layers: domain (pure), ports (Protocols), adapters (P1b), app (P1b).
Boundary rules are enforced by tests/test_boundaries.py.
"""
```

Create `helao/hexagon/domain/__init__.py`:

```python
"""Pure domain layer: no I/O, no asyncio, no vendor libs (spec §4.2)."""
```

Create `helao/hexagon/ports/__init__.py`:

```python
"""Port Protocols: typing-only seams between domain and adapters (spec §4.3)."""
```

Create `helao/hexagon/adapters/__init__.py`:

```python
"""Adapters land in P1b. This package is empty in P1a by design."""
```

Create `helao/hexagon/app/__init__.py`:

```python
"""App/composition lands in P1b. This package is empty in P1a by design."""
```

Create `helao/hexagon/tests/__init__.py` (empty file).

- [ ] **Step 5: Run the boundary test to verify it passes**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_boundaries.py -q`
Expected: `7 passed`

- [ ] **Step 6: Format and commit**

```bash
black helao/hexagon
git add helao/hexagon docs/superpowers/plans/2026-07-17-P1a-domain-ports.md
git commit -m "feat(hexagon): P1a scaffold + AST boundary test (spec §4.1)"
```

---

### Task 2: Domain models re-export surface (D8)

**Files:**
- Create: `helao/hexagon/domain/models.py`
- Test: `helao/hexagon/tests/test_ports_import.py` (first half — models section)

**Interfaces:**
- Produces: `helao.hexagon.domain.models` re-exporting every reused legacy model/enum. Ports and all later domain modules import models ONLY from here (keeps the ports allow-list at "domain + stdlib"). Names exported (exact): `Action`, `Experiment`, `Sequence`, `ActionPlanMaker`, `ExperimentPlanMaker`, `ActionModel`, `ShortActionModel`, `ExperimentModel`, `ShortExperimentModel`, `SequenceModel`, `ShortSequenceModel`, `ProcessModel`, `ShortProcessModel`, `SampleModel`, `NoneSample`, `LiquidSample`, `SolidSample`, `GasSample`, `AssemblySample`, `SampleUnion`, `object_to_sample`, `SampleType`, `SampleInheritance`, `SampleStatus`, `FileInfo`, `FileConn`, `FileConnParams`, `HloHeaderModel`, `HloFileGroup`, `DataModel`, `DataPackageModel`, `GlobalStatusModel`, `ActionServerModel`, `EndpointModel`, `MachineModel`, `HloStatus`, `OrchStatus`, `LoopStatus`, `LoopIntent`, `ActionStartCondition`, `RunUse`, `ProcessContrib`, `RunDir`, `AnalysisModel`, `AnalysisDataModel`, `AnalysisOutputModel`, `ShortAnalysisModel`, `ErrorCodes`, `HelaoDict`.

- [ ] **Step 1: Write the failing import test**

Create `helao/hexagon/tests/test_ports_import.py`:

```python
"""Import smoke tests: domain model surface + every port module (spec §4.3)."""

import importlib

MODEL_EXPORTS = [
    "Action", "Experiment", "Sequence", "ActionPlanMaker", "ExperimentPlanMaker",
    "ActionModel", "ShortActionModel", "ExperimentModel", "ShortExperimentModel",
    "SequenceModel", "ShortSequenceModel", "ProcessModel", "ShortProcessModel",
    "SampleModel", "NoneSample", "LiquidSample", "SolidSample", "GasSample",
    "AssemblySample", "SampleUnion", "object_to_sample",
    "SampleType", "SampleInheritance", "SampleStatus",
    "FileInfo", "FileConn", "FileConnParams", "HloHeaderModel", "HloFileGroup",
    "DataModel", "DataPackageModel",
    "GlobalStatusModel", "ActionServerModel", "EndpointModel", "MachineModel",
    "HloStatus", "OrchStatus", "LoopStatus", "LoopIntent",
    "ActionStartCondition", "RunUse", "ProcessContrib", "RunDir",
    "AnalysisModel", "AnalysisDataModel", "AnalysisOutputModel",
    "ShortAnalysisModel", "ErrorCodes", "HelaoDict",
]


def test_domain_models_reexports():
    mod = importlib.import_module("helao.hexagon.domain.models")
    missing = [n for n in MODEL_EXPORTS if not hasattr(mod, n)]
    assert not missing, f"missing re-exports: {missing}"


def test_domain_models_all_matches():
    mod = importlib.import_module("helao.hexagon.domain.models")
    assert sorted(mod.__all__) == sorted(MODEL_EXPORTS)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_ports_import.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'helao.hexagon.domain.models'`

- [ ] **Step 3: Write the re-export module**

Create `helao/hexagon/domain/models.py`:

```python
"""D8 model reuse surface (master spec §4.2.1).

The hexagon domain does NOT define run models. It re-exports the post-CARDS
pydantic models from helao.core.models / helao.helpers.premodels so that:
(a) artifact schemas stay byte-identical (model -> clean_dict -> dict), and
(b) ports/ can reference model types while importing only helao.hexagon.domain
    (boundary rule, spec §4.1).

Known accepted smells (Q4, master spec §14): core/models/server.py imports
premodels.Action; SampleUnion keeps the bare-SampleModel accept-anything
fallback; both are parity requirements, not bugs to fix here.
"""

from helao.helpers.premodels import (
    Action,
    ActionPlanMaker,
    Experiment,
    ExperimentPlanMaker,
    Sequence,
)
from helao.core.models.action import ActionModel, ShortActionModel
from helao.core.models.experiment import ExperimentModel, ShortExperimentModel
from helao.core.models.sequence import SequenceModel, ShortSequenceModel
from helao.core.models.process import ProcessModel, ShortProcessModel
from helao.core.models.sample import (
    AssemblySample,
    GasSample,
    LiquidSample,
    NoneSample,
    SampleInheritance,
    SampleModel,
    SampleStatus,
    SampleType,
    SampleUnion,
    SolidSample,
    object_to_sample,
)
from helao.core.models.file import (
    FileConn,
    FileConnParams,
    FileInfo,
    HloFileGroup,
    HloHeaderModel,
)
from helao.core.models.data import DataModel, DataPackageModel
from helao.core.models.server import (
    ActionServerModel,
    EndpointModel,
    GlobalStatusModel,
)
from helao.core.models.machine import MachineModel
from helao.core.models.hlostatus import HloStatus
from helao.core.models.orchstatus import LoopIntent, LoopStatus, OrchStatus
from helao.core.models.action_start_condition import ActionStartCondition
from helao.core.models.run_use import RunUse
from helao.core.models.process_contrib import ProcessContrib
from helao.core.models.run_dir import RunDir
from helao.core.models.analysis import (
    AnalysisDataModel,
    AnalysisModel,
    AnalysisOutputModel,
    ShortAnalysisModel,
)
from helao.core.error import ErrorCodes
from helao.core.helaodict import HelaoDict

__all__ = [
    "Action",
    "ActionModel",
    "ActionPlanMaker",
    "ActionServerModel",
    "ActionStartCondition",
    "AnalysisDataModel",
    "AnalysisModel",
    "AnalysisOutputModel",
    "AssemblySample",
    "DataModel",
    "DataPackageModel",
    "EndpointModel",
    "ErrorCodes",
    "Experiment",
    "ExperimentModel",
    "ExperimentPlanMaker",
    "FileConn",
    "FileConnParams",
    "FileInfo",
    "GasSample",
    "GlobalStatusModel",
    "HelaoDict",
    "HloFileGroup",
    "HloHeaderModel",
    "HloStatus",
    "LiquidSample",
    "LoopIntent",
    "LoopStatus",
    "MachineModel",
    "NoneSample",
    "OrchStatus",
    "ProcessContrib",
    "ProcessModel",
    "RunDir",
    "RunUse",
    "SampleInheritance",
    "SampleModel",
    "SampleStatus",
    "SampleType",
    "SampleUnion",
    "Sequence",
    "SequenceModel",
    "ShortActionModel",
    "ShortAnalysisModel",
    "ShortExperimentModel",
    "ShortProcessModel",
    "ShortSequenceModel",
    "SolidSample",
    "object_to_sample",
]
```

NOTE for the implementer: if any single import line fails (a name living in a
different module on current `unstable`), locate it with
`grep -rn "class <Name>" helao/core/models helao/helpers/premodels.py` and fix
the import path — do NOT drop the export.

- [ ] **Step 4: Run tests to verify they pass (incl. boundary)**

Run: `conda run -n helao python -m pytest helao/hexagon/tests -q`
Expected: all pass (boundary test confirms `models.py` stays inside the allow-list).

- [ ] **Step 5: Commit**

```bash
black helao/hexagon
git add helao/hexagon
git commit -m "feat(hexagon): domain model re-export surface (D8)"
```

---

### Task 3: Core outbound ports — Hardware, DataSink, ArtifactStore, Sync, Transport, Status

**Files:**
- Create: `helao/hexagon/ports/hardware.py`
- Create: `helao/hexagon/ports/data_sink.py`
- Create: `helao/hexagon/ports/artifact_store.py`
- Create: `helao/hexagon/ports/sync.py`
- Create: `helao/hexagon/ports/transport.py`
- Create: `helao/hexagon/ports/status.py`
- Test: `helao/hexagon/tests/test_ports_import.py` (extend)

**Interfaces:**
- Consumes: `helao.hexagon.domain.models` (Task 2).
- Produces: `HardwarePort`, `ExclusiveAccess`, `driver_response_to_error_code(resp) -> ErrorCodes`, `DataSinkPort`, `ArtifactStorePort`, `SyncPort`, `S3FacePort`, `TransportPort`, `StatusPort` — all `typing.Protocol` (runtime_checkable). Fakes (Task 11) and P1b adapters implement these.

- [ ] **Step 1: Extend the import test (failing)**

Append to `helao/hexagon/tests/test_ports_import.py`:

```python
PORT_MODULES = {
    "helao.hexagon.ports.hardware": ["HardwarePort", "ExclusiveAccess",
                                     "driver_response_to_error_code"],
    "helao.hexagon.ports.data_sink": ["DataSinkPort"],
    "helao.hexagon.ports.artifact_store": ["ArtifactStorePort"],
    "helao.hexagon.ports.sync": ["SyncPort", "S3FacePort"],
    "helao.hexagon.ports.transport": ["TransportPort"],
    "helao.hexagon.ports.status": ["StatusPort"],
}


def test_core_port_modules_import():
    for modname, names in PORT_MODULES.items():
        mod = importlib.import_module(modname)
        for n in names:
            assert hasattr(mod, n), f"{modname} missing {n}"
```

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_ports_import.py -q`
Expected: FAIL (`ModuleNotFoundError: helao.hexagon.ports.hardware`).

- [ ] **Step 2: Write `ports/hardware.py`**

```python
"""Hardware port (spec §4.3.1): the HelaoDriver seam, promoted to an interface.

Contract (normative, from helao/core/drivers/helao_driver.py + core-03):
- Construction from ``config: dict`` (the server YAML ``params:`` block) with
  NO I/O in ``__init__`` — the port bans constructor-connect. Adapters that
  wrap legacy constructor-connecting drivers defer real connection to
  ``connect()``.
- Disconnected construct is first-class: every adapter must be constructible
  (and schema-introspectable) without hardware or vendor runtime present.
- ``DriverResponse`` two-axis result kept verbatim (``response`` = did this
  call work; ``status`` = driver state), including ``DriverStatus.retry`` and
  the empty-``DriverResponse()`` = "skip this sample" poller sentinel.
- Lifecycle is async-first; adapters wrap legacy sync drivers with explicit
  thread offload where needed.
"""

from typing import AsyncContextManager, Protocol, runtime_checkable

from helao.core.drivers.helao_driver import (
    DriverResponse,
    DriverResponseType,
    DriverStatus,
)
from helao.hexagon.domain.models import ErrorCodes

__all__ = [
    "ExclusiveAccess",
    "HardwarePort",
    "driver_response_to_error_code",
]


def driver_response_to_error_code(resp: DriverResponse) -> ErrorCodes:
    """The single DriverResponse -> ErrorCodes mapping (spec §4.3.1).

    Legacy duplicates this string-compare in every executor phase
    (``resp.response == "success"``); adapters and executors must use this
    function instead.
    """
    if resp.response == DriverResponseType.success:
        return ErrorCodes.none
    if resp.status == DriverStatus.busy:
        return ErrorCodes.in_progress
    return ErrorCodes.critical_error


@runtime_checkable
class ExclusiveAccess(Protocol):
    """Async context manager serializing poller-vs-command bus contention.

    Replaces the ad-hoc ``polling``-flag handshakes (AliCat, legato
    ``_send_sync`` fork, Advantech pause/resume) and the disabled Gamry poller.
    """

    def exclusive(self) -> AsyncContextManager[None]: ...


@runtime_checkable
class HardwarePort(Protocol):
    """Async driver lifecycle: connect/arm/start/drain/abort/cleanup/disconnect."""

    async def connect(self) -> DriverResponse: ...

    async def get_status(self) -> DriverResponse: ...

    async def arm(self, **setup_params) -> DriverResponse:
        """Legacy convention ``setup(...)`` — arm a measurement."""
        ...

    async def start(self, **measure_params) -> DriverResponse:
        """Legacy convention ``measure()`` / ``start_channel()``."""
        ...

    async def drain(self, **kwargs) -> DriverResponse:
        """Legacy convention ``get_data(...)`` — incremental column-dict delta."""
        ...

    async def abort(self, **kwargs) -> DriverResponse:
        """Legacy ABC ``stop()`` — abort ALL activity."""
        ...

    async def cleanup(self, **kwargs) -> DriverResponse:
        """De-arm without disconnecting."""
        ...

    async def reset(self) -> DriverResponse: ...

    async def disconnect(self) -> DriverResponse: ...

    async def estop(self, switch: bool) -> DriverResponse: ...

    async def shutdown(self) -> DriverResponse: ...
```

NOTE for the implementer: verify `ErrorCodes.in_progress` exists (`grep -n "in_progress" helao/core/error.py`); if the member is named differently, use the member legacy executors map busy responses to and keep this function's docstring accurate.

- [ ] **Step 3: Write `ports/data_sink.py`**

```python
"""DataSink port (spec §4.3.2): what executors/drivers actually need from Active.

Precedent: cNIMAX.arm_cell_iv receiving plain callables (enqueue_data_nowait,
get_realtime_nowait, finish_hlo_header) — the best-in-tree pattern. Replaces
the ``active.base.app.driver...`` object-graph handouts and the PAL per-job
injected Active.

THREAD-SAFETY IS CONTRACTUAL: members suffixed ``_nowait`` plus
``realtime_ns`` MUST be callable from a foreign thread (the NI-DAQmx hardware
buffer callback). All other members are event-loop-affine.

Signatures mirror the legacy Active surface verbatim
(helao/core/servers/base.py:1155-1380, active_data_stream.py,
active_finalizer.py) so P1b adapters are thin delegation.
"""

from typing import List, Optional, Protocol, Union, runtime_checkable
from uuid import UUID

from helao.hexagon.domain.models import (
    Action,
    AssemblySample,
    DataModel,
    GasSample,
    HloFileGroup,
    LiquidSample,
    NoneSample,
    SolidSample,
)

__all__ = ["DataSinkPort"]

_Sample = Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]


@runtime_checkable
class DataSinkPort(Protocol):
    # --- data stream (thread-safe where noted) ---
    async def enqueue_data(
        self, datamodel: DataModel, action: Optional[Action] = None
    ) -> None: ...

    def enqueue_data_nowait(
        self, datamodel: DataModel, action: Optional[Action] = None
    ) -> None:
        """THREAD-SAFE."""
        ...

    async def enqueue_data_dflt(self, datadict: dict) -> None: ...

    def get_realtime_nowait(self, epoch_ns: Optional[float] = None) -> int:
        """THREAD-SAFE. NTP-corrected epoch nanoseconds."""
        ...

    async def finish_hlo_header(
        self,
        file_conn_keys: Optional[List[UUID]] = None,
        realtime: Optional[int] = None,
    ) -> None: ...

    # --- file output ---
    async def write_file(
        self,
        output_str: str,
        file_type: str,
        filename: Optional[str] = None,
        file_group: HloFileGroup = HloFileGroup.aux_files,
        header: Optional[str] = None,
        sample_str: Optional[str] = None,
        file_sample_label: Optional[Union[List[str], str]] = None,
        json_data_keys: Optional[List[str]] = None,
        action: Optional[Action] = None,
    ) -> Optional[str]: ...

    def write_file_nowait(
        self,
        output_str: str,
        file_type: str,
        filename: Optional[str] = None,
        file_group: HloFileGroup = HloFileGroup.aux_files,
        header: Optional[str] = None,
        sample_str: Optional[str] = None,
        file_sample_label: Optional[Union[List[str], str]] = None,
        json_data_keys: Optional[List[str]] = None,
        action: Optional[Action] = None,
    ) -> Optional[str]:
        """THREAD-SAFE."""
        ...

    async def track_file(
        self,
        file_type: str,
        file_path: str,
        samples: List[_Sample],
        action: Optional[Action] = None,
    ) -> None: ...

    # --- sample bookkeeping ---
    async def append_sample(
        self, samples: List[_Sample], IO: str, action: Optional[Action] = None
    ) -> None: ...

    # --- lifecycle ---
    async def split(
        self, uuid_list: Optional[List[UUID]] = None
    ) -> List[UUID]: ...

    def set_estop(self, action: Optional[Action] = None) -> None:
        """THREAD-SAFE."""
        ...

    # --- live buffer ---
    async def put_lbuf(self, payload: dict) -> None: ...

    def put_lbuf_nowait(self, payload: dict) -> None:
        """THREAD-SAFE."""
        ...

    def get_lbuf(self, key: str) -> tuple: ...
```

- [ ] **Step 4: Write `ports/artifact_store.py`**

```python
"""ArtifactStore port (spec §4.3.3): meta ymls, HLO streams, promotion, zip.

Abstracts MetaFileWriter + DataFileWriter/DataStreamer file side + move_dir +
yml_finisher. ALL semantics below are parity-critical (spec §5):

- Atomic yml writes (temp file + os.replace), trailing newline,
  ``file_type:`` first key.
- LAZY hlo open on first data item per file_conn_key (mode ``w+``); header
  (HloHeaderModel.clean_dict()) at open; ``%%\\n`` before first data row; one
  JSON object per line; NaN/Infinity tokens legal; NO DATA => NO FILE; close
  at finish (or substitute).
- One-shot files: mode ``a+``, ``header + "%%\\n" + payload``, FileInfo
  appended at write; gated by ``save_data``.
- ``finish()`` JOINS the write queue before closing handles (drain protocol
  §5.4); late data beyond the bounded retries is dropped exactly as legacy
  drops it.
- ``move_dir`` promotion: RUNS_ACTIVE -> RUNS_FINISHED (manual -> RUNS_DIAG;
  ``.hlo`` with sync_data=False -> RUNS_NOSYNC); 60x/30x copy/remove retries;
  then DB-server ``/finish_yml`` handoff; fire-and-forget task semantics
  preserved.
"""

from pathlib import Path
from typing import Optional, Protocol, runtime_checkable
from uuid import UUID

from helao.hexagon.domain.models import Action, Experiment, Sequence

__all__ = ["ArtifactStorePort"]


@runtime_checkable
class ArtifactStorePort(Protocol):
    # --- meta ymls (atomic; file_type first key; same-name rewrite wins) ---
    async def write_act(self, action: Action) -> None: ...

    async def write_exp(self, experiment: Experiment) -> None: ...

    async def write_seq(self, sequence: Sequence) -> None: ...

    # --- streamed hlo (lazy open contract in module docstring) ---
    async def write_data_line(
        self, action: Action, file_conn_key: UUID, payload: object
    ) -> None:
        """Open-on-first-call for this key; header + %% precede the row."""
        ...

    async def close_streams(self, action: Action) -> None:
        """Close every open file handle for this action (finish step 3 /
        substitute)."""
        ...

    # --- one-shot files ---
    async def write_one_shot(
        self,
        action: Action,
        output_str: str,
        file_type: str,
        filename: Optional[str],
        header: Optional[str],
    ) -> Optional[str]: ...

    # --- finish + promotion ---
    async def finish(self, action: Action) -> None:
        """Join pending writes, close handles, final -act.yml rewrite."""
        ...

    async def move_dir(self, hobj: object) -> bool:
        """Promote a run dir per RunDir progression; returns success."""
        ...

    async def zip_dir(self, dir_path: Path) -> Path:
        """Zip a synced sequence dir (entries relative to seq dir, .prg
        included, .lock skipped, source dir deleted)."""
        ...
```

- [ ] **Step 5: Write `ports/sync.py`**

```python
"""Sync port (spec §4.3.4): HelaoSyncer/SyncDriver surface + S3 face.

Semantics carried by the P1b adapter (documented here as the contract):
hierarchical seq-RW/exp-mutex locks; children gate with
estopped-children-terminal rule; priority re-enqueue with rank floor -5;
file push; process reconcile+flush writing -prc.yml; patched meta JSON;
.lock cleanup; move-to-SYNCED; empty-dir pruning; destructive sequence zip;
optional auto-analysis dispatch; .prg sidecar lifecycle; reset_sync reversal.
S3: retries <=5 x 30 s via asyncio.to_thread; unset S3 config => local-only
success. The Sim DB server (P0) implements S3FacePort with a recording sink.
"""

from pathlib import Path
from typing import Optional, Protocol, Union, runtime_checkable

__all__ = ["S3FacePort", "SyncPort"]


@runtime_checkable
class S3FacePort(Protocol):
    async def upload(
        self,
        key: str,
        body: Union[dict, bytes, Path],
        content_type: str = "application/json",
        compress: bool = False,
    ) -> bool: ...


@runtime_checkable
class SyncPort(Protocol):
    async def enqueue_yml(
        self, upath: Union[str, Path], rank: int = 5, rank_limit: int = -5
    ) -> None: ...

    async def sync_yml(
        self,
        yml_path: Path,
        retries: int = 3,
        rank: int = 5,
        force_s3: bool = False,
        force_api: bool = False,
        compress: bool = False,
    ) -> dict: ...

    async def finish_pending(self) -> list: ...

    async def reset_sync(self, sync_path: str) -> bool: ...

    async def to_s3(
        self, msg: Union[dict, Path], target: str, retries: int = 5
    ) -> bool: ...

    async def to_api(self, req_model: dict, meta_type: str) -> bool:
        """STUB by decision (spec §1.3): returns True unconditionally."""
        ...

    def list_pending(self) -> dict: ...

    def n_queue(self) -> int: ...
```

- [ ] **Step 6: Write `ports/transport.py`**

```python
"""Transport port (spec §4.3.5, §7): ZMQ-first RPC + HTTP-fallback dispatch.

Abstracts helao/helpers/dispatcher.py + helao/core/rpc/zmq_rpc.py. Contract
highlights the P1b adapter must honor:
- RPC port pairing derive_rpc_port(http_port) = http_port + 10000; 3 s probe
  timeout IS the down-detector.
- Action dispatch: RPC method "<server_name>/<action_name>", kwargs =
  params + {"action": A.as_dict()}; HTTP fallback POST
  http://host:port/<server>/<action>, json {"action": A.as_dict()},
  <=5 retries linear backoff. Returns (response_json | None, ErrorCodes).
- Semantic difference preserved: HTTP traverses the action-queuing
  middleware; RPC bypasses it.
- NEVER self-RPC from inside the dispatch loop (in-process self-ops).
"""

from typing import Optional, Protocol, Tuple, runtime_checkable

from helao.hexagon.domain.models import Action, ErrorCodes

__all__ = ["TransportPort"]


@runtime_checkable
class TransportPort(Protocol):
    async def dispatch_action(
        self,
        action: Action,
        params: Optional[dict] = None,
        timeout: float = 60,
        retries: int = 5,
    ) -> Tuple[Optional[dict], ErrorCodes]: ...

    async def dispatch_private(
        self,
        server_key: str,
        host: str,
        port: int,
        private_action: str,
        params_dict: Optional[dict] = None,
        json_dict: Optional[dict] = None,
        timeout: float = 60,
        retries: int = 5,
    ) -> Tuple[Optional[dict], ErrorCodes]: ...

    async def check_endpoint(self, url: str, timeout: float = 3.0) -> bool:
        """HEAD probe (endpoints_available / heartbeat monitor)."""
        ...
```

- [ ] **Step 7: Write `ports/status.py`**

```python
"""Status port (spec §4.3.6): push + dual WS stacks.

Both parallel WS mechanisms survive (consumers exist for each): the
WsPublisher-backed /ws_status /ws_data /ws_live routes AND the _ws_relay
zstd-compressed-pickle streams. Serialization happens ONLY in the adapter
(KEEP #4: _json_clean at the relay). The legacy blocking 0.3 s per-client
pacing is preserved behavior until post-parity.
"""

from typing import Optional, Protocol, Tuple, runtime_checkable
from uuid import UUID

from helao.hexagon.domain.models import ActionServerModel

__all__ = ["StatusPort"]


@runtime_checkable
class StatusPort(Protocol):
    async def attach_client(
        self, client_servkey: str, client_host: str, client_port: int
    ) -> bool: ...

    async def detach_client(
        self, client_servkey: str, client_host: str, client_port: int
    ) -> None: ...

    async def send_status(
        self, asm: ActionServerModel, retries: int = 5
    ) -> None:
        """POST the full/filtered ActionServerModel to every registered
        client's private /update_status."""
        ...

    async def send_nonblocking_status(
        self,
        client_servkey: str,
        client_host: str,
        client_port: int,
        server_key: str,
        exec_id: str,
        act_uuid: UUID,
        status: str,
        retries: int = 3,
    ) -> None:
        """Nonblocking executors push /update_nonblocking directly."""
        ...

    async def publish_status(self, payload: dict) -> None: ...

    async def publish_data(self, payload: dict) -> None: ...

    async def publish_live(self, payload: dict) -> None: ...
```

- [ ] **Step 8: Run tests (boundary + imports)**

Run: `conda run -n helao python -m pytest helao/hexagon/tests -q`
Expected: all pass. If the boundary test fails on `helao.core.drivers.helao_driver`, the ports allow-list constant in `test_boundaries.py` was mistyped — fix the code, never the rule.

- [ ] **Step 9: Commit**

```bash
black helao/hexagon
git add helao/hexagon
git commit -m "feat(hexagon): core outbound port Protocols (Hardware/DataSink/ArtifactStore/Sync/Transport/Status)"
```

---

### Task 4: Runtime-service + auxiliary ports — Clock, Logging, Config, AnalysisArtifact, SampleState, Auxiliary

**Files:**
- Create: `helao/hexagon/ports/clock.py`
- Create: `helao/hexagon/ports/logging.py`
- Create: `helao/hexagon/ports/config.py`
- Create: `helao/hexagon/ports/analysis.py`
- Create: `helao/hexagon/ports/sample_state.py`
- Create: `helao/hexagon/ports/auxiliary.py`
- Test: `helao/hexagon/tests/test_ports_import.py` (extend)

**Interfaces:**
- Consumes: `helao.hexagon.domain.models` (Task 2).
- Produces: `ClockPort`, `LoggingPort`, `ConfigPort`, `AnalysisArtifactPort`, `SampleStatePort`, `StatePersistencePort`, `PlateInfoPort`, `LibraryPort`, `HealthPort`, `NotifyPort`.

- [ ] **Step 1: Extend the import test (failing)**

In `helao/hexagon/tests/test_ports_import.py`, extend `PORT_MODULES`:

```python
PORT_MODULES.update(
    {
        "helao.hexagon.ports.clock": ["ClockPort"],
        "helao.hexagon.ports.logging": ["LoggingPort"],
        "helao.hexagon.ports.config": ["ConfigPort"],
        "helao.hexagon.ports.analysis": ["AnalysisArtifactPort"],
        "helao.hexagon.ports.sample_state": ["SampleStatePort"],
        "helao.hexagon.ports.auxiliary": [
            "StatePersistencePort",
            "PlateInfoPort",
            "LibraryPort",
            "HealthPort",
            "NotifyPort",
        ],
    }
)
```

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_ports_import.py -q`
Expected: FAIL (`ModuleNotFoundError: helao.hexagon.ports.clock`).

- [ ] **Step 2: Write `ports/clock.py`**

```python
"""Clock port (spec §4.3.7): NTP offset arithmetic.

Offset file <root>/LOGS/ntpLastSync.txt is written by launch and read at Base
init; set_time(offset) mints every *_timestamp; epoch_ns is stamped at lazy
file open OR header finish (two legal paths — goldens must not diff header
epoch). A deterministic clock may be injected ONLY in unit fixtures, never in
capture runs.
"""

from datetime import datetime
from typing import Protocol, runtime_checkable

__all__ = ["ClockPort"]


@runtime_checkable
class ClockPort(Protocol):
    def now(self) -> datetime:
        """NTP-corrected wall time (legacy set_time(offset=ntp_offset))."""
        ...

    def now_ns(self) -> int:
        """NTP-corrected epoch nanoseconds (legacy get_realtime_nowait)."""
        ...

    def offset(self) -> float:
        """The NTP offset in seconds (legacy ntp_offset)."""
        ...
```

- [ ] **Step 3: Write `ports/logging.py`**

```python
"""Logging port (spec §4.3.8, §9.1): ONE module, FAIL LOUD.

Wraps the legacy helao.helpers.helao_logging in P1b — nothing is vendored
(F3 countermeasure). The port's file-logger factory RAISES when asked to
create a file logger without a resolved log root; the mkdtemp() fallback is
unreachable through the port. Contractual path: <root>/LOGS/<server_key>.log.
"""

from typing import Optional, Protocol, runtime_checkable

__all__ = ["LoggingPort"]


@runtime_checkable
class LoggingPort(Protocol):
    def file_logger(self, server_key: str, log_root: str) -> object:
        """Create/return the named singleton logger writing
        <log_root>/<server_key>.log. MUST raise ValueError when log_root is
        falsy — never fall back to a tempdir (F3)."""
        ...

    def info(self, msg: str) -> None: ...

    def warning(self, msg: str) -> None: ...

    def error(self, msg: str, exc_info: bool = False) -> None: ...

    def alert(self, msg: str) -> None:
        """ALERT level 60: email/webhook queue listeners (throttled)."""
        ...
```

- [ ] **Step 4: Write `ports/config.py`**

```python
"""Config port (spec §4.3.9, §9.2): raw-dict identity.

The raw config dict is the runtime source of truth. Object identity of
CONFIG["servers"][key] with each server's server_cfg MUST be preserved (the
--restore in-place mutation gate rides on it). Typed views are read-only and
derived; they are never installed as the runtime dict.
"""

from typing import Protocol, runtime_checkable

__all__ = ["ConfigPort"]


@runtime_checkable
class ConfigPort(Protocol):
    def world_cfg(self) -> dict:
        """THE raw config dict (same object every call)."""
        ...

    def server_cfg(self, server_key: str) -> dict:
        """Identity-preserving view: world_cfg()['servers'][server_key]."""
        ...

    def server_params(self, server_key: str) -> dict:
        """The server's params: block (empty dict when absent)."""
        ...

    def root(self) -> str:
        """The config root: path (raises if undefined, like helao_dirs)."""
        ...
```

- [ ] **Step 5: Write `ports/analysis.py`**

```python
"""AnalysisArtifact port (spec §4.3.10): ONE way to publish an AnalysisRecord.

Unifies Deployment-C's three divergent analysis writers behind a single
"publish" seam producing the §5 row-13 layout (ANALYSES/<yy.ww>/<mmdd>/... +
per-output JSONs + analysis/<uuid>.json S3 keys, content-hash UUIDs).
Converters ENQUEUE analyses; they never write the layout themselves.
"""

from typing import List, Protocol, runtime_checkable

from helao.hexagon.domain.models import AnalysisModel, AnalysisOutputModel

__all__ = ["AnalysisArtifactPort"]


@runtime_checkable
class AnalysisArtifactPort(Protocol):
    async def publish(
        self, analysis: AnalysisModel, outputs: List[AnalysisOutputModel]
    ) -> bool: ...

    async def enqueue(self, analysis: AnalysisModel) -> None: ...
```

- [ ] **Step 6: Write `ports/sample_state.py`**

```python
"""SampleState port (spec §4.3.11): the Archive boundary.

The boundary is SAMPLE-server-behind-RPC — exactly what PAL already consumes
via sample_shim.SampleArchiveShim (fail-loud RPC client, call-time address
resolution, typed rehydration). Signatures mirror the shim's public methods
verbatim so the P1b adapter is the shim itself. Archive is NEVER ported as a
driver.
"""

from typing import Any, List, Optional, Protocol, Tuple, runtime_checkable

from helao.hexagon.domain.models import Action, ErrorCodes

__all__ = ["SampleStatePort"]


@runtime_checkable
class SampleStatePort(Protocol):
    # -- tray methods --
    async def tray_query_sample(
        self,
        tray: Optional[int] = None,
        slot: Optional[int] = None,
        vial: Optional[int] = None,
    ) -> Tuple[ErrorCodes, Any]: ...

    async def tray_get_next_full(
        self,
        after_tray: Optional[int] = None,
        after_slot: Optional[int] = None,
        after_vial: Optional[int] = None,
    ) -> dict: ...

    async def tray_new_position(self, req_vol: float = 2.0) -> dict: ...

    async def tray_update_position(
        self,
        tray: Optional[int] = None,
        slot: Optional[int] = None,
        vial: Optional[int] = None,
        sample: Optional[Any] = None,
        dilute: bool = False,
    ) -> bool: ...

    # -- custom-position methods --
    async def custom_query_sample(
        self, custom: Optional[str] = None
    ) -> Tuple[ErrorCodes, Any]: ...

    async def custom_update_position(
        self,
        custom: Optional[str] = None,
        sample: Optional[Any] = None,
        dilute: bool = False,
    ) -> Tuple[bool, Any]: ...

    async def custom_dest_allowed(self, custom: Optional[str] = None) -> bool: ...

    async def custom_assembly_allowed(
        self, custom: Optional[str] = None
    ) -> bool: ...

    async def custom_is_destroyed(self, custom: Optional[str] = None) -> bool: ...

    # -- sample creation --
    async def new_ref_samples(
        self,
        samples_in: Optional[List] = None,
        sample_out_type: Any = "",
        sample_position: str = "",
        action: Optional[Action] = None,
        combine_liquids: bool = False,
        combine_gases: bool = False,
    ) -> Tuple[ErrorCodes, list]: ...

    # -- unified sample DB sub-surface (shim's .unified) --
    async def get_samples(self, samples: Optional[list] = None) -> list: ...

    async def new_samples(self, samples: Optional[list] = None) -> list: ...

    async def update_samples(self, samples: Optional[list] = None) -> None: ...
```

NOTE for the implementer: cross-check each signature against
`helao/deploy/hte/drivers/robot/sample_shim.py` (drop only the `*args,
**kwargs` catch-alls); if the shim has additional public methods (e.g.
`custom_unloadall`, `custom_load`), add them to the Protocol with matching
signatures — the port must cover the shim's whole public surface.

- [ ] **Step 7: Write `ports/auxiliary.py`**

```python
"""Auxiliary ports (spec §4.3.12)."""

from pathlib import Path
from typing import Callable, Dict, List, Optional, Protocol, Tuple, runtime_checkable

__all__ = [
    "HealthPort",
    "LibraryPort",
    "NotifyPort",
    "PlateInfoPort",
    "StatePersistencePort",
]


@runtime_checkable
class StatePersistencePort(Protocol):
    """queues.pck export/import. Pickle shape per core-01 §2 including
    globalstatusmodel (runtime FSM state persists across restore — a parity
    behavior). Import archives the consumed pck (queues_imported_<ts>.pck)."""

    def export_queues(self, payload: dict, timestamp_pck: bool = False) -> Path: ...

    def import_queues(self) -> Optional[dict]: ...


@runtime_checkable
class PlateInfoPort(Protocol):
    """PLATE_API / HTEPlateAPI queries + the plate gate (verify_plates)."""

    async def get_platemap_plateid(self, plate_id: int) -> list: ...

    async def has_access(self, plate_id: int, usernames: List[str]) -> bool: ...


@runtime_checkable
class LibraryPort(Protocol):
    """Dynamic import of experiment/sequence/postprocessor libs +
    codehash/codepath provenance. Flat name-keyed registries with a LOAD-TIME
    COLLISION CHECK (silent shadowing becomes a loud preflight error,
    config-overridable for intentional shadowing)."""

    def experiment_lib(self) -> Dict[str, Callable]: ...

    def sequence_lib(self) -> Dict[str, Callable]: ...

    def provenance(self, func_name: str) -> Tuple[str, str]:
        """Return (codehash, codepath) for a registered library function."""
        ...


@runtime_checkable
class HealthPort(Protocol):
    """HEAD-probe endpoints_available, ping_action_servers, heartbeat
    monitors (active_action_monitor default 10 s + ignore_heartbeats;
    driver-health status_summary gate)."""

    async def endpoints_available(
        self, urls: List[str]
    ) -> List[Tuple[str, bool]]: ...

    async def ping_action_servers(self) -> Dict[str, str]: ...

    def status_summary(self) -> Dict[str, str]:
        """server_key -> driver status string; 'unknown' gates dispatch."""
        ...


@runtime_checkable
class NotifyPort(Protocol):
    """Live buffer put, globstat/WS relay, LOGGER.alert."""

    def put_lbuf_nowait(self, payload: dict) -> None: ...

    async def publish_globstat(self, payload: dict) -> None: ...

    def alert(self, msg: str) -> None: ...


@runtime_checkable
class UuidFactoryPort(Protocol):
    """Identity minting seam so domain policies stay deterministic in tests."""

    def __call__(self) -> object: ...
```

Add `"UuidFactoryPort"` to `__all__` (keep the list sorted).

- [ ] **Step 8: Run tests**

Run: `conda run -n helao python -m pytest helao/hexagon/tests -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
black helao/hexagon
git add helao/hexagon
git commit -m "feat(hexagon): runtime-service + auxiliary port Protocols"
```

---

### Task 5: Domain naming + artifact assembly

**Files:**
- Create: `helao/hexagon/domain/naming.py`
- Create: `helao/hexagon/domain/assembly.py`
- Test: `helao/hexagon/tests/test_naming.py`
- Test: `helao/hexagon/tests/test_assembly.py`

**Interfaces:**
- Consumes: `helao.hexagon.domain.models` (Task 2).
- Produces: `naming.meta_yml_filename(obj_timestamp: datetime, kind: str) -> str`; `naming.hlo_filename(action_abbr, orch_submit_order, action_order, action_retry, action_split, filenum, file_ext="hlo") -> str`; `naming.new_file_conn_key(key: str) -> UUID`; `naming.dflt_file_conn_key() -> UUID`; `naming.redirect_manual_dir(path: str) -> str`; `naming.is_nosync_file(filename: str, sync_data: bool) -> bool`; `assembly.assemble_act(action) -> dict`; `assembly.assemble_exp(experiment) -> dict`; `assembly.assemble_seq(sequence) -> dict`; `assembly.assemble_process(meta: dict) -> dict`.

Dir naming itself (sequence/experiment/action output dirs) is NOT re-implemented — it lives on the reused premodels (`get_sequence_dir`/`get_experiment_dir`/`get_action_dir`, D8) and is pinned here by tests.

- [ ] **Step 1: Write the failing naming tests**

Create `helao/hexagon/tests/test_naming.py`:

```python
"""Pin the §5.1/§5.2 naming grammar (pure functions + reused premodels)."""

from datetime import datetime
from uuid import UUID

from helao.hexagon.domain import naming
from helao.hexagon.domain.models import Sequence, Experiment


def test_meta_yml_filename_grammar():
    ts = datetime(2026, 7, 17, 13, 5, 9, 123456)
    assert naming.meta_yml_filename(ts, "act") == "260717.130509123456-act.yml"
    assert naming.meta_yml_filename(ts, "exp") == "260717.130509123456-exp.yml"
    assert naming.meta_yml_filename(ts, "seq") == "260717.130509123456-seq.yml"


def test_meta_yml_filename_rejects_unknown_kind():
    import pytest

    with pytest.raises(ValueError):
        naming.meta_yml_filename(datetime(2026, 1, 1), "prc")


def test_hlo_filename_grammar():
    # active_data_file.py:139 template, filenum = index in file_conn_keys
    assert (
        naming.hlo_filename("CA", 3, 0, 0, 1, 0)
        == "CA-3.0.0.1__0.hlo"
    )
    assert (
        naming.hlo_filename("OCV", 0, 2, 1, 0, 2, file_ext="csv")
        == "OCV-0.2.1.0__2.csv"
    )


def test_file_conn_key_is_md5_uuid():
    # base_meta_writer.py:154-168: UUID(md5(key).hexdigest())
    import hashlib

    key = "somekey"
    expect = UUID(hashlib.md5(key.encode("utf-8")).hexdigest())
    assert naming.new_file_conn_key(key) == expect


def test_dflt_file_conn_key_is_md5_of_str_none():
    assert naming.dflt_file_conn_key() == naming.new_file_conn_key(str(None))


def test_redirect_manual_dir():
    # the RUNS_ACTIVE -> RUNS_DIAG substitution, centralized (spec §4.2.3)
    assert (
        naming.redirect_manual_dir("C:/INST/RUNS_ACTIVE/26.28/0717/x")
        == "C:/INST/RUNS_DIAG/26.28/0717/x"
    )
    assert naming.redirect_manual_dir("no_state_dir/here") == "no_state_dir/here"


def test_is_nosync_file():
    # FileInfo.nosync=True for .hlo when action.sync_data is False
    assert naming.is_nosync_file("a__0.hlo", sync_data=False) is True
    assert naming.is_nosync_file("a__0.hlo", sync_data=True) is False
    assert naming.is_nosync_file("notes.csv", sync_data=False) is False


def test_sequence_dir_grammar_reused_from_premodels():
    seq = Sequence(
        sequence_name="test_seq",
        sequence_label="lab",
        sequence_params={"plate_id": 1234, "plate_sample_no_list": [7]},
    )
    seq.sequence_timestamp = datetime(2026, 7, 17, 13, 5, 9)
    # checksum: digit-sum of 1234 = 10, mod 10 = 0 -> serial "12340"
    assert (
        seq.get_sequence_dir()
        == "26.28/0717/130509__test_seq__lab-12340-7"
    )


def test_experiment_dir_grammar_reused_from_premodels():
    exp = Experiment(experiment_name="test_exp")
    exp.sequence_output_dir = "26.28/0717/130509__test_seq__lab"
    exp.experiment_timestamp = datetime(2026, 7, 17, 13, 6, 1)
    assert (
        exp.get_experiment_dir()
        == "26.28/0717/130509__test_seq__lab/260717.130601__test_exp"
    )
```

NOTE for the implementer: `%U` week-of-year depends on the calendar —
2026-07-17 falls in week 28 with Python's `%U` on this date; if the assertion
fails on the week component, print `datetime(2026,7,17).strftime("%y.%U")`
once and pin the actual value (the format string, not the constant, is the
contract). Same for `Sequence`/`Experiment` construction: if pydantic requires
extra defaults, construct with the minimal field set that legacy operator code
uses.

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_naming.py -q`
Expected: FAIL with `ImportError: cannot import name 'naming'`.

- [ ] **Step 3: Write `domain/naming.py`**

```python
"""Pure naming grammar (spec §4.2.3, §5.1-§5.2).

Sources of truth mirrored here:
- meta yml filename: base_meta_writer.py:98/124/146
  ``<obj_timestamp:%y%m%d.%H%M%S%f>-{act,exp,seq}.yml``
- streamed/one-shot data filename: active_data_file.py:139
  ``{abbr}-{orch_submit_order}.{action_order}.{action_retry}.{action_split}__{filenum}.{ext}``
- file-conn keys: base_meta_writer.py:154-172 (md5 -> UUID; default key =
  md5(str(None)) — 34 call sites)
- manual-run redirection RUNS_ACTIVE -> RUNS_DIAG: centralized here (legacy
  copy-pastes the string replace at 8+ write sites)
- nosync flag: active_data_file.py:154

Dir naming (sequence/experiment/action output dirs) is intentionally NOT
duplicated: it lives on the reused premodels (get_sequence_dir /
get_experiment_dir / get_action_dir, D8) and is pinned by tests/test_naming.py.
"""

import hashlib
from datetime import datetime
from uuid import UUID

__all__ = [
    "META_YML_TS_FMT",
    "dflt_file_conn_key",
    "hlo_filename",
    "is_nosync_file",
    "meta_yml_filename",
    "new_file_conn_key",
    "redirect_manual_dir",
]

META_YML_TS_FMT = "%y%m%d.%H%M%S%f"

_META_KINDS = ("act", "exp", "seq")


def meta_yml_filename(obj_timestamp: datetime, kind: str) -> str:
    """Return ``<ts>-{kind}.yml`` for kind in {'act','exp','seq'}."""
    if kind not in _META_KINDS:
        raise ValueError(f"unknown meta kind {kind!r}; expected one of {_META_KINDS}")
    return f"{obj_timestamp.strftime(META_YML_TS_FMT)}-{kind}.yml"


def hlo_filename(
    action_abbr: str,
    orch_submit_order: int,
    action_order: int,
    action_retry: int,
    action_split: int,
    filenum: int,
    file_ext: str = "hlo",
) -> str:
    """The streamed/one-shot data filename (active_data_file.py:139).

    ``filenum`` is the index of the file_conn_key in ``action.file_conn_keys``.
    """
    return (
        f"{action_abbr}-{orch_submit_order}.{action_order}."
        f"{action_retry}.{action_split}__{filenum}.{file_ext}"
    )


def new_file_conn_key(key: str) -> UUID:
    """UUID derived from the MD5 hash of ``key`` (base_meta_writer.py:154)."""
    md5_hash = hashlib.md5()
    md5_hash.update(key.encode("utf-8"))
    return UUID(md5_hash.hexdigest())


def dflt_file_conn_key() -> UUID:
    """The default file-connection key: ``md5(str(None))``."""
    return new_file_conn_key(str(None))


def redirect_manual_dir(path: str) -> str:
    """Manual-run redirection: substitute RUNS_ACTIVE -> RUNS_DIAG.

    State transitions are literal string substitution of the RUNS_* path
    segment (spec §5.1); this is the single domain home for the manual
    variant.
    """
    return path.replace("RUNS_ACTIVE", "RUNS_DIAG")


def is_nosync_file(filename: str, sync_data: bool) -> bool:
    """FileInfo.nosync rule: True for ``.hlo`` files when sync_data is off."""
    return (not sync_data) and filename.endswith(".hlo")
```

- [ ] **Step 4: Run naming tests to verify they pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_naming.py -q`
Expected: PASS (adjust week-number pin only per the Step-1 note if needed).

- [ ] **Step 5: Write the failing assembly tests**

Create `helao/hexagon/tests/test_assembly.py`:

```python
"""Artifact-content assembly = model -> clean_dict, file_type first (D8/§5.2)."""

from helao.hexagon.domain import assembly
from helao.hexagon.domain.models import Action, Experiment, Sequence


def _mk_action() -> Action:
    act = Action(action_name="acquire", action_params={"rate": 1.5, "n": 3})
    act.action_server.server_name = "SIM"
    act.action_server.machine_name = "testbox"
    return act


def test_assemble_act_has_file_type_first_and_clean_dict_body():
    act = _mk_action()
    act.init_act()  # manual promotion path fills seq/exp synthetics
    out = assembly.assemble_act(act)
    assert list(out.keys())[0] == "file_type"
    assert out["file_type"] == "action"
    # action_params relayed bit-exact (D7)
    assert out["action_params"] == {"rate": 1.5, "n": 3}
    # clean_dict drops Nones: no None values anywhere at top level
    assert all(v is not None for v in out.values())


def test_assemble_exp_and_seq_kinds():
    seq = Sequence(sequence_name="s", sequence_label="l")
    seq.init_seq()
    exp = Experiment(experiment_name="e")
    exp.sequence_output_dir = seq.sequence_output_dir
    exp.sequence_timestamp = seq.sequence_timestamp
    exp.init_exp()
    e = assembly.assemble_exp(exp)
    s = assembly.assemble_seq(seq)
    assert list(e.keys())[0] == "file_type" and e["file_type"] == "experiment"
    assert list(s.keys())[0] == "file_type" and s["file_type"] == "sequence"


def test_assemble_process_strips_private_keys():
    meta = {
        "process_uuid": "b0e9b5a6-6e50-44d8-8f10-4d54a297c742",
        "technique_name": "CA",
        "_private_note": "dropped",
    }
    out = assembly.assemble_process(meta)
    assert out["file_type"] == "process"
    assert "_private_note" not in out
```

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_assembly.py -q`
Expected: FAIL (`ImportError: cannot import name 'assembly'`).

- [ ] **Step 6: Write `domain/assembly.py`**

```python
"""Artifact-content assembly (spec §4.2.1/§4.2.3, D8).

The domain's artifact assembly is "model -> clean_dict -> dict", NOTHING
else. The ``file_type`` key is prepended first exactly as
base_meta_writer.py:103/128/150 does; the ArtifactStore adapter (P1b) dumps
these dicts via yml_dumps with a trailing newline and atomic replace.
Byte-parity is measured post-clean_dict (spec §5.3), never on model_dump().
"""

from helao.hexagon.domain.models import (
    Action,
    Experiment,
    ProcessModel,
    Sequence,
)

__all__ = [
    "assemble_act",
    "assemble_exp",
    "assemble_process",
    "assemble_seq",
]


def assemble_act(action: Action) -> dict:
    """-act.yml content: {"file_type": "action"} + ActionModel.clean_dict()."""
    out = {"file_type": "action"}
    out.update(action.get_act().clean_dict())
    return out


def assemble_exp(experiment: Experiment) -> dict:
    """-exp.yml content (get_exp() rebuilds samples/files aggregates)."""
    out = {"file_type": "experiment"}
    out.update(experiment.get_exp().clean_dict())
    return out


def assemble_seq(sequence: Sequence) -> dict:
    """-seq.yml content (get_seq() snapshots dispatched_experiments_abbr)."""
    out = {"file_type": "sequence"}
    out.update(sequence.get_seq().clean_dict())
    return out


def assemble_process(meta: dict) -> dict:
    """-prc.yml content: ProcessModel-validated, strip_private=True
    (sync_driver.py ~:1698 — the ONLY artifact assembled with strip_private).
    """
    out = {"file_type": "process"}
    out.update(ProcessModel.model_validate(meta).clean_dict(strip_private=True))
    return out
```

NOTE for the implementer: before finalizing, confirm against
`helao/core/servers/base_meta_writer.py` `write_act/write_exp/write_seq`
whether the dict passed to the yml dump is `obj.get_*().clean_dict()` or a
pre-computed dict handed in by the caller — mirror exactly what the writer
serializes. If the legacy `-prc.yml` writer does NOT prepend a `file_type`
key (check `sync_driver.py` around line 1628-1740), drop it from
`assemble_process` and fix the test — the legacy bytes win.

- [ ] **Step 7: Run assembly tests to verify they pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_assembly.py -q`
Expected: PASS.

- [ ] **Step 8: Full suite + commit**

Run: `conda run -n helao python -m pytest helao/hexagon/tests -q`
Expected: all pass.

```bash
black helao/hexagon
git add helao/hexagon
git commit -m "feat(hexagon): domain naming grammar + clean_dict artifact assembly"
```

---

### Task 6: Dispatch policy + global-param folds (port of already-pure CARDS code)

**Files:**
- Create: `helao/hexagon/domain/dispatch_policy.py`
- Create: `helao/hexagon/domain/global_params.py`
- Test: `helao/hexagon/tests/test_dispatch_policy.py`
- Test: `helao/hexagon/tests/test_global_params.py`

**Interfaces:**
- Consumes: `helao.hexagon.domain.models` enums (`LoopStatus`, `LoopIntent`, `OrchStatus`, `ActionStartCondition`).
- Produces: `DispatchSnapshot`, `FinalizationSnapshot`, the step dataclasses (`ExitLoop`, `DriverHealthWait`, `StopLoop`, `LaunchAction`, `FinishThenDispatchExperiment`, `FinishThenDispatchSequence`, `LogQueuesEmpty`, `PauseLoop`, `DrainForStop`, `SkipClearActions`, `EstopClearActions`, `ProceedDispatch`, `NoWaitProceed`, `AwaitEndpointFree`, `AwaitServerFree`, `AwaitWaitEndpointFree`, `AwaitPreviousActionDone`, `WaitAllActions`, `CloseOutExperiment`, `CloseOutSequence`, `SetLoopStopped`, `ClearIntent`, `ExportQueues`), guards (`should_close_out_experiment`, `should_close_out_sequence`, `should_set_stopped`, `should_export`), and class `DispatchPolicy` with methods `next_step(snap)`, `ladder_step(snap)`, `evaluate_step_thru(snap)`, `pre_dispatch_intent_step(loop_intent)`, `start_condition_step(sc)`, `finalization_plan(fsnap)`. Also `apply_from_globals(params, from_global_map, global_params, *, logger_ctx)` and `collect_to_globals(result_action, global_params, *, orch_key, orch_host, orch_port)`.

**Porting rule (Q6, rewrite-with-reference):** copy the class/dataclass/function bodies from `helao/core/servers/orch_dispatch.py:128-482` and `helao/core/servers/orch_global_params.py` byte-for-byte EXCEPT: (a) imports come from `helao.hexagon.domain.models` (never `helao.core.servers.*` / `helao.helpers.helao_logging` — both outside the domain allow-list); (b) the `LOGGER` is stdlib `logging.getLogger(__name__)` (stdlib is allowed; log wording preserved verbatim); (c) drop the `DispatchRunner` class entirely (async effect shell = P1b). The domain copy is the canonical one going forward; the legacy module remains untouched.

- [ ] **Step 1: Write the failing policy tests**

Create `helao/hexagon/tests/test_dispatch_policy.py`:

```python
"""Unit tests for the ported pure DispatchPolicy (core-01 §5b precedence)."""

import pytest

from helao.hexagon.domain.dispatch_policy import (
    AwaitEndpointFree,
    AwaitPreviousActionDone,
    AwaitServerFree,
    AwaitWaitEndpointFree,
    CloseOutExperiment,
    CloseOutSequence,
    ClearIntent,
    DispatchPolicy,
    DispatchSnapshot,
    DrainForStop,
    DriverHealthWait,
    EstopClearActions,
    ExitLoop,
    ExportQueues,
    FinalizationSnapshot,
    FinishThenDispatchExperiment,
    FinishThenDispatchSequence,
    LaunchAction,
    LogQueuesEmpty,
    NoWaitProceed,
    PauseLoop,
    ProceedDispatch,
    SetLoopStopped,
    SkipClearActions,
    StopLoop,
    WaitAllActions,
    should_close_out_experiment,
    should_close_out_sequence,
    should_export,
    should_set_stopped,
)
from helao.hexagon.domain.models import (
    ActionStartCondition,
    LoopIntent,
    LoopStatus,
    OrchStatus,
)

P = DispatchPolicy()


def snap(**kw) -> DispatchSnapshot:
    base = dict(
        loop_state=LoopStatus.started,
        loop_intent=LoopIntent.none,
        n_acts=0,
        n_exps=0,
        n_seqs=0,
        na_drivers=(),
        step_thru_actions=False,
        step_thru_experiments=False,
        step_thru_sequences=False,
    )
    base.update(kw)
    return DispatchSnapshot(**base)


# --- while-cond / exit ---

def test_exit_when_not_started():
    s = P.next_step(snap(loop_state=LoopStatus.stopped, n_acts=1))
    assert isinstance(s, ExitLoop) and s.reason == "loop_state_not_started"


def test_exit_when_all_queues_empty():
    s = P.next_step(snap())
    assert isinstance(s, ExitLoop) and s.reason == "all_queues_empty"


# --- driver-health precedes ladder, non-terminal ---

def test_driver_health_precedes_ladder():
    s = P.next_step(snap(n_acts=1, na_drivers=("PSTAT",)))
    assert isinstance(s, DriverHealthWait) and s.na_drivers == ("PSTAT",)


# --- ladder precedence: estop > acts > exps > seqs > else ---

def test_ladder_estop_state_wins_over_queues():
    s = P.ladder_step(snap(loop_state=LoopStatus.estopped, n_acts=5))
    assert isinstance(s, StopLoop)


def test_ladder_estop_intent_wins():
    s = P.ladder_step(snap(loop_intent=LoopIntent.estop, n_acts=5))
    assert isinstance(s, StopLoop)


def test_ladder_precedence_order():
    assert isinstance(P.ladder_step(snap(n_acts=1, n_exps=1, n_seqs=1)), LaunchAction)
    assert isinstance(
        P.ladder_step(snap(n_exps=1, n_seqs=1)), FinishThenDispatchExperiment
    )
    assert isinstance(P.ladder_step(snap(n_seqs=1)), FinishThenDispatchSequence)
    assert isinstance(P.ladder_step(snap()), LogQueuesEmpty)


# --- pre-dispatch intent ---

@pytest.mark.parametrize(
    "intent,cls",
    [
        (LoopIntent.stop, DrainForStop),
        (LoopIntent.skip, SkipClearActions),
        (LoopIntent.estop, EstopClearActions),
        (LoopIntent.none, ProceedDispatch),
    ],
)
def test_pre_dispatch_intent(intent, cls):
    assert isinstance(P.pre_dispatch_intent_step(intent), cls)


# --- start conditions ---

def test_start_condition_mapping():
    assert isinstance(
        P.start_condition_step(ActionStartCondition.no_wait), NoWaitProceed
    )
    assert isinstance(
        P.start_condition_step(ActionStartCondition.wait_for_endpoint),
        AwaitEndpointFree,
    )
    assert isinstance(
        P.start_condition_step(ActionStartCondition.wait_for_server),
        AwaitServerFree,
    )
    assert isinstance(
        P.start_condition_step(ActionStartCondition.wait_for_orch),
        AwaitWaitEndpointFree,
    )
    assert isinstance(
        P.start_condition_step(ActionStartCondition.wait_for_previous),
        AwaitPreviousActionDone,
    )
    assert isinstance(
        P.start_condition_step(ActionStartCondition.wait_for_all), WaitAllActions
    )
    # unknown fallback -> WaitAllActions (orch.py:900-901)
    assert isinstance(P.start_condition_step(object()), WaitAllActions)


# --- step-thru sub-decision ---

def test_step_thru_actions_pause():
    p = P.evaluate_step_thru(snap(n_acts=1, step_thru_actions=True))
    assert isinstance(p, PauseLoop) and "actions" in p.reason


def test_step_thru_experiments_only_when_no_acts():
    assert P.evaluate_step_thru(
        snap(n_acts=1, n_exps=1, step_thru_experiments=True)
    ) is None
    assert isinstance(
        P.evaluate_step_thru(snap(n_exps=1, step_thru_experiments=True)), PauseLoop
    )


def test_step_thru_none():
    assert P.evaluate_step_thru(snap(n_acts=1)) is None


# --- finalization guards (the third live estop re-check lives here) ---

def test_finalization_plan_order():
    plan = P.finalization_plan(
        FinalizationSnapshot(
            n_acts=0,
            n_exps=0,
            active_experiment_present=True,
            active_sequence_present=True,
            loop_state=LoopStatus.stopped,
        )
    )
    assert [type(x) for x in plan] == [
        CloseOutExperiment,
        CloseOutSequence,
        SetLoopStopped,
        ClearIntent,
        ExportQueues,
    ]


def test_close_out_guards_skip_under_estop():
    assert should_close_out_experiment(0, True, OrchStatus.estopped) is False
    assert should_close_out_experiment(0, True, LoopStatus.stopped) is True
    assert should_close_out_experiment(1, True, LoopStatus.stopped) is False
    assert should_close_out_sequence(0, 0, True, OrchStatus.estopped) is False
    assert should_close_out_sequence(0, 0, True, LoopStatus.stopped) is True
    assert should_set_stopped(OrchStatus.estopped) is False
    assert should_set_stopped(LoopStatus.stopped) is True
    assert should_export(0, 0, 1) is True
    assert should_export(0, 0, 0) is False
```

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_dispatch_policy.py -q`
Expected: FAIL (`ModuleNotFoundError: helao.hexagon.domain.dispatch_policy`).

- [ ] **Step 2: Write `domain/dispatch_policy.py`**

Copy from `helao/core/servers/orch_dispatch.py` lines 128-482 (section banners
"1. Snapshots" through "3. DispatchPolicy (pure)" inclusive; STOP before the
"4. DispatchRunner" banner) into a new module with this exact header, then
apply ONLY the three porting-rule changes:

```python
"""Pure dispatch decision policy — the hexagon domain copy (spec §4.2.2).

Ported verbatim from helao/core/servers/orch_dispatch.py:128-482 (CARDS P5
inversion) per Q6 rewrite-with-reference. Line references in docstrings point
at the legacy orch.py the CARDS code annotated; they are retained as the
behavioral provenance. The async DispatchRunner effect shell is NOT ported —
the P1b app layer drives this policy through the reducer in
helao.hexagon.domain.orchestration.

Changes vs the source module (allowed by the porting rule, nothing else):
1. imports come from helao.hexagon.domain.models,
2. LOGGER is stdlib logging.getLogger(__name__),
3. DispatchRunner and its imports are dropped.
"""

import logging
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from helao.hexagon.domain.models import (
    ActionStartCondition,
    LoopIntent,
    LoopStatus,
    OrchStatus,
)

LOGGER = logging.getLogger(__name__)

# ... then the verbatim copied bodies:
#   DispatchSnapshot, FinalizationSnapshot,
#   ExitLoop, DriverHealthWait, StopLoop, LaunchAction,
#   FinishThenDispatchExperiment, FinishThenDispatchSequence, LogQueuesEmpty,
#   PauseLoop, DrainForStop, SkipClearActions, EstopClearActions,
#   ProceedDispatch, NoWaitProceed, AwaitEndpointFree, AwaitServerFree,
#   AwaitWaitEndpointFree, AwaitPreviousActionDone, WaitAllActions,
#   CloseOutExperiment, CloseOutSequence, SetLoopStopped, ClearIntent,
#   ExportQueues, should_close_out_experiment, should_close_out_sequence,
#   should_set_stopped, should_export, DispatchPolicy
```

The copy is mechanical: `sed -n '128,482p' helao/core/servers/orch_dispatch.py`
gives the exact body block; paste it under the header above and verify no
`helao.core.servers` or `helao.helpers` import survives (the boundary test
enforces this). Add an `__all__` listing every public name above.

- [ ] **Step 3: Run policy tests to verify they pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_dispatch_policy.py helao/hexagon/tests/test_boundaries.py -q`
Expected: PASS.

- [ ] **Step 4: Write the failing global-params tests**

Create `helao/hexagon/tests/test_global_params.py`:

```python
"""Fold-in/fold-out semantics (orch_global_params.py, byte-identical port)."""

from helao.hexagon.domain.global_params import (
    apply_from_globals,
    collect_to_globals,
)
from helao.hexagon.domain.models import Action


def test_apply_from_globals_scalar_and_list_mapping():
    params = {}
    apply_from_globals(
        params,
        {"gk1": "pk1", "gk2": ["pk2a", "pk2b"], "missing": "pk3"},
        {"gk1": 11, "gk2": 22},
        logger_ctx="action",
    )
    # scalar mapping: params[v] = global[k]; list: fan out to every name
    assert params == {"pk1": 11, "pk2a": 22, "pk2b": 22}
    # missing global key skipped, target never created
    assert "pk3" not in params


def _result_action(to_global, **identity):
    act = Action(
        action_name="a",
        action_params={"x": 1, "shared": "from_params"},
        action_output={"y": 2, "shared": "from_output"},
        to_global_params=to_global,
    )
    act.orch_key = identity.get("orch_key", "ORCH")
    act.orch_host = identity.get("orch_host", "127.0.0.1")
    act.orch_port = identity.get("orch_port", 8001)
    return act


def test_collect_to_globals_list_form_params_precede_output():
    g = {}
    collect_to_globals(
        _result_action(["x", "y", "shared", "absent"]),
        g,
        orch_key="ORCH",
        orch_host="127.0.0.1",
        orch_port=8001,
    )
    assert g == {"x": 1, "y": 2, "shared": "from_params"}


def test_collect_to_globals_dict_form_renames():
    g = {}
    collect_to_globals(
        _result_action({"x": "renamed_x", "y": "renamed_y"}),
        g,
        orch_key="ORCH",
        orch_host="127.0.0.1",
        orch_port=8001,
    )
    assert g == {"renamed_x": 1, "renamed_y": 2}


def test_collect_to_globals_identity_guard_blocks_foreign_orch():
    g = {}
    collect_to_globals(
        _result_action(["x"], orch_key="OTHER"),
        g,
        orch_key="ORCH",
        orch_host="127.0.0.1",
        orch_port=8001,
    )
    assert g == {}


def test_collect_to_globals_port_compare_is_int():
    g = {}
    collect_to_globals(
        _result_action(["x"], orch_port="8001"),  # str port on the action
        g,
        orch_key="ORCH",
        orch_host="127.0.0.1",
        orch_port=8001,
    )
    assert g == {"x": 1}  # int(...) comparison verbatim from legacy
```

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_global_params.py -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 5: Write `domain/global_params.py`**

Copy `helao/core/servers/orch_global_params.py` in full with this header swap
(the two function bodies are byte-identical to the source; only the module
docstring and LOGGER line change):

```python
"""Pure global-params fold functions — hexagon domain copy (spec §4.2.2).

Ported byte-identically from helao/core/servers/orch_global_params.py
(CARDS P5 Stage S1) per Q6. Behavior including log wording, list-vs-dict
to_global_params handling, and key iteration order is preserved. The only
change: LOGGER is stdlib logging (helao.helpers.helao_logging is outside the
domain allow-list).
"""

import logging

LOGGER = logging.getLogger(__name__)


# then apply_from_globals(...) and collect_to_globals(...) verbatim from the
# source module (signatures:
#   apply_from_globals(params: dict, from_global_map: dict,
#                      global_params: dict, *, logger_ctx: str) -> None
#   collect_to_globals(result_action, global_params: dict, *,
#                      orch_key: str, orch_host: str, orch_port) -> None )
```

- [ ] **Step 6: Run tests + commit**

Run: `conda run -n helao python -m pytest helao/hexagon/tests -q`
Expected: all pass.

```bash
black helao/hexagon
git add helao/hexagon
git commit -m "feat(hexagon): port pure DispatchPolicy + global-param folds into domain"
```

---

### Task 7: Status fold + §4.2.4 side-effect checklist as commands

**Files:**
- Create: `helao/hexagon/domain/status_fold.py`
- Test: `helao/hexagon/tests/test_status_fold.py`

**Interfaces:**
- Consumes: `GlobalStatusModel`, `ActionServerModel`, `MachineModel`, `HloStatus`, `OrchStatus`, `LoopStatus` from `helao.hexagon.domain.models`.
- Produces: command dataclasses `RegisterHistoryEntry(action_uuid)`, `PushLiveBuffer(items)`, `WakeDispatchLoop()`, `TriggerEstopFromStatus(reason)`, `SetOrchStateError()`; function `fold_status(gsm, asm, *, loop_started: bool, last_dispatched_action_uuid) -> Tuple[OrchStatus, Tuple[object, ...]]`. The reducer (Task 8) and P1b ingestion runner consume these.

The §4.2.4 checklist is normative; this module encodes items 1, 3, 4, 5 as
emitted commands / derived state, and items 2 and 6 as documented + tested
model behavior (they live on enqueue/dispatch paths and inside
`GlobalStatusModel._sort_status` respectively).

- [ ] **Step 1: Write the failing tests**

Create `helao/hexagon/tests/test_status_fold.py`:

```python
"""Status-ingestion fold + the §4.2.4 side-effect checklist (core-01 §4)."""

from uuid import uuid4

from helao.hexagon.domain.status_fold import (
    PushLiveBuffer,
    RegisterHistoryEntry,
    SetOrchStateError,
    TriggerEstopFromStatus,
    WakeDispatchLoop,
    fold_status,
)
from helao.hexagon.domain.models import (
    Action,
    ActionServerModel,
    EndpointModel,
    GlobalStatusModel,
    HloStatus,
    MachineModel,
    OrchStatus,
)

ORCH_ID = MachineModel(server_name="ORCH", machine_name="orchbox")


def _asm(action: Action, endpoint: str, finished: bool) -> ActionServerModel:
    asm = ActionServerModel(
        action_server=action.action_server,
        endpoints={endpoint: EndpointModel(endpoint_name=endpoint)},
        last_action_uuid=action.action_uuid,
    )
    if finished:
        asm.endpoints[endpoint].active_dict = {}
        asm.endpoints[endpoint].nonactive_dict = {
            HloStatus.finished: {action.action_uuid: action}
        }
    else:
        asm.endpoints[endpoint].active_dict = {action.action_uuid: action}
    return asm


def _action(status, orch=ORCH_ID) -> Action:
    act = Action(action_name="acquire")
    act.action_uuid = uuid4()
    act.action_server = MachineModel(server_name="SIM", machine_name="simbox")
    act.orchestrator = orch
    act.action_status = list(status)
    return act


def _gsm() -> GlobalStatusModel:
    return GlobalStatusModel(orchestrator=ORCH_ID)


def test_fold_always_wakes_dispatch_loop():
    gsm = _gsm()
    act = _action([HloStatus.active])
    _, cmds = fold_status(
        gsm, _asm(act, "acquire", finished=False),
        loop_started=False, last_dispatched_action_uuid=None,
    )
    assert any(isinstance(c, WakeDispatchLoop) for c in cmds)  # checklist #5


def test_history_registered_on_last_action_uuid_match():
    gsm = _gsm()
    act = _action([HloStatus.finished])
    asm = _asm(act, "acquire", finished=True)
    _, cmds = fold_status(
        gsm, asm, loop_started=True,
        last_dispatched_action_uuid=act.action_uuid,
    )
    hits = [c for c in cmds if isinstance(c, RegisterHistoryEntry)]
    assert hits and hits[0].action_uuid == act.action_uuid  # checklist #1


def test_newly_nonactive_go_to_live_buffer():
    gsm = _gsm()
    act = _action([HloStatus.finished])
    _, cmds = fold_status(
        gsm, _asm(act, "acquire", finished=True),
        loop_started=True, last_dispatched_action_uuid=None,
    )
    lb = [c for c in cmds if isinstance(c, PushLiveBuffer)]
    assert lb and act.action_uuid in dict(lb[0].items)  # checklist #3


def test_orch_state_derivation_idle_vs_busy():
    gsm = _gsm()
    active = _action([HloStatus.active])
    state, _ = fold_status(
        gsm, _asm(active, "acquire", finished=False),
        loop_started=True, last_dispatched_action_uuid=None,
    )
    assert state == OrchStatus.busy  # checklist #4
    done = _action([HloStatus.finished])
    gsm2 = _gsm()
    state2, _ = fold_status(
        gsm2, _asm(done, "acquire", finished=True),
        loop_started=True, last_dispatched_action_uuid=None,
    )
    assert state2 == OrchStatus.idle


def test_estopped_uuid_triggers_estop_only_when_loop_started():
    est = _action([HloStatus.finished, HloStatus.estopped])
    _, cmds_started = fold_status(
        _gsm(), _asm(est, "acquire", finished=True),
        loop_started=True, last_dispatched_action_uuid=None,
    )
    assert any(isinstance(c, TriggerEstopFromStatus) for c in cmds_started)
    _, cmds_stopped = fold_status(
        _gsm(), _asm(est, "acquire", finished=True),
        loop_started=False, last_dispatched_action_uuid=None,
    )
    assert not any(isinstance(c, TriggerEstopFromStatus) for c in cmds_stopped)


def test_errored_uuid_sets_error_state_when_started():
    err = _action([HloStatus.finished, HloStatus.errored])
    state, cmds = fold_status(
        _gsm(), _asm(err, "acquire", finished=True),
        loop_started=True, last_dispatched_action_uuid=None,
    )
    assert any(isinstance(c, SetOrchStateError) for c in cmds)
    assert state == OrchStatus.error


def test_identity_rule_foreign_orchestrator_not_folded_into_own_dicts():
    """Checklist #6 / MINOR-8: finished actions are mirrored into the
    orch-level dicts only when statusmodel.orchestrator == gsm.orchestrator."""
    gsm = _gsm()
    foreign = _action(
        [HloStatus.finished],
        orch=MachineModel(server_name="OTHER", machine_name="elsewhere"),
    )
    fold_status(
        gsm, _asm(foreign, "acquire", finished=True),
        loop_started=True, last_dispatched_action_uuid=None,
    )
    assert foreign.action_uuid not in gsm.nonactive_dict.get(
        HloStatus.finished, {}
    )
```

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_status_fold.py -q`
Expected: FAIL (`ModuleNotFoundError`).

NOTE for the implementer: the `EndpointModel`/`ActionServerModel`/`GlobalStatusModel`
constructor kwargs above are written from core-06's field survey; if pydantic
rejects a kwarg (e.g. `endpoint_name` not a field, or `GlobalStatusModel`
requiring more), check `helao/core/models/server.py` and build the fixtures
with the real field names — the assertions, not the fixture spelling, are the
contract.

- [ ] **Step 2: Write `domain/status_fold.py`**

```python
"""Status ingestion fold + the normative §4.2.4 side-effect checklist.

Legacy behavior (orch_status_sync.StatusIngester.update_status, entirely
inside orch.aiolock — core-01 §4):
1. history registration on last_action_uuid match (unblocks the dispatch
   loop's history poll)                         -> RegisterHistoryEntry
2. register_obj_uuid/register_action_uuid on every enqueue/dispatch/finish
   path                                          -> NOT here; lives on the
   queue/dispatch paths (queue_policy + P1b runner); tested at those sites.
3. newly-nonactive (uuid, status) tuples         -> PushLiveBuffer
4. orch_state derivation (estopped-in-finished => estop; errored => error;
   empty active_dict => idle; else busy)         -> returned OrchStatus +
                                                    SetOrchStateError command
5. interrupt_q wake of the dispatch loop         -> WakeDispatchLoop
6. status-fold identity rule: finished actions are mirrored/removed only when
   statusmodel.orchestrator == gsm.orchestrator  -> inside the reused
   GlobalStatusModel._sort_status (D8); pinned by
   test_identity_rule_foreign_orchestrator_not_folded_into_own_dicts.

``fold_status`` mutates ``gsm`` in place (the model's own pure in-memory
fold, update_global_with_acts) and returns the derived orch_state plus the
ordered command tuple. It performs NO I/O; the P1b ingestion runner executes
the commands under the ingestion lock.
"""

from dataclasses import dataclass
from typing import Optional, Tuple
from uuid import UUID

from helao.hexagon.domain.models import (
    ActionServerModel,
    GlobalStatusModel,
    HloStatus,
    OrchStatus,
)

__all__ = [
    "PushLiveBuffer",
    "RegisterHistoryEntry",
    "SetOrchStateError",
    "TriggerEstopFromStatus",
    "WakeDispatchLoop",
    "fold_status",
]


@dataclass(frozen=True)
class RegisterHistoryEntry:
    """Checklist #1: rich history entry for the just-finished dispatched act."""

    action_uuid: UUID


@dataclass(frozen=True)
class PushLiveBuffer:
    """Checklist #3: newly-nonactive (uuid, status-tuple) pairs -> live buffer."""

    items: Tuple[Tuple[UUID, Tuple[str, ...]], ...]


@dataclass(frozen=True)
class WakeDispatchLoop:
    """Checklist #5: interrupt_q.put(globalstatusmodel)."""


@dataclass(frozen=True)
class TriggerEstopFromStatus:
    """Estopped uuid found in finished while loop started (core-01 T9 source).
    The runner feeds this back into the reducer as EstoppedUuidIngested."""

    reason: str


@dataclass(frozen=True)
class SetOrchStateError:
    """Errored uuids found while loop started (orch_state = error)."""


def fold_status(
    gsm: GlobalStatusModel,
    asm: ActionServerModel,
    *,
    loop_started: bool,
    last_dispatched_action_uuid: Optional[UUID],
) -> Tuple[OrchStatus, Tuple[object, ...]]:
    """Fold one pushed ActionServerModel into gsm; return (orch_state, cmds)."""
    commands: list = []

    # -- the model's own pure fold (D8): merge + _sort_status --------------
    newly_nonactive = gsm.update_global_with_acts(actionservermodel=asm)
    if newly_nonactive:
        commands.append(
            PushLiveBuffer(
                items=tuple(
                    (uuid, tuple(str(s) for s in statuses))
                    for uuid, statuses in newly_nonactive
                )
            )
        )

    # -- checklist #1: history registration on last_action_uuid match ------
    if (
        last_dispatched_action_uuid is not None
        and asm.last_action_uuid == last_dispatched_action_uuid
    ):
        commands.append(RegisterHistoryEntry(action_uuid=asm.last_action_uuid))

    # -- checklist #4 + estop/error reactions (core-01 §4 step 3) ----------
    estopped = gsm.find_hlostatus_in_finished(hlostatus=HloStatus.estopped)
    errored = gsm.find_hlostatus_in_finished(hlostatus=HloStatus.errored)
    if estopped and loop_started:
        commands.append(
            TriggerEstopFromStatus(
                reason=f"estopped uuids in finished: {sorted(map(str, estopped))}"
            )
        )
        orch_state = OrchStatus.estopped
    elif errored and loop_started:
        commands.append(SetOrchStateError())
        orch_state = OrchStatus.error
    elif not gsm.active_dict:
        orch_state = OrchStatus.idle
    else:
        orch_state = OrchStatus.busy

    # -- checklist #5: always wake the dispatch loop -----------------------
    commands.append(WakeDispatchLoop())
    return orch_state, tuple(commands)
```

NOTE for the implementer: verify the exact return shape of
`GlobalStatusModel.update_global_with_acts` (list of `(uuid, status)` tuples
per core-01 §4) and the signature/return of `find_hlostatus_in_finished`
(returns a dict `uuid -> Action` per orch_queues usage — adjust the
`sorted(map(str, ...))` and truthiness accordingly) against
`helao/core/models/server.py`. Match the real API; keep the command semantics.

- [ ] **Step 3: Run tests to verify they pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_status_fold.py -q`
Expected: PASS.

- [ ] **Step 4: Full suite + commit**

Run: `conda run -n helao python -m pytest helao/hexagon/tests -q`
Expected: all pass.

```bash
black helao/hexagon
git add helao/hexagon
git commit -m "feat(hexagon): status fold + §4.2.4 side-effect checklist commands"
```

---

### Task 8: Orchestration reducer FSM — `step(state, event) -> (state, commands)`

**Files:**
- Create: `helao/hexagon/domain/orchestration.py`
- Test: `helao/hexagon/tests/test_orchestration.py`

**Interfaces:**
- Consumes: `DispatchPolicy`, `DispatchSnapshot`, guards from Task 6; enums from `helao.hexagon.domain.models`.
- Produces: `OrchestrationState` (frozen dataclass), the event union (`StartRequested`, `StopRequested`, `SkipRequested`, `EstopRequested`, `ClearEstopRequested`, `ClearErrorRequested`, `DispatchFailed`, `PlateGateFailed`, `HeartbeatFailed`, `DriverHealthUnrecovered`, `ActionResultErrored`, `EstoppedUuidIngested`, `ErroredUuidIngested`, `StatusChanged`, `UncaughtLoopException`, `LoopIterate`), the command union (`CreateDispatchLoopTask`, `RefuseStart`, `DispatchHeadAction`, `FinishThenDispatchExperimentCmd`, `FinishThenDispatchSequenceCmd`, `RetryDriverHealth`, `WaitAllActionsIdle`, `RequeueHeadAction`, `ClearActionQueue`, `SetStopMessage`, `AlertOperator`, `EstopFanout`, `ClearActiveRunId`, `FinishActiveEstopped`, `CloseOutExperimentCmd`, `CloseOutSequenceCmd`, `ExportQueuesCmd`, `ClearEstoppedFromFinished`, `ClearErroredFromFinished`, `ReleaseServersEstop`, `InterruptWake`), and `step(state: OrchestrationState, event) -> Tuple[OrchestrationState, Tuple[command, ...]]`. The P1b app loop is the sole effect executor.

**Design rules (from core-01 §5/§7/§8 + spec §4.2.2 — encode, don't improvise):**
- Transition table T1–T13 is the contract; each transition gets at least one test.
- The **three live estop re-checks** are made explicit as command guards: `DispatchHeadAction`, `FinishThenDispatchExperimentCmd`, `FinishThenDispatchSequenceCmd`, `CloseOutExperimentCmd`, `CloseOutSequenceCmd` all carry `requires_live_estop_recheck=True`; the P1b effect runner MUST re-read live state before executing them (or serialize estop with the loop — P1b picks one and tests both races, per spec §4.2.2). P1a's obligation is that the guard is present and asserted.
- Dispatch transport failure ⇒ graceful stop + head-requeue, NOT estop (T12); action `error_code != none` in a result ⇒ escalates to estop (T9); skip clears only `action_dq` (T6); plain stop with empty queues still runs CloseOut commands (T4 finalization).
- Estop command order is exactly `estop_loop`'s sequence: state flip → `ClearActiveRunId` → `EstopFanout(switch=False)` → intent cleared → `FinishActiveEstopped` → `SetStopMessage` → `AlertOperator` (core-01 §7).

- [ ] **Step 1: Write the failing transition tests**

Create `helao/hexagon/tests/test_orchestration.py`:

```python
"""Reducer FSM transition-table tests (core-01 §5a T1-T13 + ladder wiring)."""

import pytest

from helao.hexagon.domain import orchestration as fsm
from helao.hexagon.domain.models import LoopIntent, LoopStatus, OrchStatus


def st(**kw) -> fsm.OrchestrationState:
    base = dict(
        loop_state=LoopStatus.stopped,
        loop_intent=LoopIntent.none,
        orch_state=OrchStatus.idle,
        n_seqs=0,
        n_exps=0,
        n_acts=0,
        active_experiment_present=False,
        active_sequence_present=False,
        na_drivers=(),
        step_thru_actions=False,
        step_thru_experiments=False,
        step_thru_sequences=False,
    )
    base.update(kw)
    return fsm.OrchestrationState(**base)


def kinds(cmds):
    return [type(c) for c in cmds]


# --- T1/T2/T3: start ---

def test_t1_start_with_queued_work_starts_loop():
    s, cmds = fsm.step(st(n_seqs=1), fsm.StartRequested())
    assert s.loop_state == LoopStatus.started
    assert kinds(cmds) == [fsm.CreateDispatchLoopTask]


def test_t1_start_with_active_sequence_only():
    s, cmds = fsm.step(st(active_sequence_present=True), fsm.StartRequested())
    assert s.loop_state == LoopStatus.started


def test_t2_start_with_everything_empty_refuses():
    s, cmds = fsm.step(st(), fsm.StartRequested())
    assert s.loop_state == LoopStatus.stopped
    assert kinds(cmds) == [fsm.RefuseStart]
    assert "empty" in cmds[0].reason


def test_t3_start_under_estop_refuses():
    s, cmds = fsm.step(st(loop_state=LoopStatus.estopped, n_acts=1),
                       fsm.StartRequested())
    assert s.loop_state == LoopStatus.estopped
    assert kinds(cmds) == [fsm.RefuseStart]
    assert "E-STOP" in cmds[0].reason


def test_start_while_started_is_noop():
    s0 = st(loop_state=LoopStatus.started, n_acts=1)
    s, cmds = fsm.step(s0, fsm.StartRequested())
    assert s == s0 and cmds == ()


# --- intents ---

def test_stop_sets_intent():
    s, cmds = fsm.step(st(loop_state=LoopStatus.started, n_acts=1),
                       fsm.StopRequested())
    assert s.loop_intent == LoopIntent.stop and cmds == ()


def test_skip_sets_intent():
    s, _ = fsm.step(st(loop_state=LoopStatus.started, n_acts=1),
                    fsm.SkipRequested())
    assert s.loop_intent == LoopIntent.skip


# --- T9: estop escalation (all four sources) ---

@pytest.mark.parametrize(
    "event",
    [
        fsm.EstopRequested(reason="ui"),
        fsm.ActionResultErrored(reason="bad result"),
        fsm.EstoppedUuidIngested(reason="status"),
        fsm.UncaughtLoopException(reason="boom"),
    ],
)
def test_t9_estop_transition_state_and_command_order(event):
    s, cmds = fsm.step(st(loop_state=LoopStatus.started, n_acts=2), event)
    assert s.loop_state == LoopStatus.estopped
    assert s.loop_intent == LoopIntent.none
    assert kinds(cmds) == [
        fsm.ClearActiveRunId,
        fsm.EstopFanout,
        fsm.FinishActiveEstopped,
        fsm.SetStopMessage,
        fsm.AlertOperator,
    ]
    fanout = cmds[1]
    assert fanout.switch is False


def test_estopped_uuid_when_loop_not_started_is_noop():
    s0 = st(loop_state=LoopStatus.stopped)
    s, cmds = fsm.step(s0, fsm.EstoppedUuidIngested(reason="late push"))
    assert s == s0 and cmds == ()


# --- T10/T11: clears ---

def test_t10_clear_estop():
    s, cmds = fsm.step(st(loop_state=LoopStatus.estopped),
                       fsm.ClearEstopRequested())
    assert s.loop_state == LoopStatus.stopped
    assert kinds(cmds) == [
        fsm.ClearEstoppedFromFinished,
        fsm.ReleaseServersEstop,
        fsm.InterruptWake,
    ]
    assert cmds[2].message == "cleared_estop"


def test_t10_clear_estop_only_from_estopped():
    s0 = st(loop_state=LoopStatus.started, n_acts=1)
    s, cmds = fsm.step(s0, fsm.ClearEstopRequested())
    assert s == s0 and cmds == ()


def test_t11_clear_error_leaves_loop_state():
    s0 = st(loop_state=LoopStatus.stopped, orch_state=OrchStatus.error)
    s, cmds = fsm.step(s0, fsm.ClearErrorRequested())
    assert s.loop_state == LoopStatus.stopped
    assert kinds(cmds) == [fsm.ClearErroredFromFinished, fsm.InterruptWake]
    assert cmds[1].message == "cleared_errored"


# --- T12: pause-class failures (never estop) ---

def test_t12_dispatch_failure_pauses_and_requeues_head():
    s, cmds = fsm.step(st(loop_state=LoopStatus.started, n_acts=1),
                       fsm.DispatchFailed(message="server down"))
    assert s.loop_state == LoopStatus.started  # drains via T5, not inline
    assert s.loop_intent == LoopIntent.stop
    assert kinds(cmds) == [fsm.SetStopMessage, fsm.RequeueHeadAction]


def test_t12_plate_gate_sets_stopped_inline():
    s, cmds = fsm.step(st(loop_state=LoopStatus.started, n_exps=1),
                       fsm.PlateGateFailed(message="no access"))
    assert s.loop_state == LoopStatus.stopped
    assert kinds(cmds) == [fsm.SetStopMessage]


def test_t12_heartbeat_failure_pauses_with_alert():
    s, cmds = fsm.step(st(loop_state=LoopStatus.started, n_acts=1),
                       fsm.HeartbeatFailed(message="endpoint gone"))
    assert s.loop_intent == LoopIntent.stop
    assert kinds(cmds) == [fsm.SetStopMessage, fsm.AlertOperator]


def test_t12_driver_health_unrecovered_pauses():
    s, cmds = fsm.step(st(loop_state=LoopStatus.started, n_acts=1),
                       fsm.DriverHealthUnrecovered(na_drivers=("PSTAT",)))
    assert s.loop_intent == LoopIntent.stop
    assert kinds(cmds) == [fsm.SetStopMessage]


# --- status-derived orch_state ---

def test_errored_uuid_sets_error_when_started():
    s, _ = fsm.step(st(loop_state=LoopStatus.started, n_acts=1),
                    fsm.ErroredUuidIngested())
    assert s.orch_state == OrchStatus.error


def test_status_changed_busy_idle():
    s, _ = fsm.step(st(loop_state=LoopStatus.started, n_acts=1),
                    fsm.StatusChanged(any_active=True))
    assert s.orch_state == OrchStatus.busy
    s2, _ = fsm.step(st(loop_state=LoopStatus.started, n_acts=1),
                     fsm.StatusChanged(any_active=False))
    assert s2.orch_state == OrchStatus.idle


# --- LoopIterate: ladder wiring ---

def test_iterate_dispatches_head_action_with_live_recheck_guard():
    s, cmds = fsm.step(st(loop_state=LoopStatus.started, n_acts=1),
                       fsm.LoopIterate())
    assert kinds(cmds) == [fsm.DispatchHeadAction]
    assert cmds[0].requires_live_estop_recheck is True


def test_iterate_finish_then_dispatch_experiment_guarded():
    s, cmds = fsm.step(st(loop_state=LoopStatus.started, n_exps=1),
                       fsm.LoopIterate())
    assert kinds(cmds) == [fsm.FinishThenDispatchExperimentCmd]
    assert cmds[0].requires_live_estop_recheck is True


def test_iterate_finish_then_dispatch_sequence_guarded():
    s, cmds = fsm.step(st(loop_state=LoopStatus.started, n_seqs=1),
                       fsm.LoopIterate())
    assert kinds(cmds) == [fsm.FinishThenDispatchSequenceCmd]
    assert cmds[0].requires_live_estop_recheck is True


def test_iterate_driver_health_is_nonterminal_command():
    s, cmds = fsm.step(
        st(loop_state=LoopStatus.started, n_acts=1, na_drivers=("PSTAT",)),
        fsm.LoopIterate(),
    )
    assert kinds(cmds) == [fsm.RetryDriverHealth]
    assert cmds[0].na_drivers == ("PSTAT",)


# --- T5/T6/T7: pre-dispatch intents on LaunchAction ---

def test_t5_drain_for_stop():
    s, cmds = fsm.step(
        st(loop_state=LoopStatus.started, n_acts=1, loop_intent=LoopIntent.stop),
        fsm.LoopIterate(),
    )
    assert s.loop_state == LoopStatus.stopped
    assert s.loop_intent == LoopIntent.none
    assert kinds(cmds) == [fsm.WaitAllActionsIdle]


def test_t6_skip_clears_only_actions():
    s, cmds = fsm.step(
        st(loop_state=LoopStatus.started, n_acts=3, n_exps=2,
           loop_intent=LoopIntent.skip),
        fsm.LoopIterate(),
    )
    assert s.loop_state == LoopStatus.started  # falls to exp dispatch next iter
    assert s.loop_intent == LoopIntent.none
    assert kinds(cmds) == [fsm.ClearActionQueue]


def test_t7_estop_intent_clears_actions_and_estops_loop_state():
    s, cmds = fsm.step(
        st(loop_state=LoopStatus.started, n_acts=3,
           loop_intent=LoopIntent.estop),
        fsm.LoopIterate(),
    )
    # ladder StopLoop wins first (estop intent) -> intend_stop; the
    # EstopClearActions path is reached when intent survives to LaunchAction.
    # Encode exactly what the reducer does; see implementation note below.
    assert s.loop_state in (LoopStatus.started, LoopStatus.estopped)


# --- T4: exit + finalization (plain stop with empty queues closes out) ---

def test_t4_exit_finalization_closes_out_and_stops():
    s, cmds = fsm.step(
        st(loop_state=LoopStatus.started, active_experiment_present=True,
           active_sequence_present=True),
        fsm.LoopIterate(),
    )
    assert s.loop_state == LoopStatus.stopped
    assert s.loop_intent == LoopIntent.none
    assert kinds(cmds) == [fsm.CloseOutExperimentCmd, fsm.CloseOutSequenceCmd]
    assert all(c.requires_live_estop_recheck for c in cmds)


def test_t4_exit_under_estop_keeps_estopped_and_skips_closeout():
    s, cmds = fsm.step(
        st(loop_state=LoopStatus.estopped, active_experiment_present=True,
           active_sequence_present=True),
        fsm.LoopIterate(),
    )
    assert s.loop_state == LoopStatus.estopped  # SetLoopStopped skipped (Q2)
    assert kinds(cmds) == []  # estop_finish_active is the sole finalizer


def test_t4_exit_with_leftover_queues_exports():
    s, cmds = fsm.step(
        st(loop_state=LoopStatus.stopped, n_seqs=2), fsm.LoopIterate()
    )
    assert fsm.ExportQueuesCmd in kinds(cmds)
```

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_orchestration.py -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 2: Write `domain/orchestration.py`**

```python
"""Orchestration reducer FSM (spec §4.2.2, KEEP #2): pure
``step(state, event) -> (state, commands)``.

Encodes core-01's loop-state transition table T1-T13 and drives the ported
DispatchPolicy ladder for LoopIterate events. The P1b app layer owns the
single long-lived Event-parked dispatch loop that feeds LoopIterate events in
and executes the returned commands; this module never awaits, never touches a
queue object, never performs I/O.

THE THREE LIVE ESTOP RE-CHECKS (core-01 §8): a concurrent estop can land
between this reducer's decision and the runner's effect. Commands that legacy
guards re-check live carry ``requires_live_estop_recheck=True``:
- DispatchHeadAction        (in-lock re-check inside the dispatch lock)
- FinishThenDispatch*Cmd    (re-check at the top of the effect)
- CloseOut*Cmd              (finalization guard ``loop_state != estopped`` so
                             estop_finish_active stays the SOLE finalizer)
The P1b effect runner must re-read live state before executing them, or
serialize estop with the loop — and test both races either way (spec
§4.2.2); P1a asserts the guards exist.
"""

from dataclasses import dataclass, replace
from typing import Tuple, Union

from helao.hexagon.domain.dispatch_policy import (
    DispatchPolicy,
    DispatchSnapshot,
    DrainForStop,
    DriverHealthWait,
    EstopClearActions,
    ExitLoop,
    FinishThenDispatchExperiment,
    FinishThenDispatchSequence,
    LaunchAction,
    LogQueuesEmpty,
    ProceedDispatch,
    SkipClearActions,
    StopLoop,
    should_close_out_experiment,
    should_close_out_sequence,
    should_export,
    should_set_stopped,
)
from helao.hexagon.domain.models import LoopIntent, LoopStatus, OrchStatus

_POLICY = DispatchPolicy()


# ===========================================================================
# State
# ===========================================================================


@dataclass(frozen=True)
class OrchestrationState:
    loop_state: LoopStatus = LoopStatus.stopped
    loop_intent: LoopIntent = LoopIntent.none
    orch_state: OrchStatus = OrchStatus.idle
    n_seqs: int = 0
    n_exps: int = 0
    n_acts: int = 0
    active_experiment_present: bool = False
    active_sequence_present: bool = False
    na_drivers: Tuple[str, ...] = ()
    step_thru_actions: bool = False
    step_thru_experiments: bool = False
    step_thru_sequences: bool = False

    def snapshot(self) -> DispatchSnapshot:
        return DispatchSnapshot(
            loop_state=self.loop_state,
            loop_intent=self.loop_intent,
            n_acts=self.n_acts,
            n_exps=self.n_exps,
            n_seqs=self.n_seqs,
            na_drivers=self.na_drivers,
            step_thru_actions=self.step_thru_actions,
            step_thru_experiments=self.step_thru_experiments,
            step_thru_sequences=self.step_thru_sequences,
        )


# ===========================================================================
# Events
# ===========================================================================


@dataclass(frozen=True)
class StartRequested:
    """POST /start (T1/T2/T3)."""


@dataclass(frozen=True)
class StopRequested:
    """POST /stop -> intend_stop (drains via T5)."""


@dataclass(frozen=True)
class SkipRequested:
    """POST /skip_experiment -> intend_skip (T6)."""


@dataclass(frozen=True)
class EstopRequested:
    """POST /estop_orch (T9)."""

    reason: str = ""


@dataclass(frozen=True)
class ClearEstopRequested:
    """POST /clear_estop (T10)."""


@dataclass(frozen=True)
class ClearErrorRequested:
    """POST /clear_error (T11)."""


@dataclass(frozen=True)
class DispatchFailed:
    """Transport failure / None result (T12: pause + head-requeue, NOT estop)."""

    message: str


@dataclass(frozen=True)
class PlateGateFailed:
    """Plate verification gate (T12; sets loop_state=stopped inline)."""

    message: str


@dataclass(frozen=True)
class HeartbeatFailed:
    """active_action_monitor probe failure (T12 + alert)."""

    message: str


@dataclass(frozen=True)
class DriverHealthUnrecovered:
    """DriverHealthWait retries exhausted, still unknown (T12)."""

    na_drivers: Tuple[str, ...]


@dataclass(frozen=True)
class ActionResultErrored:
    """Dispatch result carried error_code != none — ESCALATES to estop (T9)."""

    reason: str


@dataclass(frozen=True)
class EstoppedUuidIngested:
    """Status fold found estopped uuids in finished (T9, guard: started)."""

    reason: str


@dataclass(frozen=True)
class ErroredUuidIngested:
    """Status fold found errored uuids (orch_state=error while started)."""


@dataclass(frozen=True)
class StatusChanged:
    """Generic ingestion outcome (orch_state busy/idle derivation)."""

    any_active: bool


@dataclass(frozen=True)
class UncaughtLoopException:
    """run() caught an exception (T13 -> estop)."""

    reason: str


@dataclass(frozen=True)
class LoopIterate:
    """Top-of-iteration tick from the app loop -> ladder decision."""


Event = Union[
    StartRequested, StopRequested, SkipRequested, EstopRequested,
    ClearEstopRequested, ClearErrorRequested, DispatchFailed, PlateGateFailed,
    HeartbeatFailed, DriverHealthUnrecovered, ActionResultErrored,
    EstoppedUuidIngested, ErroredUuidIngested, StatusChanged,
    UncaughtLoopException, LoopIterate,
]


# ===========================================================================
# Commands (executed by the P1b app-layer runner; NEVER by the domain)
# ===========================================================================


@dataclass(frozen=True)
class CreateDispatchLoopTask:
    """start_loop(): create dispatch_loop_task (T1)."""


@dataclass(frozen=True)
class RefuseStart:
    reason: str


@dataclass(frozen=True)
class DispatchHeadAction:
    """popleft + start-condition wait + locked dispatch + result fold.
    Live re-check #1 happens inside the dispatch lock."""

    requires_live_estop_recheck: bool = True


@dataclass(frozen=True)
class FinishThenDispatchExperimentCmd:
    """finish_active_experiment() then dispatch_experiment().
    Live re-check #2 at the top of the effect."""

    requires_live_estop_recheck: bool = True


@dataclass(frozen=True)
class FinishThenDispatchSequenceCmd:
    requires_live_estop_recheck: bool = True


@dataclass(frozen=True)
class RetryDriverHealth:
    """Re-read status_summary <=5 x 5 s; feed DriverHealthUnrecovered back on
    exhaustion; then FALL THROUGH to the ladder in the same iteration (no
    continue — re-asking next_step would livelock)."""

    na_drivers: Tuple[str, ...]


@dataclass(frozen=True)
class WaitAllActionsIdle:
    """DrainForStop: wait actions_idle before the loop parks (T5)."""


@dataclass(frozen=True)
class RequeueHeadAction:
    """action_dq.insert(0, A) — head re-insert of the popped action."""


@dataclass(frozen=True)
class ClearActionQueue:
    """action_dq.clear() — skip/estop intents clear ONLY actions (T6/T7)."""


@dataclass(frozen=True)
class SetStopMessage:
    message: str


@dataclass(frozen=True)
class AlertOperator:
    message: str


@dataclass(frozen=True)
class EstopFanout:
    """Fan a minimal estop Action (params={'switch': switch}) to every server
    in server_dict; servers finalize their own in-flight actions; NO
    fabricated placeholder artifacts (post-bd8b83ab semantics)."""

    switch: bool = False


@dataclass(frozen=True)
class ClearActiveRunId:
    """active_run_id = None."""


@dataclass(frozen=True)
class FinishActiveEstopped:
    """estop_finish_active(): exp then seq, [finished, estopped] terminal
    status, deferred child-dir-aware promotion. The SOLE finalizer under
    estop."""


@dataclass(frozen=True)
class CloseOutExperimentCmd:
    """finish_active_experiment() in finalization. Live re-check #3: the
    runner re-checks should_close_out_experiment against LIVE loop_state."""

    requires_live_estop_recheck: bool = True


@dataclass(frozen=True)
class CloseOutSequenceCmd:
    requires_live_estop_recheck: bool = True


@dataclass(frozen=True)
class ExportQueuesCmd:
    timestamped: bool = True


@dataclass(frozen=True)
class ClearEstoppedFromFinished:
    """globalstatusmodel.clear_in_finished(estopped) (T10)."""


@dataclass(frozen=True)
class ClearErroredFromFinished:
    """clear_in_finished(errored) (T11)."""


@dataclass(frozen=True)
class ReleaseServersEstop:
    """estop_actions(switch=False) on clear_estop (T10)."""


@dataclass(frozen=True)
class InterruptWake:
    message: str


Command = Union[
    CreateDispatchLoopTask, RefuseStart, DispatchHeadAction,
    FinishThenDispatchExperimentCmd, FinishThenDispatchSequenceCmd,
    RetryDriverHealth, WaitAllActionsIdle, RequeueHeadAction,
    ClearActionQueue, SetStopMessage, AlertOperator, EstopFanout,
    ClearActiveRunId, FinishActiveEstopped, CloseOutExperimentCmd,
    CloseOutSequenceCmd, ExportQueuesCmd, ClearEstoppedFromFinished,
    ClearErroredFromFinished, ReleaseServersEstop, InterruptWake,
]

StepResult = Tuple[OrchestrationState, Tuple[Command, ...]]


# ===========================================================================
# Reducer
# ===========================================================================


def _estop_transition(state: OrchestrationState, reason: str) -> StepResult:
    """T9/T13: the estop_loop sequence (core-01 §7), exact command order."""
    new = replace(
        state,
        loop_state=LoopStatus.estopped,
        loop_intent=LoopIntent.none,
        orch_state=OrchStatus.estopped,
    )
    return new, (
        ClearActiveRunId(),
        EstopFanout(switch=False),
        FinishActiveEstopped(),
        SetStopMessage(message=reason),
        AlertOperator(message=reason),
    )


def _finalization(state: OrchestrationState) -> StepResult:
    """T4 / ExitLoop: CloseOutExperiment?, CloseOutSequence?, SetLoopStopped
    (skipped if estopped, Q2), ClearIntent, ExportQueues?."""
    cmds: list = []
    if should_close_out_experiment(
        state.n_acts, state.active_experiment_present, state.loop_state
    ):
        cmds.append(CloseOutExperimentCmd())
    if should_close_out_sequence(
        state.n_exps, state.n_acts, state.active_sequence_present,
        state.loop_state,
    ):
        cmds.append(CloseOutSequenceCmd())
    new_loop_state = (
        LoopStatus.stopped if should_set_stopped(state.loop_state)
        else state.loop_state
    )
    if should_export(state.n_seqs, state.n_exps, state.n_acts):
        cmds.append(ExportQueuesCmd(timestamped=True))
    new = replace(
        state, loop_state=new_loop_state, loop_intent=LoopIntent.none
    )
    return new, tuple(cmds)


def _iterate(state: OrchestrationState) -> StepResult:
    ladder = _POLICY.next_step(state.snapshot())
    if isinstance(ladder, ExitLoop):
        return _finalization(state)
    if isinstance(ladder, DriverHealthWait):
        return state, (RetryDriverHealth(na_drivers=ladder.na_drivers),)
    if isinstance(ladder, StopLoop):
        # stop_loop() == intend_stop(); drains via T5 on the next iteration
        return replace(state, loop_intent=LoopIntent.stop), ()
    if isinstance(ladder, LaunchAction):
        intent = _POLICY.pre_dispatch_intent_step(state.loop_intent)
        if isinstance(intent, DrainForStop):  # T5
            new = replace(
                state,
                loop_state=LoopStatus.stopped,
                loop_intent=LoopIntent.none,
            )
            return new, (WaitAllActionsIdle(),)
        if isinstance(intent, SkipClearActions):  # T6
            return (
                replace(state, loop_intent=LoopIntent.none),
                (ClearActionQueue(),),
            )
        if isinstance(intent, EstopClearActions):  # T7
            new = replace(
                state,
                loop_state=LoopStatus.estopped,
                loop_intent=LoopIntent.none,
            )
            return new, (ClearActionQueue(),)
        assert isinstance(intent, ProceedDispatch)
        return state, (DispatchHeadAction(),)
    if isinstance(ladder, FinishThenDispatchExperiment):
        return state, (FinishThenDispatchExperimentCmd(),)
    if isinstance(ladder, FinishThenDispatchSequence):
        return state, (FinishThenDispatchSequenceCmd(),)
    assert isinstance(ladder, LogQueuesEmpty)
    return state, ()


def step(state: OrchestrationState, event: Event) -> StepResult:
    """The reducer. Pure: same (state, event) in, same (state, commands) out."""
    if isinstance(event, StartRequested):
        if state.loop_state == LoopStatus.estopped:  # T3
            return state, (RefuseStart(reason="clear E-STOP first"),)
        if state.loop_state == LoopStatus.started:
            return state, ()
        has_work = (
            state.n_acts or state.n_exps or state.n_seqs
            or state.active_sequence_present
        )
        if not has_work:  # T2
            return state, (RefuseStart(reason="experiment list is empty"),)
        return (  # T1
            replace(state, loop_state=LoopStatus.started),
            (CreateDispatchLoopTask(),),
        )

    if isinstance(event, StopRequested):
        return replace(state, loop_intent=LoopIntent.stop), ()

    if isinstance(event, SkipRequested):
        return replace(state, loop_intent=LoopIntent.skip), ()

    if isinstance(event, EstopRequested):  # T9 (API source)
        return _estop_transition(state, event.reason)

    if isinstance(event, ActionResultErrored):  # T9 (result escalation)
        return _estop_transition(state, event.reason)

    if isinstance(event, UncaughtLoopException):  # T13
        return _estop_transition(state, event.reason)

    if isinstance(event, EstoppedUuidIngested):  # T9 (status source)
        if state.loop_state != LoopStatus.started:
            return state, ()
        return _estop_transition(state, event.reason)

    if isinstance(event, ClearEstopRequested):  # T10
        if state.loop_state != LoopStatus.estopped:
            return state, ()
        new = replace(
            state,
            loop_state=LoopStatus.stopped,
            orch_state=OrchStatus.idle,
        )
        return new, (
            ClearEstoppedFromFinished(),
            ReleaseServersEstop(),
            InterruptWake(message="cleared_estop"),
        )

    if isinstance(event, ClearErrorRequested):  # T11
        return state, (
            ClearErroredFromFinished(),
            InterruptWake(message="cleared_errored"),
        )

    if isinstance(event, DispatchFailed):  # T12
        return (
            replace(state, loop_intent=LoopIntent.stop),
            (SetStopMessage(message=event.message), RequeueHeadAction()),
        )

    if isinstance(event, PlateGateFailed):  # T12 (inline stopped)
        new = replace(
            state, loop_state=LoopStatus.stopped, loop_intent=LoopIntent.stop
        )
        return new, (SetStopMessage(message=event.message),)

    if isinstance(event, HeartbeatFailed):  # T12
        return (
            replace(state, loop_intent=LoopIntent.stop),
            (
                SetStopMessage(message=event.message),
                AlertOperator(message=event.message),
            ),
        )

    if isinstance(event, DriverHealthUnrecovered):  # T12
        msg = f"unknown driver states: {', '.join(event.na_drivers)}"
        return (
            replace(state, loop_intent=LoopIntent.stop),
            (SetStopMessage(message=msg),),
        )

    if isinstance(event, ErroredUuidIngested):
        if state.loop_state == LoopStatus.started:
            return replace(state, orch_state=OrchStatus.error), ()
        return state, ()

    if isinstance(event, StatusChanged):
        new_orch = OrchStatus.busy if event.any_active else OrchStatus.idle
        return replace(state, orch_state=new_orch), ()

    assert isinstance(event, LoopIterate)
    return _iterate(state)
```

Add an `__all__` listing every public name (state, all events, all commands,
`Event`, `Command`, `StepResult`, `step`).

Implementation note on the T7 test (`test_t7_estop_intent_...`): with
`loop_intent == estop` the ladder's StopLoop branch fires before LaunchAction
(exactly as legacy :1166 precedes :1171), so the reducer converts the intent
to stop first; the EstopClearActions path is only reachable when the runner
re-enters LaunchAction with the estop intent still set. The test therefore
accepts both `started` (StopLoop path) and `estopped`. If you tighten it,
tighten it to the StopLoop behavior — precedence is the contract.

- [ ] **Step 3: Run tests to verify they pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_orchestration.py -q`
Expected: PASS.

- [ ] **Step 4: Full suite + commit**

Run: `conda run -n helao python -m pytest helao/hexagon/tests -q`
Expected: all pass.

```bash
black helao/hexagon
git add helao/hexagon
git commit -m "feat(hexagon): orchestration reducer FSM (T1-T13 + guarded estop re-checks)"
```

---

### Task 9: Queue-CRUD, run-id, process-grouping, plan-merge pure policies

**Files:**
- Create: `helao/hexagon/domain/queue_policy.py`
- Test: `helao/hexagon/tests/test_queue_policy.py`

**Interfaces:**
- Consumes: `Action`, `Experiment`, `Sequence`, `ShortExperimentModel`, `MachineModel` from `helao.hexagon.domain.models`; `Callable[[], UUID]` uuid factories (deterministic in tests).
- Produces: `ensure_run_id(active_run_id, sequence_dq_empty, mint) -> UUID`; `resolve_active_run_id(sequence_run_id, active_run_id) -> Tuple[Optional[UUID], Optional[UUID]]`; `fold_sequence_onto_experiment(seq, experiment) -> Experiment`; `bump_retry(errored_action, sup_action, machine_name) -> Action`; `assign_process_groups(actions, mint) -> Tuple[Dict[int, List[int]], List[UUID]]`; `merge_planned_experiments(operator_plan, fresh_plan) -> list`.

These are the pure cores of `RunQueues` (`helao/core/servers/orch_queues.py`) and `dispatch_sequence`/`_expand_experiment_actions` (`orch_dispatch.py`). The deque objects themselves stay app-side (P1b); these functions encode the decisions.

- [ ] **Step 1: Write the failing tests**

Create `helao/hexagon/tests/test_queue_policy.py`:

```python
"""Pure queue/run-id/process-group/plan-merge policies (core-01 §2/§3)."""

from itertools import count
from uuid import UUID, uuid5, NAMESPACE_URL

from helao.hexagon.domain import queue_policy as qp
from helao.hexagon.domain.models import (
    Action,
    Experiment,
    ProcessContrib,
    Sequence,
    ShortExperimentModel,
)


def mk_uuid_factory():
    c = count()
    return lambda: uuid5(NAMESPACE_URL, f"test-{next(c)}")


# --- run-id policy (orch_queues.py:125-142) ---

def test_ensure_run_id_mints_when_queue_empty():
    mint = mk_uuid_factory()
    stale = mint()
    new = qp.ensure_run_id(active_run_id=stale, sequence_dq_empty=True, mint=mint)
    assert new != stale


def test_ensure_run_id_reuses_inflight_when_queue_nonempty():
    mint = mk_uuid_factory()
    inflight = mint()
    assert (
        qp.ensure_run_id(active_run_id=inflight, sequence_dq_empty=False, mint=mint)
        == inflight
    )


def test_resolve_active_run_id_sequence_wins():
    mint = mk_uuid_factory()
    seq_rid, orch_rid = mint(), mint()
    new_seq, new_active = qp.resolve_active_run_id(seq_rid, orch_rid)
    assert new_active == seq_rid and new_seq == seq_rid


def test_resolve_active_run_id_inherits_orch_when_sequence_unset():
    mint = mk_uuid_factory()
    orch_rid = mint()
    new_seq, new_active = qp.resolve_active_run_id(None, orch_rid)
    assert new_seq == orch_rid and new_active == orch_rid


def test_resolve_active_run_id_both_none():
    assert qp.resolve_active_run_id(None, None) == (None, None)


# --- add_experiment field-fold (orch_queues.py:350-358) ---

def test_fold_sequence_onto_experiment_setattr_loop():
    seq = Sequence(sequence_name="s", sequence_label="lab",
                   sequence_params={"a": 1})
    exp = qp.fold_sequence_onto_experiment(
        seq, ShortExperimentModel(experiment_name="e", experiment_params={"p": 2})
    )
    # every Sequence model field is folded onto the experiment
    assert exp.sequence_name == "s"
    assert exp.sequence_label == "lab"
    assert exp.sequence_params == {"a": 1}
    # experiment identity minted fresh is the CALLER's job (add_experiment
    # mints after the fold); the fold itself must not set experiment_uuid
    assert exp.experiment_name == "e"


# --- supplement_error_action retry bump (orch_queues.py:445-470) ---

def test_bump_retry_copies_orders_and_increments_retry():
    errored = Action(action_name="a")
    errored.action_order = 4
    errored.action_actual_order = 7
    errored.action_retry = 1
    sup = Action(action_name="a")
    out = qp.bump_retry(errored, sup, machine_name="orchbox")
    assert out.action_order == 4
    assert out.action_actual_order == 7
    assert out.action_retry == 2
    assert out.action_server.machine_name == "orchbox"


# --- process grouping (orch_dispatch.py:1124-1158) ---

def _acts(spec):
    """spec: list of (contrib: bool, finish: bool)."""
    acts = []
    for contrib, finish in spec:
        a = Action(action_name="x")
        if contrib:
            a.process_contrib = [ProcessContrib.files]
        a.process_finish = finish
        acts.append(a)
    return acts


def test_assign_process_groups_two_groups():
    mint = mk_uuid_factory()
    acts = _acts([(True, False), (True, True), (True, False), (True, True)])
    groups, process_list = qp.assign_process_groups(acts, mint)
    assert groups == {0: [0, 1], 1: [2, 3]}
    assert len(process_list) == 2
    # every contributing action got its group's uuid stamped
    assert acts[0].process_uuid == acts[1].process_uuid == process_list[0]
    assert acts[2].process_uuid == acts[3].process_uuid == process_list[1]


def test_assign_process_groups_no_contrib_no_groups():
    mint = mk_uuid_factory()
    acts = _acts([(False, False), (False, False)])
    groups, process_list = qp.assign_process_groups(acts, mint)
    assert groups == {} and process_list == []


def test_assign_process_groups_truncation_quirk_preserved():
    """Legacy: process_list = init_process_uuids[:len(process_order_groups)].
    With a finish-only action (no contrib) between groups, the group indices
    are non-contiguous but the uuid list is truncated by COUNT — reproduce
    exactly (parity over intuition)."""
    mint = mk_uuid_factory()
    acts = _acts([(True, True), (False, True), (True, True)])
    groups, process_list = qp.assign_process_groups(acts, mint)
    assert sorted(groups.keys()) == [0, 2]
    assert len(process_list) == 2  # count-truncated, NOT index-selected


# --- planned-experiment merge (orch_dispatch.py:1264-1293) ---

def _plan(*names):
    return [ShortExperimentModel(experiment_name=n) for n in names]


def test_merge_uses_fresh_plan_when_operator_plan_empty():
    fresh = _plan("a", "b")
    assert qp.merge_planned_experiments([], fresh) == fresh


def test_merge_prefix_match_folds_operator_fields_onto_fresh():
    operator = _plan("a", "b", "c")
    operator[1].experiment_params = {"tweaked": True}
    fresh = _plan("a", "b")
    merged = qp.merge_planned_experiments(operator, fresh)
    # operator plan longer + prefix-matches -> merged keeps operator length
    assert [e.experiment_name for e in merged] == ["a", "b", "c"]
    assert merged[1].experiment_params == {"tweaked": True}


def test_merge_name_mismatch_keeps_operator_plan():
    operator = _plan("a", "X", "c")
    fresh = _plan("a", "b")
    merged = qp.merge_planned_experiments(operator, fresh)
    # break on mismatch -> lengths differ -> operator plan retained verbatim
    assert merged == operator


def test_merge_shorter_operator_plan_keeps_operator_plan():
    operator = _plan("a")
    fresh = _plan("a", "b")
    assert qp.merge_planned_experiments(operator, fresh) == operator
```

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_queue_policy.py -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 2: Write `domain/queue_policy.py`**

```python
"""Pure queue-CRUD / run-id / process-group / plan-merge policies.

Extracted decision cores of RunQueues (helao/core/servers/orch_queues.py) and
DispatchRunner.dispatch_sequence/_expand_experiment_actions
(helao/core/servers/orch_dispatch.py). The zdeque objects and history maps
stay app-side (P1b); these functions make the decisions. UUID minting is
injected (``mint``) so tests are deterministic; production passes
helao.helpers.gen_uuid.gen_uuid through the composition root.
"""

from collections import defaultdict
from typing import Callable, Dict, List, Optional, Sequence as Seq, Tuple
from uuid import UUID

from helao.hexagon.domain.models import (
    Action,
    Experiment,
    Sequence,
    ShortExperimentModel,
)

__all__ = [
    "assign_process_groups",
    "bump_retry",
    "ensure_run_id",
    "fold_sequence_onto_experiment",
    "merge_planned_experiments",
    "resolve_active_run_id",
]

UuidFactory = Callable[[], UUID]


def ensure_run_id(
    active_run_id: Optional[UUID],
    sequence_dq_empty: bool,
    mint: UuidFactory,
) -> UUID:
    """Run-id to stamp on a sequence entering the queue (orch_queues.py:125).

    Empty/just-cleared queue -> fresh run_id; non-empty -> reuse the in-flight
    active_run_id (back-to-back queue entries share a run).
    """
    if sequence_dq_empty or active_run_id is None:
        return mint()
    return active_run_id


def resolve_active_run_id(
    sequence_run_id: Optional[UUID],
    active_run_id: Optional[UUID],
) -> Tuple[Optional[UUID], Optional[UUID]]:
    """At dequeue, sync run ids (orch_queues.py:136-142).

    Returns (run_id_for_sequence, new_active_run_id): the sequence's own
    run_id wins; else it inherits the orch's active_run_id; both None stays
    both None.
    """
    if sequence_run_id is not None:
        return sequence_run_id, sequence_run_id
    if active_run_id is not None:
        return active_run_id, active_run_id
    return None, None


def fold_sequence_onto_experiment(
    seq: Sequence,
    experimentmodel: object,
) -> Experiment:
    """The add_experiment field-fold (orch_queues.py:350-358), verbatim:
    validate into a runtime Experiment, then setattr every Sequence field.

    Minting experiment_uuid and defaulting the orchestrator identity remain
    the caller's job (they need the orch identity / uuid factory).
    """
    seq_dict = seq.model_dump()
    if not isinstance(experimentmodel, Experiment):
        experimentmodel_dict = experimentmodel.model_dump()  # type: ignore[attr-defined]
        D = Experiment.model_validate(experimentmodel_dict)
    else:
        D = experimentmodel
    for k in seq_dict.keys():
        setattr(D, k, getattr(seq, k))
    return D


def bump_retry(
    errored_action: Action,
    sup_action: Action,
    machine_name: str,
) -> Action:
    """supplement_error_action's counter surgery (orch_queues.py:464-469):
    copy order/actual_order from the errored action, bump retry, stamp the
    orch machine name. The head-appendleft stays with the caller."""
    new_action = sup_action
    new_action.action_order = errored_action.action_order
    new_action.action_actual_order = errored_action.action_actual_order
    new_action.action_retry = errored_action.action_retry + 1
    new_action.action_server.machine_name = machine_name
    return new_action


def assign_process_groups(
    actions: Seq[Action],
    mint: UuidFactory,
) -> Tuple[Dict[int, List[int]], List[UUID]]:
    """Process grouping at experiment expansion (orch_dispatch.py:1124-1158).

    Mutates each contributing action's process_uuid in place (as legacy does)
    and returns (process_order_groups, process_list). The count-based
    truncation ``init_process_uuids[:len(process_order_groups)]`` is a legacy
    quirk reproduced deliberately (parity over intuition).
    """
    process_order_groups: Dict[int, List[int]] = defaultdict(list)
    process_count = 0
    init_process_uuids = [mint()]
    for i, act in enumerate(actions):
        if act.process_contrib:
            process_order_groups[process_count].append(i)
            act.process_uuid = init_process_uuids[process_count]
        if act.process_finish:
            process_count += 1
            init_process_uuids.append(mint())
    if process_order_groups:
        process_list = init_process_uuids[: len(process_order_groups)]
        return dict(process_order_groups), process_list
    return {}, []


def merge_planned_experiments(
    operator_plan: List[ShortExperimentModel],
    fresh_plan: List[ShortExperimentModel],
) -> List[ShortExperimentModel]:
    """Planned-experiment merge at sequence dispatch (orch_dispatch.py:1264-1293).

    Empty operator plan -> fresh plan. Operator plan at least as long as the
    fresh plan -> walk pairwise; on name match fold the operator entry's
    fields onto the fresh entry; on mismatch break; adopt the merged list
    only when it kept the operator plan's full length. Anything else keeps
    the operator plan untouched.
    """
    if not operator_plan:
        return list(fresh_plan)
    if len(operator_plan) >= len(fresh_plan):
        remaining = list(fresh_plan)
        new_planned: List[ShortExperimentModel] = []
        for exp_model in operator_plan:
            if not remaining:
                new_planned.append(exp_model)
            else:
                exp = remaining.pop(0)
                if exp.experiment_name == exp_model.experiment_name:
                    for k, v in vars(exp_model).items():
                        setattr(exp, k, v)
                    new_planned.append(exp)
                else:
                    break
        if len(operator_plan) == len(new_planned):
            return new_planned
    return list(operator_plan)
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_queue_policy.py -q`
Expected: PASS. If `vars(exp_model)` on a pydantic v2 model does not yield
fields on this pydantic version, mirror whatever `orch_dispatch.py:1283`
actually does on `unstable` (it uses `vars()` today) — the port must match
the source line, not an idealized version.

- [ ] **Step 4: Full suite + commit**

Run: `conda run -n helao python -m pytest helao/hexagon/tests -q`
Expected: all pass.

```bash
black helao/hexagon
git add helao/hexagon
git commit -m "feat(hexagon): pure queue/run-id/process-group/plan-merge policies"
```

---

### Task 10: EstopPolicy + declarative stop topology (resolves Q7)

**Files:**
- Create: `helao/hexagon/domain/estop_policy.py`
- Test: `helao/hexagon/tests/test_estop_policy.py`

**Interfaces:**
- Consumes: `HloStatus`, `MachineModel` from `helao.hexagon.domain.models`; reducer commands `EstopFanout`, `FinishActiveEstopped` from `helao.hexagon.domain.orchestration` (shared command vocabulary).
- Produces: `EstopTopology` (frozen dataclass), `derive_estop_topology(servers_cfg: dict) -> EstopTopology`, trigger dataclasses (`DriverFaultEdge`, `UiEstopButton`, `StatusEstopIngested`, `OrchEstopRequest`), command dataclasses (`StopOrch(key)`, `StopRecorders(keys)`, `StopPrivate(keys)`), and class `EstopPolicy` with `commands_for(trigger) -> Tuple[command, ...]`; plus `mark_estopped(status_list) -> list` (the `[finished, estopped]` shape helper).

**Q7 DECISION (proposed here, P5/Deployment-B reviews before first real use):**
the stop topology is declared as **per-server role tags in the existing
config idiom**, not a separate top-level block:

```yaml
servers:
  ORCH:
    group: orchestrator          # orchestrator role derived automatically
    ...
  RECORD1:
    group: action
    estop_roles: [recorder]      # NEW optional per-server key
    ...
  PSTAT1:
    group: action
    estop_roles: [stop_private]  # servers needing /stop_private
    ...
```

Rationale: (a) single source of truth — the role lives on the server entry it
describes, so adding/removing a server can never leave a stale topology block
behind (the preflight validator already checks server keys); (b) it matches
the existing per-server config idiom (`group:`, `fast:`, `params:`), so
private-deployment configs change minimally at P5 cut-over; (c) **ordering is
policy, not config**: the cascade order (orchestrators → recorders →
stop_private → fanout → finalize) is fixed in `EstopPolicy` — a config cannot
accidentally reorder a safety cascade, which an explicit ordered
`estop_topology:` list could. Orchestrator keys are derived from
`group: orchestrator` (already in every config); only the two roles the config
cannot express today (`recorder`, `stop_private` — currently hardcoded server
keys inside Deployment-B's `execute_gamry_stop`) need tags.

**Parity constraint encoded:** the estopped artifact shape is unchanged —
status lists end `[finished, estopped]` (never bare `[estopped]`), no
fabricated placeholder artifacts, promotion deferral stays with
`FinishActiveEstopped` (spec §4.2.5).

- [ ] **Step 1: Write the failing tests**

Create `helao/hexagon/tests/test_estop_policy.py`:

```python
"""EstopPolicy: (declarative topology + trigger) -> ordered command list."""

import pytest

from helao.hexagon.domain import estop_policy as ep
from helao.hexagon.domain.models import HloStatus
from helao.hexagon.domain.orchestration import EstopFanout, FinishActiveEstopped

SERVERS_CFG = {
    "ORCH": {"group": "orchestrator", "host": "h", "port": 8001},
    "RECORD1": {"group": "action", "estop_roles": ["recorder"]},
    "RECORD2": {"group": "action", "estop_roles": ["recorder"]},
    "PSTAT1": {"group": "action", "estop_roles": ["stop_private"]},
    "MOTOR": {"group": "action"},
    "VIS": {"group": "visualizer", "bokeh": "x"},
}


def topo() -> ep.EstopTopology:
    return ep.derive_estop_topology(SERVERS_CFG)


def test_derive_topology_roles():
    t = topo()
    assert t.orch_keys == ("ORCH",)
    assert t.recorder_keys == ("RECORD1", "RECORD2")
    assert t.stop_private_keys == ("PSTAT1",)
    # fanout targets every non-visualizer server (server_dict members)
    assert set(t.all_server_keys) == {"ORCH", "RECORD1", "RECORD2",
                                      "PSTAT1", "MOTOR"}


def test_derive_topology_rejects_unknown_role():
    bad = {"X": {"group": "action", "estop_roles": ["recroder"]}}
    with pytest.raises(ValueError):
        ep.derive_estop_topology(bad)


def test_driver_fault_edge_orders_orch_recorders_private():
    """The Deployment-B execute_gamry_stop cascade, now policy-emitted:
    ORCH* /stop -> recorder keys /stop_record -> PSTAT keys /stop_private."""
    p = ep.EstopPolicy(topo())
    cmds = p.commands_for(ep.DriverFaultEdge(source="opcua_monitor"))
    assert [type(c) for c in cmds] == [ep.StopOrch, ep.StopRecorders,
                                       ep.StopPrivate]
    assert cmds[0].key == "ORCH"
    assert cmds[1].keys == ("RECORD1", "RECORD2")
    assert cmds[2].keys == ("PSTAT1",)


def test_ui_button_same_cascade_as_fault_edge():
    """The visualizer's duplicate buttons feed the SAME policy (spec §4.2.5)."""
    p = ep.EstopPolicy(topo())
    assert p.commands_for(ep.UiEstopButton(source="vis")) == p.commands_for(
        ep.DriverFaultEdge(source="vis")
    )


def test_orch_estop_request_full_sequence():
    """/estop_orch and status-ingested estop drive the orch-side sequence:
    fanout to every server then finalize actives (core-01 §7)."""
    p = ep.EstopPolicy(topo())
    cmds = p.commands_for(ep.OrchEstopRequest(reason="operator"))
    assert [type(c) for c in cmds] == [EstopFanout, FinishActiveEstopped]
    assert cmds[0].switch is False


def test_status_ingested_matches_orch_request():
    p = ep.EstopPolicy(topo())
    assert [type(c) for c in p.commands_for(
        ep.StatusEstopIngested(reason="uuid estopped")
    )] == [EstopFanout, FinishActiveEstopped]


def test_multiple_orchestrators_each_get_stop():
    cfg = dict(SERVERS_CFG)
    cfg["ORCH2"] = {"group": "orchestrator"}
    p = ep.EstopPolicy(ep.derive_estop_topology(cfg))
    cmds = p.commands_for(ep.DriverFaultEdge(source="x"))
    assert [c.key for c in cmds if isinstance(c, ep.StopOrch)] == [
        "ORCH", "ORCH2"
    ]


def test_empty_role_groups_emit_no_commands_for_them():
    cfg = {"ORCH": {"group": "orchestrator"}, "A": {"group": "action"}}
    p = ep.EstopPolicy(ep.derive_estop_topology(cfg))
    cmds = p.commands_for(ep.DriverFaultEdge(source="x"))
    assert [type(c) for c in cmds] == [ep.StopOrch]


# --- the estopped-artifact-shape constraint ---

def test_mark_estopped_replaces_active_and_appends_estopped():
    out = ep.mark_estopped([HloStatus.active])
    assert out == [HloStatus.finished, HloStatus.estopped]


def test_mark_estopped_idempotent():
    once = ep.mark_estopped([HloStatus.active])
    assert ep.mark_estopped(once) == once


def test_mark_estopped_never_bare_estopped():
    assert ep.mark_estopped([]) == [HloStatus.finished, HloStatus.estopped]
```

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_estop_policy.py -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 2: Write `domain/estop_policy.py`**

```python
"""EstopPolicy (spec §4.2.5): ONE policy replacing two hardcoded cascades.

Today: (a) the orch's estop_loop sequence (orch_estop.EstopController), and
(b) Deployment-B's execute_gamry_stop — a driver-resident cascade firing raw
HTTP at hardcoded server keys, duplicated with drift in a Bokeh visualizer.
This module resolves both once: a pure policy mapping (declarative stop
topology + trigger event) -> ordered command list. Commands execute through
the Transport/OrchControl outbound port — never raw httpx in a driver, never
hardcoded keys in code.

Q7 topology representation (see the P1a plan for rationale): per-server role
tags in the existing config idiom — orchestrators derived from
``group: orchestrator``; ``estop_roles: [recorder|stop_private]`` tags on the
server entries that need them. CASCADE ORDER IS POLICY, NOT CONFIG.

Parity constraint (spec §4.2.5): estopped artifact shape unchanged —
``[finished, estopped]`` status lists (mark_estopped), no fabricated
placeholder artifacts (post-bd8b83ab), estop-promote deferral stays inside
FinishActiveEstopped's executor.
"""

from dataclasses import dataclass
from typing import List, Tuple, Union

from helao.hexagon.domain.models import HloStatus
from helao.hexagon.domain.orchestration import EstopFanout, FinishActiveEstopped

__all__ = [
    "DriverFaultEdge",
    "EstopPolicy",
    "EstopTopology",
    "OrchEstopRequest",
    "StatusEstopIngested",
    "StopOrch",
    "StopPrivate",
    "StopRecorders",
    "UiEstopButton",
    "derive_estop_topology",
    "mark_estopped",
]

_VALID_ROLES = frozenset({"recorder", "stop_private"})


@dataclass(frozen=True)
class EstopTopology:
    """Declarative stop topology derived from a config's servers: block."""

    orch_keys: Tuple[str, ...]
    recorder_keys: Tuple[str, ...]
    stop_private_keys: Tuple[str, ...]
    all_server_keys: Tuple[str, ...]  # fanout targets (non-bokeh servers)


def derive_estop_topology(servers_cfg: dict) -> EstopTopology:
    """Build the topology from ``config['servers']``.

    Orchestrators come from ``group: orchestrator`` (no tag needed);
    recorder / stop_private roles come from the per-server ``estop_roles``
    list. Unknown role strings raise ValueError (loud preflight, not silent
    drift — the failure mode that let Deployment-B's two cascades diverge).
    """
    orch_keys: List[str] = []
    recorder_keys: List[str] = []
    stop_private_keys: List[str] = []
    all_server_keys: List[str] = []
    for key, cfg in servers_cfg.items():
        if "bokeh" in cfg:
            continue  # visualizer/operator bokeh apps take no estop calls
        all_server_keys.append(key)
        if cfg.get("group") == "orchestrator":
            orch_keys.append(key)
        roles = cfg.get("estop_roles", [])
        unknown = set(roles) - _VALID_ROLES
        if unknown:
            raise ValueError(
                f"server {key!r}: unknown estop_roles {sorted(unknown)}; "
                f"valid: {sorted(_VALID_ROLES)}"
            )
        if "recorder" in roles:
            recorder_keys.append(key)
        if "stop_private" in roles:
            stop_private_keys.append(key)
    return EstopTopology(
        orch_keys=tuple(orch_keys),
        recorder_keys=tuple(recorder_keys),
        stop_private_keys=tuple(stop_private_keys),
        all_server_keys=tuple(all_server_keys),
    )


# --- triggers (adapters feed these: OPC-UA fault monitor rising edge, the
#     visualizer buttons, status ingestion, POST /estop_orch) ---


@dataclass(frozen=True)
class DriverFaultEdge:
    source: str


@dataclass(frozen=True)
class UiEstopButton:
    source: str


@dataclass(frozen=True)
class StatusEstopIngested:
    reason: str


@dataclass(frozen=True)
class OrchEstopRequest:
    reason: str


Trigger = Union[DriverFaultEdge, UiEstopButton, StatusEstopIngested,
                OrchEstopRequest]


# --- commands (executed via the Transport port, P1b) ---


@dataclass(frozen=True)
class StopOrch:
    """POST /stop on an orchestrator key."""

    key: str


@dataclass(frozen=True)
class StopRecorders:
    """POST /stop_record on every recorder key."""

    keys: Tuple[str, ...]


@dataclass(frozen=True)
class StopPrivate:
    """POST /stop_private on every tagged key."""

    keys: Tuple[str, ...]


class EstopPolicy:
    """Pure: trigger in -> ordered command tuple out. No I/O, no state."""

    def __init__(self, topology: EstopTopology):
        self.topology = topology

    def commands_for(self, trigger: Trigger) -> Tuple[object, ...]:
        if isinstance(trigger, (DriverFaultEdge, UiEstopButton)):
            # the (previously hardcoded) station-side cascade:
            # orchestrators first, then recorders, then stop_private targets
            cmds: List[object] = [StopOrch(key=k) for k in self.topology.orch_keys]
            if self.topology.recorder_keys:
                cmds.append(StopRecorders(keys=self.topology.recorder_keys))
            if self.topology.stop_private_keys:
                cmds.append(StopPrivate(keys=self.topology.stop_private_keys))
            return tuple(cmds)
        # orch-side estop (API or status-ingested): fan out then finalize.
        # State flip / run-id clear / stop message stay with the reducer's
        # _estop_transition — this policy owns only the wire cascade tail.
        assert isinstance(trigger, (StatusEstopIngested, OrchEstopRequest))
        return (EstopFanout(switch=False), FinishActiveEstopped())


def mark_estopped(status_list: List[HloStatus]) -> List[HloStatus]:
    """The estopped terminal-status shape (orch_estop._mark_estopped):
    active is replaced by finished, estopped appended once — the result is
    always ``[..., finished, estopped]``, never bare ``[estopped]``."""
    out = [s for s in status_list if s != HloStatus.active]
    if HloStatus.finished not in out:
        out.append(HloStatus.finished)
    if HloStatus.estopped not in out:
        out.append(HloStatus.estopped)
    return out
```

NOTE for the implementer: compare `mark_estopped` against the real
`_mark_estopped` closure in `helao/core/servers/orch_estop.py:161` (it uses
the guarded replace-else-append semantics on the live status list). Mirror
its outcome for the three cases the tests pin (active-only, already-marked,
empty); if legacy differs on any (e.g. preserves non-active pre-existing
statuses in place rather than filtering), match legacy and fix the test.

- [ ] **Step 3: Run tests to verify they pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_estop_policy.py -q`
Expected: PASS.

- [ ] **Step 4: Full suite + commit**

Run: `conda run -n helao python -m pytest helao/hexagon/tests -q`
Expected: all pass.

```bash
black helao/hexagon
git add helao/hexagon
git commit -m "feat(hexagon): EstopPolicy + per-server-role stop topology (Q7)"
```

---

### Task 11: In-memory port fakes (test-only)

**Files:**
- Create: `helao/hexagon/tests/fakes.py`
- Test: `helao/hexagon/tests/test_fakes.py`

**Interfaces:**
- Consumes: the port Protocols (Tasks 3-4), `helao.hexagon.domain.models`.
- Produces: `FakeClock`, `FakeTransport`, `FakeArtifactStore`, `FakeDataSink`, `FakeStatusPush`, `FakeStatePersistence` — in-memory recorders satisfying the runtime_checkable Protocols, for domain-adjacent unit tests without adapters.

**Placement rule (spec §10.2 adapted for P1a):** fakes live under `tests/` in P1a because production composition does not exist yet; when P1b creates `adapters/fakes/`, these move there behind the same names and gain the "fakes are opt-in and fail loud" wiring (composition raises on unwired ports; fakes log a WARNING banner — the banner is included now so the move is mechanical).

- [ ] **Step 1: Write the failing conformance tests**

Create `helao/hexagon/tests/test_fakes.py`:

```python
"""Fakes must satisfy their Protocols and record faithfully."""

import asyncio
from datetime import datetime

from helao.hexagon.tests import fakes
from helao.hexagon.ports.artifact_store import ArtifactStorePort
from helao.hexagon.ports.clock import ClockPort
from helao.hexagon.ports.data_sink import DataSinkPort
from helao.hexagon.ports.status import StatusPort
from helao.hexagon.ports.transport import TransportPort
from helao.hexagon.ports.auxiliary import StatePersistencePort
from helao.hexagon.domain.models import Action, DataModel, ErrorCodes


def test_fakes_satisfy_protocols():
    assert isinstance(fakes.FakeClock(), ClockPort)
    assert isinstance(fakes.FakeTransport(), TransportPort)
    assert isinstance(fakes.FakeArtifactStore(), ArtifactStorePort)
    assert isinstance(fakes.FakeDataSink(), DataSinkPort)
    assert isinstance(fakes.FakeStatusPush(), StatusPort)
    assert isinstance(fakes.FakeStatePersistence(), StatePersistencePort)


def test_fake_clock_is_deterministic():
    clk = fakes.FakeClock(fixed=datetime(2026, 7, 17, 12, 0, 0), offset_s=1.5)
    assert clk.now() == datetime(2026, 7, 17, 12, 0, 0)
    assert clk.offset() == 1.5
    assert clk.now_ns() == int(datetime(2026, 7, 17, 12, 0, 0).timestamp() * 1e9)


def test_fake_transport_records_dispatches():
    tr = fakes.FakeTransport()
    act = Action(action_name="acquire")
    act.action_server.server_name = "SIM"
    resp, err = asyncio.run(tr.dispatch_action(act))
    assert err == ErrorCodes.none
    assert len(tr.dispatched) == 1
    method, payload = tr.dispatched[0]
    assert method == "SIM/acquire"
    assert payload["action"]["action_name"] == "acquire"


def test_fake_transport_scripted_failure():
    tr = fakes.FakeTransport(fail_with=ErrorCodes.http_error)
    act = Action(action_name="acquire")
    act.action_server.server_name = "SIM"
    resp, err = asyncio.run(tr.dispatch_action(act))
    assert resp is None and err == ErrorCodes.http_error


def test_fake_data_sink_records_enqueues_thread_safely():
    sink = fakes.FakeDataSink()
    dm = DataModel(data={}, errors=[])
    sink.enqueue_data_nowait(dm)
    assert sink.enqueued == [dm]
    assert isinstance(sink.get_realtime_nowait(), int)


def test_fake_artifact_store_records_writes():
    store = fakes.FakeArtifactStore()
    act = Action(action_name="acquire")
    act.init_act()
    asyncio.run(store.write_act(act))
    assert [k for k, _ in store.writes] == ["act"]


def test_fake_state_persistence_round_trip(tmp_path):
    sp = fakes.FakeStatePersistence()
    sp.export_queues({"seq": [1, 2]}, timestamp_pck=False)
    assert sp.import_queues() == {"seq": [1, 2]}
    # import consumes (queues_imported_<ts> archival semantics)
    assert sp.import_queues() is None
```

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_fakes.py -q`
Expected: FAIL (`ImportError: cannot import name 'fakes'`).

NOTE for the implementer: check `helao/core/error.py` for the exact
`ErrorCodes` member for HTTP/transport failure (`http_error` assumed; use
what exists, e.g. `http` or `request_error`).

- [ ] **Step 2: Write `tests/fakes.py`**

```python
"""In-memory port fakes for domain-adjacent unit tests (spec §10.2).

TEST-ONLY in P1a. Each fake logs a WARNING banner at construction so a
"green on fakes" run is visible in output; production composition (P1b)
raises on unwired ports and never defaults to these.
"""

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from helao.hexagon.domain.models import (
    Action,
    ActionServerModel,
    DataModel,
    ErrorCodes,
)

LOGGER = logging.getLogger(__name__)


def _banner(name: str) -> None:
    LOGGER.warning("FAKE PORT IN USE: %s (test-only, never production)", name)


class FakeClock:
    def __init__(self, fixed: Optional[datetime] = None, offset_s: float = 0.0):
        _banner("FakeClock")
        self._fixed = fixed
        self._offset = offset_s

    def now(self) -> datetime:
        return self._fixed if self._fixed is not None else datetime.now()

    def now_ns(self) -> int:
        if self._fixed is not None:
            return int(self._fixed.timestamp() * 1e9)
        return time.time_ns()

    def offset(self) -> float:
        return self._offset


class FakeTransport:
    """Records every dispatch; scripted responses/failures."""

    def __init__(
        self,
        respond_with: Optional[dict] = None,
        fail_with: Optional[ErrorCodes] = None,
    ):
        _banner("FakeTransport")
        self._respond_with = respond_with
        self._fail_with = fail_with
        self.dispatched: List[Tuple[str, dict]] = []
        self.private_calls: List[Tuple[str, str, dict]] = []
        self.probed: List[str] = []

    async def dispatch_action(
        self,
        action: Action,
        params: Optional[dict] = None,
        timeout: float = 60,
        retries: int = 5,
    ) -> Tuple[Optional[dict], ErrorCodes]:
        method = f"{action.action_server.server_name}/{action.action_name}"
        payload = dict(params or {})
        payload["action"] = action.as_dict()
        self.dispatched.append((method, payload))
        if self._fail_with is not None:
            return None, self._fail_with
        return self._respond_with or action.as_dict(), ErrorCodes.none

    async def dispatch_private(
        self,
        server_key: str,
        host: str,
        port: int,
        private_action: str,
        params_dict: Optional[dict] = None,
        json_dict: Optional[dict] = None,
        timeout: float = 60,
        retries: int = 5,
    ) -> Tuple[Optional[dict], ErrorCodes]:
        self.private_calls.append(
            (server_key, private_action, {**(params_dict or {}),
                                          **(json_dict or {})})
        )
        if self._fail_with is not None:
            return None, self._fail_with
        return self._respond_with or {}, ErrorCodes.none

    async def check_endpoint(self, url: str, timeout: float = 3.0) -> bool:
        self.probed.append(url)
        return self._fail_with is None


class FakeArtifactStore:
    def __init__(self):
        _banner("FakeArtifactStore")
        self.writes: List[Tuple[str, object]] = []
        self.data_lines: List[Tuple[object, object]] = []
        self.moved: List[object] = []
        self.finished: List[object] = []

    async def write_act(self, action) -> None:
        self.writes.append(("act", action))

    async def write_exp(self, experiment) -> None:
        self.writes.append(("exp", experiment))

    async def write_seq(self, sequence) -> None:
        self.writes.append(("seq", sequence))

    async def write_data_line(self, action, file_conn_key, payload) -> None:
        self.data_lines.append((file_conn_key, payload))

    async def close_streams(self, action) -> None:
        pass

    async def write_one_shot(
        self, action, output_str, file_type, filename, header
    ) -> Optional[str]:
        self.writes.append(("one_shot", filename))
        return filename

    async def finish(self, action) -> None:
        self.finished.append(action)

    async def move_dir(self, hobj) -> bool:
        self.moved.append(hobj)
        return True

    async def zip_dir(self, dir_path: Path) -> Path:
        return dir_path.with_suffix(".zip")


class FakeDataSink:
    """Thread-safe recorder for the DataSink surface (list.append is atomic)."""

    def __init__(self):
        _banner("FakeDataSink")
        self.enqueued: List[DataModel] = []
        self.files: List[Tuple[str, str]] = []
        self.samples: List[Tuple[str, list]] = []
        self.lbuf: dict = {}
        self.estopped = False

    async def enqueue_data(self, datamodel, action=None) -> None:
        self.enqueued.append(datamodel)

    def enqueue_data_nowait(self, datamodel, action=None) -> None:
        self.enqueued.append(datamodel)

    async def enqueue_data_dflt(self, datadict: dict) -> None:
        self.enqueued.append(DataModel(data={}, errors=[]))

    def get_realtime_nowait(self, epoch_ns=None) -> int:
        return time.time_ns()

    async def finish_hlo_header(self, file_conn_keys=None, realtime=None) -> None:
        pass

    async def write_file(self, output_str, file_type, filename=None,
                         file_group=None, header=None, sample_str=None,
                         file_sample_label=None, json_data_keys=None,
                         action=None):
        self.files.append((file_type, filename or ""))
        return filename

    def write_file_nowait(self, output_str, file_type, filename=None,
                          file_group=None, header=None, sample_str=None,
                          file_sample_label=None, json_data_keys=None,
                          action=None):
        self.files.append((file_type, filename or ""))
        return filename

    async def track_file(self, file_type, file_path, samples, action=None) -> None:
        self.files.append((file_type, file_path))

    async def append_sample(self, samples, IO, action=None) -> None:
        self.samples.append((IO, list(samples)))

    async def split(self, uuid_list=None):
        return []

    def set_estop(self, action=None) -> None:
        self.estopped = True

    async def put_lbuf(self, payload: dict) -> None:
        self.lbuf.update(payload)

    def put_lbuf_nowait(self, payload: dict) -> None:
        self.lbuf.update(payload)

    def get_lbuf(self, key: str) -> tuple:
        return (self.lbuf.get(key), time.time())


class FakeStatusPush:
    def __init__(self):
        _banner("FakeStatusPush")
        self.clients: List[Tuple[str, str, int]] = []
        self.sent: List[ActionServerModel] = []
        self.nonblocking: List[tuple] = []
        self.published: List[Tuple[str, dict]] = []

    async def attach_client(self, client_servkey, client_host, client_port) -> bool:
        self.clients.append((client_servkey, client_host, client_port))
        return True

    async def detach_client(self, client_servkey, client_host, client_port) -> None:
        self.clients.remove((client_servkey, client_host, client_port))

    async def send_status(self, asm, retries: int = 5) -> None:
        self.sent.append(asm)

    async def send_nonblocking_status(self, client_servkey, client_host,
                                      client_port, server_key, exec_id,
                                      act_uuid, status, retries: int = 3) -> None:
        self.nonblocking.append((server_key, exec_id, act_uuid, status))

    async def publish_status(self, payload: dict) -> None:
        self.published.append(("status", payload))

    async def publish_data(self, payload: dict) -> None:
        self.published.append(("data", payload))

    async def publish_live(self, payload: dict) -> None:
        self.published.append(("live", payload))


class FakeStatePersistence:
    def __init__(self):
        _banner("FakeStatePersistence")
        self._stored: Optional[dict] = None

    def export_queues(self, payload: dict, timestamp_pck: bool = False) -> Path:
        self._stored = payload
        return Path("STATES/queues.pck")

    def import_queues(self) -> Optional[dict]:
        payload, self._stored = self._stored, None  # consume-and-archive
        return payload
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_fakes.py -q`
Expected: PASS. `isinstance` checks work because every port is
`@runtime_checkable`; if one fails, the fake is missing a member — add the
member, never remove `runtime_checkable`.

- [ ] **Step 4: Full suite + commit**

Run: `conda run -n helao python -m pytest helao/hexagon/tests -q`
Expected: all pass.

```bash
black helao/hexagon
git add helao/hexagon
git commit -m "test(hexagon): in-memory port fakes with fail-loud banners"
```

---

### Task 12: P1a gate — full suite, pyright, black; record results

**Files:**
- Modify: none (verification only; fix-forward anything found)

- [ ] **Step 1: Full test suite**

Run: `conda run -n helao python -m pytest helao/hexagon/tests -q`
Expected: ALL tests pass (boundary, ports import, naming, assembly, dispatch policy, global params, status fold, orchestration, queue policy, estop policy, fakes). Record the pass count.

- [ ] **Step 2: pyright**

Run: `conda run -n helao pyright helao/hexagon`
Expected: `0 errors`. Fix any errors in hexagon code; if an error originates in a reused legacy model (D8), suppress at the hexagon usage site with `# type: ignore[<rule>]` + a comment naming the legacy smell (Q4) — never edit legacy.

- [ ] **Step 3: black check**

Run: `conda run -n helao black --check helao/hexagon`
Expected: `All done!` — nothing to reformat (every task already formatted before committing).

- [ ] **Step 4: Boundary mutation spot-check (manual, one-time)**

Temporarily add `import httpx` to `helao/hexagon/domain/naming.py`, run
`conda run -n helao python -m pytest helao/hexagon/tests/test_boundaries.py -q`,
confirm it FAILS naming the file and line, then revert the edit
(`git checkout -- helao/hexagon/domain/naming.py`). This proves the gate
guards the real tree, not just the self-test fixtures.

- [ ] **Step 5: Final commit (if any fixes landed)**

```bash
black helao/hexagon
git add helao/hexagon
git commit -m "chore(hexagon): P1a gate — suite + pyright + black green"
```

**Gate statement to record in the PR/handoff:** "P1a complete: boundary test green, N unit tests green, pyright 0 errors, black clean. NO parity claim is made — GM-1..5 golden parity and the §10.3 concurrency suite require adapters + real transport and are the P1b gate."

---

## P1b preview (deferred, NOT in this plan)

- **Legacy adapters:** thin wrappers around `MetaFileWriter`/`DataFileWriter`/`DataStreamer`/`ActionFinalizer`, `sync_driver.HelaoSyncer`, `dispatcher.py` (ZMQ+HTTP), `helao_logging`, config loader, NTP clock, `orch_persist` — behavior identical by construction, implementing the Task 3-4 Protocols.
- **App/composition:** `app/factory.py` (`makeApp`/`makeOrchApp`/…), fail-loud raise on unwired ports, launcher `deployment:` key integration, co-located RPC mirror on `http_port + 10000`.
- **Single-drainer dispatch loop:** the long-lived Event-parked task feeding `LoopIterate` into `domain.orchestration.step` and executing commands — including the live-estop re-check execution semantics for the guarded commands (pick re-read-live vs serialize-estop, test both races).
- **GM-1..5 parity gate** over legacy-wrapped adapters on `golden.yml` (P0 harness), + §9 behavior tests on the hexagon path.
- **Concurrency suite** items 1-7 (spec §10.3) on the real transport.
- **Fakes relocation:** `tests/fakes.py` → `adapters/fakes/` with opt-in wiring.
- **Also deferred from P1a scope decisions:** `TransformXY` lift (P3/P4-adjacent; ~370 lines, not trivially small), `ActionPlanMaker` caller-frame-inspection removal (context passes explicitly — needs the library port + experiment-lib wave), `Timer` primitive port (used by adapters, not the pure domain).

---

## Self-review (writing-plans checklist, applied)

**1. Spec coverage (P1a subset of §12 P1):**
- scaffold + AST boundary test → Task 1 ✔ (incl. mutation self-tests + Task 12 step 4 live check)
- port Protocols, all of §4.3 → Tasks 3-4 ✔ (Hardware §4.3.1, DataSink §4.3.2, ArtifactStore §4.3.3, Sync §4.3.4, Transport §4.3.5, Status §4.3.6, Clock §4.3.7, Logging §4.3.8, Config §4.3.9, AnalysisArtifact §4.3.10, SampleState §4.3.11, auxiliary §4.3.12: StatePersistence/PlateInfo/Library/Health/Notify + UuidFactory)
- domain run-model reuse + assembly + naming (§4.2.1/§4.2.3, D8) → Tasks 2, 5 ✔
- reducer FSM: ladder + T1-T13 + start-condition predicates + 3 live estop re-checks as command guards (§4.2.2) → Tasks 6, 8 ✔ (predicates live in the ported `start_condition_step`)
- queue-CRUD / run-id / process grouping / planned-experiment merge (§4.2.2) → Task 9 ✔
- dispatch policy + global-param folds + status fold w/ §4.2.4 checklist → Tasks 6-7 ✔ (checklist items 2 and 6 documented + item-6 pinned by the foreign-orchestrator test; item 2 is asserted at its call sites in P1b)
- EstopPolicy + Q7 topology proposal (§4.2.5) → Task 10 ✔
- fakes for testing (§10.2 adapted) → Task 11 ✔
- gate + explicit no-parity note → Task 12 ✔
- Gaps deliberately deferred and named: TransformXY, plan-maker context passing, Timer (P1b preview) ✔

**2. Placeholder scan:** two steps intentionally instruct verbatim copying from named legacy files with exact line ranges (Task 6 Steps 2/5) — the source text IS the content, and the ranges (`orch_dispatch.py:128-482`, `orch_global_params.py` whole file) are exact; every other code step carries complete code. "NOTE for the implementer" blocks are verification instructions against named files/lines, not deferred design.

**3. Type consistency:** `DispatchSnapshot` fields match between Task 6 (port) and Task 8 (`OrchestrationState.snapshot()`); `EstopFanout`/`FinishActiveEstopped` are defined once in Task 8 and imported by Task 10; `fold_status` returns `(OrchStatus, Tuple[commands])` consistently between Task 7 code and tests; `ensure_run_id`/`resolve_active_run_id` signatures match between Task 9 interfaces, code, and tests; port names in Task 11 fakes match the Protocol members of Tasks 3-4 (`enqueue_data`/`enqueue_data_nowait`/`get_realtime_nowait` mirror the legacy Active spelling used in `ports/data_sink.py`).

**Known verification points delegated to implementation** (each has an in-plan NOTE with the file to check): `ErrorCodes` member names (`in_progress`, `http_error`), `GlobalStatusModel.update_global_with_acts`/`find_hlostatus_in_finished` return shapes, pydantic fixture kwargs for `EndpointModel`/`ActionServerModel`, `%U` week pin, `-prc.yml` `file_type` key presence, `_mark_estopped` exact list surgery, sample-shim full method list. These are read-and-mirror checks, not design decisions.
