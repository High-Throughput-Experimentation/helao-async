# /runners Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Reflex `/runners` page that lists the deployment's runner scripts, shows their parameters and action-server requirements, launches them as subprocesses, and stops them.

**Architecture:** Runner modules expose `async def run(orch: MicroOrch, ...)` plus an optional `REQUIRES`. A core launcher (`python -m helao.core.runners.launch`) describes a runner as JSON (`--describe`) or runs it on a MicroOrch built from the group config, with a cooperative stop on SIGTERM. The page never imports runner code. It builds its catalog from describe subprocesses, checks requirements against live servers, and keeps a process-wide table of the runners it spawned.

**Tech Stack:** Python 3.14, Reflex 0.9.x, asyncio subprocesses, `ast`, httpx-based `async_private_dispatcher`, pytest + pytest-asyncio (strict mode).

**Spec:** `docs/superpowers/specs/2026-11-17-runners-page-design.md`

## Global Constraints

- Branch: `feat/runners-page`, created from `unstable` after `fix/runner-estop-push-409-retry` is merged; no upstream; never push to `unstable` (push = note1 deploy).
- Interpreter: `/home/dan/miniforge3/envs/helao/bin/python` with `PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async`. Bare `python` is the system one.
- `black` the changed `.py` files immediately before each commit; `git -C /mnt/STORAGE/repos/helao/helao-async` for every git call; confirm the branch before committing.
- Read `helao/ui/reflex/CLAUDE.md` before editing anything under `helao/ui/reflex/`; colours only in `helao/ui/shared/palette.py`.
- Logging: `LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER`.
- Text IO passes `encoding="utf-8"`.
- No private deployment names in tracked files.
- Never touch `/mnt/wd4` or other network mounts; tests use tmp dirs.
- Every new test must fail against a deliberate mutation of the code it covers (revert after).
- Values from the spec: describe timeout 10 s per file; requirement probes `timeout=5, retries=1`; no timer polling of the catalog or requirements; Stop = SIGTERM, Force kill = SIGKILL; second SIGTERM exit code 130; clean stop exit 0; exception exit 1; usage errors exit 2.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A runner file with a syntax error or a top-level exception: Refresh must list it greyed out with the error, never crash the page or the Reflex process (Task 5 `test_catalog_lists_broken_module_with_error`).
2. Stop pressed while a long action runs: the action completes on its server, the experiment record is written `aborted`, the runner deregisters, exit 0 (Task 1 `test_request_stop_mid_experiment_finishes_record_aborted`, Task 3 `test_sigterm_is_clean_stop`).
3. A launch whose params do not coerce (e.g. "abc" for an int): no process starts, the error names the field (Task 6 `test_launch_refuses_bad_params`).
4. A key already running from this page or registered on /group: launch refused, no second process (Task 5 `test_launch_refuses_duplicate_key`).
5. An unreachable server during the requirement check: its rows fail within the 5 s probe timeout, and the page stays responsive (Task 5 `test_probe_unreachable_server_fails_rows`).

---

## File Structure

| File | Responsibility |
|---|---|
| `helao/core/runners/micro_orch.py` (modify) | `RunnerStopped`, `request_stop()`, aborted finish. |
| `helao/core/runners/requirements.py` (create) | Pure: `inferred(source)`, `check(...)`. |
| `helao/core/runners/launch.py` (create) | CLI: `--describe` and run mode. |
| `helao/deploy/test/runners/*.py` (modify) | Migrate three runners to the contract. |
| `helao/ui/reflex/runner_procs.py` (create) | Non-Reflex backend: catalog via describe, requirement probes, process registry, overlap. |
| `helao/ui/reflex/runners.py` (create) | Reflex state and page. |
| `helao/ui/reflex/app.py`, `helao/ui/shared/palette.py`, `helao/ui/shared/operator/param_store.py` (modify) | Route, nav, tint, `runner` param kind. |
| Tests (create) | `helao/core/tests/test_micro_orch_stop.py`, `test_runner_requirements.py`, `test_runner_launch.py`, `test_test_runners_contract.py`, `test_runner_procs.py`, `test_reflex_runners.py` |

---

### Task 1: MicroOrch cooperative stop

**Files:**
- Modify: `helao/core/runners/micro_orch.py` (`dispatch_action` ~578, `_dispatch_experiment_actions` ~860, `_run_planned` ~964, `_finish_experiment` ~1128, `_finish_sequence` ~1146)
- Test: `helao/core/tests/test_micro_orch_stop.py`

**Interfaces:**
- Produces: `class RunnerStopped(Exception)` in `micro_orch.py`; `MicroOrch.request_stop() -> None`; `MicroOrch.stop_requested: bool`; `_finish_experiment(experiment, status=HloStatus.finished)`, `_finish_sequence(sequence, status=HloStatus.finished)`.

- [ ] **Step 1: Write the failing tests**

```python
"""MicroOrch cooperative stop (spec: Launcher step 6)."""

import shutil
import tempfile

import pytest
import pytest_asyncio

from helao.core.models.machine import MachineModel
from helao.core.rpc import derive_rpc_port
from helao.core.runners.micro_orch import RunnerStopped
from helao.core.tests.unit_test_micro_orch import (
    _FakeDataActionServer,
    _free_port,
    _make_orch,
)
from helao.helpers.premodels import Action, ActionPlanMaker, Experiment


@pytest_asyncio.fixture
async def rig():
    root = tempfile.mkdtemp(prefix="micro_stop_")
    port = _free_port()
    fake = _FakeDataActionServer("FAKE", "ping", root)
    await fake.dispatcher.serve("127.0.0.1", derive_rpc_port(port))
    orch = _make_orch(root, {"FAKE": {"host": "127.0.0.1", "port": port}})
    orch.group_urls = []
    await orch.start()
    try:
        yield orch, fake
    finally:
        await orch.stop()
        await fake.dispatcher.close()
        shutil.rmtree(root, ignore_errors=True)


def _three_pings(experiment):
    apm = ActionPlanMaker()
    for _ in range(3):
        apm.add("FAKE", "ping", {})
    return apm.planned_actions


@pytest.mark.asyncio
async def test_request_stop_before_dispatch_raises_and_dispatches_nothing(rig):
    orch, fake = rig
    orch.request_stop()
    act = Action(action_name="ping", action_server=MachineModel(server_name="FAKE"))
    with pytest.raises(RunnerStopped):
        await orch.run_action(act)
    assert fake.action_calls == []


@pytest.mark.asyncio
async def test_request_stop_mid_experiment_finishes_record_aborted(rig, monkeypatch):
    orch, fake = rig
    real = orch.dispatch_action
    calls = {"n": 0}

    async def stop_after_first(action, *a, **k):
        if calls["n"] == 1:
            orch.request_stop()
        calls["n"] += 1
        return await real(action, *a, **k)

    monkeypatch.setattr(orch, "dispatch_action", stop_after_first)
    with pytest.raises(RunnerStopped):
        await orch.run_experiment(_three_pings, experiment=Experiment(experiment_name="e"))
    assert len(fake.action_calls) == 1
    exp = orch.last_experiment
    assert "aborted" in [str(getattr(s, "value", s)) for s in exp.experiment_status]
    assert any(r["type"] == "experiment" for r in orch.runs)
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_micro_orch_stop.py -q`
Expected: FAIL, `ImportError: cannot import name 'RunnerStopped'`.

- [ ] **Step 3: Implement**

Below `_finish_status` add:

```python
class RunnerStopped(Exception):
    """Raised by :meth:`MicroOrch.dispatch_action` after :meth:`MicroOrch.request_stop`."""
```

In `__init__`, beside the other /group feed attributes:

```python
        self.stop_requested = False
```

New method in the "/group feed support" section:

```python
    def request_stop(self) -> None:
        """Dispatch nothing more; actions already dispatched are still awaited."""
        self.stop_requested = True
```

At the very top of `dispatch_action`'s body (before `action.init_act()`):

```python
        if self.stop_requested:
            raise RunnerStopped("stop requested")
```

`_finish_experiment(self, experiment, status: HloStatus = HloStatus.finished)`: replace `experiment.reset_experiment_status(HloStatus.finished)` with `experiment.reset_experiment_status(status)`. The same for `_finish_sequence` with `reset_sequence_status(status)`.

In `_dispatch_experiment_actions`, wrap the dispatch loop:

```python
        results: list[dict] = []
        dispatched: list[Action] = []
        try:
            for act in actions:
                self._apply_from_global(act)
                await self._wait_for_start_condition(act)
                result = await self.dispatch_action(act, timeout=dispatch_timeout)
                results.append(result)
                dispatched.append(act)
                self._capture_to_global(result, act.to_global_params)
        except RunnerStopped:
            for act, immediate in zip(dispatched, results):
                status = immediate.get("action_status") if isinstance(immediate, dict) else None
                dump = immediate
                if not _is_terminal(status) and not act.nonblocking:
                    dump = await self.wait_for_action(act.action_uuid, timeout=wait_timeout)
                if isinstance(dump, dict):
                    try:
                        experiment.dispatched_actions.append(Action.model_validate(dump))
                    except Exception:
                        LOGGER.exception("could not rebuild Action from terminal dump")
            yml_path = await self._finish_experiment(experiment, status=HloStatus.aborted)
            self._track_run(
                "experiment", experiment.experiment_uuid, experiment.experiment_name, yml_path
            )
            raise
```

The rest of the method stays unchanged after the `try`.

In `_run_planned`, wrap the per-plan loop body's `await self.run_experiment(...)` in a `try` / `except RunnerStopped:`. In the `except`, call `yml_path = await self._finish_sequence(sequence, status=HloStatus.aborted)`, then `self._track_run("sequence", sequence.sequence_uuid, sequence.sequence_name, yml_path)`, then `raise`.

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_micro_orch_stop.py helao/core/tests/test_micro_orch_group_state.py helao/core/tests/test_micro_orch_finish.py -q && PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python helao/core/tests/unit_test_micro_orch.py`
Expected: all pass. Mutations: (a) drop the `stop_requested` check, so test 1 fails; (b) finish with `HloStatus.finished` in the `except`, so test 2 fails. Revert both.

- [ ] **Step 5: Commit**

```bash
black helao/core/runners/micro_orch.py helao/core/tests/test_micro_orch_stop.py
git -C /mnt/STORAGE/repos/helao/helao-async add helao/core/runners/micro_orch.py helao/core/tests/test_micro_orch_stop.py
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(runners): cooperative stop for MicroOrch (RunnerStopped, aborted records)"
```

---

### Task 2: Requirement inference and check (pure)

**Files:**
- Create: `helao/core/runners/requirements.py`
- Modify: the spec's "Requirement check" section: replace `helao/ui/reflex/runner_requirements.py` with `helao/core/runners/requirements.py` and add one sentence: "in core because the launcher's `--describe` calls `inferred`".
- Test: `helao/core/tests/test_runner_requirements.py`

**Interfaces:**
- Produces: `inferred(source: str) -> dict[str, list[str]]`; `check(requires: dict, world_cfg: dict, endpoints: dict, status: dict, *, inferred_only: bool = False) -> list[dict]`. `endpoints` is `{server: list[str] | None}` (None means unreachable); `status` is `{server: dict | None}`. Each row is `{"server", "action", "in_config", "reachable", "has_endpoint", "estopped", "busy", "verdict"}`, with verdict in `"ok"|"warn"|"fail"`.

- [ ] **Step 1: Write the failing tests**

```python
"""Runner requirement inference and check (spec: Requirement check)."""

from helao.core.runners.requirements import check, inferred

SRC = '''
from helao.core.models.machine import MachineModel
from helao.helpers.premodels import Action
SERVER = "PSTAT"

def _act(server, name, params=None): ...

async def run(orch, plate_id: int = 1):
    await orch.run_action(_act("ORCH", "wait", {"waittime": 1}))
    await orch.run_action(_act("SIM", "acquire_data"))
    await orch.run_action(_act(SERVER, "run_CA"))          # variable: skipped
    a = Action(action_name="measure", action_server=MachineModel(server_name="XRF"))
'''


def test_inferred_collects_literals_only():
    assert inferred(SRC) == {
        "ORCH": ["wait"],
        "SIM": ["acquire_data"],
        "XRF": ["measure"],
    }


def test_inferred_on_bad_source_is_empty():
    assert inferred("def broken(:\n") == {}


WORLD = {"servers": {"SIM": {"host": "h", "port": 1}, "ORCH": {"host": "h", "port": 2}}}


def _rows(**kw):
    base = dict(
        requires={"SIM": ["acquire_data"], "ORCH": ["wait"], "GONE": ["x"]},
        world_cfg=WORLD,
        endpoints={"SIM": ["acquire_data"], "ORCH": [], "GONE": None},
        status={"SIM": {"estop": False, "endpoints": {}}, "ORCH": {"estop": False}},
    )
    base.update(kw)
    return {(r["server"], r["action"]): r for r in check(**base)}


def test_check_verdicts():
    rows = _rows()
    assert rows[("SIM", "acquire_data")]["verdict"] == "ok"
    assert rows[("ORCH", "wait")]["verdict"] == "fail"          # missing endpoint
    assert rows[("GONE", "x")]["verdict"] == "fail"             # not in config
    assert rows[("GONE", "x")]["in_config"] is False


def test_check_estop_fails_and_busy_warns():
    rows = _rows(
        endpoints={"SIM": ["acquire_data"], "ORCH": ["wait"], "GONE": None},
        status={
            "SIM": {"estop": True, "endpoints": {}},
            "ORCH": {"estop": False, "endpoints": {"wait": {"active_dict": {"u": {}}}}},
        },
    )
    assert rows[("SIM", "acquire_data")]["verdict"] == "fail"
    assert rows[("ORCH", "wait")]["verdict"] == "warn"
    assert rows[("ORCH", "wait")]["busy"] is True


def test_probe_unreachable_server_fails_rows():
    rows = _rows(endpoints={"SIM": None, "ORCH": ["wait"], "GONE": None})
    assert rows[("SIM", "acquire_data")]["reachable"] is False
    assert rows[("SIM", "acquire_data")]["verdict"] == "fail"


def test_inferred_only_downgrades_fail_to_warn():
    rows = _rows(inferred_only=True)
    assert rows[("ORCH", "wait")]["verdict"] == "warn"
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_runner_requirements.py -q`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Implement `helao/core/runners/requirements.py`**

```python
"""What a runner needs from the group's action servers (spec: Requirement check).

Pure functions: no network, no Reflex. The page gathers endpoints and status;
the launcher's ``--describe`` calls :func:`inferred`.
"""

import ast
from typing import Optional

ACT_HELPERS = ("_act", "make_action")


def _lit(node) -> Optional[str]:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _add(out: dict, server, action) -> None:
    if server and action:
        names = out.setdefault(server, [])
        if action not in names:
            names.append(action)


def inferred(source: str) -> dict:
    """``{server: [action, ...]}`` from literal action-building calls; ``{}`` if unparsable."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    out: dict = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name in ACT_HELPERS and len(node.args) >= 2:
            _add(out, _lit(node.args[0]), _lit(node.args[1]))
        elif name == "Action":
            kw = {k.arg: k.value for k in node.keywords}
            action = _lit(kw.get("action_name"))
            server = None
            srv = kw.get("action_server")
            if isinstance(srv, ast.Call):
                skw = {k.arg: k.value for k in srv.keywords}
                server = _lit(skw.get("server_name"))
            _add(out, server, action)
    return out


def _busy(status: Optional[dict], action: str) -> bool:
    ep = ((status or {}).get("endpoints") or {}).get(action) or {}
    return bool(ep.get("active_dict"))


def check(requires, world_cfg, endpoints, status, *, inferred_only=False) -> list:
    """One row per required (server, action); see the module docstring."""
    servers = (world_cfg or {}).get("servers") or {}
    rows = []
    for server, actions in (requires or {}).items():
        eps = endpoints.get(server)
        st = status.get(server)
        for action in actions:
            in_config = server in servers
            reachable = eps is not None
            has_endpoint = reachable and action in eps
            estopped = bool((st or {}).get("estop"))
            busy = _busy(st, action)
            failed = not (in_config and reachable and has_endpoint) or estopped
            verdict = "fail" if failed else ("warn" if busy else "ok")
            if inferred_only and verdict == "fail":
                verdict = "warn"
            rows.append(
                {
                    "server": server,
                    "action": action,
                    "in_config": in_config,
                    "reachable": reachable,
                    "has_endpoint": has_endpoint,
                    "estopped": estopped,
                    "busy": busy,
                    "verdict": verdict,
                }
            )
    return rows
```

- [ ] **Step 4: Run tests**

Same command as Step 2. Expected: 6 passed. Mutations: drop `or estopped`, so the estop test fails; drop the `inferred_only` downgrade, so its test fails. Revert.

- [ ] **Step 5: Commit**

```bash
black helao/core/runners/requirements.py helao/core/tests/test_runner_requirements.py
git -C /mnt/STORAGE/repos/helao/helao-async add helao/core/runners/requirements.py helao/core/tests/test_runner_requirements.py docs/superpowers/specs/2026-11-17-runners-page-design.md
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(runners): requirement inference and check"
```

---

### Task 3: Launcher (`--describe` and run mode)

**Files:**
- Create: `helao/core/runners/launch.py`
- Test: `helao/core/tests/test_runner_launch.py`

**Interfaces:**
- Consumes: `RunnerStopped`, `request_stop` (Task 1); `inferred` (Task 2); `read_config` (`helao.helpers.config_loader`); `arm_parent_death_signal` (`helao.helpers.parent_death`); `MicroOrch`, `derive_rpc_port`.
- Produces: CLI `python -m helao.core.runners.launch --describe <module>` and `python -m helao.core.runners.launch <config> <module> [--key K] [--params JSON] [--host H]`. Functions `describe(module_name) -> dict`, `default_key(module_name) -> str`, `coerce(params: dict, sig: inspect.Signature) -> dict` (raises `ValueError` naming the field), `free_port() -> int`. Exit codes: 0 clean (including stop), 1 runner exception or describe error, 2 usage error, 130 forced stop.

- [ ] **Step 1: Write the failing tests**

```python
"""Runner launcher: describe, coercion, signals (spec: Launcher)."""

import json
import os
import signal
import subprocess
import sys
import textwrap
import time

import pytest

from helao.core.runners import launch

PY = sys.executable
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _env(tmp_path):
    return {**os.environ, "PYTHONPATH": f"{tmp_path}{os.pathsep}{REPO}"}


def _write(tmp_path, name, body):
    (tmp_path / f"{name}.py").write_text(textwrap.dedent(body), encoding="utf-8")


GOOD = '''
"""Demo runner.

Longer text."""
from helao.core.runners.micro_orch import MicroOrch
REQUIRES = {"SIM": ["acquire_data"]}

async def run(orch: MicroOrch, n: int = 2, label: str = "x"):
    return None
'''


def test_describe_good_module(tmp_path):
    _write(tmp_path, "demo_runner", GOOD)
    out = subprocess.run(
        [PY, "-m", "helao.core.runners.launch", "--describe", "demo_runner"],
        capture_output=True, text=True, env=_env(tmp_path), timeout=60,
    )
    assert out.returncode == 0, out.stderr
    d = json.loads(out.stdout)
    assert d["args"] == ["n", "label"] and d["defaults"] == [2, "x"]
    assert d["argtypes"] == ["int", "str"]
    assert d["requires"] == {"SIM": ["acquire_data"]}
    assert d["doc"].startswith("Demo runner.")


@pytest.mark.parametrize("body", ["def nope(:\n", "x = 1\n", "def run(orch):\n    pass\n"])
def test_describe_bad_module_errors(tmp_path, body):
    _write(tmp_path, "bad_runner", body)
    out = subprocess.run(
        [PY, "-m", "helao.core.runners.launch", "--describe", "bad_runner"],
        capture_output=True, text=True, env=_env(tmp_path), timeout=60,
    )
    assert out.returncode == 1
    assert "error" in json.loads(out.stdout)


def test_default_key():
    assert launch.default_key("helao.deploy.test.runners.simulatews_runner") == "SIMULATEWS"
    assert launch.default_key("pkg.my_thing") == "MY_THING"


def test_coerce_types_and_unknown():
    import inspect

    async def run(orch, n: int = 1, f: float = 1.0, b: bool = False, s: str = "", raw=None):
        ...

    sig = inspect.signature(run)
    assert launch.coerce({"n": "3", "f": "2.5", "b": "true", "s": 5, "raw": [1]}, sig) == {
        "n": 3, "f": 2.5, "b": True, "s": "5", "raw": [1]}
    with pytest.raises(ValueError, match="nope"):
        launch.coerce({"nope": 1}, sig)
    with pytest.raises(ValueError, match="n"):
        launch.coerce({"n": "abc"}, sig)


SLOW = '''
import asyncio
from helao.core.runners.micro_orch import MicroOrch, RunnerStopped
async def run(orch: MicroOrch):
    print("started", flush=True)
    while True:
        await asyncio.sleep(0.05)
        if orch.stop_requested:
            print("saw-stop", flush=True)
            raise RunnerStopped("stop")
'''

BOOM = '''
from helao.core.runners.micro_orch import MicroOrch
async def run(orch: MicroOrch):
    raise RuntimeError("boom")
'''


def _cfg(tmp_path):
    p = tmp_path / "cfg.yml"
    p.write_text(f"root: {tmp_path}\nservers: {{}}\n", encoding="utf-8")
    return str(p)


def _spawn(tmp_path, module):
    return subprocess.Popen(
        [PY, "-m", "helao.core.runners.launch", _cfg(tmp_path), module, "--host", "127.0.0.1"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=_env(tmp_path),
    )


def _wait_line(p, text, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        line = p.stdout.readline()
        if text in line:
            return True
    return False


def test_sigterm_is_clean_stop(tmp_path):
    _write(tmp_path, "slow_runner", SLOW)
    p = _spawn(tmp_path, "slow_runner")
    assert _wait_line(p, "started")
    p.send_signal(signal.SIGTERM)
    assert _wait_line(p, "saw-stop")
    assert p.wait(timeout=30) == 0


def test_second_sigterm_forces_130(tmp_path):
    _write(tmp_path, "stuck_runner", SLOW.replace("if orch.stop_requested:", "if False:"))
    p = _spawn(tmp_path, "stuck_runner")
    assert _wait_line(p, "started")
    p.send_signal(signal.SIGTERM)
    time.sleep(0.5)
    p.send_signal(signal.SIGTERM)
    assert p.wait(timeout=30) == 130


def test_exception_exits_1(tmp_path):
    _write(tmp_path, "boom_runner", BOOM)
    p = _spawn(tmp_path, "boom_runner")
    assert p.wait(timeout=60) == 1


def test_key_clash_exits_2(tmp_path):
    _write(tmp_path, "slow_runner", SLOW)
    cfg = tmp_path / "cfg.yml"
    cfg.write_text(
        f"root: {tmp_path}\nservers:\n  SLOW:\n    host: 127.0.0.1\n    port: 1\n",
        encoding="utf-8",
    )
    out = subprocess.run(
        [PY, "-m", "helao.core.runners.launch", str(cfg), "slow_runner"],
        capture_output=True, text=True, env=_env(tmp_path), timeout=60,
    )
    assert out.returncode == 2
```

If `read_config` rejects a config path without a `servers` schema or without the `helao/deploy/*/configs/` location, report NEEDS_CONTEXT with the error. Do not change `read_config`.

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_runner_launch.py -q`
Expected: FAIL, `ImportError` on `launch`.

- [ ] **Step 3: Implement `helao/core/runners/launch.py`**

```python
"""Run or describe a runner module (spec: Launcher).

    python -m helao.core.runners.launch --describe <module>
    python -m helao.core.runners.launch <config> <module> [--key K] [--params JSON] [--host H]
"""

import argparse
import asyncio
import importlib
import inspect
import json
import os
import random
import signal
import socket
import sys
from typing import Optional

from helao.core.rpc import derive_rpc_port
from helao.core.runners.micro_orch import MicroOrch, RunnerStopped
from helao.core.runners.requirements import inferred
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

PORT_WINDOW = (20000, 40000)
TYPES = {"int": int, "float": float, "str": str, "bool": bool}


def default_key(module_name: str) -> str:
    """``pkg.simulatews_runner`` -> ``SIMULATEWS``."""
    last = module_name.rsplit(".", 1)[-1].upper()
    return last[: -len("_RUNNER")] if last.endswith("_RUNNER") else last


def _run_func(mod):
    fn = getattr(mod, "run", None)
    if not inspect.iscoroutinefunction(fn):
        raise TypeError("no async run(orch, ...)")
    params = list(inspect.signature(fn).parameters.values())
    if not params:
        raise TypeError("run() takes no orch argument")
    return fn, params[1:]


def _type_name(ann) -> str:
    return ann.__name__ if isinstance(ann, type) and ann.__name__ in TYPES else "unspecified"


def describe(module_name: str) -> dict:
    """The describe JSON; raises on import or contract failure."""
    mod = importlib.import_module(module_name)
    fn, params = _run_func(mod)
    for p in params:
        if p.default is inspect.Parameter.empty:
            raise TypeError(f"run() parameter '{p.name}' has no default")
    try:
        source = inspect.getsource(mod)
    except (OSError, TypeError):
        source = ""
    requires = getattr(mod, "REQUIRES", None)
    return {
        "module": module_name,
        "doc": inspect.getdoc(fn) or inspect.getdoc(mod) or "",
        "args": [p.name for p in params],
        "defaults": [p.default for p in params],
        "argtypes": [_type_name(p.annotation) for p in params],
        "requires": requires if isinstance(requires, dict) else None,
        "inferred": inferred(source),
    }


def _to_bool(v):
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off", ""):
        return False
    raise ValueError(f"not a bool: {v!r}")


def coerce(params: dict, sig: inspect.Signature) -> dict:
    """Coerce ``params`` by ``run``'s annotations; ValueError names the field."""
    known = {n: p for n, p in list(sig.parameters.items())[1:]}
    out = {}
    for name, value in params.items():
        if name not in known:
            raise ValueError(f"unknown parameter '{name}'")
        ann = known[name].annotation
        try:
            if ann is bool:
                out[name] = _to_bool(value)
            elif ann in (int, float, str):
                out[name] = ann(value)
            else:
                out[name] = value
        except (TypeError, ValueError) as exc:
            raise ValueError(f"parameter '{name}': {exc}") from exc
    return out


def _bindable(port: int) -> bool:
    for p in (port, derive_rpc_port(port)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", p))
            except OSError:
                return False
    return True


def free_port() -> int:
    """A port whose derived RPC port is also free (low window: no offset overflow)."""
    lo, hi = PORT_WINDOW
    start = random.randint(lo, hi - 1)
    for i in range(hi - lo):
        port = lo + (start - lo + i) % (hi - lo)
        if _bindable(port):
            return port
    raise RuntimeError("no free port pair")


def _reflex_host(world_cfg: dict) -> str:
    for cfg in (world_cfg.get("servers") or {}).values():
        if isinstance(cfg, dict) and cfg.get("reflex"):
            host = cfg.get("host") or "127.0.0.1"
            return "127.0.0.1" if host == "0.0.0.0" else host
    return "127.0.0.1"


async def _run(world_cfg, module_name, key, params, host) -> int:
    mod = importlib.import_module(module_name)
    fn, _ = _run_func(mod)
    loop = asyncio.get_running_loop()
    orch = MicroOrch(server_key=key, host=host, port=free_port(), world_cfg=world_cfg)
    hits = {"n": 0}
    task_box: dict = {}

    def on_signal():
        hits["n"] += 1
        if hits["n"] == 1:
            LOGGER.info(f"runner {key}: stop requested")
            orch.request_stop()
        elif "task" in task_box:
            task_box["task"].cancel()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, on_signal)
    async with orch:
        task_box["task"] = asyncio.create_task(fn(orch, **params))
        try:
            await task_box["task"]
        except RunnerStopped:
            LOGGER.info(f"runner {key}: stopped")
            return 0
        except asyncio.CancelledError:
            LOGGER.warning(f"runner {key}: forced stop")
            return 130
        except Exception:
            LOGGER.exception(f"runner {key} failed")
            return 1
    return 0


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(prog="helao.core.runners.launch")
    ap.add_argument("--describe", metavar="MODULE")
    ap.add_argument("config", nargs="?")
    ap.add_argument("module", nargs="?")
    ap.add_argument("--key")
    ap.add_argument("--params", default="{}")
    ap.add_argument("--host")
    args = ap.parse_args(argv)

    if args.describe:
        try:
            print(json.dumps(describe(args.describe), default=str))
            return 0
        except Exception as exc:
            print(json.dumps({"module": args.describe, "error": f"{type(exc).__name__}: {exc}"}))
            return 1

    if not (args.config and args.module):
        ap.print_usage(sys.stderr)
        return 2
    from helao.helpers.config_loader import read_config
    from helao.helpers.parent_death import arm_parent_death_signal

    arm_parent_death_signal()
    world_cfg = read_config(args.config)
    key = args.key or default_key(args.module)
    if key in (world_cfg.get("servers") or {}):
        print(f"key {key!r} is a server key in the config", file=sys.stderr)
        return 2
    try:
        mod = importlib.import_module(args.module)
        _run_func(mod)
        params = coerce(json.loads(args.params), inspect.signature(mod.run))
    except (ValueError, TypeError, ImportError, json.JSONDecodeError) as exc:
        print(f"usage error: {exc}", file=sys.stderr)
        return 2
    host = args.host or _reflex_host(world_cfg)
    return asyncio.run(_run(world_cfg, args.module, key, params, host))


if __name__ == "__main__":
    sys.exit(main())
```

Check `arm_parent_death_signal()`'s real signature before calling it; it reads `PARENT_PID_ENV` itself.

- [ ] **Step 4: Run tests**

Same command as Step 2. Expected: all pass. Mutations: (a) the first signal cancels the task instead of `request_stop`, so `test_sigterm_is_clean_stop` fails; (b) `coerce` skips the unknown-name check, so the coerce test fails. Revert.

- [ ] **Step 5: Commit**

```bash
black helao/core/runners/launch.py helao/core/tests/test_runner_launch.py
git -C /mnt/STORAGE/repos/helao/helao-async add helao/core/runners/launch.py helao/core/tests/test_runner_launch.py
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(runners): launcher with --describe and cooperative SIGTERM"
```

---

### Task 4: Migrate the test runners to the contract

**Files:**
- Modify: `helao/deploy/test/runners/simulatews_runner.py`, `test_runner.py`, `oersim_runner.py`
- Test: `helao/core/tests/test_test_runners_contract.py`

**Interfaces:**
- Consumes: `launch.describe` (Task 3).
- Produces: each module has `REQUIRES` and `async def run(orch: MicroOrch, ...)` whose parameters are the old module constants with the same defaults; there is no `WORLD_CFG`, `ROOT`, `main`, or MicroOrch construction.

Rules for all three files:
- Every module constant that tunes the run (e.g. `WAIT_TIME`, `DATA_DURATION`, `PLATE_ID`, `INIT_RANDOM_POINTS`, `ITERATIONS`, `CYCLES`, `SAMPLES`) becomes a `run` parameter, lower-cased, with the same default and an annotation.
- A tuple default stays a tuple; its annotation is omitted, so it renders as text.
- `ROOT`-based paths (zip archives) use `orch.world_cfg["root"]`.
- Helper functions (`_act`, `_inject`, `_capture`, scenario coroutines) stay and take values as arguments instead of reading globals.
- `test_runner.py` gains `scenario: str = "both"` (`"noblocking"`, `"conditional"`, `"both"`) that selects which of its two scenario coroutines run.
- Keep each module docstring, and update its "Run" section to `python -m helao.core.runners.launch <config> helao.deploy.test.runners.<name>`.

`simulatews_runner.py` after migration:

```python
"""MicroOrch equivalent of ``SIM_websocket_data`` (test.yml).

wait, acquire_data, wait, acquire_data on ORCH and SIM, dispatched over RPC.

Run::

    python -m helao.core.runners.launch test helao.deploy.test.runners.simulatews_runner
"""

from __future__ import annotations

import os
from typing import Optional

from helao.core.models.machine import MachineModel
from helao.core.runners.micro_orch import MicroOrch
from helao.helpers.premodels import Action

REQUIRES = {"ORCH": ["wait"], "SIM": ["acquire_data"]}


def _act(server: str, name: str, params: Optional[dict] = None) -> Action:
    """Build a one-off action targeting ``server`` (host/port resolved from cfg)."""
    return Action(
        action_name=name,
        action_server=MachineModel(server_name=server),
        action_params=params or {},
    )


async def run(orch: MicroOrch, wait_time: float = 3.0, data_duration: float = 5.0) -> None:
    """wait -> acquire -> wait -> acquire on ORCH and SIM."""
    acquisitions = []
    for i in range(2):
        await orch.run_action(_act("ORCH", "wait", {"waittime": wait_time}))
        act = await orch.run_action(
            _act("SIM", "acquire_data", {"duration": data_duration})
        )
        acquisitions.append(act)
        print(f"acquire {i + 1}/2: action {act.action_uuid} -> {act.yml_path}")
    zip_path = os.path.join(orch.world_cfg["root"], "simulatews_microorch_runs.zip")
    orch.zip_runs(zip_path)
    print(f"ran {len(acquisitions)} acquisitions; archived -> {zip_path}")
```

The other two follow the same rules. Their `REQUIRES` lists every literal `_act(...)` pair in the file; compare with `inferred(source)` to be sure none is missed.

- [ ] **Step 1: Write the failing test**

```python
"""The test deployment's runners follow the runner contract."""

import pytest

from helao.core.runners.launch import describe

EXPECTED = {
    "helao.deploy.test.runners.simulatews_runner": {"wait_time": 3.0, "data_duration": 5.0},
    "helao.deploy.test.runners.oersim_runner": {
        "plate_id": 2750, "init_random_points": 5, "iterations": 8},
    "helao.deploy.test.runners.test_runner": {
        "wait_time": 0.2, "cycles": 2, "scenario": "both"},
}


@pytest.mark.parametrize("module", sorted(EXPECTED))
def test_runner_contract(module):
    d = describe(module)
    got = dict(zip(d["args"], d["defaults"]))
    for name, default in EXPECTED[module].items():
        assert got[name] == default
    assert d["requires"], "REQUIRES declared"
    for server, actions in d["inferred"].items():
        assert set(actions) <= set(d["requires"].get(server, [])), (server, actions)
```

Before writing the expected values, read the other module constants of `oersim_runner.py` and `test_runner.py`. Add every one of them to `EXPECTED` with its current default; the dicts above are the minimum.

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_test_runners_contract.py -q`
Expected: FAIL (`TypeError: no async run(orch, ...)`).

- [ ] **Step 3: Migrate the three files** as specified above.

- [ ] **Step 4: Run tests**

Same command as Step 2. Then check that nothing else imported the removed names: `grep -rn "simulatews_runner\|oersim_runner\|test_runner\.\(main\|WORLD_CFG\)" helao harness --include=*.py`. Update any hit, or report it.

- [ ] **Step 5: Commit**

```bash
black helao/deploy/test/runners/*.py helao/core/tests/test_test_runners_contract.py
git -C /mnt/STORAGE/repos/helao/helao-async add helao/deploy/test/runners helao/core/tests/test_test_runners_contract.py
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "refactor(test runners): run(orch, ...) contract with REQUIRES"
```

---

### Task 5: Page backend (catalog, probes, process registry, overlap)

**Files:**
- Create: `helao/ui/reflex/runner_procs.py`
- Modify: `helao/ui/shared/operator/param_store.py` (`PARAM_KINDS = ("seq", "exp", "runner")`)
- Test: `helao/core/tests/test_runner_procs.py`

**Interfaces:**
- Consumes: the launcher CLI (Task 3); `check` (Task 2); `group.feed_keys`, `group.feed_for`, `group.latest_frame`, `group.REGISTRY` (existing); `async_private_dispatcher`.
- Produces:
  - `deployment_of(world_cfg) -> Optional[str]` (from `loaded_config_path` `.../helao/deploy/<dep>/configs/...`)
  - `runner_modules(deployment, repo_root) -> list[str]` (dotted names)
  - `async describe_all(modules, repo_root=None) -> list[dict]` (10 s per describe via `DESCRIBE_TIMEOUT_S`). Each entry is the describe JSON plus `"mtime"`, or `{"module", "error", "mtime"}`.
  - `CATALOG: dict[str, dict]` (module → entry) and `async refresh_catalog(world_cfg, repo_root) -> list[dict]`
  - `async probe(servers: list[str], world_cfg) -> tuple[dict, dict]` (endpoints, status)
  - `class RunnerProc` (`key, module, pid, started, state, rc, log_path, proc`)
  - `PROCS: dict[str, RunnerProc]`
  - `async launch(world_cfg, module, key, params: dict) -> RunnerProc` (raises `ValueError` on a duplicate key)
  - `stop(key) -> None`, `force_kill(key) -> None`, `dismiss(key) -> None`
  - `overlap() -> dict[str, list[str]]` (server → feed keys busy on it, only where 2 or more)

- [ ] **Step 1: Write the failing tests**

```python
"""/runners backend: catalog, probes, processes, overlap."""

import asyncio
import os
import sys
import textwrap

import pytest

from helao.ui.reflex import runner_procs as rp

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def test_deployment_of():
    cfg = {"loaded_config_path": "/x/helao/deploy/test/configs/goldenreflex.yml"}
    assert rp.deployment_of(cfg) == "test"
    assert rp.deployment_of({}) is None


def _pkg(tmp_path):
    runners = tmp_path / "helao" / "deploy" / "zz" / "runners"
    runners.mkdir(parents=True)
    for d in (tmp_path / "helao", tmp_path / "helao" / "deploy", tmp_path / "helao" / "deploy" / "zz", runners):
        (d / "__init__.py").write_text("", encoding="utf-8")
    return runners


GOOD = "from helao.core.runners.micro_orch import MicroOrch\nasync def run(orch: MicroOrch, n: int = 1):\n    pass\n"


@pytest.mark.asyncio
async def test_catalog_lists_broken_module_with_error(tmp_path, monkeypatch):
    runners = _pkg(tmp_path)
    (runners / "good_runner.py").write_text(GOOD, encoding="utf-8")
    (runners / "bad_runner.py").write_text("raise RuntimeError('top level')\n", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", f"{tmp_path}{os.pathsep}{REPO}")
    mods = rp.runner_modules("zz", str(tmp_path))
    assert mods == ["helao.deploy.zz.runners.bad_runner", "helao.deploy.zz.runners.good_runner"]
    entries = {e["module"]: e for e in await rp.describe_all(mods)}
    assert "error" in entries["helao.deploy.zz.runners.bad_runner"]
    assert entries["helao.deploy.zz.runners.good_runner"]["args"] == ["n"]


@pytest.mark.asyncio
async def test_refresh_sees_add_edit_delete(tmp_path, monkeypatch):
    runners = _pkg(tmp_path)
    (runners / "a_runner.py").write_text(GOOD, encoding="utf-8")
    (runners / "b_runner.py").write_text(GOOD, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", f"{tmp_path}{os.pathsep}{REPO}")
    cfg = {"loaded_config_path": f"{tmp_path}/helao/deploy/zz/configs/c.yml"}
    await rp.refresh_catalog(cfg, str(tmp_path))
    (runners / "a_runner.py").write_text(GOOD.replace("n: int = 1", "n: int = 7"), encoding="utf-8")
    (runners / "b_runner.py").unlink()
    (runners / "c_runner.py").write_text(GOOD, encoding="utf-8")
    entries = {e["module"].rsplit(".", 1)[-1]: e for e in await rp.refresh_catalog(cfg, str(tmp_path))}
    assert set(entries) == {"a_runner", "c_runner"}
    assert entries["a_runner"]["defaults"] == [7]


@pytest.mark.asyncio
async def test_probe_unreachable_server_fails_rows(monkeypatch):
    async def fake(server, host, port, path, **kw):
        assert kw.get("timeout") == 5 and kw.get("retries") == 1
        return None, "http"

    monkeypatch.setattr(rp, "async_private_dispatcher", fake)
    eps, st = await rp.probe(["SIM"], {"servers": {"SIM": {"host": "h", "port": 1}}})
    assert eps == {"SIM": None} and st == {"SIM": None}


SLOW = (
    "import asyncio, signal\n"
    "from helao.core.runners.micro_orch import MicroOrch\n"
    "async def run(orch: MicroOrch):\n"
    "    await asyncio.sleep(3600)\n"
)


@pytest.mark.asyncio
async def test_launch_refuses_duplicate_key_and_stop_kill(tmp_path, monkeypatch):
    runners = _pkg(tmp_path)
    (runners / "slow_runner.py").write_text(SLOW, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", f"{tmp_path}{os.pathsep}{REPO}")
    cfg = tmp_path / "cfg.yml"
    cfg.write_text(f"root: {tmp_path}\nservers: {{}}\n", encoding="utf-8")
    world = {"root": str(tmp_path), "servers": {}, "loaded_config_path": str(cfg)}
    rp.PROCS.clear()
    p = await rp.launch(world, "helao.deploy.zz.runners.slow_runner", "SLOW", {})
    try:
        assert p.state == "running" and os.path.exists(p.log_path)
        with pytest.raises(ValueError, match="SLOW"):
            await rp.launch(world, "helao.deploy.zz.runners.slow_runner", "SLOW", {})
        rp.stop("SLOW")
        assert rp.PROCS["SLOW"].state == "stopping"
        await asyncio.sleep(1.0)
        rp.force_kill("SLOW")
        await asyncio.wait_for(p.proc.wait(), 30)
        await asyncio.sleep(0.1)
        assert rp.PROCS["SLOW"].state in ("killed", "exited")
    finally:
        if p.proc.returncode is None:
            p.proc.kill()


def test_overlap(monkeypatch):
    frames = {
        "ORCH": {"servers": [{"key": "SIM", "status": "busy"}, {"key": "PSTAT", "status": "idle"}]},
        "R1": {"servers": [{"key": "SIM", "status": "busy"}]},
    }
    monkeypatch.setattr(rp.group, "feed_keys", lambda: list(frames))
    monkeypatch.setattr(rp.group, "feed_for", lambda k: k)
    monkeypatch.setattr(rp.group, "latest_frame", lambda feed: frames[feed])
    assert rp.overlap() == {"SIM": ["ORCH", "R1"]}
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_runner_procs.py -q`
Expected: FAIL, `ImportError`.

- [ ] **Step 3: Implement `helao/ui/reflex/runner_procs.py`**

```python
"""Backend of the /runners page (spec: Page). No Reflex imports.

The page never imports runner code: the catalog comes from the launcher's
``--describe`` subprocesses, so edits, additions and deletions show on Refresh.
"""

import asyncio
import json
import os
import re
import signal
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

from helao.helpers import helao_logging as logging
from helao.helpers.dispatcher import async_private_dispatcher
from helao.helpers.parent_death import PARENT_PID_ENV
from helao.ui.reflex import group

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

DESCRIBE_TIMEOUT_S = 10.0
PROBE = {"timeout": 5, "retries": 1}
LAUNCH = [sys.executable, "-m", "helao.core.runners.launch"]
_DEP_RE = re.compile(r"helao[\\/]deploy[\\/]([^\\/]+)[\\/]configs[\\/]")

CATALOG: dict = {}
PROCS: dict = {}


def deployment_of(world_cfg: dict) -> Optional[str]:
    m = _DEP_RE.search(str((world_cfg or {}).get("loaded_config_path") or ""))
    return m.group(1) if m else None


def runner_modules(deployment: str, repo_root: str) -> list:
    folder = os.path.join(repo_root, "helao", "deploy", deployment, "runners")
    if not os.path.isdir(folder):
        return []
    return sorted(
        f"helao.deploy.{deployment}.runners.{f[:-3]}"
        for f in os.listdir(folder)
        if f.endswith(".py") and f != "__init__.py"
    )


def _module_file(module: str, repo_root: str) -> str:
    return os.path.join(repo_root, *module.split(".")) + ".py"


async def _describe(module: str) -> dict:
    proc = await asyncio.create_subprocess_exec(
        *LAUNCH, "--describe", module,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), DESCRIBE_TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        return {"module": module, "error": f"describe timed out after {DESCRIBE_TIMEOUT_S:.0f} s"}
    try:
        return json.loads(out.decode("utf-8"))
    except ValueError:
        tail = err.decode("utf-8", "replace").strip().splitlines()[-1:] or ["no output"]
        return {"module": module, "error": tail[0]}


async def describe_all(modules: list, repo_root: Optional[str] = None) -> list:
    entries = await asyncio.gather(*(_describe(m) for m in modules))
    for e in entries:
        path = _module_file(e["module"], repo_root) if repo_root else None
        e["mtime"] = os.path.getmtime(path) if path and os.path.exists(path) else None
    return list(entries)


async def refresh_catalog(world_cfg: dict, repo_root: str) -> list:
    dep = deployment_of(world_cfg)
    entries = await describe_all(runner_modules(dep, repo_root), repo_root) if dep else []
    CATALOG.clear()
    CATALOG.update({e["module"]: e for e in entries})
    return entries


async def probe(servers: list, world_cfg: dict) -> tuple:
    cfg = (world_cfg or {}).get("servers") or {}

    async def one(key):
        c = cfg.get(key)
        if not c:
            return key, None, None
        try:
            eps, err = await async_private_dispatcher(
                key, c["host"], c["port"], "endpoints", json_dict={}, **PROBE
            )
        except Exception:
            return key, None, None
        if err != ErrorCodes.none or not isinstance(eps, list):
            return key, None, None
        names = [
            str(d.get("path", "")).strip("/").split("/")[-1]
            for d in eps
            if isinstance(d, dict)
        ]
        try:
            st, err2 = await async_private_dispatcher(
                key, c["host"], c["port"], "get_status", json_dict={}, **PROBE
            )
        except Exception:
            st, err2 = None, None
        ok = err2 == ErrorCodes.none and isinstance(st, dict)
        return key, names, st if ok else None

    results = await asyncio.gather(*(one(k) for k in servers))
    return {k: e for k, e, _ in results}, {k: s for k, _, s in results}


@dataclass
class RunnerProc:
    key: str
    module: str
    log_path: str
    proc: object
    started: float = field(default_factory=time.time)
    state: str = "running"
    rc: Optional[int] = None

    @property
    def pid(self) -> int:
        return self.proc.pid


def _taken(key: str) -> bool:
    p = PROCS.get(key)
    if p is not None and p.state in ("running", "stopping"):
        return True
    entry = group.REGISTRY.get(key)
    return entry is not None and not entry.lost(time.time())


async def _watch(p: RunnerProc) -> None:
    p.rc = await p.proc.wait()
    if p.state != "killed":
        p.state = "exited"


async def launch(world_cfg: dict, module: str, key: str, params: dict) -> RunnerProc:
    if _taken(key):
        raise ValueError(f"key {key} is already running")
    logs = os.path.join(world_cfg["root"], "LOGS")
    os.makedirs(logs, exist_ok=True)
    log_path = os.path.join(logs, f"runner_{key}_{time.strftime('%Y%m%d-%H%M%S')}.log")
    log = open(log_path, "w", encoding="utf-8")
    env = {**os.environ, PARENT_PID_ENV: str(os.getpid())}
    proc = await asyncio.create_subprocess_exec(
        *LAUNCH, world_cfg["loaded_config_path"], module,
        "--key", key, "--params", json.dumps(params),
        stdout=log, stderr=asyncio.subprocess.STDOUT, env=env,
    )
    log.close()
    p = RunnerProc(key=key, module=module, log_path=log_path, proc=proc)
    PROCS[key] = p
    asyncio.get_running_loop().create_task(_watch(p))
    return p


def stop(key: str) -> None:
    p = PROCS.get(key)
    if p and p.state == "running":
        p.proc.send_signal(signal.SIGTERM)
        p.state = "stopping"


def force_kill(key: str) -> None:
    p = PROCS.get(key)
    if p and p.state in ("running", "stopping"):
        p.proc.kill()
        p.state = "killed"


def dismiss(key: str) -> None:
    p = PROCS.get(key)
    if p and p.state not in ("running", "stopping"):
        del PROCS[key]


def overlap() -> dict:
    busy: dict = {}
    for k in group.feed_keys():
        frame = group.latest_frame(group.feed_for(k)) or {}
        for row in frame.get("servers", []):
            if row.get("status") == "busy":
                busy.setdefault(row["key"], []).append(k)
    return {s: ks for s, ks in busy.items() if len(ks) > 1}
```

Add `from helao.core.error import ErrorCodes` to the imports. The probe test's fake returns `(None, "http")`, which is `!= ErrorCodes.none`, so the server reads as unreachable. Keep each `_watch` task in a module-level `_WATCHERS: set` with `add_done_callback(_WATCHERS.discard)`, so it is not garbage-collected.

- [ ] **Step 4: Run tests**

Same command as Step 2. Expected: all pass. Mutations: (a) `_taken` always False, so the duplicate test fails; (b) `refresh_catalog` without `CATALOG.clear()` and with entries merged, so the delete is not seen and the refresh test fails. Revert.

- [ ] **Step 5: Commit**

```bash
black helao/ui/reflex/runner_procs.py helao/ui/shared/operator/param_store.py helao/core/tests/test_runner_procs.py
git -C /mnt/STORAGE/repos/helao/helao-async add helao/ui/reflex/runner_procs.py helao/ui/shared/operator/param_store.py helao/core/tests/test_runner_procs.py
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(reflex): /runners backend (catalog via describe, probes, process registry)"
```

---

### Task 6: /runners page, route, nav

**Files:**
- Create: `helao/ui/reflex/runners.py`
- Modify: `helao/ui/reflex/app.py` (`SHELL_ROUTES` ~157, nav menu tuple ~455, `add_page` beside `/group` ~761, a configure call beside `configure_group` ~691); `helao/ui/shared/palette.py` (`REFLEX_PAGE_TINTS` gains `"/runners"` with an unused `-50` shade; follow the neighbours)
- Test: `helao/core/tests/test_reflex_runners.py`

**Interfaces:**
- Consumes: Task 5 (`runner_procs`), `operator.fields_for_item`, `flatten_fields`, `field_options`, `coerce_params`, `param_store.read_params/write_params/form_values`, `requirements.check`.
- Produces: `configure_runners(world_cfg, repo_root)`, `RunnersState(rx.State)`, `runners_page() -> rx.Component`; helper `item_from_entry(entry) -> dict` (describe JSON → `fields_for_item` input, with argtypes mapped back to types: `{"int": int, "float": float, "str": str, "bool": bool}`, else `"unspecified"`); `stored_values(root, module, fields) -> dict` (drops names no longer in `fields`).

State (backend vars as tuples, per CLAUDE.md):
- `entries` (`list[dict]` of `{module, name, summary, mtime, error}` for display); `selected: str`; `fields_rows` (`list[list[str]]`); `field_opts`; `values: dict[str, str]`.
- `req_rows` (`list[list[str]]`: server, action, verdict, detail); `req_note` ("declared" | "inferred, may be incomplete" | "none"); `blocked: bool`; `override: bool`.
- `key: str`; `error: str`; `procs` (`list[list[str]]`: key, module, pid, started, state, rc, log); `overlap_rows`.

Events:
- `mount` → `refresh`.
- `refresh` (background): `await runner_procs.refresh_catalog(...)`, then update `entries`. If `selected` vanished, clear it.
- `select(module)`: build the form from `CATALOG[module]`, prefill `values` from `stored_values`, set `key` to `launch.default_key(module)`, then call `recheck`.
- `recheck` (background): requirements = declared or inferred, then `runner_procs.probe`, then `requirements.check(..., inferred_only=not declared)`. Set `blocked` if any row fails.
- `set_value(name, v)`; `toggle_override`.
- `launch_selected` (background):
  - `coerce_params(fields, values)`; on errors set `error` and return without spawning;
  - if `blocked and not override`, refuse;
  - otherwise `write_params(root, "runner", module, params)`, then `await runner_procs.launch(...)`; a `ValueError` goes to `error`.
- `stop(key)`, `force_kill(key)`, `dismiss(key)`.
- `tick` (`rx.moment`, 2 s): copy `PROCS` and `overlap()` into the display vars only when they changed.

Layout:
- Left: the catalog list, with a Refresh button and greyed error rows.
- Right: the selected runner's docstring, form, requirement checklist with a Re-check button, "launch anyway" checkbox, key input, and Launch button.
- Below: the process table, with Stop/Force kill/Dismiss per row and a link `/group` for that key, then the overlap warnings.
- Verdict colours come from palette `GROUP_STATE_COLORS` (`idle`=ok, `busy`=warn, `error`=fail); add no new colours.

- [ ] **Step 1: Write the failing tests**

```python
"""/runners page helpers and launch gating."""

import asyncio

import pytest

from helao.ui.reflex import runners


ENTRY = {
    "module": "m", "doc": "Demo.\n\n:param n: count", "args": ["n", "flag"],
    "defaults": [2, False], "argtypes": ["int", "bool"], "requires": None, "inferred": {},
}


def test_item_from_entry_maps_types():
    item = runners.item_from_entry(ENTRY)
    assert item["argtypes"] == [int, bool]
    assert item["args"] == ["n", "flag"]


def test_stored_values_drop_removed_params(monkeypatch):
    monkeypatch.setattr(runners, "read_params", lambda root, kind, name: {"n": 5, "gone": 1})
    from helao.ui.reflex.operator import fields_for_item

    fields = fields_for_item(runners.item_from_entry(ENTRY))
    assert runners.stored_values("/r", "m", fields) == {"n": "5"}


def test_launch_refuses_bad_params(monkeypatch):
    called = []

    async def fake_launch(*a, **k):
        called.append(a)

    monkeypatch.setattr(runners.runner_procs, "launch", fake_launch)
    err = asyncio.run(runners.try_launch({"root": "/r"}, ENTRY, {"n": "abc"}, "K", blocked=False, override=False))
    assert "n" in err and called == []


def test_launch_blocked_without_override(monkeypatch):
    async def fake_launch(*a, **k):
        raise AssertionError("must not launch")

    monkeypatch.setattr(runners.runner_procs, "launch", fake_launch)
    err = asyncio.run(runners.try_launch({"root": "/r"}, ENTRY, {}, "K", blocked=True, override=False))
    assert "requirement" in err
```

To make the gating testable, `launch_selected` delegates to a plain coroutine `try_launch(world_cfg, entry, values, key, *, blocked, override) -> str`. It returns `""` on success or an error message, and is the only caller of `write_params` and `runner_procs.launch`.

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_reflex_runners.py -q`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Implement** `runners.py` (helpers, `try_launch`, state, page) and the app/palette wiring described above. Follow `logs.py`'s structure for a self-contained page: module-level configure function, `rx.State` subclass created at import, page function. Read `helao/ui/reflex/CLAUDE.md`'s state, `add_page` and tuple-var rules first. Assert `RunnersState is not None` in `build_app` beside the other page states.

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -m pytest helao/core/tests/test_reflex_runners.py helao/core/tests/test_palette.py helao/core/tests/test_reflex_group.py -q` and `PYTHONPATH=$PWD /home/dan/miniforge3/envs/helao/bin/python -c "import helao.ui.reflex.app"`.
Expected: pass; app imports. Mutations: `try_launch` ignores `blocked`, so the blocked test fails; `stored_values` keeps unknown names, so its test fails. Revert.

- [ ] **Step 5: Commit**

```bash
black helao/ui/reflex/runners.py helao/ui/reflex/app.py helao/ui/shared/palette.py helao/core/tests/test_reflex_runners.py
git -C /mnt/STORAGE/repos/helao/helao-async add helao/ui/reflex/runners.py helao/ui/reflex/app.py helao/ui/shared/palette.py helao/core/tests/test_reflex_runners.py
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(reflex): /runners page (catalog, params, requirements, launch/stop)"
```

---

### Task 7: Docs, sweep, live check

**Files:**
- Modify: `helao/core/runners/runner.md` (a "Runner scripts" section: the contract, `REQUIRES`, the launcher commands, Stop semantics); `helao/ui/reflex/CLAUDE.md` (a short `/runners` paragraph: the page never imports runner code, the describe subprocess, process-wide `PROCS`/`CATALOG`, parent-death env); `CLAUDE.md` (one line under the Reflex section naming `/runners`).

- [ ] **Step 1:** Write the docs; check every claim against the code.
- [ ] **Step 2:** Run the full sweep on the branch: `run_tests.py` in the background with a marker file and a separate watcher, `HELAO_SOURCES_ROOT` set to a tmp dir. Compare failures with the known 3 nested-repo failures.
- [ ] **Step 3:** Live check (headless Playwright, scratch venv `playwright==1.62.0`) on `goldenreflex`, covering the spec's Success line:
  - the catalog lists the 3 test runners;
  - `simulatews` requirements are green;
  - Launch shows it on /group;
  - Stop gives exit 0 and deregistration;
  - with SIM stopped, Launch is blocked until "launch anyway" is ticked;
  - add, edit and delete a scratch runner file in `helao/deploy/test/runners/`, then Refresh, and every change shows. Delete the scratch file afterwards and confirm `git status` is clean.
  Teardown by PID only.
- [ ] **Step 4: Commit docs**

```bash
git -C /mnt/STORAGE/repos/helao/helao-async add helao/core/runners/runner.md helao/ui/reflex/CLAUDE.md CLAUDE.md
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "docs: /runners page and runner contract"
```
