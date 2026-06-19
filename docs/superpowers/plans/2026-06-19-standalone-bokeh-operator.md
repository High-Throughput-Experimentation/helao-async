# Standalone Bokeh Operator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an alternative Bokeh operator that is launched like a visualizer (config + `bokeh_launcher.py`) and drives an orchestrator over OrchAPI HTTP/RPC endpoints instead of an in-process `Orch` reference, with full parity to the existing in-orch operator.

**Architecture:** One `BokehOperator` UI class talks to an `OrchBackend` abstraction. `LocalBackend` wraps a live `Orch` (current in-orch behavior, unchanged). `RemoteBackend` calls OrchAPI endpoints via `async_private_dispatcher`, loads sequence/experiment libraries locally via `import_autolibs`, and stays in sync through the orch's `ws_status` WebSocket plus a slow poll. Backend list/state methods return **normalized plain dicts** so the UI never branches on object-vs-JSON.

**Tech Stack:** Python 3.12, Bokeh 3.x, FastAPI, `helao.helpers.dispatcher`, `helao.helpers.ws_utils.WsSubscriber`, `helao.helpers.import_autolibs`. No pytest — tests are standalone modules run with `python -m ...` (mirrors `helao/deploy/test/tests/test_data_browser.py`).

**Spec:** `docs/superpowers/specs/2026-06-19-standalone-bokeh-operator-design.md`

---

## File Structure

**Create:**
- `helao/core/servers/operator/orch_backend.py` — `OrchBackend` ABC, `LocalBackend`, `RemoteBackend`.
- `helao/deploy/test/servers/operator/standalone_operator.py` — `makeBokehApp` shim (test deployment).
- `helao/deploy/hte/servers/operator/standalone_operator.py` — `makeBokehApp` shim (hte deployment).
- `helao/deploy/test/tests/test_standalone_operator.py` — all tests.

**Modify:**
- `helao/core/servers/orch_api.py` — 6 new private endpoints; extend `/get_orch_state` with queue counts.
- `helao/core/servers/operator/bokeh_operator.py` — constructor takes `backend`; all `self.orch.*` → `self.backend.*` or `self.vis.*`; plate-map hook guarded; subscribe wiring.
- `helao/core/servers/orch.py` — `makeBokehApp` passes `LocalBackend(orch)`; import `LocalBackend`.
- `helao/deploy/test/configs/test.yml` — add a `group: operator` standalone operator entry (or a new `*.yml`).

**Backend normalized dict contracts (used by every task):**
- `list_sequences()` → `list[dict]` with keys `sequence_name, sequence_label, sequence_uuid, campaign_name, campaign_uuid`.
- `list_experiments()` → `list[dict]` with keys `experiment_name, experiment_uuid`.
- `list_actions()` → `list[dict]` with keys `action_name, action_server, action_uuid` (`action_server` is a display string).
- `get_histories()` → `{"action": list[(uuid,dict)], "experiment": [...], "sequence": [...]}`.
- `get_status_summary()` → `{server_name: [server_status, driver_status]}`.
- `get_orch_state()` → `{loop_state, active_sequence, last_sequence, active_experiment, last_experiment, n_sequences, n_experiments, n_actions, current_stop_message}`.
- `get_step_flags()` → `{"actions": bool, "experiments": bool, "sequences": bool}` (sync).

**Async vs sync rule:** reads/mutations that hit orch are `async` (UI already wraps every orch call in `doc.add_next_tick_callback`). `sequence_lib`, `experiment_lib`, `unpack_sequence`, `get_step_flags` are sync (local data / cache). `set_step_flag` is async (RemoteBackend does HTTP).

---

## Task 1: New OrchAPI endpoints

**Files:**
- Modify: `helao/core/servers/orch_api.py` (add endpoints near the other `tags=["private"]` ORCH endpoints, e.g. after `/get_orch_state` ~line 443)
- Test: `helao/deploy/test/tests/test_standalone_operator.py`

- [ ] **Step 1: Write the failing test**

Create `helao/deploy/test/tests/test_standalone_operator.py`:

```python
"""Standalone tests for the standalone Bokeh operator. No pytest; run with:

    PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao \
        python -m helao.deploy.test.tests.test_standalone_operator
"""
import asyncio
import inspect


class _FakeGlobalStatus:
    def __init__(self):
        self.loop_state = "stopped"
        self.orch_state = "stopped"
        self.loop_intent = "none"

    def as_json(self):
        return {"loop_state": self.loop_state}


class _FakeOrch:
    """Minimal stand-in for Orch exposing only what the new endpoints/backends touch."""

    def __init__(self):
        self.globalstatusmodel = _FakeGlobalStatus()
        self.step_thru_actions = False
        self.step_thru_experiments = False
        self.step_thru_sequences = False
        self.status_summary = {"motor": ("idle", "ok")}
        self.action_history = {"a1": {"action_name": "noop", "action_server": "motor"}}
        self.experiment_history = {"e1": {"experiment_name": "exp0"}}
        self.sequence_history = {"s1": {"sequence_name": "seq0"}}
        self.sequence_dq = [1, 2, 3]
        self.experiment_dq = [1]
        self.action_dq = []
        self.cleared = []

    def list_sequences(self, limit=10):
        return []

    async def clear_sequences(self):
        self.cleared.append("sequences")

    async def add_split_sequences(self, sequence):
        return ["uuid-1", "uuid-2"]


def test_endpoint_helpers_shapes():
    # Endpoint handler bodies are extracted as module-level helpers for testability.
    from helao.core.servers import orch_api

    orch = _FakeOrch()
    assert orch_api._histories_payload(orch) == {
        "action": [("a1", {"action_name": "noop", "action_server": "motor"})],
        "experiment": [("e1", {"experiment_name": "exp0"})],
        "sequence": [("s1", {"sequence_name": "seq0"})],
    }
    assert orch_api._status_summary_payload(orch) == {"motor": ["idle", "ok"]}
    assert orch_api._step_flags_payload(orch) == {
        "actions": False,
        "experiments": False,
        "sequences": False,
    }
    orch_api._set_step_flag(orch, "actions", True)
    assert orch.step_thru_actions is True
    assert orch_api._queue_counts(orch) == {
        "n_sequences": 3,
        "n_experiments": 1,
        "n_actions": 0,
    }
    print("test_endpoint_helpers_shapes PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao \
  python -m helao.deploy.test.tests.test_standalone_operator
```
(temporarily add `test_endpoint_helpers_shapes()` then `print("ok")` under `if __name__ == "__main__":`)
Expected: FAIL with `AttributeError: module 'helao.core.servers.orch_api' has no attribute '_histories_payload'`.

- [ ] **Step 3: Add module-level helpers + endpoints in `orch_api.py`**

Add these module-level functions near the top of `orch_api.py` (after `LOGGER = ...`, before `class OrchAPI`):

```python
def _histories_payload(orch) -> dict:
    """Return action/experiment/sequence history as JSON-safe (uuid, dict) item lists."""
    return {
        "action": list(orch.action_history.items()),
        "experiment": list(orch.experiment_history.items()),
        "sequence": list(orch.sequence_history.items()),
    }


def _status_summary_payload(orch) -> dict:
    """Return {server: [server_status, driver_status]} from orch.status_summary."""
    return {k: list(v) for k, v in orch.status_summary.items()}


def _step_flags_payload(orch) -> dict:
    """Return the orchestrator's three step-through flags."""
    return {
        "actions": orch.step_thru_actions,
        "experiments": orch.step_thru_experiments,
        "sequences": orch.step_thru_sequences,
    }


def _set_step_flag(orch, kind: str, value: bool) -> dict:
    """Set one step-through flag by kind ('actions'|'experiments'|'sequences')."""
    attr = {
        "actions": "step_thru_actions",
        "experiments": "step_thru_experiments",
        "sequences": "step_thru_sequences",
    }[kind]
    setattr(orch, attr, bool(value))
    return {kind: getattr(orch, attr)}


def _queue_counts(orch) -> dict:
    """Return true queue lengths for the three deques."""
    return {
        "n_sequences": len(orch.sequence_dq),
        "n_experiments": len(orch.experiment_dq),
        "n_actions": len(orch.action_dq),
    }
```

Then register endpoints inside `OrchAPI.__init__` (after the existing `/get_orch_state` block, ~line 443):

```python
        @self.post("/get_histories", tags=["private"])
        def get_histories():
            """Return action/experiment/sequence history item lists."""
            return _histories_payload(self.orch)

        @self.post("/get_status_summary", tags=["private"])
        def get_status_summary():
            """Return the per-server (server_status, driver_status) summary."""
            return _status_summary_payload(self.orch)

        @self.post("/get_step_flags", tags=["private"])
        def get_step_flags():
            """Return the orchestrator's step-through flags."""
            return _step_flags_payload(self.orch)

        @self.post("/set_step_flag", tags=["private"])
        def set_step_flag(kind: str, value: bool):
            """Set a single step-through flag and return its new value."""
            return _set_step_flag(self.orch, kind, value)

        @self.post("/clear_sequences", tags=["private"])
        async def clear_sequences():
            """Empty the orchestrator's sequence queue."""
            await self.orch.clear_sequences()
            return {}

        @self.post("/append_split_sequences", tags=["private"])
        async def append_split_sequences(sequence: Sequence = Body({}, embed=True)):
            """Split a sequence by sample and append the sub-sequences; return their UUIDs."""
            if not isinstance(sequence, Sequence):
                sequence = Sequence(**sequence)
            result = await self.orch.add_split_sequences(sequence=sequence)
            return {"sequence_uuids": result}
```

Also extend the existing `/get_orch_state` handler (`get_orch_state`, ~line 423): add the counts and stop message to `resp` before `return resp`:

```python
            resp.update(_queue_counts(self.orch))
            resp["current_stop_message"] = self.orch.current_stop_message
```

- [ ] **Step 4: Run test to verify it passes**

Run the same command as Step 2.
Expected: `test_endpoint_helpers_shapes PASS`.

- [ ] **Step 5: Commit**

```bash
git add helao/core/servers/orch_api.py helao/deploy/test/tests/test_standalone_operator.py
git commit -m "feat(orch_api): add operator read/control endpoints for standalone operator"
```

---

## Task 2: OrchBackend ABC + LocalBackend

**Files:**
- Create: `helao/core/servers/operator/orch_backend.py`
- Test: `helao/deploy/test/tests/test_standalone_operator.py`

- [ ] **Step 1: Write the failing test**

Append to the test file:

```python
def test_local_backend_normalized_shapes():
    from helao.core.servers.operator.orch_backend import LocalBackend

    class _Seq:
        def as_dict(self):
            return {
                "sequence_name": "seq0", "sequence_label": "lbl",
                "sequence_uuid": "su", "campaign_name": "camp",
                "campaign_uuid": "cu", "extra": "ignored",
            }

    class _Srv:
        def disp_name(self):
            return "motor@host"

    class _Act:
        action_server = _Srv()
        def as_dict(self):
            return {"action_name": "noop", "action_uuid": "au"}

    class _Orch2(_FakeOrch):
        def list_sequences(self, limit=10):
            return [_Seq()]
        def list_experiments(self, limit=10):
            return [type("E", (), {"as_dict": lambda s: {"experiment_name": "exp0", "experiment_uuid": "eu"}})()]
        def list_actions(self, limit=10):
            return [_Act()]
        sequence_lib = {"seq0": lambda x=1: [x]}
        experiment_lib = {}
        def unpack_sequence(self, sequence_name, sequence_params):
            return self.sequence_lib[sequence_name](**sequence_params)

    orch = _Orch2()
    be = LocalBackend(orch)
    seqs = asyncio.run(be.list_sequences())
    assert seqs == [{
        "sequence_name": "seq0", "sequence_label": "lbl", "sequence_uuid": "su",
        "campaign_name": "camp", "campaign_uuid": "cu",
    }]
    acts = asyncio.run(be.list_actions())
    assert acts == [{"action_name": "noop", "action_server": "motor@host", "action_uuid": "au"}]
    assert be.get_step_flags() == {"actions": False, "experiments": False, "sequences": False}
    assert be.unpack_sequence("seq0", {"x": 5}) == [5]
    asyncio.run(be.clear_sequences())
    assert "sequences" in orch.cleared
    print("test_local_backend_normalized_shapes PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run the test module (add `test_local_backend_normalized_shapes()` to `__main__`).
Expected: FAIL `ModuleNotFoundError: ... orch_backend`.

- [ ] **Step 3: Write `orch_backend.py` (ABC + LocalBackend)**

```python
"""Orchestrator-access backends for the Bokeh operator UI.

The :class:`BokehOperator` UI talks only to an :class:`OrchBackend`. Two
implementations exist: :class:`LocalBackend` wraps a live in-process
:class:`~helao.core.servers.orch.Orch`; :class:`RemoteBackend` (see below)
drives a remote orchestrator over OrchAPI HTTP/RPC endpoints.

List/state methods return *normalized plain dicts* so the UI never has to
branch on object-vs-JSON. See the module-level contract docstrings.
"""

from abc import ABC, abstractmethod
from typing import Callable

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class OrchBackend(ABC):
    """Abstract orchestrator access used by :class:`BokehOperator`."""

    #: name -> callable sequence library (local in every backend)
    sequence_lib: dict
    #: name -> callable experiment library (local in every backend)
    experiment_lib: dict

    @abstractmethod
    def unpack_sequence(self, sequence_name: str, sequence_params: dict) -> list:
        """Expand a library sequence into a list of planned Experiment models."""

    @abstractmethod
    def get_step_flags(self) -> dict:
        """Return {'actions': bool, 'experiments': bool, 'sequences': bool}."""

    @abstractmethod
    async def set_step_flag(self, kind: str, value: bool) -> None:
        """Set one step-through flag ('actions'|'experiments'|'sequences')."""

    @abstractmethod
    async def list_sequences(self) -> list: ...

    @abstractmethod
    async def list_experiments(self) -> list: ...

    @abstractmethod
    async def list_actions(self) -> list: ...

    @abstractmethod
    async def get_histories(self) -> dict: ...

    @abstractmethod
    async def get_status_summary(self) -> dict: ...

    @abstractmethod
    async def get_orch_state(self) -> dict: ...

    @abstractmethod
    async def add_sequence(self, sequence) -> object: ...

    @abstractmethod
    async def add_split_sequences(self, sequence) -> object: ...

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def skip(self) -> None: ...

    @abstractmethod
    async def estop(self) -> None: ...

    @abstractmethod
    async def clear_sequences(self) -> None: ...

    @abstractmethod
    async def clear_experiments(self) -> None: ...

    @abstractmethod
    async def clear_actions(self) -> None: ...

    @abstractmethod
    def subscribe(self, on_change: Callable[[], None]) -> None:
        """Register a callback fired whenever orch state may have changed."""

    @abstractmethod
    def close(self) -> None:
        """Tear down subscriptions / background tasks."""


_SEQ_KEYS = ["sequence_name", "sequence_label", "sequence_uuid", "campaign_name", "campaign_uuid"]
_EXP_KEYS = ["experiment_name", "experiment_uuid"]


class _OpShim:
    """Tiny stand-in for the in-orch operator: routes update_q puts to on_change."""

    def __init__(self, on_change):
        import asyncio
        self.update_q = asyncio.Queue()
        self._on_change = on_change
        self._task = asyncio.create_task(self._drain())

    async def _drain(self):
        while True:
            await self.update_q.get()
            self._on_change()

    def cancel(self):
        self._task.cancel()


class LocalBackend(OrchBackend):
    """Pass-through backend wrapping a live in-process Orch."""

    def __init__(self, orch):
        self.orch = orch
        self.sequence_lib = orch.sequence_lib
        self.experiment_lib = orch.experiment_lib
        self._shim = None

    def unpack_sequence(self, sequence_name, sequence_params):
        return self.orch.unpack_sequence(
            sequence_name=sequence_name, sequence_params=sequence_params
        )

    def get_step_flags(self):
        return {
            "actions": self.orch.step_thru_actions,
            "experiments": self.orch.step_thru_experiments,
            "sequences": self.orch.step_thru_sequences,
        }

    async def set_step_flag(self, kind, value):
        attr = {
            "actions": "step_thru_actions",
            "experiments": "step_thru_experiments",
            "sequences": "step_thru_sequences",
        }[kind]
        setattr(self.orch, attr, bool(value))

    async def list_sequences(self):
        return [{k: s.as_dict().get(k) for k in _SEQ_KEYS} for s in self.orch.list_sequences()]

    async def list_experiments(self):
        return [{k: e.as_dict().get(k) for k in _EXP_KEYS} for e in self.orch.list_experiments()]

    async def list_actions(self):
        out = []
        for a in self.orch.list_actions():
            d = a.as_dict()
            out.append({
                "action_name": d.get("action_name"),
                "action_server": a.action_server.disp_name(),
                "action_uuid": d.get("action_uuid"),
            })
        return out

    async def get_histories(self):
        return {
            "action": list(self.orch.action_history.items()),
            "experiment": list(self.orch.experiment_history.items()),
            "sequence": list(self.orch.sequence_history.items()),
        }

    async def get_status_summary(self):
        return {k: list(v) for k, v in self.orch.status_summary.items()}

    async def get_orch_state(self):
        gsm = self.orch.globalstatusmodel
        aseq = self.orch.active_sequence
        aexp = self.orch.active_experiment
        return {
            "loop_state": gsm.loop_state,
            "active_sequence": aseq.clean_dict() if aseq else {},
            "active_experiment": aexp.clean_dict() if aexp else {},
            "n_sequences": len(self.orch.sequence_dq),
            "n_experiments": len(self.orch.experiment_dq),
            "n_actions": len(self.orch.action_dq),
            "current_stop_message": self.orch.current_stop_message,
        }

    async def add_sequence(self, sequence):
        return await self.orch.add_sequence(sequence=sequence)

    async def add_split_sequences(self, sequence):
        return await self.orch.add_split_sequences(sequence=sequence)

    async def start(self):
        await self.orch.start()

    async def stop(self):
        await self.orch.stop()

    async def skip(self):
        await self.orch.skip()

    async def estop(self):
        await self.orch.estop_loop()

    async def clear_sequences(self):
        await self.orch.clear_sequences()

    async def clear_experiments(self):
        await self.orch.clear_experiments()

    async def clear_actions(self):
        await self.orch.clear_actions()

    def subscribe(self, on_change):
        self._shim = _OpShim(on_change)
        self.orch.orch_op = self._shim

    def close(self):
        if self._shim is not None:
            self._shim.cancel()
        self.orch.orch_op = None
```

- [ ] **Step 4: Run test to verify it passes**

Run the test module. Expected: `test_local_backend_normalized_shapes PASS`.

- [ ] **Step 5: Commit**

```bash
git add helao/core/servers/operator/orch_backend.py helao/deploy/test/tests/test_standalone_operator.py
git commit -m "feat(operator): add OrchBackend ABC and LocalBackend"
```

---

## Task 3: RemoteBackend

**Files:**
- Modify: `helao/core/servers/operator/orch_backend.py`
- Test: `helao/deploy/test/tests/test_standalone_operator.py`

RemoteBackend uses `async_private_dispatcher(server_key, host, port, endpoint, params_dict=..., json_dict=...)` which returns `(response, error_code)`. We inject a fake dispatcher in tests via the constructor arg `dispatcher=`.

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_remote_backend_dispatch_and_serialize():
    from helao.core.servers.operator.orch_backend import RemoteBackend
    from helao.core.error import ErrorCodes

    calls = []

    async def fake_dispatch(server_key, host, port, endpoint, params_dict=None, json_dict=None, **kw):
        calls.append((endpoint, params_dict, json_dict))
        canned = {
            "list_sequences": [{
                "sequence_name": "seq0", "sequence_label": "lbl", "sequence_uuid": "su",
                "campaign_name": "camp", "campaign_uuid": "cu", "junk": 1,
            }],
            "list_actions": [{
                "action_name": "noop", "action_uuid": "au",
                "action_server": {"server_name": "motor", "machine_name": "host"},
            }],
            "get_orch_state": {"loop_state": "stopped", "n_sequences": 2,
                               "n_experiments": 0, "n_actions": 0,
                               "current_stop_message": ""},
            "get_step_flags": {"actions": True, "experiments": False, "sequences": False},
            "append_sequence": {"sequence_uuid": "newseq"},
        }
        return canned.get(endpoint, {}), ErrorCodes.none

    class _Seq:
        def __init__(self):
            self.sequence_name = "seq0"
        def model_dump(self):
            return {"sequence_name": self.sequence_name}

    be = RemoteBackend.__new__(RemoteBackend)  # bypass lib loading for unit test
    be.orch_key = "ORCH"
    be.host = "127.0.0.1"
    be.port = 8001
    be._dispatch = fake_dispatch
    be._step_flags = {"actions": False, "experiments": False, "sequences": False}

    seqs = asyncio.run(be.list_sequences())
    assert seqs == [{
        "sequence_name": "seq0", "sequence_label": "lbl", "sequence_uuid": "su",
        "campaign_name": "camp", "campaign_uuid": "cu",
    }]
    acts = asyncio.run(be.list_actions())
    assert acts[0]["action_server"] == "motor"
    asyncio.run(be.add_sequence(_Seq()))
    ep, _, body = [c for c in calls if c[0] == "append_sequence"][0]
    assert body == {"sequence": {"sequence_name": "seq0"}}
    asyncio.run(be.set_step_flag("actions", True))
    assert be.get_step_flags()["actions"] is True
    print("test_remote_backend_dispatch_and_serialize PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run the module. Expected: FAIL `AttributeError: ... has no attribute 'RemoteBackend'`.

- [ ] **Step 3: Add `RemoteBackend` to `orch_backend.py`**

Add imports at top of the file:

```python
import asyncio
import functools

from helao.helpers.dispatcher import async_private_dispatcher
from helao.helpers.import_autolibs import import_autolibs
from helao.helpers.ws_utils import WsSubscriber as Wss
from helao.core.error import ErrorCodes
```

Then add the class:

```python
class RemoteBackend(OrchBackend):
    """Backend that drives a remote orchestrator over OrchAPI endpoints.

    Libraries are loaded locally (identical config -> identical libs as the
    orch), so param panels and sequence unpacking run in-process; all queue
    reads and control go over HTTP/RPC. Live refresh comes from the orch's
    ws_status WebSocket plus a slow poll safety net.
    """

    def __init__(self, vis, orch_key: str = None, poll_interval: float = 5.0):
        self.vis = vis
        self.world_cfg = vis.world_cfg
        self.orch_key = orch_key or self._detect_orch_key(vis.world_cfg)
        srv = vis.world_cfg["servers"][self.orch_key]
        self.host = srv["host"]
        self.port = srv["port"]
        self.poll_interval = poll_interval
        self._dispatch = async_private_dispatcher

        self.experiment_lib, _, _ = import_autolibs(
            world_config_dict=vis.world_cfg, lib_dir=None,
            user_lib_dir=vis.helaodirs.user_exp, lib_type="experiment",
        )
        self.sequence_lib, _, _ = import_autolibs(
            world_config_dict=vis.world_cfg, lib_dir=None,
            user_lib_dir=vis.helaodirs.user_seq, lib_type="sequence",
        )
        self._step_flags = {"actions": False, "experiments": False, "sequences": False}
        self._wss = None
        self._ws_task = None
        self._poll_task = None

    @staticmethod
    def _detect_orch_key(world_cfg) -> str:
        orch_keys = [
            k for k, v in world_cfg["servers"].items()
            if v.get("group") == "orchestrator"
        ]
        if not orch_keys:
            raise ValueError("RemoteBackend: no group:orchestrator server in config")
        return orch_keys[0]

    async def _call(self, endpoint, params_dict=None, json_dict=None):
        resp, err = await self._dispatch(
            self.orch_key, self.host, self.port, endpoint,
            params_dict=params_dict or {}, json_dict=json_dict or {},
        )
        if err != ErrorCodes.none:
            LOGGER.warning(f"RemoteBackend {endpoint} failed: {err}")
            return None
        return resp

    def unpack_sequence(self, sequence_name, sequence_params):
        return self.sequence_lib[sequence_name](**sequence_params)

    def get_step_flags(self):
        return dict(self._step_flags)

    async def set_step_flag(self, kind, value):
        await self._call("set_step_flag", params_dict={"kind": kind, "value": value})
        self._step_flags[kind] = bool(value)

    async def list_sequences(self):
        resp = await self._call("list_sequences") or []
        return [{k: row.get(k) for k in _SEQ_KEYS} for row in resp]

    async def list_experiments(self):
        resp = await self._call("list_experiments") or []
        return [{k: row.get(k) for k in _EXP_KEYS} for row in resp]

    async def list_actions(self):
        resp = await self._call("list_actions") or []
        out = []
        for row in resp:
            srv = row.get("action_server")
            srv_name = srv.get("server_name") if isinstance(srv, dict) else srv
            out.append({
                "action_name": row.get("action_name"),
                "action_server": srv_name,
                "action_uuid": row.get("action_uuid"),
            })
        return out

    async def get_histories(self):
        resp = await self._call("get_histories")
        return resp or {"action": [], "experiment": [], "sequence": []}

    async def get_status_summary(self):
        resp = await self._call("get_status_summary")
        return resp or {}

    async def get_orch_state(self):
        resp = await self._call("get_orch_state")
        return resp or {}

    async def add_sequence(self, sequence):
        return await self._call("append_sequence", json_dict={"sequence": sequence.model_dump()})

    async def add_split_sequences(self, sequence):
        return await self._call("append_split_sequences", json_dict={"sequence": sequence.model_dump()})

    async def start(self):
        await self._call("start")

    async def stop(self):
        await self._call("stop")

    async def skip(self):
        await self._call("skip_experiment")

    async def estop(self):
        await self._call("estop_orch")

    async def clear_sequences(self):
        await self._call("clear_sequences")

    async def clear_experiments(self):
        await self._call("clear_experiments")

    async def clear_actions(self):
        await self._call("clear_actions")

    def subscribe(self, on_change):
        # prime step-flag cache once
        async def _prime():
            resp = await self._call("get_step_flags")
            if resp:
                self._step_flags.update(resp)
            on_change()
        self._wss = Wss(self.host, self.port, "ws_status")
        self._ws_task = asyncio.create_task(self._ws_loop(on_change))
        self._poll_task = asyncio.create_task(self._poll_loop(on_change))
        asyncio.create_task(_prime())

    async def _ws_loop(self, on_change):
        while True:
            try:
                msgs = await self._wss.read_messages()
                if msgs:
                    on_change()
            except Exception:
                LOGGER.warning("RemoteBackend ws_status read failed", exc_info=True)
                await asyncio.sleep(1.0)
            await asyncio.sleep(0.05)

    async def _poll_loop(self, on_change):
        while True:
            await asyncio.sleep(self.poll_interval)
            on_change()

    def close(self):
        for t in (self._ws_task, self._poll_task):
            if t is not None:
                t.cancel()
```

- [ ] **Step 4: Run test to verify it passes**

Run the module. Expected: `test_remote_backend_dispatch_and_serialize PASS`.

- [ ] **Step 5: Commit**

```bash
git add helao/core/servers/operator/orch_backend.py helao/deploy/test/tests/test_standalone_operator.py
git commit -m "feat(operator): add RemoteBackend (HTTP/RPC + local libs + ws_status sync)"
```

---

## Task 4: Refactor BokehOperator constructor to take a backend

**Files:**
- Modify: `helao/core/servers/operator/bokeh_operator.py`
- Modify: `helao/core/servers/orch.py` (`makeBokehApp`, ~line 296–309; add import)

This task swaps the constructor and the in-orch call site, then makes the remaining `self.orch.*` references resolve via a temporary `self.orch = backend` shim so nothing breaks before Task 5 replaces call sites. **DRY note:** the shim is removed in Task 5.

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_operator_accepts_backend():
    import inspect
    from helao.core.servers.operator.bokeh_operator import BokehOperator
    params = list(inspect.signature(BokehOperator.__init__).parameters)
    assert params == ["self", "vis_serv", "backend"], params
    print("test_operator_accepts_backend PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run the module. Expected: FAIL (signature is `["self", "vis_serv", "orch"]`).

- [ ] **Step 3: Change the constructor signature and call site**

In `bokeh_operator.py`, change the `__init__` signature and its first lines:

```python
    def __init__(self, vis_serv: Vis, backend):
        """Build the Bokeh layout and bind the operator UI to ``backend``.

        Args:
            vis_serv: ``Vis`` helper providing the Bokeh document and config.
            backend: An ``OrchBackend`` (Local or Remote) the UI drives.
        """
        self.vis = vis_serv
        self.backend = backend
        self.orch = backend  # TEMP shim, removed in Task 5
        self.dataAPI = HTEPlateAPI()
```

In `orch.py` `makeBokehApp` (~line 309), change:

```python
        doc.operator = BokehOperator(app.vis, orch)
```
to:
```python
        from helao.core.servers.operator.orch_backend import LocalBackend
        doc.operator = BokehOperator(app.vis, LocalBackend(orch))
```

(Keep the existing `from helao.core.servers.operator.bokeh_operator import BokehOperator` import at `orch.py:43`.)

- [ ] **Step 4: Run test to verify it passes**

Run the module. Expected: `test_operator_accepts_backend PASS`.

- [ ] **Step 5: Commit**

```bash
git add helao/core/servers/operator/bokeh_operator.py helao/core/servers/orch.py helao/deploy/test/tests/test_standalone_operator.py
git commit -m "refactor(operator): BokehOperator takes OrchBackend; orch wires LocalBackend"
```

---

## Task 5: Migrate BokehOperator internals off the orch shim

**Files:**
- Modify: `helao/core/servers/operator/bokeh_operator.py`
- Test: `helao/deploy/test/tests/test_standalone_operator.py`

Replace every `self.orch.*` and the in-proc `update_q`/`IOloop` wiring with backend calls. Below is the exact mapping and the rewritten methods. After this task `self.orch` no longer exists.

**Reference — replacements (apply throughout the file):**

| Current | Replace with |
|---------|--------------|
| `self.sequence_lib = self.orch.sequence_lib` (init ~218) | `self.sequence_lib = self.backend.sequence_lib` |
| `self.experiment_lib = self.orch.experiment_lib` (~222) | `self.backend.experiment_lib` |
| `self.orch.world_cfg.get(config_key, {})` (`_build_lib` ~947) | `self.vis.world_cfg.get(config_key, {})` |
| `self.orch.world_cfg["root"]` (write/read_params ~1568,1586) | `self.vis.world_cfg["root"]` |
| `self.orch.orch_op = self` (~853) | *(deleted; replaced by subscribe wiring)* |

- [ ] **Step 1: Write the failing test**

Append a behavioral test using a mock backend that drives the table-refresh methods:

```python
class _MockBackend:
    def __init__(self):
        self.sequence_lib = {"seq0": lambda x=1: [x]}
        self.experiment_lib = {}
        self._flags = {"actions": False, "experiments": False, "sequences": False}
        self.started = False
        self.on_change = None

    def unpack_sequence(self, sequence_name, sequence_params):
        return self.sequence_lib[sequence_name](**sequence_params)

    def get_step_flags(self):
        return dict(self._flags)

    async def set_step_flag(self, kind, value):
        self._flags[kind] = value

    async def list_sequences(self):
        return [{"sequence_name": "seq0", "sequence_label": "l",
                 "sequence_uuid": "su", "campaign_name": "c", "campaign_uuid": "cu"}]

    async def list_experiments(self):
        return [{"experiment_name": "exp0", "experiment_uuid": "eu"}]

    async def list_actions(self):
        return [{"action_name": "noop", "action_server": "motor", "action_uuid": "au"}]

    async def get_histories(self):
        return {"action": [], "experiment": [], "sequence": []}

    async def get_status_summary(self):
        return {"motor": ["idle", "ok"]}

    async def get_orch_state(self):
        return {"loop_state": "stopped", "active_sequence": {}, "active_experiment": {},
                "n_sequences": 1, "n_experiments": 1, "n_actions": 1,
                "current_stop_message": ""}

    async def add_sequence(self, sequence):
        return "su"

    async def add_split_sequences(self, sequence):
        return ["su"]

    async def start(self):
        self.started = True

    async def stop(self): ...
    async def skip(self): ...
    async def estop(self): ...
    async def clear_sequences(self): ...
    async def clear_experiments(self): ...
    async def clear_actions(self): ...

    def subscribe(self, on_change):
        self.on_change = on_change

    def close(self):
        self.on_change = None


def test_operator_tables_from_backend():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator

    doc = Document()
    vis = _FakeVisOp(doc)
    be = _MockBackend()
    op = BokehOperator(vis, be)
    # backend.subscribe must have been wired
    assert be.on_change is not None
    # drive a table refresh on the doc loop
    asyncio.run(op.update_tables())
    assert op.sequence_source.data["sequence_name"] == ["seq0"]
    assert op.action_source.data["action_server"] == ["motor"]
    assert op.action_server_source.data["server_status"] == ["idle"]
    # loop_state comparison must accept a plain string
    assert "stop" in op.orch_status_button.label.lower()
    op.cleanup_session(None)
    print("test_operator_tables_from_backend PASS")
```

Also add the `_FakeVisOp` helper near the top of the test file (after imports):

```python
class _FakeDirsOp:
    def __init__(self):
        import tempfile
        from pathlib import Path
        self.root = Path(tempfile.mkdtemp())
        self.log_root = None
        self.user_exp = None
        self.user_seq = None


class _FakeVisOp:
    """Vis stand-in with the minimum surface BokehOperator reads."""
    def __init__(self, doc):
        self.doc = doc
        self.helaodirs = _FakeDirsOp()
        self.world_cfg = {
            "servers": {"ORCH": {"group": "orchestrator", "host": "h", "port": 1}},
            "root": str(self.helaodirs.root),
            "loaded_config_path": "test.yml",
        }
        self.server_cfg = {"params": {}}

    def print_message(self, *a, **k):
        pass
```

- [ ] **Step 2: Run test to verify it fails**

Run the module. Expected: FAIL — `update_tables` / table methods still call `self.orch.*` sync methods and `globalstatusmodel`, raising `AttributeError`.

- [ ] **Step 3: Rewrite the orch-touching methods**

In `bokeh_operator.py`:

(a) **Delete** the `self.orch = backend` TEMP shim line added in Task 4.

(b) **Remove** the `self.orch.orch_op = self` line (~853) and the `IOloop`/`update_q`/`IOtask` wiring in `__init__` (~850–852). Replace with backend subscribe + state init. Change:

```python
        self.IOloop_run = False
        self.IOtask = asyncio.create_task(self.IOloop())
        self.vis.doc.on_session_destroyed(self.cleanup_session)
        self.orch.orch_op = self
```
to:
```python
        self._queue_counts = {"n_sequences": 0, "n_experiments": 0, "n_actions": 0}
        self._loop_state = LoopStatus.stopped
        self._current_stop_message = ""
        self._active_sequence_name = None
        self._active_experiment_name = None
        self.backend.subscribe(self._on_backend_change)
        self.vis.doc.on_session_destroyed(self.cleanup_session)
```

(c) Add the change handler and update `cleanup_session`:

```python
    def _on_backend_change(self):
        """Backend notified a state change: schedule a table refresh on the doc thread."""
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def cleanup_session(self, session_context):
        """Tear down the backend subscription when the Bokeh session ends."""
        LOGGER.info("BokehOperator session closed")
        self.backend.close()
```

(Delete the old `IOloop` method entirely.)

(d) Rewrite the queue/history/status refresh methods to await the backend and read normalized dicts:

```python
    async def get_sequences(self):
        rows = await self.backend.list_sequences()
        for key in self.sequence_lists:
            self.sequence_lists[key] = [r.get(key) for r in rows]
        self.sequence_source.data = self.sequence_lists

    async def get_experiments(self):
        rows = await self.backend.list_experiments()
        for key in self.experiment_lists:
            self.experiment_lists[key] = [r.get(key) for r in rows]
        self.experiment_source.data = self.experiment_lists

    async def get_actions(self):
        rows = await self.backend.list_actions()
        for key in self.action_lists:
            self.action_lists[key] = [r.get(key) for r in rows]
        self.action_source.data = self.action_lists
```

Rewrite `get_history` to consume `get_histories()` (same body logic, but source the three item-lists from the backend dict):

```python
    async def get_history(self):
        hist = await self.backend.get_histories()
        for key in self.action_history_lists:
            self.action_history_lists[key] = []
        for actuuid, actdict in sorted(hist["action"], key=lambda x: x[0])[::-1]:
            self.action_history_lists["action_uuid"].append(str(actuuid)[-8:])
            self.action_history_lists["action_endpoint"].append(
                f"{actdict['action_server']}/{actdict['action_name']}"
            )
            self.action_history_lists["start"].append(actdict.get("action_timestamp", None))
            self.action_history_lists["finish"].append(actdict.get("action_finished_timestamp", None))
            for k in ["action_status", "experiment_name", "sequence_label"]:
                if k in actdict:
                    self.action_history_lists[k].append(
                        actdict[k][-1] if isinstance(actdict[k], list) else actdict[k]
                    )
        for key in self.experiment_history_lists:
            self.experiment_history_lists[key] = []
        for expuuid, expdict in sorted(hist["experiment"], key=lambda x: x[0])[::-1]:
            self.experiment_history_lists["experiment_uuid"].append(str(expuuid)[-8:])
            self.experiment_history_lists["experiment_name"].append(expdict["experiment_name"])
            self.experiment_history_lists["start"].append(expdict.get("experiment_timestamp", None))
            self.experiment_history_lists["finish"].append(expdict.get("experiment_finished_timestamp", None))
            for k in ["experiment_status", "sequence_label", "campaign_name"]:
                if k in expdict:
                    self.experiment_history_lists[k].append(
                        expdict[k][-1] if isinstance(expdict[k], list) else expdict[k]
                    )
        for key in self.sequence_history_lists:
            self.sequence_history_lists[key] = []
        for sequuid, seqdict in sorted(hist["sequence"], key=lambda x: x[0])[::-1]:
            self.sequence_history_lists["sequence_uuid"].append(str(sequuid)[-8:])
            self.sequence_history_lists["sequence_name"].append(seqdict["sequence_name"])
            self.sequence_history_lists["start"].append(seqdict.get("sequence_timestamp", None))
            self.sequence_history_lists["finish"].append(seqdict.get("sequence_finished_timestamp", None))
            for k in ["sequence_status", "sequence_label", "campaign_name"]:
                if k in seqdict:
                    self.sequence_history_lists[k].append(
                        seqdict[k][-1] if isinstance(seqdict[k], list) else seqdict[k]
                    )
        self.action_history_source.data = self.action_history_lists
        self.experiment_history_source.data = self.experiment_history_lists
        self.sequence_history_source.data = self.sequence_history_lists
```

Rewrite `get_orch_status_summary`:

```python
    async def get_orch_status_summary(self):
        summary = await self.backend.get_status_summary()
        for key in self.action_server_lists:
            self.action_server_lists[key] = []
        for server_name, (status_str, driver_str) in summary.items():
            self.action_server_lists["action_server"].append(server_name)
            self.action_server_lists["server_status"].append(status_str)
            self.action_server_lists["driver_status"].append(driver_str)
            self.action_server_source.stream(self.action_server_lists, rollover=self.num_actserv)
```

(e) Rewrite `update_tables` to fetch orch state from the backend instead of `self.orch.globalstatusmodel`. `loop_state` arrives as a string (HTTP) or a `LoopStatus` (local); compare via `.value`/str. Replace the tail of `update_tables` (from `if self.orch.globalstatusmodel.loop_state == ...` onward) with:

```python
        state = await self.backend.get_orch_state()
        self._queue_counts = {
            "n_sequences": state.get("n_sequences", 0),
            "n_experiments": state.get("n_experiments", 0),
            "n_actions": state.get("n_actions", 0),
        }
        loop_state = state.get("loop_state")
        loop_state = getattr(loop_state, "value", loop_state)  # normalize enum->str
        self._current_stop_message = state.get("current_stop_message", "") or ""
        aseq = (state.get("active_sequence") or {}).get("sequence_name")
        aexp = (state.get("active_experiment") or {}).get("experiment_name")
        if loop_state == LoopStatus.started.value:
            if aseq is not None and aexp is not None:
                self.orch_status_button.label = f"running {aseq} / {aexp}"
            else:
                self.orch_status_button.label = "running"
            self.orch_status_button.button_type = "success"
        elif loop_state == LoopStatus.stopped.value:
            stop_msg = f": {self._current_stop_message}" if self._current_stop_message else ""
            self.orch_status_button.label = f"stopped{stop_msg}"
            self.orch_status_button.button_type = "warning" if stop_msg else "primary"
        else:
            self.orch_status_button.label = f"{loop_state}"
            self.orch_status_button.button_type = "danger"
        self.button_add_expplan.label = f"Add plan [{plan_count}]"
```

(Keep the earlier part of `update_tables` that awaits `get_sequences`/`get_experiments`/`get_actions`/`get_history`/`get_orch_status_summary`, `update_queuecount_labels()`, and builds `experiment_plan_lists`.)

(f) Rewrite the control callbacks to schedule backend coroutines. `callback_start_orch` no longer reads `globalstatusmodel`; the backend/endpoints already guard state, so just call `start`:

```python
    def callback_estop_orch(self, event):
        LOGGER.info("estop orch")
        self.vis.doc.add_next_tick_callback(partial(self.backend.estop))

    def callback_start_orch(self, event):
        LOGGER.info("starting orch")
        self.vis.doc.add_next_tick_callback(partial(self.backend.start))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_stop_orch(self, event):
        LOGGER.info("stopping operator orch")
        self.vis.doc.add_next_tick_callback(partial(self.backend.stop))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_skip_exp(self, event):
        LOGGER.info("skipping experiment")
        self.vis.doc.add_next_tick_callback(partial(self.backend.skip))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_clear_sequences(self, event):
        LOGGER.info("clearing sequences")
        self.vis.doc.add_next_tick_callback(partial(self.backend.clear_sequences))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_clear_experiments(self, event):
        LOGGER.info("clearing experiments")
        self.vis.doc.add_next_tick_callback(partial(self.backend.clear_experiments))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_clear_actions(self, event):
        LOGGER.info("clearing actions")
        self.vis.doc.add_next_tick_callback(partial(self.backend.clear_actions))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))
```

(g) Rewrite `_apply_sequence_to_orch` to take a backend coroutine and the `callback_enqueue_seqspec` `self.orch.add_sequence` call:

```python
    def _apply_sequence_to_orch(self, backend_method):
        if self.sequence is None:
            return
        self.sequence.sequence_label = self.input_sequence_label.value
        if self.input_sequence_comment.value != "":
            self.sequence.sequence_comment = self.input_sequence_comment.value
        campaign_name = self.input_campaign_name.value
        if campaign_name != "":
            self.sequence.campaign_name = campaign_name
            if self.input_campaign_uuid.value.strip() == "":
                self.sequence.campaign_uuid = md5_string(campaign_name)
            else:
                self.sequence.campaign_uuid = self.input_campaign_uuid.value.strip()
        self.vis.doc.add_next_tick_callback(partial(backend_method, self.sequence))
        self.sequence = None
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))
```

Update the two callers:
```python
    def callback_add_expplan(self, event):
        self._apply_sequence_to_orch(self.backend.add_sequence)

    def callback_add_split_sequences(self, event):
        self._apply_sequence_to_orch(self.backend.add_split_sequences)
```

In `callback_enqueue_seqspec` (~1351) replace:
```python
        self.vis.doc.add_next_tick_callback(partial(self.orch.add_sequence, seq))
```
with:
```python
        self.vis.doc.add_next_tick_callback(partial(self.backend.add_sequence, seq))
```

In `callback_to_seqtab` and `callback_enqueue_seqspec`, the parser call `self.seqspec_parser.parser(specfile, self.orch, ...)` and `list_params(seqspec_path, self.orch)` pass the orch as context. Pass `self.backend` instead (parsers only read `sequence_lib`/`experiment_lib`/`world_cfg`, all present on the backend; **verify** the configured parser uses only those — if it needs more, expose it on the backend). Replace `self.orch` with `self.backend` in those three calls (~1338, 1369, 1753).

In `populate_sequence` (~1618) replace `self.orch.unpack_sequence(...)` with `self.backend.unpack_sequence(...)`.

(h) Rewrite step-flag handling. `_make_stepwise_button` reads the flag at init via `getattr(self.orch, flag_attr)`. Change it to read the backend flags dict by kind:

```python
    def _make_stepwise_button(self, flag_attr: str, kind: str, callback) -> Button:
        is_step = self.backend.get_step_flags()[kind]
        label = f"{'STEP' if is_step else 'RUN'}-THRU {kind}"
        btn = Button(label=label, button_type="danger" if is_step else "success", width=170)
        btn.on_event(ButtonClick, callback)
        return btn
```

(Note the three callers at ~374–383 pass `kind` already; the `flag_attr` arg becomes unused — keep the signature for minimal churn or drop `flag_attr` and update callers. Dropping is cleaner; update callers to `self._make_stepwise_button("actions", ...)` etc.)

Rewrite `flip_stepwise_flag` and `update_stepwise_toggle` / `update_queuecount_labels` to use the backend + cached counts:

```python
    def flip_stepwise_flag(self, sender_type):
        new_val = not self.backend.get_step_flags()[sender_type]
        self.vis.doc.add_next_tick_callback(
            partial(self.backend.set_step_flag, sender_type, new_val)
        )

    def update_stepwise_toggle(self, sender):
        sender_type = sender.label.split("[")[0].strip().split()[-1].strip()
        count_key = {"actions": "n_actions", "experiments": "n_experiments",
                     "sequences": "n_sequences"}[sender_type]
        numq = self._queue_counts.get(count_key, 0)
        self.flip_stepwise_flag(sender_type)
        if sender.button_type == "danger":
            sender.label = f"RUN-THRU {sender_type} [{numq}]"
            sender.button_type = "success"
        else:
            sender.label = f"STEP-THRU {sender_type} [{numq}]"
            sender.button_type = "danger"

    def update_queuecount_labels(self):
        for sbutton, count_key in [
            (self.orch_stepseq_button, "n_sequences"),
            (self.orch_stepexp_button, "n_experiments"),
            (self.orch_stepact_button, "n_actions"),
        ]:
            numq = self._queue_counts.get(count_key, 0)
            sbutton.label = sbutton.label.split("[")[0].strip() + f" [{numq}]"
```

(The `update_stepwise_toggle` map previously read `self.orch.action_dq` etc.; now uses cached `self._queue_counts` populated by `update_tables`.)

(i) `write_params`/`read_params` (~1568, 1586): replace `self.orch.world_cfg["root"]` with `self.vis.world_cfg["root"]`.

(j) `_build_lib` (~947): replace `self.orch.world_cfg.get(config_key, {})` with `self.vis.world_cfg.get(config_key, {})`.

- [ ] **Step 4: Run test to verify it passes**

Run the module. Expected: `test_operator_tables_from_backend PASS`. Also confirm no remaining `self.orch` references:
```
grep -n "self\.orch\b" helao/core/servers/operator/bokeh_operator.py
```
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add helao/core/servers/operator/bokeh_operator.py helao/deploy/test/tests/test_standalone_operator.py
git commit -m "refactor(operator): migrate BokehOperator internals onto OrchBackend"
```

---

## Task 6: Pluggable plate-map / HTEPlateAPI hook

**Files:**
- Modify: `helao/core/servers/operator/bokeh_operator.py`
- Test: `helao/deploy/test/tests/test_standalone_operator.py`

Today `__init__` unconditionally does `self.dataAPI = HTEPlateAPI()` and imports it at module top. That makes the operator un-importable without hte deps and always-on. Gate it behind config.

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_plate_api_disabled_by_default():
    from bokeh.document import Document
    from helao.core.servers.operator.bokeh_operator import BokehOperator
    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    assert op.dataAPI is None  # no plate_api param -> disabled
    op.cleanup_session(None)
    print("test_plate_api_disabled_by_default PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run the module. Expected: FAIL — `op.dataAPI` is an `HTEPlateAPI` instance, not `None`.

- [ ] **Step 3: Make the plate API lazy + config-gated**

In `bokeh_operator.py`, remove the top-level `from helao.helpers.plate_api import HTEPlateAPI` import. In `__init__`, replace `self.dataAPI = HTEPlateAPI()` with:

```python
        self.dataAPI = None
        plate_api_name = self.config_dict.get("plate_api")
        if plate_api_name == "HTEPlateAPI":
            from helao.helpers.plate_api import HTEPlateAPI
            self.dataAPI = HTEPlateAPI()
```

(`self.config_dict` is set from `self.vis.server_cfg.get("params", {})` — that assignment is already early in `__init__`; ensure the plate-api block runs **after** it.)

In `add_dynamic_inputs`, guard the plate-map widget creation so it only builds plate widgets when `self.dataAPI is not None`. Wrap the `if args[idx] == "solid_plate_id":` / `"solid_sample_no"` / `"x_mm"` / `"y_mm"` / `"solid_custom_position"` / `"liquid_custom_position"` / `"plate_sample_no_list"` special-casing block with:

```python
            if self.dataAPI is not None and args[idx] == "solid_plate_id":
                ...existing plate-map figure block...
            elif self.dataAPI is not None and args[idx] == "solid_sample_no":
                ...
            elif args[idx] == "solid_custom_position":   # custom positions need only dev_customitems, keep ungated
                ...
```

For `solid_custom_position` / `liquid_custom_position` (depend on `self.dev_customitems`, not `dataAPI`) keep them ungated. For `solid_plate_id` / `solid_sample_no` / `x_mm` / `y_mm` / `plate_sample_no_list` gate on `self.dataAPI is not None`; when disabled they fall through to the plain `TextInput` already created above the special-case block.

- [ ] **Step 4: Run test to verify it passes**

Run the module. Expected: `test_plate_api_disabled_by_default PASS`. Re-run the whole suite (`run_all()`) to confirm Task 5 tests still pass.

- [ ] **Step 5: Commit**

```bash
git add helao/core/servers/operator/bokeh_operator.py helao/deploy/test/tests/test_standalone_operator.py
git commit -m "feat(operator): make HTEPlateAPI plate-map hook config-gated and lazy"
```

---

## Task 7: makeBokehApp shims (test + hte deployments)

**Files:**
- Create: `helao/deploy/test/servers/operator/standalone_operator.py`
- Create: `helao/deploy/hte/servers/operator/standalone_operator.py`
- Test: `helao/deploy/test/tests/test_standalone_operator.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_shim_exposes_makebokehapp():
    import importlib, inspect
    for mod in ("helao.deploy.test.servers.operator.standalone_operator",
                "helao.deploy.hte.servers.operator.standalone_operator"):
        m = importlib.import_module(mod)
        assert hasattr(m, "makeBokehApp"), mod
        params = list(inspect.signature(m.makeBokehApp).parameters)
        assert params == ["doc", "confPrefix", "server_key", "helao_repo_root"], (mod, params)
    print("test_shim_exposes_makebokehapp PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run the module. Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Write the shim (identical content for both deployments)**

Create both files with this content (ensure each `servers/operator/` dir has an `__init__.py`; create empty ones if missing):

```python
__all__ = ["makeBokehApp"]

from socket import gethostname

from bokeh.models.widgets import Div
from bokeh.layouts import layout, Spacer

from helao.core.servers.vis import HelaoVis
from helao.core.servers.operator.orch_backend import RemoteBackend
from helao.core.servers.operator.bokeh_operator import BokehOperator
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def makeBokehApp(doc, confPrefix, server_key, helao_repo_root):
    """Build the standalone operator Bokeh document.

    Constructs a :class:`HelaoVis` host, a :class:`RemoteBackend` pointed at the
    orchestrator named by ``params.orch_key`` (or the lone group:orchestrator
    server), and a :class:`BokehOperator` UI bound to that backend.
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

Run the module. Expected: `test_shim_exposes_makebokehapp PASS`.

- [ ] **Step 5: Commit**

```bash
git add helao/deploy/test/servers/operator/ helao/deploy/hte/servers/operator/ helao/deploy/test/tests/test_standalone_operator.py
git commit -m "feat(operator): add standalone_operator makeBokehApp shims (test + hte)"
```

---

## Task 8: Finalize test runner + full-suite green

**Files:**
- Modify: `helao/deploy/test/tests/test_standalone_operator.py`

- [ ] **Step 1: Add the `run_all()` harness**

Append:

```python
def run_all():
    test_endpoint_helpers_shapes()
    test_local_backend_normalized_shapes()
    test_remote_backend_dispatch_and_serialize()
    test_operator_accepts_backend()
    test_operator_tables_from_backend()
    test_plate_api_disabled_by_default()
    test_shim_exposes_makebokehapp()
    print("ALL STANDALONE_OPERATOR TESTS PASS")


if __name__ == "__main__":
    run_all()
```

- [ ] **Step 2: Run the full module**

Run:
```
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao \
  python -m helao.deploy.test.tests.test_standalone_operator
```
Expected: `ALL STANDALONE_OPERATOR TESTS PASS`.

- [ ] **Step 3: Run the existing data_browser suite to confirm no regressions**

Run:
```
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao \
  python -m helao.deploy.test.tests.test_data_browser
```
Expected: `ALL DATA_BROWSER TESTS PASS` (unaffected; sanity that the operator/orch import changes didn't break the shared base).

- [ ] **Step 4: Run the repo unit gate**

Run:
```
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async conda run -n helao python run_unit_tests.py
```
Expected: existing sample-model unit test passes (no regression from orch_api/orch edits).

- [ ] **Step 5: Commit**

```bash
git add helao/deploy/test/tests/test_standalone_operator.py
git commit -m "test(operator): full standalone operator suite runner"
```

---

## Task 9: Config wiring + manual launch verification

**Files:**
- Modify: `helao/deploy/test/configs/test.yml` (add a `group: operator` standalone operator entry)

- [ ] **Step 1: Add the operator server entry**

In `helao/deploy/test/configs/test.yml`, under `servers:`, add (pick an unused port; match the existing orchestrator key in that file — replace `ORCH` below with the actual orchestrator server key):

```yaml
  STANDALONE_OP:
    group: operator
    bokeh: standalone_operator
    host: 127.0.0.1
    port: 5004
    params:
      orch_key: ORCH
      doc_name: "Standalone Operator (test)"
      poll_interval: 5
```

- [ ] **Step 2: Confirm `bokeh_launcher.py` handles the operator group**

Read `bokeh_launcher.py` import line (~131): it imports `helao.deploy.<dep>.servers.<group>.<bokeh>`. With `group: operator` + `bokeh: standalone_operator` this resolves to the Task 7 shim. Verify nothing in `launch.py`/`bokeh_launcher.py` special-cases `group == "visualizer"` for bokeh apps; `LAUNCH_ORDER` includes `"operator"`. If a guard rejects bokeh in the operator group, widen it. (Inspect only — no code change expected.)

- [ ] **Step 3: Manual launch (human-in-the-loop)**

Document for the operator (not automated):
```
./helao.sh test
# in the browser open the orchestrator's own operator AND http://127.0.0.1:5004/BokehOperator
# exercise: select sequence -> set params -> Append seq -> Add plan -> Start
#           -> Stop -> Skip -> Clear seqs/exps/acts -> step-thru toggles -> ESTOP
# confirm both operators show identical queues/history and that the standalone
# operator's tables refresh live (ws_status) within ~1s of orch state changes.
```

- [ ] **Step 4: Commit**

```bash
git add helao/deploy/test/configs/test.yml
git commit -m "feat(operator): wire standalone operator into test config"
```

- [ ] **Step 5: Finish the branch**

After manual verification passes, use `superpowers:finishing-a-development-branch` to merge/PR `feat/standalone-operator`.

---

## Self-Review Notes (addressed)

- **Spec §4.2 backend methods** → Tasks 2/3 implement every listed method; normalized-dict contract documented in File Structure and enforced by tests.
- **Spec §5 endpoints** → Task 1 (all 6 + `/get_orch_state` counts extension). `current_stop_message` added to `/get_orch_state` so RemoteBackend needs no separate call.
- **Spec §4.3 LocalBackend subscribe** → `_OpShim` routes `orch.update_operator`→`update_q`→`on_change`, preserving the existing in-proc push.
- **Spec §4.4 RemoteBackend ws + poll** → Task 3 `_ws_loop` + `_poll_loop`; step-flag cache primed once on subscribe.
- **Spec §4.5 plate-map hook** → Task 6 gates `HTEPlateAPI` on `params.plate_api`; widgets degrade to plain inputs when absent.
- **Spec §4.6 in-orch wiring** → Task 4 passes `LocalBackend(orch)`.
- **Spec §6 config + shim** → Tasks 7 + 9.
- **Spec §7 error handling** → `_call` returns `None` on non-`none` error code; table methods fall back to empty/last data; status banner shows non-started states.
- **Type consistency:** `get_step_flags` sync everywhere; `set_step_flag` async everywhere; list methods async returning normalized dicts; `unpack_sequence` sync. `loop_state` normalized via `getattr(x, "value", x)` to accept both enum (local) and str (remote).
- **Known verify point (not a placeholder):** Task 5(g) — the configured `seqspec_parser` must use only `sequence_lib`/`experiment_lib`/`world_cfg` from the context object; Task 9 Step 2 — operator-group bokeh launch. Both are inspection steps with a defined fallback.
