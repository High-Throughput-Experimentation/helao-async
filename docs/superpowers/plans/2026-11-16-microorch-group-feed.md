# MicroOrch Runners on /group — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show MicroOrch runners on the Reflex `/group` page beside any number of orchestrators, with a selector, peer nodes, runner E-stop, and an info box for every node and strip item.

**Architecture:** MicroOrch records run state and pushes GroupSnapshot-shaped frames over HTTP to each Reflex server, which keeps them in a `PushIngest` with the same reading surface as `WsIngest`. The `/group` page holds one feed per orchestrator and runner, renders the selected one with the existing code, and draws the rest as peer nodes. Runner object details are fetched over the runner's existing ZeroMQ dispatcher.

**Tech Stack:** Python 3.14, Reflex 0.9.x, FastAPI, httpx, pyzmq (existing `helao.core.rpc`), pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-11-16-microorch-group-feed-design.md`

## Global Constraints

- Branch: `feat/microorch-group-feed` (no upstream; never push to `unstable`).
- Run everything inside the helao env with `PYTHONPATH` at the repo root: `PYTHONPATH=$PWD python -m pytest <file> -q`.
- Never hardcode a colour outside `helao/ui/shared/palette.py` (`test_palette.py` enforces it).
- Read `helao/ui/reflex/CLAUDE.md` before editing anything under `helao/ui/reflex/`.
- Backend vars on `GroupState` touched every tick are tuples, never lists or dicts.
- Logging: `LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER`; never instantiate a logger.
- Text file IO passes `encoding="utf-8"`.
- `black` the changed files immediately before each commit.
- Do not name private deployments in any file (public repo).
- Subagents: no `git push`, no writes outside the working tree or `$CLAUDE_JOB_DIR`; use `git -C /mnt/STORAGE/repos/helao/helao-async` for every git call.
- Every new test must fail against a deliberate mutation of the code it covers before it is accepted (revert the mutation afterwards).
- Frame POST timeout 1 s; runner RPC `get_object` timeout 2 s; heartbeat 2 s; tick 100 ms; lost after `STALE_S` (5 s); runner entry removed 10 min after its last frame.

## Review Focus

1. A Reflex server that is down or hangs while a runner runs: runs must not slow or fail; POST errors are logged once per target (Task 4 test `test_post_failure_never_raises_and_logs_once`).
2. A runner killed without `DELETE` (crash, Ctrl-C): its entry must read lost within `STALE_S`, then disappear after 10 min (Task 5 test `test_silent_runner_goes_lost_then_removed`).
3. Two scripts with the same `server_key`: the second must get 409 and stop posting; the first keeps its view (Task 4 `test_409_stops_posting_to_that_target`, Task 5 `test_live_duplicate_is_409`).
4. An action whose RPC dispatch raises: the server must read `error` and a red finish pulse must appear, not a forever-busy node (Task 2 `test_dispatch_rpc_failure_emits_errored_finish`).
5. The viewed runner vanishes, or a session holds a selection that no longer exists: the page must fall back to the default feed, not blank or raise (Task 6 `test_selection_falls_back_when_runner_removed`).

---

## File Structure

| File | Responsibility |
|---|---|
| `helao/ui/shared/mask.py` (create) | `mask_secrets(obj)`: copy with credential-like keys masked. |
| `helao/core/runners/micro_orch.py` (modify) | Run-state tracking, events, `feed_config`, `get_object` RPC, feed lifecycle. |
| `helao/core/models/group_snapshot.py` (modify) | `build_runner_snapshot(micro, ...)` beside `build_snapshot`. |
| `helao/core/runners/runner_feed.py` (create) | `RunnerGraphFeed`: tick, fingerprint, POST, DELETE. |
| `helao/ui/reflex/runner_registry.py` (create) | `PushIngest`, `RunnerRegistry`, `make_runner_router`, module `REGISTRY`. |
| `helao/ui/reflex/app.py` (modify) | Mount the runner router; configure the registry's reserved keys. |
| `helao/ui/reflex/netgraph.py` (modify) | `group_layout(..., peer_keys)`. |
| `helao/ui/reflex/group.py` (modify) | Multi-feed, selector, peers, per-kind controls, node clicks, info box. |
| `helao/ui/reflex/node_info.py` (create) | Pure builders for node info: server endpoints, config views, node hit-test. |
| `helao/ui/reflex/operator.py` (modify) | `session_backend(token, orch_key=None)`, `BackendRegistry.drop_prefix`. |
| Tests (create) | `helao/core/tests/test_mask_secrets.py`, `test_micro_orch_group_state.py`, `test_runner_snapshot.py`, `test_runner_feed.py`, `test_runner_registry.py`, `test_reflex_group_multi.py`, `test_node_info.py` |
| `helao/core/tests/test_reflex_group.py` (modify) | Two `_CFG` references move to `ORCHS`. |

---

### Task 1: `mask_secrets`

**Files:**
- Create: `helao/ui/shared/mask.py`
- Test: `helao/core/tests/test_mask_secrets.py`

**Interfaces:**
- Produces: `mask_secrets(obj) -> obj` (dict/list/scalar, returns a copy), `MASK = "***"`.

- [ ] **Step 1: Write the failing test**

```python
"""mask_secrets: credential-like keys masked at any depth, input untouched."""

import copy

from helao.ui.shared.mask import MASK, mask_secrets


def test_masks_nested_secret_keys_and_keeps_others():
    cfg = {
        "host": "h",
        "server_key": "SYNC",
        "params": {
            "aws_secret_access_key": "s3cr3t",
            "api_key": "k",
            "db": {"Password": "p", "user": "u"},
            "tokens": [{"refresh_token": "t"}],
        },
    }
    before = copy.deepcopy(cfg)
    out = mask_secrets(cfg)
    assert cfg == before
    assert out["host"] == "h" and out["server_key"] == "SYNC"
    assert out["params"]["aws_secret_access_key"] == MASK
    assert out["params"]["api_key"] == MASK
    assert out["params"]["db"] == {"Password": MASK, "user": "u"}
    # a list under a masked key name is masked whole
    assert out["params"]["tokens"] == MASK


def test_scalars_and_lists_pass_through():
    assert mask_secrets(3) == 3
    assert mask_secrets([{"credential": 1}, 2]) == [{"credential": MASK}, 2]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=$PWD python -m pytest helao/core/tests/test_mask_secrets.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'helao.ui.shared.mask'`.

- [ ] **Step 3: Implement**

```python
"""Mask credential-like config values before a page renders them.

Key-name matching only: a secret stored under an innocuous key is not caught.
Keeping secrets out of config (as the sync driver does) is the real fix.
"""

import re

MASK = "***"
SECRET_KEY = re.compile(
    r"(?i)(secret|password|passwd|token|api_key|access_key|private_key|credential)"
)


def mask_secrets(obj):
    """A copy of ``obj`` with every value under a credential-like key replaced."""
    if isinstance(obj, dict):
        return {
            k: (
                MASK
                if isinstance(k, str) and SECRET_KEY.search(k)
                else mask_secrets(v)
            )
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [mask_secrets(v) for v in obj]
    return obj
```

- [ ] **Step 4: Run it to verify it passes**

Run: `PYTHONPATH=$PWD python -m pytest helao/core/tests/test_mask_secrets.py -q`
Expected: 2 passed. Mutation check: change `MASK if ...` to `v if ...`, confirm FAIL, revert.

- [ ] **Step 5: Commit**

```bash
black helao/ui/shared/mask.py helao/core/tests/test_mask_secrets.py
git -C /mnt/STORAGE/repos/helao/helao-async add helao/ui/shared/mask.py helao/core/tests/test_mask_secrets.py
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(ui): mask_secrets for config shown in pages"
```

---

### Task 2: MicroOrch run state, events, config, `get_object`

**Files:**
- Modify: `helao/core/runners/micro_orch.py` (`__init__` ~104-187, `_on_update_status` ~327, `_retire_locked` ~361, `dispatch_action` ~433, `run_experiment` ~610, `run_sequence` ~749)
- Test: `helao/core/tests/test_micro_orch_group_state.py`

**Interfaces:**
- Consumes: `ERROR_STATUSES` from `helao.core.models.group_snapshot`.
- Produces (attributes on `MicroOrch`): `instance: str`, `group_urls: Optional[list[str]]`, `active_sequence`, `last_sequence`, `active_experiment`, `last_experiment`, `finished_experiments: list[Experiment]`, `queued_experiments: list` (plan objects with `.experiment_name`), `planned_actions: list[Action]`, `server_estop: dict[str, bool]`, `finish_errors: dict[str, str]`, `t_dispatch: dict[UUID, float]`, `t_finish: dict[UUID, float]`.
- Produces (methods): `drain_events() -> list[dict]`, `active_actions() -> dict[UUID, tuple[str, str, bool]]`, `subscribed() -> set[str]`, `feed_urls() -> list[str]`, `feed_config() -> dict`, `get_object(kind: str, uuid: str) -> Optional[dict]`.
- Event dict shape: `{"kind": "dispatch"|"finish", "server": str, "action_uuid": str, "action_name": str, "status": str, "t": float}`.
- Constructor gains `group_urls: Optional[list[str]] = None` (last keyword).

- [ ] **Step 1: Write the failing tests**

```python
"""MicroOrch state the /group runner feed reads (spec: Runner side)."""

import shutil
import tempfile

import pytest
import pytest_asyncio

from helao.core.models.machine import MachineModel
from helao.core.rpc import RPCClient, derive_rpc_port
from helao.core.tests.unit_test_micro_orch import (
    _FakeDataActionServer,
    _demo_exp_func,
    _free_port,
    _make_orch,
)
from helao.helpers.premodels import Action, Experiment


@pytest_asyncio.fixture  # the repo runs pytest-asyncio in strict mode
async def rig():
    root = tempfile.mkdtemp(prefix="micro_group_")
    port = _free_port()
    fake = _FakeDataActionServer("FAKE", "ping", root)
    await fake.dispatcher.serve("127.0.0.1", derive_rpc_port(port))
    orch = _make_orch(root, {"FAKE": {"host": "127.0.0.1", "port": port}})
    orch.group_urls = []  # no feed in these tests
    await orch.start()
    try:
        yield orch
    finally:
        await orch.stop()
        await fake.dispatcher.close()
        shutil.rmtree(root, ignore_errors=True)


@pytest.mark.asyncio
async def test_run_experiment_records_and_clears_active_state(rig):
    orch = rig
    await orch.run_experiment(_demo_exp_func, experiment=Experiment(experiment_name="e1"))
    assert orch.active_experiment is None
    assert orch.last_experiment.experiment_name == "e1"
    assert [e.experiment_name for e in orch.finished_experiments] == ["e1"]
    assert len(orch.planned_actions) == 2
    assert all(a.action_uuid is not None for a in orch.planned_actions)
    events = orch.drain_events()
    kinds = [e["kind"] for e in events]
    assert kinds.count("dispatch") == 2 and kinds.count("finish") == 2
    assert all(e["server"] == "FAKE" and e["action_name"] == "ping" for e in events)
    assert orch.drain_events() == []
    u = orch.planned_actions[0].action_uuid
    assert orch.t_dispatch[u] <= orch.t_finish[u]


@pytest.mark.asyncio
async def test_dispatch_rpc_failure_emits_errored_finish(rig):
    orch = rig
    act = Action(action_name="nope", action_server=MachineModel(server_name="FAKE"))
    with pytest.raises(Exception):
        await orch.dispatch_action(act, timeout=1.0)
    events = orch.drain_events()
    assert [e["kind"] for e in events] == ["dispatch", "finish"]
    assert events[1]["status"] == "errored"
    assert orch.finish_errors["FAKE"] == "errored"
    assert orch.active_actions() == {}


@pytest.mark.asyncio
async def test_get_object_by_kind_and_uuid_over_rpc(rig):
    orch = rig
    await orch.run_experiment(_demo_exp_func, experiment=Experiment(experiment_name="e2"))
    exp_uuid = str(orch.last_experiment.experiment_uuid)
    act_uuid = str(orch.planned_actions[1].action_uuid)
    client = RPCClient(
        endpoint=f"tcp://127.0.0.1:{derive_rpc_port(orch.port)}", default_timeout=2.0
    )
    try:
        exp = await client.call("get_object", kind="experiment", uuid=exp_uuid)
        act = await client.call("get_object", kind="action", uuid=act_uuid)
        none = await client.call("get_object", kind="action", uuid="not-a-uuid")
    finally:
        await client.close()
    assert exp["experiment_name"] == "e2"
    assert act["action_name"] == "ping"
    assert none is None


def test_feed_urls_from_reflex_entries_and_override(tmp_path):
    orch = _make_orch(
        str(tmp_path),
        {
            "UI": {"host": "10.0.0.5", "port": 8100, "reflex": "helao_ui"},
            "FAKE": {"host": "h", "port": 1},
        },
    )
    assert orch.feed_urls() == ["http://10.0.0.5:8101"]
    orch.group_urls = ["http://x:1"]
    assert orch.feed_urls() == ["http://x:1"]
    orch.group_urls = []
    assert orch.feed_urls() == []


def test_feed_config_fields(tmp_path):
    orch = _make_orch(str(tmp_path), {"FAKE": {"host": "h", "port": 1}})
    cfg = orch.feed_config()
    assert cfg["server_key"] == "micro"
    assert cfg["rpc_port"] == derive_rpc_port(orch.port)
    assert cfg["world_servers"] == ["FAKE"]
    assert cfg["prefinish_experiment_hooks"] == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=$PWD python -m pytest helao/core/tests/test_micro_orch_group_state.py -q`
Expected: FAIL (`AttributeError: 'MicroOrch' object has no attribute 'group_urls'` / `drain_events`).

- [ ] **Step 3: Implement — imports and constants**

At the top of `micro_orch.py` add `import time` (stdlib block) and:

```python
from helao.core.models.group_snapshot import ERROR_STATUSES
```

Below `_PendingMeta`:

```python
#: Undrained events kept at most; the feed drains every 100 ms.
EVENTS_MAX = 500


def _finish_status(statuses) -> str:
    """The status a finish event reports: an error status wins, else ``finished``."""
    names = {str(getattr(s, "value", s)) for s in statuses or []}
    errors = sorted(names & ERROR_STATUSES)
    return errors[0] if errors else "finished"
```

- [ ] **Step 4: Implement — constructor**

Add `group_urls: Optional[list[str]] = None,` as the last `__init__` parameter (document it: "Reflex backend URLs to push /group frames to; ``None`` derives them from ``world_cfg`` reflex entries, ``[]`` disables the feed."). After `self.sequence_hooks = HookSet.empty()` add:

```python
        # /group runner feed (spec 2026-11-16-microorch-group-feed).
        self.instance = str(gen_uuid())
        self.group_urls = group_urls
        self.active_sequence: Optional[Sequence] = None
        self.last_sequence: Optional[Sequence] = None
        self.active_experiment: Optional[Experiment] = None
        self.last_experiment: Optional[Experiment] = None
        self.finished_experiments: list[Experiment] = []
        self.queued_experiments: list = []
        self.planned_actions: list[Action] = []
        self.server_estop: dict[str, bool] = {}
        self.finish_errors: dict[str, str] = {}
        # ponytail: unbounded per action; a runner is short-lived. Prune by age if one runs for days.
        self.t_dispatch: dict[UUID, float] = {}
        self.t_finish: dict[UUID, float] = {}
        self._events: list[dict] = []
        self._feed = None
        self._feed_task: Optional[asyncio.Task] = None
        self.dispatcher.register("get_object", self.get_object)
```

- [ ] **Step 5: Implement — events and accessors** (new section after `_retire_locked`)

```python
    # ------------------------------------------------------------------
    # /group feed support
    # ------------------------------------------------------------------

    def _emit(self, kind: str, server: str, name: str, uuid: UUID, status: str) -> None:
        now = time.time()
        (self.t_dispatch if kind == "dispatch" else self.t_finish)[uuid] = now
        self._events.append(
            {
                "kind": kind,
                "server": server,
                "action_uuid": str(uuid),
                "action_name": name,
                "status": status,
                "t": now,
            }
        )
        del self._events[:-EVENTS_MAX]

    def drain_events(self) -> list[dict]:
        """Events since the last drain, oldest first."""
        out, self._events = self._events, []
        return out

    def active_actions(self) -> dict:
        """``{uuid: (server, action_name, nonblocking)}`` of in-flight actions."""
        return dict(self._pending_meta)

    def subscribed(self) -> set:
        """Servers this runner has attached to."""
        return set(self._subscribed)

    def feed_urls(self) -> list[str]:
        """Reflex backends to push frames to (``group_urls`` wins when set)."""
        if self.group_urls is not None:
            return list(self.group_urls)
        servers = self.world_cfg.get("servers") or {}
        return [
            f"http://{c['host']}:{int(c['port']) + 1}"
            for c in servers.values()
            if isinstance(c, dict) and c.get("reflex")
        ]

    def feed_config(self) -> dict:
        """This runner's settings, shown when its /group node is clicked."""
        return {
            "server_key": self.server_key,
            "host": self.host,
            "port": self.port,
            "rpc_port": derive_rpc_port(self.port),
            "default_timeout": self.default_timeout,
            "finished_timeout": self.finished_timeout,
            "poll_interval": self.poll_interval,
            "group_urls": self.feed_urls(),
            "prefinish_experiment_hooks": sorted(self.experiment_hooks.hooks),
            "prefinish_sequence_hooks": sorted(self.sequence_hooks.hooks),
            "world_servers": sorted((self.world_cfg.get("servers") or {}).keys()),
        }

    def get_object(self, kind: str, uuid: str) -> Optional[dict]:
        """RPC ``get_object``: a sequence, experiment or action this runner holds."""
        if kind == "sequence":
            cands = [self.active_sequence, self.last_sequence]
            for s in cands:
                if s is not None and str(s.sequence_uuid) == uuid:
                    return s.as_dict()
        elif kind == "experiment":
            cands = [
                self.active_experiment,
                self.last_experiment,
                *reversed(self.finished_experiments),
            ]
            for e in cands:
                if e is not None and str(e.experiment_uuid) == uuid:
                    return e.as_dict()
        elif kind == "action":
            for k, dump in self._latest.items():
                if str(k) == uuid:
                    return dump
            for a in self.planned_actions:
                if str(a.action_uuid) == uuid:
                    return a.as_dict()
        return None
```

- [ ] **Step 6: Implement — hook the events in**

In `dispatch_action`, inside the first `async with self._cond:` block, after `self.last_action_uuid = action_uuid`:

```python
            self._emit("dispatch", server_name, action_name, action_uuid, "active")
```

In its `except Exception:` block, inside `async with self._cond:` after the existing pops and before `self._cond.notify_all()`:

```python
                self.finish_errors[server_name] = "errored"
                self._emit("finish", server_name, action_name, action_uuid, "errored")
```

Replace `_retire_locked`'s body with:

```python
        meta = self._pending_meta.pop(action_uuid, None)
        if meta is not None:
            # first retirement only: update_status re-reports finished actions
            status = _finish_status(dump.get("action_status"))
            self.finish_errors[meta[0]] = status
            self._emit("finish", meta[0], meta[1], action_uuid, status)
        fut = self._pending.pop(action_uuid, None)
        if fut is not None and not fut.done():
            fut.set_result(dump)
```

In `_on_update_status`, inside `async with self._cond:` before the endpoint loop:

```python
            server = actionservermodel.action_server.server_name
            if server:
                self.server_estop[server] = bool(actionservermodel.estop)
```

- [ ] **Step 7: Implement — run state in `run_experiment` and `run_sequence`**

In `run_experiment`, replace

```python
        for i, act in enumerate(actions):
            self._stage_action(act, order=i)
```

with

```python
        for i, act in enumerate(actions):
            self._stage_action(act, order=i)
        self.active_experiment = experiment
        self.planned_actions = list(actions)
        try:
            return await self._dispatch_experiment_actions(
                experiment, actions, await_completion, dispatch_timeout, wait_timeout
            )
        finally:
            self.last_experiment = experiment
            self.active_experiment = None
            self.finished_experiments.append(experiment)
```

and move the rest of the original body (from `results: list[dict] = []` to the final `return loaded`) unchanged into a new method:

```python
    async def _dispatch_experiment_actions(
        self,
        experiment: Experiment,
        actions: list[Action],
        await_completion: bool,
        dispatch_timeout: float,
        wait_timeout: Optional[float],
    ) -> Any:
        """Dispatch staged actions, wait, finish: the tail of :meth:`run_experiment`."""
        # (original body from `results: list[dict] = []` through `return loaded`)
```

In `run_sequence`, replace

```python
        planned = seq_func(**supplied)

        raw_results: list[Any] = []
        for plan in planned:
```

with

```python
        planned = seq_func(**supplied)
        self.active_sequence = sequence
        self.finished_experiments = []
        self.queued_experiments = list(planned)
        try:
            return await self._run_planned(
                sequence, planned, experiment_lib, await_completion,
                dispatch_timeout, wait_timeout,
            )
        finally:
            self.last_sequence = sequence
            self.active_sequence = None
            self.queued_experiments = []

    async def _run_planned(
        self,
        sequence: Sequence,
        planned: list,
        experiment_lib: dict,
        await_completion: bool,
        dispatch_timeout: float,
        wait_timeout: Optional[float],
    ) -> Any:
        """Run each planned experiment, then finish the sequence: the tail of :meth:`run_sequence`."""
        raw_results: list[Any] = []
        for plan in planned:
            if self.queued_experiments:
                self.queued_experiments.pop(0)
```

followed by the original loop body and everything after it (through `return loaded`) unchanged.

- [ ] **Step 8: Run the tests**

Run: `PYTHONPATH=$PWD python -m pytest helao/core/tests/test_micro_orch_group_state.py helao/core/tests/test_micro_orch_finish.py -q && PYTHONPATH=$PWD python helao/core/tests/unit_test_micro_orch.py`
Expected: all pass; the unit script reports no failures. Mutation checks: drop the `if meta is not None` guard's `_emit` (finish count test fails); remove the `except` `_emit` (errored test fails).

- [ ] **Step 9: Commit**

```bash
black helao/core/runners/micro_orch.py helao/core/tests/test_micro_orch_group_state.py
git -C /mnt/STORAGE/repos/helao/helao-async add helao/core/runners/micro_orch.py helao/core/tests/test_micro_orch_group_state.py
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(runners): MicroOrch run state, events and get_object for /group"
```

---

### Task 3: `build_runner_snapshot`

**Files:**
- Modify: `helao/core/models/group_snapshot.py` (append after `build_snapshot`)
- Test: `helao/core/tests/test_runner_snapshot.py`

**Interfaces:**
- Consumes: Task 2 attributes/methods on the micro object (duck-typed; tests use a `SimpleNamespace`).
- Produces: `build_runner_snapshot(micro, *, seq_no: int, now: float, events: list) -> dict` with every key of `build_snapshot` plus `kind="runner"`, `instance`, `config`. Server rows add `host`, `port`.

- [ ] **Step 1: Write the failing tests**

```python
"""build_runner_snapshot: a /ws_orch-shaped frame from MicroOrch state."""

from types import SimpleNamespace
from uuid import uuid4

from helao.core.models.group_snapshot import build_runner_snapshot
from helao.core.models.machine import MachineModel
from helao.helpers.premodels import Action, Experiment

ORCH_KEYS = {
    "seq_no", "t", "orch_state", "loop_state", "loop_intent", "closing_out",
    "n_sequences_queued", "seq", "orch_action", "servers", "experiments",
    "n_done", "n_queued", "act_exp", "actions", "events",
}


def _act(name, server="SIM"):
    a = Action(action_name=name, action_server=MachineModel(server_name=server))
    a.action_uuid = uuid4()
    return a


def micro(**kw):
    exp = Experiment(experiment_name="e_active")
    exp.experiment_uuid = uuid4()
    acts = [_act("wait", "ORCH"), _act("acquire_data")]
    base = dict(
        server_key="RUNNER",
        instance="i-1",
        world_cfg={"servers": {"SIM": {"host": "h", "port": 8002},
                               "ORCH": {"host": "h", "port": 8001}}},
        active_sequence=None, last_sequence=None,
        active_experiment=exp, last_experiment=None,
        finished_experiments=[], queued_experiments=[],
        planned_actions=acts,
        server_estop={}, finish_errors={},
        t_dispatch={acts[0].action_uuid: 10.0},
        t_finish={},
        active_actions=lambda: {acts[0].action_uuid: ("ORCH", "wait", False)},
        subscribed=lambda: {"ORCH", "SIM"},
        latest=lambda u: None,
        feed_config=lambda: {"server_key": "RUNNER"},
    )
    base.update(kw)
    return SimpleNamespace(**base), acts


def test_keys_match_orchestrator_frame_plus_runner_fields():
    m, _ = micro()
    snap = build_runner_snapshot(m, seq_no=1, now=11.0, events=[])
    assert ORCH_KEYS <= set(snap)
    assert snap["kind"] == "runner" and snap["instance"] == "i-1"
    assert snap["config"] == {"server_key": "RUNNER"}


def test_running_experiment_rows_and_server_status():
    m, acts = micro()
    snap = build_runner_snapshot(m, seq_no=1, now=11.0, events=[])
    assert snap["loop_state"] == "started" and snap["orch_state"] == "busy"
    assert snap["n_sequences_queued"] == 0 and snap["seq"] is None
    assert [r["state"] for r in snap["experiments"]] == ["active"]
    assert [r["state"] for r in snap["actions"]] == ["active", "queued"]
    assert snap["actions"][0]["t_start"] == 10.0
    rows = {r["key"]: r for r in snap["servers"]}
    assert rows["ORCH"]["status"] == "busy" and rows["ORCH"]["active_action"] == "wait"
    assert rows["SIM"]["status"] == "idle"
    assert (rows["SIM"]["host"], rows["SIM"]["port"]) == ("h", 8002)


def test_finished_action_done_and_error_server():
    m, acts = micro(
        active_actions=lambda: {},
        finish_errors={"SIM": "errored"},
        latest=lambda u: {"action_status": ["errored"]},
    )
    snap = build_runner_snapshot(m, seq_no=2, now=13.0, events=[])
    assert [r["state"] for r in snap["actions"]] == ["error", "error"]
    rows = {r["key"]: r for r in snap["servers"]}
    assert rows["SIM"]["status"] == "error"


def test_estop_and_idle():
    m, _ = micro(active_experiment=None, active_actions=lambda: {},
                 server_estop={"SIM": True})
    snap = build_runner_snapshot(m, seq_no=3, now=14.0, events=[])
    assert snap["loop_state"] == "estopped" and snap["orch_state"] == "estopped"
    assert {r["key"]: r["status"] for r in snap["servers"]}["SIM"] == "estop"
    m2, _ = micro(active_experiment=None, active_actions=lambda: {})
    assert build_runner_snapshot(m2, seq_no=4, now=15.0, events=[])["loop_state"] == "stopped"


def test_queued_experiments_carry_qidx_and_no_uuid():
    plans = [SimpleNamespace(experiment_name=f"q{i}") for i in range(3)]
    m, _ = micro(queued_experiments=plans)
    rows = [r for r in build_runner_snapshot(m, seq_no=1, now=1.0, events=[])["experiments"]
            if r["state"] == "queued"]
    assert [(r["name"], r["qidx"], r["uuid"]) for r in rows] == [
        ("q0", 0, None), ("q1", 1, None), ("q2", 2, None)]
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=$PWD python -m pytest helao/core/tests/test_runner_snapshot.py -q`
Expected: FAIL, `ImportError: cannot import name 'build_runner_snapshot'`.

- [ ] **Step 3: Implement** (append to `group_snapshot.py`)

```python
def _runner_action_row(m, a) -> dict:
    """One action row of a runner's ACT strip."""
    u = a.action_uuid
    if u in m.active_actions():
        state = "active"
    else:
        dump = m.latest(u)
        if dump is not None:
            state = _item_state(dump.get("action_status"))
            state = "done" if state == "active" else state
        elif u in m.t_dispatch:
            state = "done"
        else:
            state = "queued"
    return {
        "uuid": str(u) if u else None,
        "name": a.action_name,
        "server": a.action_server.server_name,
        "state": state,
        "t_start": m.t_dispatch.get(u),
        "t_end": m.t_finish.get(u),
    }


def _runner_server_rows(m) -> list:
    servers = m.world_cfg.get("servers") or {}
    active: dict = {}
    for server, name, _nb in m.active_actions().values():
        active.setdefault(server, name)
    rows = []
    for key in sorted(set(m.subscribed()) | set(active)):
        if m.server_estop.get(key):
            status = "estop"
        elif key in active:
            status = "busy"
        elif m.finish_errors.get(key) in ERROR_STATUSES:
            status = "error"
        else:
            status = "idle"
        cfg = servers.get(key) or {}
        rows.append(
            {
                "key": key,
                "status": status,
                "active_action": active.get(key),
                "host": cfg.get("host"),
                "port": cfg.get("port"),
            }
        )
    return rows


def build_runner_snapshot(micro, *, seq_no: int, now: float, events: list) -> dict:
    """One runner frame, shaped like :func:`build_snapshot`'s (spec D5)."""
    m = micro
    seq = m.active_sequence or m.last_sequence
    done_all = list(m.finished_experiments)
    done = done_all[-EXP_DONE_WINDOW:]
    experiments = [
        {
            "uuid": str(e.experiment_uuid),
            "name": e.experiment_name,
            "state": "error" if _item_state(e.experiment_status) == "error" else "done",
            "t_start": epoch(e.experiment_timestamp),
            "t_end": epoch(e.experiment_finished_timestamp),
            "qidx": None,
        }
        for e in done
    ]
    exp = m.active_experiment
    if exp is not None:
        experiments.append(
            {
                "uuid": str(exp.experiment_uuid),
                "name": exp.experiment_name,
                "state": "active",
                "t_start": epoch(exp.experiment_timestamp),
                "t_end": None,
                "qidx": None,
            }
        )
    queued = list(m.queued_experiments)
    experiments += [
        {
            "uuid": None,
            "name": p.experiment_name,
            "state": "queued",
            "t_start": None,
            "t_end": None,
            "qidx": i,
        }
        for i, p in enumerate(queued[:EXP_QUEUED_WINDOW])
    ]
    act_exp = m.active_experiment or m.last_experiment
    servers = _runner_server_rows(m)
    running = bool(m.active_actions()) or m.active_experiment is not None or (
        m.active_sequence is not None
    )
    if any(r["status"] == "estop" for r in servers):
        loop_state, orch_state = "estopped", "estopped"
    elif running:
        loop_state, orch_state = "started", "busy"
    else:
        loop_state, orch_state = "stopped", "idle"
    return {
        "seq_no": seq_no,
        "t": now,
        "orch_state": orch_state,
        "loop_state": loop_state,
        "loop_intent": "none",
        "closing_out": False,
        "n_sequences_queued": 0,
        "seq": (
            {
                "uuid": str(seq.sequence_uuid),
                "name": seq.sequence_name,
                "label": seq.sequence_label,
                "t_start": epoch(seq.sequence_timestamp),
                "finished": m.active_sequence is None,
                "ended": _seq_ended(seq, m.active_sequence is None),
            }
            if seq is not None
            else None
        ),
        "orch_action": None,
        "servers": servers,
        "experiments": experiments,
        "n_done": len(done_all) - len(done),
        "n_queued": max(0, len(queued) - EXP_QUEUED_WINDOW),
        "act_exp": str(act_exp.experiment_uuid) if act_exp is not None else None,
        "actions": [_runner_action_row(m, a) for a in m.planned_actions],
        "events": list(events),
        "kind": "runner",
        "instance": m.instance,
        "config": m.feed_config(),
    }
```

The `seq` dict and `ORCH_KEYS` match `build_snapshot` as of `origin/unstable` (checked while planning); if `build_snapshot` gained a key since, add it here too.

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=$PWD python -m pytest helao/core/tests/test_runner_snapshot.py helao/hexagon/tests/test_group_snapshot.py -q`
Expected: all pass. Mutation check: swap `"busy"`/`"idle"` in `_runner_server_rows`, confirm FAIL, revert.

- [ ] **Step 5: Commit**

```bash
black helao/core/models/group_snapshot.py helao/core/tests/test_runner_snapshot.py
git -C /mnt/STORAGE/repos/helao/helao-async add helao/core/models/group_snapshot.py helao/core/tests/test_runner_snapshot.py
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(group): build_runner_snapshot for MicroOrch frames"
```

---

### Task 4: `RunnerGraphFeed` and its lifecycle in MicroOrch

**Files:**
- Create: `helao/core/runners/runner_feed.py`
- Modify: `helao/core/runners/micro_orch.py` (`start`, `stop`)
- Test: `helao/core/tests/test_runner_feed.py`

**Interfaces:**
- Consumes: `build_runner_snapshot` (Task 3); `drain_events`, `active_actions`, `feed_urls`, `server_key`, `instance` (Task 2).
- Produces: `RunnerGraphFeed(micro, urls, *, tick_s=0.1, heartbeat_s=2.0, clock=time.time, client=None)` with `step(now) -> Optional[dict]`, `async post(frame) -> None`, `async run() -> None`, `async close() -> None`, attribute `blocked: set[str]`.
- Wire: `POST {url}/runners/{key}/frame` (JSON frame), `DELETE {url}/runners/{key}?instance=<id>`.

- [ ] **Step 1: Write the failing tests**

```python
"""RunnerGraphFeed: change/heartbeat framing and fail-safe POSTs."""

import httpx
import pytest

from helao.core.runners import runner_feed as rf
from helao.core.tests.test_runner_snapshot import micro


class Recorder:
    def __init__(self, status=200, raise_exc=None):
        self.calls = []
        self.status = status
        self.raise_exc = raise_exc

    def __call__(self, request: httpx.Request):
        self.calls.append((request.method, str(request.url)))
        if self.raise_exc:
            raise self.raise_exc
        return httpx.Response(self.status)


def feed_with(handler, urls=("http://ui:1",)):
    m, _ = micro()
    m.drain_events = lambda: []
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return rf.RunnerGraphFeed(m, list(urls), client=client), m


def test_step_frames_on_change_and_heartbeat_only():
    f, m = feed_with(Recorder())
    assert f.step(0.0) is not None          # first frame
    assert f.step(0.5) is None              # unchanged, no heartbeat yet
    assert f.step(2.1) is not None          # heartbeat
    m.active_actions = lambda: {}
    m.active_experiment = None
    assert f.step(2.2) is not None          # state changed


def test_events_force_a_frame():
    f, m = feed_with(Recorder())
    f.step(0.0)
    m.drain_events = lambda: [{"kind": "dispatch"}]
    snap = f.step(0.1)
    assert snap is not None and snap["events"] == [{"kind": "dispatch"}]


@pytest.mark.asyncio
async def test_post_failure_never_raises_and_logs_once(monkeypatch):
    warnings = []
    monkeypatch.setattr(rf.LOGGER, "warning", lambda msg, *a, **k: warnings.append(msg))
    rec = Recorder(raise_exc=httpx.ConnectError("down"))
    f, _ = feed_with(rec)
    frame = f.step(0.0)
    await f.post(frame)
    await f.post(frame)
    assert len(rec.calls) == 2
    assert len(warnings) == 1 and "frame POST" in warnings[0]


@pytest.mark.asyncio
async def test_409_stops_posting_to_that_target():
    rec = Recorder(status=409)
    f, _ = feed_with(rec)
    frame = f.step(0.0)
    await f.post(frame)
    await f.post(frame)
    assert len(rec.calls) == 1 and f.blocked == {"http://ui:1"}


@pytest.mark.asyncio
async def test_close_sends_delete_with_instance():
    rec = Recorder()
    f, _ = feed_with(rec)
    await f.close()
    assert rec.calls == [("DELETE", "http://ui:1/runners/RUNNER?instance=i-1")]
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=$PWD python -m pytest helao/core/tests/test_runner_feed.py -q`
Expected: FAIL, `ImportError` on `runner_feed`.

- [ ] **Step 3: Implement `runner_feed.py`**

```python
"""Push a MicroOrch's /group frames to Reflex backends (spec D1/D2).

Never in a run's way: each POST is short-timeout, errors are logged once per
target and swallowed, and a 409 (key held by another live runner) stops posting
to that target for good.
"""

import asyncio
import time
from typing import Optional

import httpx

from helao.core.models.group_snapshot import build_runner_snapshot
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

TICK_S = 0.1
HEARTBEAT_S = 2.0
POST_TIMEOUT_S = 1.0


def fingerprint(m) -> tuple:
    """Everything a frame shows, cheaply."""
    return (
        tuple(sorted(str(u) for u in m.active_actions())),
        str(getattr(m.active_sequence, "sequence_uuid", None)),
        str(getattr(m.active_experiment, "experiment_uuid", None)),
        str(getattr(m.last_experiment, "experiment_uuid", None)),
        len(m.finished_experiments),
        len(m.queued_experiments),
        len(m.planned_actions),
        len(m.t_finish),
        tuple(sorted(m.server_estop.items())),
        tuple(sorted(m.finish_errors.items())),
        tuple(sorted(m.subscribed())),
    )


class RunnerGraphFeed:
    """Builds runner frames and POSTs them to every target URL."""

    def __init__(
        self, micro, urls, *, tick_s=TICK_S, heartbeat_s=HEARTBEAT_S,
        clock=time.time, client: Optional[httpx.AsyncClient] = None,
    ):
        self.micro = micro
        self.urls = list(urls)
        self.tick_s = tick_s
        self.heartbeat_s = heartbeat_s
        self.clock = clock
        self.client = client or httpx.AsyncClient(timeout=POST_TIMEOUT_S)
        self.blocked: set = set()
        self._failing: set = set()
        self._seq_no = 0
        self._last_fp = None
        self._last_sent = float("-inf")

    def step(self, now: float) -> Optional[dict]:
        """A frame when something changed, events arrived, or a heartbeat is due."""
        events = self.micro.drain_events()
        fp = fingerprint(self.micro)
        if fp == self._last_fp and not events and now - self._last_sent < self.heartbeat_s:
            return None
        self._seq_no += 1
        self._last_fp, self._last_sent = fp, now
        return build_runner_snapshot(
            self.micro, seq_no=self._seq_no, now=now, events=events
        )

    def _path(self, url: str) -> str:
        return f"{url}/runners/{self.micro.server_key}"

    async def post(self, frame: dict) -> None:
        for url in self.urls:
            if url in self.blocked:
                continue
            try:
                r = await self.client.post(
                    f"{self._path(url)}/frame", json=frame, timeout=POST_TIMEOUT_S
                )
            except Exception as exc:
                if url not in self._failing:
                    self._failing.add(url)
                    LOGGER.warning(f"/group frame POST to {url} failed: {exc!r}")
                continue
            if r.status_code == 409:
                self.blocked.add(url)
                LOGGER.warning(
                    f"/group at {url} already shows a live runner named "
                    f"{self.micro.server_key!r}; not posting there"
                )
            elif r.status_code >= 400:
                if url not in self._failing:
                    self._failing.add(url)
                    LOGGER.warning(f"/group frame POST to {url}: HTTP {r.status_code}")
            else:
                self._failing.discard(url)

    async def run(self) -> None:
        """Tick until cancelled; a failed frame build is logged and skipped."""
        while True:
            try:
                frame = self.step(self.clock())
                if frame is not None:
                    await self.post(frame)
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("runner graph feed: frame skipped")
            await asyncio.sleep(self.tick_s)

    async def close(self) -> None:
        """Deregister from every target (best effort), then close the client."""
        for url in self.urls:
            try:
                await self.client.delete(
                    self._path(url),
                    params={"instance": self.micro.instance},
                    timeout=POST_TIMEOUT_S,
                )
            except Exception:
                pass
        await self.client.aclose()
```

- [ ] **Step 4: Wire into MicroOrch**

At the end of `MicroOrch.start()` (after `await self.dispatcher.serve(...)`):

```python
        urls = self.feed_urls()
        if urls:
            from helao.core.runners.runner_feed import RunnerGraphFeed

            self._feed = RunnerGraphFeed(self, urls)
            self._feed_task = asyncio.create_task(self._feed.run())
```

At the start of `MicroOrch.stop()`:

```python
        if self._feed_task is not None:
            self._feed_task.cancel()
            try:
                await self._feed_task
            except asyncio.CancelledError:
                pass
            self._feed_task = None
        if self._feed is not None:
            await self._feed.close()
            self._feed = None
```

- [ ] **Step 5: Run tests**

Run: `PYTHONPATH=$PWD python -m pytest helao/core/tests/test_runner_feed.py helao/core/tests/test_micro_orch_group_state.py helao/core/tests/test_micro_orch_finish.py -q`
Expected: all pass. Mutation: delete `self.blocked.add(url)`, confirm the 409 test fails, revert.

- [ ] **Step 6: Commit**

```bash
black helao/core/runners/runner_feed.py helao/core/runners/micro_orch.py helao/core/tests/test_runner_feed.py
git -C /mnt/STORAGE/repos/helao/helao-async add helao/core/runners/runner_feed.py helao/core/runners/micro_orch.py helao/core/tests/test_runner_feed.py
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(runners): push /group frames from MicroOrch to Reflex"
```

---

### Task 5: Runner registry, `PushIngest`, routes

**Files:**
- Create: `helao/ui/reflex/runner_registry.py`
- Modify: `helao/ui/reflex/app.py` (~line 696: `backend.include_router(...)`)
- Test: `helao/core/tests/test_runner_registry.py`

**Interfaces:**
- Consumes: `IngestStatus` from `helao.ui.reflex.ingest`.
- Produces:
  - `PushIngest(instance: str)`: `raw: deque` (maxlen 200), `n_batches: int`, `status: IngestStatus`, `instance`, `ended: bool`, `last_frame_at: float`, `put(frame, now)`, `end()`, `rpc(host, port) -> RPCClient` (cached), `async aclose()`.
  - `RunnerRegistry(clock=time.time)`: `reserve(keys)`, `post(key, frame) -> int`, `delete(key, instance) -> int`, `get(key) -> Optional[PushIngest]`, `keys() -> list[str]` (registration order), `sweep(now) -> list[PushIngest]` (removed entries; caller closes them).
  - `make_runner_router(registry) -> APIRouter`.
  - Module `REGISTRY = RunnerRegistry()`.
  - Constants `STALE_S = 5.0`, `EXPIRE_S = 600.0`.

- [ ] **Step 1: Write the failing tests**

```python
"""Runner registry: registration, 409 rules, deregister, expiry."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from helao.ui.reflex.runner_registry import (
    EXPIRE_S, STALE_S, RunnerRegistry, make_runner_router,
)


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def rig():
    clock = Clock()
    reg = RunnerRegistry(clock=clock)
    reg.reserve(["ORCH", "SIM"])
    app = FastAPI()
    app.include_router(make_runner_router(reg))
    return reg, TestClient(app), clock


def frame(instance="a", **kw):
    return {"kind": "runner", "instance": instance, "seq_no": 1, **kw}


def test_register_then_append():
    reg, c, _ = rig()
    assert c.post("/runners/R1/frame", json=frame()).status_code == 200
    assert c.post("/runners/R1/frame", json=frame()).status_code == 200
    feed = reg.get("R1")
    assert feed.n_batches == 2 and feed.status.message_count == 2
    assert reg.keys() == ["R1"]


def test_live_duplicate_is_409_and_reserved_key_is_409():
    reg, c, clock = rig()
    c.post("/runners/R1/frame", json=frame("a"))
    assert c.post("/runners/R1/frame", json=frame("b")).status_code == 409
    assert c.post("/runners/SIM/frame", json=frame("a")).status_code == 409
    assert reg.get("R1").instance == "a"


def test_lost_entry_is_replaced_by_new_instance():
    reg, c, clock = rig()
    c.post("/runners/R1/frame", json=frame("a"))
    clock.t += STALE_S + 0.1
    assert c.post("/runners/R1/frame", json=frame("b")).status_code == 200
    assert reg.get("R1").instance == "b" and reg.get("R1").n_batches == 1


def test_delete_right_and_wrong_instance():
    reg, c, _ = rig()
    c.post("/runners/R1/frame", json=frame("a"))
    assert c.delete("/runners/R1", params={"instance": "x"}).status_code == 404
    assert c.delete("/runners/R1", params={"instance": "a"}).status_code == 200
    assert reg.get("R1").ended


def test_silent_runner_goes_lost_then_removed():
    reg, c, clock = rig()
    c.post("/runners/R1/frame", json=frame("a"))
    feed = reg.get("R1")
    assert clock.t - feed.status.last_epoch <= STALE_S
    clock.t += EXPIRE_S - 1
    assert reg.sweep(clock.t) == [] and reg.get("R1") is feed
    clock.t += 2
    assert reg.sweep(clock.t) == [feed] and reg.get("R1") is None


def test_bad_body_is_400():
    _, c, _ = rig()
    assert c.post("/runners/R1/frame", json={"kind": "runner"}).status_code == 400
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=$PWD python -m pytest helao/core/tests/test_runner_registry.py -q`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Implement `runner_registry.py`**

```python
"""Runners that push /group frames to this Reflex process (spec: Page side).

A runner's first ``POST /runners/{key}/frame`` registers it; ``DELETE`` marks it
ended. :class:`PushIngest` has the reading surface /group uses on ``WsIngest``
(``raw``, ``n_batches``, ``status``), so the page's frame helpers take either.
"""

import collections
import threading
import time
from typing import Optional

from fastapi import APIRouter, Request, Response

from helao.core.rpc import RPCClient
from helao.ui.reflex.ingest import IngestStatus

STALE_S = 5.0
EXPIRE_S = 600.0
RPC_TIMEOUT_S = 2.0


class PushIngest:
    """One runner's frames, newest last."""

    def __init__(self, instance: str):
        self.instance = instance
        self.raw: collections.deque = collections.deque(maxlen=200)
        self.n_batches = 0
        self.status = IngestStatus()
        self.ended = False
        self.last_frame_at = 0.0
        self._rpc: Optional[RPCClient] = None

    def put(self, frame: dict, now: float) -> None:
        self.raw.append([frame])
        self.n_batches += 1
        self.status.message_count += 1
        self.status.last_epoch = now
        self.status.state = "live"
        self.last_frame_at = now

    def end(self) -> None:
        """Deregistered: read as lost at once."""
        self.ended = True
        self.status.last_epoch = 0.0
        self.status.state = "ended"

    def lost(self, now: float) -> bool:
        return self.ended or now - self.status.last_epoch > STALE_S

    def rpc(self, host: str, port: int) -> RPCClient:
        if self._rpc is None:
            self._rpc = RPCClient(
                endpoint=f"tcp://{host}:{port}", default_timeout=RPC_TIMEOUT_S
            )
        return self._rpc

    async def aclose(self) -> None:
        if self._rpc is not None:
            await self._rpc.close()
            self._rpc = None


class RunnerRegistry:
    """``key -> PushIngest``; safe to read from the tick and write from routes."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self._lock = threading.Lock()
        self._entries: dict = {}
        self._reserved: set = set()

    def reserve(self, keys) -> None:
        """Keys a runner may not take (every server key of the page's config)."""
        self._reserved = set(keys)

    def post(self, key: str, frame: dict) -> int:
        instance = frame.get("instance") if isinstance(frame, dict) else None
        if not instance:
            return 400
        if key in self._reserved:
            return 409
        now = self.clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.instance != instance:
                if not entry.lost(now):
                    return 409
                entry = None  # replaced; the old one's RPC client closes on sweep
            if entry is None:
                entry = PushIngest(instance)
                self._entries[key] = entry
            entry.put(frame, now)
        return 200

    def delete(self, key: str, instance: str) -> int:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry.instance != instance:
                return 404
            entry.end()
        return 200

    def get(self, key: str) -> Optional[PushIngest]:
        with self._lock:
            return self._entries.get(key)

    def keys(self) -> list:
        with self._lock:
            return list(self._entries)

    def sweep(self, now: float) -> list:
        """Remove entries silent for ``EXPIRE_S``; return them for closing."""
        with self._lock:
            gone = [k for k, e in self._entries.items() if now - e.last_frame_at > EXPIRE_S]
            return [self._entries.pop(k) for k in gone]


def make_runner_router(registry: RunnerRegistry) -> APIRouter:
    router = APIRouter()

    @router.post("/runners/{key}/frame")
    async def post_frame(key: str, request: Request) -> Response:
        try:
            frame = await request.json()
        except Exception:
            return Response(status_code=400)
        return Response(status_code=registry.post(key, frame))

    @router.delete("/runners/{key}")
    async def delete_runner(key: str, instance: str) -> Response:
        return Response(status_code=registry.delete(key, instance))

    return router


REGISTRY = RunnerRegistry()
```

Note: `test_lost_entry_is_replaced_by_new_instance` drops the old entry without closing its RPC client. Fix that leak in `post`: collect the replaced entry and schedule `asyncio.get_running_loop().create_task(old.aclose())` when a loop is running (routes always run on one). Add that and keep the test passing.

- [ ] **Step 4: Mount in `app.py`**

After `backend.include_router(make_buffer_router(plots.STORE))`:

```python
    backend.include_router(make_runner_router(RUNNERS))
```

with the import near the other `helao.ui.reflex` imports:

```python
from helao.ui.reflex.runner_registry import REGISTRY as RUNNERS, make_runner_router
```

(`configure_group` reserves the keys in Task 6.)

- [ ] **Step 5: Run tests**

Run: `PYTHONPATH=$PWD python -m pytest helao/core/tests/test_runner_registry.py -q`
Expected: 6 passed. Mutation: make `post` skip the reserved check, confirm FAIL, revert.

- [ ] **Step 6: Commit**

```bash
black helao/ui/reflex/runner_registry.py helao/ui/reflex/app.py helao/core/tests/test_runner_registry.py
git -C /mnt/STORAGE/repos/helao/helao-async add helao/ui/reflex/runner_registry.py helao/ui/reflex/app.py helao/core/tests/test_runner_registry.py
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(reflex): runner registry and frame routes"
```

---

### Task 6: `/group` multi-feed, selector, peers, per-kind controls

**Files:**
- Modify: `helao/ui/reflex/netgraph.py` (`group_layout`)
- Modify: `helao/ui/reflex/group.py`
- Modify: `helao/core/tests/test_reflex_group.py` (lines ~384 and ~789)
- Test: `helao/core/tests/test_reflex_group_multi.py`

**Interfaces:**
- Consumes: `REGISTRY`, `PushIngest` (Task 5); runner frame fields `kind`, `servers[].host/port` (Task 3).
- Produces in `group.py`:
  - `ORCHS: dict[str, dict]` (`{key: {"host", "port"}}`, config order), `_FEEDS: dict[str, WsIngest]`, `_WORLD: dict`.
  - `feed_keys() -> list[str]`, `feed_for(key) -> Optional[ingest]`, `feed_kind(key) -> Optional[str]` (`"orchestrator"|"runner"`), `default_key() -> str` (`""` when none), `resolve_key(selected: str) -> str`.
  - `peer_rows(selected: str, now: float) -> list[tuple[str, str]]`.
  - `ESTOP_LATCH: dict[str, bool]`.
  - `async _runner_estop(snap: dict, switch: bool) -> list[str]` (error strings).
  - `build_graph(snap, orch_key, lost, peers=())`; `apply_tick(s, feed, now, token, key=None, peers=())`.
  - `GroupState.selected_feed: str`, `GroupState.selected_kind: str`, `GroupState.feed_options: list[dict]` (`{"key", "label"}`), event `set_feed(key: str)`.
- Produces in `netgraph.py`: `group_layout(orch_key, server_keys, peer_keys=())`, `PEER_X = (-0.55, 0.55, -0.85, 0.85)`.

- [ ] **Step 1: Write the failing tests**

```python
"""/group with several orchestrators and runners (spec: Page side)."""

import asyncio

import pytest

from helao.ui.reflex import group
from helao.ui.reflex.netgraph import group_layout
from helao.ui.reflex.runner_registry import REGISTRY, RunnerRegistry

CFG = {
    "servers": {
        "SIM": {"host": "h", "port": 1, "group": "action"},
        "ORCH": {"host": "h", "port": 2, "group": "orchestrator"},
        "ORCH2": {"host": "h", "port": 3, "group": "orchestrator"},
    }
}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    reg = RunnerRegistry(clock=lambda: 1000.0)
    monkeypatch.setattr(group, "REGISTRY", reg)
    group.configure_group(CFG)
    group.ESTOP_LATCH.clear()
    yield reg
    group.configure_group({"servers": {}})


def runner_frame(**kw):
    return {
        "kind": "runner", "instance": "i", "seq_no": 1, "t": 1000.0,
        "orch_state": "busy", "loop_state": "started",
        "servers": [{"key": "SIM", "status": "busy", "active_action": "a",
                     "host": "h", "port": 1}],
        "experiments": [], "actions": [], "events": [], **kw,
    }


def test_all_orchestrators_and_runners_are_feeds(fresh):
    fresh.post("R1", runner_frame())
    assert group.feed_keys() == ["ORCH", "ORCH2", "R1"]
    assert group.feed_kind("ORCH2") == "orchestrator"
    assert group.feed_kind("R1") == "runner"
    assert group.default_key() == "ORCH"


def test_reserved_keys_come_from_config(fresh):
    assert fresh.post("SIM", runner_frame()) == 409


def test_runner_only_config_defaults_to_runner(fresh):
    group.configure_group({"servers": {"SIM": CFG["servers"]["SIM"]}})
    fresh.post("R1", runner_frame())
    assert group.default_key() == "R1"


def test_selection_falls_back_when_runner_removed(fresh):
    fresh.post("R1", runner_frame())
    assert group.resolve_key("R1") == "R1"
    fresh.sweep(10_000.0)
    assert group.resolve_key("R1") == "ORCH"
    assert group.resolve_key("") == "ORCH"


def test_peer_layout_on_centre_row():
    pos = group_layout("ORCH", ["SIM"], ["R1", "ORCH2"])
    assert pos["ORCH2"] == (-0.55, 0.0) and pos["R1"] == (0.55, 0.0)
    assert pos["ORCH"] == (0.0, 0.0)


def test_build_graph_adds_peer_nodes_without_edges():
    g = group.build_graph(runner_frame(), "R1", False, peers=[("ORCH", "idle")])
    assert "ORCH" in g.nodes and "SIM" in g.nodes
    assert all("ORCH" not in (e.src, e.dst) for e in g.edges.values())


def test_peer_rows_status(fresh):
    fresh.post("R1", runner_frame())
    rows = dict(group.peer_rows("ORCH", 1000.5))
    assert rows["R1"] == "busy"
    assert rows["ORCH2"] == "unreachable"  # no stream in a unit test
    assert "ORCH" not in rows


def test_runner_estop_calls_every_server_and_latches(monkeypatch, fresh):
    calls = []

    async def fake(server, host, port, path, params_dict=None, json_dict=None):
        calls.append((server, path, params_dict))
        return {}, group.ErrorCodes.none

    monkeypatch.setattr(group, "async_private_dispatcher", fake)
    errs = asyncio.run(group._runner_estop(runner_frame(), True))
    assert errs == [] and calls == [("SIM", "SIM/estop", {"switch": True})]


def test_runner_buttons_hide_start_stop():
    flags = group.button_flags(runner_frame(), False, kind="runner")
    assert flags["can_start"] is False and flags["can_stop"] is False
    flags = group.button_flags(runner_frame(), False, kind="runner", latched=True)
    assert flags["estopped"] is True and flags["can_clear_estop"] is True
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=$PWD python -m pytest helao/core/tests/test_reflex_group_multi.py -q`
Expected: FAIL (`AttributeError: module 'helao.ui.reflex.group' has no attribute 'feed_keys'`).

- [ ] **Step 3: `netgraph.group_layout` peers**

```python
#: Peer (other orchestrator / runner) slots on the centre row.
PEER_X = (-0.55, 0.55, -0.85, 0.85)


def group_layout(orch_key, server_keys, peer_keys=()):
    """Orchestrator at (0, 0); servers sorted, alternating above/below; peers
    on the centre row.

    Up to 8 servers per row sit at y = +/-0.7, evenly spaced in x; above 8 a row
    splits into two bands at +/-0.4 and +/-0.9.
    """
    keys = sorted(server_keys)
    pos = {orch_key: (0.0, 0.0)}
    for row, sign in ((keys[0::2], 1.0), (keys[1::2], -1.0)):
        bands = [(row, 0.7)] if len(row) <= 8 else [(row[0::2], 0.4), (row[1::2], 0.9)]
        for band, y in bands:
            n = len(band)
            for i, key in enumerate(band):
                pos[key] = (-0.9 + 1.8 * (i + 0.5) / n, sign * y)
    # ponytail: 4 centre-row slots; a 5th+ peer overlaps one. Add a row when needed.
    for i, key in enumerate(sorted(peer_keys)):
        pos[key] = (PEER_X[i % len(PEER_X)], 0.0)
    return pos
```

- [ ] **Step 4: `group.py` — feeds**

Replace `_CFG`/`_FEED`, `configure_group`, `start_feed`, `stop_feed` with:

```python
from helao.ui.reflex.runner_registry import REGISTRY

ORCHS: dict = {}
_FEEDS: dict = {}
_WORLD: dict = {}
#: runner key -> True while the page has E-stopped its servers (spec: Controls).
ESTOP_LATCH: dict = {}


def configure_group(world_cfg: dict) -> None:
    """Record every ``group: orchestrator`` server, in config order."""
    servers = (world_cfg or {}).get("servers") or {}
    ORCHS.clear()
    _WORLD.clear()
    _WORLD.update(world_cfg or {})
    for k, v in servers.items():
        if isinstance(v, dict) and v.get("group") == "orchestrator":
            ORCHS[k] = {"host": v["host"], "port": v["port"]}
    REGISTRY.reserve(servers.keys())


def start_feed() -> None:
    """Subscribe to every orchestrator's /ws_orch once per process."""
    for key, c in ORCHS.items():
        if key not in _FEEDS:
            _FEEDS[key] = WsIngest(c["host"], c["port"], "ws_orch", raw_maxlen=200)
            _FEEDS[key].start()


async def stop_feed() -> None:
    feeds = list(_FEEDS.values())
    _FEEDS.clear()
    for f in feeds:
        await f.stop()


def feed_keys() -> list:
    return [*ORCHS, *(k for k in REGISTRY.keys() if k not in ORCHS)]


def feed_kind(key: str):
    if key in ORCHS:
        return "orchestrator"
    return "runner" if REGISTRY.get(key) is not None else None


def feed_for(key: str):
    return _FEEDS.get(key) if key in ORCHS else REGISTRY.get(key)


def default_key() -> str:
    keys = feed_keys()
    return keys[0] if keys else ""


def resolve_key(selected: str) -> str:
    """``selected`` if it is still a feed, else the default."""
    return selected if selected and feed_kind(selected) else default_key()


def _feed_status(key: str, now: float) -> str:
    feed = feed_for(key)
    if stream_lost(feed, now):
        return "unreachable"
    snap = latest_frame(feed) or {}
    return ORCH_TO_GROUP.get(snap.get("orch_state") or "", "idle")


def peer_rows(selected: str, now: float) -> list:
    """``[(key, status)]`` of every feed but the selected one."""
    return [(k, _feed_status(k, now)) for k in feed_keys() if k != selected]
```

`REGISTRY` is read through the module attribute at call time (the tests monkeypatch it), so every function above must say `REGISTRY`, not a captured local.

Remove the `len(keys) > 1` warning (several orchestrators are now supported).

- [ ] **Step 5: `group.py` — graph, buttons, tick**

`build_graph(snap, orch_key, lost, peers=())`: pass `[k for k, _ in peers]` as `group_layout`'s third argument, and after the server loop add:

```python
    for key, status in peers:
        c = _color_key(status)
        g.add_node(
            key,
            *pos[key],
            color=GROUP_STATE_COLORS[c],
            label_color=GROUP_LABEL_COLORS[c],
            text=key,
            subtext="",
            size_px=NODE_PX,
        )
```

`graph_marks`, `pulse_items` and `_render_graph` gain a `peers=()` parameter passed through to `build_graph`; `_render_graph(s, snap, lost, token, key, peers)` uses `key` instead of `_CFG["orch_key"]`.

`button_flags(snap, lost, kind="orchestrator", latched=False)`:

```python
def button_flags(snap: dict, lost: bool, kind: str = "orchestrator", latched: bool = False) -> dict:
    estopped = _estopped(snap) or latched
    if kind == "runner":
        return {
            "can_start": False,
            "can_stop": False,
            "estopped": estopped,
            "can_estop": not estopped,
            "can_clear_estop": estopped,
        }
    # (existing orchestrator body, with `estopped` computed as above)
```

`apply_tick(s, feed, now, token, key=None, peers=())`: first line `key = key or default_key()`; replace every `_CFG["orch_key"]` with `key`; call `_render_graph(s, snap, lost, token, key, peers)` and `button_flags(snap, lost, feed_kind(key) or "orchestrator", ESTOP_LATCH.get(key, False))`; return `False` for the old-orch probe when `feed_kind(key) == "runner"`.

`_control_call(name, key)`: use `ORCHS[key]` host/port and `key` instead of `_CFG`.

New:

```python
async def _runner_estop(snap: dict, switch: bool) -> list:
    """``/{server}/estop?switch=`` on every server in the runner frame; errors."""
    rows = [r for r in snap.get("servers", []) if r.get("host") and r.get("port")]

    async def one(r):
        try:
            _, err = await async_private_dispatcher(
                r["key"], r["host"], r["port"], f"{r['key']}/estop",
                params_dict={"switch": switch}, json_dict={},
            )
        except Exception as exc:
            return f"{r['key']}: {exc}"
        return None if err == ErrorCodes.none else f"{r['key']}: {err}"

    if not rows:
        return ["runner has no servers to E-stop"]
    return [e for e in await asyncio.gather(*(one(r) for r in rows)) if e]
```

(add `import asyncio` at the top).

- [ ] **Step 6: `GroupState` — selection and controls**

Add vars:

```python
    selected_feed: str = ""
    selected_kind: str = "orchestrator"
    feed_options: list[dict] = []
```

In `tick`: replace `if not _CFG: return` with `if not feed_keys(): return`; inside the first locked block compute

```python
            key = resolve_key(self.selected_feed)
            if key != self.selected_feed:
                self.selected_feed = key
                reset_for_mount(self)
            self.selected_kind = feed_kind(key) or "orchestrator"
            now = time.time()
            options = [
                {"key": k, "label": f"{k} · {feed_kind(k)} · "
                 f"{'unreachable' if stream_lost(feed_for(k), now) else 'live'}"}
                for k in feed_keys()
            ]
            if options != self.feed_options:
                self.feed_options = options
```

and call `apply_tick(self, feed_for(key), now, token, key, peer_rows(key, now))`. Every tick also runs `for e in REGISTRY.sweep(now): await e.aclose()` outside the state lock, and drops `ESTOP_LATCH` entries for removed keys. Skip the old-orch probe for runners; for orchestrators pass the key to `_backend(token, key)` (Task 7 changes `_backend`'s signature; until then call `_backend(token)` only when `key == default_key()`).

New event:

```python
    @rx.event
    def set_feed(self, key: str):
        """Dropdown or peer-node click: view another orchestrator or runner."""
        if feed_kind(key) is None or key == self.selected_feed:
            return
        self.selected_feed = key
        reset_for_mount(self)
        self._selected = ()
        self.info_note = ""
        self.tree_header, self.tree_html = TREE_EMPTY_HEADER, ""
        return GroupState.tick("")
```

`control(name)`:

```python
        key = resolve_key(self.selected_feed)
        kind = feed_kind(key)
        err = ""
        if not kind:
            err = "cannot reach the orchestrator"
        elif kind == "runner":
            if name not in ("estop", "clear_estop"):
                err = f"{name} is not available for a runner"
            else:
                snap = latest_frame(feed_for(key)) or {}
                errs = await _runner_estop(snap, name == "estop")
                err = "; ".join(errs)
                if not errs:
                    ESTOP_LATCH[key] = name == "estop"
        else:
            try:
                await _control_call(name, key)
            except Exception as exc:
                err = str(exc)
        async with self:
            self.action_error = err
            if err or kind == "runner":
                self.pending = ""
```

- [ ] **Step 7: Page layout**

In `group_page()`: replace `if not _CFG:` with `if not ORCHS and not REGISTRY.keys():` (runners may register after the page builds, so instead of returning early, render the page and show `NO_ORCH_NOTE` via `rx.cond(S.feed_options.length() == 0, ...)`; reword `NO_ORCH_NOTE` to "No orchestrator or runner in this group yet."). Add above `header`:

```python
    selector = rx.hstack(
        rx.text("View", size="2", weight="bold"),
        rx.select.root(
            rx.select.trigger(),
            rx.select.content(
                rx.foreach(
                    S.feed_options,
                    lambda o: rx.select.item(o["label"], value=o["key"]),
                )
            ),
            value=S.selected_feed,
            on_change=S.set_feed,
            size="1",
        ),
        align="center",
        spacing="2",
    )
```

Wrap the Start and Stop buttons in `rx.cond(S.selected_kind == "orchestrator", rx.fragment(_button(...start...), _button(...stop...)))`. Put `selector` first in the returned `rx.vstack`.

- [ ] **Step 8: Fix the two old tests**

`test_reflex_group.py` ~384: replace the assertion with

```python
    assert list(group.ORCHS)[0] == RemoteBackend._detect_orch_key(cfg) == "ORCH2"
    assert list(group.ORCHS) == ["ORCH2", "ORCH1"]
```

~789: replace `group._CFG.clear()` with `group.configure_group({"servers": {}})`.

- [ ] **Step 9: Run tests**

Run: `PYTHONPATH=$PWD python -m pytest helao/core/tests/test_reflex_group_multi.py helao/core/tests/test_reflex_group.py helao/core/tests/test_palette.py -q`
Expected: all pass. Mutation: make `resolve_key` return `selected` unconditionally, confirm the fallback test fails, revert.

- [ ] **Step 10: Commit**

```bash
black helao/ui/reflex/group.py helao/ui/reflex/netgraph.py helao/core/tests/test_reflex_group.py helao/core/tests/test_reflex_group_multi.py
git -C /mnt/STORAGE/repos/helao/helao-async add helao/ui/reflex/group.py helao/ui/reflex/netgraph.py helao/core/tests/test_reflex_group.py helao/core/tests/test_reflex_group_multi.py
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(group): several orchestrators and runners, selector, peer nodes"
```

---

### Task 7: Info box for every feed, node clicks, endpoint list

**Files:**
- Create: `helao/ui/reflex/node_info.py`
- Modify: `helao/ui/reflex/operator.py` (`BackendRegistry`, `session_backend`)
- Modify: `helao/ui/reflex/group.py` (`_backend`, `_select`, `_render_graph`, `GroupState`, `group_page`)
- Test: `helao/core/tests/test_node_info.py`

**Interfaces:**
- Consumes: `mask_secrets` (Task 1); `feed_kind`, `feed_for`, `ORCHS`, `_WORLD`, `REGISTRY` (Task 6); `PushIngest.rpc` (Task 5); runner frame `config` (Task 3).
- Produces in `node_info.py`:
  - `node_at(g: NetGraph, x: float, y: float) -> Optional[str]`
  - `endpoint_rows(status: dict) -> list[dict]` (`{"name", "status", "non_idle", "active": [{"name","uuid","start"}]}`)
  - `server_info(cfg_entry: dict, status: Optional[dict]) -> dict` (tree-ready: `{"config": masked, "driver_status": ..., "endpoints": {"<name> — <status>, <n> non-idle": [...]}}`)
  - `config_info(cfg: dict) -> dict` (`{"config": masked}`)
- Produces in `operator.py`: `BackendRegistry.drop_prefix(prefix: str) -> None`; `session_backend(token, orch_key=None)`.
- Produces in `group.py`: `GroupState.select_node(payload)`, `GroupState.refresh_node()`, `GroupState.drop_backends()`; backend vars `_info_node: str`, `_info_sig: tuple`.

- [ ] **Step 1: Write the failing tests**

```python
"""Info-box builders for graph nodes (spec: Info box)."""

from helao.ui.reflex.netgraph import NetGraph
from helao.ui.reflex.node_info import config_info, endpoint_rows, node_at, server_info
from helao.ui.shared.mask import MASK

STATUS = {
    "estop": False,
    "_driver_status": "ok",
    "endpoints": {
        "acquire_data": {
            "active_dict": {"u1": {"action_name": "acquire_data", "action_uuid": "u1",
                                    "action_timestamp": "2026-11-16 10:00:00"}},
            "nonactive_dict": {},
        },
        "wait": {
            "active_dict": {},
            "nonactive_dict": {
                "finished": {"u2": {"action_finished_timestamp": "2026-11-16 09:00:00"}},
                "errored": {"u3": {"action_finished_timestamp": "2026-11-16 09:30:00"}},
            },
        },
        "never": {"active_dict": {}, "nonactive_dict": {}},
    },
}


def test_endpoint_rows_counts_and_statuses():
    rows = {r["name"]: r for r in endpoint_rows(STATUS)}
    assert rows["acquire_data"]["status"] == "busy" and rows["acquire_data"]["non_idle"] == 1
    assert rows["acquire_data"]["active"] == [
        {"name": "acquire_data", "uuid": "u1", "start": "2026-11-16 10:00:00"}]
    assert rows["wait"]["status"] == "errored" and rows["wait"]["non_idle"] == 0
    assert rows["never"]["status"] == "idle"


def test_estop_overrides_every_endpoint():
    rows = endpoint_rows({**STATUS, "estop": True})
    assert {r["status"] for r in rows} == {"estop"}


def test_server_info_masks_config_and_labels_rows():
    info = server_info({"host": "h", "params": {"api_key": "k"}}, STATUS)
    assert info["config"]["params"]["api_key"] == MASK
    assert info["driver_status"] == "ok"
    assert "acquire_data — busy, 1 non-idle" in info["endpoints"]


def test_server_info_without_status():
    info = server_info({"host": "h"}, None)
    assert info["endpoints"] == "unavailable"


def test_config_info_masks():
    assert config_info({"token": "t", "port": 1}) == {"config": {"token": MASK, "port": 1}}


def test_node_at_hits_within_radius_only():
    c = GROUP_STATE_COLORS["idle"]  # never a literal colour (test_palette.py)
    g = NetGraph(height_px=360, width_px=720)
    g.add_node("A", 0.0, 0.0, color=c, label_color=c, text="A", subtext="", size_px=44)
    assert node_at(g, 0.0, 0.0) == "A"
    assert node_at(g, 0.9, 0.9) is None
```

Add `from helao.ui.shared.palette import GROUP_STATE_COLORS` to the test's imports.

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=$PWD python -m pytest helao/core/tests/test_node_info.py -q`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Implement `node_info.py`**

```python
"""Info-box content for /group graph nodes: pure, so it is testable without Reflex."""

from typing import Optional

from helao.ui.shared.mask import mask_secrets


def node_at(g, x: float, y: float) -> Optional[str]:
    """Key of the node whose drawn circle contains data point ``(x, y)``."""
    best, best_d = None, 1.0
    for n in g.nodes.values():
        rx_, ry_ = n.size_px / 2 * g.sx, n.size_px / 2 * g.sy
        d = ((x - n.x) / rx_) ** 2 + ((y - n.y) / ry_) ** 2
        if d <= best_d:
            best, best_d = n.key, d
    return best


def _newest_finished(nonactive: dict) -> Optional[str]:
    newest = None  # (timestamp, status)
    for status, bucket in (nonactive or {}).items():
        for a in (bucket or {}).values():
            ts = str((a or {}).get("action_finished_timestamp") or "")
            if newest is None or ts > newest[0]:
                newest = (ts, str(status))
    return newest[1] if newest else None


def endpoint_rows(status: dict) -> list:
    """One row per endpoint of a ``/get_status`` dump."""
    estop = bool(status.get("estop"))
    rows = []
    for name, ep in sorted((status.get("endpoints") or {}).items()):
        active = (ep or {}).get("active_dict") or {}
        if estop:
            state = "estop"
        elif active:
            state = "busy"
        else:
            state = _newest_finished((ep or {}).get("nonactive_dict")) or "idle"
        rows.append(
            {
                "name": name,
                "status": state,
                "non_idle": len(active),
                "active": [
                    {
                        "name": a.get("action_name"),
                        "uuid": str(a.get("action_uuid") or u),
                        "start": a.get("action_timestamp"),
                    }
                    for u, a in active.items()
                ],
            }
        )
    return rows


def server_info(cfg_entry: dict, status: Optional[dict]) -> dict:
    """Tree for an action-server node: masked config, driver status, endpoints."""
    info: dict = {"config": mask_secrets(cfg_entry or {})}
    if status is None:
        info["endpoints"] = "unavailable"
        return info
    info["driver_status"] = status.get("_driver_status")
    info["endpoints"] = {
        f"{r['name']} — {r['status']}, {r['non_idle']} non-idle": r["active"]
        for r in endpoint_rows(status)
    }
    return info


def config_info(cfg: dict) -> dict:
    """Tree for an orchestrator or runner node: its masked config only."""
    return {"config": mask_secrets(cfg or {})}
```

- [ ] **Step 4: Run node_info tests**

Run: `PYTHONPATH=$PWD python -m pytest helao/core/tests/test_node_info.py -q`
Expected: 6 passed. Mutation: make `endpoint_rows` ignore `estop`, confirm FAIL, revert.

- [ ] **Step 5: Backends per orchestrator (`operator.py`)**

Add to `BackendRegistry`:

```python
    def drop_prefix(self, prefix: str) -> None:
        """Close and forget every backend whose key starts with ``prefix``."""
        with self._lock:
            keys = [k for k in self._backends if k.startswith(prefix)]
        for k in keys:
            self.drop(k)
```

Change `session_backend(token: str)` to `session_backend(token: str, orch_key: Optional[str] = None)`: registry key `token if orch_key is None else f"{token}|{orch_key}"`, and `make_backend(settings["world_cfg"], settings["server_key"], orch_key or settings.get("orch_key"))`.

In `group.py`, `_backend(token, key)`:

```python
def _backend(token: str, key: str):
    """A ``RemoteBackend`` for orchestrator ``key``; the operator's own for the first."""
    first = next(iter(ORCHS), None)
    backend = session_backend(token) if key == first else session_backend(token, key)
    if backend is not None and getattr(backend, "orch_key", None) != key:
        LOGGER.warning(
            f"/group: backend targets {getattr(backend, 'orch_key', None)}, "
            f"page shows {key}; refusing to use it"
        )
        return None
    return backend
```

Add `GroupState.drop_backends` (`BACKENDS.drop_prefix(f"{token}|")`) and bind it as `on_unmount` on the page's root `rx.vstack`. Update the tick's probe call to `_backend(token, key)`.

- [ ] **Step 6: Strip clicks for every feed (`GroupState._select`)**

After computing `request = object_request(kind, item)`:

```python
        key = resolve_key(self.selected_feed)
        obj = None
        if request is not None and feed_kind(key) == "runner":
            method, k, ident = request
            entry = feed_for(key)
            cfg = (latest_frame(entry) or {}).get("config") or {}
            if method == "get_object" and cfg.get("host") and cfg.get("rpc_port"):
                try:
                    obj = await entry.rpc(cfg["host"], cfg["rpc_port"]).call(
                        "get_object", kind=k, uuid=ident
                    )
                except Exception as exc:
                    LOGGER.warning(f"/group could not fetch {kind} {ident} from {key}: {exc}")
        elif request is not None:
            backend = _backend(token, key)
            # (existing backend fetch, unchanged)
```

- [ ] **Step 7: Node clicks**

`_render_graph`: pass `click=True` to `plots.marks_chart`, and keep the built graph for hit-testing in a module cache `_GRAPHS[token] = g` (a dict keyed by session token; a `NetGraph` cannot ride a state var).

In `group_page`, the graph `plots.chart(...)` gains `on_select=S.select_node`.

Add to `GroupState`:

```python
    _info_node: str = ""
    _info_sig: tuple = ()

    @rx.event(background=True)
    async def select_node(self, payload: dict):
        async with self:
            token = self.router.session.client_token
        g = _GRAPHS.get(token)
        p = payload or {}
        node = node_at(g, p.get("x", 9.0), p.get("y", 9.0)) if g is not None else None
        if node is None:
            return
        async with self:
            selected = resolve_key(self.selected_feed)
            self._info_node = node
            self._selected = ()
            self.info_note = ""
        if node != selected and feed_kind(node):
            async with self:
                self.selected_feed = node
                reset_for_mount(self)
        await self._show_node(node)

    async def _show_node(self, node: str):
        servers = _WORLD.get("servers") or {}
        async with self:
            snap = self._snap[0] if self._snap else {}
        if feed_kind(node) == "runner":
            info = config_info((latest_frame(feed_for(node)) or {}).get("config") or {})
        elif node in ORCHS:
            info = config_info(servers.get(node) or {})
        else:
            row = next((r for r in snap.get("servers", []) if r["key"] == node), {})
            info = server_info(*await _server_cfg_and_status(node, row, servers))
        html = object_to_html(info, open_keys=["config"])
        async with self:
            self.tree_header, self.tree_html = node, html
            row = next((r for r in snap.get("servers", []) if r["key"] == node), {})
            self._info_sig = (row.get("status"), row.get("active_action"))

    @rx.event(background=True)
    async def refresh_node(self):
        async with self:
            node = self._info_node
        if node:
            await self._show_node(node)
```

Module helpers in `group.py`:

```python
_GRAPHS: dict = {}
_SERVER_CFG: dict = {}


async def _server_cfg_and_status(key: str, row: dict, servers: dict) -> tuple:
    """``(config entry, /get_status dump or None)`` for an action server."""
    cfg = servers.get(key) or _SERVER_CFG.get(key)
    host = (cfg or {}).get("host") or row.get("host")
    port = (cfg or {}).get("port") or row.get("port")
    if not host or not port:
        return cfg or {}, None
    if cfg is None:
        world, err = await async_private_dispatcher(key, host, port, "get_config", json_dict={})
        if err == ErrorCodes.none and isinstance(world, dict):
            cfg = (world.get("servers") or {}).get(key) or {}
            _SERVER_CFG[key] = cfg
    status, err = await async_private_dispatcher(key, host, port, "get_status", json_dict={})
    return cfg or {}, (status if err == ErrorCodes.none and isinstance(status, dict) else None)
```

In `apply_tick`, after `snap` is set: if `s._info_node` is an action server row in `snap["servers"]` and `(status, active_action)` differs from `s._info_sig`, set `s._info_due = True` (new backend var, default `False`). In `tick`, after `apply_tick`, if `self._info_due` is set: clear it and `await self._show_node(self._info_node)`. Clicking a strip item clears `_info_node`. Add a small "refresh" `rx.icon_button("refresh_cw", size="1", on_click=S.refresh_node)` beside the INFO title.

Clear `_GRAPHS[token]` in `drop_backends` (page unmount).

- [ ] **Step 8: Run the UI test set**

Run: `PYTHONPATH=$PWD python -m pytest helao/core/tests/test_node_info.py helao/core/tests/test_reflex_group_multi.py helao/core/tests/test_reflex_group.py helao/core/tests/test_orch_backend_group.py helao/core/tests/test_palette.py -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
black helao/ui/reflex/node_info.py helao/ui/reflex/group.py helao/ui/reflex/operator.py helao/core/tests/test_node_info.py
git -C /mnt/STORAGE/repos/helao/helao-async add helao/ui/reflex/node_info.py helao/ui/reflex/group.py helao/ui/reflex/operator.py helao/core/tests/test_node_info.py
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "feat(group): info box for every feed, node clicks, endpoint list"
```

---

### Task 8: End-to-end check and docs

**Files:**
- Modify: `helao/ui/reflex/CLAUDE.md` (one short section: runner feeds, the estop latch, `_GRAPHS` cache)
- Modify: `helao/core/runners/runner.md` (one paragraph: `/group` feed, `group_urls`, `get_object`)

- [ ] **Step 1: Full sweep**

```bash
D=$CLAUDE_JOB_DIR/sweep; mkdir -p $D
( cd /mnt/STORAGE/repos/helao/helao-async && PYTHONPATH=$PWD python run_tests.py > $D/run.log 2>&1; echo $? > $D/done )
```

Watch with the marker-file loop (separate background command); compare failures against an `origin/unstable` baseline run in the same way. Expected: no new FAIL.

- [ ] **Step 2: Live check (headless Playwright, scratch venv)**

```bash
./helao.sh goldenreflex          # terminal 1
HELAO_ROOT=/tmp/helao-reflex python -m helao.deploy.test.runners.simulatews_runner   # terminal 2
```

`simulatews_runner`'s `WORLD_CFG` has no `reflex:` entry; for this check construct its MicroOrch with `group_urls=["http://127.0.0.1:<reflex port + 1>"]` (read the port from `goldenreflex.yml`). Check on `/group`:
- the dropdown lists ORCH and the runner; the runner is a peer node in ORCH's view;
- clicking the runner node switches the view and shows its config;
- pulses on SIM and ORCH edges; EXP and ACT strips fill;
- clicking SIM shows its config and endpoints, `acquire_data — busy, 1 non-idle` while it runs;
- clicking an ACT strip item shows its tree;
- E-stop latches SIM (`/get_status` shows `estop: true`); Clear releases it;
- Ctrl-C on the runner: it reads unreachable within 5 s.

Record screenshots under `$CLAUDE_JOB_DIR/shots/`.

- [ ] **Step 3: Docs, then commit**

```bash
git -C /mnt/STORAGE/repos/helao/helao-async add helao/ui/reflex/CLAUDE.md helao/core/runners/runner.md
git -C /mnt/STORAGE/repos/helao/helao-async commit -m "docs: runner feeds on /group"
```
