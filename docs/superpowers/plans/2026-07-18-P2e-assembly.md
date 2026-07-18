# P2e Final Assembly (DB Native-Sync Cut-Over + Launched GM-5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the P2c `NativeSyncer` LIVE into the launched DB server via a startup sync-graft, cut the goldenhex config family over to `deployment: hexagon` for DB, retire the broken `ws_demo.yml`, and pass the LAUNCHED GM-5 parity gate (0 diffs vs legacy golden) — the P2c-deferred deliverable. After this merges and GM-5 passes, **P2 is COMPLETE**.

**Architecture:** Same instance-level graft seam as P2b-1's `active_graft.py`: BaseAPI's own startup hook builds the legacy `SimHelaoSyncer` and binds it to `app.driver`; a shim-registered startup hook that runs AFTER it cancels the legacy driver's orphaned `syncer_loops`, constructs a raw `NativeSyncer(base)` (Base satisfies the `SyncerHost` duck-type), replicates the `RecordingS3Client` injection for `s3_record`, and rebinds `app.driver` to the native instance. The DB shim (`helao/deploy/hexagon/servers/action/sim_db_server.py`) reuses `makeActionApp` exactly like the P2b ws_simulator shim, so the config flip is one `deployment: hexagon` key. Zero harness changes: `parity_run.sh` + `harness.capture`/`harness.parity` run GM-5 unmodified.

**Tech Stack:** Python 3.12 in the `helao` conda env; pytest + pytest-asyncio (`helao/hexagon/tests`); pyright (authoritative) via `pyrightconfig.json`; `black` (line length 88) on changed files before every commit; bash smoke gate `helao/hexagon/tests/smoke/parity_run.sh`.

**Branch:** `feat/hexagon-p2e-assembly` (off unstable 6ff7ff69 — already checked out).

## Global Constraints

- **ZERO LEGACY EDITS:** only NEW files under `helao/hexagon/**`, `helao/deploy/hexagon/**`, `helao/hexagon/tests/**`, config YAML flips (`helao/deploy/test/configs/`), the ws_demo delete, and this plan doc. NO edits to `helao/core`, `helao/helpers`, the legacy `sim_db_server.py`/`sync_driver.py`/`base_api.py`, `harness/`, `bokeh_launcher.py`, `launch.py`. Importing `RecordingS3Client` from `helao.deploy.test.servers.action.sim_db_server` is an import, not an edit (precedent: `factory.py` imports `helao.deploy.test.*` as `LEGACY_MODULE`).
- **Bind the RAW `NativeSyncer`** (NOT `NativeSyncAdapter`/`LegacySyncAdapter` — their `finish_pending(self)` drops `actions_first` and they expose no `running_tasks`/`task_queue`, which the DB endpoints need).
- **Cancel the pre-existing legacy driver's `syncer_loops`** at graft time (orphan fix — BaseAPI startup already spawned them; `shutdown()` is a no-op; a bare rebind leaks them).
- **Replicate the `RecordingS3Client` injection** when `params.s3_record` is set (else the launched GM-5 S3 leg stops recording and the S3_SIM manifest diff fails).
- `conda run -n helao` for all tooling (python, pytest, pyright, black). NEVER the OS python.
- `black <changed files>` as the final step before every `git add`/`git commit`.
- Do NOT commit or push to any branch other than `feat/hexagon-p2e-assembly`; no pushes to remote unless the controller explicitly asks.
- `/current_progress` raising `AttributeError` (`self.progress` never assigned) is a PRE-EXISTING legacy behavior on both stacks — do NOT "fix" it (out of scope, D7).
- Ordering (D3): the DB shim (Task 2) MUST be committed before any config flip (Task 3), else `deployment: hexagon` is a `ModuleNotFoundError` at launch.

---

### Task 1: `sync_graft.py` — cancel legacy loops, construct NativeSyncer, rebind `app.driver`

**Files:**
- Create: `helao/hexagon/app/sync_graft.py`
- Test: `helao/hexagon/tests/test_sync_graft.py`

**Interfaces:**
- Consumes: `NativeSyncer(action_serv: SyncerHost, db_server_name="DB")` from `helao/hexagon/adapters/native/native_syncer.py` (P2c; `SyncerHost` = duck-type with `server_cfg: dict`, `world_cfg: dict`, `helaodirs: HelaoDirs` — the live `Base` satisfies it: base.py:142/:148/:177). `RecordingS3Client(sim_root: Path)` from `helao.deploy.test.servers.action.sim_db_server` (sim_db_server.py:40-75). `Base.app` back-ref (base.py:139 `self.app = app`) — this is how the graft reaches `app.driver` from `base`. `teardown_driver(drv)` from `helao/hexagon/tests/sync_fixtures.py` (cancels + gathers `drv.syncer_loops`).
- Produces: `graft_native_sync(base, params: dict) -> NativeSyncGraft` and `NativeSyncGraft` (fields `app`, `native: NativeSyncer`, `originals: Dict[str, object]`; method `close() -> None`). Task 2's shim hook calls `graft_native_sync(app.base, app.base.server_cfg.get("params", {}))` and stores the handle on `app.hexagon_sync_graft`.

**Design notes (binding, from D1):**
- The graft is a plain sync function (like `graft_active_write_path`), but MUST be called with a running event loop (`NativeSyncer.__init__` → `SyncDriver.__init__` spawns `max_tasks` `asyncio.create_task(self.syncer(), ...)` worker loops at native sync_driver.py:765-768). The shim's async startup hook guarantees that.
- Only `app.driver` is rebound. `app.drivers` (the namedtuple) is left holding the legacy instance on purpose: the DB endpoints read `app.driver` exclusively (sim_db_server.py:111-151), and BaseAPI's shutdown hook calls `self.driver.shutdown()` (base_api.py:813) — which resolves to the native instance post-graft (`SyncDriver.shutdown()` is a no-op on both stacks).
- `RecordingS3Client` is imported at module level. `sim_db_server` imports `BaseAPI` + `HelaoSyncer`, both config-free at import time; the Step-2 test import proves it (reviewer point 3). Boundary rule: `app/` may import anything except `helao.hexagon.tests` — this import is legal.
- The `params` arg is the DB server's local `server_cfg["params"]`. `NativeSyncer` internally resolves config the legacy way (local params → world `servers["DB"]["params"]` fallback); on the DB server itself both are the same block, so checking `params.get("s3_record")` matches `SimHelaoSyncer`'s post-fallback `self.config_dict.get("s3_record")` exactly.

- [ ] **Step 1: Write the failing test**

Create `helao/hexagon/tests/test_sync_graft.py`:

```python
"""P2e sync graft (D1): cancel the legacy driver's orphaned syncer loops,
construct a raw NativeSyncer against the SyncerHost duck-type, replicate the
RecordingS3Client injection for s3_record, and rebind app.driver. The DB
endpoints (sim_db_server.py:111-151) read app.driver exclusively, so the
rebind is the whole cut-over; the launched GM-5 gate (Task 4) is the proof."""

import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from helao.core.models.helaodirs import HelaoDirs
from helao.core.models.run_dir import RunDir
from helao.deploy.test.servers.action.sim_db_server import RecordingS3Client
from helao.hexagon.adapters.native.native_syncer import NativeSyncer
from helao.hexagon.tests.sync_fixtures import teardown_driver

PARAMS = {"aws_bucket": "helao-sim", "max_tasks": 1}


@pytest.fixture(autouse=True)
def _hermetic_aws(monkeypatch):
    monkeypatch.delenv("AWS_CONFIG_PATH", raising=False)


def _fake_base(tmp_path, params):
    """Duck-typed Base: SyncerHost surface + the .app back-ref (base.py:139)."""
    hd = HelaoDirs(
        root=Path(tmp_path),
        save_root=Path(tmp_path) / RunDir.ACTIVE.value,
        process_root=Path(tmp_path) / "PROCESSES",
    )
    app = SimpleNamespace(driver=None)
    base = SimpleNamespace(
        app=app,
        server_cfg={"params": params},
        world_cfg={"servers": {"DB": {"params": params}}},
        helaodirs=hd,
    )
    return base, app


async def _fake_legacy_driver():
    """Stands in for the SimHelaoSyncer BaseAPI startup already built: the
    only surface the graft touches is .syncer_loops (real blocked tasks)."""
    blocker = asyncio.Event()
    loops = {i: asyncio.create_task(blocker.wait()) for i in range(2)}
    return SimpleNamespace(syncer_loops=loops), loops


@pytest.mark.asyncio
async def test_graft_rebinds_driver_and_cancels_legacy_loops(tmp_path):
    from helao.hexagon.app.sync_graft import NativeSyncGraft, graft_native_sync

    base, app = _fake_base(tmp_path, dict(PARAMS))
    old_driver, old_loops = await _fake_legacy_driver()
    app.driver = old_driver

    handle = graft_native_sync(base, dict(PARAMS))
    try:
        assert isinstance(handle, NativeSyncGraft)
        assert isinstance(app.driver, NativeSyncer)
        assert app.driver is handle.native
        assert handle.originals["driver"] is old_driver
        # orphan fix: every pre-existing worker loop is cancelled
        results = await asyncio.gather(
            *old_loops.values(), return_exceptions=True
        )
        assert all(isinstance(r, asyncio.CancelledError) for r in results)
    finally:
        await teardown_driver(app.driver)


@pytest.mark.asyncio
async def test_graft_injects_recording_s3_when_s3_record(tmp_path):
    from helao.hexagon.app.sync_graft import graft_native_sync

    params = dict(PARAMS, s3_record=True)
    base, app = _fake_base(tmp_path, params)
    old_driver, _ = await _fake_legacy_driver()
    app.driver = old_driver

    graft_native_sync(base, params)
    try:
        assert isinstance(app.driver.s3, RecordingS3Client)
        # mirrors SimHelaoSyncer.__init__ (sim_db_server.py:81-85)
        assert app.driver.s3.sim_root == Path(tmp_path) / "S3_SIM"
    finally:
        await teardown_driver(app.driver)


@pytest.mark.asyncio
async def test_graft_leaves_s3_none_without_s3_record(tmp_path):
    from helao.hexagon.app.sync_graft import graft_native_sync

    base, app = _fake_base(tmp_path, dict(PARAMS))
    old_driver, _ = await _fake_legacy_driver()
    app.driver = old_driver

    graft_native_sync(base, dict(PARAMS))
    try:
        assert app.driver.s3 is None  # local-only mode (sync completes locally)
    finally:
        await teardown_driver(app.driver)


@pytest.mark.asyncio
async def test_native_driver_exposes_db_endpoint_surface(tmp_path):
    """Every attribute the DB endpoints resolve on app.driver
    (sim_db_server.py:111-146) must exist on the grafted native instance;
    finish_pending must keep the actions_first kwarg the harness posts."""
    from helao.hexagon.app.sync_graft import graft_native_sync

    base, app = _fake_base(tmp_path, dict(PARAMS))
    old_driver, _ = await _fake_legacy_driver()
    app.driver = old_driver

    graft_native_sync(base, dict(PARAMS))
    try:
        drv = app.driver
        for attr in (
            "enqueue_yml",
            "list_pending",
            "finish_pending",
            "reset_sync",
            "running_tasks",
            "task_queue",
        ):
            assert hasattr(drv, attr), attr
        assert "actions_first" in inspect.signature(drv.finish_pending).parameters
        assert drv.task_queue.qsize() == 0
        assert drv.running_tasks == {}
        # NOTE: `progress` is deliberately ABSENT on both stacks
        # (assignment commented out) — /current_progress AttributeError is
        # pre-existing legacy behavior, pinned here so nobody "fixes" it.
        assert not hasattr(drv, "progress")
    finally:
        await teardown_driver(app.driver)


@pytest.mark.asyncio
async def test_graft_close_restores_original_driver(tmp_path):
    from helao.hexagon.app.sync_graft import graft_native_sync

    base, app = _fake_base(tmp_path, dict(PARAMS))
    old_driver, _ = await _fake_legacy_driver()
    app.driver = old_driver

    handle = graft_native_sync(base, dict(PARAMS))
    native = handle.native
    handle.close()
    assert app.driver is old_driver
    results = await asyncio.gather(
        *native.syncer_loops.values(), return_exceptions=True
    )
    assert all(isinstance(r, asyncio.CancelledError) for r in results)


@pytest.mark.asyncio
async def test_graft_fails_loud_without_live_legacy_driver(tmp_path):
    """Startup-order guard: if BaseAPI's own startup has not populated
    app.driver, the graft must abort loudly, never bind over nothing."""
    from helao.hexagon.app.sync_graft import graft_native_sync

    base, app = _fake_base(tmp_path, dict(PARAMS))
    assert app.driver is None
    with pytest.raises(RuntimeError, match="app.driver"):
        graft_native_sync(base, dict(PARAMS))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_sync_graft.py -v`
Expected: 6 FAILED/ERROR, each with `ModuleNotFoundError: No module named 'helao.hexagon.app.sync_graft'`

- [ ] **Step 3: Write the implementation**

Create `helao/hexagon/app/sync_graft.py`:

```python
"""Native sync graft (P2e, D1) — the sync-leg analog of active_graft.py:
instance-level rebinding is the sanctioned wrap seam; NO legacy source is
modified.

What it reroutes: the DB server's ``app.driver``. BaseAPI's own startup
closure (base_api.py:669/:672) constructs the legacy ``SimHelaoSyncer`` and
binds it first; this graft — invoked from the DB shim's startup hook, which
Starlette runs AFTER BaseAPI's — (a) cancels the legacy driver's
``syncer_loops`` worker tasks (orphan fix: ``shutdown()`` is a no-op, a bare
rebind would leak them idle on an empty queue), (b) constructs the raw P2c
``NativeSyncer`` against the live ``Base`` (which satisfies the ``SyncerHost``
duck-type: server_cfg/world_cfg/helaodirs, base.py:142/:148/:177), (c)
replicates ``SimHelaoSyncer.__init__``'s ``RecordingS3Client`` injection
(sim_db_server.py:81-85) when ``params.s3_record`` is set, and (d) rebinds
``app.driver``. Every DB endpoint (sim_db_server.py:111-151) resolves
``app.driver`` at call time, so 100% of sync traffic routes native.

Binds the RAW ``NativeSyncer`` — NOT ``NativeSyncAdapter`` (its
``finish_pending(self)`` drops the ``actions_first`` kwarg the harness posts,
and it exposes no ``running_tasks``/``task_queue`` for ``/tasks``+``/n_queue``).

Must be called with a running event loop: ``SyncDriver.__init__`` spawns the
``max_tasks`` syncer worker tasks (native sync_driver.py:765).
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

from helao.deploy.test.servers.action.sim_db_server import RecordingS3Client
from helao.helpers import helao_logging as logging
from helao.hexagon.adapters.native.native_syncer import NativeSyncer

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

__all__ = ["NativeSyncGraft", "graft_native_sync"]


@dataclass
class NativeSyncGraft:
    app: object
    native: NativeSyncer
    originals: Dict[str, object] = field(default_factory=dict)

    def close(self) -> None:
        """Symmetric unhook: cancel the native worker loops, restore the
        pre-graft driver. Tasks are cancelled, not awaited (shutdown path)."""
        for task in self.native.syncer_loops.values():
            task.cancel()
        self.app.driver = self.originals["driver"]  # type: ignore[attr-defined]


def graft_native_sync(base, params: dict) -> NativeSyncGraft:
    """Rebind the DB server's ``app.driver`` from the legacy SimHelaoSyncer
    to the P2c NativeSyncer. ``base`` is the live legacy ``Base`` (its
    ``.app`` back-ref, base.py:139, reaches the FastAPI app); ``params`` is
    the DB server's local ``server_cfg['params']`` — on the DB server the
    NativeSyncer's world-config fallback resolves to the SAME block, so
    ``params.get('s3_record')`` matches SimHelaoSyncer's post-fallback read.
    """
    app = base.app
    old_driver = getattr(app, "driver", None)
    if old_driver is None:
        raise RuntimeError(
            "sync graft needs the legacy syncer live on app.driver; BaseAPI's "
            "startup has not run (hook order broke) or driver_classes was empty"
        )
    # Orphan fix (D1): BaseAPI startup already spawned the legacy syncer's
    # worker loops; cancel them before the native instance takes over.
    for task in getattr(old_driver, "syncer_loops", {}).values():
        task.cancel()
    native = NativeSyncer(base)
    if params.get("s3_record", False):
        # Replicates SimHelaoSyncer.__init__ (sim_db_server.py:81-85).
        # IMPORT of legacy sim code, not an edit (precedent: factory.py
        # imports helao.deploy.test.* as LEGACY_MODULE).
        native.s3 = RecordingS3Client(Path(base.helaodirs.root) / "S3_SIM")
    graft = NativeSyncGraft(app=app, native=native)
    graft.originals["driver"] = old_driver
    # The DB endpoints resolve app.driver at call time; app.drivers (the
    # namedtuple) intentionally keeps the legacy instance — nothing reads it,
    # and BaseAPI's shutdown hook resolves self.driver (now native; its
    # shutdown() is a no-op on both stacks).
    app.driver = native
    LOGGER.info(
        "hexagon native sync grafted (app.driver -> NativeSyncer; legacy "
        f"{type(old_driver).__name__} syncer_loops cancelled)"
    )
    return graft
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_sync_graft.py -v`
Expected: `6 passed`

- [ ] **Step 5: Boundary + type check the new module**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_boundaries.py -q`
Expected: pass (app/ layer may import anything except `helao.hexagon.tests`)

Run: `conda run -n helao pyright helao/hexagon/app/sync_graft.py helao/hexagon/tests/test_sync_graft.py`
Expected: `0 errors, 0 warnings, 0 informations` (add `# type: ignore[...]` narrowly if pyright flags the duck-typed `base`/`app` attribute access, mirroring active_graft.py's style)

- [ ] **Step 6: Format and commit**

```bash
conda run -n helao black helao/hexagon/app/sync_graft.py helao/hexagon/tests/test_sync_graft.py
git add helao/hexagon/app/sync_graft.py helao/hexagon/tests/test_sync_graft.py
git commit -m "feat(hexagon): P2e sync graft — rebind DB app.driver to raw NativeSyncer

Cancels the legacy SimHelaoSyncer's orphaned syncer_loops, constructs
NativeSyncer against the live Base (SyncerHost duck-type), replicates the
RecordingS3Client injection for s3_record, rebinds app.driver. D1."
```

---

### Task 2: DB shim — `deployment: hexagon` module for `sim_db_server`

**Files:**
- Create: `helao/deploy/hexagon/servers/action/sim_db_server.py`
- Test: `helao/hexagon/tests/test_db_shim.py`
- (No `__init__.py` change: `helao/deploy/hexagon/servers/action/__init__.py` already exists and covers the package.)

**Interfaces:**
- Consumes: `makeActionApp(server_key: str, legacy_module: str)` from `helao/hexagon/app/factory.py` (registers `_hexagon_active_graft_startup` after the legacy BaseAPI startup); `graft_native_sync(base, params) -> NativeSyncGraft` from Task 1.
- Produces: `makeApp(server_key) -> HelaoFastAPI` — the module the launcher resolves for a config entry with `group: action`, `fast: sim_db_server`, `deployment: hexagon` (path `helao.deploy.hexagon.servers.action.sim_db_server`). Startup-hook order on the built app: BaseAPI `startup_event` (creates `app.base` + legacy `SimHelaoSyncer` on `app.driver`) → default-head lambda → `_hexagon_active_graft_startup` → `_hexagon_sync_graft_startup` (ours, LAST).

**Design note (D2):** `makeActionApp`'s write graft + WS bridge are expected-harmless on the DB server (its Base has `contain_action`/`meta_writer` and the status/data/live queues; `ACTION_REQUIRED` is satisfied by `build_wiring` unconditionally; the DB server simply never contains an action). The Task 4 launch is the real proof. **Fallback if the launched DB server errors at startup because of the write graft:** replace the `makeActionApp` call with a bespoke `makeDBApp` in this same shim file that imports the legacy module's `makeApp`, attaches `build_wiring(server_key)` (require `*ACTION_REQUIRED`), and registers ONLY the sync-graft hooks — no `graft_active_write_path`, no `WsPublishBridge`. Do not build the fallback preemptively (YAGNI).

- [ ] **Step 1: Write the failing test**

Create `helao/hexagon/tests/test_db_shim.py`:

```python
"""P2e DB shim (D2): the launcher-visible hexagon sim_db_server module wraps
the legacy DB makeApp through makeActionApp and registers the sync-graft
startup hook LAST (Starlette preserves registration order, so it runs after
BaseAPI's own startup has bound app.base + the legacy driver). Construction
level only — full lifecycle is the Task 4 launched GM-5 gate."""

from types import SimpleNamespace

import pytest


def _world(tmp_path):
    return {
        "root": str(tmp_path),
        "dummy": True,
        "simulation": True,
        "servers": {
            "DB": {
                "host": "127.0.0.1",
                "port": 8910,
                "group": "action",
                "fast": "sim_db_server",
                "params": {"aws_bucket": "helao-sim", "s3_record": True},
            },
        },
    }


@pytest.fixture()
def installed_config(tmp_path, monkeypatch):
    from helao.helpers import config_loader

    world = _world(tmp_path)
    (tmp_path / "LOGS").mkdir()
    monkeypatch.setattr(config_loader, "CONFIG", world)
    return world


def test_db_shim_wraps_legacy_and_registers_sync_hook_last(installed_config):
    from helao.helpers.server_api import HelaoFastAPI

    from helao.deploy.hexagon.servers.action import sim_db_server as shim

    assert shim.LEGACY_MODULE == "helao.deploy.test.servers.action.sim_db_server"
    app = shim.makeApp("DB")
    assert isinstance(app, HelaoFastAPI)
    assert app.hexagon_wiring is not None
    assert app.hexagon_sync_graft is None  # applied at startup, not build
    routes = {r.path for r in app.routes}
    # real legacy DB surface survived the wrap (sim_db_server.py:99-151)
    for path in ("/finish_yml", "/finish_pending", "/tasks", "/n_queue"):
        assert path in routes, path
    startup_names = [h.__name__ for h in app.router.on_startup]
    shutdown_names = [h.__name__ for h in app.router.on_shutdown]
    assert "_hexagon_active_graft_startup" in startup_names
    assert "_hexagon_sync_graft_startup" in startup_names
    # ours LAST: after BaseAPI's startup_event AND the active-graft hook
    assert startup_names[-1] == "_hexagon_sync_graft_startup"
    assert "_hexagon_sync_graft_shutdown" in shutdown_names


@pytest.mark.asyncio
async def test_db_shim_startup_hook_calls_graft_with_base_params(
    installed_config, monkeypatch
):
    """The hook passes the LIVE app.base + its local server params into
    graft_native_sync and stores the handle (isolated from Task 1's graft
    internals — those have their own tests)."""
    from helao.deploy.hexagon.servers.action import sim_db_server as shim

    calls = {}

    def fake_graft(base, params):
        calls["base"] = base
        calls["params"] = params
        return "HANDLE"

    monkeypatch.setattr(shim, "graft_native_sync", fake_graft)
    app = shim.makeApp("DB")
    app.base = SimpleNamespace(
        server_cfg={"params": {"aws_bucket": "helao-sim", "s3_record": True}}
    )
    hook = [
        h
        for h in app.router.on_startup
        if h.__name__ == "_hexagon_sync_graft_startup"
    ][0]
    await hook()
    assert app.hexagon_sync_graft == "HANDLE"
    assert calls["base"] is app.base
    assert calls["params"] == {"aws_bucket": "helao-sim", "s3_record": True}


@pytest.mark.asyncio
async def test_db_shim_shutdown_hook_closes_graft(installed_config, monkeypatch):
    from helao.deploy.hexagon.servers.action import sim_db_server as shim

    closed = {"n": 0}

    class FakeHandle:
        def close(self):
            closed["n"] += 1

    monkeypatch.setattr(shim, "graft_native_sync", lambda b, p: FakeHandle())
    app = shim.makeApp("DB")
    app.base = SimpleNamespace(server_cfg={"params": {}})
    startup = [
        h
        for h in app.router.on_startup
        if h.__name__ == "_hexagon_sync_graft_startup"
    ][0]
    shutdown = [
        h
        for h in app.router.on_shutdown
        if h.__name__ == "_hexagon_sync_graft_shutdown"
    ][0]
    await startup()
    await shutdown()
    assert closed["n"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_db_shim.py -v`
Expected: 3 FAILED/ERROR with `ImportError: cannot import name 'sim_db_server' from 'helao.deploy.hexagon.servers.action'` (or `ModuleNotFoundError`)

- [ ] **Step 3: Write the implementation**

Create `helao/deploy/hexagon/servers/action/sim_db_server.py`:

```python
"""Hexagon-composed sim DB server (P2e, D2): wraps the test deployment's
real sim_db_server makeApp through the hexagon factory (fail-loud wiring +
co-located RPC via HelaoFastAPI), then registers ONE extra startup hook —
after makeActionApp's own, which is after BaseAPI's — that cuts app.driver
over to the raw P2c NativeSyncer (sync_graft.py). Same basename as the
legacy module so the config flips ONLY the `deployment:` key."""

from helao.hexagon.app.factory import makeActionApp
from helao.hexagon.app.sync_graft import graft_native_sync

__all__ = ["makeApp"]

LEGACY_MODULE = "helao.deploy.test.servers.action.sim_db_server"


def makeApp(server_key):
    app = makeActionApp(server_key, LEGACY_MODULE)
    app.hexagon_sync_graft = None

    # Registered AFTER BaseAPI's startup_event (app.base + the legacy
    # SimHelaoSyncer on app.driver are live) and AFTER the factory's
    # _hexagon_active_graft_startup (Starlette preserves registration
    # order): the graft cancels the legacy syncer loops and rebinds native.
    @app.on_event("startup")
    async def _hexagon_sync_graft_startup():
        app.hexagon_sync_graft = graft_native_sync(
            app.base, app.base.server_cfg.get("params", {})
        )

    @app.on_event("shutdown")
    async def _hexagon_sync_graft_shutdown():
        if app.hexagon_sync_graft is not None:
            app.hexagon_sync_graft.close()

    return app
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_db_shim.py -v`
Expected: `3 passed`

- [ ] **Step 5: Regression-check the touched suites and types**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_sync_graft.py helao/hexagon/tests/test_factory.py helao/hexagon/tests/test_boundaries.py -q`
Expected: all pass, 0 failures

Run: `conda run -n helao pyright helao/deploy/hexagon/servers/action/sim_db_server.py helao/hexagon/tests/test_db_shim.py`
Expected: `0 errors, 0 warnings, 0 informations`

- [ ] **Step 6: Format and commit**

```bash
conda run -n helao black helao/deploy/hexagon/servers/action/sim_db_server.py helao/hexagon/tests/test_db_shim.py
git add helao/deploy/hexagon/servers/action/sim_db_server.py helao/hexagon/tests/test_db_shim.py
git commit -m "feat(hexagon): P2e DB shim — deployment:hexagon sim_db_server wraps legacy + sync graft

makeActionApp wrap (same seam as ws_simulator shim) + one extra startup
hook that runs after BaseAPI's, cutting app.driver over to NativeSyncer. D2."
```

---

### Task 3: Config cut-over (goldenhex family) + retire ws_demo.yml + gate-config test

**Files:**
- Modify: `helao/deploy/test/configs/goldenhex.yml` (DB block, line 44 area + header comment line 1)
- Modify: `helao/deploy/test/configs/goldenhexid.yml` (DB block, lines 35-42)
- Modify: `helao/deploy/test/configs/goldenhexconc.yml` (DB block, lines 38-45)
- Modify: `helao/deploy/test/configs/goldenhexvis.yml` (DB block, lines 65-72)
- Delete: `helao/deploy/test/configs/ws_demo.yml` (`git rm`)
- Test: `helao/hexagon/tests/test_db_gate_config.py`

**Interfaces:**
- Consumes: Task 2's shim (`helao.deploy.hexagon.servers.action.sim_db_server.makeApp`, `LEGACY_MODULE`) — the flip is a `ModuleNotFoundError` at launch without it, so Task 2 MUST be committed first (D3). `read_config` from `helao.helpers.config_loader`; `validateConfig` from `launch` (mirroring `test_vis_gate_config.py`).
- Produces: `goldenhex.yml` with a hexagon-routed DB (the GM-5 gate config, D3 minimum) plus the full-family cut-over (goldenhexid/goldenhexconc/goldenhexvis — recommended breadth per D3: GM-5 gates on goldenhex; the other three flip as the final cut-over in the same task).

- [ ] **Step 1: Write the failing gate-config test**

Create `helao/hexagon/tests/test_db_gate_config.py`:

```python
"""P2e gate-config checks (D3): every goldenhex-family config routes DB
through `deployment: hexagon`, the dotted path import-resolves to the P2e
shim (same shape fast_launcher builds), and the config still validates.
Mirrors test_vis_gate_config.py."""

import os
import types
from importlib import import_module

import pytest

_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
_CFG_DIR = os.path.join(_REPO_ROOT, "helao", "deploy", "test", "configs")
_FAMILY = ["goldenhex", "goldenhexid", "goldenhexconc", "goldenhexvis"]


def _load(prefix):
    from helao.helpers.config_loader import read_config

    return read_config(os.path.join(_CFG_DIR, f"{prefix}.yml"))


@pytest.mark.parametrize("prefix", _FAMILY)
def test_config_validates(prefix):
    from launch import validateConfig

    conf = _load(prefix)
    pidd = types.SimpleNamespace(
        reqKeys=("host", "port", "group"), codeKeys=("fast", "bokeh")
    )
    assert validateConfig(pidd, conf, _REPO_ROOT) is True


@pytest.mark.parametrize("prefix", _FAMILY)
def test_db_routes_through_hexagon_shim(prefix):
    conf = _load(prefix)
    db = conf["servers"]["DB"]
    assert db["deployment"] == "hexagon"
    assert db["fast"] == "sim_db_server"
    assert db["group"] == "action"
    # the GM-5 S3 leg records via the injected RecordingS3Client
    assert db["params"]["s3_record"] is True
    assert db["params"]["aws_bucket"] == "helao-sim"
    modpath = (
        f"helao.deploy.{db['deployment']}.servers.{db['group']}.{db['fast']}"
    )  # fast_launcher module-path shape
    mod = import_module(modpath)
    assert callable(mod.makeApp)
    assert mod.LEGACY_MODULE == "helao.deploy.test.servers.action.sim_db_server"


def test_ws_demo_retired():
    """D5: ws_demo.yml referenced a nonexistent `bokeh: sim_visualizer`
    module (only self-reference in the repo) — it must stay deleted."""
    assert not os.path.exists(os.path.join(_CFG_DIR, "ws_demo.yml"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_db_gate_config.py -v`
Expected: `test_db_routes_through_hexagon_shim` FAILS for all 4 prefixes with `KeyError: 'deployment'`; `test_ws_demo_retired` FAILS with `AssertionError`; the 4 `test_config_validates` cases PASS (configs are valid pre-flip).

- [ ] **Step 3: Flip the four DB blocks and update the goldenhex header comment**

In `helao/deploy/test/configs/goldenhex.yml`, change the header line:

```yaml
# P1b1 SMOKE config (hexagon-composed ORCH + SIM; legacy sim DB).
```

to:

```yaml
# SMOKE config (hexagon-composed ORCH + SIM + DB; P2e sync cut-over).
```

In ALL FOUR files (`goldenhex.yml`, `goldenhexid.yml`, `goldenhexconc.yml`, `goldenhexvis.yml`), the DB block is byte-identical in shape; insert `deployment: hexagon` after the `fast:` line. Exact edit (old → new):

```yaml
  DB:
    host: 127.0.0.1
    port: 8010
    group: action
    fast: sim_db_server
    params:
      aws_bucket: helao-sim
      s3_record: true
```

becomes:

```yaml
  DB:
    host: 127.0.0.1
    port: 8010
    group: action
    fast: sim_db_server
    deployment: hexagon
    params:
      aws_bucket: helao-sim
      s3_record: true
```

- [ ] **Step 4: Retire ws_demo.yml**

Run: `git rm helao/deploy/test/configs/ws_demo.yml`
Expected: `rm 'helao/deploy/test/configs/ws_demo.yml'`

- [ ] **Step 5: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/hexagon/tests/test_db_gate_config.py -v`
Expected: `9 passed`

- [ ] **Step 6: Commit (two commits — GM-5 gate flip, then family cut-over + retirement)**

```bash
conda run -n helao black helao/hexagon/tests/test_db_gate_config.py
git add helao/deploy/test/configs/goldenhex.yml helao/hexagon/tests/test_db_gate_config.py
git commit -m "feat(hexagon): P2e cut-over — goldenhex.yml DB deployment:hexagon (GM-5 gate config)"
git add helao/deploy/test/configs/goldenhexid.yml helao/deploy/test/configs/goldenhexconc.yml helao/deploy/test/configs/goldenhexvis.yml
git commit -m "feat(hexagon): P2e cut-over — flip goldenhexid/conc/vis DB to deployment:hexagon + retire ws_demo (D3/D5)" -- helao/deploy/test/configs
```

Note: the second commit already includes the staged `git rm` of ws_demo.yml. If `git commit -- <path>` scoping proves awkward, simply stage everything remaining and use one commit message; the invariant is that the goldenhex.yml flip and the gate test land no later than the family flip.

---

### Task 4: Verification sweep + LAUNCHED GM-5 gate (MAIN-SESSION, controller-run)

**This task is executed by the controller in the main session, NOT delegated to a headless subagent** — `parity_run.sh` launches a full server group (ports 8001/8002/8010), and the DB server now runs the native syncer live.

**Files:**
- No new files. Read-only verification + launched smoke.

**Interfaces:**
- Consumes: everything from Tasks 1-3 (committed); `helao/hexagon/tests/smoke/parity_run.sh <scenario> <config_prefix> <root> <golden> <candidate>` (waits on ports 8001/8002/8010, captures via `harness.capture`, diffs via `harness.parity`; exit 0 = PASS, 1 = diffs, 2 = harness error); goldens at `/home/dan/helao_goldens/GM-{1..5}/run1`; goldenhex root `/home/dan/INST_hlo_hexsmoke` (from the config's `root:` key).
- Produces: the P2 completion evidence (D4): launched GM-5 = 0 diffs through the NATIVE syncer, GM-1 = 0 diffs, GM-2..4 unchanged, honesty log-grep proving the graft ran.

- [ ] **Step 1: Full hexagon suite**

Run: `conda run -n helao python -m pytest helao/hexagon/tests -q`
Expected: all pass, 0 failures (exit code 0); the boundary test (`test_boundaries.py`) is part of the suite and must pass.

- [ ] **Step 2: pyright over all new files**

Run: `conda run -n helao pyright helao/hexagon/app/sync_graft.py helao/deploy/hexagon/servers/action/sim_db_server.py helao/hexagon/tests/test_sync_graft.py helao/hexagon/tests/test_db_shim.py helao/hexagon/tests/test_db_gate_config.py`
Expected: `0 errors, 0 warnings, 0 informations`

- [ ] **Step 3: Zero-legacy proof (D5/D6)**

Run: `git diff unstable --stat -- helao/core helao/helpers helao/deploy/test/servers helao/deploy/test/experiments helao/deploy/test/sequences harness launch.py bokeh_launcher.py fast_launcher.py`
Expected: EMPTY output (no legacy file touched; the only `helao/deploy/test/` changes are under `configs/`).

Run: `git diff unstable --stat`
Expected: ONLY these paths: `docs/superpowers/plans/2026-07-18-P2e-assembly.md`, `helao/hexagon/app/sync_graft.py`, `helao/deploy/hexagon/servers/action/sim_db_server.py`, `helao/hexagon/tests/test_sync_graft.py`, `helao/hexagon/tests/test_db_shim.py`, `helao/hexagon/tests/test_db_gate_config.py`, the four `helao/deploy/test/configs/goldenhex*.yml`, and the `helao/deploy/test/configs/ws_demo.yml` deletion.

- [ ] **Step 4: Launched GM-5 — THE HEADLINE GATE (D4)**

Run:
```bash
bash helao/hexagon/tests/smoke/parity_run.sh GM-5 goldenhex /home/dan/INST_hlo_hexsmoke /home/dan/helao_goldens/GM-5/run1 /tmp/p2e_gm5_candidate
echo "GM-5 exit: $?"
```
Expected: `[parity_run]` progress lines, then `harness.parity` reports zero diffs and `GM-5 exit: 0`. The parity report is at `/tmp/p2e_gm5_candidate/parity-report.json`. This proves the NATIVE syncer, live in the launched DB server, produces byte-identical sync output: RUNS_SYNCED zip + PROCESSES `-prc.yml` + S3_SIM manifest/payloads (via the injected RecordingS3Client) + the `reset_sync`/`finish_pending(actions_first=True)` round-trip the harness posts to DB:8010.

If exit code is 2 with a DB-server startup error in `/tmp/p1b2a_goldenhex_GM-5.launch.log`: this is reviewer point 2 (makeActionApp's write graft on the DB server) — apply the documented Task 2 fallback (bespoke `makeDBApp` = legacy makeApp + `build_wiring` + sync-graft hooks only, no active graft / WS bridge), re-run Task 2 tests (drop the `_hexagon_active_graft_startup` assertion), commit the fallback, and re-run this step.

- [ ] **Step 5: Honesty grep — the graft actually ran (do this BEFORE the next parity run wipes the root)**

Run: `grep -r "hexagon native sync grafted" /home/dan/INST_hlo_hexsmoke/LOGS/ /tmp/p1b2a_goldenhex_GM-5.launch.log`
Expected: at least one hit of `hexagon native sync grafted (app.driver -> NativeSyncer; legacy SimHelaoSyncer syncer_loops cancelled)` from the DB server's log. A GM-5 PASS WITHOUT this line means the flip silently ran legacy — treat as FAILURE and debug the config/launcher routing.

- [ ] **Step 6: Launched GM-1 (baseline sync leg through the native syncer)**

Run:
```bash
bash helao/hexagon/tests/smoke/parity_run.sh GM-1 goldenhex /home/dan/INST_hlo_hexsmoke /home/dan/helao_goldens/GM-1/run1 /tmp/p2e_gm1_candidate
echo "GM-1 exit: $?"
```
Expected: `GM-1 exit: 0` (0 diffs).

- [ ] **Step 7: GM-2..GM-4 regression sweep (action/orch path — should be unchanged; DB-only change)**

Run (sequentially — one scenario per launch):
```bash
for gm in GM-2 GM-3 GM-4; do
  bash helao/hexagon/tests/smoke/parity_run.sh "$gm" goldenhex /home/dan/INST_hlo_hexsmoke "/home/dan/helao_goldens/$gm/run1" "/tmp/p2e_${gm}_candidate"
  echo "$gm exit: $?"
done
```
Expected: `GM-2 exit: 0`, `GM-3 exit: 0`, `GM-4 exit: 0`.

- [ ] **Step 8: Record the outcome**

No code commit unless Steps 4-7 forced a fix (any fix goes through its owning task's test cycle + black + commit). Report to the controller: suite count, pyright result, zero-legacy diff proof, GM-1..GM-5 exit codes, and the honesty-grep line. On all-green: **P2e done → after merge to unstable, P2 is COMPLETE** (D7; GM-7/P2f stays deferred; the orch-owned early-`to_s3` path stays legacy by design; `/current_progress` AttributeError stays pre-existing on both stacks).

---

## Self-Review (performed while writing)

- **Spec coverage vs p2e-decisions.md:** D1 → Task 1 (raw NativeSyncer, orphan-loop cancel, RecordingS3Client replication, app.driver rebind, handle with originals + symmetric close). D2 → Task 2 (makeActionApp wrap, hook-after-BaseAPI ordering, makeDBApp fallback documented but not built). D3 → Task 3 (goldenhex flip gates GM-5; full-family flip in the same task, second commit; shim committed before any flip). D4 → Task 4 Steps 4-7 (launched GM-5 + GM-1 + GM-2..4 + honesty grep). D5 → Task 3 Step 4 + Task 4 Steps 1-3 (ws_demo git rm, suite, pyright, boundary, zero-legacy diff). D6 → Global Constraints + Task 4 Step 3. D7 → Global Constraints (`/current_progress` untouched) + Task 4 Step 8 (orch to_s3 stays legacy; GM-7 deferred).
- **Placeholder scan:** no TBD/TODO; every code step shows complete code; every command has expected output.
- **Type/name consistency:** `graft_native_sync(base, params) -> NativeSyncGraft` and `NativeSyncGraft(app, native, originals)` are identical in Task 1 (definition), Task 2 (shim call + monkeypatch), and Task 4 (log banner). Hook names `_hexagon_sync_graft_startup`/`_hexagon_sync_graft_shutdown` match between shim and tests. `LEGACY_MODULE` string matches between shim, shim test, and gate-config test.
