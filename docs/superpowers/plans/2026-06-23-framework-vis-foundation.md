# Framework SP-VIS-1 Bokeh Visualizer Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the shared Bokeh-visualizer foundation (`Vis`/`HelaoVis`, `VisSubscriber`/`LiveVisualizer`/`ActionVisualizer` + `import_vis_class`/`mount_visualizers`, and `helao_dirs`) into the framework `app/`, `adapters/`, and `support/` layers, with API parity and unit tests, as a pure addition that rewires no deployment.

**Architecture:** Three new framework modules. `support/helao_dirs.py` ports the directory-tree helper. `app/vis.py` hosts the Bokeh `Document` (collapsing the Bokeh half of legacy `HelaoBokehAPI` into `HelaoVis`) and builds a `Vis` helper. `adapters/vis_subscriber.py` holds the WebSocket-ingest base classes (an I/O adapter: ws client + Bokeh `ColumnDataSource` streaming) plus the deployment `C_vis` discovery/mount helpers. Legacy `core/servers/vis*.py` stay untouched (strangler-fig).

**Tech Stack:** Python 3.12 (conda env `helao`), Bokeh (layout/models), pydantic models, `pytest`. Reuses legacy `helao.helpers.ws_utils.WsSubscriber` as-is.

## Global Constraints

- Run Python/pytest via the `helao` conda env: `conda run -n helao python -m pytest ...` (OS Python is 3.14; the project targets 3.12).
- Boundary contract: `domain/` never imports Bokeh/FastAPI/httpx/filesystem/adapters. New code lives only in `app/`, `adapters/`, `support/`. The AST boundary check (`helao/framework/_devtools/boundary_check.py`) must stay green.
- Pure addition: do NOT modify any `helao/core/**` or `helao/deploy/**` file.
- Preserve public symbols & attribute surfaces: `Vis`, `HelaoVis`, `LiveVisualizer`, `ActionVisualizer`, `makeBokehApp`; `HelaoVis` exposes `helao_srv`/`helao_cfg`/`server_cfg`/`server_params`/`server`/`doc`/`vis`; `Vis` exposes `server`/`server_cfg`/`world_cfg`/`doc`/`helaodirs`/`print_message`.
- Read config live: `HelaoVis`/`Vis` must read `helao.framework.support.config_loader.CONFIG` at construction time via the module (not a snapshot captured at import), so tests can set it.
- New tests live under `helao/framework/tests/` and follow the existing `test_*` naming there.

---

### Task 1: `support/helao_dirs.py` — directory-tree helper

**Files:**
- Create: `helao/framework/support/helao_dirs.py`
- Test: `helao/framework/tests/test_support_helao_dirs.py`

**Interfaces:**
- Consumes: `helao.framework.models.helaodirs.HelaoDirs` (already exists; pydantic model with `root`/`save_root`/`log_root`/`states_root`/`db_root`/`user_exp`/`user_seq`/`ana_root`/`process_root`, all `Optional` defaulting `None`).
- Produces: `helao_dirs(world_cfg: dict, server_name: Optional[str] = None) -> HelaoDirs`.

- [ ] **Step 1: Write the failing test**

```python
# helao/framework/tests/test_support_helao_dirs.py
"""Unit tests for the framework helao_dirs directory-tree helper."""
import os
import zipfile

import pytest

from helao.framework.support.helao_dirs import helao_dirs


def test_builds_tree_under_root(tmp_path):
    root = str(tmp_path / "INST")
    dirs = helao_dirs({"root": root})
    assert str(dirs.root) == root
    for sub in ("RUNS_ACTIVE", "LOGS", "STATES", "DATABASE", "ANALYSES", "PROCESSES"):
        assert os.path.isdir(os.path.join(root, sub))
    assert os.path.isdir(os.path.join(root, "USER_CONFIG", "EXP"))
    assert os.path.isdir(os.path.join(root, "USER_CONFIG", "SEQ"))
    assert str(dirs.save_root) == os.path.join(root, "RUNS_ACTIVE")
    assert str(dirs.log_root) == os.path.join(root, "LOGS")


def test_no_root_returns_all_none():
    dirs = helao_dirs({})
    assert dirs.root is None
    assert dirs.save_root is None
    assert dirs.log_root is None


def test_rotates_old_txt_logs(tmp_path):
    root = str(tmp_path / "INST")
    server = "TESTSRV"
    log_dir = os.path.join(root, "LOGS", server)
    os.makedirs(log_dir)
    log_path = os.path.join(log_dir, "TESTSRV.txt")
    with open(log_path, "w") as f:
        f.write("[12:34:56] startup line\n")

    helao_dirs({"root": root}, server_name=server)

    assert not os.path.exists(log_path)  # original removed
    zips = [n for n in os.listdir(log_dir) if n.endswith(".zip")]
    assert len(zips) == 1
    with zipfile.ZipFile(os.path.join(log_dir, zips[0])) as zf:
        assert any(name.endswith("123456.txt") for name in zf.namelist())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_support_helao_dirs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'helao.framework.support.helao_dirs'`

- [ ] **Step 3: Write minimal implementation**

Port `helao/helpers/helao_dirs.py` near-verbatim; only the `HelaoDirs` import changes to the framework model.

```python
# helao/framework/support/helao_dirs.py
"""Resolve and prepare the on-disk directory layout used by a HELAO server.

Given a loaded config, ``helao_dirs`` ensures the standard ``RUNS_ACTIVE``,
``LOGS``, ``STATES``, ``DATABASE``, ``USER_CONFIG``, ``ANALYSES`` and
``PROCESSES`` subdirectories exist under the configured ``root``, archives
any leftover ``*.txt`` log files from a previous run, and returns a
populated ``HelaoDirs`` model.
"""

__all__ = ["helao_dirs"]

import os
import zipfile
import re
from glob import glob
from typing import Optional

from helao.framework.models.helaodirs import HelaoDirs


def helao_dirs(world_cfg: dict, server_name: Optional[str] = None) -> HelaoDirs:
    """Create the standard HELAO directory tree and return its paths.

    If ``world_cfg`` defines a ``root``, the canonical subdirectories under
    that root are created if missing and any prior ``*.txt`` logs under
    ``LOGS/<server_name>`` are zipped and removed. If ``root`` is absent,
    a ``HelaoDirs`` with all-``None`` paths is returned.
    """

    def check_dir(path):
        if not os.path.isdir(path):
            print(f"Warning: directory '{path}' does not exist. Creating it.")
            os.makedirs(path)

    if "root" in world_cfg:
        root = world_cfg["root"]
        save_root = os.path.join(root, "RUNS_ACTIVE")
        log_root = os.path.join(root, "LOGS")
        states_root = os.path.join(root, "STATES")
        db_root = os.path.join(root, "DATABASE")
        user_exp = os.path.join(root, "USER_CONFIG", "EXP")
        user_seq = os.path.join(root, "USER_CONFIG", "SEQ")
        ana_root = os.path.join(root, "ANALYSES")
        process_root = os.path.join(root, "PROCESSES")
        print(f"Found root directory in config: {world_cfg['root']}")
        for path in (
            root, save_root, log_root, states_root, db_root,
            user_exp, user_seq, ana_root, process_root,
        ):
            check_dir(path)

        helaodirs = HelaoDirs(
            root=root,
            save_root=save_root,
            log_root=log_root,
            states_root=states_root,
            db_root=db_root,
            user_exp=user_exp,
            user_seq=user_seq,
            ana_root=ana_root,
            process_root=process_root,
        )

        if server_name is not None:
            old_log_txts = glob(os.path.join(log_root, server_name, "*.txt"))
            nots_counter = 0
            for old_log in old_log_txts:
                print(f"Compressing: {old_log}")
                try:
                    timestamp_found = False
                    timestamp = ""
                    with open(old_log, "r") as f:
                        for line in f:
                            if line.replace("error_[", "[").strip().startswith("["):
                                timestamp_found = True
                                timestamp = re.findall(
                                    "[0-9]{2}:[0-9]{2}:[0-9]{2}", line
                                )[0].replace(":", "")
                                zipname = old_log.replace(".txt", f"{timestamp}.zip")
                                arcname = os.path.basename(old_log).replace(
                                    ".txt", f"{timestamp}.txt"
                                )
                                break
                    if not timestamp_found:
                        while os.path.exists(
                            old_log.replace(".txt", f"__{nots_counter}.zip")
                        ):
                            nots_counter += 1
                        zipname = old_log.replace(".txt", f"__{nots_counter}.zip")
                        arcname = os.path.basename(old_log).replace(
                            ".txt", f"__{nots_counter}.txt"
                        )
                    with zipfile.ZipFile(
                        zipname, "w", compression=zipfile.ZIP_DEFLATED
                    ) as zf:
                        zf.write(old_log, arcname)
                    os.remove(old_log)
                except Exception as e:
                    print(f"Error compressing log: {old_log}, {e}")
    else:
        helaodirs = HelaoDirs(
            root=None, save_root=None, log_root=None, states_root=None,
            db_root=None, user_exp=None, user_seq=None, ana_root=None,
            process_root=None,
        )

    return helaodirs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_support_helao_dirs.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add helao/framework/support/helao_dirs.py helao/framework/tests/test_support_helao_dirs.py
git commit -m "feat(framework): SP-VIS-1 — port helao_dirs into support/"
```

---

### Task 2: `app/vis.py` — `Vis` / `HelaoVis` / `makeBokehApp`

**Files:**
- Create: `helao/framework/app/vis.py`
- Test: `helao/framework/tests/test_app_vis.py`

**Interfaces:**
- Consumes: `helao.framework.support.helao_dirs.helao_dirs` (Task 1); `helao.framework.support.config_loader` (module, for live `CONFIG`); `helao.framework.support.helao_logging` (logger factory + `LOGGER`); `helao.framework.models.machine.MachineModel`.
- Produces:
  - `class Vis` — `__init__(self, bokehapp)`; attrs `server`/`server_cfg`/`world_cfg`/`doc`/`helaodirs`; method `print_message(*args, **kwargs)`. Raises `ValueError` if `helaodirs.root is None`.
  - `class HelaoVis` — `__init__(self, server_key, doc)`; attrs `helao_srv`/`helao_cfg`/`server_cfg`/`server_params`/`server`/`doc_name`/`doc`/`vis` (a `Vis`).
  - `def makeBokehApp(doc, confPrefix, server_key, helao_repo_root) -> doc`.

> **Implementation note:** `HelaoVis` merges the Bokeh half of legacy
> `helpers/server_api.py:HelaoBokehAPI` with legacy `core/servers/vis.py`'s
> `HelaoVis`+`Vis`. It reads `config_loader.CONFIG` live at construction.
> `MachineModel` is built with `server_name`+`machine_name` (host/port are
> optional and looked up from the server config slice when present).

- [ ] **Step 1: Write the failing test**

```python
# helao/framework/tests/test_app_vis.py
"""Unit tests for the framework Bokeh visualizer host (app/vis.py)."""
import pytest

from helao.framework.support import config_loader
from helao.framework.app import vis as vis_mod
from helao.framework.app.vis import HelaoVis, Vis, makeBokehApp


class FakeDoc:
    """Minimal stand-in for a Bokeh Document."""

    def __init__(self):
        self.title = None
        self.roots = []
        self.session_destroyed_cb = None

    def add_root(self, root):
        self.roots.append(root)

    def add_next_tick_callback(self, cb):
        self.next_tick = cb

    def on_session_destroyed(self, cb):
        self.session_destroyed_cb = cb


@pytest.fixture
def cfg(tmp_path):
    """Install a minimal world config on config_loader.CONFIG, restore after."""
    prev = config_loader.CONFIG
    config_loader.CONFIG = {
        "root": str(tmp_path / "INST"),
        "loaded_config_path": "/configs/demo.yml",
        "servers": {
            "VIS": {"host": "127.0.0.1", "port": 5001, "params": {"doc_name": "Demo Vis"}},
        },
    }
    yield config_loader.CONFIG
    config_loader.CONFIG = prev


def test_helaovis_builds(cfg):
    doc = FakeDoc()
    app = HelaoVis(server_key="VIS", doc=doc)
    assert app.helao_srv == "VIS"
    assert app.server_params == {"doc_name": "Demo Vis"}
    assert app.doc_name == "Demo Vis"
    assert doc.title == "Demo Vis"
    assert isinstance(app.vis, Vis)
    assert str(app.vis.helaodirs.root) == cfg["root"]


def test_vis_raises_without_root(tmp_path):
    prev = config_loader.CONFIG
    config_loader.CONFIG = {
        "loaded_config_path": "/configs/noroot.yml",
        "servers": {"VIS": {"host": "h", "port": 1, "params": {}}},
    }
    try:
        with pytest.raises(ValueError):
            HelaoVis(server_key="VIS", doc=FakeDoc())
    finally:
        config_loader.CONFIG = prev


def test_makebokehapp_returns_doc_with_roots(cfg):
    doc = FakeDoc()
    out = makeBokehApp(doc, "demo", "VIS", "/repo/root")
    assert out is doc
    assert len(doc.roots) >= 1  # header banner mounted
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_vis.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'helao.framework.app.vis'`

- [ ] **Step 3: Write minimal implementation**

```python
# helao/framework/app/vis.py
"""Bokeh visualization host for the HELAO framework (app layer).

Ports legacy ``core/servers/vis.py`` and the Bokeh half of
``helpers/server_api.py:HelaoBokehAPI`` into the framework ``app/`` layer.
``HelaoVis`` hosts the Bokeh ``Document`` and server identity; ``Vis`` is the
per-server helper exposing config, directories and a logger; ``makeBokehApp``
is the factory the bokeh launcher imports.
"""

__all__ = ["Vis", "HelaoVis", "makeBokehApp"]

import os
from socket import gethostname

from bokeh.models.widgets import Div
from bokeh.layouts import layout, Spacer

from helao.framework.support import helao_logging as logging
from helao.framework.support import config_loader
from helao.framework.support.helao_dirs import helao_dirs
from helao.framework.models.machine import MachineModel

LOGGER = logging.LOGGER


class HelaoVis:
    """Bokeh application host: server identity + document + ``Vis`` helper.

    Reads ``config_loader.CONFIG`` live, initializes the logger if unset,
    builds a :class:`MachineModel`, titles the document from
    ``params.doc_name``, and constructs a :class:`Vis` onto ``self.vis``.
    """

    def __init__(self, server_key, doc):
        self.helao_srv = server_key
        self.helao_cfg = config_loader.CONFIG
        self.server_cfg = self.helao_cfg["servers"][self.helao_srv]
        self.server_params = self.server_cfg.get("params", {})
        if logging.LOGGER is None:
            logging.LOGGER = logging.make_logger(
                logger_name=server_key,
                log_dir=os.path.join(self.helao_cfg["root"], "LOGS")
                if "root" in self.helao_cfg
                else None,
                show_debug_console=self.helao_cfg.get("show_debug", False),
            )
        self.server = MachineModel(
            server_name=self.helao_srv,
            machine_name=gethostname().lower(),
        )
        self.doc_name = self.server_params.get("doc_name", f"{self.helao_srv} Bokeh App")
        self.doc = doc
        self.doc.title = self.doc_name
        self.vis = Vis(self)


class Vis:
    """Per-server visualization helper (config, directories, logger)."""

    def __init__(self, bokehapp):
        self.server = MachineModel(
            server_name=bokehapp.helao_srv, machine_name=gethostname().lower()
        )
        self.server_cfg = bokehapp.helao_cfg["servers"][self.server.server_name]
        self.world_cfg = bokehapp.helao_cfg
        self.doc = bokehapp.doc

        self.helaodirs = helao_dirs(self.world_cfg, self.server.server_name)

        if self.helaodirs.root is None:
            raise ValueError(
                "Warning: root directory was not defined. "
                "Logs, PRCs, PRGs, and data will not be written."
            )

    def print_message(self, *args, **kwargs):
        logging.print_message(
            LOGGER,
            self.server.server_name,
            log_dir=self.helaodirs.log_root,
            *args,
            **kwargs,
        )


def makeBokehApp(doc, confPrefix, server_key, helao_repo_root):
    """Build a generic Bokeh visualizer document for ``server_key``.

    Hosts a :class:`HelaoVis`, mounts a header banner, then mounts one
    per-action visualizer for every server declaring an ``action_vis`` key.
    Deployment-specific visualizer apps may provide their own ``makeBokehApp``.
    """
    from helao.framework.adapters.vis_subscriber import mount_visualizers

    app = HelaoVis(server_key=server_key, doc=doc)
    config = app.helao_cfg
    config_filename = os.path.basename(config["loaded_config_path"])

    app.vis.doc.add_root(
        layout(
            [
                Spacer(width=20),
                Div(
                    text=f"<b>Visualizer on {gethostname().lower()} -- config: {config_filename}</b>",
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

> If `helao.framework.support.helao_logging` does not expose `print_message`,
> use the closest available logging call in that module (check its `__all__`);
> the legacy `print_message(LOGGER, name, log_dir=..., *args)` shape is the
> target. Do not import from `helao.helpers` for logging — use the framework
> `support` logger.

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_vis.py -v`
Expected: PASS (3 passed). The `makeBokehApp` test also exercises Task 3's `mount_visualizers`; if Task 3 is not yet implemented, the import inside `makeBokehApp` will fail — implement Task 3 before running this specific test, or temporarily mark `test_makebokehapp_returns_doc_with_roots` with `@pytest.mark.skip` and unskip after Task 3. (Recommended: keep tasks ordered 1→2→3; run the full file at the end of Task 3.)

- [ ] **Step 5: Commit**

```bash
git add helao/framework/app/vis.py helao/framework/tests/test_app_vis.py
git commit -m "feat(framework): SP-VIS-1 — port Vis/HelaoVis/makeBokehApp into app/"
```

---

### Task 3: `adapters/vis_subscriber.py` — WS-ingest base classes + mount helpers

**Files:**
- Create: `helao/framework/adapters/vis_subscriber.py`
- Test: `helao/framework/tests/test_adapters_vis_subscriber.py`

**Interfaces:**
- Consumes: `helao.framework.app.vis.Vis` (type only, Task 2); `helao.helpers.ws_utils.WsSubscriber` (legacy, reused as-is — `WsSubscriber(host, port, path, max_qlen=500)`, async `read_messages() -> list`); `helao.framework.support.config_loader` (module, for `CONFIG` in `_deployment_search_order`); Bokeh `Spacer`.
- Produces:
  - `VISsubscriber` base class **named** `VisSubscriber` with class attrs `WS_PATH`/`USE_WSS`/`GUARD_EMPTY_MESSAGES`/`DEFAULT_MAX_POINTS`/`DEFAULT_UPDATE_RATE`/`SUBSCRIBE_LABEL`; `__init__(self, vis_serv, serv_key, *, max_points=None, update_rate=None)`; methods `_mount`/`cleanup_session`/`update_input_value`/`callback_input_max_points`/`callback_input_update_rate`/`IOloop_data`/`add_points` (abstract). Sets `connected`.
  - `LiveVisualizer(VisSubscriber)` (`WS_PATH="ws_live"`, `GUARD_EMPTY_MESSAGES=True`), `ActionVisualizer(VisSubscriber)` (`WS_PATH="ws_data"`, `DEFAULT_UPDATE_RATE=1e-3`).
  - `VIS_CLASS_NAME = "C_vis"`; `import_vis_class(module_name, class_name="C_vis")`; `mount_visualizers(app, vis_cfg_key) -> list`.

- [ ] **Step 1: Write the failing test**

```python
# helao/framework/tests/test_adapters_vis_subscriber.py
"""Unit tests for the framework Bokeh ws-subscriber adapter."""
import asyncio

import pytest

from helao.framework.adapters import vis_subscriber as vsmod
from helao.framework.adapters.vis_subscriber import (
    VisSubscriber,
    LiveVisualizer,
    ActionVisualizer,
    import_vis_class,
    mount_visualizers,
)


class FakeDoc:
    def __init__(self):
        self.roots = []
        self.session_destroyed_cb = None
        self.next_ticks = []

    def add_root(self, root):
        self.roots.append(root)

    def add_next_tick_callback(self, cb):
        self.next_ticks.append(cb)

    def on_session_destroyed(self, cb):
        self.session_destroyed_cb = cb


class FakeVis:
    """Stand-in for app.vis.Vis."""

    def __init__(self, servers):
        self.doc = FakeDoc()
        self.server_cfg = {"params": {}}
        self.world_cfg = {"servers": servers}


def make_sub(cls, serv_key, servers):
    """Build a subscriber with USE_WSS off (no real ws)."""

    class _Sub(cls):
        USE_WSS = False

        def add_points(self, datapackage_list):
            self.received = getattr(self, "received", [])
            self.received.append(datapackage_list)

    return _Sub(vis_serv=FakeVis(servers), serv_key=serv_key)


def test_connected_when_server_present():
    sub = make_sub(VisSubscriber, "ACT", {"ACT": {"host": "h", "port": 1}})
    assert sub.connected is True
    assert sub.host == "h" and sub.port == 1


def test_not_connected_when_absent():
    sub = make_sub(VisSubscriber, "MISSING", {"ACT": {"host": "h", "port": 1}})
    assert sub.connected is False


def test_max_points_clamps():
    sub = make_sub(VisSubscriber, "ACT", {"ACT": {"host": "h", "port": 1}})

    class Sender:
        value = ""

    sub.callback_input_max_points("value", "500", "999999", Sender())
    assert sub.max_points == 10000
    sub.callback_input_max_points("value", "500", "0", Sender())
    assert sub.max_points == 2
    sub.callback_input_max_points("value", "500", "garbage", Sender())
    assert sub.max_points == 500


def test_update_rate_parses_and_falls_back():
    sub = make_sub(VisSubscriber, "ACT", {"ACT": {"host": "h", "port": 1}})

    class Sender:
        value = ""

    sub.callback_input_update_rate("value", "0.5", "2.5", Sender())
    assert sub.update_rate == 2.5
    sub.callback_input_update_rate("value", "0.5", "bad", Sender())
    assert sub.update_rate == 0.5


def test_class_specializations():
    assert LiveVisualizer.WS_PATH == "ws_live"
    assert LiveVisualizer.GUARD_EMPTY_MESSAGES is True
    assert ActionVisualizer.WS_PATH == "ws_data"
    assert ActionVisualizer.DEFAULT_UPDATE_RATE == 1e-3


def test_import_vis_class_missing_raises():
    with pytest.raises(ModuleNotFoundError):
        import_vis_class("definitely_not_a_real_vis_module_xyz")


def test_mount_visualizers_honors_limit_vis(monkeypatch):
    calls = []

    class FakeC:
        def __init__(self, vis_serv, serv_key):
            calls.append(serv_key)

    monkeypatch.setattr(vsmod, "import_vis_class", lambda name: FakeC)

    class App:
        server_params = {"limit_vis": ["A"]}
        vis = FakeVis(
            {
                "A": {"action_vis": "x_vis"},
                "B": {"action_vis": "x_vis"},
            }
        )

    mounted = mount_visualizers(App(), "action_vis")
    assert calls == ["A"]
    assert len(mounted) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_adapters_vis_subscriber.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'helao.framework.adapters.vis_subscriber'`

- [ ] **Step 3: Write minimal implementation**

Port `core/servers/vis_subscriber.py` near-verbatim. Three import changes: (1) `Vis` type from `helao.framework.app.vis`; (2) `WsSubscriber` stays `from helao.helpers.ws_utils import WsSubscriber as Wss`; (3) `config_loader` from `helao.framework.support`; (4) `_deployment_search_order` walks `helao/deploy/*/servers/visualizer` relative to the repo root — compute the deploy root from this file's location (`<repo>/helao/framework/adapters/vis_subscriber.py` → `<repo>/helao/deploy`).

```python
# helao/framework/adapters/vis_subscriber.py
"""Bokeh ws-subscriber base classes + deployment C_vis discovery (adapter).

Ports legacy ``core/servers/vis_subscriber.py`` into the framework ``adapters/``
layer. This is an I/O adapter: it owns a WebSocket client and streams batches
into Bokeh ``ColumnDataSource``s on the document thread. Plot-specific code
lives in deployment ``C_vis`` subclasses.
"""

__all__ = [
    "VisSubscriber",
    "LiveVisualizer",
    "ActionVisualizer",
    "VIS_CLASS_NAME",
    "import_vis_class",
    "mount_visualizers",
]

import os
import time
import asyncio
from functools import partial
from importlib import import_module, util as importlib_util

from bokeh.layouts import Spacer

from helao.framework.support import helao_logging as logging
from helao.framework.support import config_loader
from helao.helpers.ws_utils import WsSubscriber as Wss

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

VIS_CLASS_NAME = "C_vis"


def _deploy_root() -> str:
    """Return ``<repo>/helao/deploy`` resolved from this file's location."""
    here = os.path.abspath(__file__)
    # <repo>/helao/framework/adapters/vis_subscriber.py
    helao_root = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    return os.path.join(helao_root, "deploy")


def _deployment_search_order() -> list:
    """Deployment names to search when resolving a vis module."""
    order = []
    cfg = config_loader.CONFIG or {}
    current = cfg.get("deployment")
    if current:
        order.append(current)
    if "hte" not in order:
        order.append("hte")
    deploy_root = _deploy_root()
    if os.path.isdir(deploy_root):
        for name in sorted(os.listdir(deploy_root)):
            if name in order:
                continue
            if os.path.isdir(os.path.join(deploy_root, name, "servers", "visualizer")):
                order.append(name)
    return order


def import_vis_class(module_name: str, class_name: str = VIS_CLASS_NAME):
    """Import a visualizer class by module short name, searching deployments."""
    tried = []
    for deployment in _deployment_search_order():
        modpath = f"helao.deploy.{deployment}.servers.visualizer.{module_name}"
        tried.append(modpath)
        try:
            spec = importlib_util.find_spec(modpath)
        except ModuleNotFoundError:
            spec = None
        if spec is None:
            continue
        module = import_module(modpath)
        return getattr(module, class_name)
    raise ModuleNotFoundError(
        f"could not locate visualizer module '{module_name}' in any deployment; "
        f"tried: {tried}"
    )


def mount_visualizers(app, vis_cfg_key: str) -> list:
    """Instantiate visualizer modules declared by action servers in the config."""
    limit_vis = app.server_params.get("limit_vis", [])
    instances = []
    for server_name, server_config in app.vis.world_cfg["servers"].items():
        if not isinstance(server_config, dict):
            continue
        module_names = server_config.get(vis_cfg_key)
        if not module_names:
            continue
        if limit_vis and server_name not in limit_vis:
            continue
        if isinstance(module_names, str):
            module_names = [module_names]
        for module_name in module_names:
            viscls = import_vis_class(module_name)
            LOGGER.info(
                f"mounting '{module_name}.{VIS_CLASS_NAME}' for server '{server_name}'"
            )
            instances.append(viscls(vis_serv=app.vis, serv_key=server_name))
    return instances


class VisSubscriber:
    """Common bring-up for Bokeh visualizers backed by an action-server WebSocket."""

    WS_PATH = "ws_data"
    USE_WSS = True
    GUARD_EMPTY_MESSAGES = False
    DEFAULT_MAX_POINTS = 500
    DEFAULT_UPDATE_RATE = 0.5
    SUBSCRIBE_LABEL = "visualizer"

    def __init__(self, vis_serv, serv_key, *, max_points: int = None, update_rate: float = None):
        self.vis = vis_serv
        self.config_dict = self.vis.server_cfg.get("params", {})
        self.max_points = self.DEFAULT_MAX_POINTS if max_points is None else max_points
        self.update_rate = (
            self.config_dict.get("update_rate", self.DEFAULT_UPDATE_RATE)
            if update_rate is None
            else update_rate
        )
        self.last_update_time = time.time()

        self.serv_key = serv_key
        self.serv_config = self.vis.world_cfg["servers"].get(serv_key, None)
        self.connected = self.serv_config is not None
        if not self.connected:
            return

        self.host = self.serv_config.get("host", None)
        self.port = self.serv_config.get("port", None)
        self.data_url = f"ws://{self.host}:{self.port}/{self.WS_PATH}"
        self.wss = Wss(self.host, self.port, self.WS_PATH) if self.USE_WSS else None

        self.IOloop_data_run = False
        self.IOloop_stat_run = False

    def _mount(self, add_spacer: bool = True):
        self.vis.doc.add_root(self.layout)
        if add_spacer:
            self.vis.doc.add_root(Spacer(height=10))
        self.IOtask = asyncio.create_task(self.IOloop_data())
        self.vis.doc.on_session_destroyed(self.cleanup_session)

    def cleanup_session(self, session_context):
        LOGGER.info(f"'{self.serv_key}' Bokeh session closed")
        self.IOloop_data_run = False
        self.IOtask.cancel()

    def update_input_value(self, sender, value):
        sender.value = value

    def callback_input_max_points(self, attr, old, new, sender):
        def to_int(val):
            try:
                return int(val)
            except ValueError:
                return None

        newpts = to_int(new)
        oldpts = to_int(old)
        if newpts is None:
            newpts = oldpts if oldpts is not None else 500
        if newpts < 2:
            newpts = 2
        if newpts > 10000:
            newpts = 10000
        self.max_points = newpts
        self.vis.doc.add_next_tick_callback(
            partial(self.update_input_value, sender, f"{self.max_points}")
        )

    def callback_input_update_rate(self, attr, old, new, sender):
        def to_float(val):
            try:
                return float(val)
            except ValueError:
                return 0.5

        self.update_rate = to_float(new)
        self.vis.doc.add_next_tick_callback(
            partial(self.update_input_value, sender, f"{self.update_rate}")
        )

    async def IOloop_data(self):
        LOGGER.info(f" ... {self.SUBSCRIBE_LABEL} subscribing to: {self.data_url}")
        while True:
            if time.time() - self.last_update_time >= self.update_rate:
                messages = await self.wss.read_messages()
                if messages or not self.GUARD_EMPTY_MESSAGES:
                    self.vis.doc.add_next_tick_callback(
                        partial(self.add_points, messages)
                    )
                    self.last_update_time = time.time()
            await asyncio.sleep(0.01)

    def add_points(self, datapackage_list: list):
        raise NotImplementedError


class LiveVisualizer(VisSubscriber):
    """``ws_live`` visualizers (continuous sensor telemetry)."""

    WS_PATH = "ws_live"
    GUARD_EMPTY_MESSAGES = True
    DEFAULT_UPDATE_RATE = 0.5
    SUBSCRIBE_LABEL = "live visualizer"


class ActionVisualizer(VisSubscriber):
    """``ws_data`` visualizers (per-action measurement packages)."""

    WS_PATH = "ws_data"
    GUARD_EMPTY_MESSAGES = False
    DEFAULT_UPDATE_RATE = 1e-3
    SUBSCRIBE_LABEL = "action visualizer"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_adapters_vis_subscriber.py helao/framework/tests/test_app_vis.py -v`
Expected: PASS (all). If `test_makebokehapp_returns_doc_with_roots` was skipped in Task 2, unskip it now and confirm it passes.

- [ ] **Step 5: Commit**

```bash
git add helao/framework/adapters/vis_subscriber.py helao/framework/tests/test_adapters_vis_subscriber.py
git commit -m "feat(framework): SP-VIS-1 — port VisSubscriber + mount helpers into adapters/"
```

---

### Task 4: Full-suite + boundary verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full framework test suite**

Run: `conda run -n helao python -m pytest helao/framework/tests/ -q`
Expected: all tests pass (new + pre-existing). No regressions.

- [ ] **Step 2: Confirm the AST boundary check is green**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_coverage_gate.py helao/framework/tests/ -q -k "boundary or coverage" `
Expected: PASS — `domain/` imports no Bokeh; the new adapter's Bokeh + `helpers/ws_utils` imports are at the adapter layer (permitted). If the boundary check is invoked differently in this repo (e.g. `python -m helao.framework._devtools.boundary_check`), run that form instead and confirm it exits 0.

- [ ] **Step 3: Confirm pure-addition (no legacy/deploy edits)**

Run: `git diff --name-only origin/feat/framework-vis-foundation...HEAD 2>/dev/null || git log --name-only --oneline -4`
Expected: only files under `helao/framework/**` and `docs/superpowers/**`. No `helao/core/**` or `helao/deploy/**` paths.

- [ ] **Step 4: Commit (if any verification fixups were needed)**

```bash
git add -A
git commit -m "test(framework): SP-VIS-1 — verify full suite + boundary green"
```

---

## Self-Review

**Spec coverage:**
- §4.1 `app/vis.py` (Vis/HelaoVis/makeBokehApp) → Task 2. ✓
- §4.2 `adapters/vis_subscriber.py` (VisSubscriber/Live/Action + import/mount) → Task 3. ✓
- §4.3 `support/helao_dirs.py` → Task 1. ✓
- §6 error handling (Vis ValueError, connected flag, import_vis_class raise, callback clamps) → tested in Tasks 1–3. ✓
- §7 test strategy (fake doc + fake ws, boundary check) → Tasks 1–4. ✓
- §8 API parity (Vis/HelaoVis/LiveVisualizer/ActionVisualizer/makeBokehApp) → preserved in Tasks 2–3. ✓
- §2 non-goals (no bokeh_ws, no deployment rewiring, no legacy edits) → enforced by Task 4 Step 3. ✓

**Placeholder scan:** No TBD/TODO; all code blocks complete. The one conditional (`print_message` fallback in Task 2) is a guarded instruction with the exact target shape, not a placeholder.

**Type consistency:** `helao_dirs(world_cfg, server_name=None)` consistent across Tasks 1–2. `Vis(bokehapp)` / `HelaoVis(server_key, doc)` consistent Tasks 2–3. `VisSubscriber.__init__(vis_serv, serv_key, *, max_points, update_rate)` and `mount_visualizers(app, vis_cfg_key)` match the test usage. `config_loader.CONFIG` live-read used consistently.
