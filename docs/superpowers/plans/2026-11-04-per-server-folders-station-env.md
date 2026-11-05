# Per-Server Folders and Station-Aware Env Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Group each `hte`/`test` instrument's server, drivers, Bokeh visualizer, Reflex panel and dependency files into one folder, resolve modules through one framework resolver with no `hte` hardcode, and let `setup_env`/`update_env` install only the dependencies of the configs a station runs.

**Architecture:** A new `helao/helpers/server_modules.py` owns every module lookup (app, Bokeh, Reflex stacks). Every caller switches to it while the old layout still resolves (P1). A reusable `harness/reorg_deploy.py` moves files with `git mv` and rewrites imports from a JSON mapping. `hte` and `test` are reorganized with it (P2, P4-test). Private deployments reuse the same tool in their own repos under separate plans. A root `helao_env.py` reads station configs and installs per-folder `environment.yml` (conda first) and `requirements.txt` (uv) (P3).

**Tech Stack:** Python 3.14, pytest, conda (rattler solver), uv, ruamel.yaml, git.

**Spec:** `docs/superpowers/specs/2026-11-04-per-server-folders-station-env-design.md`

## Global Constraints

- Run Python as `/home/dan/miniforge3/envs/helao/bin/python` with `PYTHONPATH=<repo root>`. Run tests one file per process (`python -m pytest -q -p no:cacheprovider <file>`) or through `python run_tests.py --filter <substr>`. Never collect the whole tree in one pytest session.
- Use `git -C <repo>` on every git call. `hte` and `test` belong to the parent repo; every other `helao/deploy/*` is a separate private repo that this plan never edits.
- This repo is public. Never write a private deployment's name in any tracked file, commit message or test.
- Open every text file with `encoding="utf-8"`.
- Run `black` on changed `.py` files just before each commit. `pyright` (basic) must report 0 errors on changed files.
- After P2, framework code (`helao/core`, `helao/hexagon`, `helao/helpers`, `helao/ui`, `fast_launcher.py`, `bokeh_launcher.py`, `reflex_launcher.py`, `launch.py`, `harness/`) must contain no `helao.deploy.hte` import and no `"hte"` path or module literal. The data label `access = "hte"` in `helao/core/models/*` stays.
- Config values (`fast:`, `bokeh:`, `reflex:`, `action_vis:`, `live_vis:`, `control_vis:`, `deployment:`) never change.
- Never touch `/mnt/wd4`, `/mnt/st2`, `/mnt/k`, `/mnt/j`, `/mnt/i`. Test roots go under the job temp dir or pytest `tmp_path`.
- Subagents never `git add`/`commit`/`push`/`stash`. Commit steps are run by the main session after review.
- Sweep parity: before each phase, record `run_tests.py` output in the job dir. After the phase, the failing set must be a subset of the baseline's. Two failures are known and unrelated: the private-deployment XAFS golden-float tests.

## Review Focus

1. **A panel, processor or experiment library name exists in two deployments and neither is the config's own.** Expect an error naming both. Task 2 lists collisions before the semantics change; Task 5 pins the error.
2. **`HELAO_STATION_PREFIXES` names a json file, or a config inside it, that no longer exists.** Expect `update_env` to warn and skip it, not crash. Pinned in Task 13.
3. **A config's `root:` is relative, or its `STATES` dir does not exist.** Expect the STATES dir to be created under the resolved root. Pinned in Task 13.
4. **A moved module is still imported by an f-string or path string that the AST rewrite cannot see.** Examples: `hosted_server.py`, `test_vis_ws_parity.py`, `test_ole_technique.py`. Expect the reorg tool's leftover report to list it, and the task to fix every hit. Pinned in Tasks 6 and 7.
5. **Two folders' `environment.yml` both carry a `pip:` sub-list, or the same package with and without a pin.** Expect one merged file where both pins appear, so conda reports the conflict, never a silent drop. Pinned in Task 13.

---

## Phase P1: one resolver, old layout still works

### Task 1: `server_modules` resolver

**Files:**
- Create: `helao/helpers/server_modules.py`
- Test: `helao/core/tests/test_server_modules.py`

**Interfaces:**
- Produces:
  - `DEPLOY_ROOT: Path`
  - `STACKS = ("app", "bokeh", "reflex")`
  - `class AmbiguousModule(LookupError)`
  - `deployments(deploy_root: Path = DEPLOY_ROOT) -> list[str]`
  - `module_file(deployment: str, module: str, stack: str, deploy_root: Path = DEPLOY_ROOT) -> Path | None`
  - `locate(module: str, stack: str, own: str | None = None, deploy_root: Path = DEPLOY_ROOT) -> tuple[str | None, list[str]]`
  - `import_path(path: Path, deploy_root: Path = DEPLOY_ROOT) -> str`

- [ ] **Step 1: Write the failing test**

```python
"""server_modules: one lookup for app, Bokeh and Reflex modules in every deployment."""

from pathlib import Path

import pytest

from helao.helpers import server_modules as sm


def _touch(root: Path, rel: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("", encoding="utf-8")
    return p


@pytest.fixture
def root(tmp_path):
    _touch(tmp_path, "alpha/servers/action/old_server.py")  # old layout
    _touch(tmp_path, "alpha/servers/gamry/gamry_server2.py")  # new layout
    _touch(tmp_path, "alpha/servers/gamry/bokeh/gamry_vis.py")
    _touch(tmp_path, "alpha/servers/gamry/reflex/gamry_vis.py")
    _touch(tmp_path, "alpha/servers/visualizer/live_visualizer.py")
    _touch(tmp_path, "alpha/servers/reflex/temp_vis.py")
    _touch(tmp_path, "alpha/servers/visualizer/temp_vis.py")
    _touch(tmp_path, "beta/servers/action/shared.py")
    _touch(tmp_path, "gamma/servers/action/shared.py")
    (tmp_path / "noservers").mkdir()
    return tmp_path


def test_deployments_are_dirs_with_servers(root):
    assert sm.deployments(root) == ["alpha", "beta", "gamma"]


@pytest.mark.parametrize(
    "module, stack, rel",
    [
        ("old_server", "app", "alpha/servers/action/old_server.py"),
        ("gamry_server2", "app", "alpha/servers/gamry/gamry_server2.py"),
        ("live_visualizer", "app", "alpha/servers/visualizer/live_visualizer.py"),
        ("gamry_vis", "bokeh", "alpha/servers/gamry/bokeh/gamry_vis.py"),
        ("gamry_vis", "reflex", "alpha/servers/gamry/reflex/gamry_vis.py"),
        ("temp_vis", "bokeh", "alpha/servers/visualizer/temp_vis.py"),
        ("temp_vis", "reflex", "alpha/servers/reflex/temp_vis.py"),
    ],
)
def test_each_stack_finds_its_own_file(root, module, stack, rel):
    assert sm.module_file("alpha", module, stack, root) == root / rel


def test_app_stack_never_returns_a_reflex_panel(root):
    # servers/reflex/temp_vis.py is servers/*/temp_vis.py, but it is a panel
    assert sm.module_file("alpha", "temp_vis", "app", root) == (
        root / "alpha/servers/visualizer/temp_vis.py"
    )


def test_twins_in_one_deployment_are_an_error(root):
    _touch(root, "alpha/servers/other/gamry_server2.py")
    with pytest.raises(sm.AmbiguousModule, match="gamry_server2"):
        sm.module_file("alpha", "gamry_server2", "app", root)


def test_missing_module_is_none(root):
    assert sm.module_file("alpha", "nope", "app", root) is None


def test_unknown_stack_raises(root):
    with pytest.raises(ValueError):
        sm.module_file("alpha", "x", "wrong", root)


def test_locate_prefers_own_then_unique(root):
    assert sm.locate("shared", "app", own="gamma", deploy_root=root) == (
        "gamma",
        ["beta", "gamma"],
    )
    assert sm.locate("old_server", "app", own="beta", deploy_root=root) == (
        "alpha",
        ["alpha"],
    )


def test_locate_reports_ambiguity_without_choosing(root):
    assert sm.locate("shared", "app", own="alpha", deploy_root=root) == (
        None,
        ["beta", "gamma"],
    )


def test_import_path_is_dotted_from_helao(root):
    f = root / "alpha/servers/gamry/bokeh/gamry_vis.py"
    assert sm.import_path(f, root) == "helao.deploy.alpha.servers.gamry.bokeh.gamry_vis"


def test_real_deploy_root_holds_hte_and_test():
    assert {"hte", "test"} <= set(sm.deployments())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q -p no:cacheprovider helao/core/tests/test_server_modules.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'helao.helpers.server_modules'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Find server, visualizer and panel modules inside deployments.

One lookup for every caller: launchers, preflight, panel discovery, the freezer
and env setup. A deployment is a directory under ``helao/deploy/`` with a
``servers/`` folder. A module lives in one of three stacks, by location:

- ``app``: a ``fast:``/``bokeh:`` module at ``servers/*/<m>.py``, never
  ``servers/reflex/``.
- ``bokeh``: a Bokeh visualizer at ``servers/visualizer/<m>.py`` or
  ``servers/*/bokeh/<m>.py``.
- ``reflex``: a Reflex panel at ``servers/reflex/<m>.py`` or
  ``servers/*/reflex/<m>.py``.

A Bokeh visualizer and a Reflex panel may share a name on purpose: one config
key (``action_vis: gamry_vis``) loads whichever stack the group runs.
"""

from __future__ import annotations

__all__ = [
    "DEPLOY_ROOT",
    "STACKS",
    "AmbiguousModule",
    "deployments",
    "module_file",
    "locate",
    "import_path",
]

from pathlib import Path

import helao

DEPLOY_ROOT = Path(helao.__file__).resolve().parent / "deploy"
STACKS = ("app", "bokeh", "reflex")


class AmbiguousModule(LookupError):
    """One deployment holds two files answering to the same module name."""


def _candidates(servers: Path, module: str, stack: str) -> list[Path]:
    name = f"{module}.py"
    if stack == "app":
        return [p for p in servers.glob(f"*/{name}") if p.parent.name != "reflex"]
    if stack == "bokeh":
        return [servers / "visualizer" / name, *servers.glob(f"*/bokeh/{name}")]
    if stack == "reflex":
        return [servers / "reflex" / name, *servers.glob(f"*/reflex/{name}")]
    raise ValueError(f"unknown stack {stack!r}; expected one of {STACKS}")


def deployments(deploy_root: Path = DEPLOY_ROOT) -> list[str]:
    """Names of the deployments under ``deploy_root`` that have ``servers/``."""
    if not deploy_root.is_dir():
        return []
    return sorted(d.name for d in deploy_root.iterdir() if (d / "servers").is_dir())


def module_file(
    deployment: str, module: str, stack: str, deploy_root: Path = DEPLOY_ROOT
) -> Path | None:
    """The one file in ``deployment`` for ``module`` in ``stack``, or ``None``.

    Raises:
        AmbiguousModule: two files in the deployment answer to the name.
    """
    servers = deploy_root / deployment / "servers"
    files = sorted({p for p in _candidates(servers, module, stack) if p.is_file()})
    if len(files) > 1:
        raise AmbiguousModule(
            f"deployment {deployment!r} has {len(files)} {stack} modules named "
            f"{module!r}: " + ", ".join(str(p) for p in files)
        )
    return files[0] if files else None


def locate(
    module: str, stack: str, own: str | None = None, deploy_root: Path = DEPLOY_ROOT
) -> tuple[str | None, list[str]]:
    """Deployment to load ``module`` from, and every deployment that has it.

    ``own`` wins when it has the module; otherwise the only deployment that has
    it. Returns ``(None, candidates)`` when none or several (none ``own``) do;
    the caller decides whether that is an error.
    """
    found = [
        d for d in deployments(deploy_root) if module_file(d, module, stack, deploy_root)
    ]
    if own in found:
        return own, found
    if len(found) == 1:
        return found[0], found
    return None, found


def import_path(path: Path, deploy_root: Path = DEPLOY_ROOT) -> str:
    """Dotted import path of a module file under ``deploy_root``."""
    rel = path.resolve().relative_to(deploy_root.resolve()).with_suffix("")
    return ".".join(("helao", "deploy", *rel.parts))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q -p no:cacheprovider helao/core/tests/test_server_modules.py`
Expected: PASS (all tests)

- [ ] **Step 5: Mutation check**

Temporarily change `_candidates`'s app branch to drop the `p.parent.name != "reflex"` filter. Confirm that `test_app_stack_never_returns_a_reflex_panel` fails, then restore the filter.

- [ ] **Step 6: Commit** (main session)

```bash
black helao/helpers/server_modules.py helao/core/tests/test_server_modules.py
git -C . add helao/helpers/server_modules.py helao/core/tests/test_server_modules.py
git -C . commit -m "feat(helpers): server_modules resolver for app, Bokeh and Reflex modules"
```

### Task 2: Collision report (gate before semantics change)

**Files:**
- Create: `harness/deploy_collisions.py`
- Test: `harness/tests/test_deploy_collisions.py`

**Interfaces:**
- Consumes: `server_modules.deployments`
- Produces: `collisions(deploy_root: Path) -> dict[str, dict[str, list[str]]]`, mapping kind (`processors`, `experiments`, `sequences`, `bokeh`, `reflex`) to `{name: [deployments]}` for names found in 2+ deployments. CLI: `python -m harness.deploy_collisions`.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from harness.deploy_collisions import collisions


def _touch(root: Path, rel: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("", encoding="utf-8")


def test_reports_only_names_in_two_or_more_deployments(tmp_path):
    for dep in ("a", "b"):
        _touch(tmp_path, f"{dep}/servers/action/x.py")
    _touch(tmp_path, "a/processors/p1.py")
    _touch(tmp_path, "b/processors/p1.py")
    _touch(tmp_path, "a/experiments/E_exp.py")
    _touch(tmp_path, "a/servers/visualizer/v.py")
    _touch(tmp_path, "b/servers/gamry/bokeh/v.py")
    _touch(tmp_path, "b/servers/reflex/only_b.py")
    out = collisions(tmp_path)
    assert out["processors"] == {"p1": ["a", "b"]}
    assert out["bokeh"] == {"v": ["a", "b"]}
    assert out["experiments"] == {}
    assert out["reflex"] == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q -p no:cacheprovider harness/tests/test_deploy_collisions.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'harness.deploy_collisions'`

- [ ] **Step 3: Write minimal implementation**

```python
"""List module names found in more than one deployment.

Run before the resolver stops preferring one deployment by name: a collision a
config relies on must be settled first (an explicit ``deployment:`` key, an
explicit library path, or a rename).

    python -m harness.deploy_collisions
"""

from __future__ import annotations

import sys
from pathlib import Path

from helao.helpers.server_modules import DEPLOY_ROOT, deployments

_GLOBS = {
    "processors": ("processors/*.py",),
    "experiments": ("experiments/*.py",),
    "sequences": ("sequences/*.py",),
    "bokeh": ("servers/visualizer/*.py", "servers/*/bokeh/*.py"),
    "reflex": ("servers/reflex/*.py", "servers/*/reflex/*.py"),
}


def collisions(deploy_root: Path = DEPLOY_ROOT) -> dict[str, dict[str, list[str]]]:
    out: dict[str, dict[str, list[str]]] = {}
    for kind, patterns in _GLOBS.items():
        seen: dict[str, set[str]] = {}
        for dep in deployments(deploy_root):
            for pattern in patterns:
                for p in (deploy_root / dep).glob(pattern):
                    if not p.name.startswith("_"):
                        seen.setdefault(p.stem, set()).add(dep)
        out[kind] = {n: sorted(d) for n, d in sorted(seen.items()) if len(d) > 1}
    return out


def main() -> int:
    found = collisions()
    for kind, names in found.items():
        for name, deps in names.items():
            print(f"{kind}: {name} in {deps}")
    return 1 if any(found.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q -p no:cacheprovider harness/tests/test_deploy_collisions.py`
Expected: PASS

- [ ] **Step 5: Run the report on this machine (all private deployments present)**

Run: `python -m harness.deploy_collisions`
Expected: prints every collision, exit 1 if any.
For each hit, check whether any config's resolution depends on it: `rg -n "<name>" helao/deploy/*/configs`. If a config relies on a colliding name and the config's own deployment does not hold it, **STOP and report the list to the main session.** Today the `hte` preference decides those cases; Tasks 4–5 would turn them into errors. Do not change any private deployment from this plan.

- [ ] **Step 6: Commit** (main session)

```bash
black harness/deploy_collisions.py harness/tests/test_deploy_collisions.py
git -C . add harness/deploy_collisions.py harness/tests/test_deploy_collisions.py
git -C . commit -m "feat(harness): list module names shared by several deployments"
```

### Task 3: Launchers, preflight and freezer use the resolver

**Files:**
- Modify: `helao/helpers/launcher_bootstrap.py:65-123` (`resolve_app_deployment`)
- Modify: `fast_launcher.py:103-105`
- Modify: `bokeh_launcher.py:114-116`
- Modify: `helao/hexagon/preflight.py:252-331` (`_launcher_deployment`, explicit-key branch of `_module_resolution`)
- Modify: `harness/freeze.py:486-488`
- Test: `helao/core/tests/test_resolve_app_deployment.py` (create); existing `helao/hexagon/tests/test_preflight.py`, `harness/tests/test_freeze.py`

**Interfaces:**
- Consumes: `server_modules.locate`, `module_file`, `import_path`
- Produces: `launcher_bootstrap.resolve_app_deployment(server_config, module, config_path, logger) -> str` (same signature); `launcher_bootstrap.app_module_path(deployment: str, module: str) -> str`

- [ ] **Step 1: Write the failing test**

```python
"""resolve_app_deployment: launcher semantics kept, any servers/* folder accepted."""

import logging
from pathlib import Path

import pytest

from helao.helpers import launcher_bootstrap as lb


def _touch(root: Path, rel: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("", encoding="utf-8")
    return p


LOG = logging.getLogger("t")


def test_new_layout_module_is_found(tmp_path):
    _touch(tmp_path, "alpha/servers/gamry/gamry_server2.py")
    cfg = _touch(tmp_path, "alpha/configs/c.yml")
    entry = {"group": "action", "fast": "gamry_server2"}
    assert lb.resolve_app_deployment(entry, "gamry_server2", str(cfg), LOG) == "alpha"


def test_explicit_key_is_returned_unchecked(tmp_path):
    cfg = _touch(tmp_path, "alpha/configs/c.yml")
    entry = {"group": "action", "fast": "x", "deployment": "beta"}
    assert lb.resolve_app_deployment(entry, "x", str(cfg), LOG) == "beta"


def test_ambiguous_foreign_module_warns_and_takes_first(tmp_path, caplog):
    _touch(tmp_path, "beta/servers/action/x.py")
    _touch(tmp_path, "gamma/servers/action/x.py")
    _touch(tmp_path, "alpha/servers/action/other.py")
    cfg = _touch(tmp_path, "alpha/configs/c.yml")
    with caplog.at_level(logging.WARNING):
        dep = lb.resolve_app_deployment({"group": "action"}, "x", str(cfg), LOG)
    assert dep == "beta"
    assert "deployment:" in caplog.text


def test_unknown_module_raises(tmp_path):
    _touch(tmp_path, "alpha/servers/action/other.py")
    cfg = _touch(tmp_path, "alpha/configs/c.yml")
    with pytest.raises(FileNotFoundError):
        lb.resolve_app_deployment({"group": "action"}, "nope", str(cfg), LOG)


def test_app_module_path_for_real_hte_server():
    assert lb.app_module_path("hte", "gamry_server2").endswith(".gamry_server2")


def test_app_module_path_missing_raises():
    with pytest.raises(FileNotFoundError, match="no_such_module"):
        lb.app_module_path("hte", "no_such_module")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q -p no:cacheprovider helao/core/tests/test_resolve_app_deployment.py`
Expected: FAIL. `test_new_layout_module_is_found` raises `FileNotFoundError` (old glob is pinned to `servers/action/`), and `app_module_path` does not exist yet.

- [ ] **Step 3: Implement**

Replace `resolve_app_deployment` in `helao/helpers/launcher_bootstrap.py`, and add `app_module_path` below it. Drop the now-unused `from glob import glob` if nothing else uses it.

```python
from pathlib import Path

from helao.helpers import server_modules


def resolve_app_deployment(server_config, module, config_path, logger) -> str:
    """Deployment holding the ``fast:``/``bokeh:`` module for this server.

    An explicit ``deployment:`` key wins unchecked. Otherwise the search root is
    the config's great-grandparent (``helao/deploy`` for an in-tree config) and
    the config's own deployment is preferred; a module in several other
    deployments warns and takes the first in sorted order. Unchanged semantics
    from the ``servers/<group>/`` glob, now over every ``servers/*`` folder.
    """
    if "deployment" in server_config:
        return server_config["deployment"]
    cfg = Path(config_path).resolve()
    own, root = cfg.parents[1].name, cfg.parents[2]
    deployment, found = server_modules.locate(module, "app", own=own, deploy_root=root)
    if deployment is not None:
        if deployment != own:
            logger.info(f"Auto-detected deployment: {deployment}")
        return deployment
    if not found:
        raise FileNotFoundError(f"Could not find deployment for {module}")
    logger.warning(
        f"{module} exists in {found}, none of them this config's own; falling "
        f"back to '{found[0]}'. Set an explicit 'deployment:' key on the server."
    )
    return found[0]


def app_module_path(deployment: str, module: str) -> str:
    """Dotted import path of ``module`` (app stack) inside ``deployment``."""
    path = server_modules.module_file(deployment, module, "app")
    if path is None:
        raise FileNotFoundError(
            f"deployment {deployment!r} has no module {module!r} under servers/"
        )
    return server_modules.import_path(path)
```

`fast_launcher.py:103-105`:

```python
    makeApp = import_module(
        app_module_path(deployment, server_config["fast"])
    ).makeApp
```

`bokeh_launcher.py:114-116`:

```python
    makeApp = import_module(
        app_module_path(app_deployment, server_config["bokeh"])
    ).makeBokehApp
```

Add `app_module_path` to each launcher's existing `from helao.helpers.launcher_bootstrap import ...` line.

`helao/hexagon/preflight.py` `_launcher_deployment` (signature kept, `group` now unused):

```python
def _launcher_deployment(config_path: str, group: str, module: str):
    """The launcher's auto-detection (``resolve_app_deployment``), shared code.

    Returns ``(deployment or None, candidate deployments)``. ``None`` with
    candidates means ambiguous. The search root is the config's great-grandparent,
    as in the launcher, so a smoke config outside helao/deploy needs deployment:.
    """
    cfg = Path(config_path).resolve()
    return server_modules.locate(
        module, "app", own=cfg.parents[1].name, deploy_root=cfg.parents[2]
    )
```

In `_module_resolution`, replace the explicit-key check:

```python
            if server_modules.module_file(explicit, module, "app", deploy_root):
                resolved[key] = explicit
            else:
                issues.append(
                    f"{key}: deployment: {explicit} has no {module}.py under servers/"
                )
            continue
```

In the two later messages, replace `{group}/{module}.py` with `{module}.py`. Import `from helao.helpers import server_modules` at the top of preflight.

`harness/freeze.py:486-488`:

```python
        src = server_modules.module_file(
            deployment, Path(module).stem, "app", REPO_ROOT / "helao" / "deploy"
        )
        if src is None:
            raise FileNotFoundError(f"{deployment}: no {module} under servers/")
```

- [ ] **Step 4: Run tests**

```
python -m pytest -q -p no:cacheprovider helao/core/tests/test_resolve_app_deployment.py
python -m pytest -q -p no:cacheprovider helao/hexagon/tests/test_preflight.py
python -m pytest -q -p no:cacheprovider harness/tests/test_freeze.py
```

Expected: PASS. A `test_preflight.py` assertion that matches the old `servers/<group>/<module>.py` message text is the only allowed test edit: update its expected substring to the new `has no <module>.py under servers/` wording. Any other preflight failure means the semantics changed. Stop and report.

- [ ] **Step 5: Launch smoke**

Run `python launch.py goldenreflex --no-hot-reload` in the background with a marker file (see the global background-watcher rule). Wait for every server's ready line, then send CTRL-x (or SIGTERM to the launcher PID). Expected: every server starts and the log shows no `FileNotFoundError` or `ModuleNotFoundError`. Repeat with one `test`-deployment config (`ls helao/deploy/test/configs`).

- [ ] **Step 6: Commit** (main session)

```bash
black helao/helpers/launcher_bootstrap.py fast_launcher.py bokeh_launcher.py helao/hexagon/preflight.py harness/freeze.py helao/core/tests/test_resolve_app_deployment.py
git -C . add -u && git -C . add helao/core/tests/test_resolve_app_deployment.py
git -C . commit -m "refactor(launch): resolve fast/bokeh modules through server_modules"
```

### Task 4: Panel and visualizer discovery use the resolver

**Files:**
- Modify: `helao/ui/shared/discovery.py:40-104` (`deployment_search_order`, `resolve_panel_module`)
- Modify: `helao/ui/bokeh/vis_subscriber.py:61-106` (`import_vis_class`)
- Test: `helao/core/tests/test_reflex_config.py` (existing; update the search-order expectations), `helao/core/tests/test_panel_discovery_stacks.py` (create)

**Interfaces:**
- Consumes: `server_modules.locate`, `module_file`, `import_path`
- Produces: `discovery.deployment_search_order() -> list[str]`, now `[configured, *other deployments sorted]` with no `hte` entry; `discovery.resolve_panel_module(name)` (same signature, still raises `ModuleNotFoundError`); `vis_subscriber.import_vis_class(name, class_name)` (same signature)

- [ ] **Step 1: Write the failing test**

```python
"""Panels and visualizers resolve from instrument bokeh/ and reflex/ subfolders."""

import pytest

from helao.helpers import config_loader
from helao.ui.bokeh import vis_subscriber
from helao.ui.shared import discovery


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    discovery.resolve_panel_module.cache_clear()
    vis_subscriber.import_vis_class.cache_clear()
    monkeypatch.setattr(config_loader, "CONFIG", {"deployment": "hte"})
    yield
    discovery.resolve_panel_module.cache_clear()
    vis_subscriber.import_vis_class.cache_clear()


def test_search_order_has_no_hardcoded_second_entry(monkeypatch):
    monkeypatch.setattr(config_loader, "CONFIG", {"deployment": "test"})
    order = discovery.deployment_search_order()
    assert order[0] == "test"
    assert order[1:] == sorted(order[1:])


def test_unknown_panel_still_raises_module_not_found():
    with pytest.raises(ModuleNotFoundError, match="no_such_panel"):
        discovery.resolve_panel_module("no_such_panel")


def test_unknown_visualizer_still_raises_module_not_found():
    with pytest.raises(ModuleNotFoundError, match="no_such_vis"):
        vis_subscriber.import_vis_class("no_such_vis")


def test_existing_hte_twin_resolves_per_stack():
    panel = discovery.resolve_panel_module("gamry_vis")
    assert ".reflex." in panel.__name__
    cls = vis_subscriber.import_vis_class("gamry_vis")
    assert ".reflex." not in cls.__module__
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q -p no:cacheprovider helao/core/tests/test_panel_discovery_stacks.py`
Expected: FAIL on `test_search_order_has_no_hardcoded_second_entry`. Today's order is `["test", "hte", <the rest>]`, and on this machine at least one private deployment sorts before `hte`, so the tail is not sorted. On a checkout holding only `hte` and `test` the assertion passes vacuously; Step 5's `tmp_path` case covers that.

- [ ] **Step 3: Implement**

`helao/ui/shared/discovery.py`:

```python
def deployment_search_order() -> list:
    """Configured deployment first, then every other deployment, sorted."""
    current = (config_loader.CONFIG or {}).get("deployment")
    others = [
        d for d in server_modules.deployments(Path(_deploy_root())) if d != current
    ]
    return ([current] if current else []) + others


def _resolve(module_name: str, stack: str):
    root = Path(_deploy_root())
    own = (config_loader.CONFIG or {}).get("deployment")
    deployment, found = server_modules.locate(module_name, stack, own=own, deploy_root=root)
    if deployment is None:
        where = f"several deployments {found}" if found else "no deployment"
        raise ModuleNotFoundError(
            f"could not locate {stack} module '{module_name}': found in {where}; "
            f"the config's own deployment is {own!r}"
        )
    path = server_modules.module_file(deployment, module_name, stack, root)
    return import_module(server_modules.import_path(path, root))


@lru_cache(maxsize=None)
def resolve_panel_module(module_name: str):
    """Import the Reflex panel module ``module_name`` (see ``server_modules``)."""
    return _resolve(module_name, "reflex")
```

Remove the now-unused `importlib_util` import if nothing else uses it, and add `from pathlib import Path` and `from helao.helpers import server_modules`. Keep `PANEL_SUBPACKAGE` in `__all__` (other modules import it).

`helao/ui/bokeh/vis_subscriber.py` `import_vis_class`:

```python
@lru_cache(maxsize=None)
def import_vis_class(module_name: str, class_name: str = VIS_CLASS_NAME):
    """Import ``class_name`` from the Bokeh visualizer module ``module_name``."""
    from helao.ui.shared.discovery import _resolve

    return getattr(_resolve(module_name, "bokeh"), class_name)
```

- [ ] **Step 4: Run tests**

```
python -m pytest -q -p no:cacheprovider helao/core/tests/test_panel_discovery_stacks.py
python run_tests.py --filter reflex
python run_tests.py --filter vis
python run_tests.py --filter motion_control
```

Expected: PASS. In `test_reflex_config.py`, only assertions that expect `hte` as the forced second entry may be updated, to the sorted-order rule above.

- [ ] **Step 5: Mutation check**

Temporarily re-insert `if "hte" not in order: order.append("hte")` logic into `deployment_search_order`. Confirm that a test fails. If none fails because only `hte`/`test` exist, add a `tmp_path` deploy-root case: monkeypatch `discovery._deploy_root` to a tree with `aaa`, `hte` and `zzz`, and assert the order is `[configured, "aaa", "hte", "zzz"]` minus the configured one. Restore.

- [ ] **Step 6: Commit** (main session)

```bash
black helao/ui/shared/discovery.py helao/ui/bokeh/vis_subscriber.py helao/core/tests/test_panel_discovery_stacks.py helao/core/tests/test_reflex_config.py
git -C . add -u && git -C . add helao/core/tests/test_panel_discovery_stacks.py
git -C . commit -m "refactor(ui): panels and visualizers resolve through server_modules"
```

### Task 5: Processors, libraries, analyses and preflight lose the `hte` fallback

**Files:**
- Modify: `helao/core/hooks/loader.py:74-92` (`_resolve_path`) and its docstring at lines 8-10
- Modify: `helao/helpers/import_autolibs.py:175-201` and the comment at about line 237
- Modify: `helao/core/drivers/data/analysis_driver.py:140-205`
- Modify: `helao/hexagon/preflight.py:55-56,70-86,397-399` (`HTE_EXP`, `HTE_SEQ`, smoke-config owner)
- Test: `helao/core/tests/test_deploy_fallbacks.py` (create); existing `test_hooks_loader.py`, `test_import_autolibs.py`, `test_analysis_resolution.py`, `test_preflight.py`

**Interfaces:**
- Consumes: `server_modules.DEPLOY_ROOT`, `deployments`
- Produces:
  - `hooks.loader._resolve_path(name) -> str | None`: own deployment, then the only other deployment with it; several raise `HookConfigError`. Paths are anchored on `DEPLOY_ROOT`, not the cwd.
  - `import_autolibs` per-entry fallback: the only deployment with `<lib_type>s/<file>.py`; several raise `FileNotFoundError` listing them.
  - `analysis_driver.ANALYSES_SUBPKGS = ("servers.analysis.analyses", "drivers.data.analyses")`, tried in order per candidate deployment.

- [ ] **Step 1: Write the failing test**

```python
"""No deployment is preferred by name; a shared name is an error, not a pick."""

import os
from pathlib import Path

import pytest

from helao.core.drivers.data import analysis_driver
from helao.core.hooks import loader
from helao.helpers import config_loader, server_modules


def _touch(root: Path, rel: str, text: str = "") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


@pytest.fixture
def tree(tmp_path, monkeypatch):
    for dep in ("a", "b", "c"):
        _touch(tmp_path, f"{dep}/servers/action/x.py")
    _touch(tmp_path, "a/processors/mine.py")
    _touch(tmp_path, "b/processors/shared.py")
    _touch(tmp_path, "c/processors/shared.py")
    _touch(tmp_path, "b/processors/only_b.py")
    monkeypatch.setattr(server_modules, "DEPLOY_ROOT", tmp_path)
    monkeypatch.setattr(loader, "DEPLOY_ROOT", tmp_path, raising=False)
    monkeypatch.setattr(config_loader, "CONFIG", {"deployment": "a"})
    monkeypatch.chdir(tmp_path.parent)  # cwd must not matter
    return tmp_path


def test_own_processor(tree):
    assert loader._resolve_path("mine") == str(tree / "a/processors/mine.py")


def test_unique_foreign_processor(tree):
    assert loader._resolve_path("only_b") == str(tree / "b/processors/only_b.py")


def test_shared_foreign_processor_is_an_error(tree):
    with pytest.raises(loader.HookConfigError, match="shared"):
        loader._resolve_path("shared")


def test_analyses_new_location_preferred():
    assert analysis_driver.ANALYSES_SUBPKGS[0] == "servers.analysis.analyses"
    assert "drivers.data.analyses" in analysis_driver.ANALYSES_SUBPKGS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q -p no:cacheprovider helao/core/tests/test_deploy_fallbacks.py`
Expected: FAIL. `test_shared_foreign_processor_is_an_error` currently returns the first glob hit, and `ANALYSES_SUBPKGS` does not exist.

- [ ] **Step 3: Implement**

`helao/core/hooks/loader.py`:

```python
from helao.helpers import server_modules


def _resolve_path(name: str) -> Optional[str]:
    """A processor path: explicit ``.py``, own deployment, else the only other one.

    Anchored on ``helao/deploy`` (not the cwd). A name held by several
    deployments, none of them the config's own, is a ``HookConfigError``.
    """
    if name.endswith(".py") and os.path.exists(name):
        return name
    root = server_modules.DEPLOY_ROOT
    own = (config_loader.CONFIG or {}).get("deployment", "")
    if own and (root / own / "processors" / f"{name}.py").is_file():
        return str(root / own / "processors" / f"{name}.py")
    found = sorted(root.glob(f"*/processors/{name}.py"))
    if len(found) > 1:
        raise HookConfigError(
            f"processor {name!r} exists in several deployments "
            f"{[p.parent.parent.name for p in found]}; none is this config's own"
        )
    return str(found[0]) if found else None
```

Update the module docstring (lines 8-10) to describe this order with no deployment named. Remove `from glob import glob` if unused.

`helao/helpers/import_autolibs.py`: replace lines 175-201 (the `hte` attempt plus the unsorted glob) with:

```python
            if not os.path.isfile(lib_path):
                lib_paths = sorted(
                    glob(
                        repo_path(
                            os.path.join(
                                "helao", "deploy", "*", f"{lib_type}s", f"{lib_file}.py"
                            )
                        )
                    )
                )
                if len(lib_paths) == 1:
                    lib_path = lib_paths[0]
                    LOGGER.warning(
                        f"{lib_type} library {lib_file} not in {lib_dir}; using {lib_path}"
                    )
                elif lib_paths:
                    raise FileNotFoundError(
                        f"{lib_type} library {lib_file}.py is not in {lib_dir} and "
                        f"exists in several deployments: {lib_paths}. Give the entry "
                        f"as an explicit .py path in the config."
                    )
                else:
                    raise FileNotFoundError(
                        f"{lib_type} library path {lib_path} does not exist, and no "
                        f"deployment has {lib_file}.py in its {lib_type}s folder."
                    )
```

Rewrite the comment at about line 237 to say "falls back per entry to the only deployment that has it".

`helao/core/drivers/data/analysis_driver.py`:

```python
ANALYSES_SUBPKGS = ("servers.analysis.analyses", "drivers.data.analyses")
"""Where a deployment keeps its analyses, newest layout first."""


def _analyses_packages(deployment: str) -> list[str]:
    return [f"helao.deploy.{deployment}.{sub}" for sub in ANALYSES_SUBPKGS]
```

In `resolve_analyses_package`, loop `for package in _analyses_packages(candidate)` inside the candidate loop. The final fallback returns `_analyses_packages(deployment)[0]`. Delete `_ANALYSES_SUBPKG` and `_analyses_package`, and update any other reference (`rg -n "_analyses_package\b|_ANALYSES_SUBPKG" helao`).

`helao/hexagon/preflight.py`:
- Delete `HTE_EXP`/`HTE_SEQ`. In `_library_collisions`, take `default_dir` from the config's own deployment: `REPO_ROOT / "helao" / "deploy" / <owner> / "experiments"` (and `sequences`).
- Replace the `if m.parent == HTE_SMOKE_CONFIGS: return "hte"` owner rule with a generic one: a config under `helao/deploy/<dep>/` (at any depth) belongs to `<dep>`. Delete `HTE_SMOKE_CONFIGS` once nothing references it. Smoke configs move under `helao/deploy/hte/tests/smoke/configs/` in Task 7, where this rule finds `hte` with no literal.

- [ ] **Step 4: Run tests**

```
python -m pytest -q -p no:cacheprovider helao/core/tests/test_deploy_fallbacks.py
python run_tests.py --filter hooks_loader
python run_tests.py --filter import_autolibs
python run_tests.py --filter analysis_resolution
python run_tests.py --filter preflight
```

Expected: PASS. `test_hte_processors_resolve_by_bare_name` keeps passing (`hte` processors are unique). An `import_autolibs` test that expected the `hte` preference over another deployment may only be changed to expect the "several deployments" error if Task 2 showed no config relies on it.

- [ ] **Step 5: Sweep parity for P1**

Run the full `run_tests.py` sweep in the background with a marker file. Compare its failing set to the P1 baseline. Expected: no new failures.

- [ ] **Step 6: Commit** (main session)

```bash
black helao/core/hooks/loader.py helao/helpers/import_autolibs.py helao/core/drivers/data/analysis_driver.py helao/hexagon/preflight.py helao/core/tests/test_deploy_fallbacks.py
git -C . add -u && git -C . add helao/core/tests/test_deploy_fallbacks.py
git -C . commit -m "refactor: drop the hte fallback from processor, library and analyses lookup"
```

---

## Phase P2: reorganize `hte` into instrument folders

### Task 6: `reorg_deploy` move-and-rewrite tool

**Files:**
- Create: `harness/reorg_deploy.py`
- Test: `harness/tests/test_reorg_deploy.py`

**Interfaces:**
- Produces: CLI `python -m harness.reorg_deploy <mapping.json> [--dry-run]`. It returns 0 on success and prints the leftover report. Functions:
  - `load_mapping(path) -> list[tuple[Path, Path]]`
  - `expand(moves, repo_root) -> dict[Path, Path]` (file → file)
  - `module_name(path: Path) -> str` (path relative to the repo root)
  - `rewrite_source(text, own_old: str, own_new: str, is_package: bool, modmap: dict[str, str]) -> str`
  - `apply(mapping_path, repo_root, dry_run) -> Report`
  - `leftovers(repo_root, scan_roots, old_prefixes) -> list[str]`
- Mapping JSON: `{"scan": ["helao", "harness", "*.py"], "moves": [["src", "dst"], ...]}`. Paths are relative to the repo root. A `src` that is a directory moves its whole tree, skipping `__pycache__`, `.omc` and `.ruff_cache`. New package dirs get an empty `__init__.py`. Scanning skips any directory that holds its own `.git` (a nested private repo).

- [ ] **Step 1: Write the failing test**

```python
"""reorg_deploy: git mv per a mapping, then rewrite every import to the new path."""

import json
import subprocess
import sys
from pathlib import Path

from harness import reorg_deploy as rd


def _w(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    _w(r, "helao/__init__.py", "")
    _w(r, "helao/deploy/__init__.py", "")
    _w(r, "helao/deploy/d/__init__.py", "")
    _w(r, "helao/deploy/d/servers/__init__.py", "")
    _w(r, "helao/deploy/d/servers/action/__init__.py", "")
    _w(r, "helao/deploy/d/drivers/__init__.py", "")
    _w(r, "helao/deploy/d/drivers/pump/__init__.py", "")
    _w(r, "helao/deploy/d/drivers/pump/enum.py", "SPEED = 3\n")
    _w(
        r,
        "helao/deploy/d/drivers/pump/driver.py",
        "from .enum import SPEED\nfrom helao.deploy.d.drivers.pump import enum as E\n",
    )
    _w(
        r,
        "helao/deploy/d/servers/action/pump_server.py",
        "from ...drivers.pump.driver import SPEED\n"
        "from ...drivers.pump import enum\n"
        "def f():\n    import helao.deploy.d.drivers.pump.driver as drv\n    return drv\n",
    )
    _w(
        r,
        "helao/other/user.py",
        "from helao.deploy.d.drivers.pump.enum import SPEED\n"
        "MOD = 'helao.deploy.d.drivers.pump.driver'\n",
    )
    _w(r, "helao/other/__init__.py", "")
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(r), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "init"],
        check=True,
    )
    _w(
        r,
        "map.json",
        json.dumps(
            {
                "scan": ["helao"],
                "moves": [
                    ["helao/deploy/d/drivers/pump", "helao/deploy/d/servers/pump"],
                    ["helao/deploy/d/servers/action/pump_server.py",
                     "helao/deploy/d/servers/pump/pump_server.py"],
                ],
            }
        ),
    )
    return r


def test_moves_rewrites_and_imports(tmp_path):
    r = _repo(tmp_path)
    report = rd.apply(r / "map.json", r, dry_run=False)
    srv = (r / "helao/deploy/d/servers/pump/pump_server.py").read_text(encoding="utf-8")
    assert "from helao.deploy.d.servers.pump.driver import SPEED" in srv
    assert "from helao.deploy.d.servers.pump import enum" in srv
    assert "import helao.deploy.d.servers.pump.driver as drv" in srv
    drv = (r / "helao/deploy/d/servers/pump/driver.py").read_text(encoding="utf-8")
    assert "from .enum import SPEED" in drv  # moved together: relative kept
    assert "from helao.deploy.d.servers.pump import enum as E" in drv
    user = (r / "helao/other/user.py").read_text(encoding="utf-8")
    assert "from helao.deploy.d.servers.pump.enum import SPEED" in user
    assert not (r / "helao/deploy/d/drivers/pump").exists()
    # the string literal is reported, not rewritten
    assert any("helao/other/user.py" in line for line in report.leftovers)
    out = subprocess.run(
        [sys.executable, "-c", "import helao.deploy.d.servers.pump.pump_server as m; print(m.SPEED)"],
        cwd=r, capture_output=True, text=True, env={"PYTHONPATH": str(r)},
    )
    assert out.stdout.strip() == "3", out.stderr


def test_dry_run_changes_nothing(tmp_path):
    r = _repo(tmp_path)
    rd.apply(r / "map.json", r, dry_run=True)
    assert (r / "helao/deploy/d/drivers/pump/driver.py").exists()


def test_nested_git_repo_is_not_scanned(tmp_path):
    r = _repo(tmp_path)
    _w(r, "helao/deploy/nested/x.py", "from helao.deploy.d.drivers.pump.enum import SPEED\n")
    (r / "helao/deploy/nested/.git").mkdir()
    rd.apply(r / "map.json", r, dry_run=False)
    text = (r / "helao/deploy/nested/x.py").read_text(encoding="utf-8")
    assert "drivers.pump.enum" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q -p no:cacheprovider harness/tests/test_reorg_deploy.py`
Expected: FAIL with `ImportError: cannot import name 'reorg_deploy'`

- [ ] **Step 3: Implement**

```python
"""Move files per a JSON mapping with ``git mv`` and rewrite imports to match.

    python -m harness.reorg_deploy <mapping.json> [--dry-run]

Mapping: ``{"scan": [roots...], "moves": [[src, dst], ...]}``, paths relative to
the repo root. Every ``import``/``from`` statement in scanned ``.py`` files is
resolved against the importing file's OLD module name and rewritten to the
target's NEW absolute path. A relative import between two files that moved
together into the same package is kept as it is. String literals and non-Python
files are never rewritten: they are listed as leftovers for a person to fix.
Directories holding their own ``.git`` (nested private repos) are not scanned;
they run this tool themselves with their own mapping.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

SKIP = {"__pycache__", ".omc", ".ruff_cache", ".git"}


@dataclass
class Report:
    moved: list[tuple[str, str]] = field(default_factory=list)
    rewritten: list[str] = field(default_factory=list)
    leftovers: list[str] = field(default_factory=list)


def load_mapping(path: Path) -> tuple[list[str], list[tuple[Path, Path]]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data.get("scan", ["helao", "harness"]), [
        (Path(s), Path(d)) for s, d in data["moves"]
    ]


def expand(moves, repo_root: Path) -> dict[Path, Path]:
    out: dict[Path, Path] = {}
    for src, dst in moves:
        full = repo_root / src
        if full.is_dir():
            for f in sorted(full.rglob("*")):
                if f.is_file() and not SKIP & set(f.relative_to(full).parts):
                    out[src / f.relative_to(full)] = dst / f.relative_to(full)
        elif full.is_file():
            out[src] = dst
        else:
            raise FileNotFoundError(f"mapping source missing: {src}")
    return out


def module_name(path: Path) -> str:
    parts = list(path.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _modmap(files: dict[Path, Path]) -> dict[str, str]:
    return {
        module_name(s): module_name(d)
        for s, d in files.items()
        if s.suffix == ".py"
    }


def _new(target: str, modmap: dict[str, str]) -> str:
    """Map an old absolute module to its new name, longest prefix first."""
    parts = target.split(".")
    for i in range(len(parts), 0, -1):
        head = ".".join(parts[:i])
        if head in modmap:
            return ".".join([modmap[head], *parts[i:]])
    return target


def _absolute(level: int, module: str | None, own: str, is_package: bool) -> str:
    base = own.split(".")
    if not is_package:
        base = base[:-1]
    base = base[: len(base) - (level - 1)] if level > 1 else base
    return ".".join([*base, *([module] if module else [])])


_FROM = re.compile(r"^(\s*from\s+)(\.*[\w.]*)(\s+import\b)")
_IMPORT = re.compile(r"^(\s*import\s+)([\w.]+)")


def rewrite_source(
    text: str, own_old: str, own_new: str, is_package: bool, modmap: dict[str, str]
) -> str:
    lines = text.splitlines(keepends=True)
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            old_abs = (
                _absolute(node.level, node.module, own_old, is_package)
                if node.level
                else node.module or ""
            )
            # ``from pkg import name`` may name a moved submodule
            if node.level and len(node.names) == 1:
                sub = f"{old_abs}.{node.names[0].name}"
                if sub in modmap and old_abs not in modmap:
                    old_abs_for_check = sub
                else:
                    old_abs_for_check = old_abs
            else:
                old_abs_for_check = old_abs
            new_abs = _new(old_abs, modmap)
            new_own_pkg = own_new if is_package else own_new.rpartition(".")[0]
            if node.level and _new(old_abs_for_check, modmap) == (
                _absolute(node.level, node.module, own_new, is_package)
                if node.module
                else new_own_pkg
            ):
                continue  # moved together: the relative import still resolves
            if new_abs == old_abs and not node.level:
                continue
            i = node.lineno - 1
            lines[i] = _FROM.sub(lambda m: f"{m[1]}{new_abs}{m[3]}", lines[i], count=1)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                new = _new(alias.name, modmap)
                if new != alias.name:
                    i = node.lineno - 1
                    lines[i] = lines[i].replace(alias.name, new, 1)
    return "".join(lines)


def _scan_files(repo_root: Path, roots: list[str]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if any(ch in root for ch in "*?"):
            files += sorted(repo_root.glob(root))
            continue
        base = repo_root / root
        for f in sorted(base.rglob("*.py")):
            rel_parts = f.relative_to(repo_root).parts
            if SKIP & set(rel_parts):
                continue
            if any(
                (repo_root.joinpath(*rel_parts[:k]) / ".git").exists()
                for k in range(2, len(rel_parts))
            ):
                continue
            files.append(f)
    return files


def leftovers(repo_root: Path, roots: list[str], old_prefixes: list[str]) -> list[str]:
    pats = [re.escape(p) for p in old_prefixes] + [
        re.escape(p.replace(".", "/")) for p in old_prefixes
    ]
    rx = re.compile("|".join(pats))
    out = []
    for f in _scan_files(repo_root, roots):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if rx.search(line):
                out.append(f"{f.relative_to(repo_root)}:{n}: {line.strip()}")
    return out


def apply(mapping_path: Path, repo_root: Path, dry_run: bool) -> Report:
    repo_root = Path(repo_root).resolve()
    roots, moves = load_mapping(mapping_path)
    files = expand(moves, repo_root)
    modmap = _modmap(files)
    new_to_old = {d: s for s, d in files.items()}
    report = Report(moved=[(str(s), str(d)) for s, d in files.items()])
    if dry_run:
        for s, d in report.moved:
            print(f"mv {s} -> {d}")
        return report
    for src, dst in files.items():
        (repo_root / dst).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "-C", str(repo_root), "mv", str(src), str(dst)], check=True
        )
    for dst in {d.parent for d in files.values() if d.suffix == ".py"}:
        for pkg in [dst, *dst.parents]:
            if (repo_root / pkg) == repo_root or not str(pkg).startswith("helao"):
                break
            init = repo_root / pkg / "__init__.py"
            if not init.exists():
                init.write_text("", encoding="utf-8")
    for src in {s.parent for s in files}:
        d = repo_root / src
        while d != repo_root and d.exists() and not any(
            p for p in d.rglob("*") if p.is_file() and p.name != "__init__.py"
            and "__pycache__" not in p.parts
        ):
            subprocess.run(["git", "-C", str(repo_root), "rm", "-rq", "--ignore-unmatch", str(d.relative_to(repo_root))], check=True)
            subprocess.run(["rm", "-rf", str(d)], check=True)
            d = d.parent
    for f in _scan_files(repo_root, roots):
        rel = f.relative_to(repo_root)
        old_rel = new_to_old.get(rel, rel)
        text = f.read_text(encoding="utf-8")
        new = rewrite_source(
            text, module_name(old_rel), module_name(rel), rel.name == "__init__.py", modmap
        )
        if new != text:
            f.write_text(new, encoding="utf-8")
            report.rewritten.append(str(rel))
    old_prefixes = sorted({k for k in modmap if k not in modmap.values()})
    report.leftovers = leftovers(repo_root, roots, old_prefixes)
    return report


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m harness.reorg_deploy")
    p.add_argument("mapping")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    r = apply(Path(a.mapping), repo_root, a.dry_run)
    print(f"moved {len(r.moved)} files, rewrote {len(r.rewritten)}")
    for line in r.leftovers:
        print(f"LEFTOVER {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

The relative-import "moved together" logic is the subtle part. If any test case fails on it, simplify to: always rewrite a relative import whose resolved old target is in `modmap` to the new absolute path, unless the importing file and the target moved into the same new package directory. Do not add more special cases than the tests demand.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q -p no:cacheprovider harness/tests/test_reorg_deploy.py`
Expected: PASS

- [ ] **Step 5: Mutation check**

Make `_new` return `target` unchanged. Confirm `test_moves_rewrites_and_imports` fails, then restore it.

- [ ] **Step 6: Commit** (main session)

```bash
black harness/reorg_deploy.py harness/tests/test_reorg_deploy.py
git -C . add harness/reorg_deploy.py harness/tests/test_reorg_deploy.py
git -C . commit -m "feat(harness): reorg_deploy moves files and rewrites imports from a mapping"
```

### Task 7: Move `hte` into instrument folders

**Files:**
- Create: `harness/reorg/hte.json`
- Move: everything listed in the mapping
- Create: `helao/deploy/hte/conftest.py` (only if moved tests need fixtures from `helao/hexagon/tests/conftest.py`)
- Modify: every file the leftover report lists; `helao/hexagon/domain/models.py` (PAL section out); `helao/hexagon/adapters/vis/__init__.py` (drop the aligner re-export)

**Interfaces:**
- Consumes: `python -m harness.reorg_deploy`, `server_modules`
- Produces: the `helao/deploy/hte/servers/<instrument>/` layout (table below). Module basenames used by configs are unchanged.

- [ ] **Step 1: Record the P2 baseline**

Run the full `run_tests.py` sweep in the background with a marker file. Save the log to `$CLAUDE_JOB_DIR/tmp/p2_base.log`.

- [ ] **Step 2: Write `harness/reorg/hte.json`**

`"scan": ["helao", "harness", "*.py"]`. Moves, all paths under `helao/deploy/hte/` unless they start with `helao/hexagon`:

| instrument | moves (src → dst) |
|---|---|
| gamry | `servers/action/gamry_server2.py`→`servers/gamry/gamry_server2.py`; `drivers/pstat/gamry`→`servers/gamry`; `servers/visualizer/gamry_vis.py`→`servers/gamry/bokeh/gamry_vis.py`; `servers/reflex/gamry_vis.py`→`servers/gamry/reflex/gamry_vis.py`; `helao/hexagon/adapters/native/gamry_com.py`→`servers/gamry/gamry_com.py` |
| biologic | `servers/action/biologic_server.py`→`servers/biologic/`; `drivers/pstat/biologic`→`servers/biologic/biologic`; `drivers/pstat/biologic_eclib2`→`servers/biologic/biologic_eclib2`; `drivers/pstat/biologic_ole`→`servers/biologic/biologic_ole`; `drivers/pstat/biologic_backend.py`→`servers/biologic/biologic_backend.py`; `drivers/pstat/CLAUDE.md`→`servers/biologic/CLAUDE.md`; `biologic_vis` twins → `servers/biologic/{bokeh,reflex}/` |
| galil_motion | `servers/action/galil_motion.py`; `drivers/motion/enum.py`→`servers/galil_motion/enum.py`; `helao/hexagon/adapters/native/galil_motion_native.py`; `helao/hexagon/adapters/shared/galil_command_channel.py`→`servers/galil_motion/galil_command_channel.py`; `helao/hexagon/ports/galil_command_channel.py`→`servers/galil_motion/galil_command_channel_port.py`; `helao/hexagon/adapters/vis/galil_aligner_host.py`→`servers/galil_motion/galil_aligner_host.py` |
| galil_io | `servers/action/galil_io.py`; `drivers/io/galil_io_driver.py`; `drivers/io/enum.py`→`servers/galil_io/enum.py`; `drivers/io/galil_toggle_main.dmc`, `galil_toggle_main_nostop.dmc`, `galil_toggle_sub.dmc`, `galil_toggle_sub_req.dmc` |
| andor | `servers/action/andor_server.py`; `drivers/spec/andor`→`servers/andor`; `servers/reflex/andor_vis.py`→`servers/andor/reflex/andor_vis.py` |
| spec | `servers/action/spec_server.py`; `drivers/spec/spectral_products_driver.py`; `drivers/spec/enum.py`→`servers/spec/enum.py`; `spec_vis` twins |
| kinesis | `servers/action/kinesis_server.py`; `drivers/motion/kinesis_driver.py` |
| mfc | `servers/action/mfc_server.py`; `drivers/mfc/alicat_driver.py`; `mfc_vis` twins |
| nidaqmx | `servers/action/nidaqmx_server.py`; `drivers/io/nidaqmx_driver.py`; `nidaqmx_vis` and `nidaqmx_control` twins |
| pal | `servers/action/pal_server.py`; `drivers/robot/pal_driver.py`, `enum.py`, `sample_shim.py`, `CLAUDE.md`; `helao/hexagon/adapters/shared/pal_transport.py`→`servers/pal/pal_transport.py`; `helao/hexagon/ports/pal_transport.py`→`servers/pal/pal_transport_port.py`; `helao/hexagon/adapters/shared/pal_trigger.py`→`servers/pal/pal_trigger.py`; `helao/hexagon/ports/pal_trigger.py`→`servers/pal/pal_trigger_port.py`; `helao/hexagon/domain/pal_reconciliation.py`→`servers/pal/pal_reconciliation.py` |
| pdu | `servers/action/pdu_server.py`; `drivers/io/synaccess`→`servers/pdu` |
| power_supply | `servers/action/power_supply_server.py`; `drivers/power_supply/power_supply_driver.py`; `power_supply_vis` twins |
| syringe | `servers/action/syringe_server.py`; `drivers/pump/legato_driver.py` |
| diapump | `servers/action/diapump_server.py`; `drivers/pump/simdos_driver.py` |
| tec | `servers/action/tec_server.py`; `drivers/temperature_control/mecom_driver.py`; `servers/visualizer/tec_vis.py`→`servers/tec/bokeh/tec_vis.py` |
| co2sensor | `servers/action/co2sensor_server.py`; `drivers/sensor/sprintir_driver.py`; `co2_vis` twins |
| o2sensor | `servers/action/o2sensor_server.py`; `drivers/sensor/cm0134_driver.py` |
| cam | `servers/action/cam_server.py`; `drivers/sensor/axiscam_driver.py` |
| xafs | `servers/action/xafs_server.py`; `drivers/xafs`→`servers/xafs` (keeps `sidecar/`) |
| sample | `servers/action/sample_server.py`; `drivers/data/archive_driver.py`; `sample_vis` twins |
| calc | `servers/action/calc_server.py`; `drivers/data/calc_driver.py` |
| analysis | `servers/action/analysis_server.py`; `drivers/data/analyses`→`servers/analysis/analyses` |
| htedata | `servers/action/HTEdata_server.py`; `drivers/data/HTEdata_legacy.py` |
| sync | `servers/action/sync_server.py` |
| (shared) | `drivers/serial_lifecycle.py`→`helao/helpers/serial_lifecycle.py` |

A row entry without a destination moves to `servers/<instrument>/` with its basename. "Twins" means `servers/visualizer/<m>.py`→`servers/<inst>/bokeh/<m>.py` plus `servers/reflex/<m>.py`→`servers/<inst>/reflex/<m>.py`. Do not move the generic files (spec §1 Rules) or `drivers/test_station/`.

- [ ] **Step 3: Dry run, then run**

```
python -m harness.reorg_deploy harness/reorg/hte.json --dry-run | tail -5
python -m harness.reorg_deploy harness/reorg/hte.json | tee $CLAUDE_JOB_DIR/tmp/hte_reorg.log
```

Expected: the summary line, then `LEFTOVER` lines. `helao/deploy/hte/servers/action/` and the emptied `drivers/<category>/` dirs are gone. `drivers/test_station/` remains.

- [ ] **Step 4: Fix every leftover and manual split**

- Each `LEFTOVER` line (f-string imports, path strings, docs). Known ones:
  - `helao/hexagon/tests/hosted_server.py:61`: build the path with `launcher_bootstrap.app_module_path(deployment, module)`. Callers pass the deployment, so the helper holds no `"hte"`.
  - `test_vis_ws_parity.py:114,127`
  - `test_reflex_pstat_stop.py:81,154,355`
  - `test_pstat_vis_axis_selectors.py:75,98`
  - `test_low_w2_visualizers.py:16`
  - `test_ole_technique.py:18` (templates path)
  - `biologicole.yml:32` comment
  - `helao/hexagon/tests/checklists/hte/servers.json` module names (Task 8 moves the directory)
  - the root `CLAUDE.md` driver paths
- `helao/hexagon/domain/models.py:85-250`: move the PAL classes (`_positiontype`, `Spacingmethod`, `_cam`, `PALposition`, `PalAction`, `PalMicroCam`, `PalCam`) into `helao/deploy/hte/servers/pal/models.py`, and point every importer there (`rg -n "domain.models import" helao`). Keep the rest of `domain/models.py`.
- `helao/hexagon/adapters/vis/__init__.py`: remove the `galil_aligner_host` re-export.
- `servers/biologic/CLAUDE.md`: copy the Gamry-specific sections into `servers/gamry/CLAUDE.md`, delete them from the BioLogic copy, and fix the root `CLAUDE.md` links (`drivers/pstat/CLAUDE.md` → `servers/biologic/CLAUDE.md`; `drivers/spec/andor/` → `servers/andor/`).

Done when `python -m harness.reorg_deploy` re-run in report-only form shows no leftover outside docs history. Use this command:
`rg -n "deploy\.hte\.drivers|hte/drivers|servers\.action\.|servers/action/|servers\.visualizer\.(gamry|biologic|spec|mfc|co2|nidaqmx|power_supply|sample|tec)_|hexagon\.adapters\.(native\.(gamry_com|galil_motion_native)|shared\.(galil_command_channel|pal_)|vis\.galil_aligner)|hexagon\.ports\.(galil|pal)|domain\.pal_reconciliation" -g '*.py' -g '*.md' -g '*.json' -g '*.yml' helao harness *.py`. It must print only `drivers/test_station` hits and `docs/` history.

- [ ] **Step 5: Relocate hte tests out of the framework**

List the test files that now import `helao.deploy.hte`:
`rg -l "helao\.deploy\.hte" helao/core/tests helao/hexagon/tests harness/tests`

Move each with `git -C . mv`:
- A file that imports exactly one `servers.<inst>` goes to `helao/deploy/hte/servers/<inst>/tests/`.
- Every other file goes to `helao/deploy/hte/tests/`.
- `helao/hexagon/tests/smoke/golden_capture*.py`, `smoke/station_golden_capture.py` and `smoke/configs/` go to `helao/deploy/hte/tests/smoke/`.
- A helper (`hosted_server.py`, `live_group.py`) moves only if every importer moved.

Then run each moved file: `python -m pytest -q -p no:cacheprovider <file>`. For each `fixture '<x>' not found`, add `from helao.hexagon.tests.conftest import <x>  # noqa: F401` to `helao/deploy/hte/conftest.py`.

- [ ] **Step 6: Run the hte and framework tests**

```
python run_tests.py --filter deploy/hte
python run_tests.py --filter hexagon/tests
python run_tests.py --filter core/tests
python run_tests.py --filter harness
```

Expected: every failure is one already in the P2 baseline.

- [ ] **Step 7: Launch smoke**

Launch `goldenreflex` and one `hte` sim/dummy config that has a Bokeh `action_visualizer` (`rg -l "action_visualizer" helao/deploy/hte/configs`), using the background marker pattern. Open no browser. Check the logs for `ModuleNotFoundError`, `AmbiguousModule` or `FileNotFoundError`. Expected: none, and every server's ready line printed.

- [ ] **Step 8: Commit** (main session, after review)

```bash
git -C . add -A helao/deploy/hte helao/hexagon helao/core helao/helpers harness CLAUDE.md
black $(git -C . diff --cached --name-only --diff-filter=AMR -- '*.py')
git -C . add -u
git -C . commit -m "refactor(hte): one folder per instrument (server, drivers, bokeh/, reflex/)"
```

Before pushing: the one private deployment that imports `galil_aligner_host` must have its import fix ready to merge at the same time (its own plan). Tell the user. Do not push P2 alone.

### Task 8: `hte` route checklists live in the deployment

**Files:**
- Move: `helao/hexagon/tests/checklists/hte/` → `helao/deploy/hte/tests/checklists/`
- Move: `helao/hexagon/tests/test_hte_route_checklist.py` → `helao/deploy/hte/tests/test_route_checklist.py`
- Delete: `harness/hte_freeze.py`
- Modify: the moved test's path constants; `helao/deploy/hte/tests/checklists/servers.json` (`group` values become irrelevant; module names unchanged)

**Interfaces:**
- Consumes: `preflight._checklist_dir` (already prefers `helao/deploy/<dep>/tests/checklists/`), `harness.freeze` (Task 3 made it layout-agnostic)

- [ ] **Step 1: Move and repoint**

```
git -C . mv helao/hexagon/tests/checklists/hte helao/deploy/hte/tests/checklists
git -C . mv helao/hexagon/tests/test_hte_route_checklist.py helao/deploy/hte/tests/test_route_checklist.py
git -C . rm harness/hte_freeze.py
rg -n "checklists/hte|hte_freeze" helao harness
```

Fix every hit to the new directory, building it as `helao/deploy/<deployment>/tests/checklists` from the deployment name, never from a literal in framework code.

- [ ] **Step 2: Verify the freeze reproduces the frozen checklists**

Run: `python -m harness.freeze hte --dry-run`
Expected: no drift reported for any of the 23 servers. `handler` is not compared; module paths changed only.

- [ ] **Step 3: Run the gate**

```
python -m pytest -q -p no:cacheprovider helao/deploy/hte/tests/test_route_checklist.py
python run_tests.py --filter preflight
```

Expected: PASS. 175 action routes and 81 private routes still cited.

- [ ] **Step 4: Commit** (main session)

```bash
git -C . add -A helao/deploy/hte/tests helao/hexagon/tests harness
git -C . commit -m "test(hte): route checklists live in the deployment; drop hte_freeze"
```

### Task 9: Per-instrument dependency files

**Files:**
- Create: `helao/deploy/hte/servers/<inst>/environment.yml`, `requirements.txt` and `README.md` for the instruments below
- Test: `helao/deploy/hte/tests/test_instrument_env_files.py`

- [ ] **Step 1: Write the failing test**

```python
"""Every instrument's third-party imports are declared in its folder's env files."""

import ast
import sys
from pathlib import Path

from ruamel.yaml import YAML

SERVERS = Path(__file__).resolve().parents[1] / "servers"
# import name -> distribution name, for packages declared under another name
DIST = {"serial": "pyserial", "mecom": "pymecom", "minimalmodbus": "minimalmodbus"}
VENDOR = {"gclib", "pyAndorSDK3", "pyAndorSpectrograph"}  # README only
BASE = set(sys.stdlib_module_names) | {
    "helao", "numpy", "pandas", "scipy", "fastapi", "pydantic", "bokeh", "reflex",
    "websockets", "httpx", "requests", "aiofiles", "psutil", "ruamel", "starlette",
    "uvicorn", "matplotlib", "msgspec", "pyzstd", "sklearn",
}
HARDWARE = {"serial", "pyvisa", "pylablib", "minimalmodbus", "nidaqmx", "comtypes",
            "mecom", "paramiko"}


def _imports(folder: Path) -> set[str]:
    names = set()
    for f in folder.rglob("*.py"):
        if "tests" in f.parts or "sidecar" in f.parts:
            continue
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names.add(node.module.split(".")[0])
    return names


def _declared(folder: Path) -> str:
    text = ""
    for name in ("environment.yml", "requirements.txt", "README.md"):
        if (folder / name).exists():
            text += (folder / name).read_text(encoding="utf-8").lower()
    return text


def test_hardware_imports_are_declared():
    missing = []
    for folder in sorted(p for p in SERVERS.iterdir() if p.is_dir()):
        declared = _declared(folder)
        for mod in sorted(_imports(folder) & (HARDWARE | VENDOR)):
            if DIST.get(mod, mod).lower() not in declared:
                missing.append(f"{folder.name}: {mod}")
    assert not missing, missing


def test_environment_files_parse():
    for f in SERVERS.glob("*/environment.yml"):
        data = YAML(typ="safe").load(f.read_text(encoding="utf-8"))
        assert data["dependencies"], f
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q -p no:cacheprovider helao/deploy/hte/tests/test_instrument_env_files.py`
Expected: FAIL, listing e.g. `mfc: serial`, `gamry: comtypes`, `kinesis: pylablib`.

- [ ] **Step 3: Write the files**

`environment.yml` files (each starts with `channels:\n  - conda-forge\ndependencies:`):

| folder | dependencies |
|---|---|
| kinesis | `pylablib` |
| mfc, syringe, diapump, co2sensor | `pyserial` |
| o2sensor | `pyserial`, `minimalmodbus` |
| power_supply | `pyvisa`, `pyvisa-py` |
| pal | `paramiko=3` |

`requirements.txt` files:

| folder | lines |
|---|---|
| gamry | `comtypes; sys_platform == "win32"` |
| biologic | `comtypes; sys_platform == "win32"` |
| nidaqmx | `nidaqmx` |
| pal | `nidaqmx` |
| tec | `https://github.com/meerstetter/pyMeCom/archive/master.zip` (and a comment line `# pymecom`) |

`README.md` vendor notes (each one names what to install by hand and where the driver looks for it):
- galil_io, galil_motion: Galil gclib (vendor installer plus its Python wrapper).
- andor: Andor SDK3 with the `pyAndorSDK3` and `pyAndorSpectrograph` wheels.
- biologic: EC-Lab Development Package at `C:\EC-Lab Development Package\lib` (eclib); the eclib2 SDK root from the server's config; EC-Lab itself for the OLE backend.
- gamry: Gamry Framework (COM server).
- nidaqmx: NI-DAQmx driver runtime.
- kinesis: Thorlabs Kinesis.
- spec: the Spectral Products SDK DLL loaded by `spectral_products_driver.py` (read the driver for the DLL name and path).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q -p no:cacheprovider helao/deploy/hte/tests/test_instrument_env_files.py`
Expected: PASS

- [ ] **Step 5: Mutation check**

Delete `pyserial` from `servers/mfc/environment.yml`. Confirm that `test_hardware_imports_are_declared` fails naming `mfc: serial`, then restore.

- [ ] **Step 6: Commit** (main session)

```bash
black helao/deploy/hte/tests/test_instrument_env_files.py
git -C . add helao/deploy/hte/servers helao/deploy/hte/tests/test_instrument_env_files.py
git -C . commit -m "feat(hte): per-instrument environment.yml/requirements.txt and vendor notes"
```

### Task 10: Framework stays free of `hte`

**Files:**
- Create: `helao/core/tests/test_framework_deployment_free.py`

- [ ] **Step 1: Write the test**

```python
"""Framework code names no deployment: no hte import, no hte path or module literal."""

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ROOTS = ["helao/core", "helao/hexagon", "helao/helpers", "helao/ui", "harness"]
FILES = ["fast_launcher.py", "bokeh_launcher.py", "reflex_launcher.py", "launch.py",
         "run_tests.py", "helao_env.py"]
HTE = re.compile(r"""helao\.deploy\.hte\b|deploy[/\\]hte\b|^hte$""")
# data label on records (``access``), not a deployment reference
ALLOWED_FIELD = {"access"}


def _py_files():
    for root in ROOTS:
        yield from (REPO / root).rglob("*.py")
    for name in FILES:
        if (REPO / name).exists():
            yield REPO / name


def _hits(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    allowed = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id in ALLOWED_FIELD and isinstance(node.value, ast.Constant):
                allowed.add(id(node.value))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            out += [f"import {n}" for n in names if n.startswith("helao.deploy.hte")]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in allowed and HTE.search(node.value):
                out.append(repr(node.value))
    return [f"{path.relative_to(REPO)}:{h}" for h in out]


def test_framework_names_no_deployment():
    hits = [h for f in _py_files() for h in _hits(f)]
    assert not hits, "\n".join(hits)
```

Note: module and function docstrings are `ast.Constant` strings too. A docstring that mentions `helao/deploy/hte` counts as a hit. Reword it to "a deployment" rather than adding an exemption.

- [ ] **Step 2: Run it**

Run: `python -m pytest -q -p no:cacheprovider helao/core/tests/test_framework_deployment_free.py`
Expected: PASS after Tasks 3-8. If it fails, fix each listed hit at its source. Never widen `ALLOWED_FIELD` or the regex.

- [ ] **Step 3: Mutation check (must fail on the pre-P1 code)**

Find the commit just before Task 5 with `git -C . log --oneline -12`; call it `<pre5>`. Then:

```
git -C . show <pre5>:helao/helpers/import_autolibs.py > helao/helpers/import_autolibs.py
python -m pytest -q -p no:cacheprovider helao/core/tests/test_framework_deployment_free.py
git -C . checkout -- helao/helpers/import_autolibs.py
```

Expected: the middle command FAILS, naming `helao/helpers/import_autolibs.py` and `'hte'`. After the checkout the file is restored. Never use `git stash`.

- [ ] **Step 4: Sweep parity for P2**

Run the full sweep in the background with a marker file. Its failing set must be a subset of `p2_base.log`'s.

- [ ] **Step 5: Commit** (main session)

```bash
black helao/core/tests/test_framework_deployment_free.py
git -C . add helao/core/tests/test_framework_deployment_free.py
git -C . commit -m "test: framework code names no deployment"
```

---

## Phase P3: station-aware `setup_env` / `update_env`

### Task 11: Config resolution with duplicate-prefix prompt

**Files:**
- Create: `helao_env.py` (repo root)
- Test: `helao/core/tests/test_helao_env.py`

**Interfaces:**
- Produces:
  - `REPO_ROOT`, `DEPLOY_ROOT`, `ENV_VAR = "HELAO_STATION_PREFIXES"`, `STATES_FILE = "setup_env_prefixes.json"`
  - `class EnvSetupError(Exception)`
  - `resolve_config(arg: str, deploy_root: Path = DEPLOY_ROOT, ask=input, interactive: bool | None = None) -> Path`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

import pytest

import helao_env as he


def _touch(root: Path, rel: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("servers: {}\n", encoding="utf-8")
    return p


@pytest.fixture
def root(tmp_path):
    _touch(tmp_path, "a/configs/solo.yml")
    _touch(tmp_path, "a/configs/dup.yml")
    _touch(tmp_path, "b/configs/dup.yml")
    _touch(tmp_path, "b/configs/pyonly.py")
    return tmp_path


def test_unique_prefix(root):
    assert he.resolve_config("solo", root) == (root / "a/configs/solo.yml").resolve()


def test_qualified_prefix_skips_prompt(root):
    assert he.resolve_config("b/dup", root, interactive=False) == (
        root / "b/configs/dup.yml"
    ).resolve()


def test_full_path(root):
    p = root / "a/configs/dup.yml"
    assert he.resolve_config(str(p), root) == p.resolve()


def test_py_config_when_no_yml(root):
    assert he.resolve_config("pyonly", root).name == "pyonly.py"


def test_duplicate_prompts_on_tty(root):
    answers = iter(["2"])
    got = he.resolve_config("dup", root, ask=lambda _: next(answers), interactive=True)
    assert got == (root / "b/configs/dup.yml").resolve()


def test_duplicate_reprompts_on_bad_answer(root):
    answers = iter(["9", "x", "1"])
    got = he.resolve_config("dup", root, ask=lambda _: next(answers), interactive=True)
    assert got == (root / "a/configs/dup.yml").resolve()


def test_duplicate_without_tty_exits_with_list(root):
    with pytest.raises(he.EnvSetupError, match=r"a/configs/dup\.yml[\s\S]*b/configs/dup\.yml"):
        he.resolve_config("dup", root, interactive=False)


def test_unknown_prefix(root):
    with pytest.raises(he.EnvSetupError, match="nope"):
        he.resolve_config("nope", root)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q -p no:cacheprovider helao/core/tests/test_helao_env.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'helao_env'`

- [ ] **Step 3: Implement (first part of `helao_env.py`)**

```python
"""Install the packages a station's servers need, from its config prefixes.

    python helao_env.py setup  <prefix|deployment/prefix|path> ...
    python helao_env.py update [<prefix> ...]

Called by setup_env/update_env after the base env exists. A prefix resolves
against every helao/deploy/*/configs/; a prefix found in several deployments is
asked about on a terminal and is an error without one. The resolved config paths
are recorded in <root>/STATES/setup_env_prefixes.json per config root, and the
conda env var HELAO_STATION_PREFIXES lists those files, so a later update with
no arguments reinstalls the same set.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
DEPLOY_ROOT = REPO_ROOT / "helao" / "deploy"
ENV_VAR = "HELAO_STATION_PREFIXES"
STATES_FILE = "setup_env_prefixes.json"


class EnvSetupError(Exception):
    """A config or install step that cannot proceed; the message says why."""


def resolve_config(
    arg: str, deploy_root: Path = DEPLOY_ROOT, ask=input, interactive: bool | None = None
) -> Path:
    """One config file for ``arg``: a path, ``deployment/prefix`` or a bare prefix."""
    path = Path(arg)
    if path.suffix in (".yml", ".py"):
        if path.is_file():
            return path.resolve()
        raise EnvSetupError(f"config file not found: {arg}")
    dep, _, prefix = arg.rpartition("/")
    pattern = f"{dep or '*'}/configs/{prefix}"
    matches = sorted(deploy_root.glob(f"{pattern}.yml")) or sorted(
        deploy_root.glob(f"{pattern}.py")
    )
    if not matches:
        raise EnvSetupError(f"no config named {arg!r} in any deployment")
    if len(matches) == 1:
        return matches[0].resolve()
    listing = "\n".join(
        f"  {i}. {m.relative_to(deploy_root)}" for i, m in enumerate(matches, 1)
    )
    if interactive is None:
        interactive = sys.stdin.isatty()
    if not interactive:
        raise EnvSetupError(
            f"config prefix {arg!r} exists in several deployments:\n{listing}\n"
            f"pass <deployment>/{prefix} or a full path"
        )
    while True:
        answer = ask(f"{arg!r} exists in several deployments:\n{listing}\nwhich one? ")
        if answer.strip().isdigit() and 1 <= int(answer) <= len(matches):
            return matches[int(answer) - 1].resolve()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q -p no:cacheprovider helao/core/tests/test_helao_env.py`
Expected: PASS

- [ ] **Step 5: Commit** (main session)

```bash
black helao_env.py helao/core/tests/test_helao_env.py
git -C . add helao_env.py helao/core/tests/test_helao_env.py
git -C . commit -m "feat(env): resolve station config prefixes, asking on duplicates"
```

### Task 12: Server folders of a config

**Files:**
- Modify: `helao_env.py`
- Test: `helao/core/tests/test_helao_env.py`

**Interfaces:**
- Consumes: `launcher_bootstrap.resolve_app_deployment`, `server_modules.module_file`, `config_loader.read_config`
- Produces: `server_folders(config_path: Path) -> set[Path]`. These are the directories holding each server's `fast:`/`bokeh:` module; a module in an instrument's `bokeh/` or `reflex/` subfolder maps to the instrument folder. Raises `EnvSetupError` naming the server key when a module cannot be resolved.

- [ ] **Step 1: Write the failing test**

```python
def test_server_folders_of_a_real_hte_config():
    cfg = he.resolve_config("hte/anec") if (he.DEPLOY_ROOT / "hte/configs/anec.yml").exists() else None
    if cfg is None:
        pytest.skip("anec config not present")
    folders = {f.name for f in he.server_folders(cfg)}
    assert {"gamry", "nidaqmx", "galil_motion"} <= folders


def test_unresolvable_module_names_the_server(tmp_path, monkeypatch):
    cfg = tmp_path / "x.yml"
    cfg.write_text(
        "root: " + str(tmp_path) + "\nservers:\n  BAD:\n    host: 127.0.0.1\n"
        "    port: 9999\n    group: action\n    fast: no_such_module\n"
        "    deployment: hte\n",
        encoding="utf-8",
    )
    with pytest.raises(he.EnvSetupError, match="BAD"):
        he.server_folders(cfg)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest -q -p no:cacheprovider helao/core/tests/test_helao_env.py -k server_folders`
Expected: FAIL with `AttributeError: module 'helao_env' has no attribute 'server_folders'`

- [ ] **Step 3: Implement**

```python
def server_folders(config_path: Path) -> set[Path]:
    """Folders holding this config's server modules (where env files live)."""
    import logging

    from helao.helpers import server_modules
    from helao.helpers.config_loader import read_config
    from helao.helpers.launcher_bootstrap import resolve_app_deployment

    cfg = read_config(str(config_path))
    log = logging.getLogger("helao_env")
    folders: set[Path] = set()
    for key, entry in (cfg.get("servers") or {}).items():
        module = entry.get("fast") or entry.get("bokeh")
        if not module:
            continue  # reflex: names a bundle, not a module
        try:
            dep = resolve_app_deployment(entry, module, str(config_path), log)
            path = server_modules.module_file(dep, module, "app")
        except (FileNotFoundError, server_modules.AmbiguousModule) as exc:
            raise EnvSetupError(f"{config_path.name}: server {key}: {exc}") from exc
        if path is None:
            raise EnvSetupError(
                f"{config_path.name}: server {key}: deployment {dep!r} has no {module!r}"
            )
        folder = path.parent
        if folder.name in ("bokeh", "reflex"):
            folder = folder.parent
        folders.add(folder)
    return folders
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q -p no:cacheprovider helao/core/tests/test_helao_env.py`
Expected: PASS

- [ ] **Step 5: Commit** (main session)

```bash
black helao_env.py helao/core/tests/test_helao_env.py
git -C . add helao_env.py helao/core/tests/test_helao_env.py
git -C . commit -m "feat(env): collect the server folders a config launches"
```

### Task 13: Merge, install, record, CLI

**Files:**
- Modify: `helao_env.py`
- Test: `helao/core/tests/test_helao_env.py`

**Interfaces:**
- Produces:
  - `merge_environment(folders) -> dict | None`
  - `install(folders, runner=_run, dry_run=False) -> list[list[str]]` (returns the commands)
  - `stored_configs(env: Mapping[str, str] = os.environ) -> list[Path]`
  - `record(configs, runner=_run) -> list[Path]`
  - `main(argv=None) -> int`

- [ ] **Step 1: Write the failing tests**

```python
def _env(folder: Path, text: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "environment.yml").write_text(text, encoding="utf-8")


def test_merge_unions_channels_deps_and_pip(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _env(a, "channels: [conda-forge]\ndependencies: [pyserial, {pip: [x==1]}]\n")
    _env(b, "channels: [conda-forge, other]\ndependencies: [pyserial, pyvisa=1.13, {pip: [x==2]}]\n")
    env = he.merge_environment({a, b})
    assert env["channels"] == ["conda-forge", "other"]
    assert env["dependencies"][:2] == ["pyserial", "pyvisa=1.13"]
    assert env["dependencies"][-1] == {"pip": ["x==1", "x==2"]}  # both pins kept


def test_merge_none_when_no_env_files(tmp_path):
    assert he.merge_environment({tmp_path}) is None


def test_install_runs_conda_once_then_uv_per_folder(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _env(a, "dependencies: [pyserial]\n")
    b.mkdir()
    (b / "requirements.txt").write_text("nidaqmx\n", encoding="utf-8")
    cmds = []
    he.install({a, b}, runner=cmds.append)
    assert [c[1:3] for c in cmds] == [["env", "update"], ["pip", "install"]]
    assert cmds[1][-1] == str(b / "requirements.txt")


def test_record_creates_states_and_merges(tmp_path, monkeypatch):
    root = tmp_path / "rel_root"
    cfg1 = tmp_path / "c1.yml"
    cfg1.write_text(f"root: {root}\nservers: {{}}\n", encoding="utf-8")
    cfg2 = tmp_path / "c2.yml"
    cfg2.write_text(f"root: {root}\nservers: {{}}\n", encoding="utf-8")
    monkeypatch.delenv(he.ENV_VAR, raising=False)
    calls = []
    he.record([cfg1], runner=calls.append)
    files = he.record([cfg2], runner=calls.append)
    data = json.loads((root / "STATES" / he.STATES_FILE).read_text(encoding="utf-8"))
    assert data == sorted([str(cfg1.resolve()), str(cfg2.resolve())])
    assert files == [root / "STATES" / he.STATES_FILE]
    assert calls[-1][-1].startswith(f"{he.ENV_VAR}=")


def test_relative_root_resolves_against_repo_root(tmp_path, monkeypatch):
    monkeypatch.setattr(he, "REPO_ROOT", tmp_path)
    monkeypatch.delenv(he.ENV_VAR, raising=False)
    cfg = tmp_path / "c.yml"
    cfg.write_text("root: rel_root\nservers: {}\n", encoding="utf-8")
    he.record([cfg], runner=lambda cmd: None)
    assert (tmp_path / "rel_root" / "STATES" / he.STATES_FILE).is_file()


def test_stored_configs_skips_missing_files_and_configs(tmp_path, capsys):
    good = tmp_path / "c.yml"
    good.write_text("servers: {}\n", encoding="utf-8")
    states = tmp_path / "s.json"
    states.write_text(json.dumps([str(good), str(tmp_path / "gone.yml")]), encoding="utf-8")
    env = {he.ENV_VAR: os.pathsep.join([str(states), str(tmp_path / "missing.json")])}
    assert he.stored_configs(env) == [good]
    err = capsys.readouterr().err
    assert "gone.yml" in err and "missing.json" in err


def test_main_update_without_anything_is_a_hint(monkeypatch, capsys):
    monkeypatch.delenv(he.ENV_VAR, raising=False)
    assert he.main(["update"]) == 0
    assert "setup_env" in capsys.readouterr().out


def test_main_bad_prefix_exits_2(capsys):
    assert he.main(["setup", "definitely_not_a_config"]) == 2
```

Add `import json` and `import os` to the test file's imports.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest -q -p no:cacheprovider helao/core/tests/test_helao_env.py`
Expected: FAIL with `AttributeError` for `merge_environment`, `install`, `record`, `stored_configs` and `main`.

- [ ] **Step 3: Implement**

```python
def _yaml():
    from ruamel.yaml import YAML

    return YAML(typ="safe")


def merge_environment(folders) -> dict | None:
    """One conda env spec from every folder's environment.yml (union, order kept)."""
    channels: list[str] = []
    deps: list[str] = []
    pip: list[str] = []
    for folder in sorted(folders):
        f = Path(folder) / "environment.yml"
        if not f.is_file():
            continue
        data = _yaml().load(f.read_text(encoding="utf-8")) or {}
        channels += [c for c in data.get("channels", []) if c not in channels]
        for d in data.get("dependencies", []):
            if isinstance(d, dict):
                pip += [p for p in d.get("pip", []) if p not in pip]
            elif d not in deps:
                deps.append(d)
    if not deps and not pip:
        return None
    return {
        "channels": channels or ["conda-forge"],
        "dependencies": deps + ([{"pip": pip}] if pip else []),
    }


def _conda() -> str:
    return os.environ.get("CONDA_EXE", "conda")


def _run(cmd: list[str]) -> None:
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def install(folders, runner=_run, dry_run: bool = False) -> list[list[str]]:
    """Conda first (one merged update), then uv per folder requirements.txt."""
    cmds: list[list[str]] = []
    env = merge_environment(folders)
    if env is not None:
        tmp = Path(tempfile.mkdtemp()) / "station_env.yml"
        with open(tmp, "w", encoding="utf-8") as fh:
            _yaml().dump(env, fh)
        cmds.append([_conda(), "env", "update", "--solver=rattler",
                     "--prefix", sys.prefix, "-f", str(tmp)])
    for folder in sorted(folders):
        req = Path(folder) / "requirements.txt"
        if req.is_file():
            cmds.append(["uv", "pip", "install", "--python", sys.executable, "-r", str(req)])
    for cmd in cmds:
        (print if dry_run else runner)(cmd)
    return cmds


def _warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr)


def _states_files(env) -> list[Path]:
    return [Path(p) for p in env.get(ENV_VAR, "").split(os.pathsep) if p]


def stored_configs(env=os.environ) -> list[Path]:
    """Config paths recorded by earlier setup runs; missing ones are skipped."""
    out: list[Path] = []
    for states in _states_files(env):
        if not states.is_file():
            _warn(f"{ENV_VAR} lists {states}, which does not exist; skipped")
            continue
        for p in json.loads(states.read_text(encoding="utf-8")):
            if Path(p).is_file():
                out.append(Path(p))
            else:
                _warn(f"recorded config {p} no longer exists; skipped")
    return out


def record(configs, runner=_run) -> list[Path]:
    """Add ``configs`` to <root>/STATES/setup_env_prefixes.json; point the env var."""
    from helao.helpers.config_loader import read_config

    files = set(_states_files(os.environ))
    written: list[Path] = []
    for cfg in configs:
        root = read_config(str(cfg)).get("root")
        if not root:
            _warn(f"{cfg} has no root:, so its prefix is not recorded")
            continue
        states = (REPO_ROOT / root).resolve() / "STATES" / STATES_FILE
        states.parent.mkdir(parents=True, exist_ok=True)
        known = set(json.loads(states.read_text(encoding="utf-8"))) if states.is_file() else set()
        known.add(str(Path(cfg).resolve()))
        states.write_text(json.dumps(sorted(known), indent=2), encoding="utf-8")
        files.add(states)
        if states not in written:
            written.append(states)
    if written:
        runner([_conda(), "env", "config", "vars", "set", "--prefix", sys.prefix,
                f"{ENV_VAR}={os.pathsep.join(sorted(map(str, files)))}"])
    return written


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="helao_env.py")
    p.add_argument("mode", choices=["setup", "update"])
    p.add_argument("prefixes", nargs="*")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    try:
        if a.prefixes:
            configs = [resolve_config(x) for x in a.prefixes]
        elif a.mode == "update":
            configs = stored_configs()
        else:
            configs = []
        if not configs:
            print("no station configs given or recorded: base env only. Run "
                  "setup_env <config prefix> ... to install a station's packages.")
            return 0
        folders: set[Path] = set()
        for cfg in configs:
            folders |= server_folders(cfg)
        install(folders, dry_run=a.dry_run)
        if a.prefixes and not a.dry_run:
            record(configs)
        for folder in sorted(folders):
            if (folder / "README.md").is_file():
                print(f"vendor notes: {folder / 'README.md'}")
        return 0
    except (EnvSetupError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
```

Note on `record`: `(REPO_ROOT / root)` keeps an absolute `root` as is (pathlib drops the left side), and a relative `root` resolves against the repo root, the cwd `helao.sh` launches from.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q -p no:cacheprovider helao/core/tests/test_helao_env.py`
Expected: PASS

- [ ] **Step 5: Dry run against a real config**

Run: `python helao_env.py setup anec --dry-run` (or any `hte` config prefix).
Expected: it prints one `conda env update` command (when a folder has `environment.yml`) and `uv` lines, and writes nothing (`git -C . status` clean; no STATES file).

- [ ] **Step 6: Commit** (main session)

```bash
black helao_env.py helao/core/tests/test_helao_env.py
git -C . add helao_env.py helao/core/tests/test_helao_env.py
git -C . commit -m "feat(env): install, record and replay a station's server packages"
```

### Task 14: Wrapper scripts call `helao_env.py`

**Files:**
- Modify: `setup_env.sh`, `update_env.sh`, `setup_env.bat`, `update_env.bat`
- Modify: `CLAUDE.md` (Environment section: one paragraph on `setup_env <prefixes>` and `HELAO_STATION_PREFIXES`)

- [ ] **Step 1: Edit the four wrappers**

In `setup_env.sh` and `update_env.sh`, after the `uv pip install ... requirements.txt` line and before the `conda env config vars set PYTHONPATH` line, add:

```bash
PYTHONPATH="$HA_DIR" python "$HA_DIR/helao_env.py" setup "$@" || exit 1
```

Use `update` instead of `setup` in `update_env.sh`.

In `setup_env.bat` and `update_env.bat`, after the `uv pip install` block, add:

```bat
set PYTHONPATH=%HA_DIR%
python "%HA_DIR%\helao_env.py" setup %*
if ERRORLEVEL 1 exit /b 1
```

Use `update` in `update_env.bat`.

- [ ] **Step 2: Linux check in a throwaway env**

Use the existing `helao` env. Run `bash -n setup_env.sh && bash -n update_env.sh` (syntax). Then run `PYTHONPATH=$PWD python helao_env.py update --dry-run` with `HELAO_STATION_PREFIXES` unset. Expected: the base-env hint and exit 0.

- [ ] **Step 3: Windows check**

The `.bat` files cannot run here. Read the diff and confirm `%*` is passed and `ERRORLEVEL` is checked after the call. Then run `python repin_envs.py` (dry, without `--write`) with a merged station env yml to confirm win-64 solvability: `python helao_env.py setup anec --dry-run` prints the temp yml path, and `conda create --dry-run --platform win-64 -n x -f <that yml>` solves. Report the result; do not claim Windows works beyond the solve.

- [ ] **Step 4: Commit** (main session)

```bash
git -C . add setup_env.sh update_env.sh setup_env.bat update_env.bat CLAUDE.md
git -C . commit -m "feat(env): setup_env/update_env install the station's server packages"
```

---

## Phase P4 (public part): `test` deployment

### Task 15: Reorganize `helao/deploy/test`

**Files:**
- Create: `harness/reorg/test.json`
- Move: per the mapping

- [ ] **Step 1: Write the mapping**

All paths are under `helao/deploy/test/`. `scan: ["helao", "harness", "*.py"]`.
- `servers/action/cpsim_server.py`→`servers/cpsim/cpsim_server.py`; `drivers/pstat/cpsim_driver.py`→`servers/cpsim/cpsim_driver.py`; `drivers/data/oer_metrics.py`→`servers/cpsim/oer_metrics.py`
- `servers/action/gpsim_server.py`→`servers/gpsim/`; `drivers/data/gpsim_driver.py`, `drivers/data/gp_backend.py`→`servers/gpsim/`; `servers/visualizer/gpsim_live_vis.py`→`servers/gpsim/bokeh/`; `servers/reflex/gpsim_panel.py`→`servers/gpsim/reflex/`
- `servers/visualizer/oersim_vis.py`→`servers/cpsim/bokeh/oersim_vis.py`; `servers/reflex/oersim_panel.py`→`servers/cpsim/reflex/oersim_panel.py`
- `servers/action/ws_simulator.py`→`servers/wssim/ws_simulator.py`; `servers/visualizer/wssim_live_vis.py`→`servers/wssim/bokeh/`; `servers/reflex/wssim_live_vis.py`→`servers/wssim/reflex/`; `servers/reflex/wssim_panel.py`→`servers/wssim/reflex/`
- `control_sim.py` and `sim_db_server.py` stay in `servers/action/`. They have no driver, and the resolver finds them there.

- [ ] **Step 2: Run, fix leftovers, test**

```
python -m harness.reorg_deploy harness/reorg/test.json
python run_tests.py --filter deploy/test
python run_tests.py --filter reflex
python run_unit_tests.py
```

Expected: PASS. `run_unit_tests.py:56` keeps importing `helao.deploy.test.tests...`, which is unchanged.

- [ ] **Step 3: Launch smoke**

Launch one `test` config with the background marker pattern. Expected: every server is ready, with no `ModuleNotFoundError`.

- [ ] **Step 4: Commit** (main session)

```bash
git -C . add -A helao/deploy/test harness/reorg/test.json
git -C . commit -m "refactor(test): one folder per simulator"
```

---

## Final task (gated): strip hardware packages from the base env

### Task 16: Base env holds no hardware packages

**Precondition — do not start until all of these hold, confirmed by the user:**
1. Every private deployment has shipped its folder env files (its own plan).
2. Every station has run `setup_env <its prefixes>` once, so `HELAO_STATION_PREFIXES` is set there.

**Files:**
- Modify: `helao_dev_linux-64.yml`, `helao_dev_win-64.yml`, `requirements.txt`
- Regenerate: `helao_pinned_*.yml`, `requirements_pinned_*.txt`

- [ ] **Step 1: Remove from both yml files**

Remove `pyftdi`, `pylablib`, `pymodbus`, `pyserial`, `pyusb`, `pyvisa`, `pyvisa-py`, `paramiko=3`. Also remove `comtypes` from win-64. `pymodbus` is used only by private deployments; confirm their folder files declare it before removing it.

- [ ] **Step 2: Remove from `requirements.txt`**

Remove `nidaqmx`, `pyft232`, and the pyMeCom URL line.

- [ ] **Step 3: Regenerate pins**

Run: `python repin_envs.py --write`
Expected: both platforms solve, and the pinned files no longer list the removed packages.

- [ ] **Step 4: Verify**

Run the full sweep in the background with a marker file. Hardware driver tests whose package is now absent from the dev env must report `ENV`, not `FAIL`. Any `FAIL` blocks the commit.

- [ ] **Step 5: Commit** (main session)

```bash
git -C . add helao_dev_*.yml helao_pinned_*.yml requirements*.txt
git -C . commit -m "build(env): hardware packages come from instrument folders, not the base env"
```

---

## Rollout

After P2 and P3 are merged and pushed (and the private import fixes that P2 needs):
1. One station first: `update.sh`/`update.bat`, then `setup_env <its config prefixes>`, launch, run one action per instrument.
2. Then the remaining stations, each running `setup_env <its prefixes>` once.
3. Task 16 only after every station has done step 2.

## Follow-up plans (separate repos, not in this document)

Each private deployment gets its own short plan in its own repo, using the same tool:
1. Write `<its repo>/reorg.json` with that deployment's moves, and run `python -m harness.reorg_deploy <its repo>/reorg.json` from the parent repo with `scan` limited to its own directory.
2. Rewrite its imports of moved `hte` modules (e.g. `helao.deploy.hte.drivers.motion.enum` → `helao.deploy.hte.servers.galil_motion.enum`, and the `galil_aligner_host` import). Its `deployment: hte` config keys stay as they are.
3. Add folder `environment.yml`/`requirements.txt`/`README.md` files.
4. Merge together with P2 when it depends on a moved module.
