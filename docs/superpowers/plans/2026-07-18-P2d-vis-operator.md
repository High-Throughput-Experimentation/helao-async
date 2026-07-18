# P2d — Vis/Operator Hosting via Hexagon Compat-Facade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **T4's launched gate is MAIN-SESSION controller-run — do not delegate it to a subagent.**

**Goal:** Host the three shared hte Bokeh apps (`standalone_operator`, `live_visualizer`, `action_visualizer`) UNMODIFIED under the hexagon launcher via a compat-facade (D1/Q2): replace the raising `makeVisApp` in `helao/hexagon/app/factory.py` with a pure delegator to the legacy `makeBokehApp`, add three shim modules under `helao/deploy/hexagon/servers/{operator,visualizer}/` mirroring the existing action/orch shim pattern, and gate with a new `goldenhexvis.yml` config launched main-session — the hexagon-hosted bokeh servers must start under `deployment: hexagon` routing and serve their Bokeh documents (curl 200). NO native bokeh rewrite, NO ConfigPort/WsSubscriber vis adapter — that is P3 (framework SP-VIS reference). This is a SMALL, additive sub-project.

**Architecture:** `bokeh_launcher.py` imports `helao.deploy.{deployment}.servers.{group}.{bokeh_key}.makeBokehApp` by dotted path (bokeh_launcher.py:157-159) and wraps it via `partial(makeApp, confPrefix=confArg, server_key=server_key, helao_repo_root=helao_repo_root)` mounted at route `/{bokeh_key}` (bokeh_launcher.py:185-190; `servPy = server_config["bokeh"]` at :95) — Bokeh then calls it per browser session with `doc` positional. So the seam is purely a launcher-entry-point shim: each shim module exports `makeBokehApp(doc, confPrefix, server_key, helao_repo_root)` (those EXACT parameter names — the launcher passes the last three as kwargs) delegating to `factory.makeVisApp(LEGACY_MODULE, doc, confPrefix, server_key, helao_repo_root)`, which does `import_module(legacy_module).makeBokehApp(doc, confPrefix, server_key, helao_repo_root)`. All three legacy apps have the verified identical positional signature `def makeBokehApp(doc, confPrefix, server_key, helao_repo_root)` (standalone_operator.py:11, live_visualizer.py:15, action_visualizer.py:16). `HelaoBokehAPI.__init__` self-configures from `config_loader.CONFIG` (server_api.py:143-192) — no wiring object exists or is needed; the facade attaches NOTHING. **bokeh_launcher.py + launch.py need ZERO edits** — the per-server `deployment: hexagon` config key already routes the import. Vis-module fallthrough (verified, vis_subscriber.py:60-130): with `deployment: hexagon` on the LIVE entry, `_deployment_search_order()` probes `hexagon` first for `wssim_live_vis`, `find_spec` misses (module absent there), and the loop falls through to `hte` then `test` where it lives — graceful by construction.

**Tech Stack:** Python 3.12 (`conda run -n helao`), pytest + pytest-asyncio (hexagon suite `helao/hexagon/tests/`, fixtures in `test_factory.py`), `bokeh.document.Document` for real-doc test construction, pyright (authoritative), black, `launch.py` + `bokeh_launcher.py` (read-only consumers), curl for the launched gate.

## Global Constraints

Every task's requirements implicitly include this section.

- **ZERO LEGACY EDITS**: only `helao/hexagon/**`, `helao/deploy/hexagon/**`, `helao/deploy/test/configs/**`, and this plan doc. NO edits to `helao/core/servers/vis.py`, `helao/helpers/server_api.py`, the 3 hte app modules, `bokeh_launcher.py`, or `launch.py`. (D5; `helao/deploy/hexagon/` and `helao/deploy/test/` are tracked in THIS repo.)
- **COMPAT-FACADE ONLY**: apps hosted UNMODIFIED (delegate to legacy `makeBokehApp`); NO native bokeh rewrite, NO ConfigPort/WsSubscriber vis adapter (P3). NO wiring object attached to vis apps — `HelaoBokehAPI` has no injection seam (D1/D2).
- **`conda run -n helao` for all tooling** (never the OS python).
- **pyright = 0 errors and black clean at the end of every task**: `conda run -n helao pyright helao/hexagon helao/deploy/hexagon` then `conda run -n helao black <changed .py files>` immediately before each commit.
- **Frequent commits**: one commit per task, on branch `feat/hexagon-p2d-vis-operator` (off unstable 7c205e5c, already checked out). Do NOT commit or push to `main`/`unstable`. No writes to production paths.
- **No private-deployment names** anywhere in code, tests, docs, or commit messages.
- **Signature discipline**: shim `makeBokehApp` parameters must be named exactly `doc, confPrefix, server_key, helao_repo_root` (doc first) — bokeh_launcher passes `confPrefix`/`server_key`/`helao_repo_root` as kwargs via `functools.partial` and Bokeh supplies `doc` positionally. Verified against bokeh_launcher.py:185-190; T2's delegation test re-proves it by calling the shim in that exact kwarg shape.

## Reviewer-verification points (executor/controller verifies before relying)

1. **Legacy kwarg names** — VERIFIED 2026-07-18: all 3 apps define positional `makeBokehApp(doc, confPrefix, server_key, helao_repo_root)`; names match the launcher's kwargs exactly. If any app drifted since branch point, STOP and report (`grep -n "def makeBokehApp" helao/deploy/hte/servers/operator/standalone_operator.py helao/deploy/hte/servers/visualizer/live_visualizer.py helao/deploy/hte/servers/visualizer/action_visualizer.py` must show the 4-arg signature at :11/:15/:16).
2. **Launcher call convention** — VERIFIED: `partial(makeApp, confPrefix=..., server_key=..., helao_repo_root=...)`, `doc` positional per session, route `/{bokeh_key}`.
3. **Gate needs the hexagon ORCH+SIM running** — the operator subscribes ORCH `ws_status` (RemoteBackend) and live_visualizer subscribes SIM `ws_live` (P2b-2 WsPublishBridge frames). `goldenhexvis.yml` therefore includes the hexagon ORCH+SIM (+ legacy DB, matching goldenhex.yml); `LAUNCH_ORDER = [action, orchestrator, visualizer, operator]` brings them up first. Curl only after readiness polling.
4. **`CONFIG["deployment"] = "hexagon"` vis-module fallthrough** — VERIFIED graceful (see Architecture); T4 checkpoint = LIVE log line `mounting 'wssim_live_vis.C_vis' for server 'SIM'` (`VIS_CLASS_NAME = "C_vis"`, vis_subscriber.py:56).
5. **`import launch` side effects (T3)** — the config test imports `validateConfig` from `launch.py`; confirm module import is side-effect-free (top-level work is under the `__main__` guard) before relying on it. If it is not, validate structure without `launch` (unique keys / host:port pairs / required keys inline) and note it in the commit message.

## File structure

```
helao/hexagon/app/factory.py                       # MODIFY (T1): makeVisApp raise -> compat delegator; drop HexagonDeferred import
helao/hexagon/tests/test_factory.py                # MODIFY (T1): replace test_make_vis_app_defers_loudly; (T2): add test_vis_shims_delegate
helao/deploy/hexagon/servers/operator/
    __init__.py                                    # NEW (T2): empty (mirrors servers/action/__init__.py)
    standalone_operator.py                         # NEW (T2): shim -> helao.deploy.hte.servers.operator.standalone_operator
helao/deploy/hexagon/servers/visualizer/
    __init__.py                                    # NEW (T2): empty
    live_visualizer.py                             # NEW (T2): shim -> helao.deploy.hte.servers.visualizer.live_visualizer
    action_visualizer.py                           # NEW (T2): shim -> helao.deploy.hte.servers.visualizer.action_visualizer
helao/deploy/test/configs/goldenhexvis.yml         # NEW (T3): gate config (goldenhex.yml + bokeh entries, deployment: hexagon)
helao/hexagon/tests/test_vis_gate_config.py        # NEW (T3): config resolves + validates + shim dotted paths import
docs/superpowers/plans/2026-07-18-P2d-vis-operator.md   # this plan
```

T1–T3 are **[PYTEST]** (pure in-process, subagent-executable). T4 is **[LAUNCHED]** (main-session controller-run) plus the verification sweep.

---

### Task 1: `makeVisApp` compat delegator in the factory [PYTEST]

Replace the `HexagonDeferred` raise (factory.py:123-127) with a pure delegator, TDD-first.

**Files:**
- Modify: `helao/hexagon/app/factory.py`
- Modify: `helao/hexagon/tests/test_factory.py`

**Interfaces:**
- Consumes: `from importlib import import_module` (already module-level in factory.py:15 — monkeypatchable as `factory.import_module`); legacy `makeBokehApp(doc, confPrefix, server_key, helao_repo_root)`.
- Produces: `makeVisApp(legacy_module: str, doc, confPrefix, server_key, helao_repo_root)` returning whatever the legacy app returns (the `doc`). T2's shims call this. `HexagonDeferred` import drops from factory.py (this was its only use — verified) and from test_factory.py:7 (its only use was the deleted test at :105).

- [ ] **Step 1: Write the failing test**

In `helao/hexagon/tests/test_factory.py`, DELETE `test_make_vis_app_defers_loudly` (lines 101-105) and the now-unused `from helao.hexagon.adapters.errors import HexagonDeferred` import (line 7 — first confirm no other test in the file uses it: `grep -n HexagonDeferred helao/hexagon/tests/test_factory.py`). Add in its place:

```python
def test_make_vis_app_delegates_to_legacy_module(monkeypatch):
    """P2d compat-facade: makeVisApp imports the named legacy module and
    calls its makeBokehApp with the launcher-shaped args, attaching NOTHING
    (HelaoBokehAPI self-configures from CONFIG; native vis ports = P3)."""
    from bokeh.document import Document

    from helao.hexagon.app import factory

    calls = {}

    class FakeLegacy:
        @staticmethod
        def makeBokehApp(doc, confPrefix, server_key, helao_repo_root):
            calls["args"] = (doc, confPrefix, server_key, helao_repo_root)
            return doc

    def fake_import(name):
        calls["module"] = name
        return FakeLegacy

    monkeypatch.setattr(factory, "import_module", fake_import)
    doc = Document()
    out = factory.makeVisApp(
        "helao.deploy.hte.servers.operator.standalone_operator",
        doc,
        "goldenhexvis",
        "OPERATOR",
        "/repo",
    )
    assert out is doc
    assert calls["module"] == "helao.deploy.hte.servers.operator.standalone_operator"
    assert calls["args"] == (doc, "goldenhexvis", "OPERATOR", "/repo")
```

- [ ] **Step 2: Run the test — expect FAIL**

```
conda run -n helao python -m pytest helao/hexagon/tests/test_factory.py::test_make_vis_app_delegates_to_legacy_module -q
```

Expected: 1 failed — `TypeError` (current `makeVisApp(*args, **kwargs)` raises `HexagonDeferred`; the assertion path never runs). Any other failure mode (import error in the test itself) means the test is wrong — fix the test first.

- [ ] **Step 3: Implement the delegator**

In `helao/hexagon/app/factory.py`, replace the entire `makeVisApp` body (the raise, factory.py:123-127) with:

```python
def makeVisApp(legacy_module, doc, confPrefix, server_key, helao_repo_root):
    """P2d compat-facade (D1/D2): host a legacy Bokeh app UNMODIFIED.

    Delegates completely to the legacy module's makeBokehApp — no wiring is
    attached because HelaoBokehAPI self-configures from config_loader.CONFIG
    (server_api.py) and exposes no injection seam. Native vis hosting
    (ConfigPort/WsSubscriber adapters) is P3; this only makes the bokeh
    PROCESS launchable under `deployment: hexagon` routing.
    """
    return import_module(legacy_module).makeBokehApp(
        doc, confPrefix, server_key, helao_repo_root
    )
```

(Positional pass-through — the legacy signatures are positional with matching names, so this is robust either way.) Then drop `HexagonDeferred` from the factory import line (keep `UnwiredPortError`): `from helao.hexagon.adapters.errors import UnwiredPortError`.

- [ ] **Step 4: Run the factory test file — expect PASS**

```
conda run -n helao python -m pytest helao/hexagon/tests/test_factory.py -q
```

Expected: all tests pass (the new test passes; the deleted defers-loudly test is gone; no other test referenced `makeVisApp` — confirm with `grep -rn makeVisApp helao/hexagon/tests/`).

- [ ] **Step 5: pyright + black + commit**

```
conda run -n helao pyright helao/hexagon
conda run -n helao black helao/hexagon/app/factory.py helao/hexagon/tests/test_factory.py
git add helao/hexagon/app/factory.py helao/hexagon/tests/test_factory.py
git commit -m "feat(hexagon): makeVisApp compat delegator to legacy makeBokehApp (P2d T1)"
```

Expected: pyright `0 errors`; black reformats nothing or trivially; commit lands on `feat/hexagon-p2d-vis-operator`.

---

### Task 2: The three launcher shim modules [PYTEST]

Mirror the existing action/orch shim pattern (`helao/deploy/hexagon/servers/action/ws_simulator.py` — module docstring, `__all__`, `LEGACY_MODULE`, `FACTORY`, thin function; the package dirs carry an empty `__init__.py`).

**Files:**
- Create: `helao/deploy/hexagon/servers/operator/__init__.py` (empty)
- Create: `helao/deploy/hexagon/servers/operator/standalone_operator.py`
- Create: `helao/deploy/hexagon/servers/visualizer/__init__.py` (empty)
- Create: `helao/deploy/hexagon/servers/visualizer/live_visualizer.py`
- Create: `helao/deploy/hexagon/servers/visualizer/action_visualizer.py`
- Modify: `helao/hexagon/tests/test_factory.py`

**Interfaces:**
- Consumes: `helao.hexagon.app.factory.makeVisApp` (T1).
- Produces: each shim exports `makeBokehApp(doc, confPrefix, server_key, helao_repo_root)` — the exact 4-arg shape bokeh_launcher's `partial` + Bokeh session call requires (parameter NAMES are load-bearing: three are passed as kwargs). Module basenames match the config `bokeh:` values so `deployment: hexagon` flips routing with no other config change.

- [ ] **Step 1: Write the failing test**

Append to `helao/hexagon/tests/test_factory.py` (alongside `test_launcher_shims_delegate`, whose style this extends):

```python
def test_vis_shims_delegate(monkeypatch):
    """P2d: each vis/operator shim exports the 4-arg makeBokehApp shape
    bokeh_launcher calls (doc positional; confPrefix/server_key/
    helao_repo_root as kwargs) and routes through factory.makeVisApp to
    the right legacy module."""
    from bokeh.document import Document

    import helao.deploy.hexagon.servers.operator.standalone_operator as op_shim
    import helao.deploy.hexagon.servers.visualizer.action_visualizer as av_shim
    import helao.deploy.hexagon.servers.visualizer.live_visualizer as lv_shim
    from helao.hexagon.app import factory

    expected = {
        op_shim: "helao.deploy.hte.servers.operator.standalone_operator",
        lv_shim: "helao.deploy.hte.servers.visualizer.live_visualizer",
        av_shim: "helao.deploy.hte.servers.visualizer.action_visualizer",
    }
    calls = {}

    class FakeLegacy:
        @staticmethod
        def makeBokehApp(doc, confPrefix, server_key, helao_repo_root):
            calls["args"] = (doc, confPrefix, server_key, helao_repo_root)
            return doc

    def fake_import(name):
        calls["module"] = name
        return FakeLegacy

    monkeypatch.setattr(factory, "import_module", fake_import)
    for shim, legacy_module in expected.items():
        assert shim.LEGACY_MODULE == legacy_module
        assert shim.FACTORY is factory.makeVisApp
        doc = Document()
        # the EXACT call shape bokeh_launcher.py:185-190 produces
        out = shim.makeBokehApp(
            doc, confPrefix="goldenhexvis", server_key="X", helao_repo_root="/repo"
        )
        assert out is doc
        assert calls["module"] == legacy_module
        assert calls["args"] == (doc, "goldenhexvis", "X", "/repo")
```

Run — expect FAIL with `ModuleNotFoundError: No module named 'helao.deploy.hexagon.servers.operator'`:

```
conda run -n helao python -m pytest helao/hexagon/tests/test_factory.py::test_vis_shims_delegate -q
```

- [ ] **Step 2: Create the shim packages and modules**

Create the two empty `__init__.py` files, then the three shims. `standalone_operator.py`:

```python
"""Hexagon-hosted standalone operator: same module/bokeh name as the hte
app so a config flips ONLY the `deployment:` key. P2d compat-facade —
delegates to the legacy makeBokehApp UNMODIFIED (native vis = P3)."""

from helao.hexagon.app.factory import makeVisApp

__all__ = ["makeBokehApp"]

LEGACY_MODULE = "helao.deploy.hte.servers.operator.standalone_operator"
FACTORY = makeVisApp


def makeBokehApp(doc, confPrefix, server_key, helao_repo_root):
    return FACTORY(LEGACY_MODULE, doc, confPrefix, server_key, helao_repo_root)
```

`live_visualizer.py` and `action_visualizer.py` are identical except docstring first line ("live visualizer" / "action visualizer") and `LEGACY_MODULE` = `"helao.deploy.hte.servers.visualizer.live_visualizer"` / `"helao.deploy.hte.servers.visualizer.action_visualizer"`.

- [ ] **Step 3: Run the test — expect PASS**

```
conda run -n helao python -m pytest helao/hexagon/tests/test_factory.py -q
```

Expected: all pass, including `test_vis_shims_delegate` and the pre-existing `test_launcher_shims_delegate`.

- [ ] **Step 4: pyright + black + commit**

```
conda run -n helao pyright helao/hexagon helao/deploy/hexagon
conda run -n helao black helao/deploy/hexagon/servers/operator/ helao/deploy/hexagon/servers/visualizer/ helao/hexagon/tests/test_factory.py
git add helao/deploy/hexagon/servers/operator helao/deploy/hexagon/servers/visualizer helao/hexagon/tests/test_factory.py
git commit -m "feat(hexagon): vis/operator launcher shims for the 3 shared hte bokeh apps (P2d T2)"
```

Expected: pyright `0 errors`; commit lands.

---

### Task 3: `goldenhexvis.yml` gate config + in-process resolution test [PYTEST]

A NEW config (goldenhex.yml stays a pure action/orch parity config): goldenhex.yml's ORCH/SIM/DB verbatim plus golden.yml's OPERATOR/LIVE bokeh entries (and an ACTVIS entry so all 3 shims get launch-tested), each bokeh entry flipped to `deployment: hexagon`. New `root:` so the launched gate never touches the goldenhex smoke tree. Bokeh entries use `host`/`port` — there is NO `bokeh_port` key.

**Files:**
- Create: `helao/deploy/test/configs/goldenhexvis.yml`
- Create: `helao/hexagon/tests/test_vis_gate_config.py`

**Interfaces:**
- Consumes: `helao.helpers.config_loader.read_config` (accepts a full path); `launch.validateConfig(PIDD, confDict, helao_repo_root)` with a stand-in carrying `reqKeys=("host", "port", "group")` / `codeKeys=("fast", "bokeh")` (launch.py:123-124 — do NOT instantiate `Pidd`, its ctor touches pid files); T2's shim modules via the exact dotted path bokeh_launcher builds.
- Produces: the config T4 launches; a test proving config validity + shim import-resolution WITHOUT launching (validateConfig's file-existence check is dead code for bokeh entries, so the import-resolution assertion is the real pre-launch guard).

- [ ] **Step 1: Write the failing test**

Create `helao/hexagon/tests/test_vis_gate_config.py`:

```python
"""P2d gate-config checks: goldenhexvis.yml resolves, validates, and every
bokeh entry's `deployment: hexagon` dotted path import-resolves to a shim
exporting makeBokehApp — the same path bokeh_launcher.py builds."""

import os
import types
from importlib import import_module

_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
_CFG = os.path.join(
    _REPO_ROOT, "helao", "deploy", "test", "configs", "goldenhexvis.yml"
)


def _load():
    from helao.helpers.config_loader import read_config

    return read_config(_CFG)


def test_goldenhexvis_validates():
    from launch import validateConfig

    conf = _load()
    pidd = types.SimpleNamespace(
        reqKeys=("host", "port", "group"), codeKeys=("fast", "bokeh")
    )
    assert validateConfig(pidd, conf, _REPO_ROOT) is True


def test_goldenhexvis_bokeh_entries_are_hexagon_shims():
    conf = _load()
    bokeh_entries = {
        k: v for k, v in conf["servers"].items() if isinstance(v, dict) and "bokeh" in v
    }
    assert set(bokeh_entries) == {"OPERATOR", "LIVE", "ACTVIS"}
    for key, scfg in bokeh_entries.items():
        assert scfg["deployment"] == "hexagon"
        assert "bokeh_port" not in scfg  # bokeh servers use host/port
        modpath = (
            f"helao.deploy.{scfg['deployment']}.servers."
            f"{scfg['group']}.{scfg['bokeh']}"
        )  # bokeh_launcher.py:157-159 shape
        mod = import_module(modpath)
        assert callable(mod.makeBokehApp)
        assert mod.LEGACY_MODULE.startswith("helao.deploy.hte.servers.")


def test_goldenhexvis_ws_sources_present():
    """The operator needs ORCH ws_status, live vis needs SIM ws_live — the
    hexagon action/orch group must be in the gate config (reviewer point 3)."""
    conf = _load()
    servers = conf["servers"]
    assert servers["ORCH"]["deployment"] == "hexagon"
    assert servers["SIM"]["deployment"] == "hexagon"
    assert servers["SIM"]["live_vis"] == "wssim_live_vis"
    assert servers["OPERATOR"]["params"]["orch_key"] == "ORCH"
    hostports = [
        (v["host"], v["port"]) for v in servers.values() if isinstance(v, dict)
    ]
    assert len(hostports) == len(set(hostports))
```

Run — expect FAIL (`read_config` cannot find `goldenhexvis`):

```
conda run -n helao python -m pytest helao/hexagon/tests/test_vis_gate_config.py -q
```

(Reviewer point 5: if `from launch import validateConfig` turns out to have import side effects, replace `test_goldenhexvis_validates` with inline structural checks and note it in the commit message.)

- [ ] **Step 2: Write the config**

Create `helao/deploy/test/configs/goldenhexvis.yml` exactly:

```yaml
# P2d GATE config: hexagon-hosted bokeh operator/visualizers over the
# hexagon ORCH+SIM (goldenhex.yml servers verbatim + golden.yml's bokeh
# entries, each flipped to `deployment: hexagon` so bokeh_launcher resolves
# the helao/deploy/hexagon shim modules). goldenhex.yml itself stays a pure
# action/orch parity config. DB stays legacy (cut-over is P2e).
dummy: true
simulation: true
show_debug: true
run_unit_tests: true
experiment_libraries:
  - simulatews_exp
  - helao/deploy/test/experiments/TEST_exp.py
sequence_libraries:
  - helao/deploy/test/sequences/TEST_seq.py
run_type: simulation
root: /home/dan/INST_hlo_hexvis
servers:
  ORCH:
    host: 127.0.0.1
    port: 8001
    group: orchestrator
    fast: async_orch2
    deployment: hexagon
    params: {}
    exp_postprocess_libs:
      - append_params
    seq_postprocess_libs:
      - append_params
  OPERATOR:
    host: 127.0.0.1
    port: 5001
    group: operator
    bokeh: standalone_operator
    deployment: hexagon
    params:
      orch_key: ORCH
      doc_name: "Operator (hexagon compat-facade)"
      poll_interval: 5
  SIM:
    host: 127.0.0.1
    port: 8002
    group: action
    fast: ws_simulator
    deployment: hexagon
    live_vis: wssim_live_vis
    params: {}
    hlo_postprocess_libs:
      - hlo_to_csv
  LIVE:
    host: 127.0.0.1
    port: 5002
    group: visualizer
    bokeh: live_visualizer
    deployment: hexagon
    params:
      doc_name: Websocket Live Visualizer
  ACTVIS:
    host: 127.0.0.1
    port: 5003
    group: visualizer
    bokeh: action_visualizer
    deployment: hexagon
    params:
      doc_name: Action Visualizer
  DB:
    host: 127.0.0.1
    port: 8010
    group: action
    fast: sim_db_server
    params:
      aws_bucket: helao-sim
      s3_record: true
```

Before writing, diff the ORCH/SIM/DB blocks against the live `goldenhex.yml` (it is authoritative; if goldenhex drifted from the transcription above, copy ITS blocks and keep only the bokeh additions + new `root:`). Note: no action server declares `action_vis`, so ACTVIS will serve a header-only doc — that is fine; its gate assertion is "shim resolves + serves 200", not content.

- [ ] **Step 3: Run the test — expect PASS**

```
conda run -n helao python -m pytest helao/hexagon/tests/test_vis_gate_config.py -q
```

Expected: 3 passed.

- [ ] **Step 4: pyright + black + commit**

```
conda run -n helao pyright helao/hexagon helao/deploy/hexagon
conda run -n helao black helao/hexagon/tests/test_vis_gate_config.py
git add helao/deploy/test/configs/goldenhexvis.yml helao/hexagon/tests/test_vis_gate_config.py
git commit -m "feat(hexagon): goldenhexvis gate config + in-process resolution test (P2d T3)"
```

---

### Task 4: Verification sweep + LAUNCHED gate [LAUNCHED — MAIN-SESSION controller-run]

The in-process tests (T1-T3) prove delegation + shim resolution + config validity WITHOUT launching. This task proves the bokeh PROCESS starts and serves under `deployment: hexagon` routing (D3). **Not a subagent task** — run in the controller/main session, foreground group, curl-only readiness. Note: curl-ing a Bokeh app route opens a session, which EXECUTES `makeBokehApp` (shim → makeVisApp → legacy app, constructing HelaoVis/RemoteBackend live) — a 200 is the real facade proof; a broken facade yields 500.

**Files:** none (verification only; do not run with another golden/goldenhex group live — ports 8001/8002/8010 collide).

**Interfaces:**
- Consumes: everything from T1-T3; `launch.py`; the hexagon ORCH/SIM (P0-P2c baseline).
- Produces: the P2d gate evidence.

- [ ] **Step 1: Full in-process sweep**

```
conda run -n helao python -m pytest helao/hexagon/tests -q
conda run -n helao pyright helao/hexagon helao/deploy/hexagon
conda run -n helao black --check helao/hexagon helao/deploy/hexagon/servers/operator helao/deploy/hexagon/servers/visualizer
```

Expected: pytest 0 failures (includes `test_boundaries.py`); pyright `0 errors`; black `would reformat 0 files` (the P2b/P2c native re-bodies under `adapters/native/` are force-excluded via pyproject — do NOT black them; `--check` respects the exclusion).

- [ ] **Step 2: Zero-legacy-edits proof**

```
git diff --name-only $(git merge-base unstable HEAD) HEAD -- . ':!helao/hexagon' ':!helao/deploy/hexagon' ':!helao/deploy/test/configs' ':!docs/superpowers/plans'
```

Expected: EMPTY output (every changed file is inside the D5 allowlist).

- [ ] **Step 3: Launch the gate group (foreground, background bash from the controller)**

```
cd /mnt/STORAGE/repos/helao/helao-async && conda run -n helao python launch.py goldenhexvis --no-hot-reload
```

(No `extraopt` — `nolive` would SUPPRESS live_visualizer; `--no-hot-reload` keeps the watcher out of the gate.) Run via a background Bash so the group stays up while curling. Poll readiness (up to ~90 s):

```
for p in 8001 8002 8010 5001 5002 5003; do curl -s -o /dev/null -w "$p:%{http_code}\n" --max-time 5 "http://127.0.0.1:$p/" ; done
```

Expected once settled: the three bokeh ports (5001/5002/5003) respond (root path may 404 — that still proves the port is bound; the app routes are checked next). FastAPI ports 8001/8002/8010 respond 200/404.

- [ ] **Step 4: Curl the Bokeh app routes (the gate)**

Route = `/{bokeh_key}` (bokeh_launcher.py:185):

```
curl -s -o /tmp/p2d_operator.html -w "%{http_code}\n" http://127.0.0.1:5001/standalone_operator
curl -s -o /tmp/p2d_live.html     -w "%{http_code}\n" http://127.0.0.1:5002/live_visualizer
curl -s -o /tmp/p2d_actvis.html   -w "%{http_code}\n" http://127.0.0.1:5003/action_visualizer
grep -l -i "bokeh" /tmp/p2d_operator.html /tmp/p2d_live.html /tmp/p2d_actvis.html
```

Expected: `200` three times; grep lists all three files (each page embeds the Bokeh document JS). Any 500 = the facade broke inside a session — capture the bokeh server log before touching anything.

- [ ] **Step 5: Log checkpoints**

```
grep -r "mounting 'wssim_live_vis" /home/dan/INST_hlo_hexvis/LOGS/ | head -3
grep -ril "error\|traceback" /home/dan/INST_hlo_hexvis/LOGS/ | head
```

Expected: the LIVE server log shows `mounting 'wssim_live_vis.C_vis' for server 'SIM'` (proves the hexagon-first deployment search fell through to the test deployment — reviewer point 4); no tracebacks in the OPERATOR/LIVE/ACTVIS logs (inspect any grep hits — startup WARN lines are acceptable, tracebacks are not).

- [ ] **Step 6: Shut down and confirm cleanup**

Send SIGINT to the `launch.py` process (the launcher's exit path POSTs `/shutdown` + psutil-terminates children); wait, then:

```
for p in 8001 8002 8010 5001 5002 5003; do curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$p/" && echo "$p STILL UP"; done
```

Expected: no `STILL UP` lines. If stragglers remain, terminate the PIDs from `/home/dan/INST_hlo_hexvis/STATES/pids_goldenhexvis_.pck` and report it.

- [ ] **Step 7: Final commit (plan doc if amended) + report**

If any file changed during T4 (it should NOT — this is verification only), STOP and report. Otherwise record the gate evidence (curl codes, mount log line, empty zero-legacy diff, suite/pyright output) in the task report. Work stays on `feat/hexagon-p2d-vis-operator`; merging is a separate controller decision.

---

## Out of scope (D4)

Native bokeh rewrite (domain/ports/adapters split of Vis/BokehOperator/data_browser, WsSubscriber port adapter, ConfigPort injection) = P3. Broken `ws_demo.yml`/`sim_visualizer` retirement = P2e. Full goldenhex cut-over (all servers `deployment: hexagon` incl. DB) = P2e. GM-7 = deferred. Browser-rendered UI parity is a manual concern, not part of this automated gate.
