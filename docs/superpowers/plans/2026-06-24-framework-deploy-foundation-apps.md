# Framework SP-DEPLOY-1 Generic Server Apps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deployment-agnostic generic Bokeh server entry points to the framework — `makeBokehApp` for the operator and the live/action visualizer hosts — under `helao/framework/app/servers/`, built on the SP-VIS/SP-ORCH framework modules. Pure addition; no deploy edits.

**Architecture:** Three thin `makeBokehApp(doc, confPrefix, server_key, helao_repo_root)` factories ported from the hte originals with framework imports: visualizer hosts wire `app/vis.HelaoVis` + `adapters/vis_subscriber.mount_visualizers`; the operator wires `app/vis.HelaoVis` + `adapters/operator_backend.RemoteBackend` + `app/operator/bokeh_operator.BokehOperator`. Each module exposes `makeBokehApp` (the launcher contract).

**Tech Stack:** Python 3.12 (conda env `helao`), Bokeh, `pytest`.

## Global Constraints

- Run pytest via the `helao` conda env: `conda run -n helao python -m pytest <path> -v`.
- Pure addition: do NOT modify any `helao/deploy/**` or `helao/core/**` file. SP-DEPLOY-1 adds only `helao/framework/**`.
- Each new module exposes `makeBokehApp(doc, confPrefix, server_key, helao_repo_root)` (exact launcher signature).
- Read config LIVE via `helao.framework.support.config_loader.CONFIG` (the framework `HelaoVis` already does this) — tests set `config_loader.CONFIG`.
- `app/servers/` is the app layer; importing `adapters/` is allowed (operator injects the concrete backend). AST boundary check must stay green.
- Tests set/restore `config_loader.CONFIG` AND `helao_logging.LOGGER` (the SP-VIS-1 `test_app_vis.py` isolation pattern), since `HelaoVis.__init__` sets the global logger when unset.

---

### Task 1: visualizer host apps (`action_visualizer`, `live_visualizer`)

**Files:**
- Create: `helao/framework/app/servers/__init__.py`
- Create: `helao/framework/app/servers/action_visualizer.py`
- Create: `helao/framework/app/servers/live_visualizer.py`
- Test: `helao/framework/tests/test_app_servers_visualizers.py`

**Interfaces:**
- Consumes: `helao.framework.app.vis.HelaoVis`; `helao.framework.adapters.vis_subscriber.mount_visualizers`.
- Produces: `action_visualizer.makeBokehApp(doc, confPrefix, server_key, helao_repo_root) -> doc` (mounts `"action_vis"`); `live_visualizer.makeBokehApp(...) -> doc` (mounts `"live_vis"`).

- [ ] **Step 1: Write the failing test**

```python
# helao/framework/tests/test_app_servers_visualizers.py
"""Framework generic visualizer host apps (action/live)."""
import pytest

from helao.framework.support import config_loader
from helao.framework.adapters import vis_subscriber as vsmod


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
    prev_cfg = config_loader.CONFIG
    from helao.framework.support import helao_logging
    prev_log = helao_logging.LOGGER
    config_loader.CONFIG = {
        "root": str(tmp_path / "INST"),
        "loaded_config_path": "/configs/demo.yml",
        "servers": {
            "VIS": {"host": "127.0.0.1", "port": 5001, "params": {}},
            "ACT": {"host": "127.0.0.1", "port": 5002},
        },
    }
    yield config_loader.CONFIG
    config_loader.CONFIG = prev_cfg
    helao_logging.LOGGER = prev_log


def test_action_visualizer_mounts_header(cfg):
    from helao.framework.app.servers.action_visualizer import makeBokehApp
    doc = FakeDoc()
    out = makeBokehApp(doc, "demo", "VIS", "/repo")
    assert out is doc
    assert len(doc.roots) >= 1  # header banner mounted


def test_live_visualizer_mounts_header(cfg):
    from helao.framework.app.servers.live_visualizer import makeBokehApp
    doc = FakeDoc()
    out = makeBokehApp(doc, "demo", "VIS", "/repo")
    assert out is doc
    assert len(doc.roots) >= 1


def test_action_visualizer_mounts_declared_vis(cfg, monkeypatch):
    """A server declaring action_vis gets its C_vis instantiated via mount_visualizers."""
    from helao.framework.app.servers.action_visualizer import makeBokehApp
    cfg["servers"]["ACT"]["action_vis"] = "x_vis"
    made = []

    class FakeC:
        def __init__(self, vis_serv, serv_key):
            made.append(serv_key)

    monkeypatch.setattr(vsmod, "import_vis_class", lambda name: FakeC)
    makeBokehApp(FakeDoc(), "demo", "VIS", "/repo")
    assert made == ["ACT"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_servers_visualizers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'helao.framework.app.servers'`

- [ ] **Step 3: Write minimal implementation**

Create `helao/framework/app/servers/__init__.py`:

```python
# helao/framework/app/servers/__init__.py
"""Framework-provided, deployment-agnostic generic server entry points."""
```

Create `helao/framework/app/servers/action_visualizer.py`:

```python
# helao/framework/app/servers/action_visualizer.py
"""Deployment-agnostic action-data visualizer host (framework app layer)."""
__all__ = ["makeBokehApp"]

import os
from socket import gethostname

from bokeh.models.widgets import Div
from bokeh.layouts import layout, Spacer

from helao.framework.app.vis import HelaoVis
from helao.framework.adapters.vis_subscriber import mount_visualizers
from helao.framework.support import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def makeBokehApp(doc, confPrefix, server_key, helao_repo_root):
    """Build the action-visualizer Bokeh document; mount per-server ``action_vis`` modules."""
    app = HelaoVis(server_key=server_key, doc=doc)
    config = app.helao_cfg
    config_filename = os.path.basename(config["loaded_config_path"])
    app.vis.doc.add_root(
        layout(
            [
                Spacer(width=20),
                Div(
                    text=f"<b>Action visualizer on {gethostname().lower()} -- config: {config_filename}</b>",
                    width=1004,
                    height=32,
                    styles={"font-size": "200%", "color": "#CB4335"},
                ),
            ],
            width=1024,
        )
    )
    app.vis.doc.add_root(Spacer(height=10))
    mount_visualizers(app, "action_vis")
    return doc
```

Create `helao/framework/app/servers/live_visualizer.py` (identical except the banner label and the mounted key `"live_vis"`):

```python
# helao/framework/app/servers/live_visualizer.py
"""Deployment-agnostic live-data visualizer host (framework app layer)."""
__all__ = ["makeBokehApp"]

import os
from socket import gethostname

from bokeh.models.widgets import Div
from bokeh.layouts import layout, Spacer

from helao.framework.app.vis import HelaoVis
from helao.framework.adapters.vis_subscriber import mount_visualizers
from helao.framework.support import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def makeBokehApp(doc, confPrefix, server_key, helao_repo_root):
    """Build the live-visualizer Bokeh document; mount per-server ``live_vis`` modules."""
    app = HelaoVis(server_key=server_key, doc=doc)
    app.vis.doc.add_root(
        layout(
            [
                Spacer(width=20),
                Div(
                    text=f"<b>Live visualizer on {gethostname().lower()} -- config: {confPrefix}</b>",
                    width=1004,
                    height=32,
                    styles={"font-size": "200%", "color": "#CB4335"},
                ),
            ],
            width=1024,
        )
    )
    app.vis.doc.add_root(Spacer(height=10))
    mount_visualizers(app, "live_vis")
    return doc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_servers_visualizers.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add helao/framework/app/servers/__init__.py helao/framework/app/servers/action_visualizer.py helao/framework/app/servers/live_visualizer.py helao/framework/tests/test_app_servers_visualizers.py
git commit -m "feat(framework): SP-DEPLOY-1 — generic action/live visualizer host apps"
```

---

### Task 2: operator app (`standalone_operator`)

**Files:**
- Create: `helao/framework/app/servers/standalone_operator.py`
- Test: `helao/framework/tests/test_app_servers_operator.py`

**Interfaces:**
- Consumes: `helao.framework.app.vis.HelaoVis`; `helao.framework.adapters.operator_backend.RemoteBackend`; `helao.framework.app.operator.bokeh_operator.BokehOperator`.
- Produces: `standalone_operator.makeBokehApp(doc, confPrefix, server_key, helao_repo_root) -> doc` with `doc.operator` set to a `BokehOperator`.

- [ ] **Step 1: Write the failing test**

```python
# helao/framework/tests/test_app_servers_operator.py
"""Framework generic standalone operator host app."""
import pytest

from helao.framework.support import config_loader


class FakeDoc:
    def __init__(self):
        self.title = None
        self.roots = []
        self.operator = None

    def add_root(self, root):
        self.roots.append(root)

    def add_next_tick_callback(self, cb):
        pass

    def on_session_destroyed(self, cb):
        pass


@pytest.fixture
def cfg(tmp_path):
    prev_cfg = config_loader.CONFIG
    from helao.framework.support import helao_logging
    prev_log = helao_logging.LOGGER
    config_loader.CONFIG = {
        "root": str(tmp_path / "INST"),
        "loaded_config_path": "/configs/demo.yml",
        # no experiment_libraries / sequence_libraries → RemoteBackend autoload is empty
        "servers": {
            "OP": {"host": "127.0.0.1", "port": 5003, "params": {"poll_interval": 1.0}},
            "ORCH": {"group": "orchestrator", "host": "127.0.0.1", "port": 8001},
        },
    }
    yield config_loader.CONFIG
    config_loader.CONFIG = prev_cfg
    helao_logging.LOGGER = prev_log


def test_operator_app_builds_and_binds_backend(cfg):
    from helao.framework.app.servers.standalone_operator import makeBokehApp
    from helao.framework.app.operator.bokeh_operator import BokehOperator
    from helao.framework.adapters.operator_backend import RemoteBackend

    doc = FakeDoc()
    out = makeBokehApp(doc, "demo", "OP", "/repo")
    assert out is doc
    assert isinstance(doc.operator, BokehOperator)
    assert isinstance(doc.operator.backend, RemoteBackend)
    # backend resolved the lone group:orchestrator server
    assert doc.operator.backend.orch_key == "ORCH"
```

> If `BokehOperator` stores the backend under a different attribute than `.backend`,
> inspect `helao/framework/app/operator/bokeh_operator.py` (the constructor
> `BokehOperator(vis, backend)`) for the real attribute name and assert on that.
> If `RemoteBackend.__init__` does heavier work than library autoload (e.g. opens a
> socket), monkeypatch the heavy call; the test asserts wiring (`orch_key`), not a
> live orchestrator.

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_servers_operator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'helao.framework.app.servers.standalone_operator'`

- [ ] **Step 3: Write minimal implementation**

Create `helao/framework/app/servers/standalone_operator.py`:

```python
# helao/framework/app/servers/standalone_operator.py
"""Deployment-agnostic standalone operator host (framework app layer)."""
__all__ = ["makeBokehApp"]

from helao.framework.app.vis import HelaoVis
from helao.framework.adapters.operator_backend import RemoteBackend
from helao.framework.app.operator.bokeh_operator import BokehOperator
from helao.framework.support import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def makeBokehApp(doc, confPrefix, server_key, helao_repo_root):
    """Build the standalone operator Bokeh document.

    Constructs a framework ``HelaoVis`` host, a ``RemoteBackend`` pointed at the
    orchestrator named by ``params.orch_key`` (or the lone ``group:orchestrator``
    server), and a ``BokehOperator`` UI bound to that backend.
    """
    app = HelaoVis(server_key=server_key, doc=doc)
    params = app.vis.server_cfg.get("params", {})
    backend = RemoteBackend(
        app.vis,
        orch_key=params.get("orch_key"),
        poll_interval=params.get("poll_interval", 5.0),
    )
    doc.operator = BokehOperator(app.vis, backend)
    return doc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_servers_operator.py -v`
Expected: PASS (1 passed). If it fails on the backend attribute name, adjust the assertion to the real attribute per the Step 1 note (do not change the implementation).

- [ ] **Step 5: Commit**

```bash
git add helao/framework/app/servers/standalone_operator.py helao/framework/tests/test_app_servers_operator.py
git commit -m "feat(framework): SP-DEPLOY-1 — generic standalone operator host app"
```

---

### Task 3: Full-suite + boundary verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full framework test suite**

Run: `conda run -n helao python -m pytest helao/framework/tests/ -p no:cacheprovider -q 2>&1 | tail -1`
Expected: all pass, no regressions.

- [ ] **Step 2: Confirm the AST boundary check is green**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_boundaries.py -v`
Expected: PASS. The new modules are app-layer; `domain/` untouched.

- [ ] **Step 3: Confirm pure-addition (no deploy/core edits)**

Run: `git diff --name-only feat/framework-scaffold...HEAD | grep -E "helao/(core|deploy)/" || echo "NONE (clean)"`
Expected: `NONE (clean)` — only `helao/framework/**` and docs.

- [ ] **Step 4: Commit (only if verification fixups were needed)**

```bash
git add -A
git commit -m "test(framework): SP-DEPLOY-1 — verify full suite + boundary green"
```

---

## Self-Review

**Spec coverage:**
- §4.1 `app/servers/action_visualizer.py` → Task 1. ✓
- §4.2 `app/servers/live_visualizer.py` → Task 1. ✓
- §4.3 `app/servers/standalone_operator.py` → Task 2. ✓
- §4.4 relationship to `app/vis.py` makeBokehApp (named launcher-resolvable entries) → Tasks 1/2 inline the few lines (acceptable per spec). ✓
- §6 error handling (mount skips, orch_key resolution) → exercised by Task 1 declared-vis test + Task 2 orch_key assertion. ✓
- §7 test strategy (fake doc + CONFIG isolation, header mount, declared-vis mount, operator binds backend) → Tasks 1-2. ✓
- §2 non-goals (no deploy edits, no orchestrator-config wiring, no reference mechanism) → Task 3 Step 3 guard. ✓

**Placeholder scan:** No TBD/TODO. Full module + test code given. Guarded notes (backend attribute name, RemoteBackend heavy-init monkeypatch) are concrete conditionals.

**Type consistency:** all three modules expose `makeBokehApp(doc, confPrefix, server_key, helao_repo_root) -> doc`. `HelaoVis(server_key=, doc=)` + `app.vis` + `mount_visualizers(app, key)` match SP-VIS-1. `RemoteBackend(vis, orch_key=, poll_interval=)` + `BokehOperator(vis, backend)` match SP-VIS-3. CONFIG-isolation fixtures restore both `config_loader.CONFIG` and `helao_logging.LOGGER`.
