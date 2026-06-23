# SP7: Pilot Migration (`test` Deployment) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the `test` deployment (action servers, experiments, sequences, runners, drivers) from `helao.core.*`/`helao.helpers.*` to `helao.framework.*`, proving the framework is deployment-ready.

**Architecture:** Three waves — Wave 1 ports missing support modules and fills framework API gaps; Wave 2 performs import-swaps across all deployment files; Wave 3 adds the migration test suite and verifies the framework gate. All framework additions are TDD-first.

**Tech Stack:** Python 3.12, pytest, httpx (AsyncClient), FastAPI TestClient, conda env `helao`.

## Global Constraints

- Run all tests via: `conda run -n helao python -m pytest helao/framework/tests/ -x -q`
- Coverage gate: `conda run -n helao python helao/framework/_devtools/coverage_gate.py` must pass (≥90% on `domain/`+`models/`)
- Branch: `feat/framework-migrate-test` off `unstable`
- Import-swap files get no logic changes — only `from` lines change
- `helao/deploy/test/servers/visualizer/` — **not touched** (§9 of master spec)
- `helao/deploy/test/demos/` — **not touched**
- `helao/framework/support/dispatcher.py` retains `from helao.core.rpc import ...` (transitional dep — `helao.core.rpc` is a pure ZMQ utility with no server/model coupling)

---

## File Map

**Created (framework additions):**
- `helao/framework/support/lib_decorators.py` — `@experiment`/`@sequence` decorators, rewired to `RunExperiment`
- `helao/framework/support/file_utils.py` — port of `helao.helpers.file_utils`
- `helao/framework/support/dispatcher.py` — port of `helao.helpers.dispatcher`
- `helao/framework/app/server_api.py` — `BaseAPI` compat class wrapping `FrameworkBase` in a FastAPI subclass
- `helao/framework/tests/test_migrate_test_deploy.py` — migration test suite

**Modified (framework gap-fills):**
- `helao/framework/domain/action_session.py` — add `start_executor()` compat method
- `helao/framework/runners/micro_orch.py` — accept `ActionModel` in `run_action` (coerce to `RunAction`)

**Modified (import-swap, no logic change):**
- `helao/deploy/test/servers/action/ws_simulator.py`
- `helao/deploy/test/servers/action/cpsim_server.py`
- `helao/deploy/test/servers/action/gpsim_server.py`
- `helao/deploy/test/servers/action/motion_simulator.py`
- `helao/deploy/test/servers/action/pstat_simulator.py`
- `helao/deploy/test/servers/action/analysis_simulator.py`
- `helao/deploy/test/servers/action/archive_simulator.py`
- `helao/deploy/test/experiments/TEST_exp.py`
- `helao/deploy/test/experiments/OERSIM_exp.py`
- `helao/deploy/test/experiments/simulatews_exp.py`
- `helao/deploy/test/sequences/TEST_seq.py`
- `helao/deploy/test/sequences/OERSIM_seq.py`
- `helao/deploy/test/runners/test_runner.py`
- `helao/deploy/test/runners/oersim_runner.py`
- `helao/deploy/test/runners/simulatews_runner.py`
- `helao/deploy/test/drivers/data/gpsim_driver.py`
- `helao/deploy/test/drivers/pstat/cpsim_driver.py`

---

## Task 1: Port `lib_decorators` to `helao/framework/support/lib_decorators.py`

**Files:**
- Create: `helao/framework/support/lib_decorators.py`
- Test: `helao/framework/tests/test_migrate_test_deploy.py` (create here, extend in Tasks 8-10)

**Interfaces:**
- Consumes: `EXPERIMENT_CTX` from `helao.framework.domain.plan_makers`, `RunExperiment` from `helao.framework.domain.run_models`
- Produces: `experiment(version: int) -> Callable`, `sequence(version: int) -> Callable`

- [ ] **Step 1: Write failing tests**

Create `helao/framework/tests/test_migrate_test_deploy.py`:

```python
"""Migration tests for SP7: test-deployment pilot onto helao.framework.*"""
import pytest
from helao.framework.support.lib_decorators import experiment, sequence
from helao.framework.domain.plan_makers import EXPERIMENT_CTX, ActionPlanMaker
from helao.framework.domain.run_models import RunExperiment


def _make_run_exp(**kw) -> RunExperiment:
    defaults = dict(
        experiment_name="test_exp",
        sequence_name="test_seq",
        sequence_label="test_seq__001",
        experiment_output_dir="26.25/0622/test",
    )
    defaults.update(kw)
    return RunExperiment(**defaults)


def test_experiment_decorator_sets_version():
    @experiment(version=3)
    def my_exp(param: float = 1.0):
        pass
    assert my_exp.experiment_version == 3


def test_experiment_decorator_injects_ctx():
    captured = []

    @experiment(version=1)
    def my_exp():
        captured.append(EXPERIMENT_CTX.get(None))

    run_exp = _make_run_exp()
    my_exp(run_exp)
    assert captured[0] is run_exp


def test_experiment_decorator_resets_ctx_after_call():
    @experiment(version=1)
    def my_exp():
        pass

    assert EXPERIMENT_CTX.get(None) is None
    my_exp(_make_run_exp())
    assert EXPERIMENT_CTX.get(None) is None


def test_experiment_decorator_positional_arg_form():
    received = []

    @experiment(version=1)
    def my_exp(experiment: RunExperiment, extra: int = 0):
        received.append(experiment)

    run_exp = _make_run_exp()
    my_exp(run_exp, extra=7)
    assert received[0] is run_exp


def test_sequence_decorator_sets_version():
    @sequence(version=5)
    def my_seq():
        pass
    assert my_seq.sequence_version == 5
```

- [ ] **Step 2: Run to verify failure**

```
conda run -n helao python -m pytest helao/framework/tests/test_migrate_test_deploy.py -x -q
```

Expected: `ImportError: cannot import name 'experiment' from 'helao.framework.support.lib_decorators'`

- [ ] **Step 3: Write `lib_decorators.py`**

Create `helao/framework/support/lib_decorators.py`:

```python
"""Decorators that tag experiment- and sequence-library functions with a version.

Port of ``helao.helpers.lib_decorators``, rewired to use
:class:`~helao.framework.domain.run_models.RunExperiment` and
:data:`~helao.framework.domain.plan_makers.EXPERIMENT_CTX` from the framework.
"""

__all__ = ["experiment", "sequence"]

import functools
import inspect

from helao.framework.domain.run_models import RunExperiment
from helao.framework.domain.plan_makers import EXPERIMENT_CTX


def _declares_experiment_param(sig: inspect.Signature) -> bool:
    params = [
        p
        for p in sig.parameters.values()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if not params:
        return False
    first = params[0]
    ann = first.annotation
    if isinstance(ann, type) and issubclass(ann, RunExperiment):
        return True
    return first.name == "experiment"


def experiment(version: int = 1):
    """Tag an experiment-library function and supply its parent experiment.

    Ports ``helao.helpers.lib_decorators.experiment`` using
    :class:`RunExperiment` instead of the legacy ``Experiment``.
    """
    def decorator(func):
        sig = inspect.signature(func)
        declares_exp = _declares_experiment_param(sig)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            exp = None
            if args and isinstance(args[0], RunExperiment):
                exp, args = args[0], args[1:]
            if isinstance(kwargs.get("experiment"), RunExperiment):
                exp = kwargs.pop("experiment")
            if exp is None:
                exp = EXPERIMENT_CTX.get(None)
            token = EXPERIMENT_CTX.set(exp)
            try:
                if declares_exp:
                    return func(exp, *args, **kwargs)
                return func(*args, **kwargs)
            finally:
                EXPERIMENT_CTX.reset(token)

        wrapper.experiment_version = version
        wrapper.__signature__ = sig
        return wrapper

    return decorator


def sequence(version: int = 1):
    """Tag a sequence-library function with its library version."""
    def decorator(func):
        func.sequence_version = version
        return func
    return decorator
```

- [ ] **Step 4: Run tests to verify pass**

```
conda run -n helao python -m pytest helao/framework/tests/test_migrate_test_deploy.py::test_experiment_decorator_sets_version helao/framework/tests/test_migrate_test_deploy.py::test_experiment_decorator_injects_ctx helao/framework/tests/test_migrate_test_deploy.py::test_experiment_decorator_resets_ctx_after_call helao/framework/tests/test_migrate_test_deploy.py::test_experiment_decorator_positional_arg_form helao/framework/tests/test_migrate_test_deploy.py::test_sequence_decorator_sets_version -v
```

Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add helao/framework/support/lib_decorators.py helao/framework/tests/test_migrate_test_deploy.py
git commit -m "feat(framework): SP7 wave 1 — lib_decorators support port"
```

---

## Task 2: Port `file_utils` to `helao/framework/support/file_utils.py`

**Files:**
- Create: `helao/framework/support/file_utils.py`
- Test: inline step below (import verification + `file_in_use` smoke)

**Interfaces:**
- Produces: `file_in_use`, `rm_tree`, `rm_tree_async`, `zip_dir`, `unzpickle`, `zpickle`

- [ ] **Step 1: Write failing import test**

Add to `helao/framework/tests/test_migrate_test_deploy.py`:

```python
def test_file_utils_importable():
    from helao.framework.support.file_utils import (
        file_in_use, rm_tree, rm_tree_async, zip_dir, unzpickle, zpickle
    )
    assert callable(file_in_use)
    assert callable(unzpickle)


def test_file_in_use_returns_false_for_nonexistent(tmp_path):
    from helao.framework.support.file_utils import file_in_use
    assert file_in_use(tmp_path / "no_such_file.txt") is False
```

Run: `conda run -n helao python -m pytest helao/framework/tests/test_migrate_test_deploy.py::test_file_utils_importable -x -q`

Expected: `ImportError`

- [ ] **Step 2: Create `file_utils.py`**

Create `helao/framework/support/file_utils.py` — copy of `helao/helpers/file_utils.py` with one change: replace the logging import line:

```python
# OLD (remove):
from helao.helpers import helao_logging as logging

# NEW:
from helao.framework.support import helao_logging as logging
```

The rest of the file is identical (all other imports are stdlib + third-party: `os`, `zipfile`, `pathlib`, `_pickle`, `anyio`, `pyzstd`).

- [ ] **Step 3: Run tests**

```
conda run -n helao python -m pytest helao/framework/tests/test_migrate_test_deploy.py::test_file_utils_importable helao/framework/tests/test_migrate_test_deploy.py::test_file_in_use_returns_false_for_nonexistent -v
```

Expected: 2 PASSED

- [ ] **Step 4: Commit**

```bash
git add helao/framework/support/file_utils.py helao/framework/tests/test_migrate_test_deploy.py
git commit -m "feat(framework): SP7 wave 1 — file_utils support port"
```

---

## Task 3: Port `dispatcher` to `helao/framework/support/dispatcher.py`

**Files:**
- Create: `helao/framework/support/dispatcher.py`
- Test: import-only verification

**Interfaces:**
- Produces: `async_action_dispatcher`, `async_private_dispatcher`, `private_dispatcher`, `aclose_all_rpc_clients`, `close_all_sync_rpc_clients`
- Retains: `from helao.core.rpc import RPCClient, RPCSyncClient, RPCError, derive_rpc_port` (transitional dep)

- [ ] **Step 1: Write failing import test**

Add to `helao/framework/tests/test_migrate_test_deploy.py`:

```python
def test_dispatcher_importable():
    from helao.framework.support.dispatcher import (
        async_action_dispatcher,
        async_private_dispatcher,
        private_dispatcher,
        aclose_all_rpc_clients,
        close_all_sync_rpc_clients,
    )
    assert callable(async_private_dispatcher)
```

Run: `conda run -n helao python -m pytest helao/framework/tests/test_migrate_test_deploy.py::test_dispatcher_importable -x -q`

Expected: `ImportError`

- [ ] **Step 2: Create `dispatcher.py`**

Create `helao/framework/support/dispatcher.py` as a copy of `helao/helpers/dispatcher.py` with these three import changes:

```python
# Remove:
from .premodels import Action
from helao.core.error import ErrorCodes
from helao.helpers import helao_logging as logging

# Replace with:
from helao.framework.models.action import ActionModel as Action
from helao.framework.models.errors import ErrorCodes
from helao.framework.support import helao_logging as logging
```

The `from helao.core.rpc import RPCClient, RPCSyncClient, RPCError, derive_rpc_port` line stays unchanged (transitional dep).

All function bodies are identical.

- [ ] **Step 3: Run test**

```
conda run -n helao python -m pytest helao/framework/tests/test_migrate_test_deploy.py::test_dispatcher_importable -v
```

Expected: PASSED

- [ ] **Step 4: Commit**

```bash
git add helao/framework/support/dispatcher.py helao/framework/tests/test_migrate_test_deploy.py
git commit -m "feat(framework): SP7 wave 1 — dispatcher support port"
```

---

## Task 4: Framework gap-fill — `BaseAPI`, `start_executor`, `MicroOrch` coercion

Deployment servers call `app = BaseAPI(...)`, `active.start_executor(executor)`, and `orch.run_action(ActionModel(...))`. None of these exist in the framework yet. This task fills those three gaps.

**Files:**
- Create: `helao/framework/app/server_api.py`
- Modify: `helao/framework/domain/action_session.py` (add `start_executor`)
- Modify: `helao/framework/runners/micro_orch.py` (coerce `ActionModel → RunAction` in `run_action`)
- Test: add to `test_migrate_test_deploy.py`

**Interfaces:**
- `BaseAPI(server_key, *, driver_classes=None, save_root=None, **fastapi_kwargs)` — FastAPI subclass with `.base: FrameworkBase`, `.driver`, `.drivers: dict`
- `ActionSession.start_executor(executor: Executor) -> dict` — schedules `action_loop_task` as background task, returns `self.action.as_dict()`
- `MicroOrch.run_action(action: Union[ActionModel, RunAction])` — coerces `ActionModel` to `RunAction` if needed

- [ ] **Step 1: Write failing tests**

Add to `helao/framework/tests/test_migrate_test_deploy.py`:

```python
def test_base_api_importable():
    from helao.framework.app.server_api import BaseAPI
    assert BaseAPI is not None


def test_base_api_has_base_attribute(tmp_path):
    from helao.framework.app.server_api import BaseAPI
    from helao.framework.app.base_api import FrameworkBase
    app = BaseAPI("SRV", save_root=str(tmp_path))
    assert isinstance(app.base, FrameworkBase)


def test_base_api_instantiates_driver(tmp_path):
    from helao.framework.app.server_api import BaseAPI
    from helao.framework.app.base_api import FrameworkBase

    class FakeDriver:
        def __init__(self, base: FrameworkBase):
            self.base = base

    app = BaseAPI("SRV", driver_classes=[FakeDriver], save_root=str(tmp_path))
    assert isinstance(app.driver, FakeDriver)
    assert app.driver.base is app.base


def test_action_session_start_executor(tmp_path):
    import asyncio
    from helao.framework.app.base_api import FrameworkBase, ActionContext
    from helao.framework.adapters.fs_storage import FsStorage
    from helao.framework.adapters.ntp_clock import NtpClock
    from helao.framework.adapters.queue_eventsink import QueueEventSink
    from helao.framework.adapters.fakes.transport import FakeTransport
    from helao.framework.domain.run_models import RunAction
    from helao.framework.domain.executor import Executor
    from helao.framework.models.hlostatus import HloStatus

    base = FrameworkBase(
        server_key="SRV",
        storage=FsStorage(save_root=str(tmp_path)),
        eventsink=QueueEventSink(),
        clock=NtpClock(),
        transport=FakeTransport(),
    )

    async def _drive():
        action = RunAction(
            action_name="test_act",
            action_output_dir="26.25/0622/test",
            save_act=True,
        )
        active = await base.setup_and_contain_action(ActionContext(action=action))

        exec_done = []

        class DoneExec(Executor):
            async def _exec(self):
                exec_done.append(True)
                return {"data": {}, "error": None}

        result_dict = active.start_executor(DoneExec(active=active))
        assert isinstance(result_dict, dict)
        assert "action_name" in result_dict
        # give the background task time to run
        await asyncio.sleep(0.2)
        assert exec_done, "executor _exec was not called"

    asyncio.run(_drive())


def test_micro_orch_run_action_accepts_action_model():
    import asyncio
    from helao.framework.runners.micro_orch import MicroOrch
    from helao.framework.models.action import ActionModel
    from helao.framework.models.machine import MachineModel

    action = ActionModel(
        action_name="noop",
        action_server=MachineModel(server_name="ORCH"),
        action_params={},
    )

    async def _run():
        micro = MicroOrch()
        return await micro.run_action(action)

    state = asyncio.run(_run())
    # state is OrchState — just assert it doesn't raise
    assert state is not None
```

Run: `conda run -n helao python -m pytest helao/framework/tests/test_migrate_test_deploy.py::test_base_api_importable -x -q`

Expected: `ImportError: No module named 'helao.framework.app.server_api'`

- [ ] **Step 2: Create `helao/framework/app/server_api.py`**

```python
"""Deployment-compatible FastAPI subclass wrapping FrameworkBase.

Port of the ``BaseAPI`` pattern from ``helao.core.servers.base_api``.
Deployment action servers do:

    app = BaseAPI(server_key=server_key, driver_classes=[MyDriver])

and then decorate ``@app.post(...)`` endpoints that call
``await app.base.setup_and_contain_action()``. This class wires a
``FrameworkBase`` with real adapters and exposes it as ``app.base``.

Only the action-server surface is implemented here. WebSocket status/data
publishers and the per-server admin endpoints are added in the full
production wiring (a later SP).
"""

__all__ = ["BaseAPI"]

import tempfile
from typing import List, Optional, Type

from fastapi import FastAPI

from helao.framework.app.base_api import FrameworkBase
from helao.framework.adapters.fs_storage import FsStorage
from helao.framework.adapters.ntp_clock import NtpClock
from helao.framework.adapters.queue_eventsink import QueueEventSink
from helao.framework.adapters.fakes.transport import FakeTransport


class BaseAPI(FastAPI):
    """FastAPI subclass that wires ``FrameworkBase`` for deployment action servers."""

    def __init__(
        self,
        server_key: str,
        *,
        driver_classes: Optional[List[Type]] = None,
        save_root: Optional[str] = None,
        **fastapi_kwargs,
    ) -> None:
        super().__init__(**fastapi_kwargs)
        self.server_key = server_key
        self.base = FrameworkBase(
            server_key=server_key,
            storage=FsStorage(save_root=save_root or tempfile.mkdtemp()),
            eventsink=QueueEventSink(),
            clock=NtpClock(),
            transport=FakeTransport(),
        )
        self.driver = None
        self.drivers: dict = {}
        if driver_classes:
            for cls in driver_classes:
                inst = cls(self.base)
                self.drivers[cls.__name__] = inst
            self.driver = next(iter(self.drivers.values())) if self.drivers else None
```

- [ ] **Step 3: Add `start_executor` to `ActionSession`**

In `helao/framework/domain/action_session.py`, add after the `action_loop_task` method (around line 565):

```python
    def start_executor(self, executor: "Executor") -> dict:
        """Schedule the executor loop as a background task; return action dict.

        Compat shim for deployment servers that call ``active.start_executor(executor)``
        synchronously and return its result as the HTTP response while the action
        runs in the background. Ports ``Base.start_executor`` from
        ``helao.core.servers.base``.
        """
        import asyncio

        self.executor = executor
        asyncio.ensure_future(self.action_loop_task(executor))
        return self.action.as_dict()
```

- [ ] **Step 4: Add `ActionModel` coercion to `MicroOrch.run_action`**

In `helao/framework/runners/micro_orch.py`, update the `run_action` method signature and body:

```python
    async def run_action(self, action) -> OrchState:
        """Stage a single ``action`` and drive it to completion in-process.

        Accepts either :class:`RunAction` or :class:`ActionModel` (the latter
        is coerced to ``RunAction`` for compat with deployment runner scripts).
        """
        from helao.framework.domain.run_models import RunAction
        from helao.framework.models.action import ActionModel
        if isinstance(action, ActionModel) and not isinstance(action, RunAction):
            action = RunAction(**action.model_dump())
        self.driver.state.action_dq.append(action)
        await self.driver.start()
        return self.driver.state
```

- [ ] **Step 5: Run all gap-fill tests**

```
conda run -n helao python -m pytest helao/framework/tests/test_migrate_test_deploy.py::test_base_api_importable helao/framework/tests/test_migrate_test_deploy.py::test_base_api_has_base_attribute helao/framework/tests/test_migrate_test_deploy.py::test_base_api_instantiates_driver helao/framework/tests/test_migrate_test_deploy.py::test_action_session_start_executor helao/framework/tests/test_migrate_test_deploy.py::test_micro_orch_run_action_accepts_action_model -v
```

Expected: 5 PASSED

- [ ] **Step 6: Commit**

```bash
git add helao/framework/app/server_api.py helao/framework/domain/action_session.py helao/framework/runners/micro_orch.py helao/framework/tests/test_migrate_test_deploy.py
git commit -m "feat(framework): SP7 wave 1 — BaseAPI compat, start_executor, MicroOrch coercion"
```

---

## Task 5: Import-swap action servers

**Files:**
- Modify: `helao/deploy/test/servers/action/ws_simulator.py`
- Modify: `helao/deploy/test/servers/action/cpsim_server.py`
- Modify: `helao/deploy/test/servers/action/gpsim_server.py`
- Modify: `helao/deploy/test/servers/action/motion_simulator.py`
- Modify: `helao/deploy/test/servers/action/pstat_simulator.py`
- Modify: `helao/deploy/test/servers/action/analysis_simulator.py`
- Modify: `helao/deploy/test/servers/action/archive_simulator.py`

No logic changes — only `from` lines.

**Import substitution table for all action servers:**

| Old | New |
|---|---|
| `from helao.core.error import ErrorCodes` | `from helao.framework.models.errors import ErrorCodes` |
| `from helao.core.models.hlostatus import HloStatus` | `from helao.framework.models.hlostatus import HloStatus` |
| `from helao.core.models.sample import ...` | `from helao.framework.models.sample import ...` |
| `from helao.core.models.machine import MachineModel` | `from helao.framework.models.machine import MachineModel` |
| `from helao.core.models.machine import MachineModel as MM` | `from helao.framework.models.machine import MachineModel as MM` |
| `from helao.core.models.process_contrib import ProcessContrib` | `from helao.framework.models.process_contrib import ProcessContrib` |
| `from helao.helpers import helao_logging as logging` | `from helao.framework.support import helao_logging as logging` |
| `from helao.core.servers.base import Base, Executor` | `from helao.framework.app.base_api import FrameworkBase as Base` + (new line) `from helao.framework.domain.executor import Executor` |
| `from helao.core.servers.base import Base` | `from helao.framework.app.base_api import FrameworkBase as Base` |
| `from helao.core.servers.base import Base, Active` | `from helao.framework.app.base_api import FrameworkBase as Base` + (new line) `from helao.framework.domain.action_session import ActionSession as Active` |
| `from helao.core.servers.base_api import BaseAPI` | `from helao.framework.app.server_api import BaseAPI` |
| `from helao.helpers.premodels import Action` | `from helao.framework.models.action import ActionModel as Action` |
| `from helao.helpers.executor import Executor` | `from helao.framework.domain.executor import Executor` |

- [ ] **Step 1: Swap `ws_simulator.py`**

Apply the substitutions to `helao/deploy/test/servers/action/ws_simulator.py`. The import block at lines 17-32 becomes:

```python
from helao.framework.models.errors import ErrorCodes
from helao.framework.models.hlostatus import HloStatus
from helao.framework.models.sample import (
    AssemblySample,
    LiquidSample,
    GasSample,
    SolidSample,
    NoneSample,
)

from helao.framework.support import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
from helao.framework.app.base_api import FrameworkBase as Base
from helao.framework.domain.executor import Executor
from helao.framework.app.server_api import BaseAPI
from helao.framework.models.action import ActionModel as Action
```

Verify: `conda run -n helao python -c "from helao.deploy.test.servers.action.ws_simulator import makeApp; print('ok')"` → prints `ok`

- [ ] **Step 2: Swap `cpsim_server.py`**

`helao/deploy/test/servers/action/cpsim_server.py` lines 15-16:

```python
from helao.framework.app.server_api import BaseAPI
from helao.framework.models.action import ActionModel as Action
```

Verify: `conda run -n helao python -c "from helao.deploy.test.servers.action.cpsim_server import makeApp; print('ok')"`

- [ ] **Step 3: Swap `gpsim_server.py`**

`helao/deploy/test/servers/action/gpsim_server.py`:

```python
from helao.framework.app.server_api import BaseAPI
from helao.framework.models.action import ActionModel as Action
from helao.framework.support import helao_logging as logging
```

Verify: `conda run -n helao python -c "from helao.deploy.test.servers.action.gpsim_server import makeApp; print('ok')"`

- [ ] **Step 4: Swap `motion_simulator.py`**

`helao/deploy/test/servers/action/motion_simulator.py`:

```python
from helao.framework.support import helao_logging as logging
from helao.framework.app.base_api import FrameworkBase as Base
from helao.framework.app.server_api import BaseAPI
from helao.framework.models.action import ActionModel as Action
```

Verify: `conda run -n helao python -c "from helao.deploy.test.servers.action.motion_simulator import makeApp; print('ok')"`

- [ ] **Step 5: Swap `pstat_simulator.py`**

`helao/deploy/test/servers/action/pstat_simulator.py`:

```python
from helao.framework.app.base_api import FrameworkBase as Base
from helao.framework.app.server_api import BaseAPI
from helao.framework.models.action import ActionModel as Action
```

Verify: `conda run -n helao python -c "from helao.deploy.test.servers.action.pstat_simulator import makeApp; print('ok')"`

- [ ] **Step 6: Swap `analysis_simulator.py`**

`helao/deploy/test/servers/action/analysis_simulator.py`:

```python
from helao.framework.app.base_api import FrameworkBase as Base
from helao.framework.app.server_api import BaseAPI
from helao.framework.models.action import ActionModel as Action
```

Verify: `conda run -n helao python -c "from helao.deploy.test.servers.action.analysis_simulator import makeApp; print('ok')"`

- [ ] **Step 7: Swap `archive_simulator.py`**

`helao/deploy/test/servers/action/archive_simulator.py`:

```python
from helao.framework.support import helao_logging as logging
from helao.framework.app.base_api import FrameworkBase as Base
from helao.framework.app.server_api import BaseAPI
from helao.framework.models.action import ActionModel as Action
```

Verify: `conda run -n helao python -c "from helao.deploy.test.servers.action.archive_simulator import makeApp; print('ok')"`

- [ ] **Step 8: Run full framework test suite to check no regressions**

```
conda run -n helao python -m pytest helao/framework/tests/ -x -q
```

Expected: all PASSED (same count as before this task)

- [ ] **Step 9: Commit**

```bash
git add helao/deploy/test/servers/action/
git commit -m "feat(deploy/test): SP7 wave 2 — import-swap action servers"
```

---

## Task 6: Import-swap experiments and sequences

**Files:**
- Modify: `helao/deploy/test/experiments/TEST_exp.py`
- Modify: `helao/deploy/test/experiments/OERSIM_exp.py`
- Modify: `helao/deploy/test/experiments/simulatews_exp.py`
- Modify: `helao/deploy/test/sequences/TEST_seq.py`
- Modify: `helao/deploy/test/sequences/OERSIM_seq.py`

No logic changes — only `from` lines.

**Import substitution table:**

| Old | New |
|---|---|
| `from helao.helpers.premodels import Experiment, ActionPlanMaker` | `from helao.framework.domain.run_models import RunExperiment as Experiment` + (new line) `from helao.framework.domain.plan_makers import ActionPlanMaker` |
| `from helao.helpers.premodels import ExperimentPlanMaker` | `from helao.framework.domain.plan_makers import ExperimentPlanMaker` |
| `from helao.core.models.machine import MachineModel as MM` | `from helao.framework.models.machine import MachineModel as MM` |
| `from helao.core.models.machine import MachineModel` | `from helao.framework.models.machine import MachineModel` |
| `from helao.core.models.process_contrib import ProcessContrib` | `from helao.framework.models.process_contrib import ProcessContrib` |
| `from helao.helpers.lib_decorators import experiment` | `from helao.framework.support.lib_decorators import experiment` |
| `from helao.helpers.lib_decorators import sequence` | `from helao.framework.support.lib_decorators import sequence` |

- [ ] **Step 1: Swap `TEST_exp.py`**

`helao/deploy/test/experiments/TEST_exp.py` imports become:

```python
from helao.framework.domain.run_models import RunExperiment as Experiment
from helao.framework.domain.plan_makers import ActionPlanMaker
from helao.framework.models.machine import MachineModel as MM
from helao.framework.support.lib_decorators import experiment
```

Verify: `conda run -n helao python -c "from helao.deploy.test.experiments.TEST_exp import TEST_sub_noblocking; print('ok')"`

- [ ] **Step 2: Swap `OERSIM_exp.py`**

```python
from helao.framework.domain.run_models import RunExperiment as Experiment
from helao.framework.domain.plan_makers import ActionPlanMaker
from helao.framework.models.machine import MachineModel as MM
from helao.framework.support.lib_decorators import experiment
```

Verify: `conda run -n helao python -c "from helao.deploy.test.experiments.OERSIM_exp import OERSIM_sub_CA; print('ok')"` (use the actual exported function name)

- [ ] **Step 3: Swap `simulatews_exp.py`**

```python
from helao.framework.models.machine import MachineModel
from helao.framework.models.process_contrib import ProcessContrib
from helao.framework.domain.run_models import RunExperiment as Experiment
from helao.framework.domain.plan_makers import ActionPlanMaker
from helao.framework.support.lib_decorators import experiment
```

Verify: `conda run -n helao python -c "import helao.deploy.test.experiments.simulatews_exp; print('ok')"`

- [ ] **Step 4: Swap `TEST_seq.py`**

```python
from helao.framework.domain.plan_makers import ExperimentPlanMaker
from helao.framework.support.lib_decorators import sequence
```

Verify: `conda run -n helao python -c "from helao.deploy.test.sequences.TEST_seq import TEST_consecutive_noblocking; print('ok')"`

- [ ] **Step 5: Swap `OERSIM_seq.py`**

```python
from helao.framework.domain.plan_makers import ExperimentPlanMaker
from helao.framework.support.lib_decorators import sequence
```

Verify: `conda run -n helao python -c "import helao.deploy.test.sequences.OERSIM_seq; print('ok')"`

- [ ] **Step 6: Commit**

```bash
git add helao/deploy/test/experiments/ helao/deploy/test/sequences/
git commit -m "feat(deploy/test): SP7 wave 2 — import-swap experiments and sequences"
```

---

## Task 7: Import-swap runners and drivers

**Files:**
- Modify: `helao/deploy/test/runners/test_runner.py`
- Modify: `helao/deploy/test/runners/oersim_runner.py`
- Modify: `helao/deploy/test/runners/simulatews_runner.py`
- Modify: `helao/deploy/test/drivers/data/gpsim_driver.py`
- Modify: `helao/deploy/test/drivers/pstat/cpsim_driver.py`

**Import substitution table:**

| Old | New |
|---|---|
| `from helao.core.runners.micro_orch import MicroOrch` | `from helao.framework.runners.micro_orch import MicroOrch` |
| `from helao.helpers.premodels import Action` | `from helao.framework.models.action import ActionModel as Action` |
| `from helao.helpers.premodels import Experiment` | `from helao.framework.domain.run_models import RunExperiment as Experiment` |
| `from helao.core.models.machine import MachineModel` | `from helao.framework.models.machine import MachineModel` |
| `from helao.core.servers.base import Base, Active` | `from helao.framework.app.base_api import FrameworkBase as Base` + (new line) `from helao.framework.domain.action_session import ActionSession as Active` |
| `from helao.core.servers.base import Base` | `from helao.framework.app.base_api import FrameworkBase as Base` |
| `from helao.helpers.executor import Executor` | `from helao.framework.domain.executor import Executor` |
| `from helao.helpers.file_utils import unzpickle` | `from helao.framework.support.file_utils import unzpickle` |
| `from helao.helpers.dispatcher import async_private_dispatcher` | `from helao.framework.support.dispatcher import async_private_dispatcher` |
| `from helao.core.error import ErrorCodes` | `from helao.framework.models.errors import ErrorCodes` |
| `from helao.core.models.hlostatus import HloStatus` | `from helao.framework.models.hlostatus import HloStatus` |
| `from helao.helpers import helao_logging as logging` | `from helao.framework.support import helao_logging as logging` |

- [ ] **Step 1: Swap `test_runner.py`**

`helao/deploy/test/runners/test_runner.py` lines 33-35 become:

```python
from helao.framework.runners.micro_orch import MicroOrch
from helao.framework.models.action import ActionModel as Action
from helao.framework.models.machine import MachineModel
```

Verify import only (runner requires live ORCH server): `conda run -n helao python -c "import helao.deploy.test.runners.test_runner; print('ok')"`

- [ ] **Step 2: Swap `oersim_runner.py`**

```python
from helao.framework.runners.micro_orch import MicroOrch
from helao.framework.models.action import ActionModel as Action
from helao.framework.models.machine import MachineModel
```

Verify: `conda run -n helao python -c "import helao.deploy.test.runners.oersim_runner; print('ok')"`

- [ ] **Step 3: Swap `simulatews_runner.py`**

```python
from helao.framework.runners.micro_orch import MicroOrch
from helao.framework.models.action import ActionModel as Action
from helao.framework.models.machine import MachineModel
```

Verify: `conda run -n helao python -c "import helao.deploy.test.runners.simulatews_runner; print('ok')"`

- [ ] **Step 4: Swap `gpsim_driver.py`**

`helao/deploy/test/drivers/data/gpsim_driver.py` lines 13-22 become:

```python
from helao.framework.support import helao_logging as logging
from helao.framework.models.errors import ErrorCodes
from helao.framework.models.hlostatus import HloStatus
from helao.framework.support.file_utils import unzpickle
from helao.framework.app.base_api import FrameworkBase as Base
from helao.framework.domain.action_session import ActionSession as Active
from helao.framework.domain.executor import Executor
from helao.framework.domain.run_models import RunExperiment as Experiment
from helao.framework.support.dispatcher import async_private_dispatcher
```

Verify: `conda run -n helao python -c "from helao.deploy.test.drivers.data.gpsim_driver import GPSim; print('ok')"`

- [ ] **Step 5: Swap `cpsim_driver.py`**

`helao/deploy/test/drivers/pstat/cpsim_driver.py` lines 14-21 become:

```python
from helao.framework.support import helao_logging as logging
from helao.framework.models.errors import ErrorCodes
from helao.framework.models.hlostatus import HloStatus
from helao.framework.support.file_utils import unzpickle
from helao.framework.app.base_api import FrameworkBase as Base
from helao.framework.domain.executor import Executor
```

Verify: `conda run -n helao python -c "from helao.deploy.test.drivers.pstat.cpsim_driver import CPSim; print('ok')"`

- [ ] **Step 6: Run full framework test suite**

```
conda run -n helao python -m pytest helao/framework/tests/ -x -q
```

Expected: all PASSED

- [ ] **Step 7: Commit**

```bash
git add helao/deploy/test/runners/ helao/deploy/test/drivers/
git commit -m "feat(deploy/test): SP7 wave 2 — import-swap runners and drivers"
```

---

## Task 8: WsSim golden-master integration test

Drive `ws_simulator.makeApp("SIM")` end-to-end via `httpx.AsyncClient` and assert `.hlo`/`.act` files land on disk with the correct format.

**Files:**
- Modify: `helao/framework/tests/test_migrate_test_deploy.py`

- [ ] **Step 1: Write the test**

Add to `helao/framework/tests/test_migrate_test_deploy.py`:

```python
import asyncio
import pytest


@pytest.mark.asyncio
async def test_ws_sim_action_writes_hlo_and_act(tmp_path):
    """Golden-master: WsSim acquire_data writes .hlo + .act with correct format."""
    from helao.deploy.test.servers.action.ws_simulator import makeApp
    from helao.framework.adapters.fs_storage import FsStorage
    import httpx

    app = makeApp("SIM")
    # override the storage path so we control where files land
    app.base.storage = FsStorage(save_root=str(tmp_path))

    async with httpx.AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.post(
            "/SIM/acquire_data",
            json={"duration": 0.2, "acquisition_rate": 0.2},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "action_uuid" in body

    # wait for background executor to finish (duration=0.2s + buffer)
    await asyncio.sleep(0.8)

    hlo_files = list(tmp_path.rglob("*.hlo"))
    assert hlo_files, "no .hlo file written by ws_simulator"
    content = hlo_files[0].read_text(encoding="utf-8")
    # golden format: header line, separator, data rows
    assert "%%\n" in content, "missing HLO header/data separator"
    assert "series_0" in content, "no data rows in HLO"

    act_files = list(tmp_path.rglob("*.act"))
    assert act_files, "no .act meta file written"
    import json
    meta = json.loads(act_files[0].read_text())
    assert meta.get("action_name") == "acquire_data"
```

Note: if `pytest-asyncio` is not installed, use `asyncio.run(...)` inside a sync test instead:

```python
def test_ws_sim_action_writes_hlo_and_act(tmp_path):
    async def _body():
        # ... same body as above ...
        pass
    asyncio.run(_body())
```

- [ ] **Step 2: Run the test**

```
conda run -n helao python -m pytest helao/framework/tests/test_migrate_test_deploy.py::test_ws_sim_action_writes_hlo_and_act -v
```

Expected: PASSED. If it fails with `httpx.AsyncClient` import issues, check `httpx` is installed in the `helao` env: `conda run -n helao pip show httpx`.

- [ ] **Step 3: Commit**

```bash
git add helao/framework/tests/test_migrate_test_deploy.py
git commit -m "test(framework): SP7 wave 3 — WsSim golden-master integration test"
```

---

## Task 9: Runner import smoke test

Verify that all three runner files are importable from `helao.framework.*` paths (full runner end-to-end requires a live ORCH server, so import-only is the test boundary).

**Files:**
- Modify: `helao/framework/tests/test_migrate_test_deploy.py`

- [ ] **Step 1: Write the tests**

Add to `helao/framework/tests/test_migrate_test_deploy.py`:

```python
def test_test_runner_importable():
    """test_runner.py resolves all helao.framework.* imports."""
    import helao.deploy.test.runners.test_runner  # noqa: F401


def test_oersim_runner_importable():
    """oersim_runner.py resolves all helao.framework.* imports."""
    import helao.deploy.test.runners.oersim_runner  # noqa: F401


def test_simulatews_runner_importable():
    """simulatews_runner.py resolves all helao.framework.* imports."""
    import helao.deploy.test.runners.simulatews_runner  # noqa: F401


def test_gpsim_driver_importable():
    """gpsim_driver.py resolves all helao.framework.* imports."""
    from helao.deploy.test.drivers.data.gpsim_driver import GPSim
    assert GPSim is not None


def test_cpsim_driver_importable():
    """cpsim_driver.py resolves all helao.framework.* imports."""
    from helao.deploy.test.drivers.pstat.cpsim_driver import CPSim
    assert CPSim is not None
```

- [ ] **Step 2: Run the tests**

```
conda run -n helao python -m pytest helao/framework/tests/test_migrate_test_deploy.py::test_test_runner_importable helao/framework/tests/test_migrate_test_deploy.py::test_oersim_runner_importable helao/framework/tests/test_migrate_test_deploy.py::test_simulatews_runner_importable helao/framework/tests/test_migrate_test_deploy.py::test_gpsim_driver_importable helao/framework/tests/test_migrate_test_deploy.py::test_cpsim_driver_importable -v
```

Expected: 5 PASSED

- [ ] **Step 3: Commit**

```bash
git add helao/framework/tests/test_migrate_test_deploy.py
git commit -m "test(framework): SP7 wave 3 — runner and driver import smoke tests"
```

---

## Task 10: Verify framework gate passes

- [ ] **Step 1: Run full test suite**

```
conda run -n helao python -m pytest helao/framework/tests/ -v 2>&1 | tail -20
```

Expected: all tests PASSED, no regressions in existing tests.

- [ ] **Step 2: Run coverage gate**

```
conda run -n helao python helao/framework/_devtools/coverage_gate.py
```

Expected: `domain/` and `models/` coverage ≥90%; gate exits 0.

- [ ] **Step 3: Run boundary check**

```
conda run -n helao python -m pytest helao/framework/tests/test_boundaries.py -v
```

Expected: PASSED (new `server_api.py` and `support/*.py` are allowed to import adapters/FastAPI; only `domain/` is purity-gated).

- [ ] **Step 4: Final commit and push for PR**

```bash
git add helao/framework/tests/test_migrate_test_deploy.py
git commit -m "test(framework): SP7 wave 3 — full gate verification"
```

Create PR: `feat/framework-migrate-test` → `unstable`.

---

## Self-Review Notes

**Spec coverage check:**
- §3a (new support files): Tasks 1-3 ✓
- §3b (import-swap deployment files): Tasks 5-7 ✓
- §4 (full import map): Tasks 5-7 use exact map ✓
- §5 (lib_decorators port): Task 1 ✓
- §6 (dispatcher port): Task 3 ✓
- §7 (test strategy): Tasks 1, 4, 8, 9 ✓
- §8 (boundary enforcement): Task 10 step 3 ✓

**Gaps acknowledged:**
- `BaseAPI` was missing from framework → added in Task 4
- `ActionSession.start_executor` was missing → added in Task 4
- `MicroOrch.run_action` needed `ActionModel` coercion → added in Task 4
- `dispatch_action` is not ported to framework `MicroOrch` → `test_runner.py` import-swapped but not end-to-end tested (requires live ORCH server or future `dispatch_action` port)

**Type consistency:** `ActionModel as Action` alias used consistently across all deployment files; `RunExperiment as Experiment` alias used consistently in experiments and `gpsim_driver.py`.
