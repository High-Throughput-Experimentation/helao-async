# P2c — Native Sync Pipeline (the long pole) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reimplement the 2093-line legacy sync pipeline (`helao/core/drivers/data/sync_driver.py`: `AsyncRWLock` / `HelaoYml` / `Progress` / `SyncDriver`) as a hexagon-native module `helao/hexagon/adapters/native/sync_driver.py` via VERBATIM byte-identical re-body pinned per-method by `inspect.getsource` source-parity tests (the proven P2b-1 pattern), replace the Base-coupled `HelaoSyncer` subclass with a boundary-clean `NativeSyncer` (D2), expose it through a wire-ready `NativeSyncAdapter` (SyncPort, D4, NOT wired into REQUIRED), and gate WITHOUT a launched cut-over (D3): ported legacy unit suites (process-recovery 6 scenarios + to_thread offload) run against the native driver, plus a direct-drive on-tree parity test that runs legacy and native syncers over identical copies of a GM-1-derived `RUNS_FINISHED` tree and asserts 0 diffs via the P0 parity harness (`harness.parity.run_parity`), including a reset_sync/finish_pending round-trip (the GM-5 analog).

**Architecture:** The legacy module's only `helao.core.servers.*` dependency is `from helao.core.servers.base import Base`, consumed solely by the 34-line `HelaoSyncer(SyncDriver)` subclass (sync_driver.py:2059-2093); `SyncDriver.__init__(config, helaodirs)` and every method body are Base-free. So the native module copies legacy lines **62–2057** (constants through `unsync_dir`) as one contiguous verbatim region — class names are NOT renamed, because the copied bodies construct `HelaoYml(...)` / `Progress(...)` by name and a rename would break byte-identity (D1) — drops the `Base` import and `HelaoSyncer`, and appends a native-only section (`SyncerHost` protocol + `NativeSyncer`) below a sentinel comment. Byte-parity is enforced three ways: (a) per-method `inspect.getsource` pins against the LIVE legacy module (66 pins, property/staticmethod/contextmanager-aware), (b) a cumulative verbatim-region containment pin (legacy lines 62–2057 must appear byte-identical inside the native module), (c) the direct-drive on-tree parity test reusing THE golden gate's diff pipeline (`explode_zips`/`seed_mapper`/`snapshot`/`diff_member_sets`/`diff_meta`/`diff_prg`/`diff_s3_record` + `internal_s3_checks`, which also asserts the 2 intentional S3-vs-disk quirks — FileInfo `x.hlo`→`x.hlo.json[.gz]` rename and `technique_name` list→str split — that live in the syncer and ARE P2c surface). The 728a663c process-recovery fix is preserved byte-identical by construction: `update_process` unified metas (:1436-1593, uuid-keyed idempotency :1424-1434, overlapping-groups fold :1456-1479), `reconcile_processes` (:1595-1626), `sync_process` phantom-drop (:1660-1695, api-skip :1718-1723), estopped-RUNS_ACTIVE-children-terminal (`sync_yml` :1084-1102). `PortWiring.sync` stays Optional-None and UNWIRED — the adapter is constructed/wired only in P2e (DB cut-over).

**Tech Stack:** Python 3.12 (`conda run -n helao`), pytest + pytest-asyncio strict markers (hexagon suite `helao/hexagon/tests/`), pyright (authoritative), black (with force-exclude for the re-body), boto3 (imported by the verbatim body; never contacted — tests are hermetic), the P0 parity harness (`harness/` at repo root: `treepass.py`, `s3_pass.py`, `yaml_pass.py`, `parity.py`), the sim DB server's `RecordingS3Client` (`helao/deploy/test/servers/action/sim_db_server.py:42-77`, imported read-only), golden set `/home/dan/helao_goldens/GM-1/run1`.

## Global Constraints

Every task's requirements implicitly include this section.

- **ZERO LEGACY EDITS**: only `helao/hexagon/**` + `pyproject.toml` (+ this plan file). Nothing under `helao/core/`, `helao/helpers/`, `helao/deploy/`. `sim_db_server.py` + `sync_driver.py` stay untouched (the re-body reads live legacy via `inspect` only, for the source-parity pins).
- **D1** verbatim byte-identical re-body + per-method source-parity pins vs LIVE legacy. Extend the pyproject black force-exclude regex to include the sync re-body module (it mirrors non-black-clean legacy). File-scope pyright suppression matches legacy `sync_driver.py`'s EXACT pre-existing rule-types — enumerated 2026-07-18 by `conda run -n helao pyright helao/core/drivers/data/sync_driver.py` as: `reportArgumentType` (5), `reportAttributeAccessIssue` (3), `reportCallIssue` (2), `reportOptionalMemberAccess` (2), `reportOptionalSubscript` (2). Suppress only those, in one `# pyright:` line after the module docstring, never inline in pinned bodies. (Re-run the enumeration in T2; if the set changed since branch-point, use the fresh set and note it in the commit message.)
- **D2** boundary: the native sync re-body imports ONLY `helao.helpers.*` / `helao.core.models.*` — NEVER `helao.core.servers.*` (the `adapters-native` boundary rule in `helao/hexagon/tests/test_boundaries.py` enforces this automatically for every file under `adapters/native/`). `NativeSyncer` replicates `HelaoSyncer.__init__`'s config-resolution (sync_driver.py:2072-2093) against a duck-typed `SyncerHost` protocol (NO Base import). The `SyncDriver` body stays verbatim (it never referenced Base).
- **D3** gate (NO launched cut-over — that's P2e): ported unit suite (both legacy sync tests against native) + the DIRECT-DRIVE on-tree parity test (T11) + reset_sync/finish_pending round-trip. Do NOT add `sync` to `ORCH_REQUIRED`/`ACTION_REQUIRED`; do NOT construct the adapter in `build_wiring` (no live consumer until P2e).
- **All Python via `conda run -n helao`** (never the OS python).
- **pyright `helao/hexagon` = 0 errors and black clean at the end of every task** (run black on changed *non-excluded* files immediately before each commit; NEVER run black on `adapters/native/sync_driver.py` — it is force-excluded and running it manually would break byte-identity).
- **No private-deployment names** anywhere in code, tests, docs, or commit messages.
- **Do NOT commit or push to `main`; work stays on `feat/hexagon-p2c-native-sync` (off unstable 6b35c697). No writes to production paths. Never commit golden-set data.**
- **Line ranges below are pinned to legacy `sync_driver.py` at the branch point.** Before every copy step, re-verify the anchor with the given `grep -n` command; if legacy drifted, STOP and report (do not adjust silently — the pins would catch it anyway, but drift means the branch point moved).

## Why "verbatim copy + source-parity test" instead of retyped bodies

`sync_driver.py` is 2093 lines of lock ordering (hierarchical seq-RW/exp-mutex), priority-floor re-enqueue (rank floor -5), process reconcile (the 728a663c recovery fix), `.prg` sidecar lifecycle, and the S3/zip leg — far too parity-risky to rewrite or retype. Byte-parity by construction (contiguous `sed` copies of the legacy region) + per-method drift pins against the LIVE legacy module is the approach that took P2b-1 through GM-1..GM-5 at 0 diffs. Behavior coverage (ported unit suites + direct-drive tree parity) is independent of the pins, so it survives P3's eventual legacy deletion (when the pins retire with the legacy module).

## File structure

```
pyproject.toml                                 # MODIFY (T1): force-exclude += sync_driver
helao/hexagon/adapters/native/
    sync_driver.py        # T2-T7: verbatim re-body (BLACK-EXCLUDED); T8 appends SyncerHost + NativeSyncer
    sync_adapter.py       # T8: NativeSyncAdapter (SyncPort) — hand-written, black-enforced
    __init__.py           # MODIFY (T8): exports NativeSyncer, NativeSyncAdapter
helao/hexagon/tests/
    sync_fixtures.py                      # T2: pin helper (property-aware) + tree builders + driver factory/drain/teardown
    test_native_sync_pins.py              # T2-T7: per-method source-parity pins + cumulative verbatim-region pin
    test_native_sync_driver.py            # T4: construction / enqueue-dedup / rank-floor smoke
    test_native_sync_adapter.py           # T8: SyncerHost resolution + SyncPort conformance + wiring-untouched
    test_native_sync_process_recovery.py  # T9: 6 ported recovery scenarios vs native
    test_native_sync_to_thread.py         # T10: ported to_thread offload guard vs native
    test_native_sync_parity.py            # T11: direct-drive GM-1 tree parity + round-trip
docs/superpowers/plans/2026-07-18-P2c-native-sync.md   # this plan
```

All tasks are **[PYTEST]** (pure in-process, subagent-executable). There is NO launched task in P2c — the launched GM-5 cut-over is P2e by decision D3.

## Legacy source map (authoritative copy regions — contiguous)

`helao/core/drivers/data/sync_driver.py` (2093 lines). The verbatim region is legacy lines **62–2057**, copied in six contiguous blocks:

| Task | Legacy lines | Content |
|---|---|---|
| T2 | 62–528 | `LOGGER` (:62), `ABR_MAP`/`MOD_MAP`/`PLURALS`/`MOD_PATCH` (:63-79), `dict2json` (:81-96), `move_to_synced` (:98-130), `revert_to_finished` (:132-155), `AsyncRWLock` (:157-201), `HelaoYml` (:202-528) |
| T3 | 529–672 | `Progress` (:529-672) |
| T4 | 673–1014 | `SyncDriver` class header + annotations (:673-689), `__init__` (:690-759), `try_remove_empty` (:760), `cleanup_root` (:795), `sync_exit_callback` (:830), `_rel_under_runs` (:847, staticmethod), `_node_keys` (:860), `_get_seq_lock` (:885), `_get_exp_lock` (:893), `_acquire_hierarchy_locks` (:901), `syncer` (:928), `get_progress` (:953), `enqueue_yml` (:987-1014) |
| T5 | 1015–1394 | `sync_yml` (:1015-1394; estopped-children-terminal :1084-1102) |
| T6 | 1395–1732 | `update_process` (:1395-1593), `reconcile_processes` (:1595-1626), `sync_process` (:1628-1731) |
| T7 | 1733–2057 | `to_s3` (:1733-1788), `to_api` (:1790-1808, STUB), `list_pending` (:1810), `list_pending_acts` (:1828), `list_pending_exps` (:1846), `finish_pending` (:1864-1914, nested `reset_and_queue` :1881), `reset_sync` (:1916-2036), `shutdown` (:2037), `unsync_dir` (:2041-2057) |

DROPPED (replaced by `NativeSyncer` in T8): `HelaoSyncer` (:2059-2093). Legacy header parts NOT copied verbatim: module docstring (:1-16), `__all__` (:18), imports (:20-60) — the native module gets its own docstring/`__all__`/pyright line and the import header per D2 (two edits, see T2).

---

### Task 1: pyproject black force-exclude extension + boundary-walk confirmation [PYTEST]

Land the formatter guard BEFORE the re-body module exists, so no later `black` invocation can ever reformat it.

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: existing `[tool.black]` `force-exclude` (pyproject.toml:12) covering the four P2b-1 re-bodies; existing `adapters-native` boundary rule in `helao/hexagon/tests/test_boundaries.py` (walks `rglob("*.py")` under `adapters/native/` — new files are covered automatically, no test change needed).
- Produces: force-exclude regex additionally matching `helao/hexagon/adapters/native/sync_driver.py`. Later tasks rely on: `black --check helao/hexagon` passes even though `sync_driver.py` mirrors non-black-clean legacy.

- [ ] **Step 1: Edit the force-exclude regex + comment**

In `pyproject.toml`, replace the `[tool.black]` block's comment and regex. The regex line becomes exactly:

```toml
force-exclude = 'helao/hexagon/adapters/native/(meta_writer|data_file|data_stream|finalizer|sync_driver)\.py'
```

Update the comment above it: change "Four native re-body modules" to "Five native re-body modules", and append one sentence: `# sync_driver.py is the P2c re-body of helao/core/drivers/data/sync_driver.py (D1); its hand-written NativeSyncAdapter sibling (sync_adapter.py) stays black-enforced.`

- [ ] **Step 2: Verify with a deliberately non-black probe file**

```bash
printf 'x =    1\n' > helao/hexagon/adapters/native/sync_driver.py
conda run -n helao black --check helao/hexagon/adapters/native/
rm helao/hexagon/adapters/native/sync_driver.py
```

Expected: black exits 0 and does NOT list `sync_driver.py` (output like `All done! ... N files would be left unchanged.`). If it flags the probe, the regex edit is wrong — fix before proceeding.

- [ ] **Step 3: Confirm the boundary walk needs no change**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_boundaries.py -q`
Expected: ALL PASS (the `adapters-native` layer rule from P2b-1 T1 covers every `*.py` under `adapters/native/` by construction; `sync_driver.py` will be policed automatically once created).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore(hexagon): black force-exclude covers the P2c sync re-body (P2c T1)"
```

---

### Task 2: Sync test fixtures + module skeleton with `AsyncRWLock` + `HelaoYml` re-body [PYTEST]

**Files:**
- Create: `helao/hexagon/tests/sync_fixtures.py`
- Create: `helao/hexagon/adapters/native/sync_driver.py`
- Test: `helao/hexagon/tests/test_native_sync_pins.py`

**Interfaces:**
- Consumes: legacy `sync_driver.py` lines 62–528 as the copy source; legacy import header :20-60; the tree-builder helpers proven by `helao/core/tests/unit_test_sync_process_recovery.py:39-117` (`_write_yml`/`_ts`/`_uuid`/`_exp_meta`/`_act_meta`/`_make_exp_tree`/`_make_action` — mirrored, not imported).
- Produces (later tasks rely on these exact names):
  - `sync_fixtures.assert_source_parity(native_owner, legacy_owner, names)` — property/staticmethod/`functools.wraps`-aware per-member `inspect.getsource` equality (unlike P2b-1's `native_fixtures.assert_source_parity`, which is plain-method only — `HelaoYml` has 20 `@property` members and `AsyncRWLock` has two `@asynccontextmanager` methods).
  - `sync_fixtures.assert_verbatim_region(end_line)` — asserts legacy lines 62..`end_line` appear byte-identical inside the native module.
  - `sync_fixtures.make_sync_driver(tmp_root, cls)` — `cls({"aws_bucket": "test-bucket", "max_tasks": 1}, HelaoDirs(root=..., save_root=<root>/RUNS_ACTIVE, process_root=<root>/PROCESSES))` (mirror of the legacy tests' `_make_driver`).
  - `sync_fixtures.teardown_driver(drv)` (async) — cancel `drv.syncer_loops` + gather.
  - `sync_fixtures.drain(drv, timeout=120.0)` (async) — poll until `task_queue.qsize() == 0 and not drv.running_tasks and not drv.task_set`, stable over 3 consecutive 0.1 s polls; raise `TimeoutError` past the deadline.
  - Tree builders `write_yml`, `ts`, `mk_uuid`, `exp_meta`, `act_meta`, `make_exp_tree`, `make_action` mirroring the legacy test helpers byte-for-byte in behavior (T9 depends on them).
  - Native module with `AsyncRWLock`, `HelaoYml` (legacy names kept) importable from `helao.hexagon.adapters.native.sync_driver`.

- [ ] **Step 1: Write the fixtures module**

`helao/hexagon/tests/sync_fixtures.py` (complete file):

```python
"""Shared fixtures for the P2c native-sync tests.

assert_source_parity here supersedes native_fixtures.assert_source_parity for
the sync re-body: HelaoYml is property-heavy and AsyncRWLock's lock context
managers are @asynccontextmanager-wrapped, so members are resolved via
inspect.getattr_static + property/staticmethod/wraps unwrapping before
getsource. Tree builders mirror the proven fixture shape of
helao/core/tests/unit_test_sync_process_recovery.py (bare SyncDriver on
tempdir trees; hermetic — no AWS/API).

Tests layer — may import anything (boundary rule)."""

import asyncio
import inspect
from datetime import datetime
from pathlib import Path

from helao.core.models.helaodirs import HelaoDirs
from helao.core.models.run_dir import RunDir
from helao.helpers.yml_tools import yml_dumps

LEGACY_SYNC_PATH = (
    Path(__file__).resolve().parents[3] / "core" / "drivers" / "data" / "sync_driver.py"
)
NATIVE_SYNC_PATH = (
    Path(__file__).resolve().parents[1] / "adapters" / "native" / "sync_driver.py"
)
REGION_START = 62  # first line of the verbatim legacy region (LOGGER = ...)


def _source_of(owner, name: str) -> str:
    obj = inspect.getattr_static(owner, name)
    if isinstance(obj, property):
        obj = obj.fget
    elif isinstance(obj, (staticmethod, classmethod)):
        obj = obj.__func__
    return inspect.getsource(inspect.unwrap(obj))


def assert_source_parity(native_owner, legacy_owner, names) -> None:
    """Byte-parity pin: each member's source must equal its legacy twin."""
    diffs = []
    for name in names:
        if _source_of(native_owner, name) != _source_of(legacy_owner, name):
            diffs.append(name)
    assert not diffs, f"native members drifted from legacy source: {diffs}"


def assert_verbatim_region(end_line: int) -> None:
    """Legacy lines REGION_START..end_line must appear byte-identical in the
    native module (contiguous-copy capstone; complements per-member pins).
    Reads the LIVE legacy file, so it also pins against legacy drift."""
    legacy = LEGACY_SYNC_PATH.read_text().splitlines(keepends=True)
    region = "".join(legacy[REGION_START - 1 : end_line])
    native = NATIVE_SYNC_PATH.read_text()
    assert region in native, (
        f"legacy lines {REGION_START}..{end_line} are not byte-identical "
        f"inside {NATIVE_SYNC_PATH.name}"
    )


def make_sync_driver(tmp_root, cls):
    """Bare sync driver on a tempdir tree; hermetic (s3/api unset).

    Must be called with a running event loop (SyncDriver.__init__ spawns the
    syncer worker tasks). Callers are responsible for teardown_driver()."""
    hd = HelaoDirs(
        root=Path(tmp_root),
        save_root=Path(tmp_root) / RunDir.ACTIVE.value,
        process_root=Path(tmp_root) / "PROCESSES",
    )
    cfg = {"aws_bucket": "test-bucket", "max_tasks": 1}
    return cls(cfg, hd)


async def teardown_driver(drv) -> None:
    for task in drv.syncer_loops.values():
        task.cancel()
    await asyncio.gather(*drv.syncer_loops.values(), return_exceptions=True)


async def drain(drv, timeout: float = 120.0) -> None:
    """Wait until the queue, running set, and dedup set are stably empty."""
    deadline = asyncio.get_running_loop().time() + timeout
    stable = 0
    while stable < 3:
        if asyncio.get_running_loop().time() > deadline:
            raise TimeoutError(
                f"sync drain timed out: qsize={drv.task_queue.qsize()} "
                f"running={list(drv.running_tasks)} task_set={drv.task_set}"
            )
        idle = (
            drv.task_queue.qsize() == 0
            and not drv.running_tasks
            and not drv.task_set
        )
        stable = stable + 1 if idle else 0
        await asyncio.sleep(0.1)


# --- tree builders (mirror unit_test_sync_process_recovery.py:39-117) ------


def write_yml(path: Path, meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    dumped = yml_dumps(meta)
    if isinstance(dumped, bytes):
        dumped = dumped.decode("utf-8")
    path.write_text(dumped, encoding="utf-8")


def ts(second: int) -> str:
    """Filename timestamp stem that HelaoYml can parse (%y%m%d.%H%M%S%f)."""
    return datetime(2026, 6, 10, 12, 0, second, 100).strftime("%y%m%d.%H%M%S%f")


def mk_uuid(tag: int) -> str:
    return f"00000000-0000-0000-0000-{tag:012d}"


def exp_meta(uuid: str, process_order_groups=None) -> dict:
    meta = {
        "experiment_uuid": uuid,
        "experiment_name": "test_exp",
        "sequence_uuid": mk_uuid(999),
        "technique_name": "test_tech",
        "run_type": "test",
        "experiment_params": {"foo": "bar"},
    }
    if process_order_groups is not None:
        meta["process_order_groups"] = process_order_groups
    return meta


def act_meta(order: int, process_finish: bool = False) -> dict:
    return {
        "action_uuid": mk_uuid(order),
        "action_name": "test_action",
        "action_order": order,
        "action_actual_order": order,
        "orch_submit_order": order,
        "action_split": 0,
        "action_timestamp": ts(order + 1),
        "process_finish": process_finish,
        "process_contrib": ["action_params"],
        "action_params": {f"p{order}": order},
        "technique_name": "test_tech",
    }


def make_exp_tree(root: Path, runs: str, exp_uuid: str, process_order_groups=None):
    """Create <root>/<runs>/26.23/0610/<seq>/<exp>/ and return the exp yml path."""
    exp_dir = (
        root
        / runs
        / "26.23"
        / "0610"
        / f"{ts(0)}__test__seq"
        / f"{ts(0)}__test_exp"
    )
    exp_yml = exp_dir / f"{ts(0)}-exp.yml"
    write_yml(exp_yml, exp_meta(exp_uuid, process_order_groups))
    return exp_yml


def make_action(exp_yml: Path, order: int, process_finish: bool = False) -> Path:
    """Create a child action dir + yml under the experiment dir; return act yml."""
    act_dir = exp_yml.parent / f"{order}__0__srv__test_action"
    act_yml = act_dir / f"{ts(order + 1)}-act.yml"
    write_yml(act_yml, act_meta(order, process_finish))
    return act_yml
```

- [ ] **Step 2: Write the failing pin tests**

`helao/hexagon/tests/test_native_sync_pins.py` (complete file; grown by T3–T7):

```python
"""Source-parity pins for the P2c native sync re-body (D1).

Every pinned member's source must be byte-identical to the LIVE legacy
module (helao/core/drivers/data/sync_driver.py) — proves the copy is exact
AND pins against future legacy drift. The verbatim-region test is the
capstone: the whole contiguous legacy region must appear unmodified inside
the native module. REGION_END grows per task (T2: 528 ... T7: 2057)."""

import helao.core.drivers.data.sync_driver as legacy_mod
import helao.hexagon.adapters.native.sync_driver as native_mod
from helao.hexagon.tests.sync_fixtures import (
    assert_source_parity,
    assert_verbatim_region,
)

REGION_END = 528  # T2; grows to 672 (T3), 1014 (T4), 1394 (T5), 1732 (T6), 2057 (T7)

MODULE_FUNCS = ["dict2json", "move_to_synced", "revert_to_finished"]

ASYNC_RW_LOCK = ["__init__", "read_locked", "write_locked"]

HELAO_YML = [
    "__init__", "parts", "check_paths", "exists", "__repr__", "type",
    "timestamp", "status", "meta_status", "is_estopped", "rename",
    "status_idx", "relative_path", "active_path", "finished_path",
    "synced_path", "cleanup", "list_children", "active_children",
    "finished_children", "synced_children", "children", "misc_files",
    "lock_files", "hlo_files", "parent_path", "write_meta",
]


def test_verbatim_region():
    assert_verbatim_region(REGION_END)


def test_module_functions_parity():
    assert_source_parity(native_mod, legacy_mod, MODULE_FUNCS)


def test_async_rw_lock_parity():
    assert_source_parity(native_mod.AsyncRWLock, legacy_mod.AsyncRWLock, ASYNC_RW_LOCK)


def test_helao_yml_parity():
    assert_source_parity(native_mod.HelaoYml, legacy_mod.HelaoYml, HELAO_YML)
```

- [ ] **Step 3: Run to verify failure**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_native_sync_pins.py -q`
Expected: collection FAILS with `ModuleNotFoundError: No module named 'helao.hexagon.adapters.native.sync_driver'`.

- [ ] **Step 4: Create the native module — header + verbatim block :62-528**

First re-verify anchors (both must print exactly one matching line at the stated number):

```bash
grep -n "^LOGGER = logging.make_logger" helao/core/drivers/data/sync_driver.py   # expect 62:
grep -n "^class Progress:" helao/core/drivers/data/sync_driver.py               # expect 529:
```

Write the module header of `helao/hexagon/adapters/native/sync_driver.py` — exactly this docstring, pyright line, and `__all__`:

```python
"""Native sync pipeline (hexagon P2c).

Verbatim re-body of the legacy sync driver
(``helao/core/drivers/data/sync_driver.py``): the module helpers,
``AsyncRWLock``, ``HelaoYml``, ``Progress``, and ``SyncDriver`` are
byte-identical copies of legacy lines 62-2057, source-parity-pinned per
member by ``test_native_sync_pins.py`` — including the 728a663c
process-recovery surface (``update_process`` unified metas,
``reconcile_processes`` cross-run replay, ``sync_process`` phantom-group
drop, estopped-children-terminal gate in ``sync_yml``). Class names are NOT
renamed: the copied bodies construct ``HelaoYml(...)`` / ``Progress(...)``
by name, so renaming would break byte-identity (D1).

The ONLY legacy import dropped is ``helao.core.servers.base.Base`` (D2):
the Base-coupled ``HelaoSyncer`` subclass is replaced by ``NativeSyncer``
(below the P2c native-only sentinel at the bottom of this module), which
replicates its config resolution against the narrow ``SyncerHost``
protocol — so this module imports only ``helao.helpers.*`` /
``helao.core.models.*`` and passes the adapters/native boundary rule.

Black-force-excluded (pyproject.toml): the legacy source is not black-clean
at 88. Only this docstring, the pyright file-scope suppression, ``__all__``,
two import-header lines (Base dropped, ``Protocol`` added to the typing
import), and the native-only section differ from legacy.
"""

# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportOptionalMemberAccess=false, reportOptionalSubscript=false

__all__ = ["AsyncRWLock", "HelaoYml", "Progress", "SyncDriver", "SyncerHost", "NativeSyncer"]
```

Then append the import header: copy legacy lines 20–60 VERBATIM (`import os` through `from glob import glob`) with EXACTLY two edits —
1. DELETE the line `from helao.core.servers.base import Base` (legacy :43).
2. CHANGE `from typing import Union, Optional, Dict, List` (legacy :30) to `from typing import Union, Optional, Dict, List, Protocol` (consumed by T8's `SyncerHost`; adding it now keeps the header frozen for the rest of the phase).

```bash
sed -n '20,60p' helao/core/drivers/data/sync_driver.py >> helao/hexagon/adapters/native/sync_driver.py
# then apply the two edits above to the appended block, and add one blank line
```

Then append the first verbatim block — copy, never retype:

```bash
sed -n '62,528p' helao/core/drivers/data/sync_driver.py >> helao/hexagon/adapters/native/sync_driver.py
```

NOTE: the pyright line will show unused-suppression-free behavior only once bodies that trigger each rule land (T4–T7); pyright does not error on not-yet-needed suppressions, so the full 5-rule line is safe from T2. `__all__` names `SyncerHost`/`NativeSyncer` before T8 defines them — that is fine for pyright/pytest as long as nothing does `from ... import *` (nothing does); if pyright flags the forward `__all__` entries, trim them from `__all__` now and restore in T8.

- [ ] **Step 5: Run to verify all pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_native_sync_pins.py helao/hexagon/tests/test_boundaries.py -q`
Expected: ALL PASS. (If a pin fails, the copy was edited beyond the header — re-copy with `sed`; never hand-fix a body.)

- [ ] **Step 6: pyright + black + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/tests/sync_fixtures.py helao/hexagon/tests/test_native_sync_pins.py
git add helao/hexagon/adapters/native/sync_driver.py helao/hexagon/tests/sync_fixtures.py helao/hexagon/tests/test_native_sync_pins.py
git commit -m "feat(hexagon): P2c sync re-body — module helpers + AsyncRWLock + HelaoYml, source-parity-pinned (P2c T2)"
```

Expected: pyright `0 errors`. black must list only the two test files (NEVER the re-body).

---

### Task 3: `Progress` re-body [PYTEST]

**Files:**
- Modify: `helao/hexagon/adapters/native/sync_driver.py` (append legacy :529-672)
- Modify: `helao/hexagon/tests/test_native_sync_pins.py`

**Interfaces:**
- Consumes: legacy `Progress` (:529-672; members `__init__` :548, `yml` :619 property, `list_unfinished_procs` :623, `read_dict` :643, `write_dict` :647, `s3_done` :658 property, `api_done` :663 property, `remove_prg` :667).
- Produces: `native_mod.Progress` with the exact legacy surface; `REGION_END = 672`.

- [ ] **Step 1: Extend the pin tests (failing first)**

In `test_native_sync_pins.py`: set `REGION_END = 672`, add:

```python
PROGRESS = [
    "__init__", "yml", "list_unfinished_procs", "read_dict", "write_dict",
    "s3_done", "api_done", "remove_prg",
]


def test_progress_parity():
    assert_source_parity(native_mod.Progress, legacy_mod.Progress, PROGRESS)
```

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_native_sync_pins.py -q`
Expected: `test_progress_parity` FAILS (`AttributeError: ... has no attribute 'Progress'`) and `test_verbatim_region` FAILS (region 62..672 not contained).

- [ ] **Step 2: Append the verbatim block**

```bash
grep -n "^class Progress:" helao/core/drivers/data/sync_driver.py    # expect 529:
grep -n "^class SyncDriver:" helao/core/drivers/data/sync_driver.py  # expect 673:
sed -n '529,672p' helao/core/drivers/data/sync_driver.py >> helao/hexagon/adapters/native/sync_driver.py
```

- [ ] **Step 3: Run to verify pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_native_sync_pins.py -q`
Expected: ALL PASS.

- [ ] **Step 4: pyright + black + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/tests/test_native_sync_pins.py
git add helao/hexagon/adapters/native/sync_driver.py helao/hexagon/tests/test_native_sync_pins.py
git commit -m "feat(hexagon): P2c sync re-body — Progress (.prg sidecar), source-parity-pinned (P2c T3)"
```

---

### Task 4: `SyncDriver` core — `__init__`, hierarchy locks, `syncer`, `enqueue_yml` [PYTEST]

**Files:**
- Modify: `helao/hexagon/adapters/native/sync_driver.py` (append legacy :673-1014)
- Modify: `helao/hexagon/tests/test_native_sync_pins.py`
- Test: `helao/hexagon/tests/test_native_sync_driver.py`

**Interfaces:**
- Consumes: legacy :673-1014 (see source map); `sync_fixtures.make_sync_driver`/`teardown_driver`.
- Produces: `native_mod.SyncDriver` constructible from `(config, helaodirs)` inside a running loop, with `s3`/`s3r`/`aws_session`/`api_host` None when unconfigured, `task_queue`/`task_set`/`running_tasks`/`exp_locks`/`seq_locks` initialized, and `max_tasks` syncer worker tasks spawned. `REGION_END = 1014`. NOTE: methods copied in T5–T7 (`sync_yml` etc.) are referenced by `syncer` only at call time — the partially-populated class imports and constructs cleanly.

- [ ] **Step 1: Extend the pin tests (failing first)**

In `test_native_sync_pins.py`: set `REGION_END = 1014`, add:

```python
SYNC_DRIVER_CORE = [
    "__init__", "try_remove_empty", "cleanup_root", "sync_exit_callback",
    "_rel_under_runs", "_node_keys", "_get_seq_lock", "_get_exp_lock",
    "_acquire_hierarchy_locks", "syncer", "get_progress", "enqueue_yml",
]


def test_sync_driver_core_parity():
    assert_source_parity(native_mod.SyncDriver, legacy_mod.SyncDriver, SYNC_DRIVER_CORE)
```

- [ ] **Step 2: Write the failing behavior tests**

`helao/hexagon/tests/test_native_sync_driver.py` (complete file):

```python
"""Native SyncDriver core behavior (P2c T4): hermetic construction (s3/api
None, worker tasks spawned), enqueue dedup, and the rank floor. Mirrors the
construction contract proven by unit_test_sync_to_thread.py:87-95."""

from pathlib import Path

import pytest

from helao.hexagon.adapters.native.sync_driver import SyncDriver as NativeSyncDriver
from helao.hexagon.tests.sync_fixtures import make_sync_driver, teardown_driver


@pytest.fixture(autouse=True)
def _hermetic_aws(monkeypatch):
    monkeypatch.delenv("AWS_CONFIG_PATH", raising=False)


@pytest.mark.asyncio
async def test_construction_hermetic(tmp_path):
    drv = make_sync_driver(str(tmp_path), NativeSyncDriver)
    try:
        assert drv.s3 is None and drv.s3r is None and drv.aws_session is None
        assert drv.api_host is None
        assert drv.bucket == "test-bucket"
        assert drv.task_queue.qsize() == 0
        assert len(drv.syncer_loops) == 1  # max_tasks=1
        assert all(not t.done() for t in drv.syncer_loops.values())
    finally:
        await teardown_driver(drv)


@pytest.mark.asyncio
async def test_enqueue_dedup_and_rank_floor(tmp_path):
    drv = make_sync_driver(str(tmp_path), NativeSyncDriver)
    # stop the workers FIRST so enqueued items stay observable
    await teardown_driver(drv)
    yml = Path(tmp_path) / "RUNS_FINISHED" / "x" / "260610.120000000000-seq.yml"
    await drv.enqueue_yml(yml, rank=2)
    await drv.enqueue_yml(yml, rank=2)  # dedup via task_set
    assert drv.task_queue.qsize() == 1
    other = yml.parent / "260610.120000000001-seq.yml"
    await drv.enqueue_yml(other, rank=-6)  # below rank_limit=-5 -> dropped
    assert drv.task_queue.qsize() == 1
```

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_native_sync_pins.py helao/hexagon/tests/test_native_sync_driver.py -q`
Expected: pin additions + both behavior tests FAIL (`AttributeError: ... no attribute 'SyncDriver'`).

- [ ] **Step 3: Append the verbatim block**

```bash
grep -n "^class SyncDriver:" helao/core/drivers/data/sync_driver.py  # expect 673:
grep -n "    async def sync_yml" helao/core/drivers/data/sync_driver.py  # expect 1015:
sed -n '673,1014p' helao/core/drivers/data/sync_driver.py >> helao/hexagon/adapters/native/sync_driver.py
```

- [ ] **Step 4: Run to verify pass**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_native_sync_pins.py helao/hexagon/tests/test_native_sync_driver.py helao/hexagon/tests/test_boundaries.py -q`
Expected: ALL PASS.

- [ ] **Step 5: pyright + black + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/tests/test_native_sync_pins.py helao/hexagon/tests/test_native_sync_driver.py
git add helao/hexagon/adapters/native/sync_driver.py helao/hexagon/tests/test_native_sync_pins.py helao/hexagon/tests/test_native_sync_driver.py
git commit -m "feat(hexagon): P2c sync re-body — SyncDriver core (init/locks/syncer/enqueue), pinned (P2c T4)"
```

---

### Task 5: `sync_yml` re-body (incl. estopped-children-terminal) [PYTEST]

**Files:**
- Modify: `helao/hexagon/adapters/native/sync_driver.py` (append legacy :1015-1394)
- Modify: `helao/hexagon/tests/test_native_sync_pins.py`

**Interfaces:**
- Consumes: legacy `sync_yml` (:1015-1394) — the 380-line pipeline heart: finished/synced gating, estopped-RUNS_ACTIVE-children-terminal rule (:1084-1102), child re-enqueue with decrementing rank toward the -5 floor, HLO push (incl. the >1 GB parquet conversion), the FileInfo S3-meta rename + `technique_name` list→str split (:1275, applied in the S3/prc copies only — P2c surface), patched-meta JSON push, move-to-SYNCED, destructive sequence zip, optional auto-analysis dispatch, `update_process`/`sync_process` handoff for contributing actions.
- Produces: pin `SYNC_DRIVER_YML = ["sync_yml"]`; `REGION_END = 1394`. Behavior coverage arrives with T9 (recovery scenarios drive `sync_yml` end-to-end on tempdir trees) and T11 (full-tree parity) — no standalone behavior test here, by design: any hand-rolled partial fixture would duplicate what the ported suites already prove.

- [ ] **Step 1: Extend the pin tests (failing first)**

Set `REGION_END = 1394`, add:

```python
def test_sync_yml_parity():
    assert_source_parity(native_mod.SyncDriver, legacy_mod.SyncDriver, ["sync_yml"])
```

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_native_sync_pins.py -q` — expect the two new/changed tests FAIL.

- [ ] **Step 2: Append the verbatim block**

```bash
grep -n "    async def sync_yml" helao/core/drivers/data/sync_driver.py     # expect 1015:
grep -n "    def update_process" helao/core/drivers/data/sync_driver.py    # expect 1395:
sed -n '1015,1394p' helao/core/drivers/data/sync_driver.py >> helao/hexagon/adapters/native/sync_driver.py
```

- [ ] **Step 3: Verify, then commit**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_native_sync_pins.py -q`
Expected: ALL PASS.

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/tests/test_native_sync_pins.py
git add helao/hexagon/adapters/native/sync_driver.py helao/hexagon/tests/test_native_sync_pins.py
git commit -m "feat(hexagon): P2c sync re-body — sync_yml (estopped-terminal gate incl.), pinned (P2c T5)"
```

---

### Task 6: `update_process` + `reconcile_processes` + `sync_process` (the 728a663c surface) [PYTEST]

**Files:**
- Modify: `helao/hexagon/adapters/native/sync_driver.py` (append legacy :1395-1732)
- Modify: `helao/hexagon/tests/test_native_sync_pins.py`

**Interfaces:**
- Consumes: legacy `update_process` (:1395-1593; unified legacy+non-legacy `process_metas` population :1436-1593, uuid-keyed idempotency :1424-1434, overlapping-groups fold :1456-1479), `reconcile_processes` (:1595-1626; cross-run replay, invoked from `sync_yml` :1250), `sync_process` (:1628-1731; phantom-group drop :1660-1695, api-skip :1718-1723). This block IS the process-recovery fix that MUST land byte-identical.
- Produces: pins for the three methods; `REGION_END = 1732`. Behavior coverage = T9 (all 6 scenarios).

- [ ] **Step 1: Extend the pin tests (failing first)**

Set `REGION_END = 1732`, add:

```python
SYNC_DRIVER_PROCESS = ["update_process", "reconcile_processes", "sync_process"]


def test_process_recovery_surface_parity():
    """The 728a663c fix must be byte-identical (plan MUST-PRESERVE)."""
    assert_source_parity(
        native_mod.SyncDriver, legacy_mod.SyncDriver, SYNC_DRIVER_PROCESS
    )
```

Run to confirm failure as before.

- [ ] **Step 2: Append the verbatim block**

```bash
grep -n "    def update_process" helao/core/drivers/data/sync_driver.py  # expect 1395:
grep -n "    async def to_s3" helao/core/drivers/data/sync_driver.py     # expect 1733:
sed -n '1395,1732p' helao/core/drivers/data/sync_driver.py >> helao/hexagon/adapters/native/sync_driver.py
```

- [ ] **Step 3: Verify, then commit**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_native_sync_pins.py -q`
Expected: ALL PASS.

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/tests/test_native_sync_pins.py
git add helao/hexagon/adapters/native/sync_driver.py helao/hexagon/tests/test_native_sync_pins.py
git commit -m "feat(hexagon): P2c sync re-body — process recovery surface (728a663c) byte-preserved (P2c T6)"
```

---

### Task 7: Tail re-body — `to_s3`/`to_api`/`list_pending*`/`finish_pending`/`reset_sync`/`shutdown`/`unsync_dir` + region capstone [PYTEST]

**Files:**
- Modify: `helao/hexagon/adapters/native/sync_driver.py` (append legacy :1733-2057)
- Modify: `helao/hexagon/tests/test_native_sync_pins.py`

**Interfaces:**
- Consumes: legacy `to_s3` (:1733-1788; `asyncio.to_thread` offload, retries ≤5 × 30 s, s3-unset ⇒ local-only True), `to_api` (:1790-1808, STUB by decision — returns True unconditionally, spec §1.3), `list_pending`/`list_pending_acts`/`list_pending_exps` (:1810-1862), `finish_pending` (:1864-1914), `reset_sync` (:1916-2036; zip→`.orig` reversal), `shutdown` (:2037-2040), `unsync_dir` (:2041-2057).
- Produces: pins for all nine members; `REGION_END = 2057` — the FULL verbatim region capstone now holds. After this task the native module equals legacy minus header minus `HelaoSyncer`.

- [ ] **Step 1: Extend the pin tests (failing first)**

Set `REGION_END = 2057`, add:

```python
SYNC_DRIVER_TAIL = [
    "to_s3", "to_api", "list_pending", "list_pending_acts",
    "list_pending_exps", "finish_pending", "reset_sync", "shutdown",
    "unsync_dir",
]


def test_sync_driver_tail_parity():
    assert_source_parity(native_mod.SyncDriver, legacy_mod.SyncDriver, SYNC_DRIVER_TAIL)
```

Run to confirm failure.

- [ ] **Step 2: Append the final verbatim block**

```bash
grep -n "    async def to_s3" helao/core/drivers/data/sync_driver.py   # expect 1733:
grep -n "^class HelaoSyncer" helao/core/drivers/data/sync_driver.py    # expect 2059:
sed -n '1733,2057p' helao/core/drivers/data/sync_driver.py >> helao/hexagon/adapters/native/sync_driver.py
```

- [ ] **Step 3: Verify (pins + full-region capstone + whole suite so far)**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_native_sync_pins.py helao/hexagon/tests/test_native_sync_driver.py helao/hexagon/tests/test_boundaries.py -q`
Expected: ALL PASS — `test_verbatim_region` now proves legacy :62-2057 is byte-identical inside the native module.

- [ ] **Step 4: pyright + black + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/tests/test_native_sync_pins.py
git add helao/hexagon/adapters/native/sync_driver.py helao/hexagon/tests/test_native_sync_pins.py
git commit -m "feat(hexagon): P2c sync re-body complete — full legacy region 62-2057 byte-pinned (P2c T7)"
```

---

### Task 8: `NativeSyncer` (drops Base) + `NativeSyncAdapter` (SyncPort) [PYTEST]

**Files:**
- Modify: `helao/hexagon/adapters/native/sync_driver.py` (append native-only section)
- Create: `helao/hexagon/adapters/native/sync_adapter.py`
- Modify: `helao/hexagon/adapters/native/__init__.py`
- Test: `helao/hexagon/tests/test_native_sync_adapter.py`

**Interfaces:**
- Consumes: legacy `HelaoSyncer.__init__` (:2072-2093) as the replication source (behavior, not bytes — this is the ONE deliberately-rewritten piece, per D2); `LegacySyncAdapter` (`helao/hexagon/adapters/legacy/sync.py`) as the surface template; `SyncPort` (`helao/hexagon/ports/sync.py`, `@runtime_checkable`).
- Produces:
  - `SyncerHost` protocol (`server_cfg: dict`, `world_cfg: dict`, `helaodirs: HelaoDirs`) and `NativeSyncer(SyncDriver)` in the native module, below a sentinel line `# --- P2c native-only section (not part of the verbatim legacy region) ---` (the sentinel guarantees the region capstone stays meaningful).
  - `NativeSyncAdapter` in `sync_adapter.py` with the full SyncPort surface: `enqueue_yml` / `sync_yml` / `finish_pending` / `reset_sync` / `to_s3` / `to_api` / `list_pending` / `n_queue` — construction-ready for P2e's DB shim; NOT wired anywhere.

- [ ] **Step 1: Write the failing tests**

`helao/hexagon/tests/test_native_sync_adapter.py` (complete file):

```python
"""NativeSyncer (D2: HelaoSyncer config resolution sans Base) +
NativeSyncAdapter (SyncPort conformance + delegation) + the D4 negative:
sync stays OUT of the REQUIRED wiring sets until P2e."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from helao.core.models.helaodirs import HelaoDirs
from helao.core.models.run_dir import RunDir
from helao.hexagon.adapters.native.sync_adapter import NativeSyncAdapter
from helao.hexagon.adapters.native.sync_driver import NativeSyncer
from helao.hexagon.app.wiring import ACTION_REQUIRED, ORCH_REQUIRED
from helao.hexagon.ports.sync import SyncPort
from helao.hexagon.tests.sync_fixtures import teardown_driver


@pytest.fixture(autouse=True)
def _hermetic_aws(monkeypatch):
    monkeypatch.delenv("AWS_CONFIG_PATH", raising=False)


def _host(tmp_path, local_params, world_db_params):
    hd = HelaoDirs(
        root=Path(tmp_path),
        save_root=Path(tmp_path) / RunDir.ACTIVE.value,
        process_root=Path(tmp_path) / "PROCESSES",
    )
    return SimpleNamespace(
        server_cfg={"params": local_params},
        world_cfg={"servers": {"DB": {"params": world_db_params}}},
        helaodirs=hd,
    )


@pytest.mark.asyncio
async def test_falls_back_to_db_params_without_aws_config_path(tmp_path):
    """HelaoSyncer semantics (sync_driver.py:2084-2091): local params lacking
    aws_config_path + DB present in world servers -> DB params win."""
    host = _host(
        tmp_path,
        local_params={"aws_bucket": "local-bucket", "max_tasks": 1},
        world_db_params={"aws_bucket": "db-bucket", "max_tasks": 1},
    )
    syncer = NativeSyncer(host)
    try:
        assert syncer.bucket == "db-bucket"
        assert syncer.s3 is None and syncer.api_host is None
    finally:
        await teardown_driver(syncer)


@pytest.mark.asyncio
async def test_keeps_local_params_with_aws_config_path(tmp_path, monkeypatch):
    aws_cfg = tmp_path / "aws.ini"
    aws_cfg.write_text("[default]\n", encoding="utf-8")
    host = _host(
        tmp_path,
        local_params={
            "aws_bucket": "local-bucket",
            "max_tasks": 1,
            "aws_config_path": str(aws_cfg),
            "aws_access_key_id": "x",
            "aws_secret_access_key": "y",
            "region": "us-west-1",
        },
        world_db_params={"aws_bucket": "db-bucket"},
    )
    syncer = NativeSyncer(host)
    try:
        assert syncer.bucket == "local-bucket"  # local params kept
        assert syncer.s3 is not None  # boto3 client built, never contacted
    finally:
        await teardown_driver(syncer)
        monkeypatch.delenv("AWS_CONFIG_PATH", raising=False)  # __init__ set it


@pytest.mark.asyncio
async def test_adapter_is_sync_port_and_delegates(tmp_path):
    host = _host(tmp_path, {"aws_bucket": "b", "max_tasks": 1}, {})
    syncer = NativeSyncer(host)
    adapter = NativeSyncAdapter(syncer)
    # stop workers so queue contents stay observable
    await teardown_driver(syncer)
    assert isinstance(adapter, SyncPort)
    assert adapter.n_queue() == 0
    await adapter.enqueue_yml(tmp_path / "RUNS_FINISHED" / "a-seq.yml", rank=2)
    assert adapter.n_queue() == 1
    assert (await adapter.to_api({}, "action")) is True  # documented STUB
    assert (await adapter.reset_sync(str(tmp_path / "nope"))) is False
    assert adapter.list_pending() == []


def test_sync_stays_unwired_until_p2e():
    """D4: no live hexagon consumer until the P2e DB cut-over."""
    assert "sync" not in ORCH_REQUIRED
    assert "sync" not in ACTION_REQUIRED
```

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_native_sync_adapter.py -q`
Expected: FAIL with `ImportError` (`sync_adapter` missing / `NativeSyncer` missing).

- [ ] **Step 2: Append the native-only section to `sync_driver.py`**

Append EXACTLY (after the verbatim region's last line, separated by two blank lines; hand-format black-style — this section is inside the excluded file but is new code):

```python
# --- P2c native-only section (not part of the verbatim legacy region) ---


class SyncerHost(Protocol):
    """Narrow duck-typed host surface ``NativeSyncer`` reads (D2: no Base)."""

    server_cfg: dict
    world_cfg: dict
    helaodirs: HelaoDirs


class NativeSyncer(SyncDriver):
    """Boundary-clean replacement for legacy ``HelaoSyncer`` (D2).

    Replicates HelaoSyncer.__init__'s config resolution
    (helao/core/drivers/data/sync_driver.py:2072-2093) against the
    ``SyncerHost`` protocol: local ``server_cfg['params']`` first, falling
    back to the global ``servers[db_server_name]['params']`` block when the
    local params carry no ``aws_config_path``. The P2e DB shim constructs
    this class; nothing in P2c wires it live.
    """

    def __init__(self, action_serv: SyncerHost, db_server_name: str = "DB"):
        self.host = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})
        self.world_config = action_serv.world_cfg
        if (
            not self.config_dict.get("aws_config_path", False)
            and db_server_name in self.world_config["servers"]
        ):
            self.config_dict = self.world_config["servers"][db_server_name].get(
                "params", {}
            )
        LOGGER.info("initializing SyncDriver")
        super().__init__(self.config_dict, self.host.helaodirs)
```

(One deliberate attr rename vs legacy: `self.base` → `self.host` — the native class holds no `Base`; document nothing else. The `LOGGER.info` line is kept verbatim from :2092.)

- [ ] **Step 3: Create `sync_adapter.py`**

`helao/hexagon/adapters/native/sync_adapter.py` (complete file — mirrors `LegacySyncAdapter`'s surface over the native driver; black-enforced):

```python
"""SyncPort adapter over the P2c native syncer (D4): thin delegation onto a
``NativeSyncer``/``SyncDriver`` instance from
``helao.hexagon.adapters.native.sync_driver``. All pipeline semantics (locks,
children gate, priority floor, process reconcile, .prg lifecycle) stay inside
the wrapped native driver — same shape as adapters/legacy/sync.py, which this
class replaces at the P2e DB cut-over. reset_sync/list_pending are sync in
the driver — bridged without behavior change. NOT constructed by
build_wiring in P2c (PortWiring.sync stays Optional-None; no REQUIRED entry)."""

from pathlib import Path
from typing import Union

from helao.hexagon.adapters.native.sync_driver import SyncDriver

__all__ = ["NativeSyncAdapter"]


class NativeSyncAdapter:
    def __init__(self, syncer: SyncDriver):
        self._syncer = syncer

    async def enqueue_yml(
        self, upath: Union[str, Path], rank: int = 0, rank_limit: int = -5
    ) -> None:
        await self._syncer.enqueue_yml(upath, rank=rank, rank_limit=rank_limit)

    async def sync_yml(
        self,
        yml_path: Path,
        retries: int = 3,
        rank: int = 5,
        force_s3: bool = False,
        force_api: bool = False,
        compress: bool = False,
    ) -> dict:
        return await self._syncer.sync_yml(
            yml_path,
            retries=retries,
            rank=rank,
            force_s3=force_s3,
            force_api=force_api,
            compress=compress,
        )

    async def finish_pending(self) -> list:
        return await self._syncer.finish_pending()

    async def reset_sync(self, sync_path: str) -> bool:
        return bool(self._syncer.reset_sync(sync_path))

    async def to_s3(
        self,
        msg: Union[dict, Path],
        target: str,
        retries: int = 5,
        compress: bool = False,
    ) -> bool:
        return await self._syncer.to_s3(msg, target, retries=retries, compress=compress)

    async def to_api(self, req_model: dict, meta_type: str, retries: int = 5) -> bool:
        return await self._syncer.to_api(req_model, meta_type, retries=retries)

    def list_pending(self, omit_manual_exps: bool = True) -> list:
        return self._syncer.list_pending(omit_manual_exps=omit_manual_exps)

    def n_queue(self) -> int:
        return int(self._syncer.task_queue.qsize())
```

Update `helao/hexagon/adapters/native/__init__.py`: append the two imports and extend the single `__all__`:

```python
from helao.hexagon.adapters.native.sync_driver import NativeSyncer
from helao.hexagon.adapters.native.sync_adapter import NativeSyncAdapter
```

and add `"NativeSyncer", "NativeSyncAdapter"` to `__all__` (keep one assignment).

- [ ] **Step 4: Run to verify pass (incl. boundary + pins)**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_native_sync_adapter.py helao/hexagon/tests/test_native_sync_pins.py helao/hexagon/tests/test_boundaries.py -q`
Expected: ALL PASS (boundary proves the whole module — native section included — never imports `helao.core.servers.*`; region capstone proves the appended section did not perturb the verbatim region).

- [ ] **Step 5: pyright + black + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/adapters/native/sync_adapter.py helao/hexagon/adapters/native/__init__.py helao/hexagon/tests/test_native_sync_adapter.py
git add helao/hexagon/adapters/native/sync_driver.py helao/hexagon/adapters/native/sync_adapter.py helao/hexagon/adapters/native/__init__.py helao/hexagon/tests/test_native_sync_adapter.py
git commit -m "feat(hexagon): NativeSyncer (Base-free HelaoSyncer) + NativeSyncAdapter (SyncPort, unwired) (P2c T8)"
```

---

### Task 9: Port `unit_test_sync_process_recovery` (6 scenarios) against the native driver [PYTEST]

**Files:**
- Test: `helao/hexagon/tests/test_native_sync_process_recovery.py`

**Interfaces:**
- Consumes: `helao/core/tests/unit_test_sync_process_recovery.py` (READ it in full — 362 lines) as the transcription source; `sync_fixtures` tree builders + `make_sync_driver`/`teardown_driver`.
- Produces: six pytest-asyncio tests driving the NATIVE `SyncDriver` over tempdir trees, proving the 728a663c recovery surface behaves identically. The legacy test file is NOT modified and NOT imported for logic (only mirrored).

- [ ] **Step 1: Transcribe the six scenarios (write all tests first)**

Create `helao/hexagon/tests/test_native_sync_process_recovery.py`. Mechanical translation rules — apply uniformly, no logic changes:
- `from helao.core.drivers.data.sync_driver import SyncDriver` → `from helao.hexagon.adapters.native.sync_driver import SyncDriver as NativeSyncDriver`; every `_make_driver(tmp_root)` → `make_sync_driver(tmp_root, NativeSyncDriver)` from `sync_fixtures` (identical cfg/HelaoDirs shape).
- `tempfile.TemporaryDirectory()` blocks → the pytest `tmp_path` fixture.
- The single `async def _run_checks()` accumulating `out["key"] = expr` → one `@pytest.mark.asyncio` test per scenario section, each `out["key"] = expr` becoming `assert expr, "key"`.
- Every scenario keeps its legacy teardown exactly: cancel `drv.syncer_loops` values + `await asyncio.gather(..., return_exceptions=True)` in a `finally:` (or call `sync_fixtures.teardown_driver`).
- Add the hermetic autouse fixture (`monkeypatch.delenv("AWS_CONFIG_PATH", raising=False)`), mirroring the legacy runner's env guard (legacy :319-327).
- Local helpers `_write_yml/_ts/_uuid/_exp_meta/_act_meta/_make_exp_tree/_make_action` → the `sync_fixtures` equivalents (`write_yml/ts/mk_uuid/exp_meta/act_meta/make_exp_tree/make_action`).

The six scenarios and the exact legacy blocks to mirror (each becomes one test; every listed assertion key MUST survive as an assert):

1. `test_legacy_experiment_populates_process_metas` — legacy :122-150. Keys: `legacy_flag`, `legacy_metas_populated`, `legacy_actions_done`, `legacy_finisher_recorded`.
2. `test_cross_run_reconcile_rebuilds_metas` — legacy :151-191 (reconcile half). Keys: `reconcile_before_empty`, `reconcile_group_present`, `reconcile_actions_done`, `reconcile_both_dispatched`.
3. `test_replay_is_idempotent` — legacy :151-191 (idempotency tail; keep in the same test as 2 if the legacy block shares state — mirror the block boundaries, do NOT re-derive). Key: `reconcile_idempotent`.
4. `test_phantom_group_dropped_experiment_finishes` — legacy :192-223. Keys: `phantom_unfinished_before`, `phantom_group_dropped`, `phantom_real_group_synced`, `phantom_experiment_completes`.
5. `test_split_actions_all_folded` — legacy :224-279 (includes the nested `_split_meta` helper — transcribe it inside the test). Keys: `split_both_dispatched`, `split_both_samples_kept`, `split_idempotent`.
6. `test_overlapping_groups_both_built_and_synced` — legacy :280-311. Keys: `overlap_both_metas_built`, `overlap_both_synced`, `overlap_experiment_completes`.

If scenarios 2 and 3 share driver/tree state in legacy, keep them as ONE test function (`test_cross_run_reconcile_and_idempotency`) — 6 scenarios may land as 5 test functions; the assertion-key census (all 19 keys present) is the completeness check, not the function count.

- [ ] **Step 2: Run to verify the port fails only for the right reason**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_native_sync_process_recovery.py -q`
Expected: ALL PASS immediately — the native bodies are byte-identical, so a failure here means a TRANSLATION bug (wrong fixture shape, missing teardown), not a re-body bug. Debug the test, never the module. (This inverts the usual TDD failure step: the "red" evidence for this task is Step 3.)

- [ ] **Step 3: Prove the tests actually bite (mutation check, then revert)**

Temporarily break the native module (e.g. in `update_process`, via `sed` on the NATIVE file only, flip one condition) — the recovery tests must FAIL; then `git checkout -- helao/hexagon/adapters/native/sync_driver.py` and re-run to green. Record in the commit message that the mutation check was performed. (Do NOT commit the mutation.)

- [ ] **Step 4: Legacy suite still green (zero-legacy-edit spot check)**

```bash
conda run -n helao python helao/core/tests/unit_test_sync_process_recovery.py; echo "exit=$?"
```
Expected: `exit=0`.

- [ ] **Step 5: pyright + black + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/tests/test_native_sync_process_recovery.py
git add helao/hexagon/tests/test_native_sync_process_recovery.py
git commit -m "test(hexagon): port sync process-recovery suite (6 scenarios) to native SyncDriver (P2c T9)"
```

---

### Task 10: Port `unit_test_sync_to_thread` against the native driver [PYTEST]

**Files:**
- Test: `helao/hexagon/tests/test_native_sync_to_thread.py`

**Interfaces:**
- Consumes: `helao/core/tests/unit_test_sync_to_thread.py` (READ in full — 213 lines) as transcription source: `_HeartBeat` (:52-70), `_BlockingS3` (:73-85), `BLOCK_S = 0.5` / `MAX_GAP_S = BLOCK_S / 2` (:43-49), `_run_checks` (:97-160); `move_to_synced` now imported from the NATIVE module (it is a pinned module function).
- Produces: pytest-asyncio guard that the native `to_s3` offloads blocking uploads via `asyncio.to_thread` and that the native `move_to_synced` + `zip_dir` legs keep the loop responsive.

- [ ] **Step 1: Transcribe**

Create `helao/hexagon/tests/test_native_sync_to_thread.py`. Same translation rules as T9. Import line becomes `from helao.hexagon.adapters.native.sync_driver import SyncDriver as NativeSyncDriver, move_to_synced` (note: `zip_dir` still from `helao.helpers.file_utils` — it is a keep-callable helper, not re-bodied). Keep `_HeartBeat`, `_BlockingS3`, `BLOCK_S`, `MAX_GAP_S` verbatim. Split `_run_checks` into three tests preserving every result key as an assert:

1. `test_construction_and_noop_s3` — keys `s3_none`, `api_none`, `to_s3_noop_true`.
2. `test_to_s3_offloads_blocking_upload` — keys `to_s3_returned_true`, `uploader_ran`, `upload_took_block_time`, `loop_responsive_upload`.
3. `test_move_and_zip_offload_keep_loop_responsive` — keys `move_returned_path`, `moved_into_synced`, `moved_out_of_finished`, `zip_created`, `loop_responsive_move_zip`.

Hermetic autouse `AWS_CONFIG_PATH` fixture as in T9. Teardown syncer loops in `finally` per test that constructs a driver.

- [ ] **Step 2: Run to verify**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_native_sync_to_thread.py -q`
Expected: ALL PASS (~2-3 s wall: the blocking-upload test sleeps 0.5 s). A `loop_responsive_*` failure under load is a real signal — re-run once; if persistent, STOP and report (do not widen `MAX_GAP_S`).

- [ ] **Step 3: Legacy twin still green**

```bash
conda run -n helao python helao/core/tests/unit_test_sync_to_thread.py; echo "exit=$?"
```
Expected: `exit=0`.

- [ ] **Step 4: pyright + black + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/tests/test_native_sync_to_thread.py
git add helao/hexagon/tests/test_native_sync_to_thread.py
git commit -m "test(hexagon): port sync to_thread offload guard to native SyncDriver (P2c T10)"
```

---

### Task 11: Direct-drive GM-1 on-tree parity + reset_sync/finish_pending round-trip (the P2c GM-5 analog) [PYTEST]

The D3 gate centerpiece: legacy `SyncDriver` and native `SyncDriver` each consume an identical copy of a real GM-1-derived `RUNS_FINISHED` tree, in-process, with a `RecordingS3Client`; the outputs (RUNS_SYNCED zip member set, PROCESSES `-prc.yml`, `S3_SIM/<bucket>/<key>` payloads, `manifest.jsonl`) must show **0 diffs** under THE golden gate's own comparator, `harness.parity.run_parity`.

**How the pre-sync input tree is obtained** (the goldens store POST-sync state — `RUNS_FINISHED` is empty in `/home/dan/helao_goldens/GM-1/run1/root`): reconstruct it with the LEGACY `reset_sync` (the pipeline's own reversal — the exact leg GM-5 exercises, hence the `.orig` sidecar in the GM-5 golden). The reconstruction runs once per test on a scratch copy; whatever tree it yields is copied byte-identically to BOTH sides, so input-prep bias is impossible.

**Files:**
- Test: `helao/hexagon/tests/test_native_sync_parity.py`

**Interfaces:**
- Consumes: `/home/dan/helao_goldens/GM-1/run1` (`root/` + `provenance.yml`); legacy `SyncDriver` + native `SyncDriver`; `RecordingS3Client` (`helao.deploy.test.servers.action.sim_db_server`); `harness.parity.run_parity(golden_set, candidate) -> dict` (explode_zips + seed_mapper + snapshot + diff_member_sets + per-row diff_meta/diff_prg/diff_hlo/diff_s3_record + internal_s3_checks — the FULL golden pipeline, including the 2 intentional S3-vs-disk rules); `sync_fixtures.drain`/`teardown_driver`.
- Produces: two gate tests — one full-sync parity, one reset+re-sync round-trip parity.

- [ ] **Step 1: Write the test (complete file)**

`helao/hexagon/tests/test_native_sync_parity.py`:

```python
"""P2c D3 gate: direct-drive on-tree parity, legacy vs native SyncDriver.

Input: a pre-sync RUNS_FINISHED tree reconstructed from the GM-1 golden via
the LEGACY reset_sync (the goldens are post-sync; reset_sync is the
pipeline's own reversal, proven by the GM-5 flow). Both drivers consume
byte-identical copies of that tree with a RecordingS3Client; outputs are
compared with harness.parity.run_parity — THE golden gate comparator —
asserting 0 diffs across RUNS_SYNCED zip members, PROCESSES -prc.yml,
S3_SIM payloads, and manifest.jsonl (internal_s3_checks additionally
asserts the 2 intentional S3-vs-disk quirks on BOTH outputs). The
round-trip test then reset_syncs + finish_pendings BOTH outputs again
(GM-5 analog) and re-asserts 0 diffs."""

import glob as globmod
import json
import os
import shutil
from pathlib import Path

import pytest

from harness.parity import run_parity
from helao.core.drivers.data.sync_driver import SyncDriver as LegacySyncDriver
from helao.core.models.helaodirs import HelaoDirs
from helao.core.models.run_dir import RunDir
from helao.deploy.test.servers.action.sim_db_server import RecordingS3Client
from helao.hexagon.adapters.native.sync_driver import SyncDriver as NativeSyncDriver
from helao.hexagon.tests.sync_fixtures import drain, teardown_driver

GOLDEN = Path(os.environ.get("HELAO_GOLDENS", "/home/dan/helao_goldens")) / "GM-1" / "run1"
BUCKET = "helao.data"  # matches the GM-1 capture's S3_SIM/<bucket> layout
CFG = {"aws_bucket": BUCKET, "max_tasks": 1}

pytestmark = pytest.mark.skipif(
    not GOLDEN.is_dir(), reason=f"GM-1 golden set not found at {GOLDEN}"
)
# NOTE: T12 verifies this module ran (0 skipped) — a silent skip guts the gate.


@pytest.fixture(autouse=True)
def _hermetic_aws(monkeypatch):
    monkeypatch.delenv("AWS_CONFIG_PATH", raising=False)


def _hd(root: Path) -> HelaoDirs:
    return HelaoDirs(
        root=root,
        save_root=root / RunDir.ACTIVE.value,
        process_root=root / "PROCESSES",
    )


async def _reconstruct_input(tmp_path: Path) -> Path:
    """Golden post-sync root -> pre-sync RUNS_FINISHED tree (legacy reset_sync)."""
    stage = tmp_path / "stage"
    shutil.copytree(GOLDEN / "root", stage)
    zips = globmod.glob(str(stage / RunDir.SYNCED.value / "**" / "*.zip"), recursive=True)
    assert len(zips) == 1, f"expected exactly one synced sequence zip, got {zips}"
    prep = LegacySyncDriver(CFG, _hd(stage))
    try:
        assert prep.reset_sync(zips[0]) is True
    finally:
        await teardown_driver(prep)
    for top in (RunDir.SYNCED.value, "PROCESSES", "S3_SIM", "ANALYSES", "RUNS_NOSYNC"):
        shutil.rmtree(stage / top, ignore_errors=True)
    seqs = globmod.glob(
        str(stage / RunDir.FINISHED.value / "**" / "*-seq.yml"), recursive=True
    )
    assert len(seqs) == 1, "reconstruction must yield exactly one pending sequence"
    return stage


async def _drive(root: Path, driver_cls) -> None:
    drv = driver_cls(CFG, _hd(root))
    drv.s3 = RecordingS3Client(root / "S3_SIM")
    try:
        await drv.finish_pending()
        await drain(drv, timeout=180.0)
    finally:
        await teardown_driver(drv)
    leftovers = globmod.glob(
        str(root / RunDir.FINISHED.value / "**" / "*.yml"), recursive=True
    )
    assert leftovers == [], f"{driver_cls.__module__}: unsynced ymls remain: {leftovers}"


def _assert_zero_diffs(legacy_set: Path, native_root: Path, tag: str) -> None:
    report = run_parity(legacy_set, native_root)
    assert report["status"] == "pass" and report["n_diffs"] == 0, (
        f"[{tag}] legacy-vs-native sync parity failed "
        f"(run {report['run_id']}):\n{json.dumps(report, indent=2, default=str)}"
    )


async def _prepare_both_sides(tmp_path: Path):
    stage = await _reconstruct_input(tmp_path)
    legacy_set = tmp_path / "legacy_set"
    legacy_set.mkdir()
    shutil.copytree(stage, legacy_set / "root")
    shutil.copy(GOLDEN / "provenance.yml", legacy_set / "provenance.yml")
    native_root = tmp_path / "native_root"
    shutil.copytree(stage, native_root)
    await _drive(legacy_set / "root", LegacySyncDriver)
    await _drive(native_root, NativeSyncDriver)
    return legacy_set, native_root


@pytest.mark.asyncio
async def test_direct_drive_tree_parity(tmp_path):
    legacy_set, native_root = await _prepare_both_sides(tmp_path)
    _assert_zero_diffs(legacy_set, native_root, "full-sync")


@pytest.mark.asyncio
async def test_reset_and_finish_pending_round_trip(tmp_path):
    """GM-5 analog: reset the synced output on BOTH sides with each side's own
    driver, re-sync via finish_pending, and re-assert 0 diffs (.orig included
    — explode_zips normalizes it into .origdir on both sides)."""
    legacy_set, native_root = await _prepare_both_sides(tmp_path)
    for root, driver_cls in (
        (legacy_set / "root", LegacySyncDriver),
        (native_root, NativeSyncDriver),
    ):
        zips = globmod.glob(
            str(root / RunDir.SYNCED.value / "**" / "*.zip"), recursive=True
        )
        assert len(zips) == 1
        drv = driver_cls(CFG, _hd(root))
        drv.s3 = RecordingS3Client(root / "S3_SIM")
        try:
            assert drv.reset_sync(zips[0]) is True
            assert Path(zips[0].replace(".zip", ".orig")).exists()
            await drv.finish_pending()
            await drain(drv, timeout=180.0)
        finally:
            await teardown_driver(drv)
    _assert_zero_diffs(legacy_set, native_root, "round-trip")
```

- [ ] **Step 2: Run the gate**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_native_sync_parity.py -q -x`
Expected: `2 passed` (NOT skipped), wall time roughly 1–4 min (four full in-process syncs + two parity runs). On failure, the assert prints the full `run_parity` report (tree/file/consistency diffs with normalized paths) — triage with `conda run -n helao python -m harness.normalize --root <side>` per the harness docs; a genuine diff between byte-identical bodies indicates an environment/input-prep asymmetry (check the two roots were copied from the SAME stage), not body drift — the T2–T7 pins rule that out.

- [ ] **Step 3: black + commit**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/tests/test_native_sync_parity.py
git add helao/hexagon/tests/test_native_sync_parity.py
git commit -m "test(hexagon): direct-drive GM-1 tree parity + reset/finish_pending round-trip, legacy vs native (P2c T11)"
```

---

### Task 12: Full verification sweep + zero-legacy proof [PYTEST]

**Files:** none new — verification only (fix-forward anything it finds, in the task that owns the file).

- [ ] **Step 1: Full hexagon suite (parity gate must RUN, not skip)**

Run: `conda run -n helao python -m pytest helao/hexagon -q`
Expected: ALL PASS, 0 failures (record the count; baseline before P2c was 268).

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_native_sync_parity.py -q -rs`
Expected: `2 passed` and NO `s` (skips) — the golden-set skipif must not have fired.

- [ ] **Step 2: Legacy-side sanity (unchanged legacy must still pass its own gates)**

```bash
conda run -n helao python run_unit_tests.py
conda run -n helao python helao/core/tests/unit_test_sync_process_recovery.py; echo "exit=$?"
conda run -n helao python helao/core/tests/unit_test_sync_to_thread.py; echo "exit=$?"
```
Expected: all PASS / `exit=0`.

- [ ] **Step 3: Zero-legacy-edit proof (mechanical)**

```bash
git diff --stat 6b35c697 -- helao/core helao/helpers helao/deploy
git diff --stat 6b35c697 -- pyproject.toml
```
Expected: first command EMPTY output; second shows ONLY the force-exclude hunk in `pyproject.toml`.

- [ ] **Step 4: pyright + black over everything**

```bash
conda run -n helao pyright helao/hexagon
conda run -n helao black --check helao/hexagon
```
Expected: pyright `0 errors`; black `would reformat 0 files` (`sync_driver.py` force-excluded, everything else clean). If the pyright suppression line in `sync_driver.py` carries a rule that is no longer needed (e.g. `reportOptionalSubscript`, whose legacy trigger lines lived in the dropped `HelaoSyncer`), it MAY be trimmed now — re-run pyright to confirm 0 errors either way, and keep the line's rule set ⊆ the legacy-enumerated five.

- [ ] **Step 5: Commit (only if fixes were needed); otherwise confirm clean**

```bash
git status --short   # expect clean
git log --oneline 6b35c697..HEAD   # expect the T1..T11 commit sequence
```

---

## Self-Review

- **Spec coverage vs `.superpowers/sdd/p2c-decisions.md`:** D1 (verbatim re-body + pins + black-exclude + legacy-enumerated pyright rules) = T1–T7. D2 (NativeSyncer sans Base, SyncerHost duck-type, boundary AST pass) = T2 header + T8. D3 (ported unit suites + direct-drive parity + reset/finish_pending round-trip; NO launched cut-over) = T9/T10/T11. D4 (NativeSyncAdapter wire-ready, NOT in REQUIRED) = T8 incl. the negative wiring test. D5 (sim_db_server/RecordingS3Client/orch.syncer/move_dir/to_api-stub untouched) = read-only import of RecordingS3Client only. D6 (zero legacy edits) = T12 Step 3 mechanical proof. MUST-PRESERVE 728a663c = T6 pins + T9 scenarios.
- **Every source-parity-pinned member is named:** 3 module functions + 3 `AsyncRWLock` + 27 `HelaoYml` + 8 `Progress` + 25 `SyncDriver` (12 core T4 + 1 `sync_yml` T5 + 3 process T6 + 9 tail T7) = **66 pins**, plus the cumulative verbatim-region capstone (legacy :62-2057).
- **Placeholder scan:** no TODO/stub steps; `to_api` remains a stub BY DECISION (spec §1.3) and is pinned verbatim, not reimplemented.
- **Type/name consistency:** legacy class names kept (`AsyncRWLock`/`HelaoYml`/`Progress`/`SyncDriver`) — required because pinned bodies construct `HelaoYml(...)`/`Progress(...)` by name; new names are only `SyncerHost`/`NativeSyncer`/`NativeSyncAdapter`. Test imports disambiguate via `as LegacySyncDriver` / `as NativeSyncDriver`.

## Known reviewer-verification points (assumed internals — verify before executing)

1. **GM-1 input-tree reconstruction (the load-bearing assumption):** the goldens are post-sync (`RUNS_FINISHED` empty; outputs in `RUNS_SYNCED/…zip` + `PROCESSES` + `S3_SIM`), so T11 reconstructs the pre-sync tree via legacy `reset_sync` on a scratch copy (zip → extracted `RUNS_FINISHED` tree minus `.prg`/`.lock`, zip renamed `.orig`). This is the pipeline's own reversal and the exact leg the GM-5 golden exercised (its `RUNS_SYNCED` contains both `.zip` and `.orig`). The reconstructed tree's yml statuses are the synced-patched versions, not the original finished ones — acceptable because BOTH sides consume byte-identical copies and because reset→re-sync is a production-proven flow (GM-5); if `finish_pending` were ever gated on yml-internal status rather than tree location, the `_reconstruct_input` assertion (`exactly one pending sequence`) fails loudly at Step 2.
2. **Legacy line ranges** were verified against the live file on 2026-07-18 (`grep -n` def map); every copy step re-checks its two anchors first.
3. **pyright rule enumeration** (5 types) captured 2026-07-18; T2 re-runs it.
4. **`inspect.getsource` on decorated members** (`@property` ×20, `@asynccontextmanager` ×2, `@staticmethod` ×1) resolves via `getattr_static` + unwrap in `sync_fixtures._source_of`; both sides are symmetric so decorator lines included in the source cannot cause asymmetric failures.
5. **`RecordingS3Client` import** pulls in `sim_db_server` (which imports `BaseAPI`) at module import — heavy but config-free; if importing it ever requires live CONFIG, fall back to transcribing the 36-line recorder into the test file (it is a sim fixture, not pinned legacy).
6. **Manifest ordering nondeterminism** is absorbed by `diff_s3_manifest` comparing sets; zip timestamps by `explode_zips` member-wise comparison; `.prg` timestamps by `diff_prg` — all reused from the golden gate, which already passes run1-vs-run2 (a strictly noisier comparison than same-input legacy-vs-native).
