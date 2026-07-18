# P2b-1 — Native Write Runtime + Reroute Graft Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reimplement the four CARDS-P6 write collaborators (DataStreamer / DataFileWriter / ActionFinalizer / MetaFileWriter) as hexagon-native adapters in a new `helao/hexagon/adapters/native/` package, and reroute 100% of runtime write traffic onto them via an app-layer graft (`helao/hexagon/app/active_graft.py`) that instance-rebinds `base.contain_action` + `base.meta_writer` and swaps the three per-`Active` collaborators between `Active.__init__` and `myinit()` — with zero legacy edits and GM-1..GM-5 byte parity.

**Architecture:** The CARDS-P6 decomposition made every `base.py` write anchor a call-time-resolving delegator onto a stateless collaborator (`self.data_stream.log_data_task()` at `base.py:1223`, `self.data_file_writer.write_file(...)` at `base.py:1264`, `self.action_finalizer.finish(...)` at `base.py:1423`, `self.meta_writer.write_act(...)` at `base.py:689`), so a per-instance collaborator swap is a complete reroute. The native collaborator classes are **verbatim body copies** of the legacy collaborator modules (byte-parity by construction, enforced per-method by `inspect.getsource` parity tests), relocated into `adapters/native/` where the boundary test forbids `helao.core.servers.*` imports. Two port adapters (`NativeArtifactStoreAdapter` implementing `ArtifactStorePort`, `NativeDataSinkAdapter` implementing `DataSinkPort`) expose the native bodies through the P1a ports and are wired fail-loud into `build_wiring`/`ACTION_REQUIRED`. The graft mirrors `graft_hexagon_loop` (`dispatch_loop.py:171`): it reproduces `contain_action`'s 12-line body (drift-pinned by a test against `inspect.getsource(Base.contain_action)`) because the swap MUST land before `myinit()` spawns the `data_logger` task (`base.py:1014`).

**Tech Stack:** Python 3.12 (`conda run -n helao`), pytest (hexagon suite `helao/hexagon/tests/`), pyright (authoritative, `pyrightconfig.json`), black, aiofiles, the P0/P1b2a parity harness (`harness.capture` / `harness.parity`, `parity_run.sh`, `conc_run.sh`).

## Global Constraints

Every task's requirements implicitly include this section.

- **ZERO legacy edits**: never edit anything under `helao/core/`, `helao/helpers/`, or `helao/deploy/` (the hexagon deploy shim `helao/deploy/hexagon/` is also frozen in this plan). The reroute is graft/instance-rebind + hexagon-side code only.
- **No private-deployment names** anywhere in code, tests, docs, or commit messages (say "private deployments").
- **All Python via `conda run -n helao`** (never the OS python).
- **pyright `helao/hexagon` = 0 errors and `black` clean at the end of every task** (run black on changed files immediately before each commit).
- **Cache-nothing rule (the ce846da1 rule)**: native collaborators hold only the `active`/`base` back-reference and read `file_conn_dict` / `num_data_queued` / `num_data_written` / `action_list` / `listen_uuids` / `finish_lock` off the legacy `Active` at call time. Never cache a counter, list, or file handle on the native side.
- **No `Base` subclass, no `Active` subclass** in hexagon code; `adapters/native/` must not import `helao.core.servers.*` (boundary test enforces; the app-layer graft module is the sanctioned legacy-touching layer, same as `dispatch_loop.py`).
- **GM-1..GM-5 byte parity (0 diffs) is the gate**; test-first where byte parity is at risk (the finish join-before-close chain is the highest risk).
- **Q1 (binding)**: reproduce `contain_action`'s body in the app-layer graft with a drift-pinning test — NOT a `HexActive(Active)` subclass. Swap between `Active.__init__` and `myinit()`.
- **Q2 (binding)**: `append_sample` / `set_estop` / `add_status` stay legacy-delegated behind the native DataSink adapter. Native scope = the write/artifact bodies only.
- **Q3 (binding)**: per-action state stays on the legacy `Active`; native collaborators read at call time.
- **Keep-callable helpers**: `move_dir` (`helao/helpers/yml_tools.py`) and `zip_dir` (`helao/helpers/file_utils.py`) are called, never reimplemented. The `{}`-rejection-sentinel mapping stays exactly as `adapters/legacy/artifact_store.py:101-105` handles it.
- **Syncer quirks are P2c, not P2b**: the `technique_name` list→str split and the FileInfo S3-meta rename live in `sync_driver.py:1275,1534-1539`; do not touch or replicate them.
- **Do NOT commit or push to `main`; work stays on the hexagon working branch off `unstable`. No writes to production paths.**

## Why "verbatim copy + source-parity test" instead of retyped bodies

The four collaborator modules total ~1,300 lines of byte-parity-critical logic whose value is *exactness*, not novelty. Retyping them into this plan risks transcription drift — the precise failure class this phase must avoid. Each copy task therefore specifies: (a) the exact source file to copy, (b) the complete text of every edit made to the copy (module docstring, class rename, `__all__`), and (c) a **source-parity test** asserting `inspect.getsource(NativeX.method) == inspect.getsource(LegacyX.method)` for every relocated method — which both proves the copy is exact and pins against future legacy drift. Behavior tests on real tmp trees (no file-I/O fakes) cover the §5.4 quirk checklist independently, so they survive P3's eventual legacy deletion (when the source-parity tests are retired with the legacy modules).

## File structure

```
helao/hexagon/adapters/native/
    __init__.py            # package marker + exports (Task 2..8 grow it)
    meta_writer.py         # NativeMetaFileWriter   (copy of core/servers/base_meta_writer.py)
    data_file.py           # NativeDataFileWriter   (copy of core/servers/active_data_file.py)
    data_stream.py         # NativeDataStreamer     (copy of core/servers/active_data_stream.py)
    finalizer.py           # NativeActionFinalizer  (copy of core/servers/active_finalizer.py)
    artifact_store.py      # NativeArtifactStoreAdapter (ArtifactStorePort) + collaborators_for/meta_writer_for
    data_sink.py           # NativeDataSinkAdapter  (DataSinkPort; Q2 members legacy-delegated)
helao/hexagon/app/
    active_graft.py        # graft_active_write_path + ActiveWriteGraft (mirror of dispatch_loop graft)
    factory.py             # MODIFY: build_wiring wires native adapters; makeActionApp startup/shutdown graft hooks
    wiring.py              # MODIFY: ACTION_REQUIRED grows artifact_store, data_sink
helao/hexagon/tests/
    test_boundaries.py     # MODIFY: adapters/native/ may not import helao.core.servers.*
    native_fixtures.py     # shared Base.__new__ / Action / Active fixtures (tests layer)
    test_native_meta_writer.py
    test_native_data_file.py
    test_native_data_stream.py
    test_native_finalizer.py
    test_native_artifact_store.py
    test_native_data_sink.py
    test_active_graft.py   # drift-pin + honesty tripwire + in-process end-to-end
    test_wiring.py         # MODIFY (if it asserts ACTION_REQUIRED contents)
    test_factory.py        # MODIFY: makeActionApp graft-hook assertions
```

Task labels: **[PYTEST]** = pure in-process, subagent-executable. **[LAUNCHED — MAIN SESSION ONLY]** = launches a real server group; must run in the main session (subagent background launches get reaped on idle); uses the `parity_run.sh` / `conc_run.sh` patterns.

---

### Task 1: Boundary rule — `adapters/native/` never imports `helao.core.servers.*` [PYTEST]

Land the guard first so every later task is written under it.

**Files:**
- Modify: `helao/hexagon/tests/test_boundaries.py`

**Interfaces:**
- Consumes: `iter_violations`, `_walk_layer`, `_allowed` in `test_boundaries.py` (existing).
- Produces: `_allowed(module, layer)` gains a `native-adapters` sub-rule; new tests `test_native_adapters_never_import_core_servers`, `test_checker_flags_native_importing_core_servers`. Later tasks rely on: files under `helao/hexagon/adapters/native/` may import `helao.helpers.*`, `helao.core.models.*`, `helao.core.error`, vendors (aiofiles, numpy) — but never `helao.core.servers.*`, `helao.hexagon.app`, or `helao.hexagon.tests`.

- [ ] **Step 1: Write the failing (mutation-style) test**

Append to `helao/hexagon/tests/test_boundaries.py`:

```python
def test_checker_flags_native_importing_core_servers(tmp_path):
    """Mutation self-test (P2b-1): adapters/native/ is the hexagon-owned
    write runtime — unlike adapters/legacy it must NOT wrap legacy server
    classes. helao.core.servers.* is banned there (models/helpers stay
    allowed: the native bodies are byte-copies of the collaborator modules,
    which import helao.core.models + helao.helpers only)."""
    native_dir = HEXAGON_ROOT / "adapters" / "native"
    native_dir.mkdir(exist_ok=True)
    (native_dir / "__init__.py").touch()
    victim = native_dir / "_boundary_selftest_tmp.py"
    victim.write_text(
        "import aiofiles\n"  # vendor allowed
        "from helao.helpers.yml_tools import yml_dumps\n"  # helpers allowed
        "from helao.core.models.run_dir import RunDir\n"  # models allowed
        "from helao.core.servers.base import Base\n"  # BANNED in native
        "from helao.core.servers.active_finalizer import ActionFinalizer\n"  # BANNED
    )
    try:
        hits = iter_violations(victim)
        assert {m for _, m, _ in hits} == {
            "helao.core.servers.base",
            "helao.core.servers.active_finalizer",
        }
    finally:
        victim.unlink()


def test_native_adapters_never_import_core_servers():
    d = HEXAGON_ROOT / "adapters" / "native"
    files = sorted(d.rglob("*.py")) if d.is_dir() else []
    bad = [v for f in files for v in iter_violations(f)]
    assert not bad, f"native-adapter boundary violations: {bad}"
```

- [ ] **Step 2: Run to verify it fails**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_boundaries.py -q`
Expected: `test_checker_flags_native_importing_core_servers` FAILS (the checker does not yet flag `helao.core.servers.base` — current adapters rule allows all legacy imports; the assert on the hit set fails with an empty set).

- [ ] **Step 3: Implement the rule**

In `test_boundaries.py`, extend `_layer_of` and `_allowed`. Replace the existing `_layer_of` with:

```python
def _layer_of(pyfile: Path) -> str:
    rel = pyfile.resolve().relative_to(HEXAGON_ROOT)
    if len(rel.parts) > 2 and rel.parts[0] == "adapters" and rel.parts[1] == "native":
        return "adapters-native"
    return rel.parts[0] if len(rel.parts) > 1 else "root"
```

In `_allowed`, insert this branch immediately before the existing `if layer == "adapters":` branch:

```python
    if layer == "adapters-native":
        # P2b-1: the native write runtime. Same bans as adapters/ (never
        # app, never tests) PLUS helao.core.servers.* — the native bodies
        # own the write logic; only the app-layer graft touches legacy
        # server classes.
        return not (
            module == f"{HEXAGON_PKG}.app"
            or module.startswith(f"{HEXAGON_PKG}.app.")
            or module == f"{HEXAGON_PKG}.tests"
            or module.startswith(f"{HEXAGON_PKG}.tests.")
            or module == "helao.core.servers"
            or module.startswith("helao.core.servers.")
        )
```

Also create the package now so the walk is non-vacuous:

```bash
mkdir -p helao/hexagon/adapters/native
```

`helao/hexagon/adapters/native/__init__.py`:

```python
"""Hexagon-native adapters (P2b-1): the first non-legacy, non-fake adapter
family. Bodies are verbatim copies of the CARDS-P6 write collaborators
(source-parity-pinned); they read all per-action state off the legacy
``Active``/``Base`` back-reference at call time (cache-nothing rule) and
never import ``helao.core.servers.*`` (boundary-enforced)."""
```

- [ ] **Step 4: Run to verify it passes**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_boundaries.py -q`
Expected: ALL PASS (including all pre-existing boundary tests — the `adapters-native` layer only strengthens).

- [ ] **Step 5: pyright + black + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/tests/test_boundaries.py helao/hexagon/adapters/native/__init__.py
git add helao/hexagon/tests/test_boundaries.py helao/hexagon/adapters/native/__init__.py
git commit -m "test(hexagon): boundary rule — adapters/native never imports helao.core.servers (P2b-1 T1)"
```

---

### Task 2: Shared native-test fixtures + `NativeMetaFileWriter` [PYTEST]

**Files:**
- Create: `helao/hexagon/tests/native_fixtures.py`
- Create: `helao/hexagon/adapters/native/meta_writer.py`
- Modify: `helao/hexagon/adapters/native/__init__.py`
- Test: `helao/hexagon/tests/test_native_meta_writer.py`

**Interfaces:**
- Consumes: legacy `MetaFileWriter` (`helao/core/servers/base_meta_writer.py:48-172`) as the copy source; `Base.__new__` fixture pattern from `helao/core/tests/unit_test_active_data_file.py:52-66`.
- Produces (later tasks rely on these exact names):
  - `native_fixtures.make_base(save_root: str) -> Base` — bare `Base` via `Base.__new__` with `app`, `server`, `world_cfg`, `ntp_offset`, `helaodirs`, `status_q`, `data_q`, `actives`, `history`, `local_action_task_queue`, `hlo_postprocessors`, `hlo_postprocess_libs`, then `_init_collaborators()`.
  - `native_fixtures.mk_action(**overrides) -> Action` — deterministic non-manual action, `save_data=True`.
  - `native_fixtures.mk_active(base, json_data_keys=None, action=None) -> tuple[Active, UUID]` — legacy `Active` + its default file-conn key.
  - `native_fixtures.assert_source_parity(native_cls, legacy_cls, methods: list[str])` — per-method `inspect.getsource` equality helper.
  - `NativeMetaFileWriter(base)` in `helao.hexagon.adapters.native.meta_writer` with the exact legacy `MetaFileWriter` surface: `_write_meta_atomic(output_file, output_str)`, `write_act(action)`, `write_exp(experiment)`, `write_seq(sequence)`, `new_file_conn_key(key) -> UUID`, `dflt_file_conn_key() -> UUID`.

- [ ] **Step 1: Write the fixtures module**

`helao/hexagon/tests/native_fixtures.py` (complete file):

```python
"""Shared fixtures for the P2b-1 native-adapter tests.

Mirrors the ``Base.__new__`` bypass fixture proven by
``helao/core/tests/unit_test_active_data_file.py`` (`_make_base`/`_mk_action`):
a bare ``Base`` built without ``Base.__init__`` (no FastAPI app, no NTP, no
WebSockets), populated with every attribute the Active construction + the
write collaborators + the graft touch, then ``_init_collaborators()``.

Tests layer — may import anything (boundary rule)."""

import inspect
from datetime import datetime
from types import SimpleNamespace
from uuid import UUID

from helao.core.servers.base import Base, Active
from helao.core.models.file import FileConnParams, HloFileGroup
from helao.core.models.machine import MachineModel
from helao.helpers.active_params import ActiveParams
from helao.helpers.multisubscriber_queue import MultisubscriberQueue
from helao.helpers.premodels import Action

FIXED_DT = datetime(2026, 1, 2, 3, 4, 5, 678901)


def make_base(save_root: str) -> Base:
    """Bare ``Base`` with every attribute Active construction + the write
    path (myinit/log_data_task/finish/meta writers) touches."""
    base = Base.__new__(Base)
    base.app = SimpleNamespace(driver=None)
    base.server = MachineModel(
        server_name="ACTSRV",
        machine_name="test-machine",
        hostname="127.0.0.1",
        port=8000,
    )
    base.world_cfg = {"dummy": False, "simulation": False}
    base.ntp_offset = 0.0
    base.helaodirs = SimpleNamespace(save_root=save_root)
    base.status_q = MultisubscriberQueue()
    base.data_q = MultisubscriberQueue()
    base.actives = {}
    base.history = {}
    base.local_action_task_queue = []
    base.hlo_postprocessors = []
    base.hlo_postprocess_libs = []
    base._init_collaborators()
    return base


def mk_action(**overrides) -> Action:
    """Deterministic non-manual Action with data saving enabled."""
    kwargs = dict(
        action_name="nutest",
        action_abbr="nute",
        orch_key="ORCH",
        orch_host="127.0.0.1",
        orch_port=8001,
        action_uuid=UUID("00000000-0000-0000-0000-0000000000a1"),
        action_timestamp=FIXED_DT,
        sequence_uuid=UUID("00000000-0000-0000-0000-0000000000b1"),
        sequence_name="seq_nu",
        sequence_label="p2b1",
        sequence_timestamp=FIXED_DT,
        experiment_uuid=UUID("00000000-0000-0000-0000-0000000000c1"),
        experiment_name="exp_nu",
        experiment_timestamp=FIXED_DT,
        save_data=True,
    )
    kwargs.update(overrides)
    return Action(**kwargs)


def mk_active(base: Base, json_data_keys=None, action=None):
    """Legacy Active + its default file-conn key (collaborators still legacy;
    tests swap in the native class under test explicitly)."""
    if action is None:
        action = mk_action()
    dflt = base.dflt_file_conn_key()
    ap = ActiveParams(
        action=action,
        file_conn_params_dict={
            dflt: FileConnParams(
                file_conn_key=dflt,
                json_data_keys=json_data_keys or ["t_s", "value"],
                file_type="nu__test_file",
                file_group=HloFileGroup.helao_files,
            )
        },
        aux_listen_uuids=[],
    )
    return Active(base, ap), dflt


def assert_source_parity(native_cls, legacy_cls, methods):
    """Byte-parity pin: each relocated method's source must be identical to
    its legacy counterpart (methods contain no class-name references, so
    straight equality holds for a verbatim copy)."""
    diffs = []
    for name in methods:
        n_src = inspect.getsource(getattr(native_cls, name))
        l_src = inspect.getsource(getattr(legacy_cls, name))
        if n_src != l_src:
            diffs.append(name)
    assert not diffs, f"native methods drifted from legacy source: {diffs}"
```

- [ ] **Step 2: Write the failing tests**

`helao/hexagon/tests/test_native_meta_writer.py` (complete file):

```python
"""NativeMetaFileWriter (P2b-1): verbatim re-body of legacy MetaFileWriter
(helao/core/servers/base_meta_writer.py). Source-parity-pinned + behavior
checks on a real tmp tree (atomic tmp+os.replace, trailing newline,
file_type first key, RUNS_ACTIVE->RUNS_DIAG manual swap, md5 conn keys)."""

import os
import asyncio
from uuid import UUID

import pytest

from helao.core.servers.base_meta_writer import MetaFileWriter
from helao.core.models.run_dir import RunDir
from helao.hexagon.adapters.native.meta_writer import NativeMetaFileWriter
from helao.hexagon.tests.native_fixtures import (
    make_base,
    mk_action,
    assert_source_parity,
)

METHODS = [
    "__init__",
    "_write_meta_atomic",
    "write_act",
    "write_exp",
    "write_seq",
    "new_file_conn_key",
    "dflt_file_conn_key",
]


def test_source_parity_with_legacy():
    assert_source_parity(NativeMetaFileWriter, MetaFileWriter, METHODS)


def _swap(base, tmp_path):
    base.meta_writer = NativeMetaFileWriter(base)
    return base


@pytest.mark.asyncio
async def test_write_act_layout(tmp_path):
    save_root = str(tmp_path / "RUNS_ACTIVE")
    base = _swap(make_base(save_root), tmp_path)
    action = mk_action(save_act=True)
    await base.write_act(action)
    out_dir = os.path.join(save_root, str(action.action_output_dir))
    files = [f for f in os.listdir(out_dir) if f.endswith("-act.yml")]
    assert files == ["260102.030405678901-act.yml"]
    text = open(os.path.join(out_dir, files[0])).read()
    assert text.startswith("file_type: action\n")  # file_type first key
    assert text.endswith("\n")  # trailing newline
    assert not [f for f in os.listdir(out_dir) if f.endswith(".tmp")]


@pytest.mark.asyncio
async def test_write_meta_atomic_tmp_shape(tmp_path):
    """Atomic write goes through .<basename>.<uuid1hex>.tmp then os.replace
    (base_meta_writer.py:76-79)."""
    base = _swap(make_base(str(tmp_path)), tmp_path)
    seen = {}
    real_replace = os.replace

    def spy(src, dst):
        seen["src"], seen["dst"] = src, dst
        return real_replace(src, dst)

    import helao.hexagon.adapters.native.meta_writer as mw

    orig = mw.os.replace
    mw.os.replace = spy
    try:
        target = str(tmp_path / "sub" / "x-act.yml")
        await base.meta_writer._write_meta_atomic(target, "k: v")
    finally:
        mw.os.replace = orig
    assert seen["dst"] == target
    tmp_base = os.path.basename(seen["src"])
    assert tmp_base.startswith(".x-act.yml.") and tmp_base.endswith(".tmp")
    assert open(target).read() == "k: v\n"


@pytest.mark.asyncio
async def test_manual_action_diag_swap(tmp_path):
    save_root = str(tmp_path / RunDir.ACTIVE.value)
    diag_root = str(tmp_path / RunDir.DIAG.value)
    base = _swap(make_base(save_root), tmp_path)
    action = mk_action(save_act=True, manual_action=True, run_type="manual")
    await base.write_act(action)
    out_dir = os.path.join(diag_root, str(action.action_output_dir))
    assert os.path.isdir(out_dir)
    assert [f for f in os.listdir(out_dir) if f.endswith("-act.yml")]


@pytest.mark.asyncio
async def test_write_exp_and_seq(tmp_path):
    save_root = str(tmp_path / "RUNS_ACTIVE")
    base = _swap(make_base(save_root), tmp_path)
    action = mk_action()
    await base.write_exp(action)
    await base.write_seq(action)
    exp_dir = os.path.join(save_root, str(action.get_experiment_dir()))
    seq_dir = os.path.join(save_root, str(action.get_sequence_dir()))
    assert [f for f in os.listdir(exp_dir) if f.endswith("-exp.yml")]
    assert [f for f in os.listdir(seq_dir) if f.endswith("-seq.yml")]
    exp_text = open(
        os.path.join(exp_dir, [f for f in os.listdir(exp_dir) if f.endswith("-exp.yml")][0])
    ).read()
    assert exp_text.startswith("file_type: experiment\n")


def test_conn_keys_md5(tmp_path):
    base = make_base(str(tmp_path))
    native = NativeMetaFileWriter(base)
    base.meta_writer = native
    assert native.dflt_file_conn_key() == UUID("6adf97f83acf6453d4a6a4b1070f3754")
    assert native.new_file_conn_key("abc") == UUID("900150983cd24fb0d6963f7d28e17f72")
```

Note: `experiment.get_experiment_dir()` / `sequence.get_sequence_dir()` are `Action` methods via premodels inheritance — `mk_action()` returns an `Action`, which legacy `write_exp`/`write_seq` accept in the manual-action path (`active_finalizer.py:505-507` passes the synthesized `Action` copy). If pyright flags the `Action`-for-`Experiment` argument, the tests may `# type: ignore[arg-type]` (test layer only).

- [ ] **Step 3: Run to verify failure**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_native_meta_writer.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'helao.hexagon.adapters.native.meta_writer'`.

- [ ] **Step 4: Create the native module (verbatim copy + pinned edits)**

```bash
cp helao/core/servers/base_meta_writer.py helao/hexagon/adapters/native/meta_writer.py
```

Then apply EXACTLY these edits to the copy (nothing else — the source-parity test fails on any body change):

1. Replace the module docstring (everything from the opening `"""Meta-file-writer collaborator...` through the closing `"""` before the imports) with:

```python
"""Native meta-yml writer (hexagon P2b-1).

Verbatim re-body of the CARDS-P6 ``MetaFileWriter`` collaborator
(``helao/core/servers/base_meta_writer.py``): the atomic
temp-file-then-``os.replace`` write, the three ``write_act``/``write_exp``/
``write_seq`` writers (``file_type`` first key, trailing newline,
RUNS_ACTIVE->RUNS_DIAG swap for manual), and the file-connection-key
helpers. Method bodies are byte-identical to legacy (source-parity-pinned by
``test_native_meta_writer.py``); only this docstring, the class name, and
``__all__`` differ.

Holds only the ``base`` back-reference and reads ``helaodirs`` etc. through
it at call time (cache-nothing rule). Installed per-Base by
``helao.hexagon.app.active_graft.graft_active_write_path`` as a drop-in for
``base.meta_writer`` — the ``Base`` delegators (``base.py:666-716``) resolve
``self.meta_writer`` at call time, so the swap reroutes ``write_act``/
``write_exp``/``write_seq``/``_write_meta_atomic``/``new_file_conn_key``/
``dflt_file_conn_key`` in one assignment.
"""
```

2. Rename the class line `class MetaFileWriter:` → `class NativeMetaFileWriter:` and replace its class docstring (the triple-quoted block directly under the class line, ending before `def __init__`) with:

```python
    """Native drop-in for ``base.meta_writer`` (legacy surface, native body).

    Holds only the ``base`` back-reference (never cached path/dir state),
    per the call-time state resolution rule -- see module docstring.
    """
```

3. After the `LOGGER = ...` line, add:

```python
__all__ = ["NativeMetaFileWriter"]
```

Update `helao/hexagon/adapters/native/__init__.py` to end with:

```python
from helao.hexagon.adapters.native.meta_writer import NativeMetaFileWriter

__all__ = ["NativeMetaFileWriter"]
```

- [ ] **Step 5: Run to verify all pass (incl. boundary)**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_native_meta_writer.py helao/hexagon/tests/test_boundaries.py -q`
Expected: ALL PASS. (If `test_source_parity_with_legacy` fails, the copy was edited beyond the three pinned edits — re-copy.)

- [ ] **Step 6: pyright + black + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/adapters/native/ helao/hexagon/tests/native_fixtures.py helao/hexagon/tests/test_native_meta_writer.py
git add helao/hexagon/adapters/native/ helao/hexagon/tests/native_fixtures.py helao/hexagon/tests/test_native_meta_writer.py
git commit -m "feat(hexagon): NativeMetaFileWriter — source-parity-pinned re-body of MetaFileWriter (P2b-1 T2)"
```

CAUTION: if `black` reformats `meta_writer.py` differently from the legacy file, the source-parity test breaks. The legacy modules are already black-clean (project rule), so a verbatim copy is stable; if black nonetheless changes anything, STOP and report — do not hand-tune.

---

### Task 3: `NativeDataFileWriter` [PYTEST]

**Files:**
- Create: `helao/hexagon/adapters/native/data_file.py`
- Modify: `helao/hexagon/adapters/native/__init__.py`
- Test: `helao/hexagon/tests/test_native_data_file.py`

**Interfaces:**
- Consumes: legacy `DataFileWriter` (`helao/core/servers/active_data_file.py:69-449`) as copy source; `native_fixtures.make_base/mk_action/mk_active/assert_source_parity` (Task 2).
- Produces: `NativeDataFileWriter(active)` in `helao.hexagon.adapters.native.data_file` with the exact legacy surface: `update_act_file()`, `init_datafile(header, file_type, json_data_keys, file_sample_label, filename, file_group, file_conn_key=None, action=None) -> tuple`, `finish_hlo_header(file_conn_keys=None, realtime=None)`, `log_data_set_output_file(file_conn_key)`, `_resolve_output_path(file_type, filename, file_group, header, file_sample_label, json_data_keys, action)`, `write_file(...) -> Optional[str]`, `write_file_nowait(...) -> Optional[str]`, `track_file(file_type, file_path, samples, action=None)`, `relocate_files()`.

- [ ] **Step 1: Write the failing tests**

`helao/hexagon/tests/test_native_data_file.py` (complete file):

```python
"""NativeDataFileWriter (P2b-1): verbatim re-body of legacy DataFileWriter
(helao/core/servers/active_data_file.py). Source-parity pin + real-tmp-tree
behavior checks for the §5.4 quirks: w+ truncate-on-create, filename autogen
format, one-shot a+ header+%%+payload, save_data gate, posix
PureWindowsPath+.strip("\\\\") path quirk, FileInfo recording."""

import os

import pytest

from helao.core.servers.active_data_file import DataFileWriter
from helao.core.models.file import HloFileGroup
from helao.hexagon.adapters.native.data_file import NativeDataFileWriter
from helao.hexagon.tests.native_fixtures import (
    make_base,
    mk_action,
    mk_active,
    assert_source_parity,
)

METHODS = [
    "__init__",
    "update_act_file",
    "init_datafile",
    "finish_hlo_header",
    "log_data_set_output_file",
    "_resolve_output_path",
    "write_file",
    "write_file_nowait",
    "track_file",
    "relocate_files",
]


def test_source_parity_with_legacy():
    assert_source_parity(NativeDataFileWriter, DataFileWriter, METHODS)


def _native_active(tmp_path, **action_over):
    base = make_base(str(tmp_path / "RUNS_ACTIVE"))
    active, dflt = mk_active(base, action=mk_action(**action_over) if action_over else None)
    active.data_file_writer = NativeDataFileWriter(active)  # the swap under test
    return base, active, dflt


def test_init_datafile_autogen_filename(tmp_path):
    _, active, dflt = _native_active(tmp_path)
    header, file_info = active.init_datafile(
        header={"a": 1},
        file_type="nu__test_file",
        json_data_keys=["t_s"],
        file_sample_label=None,
        filename=None,
        file_group=HloFileGroup.helao_files,
        file_conn_key=dflt,
    )
    a = active.action
    assert (
        file_info.file_name
        == f"{a.action_abbr}-{a.orch_submit_order}.{a.action_order}.{a.action_retry}.{a.action_split}__0.hlo"
    )
    assert header.endswith("\n")
    assert file_info.data_keys == ["t_s"]


def test_init_datafile_empty_header_variants(tmp_path):
    _, active, _ = _native_active(tmp_path)
    for hdr in ({}, [], None):
        header, _ = active.init_datafile(
            header=hdr,
            file_type="t",
            json_data_keys=None,
            file_sample_label=None,
            filename="x.csv",
            file_group=HloFileGroup.aux_files,
        )
        assert header == ""  # {} must NOT become "{}\n"


@pytest.mark.asyncio
async def test_log_data_set_output_file_truncates_stale_bytes(tmp_path):
    """w+ open: stale crash bytes must not survive ahead of the header
    (active_data_file.py:264-272 rationale comment)."""
    base, active, dflt = _native_active(tmp_path)
    out_dir = os.path.join(
        str(base.helaodirs.save_root), str(active.action.action_output_dir)
    )
    os.makedirs(out_dir, exist_ok=True)
    a = active.action
    fname = f"{a.action_abbr}-{a.orch_submit_order}.{a.action_order}.{a.action_retry}.{a.action_split}__0.hlo"
    stale = os.path.join(out_dir, fname)
    open(stale, "w").write("STALE-CRASH-BYTES\n")
    active.file_conn_dict[dflt].params.hloheader.epoch_ns = 1234567890
    await active.log_data_set_output_file(file_conn_key=dflt)
    await active.file_conn_dict[dflt].file.close()
    text = open(stale).read()
    assert "STALE-CRASH-BYTES" not in text
    assert "epoch_ns: 1234567890" in text
    assert active.action.files and active.action.files[-1].file_name == fname


@pytest.mark.asyncio
async def test_write_file_one_shot_layout_and_gate(tmp_path):
    base, active, _ = _native_active(tmp_path)
    path = await active.write_file(
        output_str="r1,r2",
        file_type="aux__csv",
        filename="one.csv",
        header="colA,colB",
    )
    assert path is not None and path.endswith("one.csv")
    assert open(path).read() == "colA,colB\n%%\nr1,r2"
    assert any(fi.file_name == "one.csv" for fi in active.action.files)
    # append mode a+ (not w+): a second write appends
    await active.write_file(
        output_str="r3", file_type="aux__csv", filename="one.csv"
    )
    assert open(path).read() == "colA,colB\n%%\nr1,r2%%\nr3"
    # save_data gate
    active.action.save_data = False
    assert (
        await active.write_file(output_str="x", file_type="t", filename="no.csv")
        is None
    )
    assert not os.path.exists(os.path.join(os.path.dirname(path), "no.csv"))


def test_write_file_nowait_matches_async_layout(tmp_path):
    base, active, _ = _native_active(tmp_path)
    path = active.write_file_nowait(
        output_str="r1", file_type="aux__csv", filename="two.csv", header="h"
    )
    assert path is not None
    assert open(path).read() == "h\n%%\nr1"


def test_resolve_output_path_posix_strip_quirk(tmp_path):
    """posix branch: PureWindowsPath normalization + .strip("\\\\")
    (active_data_file.py:313-316) — byte-copied, not 'fixed'."""
    base, active, _ = _native_active(tmp_path)
    result = active._resolve_output_path(
        file_type="t",
        filename="f.csv",
        file_group=HloFileGroup.aux_files,
        header=None,
        file_sample_label=None,
        json_data_keys=None,
        action=active.action,
    )
    assert result is not None
    _, _, _, output_file = result
    assert "\\" not in output_file  # windows seps collapsed on posix


@pytest.mark.asyncio
async def test_finish_hlo_header_stamps_only_unset(tmp_path):
    base, active, dflt = _native_active(tmp_path)
    active.file_conn_dict[dflt].params.hloheader.epoch_ns = None
    active.finish_hlo_header(realtime=42)
    assert active.file_conn_dict[dflt].params.hloheader.epoch_ns == 42
    active.finish_hlo_header(realtime=99)
    assert active.file_conn_dict[dflt].params.hloheader.epoch_ns == 42  # not re-stamped
```

- [ ] **Step 2: Run to verify failure**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_native_data_file.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'helao.hexagon.adapters.native.data_file'`.

- [ ] **Step 3: Create the native module (verbatim copy + pinned edits)**

```bash
cp helao/core/servers/active_data_file.py helao/hexagon/adapters/native/data_file.py
```

Apply EXACTLY these edits:

1. Replace the module docstring with:

```python
"""Native data-file writer (hexagon P2b-1).

Verbatim re-body of the CARDS-P6 ``DataFileWriter`` collaborator
(``helao/core/servers/active_data_file.py``): action-meta refresh, HLO/aux
header + ``FileInfo`` builder, the streamed-file opener (``w+``
truncate-on-create), the one-shot writers (``a+``, header + ``%%\\n`` +
payload, FileInfo appended at write, ``save_data`` gate), the
nt/posix ``_resolve_output_path`` quirk (incl. ``.strip("\\\\")`` — byte-copied,
not "fixed"), and the aux-file trackers/relocators. Method bodies are
byte-identical to legacy (source-parity-pinned by
``test_native_data_file.py``); only this docstring, the class name, and
``__all__`` differ.

Per-Active collaborator: holds only the ``active`` back-reference and reads
``file_conn_dict``/``action``/``action_list``/``base`` at call time
(cache-nothing rule). Swapped in for ``active.data_file_writer`` by
``graft_active_write_path`` between ``Active.__init__`` and ``myinit()``;
the ``Active`` delegators (``base.py:1208-1299,1432-1455``) resolve the
attribute at call time, so the swap reroutes every file-init/one-shot call.
"""
```

2. `class DataFileWriter:` → `class NativeDataFileWriter:`; replace its class docstring with:

```python
    """Native drop-in for ``active.data_file_writer`` (legacy surface, native body).

    Holds only the ``active`` back-reference (never cached path/conn state),
    per the call-time state resolution rule -- see module docstring.
    """
```

3. After the `LOGGER = ...` line, add:

```python
__all__ = ["NativeDataFileWriter"]
```

Append to `helao/hexagon/adapters/native/__init__.py`:

```python
from helao.hexagon.adapters.native.data_file import NativeDataFileWriter

__all__ = ["NativeMetaFileWriter", "NativeDataFileWriter"]
```

(Keep a single `__all__` assignment at the bottom of the file — replace the previous one.)

- [ ] **Step 4: Run to verify pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_native_data_file.py helao/hexagon/tests/test_boundaries.py -q`
Expected: ALL PASS.

- [ ] **Step 5: pyright + black + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/adapters/native/ helao/hexagon/tests/test_native_data_file.py
git add helao/hexagon/adapters/native/ helao/hexagon/tests/test_native_data_file.py
git commit -m "feat(hexagon): NativeDataFileWriter — source-parity-pinned re-body of DataFileWriter (P2b-1 T3)"
```

---

### Task 4: `NativeDataStreamer` [PYTEST]

**Files:**
- Create: `helao/hexagon/adapters/native/data_stream.py`
- Modify: `helao/hexagon/adapters/native/__init__.py`
- Test: `helao/hexagon/tests/test_native_data_stream.py`

**Interfaces:**
- Consumes: legacy `DataStreamer` (`helao/core/servers/active_data_stream.py:83-286`) as copy source; Task 2 fixtures; Task 3 `NativeDataFileWriter` (the drain loop's lazy-open hops through `active.log_data_set_output_file`).
- Produces: `NativeDataStreamer(active)` in `helao.hexagon.adapters.native.data_stream` with the exact legacy surface: `get_realtime(epoch_ns=None, offset=None)`, `get_realtime_nowait(epoch_ns=None, offset=None)`, `write_live_data(output_str, file_conn_key)`, `enqueue_data_dflt(datadict)`, `_build_data_package(datamodel, action=None) -> tuple`, `enqueue_data(datamodel, action=None)`, `enqueue_data_nowait(datamodel, action=None)`, `assemble_data_msg(datamodel, action=None) -> DataPackageModel`, `add_new_listen_uuid(new_uuid)`, `log_data_task()`.

- [ ] **Step 1: Write the failing tests**

`helao/hexagon/tests/test_native_data_stream.py` (complete file):

```python
"""NativeDataStreamer (P2b-1): verbatim re-body of legacy DataStreamer
(helao/core/servers/active_data_stream.py). Source-parity pin + drain-loop
behavior on a real MultisubscriberQueue + tmp tree: lazy open on first
matching packet, json_data_keys inference, %% exactly once, non-serializable
-> error line, string payload raw, listen_uuids filter, queued/written
counters live on Active, cancel removes the data_q subscription."""

import asyncio
import os
from uuid import uuid4

import pytest

from helao.core.servers.active_data_stream import DataStreamer
from helao.core.models.data import DataModel
from helao.core.models.hlostatus import HloStatus
from helao.hexagon.adapters.native.data_file import NativeDataFileWriter
from helao.hexagon.adapters.native.data_stream import NativeDataStreamer
from helao.hexagon.tests.native_fixtures import make_base, mk_active

METHODS = [
    "__init__",
    "get_realtime",
    "get_realtime_nowait",
    "write_live_data",
    "enqueue_data_dflt",
    "_build_data_package",
    "enqueue_data",
    "enqueue_data_nowait",
    "assemble_data_msg",
    "add_new_listen_uuid",
    "log_data_task",
]


def test_source_parity_with_legacy():
    from helao.hexagon.tests.native_fixtures import assert_source_parity

    assert_source_parity(NativeDataStreamer, DataStreamer, METHODS)


def _native_active(tmp_path):
    base = make_base(str(tmp_path / "RUNS_ACTIVE"))
    active, dflt = mk_active(base)
    # mini-graft: both write collaborators native (the drain loop hops
    # active.log_data_set_output_file -> data_file_writer)
    active.data_stream = NativeDataStreamer(active)
    active.data_file_writer = NativeDataFileWriter(active)
    return base, active, dflt


@pytest.mark.asyncio
async def test_enqueue_counts_only_data_bearing(tmp_path):
    base, active, dflt = _native_active(tmp_path)
    await active.enqueue_data(DataModel(data={dflt: {"t_s": 1}}, errors=[]))
    await active.enqueue_data(
        DataModel(data={}, errors=[], status=HloStatus.finished)
    )
    active.enqueue_data_nowait(DataModel(data={dflt: {"t_s": 2}}, errors=[]))
    assert active.num_data_queued == 2  # empty-data packet doesn't count


@pytest.mark.asyncio
async def test_drain_loop_lazy_open_separator_and_rows(tmp_path):
    base, active, dflt = _native_active(tmp_path)
    task = asyncio.get_running_loop().create_task(active.log_data_task())
    await asyncio.sleep(0.05)
    out_dir = os.path.join(
        str(base.helaodirs.save_root), str(active.action.action_output_dir)
    )
    # NO DATA => NO FILE (lazy-open contract, F2a)
    assert not os.path.isdir(out_dir) or not os.listdir(out_dir)

    await active.enqueue_data(DataModel(data={dflt: {"t_s": 1, "value": 2.5}}, errors=[]))
    await active.enqueue_data(DataModel(data={dflt: {"t_s": 2, "value": set()}}, errors=[]))  # not serializable
    await active.enqueue_data(DataModel(data={dflt: "raw-string-row"}, errors=[]))
    await asyncio.sleep(0.2)

    assert active.num_data_written == 3
    task.cancel()
    await asyncio.sleep(0.05)
    hlo = [f for f in os.listdir(out_dir) if f.endswith(".hlo")]
    assert len(hlo) == 1
    text = open(os.path.join(out_dir, hlo[0])).read()
    assert text.count("%%\n") == 1  # separator exactly once
    body = text.split("%%\n", 1)[1]
    lines = body.splitlines()
    # hlo_json_dumps uses compact separators (verified: no spaces)
    assert lines[0] == '{"t_s":1,"value":2.5}'
    assert lines[1] == '{"error":"data was not serializable"}'
    assert lines[2] == "raw-string-row"
    # subscription removed on cancel
    assert len(base.data_q.subscribers) == 0


@pytest.mark.asyncio
async def test_drain_loop_filters_foreign_uuids_and_nonactive_status(tmp_path):
    base, active, dflt = _native_active(tmp_path)
    task = asyncio.get_running_loop().create_task(active.log_data_task())
    await asyncio.sleep(0.05)
    foreign = DataModel(data={dflt: {"t_s": 9}}, errors=[])
    # a packet whose action_uuid is not in listen_uuids must be skipped
    msg = active.assemble_data_msg(datamodel=foreign)
    msg.action_uuid = uuid4()
    await base.data_q.put(msg)
    # finished-status packet must be skipped for writing
    await active.enqueue_data(
        DataModel(data={}, errors=[], status=HloStatus.finished)
    )
    await asyncio.sleep(0.2)
    assert active.num_data_written == 0
    task.cancel()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_save_data_false_no_logger(tmp_path):
    base = make_base(str(tmp_path / "RUNS_ACTIVE"))
    active, _ = mk_active(base)
    active.action.save_data = False
    active.data_stream = NativeDataStreamer(active)
    await active.log_data_task()  # returns immediately, no subscription
    assert len(base.data_q.subscribers) == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_native_data_stream.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'helao.hexagon.adapters.native.data_stream'`.

- [ ] **Step 3: Create the native module (verbatim copy + pinned edits)**

```bash
cp helao/core/servers/active_data_stream.py helao/hexagon/adapters/native/data_stream.py
```

Apply EXACTLY these edits:

1. Replace the module docstring with:

```python
"""Native data streamer (hexagon P2b-1).

Verbatim re-body of the CARDS-P6 ``DataStreamer`` collaborator
(``helao/core/servers/active_data_stream.py``): realtime-clock forwarders,
live-data appender, the ``enqueue_data*`` -> ``data_q`` publish path (queued
counter bumped only for data-bearing packets), and the ``log_data_task``
drain loop — subscribe, listen-uuid filter, LAZY file open on the first
matching packet (json_data_keys inferred from the first row when unset),
``%%`` separator exactly once via ``added_hlo_separator``, ``hlo_json_dumps``
rows, non-serializable payload -> ``{"error": "data was not serializable"}``,
string payloads written raw, ``num_data_written`` bump per data-bearing
packet, subscription removal on cancel. Method bodies are byte-identical to
legacy (source-parity-pinned by ``test_native_data_stream.py``); only this
docstring, the class name, and ``__all__`` differ.

Per-Active collaborator: holds only the ``active`` back-reference; all
counters/uuid lists/queues stay on ``Active``/``Base`` and are resolved at
call time (cache-nothing rule — the ce846da1 failure class). Swapped in for
``active.data_stream`` by ``graft_active_write_path`` between
``Active.__init__`` and ``myinit()`` — BEFORE ``myinit`` creates the
``data_logger`` task (``base.py:1014``), so the drain loop only ever runs
native code. Cross-collaborator hops stay routed through the ``Active``
surface (``self.active.write_live_data`` / ``self.active.log_data_set_output_file``),
exactly as legacy.
"""
```

2. `class DataStreamer:` → `class NativeDataStreamer:`; replace its class docstring with:

```python
    """Native drop-in for ``active.data_stream`` (legacy surface, native body).

    Holds only the ``active`` back-reference (never cached queue/counter/uuid
    state), per the call-time state resolution rule -- see module docstring.
    """
```

3. After the `LOGGER = ...` line, add:

```python
__all__ = ["NativeDataStreamer"]
```

Update `helao/hexagon/adapters/native/__init__.py` exports (single `__all__`):

```python
from helao.hexagon.adapters.native.meta_writer import NativeMetaFileWriter
from helao.hexagon.adapters.native.data_file import NativeDataFileWriter
from helao.hexagon.adapters.native.data_stream import NativeDataStreamer

__all__ = ["NativeMetaFileWriter", "NativeDataFileWriter", "NativeDataStreamer"]
```

- [ ] **Step 4: Run to verify pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_native_data_stream.py helao/hexagon/tests/test_boundaries.py -q`
Expected: ALL PASS.

- [ ] **Step 5: pyright + black + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/adapters/native/ helao/hexagon/tests/test_native_data_stream.py
git add helao/hexagon/adapters/native/ helao/hexagon/tests/test_native_data_stream.py
git commit -m "feat(hexagon): NativeDataStreamer — source-parity-pinned re-body of DataStreamer (P2b-1 T4)"
```

---

### Task 5: `NativeActionFinalizer` (finish / split / substitute / finish_manual_action) [PYTEST]

The highest-risk task: the ce846da1 join-before-close chain. Test-first on the drain protocol.

**Files:**
- Create: `helao/hexagon/adapters/native/finalizer.py`
- Modify: `helao/hexagon/adapters/native/__init__.py`
- Test: `helao/hexagon/tests/test_native_finalizer.py`

**Interfaces:**
- Consumes: legacy `ActionFinalizer` (`helao/core/servers/active_finalizer.py:90-507`) as copy source; Tasks 2-4 fixtures + native classes.
- Produces: `NativeActionFinalizer(active)` in `helao.hexagon.adapters.native.finalizer` with the exact legacy surface: `split_and_keep_active()`, `split_and_finish_prev_uuids()`, `finish_all()`, `split(uuid_list=None, new_fileconnparams=None) -> List[UUID]`, `substitute()`, `finish(finish_uuid_list=None) -> Action`, `_finish(finish_uuid_list=None) -> Action`, `finish_manual_action()`. Module globals `move_dir`, `set_time`, `async_private_dispatcher` importable/patchable on `helao.hexagon.adapters.native.finalizer` (the golden-master patching seam).

- [ ] **Step 1: Write the failing tests**

`helao/hexagon/tests/test_native_finalizer.py` (complete file):

```python
"""NativeActionFinalizer (P2b-1): verbatim re-body of legacy ActionFinalizer
(helao/core/servers/active_finalizer.py) — the ce846da1 join-drain-close
chain. Source-parity pin + behavior on real tmp trees with a full native
collaborator set (mini-graft): finish drains queued data BEFORE closing
handles, closes every file, cancels data_logger, writes the final -act.yml,
schedules move_dir only for non-manual, pops base.actives into history;
substitute closes streams; split forks file conns + resets counters;
finish_manual_action writes synthesized exp/seq metas. Module globals
(move_dir/set_time/async_private_dispatcher) are patched on THIS module,
mirroring the legacy golden-master patching seam."""

import asyncio
import os
from uuid import UUID

import pytest

import helao.hexagon.adapters.native.finalizer as native_finalizer_mod
from helao.core.servers.active_finalizer import ActionFinalizer
from helao.core.error import ErrorCodes
from helao.core.models.data import DataModel
from helao.hexagon.adapters.native.data_file import NativeDataFileWriter
from helao.hexagon.adapters.native.data_stream import NativeDataStreamer
from helao.hexagon.adapters.native.finalizer import NativeActionFinalizer
from helao.hexagon.adapters.native.meta_writer import NativeMetaFileWriter
from helao.hexagon.tests.native_fixtures import make_base, mk_action, mk_active

METHODS = [
    "__init__",
    "split_and_keep_active",
    "split_and_finish_prev_uuids",
    "finish_all",
    "split",
    "substitute",
    "finish",
    "_finish",
    "finish_manual_action",
]


def test_source_parity_with_legacy():
    from helao.hexagon.tests.native_fixtures import assert_source_parity

    assert_source_parity(NativeActionFinalizer, ActionFinalizer, METHODS)


def _grafted_active(tmp_path, **action_over):
    """Full mini-graft: all three per-Active collaborators + meta writer
    native, base.actives registration, data_logger running."""
    base = make_base(str(tmp_path / "RUNS_ACTIVE"))
    base.meta_writer = NativeMetaFileWriter(base)
    action = mk_action(**action_over) if action_over else None
    active, dflt = mk_active(base, action=action)
    active.data_stream = NativeDataStreamer(active)
    active.data_file_writer = NativeDataFileWriter(active)
    active.action_finalizer = NativeActionFinalizer(active)
    base.actives[active.action.action_uuid] = active
    return base, active, dflt


async def _start_logger(base, active):
    base.aloop = asyncio.get_running_loop()
    active.data_logger = base.aloop.create_task(active.log_data_task())
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_finish_join_drain_close_chain(tmp_path, monkeypatch):
    """The ce846da1 chain: data enqueued right before finish must land in
    the .hlo BEFORE the handle closes; afterwards every handle is closed,
    data_logger is cancelled, the final -act.yml exists, move_dir was
    scheduled (non-manual), and the active moved to history."""
    moved = []

    async def fake_move_dir(action, base=None):
        moved.append(action.action_uuid)

    monkeypatch.setattr(native_finalizer_mod, "move_dir", fake_move_dir)
    base, active, dflt = _grafted_active(tmp_path)
    await _start_logger(base, active)

    await active.enqueue_data(DataModel(data={dflt: {"t_s": 1, "value": 2.0}}, errors=[]))
    # enqueue WITHOUT yielding to the drain loop: finish must wait for it
    active.enqueue_data_nowait(DataModel(data={dflt: {"t_s": 2, "value": 3.0}}, errors=[]))
    result = await active.finish()
    await asyncio.sleep(0.1)  # let the fire-and-forget move_dir task run

    assert result is active.action
    out_dir = os.path.join(
        str(base.helaodirs.save_root), str(active.action.action_output_dir)
    )
    hlo = [f for f in os.listdir(out_dir) if f.endswith(".hlo")]
    text = open(os.path.join(out_dir, hlo[0])).read()
    # hlo_json_dumps compact separators (no spaces)
    assert '{"t_s":2,"value":3.0}' in text  # late row landed before close
    assert active.file_conn_dict == {}  # close-all cleared the dict
    assert active.data_logger.cancelled() or active.data_logger.done()
    assert [f for f in os.listdir(out_dir) if f.endswith("-act.yml")]
    assert moved == [active.action.action_uuid]
    assert active.action.action_uuid not in base.actives
    assert active.action.action_uuid in base.history
    assert len(base.data_q.subscribers) == 0  # no leaked subscription


@pytest.mark.asyncio
async def test_finish_exports_global_params(tmp_path, monkeypatch):
    calls = []

    async def fake_dispatch(**kwargs):
        calls.append(kwargs)
        return {}, ErrorCodes.none

    async def fake_move_dir(action, base=None):
        pass

    monkeypatch.setattr(native_finalizer_mod, "async_private_dispatcher", fake_dispatch)
    monkeypatch.setattr(native_finalizer_mod, "move_dir", fake_move_dir)
    base, active, _ = _grafted_active(tmp_path)
    await _start_logger(base, active)
    active.action.to_global_params = ["gain"]
    active.action.action_params = {"gain": 7}
    await active.finish()
    assert calls and calls[0]["private_action"] == "update_global_params"
    assert calls[0]["json_dict"] == {"gain": 7}

    # empty resolution => RPC skipped (the estop-interrupt guard)
    calls.clear()
    base2, active2, _ = _grafted_active(tmp_path / "b")
    await _start_logger(base2, active2)
    active2.action.to_global_params = ["missing_key"]
    await active2.finish()
    assert calls == []


@pytest.mark.asyncio
async def test_substitute_closes_open_streams(tmp_path):
    base, active, dflt = _grafted_active(tmp_path)
    await _start_logger(base, active)
    await active.enqueue_data(DataModel(data={dflt: {"t_s": 1}}, errors=[]))
    await asyncio.sleep(0.1)
    assert active.file_conn_dict[dflt].file is not None
    await active.substitute()
    # aiofiles handle closed: writing now raises ValueError on closed file
    with pytest.raises(ValueError):
        await active.file_conn_dict[dflt].file.write("x")
    active.data_logger.cancel()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_split_forks_conns_and_resets_counters(tmp_path, monkeypatch):
    async def fake_move_dir(action, base=None):
        pass

    monkeypatch.setattr(native_finalizer_mod, "move_dir", fake_move_dir)
    base, active, dflt = _grafted_active(tmp_path)
    await _start_logger(base, active)
    await active.enqueue_data(DataModel(data={dflt: {"t_s": 1}}, errors=[]))
    await asyncio.sleep(0.1)
    prev_uuid = active.action.action_uuid
    new_keys = await active.split(uuid_list=[])  # keep prior open
    assert len(new_keys) == 1
    assert active.action.action_uuid != prev_uuid
    assert active.action.action_split == 1
    assert prev_uuid not in active.listen_uuids
    assert active.action.action_uuid in active.listen_uuids
    assert active.num_data_queued == 0 and active.num_data_written == 0
    assert active.action.parent_action_uuid == prev_uuid
    active.data_logger.cancel()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_manual_action_skips_move_dir_and_writes_exp_seq(tmp_path, monkeypatch):
    moved = []

    async def fake_move_dir(action, base=None):
        moved.append(action.action_uuid)

    monkeypatch.setattr(native_finalizer_mod, "move_dir", fake_move_dir)
    base, active, dflt = _grafted_active(
        tmp_path, manual_action=True, run_type="manual", save_act=True
    )
    await _start_logger(base, active)
    await active.finish()
    assert moved == []  # manual: no promotion
    from helao.core.models.run_dir import RunDir

    diag_root = str(base.helaodirs.save_root).replace(
        RunDir.ACTIVE.value, RunDir.DIAG.value
    )
    exp_dir = os.path.join(diag_root, str(active.action.get_experiment_dir()))
    seq_dir = os.path.join(diag_root, str(active.action.get_sequence_dir()))
    assert [f for f in os.listdir(exp_dir) if f.endswith("-exp.yml")]
    assert [f for f in os.listdir(seq_dir) if f.endswith("-seq.yml")]
```

- [ ] **Step 2: Run to verify failure**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_native_finalizer.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'helao.hexagon.adapters.native.finalizer'`.

- [ ] **Step 3: Create the native module (verbatim copy + pinned edits)**

```bash
cp helao/core/servers/active_finalizer.py helao/hexagon/adapters/native/finalizer.py
```

Apply EXACTLY these edits:

1. Replace the module docstring with:

```python
"""Native action finalizer (hexagon P2b-1).

Verbatim re-body of the CARDS-P6 ``ActionFinalizer`` collaborator
(``helao/core/servers/active_finalizer.py``) — the finish / split /
substitute close-out state machine, including the ce846da1 join-drain-close
chain: send finished data_stream packets (<=5 x 0.1 s), wait
``num_data_queued <= num_data_written`` (<=5 x 0.1 s), THEN close every file
handle and cancel ``data_logger`` (late data beyond the bounded retries is
dropped exactly as legacy drops it); HLO post-processors may rewrite
``files[]``; final ``write_act`` per action; fire-and-forget ``move_dir``
promotion for non-manual actions only; ``finish_manual_action`` synthesizes
the ``exp--``/``seq--`` metas. Method bodies are byte-identical to legacy
(source-parity-pinned by ``test_native_finalizer.py``); only this docstring,
the class name, and ``__all__`` differ.

Per-Active collaborator: holds only the ``active`` back-reference; the drain
counters (``num_data_queued``/``num_data_written``), ``action_list``,
``file_conn_dict``, ``data_logger`` and ``finish_lock`` are read live off
``Active`` at call time — caching ANY of them here recreates the exact
ce846da1 failure class (a finish that closes before late data lands, a
leaked handle -> WinError 32 -> permanent promotion failure). Swapped in for
``active.action_finalizer`` by ``graft_active_write_path`` between
``Active.__init__`` and ``myinit()``.

Module-global functions ``set_time`` / ``move_dir`` /
``async_private_dispatcher`` are imported here exactly as the legacy module
imports them; tests patch them on THIS module (the same seam the legacy
golden master patches on ``active_finalizer``/``base``).
"""
```

2. `class ActionFinalizer:` → `class NativeActionFinalizer:`; replace its class docstring with:

```python
    """Native drop-in for ``active.action_finalizer`` (legacy surface, native body).

    Holds only the ``active`` back-reference (never cached counter/list/conn
    state), per the call-time state resolution rule -- see module docstring.
    """
```

3. After the `LOGGER = ...` line, add:

```python
__all__ = ["NativeActionFinalizer"]
```

Update `helao/hexagon/adapters/native/__init__.py` exports (single `__all__`):

```python
from helao.hexagon.adapters.native.meta_writer import NativeMetaFileWriter
from helao.hexagon.adapters.native.data_file import NativeDataFileWriter
from helao.hexagon.adapters.native.data_stream import NativeDataStreamer
from helao.hexagon.adapters.native.finalizer import NativeActionFinalizer

__all__ = [
    "NativeMetaFileWriter",
    "NativeDataFileWriter",
    "NativeDataStreamer",
    "NativeActionFinalizer",
]
```

- [ ] **Step 4: Run to verify pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_native_finalizer.py helao/hexagon/tests/test_boundaries.py -q`
Expected: ALL PASS. If `test_finish_join_drain_close_chain` is flaky on the `data_logger.cancelled()` assert, the drain loop may have finished naturally — the `or active.data_logger.done()` disjunct covers it; do NOT loosen the late-row byte assert.

- [ ] **Step 5: pyright + black + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/adapters/native/ helao/hexagon/tests/test_native_finalizer.py
git add helao/hexagon/adapters/native/ helao/hexagon/tests/test_native_finalizer.py
git commit -m "feat(hexagon): NativeActionFinalizer — source-parity-pinned re-body of the finish/split/substitute chain (P2b-1 T5)"
```

---

### Task 6: `NativeArtifactStoreAdapter` (ArtifactStorePort) [PYTEST]

**Files:**
- Create: `helao/hexagon/adapters/native/artifact_store.py`
- Modify: `helao/hexagon/adapters/native/__init__.py`
- Test: `helao/hexagon/tests/test_native_artifact_store.py`

**Interfaces:**
- Consumes: `ArtifactStorePort` (`helao/hexagon/ports/artifact_store.py:33-75`); Tasks 2-5 native classes; `UnwiredPortError` (`helao/hexagon/adapters/errors.py`); keep-callable `move_dir` (`helao/helpers/yml_tools.py`) and `zip_dir` (`helao/helpers/file_utils.py`); the `{}`-sentinel mapping precedent (`adapters/legacy/artifact_store.py:101-105`).
- Produces (Task 8/9 rely on these exact names):
  - `NativeArtifactStoreAdapter(config, clock, base=None, active=None)` — constructible from ports alone at `build_wiring` time.
  - `.bind_base(base) -> None` — late base binding at graft time (mirror of the queue-late-binding pattern noted for `DispatcherStatusAdapter`).
  - `.meta_writer_for(base) -> NativeMetaFileWriter`
  - `.collaborators_for(active) -> tuple[NativeDataStreamer, NativeDataFileWriter, NativeActionFinalizer]`
  - `.for_action(active) -> NativeArtifactStoreAdapter` (per-action handle, same pattern as `adapters/legacy/artifact_store.py:44`).
  - Port members: `write_act/write_exp/write_seq` (require bound base), `write_data_line(action, file_conn_key, payload)`, `close_streams(action)`, `write_one_shot(action, output_str, file_type, filename, header)`, `finish(action)`, `move_dir(hobj) -> bool`, `zip_dir(dir_path) -> Path`.

- [ ] **Step 1: Write the failing tests**

`helao/hexagon/tests/test_native_artifact_store.py` (complete file):

```python
"""NativeArtifactStoreAdapter (P2b-1): ArtifactStorePort implemented over
the native collaborator bodies. Conformance + factory members
(meta_writer_for / collaborators_for / bind_base) + keep-callable
move_dir/zip_dir mapping ({} rejection sentinel, same as the legacy
adapter's documented drift note)."""

import os

import pytest

from helao.hexagon.adapters.errors import UnwiredPortError
from helao.hexagon.adapters.native.artifact_store import NativeArtifactStoreAdapter
from helao.hexagon.adapters.native.data_file import NativeDataFileWriter
from helao.hexagon.adapters.native.data_stream import NativeDataStreamer
from helao.hexagon.adapters.native.finalizer import NativeActionFinalizer
from helao.hexagon.adapters.native.meta_writer import NativeMetaFileWriter
from helao.hexagon.ports.artifact_store import ArtifactStorePort
from helao.hexagon.tests.native_fixtures import make_base, mk_active


def _store():
    # config/clock are only stored (native bodies read state off base/active
    # at call time); construction must not need a live Base
    return NativeArtifactStoreAdapter(config=None, clock=None)


def test_port_conformance_and_no_base_inheritance():
    from helao.core.servers.base import Base

    store = _store()
    assert isinstance(store, ArtifactStorePort)  # runtime_checkable Protocol
    assert not isinstance(store, Base)


def test_factory_members(tmp_path):
    store = _store()
    base = make_base(str(tmp_path))
    mw = store.meta_writer_for(base)
    assert isinstance(mw, NativeMetaFileWriter) and mw.base is base
    active, _ = mk_active(base)
    streamer, file_writer, finalizer = store.collaborators_for(active)
    assert isinstance(streamer, NativeDataStreamer) and streamer.active is active
    assert isinstance(file_writer, NativeDataFileWriter) and file_writer.active is active
    assert isinstance(finalizer, NativeActionFinalizer) and finalizer.active is active


@pytest.mark.asyncio
async def test_meta_members_require_bound_base(tmp_path):
    store = _store()
    base = make_base(str(tmp_path / "RUNS_ACTIVE"))
    active, _ = mk_active(base)
    with pytest.raises(UnwiredPortError):
        await store.write_act(active.action)
    store.bind_base(base)
    base.meta_writer = store.meta_writer_for(base)
    active.action.save_act = True
    await store.write_act(active.action)
    out_dir = os.path.join(
        str(base.helaodirs.save_root), str(active.action.action_output_dir)
    )
    assert [f for f in os.listdir(out_dir) if f.endswith("-act.yml")]


@pytest.mark.asyncio
async def test_stream_members_require_active_handle(tmp_path):
    store = _store()
    base = make_base(str(tmp_path / "RUNS_ACTIVE"))
    active, dflt = mk_active(base)
    with pytest.raises(UnwiredPortError):
        await store.write_one_shot(active.action, "x", "t", "f.csv", None)
    streamer, file_writer, finalizer = store.collaborators_for(active)
    active.data_stream = streamer
    active.data_file_writer = file_writer
    active.action_finalizer = finalizer
    bound = store.for_action(active)
    path = await bound.write_one_shot(active.action, "row", "aux__csv", "os.csv", "h")
    assert path is not None and open(path).read() == "h\n%%\nrow"
    # write_data_line feeds the data_q (native enqueue re-body)
    await bound.write_data_line(active.action, dflt, {"t_s": 1})
    assert active.num_data_queued == 1
    await bound.close_streams(active.action)  # substitute: no open files -> no-op


@pytest.mark.asyncio
async def test_move_dir_sentinel_mapping():
    store = _store()
    # unsupported hobj type -> legacy move_dir returns {} -> port False
    assert await store.move_dir(object()) is False


@pytest.mark.asyncio
async def test_zip_dir_maps_to_helper(tmp_path):
    store = _store()
    d = tmp_path / "seqdir"
    d.mkdir()
    (d / "a.txt").write_text("x")
    out = await store.zip_dir(d)
    assert out.suffix == ".zip" and out.exists()
```

- [ ] **Step 2: Run to verify failure**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_native_artifact_store.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'helao.hexagon.adapters.native.artifact_store'`.

- [ ] **Step 3: Implement**

`helao/hexagon/adapters/native/artifact_store.py` (complete file):

```python
"""ArtifactStorePort adapter over the NATIVE write bodies (P2b-1).

The native counterpart of ``adapters/legacy/artifact_store.py``: the same
port surface and the same for_action/bound-handle pattern, but every write
body is the hexagon-native re-body (meta_writer/data_file/data_stream/
finalizer modules in this package) instead of a wrap of live legacy
collaborators. Constructible from ConfigPort+ClockPort at ``build_wiring``
time — no live ``Base`` exists yet; ``bind_base`` is called by the active
graft at startup (the late-binding pattern the status adapter documents for
its queues). It is also the composition's collaborator FACTORY:
``graft_active_write_path`` obtains the per-Active native collaborators via
``collaborators_for`` and the per-Base meta writer via ``meta_writer_for``,
so the fail-loud wired port is exactly what carries the rerouted traffic
(honesty: an unwired artifact_store aborts startup via ACTION_REQUIRED).

Promotion/zip stay keep-callable legacy helpers (``yml_tools.move_dir`` /
``file_utils.zip_dir``) — helpers, not god-class members. The ``move_dir``
``{}``-rejection-sentinel mapping is copied from the legacy adapter's
documented drift note: ``{}`` is legacy's only reject signal; ``None``
covers both success and silent retry-exhaustion, so "recognized object
type" (``result != {}``) is the most accurate bool the return carries.

Q2 (binding): sample/status mutations are NOT here — see
``native/data_sink.py``.
"""

from pathlib import Path
from typing import Optional, Tuple
from uuid import UUID

from helao.helpers.file_utils import zip_dir
from helao.helpers.yml_tools import move_dir
from helao.hexagon.adapters.errors import UnwiredPortError
from helao.hexagon.adapters.native.data_file import NativeDataFileWriter
from helao.hexagon.adapters.native.data_stream import NativeDataStreamer
from helao.hexagon.adapters.native.finalizer import NativeActionFinalizer
from helao.hexagon.adapters.native.meta_writer import NativeMetaFileWriter
from helao.hexagon.domain.models import Action, DataModel, Experiment, Sequence

__all__ = ["NativeArtifactStoreAdapter"]


class NativeArtifactStoreAdapter:
    def __init__(self, config=None, clock=None, base=None, active=None):
        self._config = config
        self._clock = clock
        self._base = base
        self._active = active

    # --- graft-time binding + collaborator factory ---
    def bind_base(self, base) -> None:
        """Late base binding (graft startup); build_wiring has no Base yet."""
        self._base = base

    def meta_writer_for(self, base) -> NativeMetaFileWriter:
        return NativeMetaFileWriter(base)

    def collaborators_for(
        self, active
    ) -> Tuple[NativeDataStreamer, NativeDataFileWriter, NativeActionFinalizer]:
        """Per-Active native collaborator set (cache-nothing: each holds only
        the back-reference; safe to construct fresh per Active)."""
        return (
            NativeDataStreamer(active),
            NativeDataFileWriter(active),
            NativeActionFinalizer(active),
        )

    def for_action(self, active) -> "NativeArtifactStoreAdapter":
        """Per-action handle bound to a live (grafted) legacy Active."""
        return NativeArtifactStoreAdapter(
            config=self._config, clock=self._clock, base=self._base, active=active
        )

    def _require_base(self):
        if self._base is None:
            raise UnwiredPortError(
                "meta members need a bound Base; the active graft calls "
                "bind_base(base) at startup"
            )
        return self._base

    def _require_active(self):
        if self._active is None:
            raise UnwiredPortError(
                "stream/one-shot/finish members need an Active-bound handle; "
                "use for_action(active)"
            )
        return self._active

    # --- meta ymls (native bodies, resolved through the bound base's
    # meta_writer — the graft has already swapped it native) ---
    async def write_act(self, action: Action) -> None:
        await self._require_base().write_act(action)

    async def write_exp(self, experiment: Experiment) -> None:
        await self._require_base().write_exp(experiment)

    async def write_seq(self, sequence: Sequence) -> None:
        await self._require_base().write_seq(sequence)

    # --- streamed hlo ---
    async def write_data_line(
        self, action: Action, file_conn_key: UUID, payload: object
    ) -> None:
        active = self._require_active()
        # native enqueue re-body via the swapped collaborator: DataModel keyed
        # by file_conn_key; the native log_data_task performs lazy open +
        # header + %% + json line. payload is dict-per-row in every real
        # caller (same cast rationale as the legacy adapter).
        await NativeDataStreamer(active).enqueue_data(
            DataModel(data={file_conn_key: payload}, errors=[]), action  # type: ignore[dict-item]
        )

    async def close_streams(self, action: Action) -> None:
        await NativeActionFinalizer(self._require_active()).substitute()

    # --- one-shot ---
    async def write_one_shot(
        self,
        action: Action,
        output_str: str,
        file_type: str,
        filename: Optional[str],
        header: Optional[str],
    ) -> Optional[str]:
        return await NativeDataFileWriter(self._require_active()).write_file(
            output_str, file_type, filename, header=header, action=action
        )

    # --- finish + promotion ---
    async def finish(self, action: Action) -> None:
        await NativeActionFinalizer(self._require_active()).finish()

    async def move_dir(self, hobj: object) -> bool:
        result = await move_dir(hobj, base=self._base)
        # {} is legacy's only reject signal (see module docstring)
        return result != {}

    async def zip_dir(self, dir_path: Path) -> Path:
        target = Path(dir_path)
        out = target.with_suffix(".zip")
        zip_dir(target, out)
        return out
```

Add to `helao/hexagon/adapters/native/__init__.py` exports (single `__all__`):

```python
from helao.hexagon.adapters.native.meta_writer import NativeMetaFileWriter
from helao.hexagon.adapters.native.data_file import NativeDataFileWriter
from helao.hexagon.adapters.native.data_stream import NativeDataStreamer
from helao.hexagon.adapters.native.finalizer import NativeActionFinalizer
from helao.hexagon.adapters.native.artifact_store import NativeArtifactStoreAdapter

__all__ = [
    "NativeMetaFileWriter",
    "NativeDataFileWriter",
    "NativeDataStreamer",
    "NativeActionFinalizer",
    "NativeArtifactStoreAdapter",
]
```

- [ ] **Step 4: Run to verify pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_native_artifact_store.py helao/hexagon/tests/test_boundaries.py -q`
Expected: ALL PASS. (`write_data_line`'s in-body construction of a fresh `NativeDataStreamer` is cache-nothing-safe: the streamer holds only the back-ref; counters live on `active`.)

- [ ] **Step 5: pyright + black + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/adapters/native/ helao/hexagon/tests/test_native_artifact_store.py
git add helao/hexagon/adapters/native/ helao/hexagon/tests/test_native_artifact_store.py
git commit -m "feat(hexagon): NativeArtifactStoreAdapter — ArtifactStorePort over the native write bodies (P2b-1 T6)"
```

---

### Task 7: `NativeDataSinkAdapter` (DataSinkPort; Q2 members legacy-delegated) [PYTEST]

**Files:**
- Create: `helao/hexagon/adapters/native/data_sink.py`
- Modify: `helao/hexagon/adapters/native/__init__.py`
- Test: `helao/hexagon/tests/test_native_data_sink.py`

**Interfaces:**
- Consumes: `DataSinkPort` (`helao/hexagon/ports/data_sink.py:38-124`); Tasks 4-6 native classes; `UnwiredPortError`.
- Produces (Task 8 wires it): `NativeDataSinkAdapter(active=None)` with `.for_action(active) -> NativeDataSinkAdapter` and the full `DataSinkPort` surface. Write members run native bodies; `append_sample` / `set_estop` delegate to the legacy `Active` (Q2); lbuf members route via `active.base` (the sanctioned reach-in, same as `adapters/legacy/data_sink.py:119-127`); the `_nowait` members preserve the legacy thread-safety contract verbatim (they run the byte-identical `enqueue_data_nowait` / `write_file_nowait` bodies).

- [ ] **Step 1: Write the failing tests**

`helao/hexagon/tests/test_native_data_sink.py` (complete file):

```python
"""NativeDataSinkAdapter (P2b-1): DataSinkPort over the native write bodies.
Q2 (binding): append_sample / set_estop stay LEGACY-delegated (pure model
mutations + status_q puts — P2a owns the status plane); split routes to the
native finalizer; lbuf members route via active.base (sanctioned)."""

import pytest

from helao.core.models.data import DataModel
from helao.core.models.hlostatus import HloStatus
from helao.core.models.sample import LiquidSample, SampleInheritance
from helao.hexagon.adapters.errors import UnwiredPortError
from helao.hexagon.adapters.native.data_sink import NativeDataSinkAdapter
from helao.hexagon.adapters.native.data_stream import NativeDataStreamer
from helao.hexagon.adapters.native.data_file import NativeDataFileWriter
from helao.hexagon.adapters.native.finalizer import NativeActionFinalizer
from helao.hexagon.ports.data_sink import DataSinkPort
from helao.hexagon.tests.native_fixtures import make_base, mk_active


def _bound(tmp_path):
    base = make_base(str(tmp_path / "RUNS_ACTIVE"))
    active, dflt = mk_active(base)
    active.data_stream = NativeDataStreamer(active)
    active.data_file_writer = NativeDataFileWriter(active)
    active.action_finalizer = NativeActionFinalizer(active)
    return base, active, dflt, NativeDataSinkAdapter().for_action(active)


def test_port_conformance_and_no_base_inheritance():
    from helao.core.servers.base import Base

    sink = NativeDataSinkAdapter()
    assert isinstance(sink, DataSinkPort)
    assert not isinstance(sink, Base)


def test_unbound_raises():
    with pytest.raises(UnwiredPortError):
        NativeDataSinkAdapter().enqueue_data_nowait(DataModel(data={}, errors=[]))


@pytest.mark.asyncio
async def test_enqueue_members_bump_active_counter(tmp_path):
    base, active, dflt, sink = _bound(tmp_path)
    await sink.enqueue_data(DataModel(data={dflt: {"t_s": 1}}, errors=[]))
    sink.enqueue_data_nowait(DataModel(data={dflt: {"t_s": 2}}, errors=[]))
    await sink.enqueue_data_dflt({"t_s": 3})
    assert active.num_data_queued == 3  # counter lives on Active (Q3)


@pytest.mark.asyncio
async def test_write_file_and_realtime_and_header(tmp_path):
    base, active, dflt, sink = _bound(tmp_path)
    assert isinstance(sink.get_realtime_nowait(), int)
    path = await sink.write_file(output_str="r", file_type="t", filename="s.csv")
    assert path is not None
    assert sink.write_file_nowait(output_str="r", file_type="t", filename="s2.csv")
    await sink.finish_hlo_header(realtime=17)
    assert active.file_conn_dict[dflt].params.hloheader.epoch_ns == 17


@pytest.mark.asyncio
async def test_q2_members_delegate_to_legacy_active(tmp_path):
    base, active, dflt, sink = _bound(tmp_path)
    sample = LiquidSample(
        sample_no=1, machine_name="test-machine", inheritance=SampleInheritance.allow_both
    )
    await sink.append_sample([sample], IO="in")
    # legacy Active.append_sample ran: sample recorded with defaults filled
    # (MultisubscriberQueue has no qsize; its put with no subscribers is a
    # drop, so the status broadcast is asserted via the sample side effects)
    assert active.action.samples_in
    assert active.action.samples_in[0].action_uuid == [active.action.action_uuid]
    sink.set_estop()
    assert HloStatus.estopped in active.action.action_status
```

- [ ] **Step 2: Run to verify failure**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_native_data_sink.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'helao.hexagon.adapters.native.data_sink'`.

- [ ] **Step 3: Implement**

`helao/hexagon/adapters/native/data_sink.py` (complete file):

```python
"""DataSinkPort adapter over the NATIVE write bodies (P2b-1).

Write members (enqueue*/realtime/finish_hlo_header/write_file*/track_file/
split) run the native collaborator bodies in this package, constructed
per-call against the bound Active (cache-nothing: collaborators hold only
the back-ref; every counter/conn lives on the Active, so fresh construction
is state-free). THREAD-SAFETY IS CONTRACTUAL and preserved verbatim: the
``_nowait`` members and ``get_realtime_nowait`` execute the byte-identical
legacy bodies (source-parity-pinned), which are the members the NI-DAQmx
hardware-buffer callback calls from a foreign thread.

Q2 (binding): ``append_sample`` and ``set_estop`` STAY legacy-delegated onto
the Active surface (pure mutations on shared pydantic models + a status_q
put; P2a owns the status plane — reimplementing them buys no decoupling
while legacy BaseAPI hosts). The lbuf members route via ``active.base`` —
the ONE sanctioned base reach-in, same as the legacy adapter.
"""

from typing import List, Optional
from uuid import UUID

from helao.hexagon.adapters.errors import UnwiredPortError
from helao.hexagon.adapters.native.data_file import NativeDataFileWriter
from helao.hexagon.adapters.native.data_stream import NativeDataStreamer
from helao.hexagon.adapters.native.finalizer import NativeActionFinalizer
from helao.hexagon.domain.models import (
    Action,
    DataModel,
    FileConnParams,
    HloFileGroup,
)

__all__ = ["NativeDataSinkAdapter"]


class NativeDataSinkAdapter:
    def __init__(self, active=None):
        self._active = active

    def for_action(self, active) -> "NativeDataSinkAdapter":
        """Per-action handle bound to a live (grafted) legacy Active."""
        return NativeDataSinkAdapter(active=active)

    def _require_active(self):
        if self._active is None:
            raise UnwiredPortError(
                "data-sink members need an Active-bound handle; use "
                "for_action(active)"
            )
        return self._active

    def _streamer(self) -> NativeDataStreamer:
        return NativeDataStreamer(self._require_active())

    def _file_writer(self) -> NativeDataFileWriter:
        return NativeDataFileWriter(self._require_active())

    # --- data stream (thread-safe where noted; native bodies) ---
    async def enqueue_data(
        self, datamodel: DataModel, action: Optional[Action] = None
    ) -> None:
        await self._streamer().enqueue_data(datamodel, action)

    def enqueue_data_nowait(
        self, datamodel: DataModel, action: Optional[Action] = None
    ) -> None:
        self._streamer().enqueue_data_nowait(datamodel, action)

    async def enqueue_data_dflt(self, datadict: dict) -> None:
        await self._streamer().enqueue_data_dflt(datadict)

    def get_realtime_nowait(
        self, epoch_ns: Optional[int] = None, offset: Optional[float] = None
    ) -> int:
        return self._streamer().get_realtime_nowait(epoch_ns=epoch_ns, offset=offset)

    async def finish_hlo_header(
        self,
        file_conn_keys: Optional[List[UUID]] = None,
        realtime: Optional[int] = None,
    ) -> None:
        # legacy finish_hlo_header is sync (base.py:1091); async-first port,
        # plain call inside the coroutine keeps semantics (legacy-adapter
        # precedent).
        self._file_writer().finish_hlo_header(
            file_conn_keys=file_conn_keys, realtime=realtime
        )

    # --- file output (native bodies) ---
    async def write_file(
        self,
        output_str,
        file_type,
        filename=None,
        file_group=HloFileGroup.aux_files,
        header=None,
        sample_str=None,
        file_sample_label=None,
        json_data_keys=None,
        action=None,
    ):
        return await self._file_writer().write_file(
            output_str,
            file_type,
            filename=filename,
            file_group=file_group,
            header=header,
            sample_str=sample_str,
            file_sample_label=file_sample_label,
            json_data_keys=json_data_keys,
            action=action,
        )

    def write_file_nowait(
        self,
        output_str,
        file_type,
        filename=None,
        file_group=HloFileGroup.aux_files,
        header=None,
        sample_str=None,
        file_sample_label=None,
        json_data_keys=None,
        action=None,
    ):
        return self._file_writer().write_file_nowait(
            output_str,
            file_type,
            filename=filename,
            file_group=file_group,
            header=header,
            sample_str=sample_str,
            file_sample_label=file_sample_label,
            json_data_keys=json_data_keys,
            action=action,
        )

    async def track_file(self, file_type, file_path, samples, action=None) -> None:
        await self._file_writer().track_file(
            file_type, file_path, samples, action=action
        )

    # --- sample bookkeeping / estop: LEGACY-delegated (Q2, binding) ---
    async def append_sample(self, samples, IO, action=None) -> None:
        await self._require_active().append_sample(samples, IO=IO, action=action)

    def set_estop(self, action: Optional[Action] = None) -> None:
        self._require_active().set_estop(action)

    # --- lifecycle (finalizer trio is native scope) ---
    async def split(
        self, uuid_list=None, new_fileconnparams: Optional[FileConnParams] = None
    ):
        return await NativeActionFinalizer(self._require_active()).split(
            uuid_list=uuid_list, new_fileconnparams=new_fileconnparams
        )

    # --- live buffer (via active.base — the sanctioned reach-in) ---
    async def put_lbuf(self, payload: dict) -> None:
        await self._require_active().base.put_lbuf(payload)

    def put_lbuf_nowait(self, payload: dict) -> None:
        self._require_active().base.put_lbuf_nowait(payload)

    def get_lbuf(self, key: str) -> tuple:
        return self._require_active().base.get_lbuf(key)
```

Add `NativeDataSinkAdapter` to `helao/hexagon/adapters/native/__init__.py` (single `__all__`, now six names — same pattern as before with `from helao.hexagon.adapters.native.data_sink import NativeDataSinkAdapter` and `"NativeDataSinkAdapter"` appended).

- [ ] **Step 4: Run to verify pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_native_data_sink.py helao/hexagon/tests/test_boundaries.py -q`
Expected: ALL PASS.

- [ ] **Step 5: pyright + black + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/adapters/native/ helao/hexagon/tests/test_native_data_sink.py
git add helao/hexagon/adapters/native/ helao/hexagon/tests/test_native_data_sink.py
git commit -m "feat(hexagon): NativeDataSinkAdapter — DataSinkPort over native bodies, Q2 members legacy-delegated (P2b-1 T7)"
```

---

### Task 8: Wire native adapters into `build_wiring` + grow `ACTION_REQUIRED` [PYTEST]

**Files:**
- Modify: `helao/hexagon/app/wiring.py:47` (ACTION_REQUIRED)
- Modify: `helao/hexagon/app/factory.py:29-44` (build_wiring)
- Test: modify `helao/hexagon/tests/test_wiring.py` and `helao/hexagon/tests/test_factory.py` (add; check both files first for existing ACTION_REQUIRED / build_wiring assertions and update them rather than duplicating).
  - **REQUIRED (this WILL break otherwise):** `helao/hexagon/tests/test_wiring.py:35` `test_required_sets_are_frozen_tuples` asserts `set(ACTION_REQUIRED) <= set(ORCH_REQUIRED) | {"transport"}`. `artifact_store`/`data_sink` are NOT in ORCH_REQUIRED, so after growing ACTION_REQUIRED this fails. Update that subset assertion to `set(ACTION_REQUIRED) <= set(ORCH_REQUIRED) | {"transport", "artifact_store", "data_sink"}` (keep the frozen-tuple/`isinstance(..., tuple)` checks intact).
  - Also spot-check `helao/hexagon/tests/test_factory.py:53` `test_build_wiring_produces_real_adapters` for any `w.artifact_store is None` assumption and correct it (it should now be a `NativeArtifactStoreAdapter`).

**Interfaces:**
- Consumes: `NativeArtifactStoreAdapter(config, clock)` and `NativeDataSinkAdapter()` (Tasks 6-7); existing `build_wiring` locals `config`, `LegacyClockAdapter.from_offset_file(log_root)`.
- Produces: `build_wiring(server_key)` returns `PortWiring` with `artifact_store`/`data_sink` wired native; `ACTION_REQUIRED == ("config", "logging", "clock", "transport", "status", "artifact_store", "data_sink")`. Task 10's `makeActionApp` fail-loud honesty rides on this.

- [ ] **Step 1: Write the failing test**

Append to `helao/hexagon/tests/test_factory.py` (uses its existing `installed_config` fixture):

```python
def test_build_wiring_wires_native_write_adapters(installed_config):
    from helao.hexagon.adapters.native.artifact_store import (
        NativeArtifactStoreAdapter,
    )
    from helao.hexagon.adapters.native.data_sink import NativeDataSinkAdapter
    from helao.hexagon.app.factory import build_wiring
    from helao.hexagon.app.wiring import ACTION_REQUIRED

    w = build_wiring("SIM")
    assert isinstance(w.artifact_store, NativeArtifactStoreAdapter)
    assert isinstance(w.data_sink, NativeDataSinkAdapter)
    assert "artifact_store" in ACTION_REQUIRED and "data_sink" in ACTION_REQUIRED
    w.require(*ACTION_REQUIRED)  # fail-loud stays satisfiable
```

- [ ] **Step 2: Run to verify failure**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_factory.py -q`
Expected: the new test FAILS (`w.artifact_store` is `None`); pre-existing tests PASS.

- [ ] **Step 3: Implement**

In `helao/hexagon/app/wiring.py` replace line 47:

```python
ACTION_REQUIRED = (
    "config",
    "logging",
    "clock",
    "transport",
    "status",
    # P2b-1: the native write runtime carries all Active write traffic —
    # a missing adapter must abort startup, never fall through to legacy
    "artifact_store",
    "data_sink",
)
```

In `helao/hexagon/app/factory.py`, add the imports:

```python
from helao.hexagon.adapters.native.artifact_store import NativeArtifactStoreAdapter
from helao.hexagon.adapters.native.data_sink import NativeDataSinkAdapter
```

and rewrite `build_wiring`'s return so clock is a named local wired into both slots:

```python
def build_wiring(server_key: str) -> PortWiring:
    config = from_global_config()  # raises when CONFIG is not installed
    root = config.root()  # KeyError -> loud, like helao_dirs
    log_root = os.path.join(root, "LOGS")
    scfg = config.server_cfg(server_key)  # KeyError -> loud, like the launcher
    clock = LegacyClockAdapter.from_offset_file(log_root)
    return PortWiring(
        config=config,
        logging=LegacyLoggingAdapter(),
        clock=clock,
        transport=LegacyTransportAdapter(config),
        state_persistence=QueuePckStore(root),
        status=DispatcherStatusAdapter(
            server_key, own_host=scfg["host"], own_port=scfg["port"]
        ),
        health=LegacyHealthAdapter(),
        # P2b-1 native write runtime (base bound later by the active graft)
        artifact_store=NativeArtifactStoreAdapter(config=config, clock=clock),
        data_sink=NativeDataSinkAdapter(),
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_factory.py helao/hexagon/tests/test_wiring.py -q`
Expected: ALL PASS. If any existing test pinned the old `ACTION_REQUIRED` tuple or asserted `w.artifact_store is None`, update that assertion to the new truth in the same commit (it is the intended behavior change of this task).

- [ ] **Step 5: pyright + black + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/app/wiring.py helao/hexagon/app/factory.py helao/hexagon/tests/test_factory.py helao/hexagon/tests/test_wiring.py
git add helao/hexagon/app/wiring.py helao/hexagon/app/factory.py helao/hexagon/tests/test_factory.py helao/hexagon/tests/test_wiring.py
git commit -m "feat(hexagon): wire native artifact_store/data_sink into build_wiring + ACTION_REQUIRED (P2b-1 T8)"
```

---

### Task 9: `active_graft.py` — reroute graft, drift pin, honesty tripwire [PYTEST]

**Files:**
- Create: `helao/hexagon/app/active_graft.py`
- Test: `helao/hexagon/tests/test_active_graft.py`

**Interfaces:**
- Consumes: `Base.contain_action` (`helao/core/servers/base.py:438-456`) — the body being reproduced; `Active` + `ActiveParams` (`helao.helpers.active_params`); `NativeArtifactStoreAdapter.collaborators_for/meta_writer_for/bind_base` (Task 6); `PortWiring` (wiring.py); `UnwiredPortError`.
- Produces (Task 10 consumes): `graft_active_write_path(base, wiring: PortWiring) -> ActiveWriteGraft`; `ActiveWriteGraft` dataclass with `.close()` restoring `base.contain_action` and `base.meta_writer`.

- [ ] **Step 1: Write the failing tests**

`helao/hexagon/tests/test_active_graft.py` (complete file):

```python
"""Active write-path graft (P2b-1): drift pin, honesty tripwire, in-process
end-to-end. The graft reproduces Base.contain_action's body (Q1, binding)
because the collaborator swap MUST land between Active.__init__ and
myinit() — myinit spawns (and awaits alongside) the data_logger task, so a
post-return swap races the drain loop's collaborator resolution."""

import asyncio
import inspect
import os
import textwrap

import pytest

import helao.hexagon.adapters.native.finalizer as native_finalizer_mod
from helao.core.models.file import FileConnParams, HloFileGroup
from helao.core.models.data import DataModel
from helao.core.servers.base import Base
from helao.core.servers.base_meta_writer import MetaFileWriter
from helao.helpers.active_params import ActiveParams
from helao.hexagon.adapters.errors import UnwiredPortError
from helao.hexagon.adapters.native.artifact_store import NativeArtifactStoreAdapter
from helao.hexagon.adapters.native.data_file import NativeDataFileWriter
from helao.hexagon.adapters.native.data_stream import NativeDataStreamer
from helao.hexagon.adapters.native.data_sink import NativeDataSinkAdapter
from helao.hexagon.adapters.native.finalizer import NativeActionFinalizer
from helao.hexagon.adapters.native.meta_writer import NativeMetaFileWriter
from helao.hexagon.app.active_graft import ActiveWriteGraft, graft_active_write_path
from helao.hexagon.app.wiring import PortWiring
from helao.hexagon.tests.native_fixtures import make_base, mk_action

# ---------------------------------------------------------------------------
# drift pin (Q1): the graft reproduces this body verbatim (+ swap lines).
# If this test fails, legacy contain_action changed — update BOTH the pinned
# text below AND hex_contain_action in app/active_graft.py, then re-run the
# GM gate.
# ---------------------------------------------------------------------------
PINNED_CONTAIN_ACTION = '''\
async def contain_action(self, activeparams: ActiveParams):
    """Register an action as ``Active`` on the server, substituting any prior one with the same UUID.

    Args:
        activeparams: Parameters describing the action to contain.

    Returns:
        The newly created ``Active`` instance for the action.
    """
    if activeparams.action.action_uuid in self.actives:
        await self.actives[activeparams.action.action_uuid].substitute()
    self.actives[activeparams.action.action_uuid] = Active(
        self, activeparams=activeparams
    )
    await self.actives[activeparams.action.action_uuid].myinit()
    cact = copy(self.actives[activeparams.action.action_uuid].action)
    self.history[cact.action_uuid] = cact
    # register action_uuid in local action task queue
    return self.actives[activeparams.action.action_uuid]
'''


def test_contain_action_drift_pin():
    src = textwrap.dedent(inspect.getsource(Base.contain_action))
    assert src == PINNED_CONTAIN_ACTION, (
        "Base.contain_action drifted from the pinned body the graft "
        "reproduces — update app/active_graft.py:hex_contain_action AND "
        "this pin, then re-run GM-1..GM-5"
    )


def _wiring():
    store = NativeArtifactStoreAdapter(config=None, clock=None)
    return PortWiring(artifact_store=store, data_sink=NativeDataSinkAdapter())


def _activeparams(base, action=None):
    action = action or mk_action()
    dflt = base.dflt_file_conn_key()
    return ActiveParams(
        action=action,
        file_conn_params_dict={
            dflt: FileConnParams(
                file_conn_key=dflt,
                json_data_keys=["t_s", "value"],
                file_type="nu__test_file",
                file_group=HloFileGroup.helao_files,
            )
        },
        aux_listen_uuids=[],
    )


def test_graft_requires_wired_artifact_store(tmp_path):
    base = make_base(str(tmp_path))
    with pytest.raises(UnwiredPortError):
        graft_active_write_path(base, PortWiring())


@pytest.mark.asyncio
async def test_honesty_tripwire_native_collaborators_carry_traffic(
    tmp_path, monkeypatch
):
    """THE DD-7 tripwire: a contained Active's collaborators must BE the
    native types (GM parity alone cannot distinguish 'native carried the
    traffic' from silent legacy fallthrough)."""

    async def fake_move_dir(action, base=None):
        pass

    monkeypatch.setattr(native_finalizer_mod, "move_dir", fake_move_dir)
    base = make_base(str(tmp_path / "RUNS_ACTIVE"))
    base.aloop = asyncio.get_running_loop()
    graft = graft_active_write_path(base, _wiring())
    assert isinstance(graft, ActiveWriteGraft)
    assert isinstance(base.meta_writer, NativeMetaFileWriter)
    # the CLASS attr is untouched (instance-rebind only, zero legacy edits)
    assert Base.contain_action is graft.originals["contain_action"].__func__

    active = await base.contain_action(_activeparams(base))
    assert isinstance(active.data_stream, NativeDataStreamer)
    assert isinstance(active.data_file_writer, NativeDataFileWriter)
    assert isinstance(active.action_finalizer, NativeActionFinalizer)
    assert active.action.action_uuid in base.history  # legacy body reproduced

    # end-to-end through the grafted runtime: enqueue -> drain -> finish
    dflt = base.dflt_file_conn_key()
    await active.enqueue_data(DataModel(data={dflt: {"t_s": 1, "value": 2.0}}, errors=[]))
    await asyncio.sleep(0.15)
    await active.finish()
    out_dir = os.path.join(
        str(base.helaodirs.save_root), str(active.action.action_output_dir)
    )
    hlo = [f for f in os.listdir(out_dir) if f.endswith(".hlo")]
    assert hlo, "native drain loop wrote no .hlo"
    text = open(os.path.join(out_dir, hlo[0])).read()
    # hlo_json_dumps compact separators (no spaces)
    assert "%%\n" in text and '{"t_s":1,"value":2.0}' in text
    assert [f for f in os.listdir(out_dir) if f.endswith("-act.yml")]


@pytest.mark.asyncio
async def test_duplicate_uuid_substitutes_prior_active(tmp_path, monkeypatch):
    """The substitute-on-duplicate-uuid branch (base.py:447-448) — the
    behavior half of the drift pin."""

    async def fake_move_dir(action, base=None):
        pass

    monkeypatch.setattr(native_finalizer_mod, "move_dir", fake_move_dir)
    base = make_base(str(tmp_path / "RUNS_ACTIVE"))
    base.aloop = asyncio.get_running_loop()
    graft_active_write_path(base, _wiring())
    first = await base.contain_action(_activeparams(base))
    dflt = base.dflt_file_conn_key()
    await first.enqueue_data(DataModel(data={dflt: {"t_s": 1}}, errors=[]))
    await asyncio.sleep(0.15)
    assert first.file_conn_dict[dflt].file is not None
    # same uuid again -> prior active's open streams are substituted (closed)
    second = await base.contain_action(_activeparams(base, action=mk_action()))
    assert second is not first
    with pytest.raises(ValueError):
        await first.file_conn_dict[dflt].file.write("x")
    first.data_logger.cancel()
    second.data_logger.cancel()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_close_restores_originals(tmp_path):
    base = make_base(str(tmp_path))
    base.aloop = asyncio.get_running_loop()
    original_contain = base.contain_action
    original_meta = base.meta_writer
    graft = graft_active_write_path(base, _wiring())
    assert base.contain_action is not original_contain
    graft.close()
    assert base.contain_action == original_contain
    assert base.meta_writer is original_meta
    assert isinstance(base.meta_writer, MetaFileWriter)
```

- [ ] **Step 2: Run to verify failure**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_active_graft.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'helao.hexagon.app.active_graft'`. (If instead `test_contain_action_drift_pin` fails, the pinned text does not match the live `base.py` — fix the PIN to the live source verbatim before proceeding; the graft body in Step 3 must then be adjusted identically.)

- [ ] **Step 3: Implement**

`helao/hexagon/app/active_graft.py` (complete file):

```python
"""Active write-path graft (P2b-1) — the analog of dispatch_loop's
graft_hexagon_loop: instance-level rebinding is the sanctioned wrap seam;
NO legacy source is modified.

What it reroutes: ``base.contain_action`` (reproduced 12-line legacy body,
drift-pinned by test_active_graft.PINNED_CONTAIN_ACTION) and
``base.meta_writer`` (one assignment; every Base meta delegator at
``base.py:666-716`` resolves ``self.meta_writer`` at call time). The
reproduced body swaps the three per-Active collaborators
(``data_stream``/``data_file_writer``/``action_finalizer``) for the wired
NativeArtifactStoreAdapter's collaborators BETWEEN ``Active.__init__`` and
``myinit()`` — mandatory window: ``myinit`` creates the ``data_logger``
task (``base.py:1014``) and then awaits (``update_act_file``, manual
metas) before returning, so the task body may resolve ``self.data_stream``
before ``contain_action`` returns; a post-return swap is a race. After the
swap, every call-time-resolving ``Active`` delegator
(``base.py:1149-1459``) routes 100% of write traffic through native code
while drivers/executors keep calling the unchanged ``Active`` surface and
legacy BaseAPI keeps hosting the routes (Q1).
"""

from copy import copy
from dataclasses import dataclass, field
from typing import Dict

from helao.core.servers.base import Active
from helao.helpers import helao_logging as logging
from helao.helpers.active_params import ActiveParams
from helao.hexagon.adapters.errors import UnwiredPortError
from helao.hexagon.app.wiring import PortWiring

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

__all__ = ["ActiveWriteGraft", "graft_active_write_path"]


@dataclass
class ActiveWriteGraft:
    base: object
    originals: Dict[str, object] = field(default_factory=dict)

    def close(self) -> None:
        """Symmetric unhook: restore the pre-graft bound method + meta writer."""
        self.base.contain_action = self.originals["contain_action"]  # type: ignore[attr-defined]
        self.base.meta_writer = self.originals["meta_writer"]  # type: ignore[attr-defined]


def graft_active_write_path(base, wiring: PortWiring) -> ActiveWriteGraft:
    """Rebind the legacy Base's write construction seam onto the native
    write runtime. Must run after the legacy app's own startup (``app.base``
    live) and before any action is contained."""
    store = wiring.artifact_store
    if store is None or not hasattr(store, "collaborators_for"):
        raise UnwiredPortError(
            "active write graft needs a wired NativeArtifactStoreAdapter "
            "(collaborators_for/meta_writer_for); got "
            f"{type(store).__name__ if store is not None else None}"
        )

    graft = ActiveWriteGraft(base=base)
    graft.originals["contain_action"] = base.contain_action
    graft.originals["meta_writer"] = base.meta_writer
    store.bind_base(base)
    base.meta_writer = store.meta_writer_for(base)

    async def hex_contain_action(activeparams: ActiveParams):
        # ------------------------------------------------------------------
        # Reproduction of Base.contain_action (base.py:438-456), statement
        # for statement — drift-pinned by test_active_graft.py. The ONLY
        # addition is the native collaborator swap, placed between
        # Active.__init__ and myinit() (see module docstring).
        # NB: the dict key is read AFTER Active() runs (init_act may assign
        # a fresh action_uuid in manual mode) — same evaluation order as the
        # legacy single-statement construct+register.
        # ------------------------------------------------------------------
        if activeparams.action.action_uuid in base.actives:
            await base.actives[activeparams.action.action_uuid].substitute()
        base.actives[activeparams.action.action_uuid] = Active(
            base, activeparams=activeparams
        )
        # --- hexagon swap (the reroute) ---
        active = base.actives[activeparams.action.action_uuid]
        streamer, file_writer, finalizer = store.collaborators_for(active)
        active.data_stream = streamer
        active.data_file_writer = file_writer
        active.action_finalizer = finalizer
        LOGGER.info(
            f"hexagon native collaborators swapped for action "
            f"{activeparams.action.action_uuid}"
        )
        # --- end swap ---
        await base.actives[activeparams.action.action_uuid].myinit()
        cact = copy(base.actives[activeparams.action.action_uuid].action)
        base.history[cact.action_uuid] = cact
        # register action_uuid in local action task queue
        return base.actives[activeparams.action.action_uuid]

    base.contain_action = hex_contain_action
    LOGGER.info(
        "hexagon native write path grafted (contain_action + meta_writer rebound)"
    )
    return graft
```

- [ ] **Step 4: Run to verify pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_active_graft.py helao/hexagon/tests/test_boundaries.py -q`
Expected: ALL PASS (`app/` may import `helao.core.servers.base` — the sanctioned legacy-touching layer).

- [ ] **Step 5: pyright + black + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/app/active_graft.py helao/hexagon/tests/test_active_graft.py
git add helao/hexagon/app/active_graft.py helao/hexagon/tests/test_active_graft.py
git commit -m "feat(hexagon): active write-path graft — drift-pinned contain_action rebind + native collaborator swap (P2b-1 T9)"
```

---

### Task 10: Hook the graft into `makeActionApp` [PYTEST]

**Files:**
- Modify: `helao/hexagon/app/factory.py:79-84` (makeActionApp)
- Test: append to `helao/hexagon/tests/test_factory.py`

**Interfaces:**
- Consumes: `graft_active_write_path` / `ActiveWriteGraft` (Task 9); `app.base` set by legacy `BaseAPI`'s startup handler (`helao/core/servers/base_api.py:646`: `self.base = Base(app=self, dyn_endpoints=dyn_endpoints)`); Starlette registration-order guarantee (the `makeOrchApp` precedent, `factory.py:64-75`).
- Produces: hexagon action apps run `graft_active_write_path(app.base, wiring)` at startup and `close()` at shutdown; attribute `app.hexagon_active_graft`.

- [ ] **Step 1: Write the failing test**

Append to `helao/hexagon/tests/test_factory.py`:

```python
def test_make_action_app_registers_graft_hooks(installed_config):
    from helao.hexagon.app.factory import makeActionApp

    app = makeActionApp("SIM", "helao.deploy.test.servers.action.ws_simulator")
    assert app.hexagon_wiring.artifact_store is not None
    assert app.hexagon_active_graft is None  # applied at startup, not build
    startup_names = [h.__name__ for h in app.router.on_startup]
    shutdown_names = [h.__name__ for h in app.router.on_shutdown]
    assert "_hexagon_active_graft_startup" in startup_names
    assert "_hexagon_active_graft_shutdown" in shutdown_names
    # ours must be registered AFTER the legacy BaseAPI startup that creates
    # app.base (Starlette preserves registration order)
    assert startup_names[-1] == "_hexagon_active_graft_startup"
```

(If the existing `test_factory.py` already constructs the SIM action app under `installed_config` with a different fixture shape — reuse whatever pattern its existing `makeActionApp` test uses; the assertions above are the deliverable.)

- [ ] **Step 2: Run to verify failure**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_factory.py -q`
Expected: new test FAILS (`AttributeError: ... has no attribute 'hexagon_active_graft'`).

- [ ] **Step 3: Implement**

In `helao/hexagon/app/factory.py`, replace `makeActionApp`:

```python
def makeActionApp(server_key: str, legacy_module: str):
    from helao.hexagon.app.active_graft import graft_active_write_path

    wiring = build_wiring(server_key)
    wiring.require(*ACTION_REQUIRED)
    app = import_module(legacy_module).makeApp(server_key)
    app.hexagon_wiring = wiring
    app.hexagon_active_graft = None

    # Registered AFTER the legacy BaseAPI's own startup handler (which sets
    # self.base = Base(app=self, ...), base_api.py:646; Starlette preserves
    # registration order): the graft sees the live app.base and rebinds
    # contain_action + meta_writer before any action can be contained.
    @app.on_event("startup")
    async def _hexagon_active_graft_startup():
        app.hexagon_active_graft = graft_active_write_path(app.base, wiring)

    @app.on_event("shutdown")
    async def _hexagon_active_graft_shutdown():
        if app.hexagon_active_graft is not None:
            app.hexagon_active_graft.close()

    return app
```

- [ ] **Step 4: Run to verify pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_factory.py -q`
Expected: ALL PASS.

- [ ] **Step 5: pyright + black + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/app/factory.py helao/hexagon/tests/test_factory.py
git add helao/hexagon/app/factory.py helao/hexagon/tests/test_factory.py
git commit -m "feat(hexagon): makeActionApp startup graft — native write runtime carries action-server traffic (P2b-1 T10)"
```

---

### Task 11: Full in-process verification sweep [PYTEST]

**Files:** none new — verification only (fix-forward anything it finds, in the task that owns the file).

- [ ] **Step 1: Full hexagon suite**

Run: `conda run -n helao python -m pytest helao/hexagon -q`
Expected: ALL PASS, 0 failures (record the count).

- [ ] **Step 2: Legacy-side sanity (unchanged legacy must still pass its own gates)**

Run: `conda run -n helao python run_unit_tests.py`
Expected: PASS (this is the launcher's precondition; zero legacy edits means it cannot regress — this is the proof).

Run: `git diff --stat unstable -- helao/core helao/helpers helao/deploy`
Expected: EMPTY output (zero-legacy-edit constraint, mechanically verified; run against the branch-point if the working branch differs).

- [ ] **Step 3: pyright + black over everything touched**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black --check helao/hexagon
```
Expected: pyright 0 errors; black "would reformat 0 files".

- [ ] **Step 4: Commit (only if fixes were needed); otherwise no-op**

```bash
git status --short   # expect clean
```

---

### Task 12: GM-1..GM-5 byte-parity gate + §10.3 concurrency re-run + launched honesty check [LAUNCHED — MAIN SESSION ONLY]

**Do NOT run this task from a subagent** — background launches get reaped on idle. The controller re-runs the launched captures with the P1b2a harness verbatim (`parity_run.sh`, `conc_run.sh`).

**Files:** none (gate evidence only; record run IDs/exit codes in the phase progress notes).

**Interfaces:**
- Consumes: `helao/hexagon/tests/smoke/parity_run.sh` (`Usage: parity_run.sh <scenario> <config_prefix> <root> <golden_dir> <candidate_dir>`); goldens at `/home/dan/helao_goldens/GM-{1..5}` (captured per `harness/capture.py` docs as `.../GM-N/run1`); the goldenhex composition root `/home/dan/INST_hlo_hexsmoke` (`helao/deploy/test/configs/goldenhex.yml:15`); `conc_run.sh <item> <config_prefix> <root> [orch_key]` with items registered in `helao/hexagon/tests/smoke/conc_items.py` (`ITEMS["item2"/"item4"/"item6"/"item7"]`).

- [ ] **Step 1: GM parity re-runs (0 diffs each)**

```bash
for GM in GM-1 GM-2 GM-3 GM-4 GM-5; do
  bash helao/hexagon/tests/smoke/parity_run.sh "$GM" goldenhex \
    /home/dan/INST_hlo_hexsmoke \
    /home/dan/helao_goldens/$GM/run1 \
    /tmp/p2b1_cand/$GM || { echo "$GM FAILED"; break; }
done
```

Expected: exit 0 (PASS) for all five; each `parity-report.json` shows 0 diffs. Use the exact golden-dir layout the P1b2a gate records used (if the goldens live at `/home/dan/helao_goldens/GM-N` without a `run1` subdir, drop the suffix — check `ls /home/dan/helao_goldens/GM-1` first). Any diff = STOP, diagnose against the §5.4 quirk checklist (lazy open `w+`; `%%` exactly-once via `added_hlo_separator`; non-serializable ⇒ `{"error": "data was not serializable"}`; string payloads raw; the ≤5×0.1 s finished-packet drain then ≤5×0.1 s `num_data_queued <= num_data_written` wait then close-all + cancel; `epoch_ns` two legal stamp paths; atomic tmp shape `.<basename>.<uuid1hex>.tmp`; one-shot `a+` not `w+`), fix in the owning task's file, re-run the in-process suite, then re-run the failed GM.

- [ ] **Step 2: Launched honesty check (native carried the traffic)**

After the GM-1 run (before wiping the root for the next scenario, or re-launch once more):

```bash
grep -r "hexagon native write path grafted" /home/dan/INST_hlo_hexsmoke/LOGS/ | head -2
grep -r "hexagon native collaborators swapped for action" /home/dan/INST_hlo_hexsmoke/LOGS/ | head -5
```

Expected: at least one graft banner (SIM server startup) and one per-action swap line per contained action. Zero hits = the graft never ran on the launched composition — STOP (the hexagon shim/`deployment: hexagon` routing or the startup hook is broken), even if parity passed.

- [ ] **Step 3: §10.3 concurrency re-run (write-path swap must not perturb status/dispatch interleavings)**

```bash
# NOTE (corrected per P1b2b/P2a gate records): item2 uses the renamed-orch
# config goldenhexid (orch key HEXORC, root INST_hlo_hexid); item4/6/7 use
# goldenhexconc (orch key ORCH, root INST_hlo_hexconc). conc_run.sh signature:
# conc_run.sh <item> <config_prefix> <root> [orch_key]
bash helao/hexagon/tests/smoke/conc_run.sh item2 goldenhexid   /home/dan/INST_hlo_hexid   HEXORC || echo "item2 FAILED"
bash helao/hexagon/tests/smoke/conc_run.sh item4 goldenhexconc /home/dan/INST_hlo_hexconc ORCH   || echo "item4 FAILED"
bash helao/hexagon/tests/smoke/conc_run.sh item6 goldenhexconc /home/dan/INST_hlo_hexconc ORCH   || echo "item6 FAILED"
bash helao/hexagon/tests/smoke/conc_run.sh item7 goldenhexconc /home/dan/INST_hlo_hexconc ORCH   || echo "item7 FAILED"
```

Expected: exit 0 each. The in-process concurrency items 1/3/5 + the item-6 in-process members already ran in Task 11's suite via `test_concurrency_live.py`.

- [ ] **Step 4: Record gate evidence + commit progress note**

Record in the phase notes (`.superpowers/sdd/` or `.omc/` per controller convention — NOT a new report file elsewhere): five GM exit codes + parity-report paths, honesty grep counts, four conc item exit codes, suite count from Task 11.

---

## Self-Review

- [ ] **Scope coverage vs `p2b-scope.md` §2 + `p2b-decisions.md`:**
  - Creates: `adapters/native/__init__.py` (T1), native re-bodies of all four collaborator roles (T2 meta, T3 file, T4 stream, T5 finalizer), `NativeArtifactStoreAdapter` (T6, ConfigPort/ClockPort-constructible + `for_action`), `NativeDataSinkAdapter` (T7, thread-safety contract preserved verbatim via byte-identical `_nowait` bodies), `app/active_graft.py` (T9: contain_action reproduction + drift pin + between-init-and-myinit swap + meta_writer rebind), unit tests on real tmp trees + honesty tripwire (T9). ✓
  - Rewires: `build_wiring` + `ACTION_REQUIRED` (T8), `makeActionApp` startup/shutdown hooks (T10), config untouched (graft rides the existing `deployment: hexagon` shim — verified `helao/deploy/hexagon/servers/action/ws_simulator.py` needs no change). ✓
  - Keeps: `move_dir`/`zip_dir` keep-callable with the `{}` sentinel mapping (T6); `add_status`/`append_sample`/`set_estop` legacy-delegated (Q2, T7 + native `_finish` calling `self.active.add_status` unchanged); StatusBroadcaster/LiveBuffer/ExecutorRunner untouched; legacy wrap adapters retained (retire in P2e); syncer quirks excluded (P2c). ✓
  - Q1/Q2/Q3 decisions are implemented exactly and restated at each point of application. ✓
  - Gate: GM-1..5 (T12.1), honesty tripwire in-process (T9) + launched (T12.2), §10.3 re-run (T12.3), suite+pyright (T11), boundary extension (T1). ✓
- [ ] **Placeholder scan:** no TBD/TODO/"similar to Task N" in any step; the four big-body tasks use verbatim-copy instructions with the complete text of every edit plus a machine-checked source-parity test — deterministic, not a placeholder (rationale section documents why this beats retyping for byte parity).
- [ ] **Type/name consistency:** `NativeMetaFileWriter(base)` / `NativeDataFileWriter(active)` / `NativeDataStreamer(active)` / `NativeActionFinalizer(active)` used identically in T6/T7/T9 as produced in T2-T5; `collaborators_for` returns `(streamer, file_writer, finalizer)` in that order in both T6 (producer) and T9 (consumer); `bind_base`/`meta_writer_for`/`for_action` names match between T6 and T9/T12; `ActiveWriteGraft.close()` (sync) matches T10's shutdown hook (no await); fixture names `make_base`/`mk_action`/`mk_active`/`assert_source_parity` consistent across T2-T9.
- [ ] **Signature fidelity spot-checks against live source:** `contain_action` pin matches `base.py:438-456`; delegators verified call-time-resolving (`base.py:666-716`, `base.py:1149-1459`); `myinit` data_logger timing (`base.py:1014`); `ActiveParams` from `helao.helpers.active_params`; `MultisubscriberQueue.subscribe/subscribers/remove` used exactly as `active_data_stream.py:186,282-283`.

## Known reviewer-verification points (assumed internals — verify before executing)

1. **`test_active_graft.PINNED_CONTAIN_ACTION`** was transcribed from `base.py:438-456` at HEAD 06e0162b — the executing agent must diff it against `inspect.getsource(Base.contain_action)` on the live branch in Step 2 of Task 9 and correct the pin (and graft body) to the live source if they differ by even whitespace.
2. **Fixture completeness of `make_base`** (Task 2): the attribute set is derived from `unit_test_active_data_file.py:52-66` plus the graft/finish path's extra reads (`status_q`, `data_q`, `actives`, `history`, `local_action_task_queue`, `hlo_postprocessors`, `hlo_postprocess_libs`, `aloop`). If a test hits `AttributeError` on a bare-Base attribute (e.g. NTP fields inside `get_realtime_nowait`), add that attribute to `make_base` rather than weakening the test.
3. **Golden-dir layout + conc config prefixes** (Task 12): `/home/dan/helao_goldens/GM-N[/run1]` and `goldenhex`/`goldenhexconc` per-item mapping must match the P1b2a/P1b2b gate records; check before launching.
4. **`test_factory.py` existing shape** (Tasks 8/10): the plan appends tests using its `installed_config` fixture; if that file already has `makeActionApp`/`ACTION_REQUIRED` assertions, update them in place instead of duplicating.
5. **pytest-asyncio availability**: the hexagon suite already runs async tests; if the marker style differs (e.g. `asyncio_mode = auto` in config vs explicit `@pytest.mark.asyncio`), match the existing suite's style.
