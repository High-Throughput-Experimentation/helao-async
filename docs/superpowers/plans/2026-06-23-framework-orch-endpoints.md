# Framework SP-ORCH-2 App Endpoints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register the operator-facing orchestrator private endpoints at the ROOT path in `app/orch_api.py`'s `makeOrchApp`, as thin handlers over the SP-ORCH-1 domain ops + the driver control surface, with dict→Run-model deserialization. Tested via FastAPI `TestClient`.

**Architecture:** All new routes live inside `makeOrchApp` and call `orch.<domain_op>(driver.state, ...)` (the SP-ORCH-1 functions) or `driver.<control>()`. Query handlers serialize the result to JSON dicts; mutation handlers deserialize posted `{"sequence"/"experiment": dict}` payloads into `RunSequence`/`RunExperiment`. Endpoints register at root (`/list_sequences`, …) to match `async_private_dispatcher`'s `http://host:port/{action}` path. No run_id stamping (the FSM stamps at dispatch). No lock (domain ops are synchronous under single-thread async).

**Tech Stack:** Python 3.12 (conda env `helao`), FastAPI + `fastapi.testclient.TestClient`, pydantic, `pytest`.

## Global Constraints

- Run pytest via the `helao` conda env: `conda run -n helao python -m pytest <path> -v`.
- Pure addition: do NOT modify any `helao/core/**` or `helao/deploy/**` file. Do NOT change `domain/orchestration.py` (SP-ORCH-1 owns it) or the dispatch FSM.
- Register operator endpoints at ROOT (no `server_key` prefix). Leave the existing `/{server_key}/...` SP5 endpoints in place.
- Handlers stay thin: deserialize/serialize + one domain-op or driver call. No business logic in handlers.
- The `orch` module alias (`import helao.framework.domain.orchestration as orch`) is already present in `app/orch_api.py` — use it. Add `RunSequence` to the run_models import if not already imported (`_as_run_experiment` already exists in the module).
- `app/orch_api.py` is the app layer; AST boundary check must stay green.

---

### Task 1: query endpoints (root) + deserialization helper

**Files:**
- Modify: `helao/framework/app/orch_api.py` (inside `makeOrchApp`, after the existing `globstat` route; module-level `_as_run_sequence` helper)
- Test: `helao/framework/tests/test_app_orch_query_endpoints.py`

**Interfaces:**
- Consumes: `orch.histories_payload/status_summary_payload/step_flags_payload/set_step_flag/queue_counts/queue_object_payload/list_sequences/list_experiments/list_actions/orch_state_payload/get_active_sequence/get_active_experiment/latest_sequence_uuids/latest_experiment_uuids/latest_action_uuids` (SP-ORCH-1); `driver.state`.
- Produces: root POST routes `get_histories`, `get_status_summary`, `get_step_flags`, `set_step_flag`, `get_orch_state`, `list_sequences`, `list_experiments`, `list_actions`, `get_queue_object`, `get_active_sequence`, `get_active_experiment`, `latest_sequence_uuids`, `latest_experiment_uuids`, `latest_action_uuids`; module helper `_as_run_sequence(d) -> RunSequence`.

- [ ] **Step 1: Write the failing test**

```python
# helao/framework/tests/test_app_orch_query_endpoints.py
"""Root-path orchestrator query endpoints (over SP-ORCH-1 domain ops)."""
from datetime import datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from helao.framework.app.factory import makeApp
from helao.framework.domain.run_models import RunSequence, RunExperiment, RunAction


def _seq(name="seq0"):
    return RunSequence(sequence_name=name, sequence_label="lbl",
                       sequence_uuid=uuid4(), sequence_timestamp=datetime.now())


def _exp(name="exp0"):
    return RunExperiment(experiment_name=name, experiment_uuid=uuid4(),
                         experiment_timestamp=datetime.now())


def _act(name="noop"):
    return RunAction(action_name=name, action_uuid=uuid4(),
                     action_timestamp=datetime.now())


def _client(tmp_path):
    app = makeApp("ORCH", save_root=str(tmp_path), group="orchestrator")
    return TestClient(app), app.state.driver


def test_get_histories_root_path(tmp_path):
    client, driver = _client(tmp_path)
    driver.state.action_history = {"a1": {"action_name": "noop"}}
    r = client.post("/get_histories")
    assert r.status_code == 200
    assert r.json()["action"] == [["a1", {"action_name": "noop"}]]


def test_get_step_flags_and_set(tmp_path):
    client, driver = _client(tmp_path)
    assert client.post("/get_step_flags").json() == {
        "actions": False, "experiments": False, "sequences": False}
    r = client.post("/set_step_flag", params={"kind": "actions", "value": True})
    assert r.json() == {"actions": True}
    assert driver.state.step_thru_actions is True


def test_get_orch_state_includes_active(tmp_path):
    client, driver = _client(tmp_path)
    driver.state.sequence_dq = [_seq(), _seq()]
    driver.state.active_sequence = _seq("running_seq")
    body = client.post("/get_orch_state").json()
    assert body["n_sequences"] == 2
    assert "loop_state" in body and "current_stop_message" in body
    assert body["active_sequence"].get("sequence_name") == "running_seq"


def test_list_sequences_limit_and_keys(tmp_path):
    client, driver = _client(tmp_path)
    driver.state.sequence_dq = [_seq("a"), _seq("b"), _seq("c")]
    rows = client.post("/list_sequences", params={"limit": 2}).json()
    assert len(rows) == 2
    assert rows[0]["sequence_name"] == "a"
    # carries the keys RemoteBackend trims to
    assert {"sequence_name", "sequence_label", "sequence_uuid"} <= set(rows[0])


def test_list_experiments_and_actions(tmp_path):
    client, driver = _client(tmp_path)
    driver.state.experiment_dq = [_exp()]
    driver.state.action_dq = [_act()]
    assert len(client.post("/list_experiments").json()) == 1
    assert len(client.post("/list_actions").json()) == 1


def test_get_queue_object_bounds(tmp_path):
    client, driver = _client(tmp_path)
    driver.state.sequence_dq = [_seq("seqX")]
    assert client.post("/get_queue_object",
                       params={"kind": "sequence", "idx": 0}).json()["sequence_name"] == "seqX"
    assert client.post("/get_queue_object",
                       params={"kind": "sequence", "idx": 9}).json() == {}


def test_latest_uuids_and_status_summary(tmp_path):
    client, driver = _client(tmp_path)
    driver.state.sequence_history = {"s1": {}, "s2": {}}
    driver.state.status_summary = {"motor": ("idle", "ok")}
    assert set(client.post("/latest_sequence_uuids").json()) == {"s1", "s2"}
    assert client.post("/get_status_summary").json() == {"motor": ["idle", "ok"]}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_orch_query_endpoints.py -v`
Expected: FAIL — `404` on `POST /get_histories` (route not registered).

- [ ] **Step 3: Write minimal implementation**

In `helao/framework/app/orch_api.py`: ensure `RunSequence` is imported alongside `RunExperiment`/`RunAction` (top of file). Add a module-level helper near `_as_run_experiment`:

```python
def _as_run_sequence(d: dict) -> RunSequence:
    """Build a RunSequence from a posted dict (filter to model fields)."""
    return RunSequence(**{k: v for k, v in d.items() if k in RunSequence.model_fields})
```

Inside `makeOrchApp`, after the existing `@app.get(f"/{server_key}/globstat")` route, add the root-path query routes (all reference `driver` and `orch` from the enclosing scope):

```python
    # --- operator-facing private endpoints (ROOT path, matching ----------
    # --- async_private_dispatcher: http://host:port/{action}) ------------

    @app.post("/get_histories")
    async def get_histories() -> dict:
        return orch.histories_payload(driver.state)

    @app.post("/get_status_summary")
    async def get_status_summary() -> dict:
        return orch.status_summary_payload(driver.state)

    @app.post("/get_step_flags")
    async def get_step_flags() -> dict:
        return orch.step_flags_payload(driver.state)

    @app.post("/set_step_flag")
    async def set_step_flag(kind: str, value: bool) -> dict:
        return orch.set_step_flag(driver.state, kind, value)

    @app.post("/get_orch_state")
    async def get_orch_state() -> dict:
        payload = orch.orch_state_payload(driver.state)
        payload["active_sequence"] = orch.get_active_sequence(driver.state)
        payload["active_experiment"] = orch.get_active_experiment(driver.state)
        return payload

    @app.post("/list_sequences")
    async def list_sequences(limit: int = 10) -> list:
        return [s.as_dict() for s in orch.list_sequences(driver.state, limit)]

    @app.post("/list_experiments")
    async def list_experiments(limit: int = 10) -> list:
        return [e.as_dict() for e in orch.list_experiments(driver.state, limit)]

    @app.post("/list_actions")
    async def list_actions(limit: int = 10) -> list:
        return [a.as_dict() for a in orch.list_actions(driver.state, limit)]

    @app.post("/get_queue_object")
    async def get_queue_object(kind: str, idx: int) -> dict:
        return orch.queue_object_payload(driver.state, kind, idx)

    @app.post("/get_active_sequence")
    async def get_active_sequence() -> dict:
        return orch.get_active_sequence(driver.state)

    @app.post("/get_active_experiment")
    async def get_active_experiment() -> dict:
        return orch.get_active_experiment(driver.state)

    @app.post("/latest_sequence_uuids")
    async def latest_sequence_uuids() -> list:
        return [str(u) for u in orch.latest_sequence_uuids(driver.state)]

    @app.post("/latest_experiment_uuids")
    async def latest_experiment_uuids() -> list:
        return [str(u) for u in orch.latest_experiment_uuids(driver.state)]

    @app.post("/latest_action_uuids")
    async def latest_action_uuids() -> list:
        return [str(u) for u in orch.latest_action_uuids(driver.state)]
```

> `s.as_dict()` is from `HelaoDict` on the summary models returned by
> `list_sequences` (SequenceModel etc.). If `as_dict` is unavailable, use
> `s.clean_dict()` or `s.model_dump(mode="json")` — keep the response JSON-safe.
> `set_step_flag` lets a bad `kind` raise `KeyError` (→ 500); that is acceptable
> per spec §6.

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_orch_query_endpoints.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add helao/framework/app/orch_api.py helao/framework/tests/test_app_orch_query_endpoints.py
git commit -m "feat(framework): SP-ORCH-2 — orchestrator query endpoints at root path"
```

---

### Task 2: mutation + control-alias endpoints (root)

**Files:**
- Modify: `helao/framework/app/orch_api.py` (inside `makeOrchApp`, after the Task 1 query routes)
- Test: `helao/framework/tests/test_app_orch_mutation_endpoints.py`

**Interfaces:**
- Consumes: `orch.append_sequence/insert_sequence/prepend_sequences/move_sequence/remove_sequence/append_experiment/insert_experiment/clear_sequences/clear_experiments/clear_actions` (SP-ORCH-1); `_as_run_sequence`/`_as_run_experiment`; `driver.start/stop/skip/estop/clear_estop`.
- Produces: root POST routes `append_sequence`, `insert_sequence`, `prepend_sequences`, `move_sequence`, `remove_sequence`, `add_split_sequences`, `append_experiment`, `insert_experiment`, `clear_sequences`, `clear_experiments`, `clear_actions`, and control aliases `start`, `stop`, `skip`, `estop`, `clear_estop`.

- [ ] **Step 1: Write the failing test**

```python
# helao/framework/tests/test_app_orch_mutation_endpoints.py
"""Root-path orchestrator mutation + control endpoints."""
from datetime import datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from helao.framework.app.factory import makeApp
from helao.framework.domain.run_models import RunSequence, RunExperiment


def _seq_dict(name="seq0"):
    return RunSequence(sequence_name=name, sequence_label="lbl",
                       sequence_uuid=uuid4(),
                       sequence_timestamp=datetime.now()).as_dict()


def _exp_dict(name="exp0"):
    return RunExperiment(experiment_name=name, experiment_uuid=uuid4(),
                         experiment_timestamp=datetime.now()).as_dict()


def _client(tmp_path):
    app = makeApp("ORCH", save_root=str(tmp_path), group="orchestrator")
    return TestClient(app), app.state.driver


def _names(dq):
    return [s.sequence_name for s in dq]


def test_append_sequence_enqueues(tmp_path):
    client, driver = _client(tmp_path)
    r = client.post("/append_sequence", json={"sequence": _seq_dict("a")})
    assert r.status_code == 200
    assert "sequence_uuid" in r.json()
    assert _names(driver.state.sequence_dq) == ["a"]


def test_prepend_sequences_order_and_uuids(tmp_path):
    client, driver = _client(tmp_path)
    client.post("/append_sequence", json={"sequence": _seq_dict("existing")})
    body = client.post("/prepend_sequences",
                       json={"sequences": [_seq_dict("a"), _seq_dict("b")]}).json()
    assert _names(driver.state.sequence_dq) == ["a", "b", "existing"]
    assert len(body) == 2


def test_move_and_remove_sequence(tmp_path):
    client, driver = _client(tmp_path)
    for n in ("a", "b", "c"):
        client.post("/append_sequence", json={"sequence": _seq_dict(n)})
    client.post("/move_sequence", params={"from_idx": 0, "to_idx": 2})
    assert _names(driver.state.sequence_dq) == ["b", "c", "a"]
    client.post("/remove_sequence", params={"idx": 1})
    assert _names(driver.state.sequence_dq) == ["b", "a"]


def test_insert_sequence(tmp_path):
    client, driver = _client(tmp_path)
    client.post("/append_sequence", json={"sequence": _seq_dict("a")})
    client.post("/insert_sequence", params={"idx": 0}, json={"sequence": _seq_dict("z")})
    assert _names(driver.state.sequence_dq) == ["z", "a"]


def test_append_and_insert_experiment(tmp_path):
    client, driver = _client(tmp_path)
    client.post("/append_experiment", json={"experiment": _exp_dict("a")})
    client.post("/insert_experiment", params={"idx": 0}, json={"experiment": _exp_dict("z")})
    assert [e.experiment_name for e in driver.state.experiment_dq] == ["z", "a"]


def test_add_split_sequences_fallback(tmp_path):
    client, driver = _client(tmp_path)
    body = client.post("/add_split_sequences", json={"sequence": _seq_dict("s")}).json()
    assert isinstance(body, list) and len(body) == 1
    assert _names(driver.state.sequence_dq) == ["s"]


def test_clear_ops(tmp_path):
    client, driver = _client(tmp_path)
    client.post("/append_sequence", json={"sequence": _seq_dict("a")})
    client.post("/append_experiment", json={"experiment": _exp_dict("b")})
    client.post("/clear_sequences")
    client.post("/clear_experiments")
    client.post("/clear_actions")
    assert driver.state.sequence_dq == []
    assert driver.state.experiment_dq == []
    assert driver.state.action_dq == []


def test_control_aliases_at_root(tmp_path):
    client, driver = _client(tmp_path)
    # no work queued: start returns immediately with a loop_state
    assert "loop_state" in client.post("/start").json()
    assert "loop_intent" in client.post("/stop").json()
    assert "loop_state" in client.post("/estop").json()
    assert "loop_state" in client.post("/clear_estop").json()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_orch_mutation_endpoints.py -v`
Expected: FAIL — `404` on `POST /append_sequence`.

- [ ] **Step 3: Write minimal implementation**

Inside `makeOrchApp`, after the Task 1 query routes, add:

```python
    @app.post("/append_sequence")
    async def append_sequence(sequence: dict = Body(..., embed=True)) -> dict:
        seq = _as_run_sequence(sequence)
        orch.append_sequence(driver.state, seq)
        return {"sequence_uuid": str(seq.sequence_uuid)}

    @app.post("/insert_sequence")
    async def insert_sequence(idx: int, sequence: dict = Body(..., embed=True)) -> dict:
        seq = _as_run_sequence(sequence)
        orch.insert_sequence(driver.state, seq, idx)
        return {"sequence_uuid": str(seq.sequence_uuid)}

    @app.post("/prepend_sequences")
    async def prepend_sequences(sequences: list = Body(..., embed=True)) -> list:
        seqs = [_as_run_sequence(d) for d in sequences]
        uuids = orch.prepend_sequences(driver.state, seqs)
        return [str(u) for u in uuids]

    @app.post("/move_sequence")
    async def move_sequence(from_idx: int, to_idx: int) -> dict:
        orch.move_sequence(driver.state, from_idx, to_idx)
        return {"n_sequences": len(driver.state.sequence_dq)}

    @app.post("/remove_sequence")
    async def remove_sequence(idx: int) -> dict:
        orch.remove_sequence(driver.state, idx)
        return {"n_sequences": len(driver.state.sequence_dq)}

    @app.post("/add_split_sequences")
    async def add_split_sequences(sequence: dict = Body(..., embed=True)) -> list:
        # split-by-seq-param config is not present in OrchPorts; fall back to a
        # plain append (faithful to the legacy no-split branch). Real splitting
        # is a documented follow-up.
        seq = _as_run_sequence(sequence)
        orch.append_sequence(driver.state, seq)
        return [str(seq.sequence_uuid)]

    @app.post("/append_experiment")
    async def append_experiment(experiment: dict = Body(..., embed=True)) -> dict:
        exp = _as_run_experiment(experiment)
        orch.append_experiment(driver.state, exp)
        return {"experiment_uuid": str(exp.experiment_uuid)}

    @app.post("/insert_experiment")
    async def insert_experiment(idx: int, experiment: dict = Body(..., embed=True)) -> dict:
        exp = _as_run_experiment(experiment)
        orch.insert_experiment(driver.state, exp, idx)
        return {"experiment_uuid": str(exp.experiment_uuid)}

    @app.post("/clear_sequences")
    async def clear_sequences() -> dict:
        orch.clear_sequences(driver.state)
        return {"n_sequences": 0}

    @app.post("/clear_experiments")
    async def clear_experiments() -> dict:
        orch.clear_experiments(driver.state)
        return {"n_experiments": 0}

    @app.post("/clear_actions")
    async def clear_actions() -> dict:
        orch.clear_actions(driver.state)
        return {"n_actions": 0}

    # --- control aliases at root (share the driver control surface) ------

    @app.post("/start")
    async def start_root() -> dict:
        await driver.start()
        return {"loop_state": driver.state.loop_state.value}

    @app.post("/stop")
    async def stop_root() -> dict:
        await driver.stop()
        return {"loop_intent": driver.state.loop_intent.value}

    @app.post("/skip")
    async def skip_root() -> dict:
        await driver.skip()
        return {"loop_intent": driver.state.loop_intent.value}

    @app.post("/estop")
    async def estop_root(reason: str = "") -> dict:
        await driver.estop(reason=reason)
        return {"loop_state": driver.state.loop_state.value}

    @app.post("/clear_estop")
    async def clear_estop_root() -> dict:
        await driver.clear_estop()
        return {"loop_state": driver.state.loop_state.value}
```

Ensure `Body` is imported from `fastapi` at the top of `makeOrchApp`'s module (the
factory imports `Body` already in `app/factory.py`; in `orch_api.py` add
`from fastapi import Body` inside `makeOrchApp` alongside the existing
`from fastapi import FastAPI`, or at module top — match the file's lazy-import style).

> `_as_run_experiment` already exists in this module. `_as_run_sequence` was added in
> Task 1. The `embed=True` Body params match the wire shape
> (`{"sequence": {...}}` / `{"sequences": [...]}` / `{"experiment": {...}}`).

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_orch_mutation_endpoints.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add helao/framework/app/orch_api.py helao/framework/tests/test_app_orch_mutation_endpoints.py
git commit -m "feat(framework): SP-ORCH-2 — orchestrator mutation + control endpoints at root path"
```

---

### Task 3: Full-suite + boundary verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full framework test suite**

Run: `conda run -n helao python -m pytest helao/framework/tests/ -p no:cacheprovider -q 2>&1 | tail -1`
Expected: all pass (new + pre-existing), no regressions.

- [ ] **Step 2: Confirm the AST boundary check is green**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_boundaries.py -v`
Expected: PASS. `domain/` untouched; the new routes are app-layer.

- [ ] **Step 3: Confirm pure-addition (no legacy/deploy/domain edits)**

Run: `git diff --name-only feat/framework-scaffold...HEAD | grep -E "helao/(core|deploy)/|domain/orchestration" || echo "NONE (clean)"`
Expected: `NONE (clean)` — only `helao/framework/app/orch_api.py`, new tests, and docs.

- [ ] **Step 4: Commit (only if verification fixups were needed)**

```bash
git add -A
git commit -m "test(framework): SP-ORCH-2 — verify full suite + boundary green"
```

---

## Self-Review

**Spec coverage:**
- §4.1 deserialization helper `_as_run_sequence` (+ reuse `_as_run_experiment`) → Task 1. ✓
- §4.2 query endpoints (14) → Task 1. ✓
- §4.3 mutation endpoints (11 incl. add_split fallback) → Task 2. ✓
- §4.4 control aliases at root → Task 2. ✓
- §6 error handling (set_step_flag KeyError surfaces; queue_object/move/remove bounds no-op) → covered by domain ops + tests. ✓
- §7 test strategy (TestClient over makeApp, root paths, payload shapes, mutations, RemoteBackend-key round-trip) → Tasks 1-2. ✓
- §2 non-goals (no WS, no status_summary population, add_split fallback, no domain change) → Task 2 add_split fallback + Task 3 Step 3 guard. ✓

**Placeholder scan:** No TBD/TODO. Full handler + test code for every endpoint. Guarded notes (`as_dict` fallback, `Body` import location) are concrete conditionals, not placeholders.

**Type consistency:** `_as_run_sequence(d) -> RunSequence` defined Task 1, used Task 2. `orch.<op>(driver.state, ...)` signatures match SP-ORCH-1. `embed=True` Body params match the `{"sequence"/"sequences"/"experiment": ...}` wire shapes the operator sends. Control aliases reuse `driver.start/stop/skip/estop/clear_estop` returning the same dict shapes as the SP5 prefixed handlers.
