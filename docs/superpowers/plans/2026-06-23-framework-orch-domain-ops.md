# Framework SP-ORCH-1 Orchestrator Domain Ops Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add pure queue-mutation + query/serialization + step-flag + status-summary operations to `domain/orchestration.py` (and `get_seq`/`get_exp` to the run_models), unit-tested against the legacy orch contracts. No FastAPI, no I/O.

**Architecture:** Module-level pure functions taking `OrchState` first (matching the existing `decide_next`/`apply_intent`/`register_obj_uuid` convention); mutations mutate `state` in place and return it (SP5 FSM convention). Serialization mirrors legacy `orch_api.py` payload helpers; mutations mirror legacy `orch.py` queue methods (pure parts only). All additions go in `__all__`.

**Tech Stack:** Python 3.12 (conda env `helao`), pydantic models, `pytest`.

## Global Constraints

- Run pytest via the `helao` conda env: `conda run -n helao python -m pytest <path> -v`. OS Python is 3.14; the project targets 3.12.
- Pure addition: do NOT modify any `helao/core/**` or `helao/deploy/**` file.
- `domain/orchestration.py` and `domain/run_models.py` stay pure: imports only `models/` + stdlib; never FastAPI/httpx/filesystem/Bokeh/adapters. AST boundary check (`helao/framework/tests/test_boundaries.py`) must stay green.
- Mutations mutate `OrchState` in place and return it. Serializers are read-only.
- Add every new public function to the module `__all__` in `domain/orchestration.py`.
- `add_split_sequences` is OUT of scope (deferred to SP-ORCH-2 — config/codehash/run_id coupled).

---

### Task 1: `run_models` `get_seq` / `get_exp`

**Files:**
- Modify: `helao/framework/domain/run_models.py`
- Test: `helao/framework/tests/test_run_models_summaries.py`

**Interfaces:**
- Produces: `RunSequence.get_seq() -> SequenceModel`; `RunExperiment.get_exp() -> ExperimentModel`. (Mirror the existing `RunAction.get_act() -> ActionModel` = `ActionModel(**self.model_dump())`.)

- [ ] **Step 1: Write the failing test**

```python
# helao/framework/tests/test_run_models_summaries.py
"""get_seq/get_exp summary snapshots on the orchestrator run_models."""
from datetime import datetime
from uuid import uuid4

from helao.framework.domain.run_models import RunSequence, RunExperiment
from helao.framework.models.sequence import SequenceModel
from helao.framework.models.experiment import ExperimentModel


def _seq():
    return RunSequence(sequence_name="seq0", sequence_label="lbl",
                       sequence_uuid=uuid4(), sequence_timestamp=datetime.now())


def _exp():
    return RunExperiment(experiment_name="exp0", experiment_uuid=uuid4(),
                         experiment_timestamp=datetime.now())


def test_get_seq_returns_sequence_model():
    s = _seq()
    out = s.get_seq()
    assert isinstance(out, SequenceModel)
    assert out.sequence_name == "seq0"
    assert out.sequence_label == "lbl"


def test_get_exp_returns_experiment_model():
    e = _exp()
    out = e.get_exp()
    assert isinstance(out, ExperimentModel)
    assert out.experiment_name == "exp0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_run_models_summaries.py -v`
Expected: FAIL — `AttributeError: 'RunSequence' object has no attribute 'get_seq'`

> If the test instead fails at construction (a required `SequenceModel`/`ExperimentModel` field missing from the kwargs above), add the minimal required fields to `_seq()`/`_exp()` so construction succeeds, then re-run to get the real `AttributeError`. Inspect `helao/framework/models/sequence.py` / `experiment.py` for required fields.

- [ ] **Step 3: Write minimal implementation**

In `helao/framework/domain/run_models.py`, add to `RunSequence` (next to where `RunAction.get_act` lives in `RunAction`):

```python
    def get_seq(self) -> "SequenceModel":
        """Return a plain :class:`SequenceModel` snapshot. Mirrors ``RunAction.get_act``."""
        return SequenceModel(**self.model_dump())
```

and to `RunExperiment`:

```python
    def get_exp(self) -> "ExperimentModel":
        """Return a plain :class:`ExperimentModel` snapshot. Mirrors ``RunAction.get_act``."""
        return ExperimentModel(**self.model_dump())
```

Ensure `SequenceModel` and `ExperimentModel` are imported in `run_models.py` (they are the bases of `RunSequence`/`RunExperiment`, so likely already imported — if referenced only via the class bases, add explicit imports `from helao.framework.models.sequence import SequenceModel` / `from helao.framework.models.experiment import ExperimentModel`).

> If `SequenceModel(**self.model_dump())` raises on extra keys (Run-only fields not on the base), mirror exactly what `RunAction.get_act` does — `get_act` uses `ActionModel(**self.model_dump())` successfully, so the same pattern works unless RunSequence/RunExperiment add base-incompatible fields. If they do, filter to the base's field names: `SequenceModel(**{k: v for k, v in self.model_dump().items() if k in SequenceModel.model_fields})`.

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_run_models_summaries.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add helao/framework/domain/run_models.py helao/framework/tests/test_run_models_summaries.py
git commit -m "feat(framework): SP-ORCH-1 — add get_seq/get_exp to run_models"
```

---

### Task 2: read-side ops (status_summary field + payloads/lists/getters)

**Files:**
- Modify: `helao/framework/domain/orchestration.py`
- Test: `helao/framework/tests/test_domain_orch_payloads.py`

**Interfaces:**
- Consumes: `RunSequence.get_seq`/`RunExperiment.get_exp`/`RunAction.get_act` (Task 1); `OrchState`.
- Produces (all module-level, in `__all__`): `histories_payload(state)`, `status_summary_payload(state)`, `step_flags_payload(state)`, `set_step_flag(state, kind, value)`, `queue_counts(state)`, `queue_object_payload(state, kind, idx)`, `list_sequences(state, limit=10)`, `list_experiments(state, limit=10)`, `list_actions(state, limit=10)`, `orch_state_payload(state)`, `get_active_sequence(state)`, `get_active_experiment(state)`, `get_last_sequence(state)`, `get_last_experiment(state)`, `latest_sequence_uuids(state)`, `latest_experiment_uuids(state)`, `latest_action_uuids(state)`. New `OrchState` field `status_summary: dict`.

- [ ] **Step 1: Write the failing test**

```python
# helao/framework/tests/test_domain_orch_payloads.py
"""Read-side orchestrator domain ops (payloads, lists, getters)."""
from datetime import datetime
from uuid import uuid4

import pytest

from helao.framework.domain import orchestration as orch
from helao.framework.domain.orchestration import OrchState
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


def test_histories_payload():
    s = OrchState()
    s.action_history = {"a1": {"action_name": "noop"}}
    s.experiment_history = {"e1": {"experiment_name": "exp0"}}
    s.sequence_history = {"s1": {"sequence_name": "seq0"}}
    assert orch.histories_payload(s) == {
        "action": [("a1", {"action_name": "noop"})],
        "experiment": [("e1", {"experiment_name": "exp0"})],
        "sequence": [("s1", {"sequence_name": "seq0"})],
    }


def test_status_summary_payload():
    s = OrchState()
    s.status_summary = {"motor": ("idle", "ok")}
    assert orch.status_summary_payload(s) == {"motor": ["idle", "ok"]}


def test_step_flags_roundtrip_and_unknown():
    s = OrchState()
    assert orch.step_flags_payload(s) == {
        "actions": False, "experiments": False, "sequences": False}
    assert orch.set_step_flag(s, "actions", True) == {"actions": True}
    assert s.step_thru_actions is True
    assert orch.step_flags_payload(s)["actions"] is True
    with pytest.raises(KeyError):
        orch.set_step_flag(s, "bogus", True)


def test_queue_counts():
    s = OrchState()
    s.sequence_dq = [_seq(), _seq(), _seq()]
    s.experiment_dq = [_exp()]
    s.action_dq = []
    assert orch.queue_counts(s) == {
        "n_sequences": 3, "n_experiments": 1, "n_actions": 0}


def test_queue_object_payload_and_bounds():
    s = OrchState()
    sq = _seq("seqX")
    s.sequence_dq = [sq]
    payload = orch.queue_object_payload(s, "sequence", 0)
    assert payload.get("sequence_name") == "seqX"
    assert orch.queue_object_payload(s, "sequence", 9) == {}     # out of range
    assert orch.queue_object_payload(s, "bogus", 0) == {}        # unknown kind


def test_list_sequences_limit_and_order():
    s = OrchState()
    s.sequence_dq = [_seq("a"), _seq("b"), _seq("c")]
    rows = orch.list_sequences(s, limit=2)
    assert len(rows) == 2
    assert rows[0].sequence_name == "a"  # front-of-deque first


def test_list_actions_and_experiments():
    s = OrchState()
    s.action_dq = [_act("noop")]
    s.experiment_dq = [_exp("exp0")]
    assert len(orch.list_actions(s)) == 1
    assert len(orch.list_experiments(s)) == 1


def test_orch_state_payload_shape():
    s = OrchState()
    s.sequence_dq = [_seq(), _seq()]
    s.current_stop_message = ""
    p = orch.orch_state_payload(s)
    assert set(p) >= {"loop_state", "n_sequences", "n_experiments",
                      "n_actions", "current_stop_message"}
    assert p["n_sequences"] == 2


def test_active_and_last_getters_default_empty():
    s = OrchState()
    assert orch.get_active_sequence(s) == {}
    assert orch.get_last_experiment(s) == {}
    s.active_sequence = _seq("act_seq")
    assert orch.get_active_sequence(s).get("sequence_name") == "act_seq"


def test_latest_uuid_lists():
    s = OrchState()
    s.sequence_history = {"s1": {}, "s2": {}}
    s.experiment_history = {"e1": {}}
    s.action_history = {"a1": {}}
    assert set(orch.latest_sequence_uuids(s)) == {"s1", "s2"}
    assert orch.latest_experiment_uuids(s) == ["e1"]
    assert orch.latest_action_uuids(s) == ["a1"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_domain_orch_payloads.py -v`
Expected: FAIL — `AttributeError: module 'helao.framework.domain.orchestration' has no attribute 'histories_payload'` (and/or `OrchState` has no `status_summary`).

- [ ] **Step 3: Write minimal implementation**

In `helao/framework/domain/orchestration.py`:

(a) Add the `status_summary` field to the `OrchState` dataclass (next to the history fields):

```python
    status_summary: dict = field(default_factory=dict)
```

(b) Add these module-level functions (place them after the existing history helpers):

```python
def histories_payload(state: OrchState) -> dict:
    """Action/experiment/sequence history as (uuid, dict) item lists. Ports orch_api._histories_payload."""
    return {
        "action": list(state.action_history.items()),
        "experiment": list(state.experiment_history.items()),
        "sequence": list(state.sequence_history.items()),
    }


def status_summary_payload(state: OrchState) -> dict:
    """{server: [server_status, driver_status]} from state.status_summary. Ports orch_api._status_summary_payload."""
    return {k: list(v) for k, v in state.status_summary.items()}


_STEP_FLAG_ATTR = {
    "actions": "step_thru_actions",
    "experiments": "step_thru_experiments",
    "sequences": "step_thru_sequences",
}


def step_flags_payload(state: OrchState) -> dict:
    """The three step-through flags. Ports orch_api._step_flags_payload."""
    return {
        "actions": state.step_thru_actions,
        "experiments": state.step_thru_experiments,
        "sequences": state.step_thru_sequences,
    }


def set_step_flag(state: OrchState, kind: str, value: bool) -> dict:
    """Set one step flag by kind. Raises KeyError on unknown kind. Ports orch_api._set_step_flag."""
    attr = _STEP_FLAG_ATTR[kind]
    setattr(state, attr, bool(value))
    return {kind: getattr(state, attr)}


def queue_counts(state: OrchState) -> dict:
    """True queue lengths. Ports orch_api._queue_counts."""
    return {
        "n_sequences": len(state.sequence_dq),
        "n_experiments": len(state.experiment_dq),
        "n_actions": len(state.action_dq),
    }


def queue_object_payload(state: OrchState, kind: str, idx: int) -> dict:
    """Full dict for the queued item of kind at idx, or {} (snapshot-safe). Ports orch_api._queue_object_payload."""
    dq = {
        "sequence": state.sequence_dq,
        "experiment": state.experiment_dq,
        "action": state.action_dq,
    }.get(kind)
    if dq is None:
        return {}
    try:
        return dq[idx].as_dict()
    except (IndexError, KeyError, AttributeError):
        return {}


def list_sequences(state: OrchState, limit: int = 10) -> list:
    """At most `limit` sequence summaries from the front of the deque. Ports Orch.list_sequences."""
    return [state.sequence_dq[i].get_seq()
            for i in range(min(len(state.sequence_dq), limit))]


def list_experiments(state: OrchState, limit: int = 10) -> list:
    """At most `limit` experiment summaries. Ports Orch.list_experiments."""
    return [state.experiment_dq[i].get_exp()
            for i in range(min(len(state.experiment_dq), limit))]


def list_actions(state: OrchState, limit: int = 10) -> list:
    """At most `limit` action summaries. Ports Orch.list_actions."""
    return [state.action_dq[i].get_act()
            for i in range(min(len(state.action_dq), limit))]


def orch_state_payload(state: OrchState) -> dict:
    """{loop_state, n_*, current_stop_message} — the shape RemoteBackend.get_orch_state consumes."""
    return {
        "loop_state": state.loop_state,
        "n_sequences": len(state.sequence_dq),
        "n_experiments": len(state.experiment_dq),
        "n_actions": len(state.action_dq),
        "current_stop_message": state.current_stop_message,
    }


def _obj_dict(obj) -> dict:
    """Serialize an active/last sequence|experiment object to a dict, or {}."""
    if obj is None:
        return {}
    try:
        return obj.as_dict()
    except AttributeError:
        return {}


def get_active_sequence(state: OrchState) -> dict:
    return _obj_dict(state.active_sequence)


def get_active_experiment(state: OrchState) -> dict:
    return _obj_dict(state.active_experiment)


def get_last_sequence(state: OrchState) -> dict:
    return _obj_dict(state.last_sequence)


def get_last_experiment(state: OrchState) -> dict:
    return _obj_dict(state.last_experiment)


def latest_sequence_uuids(state: OrchState) -> list:
    """UUIDs of recently registered sequences (history keys)."""
    return list(state.sequence_history.keys())


def latest_experiment_uuids(state: OrchState) -> list:
    return list(state.experiment_history.keys())


def latest_action_uuids(state: OrchState) -> list:
    return list(state.action_history.keys())
```

(c) Add all the new names + `status_summary` is a field (not in `__all__`) to the module `__all__` list: `histories_payload`, `status_summary_payload`, `step_flags_payload`, `set_step_flag`, `queue_counts`, `queue_object_payload`, `list_sequences`, `list_experiments`, `list_actions`, `orch_state_payload`, `get_active_sequence`, `get_active_experiment`, `get_last_sequence`, `get_last_experiment`, `latest_sequence_uuids`, `latest_experiment_uuids`, `latest_action_uuids`.

> `state.loop_state` is a `LoopStatus` (str enum) and JSON-serializes fine. `as_dict()` comes from `HelaoDict` on the model bases — `RunSequence`/`RunExperiment`/`RunAction` inherit it. If `as_dict()` is absent on a run_model, use `.get_seq()/.get_exp()/.get_act()` then `.as_dict()`, or `model_dump(mode="json")`; keep `queue_object_payload`'s `{}`-on-failure guard.

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_domain_orch_payloads.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add helao/framework/domain/orchestration.py helao/framework/tests/test_domain_orch_payloads.py
git commit -m "feat(framework): SP-ORCH-1 — orchestrator read-side domain ops + status_summary field"
```

---

### Task 3: mutation ops (move/remove/prepend/append/insert/clear)

**Files:**
- Modify: `helao/framework/domain/orchestration.py`
- Test: `helao/framework/tests/test_domain_orch_queue_ops.py`

**Interfaces:**
- Consumes: `OrchState`; run_models with a `sequence_uuid` attribute on sequences.
- Produces (all module-level, in `__all__`): `move_sequence(state, from_idx, to_idx)`, `remove_sequence(state, idx)`, `prepend_sequences(state, sequences)`, `append_sequence(state, sequence)`, `insert_sequence(state, sequence, idx)`, `append_experiment(state, experiment)`, `insert_experiment(state, experiment, idx)`, `clear_sequences(state)`, `clear_experiments(state)`, `clear_actions(state)`. All return the mutated `state`.

- [ ] **Step 1: Write the failing test**

```python
# helao/framework/tests/test_domain_orch_queue_ops.py
"""Pure queue-mutation orchestrator domain ops."""
from datetime import datetime
from uuid import uuid4

from helao.framework.domain import orchestration as orch
from helao.framework.domain.orchestration import OrchState
from helao.framework.domain.run_models import RunSequence, RunExperiment


def _seq(name):
    return RunSequence(sequence_name=name, sequence_label="l",
                       sequence_uuid=uuid4(), sequence_timestamp=datetime.now())


def _exp(name):
    return RunExperiment(experiment_name=name, experiment_uuid=uuid4(),
                         experiment_timestamp=datetime.now())


def _names(dq):
    return [s.sequence_name for s in dq]


def test_move_sequence_reorders():
    s = OrchState()
    s.sequence_dq = [_seq("a"), _seq("b"), _seq("c")]
    orch.move_sequence(s, 0, 2)
    assert _names(s.sequence_dq) == ["b", "c", "a"]


def test_move_sequence_out_of_range_noop():
    s = OrchState()
    s.sequence_dq = [_seq("a"), _seq("b")]
    orch.move_sequence(s, 5, 0)
    assert _names(s.sequence_dq) == ["a", "b"]


def test_remove_sequence_and_bounds():
    s = OrchState()
    s.sequence_dq = [_seq("a"), _seq("b"), _seq("c")]
    orch.remove_sequence(s, 1)
    assert _names(s.sequence_dq) == ["a", "c"]
    orch.remove_sequence(s, 99)  # no-op
    assert _names(s.sequence_dq) == ["a", "c"]


def test_prepend_sequences_order_and_uuids():
    s = OrchState()
    s.sequence_dq = [_seq("existing")]
    a, b = _seq("a"), _seq("b")
    uuids = orch.prepend_sequences(s, [a, b])
    assert _names(s.sequence_dq) == ["a", "b", "existing"]
    assert uuids == [a.sequence_uuid, b.sequence_uuid]


def test_prepend_empty_noop():
    s = OrchState()
    s.sequence_dq = [_seq("x")]
    assert orch.prepend_sequences(s, []) == []
    assert _names(s.sequence_dq) == ["x"]


def test_append_and_insert_sequence():
    s = OrchState()
    s.sequence_dq = [_seq("a")]
    orch.append_sequence(s, _seq("z"))
    assert _names(s.sequence_dq) == ["a", "z"]
    orch.insert_sequence(s, _seq("m"), 1)
    assert _names(s.sequence_dq) == ["a", "m", "z"]


def test_append_and_insert_experiment():
    s = OrchState()
    s.experiment_dq = [_exp("a")]
    orch.append_experiment(s, _exp("z"))
    orch.insert_experiment(s, _exp("m"), 1)
    assert [e.experiment_name for e in s.experiment_dq] == ["a", "m", "z"]


def test_clear_ops():
    s = OrchState()
    s.sequence_dq = [_seq("a")]
    s.experiment_dq = [_exp("b")]
    s.action_dq = ["x"]
    orch.clear_sequences(s)
    orch.clear_experiments(s)
    orch.clear_actions(s)
    assert s.sequence_dq == [] and s.experiment_dq == [] and s.action_dq == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_domain_orch_queue_ops.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'move_sequence'`

- [ ] **Step 3: Write minimal implementation**

Add to `helao/framework/domain/orchestration.py` (after the read-side ops from Task 2):

```python
def move_sequence(state: OrchState, from_idx: int, to_idx: int) -> OrchState:
    """Move the queued sequence at from_idx to to_idx; out-of-range is a no-op. Ports Orch.move_sequence."""
    dq = state.sequence_dq
    n = len(dq)
    if 0 <= from_idx < n and 0 <= to_idx < n:
        seq = dq.pop(from_idx)
        dq.insert(to_idx, seq)
    return state


def remove_sequence(state: OrchState, idx: int) -> OrchState:
    """Drop the queued sequence at idx; out-of-range no-op. Ports Orch.remove_sequence."""
    if 0 <= idx < len(state.sequence_dq):
        del state.sequence_dq[idx]
    return state


def prepend_sequences(state: OrchState, sequences: list) -> list:
    """Insert sequences at the front preserving order; return their sequence_uuids.

    Pure insert only — run_id/codehash stamping is the app layer's job (SP-ORCH-2).
    Empty list is a no-op returning []. Ports the queue half of Orch.prepend_sequences.
    """
    if not sequences:
        return []
    uuids = []
    for i, sequence in enumerate(sequences):
        state.sequence_dq.insert(i, sequence)
        uuids.append(sequence.sequence_uuid)
    return uuids


def append_sequence(state: OrchState, sequence) -> OrchState:
    """Append a sequence to the back of the queue."""
    state.sequence_dq.append(sequence)
    return state


def insert_sequence(state: OrchState, sequence, idx: int) -> OrchState:
    """Insert a sequence at idx."""
    state.sequence_dq.insert(idx, sequence)
    return state


def append_experiment(state: OrchState, experiment) -> OrchState:
    """Append an experiment to the back of the queue."""
    state.experiment_dq.append(experiment)
    return state


def insert_experiment(state: OrchState, experiment, idx: int) -> OrchState:
    """Insert an experiment at idx."""
    state.experiment_dq.insert(idx, experiment)
    return state


def clear_sequences(state: OrchState) -> OrchState:
    """Empty the sequence queue. Ports Orch.clear_sequences."""
    state.sequence_dq.clear()
    return state


def clear_experiments(state: OrchState) -> OrchState:
    """Empty the experiment queue. Ports Orch.clear_experiments."""
    state.experiment_dq.clear()
    return state


def clear_actions(state: OrchState) -> OrchState:
    """Empty the action queue. Ports Orch.clear_actions."""
    state.action_dq.clear()
    return state
```

Add all ten names to the module `__all__`.

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_domain_orch_queue_ops.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add helao/framework/domain/orchestration.py helao/framework/tests/test_domain_orch_queue_ops.py
git commit -m "feat(framework): SP-ORCH-1 — orchestrator queue-mutation domain ops"
```

---

### Task 4: Full-suite + boundary verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full framework test suite**

Run: `conda run -n helao python -m pytest helao/framework/tests/ -p no:cacheprovider -q 2>&1 | tail -1`
Expected: all pass (new + pre-existing), no regressions.

- [ ] **Step 2: Confirm the AST boundary check is green**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_boundaries.py -v`
Expected: PASS. `domain/orchestration.py` and `domain/run_models.py` import no I/O/adapters.

- [ ] **Step 3: Confirm pure-addition (no legacy/deploy edits)**

Run: `git diff --name-only feat/framework-scaffold...HEAD | grep -E "helao/(core|deploy)/" || echo "NONE (clean)"`
Expected: `NONE (clean)` — only files under `helao/framework/**` and `docs/superpowers/**`.

- [ ] **Step 4: Commit (only if verification fixups were needed)**

```bash
git add -A
git commit -m "test(framework): SP-ORCH-1 — verify full suite + boundary green"
```

---

## Self-Review

**Spec coverage:**
- §4.1 `status_summary` field (population deferred) → Task 2 Step 3(a). ✓
- §4.2 query/serialization functions (all 17) → Task 2. ✓
- §4.3 mutation functions (move/remove/prepend/append/insert/clear) → Task 3. ✓
- §4.4 run_models `get_seq`/`get_exp` → Task 1. ✓
- §6 error handling (set_step_flag KeyError, queue_object {} bounds, move/remove no-op) → tested in Tasks 2/3. ✓
- §7 test strategy (parity shapes, mutation bounds, step-flag, status_summary serialize) → Tasks 1-3. ✓
- §3 boundary purity → Task 4 Steps 2-3. ✓
- `add_split_sequences` correctly ABSENT (deferred to SP-ORCH-2). ✓

**Placeholder scan:** No TBD/TODO. Full implementation + test code given for every code step. Guarded notes (run_model field filtering, as_dict fallback) are concrete conditional instructions, not placeholders.

**Type consistency:** `OrchState` first-arg convention consistent across all functions. `get_seq`/`get_exp`/`get_act` return `SequenceModel`/`ExperimentModel`/`ActionModel` (Task 1) and are consumed by `list_*` (Task 2). `prepend_sequences` returns `list` of uuids (Tasks 3) — distinct from the in-place-return mutators, matching the spec. `_STEP_FLAG_ATTR`/`set_step_flag`/`step_flags_payload` consistent.
