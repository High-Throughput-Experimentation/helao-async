# Framework SP-DEPLOY-2 Test Repoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repoint the `test` deployment onto the framework: a launcher `deployment: framework` resolution path + a framework config-global bridge, framework orchestrator + data_browser entry points, repointed test configs and `*_vis.py`, and a live bring-up smoke. `hte`/`helao/core` untouched.

**Architecture:** Both launchers gain a small additive branch — when a server sets `deployment: framework`, the app module resolves from `helao.framework.app.servers.<module>` instead of `helao.deploy.<deployment>...`; default resolution is unchanged. The launcher also bridges the framework config global to the loaded config so framework apps (HelaoVis, orchestrator entry, operator backend autoload) see it. New framework entries wire libs/action_servers (orchestrator) and `build_document` (data_browser). Test configs add `deployment: framework`; test `*_vis.py` repoint their base-class imports to the framework.

**Tech Stack:** Python 3.12 (conda env `helao`), FastAPI/Bokeh launchers, `pytest`.

## Global Constraints

- Run pytest via the `helao` conda env: `conda run -n helao python -m pytest <path> -v`.
- The launcher change MUST be additive: any config WITHOUT `deployment: framework` resolves exactly as before (the resolver unit test asserts this). Do NOT change the default deploy-path or the auto-detect glob.
- `helao/deploy/hte/**` and `helao/core/**` MUST NOT be modified (gated). Only `helao/deploy/test/**`, the two launchers, and `helao/framework/**` change.
- After repoint, NO `helao.core.servers` import may remain in `helao/deploy/test/**`.
- For framework Bokeh visualizer hosts, `CONFIG["deployment"]` must stay the *real* deployment (`test`) so `mount_visualizers` resolves per-instrument `*_vis.py` from the test deploy — only the host-app *import path* comes from the framework.

---

### Task 1: launcher framework-path resolution + config bridge

**Files:**
- Modify: `fast_launcher.py`, `bokeh_launcher.py`
- Test: `helao/framework/tests/test_launcher_framework_resolution.py`

**Interfaces:**
- Produces (in each launcher, a small pure helper for testability): `resolve_app_module_path(deployment: str, group: str, name: str) -> str` returning `"helao.framework.app.servers.<name>"` when `deployment == "framework"` else `"helao.deploy.<deployment>.servers.<group>.<name>"`.

- [ ] **Step 1: Write the failing test**

```python
# helao/framework/tests/test_launcher_framework_resolution.py
"""Launcher framework-path resolution + config-global bridge."""
import importlib


def test_fast_resolver_framework_vs_deploy():
    fl = importlib.import_module("fast_launcher")
    assert fl.resolve_app_module_path("framework", "orchestrator", "orchestrator") == \
        "helao.framework.app.servers.orchestrator"
    assert fl.resolve_app_module_path("hte", "orchestrator", "async_orch2") == \
        "helao.deploy.hte.servers.orchestrator.async_orch2"


def test_bokeh_resolver_framework_vs_deploy():
    bl = importlib.import_module("bokeh_launcher")
    assert bl.resolve_app_module_path("framework", "operator", "standalone_operator") == \
        "helao.framework.app.servers.standalone_operator"
    assert bl.resolve_app_module_path("test", "visualizer", "oersim_vis") == \
        "helao.deploy.test.servers.visualizer.oersim_vis"


def test_config_bridge_helper():
    """bridge_framework_config points the framework global at the legacy CONFIG object."""
    fl = importlib.import_module("fast_launcher")
    from helao.helpers import config_loader as legacy
    from helao.framework.support import config_loader as fw
    prev_legacy, prev_fw = legacy.CONFIG, fw.CONFIG
    try:
        legacy.CONFIG = {"sentinel": 1}
        fl.bridge_framework_config()
        assert fw.CONFIG is legacy.CONFIG
    finally:
        legacy.CONFIG, fw.CONFIG = prev_legacy, prev_fw
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_launcher_framework_resolution.py -v`
Expected: FAIL — `AttributeError: module 'fast_launcher' has no attribute 'resolve_app_module_path'`.

> If importing `fast_launcher`/`bokeh_launcher` at module scope triggers heavy side effects (they are scripts), check their top level — they define functions and only run under `if __name__ == "__main__"`. If a bare import errors, the test should import via `importlib` after ensuring the repo root is on `sys.path` (it is, per PYTHONPATH). If they execute work on import, extract the helpers into an importable form (do NOT run the launch body on import).

- [ ] **Step 3: Write minimal implementation**

In **both** `fast_launcher.py` and `bokeh_launcher.py`, add two module-level helpers near the top (after imports):

```python
def resolve_app_module_path(deployment: str, group: str, name: str) -> str:
    """Resolve the app module import path. ``deployment == "framework"`` selects the
    deployment-agnostic framework app under ``helao.framework.app.servers``; any
    other value uses the per-deployment path (unchanged default)."""
    if deployment == "framework":
        return f"helao.framework.app.servers.{name}"
    return f"helao.deploy.{deployment}.servers.{group}.{name}"


def bridge_framework_config() -> None:
    """Point the framework config global at the launcher-loaded legacy CONFIG so
    framework apps (HelaoVis, orchestrator entry, operator backend autoload) see it."""
    from helao.helpers import config_loader as _legacy
    from helao.framework.support import config_loader as _fw
    _fw.CONFIG = _legacy.CONFIG
```

In **`fast_launcher.py`**, replace the `makeApp = import_module(f"helao.deploy...").makeApp` block with:

```python
    CONFIG["deployment"] = deployment
    bridge_framework_config()
    makeApp = import_module(
        resolve_app_module_path(deployment, server_config["group"], server_config["fast"])
    ).makeApp
    app = makeApp(server_key)
```

In **`bokeh_launcher.py`**, replace the resolution + `CONFIG["deployment"]` block with (note: for framework apps, `CONFIG["deployment"]` stays the *detected* deployment so per-instrument vis modules resolve from the real deployment):

```python
    if app_deployment == "framework":
        CONFIG["deployment"] = detected_deployment
    else:
        CONFIG["deployment"] = server_config.get("deployment", detected_deployment)
    bridge_framework_config()
    makeApp = import_module(
        resolve_app_module_path(app_deployment, server_config["group"], server_config["bokeh"])
    ).makeBokehApp
```

(Leave the `deployment`/`app_deployment` computation and auto-detect glob above exactly as-is.)

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_launcher_framework_resolution.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add fast_launcher.py bokeh_launcher.py helao/framework/tests/test_launcher_framework_resolution.py
git commit -m "feat(framework): SP-DEPLOY-2 — launcher framework-path resolution + config bridge"
```

---

### Task 2: framework orchestrator + data_browser entries

**Files:**
- Create: `helao/framework/app/servers/orchestrator.py`
- Create: `helao/framework/app/servers/data_browser.py`
- Test: `helao/framework/tests/test_app_servers_orchestrator_databrowser.py`

**Interfaces:**
- Consumes: `helao.framework.app.factory.makeApp` (orchestrator branch: `makeApp(server_key, group="orchestrator", sequence_lib=, experiment_lib=, action_servers=)`); `helao.helpers.import_autolibs.import_autolibs` (legacy seam — returns `(lib, codehash_lib, codepath_lib)`); `helao.framework.support.config_loader.CONFIG`; `helao.framework.app.vis.HelaoVis`; `helao.framework.app.data_browser.build_document`.
- Produces: `orchestrator.makeApp(server_key) -> FastAPI`; `data_browser.makeBokehApp(doc, confPrefix, server_key, helao_repo_root) -> doc`.

- [ ] **Step 1: Write the failing test**

```python
# helao/framework/tests/test_app_servers_orchestrator_databrowser.py
"""Framework orchestrator + data_browser generic entries."""
import pytest

from helao.framework.support import config_loader


class FakeDoc:
    def __init__(self):
        self.title = None
        self.roots = []

    def add_root(self, root):
        self.roots.append(root)

    def add_next_tick_callback(self, cb):
        pass

    def on_session_destroyed(self, cb):
        pass


@pytest.fixture
def cfg(tmp_path):
    prev = config_loader.CONFIG
    from helao.framework.support import helao_logging
    prev_log = helao_logging.LOGGER
    config_loader.CONFIG = {
        "root": str(tmp_path / "INST"),
        "loaded_config_path": "/configs/demo.yml",
        "servers": {
            "ORCH": {"group": "orchestrator", "host": "127.0.0.1", "port": 8001},
            "MOTOR": {"group": "action", "host": "127.0.0.1", "port": 8002},
            "VIS": {"group": "visualizer", "host": "127.0.0.1", "port": 5003, "params": {}},
        },
    }
    yield config_loader.CONFIG
    config_loader.CONFIG = prev
    helao_logging.LOGGER = prev_log


def test_orchestrator_entry_builds_app(cfg):
    from helao.framework.app.servers.orchestrator import makeApp
    app = makeApp("ORCH")
    assert app is not None
    assert hasattr(app.state, "driver")
    # action_servers derived from CONFIG (pingable action servers present)
    assert "MOTOR" in app.state.driver.action_servers


def test_data_browser_entry_builds_doc(cfg):
    from helao.framework.app.servers.data_browser import makeBokehApp
    doc = FakeDoc()
    out = makeBokehApp(doc, "demo", "VIS", "/repo")
    assert out is doc
    assert len(doc.roots) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_servers_orchestrator_databrowser.py -v`
Expected: FAIL — `ModuleNotFoundError: ...app.servers.orchestrator`.

- [ ] **Step 3: Write minimal implementation**

First READ `helao/helpers/import_autolibs.py` for the exact `import_autolibs(...)` signature (how it selects `experiment_libraries` vs `sequence_libraries`, and its return tuple). Then create `helao/framework/app/servers/orchestrator.py`:

```python
# helao/framework/app/servers/orchestrator.py
"""Deployment-agnostic framework orchestrator entry point.

Builds the framework orchestrator FastAPI app from the loaded CONFIG: loads the
experiment/sequence libraries and derives the action-server list for the
SP-ORCH-4 status heartbeat.
"""
__all__ = ["makeApp"]

from helao.framework.support import config_loader
from helao.framework.support import helao_logging as logging
from helao.framework.app.factory import makeApp as _make_framework_app

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def makeApp(server_key):
    """Construct the framework orchestrator app for ``server_key`` from CONFIG."""
    cfg = config_loader.CONFIG
    sequence_lib = {}
    experiment_lib = {}
    try:
        from helao.helpers.import_autolibs import import_autolibs
        # NOTE: match the real import_autolibs signature discovered in Step 3.
        # It returns (lib, codehash_lib, codepath_lib); call once per library type.
        experiment_lib, _, _ = import_autolibs(cfg, "experiment")
        sequence_lib, _, _ = import_autolibs(cfg, "sequence")
    except Exception as exc:  # config without libs / loader unavailable -> empty maps
        LOGGER.warning(f"orchestrator lib autoload skipped/failed: {exc!r}")
    action_servers = {
        k: v for k, v in (cfg.get("servers") or {}).items()
        if isinstance(v, dict) and v.get("group") == "action"
    }
    return _make_framework_app(
        server_key,
        group="orchestrator",
        sequence_lib=sequence_lib,
        experiment_lib=experiment_lib,
        action_servers=action_servers,
    )
```

> The exact `import_autolibs` call (positional/keyword arg selecting experiment vs
> sequence, and whether it takes the whole `world_cfg`) MUST match the real
> signature from Step 3's read. If `import_autolibs` reads the *legacy*
> `helao.helpers.config_loader.CONFIG` internally (it does — module-level `CONFIG`),
> that is fine at launch because Task 1's `bridge_framework_config` keeps both
> globals pointing at the same object; in this unit test, the framework CONFIG is
> set but legacy is not, so the `try/except` yields empty libs — assert only on
> `action_servers` (as the test does), not on the lib maps.

Create `helao/framework/app/servers/data_browser.py`:

```python
# helao/framework/app/servers/data_browser.py
"""Deployment-agnostic framework data-browser entry point."""
__all__ = ["makeBokehApp"]

from helao.framework.app.vis import HelaoVis
from helao.framework.app.data_browser import build_document
from helao.framework.support import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def makeBokehApp(doc, confPrefix, server_key, helao_repo_root):
    """Build the data-browser Bokeh document on framework modules."""
    app = HelaoVis(server_key=server_key, doc=doc)
    build_document(app.vis)
    return doc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_servers_orchestrator_databrowser.py -v`
Expected: PASS (2 passed). If `factory.makeApp` does not accept `action_servers`, confirm SP-ORCH-4 added it (it did) and that the orchestrator branch forwards it; if a kwarg name differs, match the real `factory.makeApp` signature.

- [ ] **Step 5: Commit**

```bash
git add helao/framework/app/servers/orchestrator.py helao/framework/app/servers/data_browser.py helao/framework/tests/test_app_servers_orchestrator_databrowser.py
git commit -m "feat(framework): SP-DEPLOY-2 — framework orchestrator + data_browser entry points"
```

---

### Task 3: repoint test configs + `*_vis.py` + data_browser shim

**Files:**
- Modify: `helao/deploy/test/configs/{test,demo0,demo1,ws_demo}.yml`
- Modify: `helao/deploy/test/servers/visualizer/{gpsim_live_vis,oersim_vis,wssim_live_vis,data_browser}.py`
- Test: `helao/framework/tests/test_test_deploy_no_legacy_core.py`

**Interfaces:**
- Consumes: the framework entries (Tasks 1-2) + the framework vis base classes (`helao.framework.app.vis.Vis`, `helao.framework.adapters.vis_subscriber.{LiveVisualizer,ActionVisualizer}`).

- [ ] **Step 1: Write the failing test**

```python
# helao/framework/tests/test_test_deploy_no_legacy_core.py
"""Guard: the test deployment no longer imports legacy helao.core.servers."""
import os
import glob


def test_no_legacy_core_servers_import_in_test_deploy():
    root = os.path.join(os.path.dirname(__file__), "..", "..", "deploy", "test")
    root = os.path.abspath(root)
    offenders = []
    for path in glob.glob(os.path.join(root, "**", "*.py"), recursive=True):
        if "__pycache__" in path or os.sep + "tests" + os.sep in path:
            continue
        with open(path) as f:
            text = f.read()
        if "helao.core.servers" in text:
            offenders.append(os.path.relpath(path, root))
    assert offenders == [], f"test deploy still imports legacy core servers: {offenders}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_test_deploy_no_legacy_core.py -v`
Expected: FAIL — lists `servers/visualizer/{gpsim_live_vis,oersim_vis,wssim_live_vis,data_browser}.py`.

- [ ] **Step 3: Write minimal implementation**

(a) **Configs** — in each of `test.yml`, `demo0.yml`, `demo1.yml`, `ws_demo.yml`, for every server entry whose `fast`/`bokeh` names a generic shared app, add `deployment: framework` and set the module name to the framework module:
- orchestrator: `fast: async_orch2` → `fast: orchestrator` + `deployment: framework`.
- operator: `bokeh: standalone_operator` → keep name, add `deployment: framework`.
- generic visualizer hosts: `bokeh: live_visualizer` / `bokeh: action_visualizer` → keep name, add `deployment: framework`.
- data browser: `bokeh: data_browser` → keep name, add `deployment: framework`.
- `bokeh: sim_visualizer` (ws_demo) if present: only repoint if it is a generic shared app from hte; if it is a test-local module, leave it (and repoint its imports in 3(b) instead). Inspect before changing.
Leave action servers (`fast: ws_simulator` etc.) and the per-server `action_vis`/`live_vis` keys unchanged.

(b) **`*_vis.py` + data_browser shim** — repoint imports (only the import lines; class bodies unchanged):
- `gpsim_live_vis.py`, `wssim_live_vis.py`: `from helao.core.servers.vis import Vis` → `from helao.framework.app.vis import Vis`; `from helao.core.servers.vis_subscriber import LiveVisualizer` → `from helao.framework.adapters.vis_subscriber import LiveVisualizer`.
- `oersim_vis.py`: same with `ActionVisualizer`; also `from helao.core.models.hlostatus import HloStatus` → `from helao.framework.models.hlostatus import HloStatus`.
- Any other `helao.core.models.*` import in these files → `helao.framework.models.*`.
- `data_browser.py` (test shim): `from helao.core.servers.vis import HelaoVis` → `from helao.framework.app.vis import HelaoVis`; `from helao.core.servers.data_browser import build_document` → `from helao.framework.app.data_browser import build_document`. (Or delete this shim and rely on the §3.4 `deployment: framework` data_browser entry — but keeping the per-instrument repoint is simplest and the no-legacy-import guard then passes.)

Grep each edited file afterward: `grep -n "helao.core" <file>` — only `helao.framework` (and any allowed non-server `helao.core.models`→ now framework) should remain; zero `helao.core.servers`.

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_test_deploy_no_legacy_core.py -v`
Expected: PASS. Also import-smoke each repointed module:
`conda run -n helao python -c "import importlib; [importlib.import_module(m) for m in ['helao.deploy.test.servers.visualizer.oersim_vis','helao.deploy.test.servers.visualizer.gpsim_live_vis','helao.deploy.test.servers.visualizer.wssim_live_vis','helao.deploy.test.servers.visualizer.data_browser']]; print('imports OK')"`
Expected: `imports OK`.

- [ ] **Step 5: Commit**

```bash
git add helao/deploy/test/configs/ helao/deploy/test/servers/visualizer/ helao/framework/tests/test_test_deploy_no_legacy_core.py
git commit -m "feat(test-deploy): SP-DEPLOY-2 — repoint test deployment onto the framework"
```

---

### Task 4: live bring-up smoke + verification

**Files:** none (verification); may add `helao/framework/tests/` smoke artifacts only if useful.

- [ ] **Step 1: Full framework suite + boundary**

Run: `conda run -n helao python -m pytest helao/framework/tests/ -p no:cacheprovider -q 2>&1 | tail -1` → all pass.
Run: `conda run -n helao python -m pytest helao/framework/tests/test_boundaries.py -q 2>&1 | tail -1` → PASS.

- [ ] **Step 2: Confirm hte/core untouched**

Run: `git diff --name-only feat/framework-scaffold...HEAD | grep -E "helao/(core|deploy/hte)/" || echo "NONE (clean)"`
Expected: `NONE (clean)` — only `helao/deploy/test/**`, the two launchers, `helao/framework/**`, docs.

- [ ] **Step 3: Per-server construction smoke (deterministic, no ports)**

This proves the repoint wires without a full multi-process launch. With a Linux-safe root, load a test config and construct each server's app:

```bash
conda run -n helao python - <<'PY'
import tempfile, os
from helao.helpers import config_loader as legacy
from helao.framework.support import config_loader as fw
cfg = legacy.load_global_config("test", True)
cfg["root"] = tempfile.mkdtemp(prefix="helao_smoke_")   # Linux-safe root
cfg["deployment"] = "test"
fw.CONFIG = legacy.CONFIG = cfg
# orchestrator entry
from helao.framework.app.servers.orchestrator import makeApp as orch
app = orch("ORCH"); assert hasattr(app.state, "driver")
# bokeh entries against a fake doc
class D:
    def __init__(self): self.roots=[]; self.title=None
    def add_root(s,r): s.roots.append(r)
    def add_next_tick_callback(s,c): pass
    def on_session_destroyed(s,c): pass
    operator=None
from helao.framework.app.servers.standalone_operator import makeBokehApp as op
from helao.framework.app.servers.live_visualizer import makeBokehApp as live
from helao.framework.app.servers.data_browser import makeBokehApp as db
# operator subscribe needs a loop; run under asyncio
import asyncio
async def _run():
    op(D(), "test", "OPERATOR", ".")
    live(D(), "test", "LIVE", ".")
    db(D(), "test", "DATABROWSE", ".")
asyncio.run(_run())
print("CONSTRUCTION SMOKE OK")
PY
```
Expected: `CONSTRUCTION SMOKE OK`. If the operator construction needs a running loop for `RemoteBackend.subscribe`, the `asyncio.run` wrapper provides it; if a real ws connect blocks, wrap the subscribe in a short timeout or assert `doc.operator` is built before subscribe completes.

- [ ] **Step 4: Live group launch (best-effort)**

Attempt the real multi-process launch on a Linux-safe config (copy `test.yml` to a temp prefix with a Linux `root`, or export the root). Run in the background, give it time, probe readiness, capture the log, then terminate:

```bash
# pick/clone a sims config with a Linux root, then:
conda run -n helao python launch.py test    # or the Linux-rooted prefix
```
- Confirm each FastAPI server answers (e.g. `curl -s http://127.0.0.1:8001/openapi.json | head -c 50`, port 8002 for SIM).
- Confirm each Bokeh app process started without a traceback in its log under `<root>/LOGS/`.
- Terminate the group (the launch.py hotkey `CTRL-x`, or kill the spawned PIDs from `STATES/pids_*.pck`).
- Capture the launch log tail in the task report.

> If the sandbox cannot sustain the multi-process launch (port binding, background process limits, Windows-only sim deps), record exactly what failed, rely on Step 3's construction smoke as the deterministic proof, and note that the human runs the full `launch.py` + browser check. Do NOT mark the task failed solely because the sandbox can't host a long-running multi-process group — Step 3 is the gating proof; Step 4 is best-effort.

- [ ] **Step 5: Commit (if any smoke fixups were needed)**

```bash
git add -A
git commit -m "test(framework): SP-DEPLOY-2 — bring-up smoke + verification"
```

---

## Self-Review

**Spec coverage:**
- §3.1 launcher framework-path resolution (both launchers) → Task 1. ✓
- §3.2 config-global bridge → Task 1 (`bridge_framework_config`). ✓
- §3.3 framework orchestrator entry → Task 2. ✓
- §3.4 framework data_browser entry → Task 2. ✓
- §3.5 repoint test configs → Task 3(a). ✓
- §3.6 repoint test `*_vis.py` + data_browser shim → Task 3(b). ✓
- §3.7 carry-forward resolution (config global via bridge; subscribe loop via live/asyncio) → Task 1 bridge + Task 4 smoke. ✓
- §4 smoke strategy (resolver unit test, bridge test, entry tests, no-legacy guard, construction smoke, live launch best-effort) → Tasks 1-4. ✓
- §6 risks (additive launcher branch + resolver test; CONFIG["deployment"]=detected for framework bokeh) → Task 1. ✓

**Placeholder scan:** No TBD/TODO. Exact launcher edits + entry code + repoint rules given. Two guarded notes (`import_autolibs` real signature, `factory.makeApp` kwarg) are concrete "match the real API" instructions, not placeholders.

**Type consistency:** `resolve_app_module_path(deployment, group, name)` + `bridge_framework_config()` defined + tested Task 1, used in both launchers. Orchestrator entry `makeApp(server_key)` and data_browser `makeBokehApp(doc, confPrefix, server_key, helao_repo_root)` match the launcher contracts (Task 1 resolves them). `action_servers` kwarg matches `factory.makeApp` (SP-ORCH-4). The no-legacy guard (Task 3) enforces §3.6.
