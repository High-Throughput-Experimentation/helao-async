# experiment_order Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `experiment_order` field to `ExperimentModel` (analog of `action_order`) and stamp it per-sequence at dispatch.

**Architecture:** A new `Optional[int] = 0` field on the full `ExperimentModel`, stamped in `dispatch_experiment()` from the existing per-sequence counter `OrchState.active_seq_exp_counter` (reset to 0 in `dispatch_sequence`, incremented per experiment). `RunExperiment(ExperimentModel)` inherits the field; no other model touched.

**Tech Stack:** Python 3.12, pydantic v2, pytest. Run python/pytest via `conda run -n helao`.

## Global Constraints

- Framework only — changes confined to `helao/framework/`.
- Field must byte-for-byte match `ActionModel.action_order` (`helao/framework/models/action.py:133`): `experiment_order: Optional[int] = 0`.
- `experiment_order` is 0-indexed and per-sequence (resets each sequence).
- Do NOT introduce minimal models, retype `dispatched_*`/`planned_*` lists, or change `.yml` write contents. `ShortExperimentModel`, `ProcessModel`, and the full→short inheritance stay untouched.
- Spec: `docs/superpowers/specs/2026-06-29-experiment-order-design.md`.

---

### Task 1: Add `experiment_order` field to `ExperimentModel`

**Files:**
- Modify: `helao/framework/models/experiment.py` (class `ExperimentModel`, field block ~101-137; docstring ~66-99)
- Test: `helao/framework/tests/test_models_aes.py`

**Interfaces:**
- Produces: `ExperimentModel.experiment_order: Optional[int]` (default `0`); inherited by `RunExperiment`.

- [ ] **Step 1: Write the failing test**

Add to `helao/framework/tests/test_models_aes.py` (after `test_experiment_model_defaults`, ~line 88):

```python
def test_experiment_model_has_experiment_order_default():
    em = ExperimentModel()
    assert em.experiment_order == 0


def test_experiment_order_round_trips():
    em = ExperimentModel(experiment_name="exp", experiment_order=3)
    assert ExperimentModel(**em.model_dump()).experiment_order == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_models_aes.py::test_experiment_model_has_experiment_order_default helao/framework/tests/test_models_aes.py::test_experiment_order_round_trips -v`
Expected: FAIL — `test_experiment_order_round_trips` raises (pydantic ignores the unknown kwarg so `experiment_order` is absent) / `experiment_model_has_experiment_order_default` fails with `AttributeError`/no such attribute.

- [ ] **Step 3: Add the field**

In `helao/framework/models/experiment.py`, in `ExperimentModel`, add the field immediately after the existing `experiment_label: Optional[str] = None` line (~115):

```python
    experiment_label: Optional[str] = None
    experiment_order: Optional[int] = 0
```

And add the matching docstring line in the `ExperimentModel` Attributes block, immediately after the `experiment_label` entry (~80):

```python
        experiment_label (Optional[str]): Free-form label.
        experiment_order (Optional[int]): Index of the experiment within its sequence (analog of action_order).
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_models_aes.py -v`
Expected: PASS (all tests in the file, including the two new ones).

- [ ] **Step 5: Commit**

```bash
git add helao/framework/models/experiment.py helao/framework/tests/test_models_aes.py
git commit -m "feat(framework): add experiment_order field to ExperimentModel"
```

---

### Task 2: Stamp `experiment_order` at dispatch

**Files:**
- Modify: `helao/framework/domain/orchestration.py` (`dispatch_experiment`, at the `state.active_seq_exp_counter += 1` line ~1239)
- Test: `helao/framework/tests/test_domain_orchestration.py`

**Interfaces:**
- Consumes: `OrchState.active_seq_exp_counter` (default 0; reset to 0 in `dispatch_sequence` at line 1142; incremented in `dispatch_experiment` at line 1239); `ExperimentModel.experiment_order` (Task 1).

- [ ] **Step 1: Write the failing tests**

Add to `helao/framework/tests/test_domain_orchestration.py` (in the `dispatch_experiment` section, after `test_dispatch_experiment_emits_expand_when_no_result`, ~line 540):

```python
def test_dispatch_experiment_stamps_experiment_order():
    exp = RunExperiment(experiment_name="e0")
    seq = RunSequence(sequence_uuid=uuid4())
    st = _state(experiment_dq=[exp], active_sequence=seq)
    st, _ = orch.dispatch_experiment(st, now=NOW, uuid=SEED)
    assert exp.experiment_order == 0
    assert st.active_seq_exp_counter == 1


def test_dispatch_experiment_order_increments_then_resets_per_sequence():
    seq_a = RunSequence(sequence_uuid=uuid4())
    e0 = RunExperiment(experiment_name="e0")
    e1 = RunExperiment(experiment_name="e1")
    st = _state(experiment_dq=[e0, e1], active_sequence=seq_a)
    st, _ = orch.dispatch_experiment(st, now=NOW, uuid=SEED)
    st, _ = orch.dispatch_experiment(st, now=NOW, uuid=SEED)
    assert e0.experiment_order == 0
    assert e1.experiment_order == 1

    # a new sequence resets the per-sequence counter -> order restarts at 0
    seq_b = RunSequence(sequence_uuid=uuid4())
    st.sequence_dq = [seq_b]
    st, _ = orch.dispatch_sequence(st, now=NOW, uuid=SEED)
    e2 = RunExperiment(experiment_name="e2")
    st.experiment_dq = [e2]
    st, _ = orch.dispatch_experiment(st, now=NOW, uuid=SEED)
    assert e2.experiment_order == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_domain_orchestration.py::test_dispatch_experiment_stamps_experiment_order helao/framework/tests/test_domain_orchestration.py::test_dispatch_experiment_order_increments_then_resets_per_sequence -v`
Expected: FAIL — `exp.experiment_order` is `0` by default so the first assertion may pass, but the increment/reset test fails because `e1.experiment_order` is still `0` (never stamped). Both tests must be present and the second must fail before implementing.

- [ ] **Step 3: Stamp the field**

In `helao/framework/domain/orchestration.py`, in `dispatch_experiment`, change the counter increment (~line 1239) from:

```python
    if state.active_sequence is not None:
        exp.sequence_uuid = state.active_sequence.sequence_uuid
    state.active_seq_exp_counter += 1
```

to:

```python
    if state.active_sequence is not None:
        exp.sequence_uuid = state.active_sequence.sequence_uuid
    # experiment_order = 0-indexed position within the sequence (analog of
    # action_order); the counter resets per sequence in dispatch_sequence.
    exp.experiment_order = state.active_seq_exp_counter
    state.active_seq_exp_counter += 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_domain_orchestration.py -v`
Expected: PASS (all dispatch tests, including the two new ones).

- [ ] **Step 5: Commit**

```bash
git add helao/framework/domain/orchestration.py helao/framework/tests/test_domain_orchestration.py
git commit -m "feat(framework): stamp experiment_order per-sequence at dispatch"
```

---

### Task 3: Full-suite regression check

**Files:** none (verification only).

- [ ] **Step 1: Run the full framework suite**

Run: `conda run -n helao python -m pytest helao/framework/tests -p no:warnings`
Expected: PASS — prior baseline 1651 passed, 28 skipped; now **1655 passed, 28 skipped** (+4 new tests). No failures.

- [ ] **Step 2: If green, no commit needed**

Tasks 1-2 already committed. If any pre-existing test asserts an exact `ExperimentModel.model_dump()` / round-trip equality that now carries the new key, update that assertion to include `experiment_order` and commit with `test(framework): account for experiment_order in model dump assertions`.

---

## Self-Review

**Spec coverage:**
- Field addition (`experiment_order: Optional[int] = 0` on `ExperimentModel`, docstring) → Task 1. ✓
- Stamping at dispatch via `active_seq_exp_counter` before increment → Task 2. ✓
- 0-indexed, per-sequence reset → Task 2 second test. ✓
- `RunExperiment` inherits, no `run_models.py` change → covered (inheritance; no task needed). ✓
- Out-of-scope items (minimal models, list retyping, serialization) → not in any task. ✓
- Testing (model default/round-trip; stamping order + reset) → Tasks 1, 2. ✓

**Placeholder scan:** none — all steps carry concrete code/commands. ✓

**Type consistency:** `experiment_order: Optional[int]` used consistently across Task 1 (field), Task 2 (stamping `state.active_seq_exp_counter` → `int`). `dispatch_experiment(state, now=, uuid=, expand_result=)` and `_state(...)` match existing test usage. ✓
